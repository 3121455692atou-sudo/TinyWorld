from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

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
