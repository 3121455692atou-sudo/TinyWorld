from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import agent_detail, agent_list_item
from app.api.websocket import manager
from app.content.toolsets import AGENT_SPECIAL_TOOLSET_BY_ID
from app.core.config import settings
from app.core.database import get_db
from app.core.models import Agent, World
from app.events.event_store import create_event
from app.image_generation.service import normalize_image_generation_settings
from app.llm.runtime import normalize_llm_generation, normalize_llm_runtime
from app.simulation.scheduler import simulation_manager


router = APIRouter(prefix="/api/worlds/{world_id}/agents", tags=["agents"])


async def world_mutation_guard(world_id: str):
    async with simulation_manager.mutation_lock(world_id):
        yield


class LLMGenerationPatch(BaseModel):
    stream: bool | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=0, le=200_000)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)


class UpdateAgentLLMRequest(BaseModel):
    provider_id: str | None = Field(default=None, max_length=80)
    provider_name: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=4000)
    clear_api_key: bool = False
    model_name: str | None = Field(default=None, max_length=120)
    custom_system_prompt: str | None = Field(default=None, max_length=20_000)
    tool_context_mode: str | None = Field(default=None, pattern="^(dynamic|all)$")
    agent_toolset_ids: list[str] | None = None
    retry_count: int | None = Field(default=None, ge=0, le=100_000)
    retry_interval_ms: int | None = Field(default=None, ge=0, le=21_600_000)
    request_timeout_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    rpm: int | None = Field(default=None, ge=0, le=100_000)
    llm_generation: LLMGenerationPatch | None = None


class UpdateAgentProfileRequest(BaseModel):
    avatar_hint: dict | None = None
    tts_config: dict | None = None
    image_prompt_name: str | None = Field(default=None, max_length=120)


