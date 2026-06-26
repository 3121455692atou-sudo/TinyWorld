from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.traits import mood_label
from app.agents.v5_state import ensure_v5_agent_state
from app.content.toolsets import DEFAULT_AGENT_SPECIAL_TOOLSET_IDS, survival_needs_enabled
from app.core.clock import format_world_time
from app.core.models import Agent, AgentLocation, Event, IdentityKnowledge, Inventory, Item, Location, Memory, NarratorRun, Relationship, World
from app.economy.v6 import ensure_v6_agent_state
from app.economy.work_schedule import active_work_status
from app.llm.runtime import agent_llm_generation, agent_llm_runtime
from app.events.event_store import chronological_order_desc, strip_model_reasoning_text
from app.image_generation.service import IMAGE_EVENT_CONFIG_SNAPSHOT_FIELDS, normalize_image_generation_settings
from app.storage.audio import audio_url_for_key
from app.storage.images import image_url_for_key
from app.world.notice_board import notice_board_entries
from app.world.visibility import location_public_name

MARKET_META_MARKER = "[market_item_meta]"

_MEMORY_TYPE_LABELS = {
    "short": "短期记忆",
    "long": "长期记忆",
    "summary": "梦境/摘要",
    "diary": "日记",
    "relationship": "关系记忆",
    "event": "事件记忆",
    "episodic": "事件记忆",
    "pregnancy": "怀孕/育儿",
    "werewolf": "狼人杀记忆",
    "memory": "主动记忆",
}


_PUBLIC_TECHNICAL_DETAIL_KEYS = {
    "llm_feedback",
    "agent_visible_text",
    "validation_message",
    "failure_message",
    "backend_hint",
    "raw_error",
    "raw_response",
    "raw_tool_error",
    "system_prompt",
    "repair_prompt",
    "tool_call",
    "params",
    "chosen_effect",
    "before_worldpack_state",
    "after_worldpack_state",
    "failure_reason_code",
    "tool_name",
}

_PUBLIC_TECHNICAL_KEY_FRAGMENTS = (
    "api_key",
    "llm",
    "backend",
    "prompt",
    "raw",
    "repair",
    "validation",
    "feedback",
    "debug",
    "internal",
)

_PUBLIC_TECHNICAL_TEXT_MARKERS = (
    "工具调用格式错误",
    "当前尝试的工具",
    "请重新选择",
    "参数完整且符合",
    "参数完整",
    "validation.message",
    "failure_reason_code",
    "failure_reason",
    "llm_feedback",
    "state_delta",
    "payload",
    "EffectEngine",
    "RuleEngine",
    "ToolValidation",
    "tool_name",
    "reason_code",
    "missing_visible_ref",
    "missing_location",
    "missing_known_name",
    "missing_speech",
    "missing_text",
    "target_not_visible",
    "private_room_blocked",
    "bad_location",
    "location_not_adjacent",
    "工具失败",
    "当前生命状态不能执行",
    "这个行动需要第二行",
    "这个行动需要台词",
    "请用行动菜单",
    "后端",
    "硬规则",
    "基础饱腹规则",
    "数值变化",
    "机制词",
    "抽象结果",
    "当前工具可能不足",
    "隐藏候选",
    "候选工具",
    "解释过滤原因",
    "向系统申请",
    "agent_requested_more_candidates",
    "系统会优先鼓励使用当前工具",
)


_WORLD_LIST_SETTING_KEYS = {
    "save_name",
    "survival_difficulty",
    "survival_difficulty_label",
    "worldview_id",
    "worldview_name",
    "world_toolset_id",
    "toolset_id",
}


def world_summary(world: World, session: Session | None = None, *, include_settings: bool = True) -> dict:
    settings = world.settings_json or {}
    display_time = world.current_world_time_minutes
    if session is not None:
        latest_event_time = session.execute(select(func.max(Event.world_time)).where(Event.world_id == world.world_id)).scalar()
        if latest_event_time is not None:
            display_time = max(display_time, int(latest_event_time))
    public_settings = _redact_secrets(settings) if include_settings else _list_settings(settings)
    return {
        "world_id": world.world_id,
        "name": world.name,
        "save_name": settings.get("save_name") or world.name,
        "status": world.status,
        "seed": world.seed,
        "created_at": world.created_at.isoformat() if world.created_at else "",
        "current_world_time_minutes": display_time,
        "world_time_label": format_world_time(display_time),
        "settings_version": _settings_version(settings),
        "settings": public_settings,
    }


