from __future__ import annotations

import asyncio
import base64
import uuid
from datetime import datetime, timezone

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
from app.llm.language import normalize_language
from app.llm.runtime import normalize_llm_runtime
from app.knowledge.relationships import adjust_relationship
from app.narrator.narrator_service import create_narration
from app.simulation.difficulty import DIFFICULTY_LABELS, profile_for_world
from app.simulation.scheduler import simulation_manager
from app.world.seed_world import private_home_location as build_private_home_location, private_home_location_id, seed_world_content


router = APIRouter(prefix="/api/worlds", tags=["worlds"])
MAX_AGENT_COUNT = 64
MAX_SYSTEM_PROMPT_LENGTH = 20_000
MAX_APPEARANCE_LENGTH = 4_000
MAX_AVATAR_DATA_URL_LENGTH = 10_000_000
SPEECH_EVENT_TYPES = ("dialogue", "introduce_self", "refuse_introduction")
PROMPT_SETTING_BOUNDS = {
    "memory_limit": (0, 200),
    "recent_event_limit": (0, 200),
    "recent_self_event_limit": (0, 100),
    "action_option_limit": (20, 500),
    "dream_memory_limit": (4, 200),
    "dream_important_limit": (0, 40),
    "dream_background_limit": (0, 40),
}


class CreateWorldRequest(BaseModel):
    name: str = Field(default=settings.world_name, max_length=120)
    agent_count: int = Field(default=settings.initial_agent_count, ge=1, le=MAX_AGENT_COUNT)
    collective_core_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    seed: int = settings.seed
    language: str = Field(default="zh", pattern="^(zh|en)$")
    speed: str = "fast"
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
    providers: list["ProviderConfigInput"] = Field(default_factory=list)
    narrator_config: "NarratorConfigInput | None" = None
    baby_model_configs: list["BabyModelConfigInput"] = Field(default_factory=list)
    agent_configs: list["AgentConfigInput"] = Field(default_factory=list)
    prompt_settings: "PromptSettingsInput | None" = None


class ProviderConfigInput(BaseModel):
    provider_id: str = Field(default="default", max_length=80)
    name: str = Field(default="默认提供商", max_length=80)
    base_url: str = Field(default=settings.llm_base_url, max_length=300)
    api_key: str | None = Field(default=None, max_length=4000)
    retry_count: int = Field(default=2, ge=0, le=100_000)
    retry_interval_ms: int = Field(default=1500, ge=0, le=21_600_000)
    rpm: int = Field(default=0, ge=0, le=100_000)


class AgentConfigInput(BaseModel):
    provider_id: str = Field(default="default", max_length=80)
    model_name: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    chosen_name: str | None = Field(default=None, max_length=12)
    appearance: str | None = Field(default=None, max_length=MAX_APPEARANCE_LENGTH)
    avatar_data_url: str | None = Field(default=None, max_length=MAX_AVATAR_DATA_URL_LENGTH)
    trait_mode: str | None = Field(default=None, pattern="^(agent|player|random)$")
    trait_sliders: dict[str, int] = Field(default_factory=dict)
    tool_context_mode: str = Field(default="dynamic", pattern="^(dynamic|all)$")
    agent_toolset_ids: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS))
    tts_config: dict | None = None


class NarratorConfigInput(BaseModel):
    enabled: bool = True
    provider_id: str = Field(default="default", max_length=80)
    model_name: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)


class BabyModelConfigInput(BaseModel):
    provider_id: str = Field(default="default", max_length=80)
    model_name: str | None = Field(default=None, max_length=120)


class SaveNameUpdateRequest(BaseModel):
    save_name: str = Field(default="", max_length=120)


class PromptSettingsInput(BaseModel):
    memory_limit: int = Field(default=10, ge=0, le=200)
    recent_event_limit: int = Field(default=8, ge=0, le=200)
    recent_self_event_limit: int = Field(default=6, ge=0, le=100)
    action_option_limit: int = Field(default=90, ge=20, le=500)
    dream_memory_limit: int = Field(default=24, ge=4, le=200)
    dream_important_limit: int = Field(default=5, ge=0, le=40)
    dream_background_limit: int = Field(default=3, ge=0, le=40)


class WorldRuntimeSettingsUpdateRequest(BaseModel):
    collective_core_prompt: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_LENGTH)
    speed: str | None = Field(default=None, pattern="^(slow|fast)$")
    prompt_settings: PromptSettingsInput | None = None


