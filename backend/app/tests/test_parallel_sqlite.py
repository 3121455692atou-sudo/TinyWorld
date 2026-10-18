import asyncio
import importlib
import sqlite3
from collections import Counter
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core import database
from app.core.models import Agent, Event
from app.llm.openai_compatible import OpenAICompatibleProvider
from conftest import make_world

runner_module = importlib.import_module('app.simulation.turn_runner')


def setup_world(db, monkeypatch, count=3):
    world, agents = make_world(db, count)
    world.settings_json = {'agent_request_mode': 'parallel', 'llm_concurrency': {'default_provider_limit': 2}, 'narrator_enabled': False}
    for i, agent in enumerate(agents):
        agent.model_name = f'model-{i}'
        agent.llm_api_key = 'test-key'
        agent.llm_base_url = 'https://example.invalid/v1'
        agent.model_provider_name = 'test'
        agent.tool_learning_json = {'llm_runtime': {'retry_count': 0}}
    db.commit()
    # These module globals must use this test's temporary file database.
    assert runner_module.database_module.SessionLocal is database.SessionLocal
    monkeypatch.setattr(runner_module, '_broadcast_step_progress', AsyncMock())
    client = OpenAICompatibleProvider()
    monkeypatch.setattr(runner_module, 'provider', client)
    return world, agents, runner_module.TurnRunner(), client


def assert_writer_free(db):
    # A separate writer must remain available while requests are waiting.
    with sqlite3.connect(database.engine.url.database, timeout=0.05) as other:
        other.execute('BEGIN IMMEDIATE')
        other.rollback()


