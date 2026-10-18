"""Experiences come from executed state changes, never reconstructed testimony."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.models import Event, Location, Memory
from app.effects.effect_engine import execute_tool
from app.events.event_store import create_event
from app.knowledge.event_access import agent_can_access_event
from app.knowledge.perception import build_turn_context_with_options, sanitize_event_for_agent
from app.memory.memory_service import auto_memory_for_event
from app.simulation.reaction_queue import ReactionTask, ReactionQueue, reaction_queue
from app.simulation.turn_runner import TurnRunner, TurnResult
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world
from app.tests.test_werewolf_host_resolution import set_roles
from app.tools.validators import validate_tool
from app.world.housing import unanswered_room_ids
from app.world.visibility import mark_name_known
from app.world.werewolf import sync_werewolf_phase, werewolf_current_discussion_actor_id


def place(db, agent, location):
    agent.location.location_id = location.location_id
    agent.location.location = location
    db.flush()


def room_scene(db):
    world, agents = _make_werewolf_world(db)
    visitor, owner, outside, remote = agents
    room = db.get(Location, owner.wallet_json['housing']['home_location_id'])
    entrance = db.get(Location, room.neighbors_json[0])
    for agent in (visitor, outside):
        place(db, agent, entrance)
    place(db, owner, room)
    place(db, remote, db.get(Location, f'{world.world_id}:cafeteria'))
    for observer in agents:
        for target in agents:
            if observer != target:
                mark_name_known(db, observer.agent_id, target, 480, 'test')
    return world, agents, room, entrance


def action_event(db, world, agent, tool, **params):
    result = execute_tool(db, world=world, actor=agent, tool_name=tool, params=params)
    assert result.ok, result.message
    return db.get(Event, result.event_ids[0])


def test_entry_then_exit_are_witnessed_on_both_sides_and_retained_in_memory(db, monkeypatch):
    world, (visitor, owner, outside, remote), room, entrance = room_scene(db)
    monkeypatch.setattr('app.effects.effect_engine.random.Random.random', lambda _: 0.0)
    entry = action_event(db, world, visitor, 'knock_private_room', location_id=room.location_id)
    assert entry.event_type == 'door_opened'
    assert agent_can_access_event(db, world, outside.agent_id, entry)
    assert not agent_can_access_event(db, world, remote.agent_id, entry)
    # The room's conversation remains inaudible outside even though entry was visible.
    speech = action_event(db, world, visitor, 'speak_to_nearby', speech='房内独有的台词ROOM_SECRET。')
    assert not agent_can_access_event(db, world, outside.agent_id, speech)
    departure = action_event(db, world, owner, 'move_to_location', location_id=entrance.location_id)
    assert agent_can_access_event(db, world, visitor.agent_id, departure)
    assert agent_can_access_event(db, world, outside.agent_id, departure)
    assert not agent_can_access_event(db, world, remote.agent_id, departure)
    for observer, event in [(outside, entry), (visitor, departure), (owner, entry)]:
        memory = db.scalar(select(Memory).where(Memory.agent_id == observer.agent_id,
                                              Memory.source_event_id == event.event_id))
        assert memory is not None
        assert room.public_name in memory.content
    prompt = build_turn_context_with_options(db, world, visitor).prompt
    assert owner.chosen_name in prompt and room.public_name in prompt
    assert 'ROOM_SECRET' not in build_turn_context_with_options(db, world, outside).prompt


def test_knocking_uses_homeowner_not_first_guest(db, monkeypatch):
    world, (guest, owner, visitor, _), room, _ = room_scene(db)
    place(db, guest, room)  # guest sorts before owner in the database
    monkeypatch.setattr('app.effects.effect_engine.random.Random.random', lambda _: 0.0)
    event = action_event(db, world, visitor, 'knock_private_room', location_id=room.location_id)
    assert event.target_agent_id == owner.agent_id


@pytest.mark.parametrize('sleeping', [False, True])
def test_unanswered_unlocked_door_can_be_inspected_without_inventing_a_reply(db, monkeypatch, sleeping):
    world, (visitor, owner, _, _), room, _ = room_scene(db)
    if sleeping:
        owner.desires_json = {'sleep_until_world_time': 1000}
    monkeypatch.setattr('app.effects.effect_engine.random.Random.random', lambda _: 0.99)
    knock = action_event(db, world, visitor, 'knock_private_room', location_id=room.location_id)
    assert knock.target_agent_id is None  # silence does not reveal an occupant's identity
    assert room.location_id in unanswered_room_ids(db, world, visitor)
    assert agent_can_access_event(db, world, owner.agent_id, knock) is not sleeping
    assert validate_tool(db, actor=visitor, tool_name='inspect_unanswered_room',
                         params={'location_id': room.location_id}, world_time=world.current_world_time_minutes).ok
    entered = action_event(db, world, visitor, 'inspect_unanswered_room', location_id=room.location_id)
    assert entered.event_type == 'room_entered_for_inspection'
    assert visitor.location.location_id == room.location_id
    assert '有人回应' not in entered.viewer_text


def test_sleeping_owner_cannot_open_door_or_hear_ordinary_speech(db, monkeypatch):
    world, (visitor, owner, _, _), room, _ = room_scene(db)
    owner.desires_json = {'sleep_until_world_time': 1000}
    monkeypatch.setattr('app.effects.effect_engine.random.Random.random', lambda _: 0.0)
    knock = action_event(db, world, visitor, 'knock_private_room', location_id=room.location_id)
    assert knock.event_type == 'knock_room'
    assert not agent_can_access_event(db, world, owner.agent_id, knock)
    place(db, visitor, room)
    event = action_event(db, world, visitor, 'speak_to_nearby', speech='睡着时听不到ASLEEP_SECRET。')
    assert not agent_can_access_event(db, world, owner.agent_id, event)
    assert not db.scalar(select(Memory).where(Memory.agent_id == owner.agent_id, Memory.source_event_id == event.event_id))


def test_recent_observation_contains_actual_speech_time_place_and_target(db):
    world, (visitor, owner, outside, _), room, entrance = room_scene(db)
    event = create_event(db, world=world, event_type='dialogue', actor_agent_id=visitor.agent_id,
                        target_agent_id=outside.agent_id, location_id=entrance.location_id,
                        viewer_text=f'{visitor.chosen_name}向附近的人说话。',
                        payload={'speech': '请在门口等我ACTUAL_WORDS。'})
    text = sanitize_event_for_agent(db, outside, event)
    assert 'ACTUAL_WORDS' in text
    assert entrance.public_name in text
    assert '08:00' in text and outside.chosen_name in text
    assert sanitize_event_for_agent(db, owner, event) == ''
    # No memory row is needed to preserve recent spoken words.
    assert 'ACTUAL_WORDS' in build_turn_context_with_options(db, world, outside).prompt


def test_room_entry_remains_retrievable_after_recent_event_window(db, monkeypatch):
    world, (visitor, owner, outside, _), room, _ = room_scene(db)
    monkeypatch.setattr('app.effects.effect_engine.random.Random.random', lambda _: 0.0)
    entry = action_event(db, world, visitor, 'knock_private_room', location_id=room.location_id)
    for i in range(30):
        world.current_world_time_minutes += 1
        create_event(db, world=world, event_type='look', actor_agent_id=outside.agent_id,
                     location_id=outside.location.location_id, viewer_text=f'观察环境{i}')
    prompt = build_turn_context_with_options(db, world, outside).prompt
    assert entry.viewer_text in prompt


def test_reaction_queue_does_not_merge_different_times_or_speakers():
    queue = ReactionQueue()
    for when, source in [(480, 'a'), (481, 'a'), (481, 'b')]:
        queue.push('world', ReactionTask('listener', f'{source}:{when}', source_agent_id=source,
                                         created_world_time=when), 3)
    assert [queue.pop('world', 482).trigger_text for _ in range(3)] == ['a:480', 'a:481', 'b:481']


def test_remote_speaker_does_not_trigger_a_face_to_face_reply(db):
    world, (visitor, owner, _, _), _, _ = room_scene(db)
    task = ReactionTask(visitor.agent_id, '旧的当面邀请', source_agent_id=owner.agent_id, created_world_time=480)
    assert TurnRunner()._reaction_agent(db, world, task) is None


def test_trigger_text_is_filtered_for_each_recipient(db):
    from app.effects.effect_engine import ExecutionResult
    world, (actor, _, listener, _), _, entrance = room_scene(db)
    public = create_event(db, world=world, event_type='dialogue', actor_agent_id=actor.agent_id,
                          location_id=entrance.location_id, viewer_text='说话', payload={'speech': 'PUBLIC_WORDS'})
    private = create_event(db, world=world, event_type='self_status', actor_agent_id=actor.agent_id,
                           visibility_scope='private', viewer_text='PRIVATE_SECRET')
    result = ExecutionResult(True, event_ids=[public.event_id, private.event_id], reaction_agent_ids=[listener.agent_id])
    TurnRunner()._enqueue_reactions(db, world, actor, result, 0)
    task = reaction_queue.pop(world.world_id, 480)
    assert 'PUBLIC_WORDS' in task.trigger_text
    assert 'PRIVATE_SECRET' not in task.trigger_text
    assert '08:00' in task.trigger_text


def test_roundtable_speaker_takes_priority_over_old_free_time_reactions(db, monkeypatch):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ['werewolf', 'villager', 'villager', 'villager'], public=True)
    world.current_world_time_minutes = 1440 + 12 * 60
    sync_werewolf_phase(db, world)
    speaker = werewolf_current_discussion_actor_id(db, world)
    other = next(a for a in agents if a.agent_id != speaker)
    reaction_queue.push(world.world_id, ReactionTask(other.agent_id, '昨天留下来的闲聊',
                        source_agent_id=speaker, created_world_time=world.current_world_time_minutes), 3)
    db.commit()
    runner = TurnRunner()
    async def regular(session, world, selected, **kwargs):
        assert [a.agent_id for a in selected] == [speaker]
        return TurnResult(status='hosted')
    monkeypatch.setattr(runner, '_run_regular_batch', regular)
    monkeypatch.setattr(runner, '_run_single_agent_turn', AsyncMock(side_effect=AssertionError('stale reaction stole hosted turn')))
    assert asyncio.run(runner.run_one_step(db, world.world_id)).status == 'hosted'
    assert reaction_queue.pop(world.world_id, world.current_world_time_minutes) is None


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
def test_same_start_actions_resolve_in_finish_order_and_do_not_hear_through_walls(db, monkeypatch, mode):
    from app.llm.schemas import ActionChoice
    world, (visitor, owner, outside, _), room, entrance = room_scene(db)
    world.settings_json = {**world.settings_json, 'agent_request_mode': mode,
                           'narrator_enabled': False, 'image_generation': {'enabled': False}}
    monkeypatch.setattr('app.effects.effect_engine.random.Random.random', lambda _: 0.0)
    monkeypatch.setattr('app.simulation.turn_runner.maybe_create_narration', AsyncMock(return_value=[]))
    monkeypatch.setattr('app.simulation.turn_runner.schedule_daily_summary_tasks', lambda *a: None)
    choices = {
        visitor.agent_id: ActionChoice(tool_name='knock_private_room', params={'location_id': room.location_id}),
        outside.agent_id: ActionChoice(tool_name='speak_to_nearby', params={'speech': '进门之后才说的AFTER_ENTRY。'}),
    }
    decision_times = []
    async def choose(self, session, world, agent, **kwargs):
        decision_times.append(world.current_world_time_minutes)
        return choices[agent.agent_id]
    monkeypatch.setattr(TurnRunner, '_choose_action', choose)
    db.commit()
    result = asyncio.run(TurnRunner()._run_regular_batch(db, world, [outside, visitor], initial_event_ids=[]))
    events = [db.get(Event, eid) for eid in result.event_ids if db.get(Event, eid).event_type in {'door_opened','dialogue'}]
    assert decision_times == [480, 480]
    assert [e.event_type for e in events] == ['door_opened', 'dialogue']
    assert events[0].world_time < events[1].world_time
    assert agent_can_access_event(db, world, outside.agent_id, events[0])
    assert not agent_can_access_event(db, world, visitor.agent_id, events[1])
    assert not agent_can_access_event(db, world, owner.agent_id, events[1])
