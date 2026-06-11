from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.bundle_manifest import BUNDLE_FORMAT, WORLD_CONFIG_FORMAT
from app.core.config import settings
from app.core.models import Agent, IdentityKnowledge, Relationship, World
from app.llm.runtime import agent_llm_runtime, normalize_llm_runtime


AGENT_ARCHIVE_FORMAT = "tiny-living-world-agent-config-v2"
TRAIT_KEYS = [
    "openness",
    "caution",
    "sociability",
    "empathy",
    "curiosity",
    "discipline",
    "aggression",
    "honesty",
    "creativity",
    "neuroticism",
]


def build_agent_preset_zip(session: Session, world: World) -> bytes:
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id)
            .order_by(Agent.created_at_world_time.asc(), Agent.agent_id.asc())
        ).scalars()
    )
    provider_pool = _ProviderPool()
    manifest_agents: list[dict[str, Any]] = []
    avatar_files: dict[str, bytes] = {}
    index_by_agent_id = {agent.agent_id: index for index, agent in enumerate(agents)}
    initial_knowledge = _export_initial_knowledge(session, agents, index_by_agent_id)
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    image_generation = settings_json.get("image_generation") if isinstance(settings_json.get("image_generation"), dict) else {}
    image_aliases = image_generation.get("agent_aliases") if isinstance(image_generation.get("agent_aliases"), dict) else {}

    for index, agent in enumerate(agents):
        provider_id = provider_pool.add(
            name=agent.model_provider_name or "默认提供商",
            base_url=agent.llm_base_url or settings.llm_base_url,
            api_key=agent.llm_api_key or "",
            model_name=agent.model_name or settings.model_name(agent.model_alias or "world_agent"),
            provider_id_hint=agent.model_provider_id,
            runtime=agent_llm_runtime(agent),
        )
        avatar_hint = agent.avatar_hint_json if isinstance(agent.avatar_hint_json, dict) else {}
        avatar_path = _extract_image_file(index, agent, avatar_hint, avatar_files, key="image_data_url", folder="avatars")
        standing_path = _extract_image_file(index, agent, avatar_hint, avatar_files, key="standing_image_data_url", folder="standings")
        tool_learning = agent.tool_learning_json if isinstance(agent.tool_learning_json, dict) else {}
        item: dict[str, Any] = {
            "index": index,
            "agentId": agent.agent_id,
            "providerId": provider_id,
            "modelName": agent.model_name or "",
            "toolContextMode": "all" if tool_learning.get("tool_context_mode") == "all" else "dynamic",
            "agentToolsetIds": [str(item) for item in tool_learning.get("agent_toolset_ids") or []],
            "systemPrompt": agent.custom_system_prompt or "",
            "chosenName": agent.chosen_name or "",
            "imagePromptName": str(image_aliases.get(agent.agent_id) or ""),
            "appearance": agent.appearance_full or agent.appearance_short or "",
            "traits": _agent_traits(agent),
            "knowledgeMode": "custom" if initial_knowledge.get(agent.agent_id) else "none",
            "knownAgents": initial_knowledge.get(agent.agent_id, {}),
            "identity": {
                "genderIdentity": agent.gender_identity,
                "genderCustomText": agent.gender_custom_text,
                "genderPublicity": agent.gender_publicity,
                "genderExpression": agent.gender_expression,
                "ageStage": agent.age_stage,
                "appearanceShort": agent.appearance_short,
                "speakingStyle": agent.speaking_style,
                "personalitySeed": agent.personality_seed,
                "initialGoal": agent.initial_goal,
                "introPolicy": agent.intro_policy,
                "userConfiguredName": agent.user_configured_name,
            },
            "ttsConfig": tool_learning.get("tts_config") or {},
        }
        if avatar_path:
            item["avatarPath"] = avatar_path
        if standing_path:
            item["standingImagePath"] = standing_path
        manifest_agents.append(item)

    narrator_config = _export_narrator_config(settings_json, provider_pool)
    baby_model_configs = _export_baby_model_configs(settings_json, provider_pool)
    agent_config = {
        "format": AGENT_ARCHIVE_FORMAT,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "exportedFromWorldId": world.world_id,
        "worldName": world.name,
        "saveName": settings_json.get("save_name") or world.name,
        "agentCount": len(agents),
        "collectiveCorePrompt": settings_json.get("collective_core_prompt", ""),
        "pregnancyMode": settings_json.get("pregnancy_mode", "any_gender"),
        "survivalDifficulty": settings_json.get("survival_difficulty", "NORMAL"),
        "worldviewId": settings_json.get("worldview_id", "fast_modern_worldview"),
        "coreToolsetEnabled": bool(settings_json.get("core_toolset_enabled", True)),
        "coreToolsetId": settings_json.get("core_toolset_id", "core_basic_toolset"),
        "optionalToolsetIds": list(settings_json.get("enabled_optional_toolset_ids") or []),
        "worldToolsetId": settings_json.get("world_toolset_id") or settings_json.get("toolset_id") or "fast_modern_world_toolset",
        "traitMode": settings_json.get("trait_mode", "player"),
        "traitBudget": settings_json.get("trait_budget", 500),
        "imageGeneration": image_generation,
        "exportOptions": {
            "names": True,
            "imagePrompts": True,
            "prompts": True,
            "appearances": True,
            "avatars": True,
            "standingImages": True,
            "collectivePrompt": True,
            "providerModels": True,
            "toolModes": True,
            "agentToolsets": True,
            "traits": True,
            "knowledge": True,
            "narrator": True,
            "imageGeneration": True,
            "babyModels": True,
            "providers": True,
            "tts": True,
        },
        "providers": provider_pool.items(),
        "narratorConfig": narrator_config,
        "babyModelConfigs": baby_model_configs,
        "agents": manifest_agents,
    }
    world_config = {
        "format": WORLD_CONFIG_FORMAT,
        "exportedAt": agent_config["exportedAt"],
        "exportedFromWorldId": world.world_id,
        "name": world.name,
        "worldName": world.name,
        "saveName": settings_json.get("save_name") or world.name,
        "worldviewId": settings_json.get("worldview_id", "fast_modern_worldview"),
        "worldviewName": settings_json.get("worldview_name", ""),
        "worldviewVersion": settings_json.get("worldview_version", ""),
        "worldviewPackId": settings_json.get("worldview_pack_id"),
        "coreToolsetEnabled": bool(settings_json.get("core_toolset_enabled", True)),
        "coreToolsetId": settings_json.get("core_toolset_id", "core_basic_toolset"),
        "optionalToolsetIds": list(settings_json.get("enabled_optional_toolset_ids") or []),
        "worldToolsetId": settings_json.get("world_toolset_id") or settings_json.get("toolset_id") or "fast_modern_world_toolset",
        "survivalDifficulty": settings_json.get("survival_difficulty", "NORMAL"),
        "pregnancyMode": settings_json.get("pregnancy_mode", "any_gender"),
        "agentRequestMode": settings_json.get("agent_request_mode", "serial"),
        "eventDisplayMode": settings_json.get("event_display_mode", "batch"),
        "traitMode": settings_json.get("trait_mode", "player"),
        "traitBudget": settings_json.get("trait_budget", 500),
        "promptSettings": settings_json.get("prompt_settings") or {},
        "imageGeneration": image_generation,
    }
    bundle_manifest = {
        "format": BUNDLE_FORMAT,
        "bundleVersion": "1.0.0",
        "exportedAt": agent_config["exportedAt"],
        "name": f"{world.name} bundled configuration",
        "description": "Top-level AIworld manifest shared by import/export. Components point to smaller configs that can be recognized independently.",
        "components": [
            {
                "component_id": "world_config",
                "type": "world_config",
                "format": WORLD_CONFIG_FORMAT,
                "path": "configs/world_config.json",
                "required": False,
            },
            {
                "component_id": "agent_config",
                "type": "agent_config",
                "format": AGENT_ARCHIVE_FORMAT,
                "path": "configs/agent_config.json",
                "required": True,
            },
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("manifest.json", json.dumps(bundle_manifest, ensure_ascii=False, indent=2))
        zf.writestr("configs/world_config.json", json.dumps(world_config, ensure_ascii=False, indent=2))
        zf.writestr("configs/agent_config.json", json.dumps(agent_config, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", "这是微世界人员配置预设。回到创建页后，可在模型与身份配置里导入这个 zip。\n")
        for path, content in avatar_files.items():
            zf.writestr(path, content)
    return buffer.getvalue()


def _export_initial_knowledge(session: Session, agents: list[Agent], index_by_agent_id: dict[str, int]) -> dict[str, dict[str, dict[str, Any]]]:
    world_agent_ids = set(index_by_agent_id)
    rows: dict[str, dict[str, dict[str, Any]]] = {agent.agent_id: {} for agent in agents}
    known_pairs: set[tuple[str, str]] = set()

    for knowledge in session.execute(
        select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id.in_(world_agent_ids),
            IdentityKnowledge.target_agent_id.in_(world_agent_ids),
        )
    ).scalars():
        if knowledge.observer_agent_id == knowledge.target_agent_id:
            continue
        if not (knowledge.name_known or knowledge.visual_known):
            continue
        target_index = index_by_agent_id.get(knowledge.target_agent_id)
        if target_index is None:
            continue
        rows[knowledge.observer_agent_id][str(target_index)] = {"knows": True, "affection": 0}
        known_pairs.add((knowledge.observer_agent_id, knowledge.target_agent_id))

    for rel in session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id.in_(world_agent_ids),
            Relationship.target_agent_id.in_(world_agent_ids),
        )
    ).scalars():
        if rel.observer_agent_id == rel.target_agent_id:
            continue
        target_index = index_by_agent_id.get(rel.target_agent_id)
        if target_index is None:
            continue
        affection = max(-100, min(100, float(rel.affection or 0)))
        familiar = float(rel.familiarity or 0) > 0 or abs(affection) > 0 or (rel.observer_agent_id, rel.target_agent_id) in known_pairs
        if not familiar:
            continue
        rows[rel.observer_agent_id][str(target_index)] = {"knows": True, "affection": affection}

    return {agent_id: known for agent_id, known in rows.items() if known}


class _ProviderPool:
    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._by_key: dict[tuple[str, str, str, int, int, int, int], str] = {}
        self._used_ids: set[str] = set()

    def add(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model_name: str | None = None,
        provider_id_hint: str | None = None,
        runtime: dict[str, Any] | None = None,
    ) -> str:
        llm_runtime = normalize_llm_runtime(runtime)
        key = (
            name or "默认提供商",
            base_url or settings.llm_base_url,
            api_key or "",
            llm_runtime["retry_count"],
            llm_runtime["retry_interval_ms"],
            llm_runtime["request_timeout_ms"],
            llm_runtime["rpm"],
        )
        existing_id = self._by_key.get(key)
        if existing_id:
            self._add_model(existing_id, model_name)
            return existing_id
        provider_id = _safe_id(provider_id_hint or name or f"provider_{len(self._entries) + 1}")
        if provider_id in self._used_ids:
            provider_id = f"provider_{len(self._entries) + 1}"
        self._used_ids.add(provider_id)
        self._by_key[key] = provider_id
        self._entries.append(
            {
                "providerId": provider_id,
                "name": key[0],
                "baseUrl": key[1],
                "apiKey": key[2],
                "retryCount": llm_runtime["retry_count"],
                "retryIntervalMs": llm_runtime["retry_interval_ms"],
                "requestTimeoutMs": llm_runtime["request_timeout_ms"],
                "rpm": llm_runtime["rpm"],
                "models": [model_name] if model_name else [],
            }
        )
        return provider_id

    def items(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._entries]

    def _add_model(self, provider_id: str, model_name: str | None) -> None:
        if not model_name:
            return
        for item in self._entries:
            if item["providerId"] == provider_id and model_name not in item["models"]:
                item["models"].append(model_name)
                return


def _export_narrator_config(settings_json: dict[str, Any], provider_pool: _ProviderPool) -> dict[str, Any]:
    enabled = bool(settings_json.get("narrator_enabled", False))
    config = settings_json.get("narrator_config") if isinstance(settings_json.get("narrator_config"), dict) else {}
    if not enabled or not config:
        return {"enabled": False, "providerId": "", "modelName": "", "systemPrompt": "", "autoFrequency": str(settings_json.get("narrator_frequency") or "normal")}
    model_name = str(config.get("model_name") or settings.model_name("narrator"))
    provider_id = provider_pool.add(
        provider_id_hint=str(config.get("provider_id") or ""),
        name=str(config.get("provider_name") or "解说提供商"),
        base_url=str(config.get("base_url") or settings.llm_base_url),
        api_key=str(config.get("api_key") or ""),
        model_name=model_name,
        runtime=normalize_llm_runtime(config),
    )
    return {
        "enabled": True,
        "providerId": provider_id,
        "modelName": model_name,
        "systemPrompt": str(config.get("system_prompt") or ""),
        "autoFrequency": str(config.get("auto_frequency") or settings_json.get("narrator_frequency") or "normal"),
    }


def _export_baby_model_configs(settings_json: dict[str, Any], provider_pool: _ProviderPool) -> list[dict[str, str]]:
    pool = settings_json.get("baby_model_pool")
    if not isinstance(pool, list):
        return []
    result: list[dict[str, str]] = []
    for raw in pool:
        if not isinstance(raw, dict):
            continue
        model_name = str(raw.get("model_name") or "")
        if not model_name:
            continue
        provider_id = provider_pool.add(
            provider_id_hint=str(raw.get("provider_id") or ""),
            name=str(raw.get("provider_name") or "宝宝池提供商"),
            base_url=str(raw.get("base_url") or settings.llm_base_url),
            api_key=str(raw.get("api_key") or ""),
            model_name=model_name,
            runtime=normalize_llm_runtime(raw),
        )
        result.append({"providerId": provider_id, "modelName": model_name})
    return result


def _agent_traits(agent: Agent) -> dict[str, int]:
    traits = agent.traits
    if not traits:
        return {key: 50 for key in TRAIT_KEYS}
    return {key: int(getattr(traits, key, 50)) for key in TRAIT_KEYS}


def _extract_image_file(index: int, agent: Agent, avatar_hint: dict[str, Any], avatar_files: dict[str, bytes], *, key: str, folder: str) -> str | None:
    data_url = avatar_hint.get(key)
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None
    match = re.match(r"^data:([^;,]+);base64,(.+)$", data_url, re.S)
    if not match:
        return None
    mime = match.group(1).lower()
    extension = _extension_for_mime(mime)
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except Exception:
        return None
    if not content:
        return None
    base_name = _safe_filename(agent.chosen_name or f"agent_{index + 1}")
    path = f"{folder}/{index + 1:02d}_{base_name}.{extension}"
    avatar_files[path] = content
    return path


def _extension_for_mime(mime: str) -> str:
    if "jpeg" in mime or "jpg" in mime:
        return "jpg"
    if "webp" in mime:
        return "webp"
    if "gif" in mime:
        return "gif"
    return "png"


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_\-]+", "_", value.strip().lower()).strip("_")
    if not text or not re.match(r"^[A-Za-z]", text):
        text = f"provider_{text or 'default'}"
    return text[:80]


def _safe_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", value).strip("._")
    return text[:60] or "agent"
