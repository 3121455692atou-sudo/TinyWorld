from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.models import Agent, World
from app.knowledge.relationships import get_relationship
from app.world.visibility import same_location_agent_ids


PENDING_SOCIAL_REQUESTS_KEY = "pending_social_requests"
SOCIAL_REQUEST_EXPIRES_MINUTES = 4 * 60


@dataclass(frozen=True, slots=True)
class SocialRequestKind:
    request_type: str
    title: str
    request_verb: str
    complete_verb: str
    request_event_type: str = "social_request"
    complete_event_type: str = "social_interaction_completed"
    color_class: str = "important"
    request_importance: int = 50
    complete_importance: int = 65
    actor_delta: dict[str, float] | None = None
    target_delta: dict[str, float] | None = None
    relationship_delta: dict[str, float] | None = None
    requires_relationship_commit: bool = False


SOCIAL_REQUEST_KINDS: dict[str, SocialRequestKind] = {
    "comfort": SocialRequestKind(
        request_type="comfort",
        title="安慰",
        request_verb="提出想陪伴和安慰对方",
        complete_verb="靠近坐了一会儿，认真陪伴并安慰了对方",
        request_event_type="comfort_request",
        complete_event_type="comfort_accepted",
        actor_delta={"social": 3, "stress": -1, "energy": -1},
        target_delta={"social": 4, "stress": -6, "mood": 2},
        relationship_delta={"familiarity": 2, "trust": 3, "affection": 1},
    ),
    "walk_together": SocialRequestKind(
        request_type="walk_together",
        title="一起散步",
        request_verb="邀请对方一起散步",
        complete_verb="并肩走了一小段路，边走边慢慢说话",
        request_event_type="walk_invitation",
        complete_event_type="walk_together",
        actor_delta={"social": 4, "fun": 3, "stress": -3, "energy": -2},
        target_delta={"social": 4, "fun": 3, "stress": -3, "energy": -2},
        relationship_delta={"familiarity": 3, "trust": 1, "affection": 1},
    ),
    "hot_spring": SocialRequestKind(
        request_type="hot_spring",
        title="一起泡温泉",
        request_verb="邀请对方一起去泡温泉",
        complete_verb="一起去了温泉，在热气和水声里放松地聊了一会儿",
        request_event_type="hot_spring_invitation",
        complete_event_type="hot_spring_together",
        actor_delta={"social": 4, "fun": 5, "stress": -4, "hygiene": 18, "energy": -2},
        target_delta={"social": 4, "fun": 5, "stress": -4, "hygiene": 18, "energy": -2},
        relationship_delta={"familiarity": 3, "trust": 1, "affection": 2},
    ),
    "help": SocialRequestKind(
        request_type="help",
        title="帮忙",
        request_verb="向对方请求实际帮助",
        complete_verb="一起处理起了眼前的问题",
        request_event_type="help_request",
        complete_event_type="help_accepted",
        actor_delta={"social": 3, "stress": -2},
        target_delta={"social": 3, "stress": -2, "energy": -1},
        relationship_delta={"familiarity": 2, "trust": 3},
    ),
    "date": SocialRequestKind(
        request_type="date",
        title="约会",
        request_verb="邀请对方进行一次非性化约会或散步",
        complete_verb="一起开始了一段轻松的约会式相处",
        request_event_type="date_request",
        complete_event_type="date_accepted",
        actor_delta={"social": 5, "fun": 5, "stress": -2, "energy": -2},
        target_delta={"social": 5, "fun": 5, "stress": -2, "energy": -2},
        relationship_delta={"familiarity": 4, "trust": 2, "affection": 3},
    ),
    "hold_hands": SocialRequestKind(
        request_type="hold_hands",
        title="牵手",
        request_verb="轻声提出想牵手",
        complete_verb="轻轻牵住了彼此的手",
        request_event_type="hold_hands_request",
        complete_event_type="hold_hands_accepted",
        actor_delta={"social": 4, "fun": 3, "stress": -2, "energy": -1},
        target_delta={"social": 4, "fun": 3, "stress": -2, "energy": -1},
        relationship_delta={"familiarity": 2, "trust": 3, "affection": 4},
    ),
    "hug": SocialRequestKind(
        request_type="hug",
        title="拥抱",
        request_verb="请求一个拥抱",
        complete_verb="短暂地拥抱了一下",
        request_event_type="hug_request",
        complete_event_type="hug_accepted",
        actor_delta={"social": 4, "fun": 2, "stress": -5, "energy": -1},
        target_delta={"social": 4, "fun": 2, "stress": -5, "energy": -1},
        relationship_delta={"familiarity": 2, "trust": 3, "affection": 4},
    ),
    "relationship": SocialRequestKind(
        request_type="relationship",
        title="确认关系",
        request_verb="认真提出确认伴侣关系的请求",
        complete_verb="认真确认了彼此的伴侣关系",
        request_event_type="relationship_request",
        complete_event_type="relationship_confirmed",
        actor_delta={"social": 5, "fun": 4, "stress": -2},
        target_delta={"social": 5, "fun": 4, "stress": -2},
        relationship_delta={"familiarity": 5, "trust": 4, "affection": 6},
        requires_relationship_commit=True,
    ),
}

