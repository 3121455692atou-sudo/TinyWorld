from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.agents.identity_generation import choose_model_alias, create_agent_with_identity, prepare_identity_draft
from app.agents.state import apply_delta
from app.agents.v5_state import ensure_v5_agent_state
from app.api.serializers import event_to_dict, location_to_dict, narrator_to_dict, world_summary
from app.api.left_snapshot import build_left_snapshot
from app.api.websocket import manager
from app.content.presets import (
    DEFAULT_CORE_TOOLSET_ID,
    DEFAULT_FINANCE_INVESTING_TOOLSET_ID,
    DEFAULT_REPRODUCTION_TOOLSET_ID,
    DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID,
    DEFAULT_TOOLSET_ID,
    DEFAULT_WORLDVIEW_ID,
    core_toolset_by_id,
    optional_toolsets_by_ids,
    worldview_by_id,
    world_toolset_by_id,
)
from app.content.toolsets import DEFAULT_AGENT_SPECIAL_TOOLSET_IDS, DEFAULT_OPTIONAL_TOOLSET_IDS, finance_investing_enabled, survival_needs_enabled
from app.content.worldview_runtime import infer_worldpack_state_schema, location_color_map, location_order, worldview_rule_parameters, worldview_ui_schema
from app.content.worldpacks import worldview_default_create_settings, worldview_start_minute
from app.core.config import settings
from app.core.clock import format_world_time
from app.core.database import get_db
from app.core.models import (
    Agent,
    AgentDynamicState,
    AgentLocation,
    AgentTrait,
    Conversation,
    Event,
    IdentityKnowledge,
    Inventory,
    Item,
    Location,
    Memory,
    NarratorRun,
    Relationship,
    World,
)
from app.economy.v6 import economy_metrics
from app.effects.effect_engine import _create_child_from_birth
from app.events.event_store import chronological_order_asc, chronological_order_desc, create_event, sort_chronologically
from app.export.agent_presets import build_agent_preset_zip
from app.export.event_archive import build_event_archive_zip
from app.export.story_exporter import export_world_zip
from app.image_generation.service import cancel_image_generation_event, cancel_pending_image_generations, create_manual_image_generation, create_prompt_image_generation, normalize_image_generation_settings, rerun_image_generation_event
from app.llm.language import normalize_language
from app.llm.runtime import normalize_llm_generation, normalize_llm_runtime
from app.knowledge.relationships import adjust_relationship, derive_label, get_relationship
from app.narrator.narrator_service import create_narration
from app.simulation.difficulty import DIFFICULTY_LABELS, profile_for_world
from app.simulation.scheduler import simulation_manager
from app.social.intervention_crush import INTERVENTION_CRUSH_DURATION_MINUTES, set_intervention_crush
from app.storage.audio import audio_url_for_key, store_audio_data_url
from app.world.seed_world import private_home_location as build_private_home_location, private_home_location_id, seed_world_content, world_location_id
from app.world.werewolf import initialize_werewolf_game


router = APIRouter(prefix="/api/worlds", tags=["worlds"])
MAX_AGENT_COUNT = 64
MAX_SYSTEM_PROMPT_LENGTH = 20_000
MAX_APPEARANCE_LENGTH = 4_000
MAX_AVATAR_DATA_URL_LENGTH = 10_000_000
SPEECH_EVENT_TYPES = ("dialogue", "introduce_self", "refuse_introduction")
TRIVIAL_CONFIG_EVENT_TYPES = ("llm_config_changed", "agent_profile_changed")


async def world_mutation_guard(world_id: str):
    async with simulation_manager.mutation_lock(world_id):
        yield
PROMPT_SETTING_BOUNDS = {
    "memory_limit": (0, 200),
    "recent_event_limit": (0, 200),
    "recent_self_event_limit": (0, 100),
    "action_option_limit": (20, 500),
    "dream_memory_limit": (4, 200),
    "dream_important_limit": (0, 40),
    "dream_background_limit": (0, 40),
}
MAX_CONCURRENCY_LIMIT = 100_000
WEREWOLF_ROLE_NAMES = {"villager", "werewolf", "seer", "coroner", "guard"}
EVENT_DELETE_UNDO_STACK_KEY = "event_delete_undo_stack"
EVENT_DELETE_UNDO_LIMIT_KEY = "event_delete_undo_limit"
DEFAULT_EVENT_DELETE_UNDO_LIMIT = 5
MAX_EVENT_DELETE_UNDO_LIMIT = 100


class WerewolfRoleAssignmentInput(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|counts|manual)$")
    counts: dict[str, int] = Field(default_factory=dict)
    manual_roles: list[str] = Field(default_factory=list)


class EventDeleteRequest(BaseModel):
    event_ids: list[int] = Field(default_factory=list, max_length=1000)


class EventDeleteUndoLimitRequest(BaseModel):
    limit: int = Field(default=DEFAULT_EVENT_DELETE_UNDO_LIMIT, ge=0, le=MAX_EVENT_DELETE_UNDO_LIMIT)


class EventTextUpdateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


def _narration_edit_parts(event: Event, text: str) -> tuple[str, str, str]:
    payload = dict(event.payload or {}) if isinstance(event.payload, dict) else {}
    title = str(payload.get("summary_title") or "").strip()
    narration = text.strip()
    if narration.startswith("【解说】"):
        stripped = narration.removeprefix("【解说】").strip()
        for separator in (":", "："):
            if separator in stripped:
                maybe_title, maybe_narration = stripped.split(separator, 1)
                title = maybe_title.strip() or title
                narration = maybe_narration.strip()
                break
        else:
            narration = stripped
    title = (title or "解说")[:160]
    if not narration:
        raise HTTPException(400, "text is required")
    return title, narration, f"【解说】{title}: {narration}"


class ManualImagePromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str | None = Field(default=None, max_length=3000)
    title: str | None = Field(default=None, max_length=80)


class ImageGenerationRerunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    negative_prompt: str | None = Field(default=None, max_length=8000)
    overrides: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationSettingsInput(BaseModel):
    enabled: bool = False
    source_mode: str = Field(default="narration", pattern="^(narration|auto_summary)$")
    provider_type: str = Field(default="sdxl", pattern="^(novelai|comfyui|sdxl|anima)$")
    prompt_style: str = Field(default="auto", pattern="^(auto|novelai|sdxl|flux|pony|anima|danbooru|illustrious|stable_diffusion|midjourney|dalle|custom)$")
    custom_prompt_style: str | None = Field(default=None, max_length=4000)
    prompt_llm_mode: str = Field(default="narrator", pattern="^(narrator|custom)$")
    prompt_llm_provider_id: str | None = Field(default=None, max_length=80)
    prompt_llm_provider_name: str | None = Field(default=None, max_length=120)
    prompt_llm_base_url: str | None = Field(default=None, max_length=500)
    prompt_llm_api_key: str | None = Field(default=None, max_length=4000)
    prompt_llm_model_name: str | None = Field(default=None, max_length=200)
    prompt_llm_system_prompt: str | None = Field(default=None, max_length=4000)
    prompt_llm_generation: "LLMGenerationInput | None" = None
    prompt_llm_retry_count: int = Field(default=2, ge=0, le=100_000)
    prompt_llm_retry_interval_ms: int = Field(default=1500, ge=0, le=21_600_000)
    prompt_llm_request_timeout_ms: int = Field(default=300_000, ge=0, le=86_400_000)
    prompt_llm_rpm: int = Field(default=0, ge=0, le=100_000)
    auto_frequency: str = Field(default="normal", pattern="^(low|normal|high)$")
    display_mode: str = Field(default="placeholder", pattern="^(placeholder|wait)$")
    base_url: str | None = Field(default=None, max_length=500)
    endpoint_path: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4000)
    model_name: str | None = Field(default=None, max_length=200)
    model_options: list[str] = Field(default_factory=list, max_length=500)
    use_agent_appearance: bool = True
    reference_avatar_images: bool = False
    reference_standing_images: bool = False
    style_prompt: str | None = Field(default=None, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=4000)
    request_template_json: str | None = Field(default=None, max_length=80_000)
    custom_headers_json: str | None = Field(default=None, max_length=20_000)
    nai_action: str | None = Field(default="generate", max_length=60)
    nai_image_format: str | None = Field(default="png", max_length=20)
    nai_n_samples: int = Field(default=1, ge=1, le=4)
    nai_uc_preset: int = Field(default=0, ge=0, le=10)
    nai_quality_toggle: bool = True
    nai_params_version: int = Field(default=3, ge=1, le=10)
    nai_cfg_rescale: float = Field(default=0.0, ge=0.0, le=20.0)
    nai_sm: bool = False
    nai_sm_dyn: bool = False
    nai_dynamic_thresholding: bool = False
    nai_reference_strength: float = Field(default=0.45, ge=0.0, le=1.0)
    nai_reference_information_extracted: float = Field(default=1.0, ge=0.0, le=1.0)
    nai_strength: float = Field(default=0.35, ge=0.0, le=1.0)
    nai_noise: float = Field(default=0.0, ge=0.0, le=1.0)
    nai_add_original_image: bool = False
    nai_params_json: str | None = Field(default=None, max_length=80_000)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    steps: int = Field(default=28, ge=1, le=150)
    cfg_scale: float = Field(default=7.0, ge=1.0, le=30.0)
    sampler: str | None = Field(default=None, max_length=120)
    seed: int = Field(default=-1, ge=-1, le=2_147_483_647)
    workflow_json: str | None = Field(default=None, max_length=80_000)
    agent_aliases: dict[str, str] = Field(default_factory=dict)


class CreateWorldRequest(BaseModel):
    name: str = Field(default=settings.world_name, max_length=120)
    agent_count: int = Field(default=settings.initial_agent_count, ge=1, le=MAX_AGENT_COUNT)
    collective_core_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    seed: int = settings.seed
    language: str = Field(default="zh", pattern="^(zh|en)$")
    speed: str = "fast"
    agent_request_mode: str = Field(default="serial", pattern="^(serial|parallel)$")
    event_display_mode: str = Field(default="batch", pattern="^(batch|per_agent)$")
    pregnancy_mode: str = Field(default="any_gender", pattern="^(any_gender|heterosexual)$")
    trait_mode: str = Field(default="agent", pattern="^(agent|player|random)$")
    trait_budget: int = Field(default=500, ge=0, le=2000)
    survival_difficulty: str = Field(default="NORMAL", pattern="^(FAIRY|NORMAL|HARD|HELL)$")
    worldview_id: str = Field(default=DEFAULT_WORLDVIEW_ID, max_length=120)
    core_toolset_enabled: bool = True
    core_toolset_id: str = Field(default=DEFAULT_CORE_TOOLSET_ID, max_length=120)
    optional_toolset_ids: list[str] = Field(default_factory=lambda: list(DEFAULT_OPTIONAL_TOOLSET_IDS))
    world_toolset_id: str = Field(default=DEFAULT_TOOLSET_ID, max_length=120)
    toolset_id: str | None = Field(default=None, max_length=120)
    werewolf_role_assignment: WerewolfRoleAssignmentInput = Field(default_factory=WerewolfRoleAssignmentInput)
    providers: list["ProviderConfigInput"] = Field(default_factory=list)
    narrator_config: "NarratorConfigInput | None" = None
    image_generation: ImageGenerationSettingsInput | None = None
    baby_model_configs: list["BabyModelConfigInput"] = Field(default_factory=list)
    agent_configs: list["AgentConfigInput"] = Field(default_factory=list)
    prompt_settings: "PromptSettingsInput | None" = None
    llm_generation: "LLMGenerationInput | None" = None
    llm_concurrency: "LLMConcurrencyInput | None" = None


class ProviderConfigInput(BaseModel):
    provider_id: str = Field(default="default", max_length=80)
    name: str = Field(default="默认提供商", max_length=80)
    base_url: str = Field(default=settings.llm_base_url, max_length=300)
    api_key: str | None = Field(default=None, max_length=4000)
    retry_count: int = Field(default=2, ge=0, le=100_000)
    retry_interval_ms: int = Field(default=1500, ge=0, le=21_600_000)
    request_timeout_ms: int = Field(default=300_000, ge=0, le=86_400_000)
    rpm: int = Field(default=0, ge=0, le=100_000)
    models: list[str] = Field(default_factory=list, max_length=1000)


class AgentConfigInput(BaseModel):
    provider_id: str = Field(default="default", max_length=80)
    model_name: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    chosen_name: str | None = Field(default=None, max_length=12)
    image_prompt_name: str | None = Field(default=None, max_length=120)
    appearance: str | None = Field(default=None, max_length=MAX_APPEARANCE_LENGTH)
    avatar_data_url: str | None = Field(default=None, max_length=MAX_AVATAR_DATA_URL_LENGTH)
    standing_image_data_url: str | None = Field(default=None, max_length=MAX_AVATAR_DATA_URL_LENGTH)
    trait_mode: str | None = Field(default=None, pattern="^(agent|player|random)$")
    trait_sliders: dict[str, int] = Field(default_factory=dict)
    tool_context_mode: str = Field(default="dynamic", pattern="^(dynamic|all)$")
    agent_toolset_ids: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS))
    knowledge_mode: str = Field(default="none", pattern="^(all|none|custom)$")
    known_agents: dict[str, "InitialKnownAgentInput"] = Field(default_factory=dict)
    llm_generation: "LLMGenerationInput | None" = None
    tts_config: dict | None = None