def _settings_version(settings: dict) -> str:
    return hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def _list_settings(settings: dict) -> dict:
    return {key: _redact_secrets(settings[key]) for key in _WORLD_LIST_SETTING_KEYS if key in settings}


def _redact_secrets(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            result[key] = "***" if "api_key" in lowered and item else _redact_secrets(item)
        return result
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def agent_list_item(session: Session, agent: Agent) -> dict:
    ensure_v5_agent_state(agent)
    ensure_v6_agent_state(agent)
    state = agent.dynamic_state
    location = agent.location.location if agent.location else None
    activity_status = _activity_status(agent, session)
    survival_enabled = survival_needs_enabled(agent.world)
    tts_config = (agent.tool_learning_json or {}).get("tts_config") if isinstance(agent.tool_learning_json, dict) else None
    image_generation = (agent.world.settings_json or {}).get("image_generation") if agent.world else {}
    image_aliases = (image_generation.get("agent_aliases") or {}) if isinstance(image_generation, dict) else {}
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.chosen_name,
        "image_prompt_name": str(image_aliases.get(agent.agent_id) or ""),
        "avatar_hint": agent.avatar_hint_json or {},
        "appearance_short": agent.appearance_short,
        "age_stage": agent.age_stage,
        "lifecycle_state": agent.lifecycle_state,
        "location_id": agent.location.location_id if agent.location else None,
        "location_name": location.public_name if location else "未知地点",
        "location_color": _location_color(session, agent.location.location_id if agent.location else None),
        "health": state.health if state else 0,
        "energy": state.energy if state else 0,
        "mood_label": mood_label(state.mood if state else 0),
        "activity_status": activity_status,
        "money": int((agent.wallet_json or {}).get("money", 0)),
        "tts_enabled": bool(isinstance(tts_config, dict) and tts_config.get("enabled")),
        "llm_consecutive_failures": int((agent.tool_learning_json or {}).get("llm_consecutive_failures") or 0),
        "has_warning": bool(state and (state.health < 40 or state.energy < 20 or (survival_enabled and (state.satiety < 20 or state.hydration < 20)))),
    }


