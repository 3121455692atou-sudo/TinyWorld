from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.serializers import (
    _activity_status,
    _location_color,
    _location_items,
    agent_list_item,
    location_notice_board_to_dict,
)
from app.core.models import Agent, AgentLocation, Event, Location, World
from app.core.clock import format_world_time


def build_left_snapshot(
    db: Session,
    world_id: str,
    *,
    include_private: bool = False,
) -> dict[str, Any]:
    """Build the state payload used by the left sidebar.

    This is deliberately shared by the standalone /left-snapshot endpoint,
    /events responses, and WebSocket step_progress messages so the event feed and
    location map move forward from the same state source instead of racing three
    independent refresh paths.
    """
    world = db.get(World, world_id)
    if not world:
        raise LookupError("world not found")

    latest_event_id = db.execute(
        select(func.max(Event.event_id)).where(Event.world_id == world_id),
    ).scalar()
    latest_event_time = db.execute(
        select(func.max(Event.world_time)).where(Event.world_id == world_id),
    ).scalar()
    agents = list(
        db.execute(
            select(Agent)
            .where(Agent.world_id == world_id)
            .order_by(Agent.created_at_world_time, Agent.agent_id),
        ).scalars(),
    )
    rows = list(db.execute(select(Location).where(Location.world_id == world_id)).scalars())
    occupant_rows = list(
        db.execute(
            select(Agent, AgentLocation.location_id)
            .join(AgentLocation, AgentLocation.agent_id == Agent.agent_id)
            .where(
                Agent.world_id == world_id,
                Agent.lifecycle_state.in_(["alive", "critical"]),
            )
            .order_by(Agent.created_at_world_time, Agent.agent_id),
        ).all(),
    )
    occupants_by_location: dict[str, list[dict[str, Any]]] = {}
    for agent, location_id in occupant_rows:
        occupants_by_location.setdefault(str(location_id), []).append(
            _left_snapshot_location_occupant(agent),
        )

    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    order = {
        str(location_id): index
        for index, location_id in enumerate(settings_json.get("worldview_locations") or [])
    }
    colors = settings_json.get("location_colors") if isinstance(settings_json, dict) else {}
    rows.sort(key=lambda loc: (order.get(loc.location_id, 10_000), loc.public_name))

    locations: list[dict[str, Any]] = []
    for location in rows:
        tags = list(location.tags_json or [])
        occupants = occupants_by_location.get(location.location_id, [])
        location_items = _location_items(db, location)
        notices = location_notice_board_to_dict(db, world_id, location.location_id)
        item = {
            "location_id": location.location_id,
            "name": location.public_name,
            "description": location.description,
            "neighbors": list(location.neighbors_json or []),
            "available_tools": list(location.available_tools_json or []),
            "tags": tags,
            "is_private": "private" in tags,
            "color": str(colors.get(location.location_id))
            if isinstance(colors, dict) and colors.get(location.location_id)
            else _location_color(db, location.location_id),
            "capacity": location.capacity,
            "visibility_radius": location.visibility_radius,
            "occupant_count": len(occupants),
            "occupants": occupants,
            "item_count": len(location_items),
            "items": location_items,
            "notice_count": len(notices),
            "notice_board": notices,
        }
        if not include_private and item["is_private"]:
            continue
        locations.append(item)

    snapshot_event_id = int(latest_event_id or 0)
    snapshot_event_time = int(latest_event_time or world.current_world_time_minutes or 0)
    return {
        "world": _left_snapshot_world(db, world),
        "agents": [_left_snapshot_agent_item(db, agent) for agent in agents],
        "locations": locations,
        "latest_event_id": snapshot_event_id,
        "latest_event_world_time": snapshot_event_time,
        "state_version": f"{snapshot_event_id}:{snapshot_event_time}",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }


def _left_snapshot_world(db: Session, world: World) -> dict[str, Any]:
    """Small world payload for high-frequency state refreshes."""
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    settings_version = hashlib.sha256(
        json.dumps(settings_json, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"),
    ).hexdigest()[:16]
    display_time = int(world.current_world_time_minutes or 0)
    latest_event_time = db.execute(
        select(func.max(Event.world_time)).where(Event.world_id == world.world_id),
    ).scalar()
    if latest_event_time is not None:
        display_time = max(display_time, int(latest_event_time))
    return {
        "world_id": world.world_id,
        "name": world.name,
        "save_name": str(settings_json.get("save_name") or world.name),
        "status": world.status,
        "seed": world.seed,
        "current_world_time_minutes": display_time,
        "world_time_label": format_world_time(display_time),
        "settings_version": settings_version,
        "settings": {},
    }


def _left_snapshot_agent_item(db: Session, agent: Agent) -> dict[str, Any]:
    item = agent_list_item(db, agent)
    item["avatar_hint"] = _light_avatar_hint(item.get("avatar_hint"))
    return item


def _left_snapshot_location_occupant(agent: Agent) -> dict[str, Any]:
    state = agent.dynamic_state
    if agent.lifecycle_state == "critical" or (state and state.critical_reason):
        activity = "昏迷" if (state and state.critical_reason in {"unconscious", "fainted", "satiety", "hydration"}) else "危险"
    else:
        status = _activity_status(agent, None)
        activity = status.get("label") if status.get("state") == "working" else "在场"
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.chosen_name,
        "avatar_hint": _light_avatar_hint(agent.avatar_hint_json or {}),
        "appearance_short": agent.appearance_short,
        "lifecycle_state": agent.lifecycle_state,
        "age_stage": agent.age_stage,
        "activity_label": activity,
    }


def _light_avatar_hint(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key != "image_data_url"}
