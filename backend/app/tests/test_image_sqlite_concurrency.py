import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.core import database
from app.core.models import Event
from app.events.event_store import create_event
from app.image_generation import service
from app.narrator import narrator_service
from app.tests.test_image_prompt_integrity import setup_image


def _other_writer(db, event_id, cancel=False):
    assert not db.in_transaction(), 'No database transaction may span a network wait'
    with sqlite3.connect(database.engine.url.database, timeout=0.05) as other:
        other.execute('BEGIN IMMEDIATE')
        if cancel:
            other.execute("update events set payload=json_set(payload,'$.status','canceled') where event_id=?", (event_id,))
        other.commit()


@pytest.mark.parametrize('cancel_at', [None, 'prompt', 'image'])
def test_image_network_waits_release_database_and_preserve_cancellation(db, monkeypatch, cancel_at):
    world, agents, event, config = setup_image(db)
    event_id = event.event_id
    async def prompt(**kwargs):
        _other_writer(db, event_id, cancel_at == 'prompt')
        return SimpleNamespace(raw_text='POSITIVE=林见舟在窗边。\nNEGATIVE=', error=None)
    async def image(*args, **kwargs):
        _other_writer(db, event_id, cancel_at == 'image')
        return 'data:image/png;base64,c2FtcGxl'
    image_call = AsyncMock(side_effect=image)
    monkeypatch.setattr(service.provider, 'complete_text', prompt)
    monkeypatch.setattr(service, '_call_image_provider', image_call)
    monkeypatch.setattr(service, 'store_image_data_url', lambda _: {'image_url': '/mock.png'})
    monkeypatch.setattr(service, '_broadcast_image_update', AsyncMock())
    asyncio.run(service._generate_image_with_session(db, world, event))
    db.refresh(event)
    assert event.payload['status'] == ('canceled' if cancel_at else 'completed')
    assert image_call.await_count == (0 if cancel_at == 'prompt' else 1)


def test_database_failure_is_rolled_back_and_recorded_without_image_retry(db, monkeypatch):
    world, agents, event, config = setup_image(db)
    event_id, world_id = event.event_id, world.world_id
    async def fail(*args):
        # A failed flush poisons the session until rollback; reproduce that state.
        db.add(Event(world_id=world_id, event_type='invalid',
            world_time=0, viewer_text=None, agent_visible_text='test'))
        db.flush()
    monkeypatch.setattr(service, '_create_image_prompt', fail)
    image_call = AsyncMock(side_effect=AssertionError('No paid request'))
    monkeypatch.setattr(service, '_call_image_provider', image_call)
    monkeypatch.setattr(service, '_broadcast_image_update', AsyncMock())
    asyncio.run(service._generate_image_with_session(db, world, event))
    db.refresh(event)
    assert event.payload['status'] == 'failed'
    assert event.payload['failed_stage'] == 'prompt_writing'
    assert db.is_active
    image_call.assert_not_called()


def test_narrator_does_not_block_background_image_writer(db, monkeypatch):
    world, agents, event, config = setup_image(db)
    world.settings_json = {**world.settings_json, 'narrator_enabled': True,
        'narrator_config': {'model_name': 'test'}}
    source = create_event(db, world=world, event_type='note', viewer_text='大家到了。')
    async def narrator(**kwargs):
        _other_writer(db, event.event_id)
        return SimpleNamespace(raw_text='', error='offline stop')
    monkeypatch.setattr(narrator_service.provider, 'complete_text', narrator)
    asyncio.run(narrator_service.create_narration(db, world, [source.event_id]))
    # The writer test must run: swallowed provider exceptions would hide failure.
    assert not db.in_transaction()