def agent_detail(session: Session, agent: Agent) -> dict:
    ensure_v5_agent_state(agent)
    ensure_v6_agent_state(agent)
    state = agent.dynamic_state
    traits = agent.traits
    image_generation = (agent.world.settings_json or {}).get("image_generation") if agent.world else {}
    image_aliases = (image_generation.get("agent_aliases") or {}) if isinstance(image_generation, dict) else {}
    inventory = []
    for inv in session.execute(select(Inventory).where(Inventory.agent_id == agent.agent_id)).scalars():
        item = session.get(Item, inv.item_id)
        inventory.append({"item_id": inv.item_id, "name": item.name if item else inv.item_id, "quantity": inv.quantity})
    knowledge_rows = list(session.execute(select(IdentityKnowledge).where(IdentityKnowledge.observer_agent_id == agent.agent_id)).scalars())
    relationships = []
    for rel in session.execute(select(Relationship).where(Relationship.observer_agent_id == agent.agent_id)).scalars():
        target = session.get(Agent, rel.target_agent_id)
        relationships.append(
            {
                "target_agent_id": rel.target_agent_id,
                "target_name": target.chosen_name if target else rel.target_agent_id,
                "familiarity": rel.familiarity,
                "trust": rel.trust,
                "affection": rel.affection,
                "fear": rel.fear,
                "conflict": rel.conflict,
                "relationship_label": rel.relationship_label,
                "notes": rel.notes,
            }
        )
    memory_display_limit = _agent_memory_display_limit(agent)
    memories = list(
        session.execute(
            select(Memory)
            .where(Memory.agent_id == agent.agent_id)
            .order_by(Memory.memory_id.desc())
            .limit(max(80, memory_display_limit * 4))
        ).scalars()
    )
    recent_events = list(
        session.execute(
            select(Event)
            .where((Event.actor_agent_id == agent.agent_id) | (Event.target_agent_id == agent.agent_id))
            .order_by(*chronological_order_desc())
            .limit(20)
        ).scalars()
    )
    return {
        "world_id": agent.world_id,
        "tool_audit_history": list((agent.tool_learning_json or {}).get("tool_audit_history") or []),
        "identity": {
            "agent_id": agent.agent_id,
            "model_provider_id": agent.model_provider_id,
            "model_provider_name": agent.model_provider_name,
            "model_name": (agent.model_name or "").strip(),
            "llm_base_url": agent.llm_base_url,
            "llm_consecutive_failures": int((agent.tool_learning_json or {}).get("llm_consecutive_failures") or 0),
            "last_llm_error": (agent.tool_learning_json or {}).get("last_llm_error"),
            "llm_retry_count": agent_llm_runtime(agent)["retry_count"],
            "llm_retry_interval_ms": agent_llm_runtime(agent)["retry_interval_ms"],
            "llm_request_timeout_ms": agent_llm_runtime(agent)["request_timeout_ms"],
            "llm_rpm": agent_llm_runtime(agent)["rpm"],
            "llm_generation": agent_llm_generation(agent, agent.world),
            "tool_context_mode": (agent.tool_learning_json or {}).get("tool_context_mode", "dynamic"),
            "agent_toolset_ids": (agent.tool_learning_json or {}).get("agent_toolset_ids", list(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS)),
            "custom_system_prompt": agent.custom_system_prompt,
            "image_prompt_name": str(image_aliases.get(agent.agent_id) or ""),
            "user_configured_name": agent.user_configured_name,
            "chosen_name": agent.chosen_name,
            "gender_identity": agent.gender_identity,
            "gender_custom_text": agent.gender_custom_text,
            "gender_publicity": agent.gender_publicity,
            "gender_expression": agent.gender_expression,
            "age_stage": agent.age_stage,
            "appearance_full": agent.appearance_full,
            "appearance_short": agent.appearance_short,
            "avatar_hint": agent.avatar_hint_json,
            "speaking_style": agent.speaking_style,
            "personality_seed": agent.personality_seed,
            "initial_goal": agent.initial_goal,
            "intro_policy": agent.intro_policy,
            "lifecycle_state": agent.lifecycle_state,
            "death_cause": agent.death_cause,
            "tts_config": _redact_secrets((agent.tool_learning_json or {}).get("tts_config") or {}),
            "werewolf_observer_role": _werewolf_observer_role(agent),
        },
        "activity_status": _activity_status(agent, session),
        "state_display_schema": _state_display_schema(agent.world),
        "worldview_state": _worldview_state(agent),
        "traits": {column: getattr(traits, column) for column in ["openness", "caution", "sociability", "empathy", "curiosity", "discipline", "aggression", "honesty", "creativity", "neuroticism"]},
        "dynamic_state": {column: getattr(state, column) for column in ["health", "energy", "satiety", "hydration", "hygiene", "social", "fun", "stress", "mood", "critical_reason"]},
        "v5_state": {
            "wallet": agent.wallet_json,
            "work": agent.work_json,
            "family": agent.family_json,
            "family_display": _family_display(session, agent.family_json),
            "law": agent.law_json,
            "trauma": agent.trauma_json,
            "desires": agent.desires_json,
            "morality": agent.morality_json,
            "tool_learning": agent.tool_learning_json,
        },
        "v6_state": {
            "economy_profile": (agent.wallet_json or {}).get("economy_profile") or {},
            "hedonic_state": (agent.wallet_json or {}).get("hedonic_state") or {},
            "housing": (agent.wallet_json or {}).get("housing") or {},
            "assets": (agent.wallet_json or {}).get("assets") or [],
            "liabilities": (agent.wallet_json or {}).get("liabilities") or [],
            "vehicles": (agent.wallet_json or {}).get("vehicles") or [],
            "creator_profile": (agent.wallet_json or {}).get("creator_profile") or {},
            "broker_account": (agent.wallet_json or {}).get("broker_account") or None,
            "social_status": (agent.wallet_json or {}).get("social_status") or {},
            "economy_ledger": (agent.wallet_json or {}).get("economy_ledger") or [],
        },
        "current_location": {"location_id": agent.location.location_id if agent.location else None, "name": location_public_name(session, agent.location.location_id if agent.location else None)},
        "inventory": inventory,
        "knowledge_summary": [
            {
                "target_agent_id": row.target_agent_id,
                "target_real_name": session.get(Agent, row.target_agent_id).chosen_name if session.get(Agent, row.target_agent_id) else row.target_agent_id,
                "visual_known": row.visual_known,
                "appearance_snapshot": row.appearance_snapshot,
                "name_known": row.name_known,
                "known_name": row.known_name,
                "gender_known": row.gender_known,
                "known_gender_text": row.known_gender_text,
                "last_seen_at": row.last_seen_at,
            }
            for row in knowledge_rows
        ],
        "relationships": relationships,
        "memory_display_limit": memory_display_limit,
        "memory_buckets": _memory_buckets_to_dict(memories, memory_display_limit),
        "memories_recent": [_memory_to_dict(m) for m in memories if m.memory_type != "diary"][:memory_display_limit],
        "diaries_recent": [_memory_to_dict(m) for m in memories if m.memory_type == "diary"][:memory_display_limit],
        "recent_events": [event_to_dict(e, session) for e in recent_events],
    }


