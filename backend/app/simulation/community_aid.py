from __future__ import annotations

from app.core.models import Agent, World
from app.simulation.difficulty import profile_for_world


def community_aid_wait_minutes(world: World | None, actor: Agent, world_time: int) -> int:
    """Return the remaining wait using the same rule for menus and execution."""
    last_aid = (actor.desires_json or {}).get("last_community_aid_world_time")
    if last_aid is None:
        return 0
    try:
        last_aid = int(last_aid)
    except (TypeError, ValueError, OverflowError):
        return 0
    cooldown = int(profile_for_world(world)["aid_food_cooldown_h"]) * 60
    return max(0, last_aid + cooldown - world_time)
