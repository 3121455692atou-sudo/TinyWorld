from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, IdentityKnowledge
from app.world.visibility import get_or_create_knowledge, mark_name_known, mark_visual_known


def known_names(session: Session, observer_id: str) -> list[IdentityKnowledge]:
    return list(
        session.execute(
            select(IdentityKnowledge).where(
                IdentityKnowledge.observer_agent_id == observer_id,
                IdentityKnowledge.name_known.is_(True),
            )
        ).scalars()
    )


def visual_only(session: Session, observer_id: str) -> list[IdentityKnowledge]:
    return list(
        session.execute(
            select(IdentityKnowledge).where(
                IdentityKnowledge.observer_agent_id == observer_id,
                IdentityKnowledge.visual_known.is_(True),
                IdentityKnowledge.name_known.is_(False),
            )
        ).scalars()
    )


def observer_knows_name(session: Session, observer_id: str, target_id: str) -> bool:
    row = get_or_create_knowledge(session, observer_id, target_id)
    return bool(row.name_known)


def learn_name_from_self_intro(session: Session, observer_id: str, target: Agent, world_time: int, gender_revealed: bool) -> None:
    mark_visual_known(session, session.get(Agent, observer_id), target, world_time)  # type: ignore[arg-type]
    mark_name_known(session, observer_id, target, world_time, "self_intro", gender_revealed)