def _memory_to_dict(memory: Memory) -> dict:
    return {
        "memory_id": memory.memory_id,
        "source_event_id": memory.source_event_id,
        "type": memory.memory_type,
        "content": memory.content,
        "importance": memory.importance,
        "visibility": memory.visibility,
        "archived": bool(memory.archived),
        "world_time": memory.created_world_time,
    }


def _agent_memory_display_limit(agent: Agent) -> int:
    settings = agent.world.settings_json if agent.world and isinstance(agent.world.settings_json, dict) else {}
    prompt_settings = settings.get("prompt_settings") if isinstance(settings.get("prompt_settings"), dict) else {}
    value = prompt_settings.get("memory_limit", 40)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 40
    return max(1, min(200, parsed))


def _memory_buckets_to_dict(memories: list[Memory], limit: int) -> list[dict]:
    grouped: dict[str, list[Memory]] = {}
    order: list[str] = []
    for memory in memories:
        key = str(memory.memory_type or "memory").strip() or "memory"
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        if len(grouped[key]) < limit:
            grouped[key].append(memory)
    return [
        {
            "key": key,
            "label": _MEMORY_TYPE_LABELS.get(key, key),
            "count": len(grouped[key]),
            "items": [_memory_to_dict(memory) for memory in grouped[key]],
        }
        for key in order
        if grouped[key]
    ]


def _event_time_label(event: Event) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    if payload.get("hide_clock") or event.event_type in {"werewolf_speech", "werewolf_end_speech", "werewolf_rebuttal", "werewolf_rebuttal_reply", "werewolf_debate_paused"}:
        day = payload.get("day")
        try:
            day_number = int(day)
        except (TypeError, ValueError):
            day_number = None
        return f"第{day_number}天 圆桌讨论" if day_number else "圆桌讨论"
    return format_world_time(event.world_time)