CORE_SOCIAL_REQUEST_TOOL_TYPES: dict[str, str] = {
    "invite_visible_agent_to_walk": "walk_together",
    "invite_visible_agent_to_hot_spring": "hot_spring",
    "ask_for_help_from_visible_agent": "help",
    "ask_date_visible_agent": "date",
    "hold_hands_visible_agent": "hold_hands",
    "hug_visible_agent": "hug",
    "define_relationship_visible_agent": "relationship",
}

# v5 大目录里也有一批“请求/接受/拒绝”工具。过去它们会落入 v5_catalog_generic，
# 只生成一条抽象事件，导致 A 请求拥抱、B 也请求拥抱时不会合并成真正完成的互动。
# 这里把这些目录工具映射到同一套 pending request 状态机，避免 800+ 工具里存在两套互相打架的语义。
CATALOG_SOCIAL_REQUEST_TOOL_TYPES: dict[str, str] = {
    "tool_social_invite_to_location": "walk_together",
    "tool_romance_ask_walk": "walk_together",
    "tool_romance_ask_date": "date",
    "tool_romance_request_hold_hands": "hold_hands",
    "tool_romance_request_hug": "hug",
    "tool_romance_define_relationship": "relationship",
}

SOCIAL_REQUEST_ACCEPT_TOOL_TYPES: dict[str, str | None] = {
    "accept_social_request_visible_agent": None,
    "tool_social_accept_invite": "walk_together",
    "tool_romance_accept_date": "date",
    "tool_romance_accept_hold_hands": "hold_hands",
    "tool_romance_accept_hug": "hug",
}

SOCIAL_REQUEST_DECLINE_TOOL_TYPES: dict[str, str | None] = {
    "decline_social_request_visible_agent": None,
    "tool_social_decline_invite": "walk_together",
    "tool_romance_decline_date": "date",
    "tool_romance_decline_hold_hands": "hold_hands",
    "tool_romance_decline_hug": "hug",
}

SOCIAL_REQUEST_TOOL_TYPES: dict[str, str] = {
    **CORE_SOCIAL_REQUEST_TOOL_TYPES,
    **CATALOG_SOCIAL_REQUEST_TOOL_TYPES,
}
SOCIAL_REQUEST_RESPONSE_TOOLS = set(SOCIAL_REQUEST_ACCEPT_TOOL_TYPES) | set(SOCIAL_REQUEST_DECLINE_TOOL_TYPES)
SOCIAL_REQUEST_TOOL_NAMES = set(SOCIAL_REQUEST_TOOL_TYPES) | SOCIAL_REQUEST_RESPONSE_TOOLS


def social_request_type_for_tool(tool_name: str) -> str | None:
    return SOCIAL_REQUEST_TOOL_TYPES.get(tool_name)


def is_accept_social_request_tool(tool_name: str) -> bool:
    return tool_name in SOCIAL_REQUEST_ACCEPT_TOOL_TYPES


def is_decline_social_request_tool(tool_name: str) -> bool:
    return tool_name in SOCIAL_REQUEST_DECLINE_TOOL_TYPES


def social_response_request_type_for_tool(tool_name: str) -> str | None:
    if tool_name in SOCIAL_REQUEST_ACCEPT_TOOL_TYPES:
        return SOCIAL_REQUEST_ACCEPT_TOOL_TYPES[tool_name]
    if tool_name in SOCIAL_REQUEST_DECLINE_TOOL_TYPES:
        return SOCIAL_REQUEST_DECLINE_TOOL_TYPES[tool_name]
    return None


