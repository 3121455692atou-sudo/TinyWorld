from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agents.v5_state import ensure_v5_agent_state
from app.core.models import Agent, World
from app.world.visibility import same_location_agent_ids


PENDING_INFidelity_RESPONSES_KEY = "pending_infidelity_responses"
INFIDELITY_RESPONSE_EXPIRES_MINUTES = 2 * 24 * 60

REACT_INFidelity_ANGRY_TOOL = "react_infidelity_angry_visible_agent"
REACT_INFidelity_FORGIVE_TOOL = "react_infidelity_forgive_visible_agent"
REACT_INFidelity_EXCITED_TOOL = "react_infidelity_excited_visible_agent"
INFIDELITY_RESPONSE_TOOL_NAMES = {
    REACT_INFidelity_ANGRY_TOOL,
    REACT_INFidelity_FORGIVE_TOOL,
    REACT_INFidelity_EXCITED_TOOL,
}


@dataclass(frozen=True, slots=True)
class InfidelityResponseKind:
    response: str
    title: str
    event_type: str
    relationship_delta: dict[str, int]
    actor_delta: dict[str, int]
    cheater_delta: dict[str, int]


INFIDELITY_RESPONSE_KINDS: dict[str, InfidelityResponseKind] = {
    REACT_INFidelity_ANGRY_TOOL: InfidelityResponseKind(
        response="angry",
        title="生气",
        event_type="infidelity_response_angry",
        relationship_delta={"affection": -24, "trust": -28, "conflict": 18},
        actor_delta={"stress": 12, "mood": -10, "social": -4},
        cheater_delta={"stress": 8, "mood": -5},
    ),
    REACT_INFidelity_FORGIVE_TOOL: InfidelityResponseKind(
        response="forgive",
        title="原谅",
        event_type="infidelity_response_forgive",
        relationship_delta={"affection": -6, "trust": -8, "conflict": -2},
        actor_delta={"stress": -2, "mood": -2, "social": 1},
        cheater_delta={"stress": -3, "mood": 1},
    ),
    REACT_INFidelity_EXCITED_TOOL: InfidelityResponseKind(
        response="excited",
        title="兴奋",
        event_type="infidelity_response_excited",
        relationship_delta={"affection": 3, "trust": -2, "conflict": -3},
        actor_delta={"stress": -4, "mood": 4, "fun": 6},
        cheater_delta={"stress": -1, "mood": 2},
    ),
}


def infidelity_response_kind(tool_name: str) -> InfidelityResponseKind | None:
    return INFIDELITY_RESPONSE_KINDS.get(tool_name)


def _requests(agent: Agent) -> list[dict[str, Any]]:
    ensure_v5_agent_state(agent)
    raw = (agent.family_json or {}).get(PENDING_INFidelity_RESPONSES_KEY) or []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _is_pending(request: dict[str, Any], world_time: int) -> bool:
    if request.get("status") != "pending":
        return False
    try:
        expires_at = int(request.get("expires_at_world_time") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    return not expires_at or expires_at >= int(world_time)


def expire_infidelity_responses(agent: Agent, world_time: int) -> None:
    requests = _requests(agent)
    changed = False
    next_requests: list[dict[str, Any]] = []
    for request in requests:
        if request.get("status") == "pending" and not _is_pending(request, world_time):
            request = {**request, "status": "expired", "resolved_world_time": int(world_time)}
            changed = True
        next_requests.append(request)
    if changed:
        agent.family_json = {**(agent.family_json or {}), PENDING_INFidelity_RESPONSES_KEY: next_requests}


def add_pending_infidelity_response(
    observer: Agent,
    cheater: Agent,
    affair_partner: Agent,
    world_time: int,
    *,
    source_event_id: int | None = None,
) -> dict[str, Any]:
    ensure_v5_agent_state(observer)
    expire_infidelity_responses(observer, world_time)
    request = {
        "response_id": f"infidelity_{uuid4().hex[:12]}",
        "status": "pending",
        "cheater_agent_id": cheater.agent_id,
        "affair_partner_agent_id": affair_partner.agent_id,
        "source_event_id": source_event_id,
        "created_world_time": int(world_time),
        "expires_at_world_time": int(world_time) + INFIDELITY_RESPONSE_EXPIRES_MINUTES,
    }
    pending = [
        item
        for item in _requests(observer)
        if not (
            item.get("status") == "pending"
            and item.get("cheater_agent_id") == cheater.agent_id
            and item.get("affair_partner_agent_id") == affair_partner.agent_id
        )
    ]
    pending.append(request)
    observer.family_json = {**(observer.family_json or {}), PENDING_INFidelity_RESPONSES_KEY: pending}
    return request


def pending_infidelity_response_from(agent: Agent, cheater_agent_id: str, world_time: int) -> dict[str, Any] | None:
    expire_infidelity_responses(agent, world_time)
    for request in _requests(agent):
        if request.get("cheater_agent_id") == cheater_agent_id and _is_pending(request, world_time):
            return request
    return None


def pending_infidelity_response_by_id(agent: Agent, response_id: str, world_time: int) -> dict[str, Any] | None:
    expire_infidelity_responses(agent, world_time)
    for request in _requests(agent):
        if request.get("response_id") == response_id and _is_pending(request, world_time):
            return request
    return None


def resolve_infidelity_response(agent: Agent, response_id: str, world_time: int, status: str) -> None:
    requests: list[dict[str, Any]] = []
    for request in _requests(agent):
        if request.get("response_id") == response_id:
            request = {**request, "status": status, "resolved_world_time": int(world_time)}
        requests.append(request)
    agent.family_json = {**(agent.family_json or {}), PENDING_INFidelity_RESPONSES_KEY: requests}


def has_pending_infidelity_response_from_visible(session: Session, agent: Agent, world_time: int) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    if not visible_ids:
        return False
    expire_infidelity_responses(agent, world_time)
    return any(request.get("cheater_agent_id") in visible_ids and _is_pending(request, world_time) for request in _requests(agent))


def infidelity_response_prompt_lines(session: Session, agent: Agent, world: World, *, language: str = "zh") -> list[str]:
    now = int(world.current_world_time_minutes or 0)
    expire_infidelity_responses(agent, now)
    visible_ids = set(same_location_agent_ids(session, agent))
    lines: list[str] = []
    for request in _requests(agent):
        if not _is_pending(request, now):
            continue
        cheater = session.get(Agent, request.get("cheater_agent_id"))
        affair_partner = session.get(Agent, request.get("affair_partner_agent_id"))
        if not cheater or cheater.agent_id not in visible_ids:
            continue
        other_name = affair_partner.chosen_name if affair_partner else "另一个人"
        if language == "en":
            lines.append(
                f"You noticed {cheater.chosen_name}'s infidelity involving {other_name}. "
                "You may react angrily, forgive, react with excitement, or ignore it; ignoring changes nothing."
            )
        else:
            lines.append(
                f"你发现 {cheater.chosen_name} 和 {other_name} 越过了伴侣边界。"
                "你可以生气、原谅、感到兴奋，也可以装作没看见；只有选择回应工具才会改变关系。"
            )
    return lines
