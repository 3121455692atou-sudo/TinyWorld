from __future__ import annotations

from app.api.worlds import _pending_image_wait_cutoff
from app.core.models import Event, NarratorRun
from app.events.event_store import create_event
from app.image_generation.service import (
    create_manual_image_generation,
    maybe_schedule_auto_image_generation,
    _request_payload,
    normalize_image_generation_settings,
    schedule_image_generation,
)

from conftest import make_world


def test_image_generation_template_places_positive_and_negative_prompts():
    config = normalize_image_generation_settings(
        {
            "enabled": True,
            "provider_type": "sdxl",
            "request_template_json": '{"input":{"positive":"%prompt%","negative":"{{negative_prompt}}"},"width":"{{width}}","height":"%height%"}',
            "width": 768,
            "height": 1024,
        }
    )

    payload = _request_payload(config, "sdxl", "saki at the village square", "bad anatomy")

    assert payload["input"]["positive"] == "saki at the village square"
    assert payload["input"]["negative"] == "bad anatomy"
    assert payload["width"] == 768
    assert payload["height"] == 1024


def test_image_generation_default_payload_maps_known_providers():
    novelai = normalize_image_generation_settings({"provider_type": "novelai", "model_name": "nai-test"})
    sdxl = normalize_image_generation_settings({"provider_type": "sdxl", "model_name": "sdxl-test"})

    novelai_payload = _request_payload(novelai, "novelai", "positive tags", "negative tags")
    sdxl_payload = _request_payload(sdxl, "sdxl", "positive prose", "negative prose")

    assert novelai_payload["input"] == "positive tags"
    assert novelai_payload["parameters"]["negative_prompt"] == "negative tags"
    assert sdxl_payload["prompt"] == "positive prose"
    assert sdxl_payload["negative_prompt"] == "negative prose"


def test_image_generation_normalization_does_not_stringify_none():
    config = normalize_image_generation_settings(
        {
            "enabled": True,
            "base_url": None,
            "endpoint_path": None,
            "api_key": None,
            "prompt_llm_api_key": None,
            "workflow_json": None,
        }
    )

    assert config["enabled"] is True
    assert config["base_url"] == ""
    assert config["endpoint_path"] == ""
    assert config["api_key"] == ""
    assert config["prompt_llm_api_key"] == ""
    assert config["workflow_json"] == ""


def test_wait_display_mode_cuts_event_feed_at_pending_image(db):
    world, agents = make_world(db, 1)
    world.settings_json = {"image_generation": {"enabled": True, "display_mode": "wait"}}
    create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="前置事件。")
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"status": "pending", "display_mode": "wait"},
    )
    create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="后续事件。")
    db.flush()

    assert _pending_image_wait_cutoff(db, world) == image_event.event_id

    image_event.payload = {"status": "completed", "display_mode": "wait", "image_data_url": "data:image/png;base64,AA=="}
    db.flush()

    assert _pending_image_wait_cutoff(db, world) is None


def test_schedule_image_generation_creates_placeholder_event_without_loop(db):
    world, agents = make_world(db, 1)
    world.settings_json = {"image_generation": {"enabled": True, "display_mode": "placeholder", "provider_type": "sdxl"}}
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="发生了值得画下来的事。")
    run = NarratorRun(world_id=world.world_id, input_event_ids_json=[source.event_id], summary_title="画面", narration="一幕安静的场景。")
    db.add(run)
    db.flush()
    narration = create_event(db, world=world, event_type="narration", viewer_text="【解说】画面: 一幕安静的场景。")

    event_ids = schedule_image_generation(db, world, narrator_run=run, narration_event=narration, source_events=[source])

    assert len(event_ids) == 1
    image_event = db.get(Event, event_ids[0])
    assert image_event.event_type == "image_generation"
    assert image_event.payload["status"] == "pending"


def test_image_generation_normalizes_prompt_style_and_custom_prompt_llm():
    config = normalize_image_generation_settings(
        {
            "enabled": True,
            "source_mode": "auto_summary",
            "prompt_style": "flux",
            "prompt_llm_mode": "custom",
            "prompt_llm_base_url": "http://127.0.0.1:9000/v1",
            "prompt_llm_api_key": "secret",
            "prompt_llm_model_name": "prompt-model",
            "auto_frequency": "high",
        }
    )
    preserved = normalize_image_generation_settings({"prompt_llm_api_key": "***"}, existing=config)

    assert config["source_mode"] == "auto_summary"
    assert config["prompt_style"] == "flux"
    assert config["prompt_llm_mode"] == "custom"
    assert config["auto_frequency"] == "high"
    assert preserved["prompt_llm_api_key"] == "secret"


def test_auto_summary_image_generation_uses_rough_frequency(db):
    world, agents = make_world(db, 1)
    world.settings_json = {"image_generation": {"enabled": True, "source_mode": "auto_summary", "auto_frequency": "high"}}
    event_ids = [
        create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text=f"事件 {index}", importance=20).event_id
        for index in range(8)
    ]

    image_event_ids = maybe_schedule_auto_image_generation(db, world, event_ids)

    assert len(image_event_ids) == 1
    image_event = db.get(Event, image_event_ids[0])
    assert image_event.event_type == "image_generation"
    assert image_event.payload["source_mode"] == "auto_summary"


def test_manual_narration_image_generation_anchors_to_latest_narration(db):
    world, agents = make_world(db, 1)
    world.settings_json = {"image_generation": {"enabled": True, "source_mode": "narration", "provider_type": "sdxl"}}
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="一件适合成图的事。")
    run = NarratorRun(world_id=world.world_id, input_event_ids_json=[source.event_id], summary_title="一幕", narration="一幕适合绘制的场景。")
    db.add(run)
    db.flush()
    narration = create_event(
        db,
        world=world,
        event_type="narration",
        viewer_text="【解说】一幕: 一幕适合绘制的场景。",
        payload={"summary_title": "一幕", "narration": "一幕适合绘制的场景。", "narrator_run_id": run.narrator_run_id},
    )
    world.current_world_time_minutes += 120

    image_event_ids = create_manual_image_generation(db, world)

    assert len(image_event_ids) == 1
    image_event = db.get(Event, image_event_ids[0])
    assert image_event.world_time == narration.world_time
    assert image_event.payload["source_mode"] == "narration"
    assert image_event.payload["narration_event_id"] == narration.event_id