def event_to_dict(event: Event, session: Session | None = None, *, include_debug: bool = False) -> dict:
    location_name = location_public_name(session, event.location_id) if session else None
    viewer_text = event.viewer_text if include_debug else _sanitize_public_text(event.viewer_text)
    payload = event.payload if include_debug else _sanitize_public_payload(event.payload)
    if not include_debug and event.event_type == "image_generation":
        payload = _image_generation_public_payload(event, payload, session)
    if isinstance(payload, dict):
        image_key = payload.get("image_key")
        if isinstance(image_key, str) and image_key and not payload.get("image_url"):
            payload = {**payload, "image_url": image_url_for_key(image_key)}
        audio_key = payload.get("tts_audio_key")
        if isinstance(audio_key, str) and audio_key and not payload.get("tts_audio_url"):
            payload = {**payload, "tts_audio_url": audio_url_for_key(audio_key)}
    if not include_debug and event.event_type in {"tool_failed", "job_application_failed", "candidate_request"}:
        payload = {}
    state_delta = event.state_delta if include_debug else {}
    return {
        "event_id": event.event_id,
        "world_id": event.world_id,
        "world_time": event.world_time,
        "world_time_label": _event_time_label(event),
        "real_created_at": event.real_created_at.isoformat() if event.real_created_at else None,
        "event_type": event.event_type,
        "actor_agent_id": event.actor_agent_id,
        "target_agent_id": event.target_agent_id,
        "location_id": event.location_id,
        "location_name": location_name,
        "location_color": _location_color(session, event.location_id),
        "visibility_scope": event.visibility_scope,
        "importance": event.importance,
        "color_class": event.color_class,
        "viewer_text": viewer_text,
        "payload": payload,
        "state_delta": state_delta,
        "no_state_changed": event.no_state_changed,
    }


def _image_generation_public_payload(event: Event, payload: object, session: Session | None) -> dict:
    raw = event.payload if isinstance(event.payload, dict) else {}
    public = dict(payload) if isinstance(payload, dict) else {}
    for key in (
        "prompt",
        "negative_prompt",
        "manual_prompt",
        "manual_negative_prompt",
        "prompt_generation_source",
        "prompt_content_raw",
        "prompt_content_cleaned",
        "prompt_llm_error",
        "image_config_overrides",
        *IMAGE_EVENT_CONFIG_SNAPSHOT_FIELDS,
    ):
        if key in raw:
            public[key] = raw[key]
    config = None
    if session is not None:
        world = session.get(World, event.world_id)
        settings_json = world.settings_json if world and isinstance(world.settings_json, dict) else {}
        config = normalize_image_generation_settings(settings_json.get("image_generation"))
    if config:
        for key in IMAGE_EVENT_CONFIG_SNAPSHOT_FIELDS:
            if public.get(key) in (None, ""):
                public[key] = config.get(key)
    return public


def _werewolf_observer_role(agent: Agent) -> str | None:
    world = agent.world
    settings = world.settings_json if world and isinstance(world.settings_json, dict) else {}
    observer_roles = settings.get("werewolf_observer_roles") if isinstance(settings.get("werewolf_observer_roles"), dict) else {}
    if agent.agent_id in observer_roles:
        return observer_roles.get(agent.agent_id)
    state = settings.get("werewolf_state") if isinstance(settings.get("werewolf_state"), dict) else {}
    roles = state.get("roles") if isinstance(state.get("roles"), dict) else {}
    role = roles.get(agent.agent_id)
    labels = {"villager": "平民", "werewolf": "狼人", "seer": "预言家", "coroner": "验尸官", "guard": "守卫", "witch": "女巫", "hunter": "猎人", "medium": "灵媒", "idiot": "白痴"}
    return labels.get(role, role) if role else None


def _sanitize_public_payload(value, *, parent_key: str = ""):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if key in _PUBLIC_TECHNICAL_DETAIL_KEYS or lowered in _PUBLIC_TECHNICAL_DETAIL_KEYS:
                continue
            if any(fragment in lowered for fragment in _PUBLIC_TECHNICAL_KEY_FRAGMENTS):
                continue
            # 角色台词必须是干净的自然发言；机械提示不能被替换成“角色说了一句失败提示”。
            if lowered in {"speech", "text"} and isinstance(item, str):
                cleaned_text = _sanitize_public_dialogue_text(item)
                if cleaned_text:
                    result[key] = cleaned_text
                continue
            cleaned = _sanitize_public_payload(item, parent_key=lowered)
            if cleaned is not None:
                result[key] = cleaned
        return result
    if isinstance(value, list):
        cleaned_items = []
        for item in value:
            cleaned = _sanitize_public_payload(item, parent_key=parent_key)
            if cleaned is None:
                continue
            if parent_key == "dialogue_lines" and isinstance(cleaned, dict) and not str(cleaned.get("text") or cleaned.get("speech") or "").strip():
                continue
            cleaned_items.append(cleaned)
        return cleaned_items
    if isinstance(value, str):
        return _sanitize_public_text(value)
    return value


