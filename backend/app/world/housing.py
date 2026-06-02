from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, Location, World


MINOR_AGE_STAGES = {"newborn", "infant", "toddler", "child", "teen"}


def ensure_agent_home(session: Session, world: World, agent: Agent) -> str | None:
    wallet = dict(agent.wallet_json or {})
    housing = dict(wallet.get("housing") or {})
    if agent.age_stage in MINOR_AGE_STAGES:
        guardian_home = _guardian_home_location_id(session, agent)
        home_id = guardian_home or housing.get("home_location_id")
        housing.update(
            {
                "status": "dependent",
                "quality_tier": "guardian_home",
                "rent_per_10_days": 0,
                "next_rent_due_day": None,
                "rent_late_count": 0,
                "homeless": False,
                "home_location_id": home_id,
                "guardian_dependent": True,
            }
        )
        wallet["housing"] = housing
        agent.wallet_json = wallet
        return str(home_id) if home_id else None

    home_id = housing.get("home_location_id")
    if _is_private_home(session, home_id):
        return str(home_id)

    assigned = _assigned_private_cabin(session, world, agent)
    if not assigned:
        return str(home_id) if home_id else None
    housing["home_location_id"] = assigned
    wallet["housing"] = housing
    agent.wallet_json = wallet
    return assigned


def _is_private_home(session: Session, location_id: str | None) -> bool:
    if not location_id:
        return False
    location = session.get(Location, location_id)
    if not location:
        return False
    tags = set(location.tags_json or [])
    return "home" in tags and "private" in tags


def _assigned_private_cabin(session: Session, world: World, agent: Agent) -> str | None:
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id)
            .order_by(Agent.created_at_world_time.asc(), Agent.agent_id.asc())
        ).scalars()
    )
    try:
        index = next(i for i, candidate in enumerate(agents) if candidate.agent_id == agent.agent_id)
    except StopIteration:
        return None
    preferred_id = f"{world.world_id}:private_cabin_{index + 1}"
    if _is_private_home(session, preferred_id):
        return preferred_id
    fallback = session.execute(
        select(Location)
        .where(Location.world_id == world.world_id)
        .order_by(Location.location_id.asc())
    ).scalars()
    for location in fallback:
        tags = set(location.tags_json or [])
        if "home" in tags and "private" in tags:
            return location.location_id
    return None


def _guardian_home_location_id(session: Session, agent: Agent) -> str | None:
    family = agent.family_json or {}
    for guardian_id in family.get("guardian_agent_ids") or []:
        guardian = session.get(Agent, guardian_id)
        if not guardian:
            continue
        home_id = ((guardian.wallet_json or {}).get("housing") or {}).get("home_location_id")
        if _is_private_home(session, home_id):
            return str(home_id)
    return None
