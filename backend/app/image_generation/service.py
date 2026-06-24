from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import zipfile
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.websocket import manager
from app.core.clock import format_world_time
from app.core.database import SessionLocal
from app.core.models import Agent, Event, Location, NarratorRun, World
from app.events.event_store import create_event
from app.llm.language import normalize_language, world_language
from app.llm.openai_compatible import provider
from app.llm.runtime import llm_generation_kwargs, llm_runtime_kwargs, normalize_llm_generation, normalize_llm_runtime
from app.storage.images import store_image_data_url


IMAGE_PROVIDER_TYPES = {"novelai", "comfyui", "sdxl", "anima"}
IMAGE_DISPLAY_MODES = {"placeholder", "wait"}
IMAGE_SOURCE_MODES = {"narration", "auto_summary"}
IMAGE_PROMPT_LLM_MODES = {"narrator", "custom"}
IMAGE_AUTO_FREQUENCIES = {"low", "normal", "high"}
IMAGE_PROMPT_STYLES = {
    "auto",
    "novelai",
    "sdxl",
    "flux",
    "pony",
    "anima",
    "danbooru",
    "illustrious",
    "stable_diffusion",
    "midjourney",
    "dalle",
    "custom",
}
MAX_IMAGE_PROMPT_NAMED_CHARACTERS = 5

NOVELAI_MODEL_OPTIONS = {
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-full",
    "nai-diffusion-4-curated-preview",
    "nai-diffusion-3",
}
NOVELAI_SAMPLER_OPTIONS = {
    "k_euler",
    "k_euler_ancestral",
    "k_dpmpp_2s_ancestral",
    "k_dpmpp_2m",
    "k_dpmpp_sde",
    "k_dpmpp_2m_sde",
    "ddim",
}
NOVELAI_RESOLUTION_OPTIONS = {
    (832, 1216),
    (1216, 832),
    (1024, 1024),
    (1024, 1536),
    (1536, 1024),
    (1472, 1472),
}

NOVELAI_DEFAULT_STYLE_PROMPT = (
    "best quality, amazing quality, very aesthetic, absurdres, newest, "
    "anime illustration, crisp lineart, highly detailed eyes, cinematic lighting, "
    "depth of field, soft shading, warm lighting, delicate face, detailed eyes"
)
NOVELAI_DEFAULT_NEGATIVE_PROMPT = (
    "lowres, worst quality, bad quality, normal quality, bad anatomy, bad hands, "
    "mutated hands, malformed hands, poorly drawn hands, extra hands, missing hands, "
    "fused fingers, webbed fingers, extra fingers, missing fingers, malformed fingers, "
    "mutated fingers, bad fingers, extra digits, fewer digits, long fingers, broken fingers, "
    "extra arms, missing arms, extra limbs, malformed limbs, disembodied limb, long neck, "
    "bad face, deformed, blurry, jpeg artifacts, watermark, signature, text, logo, "
    "multiple views, comic, panels"
)

_IMAGE_GENERATION_SEMAPHORE = asyncio.Semaphore(1)
_IMAGE_GENERATION_TASKS: dict[tuple[str, int], asyncio.Task] = {}

IMAGE_EVENT_CONFIG_SNAPSHOT_FIELDS = (
    "provider_type",
    "prompt_style",
    "base_url",
    "endpoint_path",
    "model_name",
    "model_options",
    "image_retry_count",
    "request_timeout_seconds",
    "comfyui_timeout_seconds",
    "custom_headers_json",
    "request_template_json",
    "workflow_json",
    "width",
    "height",
    "steps",
    "cfg_scale",
    "sampler",
    "seed",
    "nai_action",
    "nai_image_format",
    "nai_n_samples",
    "nai_uc_preset",
    "nai_quality_toggle",
    "nai_params_version",
    "nai_cfg_rescale",
    "nai_reference_strength",
    "nai_reference_information_extracted",
    "nai_strength",
    "nai_noise",
    "nai_sm_dyn",
    "nai_dynamic_thresholding",
    "nai_add_original_image",
    "nai_params_json",
)


def _image_config_snapshot(image_config: dict[str, Any]) -> dict[str, Any]:
    return {key: image_config.get(key) for key in IMAGE_EVENT_CONFIG_SNAPSHOT_FIELDS if key in image_config}


DEFAULT_IMAGE_GENERATION_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "source_mode": "narration",
    "provider_type": "sdxl",
    "prompt_style": "auto",
    "custom_prompt_style": "",
    "prompt_llm_mode": "narrator",
    "prompt_llm_provider_id": "",
    "prompt_llm_provider_name": "",
    "prompt_llm_base_url": "",
    "prompt_llm_api_key": "",
    "prompt_llm_model_name": "",
    "prompt_llm_system_prompt": "",
    "prompt_llm_generation": normalize_llm_generation({"temperature": 0.35, "max_tokens": 1600}),
    **{f"prompt_llm_{key}": value for key, value in normalize_llm_runtime().items()},
    "auto_frequency": "normal",
    "display_mode": "placeholder",
    "base_url": "",
    "endpoint_path": "",
    "api_key": "",
    "model_name": "",
    "model_options": [],
    "image_retry_count": 0,
    "request_timeout_seconds": 300,
    "comfyui_timeout_seconds": 0,
    "use_agent_appearance": True,
    "reference_avatar_images": False,
    "reference_standing_images": False,
    "style_prompt": "",
    "negative_prompt": "",
    "request_template_json": "",
    "custom_headers_json": "",
    "nai_action": "generate",
    "nai_image_format": "png",
    "nai_n_samples": 1,
    "nai_uc_preset": 0,
    "nai_quality_toggle": True,
    "nai_params_version": 3,
    "nai_cfg_rescale": 0.0,
    "nai_sm": False,
    "nai_sm_dyn": False,
    "nai_dynamic_thresholding": False,
    "nai_reference_strength": 0.45,
    "nai_reference_information_extracted": 1.0,
    "nai_strength": 0.35,
    "nai_noise": 0.0,
    "nai_add_original_image": False,
    "nai_params_json": "",
    "width": 1024,
    "height": 1024,
    "steps": 28,
    "cfg_scale": 7.0,
    "sampler": "",
    "seed": -1,
    "workflow_json": "",
    "agent_aliases": {},
}


IMAGE_TEXT_FIELDS: list[tuple[str, str, int]] = [
    ("base_url", "baseUrl", 500),
    ("endpoint_path", "endpointPath", 500),
    ("model_name", "modelName", 200),
    ("style_prompt", "stylePrompt", 4000),
    ("custom_prompt_style", "customPromptStyle", 4000),
    ("negative_prompt", "negativePrompt", 4000),
    ("request_template_json", "requestTemplateJson", 80_000),
    ("custom_headers_json", "customHeadersJson", 20_000),
    ("nai_action", "naiAction", 60),
    ("nai_image_format", "naiImageFormat", 20),
    ("nai_params_json", "naiParamsJson", 80_000),
    ("sampler", "sampler", 120),
    ("workflow_json", "workflowJson", 80_000),
    ("prompt_llm_provider_id", "promptLlmProviderId", 80),
    ("prompt_llm_provider_name", "promptLlmProviderName", 120),
    ("prompt_llm_base_url", "promptLlmBaseUrl", 500),
    ("prompt_llm_model_name", "promptLlmModelName", 200),
    ("prompt_llm_system_prompt", "promptLlmSystemPrompt", 4000),
]


def _raw_config_value(data: dict[str, Any], key: str, camel_key: str) -> Any:
    if key in data:
        return data.get(key)
    if camel_key in data:
        return data.get(camel_key)
    return None


def _clean_optional_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "null"} else text[:limit]