def social_request_kind(request_type: str) -> SocialRequestKind:
    return SOCIAL_REQUEST_KINDS[request_type]


def social_request_label(request_type: str) -> str:
    return SOCIAL_REQUEST_KINDS.get(request_type, SOCIAL_REQUEST_KINDS["help"]).title


def social_response_tool_hint(request_type: str) -> tuple[str | None, str | None]:
    accept = next((tool for tool, kind in SOCIAL_REQUEST_ACCEPT_TOOL_TYPES.items() if kind == request_type), None)
    decline = next((tool for tool, kind in SOCIAL_REQUEST_DECLINE_TOOL_TYPES.items() if kind == request_type), None)
    return accept, decline


def make_social_request(*, requester: Agent, target: Agent, request_type: str, world_time: int, message: str | None = None) -> dict[str, Any]:
    return {
        "request_id": f"social_{uuid4().hex[:12]}",
        "from_agent_id": requester.agent_id,
        "to_agent_id": target.agent_id,
        "request_type": request_type,
        "status": "pending",
        "created_world_time": int(world_time),
        "expires_at_world_time": int(world_time) + SOCIAL_REQUEST_EXPIRES_MINUTES,
        "message": (message or ""),
    }


def _family(agent: Agent) -> dict[str, Any]:
    return dict(agent.family_json or {})


def _requests(agent: Agent) -> list[dict[str, Any]]:
    raw = (_family(agent).get(PENDING_SOCIAL_REQUESTS_KEY) or [])
    return [dict(item) for item in raw if isinstance(item, dict)]


def _is_pending(request: dict[str, Any], world_time: int | None = None) -> bool:
    if request.get("status") != "pending":
        return False
    if world_time is None:
        return True
    expires_at = request.get("expires_at_world_time")
    try:
        return int(expires_at) >= int(world_time)
    except (TypeError, ValueError):
        return True


def incoming_social_requests(agent: Agent, world_time: int | None = None, *, include_expired: bool = False) -> list[dict[str, Any]]:
    requests = _requests(agent)
    if not include_expired:
        requests = [request for request in requests if _is_pending(request, world_time)]
    return sorted(requests, key=lambda item: (int(item.get("created_world_time") or 0), str(item.get("request_id") or "")))


def pending_social_request_by_id(agent: Agent, request_id: str, world_time: int | None = None) -> dict[str, Any] | None:
    for request in incoming_social_requests(agent, world_time):
        if str(request.get("request_id") or "") == str(request_id):
            return request
    return None


def pending_social_request_from(agent: Agent, requester_id: str, world_time: int | None = None, request_type: str | None = None) -> dict[str, Any] | None:
    for request in incoming_social_requests(agent, world_time):
        if request.get("from_agent_id") != requester_id:
            continue
        if request_type and request.get("request_type") != request_type:
            continue
        return request
    return None


def store_social_request(target: Agent, request: dict[str, Any]) -> None:
    family = _family(target)
    requests = [
        old
        for old in _requests(target)
        if not (
            old.get("from_agent_id") == request.get("from_agent_id")
            and old.get("to_agent_id") == request.get("to_agent_id")
            and old.get("request_type") == request.get("request_type")
            and old.get("status") == "pending"
        )
    ]
    family[PENDING_SOCIAL_REQUESTS_KEY] = [*requests, request]
    target.family_json = family


def resolve_social_request(target: Agent, requester_id: str, status: str, world_time: int, request_type: str | None = None, request_id: str | None = None) -> dict[str, Any] | None:
    family = _family(target)
    resolved_request: dict[str, Any] | None = None
    resolved: list[dict[str, Any]] = []
    for request in _requests(target):
        if (
            request.get("from_agent_id") == requester_id
            and request.get("status") == "pending"
            and (not request_type or request.get("request_type") == request_type)
            and (not request_id or str(request.get("request_id") or "") == str(request_id))
        ):
            updated = {**request, "status": status, "resolved_world_time": int(world_time)}
            resolved.append(updated)
            if resolved_request is None:
                resolved_request = updated
        else:
            resolved.append(request)
    family[PENDING_SOCIAL_REQUESTS_KEY] = resolved
    target.family_json = family
    return resolved_request


def expire_old_social_requests(agent: Agent, world_time: int) -> None:
    changed = False
    updated: list[dict[str, Any]] = []
    for request in _requests(agent):
        if request.get("status") == "pending" and not _is_pending(request, world_time):
            updated.append({**request, "status": "expired", "resolved_world_time": int(world_time)})
            changed = True
        else:
            updated.append(request)
    if changed:
        family = _family(agent)
        family[PENDING_SOCIAL_REQUESTS_KEY] = updated
        agent.family_json = family


