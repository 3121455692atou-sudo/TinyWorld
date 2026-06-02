from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.traits import mood_label
from app.agents.v5_state import ensure_v5_agent_state
from app.content.toolsets import DEFAULT_AGENT_SPECIAL_TOOLSET_IDS, survival_needs_enabled
from app.core.clock import format_world_time
from app.core.models import Agent, Event, IdentityKnowledge, Inventory, Item, Location, Memory, NarratorRun, Relationship, World
from app.economy.v6 import ensure_v6_agent_state
from app.llm.runtime import agent_llm_runtime
from app.events.event_store import chronological_order_desc
from app.world.visibility import location_public_name


def world_summary(world: World, session: Session | None = None) -> dict:
    settings = world.settings_json or {}
    display_time = world.current_world_time_minutes
    if session is not None:
        latest_event_time = session.execute(select(func.max(Event.world_time)).where(Event.world_id == world.world_id)).scalar()
        if latest_event_time is not None:
            display_time = max(display_time, int(latest_event_time))
    return {
        "world_id": world.world_id,
        "name": world.name,
        "save_name": settings.get("save_name") or world.name,
        "status": world.status,
        "seed": world.seed,
        "current_world_time_minutes": display_time,
        "world_time_label": format_world_time(display_time),
        "settings": _redact_secrets(settings),
    }


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
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.chosen_name,
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
        "has_warning": bool(state and (state.health < 40 or state.energy < 20 or (survival_enabled and (state.satiety < 20 or state.hydration < 20)))),
    }


def agent_detail(session: Session, agent: Agent) -> dict:
    ensure_v5_agent_state(agent)
    ensure_v6_agent_state(agent)
    state = agent.dynamic_state
    traits = agent.traits
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
    memories = list(session.execute(select(Memory).where(Memory.agent_id == agent.agent_id).order_by(Memory.memory_id.desc()).limit(20)).scalars())
    recent_events = list(
        session.execute(
            select(Event)
            .where((Event.actor_agent_id == agent.agent_id) | (Event.target_agent_id == agent.agent_id))
            .order_by(*chronological_order_desc())
            .limit(20)
        ).scalars()
    )
    return {
        "identity": {
            "agent_id": agent.agent_id,
            "model_provider_name": agent.model_provider_name,
            "model_name": agent.model_name or agent.model_alias,
            "llm_base_url": agent.llm_base_url,
            "llm_consecutive_failures": int((agent.tool_learning_json or {}).get("llm_consecutive_failures") or 0),
            "last_llm_error": (agent.tool_learning_json or {}).get("last_llm_error"),
            "llm_retry_count": agent_llm_runtime(agent)["retry_count"],
            "llm_retry_interval_ms": agent_llm_runtime(agent)["retry_interval_ms"],
            "llm_rpm": agent_llm_runtime(agent)["rpm"],
            "tool_context_mode": (agent.tool_learning_json or {}).get("tool_context_mode", "dynamic"),
            "agent_toolset_ids": (agent.tool_learning_json or {}).get("agent_toolset_ids", list(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS)),
            "custom_system_prompt": agent.custom_system_prompt,
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
        "memories_recent": [{"memory_id": m.memory_id, "type": m.memory_type, "content": m.content, "importance": m.importance, "world_time": m.created_world_time} for m in memories if m.memory_type != "diary"],
        "diaries_recent": [{"memory_id": m.memory_id, "content": m.content, "world_time": m.created_world_time} for m in memories if m.memory_type == "diary"],
        "recent_events": [event_to_dict(e, session) for e in recent_events],
    }


def event_to_dict(event: Event, session: Session | None = None) -> dict:
    location_name = location_public_name(session, event.location_id) if session else None
    return {
        "event_id": event.event_id,
        "world_id": event.world_id,
        "world_time": event.world_time,
        "world_time_label": format_world_time(event.world_time),
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
        "viewer_text": event.viewer_text,
        "payload": event.payload,
        "state_delta": event.state_delta,
        "no_state_changed": event.no_state_changed,
    }


def location_to_dict(location: Location, session: Session) -> dict:
    tags = list(location.tags_json or [])
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
    }


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