def normalize_image_generation_settings(raw: dict[str, Any] | None, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    previous = existing if isinstance(existing, dict) else {}
    result = {
        key: dict(value) if isinstance(value, dict) else list(value) if isinstance(value, list) else value
        for key, value in DEFAULT_IMAGE_GENERATION_SETTINGS.items()
    }
    result.update({key: previous[key] for key in result if key in previous})
    if "enabled" in data:
        result["enabled"] = bool(data.get("enabled"))
    source_mode = str(data.get("source_mode") or data.get("sourceMode") or result["source_mode"]).strip().lower()
    result["source_mode"] = source_mode if source_mode in IMAGE_SOURCE_MODES else "narration"
    provider_type = str(data.get("provider_type") or data.get("providerType") or result["provider_type"]).strip().lower()
    result["provider_type"] = provider_type if provider_type in IMAGE_PROVIDER_TYPES else "sdxl"
    prompt_style = str(data.get("prompt_style") or data.get("promptStyle") or result["prompt_style"]).strip().lower()
    result["prompt_style"] = prompt_style if prompt_style in IMAGE_PROMPT_STYLES else "auto"
    if result["provider_type"] == "novelai":
        result["prompt_style"] = "novelai"
    prompt_llm_mode = str(data.get("prompt_llm_mode") or data.get("promptLlmMode") or result["prompt_llm_mode"]).strip().lower()
    result["prompt_llm_mode"] = prompt_llm_mode if prompt_llm_mode in IMAGE_PROMPT_LLM_MODES else "narrator"
    auto_frequency = str(data.get("auto_frequency") or data.get("autoFrequency") or result["auto_frequency"]).strip().lower()
    result["auto_frequency"] = auto_frequency if auto_frequency in IMAGE_AUTO_FREQUENCIES else "normal"
    display_mode = str(data.get("display_mode") or data.get("displayMode") or result["display_mode"]).strip().lower()
    result["display_mode"] = display_mode if display_mode in IMAGE_DISPLAY_MODES else "placeholder"
    for key, camel_key, limit in IMAGE_TEXT_FIELDS:
        if key in data or camel_key in data:
            result[key] = _clean_optional_text(_raw_config_value(data, key, camel_key), limit)
    if "api_key" in data or "apiKey" in data:
        value = _clean_optional_text(_raw_config_value(data, "api_key", "apiKey"), 4000)
        if value == "***" or (not value and previous.get("api_key")):
            result["api_key"] = str(previous.get("api_key") or "")
        else:
            result["api_key"] = value[:4000]
    if "prompt_llm_api_key" in data or "promptLlmApiKey" in data:
        value = _clean_optional_text(_raw_config_value(data, "prompt_llm_api_key", "promptLlmApiKey"), 4000)
        if value == "***" or (not value and previous.get("prompt_llm_api_key")):
            result["prompt_llm_api_key"] = str(previous.get("prompt_llm_api_key") or "")
        else:
            result["prompt_llm_api_key"] = value[:4000]
    for key, minimum, maximum, fallback in [
        ("width", 256, 2048, 1024),
        ("height", 256, 2048, 1024),
        ("steps", 1, 150, 28),
        ("seed", -1, 2_147_483_647, -1),
        ("image_retry_count", 0, 100, 0),
        ("request_timeout_seconds", 0, 86_400, 300),
        ("comfyui_timeout_seconds", 0, 86_400, 0),
    ]:
        camel_key = "".join([key.split("_")[0], *[part.capitalize() for part in key.split("_")[1:]]])
        if key in data or camel_key in data:
            result[key] = _safe_int(_raw_config_value(data, key, camel_key), minimum, maximum, int(result.get(key) if result.get(key) is not None else fallback))
    if result["provider_type"] == "novelai":
        if str(result.get("model_name") or "").strip() not in NOVELAI_MODEL_OPTIONS:
            result["model_name"] = "nai-diffusion-4-5-full"
        if str(result.get("sampler") or "").strip() not in NOVELAI_SAMPLER_OPTIONS:
            result["sampler"] = "k_euler_ancestral"
        size = (int(result.get("width") or 0), int(result.get("height") or 0))
        if size not in NOVELAI_RESOLUTION_OPTIONS:
            result["width"], result["height"] = 832, 1216
    if "cfg_scale" in data or "cfgScale" in data:
        result["cfg_scale"] = _safe_float(data.get("cfg_scale") if "cfg_scale" in data else data.get("cfgScale"), 1.0, 30.0, float(result.get("cfg_scale") or 7.0))
    for key, minimum, maximum, fallback in [
        ("nai_n_samples", 1, 4, 1),
        ("nai_uc_preset", 0, 10, 0),
        ("nai_params_version", 1, 10, 3),
    ]:
        camel_key = "".join([key.split("_")[0], *[part.capitalize() for part in key.split("_")[1:]]])
        if key in data or camel_key in data:
            result[key] = _safe_int(_raw_config_value(data, key, camel_key), minimum, maximum, int(result.get(key) or fallback))
    for key, minimum, maximum, fallback in [
        ("nai_cfg_rescale", 0.0, 20.0, 0.0),
        ("nai_reference_strength", 0.0, 1.0, 0.45),
        ("nai_reference_information_extracted", 0.0, 1.0, 1.0),
        ("nai_strength", 0.0, 1.0, 0.35),
        ("nai_noise", 0.0, 1.0, 0.0),
    ]:
        camel_key = "".join([key.split("_")[0], *[part.capitalize() for part in key.split("_")[1:]]])
        if key in data or camel_key in data:
            result[key] = _safe_float(_raw_config_value(data, key, camel_key), minimum, maximum, float(result.get(key) or fallback))
    for key, camel_key in [
        ("use_agent_appearance", "useAgentAppearance"),
        ("reference_avatar_images", "referenceAvatarImages"),
        ("reference_standing_images", "referenceStandingImages"),
        ("nai_quality_toggle", "naiQualityToggle"),
        ("nai_sm", "naiSm"),
        ("nai_sm_dyn", "naiSmDyn"),
        ("nai_dynamic_thresholding", "naiDynamicThresholding"),
        ("nai_add_original_image", "naiAddOriginalImage"),
    ]:
        if key in data or camel_key in data:
            result[key] = bool(_raw_config_value(data, key, camel_key))
    model_options = data.get("model_options") if "model_options" in data else data.get("modelOptions")
    if isinstance(model_options, list):
        seen_models: set[str] = set()
        result["model_options"] = []
        for item in model_options[:500]:
            model = str(item or "").strip()[:200]
            if model and model not in seen_models:
                seen_models.add(model)
                result["model_options"].append(model)
    elif not isinstance(result.get("model_options"), list):
        result["model_options"] = []
    prompt_runtime = normalize_llm_runtime(
        {
            "retry_count": data.get("prompt_llm_retry_count", data.get("promptLlmRetryCount", result.get("prompt_llm_retry_count"))),
            "retry_interval_ms": data.get("prompt_llm_retry_interval_ms", data.get("promptLlmRetryIntervalMs", result.get("prompt_llm_retry_interval_ms"))),
            "request_timeout_ms": data.get("prompt_llm_request_timeout_ms", data.get("promptLlmRequestTimeoutMs", result.get("prompt_llm_request_timeout_ms"))),
            "rpm": data.get("prompt_llm_rpm", data.get("promptLlmRpm", result.get("prompt_llm_rpm"))),
        }
    )
    result.update({f"prompt_llm_{key}": value for key, value in prompt_runtime.items()})
    prompt_generation = data.get("prompt_llm_generation") if "prompt_llm_generation" in data else data.get("promptLlmGeneration")
    if isinstance(prompt_generation, dict):
        result["prompt_llm_generation"] = normalize_llm_generation(prompt_generation, temperature=prompt_generation.get("temperature", 0.35))
    elif not isinstance(result.get("prompt_llm_generation"), dict):
        result["prompt_llm_generation"] = normalize_llm_generation({"temperature": 0.35, "max_tokens": 1600})
    aliases = data.get("agent_aliases") if "agent_aliases" in data else data.get("agentAliases")
    if isinstance(aliases, dict):
        result["agent_aliases"] = {
            str(agent_id).strip()[:80]: str(alias).strip()[:120]
            for agent_id, alias in aliases.items()
            if str(agent_id).strip() and str(alias).strip()
        }
    elif not isinstance(result.get("agent_aliases"), dict):
        result["agent_aliases"] = {}
    for key, _camel_key, limit in IMAGE_TEXT_FIELDS:
        result[key] = _clean_optional_text(result.get(key), limit)
    result["api_key"] = _clean_optional_text(result.get("api_key"), 4000)
    result["prompt_llm_api_key"] = _clean_optional_text(result.get("prompt_llm_api_key"), 4000)
    return result


def image_generation_enabled(world: World) -> bool:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    return bool(config.get("enabled"))


def image_generation_display_mode(world: World) -> str:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    return str(config.get("display_mode") or "placeholder")


def schedule_image_generation(
    session: Session,
    world: World,
    *,
    narrator_run: NarratorRun,
    narration_event: Event,
    source_events: list[Event],
) -> list[int]:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    if not config.get("enabled") or config.get("source_mode") != "narration":
        return []
    image_event = _create_pending_image_event(
        session,
        world=world,
        importance=max(20, min(80, int(narrator_run.importance or 40))),
        title=narrator_run.summary_title or "画面",
        payload={
            "source_mode": "narration",
            "narrator_run_id": narrator_run.narrator_run_id,
            "narration_event_id": narration_event.event_id,
            "source_event_ids": [event.event_id for event in source_events],
            "summary_title": narrator_run.summary_title,
            "narration": narrator_run.narration,
        },
    )
    image_event.world_time = narration_event.world_time
    image_event.payload = {
        **dict(image_event.payload or {}),
        "provider_type": config["provider_type"],
        "prompt_style": _resolved_prompt_style(config),
        "display_mode": config["display_mode"],
    }
    session.flush()
    _schedule_background_generation(world.world_id, image_event.event_id)
    return [image_event.event_id]


def maybe_schedule_auto_image_generation(session: Session, world: World, input_event_ids: list[int], *, force: bool = False) -> list[int]:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    if not config.get("enabled") or config.get("source_mode") != "auto_summary":
        return []
    source_events = [session.get(Event, event_id) for event_id in input_event_ids]
    source_events = [event for event in source_events if event and event.event_type not in {"image_generation", "narration"}]
    if not source_events:
        return []
    if not force and not _auto_image_frequency_allows(session, world, config):
        return []
    max_importance = max(int(event.importance or 0) for event in source_events)
    if force and max_importance < 45 and not _auto_image_frequency_allows(session, world, config, relaxed=True):
        return []
    image_event = _create_pending_image_event(
        session,
        world=world,
        importance=max(20, min(80, max_importance or 40)),
        title="当前画面",
        payload={
            "source_mode": "auto_summary",
            "source_event_ids": [event.event_id for event in source_events[-16:]],
            "summary_title": "当前画面",
            "narration": "",
        },
    )
    _schedule_background_generation(world.world_id, image_event.event_id)
    return [image_event.event_id]


def create_manual_image_generation(session: Session, world: World) -> list[int]:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    if not config.get("enabled"):
        return []
    if config.get("source_mode") == "narration":
        narration_event = (
            session.execute(
                select(Event)
                .where(Event.world_id == world.world_id, Event.event_type == "narration")
                .order_by(Event.world_time.desc(), Event.event_id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not narration_event:
            return []
        payload = dict(narration_event.payload or {})
        source_ids = [int(item) for item in payload.get("source_event_ids") or [] if str(item).isdigit()]
        narrator_run_id = payload.get("narrator_run_id")
        if not source_ids and narrator_run_id:
            run = session.get(NarratorRun, int(narrator_run_id))
            source_ids = [int(item) for item in (run.input_event_ids_json or []) if str(item).isdigit()] if run else []
        title = str(payload.get("summary_title") or "画面").strip() or "画面"
        image_event = _create_pending_image_event(
            session,
            world=world,
            importance=max(20, min(80, int(narration_event.importance or 40))),
            title=title,
            payload={
                "source_mode": "narration",
                "manual": True,
                "narrator_run_id": narrator_run_id,
                "narration_event_id": narration_event.event_id,
                "source_event_ids": source_ids,
                "summary_title": title,
                "narration": str(payload.get("narration") or narration_event.viewer_text or ""),
            },
        )
        image_event.world_time = narration_event.world_time
    else:
        events = _recent_source_events(session, world, limit=16)
        if not events:
            return []
        image_event = _create_pending_image_event(
            session,
            world=world,
            importance=max(20, min(80, max(int(event.importance or 0) for event in events) or 40)),
            title="当前画面",
            payload={
                "source_mode": "auto_summary",
                "manual": True,
                "source_event_ids": [event.event_id for event in events],
                "summary_title": "当前画面",
                "narration": "",
            },
        )
    image_event.payload = {
        **dict(image_event.payload or {}),
        "provider_type": config["provider_type"],
        "prompt_style": _resolved_prompt_style(config),
        "display_mode": config["display_mode"],
    }
    session.flush()
    _schedule_background_generation(world.world_id, image_event.event_id)
    return [image_event.event_id]


def create_prompt_image_generation(session: Session, world: World, *, prompt: str, negative_prompt: str = "", title: str = "") -> list[int]:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    clean_prompt = str(prompt or "").strip()
    if not config.get("enabled") or not clean_prompt:
        return []
    latest_event = (
        session.execute(
            select(Event)
            .where(Event.world_id == world.world_id)
            .order_by(Event.world_time.desc(), Event.event_id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    summary_title = str(title or "").strip()[:80] or "手动提示词"
    image_event = _create_pending_image_event(
        session,
        world=world,
        importance=40,
        title=summary_title,
        payload={
            "source_mode": "manual_prompt",
            "manual": True,
            "source_event_ids": [latest_event.event_id] if latest_event else [],
            "summary_title": summary_title,
            "narration": "",
            "manual_prompt": clean_prompt[:8000],
            "manual_negative_prompt": str(negative_prompt or "").strip()[:3000],
            "display_mode": "placeholder",
        },
    )
    if latest_event:
        image_event.world_time = max(int(world.current_world_time_minutes or 0), int(latest_event.world_time or 0))
    image_event.payload = {
        **dict(image_event.payload or {}),
        "provider_type": config["provider_type"],
        "prompt_style": _resolved_prompt_style(config),
        "display_mode": "placeholder",
    }
    session.flush()
    _schedule_background_generation(world.world_id, image_event.event_id)
    return [image_event.event_id]


def _create_pending_image_event(session: Session, *, world: World, importance: int, title: str, payload: dict[str, Any]) -> Event:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = normalize_image_generation_settings(settings_json.get("image_generation"))
    return create_event(
        session,
        world=world,
        event_type="image_generation",
        visibility_scope="viewer_only",
        importance=importance,
        color_class="image",
        viewer_text=f"【生图】{title or '画面'} 正在生成。",
        payload={
            "status": "pending",
            "provider_type": config["provider_type"],
            "prompt_style": _resolved_prompt_style(config),
            "display_mode": config["display_mode"],
            **payload,
        },
        no_state_changed=True,
    )


def _schedule_background_generation(world_id: str, image_event_id: int) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    key = (world_id, int(image_event_id))
    existing = _IMAGE_GENERATION_TASKS.get(key)
    if existing and not existing.done():
        return
    task = loop.create_task(_generate_image_background(world_id, image_event_id))
    _IMAGE_GENERATION_TASKS[key] = task
    task.add_done_callback(lambda _completed, task_key=key: _IMAGE_GENERATION_TASKS.pop(task_key, None))


def resume_pending_image_generations(limit: int = 100) -> int:
    scheduled = 0
    with SessionLocal() as session:
        events = list(
            session.execute(
                select(Event)
                .where(
                    Event.event_type == "image_generation",
                    func.json_extract(Event.payload, "$.status").in_(["pending", "running"]),
                )
                .order_by(Event.event_id.asc())
                .limit(limit)
            ).scalars()
        )
        for event in events:
            payload = dict(event.payload or {})
            world = session.get(World, event.world_id) if event.world_id else None
            settings_json = world.settings_json if world and isinstance(world.settings_json, dict) else {}
            current_config = normalize_image_generation_settings(settings_json.get("image_generation"))
            if not current_config.get("enabled") or payload.get("provider_type") != current_config.get("provider_type"):
                payload["status"] = "failed"
                payload["error"] = "已取消：当前生图配置已变更，旧任务不再自动恢复"
                event.payload = payload
                continue
            if payload.get("status") == "running":
                payload["status"] = "pending"
                payload["error"] = None
                event.payload = payload
        session.commit()
        for event in events:
            payload = dict(event.payload or {})
            if event.world_id and payload.get("status") in {"pending", "running"}:
                _schedule_background_generation(event.world_id, event.event_id)
                scheduled += 1
    return scheduled


def _recent_source_events(session: Session, world: World, *, limit: int) -> list[Event]:
    return list(
        session.execute(
            select(Event)
            .where(
                Event.world_id == world.world_id,
                Event.event_type.not_in(["image_generation", "narration", "narrator_failed", "tool_failed"]),
            )
            .order_by(Event.world_time.desc(), Event.event_id.desc())
            .limit(limit)
        ).scalars()
    )[::-1]


def _auto_image_frequency_allows(session: Session, world: World, config: dict[str, Any], *, relaxed: bool = False) -> bool:
    last_image = (
        session.execute(
            select(Event)
            .where(Event.world_id == world.world_id, Event.event_type == "image_generation")
            .order_by(Event.world_time.desc(), Event.event_id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    threshold = {"low": 24, "normal": 14, "high": 8}.get(str(config.get("auto_frequency") or "normal"), 14)
    if relaxed:
        threshold = max(4, threshold // 2)
    stmt = select(func.count(Event.event_id)).where(
        Event.world_id == world.world_id,
        Event.importance >= 15,
        Event.event_type.not_in(["image_generation", "narration", "narrator_failed", "tool_failed"]),
    )
    if last_image:
        stmt = stmt.where(Event.event_id > last_image.event_id)
    return int(session.execute(stmt).scalar_one() or 0) >= threshold


async def _generate_image_background(world_id: str, image_event_id: int) -> None:
    await asyncio.sleep(0.2)
    async with _IMAGE_GENERATION_SEMAPHORE:
        for _ in range(40):
            try:
                with SessionLocal() as session:
                    image_event = session.get(Event, image_event_id)
                    world = session.get(World, world_id)
                    if image_event and world:
                        await _generate_image_with_session(session, world, image_event)
                        return
            except Exception:
                return
            await asyncio.sleep(0.5)


async def _generate_image_with_session(session: Session, world: World, image_event: Event) -> None:
    payload = dict(image_event.payload or {})
    if payload.get("status") not in {"pending", "running"}:
        return
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    image_config = normalize_image_generation_settings(settings_json.get("image_generation"))
    image_config = _image_config_for_event(image_config, payload)
    if not image_config.get("enabled"):
        image_event.payload = {**payload, "status": "skipped", "error": "image generation disabled"}
        session.commit()
        await _broadcast_image_update(world.world_id, image_event.event_id)
        return
    payload["status"] = "running"
    image_event.payload = payload
    session.commit()

    try:
        prompt, negative_prompt, prompt_debug = await _create_image_prompt(session, world, image_event, image_config)
        reference_images = _reference_images_for_event(session, world, image_event, image_config)
        image_event = session.get(Event, image_event.event_id)
        if not image_event:
            return
        image_event.payload = {
            **dict(image_event.payload or {}),
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            **_image_config_snapshot(image_config),
            **prompt_debug,
        }
        session.commit()
        image_event = session.get(Event, image_event.event_id)
        if not image_event or dict(image_event.payload or {}).get("status") == "canceled":
            return
        image_data_url = await _call_image_provider(image_config, prompt, negative_prompt, reference_images=reference_images)
        image_storage = store_image_data_url(image_data_url)
        image_event = session.get(Event, image_event.event_id)
        if not image_event:
            return
        if dict(image_event.payload or {}).get("status") == "canceled":
            return
        image_event.viewer_text = f"【生图】{payload.get('summary_title') or '画面'} 已生成。"
        image_event.agent_visible_text = image_event.viewer_text
        image_event.payload = {
            **dict(image_event.payload or {}),
            "status": "completed",
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            **_image_config_snapshot(image_config),
            **image_storage,
            "error": None,
        }
    except Exception as exc:
        image_event = session.get(Event, image_event.event_id)
        if not image_event:
            return
        error_text = str(exc).strip() or exc.__class__.__name__
        image_event.viewer_text = f"【生图】{payload.get('summary_title') or '画面'} 生成失败。"
        image_event.agent_visible_text = image_event.viewer_text
        image_event.payload = {
            **dict(image_event.payload or {}),
            "status": "failed",
            "error": error_text[:1000],
            "provider_error_body": _provider_error_body(exc),
        }
    session.commit()
    await _broadcast_image_update(world.world_id, image_event.event_id)


def _image_config_for_event(image_config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    overrides = payload.get("image_config_overrides")
    if not isinstance(overrides, dict) or not overrides:
        return image_config
    return normalize_image_generation_settings({**image_config, **_clean_image_config_overrides(overrides)}, existing=image_config)


def _clean_image_config_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    text_limits = {
        "provider_type": 40,
        "prompt_style": 60,
        "base_url": 500,
        "endpoint_path": 500,
        "api_key": 4000,
        "model_name": 200,
        "sampler": 120,
        "nai_action": 60,
        "nai_image_format": 20,
        "request_template_json": 80_000,
        "custom_headers_json": 20_000,
        "workflow_json": 80_000,
        "nai_params_json": 80_000,
    }
    for key, limit in text_limits.items():
        if key not in raw:
            continue
        value = raw.get(key)
        if isinstance(value, str):
            result[key] = value.strip()[:limit]
    numeric_bounds: dict[str, tuple[float, float, bool]] = {
        "width": (256, 2048, True),
        "height": (256, 2048, True),
        "steps": (1, 150, True),
        "cfg_scale": (0, 30, False),
        "seed": (-1, 2_147_483_647, True),
        "image_retry_count": (0, 100, True),
        "request_timeout_seconds": (0, 86_400, True),
        "comfyui_timeout_seconds": (0, 86_400, True),
        "nai_n_samples": (1, 4, True),
        "nai_uc_preset": (0, 10, True),
        "nai_params_version": (1, 10, True),
        "nai_cfg_rescale": (0, 20, False),
        "nai_reference_strength": (0, 1, False),
        "nai_reference_information_extracted": (0, 1, False),
        "nai_strength": (0, 1, False),
        "nai_noise": (0, 1, False),
    }
    for key, (minimum, maximum, as_int) in numeric_bounds.items():
        if key not in raw:
            continue
        try:
            value = float(raw.get(key))
        except (TypeError, ValueError):
            continue
        value = min(max(value, minimum), maximum)
        result[key] = int(round(value)) if as_int else value
    for key in ("nai_quality_toggle", "nai_sm_dyn", "nai_dynamic_thresholding", "nai_add_original_image"):
        if key in raw:
            result[key] = bool(raw.get(key))
    return result


async def _broadcast_image_update(world_id: str, event_id: int) -> None:
    try:
        await manager.broadcast(world_id, {"type": "image_generation_updated", "world_id": world_id, "event_id": event_id})
    except Exception:
        return


async def cancel_pending_image_generations(session: Session, world: World) -> int:
    """Cancel every still-pending/running image render for a world.

    Called when narrator image generation is switched off mid-run so already
    queued renders stop immediately instead of finishing after the toggle.
    """
    events = (
        session.execute(
            select(Event).where(
                Event.world_id == world.world_id,
                Event.event_type == "image_generation",
            )
        )
        .scalars()
        .all()
    )
    canceled = 0
    for event in events:
        status = str((event.payload or {}).get("status") or "")
        if status in {"pending", "running"}:
            await cancel_image_generation_event(session, world, event.event_id)
            canceled += 1
    return canceled


async def cancel_image_generation_event(session: Session, world: World, image_event_id: int) -> Event:
    image_event = session.get(Event, image_event_id)
    if not image_event or image_event.world_id != world.world_id or image_event.event_type != "image_generation":
        raise ValueError("image generation event not found")
    payload = dict(image_event.payload or {})
    status = str(payload.get("status") or "")
    if status not in {"pending", "running"}:
        return image_event
    payload["status"] = "canceled"
    payload["error"] = "已中断"
    task = _IMAGE_GENERATION_TASKS.pop((world.world_id, int(image_event_id)), None)
    if task and not task.done():
        task.cancel()
    image_event.viewer_text = f"【生图】{payload.get('summary_title') or '画面'} 已中断。"
    image_event.agent_visible_text = image_event.viewer_text
    image_event.payload = payload
    session.commit()
    await _interrupt_image_provider_if_needed(world, payload)
    await _broadcast_image_update(world.world_id, image_event.event_id)
    return image_event


async def rerun_image_generation_event(
    session: Session,
    world: World,
    image_event_id: int,
    *,
    prompt: str,
    negative_prompt: str,
    overrides: dict[str, Any] | None = None,
) -> Event:
    image_event = session.get(Event, image_event_id)
    if not image_event or image_event.world_id != world.world_id or image_event.event_type != "image_generation":
        raise ValueError("image generation event not found")
    task = _IMAGE_GENERATION_TASKS.pop((world.world_id, int(image_event_id)), None)
    if task and not task.done():
        task.cancel()
    payload = dict(image_event.payload or {})
    clean_prompt = str(prompt or "").strip()
    clean_negative = str(negative_prompt or "").strip()
    if not clean_prompt:
        clean_prompt = str(payload.get("prompt") or payload.get("manual_prompt") or "").strip()
    rerun_payload = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "status",
            "error",
            "provider_error_body",
            "image_data_url",
            "image_key",
            "image_url",
            "image_mime_type",
            "image_size_bytes",
            "image_sha256",
        }
    }
    rerun_payload.update(
        {
            "status": "pending",
            "rerun": True,
            "rerun_at": format_world_time(int(world.current_world_time_minutes or image_event.world_time or 0)),
            "manual_prompt": clean_prompt,
            "manual_negative_prompt": clean_negative,
            "prompt": clean_prompt,
            "negative_prompt": clean_negative,
            "image_config_overrides": _clean_image_config_overrides(overrides or {}),
        }
    )
    image_event.viewer_text = f"【生图】{rerun_payload.get('summary_title') or '画面'} 正在生成。"
    image_event.agent_visible_text = image_event.viewer_text
    image_event.payload = rerun_payload
    session.commit()
    _schedule_background_generation(world.world_id, image_event.event_id)
    await _broadcast_image_update(world.world_id, image_event.event_id)
    return image_event


async def _interrupt_image_provider_if_needed(world: World, payload: dict[str, Any]) -> None:
    provider_type = str(payload.get("provider_type") or "").strip().lower()
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    image_config = normalize_image_generation_settings(settings_json.get("image_generation"))
    if provider_type != "comfyui" and str(image_config.get("provider_type") or "") != "comfyui":
        return
    base_url = _base_url(image_config)
    if not base_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{base_url.rstrip('/')}/interrupt")
    except Exception:
        return


def _provider_error_body(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            return exc.response.text[:2000]
        except Exception:
            return ""
    return ""


async def _create_image_prompt(session: Session, world: World, image_event: Event, image_config: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    payload = dict(image_event.payload or {})
    source_ids = [int(item) for item in payload.get("source_event_ids") or [] if str(item).isdigit()]
    source_events = [session.get(Event, event_id) for event_id in source_ids]
    source_events = [event for event in source_events if event]
    agents = list(session.execute(select(Agent).where(Agent.world_id == world.world_id)).scalars())
    alias_lines = _agent_alias_lines(agents, image_config)
    source_lines = _source_event_lines(session, source_events[-12:])
    source_locations = _source_location_names(session, source_events[-12:])
    narration = str(payload.get("narration") or "").strip()
    language = world_language(world)
    provider_type = str(image_config.get("provider_type") or "sdxl")
    prompt_style = _resolved_prompt_style(image_config)
    custom_prompt_style = str(image_config.get("custom_prompt_style") or "").strip()
    style = str(image_config.get("style_prompt") or "").strip()
    negative_base = str(image_config.get("negative_prompt") or "").strip()
    if prompt_style == "novelai":
        style = style or NOVELAI_DEFAULT_STYLE_PROMPT
        negative_base = negative_base or NOVELAI_DEFAULT_NEGATIVE_PROMPT
    context_aliases = _image_context_aliases(source_events, narration, source_lines, agents, image_config)
    if payload.get("rerun") and str(payload.get("prompt") or "").strip():
        rerun_prompt = str(payload.get("prompt") or "").strip()
        rerun_negative = str(payload.get("negative_prompt") or "").strip()
        return (
            rerun_prompt,
            rerun_negative,
            {
                "prompt_generation_source": "rerun_manual",
                "prompt_content_raw": rerun_prompt[:6000],
                "prompt_content_cleaned": rerun_prompt[:6000],
                "prompt_llm_raw": "",
                "prompt_llm_error": "",
            },
        )
    manual_prompt = str(payload.get("manual_prompt") or "").strip()
    if manual_prompt:
        manual_negative = str(payload.get("manual_negative_prompt") or "").strip()
        return (
            _join_prompt(style, manual_prompt, prompt_style),
            _join_negative(negative_base, manual_negative),
            {
                "prompt_generation_source": "manual_prompt",
                "prompt_content_raw": manual_prompt[:6000],
                "prompt_content_cleaned": manual_prompt[:6000],
                "prompt_llm_raw": "",
                "prompt_llm_error": "",
            },
        )
    prompt_llm_config = _prompt_llm_config(world, image_config)
    system_prompt = _image_prompt_system(prompt_style, custom_prompt_style, language)
    if prompt_llm_config.get("system_prompt"):
        system_prompt += f"\nAdditional user instructions for image prompt writing: {prompt_llm_config['system_prompt']}"
    user_prompt = _image_prompt_user(
        provider_type=provider_type,
        prompt_style=prompt_style,
        custom_prompt_style=custom_prompt_style,
        source_lines=source_lines,
        source_locations=source_locations,
        narration=narration,
        alias_lines=alias_lines,
        style_prompt=style,
        negative_prompt=negative_base,
        language=language,
    )
    if not str(prompt_llm_config.get("model_name") or "").strip():
        fallback_prompt, fallback_negative = _fallback_prompt(prompt_style, narration, source_events, alias_lines, style, negative_base, source_locations)
        return (
            fallback_prompt,
            fallback_negative,
            {
                "prompt_generation_source": "fallback",
                "prompt_llm_raw": "",
                "prompt_content_raw": "",
                "prompt_content_cleaned": "",
                "prompt_llm_error": "prompt LLM model is not configured; refusing implicit model fallback",
                "prompt_llm_provider_name": str(prompt_llm_config.get("provider_name") or "")[:120],
                "prompt_llm_model_name": "",
            },
        )
    try:
        result = await provider.complete_text(
            model_alias="image_prompt",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_name=prompt_llm_config.get("model_name"),
            base_url=prompt_llm_config.get("base_url"),
            api_key=prompt_llm_config.get("api_key"),
            **llm_generation_kwargs(prompt_llm_config.get("llm_generation"), default_temperature=0.35),
            **llm_runtime_kwargs(normalize_llm_runtime(prompt_llm_config)),
        )
        raw_text = str(result.raw_text or "")
        if not result.error:
            parsed = _parse_prompt_result(raw_text)
            if parsed[0]:
                raw_content_prompt = parsed[0]
                should_strip_style_terms = prompt_style == "novelai" or bool(style)
                content_source = _strip_generated_style_terms(raw_content_prompt) if should_strip_style_terms else raw_content_prompt
                content_prompt = _replace_display_names_with_aliases(content_source, agents, image_config)
                if prompt_style == "novelai":
                    content_prompt = _clean_novelai_content_prompt(content_prompt, strip_style_terms=should_strip_style_terms)
                content_prompt = _enforce_image_character_aliases(content_prompt, context_aliases, agents, image_config, prompt_style)
                positive = _join_prompt(style, content_prompt, prompt_style)
                generated_negative = _strip_generated_style_terms(parsed[1]) if prompt_style == "novelai" else _clean_prompt_tag_list(parsed[1], limit=3000)
                negative = _join_negative(negative_base, _clean_prompt_tag_list(generated_negative, limit=3000))
                return (
                    positive,
                    negative,
                    {
                        "prompt_generation_source": "llm",
                        "prompt_llm_raw": raw_text[:6000],
                        "prompt_content_raw": raw_content_prompt[:6000],
                        "prompt_content_cleaned": content_prompt[:6000],
                        "prompt_llm_error": "",
                        "prompt_llm_provider_name": str(prompt_llm_config.get("provider_name") or "")[:120],
                        "prompt_llm_model_name": str(prompt_llm_config.get("model_name") or "")[:200],
                    },
                )
            fallback_reason = "prompt LLM response did not contain a usable POSITIVE line"
        else:
            fallback_reason = str(result.error)[:1000] or "prompt LLM returned an error"
        fallback_prompt, fallback_negative = _fallback_prompt(prompt_style, narration, source_events, alias_lines, style, negative_base, source_locations)
        return (
            fallback_prompt,
            fallback_negative,
            {
                "prompt_generation_source": "fallback",
                "prompt_llm_raw": raw_text[:6000],
                "prompt_content_raw": "",
                "prompt_content_cleaned": "",
                "prompt_llm_error": fallback_reason,
                "prompt_llm_provider_name": str(prompt_llm_config.get("provider_name") or "")[:120],
                "prompt_llm_model_name": str(prompt_llm_config.get("model_name") or "")[:200],
            },
        )
    except Exception as exc:
        fallback_reason = str(exc)[:1000] or exc.__class__.__name__
    fallback_prompt, fallback_negative = _fallback_prompt(prompt_style, narration, source_events, alias_lines, style, negative_base, source_locations)
    return (
        fallback_prompt,
        fallback_negative,
        {
            "prompt_generation_source": "fallback",
            "prompt_llm_raw": "",
            "prompt_content_raw": "",
            "prompt_content_cleaned": "",
            "prompt_llm_error": fallback_reason,
            "prompt_llm_provider_name": str(prompt_llm_config.get("provider_name") or "")[:120],
            "prompt_llm_model_name": str(prompt_llm_config.get("model_name") or "")[:200],
        },
    )


def _resolved_prompt_style(image_config: dict[str, Any]) -> str:
    prompt_style = str(image_config.get("prompt_style") or image_config.get("promptStyle") or "auto").strip().lower()
    if prompt_style in IMAGE_PROMPT_STYLES and prompt_style != "auto":
        return prompt_style
    provider_type = str(image_config.get("provider_type") or image_config.get("providerType") or "sdxl").strip().lower()
    if provider_type in {"novelai", "sdxl", "anima"}:
        return provider_type
    workflow_text = str(image_config.get("workflow_json") or image_config.get("workflowJson") or "").lower()
    for marker, inferred_style in [
        ("pony", "pony"),
        ("anima", "anima"),
        ("flux", "flux"),
        ("illustrious", "illustrious"),
        ("noobai", "danbooru"),
        ("nai-", "novelai"),
        ("novelai", "novelai"),
    ]:
        if marker in workflow_text:
            return inferred_style
    return "sdxl"


def _image_prompt_system(prompt_style: str, custom_prompt_style: str, language: str) -> str:
    english = normalize_language(language) == "en"
    if prompt_style == "novelai":
        return (
            "Convert the provided story into content tags for one image. You are not responsible for image quality, art style, medium, artist, year, rendering, or finish tags.\n"
            "\n"
            "Output exactly two lines in this strict format:\n"
            "POSITIVE=...\n"
            "NEGATIVE=...\n"
            "\n"
            "After POSITIVE= and NEGATIVE=, output only English comma-separated content tags. Do not explain, do not use Markdown, do not number anything, and do not add extra lines.\n"
            "Choose one moment that works best as a single illustration. Do not cram multiple consecutive actions, multiple camera shots, or before/after plot beats into one image.\n"
            "Do not invent new plot facts. Do not add details that are not provided by the story or character information.\n"
            "You may use appearance information supplied in the character drawing alias mapping. Apart from that, do not guess characters, outfits, props, locations, relationships, emotions, or body features.\n"
            "POSITIVE must contain only content: character aliases, character count, pose/action, expression, gaze, interaction, location, time of day if story-relevant, concrete props, camera relationship, and simple scene layout.\n"
            "NEGATIVE should normally be empty. Only use it for story-specific exclusions, not generic quality/style exclusions.\n"
            "Forbidden in both lines: quality tags, art-style tags, medium tags, artist tags, year/newest tags, resolution tags, rendering/detail tags, lighting-style tags, aesthetic tags, score/source tags, and generic bad-quality negatives.\n"
            "Forbidden examples include: best quality, masterpiece, amazing quality, very aesthetic, absurdres, newest, anime illustration, crisp lineart, detailed eyes, cinematic lighting, soft shading, depth of field, lowres, worst quality, bad anatomy, bad hands, blurry, watermark, text.\n"
            "\n"
            "Character mapping rules:\n"
            "If the input contains 'display name -> drawing alias', prompts must use only the drawing alias on the right.\n"
            "Never output the display name on the left.\n"
            "Do not translate character names.\n"
            "Do not guess official character tags that are not provided.\n"
            "If a character has no drawing alias, use only generic person tags such as 1girl, 1boy, woman, man.\n"
            "The character-count tag must match the named visible characters. If two named girls are visible, use 2girls instead of 1girl. Do not write a solo/1girl prompt and then put other named characters in the background.\n"
            "Never use vague multi-person tags such as multiple girls, several girls, multiple people, group, or crowd when named characters are visible. If named characters are visible, output the exact count tag and every visible character's drawing alias.\n"
            "Never include more than five visible named characters. If the story involves more than five people, choose a tighter moment with at most five visible named characters and use 5girls/5boys at most.\n"
            "\n"
            "Output should be concise, tag-like, and specific. Avoid long sentences, prose descriptions, and complete sentences. Do not use Chinese tags."
        )
    base = (
        "You are the narrator's image-prompt specialist. Convert the recent story into one image prompt. "
        "Do not invent new plot facts. When a character mapping is written as 'display name -> drawing alias', you must use only the drawing alias in prompts and must not output the display name. Output only POSITIVE= and NEGATIVE= lines."
        if english
        else "你是解说 AI 的生图提示词专员。把上方情节转换成一张图的提示词，不要编造新剧情。角色映射写成“显示名 -> 绘图名”时，提示词里必须只使用右侧绘图名，禁止输出左侧显示名。只输出 POSITIVE= 和 NEGATIVE= 两行。"
    )
    guidance = {
        "novelai": "NovelAI: use concise Danbooru-style comma-separated tags. Prefer character tags, outfit, pose, place, mood, lighting. Avoid long prose.",
        "sdxl": "SDXL: use descriptive English prompt phrases with clear subject, composition, action, location, lighting, mood, and style.",
        "flux": "Flux: use natural-language prompt sentences with clear subject, composition, action, environment, lighting, mood, and visual style. Avoid Pony score tags and dense booru-only tag lists.",
        "pony": "Pony v6/v7: use Pony tag style, beginning with score_9, score_8_up, score_7_up, source_anime. Use comma-separated tags, character tags, scene tags, and avoid prose.",
        "anima": "Anima / Pony v7: use Pony tag style, beginning with score_9, score_8_up, score_7_up, source_anime. Use comma-separated tags, character tags, scene tags, and avoid prose.",
        "danbooru": "Danbooru / Booru tags: use concise comma-separated tags. Prefer character tags, outfit tags, pose, expression, place, object, lighting, and quality tags. Avoid full prose sentences.",
        "illustrious": "Illustrious / NoobAI: use anime booru-style tags with quality tags, character tags, outfit, pose, expression, setting, lighting, and mood. Avoid Flux-style paragraphs.",
        "stable_diffusion": "Stable Diffusion 1.5 / classic SD: use concise comma-separated prompt phrases. Include subject, appearance, action, composition, background, lighting, and style; keep negatives explicit.",
        "midjourney": "Midjourney-style: use a compact natural-language art direction prompt with subject, action, scene, composition, lighting, mood, lens or art style. Keep negatives separate.",
        "dalle": "DALL-E-style: use plain natural-language image description. Be concrete about subjects, action, environment, composition, and lighting. Avoid model-specific tag syntax.",
    }
    if prompt_style == "custom" and custom_prompt_style:
        guidance_text = f"Custom prompt style instructions from the user: {custom_prompt_style}"
    else:
        guidance_text = guidance.get(prompt_style, guidance["sdxl"])
    return f"{base}\n{guidance_text}"


def _image_prompt_user(
    *,
    provider_type: str,
    prompt_style: str,
    custom_prompt_style: str,
    source_lines: str,
    source_locations: str,
    narration: str,
    alias_lines: str,
    style_prompt: str,
    negative_prompt: str,
    language: str,
) -> str:
    if normalize_language(language) == "en":
        return f"""
Provider type: {provider_type}
Prompt style: {prompt_style}
Custom prompt style instructions: {custom_prompt_style or "-"}
Fixed style/quality prompt is supplied separately by the system. Do not write any style/quality tags yourself: {style_prompt or "-"}
Base negative prompt is supplied separately by the system. Do not write generic quality negatives yourself: {negative_prompt or "-"}

Character drawing aliases:
{alias_lines or "-"}

Recent event excerpts:
{source_lines or "-"}

Narrator text:
{narration or "-"}

Write content tags for the most visually representative moment. Use aliases instead of display names when aliases exist. For NovelAI, write only content tags: characters, count, action, pose, expression, location, props, and scene relationship. Do not write quality/style/medium/year/artist/detail/lighting-finish tags.
Output:
POSITIVE=...
NEGATIVE=...
"""
    return f"""
	API 类型: {provider_type}
	提示词风格: {prompt_style}
	自定义提示词风格说明: {custom_prompt_style or "-"}
	固定画风/质量提示词会由系统单独拼接到 POSITIVE 最前面，你自己禁止写任何画风、质量、媒介、年代、艺术家、细节渲染、光照风格类标签: {style_prompt or "-"}
	基础负面提示词会由系统单独拼接到 NEGATIVE 最前面，你自己禁止写通用质量负面词: {negative_prompt or "-"}

角色绘图名映射:
{alias_lines or "-"}

最近事件摘录:
{source_lines or "-"}

解说文字:
{narration or "-"}

请为最适合成图的瞬间写内容标签。有绘图名时用绘图名，不要用显示名。NovelAI 时只写人物、人数、动作、姿势、表情、地点、道具、场景关系；禁止写画风、质量、媒介、年代、艺术家、细节渲染、光照风格类标签。
输出:
POSITIVE=...
NEGATIVE=...
"""


def _agent_alias_lines(agents: list[Agent], image_config: dict[str, Any]) -> str:
    aliases = image_config.get("agent_aliases") if isinstance(image_config.get("agent_aliases"), dict) else {}
    include_appearance = bool(image_config.get("use_agent_appearance", True))
    lines = []
    for agent in agents:
        display = (agent.chosen_name or agent.agent_id or "").strip()
        alias = str(aliases.get(agent.agent_id) or "").strip()
        appearance = (agent.appearance_short or agent.appearance_full or "").strip() if include_appearance else ""
        if alias:
            suffix = f"; appearance: {appearance[:220]}" if appearance else ""
            lines.append(f"{display} -> {alias}{suffix}")
        elif display:
            suffix = f"; appearance: {appearance[:220]}" if appearance else ""
            lines.append(f"{display}{suffix}")
    return "\n".join(lines)


def _replace_display_names_with_aliases(text: str, agents: list[Agent], image_config: dict[str, Any]) -> str:
    aliases = image_config.get("agent_aliases") if isinstance(image_config.get("agent_aliases"), dict) else {}
    result = str(text or "")
    replacements: list[tuple[str, str]] = []
    for agent in agents:
        alias = str(aliases.get(agent.agent_id) or "").strip()
        display = (agent.chosen_name or "").strip()
        if alias and display and display != alias:
            replacements.append((display, alias))
    for display, alias in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        result = result.replace(display, alias)
    return result


_PEOPLE_PROMPT_RE = re.compile(
    r"\b(?:solo|1girl|[2-9]\d*girls|multiple girls|several girls|girls?|"
    r"1boy|[2-9]\d*boys|multiple boys|boys?|woman|women|man|men|"
    r"person|people|characters?|students?|classmates?|group|crowd)\b",
    flags=re.I,
)

_GENERIC_MULTI_PERSON_TAGS = {
    "multiple girls",
    "several girls",
    "multiple boys",
    "several boys",
    "multiple people",
    "several people",
    "group",
    "crowd",
    "characters",
    "people",
}


def _agent_image_alias(agent: Agent, image_config: dict[str, Any]) -> str:
    aliases = image_config.get("agent_aliases") if isinstance(image_config.get("agent_aliases"), dict) else {}
    return str(aliases.get(agent.agent_id) or "").strip()


def _append_unique(items: list[str], value: str) -> None:
    normalized = value.strip().lower()
    if not normalized:
        return
    if normalized not in {item.lower() for item in items}:
        items.append(value.strip())


def _image_context_aliases(
    source_events: list[Event],
    narration: str,
    source_lines: str,
    agents: list[Agent],
    image_config: dict[str, Any],
) -> list[str]:
    by_id = {agent.agent_id: agent for agent in agents}
    aliases: list[str] = []

    def add_agent(agent_id: str | None) -> None:
        if not agent_id:
            return
        agent = by_id.get(agent_id)
        if not agent:
            return
        alias = _agent_image_alias(agent, image_config)
        if alias:
            _append_unique(aliases, alias)

    for event in source_events:
        add_agent(event.actor_agent_id)
        add_agent(event.target_agent_id)
        payload = event.payload if isinstance(event.payload, dict) else {}
        for key in ("actor_agent_ids", "target_agent_ids", "participants", "participant_agent_ids", "agent_ids"):
            raw_ids = payload.get(key)
            if isinstance(raw_ids, list):
                for raw_id in raw_ids:
                    add_agent(str(raw_id))
        for line_key in ("dialogue_lines", "speech_lines"):
            raw_lines = payload.get(line_key)
            if isinstance(raw_lines, list):
                for raw_line in raw_lines:
                    if not isinstance(raw_line, dict):
                        continue
                    for agent_key in ("speaker_agent_id", "target_agent_id", "actor_agent_id", "agent_id"):
                        add_agent(str(raw_line.get(agent_key) or ""))

    context_text = "\n".join(part for part in [narration, source_lines] if part)
    for agent in agents:
        display = (agent.chosen_name or "").strip()
        alias = _agent_image_alias(agent, image_config)
        if alias and ((display and display in context_text) or alias in context_text):
            _append_unique(aliases, alias)
    return aliases


def _prompt_contains_alias(prompt: str, alias: str) -> bool:
    return bool(alias) and alias.lower() in prompt.lower()


def _prompt_person_count_tag(count: int, prompt: str) -> str:
    lower = prompt.lower()
    if re.search(r"\b(?:boy|boys|man|men)\b", lower) and not re.search(r"\b(?:girl|girls|woman|women)\b", lower):
        return "1boy" if count == 1 else f"{count}boys"
    return "1girl" if count == 1 else f"{count}girls"


def _is_person_count_tag(tag: str) -> bool:
    return bool(re.fullmatch(r"(?:solo|1girl|[2-9]\d*girls|1boy|[2-9]\d*boys)", tag.strip(), flags=re.I))


def _enforce_image_character_aliases(
    prompt: str,
    context_aliases: list[str],
    agents: list[Agent],
    image_config: dict[str, Any],
    prompt_style: str,
) -> str:
    text = str(prompt or "").strip()
    if not text or not context_aliases:
        return text

    all_aliases = [_agent_image_alias(agent, image_config) for agent in agents]
    all_aliases = [alias for alias in all_aliases if alias]
    existing_aliases = [alias for alias in context_aliases if _prompt_contains_alias(text, alias)]
    has_people_tag = bool(_PEOPLE_PROMPT_RE.search(text))
    missing_aliases = [alias for alias in context_aliases if not _prompt_contains_alias(text, alias)]

    if not has_people_tag and existing_aliases:
        return text
    if not has_people_tag and not existing_aliases:
        return text
    if has_people_tag and not missing_aliases and not re.search(r"\bmultiple (?:girls|boys|people)\b|\bseveral (?:girls|boys|people)\b|\bgroup\b|\bcrowd\b", text, flags=re.I):
        return text

    wanted_aliases = (context_aliases if has_people_tag else existing_aliases)[:MAX_IMAGE_PROMPT_NAMED_CHARACTERS]
    if not wanted_aliases:
        return text

    tags: list[str] = []
    seen: set[str] = set()
    for raw_part in text.replace("\n", ",").split(","):
        tag = re.sub(r"\s+", " ", raw_part).strip(" .;，、")
        if not tag:
            continue
        key = tag.lower()
        if key in _GENERIC_MULTI_PERSON_TAGS or _is_person_count_tag(tag):
            continue
        if any(key == alias.lower() for alias in all_aliases):
            continue
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)

    prefix = [_prompt_person_count_tag(len(wanted_aliases), text), *wanted_aliases]
    cleaned = ", ".join([*prefix, *tags])
    if prompt_style == "novelai":
        return _clean_novelai_content_prompt(cleaned, strip_style_terms=False)
    return cleaned[:6000]


def _source_event_lines(session: Session, events: list[Event]) -> str:
    lines: list[str] = []
    for event in events:
        location = session.get(Location, event.location_id) if event.location_id else None
        actor = session.get(Agent, event.actor_agent_id) if event.actor_agent_id else None
        target = session.get(Agent, event.target_agent_id) if event.target_agent_id else None
        parts = [
            f"time={format_world_time(event.world_time)}",
            f"type={event.event_type}",
            f"location={location.public_name if location else '未记录'}",
        ]
        if actor:
            parts.append(f"actor={actor.chosen_name}")
        if target:
            parts.append(f"target={target.chosen_name}")
        if event.viewer_text:
            parts.append(f"text={event.viewer_text}")
        speech_lines = _source_event_speech_lines(session, event)
        if speech_lines:
            parts.append("dialogue=" + " / ".join(speech_lines))
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def _source_location_names(session: Session, events: list[Event]) -> str:
    names: list[str] = []
    for event in events:
        location = session.get(Location, event.location_id) if event.location_id else None
        name = (location.public_name if location else "").strip()
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def _source_event_speech_lines(session: Session, event: Event) -> list[str]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    raw_lines = payload.get("dialogue_lines")
    lines: list[str] = []
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("speech") or "").strip()
            if not text:
                continue
            speaker = session.get(Agent, item.get("speaker_agent_id")) if item.get("speaker_agent_id") else None
            target = session.get(Agent, item.get("target_agent_id")) if item.get("target_agent_id") else None
            prefix = speaker.chosen_name if speaker else ""
            if target:
                prefix = f"{prefix} -> {target.chosen_name}" if prefix else target.chosen_name
            lines.append(f"{prefix}: {text}" if prefix else text)
    elif isinstance(payload.get("speech"), str) and payload["speech"].strip():
        speaker = session.get(Agent, event.actor_agent_id) if event.actor_agent_id else None
        lines.append(f"{speaker.chosen_name}: {payload['speech'].strip()}" if speaker else payload["speech"].strip())
    return lines


def _parse_prompt_result(raw: str) -> tuple[str, str]:
    positive = ""
    negative = ""
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("POSITIVE="):
            positive = stripped.split("=", 1)[1].strip()
        elif stripped.upper().startswith("NEGATIVE="):
            negative = stripped.split("=", 1)[1].strip()
    if not positive:
        match = re.search(r'"positive"\s*:\s*"([^"]+)"', raw or "", flags=re.I)
        if match:
            positive = match.group(1).strip()
    if not negative:
        match = re.search(r'"negative"\s*:\s*"([^"]+)"', raw or "", flags=re.I)
        if match:
            negative = match.group(1).strip()
    return positive[:6000], negative[:3000]


def _fallback_prompt(
    prompt_style: str,
    narration: str,
    source_events: list[Event],
    alias_lines: str,
    style: str,
    negative_base: str,
    source_locations: str = "",
) -> tuple[str, str]:
    scene = narration or " ".join(event.viewer_text for event in source_events[-3:])
    if source_locations:
        event_scene = " ".join(event.viewer_text for event in source_events[-3:] if event.viewer_text.strip())
        scene = f"recorded location: {source_locations}. {event_scene or scene}"
    alias_names = []
    for line in alias_lines.splitlines():
        if "->" in line:
            alias_names.append(line.split("->", 1)[1].split(";", 1)[0].strip())
    subjects = ", ".join(alias_names[:4])
    if prompt_style in {"anima", "pony"}:
        prompt = _join_prompt(style, f"{subjects}, dramatic confrontation, {scene[:500]}", prompt_style)
    elif prompt_style in {"novelai", "danbooru", "illustrious"}:
        prompt = _join_prompt(style, f"{subjects}, expressive faces, background from the recorded location, {scene[:500]}", prompt_style)
    elif prompt_style == "flux":
        prompt = _join_prompt(style, f"{subjects or 'the characters'} in the recent scene: {scene[:700]}", prompt_style)
    elif prompt_style in {"midjourney", "dalle"}:
        prompt = _join_prompt(style, f"{subjects or 'The characters'} during the story moment, {scene[:700]}", prompt_style)
    else:
        prompt = _join_prompt(style, f"{subjects}, {scene[:700]}", prompt_style)
    return prompt, negative_base


def _join_prompt(style: str, prompt: str, prompt_style: str) -> str:
    parts = [style.strip(), prompt.strip()]
    text = ", ".join(part for part in parts if part)
    return text[:8000]


_GENERATED_STYLE_TERM_RE = re.compile(
    r"^(?:"
    r"best quality|amazing quality|masterpiece|high quality|low quality|worst quality|normal quality|very aesthetic|absurdres|highres|"
    r"newest|year[_ ]?\d{4}|\d{4}|source_anime|score_[0-9](?:_up)?|artist:.+|"
    r"anime illustration|anime scene|cinematic anime illustration|water ?color(?: \(medium\))?|"
    r"detailed skin|realistic rendering|detailed textures|intricate details|depth of field|soft lighting|cinematic lighting|"
    r"clean lineart|crisp lineart|highly detailed eyes|detailed eyes|soft shading|warm lighting|delicate face|"
    r"lowres|bad anatomy|bad hands|missing fingers|extra fingers|extra digits|fewer digits|extra limbs|malformed limbs|"
    r"long neck|bad face|deformed|blurry|jpeg artifacts|watermark|signature|text|logo|multiple views|comic|panels|masterpiece"
    r")$",
    flags=re.I,
)


def _strip_generated_style_terms(text: str) -> str:
    parts = [part.strip() for part in str(text or "").split(",")]
    kept = [part for part in parts if part and not _GENERATED_STYLE_TERM_RE.match(part)]
    return ", ".join(kept)[:6000]


def _clean_novelai_content_prompt(text: str, *, strip_style_terms: bool = True) -> str:
    cleaned = re.sub(r"\(([^():]{1,80}):\s*[0-9.]+\)", r"\1", str(text or ""))
    cleaned = re.sub(r"\b([a-z][a-z0-9_ -]{1,40}):\s*", r"\1, ", cleaned, flags=re.I)
    parts: list[str] = []
    seen: set[str] = set()
    for raw_part in cleaned.replace("\n", ",").split(","):
        part = re.sub(r"\s+", " ", raw_part).strip(" .;，、()")
        if not part or re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", part) or (strip_style_terms and _GENERATED_STYLE_TERM_RE.match(part)):
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(part)
        if len(parts) >= 72:
            break
    return ", ".join(parts)[:5000]


def _clean_prompt_tag_list(text: str, *, limit: int) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw_part in str(text or "").replace("\n", ",").split(","):
        part = re.sub(r"\s+", " ", raw_part).strip(" .;，、")
        if not part:
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(part)
        if len(", ".join(parts)) >= limit:
            break
    return ", ".join(parts)[:limit]


def _join_negative(base: str, generated: str) -> str:
    return ", ".join(part for part in [base.strip(), generated.strip()] if part)[:4000]


def _reference_images_for_event(session: Session, world: World, image_event: Event, image_config: dict[str, Any]) -> list[dict[str, Any]]:
    if not (image_config.get("reference_avatar_images") or image_config.get("reference_standing_images")):
        return []
    payload = dict(image_event.payload or {})
    source_ids = [int(item) for item in payload.get("source_event_ids") or [] if str(item).isdigit()]
    source_events = [session.get(Event, event_id) for event_id in source_ids]
    agent_ids: list[str] = []
    for event in source_events:
        if not event:
            continue
        for agent_id in [event.actor_agent_id, event.target_agent_id]:
            if agent_id and agent_id not in agent_ids:
                agent_ids.append(agent_id)
    if not agent_ids:
        agent_ids = [agent.agent_id for agent in session.execute(select(Agent).where(Agent.world_id == world.world_id).order_by(Agent.created_at_world_time, Agent.agent_id).limit(4)).scalars()]
    images: list[dict[str, Any]] = []
    for agent_id in agent_ids[:8]:
        agent = session.get(Agent, agent_id)
        if not agent:
            continue
        avatar_hint = agent.avatar_hint_json if isinstance(agent.avatar_hint_json, dict) else {}
        label = agent.chosen_name or agent.agent_id
        if image_config.get("reference_standing_images"):
            _append_reference_image(images, avatar_hint.get("standing_image_data_url"), f"{label} standing")
        if image_config.get("reference_avatar_images"):
            _append_reference_image(images, avatar_hint.get("image_data_url"), f"{label} avatar")
    return images[:8]


def _append_reference_image(images: list[dict[str, Any]], data_url: Any, label: str) -> None:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        return
    parsed = _parse_image_data_url(data_url)
    if not parsed:
        return
    media_type, content = parsed
    if not content:
        return
    images.append({"label": label, "media_type": media_type, "content": content})


def _parse_image_data_url(data_url: str) -> tuple[str, bytes] | None:
    match = re.match(r"^data:(image/[^;,]+);base64,(.+)$", data_url, re.S)
    if not match:
        return None
    try:
        return match.group(1).lower(), base64.b64decode(match.group(2), validate=True)
    except Exception:
        return None


async def _call_image_provider(image_config: dict[str, Any], prompt: str, negative_prompt: str, *, reference_images: list[dict[str, Any]] | None = None) -> str:
    retry_count = max(0, int(image_config.get("image_retry_count") or 0))
    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            return await _call_image_provider_once(image_config, prompt, negative_prompt, reference_images=reference_images)
        except Exception as exc:
            last_error = exc
            if attempt >= retry_count:
                break
            await asyncio.sleep(min(30.0, 1.5 * (attempt + 1)))
    if last_error:
        raise last_error
    raise RuntimeError("image generation failed")


async def _call_image_provider_once(image_config: dict[str, Any], prompt: str, negative_prompt: str, *, reference_images: list[dict[str, Any]] | None = None) -> str:
    provider_type = str(image_config.get("provider_type") or "sdxl")
    if provider_type == "comfyui" and str(image_config.get("workflow_json") or "").strip():
        return await _call_comfyui_workflow(image_config, prompt, negative_prompt)
    base_url = _default_base_url(image_config)
    if provider_type == "sdxl" and reference_images:
        return await _call_openai_image_edit(image_config, base_url, prompt, negative_prompt, reference_images)
    endpoint_path = _endpoint_path(image_config, provider_type)
    headers = _image_request_headers(image_config, provider_type)
    api_key = str(image_config.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request_payload = _request_payload(image_config, provider_type, prompt, negative_prompt, reference_images=reference_images)
    async with httpx.AsyncClient(timeout=_image_http_timeout(image_config)) as client:
        response = await client.post(f"{base_url}{endpoint_path}", headers=headers, json=request_payload)
        response.raise_for_status()
        return await _image_from_response(client, response)


async def _call_openai_image_edit(image_config: dict[str, Any], base_url: str, prompt: str, negative_prompt: str, reference_images: list[dict[str, Any]]) -> str:
    width = int(image_config.get("width") or 1024)
    height = int(image_config.get("height") or 1024)
    model_name = str(image_config.get("model_name") or "").strip()
    endpoint_path = str(image_config.get("endpoint_path") or "").strip()
    if not endpoint_path or "generations" in endpoint_path:
        endpoint_path = "/images/edits"
    endpoint_path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
    image_prompt = prompt if not negative_prompt else f"{prompt}\nAvoid: {negative_prompt}"
    data = {
        "prompt": image_prompt,
        "n": "1",
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }
    if model_name:
        data["model"] = model_name
    files = []
    for index, image in enumerate(reference_images[:8]):
        media_type = str(image.get("media_type") or "image/png")
        extension = "jpg" if "jpeg" in media_type else "webp" if "webp" in media_type else "png"
        files.append(("image", (f"reference_{index}.{extension}", image.get("content") or b"", media_type)))
    headers = {}
    api_key = str(image_config.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=_image_http_timeout(image_config)) as client:
        response = await client.post(f"{base_url}{endpoint_path}", headers=headers, data=data, files=files)
        response.raise_for_status()
        return await _image_from_response(client, response)


def _image_http_timeout(image_config: dict[str, Any]) -> float | None:
    timeout_seconds = int(image_config.get("request_timeout_seconds") if image_config.get("request_timeout_seconds") is not None else 300)
    return None if timeout_seconds <= 0 else float(timeout_seconds)


def _default_base_url(image_config: dict[str, Any]) -> str:
    base_url = str(image_config.get("base_url") or "").strip().rstrip("/")
    if not base_url and str(image_config.get("provider_type") or "") == "novelai":
        base_url = "https://image.novelai.net"
    if not base_url:
        raise RuntimeError("image generation base_url is not configured")
    return base_url


def _endpoint_path(image_config: dict[str, Any], provider_type: str) -> str:
    endpoint_path = str(image_config.get("endpoint_path") or "").strip()
    if not endpoint_path:
        endpoint_path = "/ai/generate-image" if provider_type == "novelai" else "/api/generate" if provider_type == "comfyui" else "/images/generations"
    return endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"


def _image_request_headers(image_config: dict[str, Any], provider_type: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider_type == "novelai":
        headers["Accept"] = "application/zip"
    custom_headers = _json_object_from_text(str(image_config.get("custom_headers_json") or ""), field_name="custom_headers_json")
    for key, value in custom_headers.items():
        name = str(key).strip()
        if name:
            headers[name] = str(value)
    return headers


def _request_payload(
    image_config: dict[str, Any],
    provider_type: str,
    prompt: str,
    negative_prompt: str,
    *,
    reference_images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request_template = str(image_config.get("request_template_json") or "").strip()
    if request_template:
        patched = _patched_json_template(request_template, prompt, negative_prompt, image_config)
        if not isinstance(patched, dict):
            raise RuntimeError("request_template_json must describe a JSON object")
        return patched
    width = int(image_config.get("width") or 1024)
    height = int(image_config.get("height") or 1024)
    steps = int(image_config.get("steps") or 28)
    cfg = float(image_config.get("cfg_scale") or 7.0)
    seed = int(image_config.get("seed") if image_config.get("seed") is not None else -1)
    model_name = str(image_config.get("model_name") or "").strip()
    sampler = str(image_config.get("sampler") or "").strip()
    if provider_type == "novelai":
        if "augment-image" in _endpoint_path(image_config, provider_type):
            return _novelai_augment_payload(
                image_config,
                prompt=prompt,
                reference_images=reference_images or [],
                width=width,
                height=height,
            )
        return _novelai_payload(
            image_config,
            prompt=prompt,
            negative_prompt=negative_prompt,
            reference_images=reference_images or [],
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
            model_name=model_name,
            sampler=sampler,
        )
    if provider_type == "comfyui":
        return {
            "model": model_name or None,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg,
            "sampler": sampler or None,
            "seed": seed if seed >= 0 else None,
            "n": 1,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
        }
    image_prompt = prompt if not negative_prompt else f"{prompt}\nAvoid: {negative_prompt}"
    payload: dict[str, Any] = {
        "prompt": image_prompt,
        "n": 1,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
    }
    if model_name:
        payload["model"] = model_name
    return payload


def _novelai_augment_payload(
    image_config: dict[str, Any],
    *,
    prompt: str,
    reference_images: list[dict[str, Any]],
    width: int,
    height: int,
) -> dict[str, Any]:
    if not reference_images:
        raise RuntimeError("NovelAI augment-image requires at least one reference image")
    image = next((item for item in reference_images if item.get("content")), None)
    if not image:
        raise RuntimeError("NovelAI augment-image reference image is empty")
    params = _json_object_from_text(str(image_config.get("nai_params_json") or ""), field_name="nai_params_json")
    return {
        "image": base64.b64encode(bytes(image.get("content") or b"")).decode("ascii"),
        "prompt": prompt,
        "width": int(params.pop("width", width)),
        "height": int(params.pop("height", height)),
        "req_type": str(params.pop("req_type", "lineart")),
        "defry": int(params.pop("defry", 0)),
        **params,
    }


def _novelai_payload(
    image_config: dict[str, Any],
    *,
    prompt: str,
    negative_prompt: str,
    reference_images: list[dict[str, Any]],
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: int,
    model_name: str,
    sampler: str,
) -> dict[str, Any]:
    action = str(image_config.get("nai_action") or "generate").strip().lower() or "generate"
    if action not in {"generate", "img2img", "infill"}:
        action = "generate"
    model = model_name or "nai-diffusion-4-5-full"
    uses_v4_prompt = _novelai_uses_v4_prompt(model)
    image_format = str(image_config.get("nai_image_format") or "png").strip().lower()
    if image_format not in {"png", "webp"}:
        image_format = "png"
    params: dict[str, Any] = {
        "width": width,
        "height": height,
        "scale": cfg,
        "steps": steps,
        "sampler": sampler or "k_euler_ancestral",
        "seed": seed if seed >= 0 else None,
        "n_samples": int(image_config.get("nai_n_samples") or 1),
        "ucPreset": int(image_config.get("nai_uc_preset") or 0),
        "qualityToggle": bool(image_config.get("nai_quality_toggle", True)),
        "params_version": int(image_config.get("nai_params_version") or 3),
        "image_format": image_format,
    }
    if uses_v4_prompt:
        params["v4_prompt"] = _novelai_v4_condition(prompt, legacy_uc=False)
        params["v4_negative_prompt"] = _novelai_v4_condition(negative_prompt, legacy_uc=False)
    else:
        params["negative_prompt"] = negative_prompt
    cfg_rescale = float(image_config.get("nai_cfg_rescale") or 0)
    if cfg_rescale > 0:
        params["cfg_rescale"] = cfg_rescale
    for key, nai_key in [
        ("nai_sm_dyn", "sm_dyn"),
        ("nai_dynamic_thresholding", "dynamic_thresholding"),
        ("nai_add_original_image", "add_original_image"),
    ]:
        if bool(image_config.get(key)):
            params[nai_key] = True
    if bool(image_config.get("nai_sm")) and not uses_v4_prompt:
        params["sm"] = True
    if reference_images:
        encoded = [
            _novelai_reference_image_b64(bytes(image.get("content") or b""), v4_director=uses_v4_prompt and action != "img2img")
            for image in reference_images[:8]
            if image.get("content")
        ]
        if encoded:
            if action == "img2img":
                params["image"] = encoded[0]
                params["strength"] = float(image_config.get("nai_strength") or 0.35)
                params["noise"] = float(image_config.get("nai_noise") or 0.0)
            else:
                strength = float(image_config.get("nai_reference_strength") or 0.45)
                extracted = float(image_config.get("nai_reference_information_extracted") or 1.0)
                if uses_v4_prompt:
                    params["director_reference_images"] = encoded
                    params["director_reference_strength_values"] = [strength for _ in encoded]
                    params["director_reference_information_extracted"] = [extracted for _ in encoded]
                    params["director_reference_descriptions"] = [
                        _novelai_v4_condition("character", legacy_uc=False)
                        for _ in encoded
                    ]
                else:
                    params["reference_image_multiple"] = encoded
                    params["reference_strength_multiple"] = [strength for _ in encoded]
                    params["reference_information_extracted_multiple"] = [extracted for _ in encoded]
    params.update(_json_object_from_text(str(image_config.get("nai_params_json") or ""), field_name="nai_params_json"))
    params = {key: value for key, value in params.items() if value is not None}
    return {
            "input": "" if uses_v4_prompt else prompt,
            "model": model,
            "action": action,
            "parameters": params,
        }


def _novelai_uses_v4_prompt(model_name: str) -> bool:
    model = model_name.strip().lower()
    return model.startswith("nai-diffusion-4") or model.startswith("nai-diffusion-4-5")


def _novelai_reference_image_b64(content: bytes, *, v4_director: bool) -> str:
    if not v4_director:
        return base64.b64encode(content).decode("ascii")
    return base64.b64encode(_novelai_v4_director_reference_png(content)).decode("ascii")


def _novelai_v4_director_reference_png(content: bytes) -> bytes:
    from PIL import Image

    source = Image.open(io.BytesIO(content)).convert("RGB")
    width, height = source.size
    if width <= 0 or height <= 0:
        return content
    source_ratio = width / height
    portrait_ratio = 1024 / 1536
    landscape_ratio = 1536 / 1024
    square_ratio = 1.0
    target_width, target_height = min(
        [(1024, 1536), (1536, 1024), (1472, 1472)],
        key=lambda item: abs(source_ratio - (item[0] / item[1])),
    )
    if abs(source_ratio - portrait_ratio) <= abs(source_ratio - landscape_ratio) and abs(source_ratio - portrait_ratio) <= abs(source_ratio - square_ratio):
        target_width, target_height = 1024, 1536
    fit_scale = min(target_width / width, target_height / height)
    resized_size = (max(1, round(width * fit_scale)), max(1, round(height * fit_scale)))
    resized = source.resize(resized_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (target_width, target_height), (0, 0, 0))
    offset = ((target_width - resized_size[0]) // 2, (target_height - resized_size[1]) // 2)
    canvas.paste(resized, offset)
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


def _novelai_v4_condition(caption: str, *, legacy_uc: bool) -> dict[str, Any]:
    clean_caption = _novelai_v4_caption_text(caption)
    return {
        "caption": {
            "base_caption": clean_caption,
            "char_captions": [],
        },
        "use_coords": False,
        "use_order": True,
        "legacy_uc": legacy_uc,
    }


def _novelai_v4_caption_text(caption: str) -> str:
    text = str(caption or "")
    text = "".join(char if ord(char) < 128 else " " for char in text)
    parts: list[str] = []
    seen: set[str] = set()
    for raw_part in text.replace("\n", ",").split(","):
        part = re.sub(r"\s+", " ", raw_part).strip(" .;，、")
        if not part:
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(part)
    return ", ".join(parts)


def _json_object_from_text(raw: str, *, field_name: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{field_name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{field_name} must describe a JSON object")
    return value


async def _call_comfyui_workflow(image_config: dict[str, Any], prompt: str, negative_prompt: str) -> str:
    base_url = _default_base_url(image_config)
    workflow = _patched_workflow(str(image_config.get("workflow_json") or ""), prompt, negative_prompt, image_config)
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=_image_http_timeout(image_config)) as client:
        response = await client.post(f"{base_url}/prompt", headers=headers, json={"prompt": workflow})
        response.raise_for_status()
        prompt_id = str((response.json() or {}).get("prompt_id") or "").strip()
        if not prompt_id:
            return await _image_from_response(client, response)
        timeout_seconds = max(0, int(image_config.get("comfyui_timeout_seconds") or 0))
        waited = 0
        while timeout_seconds <= 0 or waited < timeout_seconds:
            await asyncio.sleep(1)
            waited += 1
            history = await client.get(f"{base_url}/history/{prompt_id}")
            history.raise_for_status()
            image = await _image_from_comfyui_history(client, base_url, history.json(), prompt_id)
            if image:
                return image
    raise RuntimeError("ComfyUI image generation timed out")


def _patched_workflow(raw: str, prompt: str, negative_prompt: str, image_config: dict[str, Any]) -> Any:
    try:
        workflow = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ComfyUI workflow_json is invalid JSON") from exc
    return _replace_template_values(workflow, _template_replacements(prompt, negative_prompt, image_config))


def _patched_json_template(raw: str, prompt: str, negative_prompt: str, image_config: dict[str, Any]) -> Any:
    try:
        template = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("request_template_json is invalid JSON") from exc
    return _replace_template_values(template, _template_replacements(prompt, negative_prompt, image_config))


def _template_replacements(prompt: str, negative_prompt: str, image_config: dict[str, Any]) -> dict[str, Any]:
    width = int(image_config.get("width") or 1024)
    height = int(image_config.get("height") or 1024)
    steps = int(image_config.get("steps") or 28)
    cfg_scale = float(image_config.get("cfg_scale") or 7.0)
    seed = int(image_config.get("seed") if image_config.get("seed") is not None else -1)
    sampler = str(image_config.get("sampler") or "")
    model = str(image_config.get("model_name") or "")
    values: dict[str, Any] = {
        "prompt": prompt,
        "positive_prompt": prompt,
        "negative_prompt": negative_prompt,
        "negative": negative_prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg_scale,
        "cfg_scale": cfg_scale,
        "seed": seed,
        "sampler": sampler,
        "model": model,
    }
    replacements: dict[str, Any] = {}
    for key, value in values.items():
        replacements[f"{{{{{key}}}}}"] = value
        replacements[f"%{key}%"] = value
    return replacements


def _replace_template_values(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        result = value
        for key, replacement in replacements.items():
            result = result.replace(key, str(replacement))
        return result
    if isinstance(value, list):
        return [_replace_template_values(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_template_values(item, replacements) for key, item in value.items()}
    return value


async def _image_from_comfyui_history(client: httpx.AsyncClient, base_url: str, history: dict[str, Any], prompt_id: str) -> str | None:
    prompt_history = history.get(prompt_id) if isinstance(history, dict) else None
    outputs = prompt_history.get("outputs") if isinstance(prompt_history, dict) else None
    if not isinstance(outputs, dict):
        return None
    for output in outputs.values():
        images = output.get("images") if isinstance(output, dict) else None
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            params = {
                "filename": str(image.get("filename") or ""),
                "subfolder": str(image.get("subfolder") or ""),
                "type": str(image.get("type") or "output"),
            }
            view = await client.get(f"{base_url}/view", params=params)
            view.raise_for_status()
            content_type = view.headers.get("content-type", "image/png").split(";")[0].strip().lower()
            return f"data:{content_type if content_type.startswith('image/') else 'image/png'};base64,{base64.b64encode(view.content).decode('ascii')}"
    return None


async def _image_from_response(client: httpx.AsyncClient, response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type.startswith("image/"):
        return f"data:{content_type};base64,{base64.b64encode(response.content).decode('ascii')}"
    if "zip" in content_type or response.content[:2] == b"PK":
        return _image_from_zip(response.content)
    if content_type == "application/json" or response.text.strip().startswith("{"):
        return await _image_from_json(client, response.json())
    raise RuntimeError(f"image provider returned unsupported content-type: {content_type or 'unknown'}")


async def _image_from_json(client: httpx.AsyncClient, data: Any) -> str:
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend(data.get(key) for key in ("image_data_url", "imageDataUrl", "data_url", "url", "image_url", "b64_json", "image", "output"))
        if isinstance(data.get("data"), list):
            candidates.extend(data["data"])
        if isinstance(data.get("images"), list):
            candidates.extend(data["images"])
    elif isinstance(data, list):
        candidates.extend(data)
    for candidate in candidates:
        image = await _image_from_candidate(client, candidate)
        if image:
            return image
    raise RuntimeError("image provider JSON did not contain an image")


async def _image_from_candidate(client: httpx.AsyncClient, candidate: Any) -> str | None:
    if isinstance(candidate, str):
        if candidate.startswith("data:image/"):
            return candidate
        if candidate.startswith("http://") or candidate.startswith("https://"):
            response = await client.get(candidate)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/png").split(";")[0].strip().lower()
            return f"data:{content_type if content_type.startswith('image/') else 'image/png'};base64,{base64.b64encode(response.content).decode('ascii')}"
        if len(candidate) > 200 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", candidate):
            return f"data:image/png;base64,{candidate.strip()}"
    if isinstance(candidate, dict):
        for key in ("image_data_url", "imageDataUrl", "data_url", "url", "image_url", "b64_json", "image"):
            image = await _image_from_candidate(client, candidate.get(key))
            if image:
                return image
    return None


def _image_from_zip(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if lowered.endswith((".png", ".jpg", ".jpeg", ".webp")):
                media_type = "image/jpeg" if lowered.endswith((".jpg", ".jpeg")) else "image/webp" if lowered.endswith(".webp") else "image/png"
                return f"data:{media_type};base64,{base64.b64encode(archive.read(name)).decode('ascii')}"
    raise RuntimeError("image provider zip did not contain an image")


def _narrator_config(world: World) -> dict[str, Any]:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = settings_json.get("narrator_config")
    return config if isinstance(config, dict) else {}


def _prompt_llm_config(world: World, image_config: dict[str, Any]) -> dict[str, Any]:
    if str(image_config.get("prompt_llm_mode") or "narrator") == "custom":
        config = {
            "provider_id": image_config.get("prompt_llm_provider_id") or "",
            "provider_name": image_config.get("prompt_llm_provider_name") or "",
            "base_url": image_config.get("prompt_llm_base_url") or "",
            "api_key": image_config.get("prompt_llm_api_key") or "",
            "model_name": image_config.get("prompt_llm_model_name") or "",
            "system_prompt": image_config.get("prompt_llm_system_prompt") or "",
            "llm_generation": image_config.get("prompt_llm_generation") if isinstance(image_config.get("prompt_llm_generation"), dict) else None,
            "retry_count": image_config.get("prompt_llm_retry_count"),
            "retry_interval_ms": image_config.get("prompt_llm_retry_interval_ms"),
            "request_timeout_ms": image_config.get("prompt_llm_request_timeout_ms"),
            "rpm": image_config.get("prompt_llm_rpm"),
        }
        if config["base_url"] or config["model_name"] or config["api_key"]:
            return config
    return _narrator_config(world)


def _safe_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _safe_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))
