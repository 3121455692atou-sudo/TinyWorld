from __future__ import annotations

from typing import Any


DEFAULT_LLM_RETRY_COUNT = 2
DEFAULT_LLM_RETRY_INTERVAL_MS = 1500
DEFAULT_LLM_RPM = 0
MAX_LLM_RETRY_COUNT = 100_000
MAX_LLM_RETRY_INTERVAL_MS = 21_600_000
MAX_LLM_RPM = 100_000


def normalize_llm_runtime(
    raw: dict[str, Any] | None = None,
    *,
    retry_count: Any = None,
    retry_interval_ms: Any = None,
    rpm: Any = None,
) -> dict[str, int]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "retry_count": _int_in_range(
            retry_count if retry_count is not None else data.get("retry_count"),
            0,
            MAX_LLM_RETRY_COUNT,
            DEFAULT_LLM_RETRY_COUNT,
        ),
        "retry_interval_ms": _int_in_range(
            retry_interval_ms if retry_interval_ms is not None else data.get("retry_interval_ms"),
            0,
            MAX_LLM_RETRY_INTERVAL_MS,
            DEFAULT_LLM_RETRY_INTERVAL_MS,
        ),
        "rpm": _int_in_range(rpm if rpm is not None else data.get("rpm"), 0, MAX_LLM_RPM, DEFAULT_LLM_RPM),
    }


def llm_runtime_kwargs(raw: dict[str, Any] | None = None) -> dict[str, int]:
    runtime = normalize_llm_runtime(raw)
    return {
        "retry_count": runtime["retry_count"],
        "retry_interval_ms": runtime["retry_interval_ms"],
        "rpm": runtime["rpm"],
    }


def agent_llm_runtime(agent: Any) -> dict[str, int]:
    learning = getattr(agent, "tool_learning_json", None)
    raw = learning.get("llm_runtime") if isinstance(learning, dict) else None
    return normalize_llm_runtime(raw if isinstance(raw, dict) else None)


def _int_in_range(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))
