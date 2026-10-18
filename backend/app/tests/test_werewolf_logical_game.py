import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.models import Event, Memory, Location
from app.effects.effect_engine import execute_tool
from app.events.event_store import create_event
from app.knowledge.event_access import agent_can_access_event
from app.knowledge.perception import build_turn_context_with_options
from app.llm.provider_base import LLMResult
from app.narrator.narrator_prompts import narrator_user_prompt
from app.social.private_talk import private_talk_peer
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world
from app.tests.test_werewolf_host_resolution import set_roles, reload_world
from app.tools.validators import validate_tool
from app.world.visibility import mark_name_known
from app.world.werewolf import handle_werewolf_tool, sync_werewolf_phase, werewolf_state, werewolf_menu_tool_names, werewolf_final_speech_prompt


def choose(db, world, agent, tool, speech=None, destination=None):
    context = build_turn_context_with_options(db, world, agent)
    options = [o for o in context.action_options if o.tool_name == tool]
    if destination:
        options = [o for o in options if o.params.get('location_id') == destination]
    assert options, (tool, [o.tool_name for o in context.action_options])
    option = options[0]
    params = dict(option.params)
    if option.target_choices:
        params.update(option.target_choices[0]['params'])
    if speech:
        params['speech'] = speech
    result = execute_tool(db, world=world, actor=agent, tool_name=tool, params=params)
    assert not any(db.get(Event, eid).event_type == 'tool_failed' for eid in result.event_ids), result
    return result


def test_private_conversation_requires_acceptance_and_reaches_only_participants(db):
    world, agents = _make_werewolf_world(db)
    first, second, bystander, _ = agents
    for target in agents:
        for observer in agents:
            if target != observer:
                mark_name_known(db, observer.agent_id, target, 480, 'test')
    assert not validate_tool(db, actor=first, tool_name='say_in_private_talk', params={'speech':'secret'}, world_time=480).ok
    choose(db, world, first, 'tool_comm_ask_private_talk', '我们可以私下聊聊吗？')
    assert not private_talk_peer(db, world, first)
    choose(db, world, second, 'accept_social_request_visible_agent', '可以，我们私下说。')
    assert private_talk_peer(db, world, first).agent_id == second.agent_id
    result = choose(db, world, first, 'say_in_private_talk', '只有你知道的独有线索SENTINEL。')
    event = next(db.get(Event, eid) for eid in result.event_ids if db.get(Event, eid).event_type == 'private_dialogue')
    for agent in [first, second]:
        assert agent_can_access_event(db, world, agent.agent_id, event)
        assert '独有线索SENTINEL' in build_turn_context_with_options(db, world, agent).prompt
    assert not agent_can_access_event(db, world, bystander.agent_id, event)
    assert '独有线索SENTINEL' not in build_turn_context_with_options(db, world, bystander).prompt
    assert not db.scalar(select(Memory).where(Memory.agent_id == bystander.agent_id, Memory.source_event_id == event.event_id))
    choose(db, world, second, 'end_private_talk')
    assert not private_talk_peer(db, world, first)


def test_sleep_body_investigation_and_burial_use_actual_room(db):
    world, agents = _make_werewolf_world(db)
    wolf, witness, remote, victim = agents
    set_roles(world, agents, ['werewolf','villager','villager','villager'])
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    victim_room = victim.wallet_json['housing']['home_location_id']
    assert victim.location.location_id == victim_room
    handle_werewolf_tool(db, world, wolf, 'werewolf_kill_by_name', {}, target=victim)
    assert world.settings_json['corpse_records'][0]['location_id'] == victim_room
    world.current_world_time_minutes = 1920
    sync_werewolf_phase(db, world)
    witness.desires_json = {}  # waking is normally performed by TurnRunner
    destination = db.get(Location, victim_room)
    entrance = db.get(Location, destination.neighbors_json[0])
    witness.location.location_id = entrance.location_id; witness.location.location = entrance
    before = build_turn_context_with_options(db, world, witness)
    assert not any(o.tool_name == 'inspect_unanswered_room' for o in before.action_options)
    choose(db, world, witness, 'knock_private_room', destination=victim_room)
    assert witness.location.location_id == entrance.location_id
    choose(db, world, witness, 'inspect_unanswered_room', destination=victim_room)
    assert witness.location.location_id == victim_room
    records = world.settings_json['corpse_records']
    assert witness.agent_id in records[0]['discovered_by_agent_ids']
    assert remote.agent_id not in records[0]['discovered_by_agent_ids']
    choose(db, world, witness, 'bury_visible_corpse')
    assert world.settings_json['corpse_records'][0]['buried'] is True
    assert not any(o.tool_name == 'bury_visible_corpse' for o in build_turn_context_with_options(db, world, witness).action_options)