class WorldInterventionRequest(BaseModel):
    action: str = Field(max_length=120)
    actor_agent_id: str | None = Field(default=None, max_length=48)
    target_agent_id: str | None = Field(default=None, max_length=48)
    location_id: str | None = Field(default=None, max_length=48)
    note: str | None = Field(default=None, max_length=240)


CreateWorldRequest.model_rebuild()


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
            "worldview_ui": ui_schema,
            "worldpack_state_schema": worldpack_state_schema,
            "worldpack_default_create_settings": defaults,
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
    narrator_config = payload.narrator_config
    narrator_enabled = bool(narrator_config and narrator_config.enabled)
    narrator_provider = providers.get(narrator_config.provider_id) if narrator_config else None
    narrator_provider = narrator_provider or next(iter(providers.values()))
    baby_model_pool = _baby_model_pool(payload, providers)
    world = _world_or_404(db, world_id)
    stored_narrator_config = None
    if narrator_enabled and narrator_config:
        narrator_runtime = normalize_llm_runtime(
            None,
            retry_count=narrator_provider.retry_count,
            retry_interval_ms=narrator_provider.retry_interval_ms,
            rpm=narrator_provider.rpm,
        )
        stored_narrator_config = {
            "provider_id": narrator_provider.provider_id,
            "provider_name": narrator_provider.name,
            "base_url": narrator_provider.base_url,
            "api_key": narrator_provider.api_key,
            "model_name": narrator_config.model_name or settings.model_name("narrator"),
            "system_prompt": narrator_config.system_prompt,
            **narrator_runtime,
        }
    world.settings_json = {
        **(world.settings_json or {}),
        "narrator_enabled": narrator_enabled,
        "narrator_config": stored_narrator_config,
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
        own_preset_name = (agent_config.chosen_name or "").strip()
        agent_plans.append((index, agent_config, provider_config))

    identity_drafts = await asyncio.gather(
        *[
            prepare_identity_draft(
                world_id=world_id,
                world_seed=payload.seed,
                index=index,
                taken_names=reserved_names - ({own_preset_name} if own_preset_name else set()),
                model_alias=choose_model_alias(index),
                model_name=agent_config.model_name,
                base_url=provider_config.base_url,
                api_key=provider_config.api_key,
                llm_retry_count=provider_config.retry_count,
                llm_retry_interval_ms=provider_config.retry_interval_ms,
                llm_rpm=provider_config.rpm,
                language=normalize_language(payload.language),
                custom_system_prompt=agent_config.system_prompt,
                collective_core_prompt=payload.collective_core_prompt,
                preset_name=agent_config.chosen_name,
                preset_appearance=agent_config.appearance,
                avatar_data_url=agent_config.avatar_data_url,
                user_trait_sliders=agent_config.trait_sliders,
            )
            for index, agent_config, provider_config in agent_plans
            for own_preset_name in [(agent_config.chosen_name or "").strip()]
        ]
    )
    for (index, agent_config, provider_config), identity_draft in zip(agent_plans, identity_drafts, strict=True):
        world = _world_or_404(db, world_id)
        initial_location_id = private_home_location_id(world_id, index, worldview)
        agent = await create_agent_with_identity(
            db,
            world,
            index=index,
            model_alias=choose_model_alias(index),
            initial_location_id=initial_location_id,
            provider_name=provider_config.name,
            model_name=agent_config.model_name,
            base_url=provider_config.base_url,
            api_key=provider_config.api_key,
            llm_retry_count=provider_config.retry_count,
            llm_retry_interval_ms=provider_config.retry_interval_ms,
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
        if isinstance(agent_config.tts_config, dict):
            agent.tool_learning_json = {
                **(agent.tool_learning_json or {}),
                "tts_config": _normalize_tts_config(agent_config.tts_config),
            }
        agent.wallet_json = {
            **(agent.wallet_json or {}),
            "money": int(profile_for_world(world)["start_money"]),
            "housing": {
                **((agent.wallet_json or {}).get("housing") or {}),
                "home_location_id": initial_location_id,
                "rent_per_10_days": int(profile_for_world(world)["rent_per_10"]),
                "rent_grace_days": int(profile_for_world(world)["rent_grace_days"]),
            },
        }
        create_event(
            db,
            world=world,
            event_type="birth",
            actor_agent_id=agent.agent_id,
            location_id=initial_location_id,
            importance=70,
            color_class="important",
            viewer_text=f"{agent.chosen_name} 在自己的住所里醒来，暂时还没有见到其他居民。",
            payload={"model_alias": agent.model_alias, "worldview_id": worldview["worldview_id"]},
        )
        db.commit()
        await manager.broadcast(world_id, {"type": "agent_updated", "agent_id": agent.agent_id})
    world = _world_or_404(db, world_id)
    await manager.broadcast(world_id, {"type": "world_state_updated", "world": world_summary(world, db)})
    return world_summary(world, db)


@router.get("")
def list_worlds(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    total = int(db.execute(select(func.count()).select_from(World)).scalar_one() or 0)
    worlds = list(db.execute(select(World).order_by(World.created_at.desc()).offset(offset).limit(limit)).scalars())
    for world in worlds:
        _sync_runtime_status(db, world)
    return {"worlds": [world_summary(world, db) for world in worlds], "total": total, "limit": limit, "offset": offset}


@router.patch("/{world_id}/save-name")
def update_world_save_name(world_id: str, payload: SaveNameUpdateRequest, db: Session = Depends(get_db)) -> dict:
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
    return world_summary(world, db)


@router.delete("/{world_id}")
async def delete_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    _world_or_404(db, world_id)
    await simulation_manager.stop(world_id)
    deleted = _delete_world_rows(db, world_id)
    db.commit()
    return {"ok": True, "world_id": world_id, "deleted": deleted}


@router.patch("/{world_id}/runtime-settings")
async def update_world_runtime_settings(world_id: str, payload: WorldRuntimeSettingsUpdateRequest, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    settings_json = dict(world.settings_json or {})
    changed = False
    if payload.collective_core_prompt is not None:
        settings_json["collective_core_prompt"] = payload.collective_core_prompt.strip()
        changed = True
    if payload.speed is not None:
        settings_json["speed"] = payload.speed
        changed = True
    if payload.prompt_settings is not None:
        settings_json["prompt_settings"] = _normalize_prompt_settings(payload.prompt_settings)
        changed = True
    if changed:
        world.settings_json = settings_json
        db.commit()
        db.refresh(world)
        await manager.broadcast(world_id, {"type": "world_settings_updated", "world": world_summary(world, db)})
    return world_summary(world, db)


@router.post("/{world_id}/interventions")
async def apply_world_intervention(world_id: str, payload: WorldInterventionRequest, db: Session = Depends(get_db)) -> dict:
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
        if actor.dynamic_state:
            apply_delta(actor.dynamic_state, social=4, fun=10, stress=-3, mood=10)
        if payload.action == "love_mutual":
            adjust_relationship(db, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=18, trust=12, affection=60, conflict=-8, fear=-5)
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
            payload={"intervention": payload.action},
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
            "due_world_time": world.current_world_time_minutes if payload.action == "miracle_birth" else world.current_world_time_minutes + 10 * 1440,
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
    await manager.broadcast(world_id, {"type": "world_state_updated", "world": world_summary(world, db), "event_ids": event_ids})
    return {"ok": True, "event_ids": event_ids, "world": world_summary(world, db)}


@router.get("/{world_id}")
def get_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = db.get(World, world_id)
    if not world:
        raise HTTPException(404, "world not found")
    _sync_runtime_status(db, world)
    return world_summary(world, db)


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
        occupant_count = int(
            db.execute(
                select(func.count(Agent.agent_id))
                .join(Agent.location)
                .where(Agent.world_id == world_id, Agent.lifecycle_state.in_(["alive", "critical"]), AgentLocation.location_id == location.location_id)
            ).scalar_one()
            or 0
        )
        item["occupant_count"] = occupant_count
        payload.append(item)
    return {"locations": payload}


@router.post("/{world_id}/start")
async def start_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    world.status = "running"
    db.commit()
    simulation_manager.start(world_id, world.settings_json.get("speed", settings.simulation_speed))
    await manager.broadcast(world_id, {"type": "simulation_status_changed", "status": "running"})
    return world_summary(world, db)


@router.post("/{world_id}/pause")
async def pause_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    world.status = "paused"
    db.commit()
    await simulation_manager.pause(world_id)
    await manager.broadcast(world_id, {"type": "simulation_status_changed", "status": "paused"})
    return world_summary(world, db)


@router.post("/{world_id}/resume")
async def resume_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    return await start_world(world_id, db)


@router.post("/{world_id}/step")
async def step_world(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    if world.status == "ended":
        raise HTTPException(400, "world ended")
    world.status = "paused"
    db.commit()
    result = await simulation_manager.step(world_id)
    await manager.broadcast(world_id, {"type": "world_state_updated", "world_id": world_id, "result": result})
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
    _world_or_404(db, world_id)
    stmt = select(Event).where(Event.world_id == world_id)
    if after_event_id:
        stmt = stmt.where(Event.event_id > after_event_id)
    if start_event_id:
        stmt = stmt.where(Event.event_id >= start_event_id)
    if end_event_id:
        stmt = stmt.where(Event.event_id <= end_event_id)
    if min_importance:
        stmt = stmt.where(or_(Event.importance >= min_importance, _speech_event_condition()))
    if agent_id:
        stmt = stmt.where((Event.actor_agent_id == agent_id) | (Event.target_agent_id == agent_id))
    if location_id:
        stmt = stmt.where(Event.location_id == location_id)
    if dialogue_only:
        stmt = stmt.where(_speech_event_condition())
    elif not show_narrator:
        stmt = stmt.where(Event.event_type != "narration")
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if not include_debug:
        stmt = stmt.where(Event.visibility_scope != "system")
    limit = max(1, min(limit, 10000))
    if after_event_id:
        events = list(db.execute(stmt.order_by(*chronological_order_asc()).limit(limit)).scalars())
    elif latest:
        events = sort_chronologically(list(db.execute(stmt.order_by(*chronological_order_desc()).limit(limit)).scalars()))
    else:
        events = list(db.execute(stmt.order_by(*chronological_order_asc()).limit(limit)).scalars())
    return {"events": [event_to_dict(event, db) for event in events]}


@router.post("/{world_id}/events/{event_id}/tts")
async def synthesize_event_tts(world_id: str, event_id: int, db: Session = Depends(get_db)) -> dict:
    _world_or_404(db, world_id)
    event = db.get(Event, event_id)
    if not event or event.world_id != world_id:
        raise HTTPException(404, "event not found")
    payload = dict(event.payload or {})
    existing_audio = payload.get("tts_audio_data_url")
    if isinstance(existing_audio, str) and existing_audio.startswith("data:audio/"):
        return {"event_id": event.event_id, "audio_data_url": existing_audio, "cached": True}
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
    event.payload = {**payload, "tts_audio_data_url": audio_data_url, "tts_speaker_agent_id": actor.agent_id}
    db.commit()
    return {"event_id": event.event_id, "audio_data_url": audio_data_url, "cached": False}


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
    db: Session = Depends(get_db),
) -> Response:
    world = _world_or_404(db, world_id)
    stmt = select(Event).where(Event.world_id == world_id, Event.visibility_scope != "system")
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
    events = list(db.execute(stmt.order_by(*chronological_order_asc())).scalars())
    content = build_event_archive_zip(db, world, events, include_avatars=include_avatars, include_audio=include_audio)
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
async def summarize_now(world_id: str, db: Session = Depends(get_db)) -> dict:
    world = _world_or_404(db, world_id)
    if not (world.settings_json or {}).get("narrator_enabled", True):
        return {"narration_event_ids": []}
    event_ids = [event.event_id for event in db.execute(select(Event).where(Event.world_id == world_id).order_by(*chronological_order_desc()).limit(8)).scalars()]
    narration_event_ids = await create_narration(db, world, event_ids, trigger_type="manual")
    db.commit()
    return {"narration_event_ids": narration_event_ids}


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
    return or_(
        Event.event_type.in_(SPEECH_EVENT_TYPES),
        func.json_extract(Event.payload, "$.speech").is_not(None),
        func.json_extract(Event.payload, "$.message").is_not(None),
        func.json_extract(Event.payload, "$.content").is_not(None),
    )


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
            speech = event.payload.get("speech") or event.payload.get("message") or event.payload.get("content")
            if isinstance(speech, str) and speech:
                lines.append(f"  话语: {speech}")
        lines.append("")
    if not events:
        lines.append("没有符合当前筛选条件的事件。")
    return "\n".join(lines)


def _speech_from_payload(payload: dict) -> str:
    for key in ("speech", "message", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
                    rpm=provider_config.rpm,
                ),
            }
        )
    return pool
