from __future__ import annotations

import asyncio
import io
import zipfile
from types import SimpleNamespace

from app.api.worlds import _pending_image_wait_cutoff
from app.core.models import Agent, Event, NarratorRun
from app.events.event_store import create_event
from app.image_generation.service import (
    _create_image_prompt,
    _fallback_prompt,
    _agent_alias_lines,
    _image_request_headers,
    _reference_images_for_event,
    create_manual_image_generation,
    create_prompt_image_generation,
    maybe_schedule_auto_image_generation,
    rerun_image_generation_event,
    _request_payload,
    _source_event_lines,
    _source_location_names,
    normalize_image_generation_settings,
    schedule_image_generation,
)
from app.export.event_archive import build_event_archive_zip
from app.narrator.narrator_service import _event_context_lines

from conftest import make_world


def _with_prompt_llm(config: dict) -> dict:
    return {
        **config,
        "prompt_llm_mode": "custom",
        "prompt_llm_provider_name": "test-provider",
        "prompt_llm_base_url": "http://127.0.0.1:9/v1",
        "prompt_llm_model_name": "test-prompt-model",
    }


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
    novelai = normalize_image_generation_settings({"provider_type": "novelai", "model_name": "nai-diffusion-3"})
    sdxl = normalize_image_generation_settings({"provider_type": "sdxl", "model_name": "sdxl-test"})

    novelai_payload = _request_payload(novelai, "novelai", "positive tags", "negative tags")
    sdxl_payload = _request_payload(sdxl, "sdxl", "positive prose", "negative prose")

    assert novelai_payload["input"] == "positive tags"
    assert novelai_payload["parameters"]["negative_prompt"] == "negative tags"
    assert sdxl_payload["prompt"].startswith("positive prose")
    assert "Avoid: negative prose" in sdxl_payload["prompt"]
    assert "negative_prompt" not in sdxl_payload
    assert sdxl_payload["model"] == "sdxl-test"


def test_novelai_payload_maps_advanced_parameters_and_reference_images():
    config = normalize_image_generation_settings(
        {
            "provider_type": "novelai",
            "custom_headers_json": '{"x-correlation-id":"ABC123"}',
            "nai_action": "img2img",
            "nai_image_format": "webp",
            "nai_n_samples": 2,
            "nai_uc_preset": 1,
            "nai_cfg_rescale": 0.4,
            "nai_sm": True,
            "nai_params_json": '{"noise_schedule":"native"}',
            "width": 640,
            "height": 768,
        }
    )

    headers = _image_request_headers(config, "novelai")
    payload = _request_payload(
        config,
        "novelai",
        "positive tags",
        "negative tags",
        reference_images=[{"content": b"abc", "media_type": "image/png"}],
    )

    assert headers["Accept"] == "application/zip"
    assert headers["x-correlation-id"] == "ABC123"
    assert payload["action"] == "img2img"
    assert payload["parameters"]["image"] == "YWJj"
    assert payload["parameters"]["image_format"] == "webp"
    assert payload["parameters"]["n_samples"] == 2
    assert payload["parameters"]["ucPreset"] == 1
    assert payload["parameters"]["cfg_rescale"] == 0.4
    assert "sm" not in payload["parameters"]
    assert payload["parameters"]["noise_schedule"] == "native"


def test_novelai_augment_payload_uses_reference_image():
    config = normalize_image_generation_settings(
        {
            "provider_type": "novelai",
            "endpoint_path": "/ai/augment-image",
            "nai_params_json": '{"req_type":"lineart","defry":1}',
        }
    )

    payload = _request_payload(
        config,
        "novelai",
        "keep the character",
        "",
        reference_images=[{"content": b"image-bytes", "media_type": "image/png"}],
    )

    assert payload["image"] == "aW1hZ2UtYnl0ZXM="
    assert payload["prompt"] == "keep the character"
    assert payload["req_type"] == "lineart"
    assert payload["defry"] == 1


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


def test_image_generation_empty_keys_preserve_existing_secrets():
    previous = normalize_image_generation_settings(
        {
            "api_key": "image-secret",
            "prompt_llm_api_key": "prompt-secret",
        }
    )

    preserved = normalize_image_generation_settings(
        {"api_key": "", "prompt_llm_api_key": None},
        existing=previous,
    )

    assert preserved["api_key"] == "image-secret"
    assert preserved["prompt_llm_api_key"] == "prompt-secret"


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


def test_image_generation_normalizes_model_options():
    config = normalize_image_generation_settings({"model_options": ["sdxl-a", "sdxl-a", "", "sdxl-b"]})

    assert config["model_options"] == ["sdxl-a", "sdxl-b"]


