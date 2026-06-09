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
from app.core.database import SessionLocal
from app.core.models import Agent, Event, NarratorRun, World
from app.events.event_store import create_event
from app.llm.language import normalize_language, world_language
from app.llm.openai_compatible import provider
from app.llm.runtime import llm_generation_kwargs, llm_runtime_kwargs, normalize_llm_generation, normalize_llm_runtime


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
    "style_prompt": "",
    "negative_prompt": "",
    "request_template_json": "",
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
    result = {key: dict(value) if isinstance(value, dict) else value for key, value in DEFAULT_IMAGE_GENERATION_SETTINGS.items()}
    result.update({key: previous[key] for key in result if key in previous})
    if "enabled" in data:
        result["enabled"] = bool(data.get("enabled"))
    source_mode = str(data.get("source_mode") or data.get("sourceMode") or result["source_mode"]).strip().lower()
    result["source_mode"] = source_mode if source_mode in IMAGE_SOURCE_MODES else "narration"
    provider_type = str(data.get("provider_type") or data.get("providerType") or result["provider_type"]).strip().lower()
    result["provider_type"] = provider_type if provider_type in IMAGE_PROVIDER_TYPES else "sdxl"
    prompt_style = str(data.get("prompt_style") or data.get("promptStyle") or result["prompt_style"]).strip().lower()
    result["prompt_style"] = prompt_style if prompt_style in IMAGE_PROMPT_STYLES else "auto"
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
        result["api_key"] = str(previous.get("api_key") or "") if value == "***" else value[:4000]
    if "prompt_llm_api_key" in data or "promptLlmApiKey" in data:
        value = _clean_optional_text(_raw_config_value(data, "prompt_llm_api_key", "promptLlmApiKey"), 4000)
        result["prompt_llm_api_key"] = str(previous.get("prompt_llm_api_key") or "") if value == "***" else value[:4000]
    for key, minimum, maximum, fallback in [
        ("width", 256, 2048, 1024),
        ("height", 256, 2048, 1024),
        ("steps", 1, 150, 28),
        ("seed", -1, 2_147_483_647, -1),
    ]:
        if key in data:
            result[key] = _safe_int(data.get(key), minimum, maximum, int(result.get(key) or fallback))
    if "cfg_scale" in data or "cfgScale" in data:
        result["cfg_scale"] = _safe_float(data.get("cfg_scale") if "cfg_scale" in data else data.get("cfgScale"), 1.0, 30.0, float(result.get("cfg_scale") or 7.0))
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
    loop.create_task(_generate_image_background(world_id, image_event_id))


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
    if not image_config.get("enabled"):
        image_event.payload = {**payload, "status": "skipped", "error": "image generation disabled"}
        session.commit()
        await _broadcast_image_update(world.world_id, image_event.event_id)
        return
    payload["status"] = "running"
    image_event.payload = payload
    session.commit()

    try:
        prompt, negative_prompt = await _create_image_prompt(session, world, image_event, image_config)
        image_data_url = await _call_image_provider(image_config, prompt, negative_prompt)
        image_event = session.get(Event, image_event.event_id)
        if not image_event:
            return
        image_event.viewer_text = f"【生图】{payload.get('summary_title') or '画面'} 已生成。"
        image_event.agent_visible_text = image_event.viewer_text
        image_event.payload = {
            **dict(image_event.payload or {}),
            "status": "completed",
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image_data_url": image_data_url,
            "error": None,
        }
    except Exception as exc:
        image_event = session.get(Event, image_event.event_id)
        if not image_event:
            return
        image_event.viewer_text = f"【生图】{payload.get('summary_title') or '画面'} 生成失败。"
        image_event.agent_visible_text = image_event.viewer_text
        image_event.payload = {
            **dict(image_event.payload or {}),
            "status": "failed",
            "error": str(exc)[:1000],
        }
    session.commit()
    await _broadcast_image_update(world.world_id, image_event.event_id)


