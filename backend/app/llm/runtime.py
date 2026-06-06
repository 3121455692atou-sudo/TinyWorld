from __future__ import annotations

from typing import Any


DEFAULT_LLM_RETRY_COUNT = 2
DEFAULT_LLM_RETRY_INTERVAL_MS = 1500
DEFAULT_LLM_REQUEST_TIMEOUT_MS = 300_000
DEFAULT_LLM_RPM = 0
MAX_LLM_RETRY_COUNT = 100_000
MAX_LLM_RETRY_INTERVAL_MS = 21_600_000
MAX_LLM_REQUEST_TIMEOUT_MS = 86_400_000
MAX_LLM_RPM = 100_000
DEFAULT_LLM_TEMPERATURE = 0.7
DEFAULT_LLM_TOP_P = 1.0
DEFAULT_LLM_STREAM = False
DEFAULT_LLM_MAX_TOKENS = 0
DEFAULT_LLM_PRESENCE_PENALTY = 0.0
DEFAULT_LLM_FREQUENCY_PENALTY = 0.0


def normalize_llm_runtime(
    raw: dict[str, Any] | None = None,
    *,
    retry_count: Any = None,
    retry_interval_ms: Any = None,
    request_timeout_ms: Any = None,
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
        "request_timeout_ms": _int_in_range(
            request_timeout_ms if request_timeout_ms is not None else data.get("request_timeout_ms"),
            0,
            MAX_LLM_REQUEST_TIMEOUT_MS,
            DEFAULT_LLM_REQUEST_TIMEOUT_MS,
        ),
        "rpm": _int_in_range(rpm if rpm is not None else data.get("rpm"), 0, MAX_LLM_RPM, DEFAULT_LLM_RPM),
    }


def llm_runtime_kwargs(raw: dict[str, Any] | None = None) -> dict[str, int]:
    runtime = normalize_llm_runtime(raw)
    return {
        "retry_count": runtime["retry_count"],
        "retry_interval_ms": runtime["retry_interval_ms"],
        "request_timeout_ms": runtime["request_timeout_ms"],
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


def normalize_llm_generation(
    raw: dict[str, Any] | None = None,
    *,
    stream: Any = None,
    temperature: Any = None,
    top_p: Any = None,
    max_tokens: Any = None,
    presence_penalty: Any = None,
    frequency_penalty: Any = None,
) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "stream": bool(stream if stream is not None else data.get("stream", DEFAULT_LLM_STREAM)),
        "temperature": _float_in_range(temperature if temperature is not None else data.get("temperature"), 0.0, 2.0, DEFAULT_LLM_TEMPERATURE),
        "top_p": _float_in_range(top_p if top_p is not None else data.get("top_p"), 0.0, 1.0, DEFAULT_LLM_TOP_P),
        "max_tokens": _int_in_range(max_tokens if max_tokens is not None else data.get("max_tokens"), 0, 200_000, DEFAULT_LLM_MAX_TOKENS),
        "presence_penalty": _float_in_range(presence_penalty if presence_penalty is not None else data.get("presence_penalty"), -2.0, 2.0, DEFAULT_LLM_PRESENCE_PENALTY),
        "frequency_penalty": _float_in_range(frequency_penalty if frequency_penalty is not None else data.get("frequency_penalty"), -2.0, 2.0, DEFAULT_LLM_FREQUENCY_PENALTY),
    }


def llm_generation_kwargs(raw: dict[str, Any] | None = None, *, default_temperature: float = DEFAULT_LLM_TEMPERATURE) -> dict[str, Any]:
    generation = normalize_llm_generation(raw, temperature=(raw or {}).get("temperature") if isinstance(raw, dict) and "temperature" in raw else default_temperature)
    result: dict[str, Any] = {
        "stream": generation["stream"],
        "temperature": generation["temperature"],
        "top_p": generation["top_p"],
        "presence_penalty": generation["presence_penalty"],
        "frequency_penalty": generation["frequency_penalty"],
    }
    if generation["max_tokens"] > 0:
        result["max_tokens"] = generation["max_tokens"]
    return result


def agent_llm_generation(agent: Any, world: Any | None = None, *, default_temperature: float = DEFAULT_LLM_TEMPERATURE) -> dict[str, Any]:
    world_settings = getattr(world, "settings_json", None) if world is not None else None
    world_generation = world_settings.get("llm_generation") if isinstance(world_settings, dict) and isinstance(world_settings.get("llm_generation"), dict) else {}
    learning = getattr(agent, "tool_learning_json", None)
    agent_generation = learning.get("llm_generation") if isinstance(learning, dict) and isinstance(learning.get("llm_generation"), dict) else {}
    merged = {**world_generation, **agent_generation}
    if "temperature" not in merged:
        merged["temperature"] = default_temperature
    return normalize_llm_generation(merged)


def _float_in_range(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))
