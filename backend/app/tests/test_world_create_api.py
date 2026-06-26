from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.content.bundle_manifest import BUNDLE_FORMAT, WORLD_CONFIG_FORMAT
from app.export.agent_presets import AGENT_ARCHIVE_FORMAT
from app.core.models import Agent, Conversation, Event, IdentityKnowledge, Item, Memory, NarratorRun, Relationship, World
from app.events.event_store import create_event
from app.main import app
from app.api.worlds import WerewolfRoleAssignmentInput, _normalize_werewolf_role_assignment


def test_werewolf_auto_role_assignment_normalizes_by_player_capacity():
    config = WerewolfRoleAssignmentInput(
        mode="auto",
        auto_roles=["villager", "werewolf", "seer", "coroner", "guard", "witch", "hunter", "medium", "idiot"],
    )

    normalized = _normalize_werewolf_role_assignment(config, 6)

    assert normalized["auto_roles"] == ["villager", "werewolf", "seer", "coroner", "guard", "witch"]


def test_werewolf_count_role_assignment_normalizes_to_player_capacity():
    config = WerewolfRoleAssignmentInput(
        mode="counts",
        counts={"werewolf": 2, "seer": 1, "coroner": 1, "guard": 1, "witch": 1, "hunter": 1},
    )

    normalized = _normalize_werewolf_role_assignment(config, 6)

    assert sum(normalized["counts"].values()) == 6
    assert normalized["counts"]["hunter"] == 0


