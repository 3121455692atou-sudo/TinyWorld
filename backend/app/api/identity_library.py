from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.traits import TRAIT_NAMES
from app.core.database import get_db
from app.core.models import Agent, AgentDynamicState, AgentLocation, AgentTrait, Conversation, IdentityKnowledge, Inventory, Memory, Relationship, World
from app.llm.runtime import agent_llm_runtime


router = APIRouter(prefix="/api/identity-library", tags=["identity-library"])


@router.get("")
def list_identity_library(limit: int = 200, db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(limit, 1000))
    agents = list(
        db.execute(
            select(Agent)
            .outerjoin(World, World.world_id == Agent.world_id)
            .order_by(World.created_at.desc(), Agent.created_at_world_time.asc(), Agent.agent_id.asc())
            .limit(limit)
        ).scalars()
    )
    worlds = {
        world.world_id: world
        for world in db.execute(select(World).where(World.world_id.in_({agent.world_id for agent in agents}))).scalars()
    } if agents else {}
    return {"items": [_identity_item(agent, worlds.get(agent.world_id)) for agent in agents]}


@router.delete("/{agent_id}")
def delete_identity_library_item(agent_id: str, db: Session = Depends(get_db)) -> dict:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "identity not found")
    world_id = agent.world_id
    deleted: dict[str, int] = {}

    def run(name: str, statement) -> None:
        result = db.execute(statement)
        deleted[name] = int(result.rowcount or 0)

    run("inventories", delete(Inventory).where(Inventory.agent_id == agent_id))
    run("memories", delete(Memory).where(Memory.agent_id == agent_id))
    run("conversations", delete(Conversation).where(or_(Conversation.speaker_agent_id == agent_id, Conversation.target_agent_id == agent_id)))
    run("identity_knowledge", delete(IdentityKnowledge).where(or_(IdentityKnowledge.observer_agent_id == agent_id, IdentityKnowledge.target_agent_id == agent_id)))
    run("relationships", delete(Relationship).where(or_(Relationship.observer_agent_id == agent_id, Relationship.target_agent_id == agent_id)))
    run("agent_locations", delete(AgentLocation).where(AgentLocation.agent_id == agent_id))
    run("agent_dynamic_state", delete(AgentDynamicState).where(AgentDynamicState.agent_id == agent_id))
    run("agent_traits", delete(AgentTrait).where(AgentTrait.agent_id == agent_id))
    run("agents", delete(Agent).where(Agent.agent_id == agent_id))
    db.commit()
    return {"ok": True, "agent_id": agent_id, "world_id": world_id, "deleted": deleted}


def _identity_item(agent: Agent, world: World | None) -> dict:
    tool_learning = agent.tool_learning_json if isinstance(agent.tool_learning_json, dict) else {}
    avatar_hint = agent.avatar_hint_json if isinstance(agent.avatar_hint_json, dict) else {}
    settings = world.settings_json if world and isinstance(world.settings_json, dict) else {}
    return {
        "agentId": agent.agent_id,
        "worldId": agent.world_id,
        "worldName": world.name if world else agent.world_id,
        "saveName": settings.get("save_name") or (world.name if world else agent.world_id),
        "worldCreatedAt": world.created_at.isoformat() if world and world.created_at else "",
        "worldviewId": settings.get("worldview_id") or "",
        "worldviewName": settings.get("worldview_name") or "",
        "name": agent.chosen_name or "",
        "appearance": agent.appearance_full or agent.appearance_short or "",
        "appearanceShort": agent.appearance_short or "",
        "systemPrompt": agent.custom_system_prompt or "",
        "avatarDataUrl": avatar_hint.get("image_data_url") if isinstance(avatar_hint.get("image_data_url"), str) else "",
        "avatarHint": avatar_hint,
        "providerName": agent.model_provider_name or "",
        "modelName": agent.model_name or "",
        "baseUrl": agent.llm_base_url or "",
        "llmRuntime": agent_llm_runtime(agent),
        "toolContextMode": "all" if tool_learning.get("tool_context_mode") == "all" else "dynamic",
        "agentToolsetIds": [str(item) for item in tool_learning.get("agent_toolset_ids") or []],
        "ttsConfig": _redact_tts(tool_learning.get("tts_config") if isinstance(tool_learning.get("tts_config"), dict) else {}),
        "traits": _agent_traits(agent),
        "genderIdentity": agent.gender_identity,
        "genderExpression": agent.gender_expression,
        "speakingStyle": agent.speaking_style,
        "personalitySeed": agent.personality_seed,
        "initialGoal": agent.initial_goal,
        "createdAtWorldTime": agent.created_at_world_time,
        "lifecycleState": agent.lifecycle_state,
    }


def _agent_traits(agent: Agent) -> dict[str, int]:
    traits = agent.traits
    if not traits:
        return {name: 50 for name in TRAIT_NAMES}
    return {name: int(getattr(traits, name, 50)) for name in TRAIT_NAMES}


def _redact_tts(value: dict) -> dict:
    result = dict(value or {})
    if result.get("api_key"):
        result["api_key"] = ""
    return result
