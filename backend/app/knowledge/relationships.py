from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.traits import clamp
from app.core.models import Agent, Relationship


def derive_label(rel: Relationship) -> str:
    if rel.fear >= 70:
        return "害怕"
    if rel.conflict >= 70 or rel.affection <= -50:
        return "讨厌"
    if rel.trust < 25 and rel.familiarity > 20:
        return "警惕"
    if rel.affection >= 70 and rel.trust >= 65:
        return "亲近"
    if rel.affection >= 35 and rel.trust >= 50:
        return "朋友"
    if rel.familiarity >= 15:
        return "点头之交"
    return "陌生"


def get_relationship(session: Session, observer_id: str, target_id: str) -> Relationship:
    rel = session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == observer_id,
            Relationship.target_agent_id == target_id,
        )
    ).scalar_one_or_none()
    if rel:
        return rel
    rel = Relationship(observer_agent_id=observer_id, target_agent_id=target_id)
    session.add(rel)
    session.flush()
    return rel


def adjust_relationship(
    session: Session,
    observer_id: str,
    target_id: str,
    *,
    world_time: int,
    familiarity: float = 0,
    trust: float = 0,
    affection: float = 0,
    fear: float = 0,
    conflict: float = 0,
) -> Relationship:
    familiarity, trust, affection, fear, conflict = _scaled_deltas(session, observer_id, familiarity, trust, affection, fear, conflict)
    rel = get_relationship(session, observer_id, target_id)
    rel.familiarity = clamp(rel.familiarity + familiarity)
    rel.trust = clamp(rel.trust + trust)
    rel.affection = clamp(rel.affection + affection, -100, 100)
    rel.fear = clamp(rel.fear + fear)
    rel.conflict = clamp(rel.conflict + conflict)
    rel.relationship_label = derive_label(rel)
    rel.last_interaction_at = world_time
    return rel


def _scaled_deltas(
    session: Session,
    observer_id: str,
    familiarity: float,
    trust: float,
    affection: float,
    fear: float,
    conflict: float,
) -> tuple[float, float, float, float, float]:
    agent = session.get(Agent, observer_id)
    world = agent.world if agent else None
    params = ((world.settings_json or {}).get("worldview_rule_parameters") or {}) if world else {}
    rel_params = params.get("relationship") if isinstance(params, dict) else None
    if not isinstance(rel_params, dict):
        return familiarity, trust, affection, fear, conflict

    def scale(value: float, key: str, *, positive_key: str | None = None, negative_key: str | None = None) -> float:
        if value == 0:
            return value
        multiplier_key = positive_key if value > 0 and positive_key else negative_key if value < 0 and negative_key else key
        try:
            multiplier = float(rel_params.get(multiplier_key, rel_params.get(key, 1.0)))
        except (TypeError, ValueError):
            multiplier = 1.0
        return value * max(0.0, min(100.0, multiplier))

    return (
        scale(familiarity, "familiarity_multiplier"),
        scale(trust, "trust_multiplier", positive_key="trust_positive_multiplier", negative_key="trust_negative_multiplier"),
        scale(affection, "affection_multiplier", positive_key="affection_positive_multiplier", negative_key="affection_negative_multiplier"),
        scale(fear, "fear_multiplier"),
        scale(conflict, "conflict_multiplier"),
    )