async def _broadcast_image_update(world_id: str, event_id: int) -> None:
    try:
        await manager.broadcast(world_id, {"type": "image_generation_updated", "world_id": world_id, "event_id": event_id})
    except Exception:
        return


async def _create_image_prompt(session: Session, world: World, image_event: Event, image_config: dict[str, Any]) -> tuple[str, str]:
    payload = dict(image_event.payload or {})
    source_ids = [int(item) for item in payload.get("source_event_ids") or [] if str(item).isdigit()]
    source_events = [session.get(Event, event_id) for event_id in source_ids]
    source_events = [event for event in source_events if event]
    agents = list(session.execute(select(Agent).where(Agent.world_id == world.world_id)).scalars())
    alias_lines = _agent_alias_lines(agents, image_config)
    source_lines = "\n".join(f"- {event.viewer_text}" for event in source_events[-12:])
    narration = str(payload.get("narration") or "").strip()
    language = world_language(world)
    provider_type = str(image_config.get("provider_type") or "sdxl")
    prompt_style = _resolved_prompt_style(image_config)
    custom_prompt_style = str(image_config.get("custom_prompt_style") or "").strip()
    style = str(image_config.get("style_prompt") or "").strip()
    negative_base = str(image_config.get("negative_prompt") or "").strip()
    prompt_llm_config = _prompt_llm_config(world, image_config)
    system_prompt = _image_prompt_system(prompt_style, custom_prompt_style, language)
    if prompt_llm_config.get("system_prompt"):
        system_prompt += f"\nAdditional user instructions for image prompt writing: {prompt_llm_config['system_prompt']}"
    user_prompt = _image_prompt_user(
        provider_type=provider_type,
        prompt_style=prompt_style,
        custom_prompt_style=custom_prompt_style,
        source_lines=source_lines,
        narration=narration,
        alias_lines=alias_lines,
        style_prompt=style,
        negative_prompt=negative_base,
        language=language,
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
        if not result.error:
            parsed = _parse_prompt_result(result.raw_text)
            if parsed[0]:
                positive = _join_prompt(style, parsed[0], prompt_style)
                negative = _join_negative(negative_base, parsed[1])
                return positive, negative
    except Exception:
        pass
    return _fallback_prompt(prompt_style, narration, source_events, alias_lines, style, negative_base)


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
    base = (
        "You are the narrator's image-prompt specialist. Convert the recent story into one image prompt. "
        "Do not invent new plot facts. Use drawing aliases exactly when provided. Output only POSITIVE= and NEGATIVE= lines."
        if english
        else "你是解说 AI 的生图提示词专员。把上方情节转换成一张图的提示词，不要编造新剧情。有绘图角色名时必须直接使用绘图角色名。只输出 POSITIVE= 和 NEGATIVE= 两行。"
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
Fixed style prompt to include: {style_prompt or "-"}
Base negative prompt to keep compatible with: {negative_prompt or "-"}

Character drawing aliases:
{alias_lines or "-"}

Recent event excerpts:
{source_lines or "-"}

Narrator text:
{narration or "-"}

Write a single image prompt for the most visually representative moment. Use aliases instead of display names when aliases exist.
Output:
POSITIVE=...
NEGATIVE=...
"""
    return f"""
API 类型: {provider_type}
提示词风格: {prompt_style}
自定义提示词风格说明: {custom_prompt_style or "-"}
固定画风提示词，必须兼容保留: {style_prompt or "-"}
基础负面提示词，必须兼容保留: {negative_prompt or "-"}

角色绘图名映射:
{alias_lines or "-"}

最近事件摘录:
{source_lines or "-"}

解说文字:
{narration or "-"}

请为最适合成图的瞬间写一组提示词。有绘图名时用绘图名，不要用显示名。
输出:
POSITIVE=...
NEGATIVE=...
"""


def _agent_alias_lines(agents: list[Agent], image_config: dict[str, Any]) -> str:
    aliases = image_config.get("agent_aliases") if isinstance(image_config.get("agent_aliases"), dict) else {}
    lines = []
    for agent in agents:
        display = (agent.chosen_name or agent.agent_id or "").strip()
        alias = str(aliases.get(agent.agent_id) or "").strip()
        appearance = (agent.appearance_short or agent.appearance_full or "").strip()
        if alias:
            lines.append(f"{display} -> {alias}; appearance: {appearance[:220]}")
        elif display:
            lines.append(f"{display}; appearance: {appearance[:220]}")
    return "\n".join(lines)


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
) -> tuple[str, str]:
    scene = narration or " ".join(event.viewer_text for event in source_events[-3:])
    alias_names = []
    for line in alias_lines.splitlines():
        if "->" in line:
            alias_names.append(line.split("->", 1)[1].split(";", 1)[0].strip())
    subjects = ", ".join(alias_names[:4])
    if prompt_style in {"anima", "pony"}:
        prompt = _join_prompt(style, f"score_9, score_8_up, score_7_up, source_anime, {subjects}, dramatic scene, {scene[:500]}", prompt_style)
    elif prompt_style in {"novelai", "danbooru", "illustrious"}:
        prompt = _join_prompt(style, f"{subjects}, anime scene, expressive, detailed background, {scene[:500]}", prompt_style)
    elif prompt_style == "flux":
        prompt = _join_prompt(style, f"A detailed cinematic image of {subjects or 'the characters'} in the recent scene: {scene[:700]}", prompt_style)
    elif prompt_style in {"midjourney", "dalle"}:
        prompt = _join_prompt(style, f"{subjects or 'The characters'} in a visually representative story moment, {scene[:700]}", prompt_style)
    else:
        prompt = _join_prompt(style, f"{subjects}, cinematic anime illustration, {scene[:700]}", prompt_style)
    return prompt, negative_base


def _join_prompt(style: str, prompt: str, prompt_style: str) -> str:
    parts = [style.strip(), prompt.strip()]
    text = ", ".join(part for part in parts if part)
    if prompt_style in {"anima", "pony"} and "score_9" not in text:
        text = "score_9, score_8_up, score_7_up, source_anime, " + text
    return text[:8000]


def _join_negative(base: str, generated: str) -> str:
    return ", ".join(part for part in [base.strip(), generated.strip()] if part)[:4000]


async def _call_image_provider(image_config: dict[str, Any], prompt: str, negative_prompt: str) -> str:
    provider_type = str(image_config.get("provider_type") or "sdxl")
    if provider_type == "comfyui" and str(image_config.get("workflow_json") or "").strip():
        return await _call_comfyui_workflow(image_config, prompt, negative_prompt)
    base_url = _default_base_url(image_config)
    endpoint_path = _endpoint_path(image_config, provider_type)
    headers = {"Content-Type": "application/json"}
    api_key = str(image_config.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request_payload = _request_payload(image_config, provider_type, prompt, negative_prompt)
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(f"{base_url}{endpoint_path}", headers=headers, json=request_payload)
        response.raise_for_status()
        return await _image_from_response(client, response)


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


def _request_payload(image_config: dict[str, Any], provider_type: str, prompt: str, negative_prompt: str) -> dict[str, Any]:
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
        return {
            "input": prompt,
            "model": model_name or "nai-diffusion-4-full",
            "action": "generate",
            "parameters": {
                "width": width,
                "height": height,
                "scale": cfg,
                "steps": steps,
                "sampler": sampler or "k_euler_ancestral",
                "seed": seed if seed >= 0 else None,
                "negative_prompt": negative_prompt,
            },
        }
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


async def _call_comfyui_workflow(image_config: dict[str, Any], prompt: str, negative_prompt: str) -> str:
    base_url = _default_base_url(image_config)
    workflow = _patched_workflow(str(image_config.get("workflow_json") or ""), prompt, negative_prompt, image_config)
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(f"{base_url}/prompt", headers=headers, json={"prompt": workflow})
        response.raise_for_status()
        prompt_id = str((response.json() or {}).get("prompt_id") or "").strip()
        if not prompt_id:
            return await _image_from_response(client, response)
        for _ in range(120):
            await asyncio.sleep(1)
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