class InitialKnownAgentInput(BaseModel):
    knows: bool = False
    affection: float = Field(default=0, ge=-100, le=100)


class NarratorConfigInput(BaseModel):
    enabled: bool = True
    provider_id: str = Field(default="default", max_length=80)
    model_name: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    auto_frequency: str = Field(default="normal", pattern="^(low|normal|high)$")
    llm_generation: "LLMGenerationInput | None" = None


class RuntimeNarratorConfigInput(BaseModel):
    enabled: bool | None = None
    provider_id: str | None = Field(default=None, max_length=80)
    provider_name: str | None = Field(default=None, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4000)
    clear_api_key: bool = False
    model_name: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    auto_frequency: str | None = Field(default=None, pattern="^(low|normal|high)$")
    llm_generation: "LLMGenerationInput | None" = None
    retry_count: int | None = Field(default=None, ge=0, le=100_000)
    retry_interval_ms: int | None = Field(default=None, ge=0, le=21_600_000)
    request_timeout_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    rpm: int | None = Field(default=None, ge=0, le=100_000)


class BabyModelConfigInput(BaseModel):
    provider_id: str = Field(default="default", max_length=80)
    model_name: str | None = Field(default=None, max_length=120)


class SaveNameUpdateRequest(BaseModel):
    save_name: str = Field(default="", max_length=120)


class PromptSettingsInput(BaseModel):
    memory_limit: int = Field(default=24, ge=0, le=200)
    recent_event_limit: int = Field(default=14, ge=0, le=200)
    recent_self_event_limit: int = Field(default=10, ge=0, le=100)
    action_option_limit: int = Field(default=90, ge=20, le=500)
    dream_memory_limit: int = Field(default=48, ge=4, le=200)
    dream_important_limit: int = Field(default=10, ge=0, le=40)
    dream_background_limit: int = Field(default=5, ge=0, le=40)


class LLMGenerationInput(BaseModel):
    stream: bool = False
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=0, ge=0, le=200_000)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)


class LLMConcurrencyInput(BaseModel):
    default_provider_limit: int = Field(default=0, ge=0, le=MAX_CONCURRENCY_LIMIT)
    provider_limits: dict[str, int] = Field(default_factory=dict)
    model_limits: dict[str, int] = Field(default_factory=dict)


class WorldRuntimeSettingsUpdateRequest(BaseModel):
    collective_core_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    speed: str | None = Field(default=None, pattern="^(slow|fast)$")
    narrator_frequency: str | None = Field(default=None, pattern="^(low|normal|high)$")
    narrator_config: RuntimeNarratorConfigInput | None = None
    prompt_settings: PromptSettingsInput | None = None
    agent_request_mode: str | None = Field(default=None, pattern="^(serial|parallel)$")
    event_display_mode: str | None = Field(default=None, pattern="^(batch|per_agent)$")
    llm_generation: LLMGenerationInput | None = None
    llm_concurrency: LLMConcurrencyInput | None = None
    image_generation: ImageGenerationSettingsInput | None = None
    disabled_tool_modules: list[str] | None = None


class WorldInterventionRequest(BaseModel):
    action: str = Field(max_length=120)
    actor_agent_id: str | None = Field(default=None, max_length=48)
    target_agent_id: str | None = Field(default=None, max_length=48)
    location_id: str | None = Field(default=None, max_length=48)
    note: str | None = Field(default=None, max_length=240)


CreateWorldRequest.model_rebuild()


def _agent_initial_location_id(world_id: str, index: int, worldview: dict, defaults: dict, db: Session) -> str:
    """Return the playable spawn location while keeping a separate private home.

    Modern worlds still start residents in their homes. Special worlds can set
    ``initial_location_id`` so new residents actually meet each other in the
    intended opening scene instead of silently isolating in private rooms.
    """
    home_id = private_home_location_id(world_id, index, worldview)
    raw_initial = defaults.get("initial_location_id") or worldview.get("initial_location_id")
    if not raw_initial:
        return home_id
    candidate = world_location_id(world_id, str(raw_initial))
    return candidate if db.get(Location, candidate) else home_id


def _birth_event_text(agent_name: str, initial_location: Location | None, home_location_id: str, language: str) -> str:
    if not initial_location or initial_location.location_id == home_location_id:
        return (
            f"{agent_name} woke up in their own home and has not seen any other residents yet."
            if normalize_language(language) == "en"
            else f"{agent_name} 在自己的住所里醒来，暂时还没有见到其他居民。"
        )
    place = initial_location.public_name or "起点"
    return (
        f"{agent_name} arrived at {place}, ready to meet the others."
        if normalize_language(language) == "en"
        else f"{agent_name} 来到了{place}，准备在这里和其他居民相遇。"
    )


def _normalize_werewolf_role_assignment(config: WerewolfRoleAssignmentInput, agent_count: int) -> dict:
    count = max(1, min(MAX_AGENT_COUNT, int(agent_count or 1)))
    return {
        "mode": config.mode if config.mode in {"auto", "counts", "manual"} else "auto",
        "counts": {
            role: max(0, min(count, int(config.counts.get(role, 0) or 0)))
            for role in WEREWOLF_ROLE_NAMES
        },
        "manual_roles": [
            role if role in WEREWOLF_ROLE_NAMES else "villager"
            for role in list(config.manual_roles or [])[:count]
        ],
    }


def _apply_initial_agent_knowledge(db: Session, world: World, agents: list[Agent], configs: list[AgentConfigInput]) -> None:
    world_time = int(world.current_world_time_minutes or 0)
    for observer_index, observer in enumerate(agents):
        config = configs[observer_index] if observer_index < len(configs) else AgentConfigInput()
        if config.knowledge_mode == "none":
            continue
        if config.knowledge_mode == "all":
            target_entries = {
                target_index: InitialKnownAgentInput(knows=True, affection=0)
                for target_index in range(len(agents))
                if target_index != observer_index
            }
        else:
            target_entries = {}
            for raw_index, entry in (config.known_agents or {}).items():
                try:
                    target_index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if target_index == observer_index or target_index < 0 or target_index >= len(agents):
                    continue
                target_entries[target_index] = entry

        for target_index, entry in target_entries.items():
            if not entry.knows:
                continue
            target = agents[target_index]
            knowledge = db.execute(
                select(IdentityKnowledge).where(
                    IdentityKnowledge.observer_agent_id == observer.agent_id,
                    IdentityKnowledge.target_agent_id == target.agent_id,
                )
            ).scalar_one_or_none()
            if knowledge is None:
                knowledge = IdentityKnowledge(observer_agent_id=observer.agent_id, target_agent_id=target.agent_id)
                db.add(knowledge)
                db.flush()
            knowledge.visual_known = True
            knowledge.appearance_snapshot = target.appearance_short or target.appearance or None
            knowledge.appearance_confidence = max(int(knowledge.appearance_confidence or 0), 90)
            knowledge.name_known = True
            knowledge.known_name = target.chosen_name
            knowledge.name_confidence = max(int(knowledge.name_confidence or 0), 100)
            knowledge.name_learned_via = "initial_setup"
            knowledge.first_seen_at = knowledge.first_seen_at if knowledge.first_seen_at is not None else world_time
            knowledge.first_name_learned_at = knowledge.first_name_learned_at if knowledge.first_name_learned_at is not None else world_time
            knowledge.last_seen_at = world_time
            note = "开局预设认识。"
            if note not in (knowledge.notes or ""):
                knowledge.notes = (knowledge.notes or "") + note

            rel = get_relationship(db, observer.agent_id, target.agent_id)
            rel.familiarity = max(float(rel.familiarity or 0), 25)
            rel.affection = max(-100, min(100, float(entry.affection)))
            rel.relationship_label = derive_label(rel)
            rel.last_interaction_at = world_time


