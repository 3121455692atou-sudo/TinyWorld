"""Shared sleep quota and retry rules for menus, validation and execution."""
from __future__ import annotations

from app.agents.numeric import safe_int
from app.core.models import Agent


MAX_SLEEP_MINUTES_PER_DAY = 10 * 60
INSOMNIA_ATTEMPT_MINUTES = 15
INSOMNIA_RETRY_MINUTES = 30


def sleep_quota_day(world_time: int) -> int:
    return world_time // 1440 + 1


def remaining_sleep_minutes_today(actor: Agent, world_time: int) -> int:
    desires = actor.desires_json if isinstance(actor.desires_json, dict) else {}
    if safe_int(desires.get("sleep_quota_day"), -1) != sleep_quota_day(world_time):
        return MAX_SLEEP_MINUTES_PER_DAY
    used = max(0, safe_int(desires.get("sleep_minutes_today")))
    return max(0, MAX_SLEEP_MINUTES_PER_DAY - used)


def sleep_retry_wait_minutes(actor: Agent, world_time: int) -> int:
    desires = actor.desires_json if isinstance(actor.desires_json, dict) else {}
    last = safe_int(desires.get("last_insomnia_world_time"), -1)
    if last < 0 or last > world_time:
        return 0
    return max(0, INSOMNIA_RETRY_MINUTES - (world_time - last))
