from __future__ import annotations

from app.core.models import Agent


ACTIVE_STATES = {"alive", "critical"}


def can_act(agent: Agent) -> bool:
    return agent.lifecycle_state in ACTIVE_STATES


def mark_dead(agent: Agent, world_time: int, cause: str) -> None:
    agent.lifecycle_state = "dead"
    agent.death_at_world_time = world_time
    agent.death_cause = cause

