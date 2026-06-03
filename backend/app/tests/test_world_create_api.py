from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.content.bundle_manifest import BUNDLE_FORMAT, WORLD_CONFIG_FORMAT
from app.export.agent_presets import AGENT_ARCHIVE_FORMAT
from app.core.models import Agent, Event
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