def _sanitize_public_dialogue_text(text: str | None) -> str:
    if not text:
        return ""
    value = strip_model_reasoning_text(text)
    if not value:
        return ""
    if any(marker.lower() in value.lower() for marker in _PUBLIC_TECHNICAL_TEXT_MARKERS):
        return ""
    return value


def _sanitize_public_text(text: str | None) -> str:
    if not text:
        return ""
    value = strip_model_reasoning_text(text)
    if not value:
        return ""
    if any(marker.lower() in value.lower() for marker in _PUBLIC_TECHNICAL_TEXT_MARKERS):
        lowered = value.lower()
        if "private_room_blocked" in lowered or "私人小屋" in value or "别人的私人" in value:
            return "想进一间别人房间，但门没有对自己开放。"
        return "有一次行动没有顺利完成。"
    return value



def location_to_dict(location: Location, session: Session) -> dict:
    tags = list(location.tags_json or [])
    occupants = _location_occupants(session, location)
    items = _location_items(session, location)
    notices = location_notice_board_to_dict(session, location.world_id, location.location_id)
    return {
        "location_id": location.location_id,
        "name": location.public_name,
        "description": location.description,
        "neighbors": list(location.neighbors_json or []),
        "available_tools": list(location.available_tools_json or []),
        "tags": tags,
        "is_private": "private" in tags,
        "color": _location_color(session, location.location_id),
        "capacity": location.capacity,
        "visibility_radius": location.visibility_radius,
        "occupant_count": len(occupants),
        "occupants": occupants,
        "item_count": len(items),
        "items": items,
        "notice_count": len(notices),
        "notice_board": notices,
    }


def location_notice_board_to_dict(session: Session, world_id: str, location_id: str | None) -> list[dict]:
    world = session.get(World, world_id)
    if not world:
        return []
    result: list[dict] = []
    for entry in notice_board_entries(world, location_id):
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        author_agent_id = str(entry.get("author_agent_id") or "")
        author = session.get(Agent, author_agent_id) if author_agent_id else None
        result.append(
            {
                "content": content,
                "author_agent_id": author_agent_id or None,
                "author_name": author.chosen_name if author else "",
                "world_time": int(entry.get("world_time") or 0),
            }
        )
    return result[-20:]


