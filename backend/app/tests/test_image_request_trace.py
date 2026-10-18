import asyncio
import base64
import json
import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.image_generation import service
from app.llm import request_trace
from app.tests.test_image_prompt_integrity import setup_image


@pytest.fixture
def trace_file(monkeypatch, tmp_path):
    path = tmp_path / "requests.jsonl"
    logger = logging.getLogger(uuid4().hex)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    monkeypatch.setattr(request_trace, "TRACE_PATH", path)
    monkeypatch.setattr(request_trace, "_logger", logger)
    yield path
    for handler in logger.handlers:
        handler.close()


def test_trace_redacts_credentials_and_image_bytes(trace_file):
    request_trace.trace("test", endpoint="https://user:secret@example.com/images?key=secret",
        payload={"api_key": "secret", "headers": {"Authorization": "Bearer secret"},
                 "reference": "data:image/png;base64," + "YQ==" * 2000,
                 "image": "YQ==" * 2000, "prompt": "手写画面。"})
    raw = trace_file.read_text()
    assert "secret" not in raw and "YQ==" not in raw
    assert "手写画面。" in raw
    assert trace_file.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("http_status", [200, 402])
def test_image_http_stages_are_correlated_and_failure_is_persisted(db, monkeypatch, trace_file, http_status):
    world, agents, event, config = setup_image(db)
    config.update(base_url="https://openrouter.ai/api/v1", endpoint_path="/images", api_key="secret-test", model_name="test-image")
    world.settings_json = {"image_generation": config}
    db.commit()
    monkeypatch.setattr(service, "_create_image_prompt", AsyncMock(return_value=("手写画面。", "", {})))
    monkeypatch.setattr(service, "_reference_images_for_event", lambda *args, **kwargs: [{"label": "角色甲", "media_type": "image/png", "content": b"sample"}])
    monkeypatch.setattr(service, "store_image_data_url", lambda _: {"image_url": "/mock.png"})
    monkeypatch.setattr(service, "_broadcast_image_update", AsyncMock())
    original = httpx.AsyncClient
    def respond(request):
        return httpx.Response(http_status, headers={"x-request-id": "upstream-42"}, json={"data": [{"b64_json": base64.b64encode(b"sample" * 100).decode()}]} if http_status == 200 else {"error": "payment required"})
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    asyncio.run(service._generate_image_with_session(db, world, event))
    db.refresh(event)
    entries = [json.loads(line) for line in trace_file.read_text().splitlines()]
    assert all(e["trace_id"] == event.payload["request_trace_id"] for e in entries)
    assert all(e["image_event_id"] == event.event_id for e in entries)
    assert "image.prompt_writing" in [e["stage"] for e in entries]
    request = next(e for e in entries if e["stage"] == "image.http_request")
    assert request["payload"]["prompt"] == "手写画面。" and request["reference_count"] == 1
    response = next(e for e in entries if e["stage"] == "image.http_response")
    assert response["status_code"] == http_status and response["upstream_request_id"] == "upstream-42"
    assert "secret-test" not in trace_file.read_text()
    assert event.payload["status"] == ("completed" if http_status == 200 else "failed")
    if http_status != 200:
        assert event.payload["failed_stage"] == "image_request"
        assert any(e["stage"] == "image.failed" for e in entries)


def test_restart_never_resubmits_an_unknown_billed_request(db, monkeypatch, trace_file):
    from contextlib import nullcontext
    world, agents, event, config = setup_image(db)
    event.payload = {**event.payload, "provider_type": "sdxl", "status": "running", "generation_stage": "image_request"}
    db.commit()
    monkeypatch.setattr(service, "SessionLocal", lambda: nullcontext(db))
    schedule = AsyncMock(side_effect=AssertionError("No paid duplicate"))
    monkeypatch.setattr(service, "_schedule_background_generation", schedule)
    assert service.resume_pending_image_generations() == 0
    assert event.payload["status"] == "failed"
    assert event.payload["generation_stage"] == "interrupted"
    schedule.assert_not_called()