def test_create_world_uses_payload_language_for_initial_event(db):
    client = TestClient(app)

    response = client.post(
        "/api/worlds",
        json={
            "name": "API Smoke World",
            "agent_count": 1,
            "language": "en",
            "narrator_config": {"enabled": False},
            "providers": [
                {
                    "provider_id": "local",
                    "name": "Local",
                    "base_url": "http://127.0.0.1:9/v1",
                    "api_key": "",
                    "retry_count": 0,
                    "retry_interval_ms": 0,
                    "rpm": 0,
                }
            ],
            "agent_configs": [
                {
                    "provider_id": "local",
                    "model_name": "test-model",
                    "chosen_name": "Ada",
                    "appearance": "Short dark hair, calm eyes, and a practical gray coat.",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "API Smoke World"
    assert payload["world_id"]

    agents = db.execute(select(Agent).where(Agent.world_id == payload["world_id"])).scalars().all()
    assert len(agents) == 1
    event = db.execute(select(Event).where(Event.event_type == "birth")).scalar_one()
    assert event.viewer_text == "Ada woke up in their own home and has not seen any other residents yet."


def test_edit_narration_event_updates_event_payload_and_narrator_run(db):
    client = TestClient(app)
    world = World(world_id="world_edit_narration", name="Edit Narration", status="paused", seed=1, settings_json={})
    db.add(world)
    db.flush()
    run = NarratorRun(
        world_id=world.world_id,
        input_event_ids_json=[],
        summary_title="旧标题",
        narration="旧正文。",
        trigger_type="manual",
    )
    db.add(run)
    db.flush()
    event = create_event(
        db,
        world=world,
        event_type="narration",
        visibility_scope="viewer_only",
        color_class="narrator",
        viewer_text="【解说】旧标题: 旧正文。",
        payload={"summary_title": "旧标题", "narration": "旧正文。", "narrator_run_id": run.narrator_run_id},
    )
    db.commit()

    response = client.patch(f"/api/worlds/{world.world_id}/events/{event.event_id}", json={"text": "新的正文。"})

    assert response.status_code == 200, response.text
    payload = response.json()["event"]
    assert payload["viewer_text"] == "【解说】旧标题: 新的正文。"
    assert payload["payload"]["summary_title"] == "旧标题"
    assert payload["payload"]["narration"] == "新的正文。"
    db.refresh(run)
    assert run.summary_title == "旧标题"
    assert run.narration == "新的正文。"

    response = client.patch(f"/api/worlds/{world.world_id}/events/{event.event_id}", json={"text": "【解说】新标题: 再改一次。"})

    assert response.status_code == 200, response.text
    payload = response.json()["event"]
    assert payload["viewer_text"] == "【解说】新标题: 再改一次。"
    db.refresh(run)
    assert run.summary_title == "新标题"
    assert run.narration == "再改一次。"


def test_runtime_settings_support_parallel_mode_and_concurrency_limits(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Runtime Settings World",
            "agent_count": 1,
            "agent_request_mode": "parallel",
            "event_display_mode": "per_agent",
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "agent_configs": [{"provider_id": "local", "chosen_name": "Ada", "appearance": "Short dark hair, calm eyes, and a practical gray coat."}],
        },
    )
    assert response.status_code == 200, response.text
    created_payload = response.json()
    world_id = created_payload["world_id"]
    assert created_payload["settings"]["agent_request_mode"] == "parallel"
    assert created_payload["settings"]["event_display_mode"] == "batch"

    patch = client.patch(
        f"/api/worlds/{world_id}/runtime-settings",
        json={
            "agent_request_mode": "parallel",
            "event_display_mode": "per_agent",
            "llm_concurrency": {
                "default_provider_limit": 8,
                "provider_limits": {"Local": 3},
                "model_limits": {"test-model": 2},
            },
        },
    )

    assert patch.status_code == 200, patch.text
    settings = patch.json()["settings"]
    assert settings["agent_request_mode"] == "parallel"
    assert settings["event_display_mode"] == "batch"
    assert settings["llm_concurrency"]["default_provider_limit"] == 8
    assert settings["llm_concurrency"]["provider_limits"]["Local"] == 3
    assert settings["llm_concurrency"]["model_limits"]["test-model"] == 2


def test_create_world_persists_image_generation_settings(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Image Settings World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "image_generation": {
                "enabled": True,
                "source_mode": "narration",
                "provider_type": "comfyui",
                "prompt_style": "anima",
                "display_mode": "placeholder",
                "base_url": "http://127.0.0.1:8188",
                "workflow_json": "{}",
            },
            "agent_configs": [
                {
                    "provider_id": "local",
                    "chosen_name": "Ada",
                    "image_prompt_name": "ada_tag",
                    "appearance": "Short dark hair, calm eyes.",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    image_generation = response.json()["settings"]["image_generation"]
    assert image_generation["enabled"] is True
    assert image_generation["source_mode"] == "narration"
    assert image_generation["provider_type"] == "comfyui"
    assert image_generation["prompt_style"] == "anima"
    assert image_generation["display_mode"] == "placeholder"

    world = db.get(World, response.json()["world_id"])
    aliases = world.settings_json["image_generation"]["agent_aliases"]
    agent = db.execute(select(Agent).where(Agent.world_id == world.world_id)).scalar_one()
    assert aliases[agent.agent_id] == "ada_tag"


def test_agent_config_change_events_are_low_importance(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Config Event World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "agent_configs": [{"provider_id": "local", "chosen_name": "Ada", "appearance": "Short dark hair, calm eyes."}],
        },
    )
    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    agent = db.execute(select(Agent).where(Agent.world_id == world_id)).scalar_one()

    llm_patch = client.patch(
        f"/api/worlds/{world_id}/agents/{agent.agent_id}/llm",
        json={"model_name": "other-test-model", "retry_count": 1},
    )
    assert llm_patch.status_code == 200, llm_patch.text
    profile_patch = client.patch(
        f"/api/worlds/{world_id}/agents/{agent.agent_id}/profile",
        json={
            "tts_config": {"enabled": True, "base_url": "http://127.0.0.1:9881", "endpoint_path": "/tts"},
            "image_prompt_name": "ada_runtime_tag",
        },
    )
    assert profile_patch.status_code == 200, profile_patch.text
    assert profile_patch.json()["identity"]["image_prompt_name"] == "ada_runtime_tag"
    db.refresh(agent.world)
    image_generation = agent.world.settings_json["image_generation"]
    assert image_generation["agent_aliases"][agent.agent_id] == "ada_runtime_tag"

    events = db.execute(
        select(Event)
        .where(Event.world_id == world_id, Event.event_type.in_(["llm_config_changed", "agent_profile_changed"]))
        .order_by(Event.event_id.asc())
    ).scalars().all()

    assert [event.event_type for event in events] == ["llm_config_changed", "agent_profile_changed"]
    assert all(event.importance == 1 for event in events)
    assert all(event.color_class == "muted" for event in events)
    assert all(event.no_state_changed for event in events)


def test_event_delete_restores_events_conversations_and_source_refs(db):
    client = TestClient(app)
    world = World(world_id="world_event_delete_restore", name="Event Delete Restore", status="paused", seed=1, settings_json={})
    agent = Agent(agent_id="agent_event_delete_restore", world_id=world.world_id, lifecycle_state="alive")
    db.add_all([world, agent])
    db.flush()
    event = create_event(
        db,
        world=world,
        event_type="dialogue",
        actor_agent_id=agent.agent_id,
        viewer_text="Ada 说了一句话。",
        agent_visible_text="Ada 说了一句话。",
        payload={"speech": "你好。"},
    )
    conversation = Conversation(
        event_id=event.event_id,
        speaker_agent_id=agent.agent_id,
        content_zh="你好。",
        tone="calm",
        heard_by_agent_ids_json=[agent.agent_id],
        world_time=event.world_time,
    )
    memory = Memory(
        agent_id=agent.agent_id,
        source_event_id=event.event_id,
        memory_type="episodic",
        content="Ada 说了你好。",
        created_world_time=event.world_time,
    )
    item = Item(item_id="item_event_delete_restore", world_id=world.world_id, name="记录纸", created_event_id=event.event_id)
    db.add_all([conversation, memory, item])
    db.commit()
    event_id = event.event_id
    utterance_id = conversation.utterance_id
    memory_id = memory.memory_id
    item_id = item.item_id

    response = client.post(f"/api/worlds/{world.world_id}/events/delete", json={"event_ids": [event_id]})
    assert response.status_code == 200, response.text
    assert response.json()["deleted_event_ids"] == [event_id]
    assert response.json()["undo_count"] == 1
    db.expire_all()
    assert db.get(Event, event_id) is None
    assert db.get(Conversation, utterance_id) is None
    assert db.get(Memory, memory_id).source_event_id is None
    assert db.get(Item, item_id).created_event_id is None

    undo_response = client.post(f"/api/worlds/{world.world_id}/events/undo-delete")
    assert undo_response.status_code == 200, undo_response.text
    assert undo_response.json()["restored_event_ids"] == [event_id]
    assert undo_response.json()["undo_count"] == 0
    db.expire_all()
    restored_event = db.get(Event, event_id)
    assert restored_event is not None
    assert restored_event.viewer_text == "Ada 说了一句话。"
    assert db.get(Conversation, utterance_id).event_id == event_id
    assert db.get(Memory, memory_id).source_event_id == event_id
    assert db.get(Item, item_id).created_event_id == event_id


def test_event_delete_undo_limit_keeps_latest_batches_only(db):
    client = TestClient(app)
    world = World(world_id="world_event_delete_limit", name="Event Delete Limit", status="paused", seed=1, settings_json={})
    db.add(world)
    db.flush()
    event_a = create_event(db, world=world, event_type="notice", viewer_text="第一条")
    event_b = create_event(db, world=world, event_type="notice", viewer_text="第二条")
    db.commit()
    event_a_id = event_a.event_id
    event_b_id = event_b.event_id

    limit_response = client.patch(f"/api/worlds/{world.world_id}/events/delete-state", json={"limit": 1})
    assert limit_response.status_code == 200, limit_response.text
    assert limit_response.json()["undo_limit"] == 1
    assert client.post(f"/api/worlds/{world.world_id}/events/delete", json={"event_ids": [event_a_id]}).status_code == 200
    second_delete = client.post(f"/api/worlds/{world.world_id}/events/delete", json={"event_ids": [event_b_id]})
    assert second_delete.status_code == 200, second_delete.text
    assert second_delete.json()["undo_count"] == 1

    undo_response = client.post(f"/api/worlds/{world.world_id}/events/undo-delete")
    assert undo_response.status_code == 200, undo_response.text
    db.expire_all()
    assert db.get(Event, event_a_id) is None
    assert db.get(Event, event_b_id) is not None


def test_start_world_resets_llm_failure_retry_window(db, monkeypatch):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "LLM Retry Reset World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "agent_configs": [{"provider_id": "local", "chosen_name": "Ada", "appearance": "Short dark hair, calm eyes."}],
        },
    )
    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    agent = db.execute(select(Agent).where(Agent.world_id == world_id)).scalar_one()
    agent.tool_learning_json = {
        **(agent.tool_learning_json or {}),
        "llm_consecutive_failures": 3,
        "last_llm_error": "request timed out",
    }
    db.commit()

    monkeypatch.setattr("app.api.worlds.simulation_manager.start", lambda world_id, speed: None)
    start_response = client.post(f"/api/worlds/{world_id}/start")

    assert start_response.status_code == 200, start_response.text
    db.expire_all()
    refreshed = db.get(Agent, agent.agent_id)
    assert refreshed.tool_learning_json["llm_consecutive_failures"] == 0
    assert refreshed.tool_learning_json["last_llm_error"] == "request timed out"
    world = db.get(World, world_id)
    assert refreshed.tool_learning_json["llm_manual_retry_world_time"] == world.current_world_time_minutes


def test_create_world_initial_agent_knowledge_and_affection(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Initial Knowledge World",
            "agent_count": 3,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "agent_configs": [
                {
                    "provider_id": "local",
                    "chosen_name": "Ada",
                    "appearance": "Short dark hair, calm eyes.",
                    "knowledge_mode": "custom",
                    "known_agents": {"1": {"knows": True, "affection": 42}, "2": {"knows": False, "affection": 80}},
                },
                {"provider_id": "local", "chosen_name": "Bert", "appearance": "Tall and quiet.", "knowledge_mode": "none"},
                {"provider_id": "local", "chosen_name": "Cora", "appearance": "Bright jacket.", "knowledge_mode": "all"},
            ],
        },
    )

    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    agents = db.execute(select(Agent).where(Agent.world_id == world_id)).scalars().all()
    by_name = {agent.chosen_name: agent for agent in agents}
    ada, bert, cora = by_name["Ada"], by_name["Bert"], by_name["Cora"]

    ada_knows_bert = db.execute(
        select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == ada.agent_id,
            IdentityKnowledge.target_agent_id == bert.agent_id,
        )
    ).scalar_one()
    assert ada_knows_bert.name_known is True
    assert ada_knows_bert.visual_known is True
    assert ada_knows_bert.known_name == "Bert"

    assert db.execute(
        select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == ada.agent_id,
            IdentityKnowledge.target_agent_id == cora.agent_id,
        )
    ).scalar_one_or_none() is None

    ada_to_bert = db.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == ada.agent_id,
            Relationship.target_agent_id == bert.agent_id,
        )
    ).scalar_one()
    assert ada_to_bert.affection == 42
    assert ada_to_bert.familiarity >= 25

    cora_known = db.execute(select(IdentityKnowledge).where(IdentityKnowledge.observer_agent_id == cora.agent_id)).scalars().all()
    assert {row.known_name for row in cora_known} == {"Ada", "Bert"}

    export_response = client.get(f"/api/worlds/{world_id}/agents/export")
    assert export_response.status_code == 200, export_response.text
    with zipfile.ZipFile(io.BytesIO(export_response.content)) as zf:
        agent_config = json.loads(zf.read("configs/agent_config.json"))
    assert agent_config["exportOptions"]["knowledge"] is True
    exported_by_name = {item["chosenName"]: item for item in agent_config["agents"]}
    bert_index = str(exported_by_name["Bert"]["index"])
    ada_index = str(exported_by_name["Ada"]["index"])
    assert exported_by_name["Ada"]["knowledgeMode"] == "custom"
    assert exported_by_name["Ada"]["knownAgents"][bert_index] == {"knows": True, "affection": 42.0}
    assert exported_by_name["Cora"]["knowledgeMode"] == "custom"
    assert exported_by_name["Cora"]["knownAgents"][ada_index] == {"knows": True, "affection": 0}
    assert exported_by_name["Cora"]["knownAgents"][bert_index] == {"knows": True, "affection": 0}


