from __future__ import annotations

import asyncio
import json
from collections import deque
import threading
import time
from typing import Any

import httpx

from app.core.config import Settings, settings
from app.llm.provider_base import LLMResult
from app.llm.runtime import normalize_llm_runtime


class OpenAICompatibleProvider:
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.provider_name = config.llm_default_provider
        self._active_by_model: dict[str, int] = {}
        self._active_by_provider: dict[str, int] = {}
        self._capacity_lock = threading.Lock()
        self._rpm_lock = asyncio.Lock()
        self._request_times_by_key: dict[str, deque[float]] = {}

    def model_limit(self, model_name: str | None) -> int:
        model = (model_name or "").lower()
        if "pro" in model:
            return 4
        return 16

    def model_has_capacity_now(self, *, model_name: str | None, base_url: str | None = None, provider_name: str | None = None, limits: dict[str, Any] | None = None) -> bool:
        model = model_name or self.config.model_name("world_agent")
        resolved_base_url = base_url or self.config.llm_base_url
        key = self._capacity_key(resolved_base_url, model)
        limit = self._model_limit(resolved_base_url, model, provider_name, limits)
        with self._capacity_lock:
            return self._active_by_model.get(key, 0) < limit

    async def complete_text(
        self,
        *,
        model_alias: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        stream: bool = False,
        top_p: float | None = None,
        max_tokens: int | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        provider_name: str | None = None,
        retry_count: int = 2,
        retry_interval_ms: int = 1500,
        request_timeout_ms: int = 300_000,
        rpm: int = 0,
        concurrency_limits: dict[str, Any] | None = None,
    ) -> LLMResult:
        """Plain chat-completion call used by all model-facing protocols."""
        started = time.perf_counter()
        resolved_api_key = api_key or self.config.api_key
        if not resolved_api_key:
            return LLMResult("", None, {}, 0, self.provider_name, "LLM API key is not configured")
        model = model_name or self.config.model_name(model_alias)
        resolved_base_url = (base_url or self.config.llm_base_url).rstrip("/")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if stream:
            payload["stream"] = True
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        if presence_penalty is not None:
            payload["presence_penalty"] = presence_penalty
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty
        headers = {"Authorization": f"Bearer {resolved_api_key}", "Content-Type": "application/json"}
        capacity_key = await self._reserve_capacity(
            resolved_base_url,
            model,
            provider_name=provider_name,
            limits=concurrency_limits,
        )
        runtime = normalize_llm_runtime(
            {
                "retry_count": retry_count,
                "retry_interval_ms": retry_interval_ms,
                "request_timeout_ms": request_timeout_ms,
                "rpm": rpm,
            }
        )
        attempts = runtime["retry_count"] + 1
        retry_sleep_seconds = runtime["retry_interval_ms"] / 1000
        request_timeout = None if runtime["request_timeout_ms"] <= 0 else runtime["request_timeout_ms"] / 1000
        rpm_key = self._capacity_key(resolved_base_url, model)
        last_error: Exception | None = None
        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                for attempt in range(attempts):
                    try:
                        await self._wait_for_rpm_slot(rpm_key, runtime["rpm"])
                        data = await self._post_chat_completion(
                            client,
                            resolved_base_url=resolved_base_url,
                            headers=headers,
                            payload=payload,
                            stream=stream,
                        )
                        choice = data["choices"][0]
                        finish_reason = str(choice.get("finish_reason") or "")
                        raw = str(choice["message"].get("content") or "")
                        if not raw.strip():
                            raise ValueError("model returned empty text")
                        if _is_length_finish_reason(finish_reason):
                            raise ValueError("model output was truncated because the completion token budget was exhausted")
                        usage = dict(data.get("usage") or {})
                        if finish_reason:
                            usage["finish_reason"] = finish_reason
                        return LLMResult(
                            raw_text=raw,
                            parsed_object=raw,
                            token_usage=usage,
                            latency_ms=int((time.perf_counter() - started) * 1000),
                            provider_name=self.provider_name,
                        )
                    except (httpx.HTTPError, KeyError, ValueError) as exc:
                        last_error = exc
                        if attempt < attempts - 1 and retry_sleep_seconds > 0:
                            await asyncio.sleep(retry_sleep_seconds)
            return LLMResult(
                raw_text="",
                parsed_object=None,
                token_usage={},
                latency_ms=int((time.perf_counter() - started) * 1000),
                provider_name=self.provider_name,
                error=str(last_error or "LLM request failed"),
            )
        finally:
            self._release_capacity(capacity_key)

    async def _post_chat_completion(
        self,
        client: httpx.AsyncClient,
        *,
        resolved_base_url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        stream: bool = False,
    ) -> dict[str, Any]:
        if not stream:
            response = await client.post(
                f"{resolved_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

        parts: list[str] = []
        usage: dict[str, Any] = {}
        finish_reason = ""
        async with client.stream(
            "POST",
            f"{resolved_base_url}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if data_text == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
                delta = choice.get("delta") if isinstance(choice, dict) else None
                message = choice.get("message") if isinstance(choice, dict) else None
                if isinstance(delta, dict):
                    content = delta.get("content") or ""
                elif isinstance(message, dict):
                    content = message.get("content") or ""
                else:
                    content = ""
                if content:
                    parts.append(str(content))
        return {"choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish_reason}], "usage": usage}

    async def _reserve_capacity(self, base_url: str, model: str, *, provider_name: str | None = None, limits: dict[str, Any] | None = None) -> tuple[str, str]:
        model_key = self._capacity_key(base_url, model)
        provider_key = self._provider_capacity_key(base_url, provider_name)
        model_limit = self._model_limit(base_url, model, provider_name, limits)
        provider_limit = self._provider_limit(base_url, provider_key, provider_name, limits)
        while True:
            with self._capacity_lock:
                model_active = self._active_by_model.get(model_key, 0)
                provider_active = self._active_by_provider.get(provider_key, 0)
                if model_active < model_limit and provider_active < provider_limit:
                    self._active_by_model[model_key] = model_active + 1
                    self._active_by_provider[provider_key] = provider_active + 1
                    return model_key, provider_key
            await asyncio.sleep(0.05)

    def _release_capacity(self, key: tuple[str, str]) -> None:
        model_key, provider_key = key
        with self._capacity_lock:
            active = self._active_by_model.get(model_key, 0)
            if active <= 1:
                self._active_by_model.pop(model_key, None)
            else:
                self._active_by_model[model_key] = active - 1
            provider_active = self._active_by_provider.get(provider_key, 0)
            if provider_active <= 1:
                self._active_by_provider.pop(provider_key, None)
            else:
                self._active_by_provider[provider_key] = provider_active - 1

    def _capacity_key(self, base_url: str, model: str) -> str:
        return f"{base_url.rstrip('/')}::{model}"

    def _provider_capacity_key(self, base_url: str, provider_name: str | None) -> str:
        name = (provider_name or "").strip() or "default"
        return f"{base_url.rstrip('/')}::{name}"

    def _model_limit(self, base_url: str, model_name: str | None, provider_name: str | None = None, limits: dict[str, Any] | None = None) -> int:
        model = (model_name or "").strip()
        model_limits = limits.get("model_limits") if isinstance(limits, dict) else None
        if isinstance(model_limits, dict):
            normalized_base_url = base_url.rstrip("/")
            provider = (provider_name or "").strip()
            candidates = [
                self._capacity_key(normalized_base_url, model),
                f"{normalized_base_url}::{provider}::{model}" if provider else "",
                model,
                model.lower(),
            ]
            for key in candidates:
                if not key:
                    continue
                value = _positive_int(model_limits.get(key))
                if value:
                    return value
        return self.model_limit(model)

    def _provider_limit(self, base_url: str, provider_key: str, provider_name: str | None, limits: dict[str, Any] | None = None) -> int:
        provider_limits = limits.get("provider_limits") if isinstance(limits, dict) else None
        if isinstance(provider_limits, dict):
            normalized_base_url = base_url.rstrip("/")
            candidates = [provider_key, provider_key.lower(), normalized_base_url, normalized_base_url.lower()]
            if provider_name:
                candidates.extend([provider_name, provider_name.lower()])
            for key in candidates:
                value = _positive_int(provider_limits.get(key))
                if value:
                    return value
        value = _positive_int(limits.get("default_provider_limit") if isinstance(limits, dict) else None)
        return value or 100_000

    async def _wait_for_rpm_slot(self, key: str, rpm: int) -> None:
        if rpm <= 0:
            return
        while True:
            async with self._rpm_lock:
                now = time.monotonic()
                bucket = self._request_times_by_key.setdefault(key, deque())
                while bucket and now - bucket[0] >= 60:
                    bucket.popleft()
                if len(bucket) < rpm:
                    bucket.append(now)
                    return
                wait_for = max(0.05, 60 - (now - bucket[0]))
            await asyncio.sleep(min(wait_for, 5.0))


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _is_length_finish_reason(reason: str) -> bool:
    normalized = str(reason or "").strip().lower()
    return normalized in {"length", "max_tokens", "token_limit", "max_output_tokens"}


provider = OpenAICompatibleProvider()
