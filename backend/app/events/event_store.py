from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.sql import ColumnElement
from sqlalchemy.orm import Session

from app.core.models import Event, World
from app.events.importance import color_for_importance


def create_event(
    session: Session,
    *,
    world: World,
    event_type: str,
    viewer_text: str,
    agent_visible_text: str | None = None,
    actor_agent_id: str | None = None,
    target_agent_id: str | None = None,
    location_id: str | None = None,
    visibility_scope: str = "public",
    importance: int = 10,
    color_class: str | None = None,
    payload: dict[str, Any] | None = None,
    state_delta: dict[str, Any] | None = None,
    no_state_changed: bool = False,
) -> Event:
    event = Event(
        world_id=world.world_id,
        world_time=world.current_world_time_minutes,
        event_type=event_type,
        actor_agent_id=actor_agent_id,
        target_agent_id=target_agent_id,
        location_id=location_id,
        visibility_scope=visibility_scope,
        importance=importance,
        color_class=color_class or color_for_importance(importance, event_type),
        viewer_text=viewer_text,
        agent_visible_text=agent_visible_text or viewer_text,
        payload=payload or {},
        state_delta=state_delta or {},
        no_state_changed=no_state_changed,
    )
    session.add(event)
    session.flush()
    return event


def chronological_order_asc() -> tuple[ColumnElement, ColumnElement]:
    return (Event.world_time.asc(), Event.event_id.asc())


def chronological_order_desc() -> tuple[ColumnElement, ColumnElement]:
    return (Event.world_time.desc(), Event.event_id.desc())


def sort_chronologically(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda event: (int(event.world_time or 0), int(event.event_id or 0)))


def latest_events(session: Session, world_id: str, limit: int = 50, min_importance: int = 0) -> list[Event]:
    newest = list(
        session.execute(
            select(Event)
            .where(Event.world_id == world_id, Event.importance >= min_importance)
            .order_by(*chronological_order_desc())
            .limit(limit)
        ).scalars()
    )
    return sort_chronologically(newest)


def events_after(session: Session, world_id: str, after_event_id: int | None, limit: int = 100) -> list[Event]:
    stmt = select(Event).where(Event.world_id == world_id)
    if after_event_id:
        stmt = stmt.where(Event.event_id > after_event_id)
    return list(session.execute(stmt.order_by(*chronological_order_asc()).limit(limit)).scalars())
