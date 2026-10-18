"""Ten residents, real runner/protocol/effects, deterministic offline model replies.

Only model/image I/O and background scheduling are replaced. The test clock skips
idle free time, never an unfinished hosted phase. This tests engine consistency,
not the reasoning quality of real models.
"""
import asyncio
from contextvars import ContextVar
import importlib
import json
import socket
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.api.worlds import CreateWorldRequest, create_world
from app.content.presets import WEREWOLF_WORLDVIEW_ID
from app.core.models import Agent, Event, Memory, World, Location
from app.knowledge.perception import build_turn_context_with_options
from app.llm.openai_compatible import provider
from app.llm.provider_base import LLMResult
from app.llm.schemas import NarrationDraft
from app.simulation.reaction_queue import reaction_queue
from app.tests.test_werewolf_logical_game import choose
from app.world.werewolf import werewolf_phase, werewolf_state

runner_module = importlib.import_module('app.simulation.turn_runner')
images = importlib.import_module('app.image_generation.service')


def test_ten_residents_complete_game_with_narration_images_and_parallel_requests(db, monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError('Offline game attempted a real network request')
    monkeypatch.setattr(socket.socket, 'connect', reject_network)
    monkeypatch.setattr(runner_module, '_broadcast_step_progress', AsyncMock())
    monkeypatch.setattr(runner_module, 'schedule_daily_summary_tasks', lambda *args: None)
    monkeypatch.setattr(images, '_schedule_background_generation', lambda *args: None)
    monkeypatch.setattr(images, '_broadcast_image_update', AsyncMock())
    monkeypatch.setattr(images, '_call_image_provider', AsyncMock(return_value='offline-image'))
    monkeypatch.setattr(images, 'store_image_data_url', lambda _: {'image_url':'/offline/test.png'})

    packet = ContextVar('offline_packet', default=None)
    active = peak = calls = 0
    async def complete_text(**kwargs):
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.005)
            alias = kwargs.get('model_alias')
            if alias == 'narrator':
                return LLMResult('', NarrationDraft(narration='村里的交谈暂时停下，窗边仍然安静。'), {}, 5, 'offline')
            if alias == 'image_prompt':
                text = 'POSITIVE=林零站在窗边，望向窗外，午后的光落在她的侧脸。\nNEGATIVE='
            else:
                text = packet.get() or '我记得自己做过的选择，还有亲耳听到的那些话。接下来的日子，我会认真面对。'
            return LLMResult(text, None, {'prompt_tokens':1000,'completion_tokens':60}, 5, 'offline')
        finally:
            active -= 1
    monkeypatch.setattr(provider, 'complete_text', complete_text)

    async def game():
        names = ['林零','林一','林二','林三','林四','林五','林六','林七','林八','林九']
        response = await create_world(CreateWorldRequest(
            name='离线完整十人局', seed=31415, agent_count=10,
            worldview_id=WEREWOLF_WORLDVIEW_ID, trait_mode='player',
            agent_request_mode='parallel',
            providers=[{'provider_id':'offline','name':'offline','base_url':'https://example.invalid/v1','api_key':'test','retry_count':0}],
            agent_configs=[{'chosen_name':name,'appearance':'深色短发，穿着灰色外套。',
                'provider_id':'offline','model_name':f'offline-{i}','knowledge_mode':'all',
                'trait_mode':'player','system_prompt':f'你是{name}。'} for i,name in enumerate(names)],
            narrator_config={'provider_id':'offline','model_name':'offline-narrator','enabled':True,'auto_frequency':'normal'},
            image_generation={'enabled':True,'auto_enabled':True,'source_mode':'narration',
                'prompt_style':'dalle','provider_type':'sdxl','base_url':'https://example.invalid',
                'model_name':'offline-image','width':1536,'height':864},
        ), db)
        world = db.get(World, response['world_id'])
        agents = [db.scalar(select(Agent).where(Agent.world_id == world.world_id, Agent.chosen_name == name)) for name in names]
        state = werewolf_state(world)
        roles = dict(zip([a.agent_id for a in agents], ['werewolf']*3+['seer','guard','coroner']+['villager']*4))
        state['roles'] = roles
        world.settings_json = {**world.settings_json, 'werewolf_state':state}
        world.status = 'running'
        db.commit()
        runner = runner_module.TurnRunner()
        original_request = runner._request_action_choice
        active_decision_minutes = []

        async def request(agent, *, world, options, **kwargs):
            alive = list(db.scalars(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(['alive','critical']))))
            wolves = sorted([a for a in alive if roles[a.agent_id] == 'werewolf'], key=lambda a:a.chosen_name)
            villagers = sorted([a for a in alive if roles[a.agent_id] == 'villager'], key=lambda a:a.chosen_name, reverse=True)
            priorities = ['werewolf_vote_by_name','werewolf_speak','werewolf_wolf_discuss',
                'werewolf_kill_by_name','werewolf_seer_check_by_name','werewolf_coroner_report_latest',
                'werewolf_skip_night_action','do_nothing']
            choices = sorted(options, key=lambda o:priorities.index(o.tool_name) if o.tool_name in priorities else 999)
            option = choices[0]
            assert option.tool_name in priorities, [o.tool_name for o in options]
            head = f'{option.option_id:02d}'
            if option.target_choices:
                wanted = villagers[0] if option.tool_name == 'werewolf_kill_by_name' else wolves[0] if wolves else alive[0]
                targets = [t for t in option.target_choices if wanted.agent_id in t['params'].values() or wanted.chosen_name in t['params'].values()]
                target = targets[0] if targets else option.target_choices[0]
                head += f":{target['id']}"
            decision_minute = world.current_world_time_minutes
            assert all(t == decision_minute for t in active_decision_minutes), active_decision_minutes
            active_decision_minutes.append(decision_minute)
            token = packet.set(f'[{head}]\n我还没有足够的线索，先听完其他人的说明。' if option.text_slot else f'[{head}]\n-')
            try:
                return await original_request(agent, world=world, options=options, **kwargs)
            finally:
                packet.reset(token)
                active_decision_minutes.remove(decision_minute)
        monkeypatch.setattr(runner, '_request_action_choice', request)

        phases = []
        discovered = False
        for step in range(180):
            result = await runner.run_one_step(db, world.world_id)
            db.commit(); db.expire_all()
            world = db.get(World, world.world_id)
            state = werewolf_state(world)
            day, phase = werewolf_phase(world)
            phases.append((day, phase, result.status))
            if step % 20 == 0:
                print("offline progress", step, world.current_world_time_minutes, phases[-1], flush=True)
            assert result.status not in {'llm_stalled','werewolf_host_incomplete','werewolf_final_speech_retry'}, phases[-8:]
            for event in list(db.scalars(select(Event).where(Event.world_id == world.world_id, Event.event_type == 'image_generation'))):
                if event.payload['status'] == 'pending':
                    await images._generate_image_with_session(db, world, event)
                assert event.payload['status'] == 'completed', event.payload
            if world.status == 'ended':
                break
            if state.get('winner'):
                continue
            if phase == 'morning':
                if day == 2 and not discovered:
                    records = world.settings_json.get('corpse_records') or []
                    assert len(records) == 1
                    victim_id = records[0]['agent_id']
                    victim = db.get(Agent, victim_id)
                    living_villagers = [a for a in agents[6:] if a.agent_id != victim_id and a.lifecycle_state == 'alive']
                    witness, outsider = living_villagers[:2]
                    assert not db.scalar(select(Event).where(Event.world_id == world.world_id, Event.event_type == 'werewolf_body_found'))
                    before = build_turn_context_with_options(db, world, outsider).prompt
                    assert f'{victim.chosen_name}昨夜遭到' not in before
                    room = db.get(Location, records[0]['location_id'])
                    # Test clock skips walking time; actual knock/investigation/burial still execute.
                    witness.location.location_id = room.neighbors_json[0]
                    witness.location.location = db.get(Location, room.neighbors_json[0])
                    choose(db, world, witness, 'knock_private_room', destination=room.location_id)
                    choose(db, world, witness, 'inspect_unanswered_room', destination=room.location_id)
                    assert outsider.agent_id not in world.settings_json['corpse_records'][0]['discovered_by_agent_ids']
                    choose(db, world, witness, 'bury_visible_corpse')
                    discovered = True
                world.current_world_time_minutes = (day-1)*1440 + (22 if day == 1 or world.current_world_time_minutes % 1440 >= 18*60 else 12)*60
                reaction_queue.clear(world.world_id)
            elif phase == 'free':
                world.current_world_time_minutes = (day-1)*1440 + 22*60
                reaction_queue.clear(world.world_id)
            db.commit()
        else:
            raise AssertionError(phases[-20:])

        events = list(db.scalars(select(Event).where(Event.world_id == world.world_id)))
        types = [e.event_type for e in events]
        assert state['winner'] == '人类阵营'
        assert discovered and len(state['night_kills']) == 3
        assert peak >= 2
        assert 'tool_failed' not in types and 'werewolf_host_incomplete' not in types
        image_events = [e for e in events if e.event_type == 'image_generation']
        narration_ids = {e.event_id for e in events if e.event_type == 'narration'}
        assert len(image_events) > 0
        assert {e.payload['narration_event_id'] for e in image_events} == narration_ids
        assert len(image_events) == len(narration_ids)
        survivor_ids = {a.agent_id for a in agents if a.lifecycle_state in {'alive','critical'}}
        assert len(survivor_ids) == 4
        assert {e.actor_agent_id for e in events if e.event_type == 'werewolf_final_speech'} == survivor_ids
        print(json.dumps({'offline':True,'residents':10,'steps':step+1,'days':day,
            'nights':len(state['night_kills']),'winner':state['winner'],
            'peak_parallel_requests':peak,'model_calls':calls,'narrations':len(narration_ids),
            'completed_images':len(image_events),'final_speeches':types.count('werewolf_final_speech')},ensure_ascii=False))
    asyncio.run(game())