def test_high_importance_legacy_config_events_are_filtered_from_significant_feed(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Legacy Config Event World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "agent_configs": [{"provider_id": "local", "chosen_name": "Ada", "appearance": "Short dark hair, calm eyes."}],
        },
    )
    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]
    world = db.get(World, world_id)
    assert world is not None
    agent = db.execute(select(Agent).where(Agent.world_id == world_id)).scalar_one()
    create_event(
        db,
        world=world,
        event_type="llm_config_changed",
        actor_agent_id=agent.agent_id,
        viewer_text="Ada 的 LLM 配置已更新。",
        importance=45,
        color_class="info",
    )
    db.commit()

    feed = client.get(f"/api/worlds/{world_id}/events", params={"min_importance": 45, "limit": 10000})

    assert feed.status_code == 200, feed.text
    assert all(event["event_type"] != "llm_config_changed" for event in feed.json()["events"])


def test_agent_preset_export_redacts_provider_generation_and_tts_secrets(db):
    client = TestClient(app)
    world = World(
        world_id="world_export_secret_redaction",
        name="Secret Redaction World",
        status="paused",
        seed=1,
        settings_json={
            "image_generation": {
                "enabled": True,
                "api_key": "image-secret-key",
                "prompt_llm_api_key": "prompt-secret-key",
                "custom_headers_json": '{"Authorization":"Bearer image-header-secret"}',
                "max_tokens": 321,
            },
            "narrator_enabled": True,
            "narrator_config": {
                "provider_id": "narrator-provider",
                "provider_name": "Narrator Provider",
                "base_url": "http://127.0.0.1:9/v1",
                "api_key": "narrator-secret-key",
                "model_name": "narrator-model",
            },
            "baby_model_pool": [
                {
                    "provider_id": "baby-provider",
                    "provider_name": "Baby Provider",
                    "base_url": "http://127.0.0.1:9/v1",
                    "api_key": "baby-secret-key",
                    "model_name": "baby-model",
                }
            ],
        },
    )
    agent = Agent(
        agent_id="agent_export_secret_redaction",
        world_id=world.world_id,
        lifecycle_state="alive",
        model_provider_id="agent-provider",
        model_provider_name="Agent Provider",
        model_name="agent-model",
        llm_base_url="http://127.0.0.1:9/v1",
        llm_api_key="agent-secret-key",
        chosen_name="Ada",
        appearance_full="Short dark hair, calm eyes.",
        tool_learning_json={
            "tts_config": {
                "enabled": True,
                "apiKey": "tts-secret-key",
                "access_token": "voice-access-token",
                "secret": "voice-secret",
                "max_tokens": 64,
            }
        },
    )
    db.add_all([world, agent])
    db.commit()

    export = client.get(f"/api/worlds/{world.world_id}/agents/export")

    assert export.status_code == 200, export.text
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        agent_config = json.loads(zf.read("configs/agent_config.json").decode("utf-8"))
    dumped = json.dumps(agent_config, ensure_ascii=False)
    for secret in (
        "agent-secret-key",
        "narrator-secret-key",
        "baby-secret-key",
        "image-secret-key",
        "prompt-secret-key",
        "image-header-secret",
        "tts-secret-key",
        "voice-access-token",
        "voice-secret",
    ):
        assert secret not in dumped
    assert all(provider["apiKey"] == "" for provider in agent_config["providers"])
    assert agent_config["imageGeneration"]["api_key"] == ""
    assert agent_config["imageGeneration"]["prompt_llm_api_key"] == ""
    assert json.loads(agent_config["imageGeneration"]["custom_headers_json"]) == {"Authorization": ""}
    assert agent_config["imageGeneration"]["max_tokens"] == 321
    tts_config = agent_config["agents"][0]["ttsConfig"]
    assert tts_config["apiKey"] == ""
    assert tts_config["access_token"] == ""
    assert tts_config["secret"] == ""
    assert tts_config["max_tokens"] == 64


def test_agent_preset_export_uses_bundle_manifest_with_world_and_agent_configs(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Bundle Export World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "models": ["test-model"]}],
            "agent_configs": [{"provider_id": "local", "chosen_name": "Ada", "appearance": "Short dark hair, calm eyes."}],
        },
    )
    assert response.status_code == 200, response.text
    world_id = response.json()["world_id"]

    export = client.get(f"/api/worlds/{world_id}/agents/export")

    assert export.status_code == 200, export.text
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["format"] == BUNDLE_FORMAT
        components = {item["type"]: item for item in manifest["components"]}
        assert components["world_config"]["format"] == WORLD_CONFIG_FORMAT
        assert components["agent_config"]["format"] == AGENT_ARCHIVE_FORMAT
        world_config = json.loads(zf.read(components["world_config"]["path"]).decode("utf-8"))
        agent_config = json.loads(zf.read(components["agent_config"]["path"]).decode("utf-8"))
    assert world_config["name"] == "Bundle Export World"
    assert agent_config["agents"][0]["chosenName"] == "Ada"
