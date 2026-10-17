import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.llm.openai_compatible import OpenAICompatibleProvider, apply_haiku_context_guard


@pytest.mark.parametrize("model", ["anthropic/claude-haiku-5.5", "claude-haiku-5-5", "anthropic/claude-haiku-5.5:batch"])
def test_boundary(model):
    payload = {"model": model, "messages": [{"role": "user", "content": ""}], "max_tokens": 200000}
    overhead = len(json.dumps(payload["messages"], ensure_ascii=False).encode())
    n = 99000 - 2048 - 8192 - overhead - 1
    payload["messages"][0]["content"] = "a" * n
    assert apply_haiku_context_guard(payload) is None
    assert payload["max_tokens"] == 8192
    payload["messages"][0]["content"] += "a"
    assert "未发送" in apply_haiku_context_guard(payload)


@pytest.mark.parametrize("stream", [False, True])
def test_long_unicode_never_calls_network(stream):
    provider = OpenAICompatibleProvider()
    provider._post_chat_completion = AsyncMock(side_effect=AssertionError("network forbidden"))
    result = asyncio.run(provider.complete_text(
        model_alias="world_agent", system_prompt="角色设定", user_prompt="你" * 40000,
        model_name="anthropic/claude-haiku-5.5", api_key="test", base_url="http://invalid", stream=stream,
    ))
    assert "未发送" in result.error
    provider._post_chat_completion.assert_not_called()


def test_small_payload_and_other_models():
    payload = {"model": "anthropic/claude-haiku-5.5", "messages": [{"role": "user", "content": "你好"}]}
    assert apply_haiku_context_guard(payload) is None
    assert payload["max_tokens"] == 8192
    other = {"model": "openai/gpt-6-luna", "messages": [{"role": "user", "content": "a" * 200000}]}
    assert apply_haiku_context_guard(other) is None
    assert "max_tokens" not in other


def test_guard_rejects_uncounted_modalities():
    payload = {"model": "anthropic/claude-haiku-5.5", "messages": [{"role": "user", "content": [{"type": "image_url"}]}]}
    assert "未发送" in apply_haiku_context_guard(payload)
