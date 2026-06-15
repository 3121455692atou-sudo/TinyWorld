from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.v5_state import ensure_v5_agent_state
from app.core.models import Agent, World


INTERVENTION_CRUSH_KEY = "intervention_crushes"
INTERVENTION_CRUSH_DURATION_MINUTES = 3 * 24 * 60
INTERVENTION_CRUSH_ROMANCE_TOOLS = {
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
}


def _world_time(world_or_time: World | int | None) -> int:
    if isinstance(world_or_time, World):
        return int(world_or_time.current_world_time_minutes or 0)
    if world_or_time is None:
        return 0
    try:
        return int(world_or_time)
    except (TypeError, ValueError):
        return 0


def _clean_crushes(agent: Agent, now: int) -> dict[str, dict[str, Any]]:
    ensure_v5_agent_state(agent)
    family = dict(agent.family_json or {})
    raw = family.get(INTERVENTION_CRUSH_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    active: dict[str, dict[str, Any]] = {}
    changed = False
    for target_id, value in raw.items():
        if not isinstance(value, dict):
            changed = True
            continue
        try:
            expires_at = int(value.get("expires_world_time") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at and expires_at < now:
            changed = True
            continue
        active[str(target_id)] = dict(value)
    if changed or active != raw:
        family[INTERVENTION_CRUSH_KEY] = active
        agent.family_json = family
    return active


def set_intervention_crush(agent: Agent, target: Agent, world_time: int, *, duration_minutes: int = INTERVENTION_CRUSH_DURATION_MINUTES) -> None:
    ensure_v5_agent_state(agent)
    family = dict(agent.family_json or {})
    crushes = _clean_crushes(agent, int(world_time))
    crushes[target.agent_id] = {
        "target_agent_id": target.agent_id,
        "target_name": target.chosen_name or "",
        "source": "player_intervention",
        "intensity": 100,
        "started_world_time": int(world_time),
        "expires_world_time": int(world_time) + max(1, int(duration_minutes)),
    }
    family = dict(agent.family_json or {})
    family[INTERVENTION_CRUSH_KEY] = crushes
    agent.family_json = family


def has_active_intervention_crush(agent: Agent | None, target_agent_id: str | None, world_or_time: World | int | None = None) -> bool:
    if not agent or not target_agent_id:
        return False
    return str(target_agent_id) in _clean_crushes(agent, _world_time(world_or_time))


def active_intervention_crush_target_ids(agent: Agent, world_or_time: World | int | None = None) -> set[str]:
    return set(_clean_crushes(agent, _world_time(world_or_time)))


def intervention_crush_prompt_lines(session: Session, world: World, agent: Agent, *, language: str = "zh") -> list[str]:
    now = int(world.current_world_time_minutes or 0)
    lines: list[str] = []
    for target_id, crush in _clean_crushes(agent, now).items():
        target = session.get(Agent, target_id)
        target_name = (target.chosen_name if target else "") or str(crush.get("target_name") or target_id)
        if language == "en":
            lines.append(
                f"World influence status: you have an unusually strong intervention-born crush on {target_name}. "
                "You especially want to get closer or confess, but you still choose one valid action yourself."
            )
        else:
            lines.append(
                f"影响世界状态：你现在对 {target_name} 有强烈的强制心动，很想靠近、约会或表白；"
                "这不是普通好感，而是玩家影响世界造成的临时状态。你仍然只能按自己的性格和行动菜单选择，不会被强制表白。"
            )
    return lines