def ranked_incoming_social_requests(session: Session, agent: Agent, world_time: int) -> list[dict[str, Any]]:
    """Requests ordered for fallback/UI when more than one person asks at once."""
    priority_by_type = {
        "adult_boundary": 0,
        "relationship": 10,
        "date": 20,
        "hug": 30,
        "hold_hands": 30,
        "comfort": 35,
        "help": 40,
        "walk_together": 50,
        "hot_spring": 50,
    }

    def score(request: dict[str, Any]) -> tuple[float, int, str]:
        requester_id = str(request.get("from_agent_id") or "")
        rel = get_relationship(session, agent.agent_id, requester_id) if requester_id else None
        warmth = 0.0
        conflict = 0.0
        if rel:
            warmth = rel.trust * 0.45 + rel.affection * 0.35 + rel.familiarity * 0.20
            conflict = rel.conflict + rel.fear
        base = priority_by_type.get(str(request.get("request_type") or ""), 60)
        created = int(request.get("created_world_time") or 0)
        return (base - warmth * 0.05 + conflict * 0.05, created, str(request.get("request_id") or ""))

    return sorted(incoming_social_requests(agent, world_time), key=score)


def choose_social_request_for_fallback(session: Session, agent: Agent, world_time: int) -> dict[str, Any] | None:
    requests = [request for request in ranked_incoming_social_requests(session, agent, world_time) if request.get("from_agent_id") in set(same_location_agent_ids(session, agent))]
    return requests[0] if requests else None


def has_pending_social_request_from_visible(session: Session, agent: Agent, world_time: int, request_type: str | None = None) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    return any(
        request.get("from_agent_id") in visible_ids and (request_type is None or request.get("request_type") == request_type)
        for request in incoming_social_requests(agent, world_time)
    )


def pending_social_request_prompt_lines(session: Session, agent: Agent, world: World) -> list[str]:
    lines: list[str] = []
    visible_ids = set(same_location_agent_ids(session, agent))
    current_requests = [request for request in ranked_incoming_social_requests(session, agent, world.current_world_time_minutes) if request.get("from_agent_id") in visible_ids]
    if len(current_requests) >= 2:
        names = []
        for item in current_requests:
            requester = session.get(Agent, str(item.get("from_agent_id") or ""))
            kind = SOCIAL_REQUEST_KINDS.get(str(item.get("request_type") or ""))
            if requester and kind:
                names.append(f"{requester.chosen_name or '某人'}的{kind.title}")
        if names:
            lines.append("你同时收到了多个请求：" + "、".join(names[:6]) + "。请根据关系、风险和当下状态选择先回应哪一个；不要把几个请求混成同一个人的意思。")
    for request in current_requests:
        requester_id = str(request.get("from_agent_id") or "")
        if requester_id not in visible_ids:
            continue
        requester = session.get(Agent, requester_id)
        if not requester:
            continue
        kind = SOCIAL_REQUEST_KINDS.get(str(request.get("request_type")))
        if not kind:
            continue
        message = str(request.get("message") or "").strip()
        rel = get_relationship(session, agent.agent_id, requester.agent_id)
        rel_hint = f"好感={rel.affection:.0f}, 信任={rel.trust:.0f}, 熟悉={rel.familiarity:.0f}, 冲突={rel.conflict:.0f}, 恐惧={rel.fear:.0f}"
        line = f"{requester.chosen_name or '某人'} 正在等待你回应：{kind.title}（请求ID {request.get('request_id')}）。关系参考: {rel_hint}。"
        if message:
            line += f" 对方原话/意图: {message[:120]}"
        accept_alias, decline_alias = social_response_tool_hint(str(request.get("request_type") or ""))
        accept_hint = f"accept_social_request_visible_agent（或 {accept_alias}）" if accept_alias else "accept_social_request_visible_agent"
        decline_hint = f"decline_social_request_visible_agent（或 {decline_alias}）" if decline_alias else "decline_social_request_visible_agent"
        line += f" 如果你愿意，使用 {accept_hint}；不愿意或想保持距离，使用 {decline_hint}、set_boundary_visible_agent、walk_away_from_visible_agent 或 ignore。"
        lines.append(line)
    return lines