def test_image_generation_reference_options_collect_standing_images(db):
    world, agents = make_world(db, 1)
    agents[0].avatar_hint_json = {
        "image_data_url": "data:image/png;base64,QUJD",
        "standing_image_data_url": "data:image/png;base64,REVG",
    }
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="适合成图。")
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"source_event_ids": [source.event_id]},
    )
    config = normalize_image_generation_settings(
        {
            "reference_standing_images": True,
            "reference_avatar_images": False,
            "use_agent_appearance": False,
            "agent_aliases": {agents[0].agent_id: "test_alias"},
        }
    )

    references = _reference_images_for_event(db, world, image_event, config)
    alias_lines = _agent_alias_lines(agents, config)

    assert len(references) == 1
    assert references[0]["label"].endswith("standing")
    assert references[0]["content"] == b"DEF"
    assert "test_alias" in alias_lines
    assert "appearance:" not in alias_lines


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


def test_manual_prompt_image_generation_uses_user_prompt_without_prompt_llm(db):
    world, agents = make_world(db, 1)
    world.settings_json = {
        "image_generation": {
            "enabled": True,
            "source_mode": "narration",
            "provider_type": "sdxl",
            "style_prompt": "anime illustration",
            "negative_prompt": "low quality",
        }
    }
    latest = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="最新事件。")
    world.current_world_time_minutes += 60

    image_event_ids = create_prompt_image_generation(db, world, prompt="takamatsu tomori, village square", negative_prompt="bad hands")

    assert len(image_event_ids) == 1
    image_event = db.get(Event, image_event_ids[0])
    assert image_event.world_time == max(world.current_world_time_minutes, latest.world_time)
    assert image_event.payload["source_mode"] == "manual_prompt"
    assert image_event.payload["display_mode"] == "placeholder"
    prompt, negative, debug = asyncio.run(_create_image_prompt(db, world, image_event, normalize_image_generation_settings(world.settings_json["image_generation"])))
    assert prompt == "anime illustration, takamatsu tomori, village square"
    assert negative == "low quality, bad hands"
    assert debug["prompt_generation_source"] == "manual_prompt"


def test_image_prompt_records_llm_raw_output(monkeypatch, db):
    world, agents = make_world(db, 1)
    world.settings_json = {"image_generation": _with_prompt_llm({"enabled": True, "provider_type": "novelai", "style_prompt": "best quality"})}
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="她站在村庄广场。")
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"source_mode": "narration", "source_event_ids": [source.event_id], "narration": "她站在村庄广场。"},
    )

    async def fake_complete_text(**_kwargs):
        return SimpleNamespace(raw_text="POSITIVE=takamatsu tomori, village square, standing\nNEGATIVE=extra people", error=None)

    monkeypatch.setattr("app.image_generation.service.provider.complete_text", fake_complete_text)

    prompt, negative, debug = asyncio.run(_create_image_prompt(db, world, image_event, normalize_image_generation_settings(world.settings_json["image_generation"])))

    assert debug["prompt_generation_source"] == "llm"
    assert debug["prompt_llm_raw"].startswith("POSITIVE=takamatsu tomori")
    assert debug["prompt_content_raw"] == "takamatsu tomori, village square, standing"
    assert "takamatsu tomori" in prompt
    assert "extra people" in negative


def test_novelai_prompt_uses_default_style_and_strips_llm_style_terms(monkeypatch, db):
    world, agents = make_world(db, 1)
    world.settings_json = {"image_generation": _with_prompt_llm({"enabled": True, "provider_type": "novelai", "style_prompt": ""})}
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="她站在窗边。")
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"source_mode": "narration", "source_event_ids": [source.event_id], "narration": "她站在窗边。"},
    )

    async def fake_complete_text(**_kwargs):
        return SimpleNamespace(raw_text="POSITIVE=best quality, masterpiece, soft lighting, takamatsu tomori, by window\nNEGATIVE=low quality", error=None)

    monkeypatch.setattr("app.image_generation.service.provider.complete_text", fake_complete_text)

    prompt, negative, debug = asyncio.run(_create_image_prompt(db, world, image_event, normalize_image_generation_settings(world.settings_json["image_generation"])))

    assert "best quality" in prompt
    assert "amazing quality" in prompt
    assert "soft shading" in prompt
    assert "takamatsu tomori" in prompt
    assert "by window" in prompt
    assert "low quality" not in negative
    assert "worst quality" in negative
    assert debug["prompt_content_cleaned"] == "takamatsu tomori, by window"


