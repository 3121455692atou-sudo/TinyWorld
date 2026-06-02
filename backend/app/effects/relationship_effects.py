from __future__ import annotations

from sqlalchemy.orm import Session

from app.knowledge.relationships import adjust_relationship


def mutual_adjust(
    session: Session,
    actor_id: str,
    target_id: str,
    *,
    world_time: int,
    familiarity: float = 0,
    trust: float = 0,
    affection: float = 0,
    fear: float = 0,
    conflict: float = 0,
) -> None:
    adjust_relationship(
        session,
        actor_id,
        target_id,
        world_time=world_time,
        familiarity=familiarity,
        trust=trust,
        affection=affection,
        fear=fear,
        conflict=conflict,
    )
    adjust_relationship(
        session,
        target_id,
        actor_id,
        world_time=world_time,
        familiarity=familiarity,
        trust=trust,
        affection=affection,
        fear=fear,
        conflict=conflict,
    )