@router.post("")
async def create_world(payload: CreateWorldRequest, db: Session = Depends(get_db)) -> dict:
    world_id = f"world_{uuid.uuid4().hex[:12]}"
    worldview = worldview_by_id(payload.worldview_id)
    defaults = worldview_default_create_settings(worldview)
    is_external_worldview = worldview.get("worldview_id") != DEFAULT_WORLDVIEW_ID

    effective_survival_difficulty = payload.survival_difficulty
    effective_speed = payload.speed
    effective_core_toolset_enabled = payload.core_toolset_enabled
    effective_core_toolset_id = payload.core_toolset_id
    effective_optional_toolset_ids = list(payload.optional_toolset_ids)
    effective_world_toolset_id = payload.world_toolset_id
    if is_external_worldview:
        if "speed" in defaults and payload.speed == CreateWorldRequest.model_fields["speed"].default:
            effective_speed = str(defaults.get("speed") or payload.speed)
        if "survival_difficulty" in defaults and payload.survival_difficulty == "NORMAL":
            effective_survival_difficulty = str(defaults.get("survival_difficulty") or payload.survival_difficulty)
        if "core_toolset_enabled" in defaults:
            effective_core_toolset_enabled = bool(defaults.get("core_toolset_enabled"))
        if defaults.get("core_toolset_id") and payload.core_toolset_id == DEFAULT_CORE_TOOLSET_ID:
            effective_core_toolset_id = str(defaults["core_toolset_id"])
        if "optional_toolset_ids" in defaults and set(payload.optional_toolset_ids) == set(DEFAULT_OPTIONAL_TOOLSET_IDS):
            raw_optional = defaults.get("optional_toolset_ids")
            effective_optional_toolset_ids = [str(x) for x in raw_optional] if isinstance(raw_optional, list) else []
        if defaults.get("world_toolset_id") and payload.world_toolset_id == DEFAULT_TOOLSET_ID:
            effective_world_toolset_id = str(defaults["world_toolset_id"])

    legacy_toolset_id = payload.toolset_id if payload.toolset_id and effective_world_toolset_id == DEFAULT_TOOLSET_ID else None
    core_toolset = core_toolset_by_id(effective_core_toolset_id) if effective_core_toolset_enabled else None
    optional_toolsets = optional_toolsets_by_ids(effective_optional_toolset_ids)
    enabled_optional_toolset_ids = [toolset["toolset_id"] for toolset in optional_toolsets]
    survival_enabled = DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID in enabled_optional_toolset_ids
    finance_enabled = DEFAULT_FINANCE_INVESTING_TOOLSET_ID in enabled_optional_toolset_ids
    reproduction_enabled = DEFAULT_REPRODUCTION_TOOLSET_ID in enabled_optional_toolset_ids
    world_toolset = world_toolset_by_id(legacy_toolset_id or effective_world_toolset_id)
    start_minute = worldview_start_minute(worldview, 8 * 60)
    location_colors = location_color_map(world_id, worldview)
    ordered_locations = location_order(world_id, worldview)
    rule_parameters = worldview_rule_parameters(worldview)
    ui_schema = worldview_ui_schema(
        worldview,
        survival_enabled=survival_enabled,
        finance_enabled=finance_enabled,
        reproduction_enabled=reproduction_enabled,
        world_toolset_id=effective_world_toolset_id,
    )
    worldpack_state_schema = infer_worldpack_state_schema(worldview, world_toolset)
    world = World(
        world_id=world_id,
        name=payload.name,
        status="paused",
        seed=payload.seed,
        current_world_time_minutes=start_minute,
        settings_json={
            "agent_count": payload.agent_count,
            "language": normalize_language(payload.language),
            "save_name": payload.name,
            "collective_core_prompt": payload.collective_core_prompt or "",
            "speed": effective_speed,
            "pregnancy_mode": payload.pregnancy_mode,
            "trait_mode": payload.trait_mode,
            "trait_budget": payload.trait_budget,
            "survival_difficulty": effective_survival_difficulty,
            "survival_difficulty_label": DIFFICULTY_LABELS.get(effective_survival_difficulty, effective_survival_difficulty),
            "worldview_id": worldview["worldview_id"],
            "worldview_name": worldview["name"],
            "worldview_version": worldview["version"],
            "worldview_pack_id": worldview.get("pack_id"),
            "worldview_source_path": worldview.get("source_path"),
            "worldview_prompt_blocks": worldview.get("prompt_blocks") or [],
            "worldview_mechanics": worldview.get("mechanics") or [],
            "worldview_locations": ordered_locations,
            "location_colors": location_colors,
            "worldview_rule_parameters": rule_parameters,
            "pregnancy_duration_days": int(rule_parameters.get("pregnancy_duration_days", rule_parameters.get("reproduction.pregnancy_days", 3)) or 3),
            "child_growth_days": int(rule_parameters.get("child_growth_days", rule_parameters.get("reproduction.child_growth_days", 3)) or 3),
            "worldview_ui": ui_schema,
            "worldpack_state_schema": worldpack_state_schema,
            "worldpack_default_create_settings": defaults,
            "no_basic_needs": bool(defaults.get("no_basic_needs", False)),
            "mortality_disabled": bool(defaults.get("mortality_disabled", False)),
            "day_only": bool(defaults.get("day_only", False)),
            "werewolf_mode_enabled": bool(defaults.get("werewolf_mode_enabled", False)),
            "werewolf_role_assignment": _normalize_werewolf_role_assignment(payload.werewolf_role_assignment, payload.agent_count),
            "core_toolset_enabled": effective_core_toolset_enabled,
            "core_toolset_id": core_toolset["toolset_id"] if core_toolset else None,
            "core_toolset_name": core_toolset["name"] if core_toolset else None,
            "core_toolset_version": core_toolset["version"] if core_toolset else None,
            "enabled_optional_toolset_ids": enabled_optional_toolset_ids,
            "optional_toolset_names": [toolset["name"] for toolset in optional_toolsets],
            "survival_needs_enabled": survival_enabled,
            "finance_investing_enabled": finance_enabled,
            "reproduction_enabled": reproduction_enabled,
            "world_toolset_id": world_toolset["toolset_id"],
            "world_toolset_name": world_toolset["name"],
            "world_toolset_version": world_toolset["version"],
            "world_toolset_pack_id": world_toolset.get("pack_id"),
            "toolset_id": world_toolset["toolset_id"],
            "toolset_name": world_toolset["name"],
            "toolset_version": world_toolset["version"],
            "max_reaction_chain": settings.max_reaction_chain,
            "turn_minutes": settings.turn_minutes,
            "prompt_settings": _normalize_prompt_settings(payload.prompt_settings),
            "llm_generation": normalize_llm_generation(payload.llm_generation.model_dump() if payload.llm_generation else None),
            "agent_request_mode": payload.agent_request_mode,
            "event_display_mode": "batch" if payload.agent_request_mode == "parallel" else payload.event_display_mode,
            "llm_concurrency": _normalize_llm_concurrency(payload.llm_concurrency),
            "image_generation": normalize_image_generation_settings(payload.image_generation.model_dump() if payload.image_generation else None),
        },
    )
    db.add(world)
    db.flush()
    seed_world_content(db, world_id, worldview)
    for index in range(payload.agent_count):
        db.add(build_private_home_location(world_id, index, worldview))
    db.commit()

    providers = {provider.provider_id: provider for provider in payload.providers}
    if not providers:
        providers["default"] = ProviderConfigInput()
    stored_image_generation = _resolve_image_generation_settings(payload.image_generation, providers, payload.llm_generation, seed=payload.seed)
    narrator_config = payload.narrator_config
    narrator_enabled = bool(narrator_config and narrator_config.enabled)
    narrator_provider = providers.get(narrator_config.provider_id) if narrator_config else None
    narrator_provider = narrator_provider or next(iter(providers.values()))
    baby_model_pool = _baby_model_pool(payload, providers)
    world = _world_or_404(db, world_id)
    stored_narrator_config = None
    if narrator_enabled and narrator_config:
        narrator_model_name = _resolve_provider_model(
            narrator_provider,
            narrator_config.model_name,
            context="narrator",
            seed=payload.seed,
        )
        narrator_runtime = normalize_llm_runtime(
            None,
            retry_count=narrator_provider.retry_count,
            retry_interval_ms=narrator_provider.retry_interval_ms,
            request_timeout_ms=narrator_provider.request_timeout_ms,
            rpm=narrator_provider.rpm,
        )
        stored_narrator_config = {
            "provider_id": narrator_provider.provider_id,
            "provider_name": narrator_provider.name,
            "base_url": narrator_provider.base_url,
            "api_key": narrator_provider.api_key,
            "model_name": narrator_model_name,
            "system_prompt": narrator_config.system_prompt,
            "auto_frequency": narrator_config.auto_frequency,
            "llm_generation": normalize_llm_generation(
                narrator_config.llm_generation.model_dump() if narrator_config.llm_generation else (payload.llm_generation.model_dump() if payload.llm_generation else None)
            ),
            **narrator_runtime,
        }
    world.settings_json = {
        **(world.settings_json or {}),
        "image_generation": stored_image_generation,
        "narrator_enabled": narrator_enabled,
        "narrator_config": stored_narrator_config,
        "narrator_frequency": narrator_config.auto_frequency if narrator_config else "normal",
        "birth_enabled": reproduction_enabled,
        "baby_model_pool": baby_model_pool if reproduction_enabled else [],
    }
    db.commit()
    agent_plans = []
    reserved_names = {
        (config.chosen_name or "").strip()
        for config in payload.agent_configs[: payload.agent_count]
        if (config.chosen_name or "").strip()
    }
    for index in range(payload.agent_count):
        agent_config = payload.agent_configs[index] if index < len(payload.agent_configs) else AgentConfigInput()
        provider_config = providers.get(agent_config.provider_id) or next(iter(providers.values()))
        model_name = _resolve_provider_model(
            provider_config,
            agent_config.model_name,
            context=f"agent:{index}",
            seed=payload.seed,
        )
        own_preset_name = (agent_config.chosen_name or "").strip()
        agent_plans.append((index, agent_config, provider_config, model_name))

    identity_drafts = await asyncio.gather(
        *[
            prepare_identity_draft(
                world_id=world_id,
                world_seed=payload.seed,
                index=index,
                taken_names=reserved_names - ({own_preset_name} if own_preset_name else set()),
                model_alias=choose_model_alias(index),
                model_name=model_name,
                base_url=provider_config.base_url,
                api_key=provider_config.api_key,
                llm_retry_count=provider_config.retry_count,
                llm_retry_interval_ms=provider_config.retry_interval_ms,
                llm_request_timeout_ms=provider_config.request_timeout_ms,
                llm_rpm=provider_config.rpm,
                language=normalize_language(payload.language),
                custom_system_prompt=agent_config.system_prompt,
                collective_core_prompt=payload.collective_core_prompt,
                preset_name=agent_config.chosen_name,
                preset_appearance=agent_config.appearance,
                avatar_data_url=agent_config.avatar_data_url,
                user_trait_sliders=agent_config.trait_sliders,
            )
            for index, agent_config, provider_config, model_name in agent_plans
            for own_preset_name in [(agent_config.chosen_name or "").strip()]
        ]
    )
    created_agents: list[Agent] = []
    image_agent_aliases: dict[str, str] = {}
    for (index, agent_config, provider_config, model_name), identity_draft in zip(agent_plans, identity_drafts, strict=True):
        world = _world_or_404(db, world_id)
        home_location_id = private_home_location_id(world_id, index, worldview)
        initial_location_id = _agent_initial_location_id(world_id, index, worldview, defaults, db)
        agent = await create_agent_with_identity(
            db,
            world,
            index=index,
            model_alias=choose_model_alias(index),
            initial_location_id=initial_location_id,
            provider_id=provider_config.provider_id,
            provider_name=provider_config.name,
            model_name=model_name,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            llm_retry_count=provider_config.retry_count,
            llm_retry_interval_ms=provider_config.retry_interval_ms,
            llm_request_timeout_ms=provider_config.request_timeout_ms,
            llm_rpm=provider_config.rpm,
            language=normalize_language(payload.language),
            custom_system_prompt=agent_config.system_prompt,
            collective_core_prompt=payload.collective_core_prompt,
            preset_name=agent_config.chosen_name,
            preset_appearance=agent_config.appearance,
            avatar_data_url=agent_config.avatar_data_url,
            trait_mode=agent_config.trait_mode or payload.trait_mode,
            trait_budget=payload.trait_budget,
            user_trait_sliders=agent_config.trait_sliders,
            tool_context_mode=agent_config.tool_context_mode,
            agent_toolset_ids=agent_config.agent_toolset_ids,
            prepared_identity=identity_draft,
        )
        learning_json = dict(agent.tool_learning_json or {})
        if agent_config.llm_generation is not None:
            learning_json["llm_generation"] = normalize_llm_generation(agent_config.llm_generation.model_dump())
        if isinstance(agent_config.tts_config, dict):
            learning_json["tts_config"] = _normalize_tts_config(agent_config.tts_config)
        if learning_json != (agent.tool_learning_json or {}):
            agent.tool_learning_json = learning_json
        if agent_config.standing_image_data_url:
            avatar_hint = dict(agent.avatar_hint_json or {})
            avatar_hint["standing_image_data_url"] = agent_config.standing_image_data_url
            avatar_hint["standing_image_source"] = "user_config"
            agent.avatar_hint_json = avatar_hint
        image_prompt_name = (agent_config.image_prompt_name or "").strip()
        if image_prompt_name:
            image_agent_aliases[agent.agent_id] = image_prompt_name
        agent.wallet_json = {
            **(agent.wallet_json or {}),
            "money": int(profile_for_world(world)["start_money"]),
            "housing": {
                **((agent.wallet_json or {}).get("housing") or {}),
                "home_location_id": home_location_id,
                "rent_per_10_days": int(profile_for_world(world)["rent_per_10"]),
                "rent_grace_days": int(profile_for_world(world)["rent_grace_days"]),
            },
        }
        initial_location = db.get(Location, initial_location_id)
        create_event(
            db,
            world=world,
            event_type="birth",
            actor_agent_id=agent.agent_id,
            location_id=initial_location_id,
            importance=70,
            color_class="important",
            viewer_text=_birth_event_text(agent.chosen_name, initial_location, home_location_id, payload.language),
            payload={"model_alias": agent.model_alias, "worldview_id": worldview["worldview_id"], "home_location_id": home_location_id},
        )
        db.commit()
        created_agents.append(agent)
        await manager.broadcast(world_id, {"type": "agent_updated", "agent_id": agent.agent_id})
    world = _world_or_404(db, world_id)
    if image_agent_aliases:
        settings_json = dict(world.settings_json or {})
        image_generation = normalize_image_generation_settings(settings_json.get("image_generation"))
        aliases = dict(image_generation.get("agent_aliases") or {})
        aliases.update(image_agent_aliases)
        image_generation["agent_aliases"] = aliases
        settings_json["image_generation"] = image_generation
        world.settings_json = settings_json
    _apply_initial_agent_knowledge(db, world, created_agents, payload.agent_configs)
    db.commit()
    if (world.settings_json or {}).get("werewolf_mode_enabled"):
        initialize_werewolf_game(db, world)
        db.commit()
        world = _world_or_404(db, world_id)
    await manager.broadcast(world_id, {"type": "world_state_updated", "world": world_summary(world, db)})
    return world_summary(world, db)


@router.get("")
def list_worlds(
    limit: int = 20,
    offset: int = 0,
    q: str = "",
    status: str = "",
    worldview_id: str = "",
    sort: str = "recent",
    db: Session = Depends(get_db),
) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    worlds = list(db.execute(select(World)).scalars())
    summaries: list[dict] = []
    status_changed = False
    for world in worlds:
        summary = world_summary(world, db, include_settings=False)
        if summary["status"] == "running" and not simulation_manager.is_running(world.world_id):
            summary["status"] = "paused"
            if world.status != "paused":
                world.status = "paused"
                status_changed = True
        summaries.append(summary)
    if status_changed:
        db.commit()
    query = q.strip().lower()
    if query:
        summaries = [
            item
            for item in summaries
            if query in " ".join([
                str(item.get("save_name") or ""),
                str(item.get("name") or ""),
                str((item.get("settings") or {}).get("worldview_name") or ""),
                str((item.get("settings") or {}).get("worldview_id") or ""),
            ]).lower()
        ]
    if status:
        summaries = [item for item in summaries if item.get("status") == status]
    if worldview_id:
        summaries = [item for item in summaries if (item.get("settings") or {}).get("worldview_id") == worldview_id]
    if sort == "time_asc":
        summaries.sort(key=lambda item: int(item.get("current_world_time_minutes") or 0))
    elif sort == "name":
        summaries.sort(key=lambda item: str(item.get("save_name") or item.get("name") or ""))
    elif sort == "updated":
        summaries.sort(key=lambda item: int(item.get("current_world_time_minutes") or 0), reverse=True)
    else:
        summaries.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    total = len(summaries)
    return {"worlds": summaries[offset:offset + limit], "total": total, "limit": limit, "offset": offset}