def test_novelai_prompt_cleaner_drops_sd_weight_numbers(db):
    from app.image_generation.service import _clean_novelai_content_prompt

    cleaned = _clean_novelai_content_prompt("(nagasaki soyo: 1.1), (candlelight:1.2), 1.1, village hall", strip_style_terms=False)

    assert "nagasaki soyo" in cleaned
    assert "candlelight" in cleaned
    assert "village hall" in cleaned
    assert ", 1.1" not in cleaned


def test_image_prompt_replaces_display_name_with_drawing_alias(monkeypatch, db):
    world, agents = make_world(db, 1)
    agents[0].chosen_name = "丰川祥子"
    world.settings_json = {
        "image_generation": _with_prompt_llm({
            "enabled": True,
            "provider_type": "novelai",
            "agent_aliases": {agents[0].agent_id: "togawa sakiko"},
        })
    }
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="丰川祥子站在会议厅。")
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"source_mode": "narration", "source_event_ids": [source.event_id], "narration": "丰川祥子站在会议厅。"},
    )

    async def fake_complete_text(**_kwargs):
        return SimpleNamespace(raw_text="POSITIVE=丰川祥子, standing in meeting hall\nNEGATIVE=", error=None)

    monkeypatch.setattr("app.image_generation.service.provider.complete_text", fake_complete_text)

    prompt, _negative, debug = asyncio.run(_create_image_prompt(db, world, image_event, normalize_image_generation_settings(world.settings_json["image_generation"])))

    assert "togawa sakiko" in prompt
    assert "丰川祥子" not in prompt
    assert "togawa sakiko" in debug["prompt_content_cleaned"]


def test_novelai_prompt_enforces_character_aliases_for_generic_multi_person_tags(monkeypatch, db):
    world, agents = make_world(db, 2)
    agents[0].chosen_name = "千早爱音"
    agents[1].chosen_name = "三角初华"
    world.settings_json = {
        "image_generation": _with_prompt_llm({
            "enabled": True,
            "provider_type": "novelai",
            "style_prompt": "",
            "agent_aliases": {
                agents[0].agent_id: "chihaya anon",
                agents[1].agent_id: "misumi uika",
            },
        })
    }
    source = create_event(
        db,
        world=world,
        event_type="vote",
        actor_agent_id=agents[0].agent_id,
        target_agent_id=agents[1].agent_id,
        viewer_text="千早爱音和三角初华在圆桌旁举手投票。",
    )
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"source_mode": "narration", "source_event_ids": [source.event_id], "narration": "两人在圆桌旁投票。"},
    )

    async def fake_complete_text(**_kwargs):
        return SimpleNamespace(raw_text="POSITIVE=multiple girls, round table, raising hands, voting\nNEGATIVE=", error=None)

    monkeypatch.setattr("app.image_generation.service.provider.complete_text", fake_complete_text)

    prompt, _negative, debug = asyncio.run(_create_image_prompt(db, world, image_event, normalize_image_generation_settings(world.settings_json["image_generation"])))

    assert "2girls" in prompt
    assert "chihaya anon" in prompt
    assert "misumi uika" in prompt
    assert "multiple girls" not in prompt
    assert debug["prompt_content_cleaned"].startswith("2girls, chihaya anon, misumi uika")


def test_novelai_prompt_caps_generic_people_to_five_named_aliases(monkeypatch, db):
    world, agents = make_world(db, 4)
    for index in range(4, 8):
        agent = Agent(
            agent_id=f"agent_{index}",
            world_id=world.world_id,
            lifecycle_state="alive",
            model_alias="world_agent",
            chosen_name=f"角色{index + 1}",
            appearance_short="测试外貌",
        )
        db.add(agent)
        agents.append(agent)
    db.flush()
    aliases = {}
    for index, agent in enumerate(agents):
        agent.chosen_name = f"角色{index + 1}"
        aliases[agent.agent_id] = f"character tag {index + 1}"
    world.settings_json = {
        "image_generation": _with_prompt_llm({
            "enabled": True,
            "provider_type": "novelai",
            "style_prompt": "",
            "agent_aliases": aliases,
        })
    }
    source = create_event(
        db,
        world=world,
        event_type="roundtable",
        viewer_text="、".join(agent.chosen_name for agent in agents) + "围坐在圆桌旁。",
        payload={"participant_agent_ids": [agent.agent_id for agent in agents]},
    )
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="图片生成中。",
        payload={"source_mode": "narration", "source_event_ids": [source.event_id], "narration": "大家围坐在圆桌旁。"},
    )

    async def fake_complete_text(**_kwargs):
        return SimpleNamespace(raw_text="POSITIVE=multiple people, round table, sitting, paper, pen\nNEGATIVE=", error=None)

    monkeypatch.setattr("app.image_generation.service.provider.complete_text", fake_complete_text)

    prompt, _negative, debug = asyncio.run(_create_image_prompt(db, world, image_event, normalize_image_generation_settings(world.settings_json["image_generation"])))

    assert "5girls" in prompt
    assert "multiple people" not in prompt
    for index in range(1, 6):
        assert f"character tag {index}" in prompt
    assert "character tag 6" not in prompt
    assert debug["prompt_content_cleaned"].startswith("5girls, character tag 1, character tag 2")


