from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.content.bundle_manifest import BUNDLE_FORMAT, WORLD_CONFIG_FORMAT
from app.export.agent_presets import AGENT_ARCHIVE_FORMAT
from app.core.models import Agent, Event, IdentityKnowledge, Relationship, World
from app.events.event_store import create_event
from app.main import app


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
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
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


def test_agent_config_change_events_are_low_importance(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Config Event World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
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
        json={"tts_config": {"enabled": True, "base_url": "http://127.0.0.1:9881", "endpoint_path": "/tts"}},
    )
    assert profile_patch.status_code == 200, profile_patch.text

    events = db.execute(
        select(Event)
        .where(Event.world_id == world_id, Event.event_type.in_(["llm_config_changed", "agent_profile_changed"]))
        .order_by(Event.event_id.asc())
    ).scalars().all()

    assert [event.event_type for event in events] == ["llm_config_changed", "agent_profile_changed"]
    assert all(event.importance == 1 for event in events)
    assert all(event.color_class == "muted" for event in events)
    assert all(event.no_state_changed for event in events)


def test_start_world_resets_llm_failure_retry_window(db, monkeypatch):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "LLM Retry Reset World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
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
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
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
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
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


def test_agent_preset_export_uses_bundle_manifest_with_world_and_agent_configs(db):
    client = TestClient(app)
    response = client.post(
        "/api/worlds",
        json={
            "name": "Bundle Export World",
            "agent_count": 1,
            "narrator_config": {"enabled": False},
            "providers": [{"provider_id": "local", "name": "Local", "base_url": "http://127.0.0.1:9/v1", "api_key": ""}],
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