@router.patch("/{world_id}/save-name")
async def update_world_save_name(world_id: str, payload: SaveNameUpdateRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    save_name = payload.save_name.strip()
    settings_json = dict(world.settings_json or {})
    if save_name:
        settings_json["save_name"] = save_name
    else:
        settings_json.pop("save_name", None)
    world.settings_json = settings_json
    db.commit()
    db.refresh(world)
    summary = world_summary(world, db)
    await manager.broadcast(world_id, {"type": "world_settings_updated", "world": summary})
    return summary


@router.delete("/{world_id}")
async def delete_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    _world_or_404(db, world_id)
    await simulation_manager.stop(world_id)
    deleted = _delete_world_rows(db, world_id)
    db.commit()
    return {"ok": True, "world_id": world_id, "deleted": deleted}


@router.patch("/{world_id}/runtime-settings")
async def update_world_runtime_settings(world_id: str, payload: WorldRuntimeSettingsUpdateRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    settings_json = dict(world.settings_json or {})
    changed = False
    if payload.collective_core_prompt is not None:
        settings_json["collective_core_prompt"] = payload.collective_core_prompt.strip()
        changed = True
    if payload.speed is not None:
        settings_json["speed"] = payload.speed
        changed = True
    if payload.narrator_frequency is not None:
        settings_json["narrator_frequency"] = payload.narrator_frequency
        narrator_config = dict(settings_json.get("narrator_config") or {})
        if narrator_config:
            narrator_config["auto_frequency"] = payload.narrator_frequency
            settings_json["narrator_config"] = narrator_config
        changed = True
    if payload.narrator_config is not None:
        settings_json = _apply_runtime_narrator_config(settings_json, payload.narrator_config)
        changed = True
    if payload.prompt_settings is not None:
        settings_json["prompt_settings"] = _normalize_prompt_settings(payload.prompt_settings)
        changed = True
    if payload.agent_request_mode is not None:
        settings_json["agent_request_mode"] = payload.agent_request_mode
        if payload.agent_request_mode == "parallel":
            settings_json["event_display_mode"] = "batch"
        changed = True
    if payload.event_display_mode is not None:
        request_mode = str(settings_json.get("agent_request_mode") or "serial")
        settings_json["event_display_mode"] = "batch" if request_mode == "parallel" else payload.event_display_mode
        changed = True
    if payload.llm_generation is not None:
        settings_json["llm_generation"] = normalize_llm_generation(payload.llm_generation.model_dump())
        changed = True
    if payload.llm_concurrency is not None:
        settings_json["llm_concurrency"] = _normalize_llm_concurrency(payload.llm_concurrency)
        changed = True
    if payload.image_generation is not None:
        settings_json["image_generation"] = normalize_image_generation_settings(
            payload.image_generation.model_dump(exclude_unset=True),
            settings_json.get("image_generation") if isinstance(settings_json.get("image_generation"), dict) else None,
        )
        changed = True
        if not settings_json["image_generation"].get("enabled"):
            # Switching narrator image generation off mid-run must stop already
            # queued renders too, otherwise pending images keep appearing.
            world.settings_json = settings_json
            await cancel_pending_image_generations(db, world)
            settings_json = dict(world.settings_json or {})
    if payload.disabled_tool_modules is not None:
        from app.tools.registry import TOGGLEABLE_TOOL_MODULES

        settings_json["disabled_tool_modules"] = sorted(
            {m for m in payload.disabled_tool_modules if m in TOGGLEABLE_TOOL_MODULES}
        )
        changed = True
    if changed:
        world.settings_json = settings_json
        db.commit()
        db.refresh(world)
        await manager.broadcast(world_id, {"type": "world_settings_updated", "world": world_summary(world, db)})
    return world_summary(world, db)


@router.get("/{world_id}/model-usage")
def get_world_model_usage(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    return {"entries": _world_model_usage_entries(db, world)}


@router.post("/{world_id}/interventions")
async def apply_world_intervention(world_id: str, payload: WorldInterventionRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    if world.status == "ended":
        raise HTTPException(400, "world ended")
    actor = db.get(Agent, payload.actor_agent_id) if payload.actor_agent_id else None
    target = db.get(Agent, payload.target_agent_id) if payload.target_agent_id else None
    if payload.actor_agent_id and (not actor or actor.world_id != world_id):
        raise HTTPException(404, "actor not found")
    if payload.target_agent_id and (not target or target.world_id != world_id):
        raise HTTPException(404, "target not found")
    location = db.get(Location, payload.location_id) if payload.location_id else None
    if payload.location_id and (not location or location.world_id != world_id):
        raise HTTPException(404, "location not found")

    event_ids: list[int] = []
    note = (payload.note or "").strip()

    if payload.action == "move_agent":
        if not actor or not location:
            raise HTTPException(400, "move_agent requires actor_agent_id and location_id")
        if actor.location:
            actor.location.location_id = location.location_id
            actor.location.arrived_at_world_time = world.current_world_time_minutes
        else:
            db.add(AgentLocation(agent_id=actor.agent_id, location_id=location.location_id, arrived_at_world_time=world.current_world_time_minutes))
        text = f"{actor.chosen_name} 恍惚了一瞬，回过神时已经站在{location.public_name}。"
        if note:
            text += f" {note}"
        event = create_event(
            db,
            world=world,
            event_type="player_intervention_move",
            actor_agent_id=actor.agent_id,
            location_id=location.location_id,
            viewer_text=text,
            importance=65,
            color_class="important",
            payload={"intervention": "move_agent", "actor_agent_id": actor.agent_id, "location_id": location.location_id},
        )
        event_ids.append(event.event_id)

    elif payload.action == "meteor_kill":
        if not actor:
            raise HTTPException(400, "meteor_kill requires actor_agent_id")
        before = actor.dynamic_state.health if actor.dynamic_state else None
        if actor.dynamic_state:
            actor.dynamic_state.health = 0
            actor.dynamic_state.energy = 0
            actor.dynamic_state.critical_reason = "陨石坠落"
        actor.lifecycle_state = "dead"
        actor.death_at_world_time = world.current_world_time_minutes
        actor.death_cause = "陨石坠落"
        text = f"天光忽然撕开一瞬，一块陨石坠下，{actor.chosen_name} 当场死亡。"
        if note:
            text += f" {note}"
        event = create_event(
            db,
            world=world,
            event_type="death",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=text,
            importance=100,
            color_class="danger",
            payload={"death_cause": "meteor", "intervention": "meteor_kill"},
            state_delta={actor.agent_id: {"health": {"before": before, "after": 0}}},
        )
        event_ids.append(event.event_id)

    elif payload.action in {"love_one_way", "love_mutual"}:
        if not actor or not target:
            raise HTTPException(400, "love intervention requires actor_agent_id and target_agent_id")
        ensure_v5_agent_state(actor)
        ensure_v5_agent_state(target)
        adjust_relationship(db, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=18, trust=12, affection=60, conflict=-8, fear=-5)
        set_intervention_crush(actor, target, world.current_world_time_minutes)
        if actor.dynamic_state:
            apply_delta(actor.dynamic_state, social=4, fun=10, stress=-3, mood=10)
        if payload.action == "love_mutual":
            adjust_relationship(db, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=18, trust=12, affection=60, conflict=-8, fear=-5)
            set_intervention_crush(target, actor, world.current_world_time_minutes)
            if target.dynamic_state:
                apply_delta(target.dynamic_state, social=4, fun=10, stress=-3, mood=10)
            text = f"{actor.chosen_name} 和 {target.chosen_name} 忽然对彼此生出强烈的心动，像是一场不讲道理的一见钟情。"
        else:
            text = f"{actor.chosen_name} 忽然对 {target.chosen_name} 心动得厉害，像被某个瞬间轻轻击中了。"
        if note:
            text += f" {note}"
        event = create_event(
            db,
            world=world,
            event_type="player_intervention_love",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=text,
            importance=85,
            color_class="important",
            payload={"intervention": payload.action, "intervention_crush": True, "crush_duration_minutes": INTERVENTION_CRUSH_DURATION_MINUTES},
        )
        event_ids.append(event.event_id)

    elif payload.action in {"miracle_pregnancy", "miracle_birth"}:
        if not actor:
            raise HTTPException(400, "pregnancy intervention requires actor_agent_id")
        ensure_v5_agent_state(actor)
        existing_pregnancy = (actor.family_json or {}).get("pregnancy_state") if isinstance((actor.family_json or {}).get("pregnancy_state"), dict) else {}
        co_parent_id = target.agent_id if target else existing_pregnancy.get("co_parent_agent_id")
        co_parent = target or (db.get(Agent, co_parent_id) if co_parent_id else None)
        pregnancy = {
            "pregnant": True,
            "co_parent_agent_id": co_parent_id,
            "started_world_time": world.current_world_time_minutes,
            "due_world_time": world.current_world_time_minutes if payload.action == "miracle_birth" else world.current_world_time_minutes + max(1, int((world.settings_json or {}).get("pregnancy_duration_days") or 3)) * 1440,
            "discovered": True,
            "source": "miracle_intervention",
        }
        actor.family_json = {**(actor.family_json or {}), "pregnancy_state": pregnancy}
        if payload.action == "miracle_birth":
            birth_event = await _create_child_from_birth(db, world, actor, pregnancy)
            birth_event.payload = {
                **(birth_event.payload or {}),
                "intervention": "miracle_birth",
                "pregnant_agent_id": actor.agent_id,
                "pregnant_agent_name": actor.chosen_name,
                "partner_agent_id": co_parent_id,
                "partner_agent_name": co_parent.chosen_name if co_parent else None,
            }
            event_ids.append(birth_event.event_id)
        else:
            partner_text = f"，伴侣是 {co_parent.chosen_name}" if co_parent else ""
            text = f"怀孕人 {actor.chosen_name}{partner_text}，忽然意识到自己孕育着一个新生命，像是无法解释的奇迹。"
            if note:
                text += f" {note}"
            event = create_event(
                db,
                world=world,
                event_type="pregnancy_started",
                actor_agent_id=actor.agent_id,
                target_agent_id=co_parent_id,
                location_id=actor.location.location_id if actor.location else None,
                viewer_text=text,
                importance=90,
                color_class="important",
                payload={
                    "intervention": "miracle_pregnancy",
                    "pregnant_agent_id": actor.agent_id,
                    "pregnant_agent_name": actor.chosen_name,
                    "partner_agent_id": co_parent_id,
                    "partner_agent_name": co_parent.chosen_name if co_parent else None,
                },
            )
            event_ids.append(event.event_id)

    else:
        from app.content.intervention_abilities import apply_intervention_ability

        try:
            plugin_event_ids = apply_intervention_ability(
                db,
                world,
                ability_id=payload.action,
                actor=actor,
                target=target,
                location=location,
                note=note,
            )
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc
        if plugin_event_ids is None:
            raise HTTPException(400, f"unknown intervention action: {payload.action}")
        event_ids.extend(plugin_event_ids)

    db.commit()
    await manager.broadcast(world_id, {"type": "world_state_updated", "world": world_summary(world, db), "event_ids": event_ids, "left_snapshot": build_left_snapshot(db, world_id)})
    return {"ok": True, "event_ids": event_ids, "world": world_summary(world, db)}


@router.get("/{world_id}")
def get_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = db.get(World, world_id)
    if not world:
        raise HTTPException(404, "world not found")
    _sync_runtime_status(db, world)
    return world_summary(world, db)


@router.get("/{world_id}/left-snapshot")
def get_left_snapshot(world_id: str, include_private: bool = False, db: Session = Depends(get_db)) -> dict:
    """Return the same state snapshot that is attached to event refreshes."""
    world = _world_or_404(db, world_id)
    _sync_runtime_status(db, world)
    try:
        return build_left_snapshot(db, world_id, include_private=include_private)
    except LookupError as exc:
        raise HTTPException(404, "world not found") from exc


@router.get("/{world_id}/locations")
def list_locations(world_id: str, include_private: bool = False, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    rows = list(db.execute(select(Location).where(Location.world_id == world_id)).scalars())
    order = {str(location_id): index for index, location_id in enumerate((world.settings_json or {}).get("worldview_locations") or [])}
    rows.sort(key=lambda loc: (order.get(loc.location_id, 10_000), loc.public_name))
    payload = []
    for location in rows:
        item = location_to_dict(location, db)
        if not include_private and item["is_private"]:
            continue
        # location_to_dict already includes occupant_count and an occupant list.
        payload.append(item)
    return {"locations": payload}


@router.post("/{world_id}/start")
async def start_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    _reset_llm_failure_retry_window(db, world)
    world.status = "running"
    db.commit()
    simulation_manager.start(world_id, world.settings_json.get("speed", settings.simulation_speed))
    await manager.broadcast(world_id, {"type": "simulation_status_changed", "status": "running", "world": world_summary(world, db), "left_snapshot": build_left_snapshot(db, world_id)})
    return world_summary(world, db)


@router.post("/{world_id}/pause")
async def pause_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    world.status = "paused"
    db.commit()
    await simulation_manager.pause(world_id)
    await manager.broadcast(world_id, {"type": "simulation_status_changed", "status": "paused", "world": world_summary(world, db), "left_snapshot": build_left_snapshot(db, world_id)})
    return world_summary(world, db)


@router.post("/{world_id}/resume")
async def resume_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    return await start_world(world_id, db)


def _reset_llm_failure_retry_window(db: Session, world: World) -> int:
    """Manual start/resume means the user wants another provider retry window."""
    reset_count = 0
    agents = db.execute(select(Agent).where(Agent.world_id == world.world_id)).scalars()
    for agent in agents:
        learning = dict(agent.tool_learning_json or {})
        if int(learning.get("llm_consecutive_failures") or 0) <= 0:
            continue
        learning["llm_consecutive_failures"] = 0
        learning["llm_manual_retry_world_time"] = int(world.current_world_time_minutes or 0)
        agent.tool_learning_json = learning
        reset_count += 1
    return reset_count


@router.post("/{world_id}/step")
async def step_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    if world.status == "ended":
        raise HTTPException(400, "world ended")
    if world.status == "running" or simulation_manager.is_running(world_id):
        raise HTTPException(409, "world is running; pause before single step")
    _reset_llm_failure_retry_window(db, world)
    world.status = "paused"
    db.commit()
    result = await simulation_manager.step(world_id)
    db.expire_all()
    latest_world = _world_or_404(db, world_id)
    await manager.broadcast(world_id, {"type": "world_state_updated", "world_id": world_id, "result": result, "world": world_summary(latest_world, db), "left_snapshot": build_left_snapshot(db, world_id)})
    return result


@router.post("/{world_id}/end")
async def end_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    await simulation_manager.stop(world_id)
    world.status = "ended"
    world.ended_at = datetime.now(timezone.utc)
    await create_narration(db, world, [], trigger_type="final")
    db.commit()
    zip_path = export_world_zip(db, world_id)
    await manager.broadcast(world_id, {"type": "export_ready", "world_id": world_id})
    return {"world": world_summary(world, db), "export_path": str(zip_path)}


def _event_delete_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_EVENT_DELETE_UNDO_LIMIT
    return max(0, min(limit, MAX_EVENT_DELETE_UNDO_LIMIT))


def _event_delete_settings(world: World) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    settings_json = dict(world.settings_json or {})
    stack = settings_json.get(EVENT_DELETE_UNDO_STACK_KEY)
    if not isinstance(stack, list):
        stack = []
    else:
        stack = [batch for batch in stack if isinstance(batch, dict)]
    limit = _event_delete_limit(settings_json.get(EVENT_DELETE_UNDO_LIMIT_KEY, DEFAULT_EVENT_DELETE_UNDO_LIMIT))
    stack = stack[-limit:] if limit > 0 else []
    settings_json[EVENT_DELETE_UNDO_STACK_KEY] = stack
    settings_json[EVENT_DELETE_UNDO_LIMIT_KEY] = limit
    return settings_json, stack, limit


def _event_delete_state_payload(world: World) -> dict[str, Any]:
    _settings_json, stack, limit = _event_delete_settings(world)
    latest = stack[-1] if stack else {}
    latest_events = latest.get("events") if isinstance(latest.get("events"), list) else []
    return {
        "undo_available": bool(stack),
        "undo_count": len(stack),
        "undo_limit": limit,
        "latest_batch": {
            "batch_id": latest.get("batch_id"),
            "deleted_at": latest.get("deleted_at"),
            "event_count": len(latest_events),
        } if stack else None,
    }


def _snapshot_event(event: Event) -> dict[str, Any]:
    return {
        "event_id": int(event.event_id),
        "world_id": event.world_id,
        "world_time": int(event.world_time or 0),
        "real_created_at": event.real_created_at.isoformat() if event.real_created_at else None,
        "event_type": event.event_type,
        "actor_agent_id": event.actor_agent_id,
        "target_agent_id": event.target_agent_id,
        "location_id": event.location_id,
        "visibility_scope": event.visibility_scope,
        "importance": int(event.importance or 0),
        "color_class": event.color_class,
        "viewer_text": event.viewer_text,
        "agent_visible_text": event.agent_visible_text,
        "payload": event.payload or {},
        "state_delta": event.state_delta or {},
        "no_state_changed": bool(event.no_state_changed),
    }


def _snapshot_conversation(conversation: Conversation) -> dict[str, Any]:
    return {
        "utterance_id": int(conversation.utterance_id),
        "event_id": int(conversation.event_id),
        "speaker_agent_id": conversation.speaker_agent_id,
        "target_agent_id": conversation.target_agent_id,
        "location_id": conversation.location_id,
        "content_zh": conversation.content_zh,
        "tone": conversation.tone,
        "is_identity_reveal": bool(conversation.is_identity_reveal),
        "heard_by_agent_ids_json": list(conversation.heard_by_agent_ids_json or []),
        "world_time": int(conversation.world_time or 0),
    }


def _parse_event_datetime(value: Any) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _restore_event_from_snapshot(world_id: str, snapshot: dict[str, Any], *, event_id: int | None) -> Event:
    data: dict[str, Any] = {
        "world_id": world_id,
        "world_time": int(snapshot.get("world_time") or 0),
        "real_created_at": _parse_event_datetime(snapshot.get("real_created_at")),
        "event_type": str(snapshot.get("event_type") or "event"),
        "actor_agent_id": snapshot.get("actor_agent_id") if isinstance(snapshot.get("actor_agent_id"), str) else None,
        "target_agent_id": snapshot.get("target_agent_id") if isinstance(snapshot.get("target_agent_id"), str) else None,
        "location_id": snapshot.get("location_id") if isinstance(snapshot.get("location_id"), str) else None,
        "visibility_scope": str(snapshot.get("visibility_scope") or "public"),
        "importance": int(snapshot.get("importance") or 0),
        "color_class": str(snapshot.get("color_class") or "normal"),
        "viewer_text": str(snapshot.get("viewer_text") or ""),
        "agent_visible_text": str(snapshot.get("agent_visible_text") or snapshot.get("viewer_text") or ""),
        "payload": snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {},
        "state_delta": snapshot.get("state_delta") if isinstance(snapshot.get("state_delta"), dict) else {},
        "no_state_changed": bool(snapshot.get("no_state_changed")),
    }
    if event_id is not None:
        data["event_id"] = event_id
    return Event(**data)


def _restore_conversation_from_snapshot(snapshot: dict[str, Any], event_id_map: dict[int, int], db: Session) -> int | None:
    try:
        original_event_id = int(snapshot.get("event_id") or 0)
    except (TypeError, ValueError):
        return None
    restored_event_id = event_id_map.get(original_event_id)
    if not restored_event_id:
        return None
    try:
        original_utterance_id = int(snapshot.get("utterance_id") or 0)
    except (TypeError, ValueError):
        original_utterance_id = 0
    data: dict[str, Any] = {
        "event_id": restored_event_id,
        "speaker_agent_id": str(snapshot.get("speaker_agent_id") or ""),
        "target_agent_id": snapshot.get("target_agent_id") if isinstance(snapshot.get("target_agent_id"), str) else None,
        "location_id": snapshot.get("location_id") if isinstance(snapshot.get("location_id"), str) else None,
        "content_zh": str(snapshot.get("content_zh") or ""),
        "tone": str(snapshot.get("tone") or "neutral"),
        "is_identity_reveal": bool(snapshot.get("is_identity_reveal")),
        "heard_by_agent_ids_json": snapshot.get("heard_by_agent_ids_json") if isinstance(snapshot.get("heard_by_agent_ids_json"), list) else [],
        "world_time": int(snapshot.get("world_time") or 0),
    }
    if original_utterance_id and db.get(Conversation, original_utterance_id) is None:
        data["utterance_id"] = original_utterance_id
    conversation = Conversation(**data)
    db.add(conversation)
    db.flush()
    return int(conversation.utterance_id)


@router.get("/{world_id}/events")
def list_events(
    world_id: str,
    after_event_id: int | None = None,
    limit: int = 100,
    min_importance: int = 0,
    agent_id: str | None = None,
    location_id: str | None = None,
    start_event_id: int | None = None,
    end_event_id: int | None = None,
    dialogue_only: bool = False,
    show_narrator: bool = True,
    event_type: str | None = None,
    include_debug: bool = False,
    latest: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    world = _world_or_404(db, world_id)
    stmt = select(Event).where(Event.world_id == world_id)
    wait_cutoff_event_id = _pending_image_wait_cutoff(db, world)
    if wait_cutoff_event_id and not include_debug:
        stmt = stmt.where(Event.event_id <= wait_cutoff_event_id)
    if after_event_id:
        stmt = stmt.where(Event.event_id > after_event_id)
    if start_event_id:
        stmt = stmt.where(Event.event_id >= start_event_id)
    if end_event_id:
        stmt = stmt.where(Event.event_id <= end_event_id)
    if min_importance:
        stmt = stmt.where(or_(Event.importance >= min_importance, _speech_event_condition()))
        stmt = stmt.where(Event.event_type.not_in(TRIVIAL_CONFIG_EVENT_TYPES))
    if agent_id:
        stmt = stmt.where((Event.actor_agent_id == agent_id) | (Event.target_agent_id == agent_id))
    if location_id:
        stmt = stmt.where(Event.location_id == location_id)
    if dialogue_only:
        stmt = stmt.where(_speech_event_condition())
    elif not show_narrator:
        stmt = stmt.where(Event.event_type.not_in(["narration", "image_generation"]))
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if not include_debug:
        stmt = stmt.where(
            Event.visibility_scope != "system",
            Event.event_type.not_in(["candidate_request", "tool_failed", "nothing"]),
        )
    limit = max(1, min(limit, 10000))
    if after_event_id:
        events = list(db.execute(stmt.order_by(*chronological_order_asc()).limit(limit)).scalars())
    elif latest:
        events = sort_chronologically(list(db.execute(stmt.order_by(*chronological_order_desc()).limit(limit)).scalars()))
    else:
        events = list(db.execute(stmt.order_by(*chronological_order_asc()).limit(limit)).scalars())
    return {
        "events": [event_to_dict(event, db, include_debug=include_debug) for event in events],
        "image_wait_cutoff_event_id": wait_cutoff_event_id,
        "waiting_image_event_id": wait_cutoff_event_id,
        "left_snapshot": build_left_snapshot(db, world_id),
    }


@router.get("/{world_id}/refresh")
def refresh_world_state(
    world_id: str,
    after_event_id: int | None = None,
    limit: int = 100,
    min_importance: int = 0,
    agent_id: str | None = None,
    location_id: str | None = None,
    start_event_id: int | None = None,
    end_event_id: int | None = None,
    dialogue_only: bool = False,
    show_narrator: bool = True,
    event_type: str | None = None,
    include_debug: bool = False,
    latest: bool = True,
    include_private: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Return the event feed and the whole left-rail state from one DB view.

    The event feed has always refreshed reliably, while the left rail previously
    depended on several independent requests whose responses could arrive in a
    different order. This endpoint deliberately makes the main refresh one
    atomic UI payload: full world summary, events, left snapshot, and event delete
    state all come from the same request/session.
    """
    world = _world_or_404(db, world_id)
    _sync_runtime_status(db, world)
    event_payload = list_events(
        world_id,
        after_event_id=after_event_id,
        limit=limit,
        min_importance=min_importance,
        agent_id=agent_id,
        location_id=location_id,
        start_event_id=start_event_id,
        end_event_id=end_event_id,
        dialogue_only=dialogue_only,
        show_narrator=show_narrator,
        event_type=event_type,
        include_debug=include_debug,
        latest=latest,
        db=db,
    )
    left_snapshot = build_left_snapshot(db, world_id, include_private=include_private)
    return {
        **event_payload,
        "left_snapshot": left_snapshot,
        "world": left_snapshot.get("world") or world_summary(world, db),
        "agents": left_snapshot.get("agents") or [],
        "locations": left_snapshot.get("locations") or [],
        "event_delete_state": _event_delete_state_payload(world),
    }


@router.get("/{world_id}/events/delete-state")
def get_event_delete_state(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    return _event_delete_state_payload(world)


@router.patch("/{world_id}/events/delete-state")
async def update_event_delete_state(
    world_id: str,
    payload: EventDeleteUndoLimitRequest,
    db: Session = Depends(get_db),
) -> dict:
    world = _world_or_404(db, world_id)
    settings_json, stack, _limit = _event_delete_settings(world)
    limit = _event_delete_limit(payload.limit)
    settings_json[EVENT_DELETE_UNDO_LIMIT_KEY] = limit
    settings_json[EVENT_DELETE_UNDO_STACK_KEY] = stack[-limit:] if limit > 0 else []
    world.settings_json = settings_json
    db.commit()
    await manager.broadcast(world_id, {"type": "event_delete_state_updated", "world_id": world_id})
    return _event_delete_state_payload(world)


@router.post("/{world_id}/events/delete")
async def delete_events(
    world_id: str,
    payload: EventDeleteRequest,
    db: Session = Depends(get_db),
    _lock: None = Depends(world_mutation_guard),
) -> dict:
    world = _world_or_404(db, world_id)
    event_ids = sorted({int(event_id) for event_id in payload.event_ids if int(event_id) > 0})
    if not event_ids:
        raise HTTPException(400, "event_ids is required")

    events = sort_chronologically(
        list(db.execute(select(Event).where(Event.world_id == world_id, Event.event_id.in_(event_ids))).scalars())
    )
    if not events:
        raise HTTPException(404, "events not found")

    found_event_ids = [int(event.event_id) for event in events]
    conversations = list(db.execute(select(Conversation).where(Conversation.event_id.in_(found_event_ids))).scalars())
    memories = list(db.execute(select(Memory).where(Memory.source_event_id.in_(found_event_ids))).scalars())
    items = list(db.execute(select(Item).where(Item.created_event_id.in_(found_event_ids))).scalars())
    batch = {
        "batch_id": uuid.uuid4().hex,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "events": [_snapshot_event(event) for event in events],
        "conversations": [_snapshot_conversation(conversation) for conversation in conversations],
        "memory_refs": [
            {"memory_id": int(memory.memory_id), "source_event_id": int(memory.source_event_id)}
            for memory in memories
            if memory.source_event_id is not None
        ],
        "item_refs": [
            {"item_id": item.item_id, "created_event_id": int(item.created_event_id)}
            for item in items
            if item.created_event_id is not None
        ],
    }

    settings_json, stack, limit = _event_delete_settings(world)
    if limit > 0:
        stack.append(batch)
        stack = stack[-limit:]
    else:
        stack = []
    settings_json[EVENT_DELETE_UNDO_STACK_KEY] = stack
    settings_json[EVENT_DELETE_UNDO_LIMIT_KEY] = limit
    world.settings_json = settings_json

    for conversation in conversations:
        db.delete(conversation)
    for memory in memories:
        memory.source_event_id = None
    for item in items:
        item.created_event_id = None
    for event in events:
        db.delete(event)
    db.commit()
    await manager.broadcast(world_id, {"type": "events_changed", "world_id": world_id, "deleted_event_ids": found_event_ids})
    return {
        "ok": True,
        "deleted_event_ids": found_event_ids,
        **_event_delete_state_payload(world),
    }


@router.patch("/{world_id}/events/{event_id}")
async def update_event_text(
    world_id: str,
    event_id: int,
    payload: EventTextUpdateRequest,
    db: Session = Depends(get_db),
) -> dict:
    _world_or_404(db, world_id)
    event = db.get(Event, event_id)
    if not event or event.world_id != world_id:
        raise HTTPException(404, "event not found")
    if event.event_type != "narration":
        raise HTTPException(400, "only narration events can be edited")
    title, narration, viewer_text = _narration_edit_parts(event, payload.text)
    event.viewer_text = viewer_text
    event.agent_visible_text = viewer_text
    event.payload = {
        **dict(event.payload or {}),
        "summary_title": title,
        "narration": narration,
        "edited": True,
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    narrator_run_id = event.payload.get("narrator_run_id") if isinstance(event.payload, dict) else None
    try:
        narrator_run_pk = int(narrator_run_id)
    except (TypeError, ValueError):
        narrator_run_pk = 0
    if narrator_run_pk:
        run = db.get(NarratorRun, narrator_run_pk)
        if run and run.world_id == world_id:
            run.summary_title = title
            run.narration = narration
    db.commit()
    await manager.broadcast(world_id, {"type": "events_changed", "world_id": world_id, "updated_event_ids": [event.event_id]})
    return {"ok": True, "event": event_to_dict(event, db)}


@router.post("/{world_id}/events/undo-delete")
async def undo_delete_events(world_id: str, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    settings_json, stack, limit = _event_delete_settings(world)
    if not stack:
        raise HTTPException(400, "no deleted events to undo")
    batch = stack.pop()
    event_snapshots = [snapshot for snapshot in batch.get("events", []) if isinstance(snapshot, dict)]
    conversation_snapshots = [snapshot for snapshot in batch.get("conversations", []) if isinstance(snapshot, dict)]
    event_id_map: dict[int, int] = {}
    restored_event_ids: list[int] = []
    restored_original_event_ids: list[int] = []
    remapped_event_ids: dict[str, int] = {}

    for snapshot in sorted(event_snapshots, key=lambda item: (int(item.get("world_time") or 0), int(item.get("event_id") or 0))):
        try:
            original_event_id = int(snapshot.get("event_id") or 0)
        except (TypeError, ValueError):
            continue
        explicit_event_id = original_event_id if original_event_id and db.get(Event, original_event_id) is None else None
        event = _restore_event_from_snapshot(world_id, snapshot, event_id=explicit_event_id)
        db.add(event)
        db.flush()
        event_id_map[original_event_id] = int(event.event_id)
        restored_original_event_ids.append(original_event_id)
        restored_event_ids.append(int(event.event_id))
        if original_event_id != int(event.event_id):
            remapped_event_ids[str(original_event_id)] = int(event.event_id)

    restored_utterance_ids: list[int] = []
    for snapshot in conversation_snapshots:
        utterance_id = _restore_conversation_from_snapshot(snapshot, event_id_map, db)
        if utterance_id is not None:
            restored_utterance_ids.append(utterance_id)

    for ref in batch.get("memory_refs", []):
        if not isinstance(ref, dict):
            continue
        try:
            memory_id = int(ref.get("memory_id") or 0)
            source_event_id = int(ref.get("source_event_id") or 0)
        except (TypeError, ValueError):
            continue
        memory = db.get(Memory, memory_id)
        restored_event_id = event_id_map.get(source_event_id)
        if memory and restored_event_id:
            memory.source_event_id = restored_event_id

    for ref in batch.get("item_refs", []):
        if not isinstance(ref, dict):
            continue
        item_id = ref.get("item_id")
        if not isinstance(item_id, str):
            continue
        try:
            created_event_id = int(ref.get("created_event_id") or 0)
        except (TypeError, ValueError):
            continue
        item = db.get(Item, item_id)
        restored_event_id = event_id_map.get(created_event_id)
        if item and restored_event_id:
            item.created_event_id = restored_event_id

    settings_json[EVENT_DELETE_UNDO_STACK_KEY] = stack[-limit:] if limit > 0 else []
    settings_json[EVENT_DELETE_UNDO_LIMIT_KEY] = limit
    world.settings_json = settings_json
    db.commit()
    await manager.broadcast(world_id, {"type": "events_changed", "world_id": world_id, "restored_event_ids": restored_event_ids})
    return {
        "ok": True,
        "restored_event_ids": restored_event_ids,
        "restored_original_event_ids": restored_original_event_ids,
        "remapped_event_ids": remapped_event_ids,
        "restored_utterance_ids": restored_utterance_ids,
        **_event_delete_state_payload(world),
    }


@router.post("/{world_id}/events/{event_id}/tts")
async def synthesize_event_tts(world_id: str, event_id: int, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    _world_or_404(db, world_id)
    event = db.get(Event, event_id)
    if not event or event.world_id != world_id:
        raise HTTPException(404, "event not found")
    payload = dict(event.payload or {})
    existing_audio = payload.get("tts_audio_data_url")
    if isinstance(existing_audio, str) and existing_audio.startswith("data:audio/"):
        return {"event_id": event.event_id, "audio_data_url": existing_audio, "cached": True}
    existing_audio_url = payload.get("tts_audio_url")
    if isinstance(existing_audio_url, str) and existing_audio_url:
        return {"event_id": event.event_id, "audio_data_url": existing_audio_url, "cached": True}
    existing_audio_key = payload.get("tts_audio_key")
    if isinstance(existing_audio_key, str) and existing_audio_key:
        return {"event_id": event.event_id, "audio_data_url": audio_url_for_key(existing_audio_key), "cached": True}
    speech = _speech_from_payload(payload)
    if not speech:
        raise HTTPException(400, "event has no speech text")
    actor = db.get(Agent, event.actor_agent_id) if event.actor_agent_id else None
    if not actor or actor.world_id != world_id:
        raise HTTPException(404, "speaker not found")
    tts_config = (actor.tool_learning_json or {}).get("tts_config")
    if not isinstance(tts_config, dict) or not tts_config.get("enabled"):
        raise HTTPException(400, "speaker has no enabled TTS config")
    audio_data_url = await _call_tts_provider(tts_config, speech)
    audio_storage = store_audio_data_url(audio_data_url)
    event.payload = {**payload, **audio_storage, "tts_speaker_agent_id": actor.agent_id}
    db.commit()
    await manager.broadcast(world_id, {"type": "events_changed", "world_id": world_id, "updated_event_ids": [event.event_id]})
    return {"event_id": event.event_id, "audio_data_url": audio_storage["tts_audio_url"], "cached": False}


@router.get("/{world_id}/events/export")
def export_events(
    world_id: str,
    min_importance: int = 0,
    agent_id: str | None = None,
    location_id: str | None = None,
    start_event_id: int | None = None,
    end_event_id: int | None = None,
    dialogue_only: bool = False,
    show_narrator: bool = True,
    include_avatars: bool = True,
    include_audio: bool = False,
    include_images: bool = False,
    db: Session = Depends(get_db),
) -> Response:
    world = _world_or_404(db, world_id)
    stmt = select(Event).where(Event.world_id == world_id, Event.visibility_scope != "system", Event.event_type != "candidate_request")
    if min_importance:
        stmt = stmt.where(or_(Event.importance >= min_importance, _speech_event_condition()))
    if agent_id:
        stmt = stmt.where((Event.actor_agent_id == agent_id) | (Event.target_agent_id == agent_id))
    if location_id:
        stmt = stmt.where(Event.location_id == location_id)
    if start_event_id:
        stmt = stmt.where(Event.event_id >= start_event_id)
    if end_event_id:
        stmt = stmt.where(Event.event_id <= end_event_id)
    if dialogue_only:
        stmt = stmt.where(_speech_event_condition())
    elif not show_narrator:
        stmt = stmt.where(Event.event_type != "narration")
    if min_importance:
        stmt = stmt.where(Event.event_type.not_in(TRIVIAL_CONFIG_EVENT_TYPES))
    events = list(db.execute(stmt.order_by(*chronological_order_asc())).scalars())
    content = build_event_archive_zip(db, world, events, include_avatars=include_avatars, include_audio=include_audio, include_images=include_images)
    filename = f"{world_id}_events_{start_event_id or 'start'}_{end_event_id or 'end'}.zip"
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{world_id}/agents/export")
def export_agent_presets(world_id: str, db: Session = Depends(get_db)) -> Response:
    world = _world_or_404(db, world_id)
    content = build_agent_preset_zip(db, world)
    filename = f"{world_id}_agent_presets.tlwagents.zip"
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{world_id}/conversations")
def list_conversations(world_id: str, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    _world_or_404(db, world_id)
    events = sort_chronologically(list(db.execute(select(Event).where(Event.world_id == world_id, _speech_event_condition()).order_by(*chronological_order_desc()).limit(limit)).scalars()))
    return {"events": [event_to_dict(event, db) for event in events]}


@router.get("/{world_id}/narrator")
def list_narrator(world_id: str, limit: int = 500, db: Session = Depends(get_db)) -> dict:
    _world_or_404(db, world_id)
    limit = max(1, min(2000, limit))
    runs = list(db.execute(select(NarratorRun).where(NarratorRun.world_id == world_id).order_by(NarratorRun.narrator_run_id.desc()).limit(limit)).scalars())[::-1]
    return {"narrations": [narrator_to_dict(run) for run in runs]}


@router.get("/{world_id}/metrics")
def world_metrics(world_id: str, db: Session = Depends(get_db)) -> dict:
    _world_or_404(db, world_id)
    agents = list(db.execute(select(Agent).where(Agent.world_id == world_id)).scalars())
    events = list(db.execute(select(Event).where(Event.world_id == world_id)).scalars())
    alive = [agent for agent in agents if agent.lifecycle_state in {"alive", "critical"}]
    survival_enabled = survival_needs_enabled(_world_or_404(db, world_id))
    hungry = [agent for agent in alive if survival_enabled and agent.dynamic_state and agent.dynamic_state.satiety < 35]
    thirsty = [agent for agent in alive if survival_enabled and agent.dynamic_state and agent.dynamic_state.hydration < 35]
    burnout = [agent for agent in alive if int((agent.work_json or {}).get("burnout", 0)) >= 60]
    employed = [agent for agent in alive if bool((agent.work_json or {}).get("employed"))]
    jailed = [agent for agent in alive if bool((agent.law_json or {}).get("jailed"))]
    wanted = [agent for agent in alive if bool((agent.law_json or {}).get("wanted"))]
    pregnant = [agent for agent in alive if bool(((agent.family_json or {}).get("pregnancy_state") or {}).get("pregnant"))]
    children = [agent for agent in alive if agent.age_stage in {"newborn", "infant", "toddler", "child"}]
    child_need_risk = [
        agent
        for agent in children
        if agent.dynamic_state and ((survival_enabled and (agent.dynamic_state.satiety < 45 or agent.dynamic_state.hydration < 45)) or agent.dynamic_state.stress > 75)
    ]
    births = sum(1 for event in events if event.event_type == "birth")
    deaths = sum(1 for event in events if event.event_type == "death")
    invalid_tools = sum(1 for event in events if event.event_type == "tool_failed")
    crime_events = [event for event in events if event.event_type.startswith("crime_")]
    detected_crimes = [event for event in crime_events if bool((event.payload or {}).get("detected"))]
    base_metrics = {
        "population": len(agents),
        "alive": len(alive),
        "dead": deaths,
        "births": births,
        "children": len(children),
        "pregnant": len(pregnant),
        "child_need_risk": len(child_need_risk),
        "hunger_risk": len(hungry),
        "thirst_risk": len(thirsty),
        "employment_rate": round(len(employed) / len(alive), 3) if alive else 0,
        "burnout_rate": round(len(burnout) / len(alive), 3) if alive else 0,
        "jailed": len(jailed),
        "wanted": len(wanted),
        "adult_intimacy_events": sum(1 for event in events if event.event_type == "adult_intimacy"),
        "crime_attempts": len(crime_events),
        "crime_detected": len(detected_crimes),
        "jail_sentences": sum(1 for event in events if event.event_type == "jail_sentence"),
        "jail_escapes": sum(1 for event in events if event.event_type == "jail_escape"),
        "jail_escape_failures": sum(1 for event in events if event.event_type == "jail_escape_failed"),
        "crime_attempt_rate": len(crime_events) / max(1, len(events)),
        "llm_invalid_tool_call_rate": round(invalid_tools / max(1, len(events)), 3),
    }
    return {**base_metrics, **economy_metrics(agents, events)}


@router.post("/{world_id}/narrator/summarize-now")
async def summarize_now(world_id: str, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    if not (world.settings_json or {}).get("narrator_enabled", True):
        return {"narration_event_ids": []}
    event_ids = [event.event_id for event in db.execute(select(Event).where(Event.world_id == world_id).order_by(*chronological_order_desc()).limit(8)).scalars()]
    narration_event_ids = await create_narration(db, world, event_ids, trigger_type="manual")
    db.commit()
    return {"narration_event_ids": narration_event_ids}


@router.post("/{world_id}/image-generation/generate-now")
async def generate_image_now(world_id: str, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    image_event_ids = create_manual_image_generation(db, world)
    db.commit()
    return {"image_event_ids": image_event_ids}


@router.post("/{world_id}/image-generation/generate-prompt")
async def generate_image_from_prompt(world_id: str, payload: ManualImagePromptRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    image_event_ids = create_prompt_image_generation(
        db,
        world,
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt or "",
        title=payload.title or "",
    )
    db.commit()
    return {"image_event_ids": image_event_ids}


@router.post("/{world_id}/image-generation/{event_id}/cancel")
async def cancel_image_generation(world_id: str, event_id: int, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    try:
        event = await cancel_image_generation_event(db, world, event_id)
    except ValueError:
        raise HTTPException(404, "image generation event not found") from None
    db.refresh(event)
    return {"ok": True, "event": event_to_dict(event, db)}


@router.post("/{world_id}/image-generation/{event_id}/rerun")
async def rerun_image_generation(world_id: str, event_id: int, payload: ImageGenerationRerunRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = _world_or_404(db, world_id)
    try:
        event = await rerun_image_generation_event(
            db,
            world,
            event_id,
            prompt=payload.prompt,
            negative_prompt=payload.negative_prompt or "",
            overrides=payload.overrides,
        )
    except ValueError:
        raise HTTPException(404, "image generation event not found") from None
    db.refresh(event)
    return {"ok": True, "event": event_to_dict(event, db)}


@router.get("/{world_id}/export")
def download_export(world_id: str, db: Session = Depends(get_db)) -> FileResponse:
    _world_or_404(db, world_id)
    path = export_world_zip(db, world_id)
    return FileResponse(path, media_type="application/zip", filename=f"{world_id}_story.zip")


def _world_or_404(db: Session, world_id: str) -> World:
    world = db.get(World, world_id)
    if not world:
        raise HTTPException(404, "world not found")
    return world


def _normalize_prompt_settings(raw: PromptSettingsInput | dict | None = None) -> dict[str, int]:
    if isinstance(raw, PromptSettingsInput):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}
    defaults = PromptSettingsInput().model_dump()
    result: dict[str, int] = {}
    for key, fallback in defaults.items():
        try:
            value = int(data.get(key, fallback))
        except (TypeError, ValueError):
            value = int(fallback)
        ge, le = PROMPT_SETTING_BOUNDS.get(key, (0, 10_000))
        result[key] = max(ge, min(le, value))
    return result


def _normalize_llm_concurrency(raw: LLMConcurrencyInput | dict | None = None) -> dict:
    if isinstance(raw, LLMConcurrencyInput):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}
    return {
        "default_provider_limit": _safe_limit(data.get("default_provider_limit"), 0),
        "provider_limits": _normalize_limit_map(data.get("provider_limits")),
        "model_limits": _normalize_limit_map(data.get("model_limits")),
    }


def _normalize_limit_map(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            continue
        limit = _safe_limit(value, 0)
        if limit > 0:
            result[name[:300]] = limit
    return result


def _safe_limit(value: object, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(0, min(MAX_CONCURRENCY_LIMIT, number))


def _delete_world_rows(db: Session, world_id: str) -> dict[str, int]:
    agent_ids = select(Agent.agent_id).where(Agent.world_id == world_id)
    location_ids = select(Location.location_id).where(Location.world_id == world_id)
    event_ids = select(Event.event_id).where(Event.world_id == world_id)
    item_ids = select(Item.item_id).where(Item.world_id == world_id)
    deleted: dict[str, int] = {}

    def run(table_name: str, statement) -> None:
        result = db.execute(statement)
        deleted[table_name] = int(result.rowcount or 0)

    run("inventories", delete(Inventory).where(or_(Inventory.agent_id.in_(agent_ids), Inventory.item_id.in_(item_ids))))
    run(
        "conversations",
        delete(Conversation).where(
            or_(
                Conversation.event_id.in_(event_ids),
                Conversation.speaker_agent_id.in_(agent_ids),
                Conversation.target_agent_id.in_(agent_ids),
                Conversation.location_id.in_(location_ids),
            )
        ),
    )
    run("memories", delete(Memory).where(or_(Memory.agent_id.in_(agent_ids), Memory.source_event_id.in_(event_ids))))
    run("narrator_runs", delete(NarratorRun).where(NarratorRun.world_id == world_id))
    run(
        "identity_knowledge",
        delete(IdentityKnowledge).where(or_(IdentityKnowledge.observer_agent_id.in_(agent_ids), IdentityKnowledge.target_agent_id.in_(agent_ids))),
    )
    run("relationships", delete(Relationship).where(or_(Relationship.observer_agent_id.in_(agent_ids), Relationship.target_agent_id.in_(agent_ids))))
    run("agent_locations", delete(AgentLocation).where(or_(AgentLocation.agent_id.in_(agent_ids), AgentLocation.location_id.in_(location_ids))))
    run("agent_dynamic_state", delete(AgentDynamicState).where(AgentDynamicState.agent_id.in_(agent_ids)))
    run("agent_traits", delete(AgentTrait).where(AgentTrait.agent_id.in_(agent_ids)))
    run("items", delete(Item).where(Item.world_id == world_id))
    run("events", delete(Event).where(Event.world_id == world_id))
    run("locations", delete(Location).where(Location.world_id == world_id))
    run("agents", delete(Agent).where(Agent.world_id == world_id))
    run("worlds", delete(World).where(World.world_id == world_id))
    return deleted


def _speech_event_condition():
    # 角色台词只允许走结构化字段；event_type/message/content 可能只是旧事件或后端说明，不能当成公开台词。
    return or_(
        func.json_extract(Event.payload, "$.speech").is_not(None),
        func.json_extract(Event.payload, "$.dialogue_lines").is_not(None),
    )


def _pending_image_wait_cutoff(db: Session, world: World) -> int | None:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    image_generation = normalize_image_generation_settings(settings_json.get("image_generation"))
    pending = db.execute(
        select(Event)
        .where(
            Event.world_id == world.world_id,
            Event.event_type == "image_generation",
            func.json_extract(Event.payload, "$.status").in_(["pending", "running"]),
        )
        .order_by(*chronological_order_asc())
        .limit(1)
    ).scalar_one_or_none()
    if not pending:
        return None
    event_display_mode = str((pending.payload or {}).get("display_mode") or "")
    if event_display_mode == "wait":
        return int(pending.event_id)
    return None


def _events_markdown(db: Session, world: World, events: list[Event]) -> str:
    lines = [
        f"# {world.name} 事件导出",
        "",
        "筛选后的事件按 event_id 升序导出。对话、地点、时间和事件原文都来自后端事件账本。",
        "",
    ]
    for event in events:
        location_name = db.get(Location, event.location_id).public_name if event.location_id else ""
        prefix = f"- #{event.event_id} · {format_world_time(event.world_time)}"
        if location_name:
            prefix += f" · {location_name}"
        lines.append(f"{prefix} · {event.event_type}")
        lines.append(f"  {event.viewer_text}")
        if event.payload:
            for speech in _speech_lines_from_payload(event.payload):
                lines.append(f"  话语: {speech}")
        lines.append("")
    if not events:
        lines.append("没有符合当前筛选条件的事件。")
    return "\n".join(lines)


def _speech_lines_from_payload(payload: dict) -> list[str]:
    if not isinstance(payload, dict):
        return []
    result: list[str] = []
    raw_lines = payload.get("dialogue_lines")
    if isinstance(raw_lines, list):
        for raw in raw_lines:
            if not isinstance(raw, dict):
                continue
            text = raw.get("text") or raw.get("speech")
            if isinstance(text, str) and text.strip():
                result.append(text.strip())
    speech = payload.get("speech")
    if isinstance(speech, str) and speech.strip() and speech.strip() not in result:
        result.append(speech.strip())
    return result


def _speech_from_payload(payload: dict) -> str:
    lines = _speech_lines_from_payload(payload)
    return lines[0] if lines else ""


def _normalize_tts_config(raw: dict) -> dict:
    mode = str(raw.get("mode") or raw.get("provider_type") or "openai").strip().lower()
    if mode not in {"openai", "mimo", "qwen_dashscope", "gptsovits"}:
        mode = "openai"
    default_endpoint = "/services/aigc/multimodal-generation/generation" if mode == "qwen_dashscope" else "/tts" if mode == "gptsovits" else "/audio/speech"
    default_format = "wav" if mode in {"qwen_dashscope", "gptsovits"} else "mp3"
    return {
        "enabled": bool(raw.get("enabled")),
        "provider": str(raw.get("provider") or "").strip(),
        "mode": mode,
        "base_url": str(raw.get("base_url") or raw.get("baseUrl") or "").strip(),
        "endpoint_path": str(raw.get("endpoint_path") or raw.get("endpointPath") or default_endpoint).strip() or default_endpoint,
        "api_key": str(raw.get("api_key") or raw.get("apiKey") or "").strip(),
        "model": str(raw.get("model") or ("qwen3-tts-flash" if mode == "qwen_dashscope" else "tts-1")).strip(),
        "voice": str(raw.get("voice") or ("Cherry" if mode == "qwen_dashscope" else "alloy")).strip(),
        "response_format": str(raw.get("response_format") or raw.get("responseFormat") or default_format).strip().lower() or default_format,
        "language_type": str(raw.get("language_type") or raw.get("languageType") or "Chinese").strip() or "Chinese",
        "instructions": str(raw.get("instructions") or "").strip(),
        "ref_audio_path": str(raw.get("ref_audio_path") or raw.get("refAudioPath") or "").strip(),
        "prompt_text": str(raw.get("prompt_text") or raw.get("promptText") or "").strip(),
        "prompt_lang": str(raw.get("prompt_lang") or raw.get("promptLang") or "zh").strip() or "zh",
        "text_lang": str(raw.get("text_lang") or raw.get("textLang") or "zh").strip() or "zh",
        "text_split_method": str(raw.get("text_split_method") or raw.get("textSplitMethod") or "cut5").strip() or "cut5",
        "batch_size": _safe_int(raw.get("batch_size") or raw.get("batchSize") or 1, 1, 32, 1),
    }


def _safe_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


async def _call_tts_provider(tts_config: dict, text: str) -> str:
    tts_config = _normalize_tts_config(tts_config)
    base_url = str(tts_config.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(400, "TTS base_url is not configured")
    endpoint_path = str(tts_config.get("endpoint_path") or "/audio/speech").strip() or "/audio/speech"
    if not endpoint_path.startswith("/"):
        endpoint_path = "/" + endpoint_path
    api_key = str(tts_config.get("api_key") or "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response_format = str(tts_config.get("response_format") or "mp3").strip().lower() or "mp3"
    mode = str(tts_config.get("mode") or "openai")
    if mode == "gptsovits":
        request_payload = {
            "text": text[:4000],
            "text_lang": str(tts_config.get("text_lang") or "zh"),
            "ref_audio_path": str(tts_config.get("ref_audio_path") or ""),
            "prompt_text": str(tts_config.get("prompt_text") or ""),
            "prompt_lang": str(tts_config.get("prompt_lang") or "zh"),
            "text_split_method": str(tts_config.get("text_split_method") or "cut5"),
            "batch_size": int(tts_config.get("batch_size") or 1),
            "media_type": response_format,
            "streaming_mode": False,
        }
    elif mode == "qwen_dashscope":
        request_payload = {
            "model": str(tts_config.get("model") or "qwen3-tts-flash"),
            "input": {
                "text": text[:1200],
                "voice": str(tts_config.get("voice") or "Cherry"),
                "language_type": str(tts_config.get("language_type") or "Chinese"),
            },
        }
        instructions = str(tts_config.get("instructions") or "").strip()
        if instructions:
            request_payload["parameters"] = {"instructions": instructions}
    else:
        request_payload = {
            "model": str(tts_config.get("model") or "tts-1"),
            "voice": str(tts_config.get("voice") or "alloy"),
            "input": text[:4000],
            "response_format": response_format,
        }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{base_url}{endpoint_path}", headers=headers, json=request_payload)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type == "application/json":
                audio = await _audio_from_tts_json_response(client, response, response_format)
                if audio:
                    return audio
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"TTS request failed: {exc}") from exc
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "application/json":
        raise HTTPException(502, "TTS provider JSON did not contain audio")
    media_type = content_type if content_type.startswith("audio/") else f"audio/{response_format}"
    return f"data:{media_type};base64,{base64.b64encode(response.content).decode('ascii')}"


async def _audio_from_tts_json_response(client: httpx.AsyncClient, response: httpx.Response, response_format: str) -> str | None:
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(502, "TTS provider returned invalid JSON") from exc
    for key in ("audio_data_url", "audioDataUrl", "data_url"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    audio_base64 = data.get("audio_base64") or data.get("audio")
    if isinstance(audio_base64, str) and audio_base64:
        return f"data:audio/{response_format};base64,{audio_base64}"
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    nested_audio = output.get("audio") if isinstance(output, dict) and isinstance(output.get("audio"), dict) else {}
    nested_data = nested_audio.get("data") if isinstance(nested_audio, dict) else None
    if isinstance(nested_data, str) and nested_data:
        return f"data:audio/{response_format};base64,{nested_data}"
    nested_url = nested_audio.get("url") if isinstance(nested_audio, dict) else None
    direct_url = data.get("url")
    audio_url = nested_url if isinstance(nested_url, str) and nested_url else direct_url if isinstance(direct_url, str) and direct_url else ""
    if audio_url:
        audio_response = await client.get(audio_url)
        audio_response.raise_for_status()
        content_type = audio_response.headers.get("content-type", "").split(";")[0].strip().lower()
        media_type = content_type if content_type.startswith("audio/") else f"audio/{response_format}"
        return f"data:{media_type};base64,{base64.b64encode(audio_response.content).decode('ascii')}"
    return None


def _sync_runtime_status(db: Session, world: World) -> None:
    if world.status == "running" and not simulation_manager.is_running(world.world_id):
        world.status = "paused"
        db.commit()
        db.refresh(world)


def _provider_model_options(provider_config: ProviderConfigInput) -> list[str]:
    seen: set[str] = set()
    models: list[str] = []
    for raw_model in provider_config.models or []:
        model = str(raw_model or "").strip()
        if model and model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _resolve_provider_model(
    provider_config: ProviderConfigInput,
    configured_model: str | None,
    *,
    context: str,
    seed: int,
) -> str:
    model = (configured_model or "").strip()
    if model:
        return model
    options = _provider_model_options(provider_config)
    if not options:
        raise HTTPException(
            400,
            f"{context} 没有指定模型，且提供商「{provider_config.name or provider_config.provider_id}」没有可随机选择的已拉取模型。请先拉取模型或手动选择模型。",
        )
    digest = hashlib.sha256(f"{seed}:{provider_config.provider_id}:{context}".encode("utf-8")).hexdigest()
    return options[int(digest[:12], 16) % len(options)]


def _apply_runtime_narrator_config(settings_json: dict, payload: RuntimeNarratorConfigInput) -> dict:
    next_settings = dict(settings_json)
    existing = dict(next_settings.get("narrator_config") or {})
    if payload.enabled is False:
        next_settings["narrator_enabled"] = False
        next_settings["narrator_config"] = None
        return next_settings

    config = existing
    config["enabled"] = True
    if payload.provider_id is not None:
        config["provider_id"] = payload.provider_id.strip()
    if payload.provider_name is not None:
        config["provider_name"] = payload.provider_name.strip()
    if payload.base_url is not None:
        config["base_url"] = payload.base_url.strip().rstrip("/")
    if payload.clear_api_key:
        config["api_key"] = ""
    elif payload.api_key is not None and payload.api_key != "***":
        config["api_key"] = payload.api_key.strip()
    if payload.model_name is not None:
        model_name = payload.model_name.strip()
        if not model_name:
            raise HTTPException(400, "解说 Agent 必须选择一个明确模型；运行中不能清空模型后让后端自动兜底。")
        config["model_name"] = model_name
    if payload.system_prompt is not None:
        config["system_prompt"] = payload.system_prompt.strip()
    if payload.auto_frequency is not None:
        config["auto_frequency"] = payload.auto_frequency
        next_settings["narrator_frequency"] = payload.auto_frequency
    if payload.llm_generation is not None:
        config["llm_generation"] = normalize_llm_generation(payload.llm_generation.model_dump())
    if payload.retry_count is not None or payload.retry_interval_ms is not None or payload.request_timeout_ms is not None or payload.rpm is not None:
        config.update(
            normalize_llm_runtime(
                config,
                retry_count=payload.retry_count,
                retry_interval_ms=payload.retry_interval_ms,
                request_timeout_ms=payload.request_timeout_ms,
                rpm=payload.rpm,
            )
        )
    if not str(config.get("model_name") or "").strip():
        raise HTTPException(400, "解说 Agent 必须选择一个明确模型；运行中不能清空模型后让后端自动兜底。")
    next_settings["narrator_enabled"] = True
    next_settings["narrator_config"] = config
    return next_settings


def _model_usage_entry(
    *,
    source_type: str,
    source_id: str,
    label: str,
    provider_id: str | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    editable: bool = True,
    note: str = "",
    last_llm_phase: str | None = None,
    last_llm_world_time: int | None = None,
    last_llm_completed_at: str | None = None,
    last_llm_latency_ms: int | None = None,
    last_llm_token_usage: dict | None = None,
    last_llm_error: str | None = None,
    llm_consecutive_failures: int = 0,
) -> dict:
    model = str(model_name or "").strip()
    return {
        "source_type": source_type,
        "source_id": source_id,
        "label": label,
        "provider_id": provider_id or "",
        "provider_name": provider_name or "",
        "model_name": model,
        "base_url": base_url or "",
        "editable": editable,
        "implicit": not bool(model),
        "warning": "" if model else "未配置明确模型。该项不会自动调用其他模型兜底；请在对应设置里选择模型。",
        "note": note,
        "last_llm_phase": last_llm_phase or "",
        "last_llm_world_time": last_llm_world_time,
        "last_llm_completed_at": last_llm_completed_at or "",
        "last_llm_latency_ms": last_llm_latency_ms,
        "last_llm_token_usage": last_llm_token_usage or {},
        "last_llm_error": last_llm_error or "",
        "llm_consecutive_failures": llm_consecutive_failures,
    }


def _world_model_usage_entries(db: Session, world: World) -> list[dict]:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    entries: list[dict] = []
    agents = list(db.execute(select(Agent).where(Agent.world_id == world.world_id).order_by(Agent.created_at_world_time, Agent.agent_id)).scalars())
    for agent in agents:
        learning = agent.tool_learning_json if isinstance(agent.tool_learning_json, dict) else {}
        token_usage = learning.get("last_llm_token_usage") if isinstance(learning.get("last_llm_token_usage"), dict) else {}
        entries.append(
            _model_usage_entry(
                source_type="agent",
                source_id=agent.agent_id,
                label=agent.chosen_name or agent.agent_id,
                provider_id=agent.model_provider_id,
                provider_name=agent.model_provider_name,
                model_name=agent.model_name,
                base_url=agent.llm_base_url,
                note="居民行动、工具选择和相关判定",
                last_llm_phase=str(learning.get("last_llm_phase") or ""),
                last_llm_world_time=learning.get("last_llm_world_time") if isinstance(learning.get("last_llm_world_time"), int) else None,
                last_llm_completed_at=str(learning.get("last_llm_completed_at") or ""),
                last_llm_latency_ms=learning.get("last_llm_latency_ms") if isinstance(learning.get("last_llm_latency_ms"), int) else None,
                last_llm_token_usage=token_usage,
                last_llm_error=str(learning.get("last_llm_error") or learning.get("last_llm_protocol_error") or ""),
                llm_consecutive_failures=int(learning.get("llm_consecutive_failures") or 0),
            )
        )

    narrator_config = settings_json.get("narrator_config") if isinstance(settings_json.get("narrator_config"), dict) else None
    if narrator_config:
        entries.append(
            _model_usage_entry(
                source_type="narrator",
                source_id="narrator",
                label="解说 Agent / 每日总结",
                provider_id=str(narrator_config.get("provider_id") or ""),
                provider_name=str(narrator_config.get("provider_name") or ""),
                model_name=str(narrator_config.get("model_name") or ""),
                base_url=str(narrator_config.get("base_url") or ""),
                note="解说、每日总结、沿用解说的生图提示词",
            )
        )

    image_generation = normalize_image_generation_settings(settings_json.get("image_generation") if isinstance(settings_json.get("image_generation"), dict) else None)
    if image_generation.get("enabled"):
        if image_generation.get("prompt_llm_mode") == "custom":
            entries.append(
                _model_usage_entry(
                    source_type="image_prompt",
                    source_id="image_prompt",
                    label="生图提示词 LLM",
                    provider_id=str(image_generation.get("prompt_llm_provider_id") or ""),
                    provider_name=str(image_generation.get("prompt_llm_provider_name") or ""),
                    model_name=str(image_generation.get("prompt_llm_model_name") or ""),
                    base_url=str(image_generation.get("prompt_llm_base_url") or ""),
                    note="把剧情或解说改写成绘图提示词",
                )
            )
        entries.append(
            _model_usage_entry(
                source_type="image_provider",
                source_id="image_provider",
                label="生图接口模型",
                provider_name=str(image_generation.get("provider_type") or ""),
                model_name=str(image_generation.get("model_name") or ""),
                base_url=str(image_generation.get("base_url") or ""),
                editable=True,
                note="图片生成接口，不是聊天 LLM token",
            )
        )

    for index, config in enumerate(settings_json.get("baby_model_pool") or []):
        if isinstance(config, dict):
            entries.append(
                _model_usage_entry(
                    source_type="baby_model",
                    source_id=f"baby_model:{index}",
                    label=f"宝宝 Agent 模型 {index + 1}",
                    provider_id=str(config.get("provider_id") or ""),
                    provider_name=str(config.get("provider_name") or ""),
                    model_name=str(config.get("model_name") or ""),
                    base_url=str(config.get("base_url") or ""),
                    note="新生/成长身份生成",
                )
            )
    return entries


def _baby_model_pool(payload: CreateWorldRequest, providers: dict[str, ProviderConfigInput]) -> list[dict]:
    pool = []
    for config in payload.baby_model_configs:
        if not config.model_name:
            continue
        provider_config = providers.get(config.provider_id) or next(iter(providers.values()))
        pool.append(
            {
                "provider_id": provider_config.provider_id,
                "provider_name": provider_config.name,
                "base_url": provider_config.base_url,
                "api_key": provider_config.api_key,
                "model_name": config.model_name,
                **normalize_llm_runtime(
                    None,
                    retry_count=provider_config.retry_count,
                    retry_interval_ms=provider_config.retry_interval_ms,
                    request_timeout_ms=provider_config.request_timeout_ms,
                    rpm=provider_config.rpm,
                ),
            }
        )
    return pool


def _resolve_image_generation_settings(
    image_generation: ImageGenerationSettingsInput | None,
    providers: dict[str, ProviderConfigInput],
    default_generation: LLMGenerationInput | None = None,
    *,
    seed: int = 0,
) -> dict:
    raw = image_generation.model_dump() if image_generation else None
    config = normalize_image_generation_settings(raw)
    if config.get("prompt_llm_mode") != "custom":
        return config
    provider = providers.get(str(config.get("prompt_llm_provider_id") or "")) or next(iter(providers.values()))
    prompt_llm_model = _resolve_provider_model(
        provider,
        str(config.get("prompt_llm_model_name") or ""),
        context="image_prompt",
        seed=seed,
    )
    config.update(
        {
            "prompt_llm_provider_id": provider.provider_id,
            "prompt_llm_provider_name": provider.name,
            "prompt_llm_base_url": config.get("prompt_llm_base_url") or provider.base_url,
            "prompt_llm_api_key": config.get("prompt_llm_api_key") or provider.api_key or "",
            "prompt_llm_model_name": prompt_llm_model,
            "prompt_llm_generation": normalize_llm_generation(
                image_generation.prompt_llm_generation.model_dump()
                if image_generation and image_generation.prompt_llm_generation
                else (default_generation.model_dump() if default_generation else config.get("prompt_llm_generation"))
            ),
            **{
                f"prompt_llm_{key}": value
                for key, value in normalize_llm_runtime(
                    None,
                    retry_count=provider.retry_count,
                    retry_interval_ms=provider.retry_interval_ms,
                    request_timeout_ms=provider.request_timeout_ms,
                    rpm=provider.rpm,
                ).items()
            },
        }
    )
    return normalize_image_generation_settings(config)