@router.get("")
def list_agents(world_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(World, world_id):
        raise HTTPException(404, "world not found")
    agents = list(db.execute(select(Agent).where(Agent.world_id == world_id).order_by(Agent.created_at_world_time, Agent.agent_id)).scalars())
    return {"agents": [agent_list_item(db, agent) for agent in agents]}


@router.get("/{agent_id}")
def get_agent(world_id: str, agent_id: str, db: Session = Depends(get_db)) -> dict:
    agent = db.get(Agent, agent_id)
    if not agent or agent.world_id != world_id:
        raise HTTPException(404, "agent not found")
    return agent_detail(db, agent)


@router.patch("/{agent_id}/llm")
async def update_agent_llm(world_id: str, agent_id: str, payload: UpdateAgentLLMRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = db.get(World, world_id)
    if not world:
        raise HTTPException(404, "world not found")
    agent = db.get(Agent, agent_id)
    if not agent or agent.world_id != world_id:
        raise HTTPException(404, "agent not found")

    if payload.provider_id is not None:
        agent.model_provider_id = payload.provider_id.strip() or None
    if payload.provider_name is not None:
        agent.model_provider_name = payload.provider_name.strip() or None
    if payload.base_url is not None:
        agent.llm_base_url = payload.base_url.strip().rstrip("/") or None
    if payload.model_name is not None:
        model_name = payload.model_name.strip()
        agent.model_name = model_name or None
        if model_name:
            agent.model_alias = "world_agent_pro" if "pro" in model_name.lower() else "world_agent"
    if payload.clear_api_key:
        agent.llm_api_key = None
    elif payload.api_key is not None:
        agent.llm_api_key = payload.api_key.strip() or None
    if payload.custom_system_prompt is not None:
        agent.custom_system_prompt = payload.custom_system_prompt.strip() or None

    learning = dict(agent.tool_learning_json or {})
    if payload.tool_context_mode is not None:
        learning["tool_context_mode"] = payload.tool_context_mode
    if payload.agent_toolset_ids is not None:
        learning["agent_toolset_ids"] = [toolset_id for toolset_id in payload.agent_toolset_ids if toolset_id in AGENT_SPECIAL_TOOLSET_BY_ID]
    if payload.retry_count is not None or payload.retry_interval_ms is not None or payload.request_timeout_ms is not None or payload.rpm is not None:
        existing_runtime = learning.get("llm_runtime") if isinstance(learning.get("llm_runtime"), dict) else None
        learning["llm_runtime"] = normalize_llm_runtime(
            existing_runtime,
            retry_count=payload.retry_count,
            retry_interval_ms=payload.retry_interval_ms,
            request_timeout_ms=payload.request_timeout_ms,
            rpm=payload.rpm,
        )
    if payload.llm_generation is not None:
        existing_generation = learning.get("llm_generation") if isinstance(learning.get("llm_generation"), dict) else None
        generation_patch = {key: value for key, value in payload.llm_generation.model_dump().items() if value is not None}
        learning["llm_generation"] = normalize_llm_generation({**(existing_generation or {}), **generation_patch})
    learning.update(
        {
            "llm_consecutive_failures": 0,
            "last_llm_error": None,
            "last_llm_failed_at_world_time": None,
            "llm_replaced_at_world_time": world.current_world_time_minutes,
            "last_llm_model_name": agent.model_name or settings.model_name(agent.model_alias or "world_agent"),
            "last_llm_base_url": agent.llm_base_url or settings.llm_base_url,
        }
    )
    agent.tool_learning_json = learning
    create_event(
        db,
        world=world,
        event_type="llm_config_changed",
        actor_agent_id=agent.agent_id,
        location_id=agent.location.location_id if agent.location else None,
        viewer_text=f"{agent.chosen_name} 的 LLM 配置已更新；下次行动会使用新的模型设置。",
        importance=1,
        color_class="muted",
        payload={
            "provider_name": agent.model_provider_name,
            "provider_id": agent.model_provider_id,
            "model_name": agent.model_name or agent.model_alias,
            "base_url": agent.llm_base_url or settings.llm_base_url,
            "custom_system_prompt_changed": payload.custom_system_prompt is not None,
            "tool_context_mode": (agent.tool_learning_json or {}).get("tool_context_mode", "dynamic"),
            "agent_toolset_ids": (agent.tool_learning_json or {}).get("agent_toolset_ids"),
            "llm_runtime": (agent.tool_learning_json or {}).get("llm_runtime"),
            "llm_generation": (agent.tool_learning_json or {}).get("llm_generation"),
        },
        no_state_changed=True,
    )
    db.commit()
    db.refresh(agent)
    await manager.broadcast(world_id, {"type": "agent_updated", "world_id": world_id, "agent_id": agent.agent_id})
    return agent_detail(db, agent)


@router.patch("/{agent_id}/profile")
async def update_agent_profile(world_id: str, agent_id: str, payload: UpdateAgentProfileRequest, db: Session = Depends(get_db), _lock: None = Depends(world_mutation_guard)) -> dict:
    world = db.get(World, world_id)
    if not world:
        raise HTTPException(404, "world not found")
    agent = db.get(Agent, agent_id)
    if not agent or agent.world_id != world_id:
        raise HTTPException(404, "agent not found")

    changed = False
    if payload.avatar_hint is not None:
        avatar_hint = dict(payload.avatar_hint or {})
        image_data_url = avatar_hint.get("image_data_url")
        if isinstance(image_data_url, str) and len(image_data_url) > 10_000_000:
            raise HTTPException(413, "avatar image is too large")
        standing_image_data_url = avatar_hint.get("standing_image_data_url")
        if isinstance(standing_image_data_url, str) and len(standing_image_data_url) > 10_000_000:
            raise HTTPException(413, "standing image is too large")
        agent.avatar_hint_json = avatar_hint
        changed = True

    if payload.tts_config is not None:
        learning = dict(agent.tool_learning_json or {})
        existing_tts = learning.get("tts_config") if isinstance(learning.get("tts_config"), dict) else {}
        tts_config = dict(payload.tts_config or {})
        if "api_key" in tts_config and tts_config.get("api_key") is None:
            tts_config.pop("api_key", None)
        learning["tts_config"] = {**existing_tts, **tts_config}
        agent.tool_learning_json = learning
        changed = True

    if payload.image_prompt_name is not None:
        settings_json = dict(world.settings_json or {})
        image_generation = normalize_image_generation_settings(
            settings_json.get("image_generation") if isinstance(settings_json.get("image_generation"), dict) else None
        )
        aliases = dict(image_generation.get("agent_aliases") or {})
        image_prompt_name = payload.image_prompt_name.strip()
        if image_prompt_name:
            aliases[agent.agent_id] = image_prompt_name
        else:
            aliases.pop(agent.agent_id, None)
        image_generation["agent_aliases"] = aliases
        settings_json["image_generation"] = image_generation
        world.settings_json = settings_json
        changed = True

    if changed:
        create_event(
            db,
            world=world,
            event_type="agent_profile_changed",
            actor_agent_id=agent.agent_id,
            location_id=agent.location.location_id if agent.location else None,
            viewer_text=f"{agent.chosen_name} 的外观或接口配置已更新。",
            importance=1,
            color_class="muted",
            payload={
                "avatar_changed": payload.avatar_hint is not None,
                "tts_changed": payload.tts_config is not None,
                "image_prompt_name_changed": payload.image_prompt_name is not None,
            },
            no_state_changed=True,
        )
        db.commit()
        db.refresh(agent)
        await manager.broadcast(world_id, {"type": "agent_updated", "world_id": world_id, "agent_id": agent.agent_id})
    return agent_detail(db, agent)