def test_image_rerun_uses_user_prompt_verbatim(db):
    world, agents = make_world(db, 2)
    world.settings_json = {
        "image_generation": {
            "enabled": True,
            "provider_type": "novelai",
            "agent_aliases": {
                agents[0].agent_id: "chihaya anon",
                agents[1].agent_id: "misumi uika",
            },
        }
    }
    source = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, target_agent_id=agents[1].agent_id, viewer_text="两人说话。")
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="【生图】画面 已生成。",
        payload={"status": "completed", "source_event_ids": [source.event_id], "prompt": "old prompt"},
    )

    rerun_event = asyncio.run(
        rerun_image_generation_event(
            db,
            world,
            image_event.event_id,
            prompt="multiple girls, custom user prompt",
            negative_prompt="bad hands",
        )
    )

    prompt, negative, debug = asyncio.run(_create_image_prompt(db, world, rerun_event, normalize_image_generation_settings(world.settings_json["image_generation"])))

    assert prompt == "multiple girls, custom user prompt"
    assert negative == "bad hands"
    assert debug["prompt_generation_source"] == "rerun_manual"


def test_event_archive_can_include_generated_images(db):
    world, _agents = make_world(db, 1)
    image_event = create_event(
        db,
        world=world,
        event_type="image_generation",
        viewer_text="【生图】画面 已生成。",
        payload={
            "status": "completed",
            "summary_title": "食堂里的声音",
            "image_data_url": "data:image/png;base64,iVBORw0KGgo=",
        },
    )

    content = build_event_archive_zip(db, world, [image_event], include_images=True)

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        events_json = archive.read("events.json").decode("utf-8")

    assert "images/event_" + str(image_event.event_id) + "_食堂里的声音.png" in names
    assert f'"imagePath": "images/event_{image_event.event_id}_食堂里的声音.png"' in events_json
    assert '"text": ""' in events_json
    assert '"imageTitle": "食堂里的声音"' in events_json
    assert "[exported as image file]" in events_json


def test_narrator_context_includes_recorded_location_and_dialogue(db):
    world, agents = make_world(db, 2)
    event = create_event(
        db,
        world=world,
        event_type="dialogue",
        actor_agent_id=agents[0].agent_id,
        target_agent_id=agents[1].agent_id,
        location_id=f"{world.world_id}:central_square",
        viewer_text=f"{agents[0].chosen_name}向{agents[1].chosen_name}说话。",
        payload={
            "speech": "我们先在广场观察一下。",
            "dialogue_lines": [
                {
                    "speaker_agent_id": agents[0].agent_id,
                    "target_agent_id": agents[1].agent_id,
                    "text": "我们先在广场观察一下。",
                }
            ],
        },
    )

    context = _event_context_lines(db, [event])

    assert "location=中央广场" in context
    assert f"actor={agents[0].chosen_name}" in context
    assert "我们先在广场观察一下。" in context


def test_image_prompt_context_prefers_recorded_location_over_narration(db):
    world, agents = make_world(db, 2)
    event = create_event(
        db,
        world=world,
        event_type="dialogue",
        actor_agent_id=agents[0].agent_id,
        target_agent_id=agents[1].agent_id,
        location_id=f"{world.world_id}:central_square",
        viewer_text=f"{agents[0].chosen_name}向{agents[1].chosen_name}说话。",
        payload={
            "dialogue_lines": [
                {
                    "speaker_agent_id": agents[0].agent_id,
                    "target_agent_id": agents[1].agent_id,
                    "text": "我们先在广场观察一下。",
                }
            ]
        },
    )

    source_lines = _source_event_lines(db, [event])
    source_locations = _source_location_names(db, [event])
    fallback_prompt, _negative = _fallback_prompt(
        "anima",
        "声音落在傍晚的教室里。",
        [event],
        f"{agents[0].chosen_name} -> test_alias; appearance: short hair",
        "",
        "",
        source_locations,
    )

    assert "location=中央广场" in source_lines
    assert "我们先在广场观察一下。" in source_lines
    assert source_locations == "中央广场"
    assert "recorded location: 中央广场" in fallback_prompt
    assert "教室" not in fallback_prompt
