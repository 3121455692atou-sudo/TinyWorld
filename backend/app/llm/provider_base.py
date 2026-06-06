from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class LLMResult:
    raw_text: str
    parsed_object: Any | None
    token_usage: dict[str, Any]
    latency_ms: int
    provider_name: str
    error: str | None = None


class LLMProvider(Protocol):
    async def complete_text(
        self,
        *,
        model_alias: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        retry_count: int = 2,
        retry_interval_ms: int = 1500,
        request_timeout_ms: int = 300_000,
        rpm: int = 0,
    ) -> LLMResult:
        ...
