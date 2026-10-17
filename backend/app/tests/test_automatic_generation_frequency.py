import asyncio

from app.events.event_store import create_event
from app.image_generation.service import maybe_schedule_auto_image_generation
from app.narrator import narrator_service
from conftest import make_world


def test_normal_narration_accumulates_new_events_and_ignores_force(db, monkeypatch):
    world, _ = make_world(db, 1)
    world.settings_json = {"narrator_config": {"model_name": "test", "auto_frequency": "normal"}}
    monkeypatch.setattr(narrator_service.settings, "narrator_events_per_summary", 8)
    calls = []

    async def narrate(session, world, ids, trigger_type):
        calls.append(ids)
        return [create_event(session, world=world, event_type="narration", viewer_text="summary").event_id]

    monkeypatch.setattr(narrator_service, "create_narration", narrate)
    for _ in range(10):
        create_event(db, world=world, event_type="birth", viewer_text="initial resident", importance=70)
    ids = []
    for index in range(8):
        event = create_event(db, world=world, event_type="introduce_self", viewer_text=f"hello {index}", importance=70)
        ids.append(event.event_id)
        result = asyncio.run(narrator_service.maybe_create_narration(db, world, [event.event_id], force=True))
        assert bool(result) == (index == 7)
    assert calls == [ids]
    # Neither an old event nor a low-importance action retriggers the same batch.
    assert asyncio.run(narrator_service.maybe_create_narration(db, world, ids, force=True)) == []
    quiet = create_event(db, world=world, event_type="look", viewer_text="look", importance=5)
    assert asyncio.run(narrator_service.maybe_create_narration(db, world, [quiet.event_id])) == []
    # A batch that crosses the threshold must not be missed by modulo counting.
    next_ids = [create_event(db, world=world, event_type="dialogue", viewer_text="talk", importance=60).event_id for _ in range(9)]
    assert asyncio.run(narrator_service.maybe_create_narration(db, world, next_ids))
    assert calls[-1] == next_ids


def test_normal_images_cannot_be_forced_by_introductions(db, monkeypatch):
    world, _ = make_world(db, 1)
    world.settings_json = {"image_generation": {"enabled": True, "auto_enabled": True, "source_mode": "auto_summary", "auto_frequency": "normal"}}
    monkeypatch.setattr("app.image_generation.service._schedule_background_generation", lambda *args: None)
    for _ in range(10):
        create_event(db, world=world, event_type="birth", viewer_text="initial resident", importance=70)
    for index in range(28):
        event = create_event(db, world=world, event_type="introduce_self", viewer_text="hello", importance=70)
        result = maybe_schedule_auto_image_generation(db, world, [event.event_id], force=True)
        assert bool(result) == (index in {13, 27})