def test_explicit_night_pass_resolves_pending_attack_and_is_private(db):
    world, agents = _make_werewolf_world(db)
    wolf, guard, other, victim = agents
    set_roles(world, agents, ['werewolf','guard','villager','villager'], public=True)
    world.current_world_time_minutes = 1320; sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, wolf, 'werewolf_kill_by_name', {}, target=victim)
    assert victim.lifecycle_state == 'alive'
    assert 'werewolf_skip_night_action' in werewolf_menu_tool_names(db, world, guard)
    choose(db, world, guard, 'werewolf_skip_night_action')
    sync_werewolf_phase(db, world)
    assert victim.lifecycle_state == 'dead'
    assert not werewolf_menu_tool_names(db, world, guard)
    assert '主动决定不使用' not in build_turn_context_with_options(db, world, other).prompt
    assert not werewolf_state(world).get('winner')


def test_witch_can_decline_and_potions_are_finite(db):
    world, agents = _make_werewolf_world(db)
    wolf, witch, victim, other = agents
    set_roles(world, agents, ['werewolf','witch','villager','villager'], public=True)
    world.current_world_time_minutes = 1320; sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, wolf, 'werewolf_kill_by_name', {}, target=victim)
    assert 'werewolf_skip_night_action' in werewolf_menu_tool_names(db, world, witch)
    handle_werewolf_tool(db, world, witch, 'werewolf_witch_save_latest', {})
    assert victim.lifecycle_state == 'alive'
    assert not werewolf_menu_tool_names(db, world, witch)  # one potion per night
    world.current_world_time_minutes = 2760; sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, wolf, 'werewolf_kill_by_name', {}, target=other)
    names = werewolf_menu_tool_names(db, world, witch)
    assert 'werewolf_witch_save_latest' not in names
    assert 'werewolf_skip_night_action' in names


def test_poison_cannot_decide_winner_before_dawn(db):
    world, agents = _make_werewolf_world(db)
    wolf, witch, victim, other = agents
    set_roles(world, agents, ['werewolf','witch','villager','villager'], public=True)
    world.current_world_time_minutes = 1320; sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, wolf, 'werewolf_kill_by_name', {}, target=victim)
    handle_werewolf_tool(db, world, witch, 'werewolf_witch_poison_by_name', {}, target=wolf)
    assert not werewolf_state(world).get('winner')
    world.current_world_time_minutes = 1920; sync_werewolf_phase(db, world)
    assert werewolf_state(world)['winner'] == '人类阵营'


def test_final_speech_keeps_personal_evidence_without_other_roles_secrets(db):
    world, agents = _make_werewolf_world(db)
    guard, seer, _, target = agents
    own = create_event(db, world=world, event_type='werewolf_guard_protect', actor_agent_id=guard.agent_id,
        visibility_scope='private', agent_visible_text='你实际守护了目标甲OWN_RESULT。', viewer_text='守护', importance=80)
    secret = create_event(db, world=world, event_type='werewolf_seer_check', actor_agent_id=seer.agent_id,
        visibility_scope='private', agent_visible_text='预言家私密结果OTHER_SECRET', viewer_text='查验', importance=80)
    db.add(Memory(agent_id=guard.agent_id, content='我们开局前就认识。', memory_type='relationship', created_world_time=480, importance=90))
    world.settings_json = {**world.settings_json, 'werewolf_state': {**werewolf_state(world), 'winner':'人类阵营'}}
    db.flush()
    system, prompt = werewolf_final_speech_prompt(db, world, guard)
    assert 'OWN_RESULT' in prompt and 'OTHER_SECRET' not in prompt
    assert '我们开局前就认识' in prompt
    assert '台词都是硬事实' not in narrator_user_prompt('一人声称自己是预言家。')
    assert '台词只证明' in narrator_user_prompt('一人声称自己是预言家。')