def _location_occupants(session: Session, location: Location) -> list[dict]:
    rows = list(
        session.execute(
            select(Agent)
            .join(AgentLocation, AgentLocation.agent_id == Agent.agent_id)
            .where(
                Agent.world_id == location.world_id,
                Agent.lifecycle_state.in_(["alive", "critical"]),
                AgentLocation.location_id == location.location_id,
            )
            .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    )
    occupants = []
    for agent in rows:
        state = agent.dynamic_state
        if agent.lifecycle_state == "critical" or (state and state.critical_reason):
            activity = "昏迷" if (state and state.critical_reason in {"unconscious", "fainted", "satiety", "hydration"}) else "危险"
        else:
            status = _activity_status(agent, session)
            activity = status.get("label") if status.get("state") == "working" else "在场"
        occupants.append(
            {
                "agent_id": agent.agent_id,
                "display_name": agent.chosen_name,
                "avatar_hint": agent.avatar_hint_json or {},
                "appearance_short": agent.appearance_short,
                "lifecycle_state": agent.lifecycle_state,
                "age_stage": agent.age_stage,
                "activity_label": activity,
            }
        )
    return occupants


def _location_items(session: Session, location: Location) -> list[dict]:
    rows = list(
        session.execute(
            select(Item)
            .where(
                Item.world_id == location.world_id,
                Item.location_id == location.location_id,
            )
            .order_by(Item.name, Item.item_id)
        ).scalars()
    )
    return [
        {
            "item_id": item.item_id,
            "name": item.name,
            "description": _public_item_description(item.description),
            "item_type": item.item_type,
        }
        for item in rows
    ]


def _public_item_description(description: str | None) -> str:
    if not description:
        return ""
    return description.split(MARKET_META_MARKER, 1)[0].strip()


def _location_color(session: Session | None, location_id: str | None) -> str | None:
    key = _public_location_key(location_id)
    if not key:
        return None
    if session and location_id:
        location = session.get(Location, location_id)
        world = session.get(World, location.world_id) if location else None
        colors = (world.settings_json or {}).get("location_colors") if world else None
        if isinstance(colors, dict):
            color = colors.get(location_id) or colors.get(key)
            if color:
                return str(color)
    palette_by_key = {
        "central_square": "#2f80ed",
        "cafeteria": "#27ae60",
        "cabin": "#f2994a",
        "library": "#9b51e0",
        "lake": "#00a6a6",
        "workshop": "#b8860b",
        "medical_room": "#eb5757",
        "garden": "#4f6f52",
        "market": "#d94888",
        "campfire": "#c66a31",
        "notice_board": "#6c7a89",
        "jail": "#4d4d4d",
        "hot_spring_lobby": "#c48a5a",
        "hot_spring_men": "#4aa3a2",
        "hot_spring_women": "#d06f9f",
        "hot_spring_mixed": "#8a79d6",
    }
    return palette_by_key.get(key) or _legacy_location_color(location_id)


def _family_display(session: Session, family_json: dict | None) -> dict:
    family = family_json or {}

    def name(agent_id: str | None) -> str | None:
        if not agent_id:
            return None
        agent = session.get(Agent, agent_id)
        return agent.chosen_name if agent and agent.chosen_name else agent_id

    children = []
    for child_id in family.get("children_agent_ids") or []:
        child_name = name(str(child_id))
        if child_name:
            children.append({"agent_id": str(child_id), "name": child_name})
    guardians = []
    for guardian_id in family.get("guardian_agent_ids") or []:
        guardian_name = name(str(guardian_id))
        if guardian_name:
            guardians.append({"agent_id": str(guardian_id), "name": guardian_name})
    pregnancy = family.get("pregnancy_state") if isinstance(family.get("pregnancy_state"), dict) else None
    co_parent_id = str(pregnancy.get("co_parent_agent_id")) if pregnancy and pregnancy.get("co_parent_agent_id") else None
    return {
        "partner": {"agent_id": family.get("partner_agent_id"), "name": name(family.get("partner_agent_id"))} if family.get("partner_agent_id") else None,
        "children": children,
        "guardians": guardians,
        "pregnancy": {
            **pregnancy,
            "co_parent_name": name(co_parent_id),
        } if pregnancy else None,
    }


def _public_location_key(location_id: str | None) -> str | None:
    if not location_id or ":" not in location_id:
        return None
    key = location_id.split(":", 1)[1]
    if key.startswith("private_cabin_"):
        return None
    if "private_" in key:
        return None
    return key


def _state_display_schema(world: World | None) -> dict:
    ui = (world.settings_json or {}).get("worldview_ui") if world else None
    if isinstance(ui, dict) and isinstance(ui.get("state_display"), dict):
        return ui["state_display"]
    return {"dynamic_fields": ["health", "energy", "satiety", "hydration", "hygiene", "social", "fun", "stress", "mood"], "worldpack": {"show_progress": True, "show_resources": True, "show_flags": True}}


def _worldview_state(agent: Agent) -> dict:
    wallet = agent.wallet_json or {}
    all_state = wallet.get("worldpack_state") or {}
    settings = (agent.world.settings_json or {}) if agent.world else {}
    world_key = str(settings.get("worldview_id") or settings.get("world_toolset_id") or "")
    current = all_state.get(world_key) if isinstance(all_state, dict) else None
    if current is None and isinstance(all_state, dict):
        for key, value in all_state.items():
            if str(key).startswith(world_key) or world_key.startswith(str(key)):
                current = value
                break
    schema = settings.get("worldpack_state_schema") or {}
    return {"key": world_key, "state": current or {"resources": {}, "progress": {"level": 1, "exp": 0}, "flags": []}, "schema": schema}


def _activity_status(agent: Agent, session: Session | None = None) -> dict:
    if agent.lifecycle_state == "dead":
        cause = agent.death_cause or (agent.dynamic_state.critical_reason if agent.dynamic_state else "") or "死亡"
        return {"state": "dead", "label": f"死亡：{cause}", "is_sleeping": False}
    world_time = agent.world.current_world_time_minutes if agent.world else None
    sleep_until = _positive_int((agent.desires_json or {}).get("sleep_until_world_time"))
    sleep_started = _positive_int((agent.desires_json or {}).get("sleep_started_world_time"))
    unconscious_until = _positive_int((agent.desires_json or {}).get("unconscious_until_world_time"))
    if sleep_until and (world_time is None or sleep_until > world_time):
        if session and _sleep_schedule_is_stale(session, agent):
            return {"state": "awake", "label": "清醒", "is_sleeping": False}
        if sleep_started:
            label = f"睡眠中，{format_world_time(sleep_started)} 入睡，预计 {format_world_time(sleep_until)} 醒来"
        else:
            label = f"睡眠中，预计 {format_world_time(sleep_until)} 醒来"
        return {
            "state": "sleeping",
            "label": label,
            "is_sleeping": True,
            "sleep_started_world_time": sleep_started,
            "sleep_started_label": format_world_time(sleep_started) if sleep_started else None,
            "sleep_until_world_time": sleep_until,
            "sleep_until_label": format_world_time(sleep_until),
        }
    if unconscious_until and (world_time is None or unconscious_until > world_time):
        return {
            "state": "unconscious",
            "label": f"昏睡中，最早 {format_world_time(unconscious_until)} 恢复",
            "is_sleeping": True,
            "sleep_until_world_time": unconscious_until,
            "sleep_until_label": format_world_time(unconscious_until),
        }
    working = active_work_status(agent, world_time)
    if isinstance(working, dict):
        until = _positive_int(working.get("until_world_time"))
        job_name = str(working.get("job_name") or "工作")
        return {
            "state": "working",
            "label": f"工作中：{job_name}，预计 {format_world_time(until)} 结束" if until else f"工作中：{job_name}",
            "is_sleeping": False,
            "working_status": working,
        }
    return {"state": "awake", "label": "清醒", "is_sleeping": False}


def _sleep_schedule_is_stale(session: Session, agent: Agent) -> bool:
    latest_sleep = session.execute(
        select(Event)
        .where(Event.world_id == agent.world_id, Event.actor_agent_id == agent.agent_id, Event.event_type == "sleep_start")
        .order_by(*chronological_order_desc())
        .limit(1)
    ).scalar_one_or_none()
    latest_wake = session.execute(
        select(Event)
        .where(Event.world_id == agent.world_id, Event.actor_agent_id == agent.agent_id, Event.event_type == "wake")
        .order_by(*chronological_order_desc())
        .limit(1)
    ).scalar_one_or_none()
    return bool(latest_wake and (not latest_sleep or latest_wake.event_id > latest_sleep.event_id))


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _legacy_location_color(location_id: str | None) -> str:
    palette = ["#2f80ed", "#27ae60", "#f2994a", "#9b51e0", "#eb5757", "#00a6a6", "#b8860b", "#6c7a89", "#d94888", "#4f6f52"]
    if not location_id:
        return "#8a99a1"
    return palette[sum(ord(ch) for ch in location_id) % len(palette)]


def narrator_to_dict(run: NarratorRun) -> dict:
    return {
        "narrator_run_id": run.narrator_run_id,
        "world_id": run.world_id,
        "trigger_type": run.trigger_type,
        "input_event_ids": run.input_event_ids_json,
        "summary_title": run.summary_title,
        "narration": run.narration,
        "tone": run.tone,
        "importance": run.importance,
        "created_world_time": run.created_world_time,
        "error": run.error,
    }