def reply(payload):
    prompt = payload['messages'][1]['content']
    for line in prompt.splitlines():
        line = line.strip()
        if line[:2].isdigit() and '什么也不做' in line:
            return {'choices': [{'message': {'content': f'[{line[:2]}]\n-'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 123, 'completion_tokens': 7}}
    raise AssertionError('No idle action in the real menu')


@pytest.mark.parametrize('protocol_retry', [False, True])
def test_sqlite_overlaps_requests_respects_limit_and_preserves_usage(db, monkeypatch, protocol_retry):
    world, agents, runner, client = setup_world(db, monkeypatch)
    async def run():
        active = peak = entered = 0
        pair_started = asyncio.Event()
        calls = Counter()
        async def post(_client, *, payload, **kwargs):
            nonlocal active, peak, entered
            assert_writer_free(db)
            active += 1; entered += 1; peak = max(peak, active)
            calls[payload['model']] += 1
            if entered >= 2:
                pair_started.set()
            try:
                await asyncio.wait_for(pair_started.wait(), 2)
                await asyncio.sleep(0.02)
                if protocol_retry and payload['model'] == 'model-0' and calls['model-0'] == 1:
                    return {'choices': [{'message': {'content': 'invalid action'}, 'finish_reason': 'stop'}]}
                return reply(payload)
            finally:
                active -= 1
        monkeypatch.setattr(client, '_post_chat_completion', post)
        result = await asyncio.wait_for(runner.run_one_step(db, world.world_id), 5)
        db.commit(); db.expire_all()
        assert result.status == 'parallel_batch_ok'
        assert len(result.acted_agent_ids) == 3
        assert peak == 2 and active == 0
        assert calls['model-0'] == (2 if protocol_retry else 1)
        for agent in db.scalars(select(Agent)):
            learning = agent.tool_learning_json
            assert learning['last_llm_token_usage']['prompt_tokens'] == 123
            assert learning['last_llm_completed_at']
            assert learning['tool_audit_history']
        updates = runner_module._broadcast_step_progress.await_args_list
        assert [x.kwargs['completed'] for x in updates if x.kwargs.get('phase') == 'parallel_llm'] == [1, 2, 3]
        assert not client._active_by_model and not client._active_by_provider
    asyncio.run(run())


@pytest.mark.parametrize('unexpected_error', [False, True])
def test_cancellation_joins_workers_and_releases_capacity(db, monkeypatch, unexpected_error):
    world, agents, runner, client = setup_world(db, monkeypatch)
    async def run():
        entered = 0
        finished = []
        pair_started = asyncio.Event()
        never = asyncio.Event()
        async def post(_client, *, payload, **kwargs):
            nonlocal entered
            assert_writer_free(db)
            entered += 1
            if entered == 2:
                pair_started.set()
            try:
                await pair_started.wait()
                if unexpected_error and payload['model'] == 'model-0':
                    raise RuntimeError('test worker failure')
                await never.wait()
            finally:
                finished.append(payload['model'])
        monkeypatch.setattr(client, '_post_chat_completion', post)
        task = asyncio.create_task(runner.run_one_step(db, world.world_id))
        await asyncio.wait_for(pair_started.wait(), 2)
        if unexpected_error:
            with pytest.raises(ExceptionGroup):
                await asyncio.wait_for(task, 2)
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(finished) == 2
        assert not client._active_by_model and not client._active_by_provider
        assert not db.scalars(select(Event)).all()
        assert_writer_free(db)
    asyncio.run(run())


def test_failed_agent_retry_keeps_other_actions_without_requery(db, monkeypatch):
    world, agents, runner, client = setup_world(db, monkeypatch)
    agents[0].tool_learning_json = {'llm_consecutive_failures': 2, 'llm_runtime': {'retry_count': 0}}
    db.commit()
    async def run():
        calls = Counter()
        async def post(_client, *, payload, **kwargs):
            assert_writer_free(db)
            calls[payload['model']] += 1
            await asyncio.sleep(0)
            if payload['model'] == 'model-0' and calls['model-0'] == 1:
                raise ValueError('test provider failure')
            return reply(payload)
        monkeypatch.setattr(client, '_post_chat_completion', post)
        first = await runner.run_one_step(db, world.world_id)
        db.commit()
        assert first.status == 'llm_stalled'
        assert len(runner._pending_actions[world.world_id]) == 2
        second = await runner.run_one_step(db, world.world_id)
        db.commit()
        assert second.status == 'parallel_batch_ok'
        assert len(second.acted_agent_ids) == 3
        assert calls == {'model-0': 2, 'model-1': 1, 'model-2': 1}
        assert not runner._pending_actions and not runner._retry_agent_ids
    asyncio.run(run())


@pytest.mark.parametrize('display_mode', ['batch', 'per_agent'])
@pytest.mark.parametrize('protocol_retry', [False, True])
def test_serial_choices_allow_background_image_writes(db, monkeypatch, display_mode, protocol_retry):
    from app.events.event_store import create_event
    world, agents, runner, client = setup_world(db, monkeypatch, count=1)
    world.settings_json = {**world.settings_json, 'agent_request_mode': 'serial',
                          'event_display_mode': display_mode}
    image = create_event(db, world=world, event_type='image_generation',
                         viewer_text='待生成', payload={'status': 'running'})
    db.commit()
    calls = 0

    async def post(_client, *, payload, **kwargs):
        nonlocal calls
        calls += 1
        # The model is waiting on HTTP while the independent image task saves.
        # A short timeout reproduces the production stall without waiting 30s.
        assert_writer_free(db)
        with sqlite3.connect(database.engine.url.database, timeout=0.05) as other:
            other.execute("update events set payload=json_set(payload,'$.status','completed') where event_id=?", (image.event_id,))
            other.commit()
        await asyncio.sleep(0)
        if protocol_retry and calls == 1:
            return {'choices': [{'message': {'content': 'invalid action'}}]}
        return reply(payload)

    monkeypatch.setattr(client, '_post_chat_completion', post)
    result = asyncio.run(runner.run_one_step(db, world.world_id))
    db.commit()
    db.refresh(image)
    assert calls == (2 if protocol_retry else 1)
    assert result.acted_agent_ids == [agents[0].agent_id]
    assert image.payload['status'] == 'completed'


def test_parallel_setting_roundtable_also_releases_writer(db, monkeypatch):
    from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world
    from app.world.werewolf import sync_werewolf_phase
    world, agents = _make_werewolf_world(db)
    world.settings_json = {**world.settings_json, 'agent_request_mode': 'parallel',
                          'narrator_enabled': False}
    world.current_world_time_minutes = 2160
    sync_werewolf_phase(db, world)
    db.commit()
    monkeypatch.setattr(runner_module, '_broadcast_step_progress', AsyncMock())
    calls = []

    async def complete(**kwargs):
        from app.llm.provider_base import LLMResult
        assert_writer_free(db)
        calls.append(kwargs['conversation_id'])
        await asyncio.sleep(0)
        return LLMResult('[01]\n我只说明自己亲眼见到的事。', None, {}, 1, 'test')

    monkeypatch.setattr(runner_module.provider, 'complete_text', complete)
    result = asyncio.run(runner_module.TurnRunner().run_one_step(db, world.world_id))
    assert len(calls) == len(result.acted_agent_ids) == 1
    assert db.get(Agent, result.acted_agent_ids[0]).chosen_name in [a.chosen_name for a in agents]