def test_room_locks_block_inspection_and_only_nearby_residents_see_state(db):
    from app.world.doors import room_door_locked
    world, agents = _make_werewolf_world(db)
    owner, visitor, remote, _ = agents
    room = db.get(Location, owner.wallet_json['housing']['home_location_id'])
    entrance = db.get(Location, room.neighbors_json[0])
    for agent in (owner, visitor):
        agent.location.location_id = entrance.location_id
        agent.location.location = entrance
    remote_room = db.get(Location, f"{world.world_id}:cafeteria")
    remote.location.location_id = remote_room.location_id
    remote.location.location = remote_room
    assert not room_door_locked(world, room.location_id)
    choose(db, world, owner, 'lock_home_door')
    assert room_door_locked(world, room.location_id)
    assert f'{room.public_name}: 已上锁' in build_turn_context_with_options(db, world, visitor).prompt
    assert f'{room.public_name}: 已上锁' not in build_turn_context_with_options(db, world, remote).prompt
    choose(db, world, visitor, 'knock_private_room', destination=room.location_id)
    invalid = validate_tool(db, actor=visitor, tool_name='inspect_unanswered_room', params={'location_id':room.location_id}, world_time=world.current_world_time_minutes)
    assert not invalid.ok and invalid.reason_code == 'door_locked'
    assert not any(o.tool_name == 'inspect_unanswered_room' for o in build_turn_context_with_options(db, world, visitor).action_options)
    choose(db, world, owner, 'unlock_home_door')
    assert not room_door_locked(world, room.location_id)
    choose(db, world, visitor, 'inspect_unanswered_room', destination=room.location_id)
    assert visitor.location.location_id == room.location_id


def test_death_unlocks_home_without_announcing_the_death_to_observers(db):
    from app.world.doors import room_door_locked, set_room_door_lock
    world, agents = _make_werewolf_world(db)
    wolf, observer, _, victim = agents
    set_roles(world, agents, ['werewolf','villager','villager','villager'])
    room_id = victim.wallet_json['housing']['home_location_id']
    set_room_door_lock(world, room_id, True)
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, wolf, 'werewolf_kill_by_name', {}, target=victim)
    assert victim.lifecycle_state == 'dead'
    assert not room_door_locked(world, room_id)
    room = db.get(Location, room_id)
    observer.location.location_id = room.neighbors_json[0]
    observer.location.location = db.get(Location, room.neighbors_json[0])
    observer.desires_json = {}
    prompt = build_turn_context_with_options(db, world, observer).prompt
    assert f'{room.public_name}: 未锁' in prompt
    assert not any(e for e in db.scalars(select(Event).where(Event.world_id == world.world_id, Event.event_type == 'room_lock_changed')))
    assert observer.agent_id not in world.settings_json['corpse_records'][0]['discovered_by_agent_ids']


def test_speaking_turns_one_minute_apart_are_serial_and_see_previous_speech(db, monkeypatch):
    from app.simulation.turn_runner import TurnRunner
    from app.llm.openai_compatible import provider
    from app.simulation.reaction_queue import reaction_queue
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ['werewolf','villager','villager','villager'], public=True)
    params = dict(world.settings_json['worldview_rule_parameters'])
    params['werewolf'] = {**params.get('werewolf', {}), 'tool_time_scale':0.1}
    world.settings_json = {**world.settings_json, 'agent_request_mode':'parallel',
        'worldview_rule_parameters':params, 'narrator_enabled':False}
    world.current_world_time_minutes = 1440 + 12*60
    sync_werewolf_phase(db, world)
    db.commit()
    runner = TurnRunner()
    monkeypatch.setattr(runner, '_run_regular_batch_parallel', AsyncMock(side_effect=AssertionError('different speaking times must not be batched')))
    original = runner._request_action_choice
    starts = []
    prompts = []
    async def choose_speech(agent, *, world, options, **kwargs):
        starts.append(world.current_world_time_minutes)
        prompts.append(kwargs['user_prompt'])
        option = next(o for o in options if o.tool_name == 'werewolf_speak')
        monkeypatch.setattr(provider, 'complete_text', AsyncMock(return_value=LLMResult(
            f'[{option.option_id:02d}]\n我会先核实自己亲眼看到的事情ONE_MINUTE_SENTINEL。', None, {}, 1, 'offline')))
        return await original(agent, world=world, options=options, **kwargs)
    monkeypatch.setattr(runner, '_request_action_choice', choose_speech)
    async def run():
        await runner.run_one_step(db, world.world_id)
        reaction_queue.clear(world.world_id)
        await runner.run_one_step(db, world.world_id)
    asyncio.run(run())
    assert len(starts) == 2 and starts[1] == starts[0] + 1
    assert 'ONE_MINUTE_SENTINEL' in prompts[1]
