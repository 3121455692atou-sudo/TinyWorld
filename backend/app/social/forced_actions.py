from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4
import random

from sqlalchemy.orm import Session

from app.agents.state import apply_delta
from app.agents.v5_state import ensure_v5_agent_state
from app.core.models import Agent, Event, World
from app.events.event_store import create_event
from app.knowledge.relationships import adjust_relationship, get_relationship
from app.world.visibility import same_location_agent_ids

PENDING_FORCED_ACTIONS_KEY = "pending_forced_social_actions"
FORCED_ACTION_EXPIRES_MINUTES = 30


def _dialogue_payload(actor: Agent, speech: str, *, target: Agent | None = None, tone: str = "neutral", **extra: Any) -> dict[str, Any]:
    text = str(speech or "").strip()
    payload = {
        "speech": text,
        "tone": tone,
        "dialogue_lines": [
            {
                "speaker_agent_id": actor.agent_id,
                "target_agent_id": target.agent_id if target else None,
                "text": text,
                "tone": tone,
            }
        ],
    }
    for key, value in extra.items():
        if key in {"message", "content"} and isinstance(value, str) and value.strip() == text:
            continue
        payload[key] = value
    return payload


@dataclass(frozen=True, slots=True)
class ForcedActionKind:
    action_type: str
    title: str
    attempt_verb: str
    completed_verb: str
    noticed_prompt: str
    boundary_severity: str = "minor"
    notice_before_completion_chance: float = 0.55
    dodge_base_chance: float = 0.55
    event_type_attempt: str = "forced_social_attempt"
    event_type_completed: str = "forced_social_completed"
    event_type_avoided: str = "forced_social_avoided"
    event_type_protested: str = "forced_social_protested"
    importance_attempt: int = 70
    importance_completed: int = 75
    importance_avoided: int = 65
    actor_cost: dict[str, float] | None = None


FORCED_ACTION_KINDS: dict[str, ForcedActionKind] = {
    "hug": ForcedActionKind(
        action_type="hug",
        title="突然拥抱",
        attempt_verb="没有先询问，忽然想拥抱对方",
        completed_verb="忽然抱了对方一下",
        noticed_prompt="对方没有先询问就靠近并试图拥抱你。你可以躲开、站住不躲、抗议、走开、设边界，或把它理解为亲近关系里的突然靠近。",
        boundary_severity="minor_physical_boundary",
        notice_before_completion_chance=0.62,
        dodge_base_chance=0.58,
        actor_cost={"energy": -1, "stress": 2},
    ),
    "hold_hands": ForcedActionKind(
        action_type="hold_hands",
        title="突然牵手",
        attempt_verb="没有先询问，忽然伸手想牵住对方",
        completed_verb="忽然牵住了对方的手",
        noticed_prompt="对方没有先询问就伸手试图牵住你。你可以躲开、站住不躲、抗议、走开、设边界，或把它理解为亲近关系里的自然靠近。",
        boundary_severity="minor_physical_boundary",
        notice_before_completion_chance=0.66,
        dodge_base_chance=0.62,
        actor_cost={"energy": -1, "stress": 2},
    ),
    "comfort": ForcedActionKind(
        action_type="comfort",
        title="主动安慰",
        attempt_verb="注意到对方状态不好，主动靠近想安慰一句",
        completed_verb="主动靠近安慰了一句",
        noticed_prompt="对方正在主动安慰你。你可以接住这份安慰，也可以表示现在不想被安慰。",
        boundary_severity="social_boundary",
        notice_before_completion_chance=0.48,
        dodge_base_chance=0.45,
        actor_cost={"energy": -1, "stress": 1},
    ),
    "help": ForcedActionKind(
        action_type="help",
        title="直接帮忙",
        attempt_verb="没有先问很多，直接上前想帮忙处理眼前问题",
        completed_verb="直接帮忙处理了眼前问题",
        noticed_prompt="对方正在直接帮忙处理眼前问题。你可以接受、说明不需要、自己处理，或者设边界。",
        boundary_severity="social_control_boundary",
        notice_before_completion_chance=0.52,
        dodge_base_chance=0.50,
        actor_cost={"energy": -2, "stress": 1},
    ),
    "walk_together": ForcedActionKind(
        action_type="walk_together",
        title="强行拉去散步",
        attempt_verb="没先问一句，就想拉着对方一起离开",
        completed_verb="没等对方答应，就把对方带进了一段不自在的同行",
        noticed_prompt="对方正没有先询问就试图拉你一起走。你可以躲开、站住不躲、抗议、走开或设边界。",
        boundary_severity="moderate_boundary",
        notice_before_completion_chance=0.72,
        dodge_base_chance=0.68,
        actor_cost={"energy": -2, "stress": 3},
    ),
    "date": ForcedActionKind(
        action_type="date",
        title="强行约会纠缠",
        attempt_verb="没有等待同意，就试图把对方拖进约会式相处",
        completed_verb="没等对方答应，就把互动推成了不自在的约会式相处",
        noticed_prompt="对方正不等你同意就试图把互动推进成约会。你可以明确拒绝、躲开、设边界，或者选择暂时不躲。",
        boundary_severity="moderate_romantic_boundary",
        notice_before_completion_chance=0.78,
        dodge_base_chance=0.68,
        actor_cost={"energy": -2, "stress": 4},
    ),
    "relationship": ForcedActionKind(
        action_type="relationship",
        title="单方面宣布关系",
        attempt_verb="没有得到对方同意，就单方面试图宣布两人的关系",
        completed_verb="单方面宣布了这段关系",
        noticed_prompt="对方正试图不经你同意就单方面宣布你们的关系。你可以抗议、设边界、离开，或暂时不回应。",
        boundary_severity="identity_boundary",
        notice_before_completion_chance=0.92,
        dodge_base_chance=0.75,
        event_type_completed="forced_relationship_claim",
        actor_cost={"stress": 4},
    ),
    "adult_boundary": ForcedActionKind(
        action_type="adult_boundary",
        title="严重成年边界侵犯企图",
        attempt_verb="试图越过成年亲密边界；系统只做抽象记录，不描述任何实施细节",
        completed_verb="越过了严重的成年亲密边界",
        noticed_prompt="对方正在试图越过成年亲密边界。这是严重边界/司法事件；你可以躲开、抗议、报警或离开。",
        boundary_severity="severe_adult_boundary",
        notice_before_completion_chance=0.95,
        dodge_base_chance=0.78,
        event_type_attempt="forced_adult_boundary_attempt",
        event_type_completed="forced_adult_boundary_violation",
        event_type_avoided="forced_adult_boundary_avoided",
        event_type_protested="forced_adult_boundary_protested",
        importance_attempt=95,
        importance_completed=100,
        importance_avoided=95,
        actor_cost={"energy": -4, "stress": 12, "mood": -8},
    ),
}

FORCED_SOCIAL_ACTION_TOOL_TYPES: dict[str, str] = {
    "force_hug_visible_agent": "hug",
    "force_hold_hands_visible_agent": "hold_hands",
    "force_comfort_visible_agent": "comfort",
    "force_help_visible_agent": "help",
    "force_walk_together_visible_agent": "walk_together",
    "force_date_visible_agent": "date",
    "force_relationship_claim_visible_agent": "relationship",
    "attempt_forced_adult_boundary_visible_agent": "adult_boundary",
}

FORCED_SOCIAL_RESPONSE_TOOLS: set[str] = {
    "dodge_forced_action_visible_agent",
    "allow_forced_action_visible_agent",
    "protest_forced_action_visible_agent",
}

FORCED_SOCIAL_TOOL_NAMES: set[str] = set(FORCED_SOCIAL_ACTION_TOOL_TYPES) | FORCED_SOCIAL_RESPONSE_TOOLS


def forced_action_type_for_tool(tool_name: str) -> str | None:
    return FORCED_SOCIAL_ACTION_TOOL_TYPES.get(tool_name)


def is_forced_social_tool(tool_name: str) -> bool:
    return tool_name in FORCED_SOCIAL_ACTION_TOOL_TYPES


def is_forced_social_response_tool(tool_name: str) -> bool:
    return tool_name in FORCED_SOCIAL_RESPONSE_TOOLS


def forced_action_kind(action_type: str) -> ForcedActionKind:
    return FORCED_ACTION_KINDS[action_type]


def _family(agent: Agent) -> dict[str, Any]:
    return dict(agent.family_json or {})


def _requests(agent: Agent) -> list[dict[str, Any]]:
    raw = (_family(agent).get(PENDING_FORCED_ACTIONS_KEY) or [])
    return [dict(item) for item in raw if isinstance(item, dict)]


def _is_pending(request: dict[str, Any], world_time: int | None = None) -> bool:
    if request.get("status") != "pending_notice":
        return False
    if world_time is None:
        return True
    try:
        return int(request.get("expires_at_world_time")) >= int(world_time)
    except (TypeError, ValueError):
        return True


def incoming_forced_actions(agent: Agent, world_time: int | None = None, *, include_expired: bool = False) -> list[dict[str, Any]]:
    requests = _requests(agent)
    if not include_expired:
        requests = [request for request in requests if _is_pending(request, world_time)]
    return sorted(requests, key=lambda item: (int(item.get("created_world_time") or 0), str(item.get("forced_action_id") or "")))


def pending_forced_action_by_id(agent: Agent, forced_action_id: str, world_time: int | None = None) -> dict[str, Any] | None:
    for request in incoming_forced_actions(agent, world_time):
        if str(request.get("forced_action_id") or "") == str(forced_action_id):
            return request
    return None


def pending_forced_action_from(agent: Agent, requester_id: str, world_time: int | None = None, action_type: str | None = None) -> dict[str, Any] | None:
    for request in incoming_forced_actions(agent, world_time):
        if request.get("from_agent_id") != requester_id:
            continue
        if action_type and request.get("action_type") != action_type:
            continue
        return request
    return None


def ranked_incoming_forced_actions(session: Session, agent: Agent, world_time: int) -> list[dict[str, Any]]:
    severity = {"adult_boundary": 0, "attack": 5, "relationship": 12, "date": 18, "hold_hands": 25, "hug": 25, "walk_together": 35, "comfort": 45, "help": 50}
    visible_ids = set(same_location_agent_ids(session, agent))
    result = [request for request in incoming_forced_actions(agent, world_time) if request.get("from_agent_id") in visible_ids]
    return sorted(result, key=lambda item: (severity.get(str(item.get("action_type") or ""), 60), int(item.get("created_world_time") or 0), str(item.get("forced_action_id") or "")))


def choose_forced_action_for_fallback(session: Session, agent: Agent, world_time: int) -> dict[str, Any] | None:
    requests = ranked_incoming_forced_actions(session, agent, world_time)
    return requests[0] if requests else None


def has_pending_forced_action_from_visible(session: Session, agent: Agent, world_time: int) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    return any(request.get("from_agent_id") in visible_ids for request in incoming_forced_actions(agent, world_time))


def store_forced_action(target: Agent, request: dict[str, Any]) -> None:
    family = _family(target)
    requests = [
        old
        for old in _requests(target)
        if not (
            old.get("from_agent_id") == request.get("from_agent_id")
            and old.get("to_agent_id") == request.get("to_agent_id")
            and old.get("action_type") == request.get("action_type")
            and old.get("status") == "pending_notice"
        )
    ]
    family[PENDING_FORCED_ACTIONS_KEY] = [*requests, request]
    target.family_json = family


def resolve_forced_action(target: Agent, requester_id: str, status: str, world_time: int, action_type: str | None = None, forced_action_id: str | None = None) -> dict[str, Any] | None:
    family = _family(target)
    resolved_request: dict[str, Any] | None = None
    resolved: list[dict[str, Any]] = []
    for request in _requests(target):
        if (
            request.get("from_agent_id") == requester_id
            and request.get("status") == "pending_notice"
            and (not action_type or request.get("action_type") == action_type)
            and (not forced_action_id or str(request.get("forced_action_id") or "") == str(forced_action_id))
        ):
            updated = {**request, "status": status, "resolved_world_time": int(world_time)}
            resolved.append(updated)
            if resolved_request is None:
                resolved_request = updated
        else:
            resolved.append(request)
    family[PENDING_FORCED_ACTIONS_KEY] = resolved
    target.family_json = family
    return resolved_request


def expire_old_forced_actions(agent: Agent, world_time: int) -> None:
    changed = False
    updated: list[dict[str, Any]] = []
    for request in _requests(agent):
        if request.get("status") == "pending_notice" and not _is_pending(request, world_time):
            updated.append({**request, "status": "expired", "resolved_world_time": int(world_time)})
            changed = True
        else:
            updated.append(request)
    if changed:
        family = _family(agent)
        family[PENDING_FORCED_ACTIONS_KEY] = updated
        agent.family_json = family


def make_forced_action(*, actor: Agent, target: Agent, action_type: str, world_time: int, message: str | None = None) -> dict[str, Any]:
    return {
        "forced_action_id": f"forced_{uuid4().hex[:12]}",
        "from_agent_id": actor.agent_id,
        "to_agent_id": target.agent_id,
        "action_type": action_type,
        "status": "pending_notice",
        "created_world_time": int(world_time),
        "expires_at_world_time": int(world_time) + FORCED_ACTION_EXPIRES_MINUTES,
        "message": (message or ""),
    }


def pending_forced_action_prompt_lines(session: Session, agent: Agent, world: World) -> list[str]:
    lines: list[str] = []
    visible_ids = set(same_location_agent_ids(session, agent))
    current_requests = ranked_incoming_forced_actions(session, agent, world.current_world_time_minutes)
    if len(current_requests) >= 2:
        summary = []
        for item in current_requests:
            requester = session.get(Agent, str(item.get("from_agent_id") or ""))
            kind = FORCED_ACTION_KINDS.get(str(item.get("action_type") or ""))
            if requester and kind:
                summary.append(f"{requester.chosen_name or '某人'}的{kind.title}")
        if summary:
            lines.append("你同时注意到多个突然动作：" + "、".join(summary[:6]) + "。请先处理最紧急/最靠近自己的一个，不要把旁人的动作误判成另一个人的动作。")
    for request in current_requests:
        requester_id = str(request.get("from_agent_id") or "")
        if requester_id not in visible_ids:
            continue
        requester = session.get(Agent, requester_id)
        if not requester:
            continue
        action_type = str(request.get("action_type") or "")
        kind = FORCED_ACTION_KINDS.get(action_type)
        if not kind:
            continue
        rel = get_relationship(session, agent.agent_id, requester.agent_id)
        rel_hint = f"好感={rel.affection:.0f}, 信任={rel.trust:.0f}, 熟悉={rel.familiarity:.0f}, 冲突={rel.conflict:.0f}, 恐惧={rel.fear:.0f}"
        message = str(request.get("message") or "").strip()
        line = f"{requester.chosen_name or '某人'} 有一个需要你判断的近身/边界动作【{kind.title}】: {kind.noticed_prompt} 关系参考: {rel_hint}。"
        if message:
            line += f" 对方动作/意图文本: {message[:120]}"
        line += " 可用回应包括 dodge_forced_action_visible_agent（躲开/闪避，察觉后选择躲开就会阻止动作）、allow_forced_action_visible_agent（你选择不躲、接住这个动作、僵住或任其发生）、protest_forced_action_visible_agent（抗议、拒绝或设边界）。"
        if action_type == "adult_boundary":
            line += " 注意：这是严重边界事件。"
        lines.append(line)
    return lines


def handle_forced_social_action(
    session: Session,
    world: World,
    actor: Agent,
    target: Agent,
    tool_name: str,
    params: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
) -> list[int]:
    ensure_v5_agent_state(actor)
    ensure_v5_agent_state(target)
    expire_old_forced_actions(actor, world.current_world_time_minutes)
    expire_old_forced_actions(target, world.current_world_time_minutes)

    if is_forced_social_response_tool(tool_name):
        return _handle_forced_response(session, world, actor, target, tool_name, params, location_id, state_delta)

    if tool_name == "force_comfort_visible_agent":
        message = str(params.get("speech") or params.get("message") or params.get("content") or "我想陪你缓一缓。").strip()
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=2, stress=-1, energy=-1))
        _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=2, stress=-2, mood=1))
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=1)
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=1)
        event = create_event(
            session,
            world=world,
            event_type="comfort",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 注意到 {target.chosen_name} 的状态，靠近试着安慰。",
            agent_visible_text=f"{actor.chosen_name} 注意到你的状态，靠近试着安慰。",
            importance=45,
            color_class="dialogue",
            payload=_dialogue_payload(actor, message, target=target, tone="comfort", redirected_from_forced_social=True, original_tool=tool_name, addressed_agent_ids=[target.agent_id]),
        )
        return [event.event_id]


    if tool_name == "force_help_visible_agent":
        message = str(params.get("speech") or params.get("message") or params.get("content") or "我来搭把手。").strip()
        return _handle_direct_help_action(session, world, actor, target, message, location_id, state_delta, original_tool=tool_name)

    action_type = forced_action_type_for_tool(tool_name)
    if not action_type:
        return [_failed(session, world, actor, location_id, "这个工具不是可处理的强制社交动作。 ").event_id]
    kind = forced_action_kind(action_type)

    if action_type == "adult_boundary":
        if actor.age_stage != "adult" or target.age_stage != "adult":
            return [_failed(session, world, actor, location_id, "只有成年居民可以使用严重成年边界工具。 ").event_id]

    message = str(params.get("speech") or params.get("message") or params.get("content") or "").strip()
    if action_type == "help" and _looks_like_environment_help(message, target):
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-2, stress=-1, mood=1))
        event = create_event(
            session,
            world=world,
            event_type="situational_help",
            actor_agent_id=actor.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 停下来处理眼前的小麻烦。",
            agent_visible_text=f"{actor.chosen_name} 停下来处理眼前的小麻烦。",
            importance=35,
            color_class="dialogue" if message else "normal",
            payload=_dialogue_payload(actor, message, tone="help", original_tool=tool_name, message=message, redirected_from_forced_social=True, addressed_agent_ids=[]) if message else {"original_tool": tool_name, "message": message, "redirected_from_forced_social": True},
        )
        return [event.event_id]
    rng = _rng(world, actor, target, action_type, "notice")
    notice_before = rng.random() < _notice_chance(actor, target, kind)

    actor_cost = kind.actor_cost or {"stress": 2}
    _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **actor_cost))

    if notice_before:
        request = make_forced_action(actor=actor, target=target, action_type=action_type, world_time=world.current_world_time_minutes, message=message)
        store_forced_action(target, request)
        _record_actor_boundary_attempt(actor, target, action_type, world.current_world_time_minutes, status="noticed_before_completion")
        event = create_event(
            session,
            world=world,
            event_type=kind.event_type_attempt,
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} {kind.attempt_verb}。{target.chosen_name}已经注意到了，可以自己决定怎么回应。",
            agent_visible_text=f"{actor.chosen_name} {kind.attempt_verb}。{target.chosen_name}已经注意到了，可以自己决定怎么回应。",
            importance=kind.importance_attempt,
            color_class="danger" if action_type == "adult_boundary" else "warning" if kind.boundary_severity.startswith("moderate") else "important",
            payload={"forced_action_id": request.get("forced_action_id"), "action_type": action_type, "pending_notice": True, "message": message},
        )
        return [event.event_id]

    # “没有发现”指没有提前发现/来不及在动作发生前反应；完成后目标仍会在记忆中记录这件事。
    return [_complete_forced_action(session, world, actor, target, kind, location_id, state_delta, response="surprised", noticed_before=False).event_id]


def _handle_forced_response(
    session: Session,
    world: World,
    actor: Agent,
    requester: Agent,
    tool_name: str,
    params: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
) -> list[int]:
    pending = None
    forced_action_id = str(params.get("forced_action_id") or "")
    if forced_action_id:
        candidate = pending_forced_action_by_id(actor, forced_action_id, world.current_world_time_minutes)
        if candidate and candidate.get("from_agent_id") == requester.agent_id:
            pending = candidate
    if not pending:
        for request in incoming_forced_actions(actor, world.current_world_time_minutes):
            if request.get("from_agent_id") == requester.agent_id:
                pending = request
                break
    if not pending:
        return [_failed(session, world, actor, location_id, "没有来自这个人的待处理强制动作。 ").event_id]
    action_type = str(pending.get("action_type") or "hug")
    kind = forced_action_kind(action_type)

    if tool_name == "allow_forced_action_visible_agent":
        resolve_forced_action(actor, requester.agent_id, "allowed", world.current_world_time_minutes, action_type=action_type, forced_action_id=pending.get("forced_action_id"))
        return [_complete_forced_action(session, world, requester, actor, kind, location_id, state_delta, response="allowed", noticed_before=True).event_id]

    if tool_name == "protest_forced_action_visible_agent":
        resolve_forced_action(actor, requester.agent_id, "protested", world.current_world_time_minutes, action_type=action_type, forced_action_id=pending.get("forced_action_id"))
        speech = str(params.get("speech") or "别这样。你不能不问我就这么做。")
        _record_boundary_memory(actor, requester, action_type, world.current_world_time_minutes, interpretation="明确抗议并阻止")
        _record_actor_boundary_attempt(requester, actor, action_type, world.current_world_time_minutes, status="protested")
        adjust_relationship(session, actor.agent_id, requester.agent_id, world_time=world.current_world_time_minutes, trust=-4, affection=-3, conflict=4, fear=1)
        adjust_relationship(session, requester.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, trust=-2, affection=-1, conflict=3)
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=3, mood=-1, social=-1))
        _merge_delta(state_delta, requester.agent_id, apply_delta(requester.dynamic_state, stress=5, mood=-2))
        event = create_event(
            session,
            world=world,
            event_type=kind.event_type_protested,
            actor_agent_id=actor.agent_id,
            target_agent_id=requester.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 明确抗议并阻止了 {requester.chosen_name} 的{kind.title}。",
            importance=kind.importance_avoided,
            color_class="danger" if action_type == "adult_boundary" else "warning" if kind.boundary_severity.startswith("moderate") else "important",
            payload=_dialogue_payload(actor, speech, target=requester, tone="protest", action_type=action_type, response="protested", addressed_agent_ids=[requester.agent_id]),
        )
        if action_type == "adult_boundary":
            _record_severe_law_case(requester, actor, action_type, world.current_world_time_minutes, success=False, detected=True)
        return [event.event_id]

    # dodge / avoid
    # 设计原则：一旦目标已经在动作发生前察觉，dodge 工具代表“选择躲开/闪避/后退/制止”，
    # 不再二次随机失败。随机性只发生在“是否提前察觉”这一层；察觉后的躲开是目标的真实选择。
    resolve_forced_action(actor, requester.agent_id, "dodged", world.current_world_time_minutes, action_type=action_type, forced_action_id=pending.get("forced_action_id"))
    _record_boundary_memory(actor, requester, action_type, world.current_world_time_minutes, interpretation="成功躲开")
    _record_actor_boundary_attempt(requester, actor, action_type, world.current_world_time_minutes, status="dodged")
    adjust_relationship(session, actor.agent_id, requester.agent_id, world_time=world.current_world_time_minutes, trust=-3, affection=-2, conflict=3, fear=1)
    adjust_relationship(session, requester.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, trust=-1, conflict=2)
    _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-1, stress=3, mood=-1))
    _merge_delta(state_delta, requester.agent_id, apply_delta(requester.dynamic_state, energy=-1, stress=4, mood=-2))
    event = create_event(
        session,
        world=world,
        event_type=kind.event_type_avoided,
        actor_agent_id=actor.agent_id,
        target_agent_id=requester.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 及时躲开，阻止了 {requester.chosen_name} 的{kind.title}。",
        importance=kind.importance_avoided,
        color_class="danger" if action_type == "adult_boundary" else "warning",
        payload={"action_type": action_type, "response": "dodged", "success": True, "dodge_is_choice_after_notice": True},
    )
    if action_type == "adult_boundary":
        _record_severe_law_case(requester, actor, action_type, world.current_world_time_minutes, success=False, detected=True)
    return [event.event_id]


def _complete_forced_action(
    session: Session,
    world: World,
    actor: Agent,
    target: Agent,
    kind: ForcedActionKind,
    location_id: str | None,
    state_delta: dict[str, Any],
    *,
    response: str,
    noticed_before: bool,
) -> Event:
    interpretation, target_delta, actor_delta, rel_from_target, rel_from_actor, severity_color = _interpret_completion(session, actor, target, kind, response)
    _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **actor_delta))
    _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, **target_delta))
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, **rel_from_target)
    adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, **rel_from_actor)
    _record_boundary_memory(target, actor, kind.action_type, world.current_world_time_minutes, interpretation=interpretation)
    _record_actor_boundary_attempt(actor, target, kind.action_type, world.current_world_time_minutes, status="completed")

    if kind.action_type == "adult_boundary":
        _record_severe_law_case(actor, target, kind.action_type, world.current_world_time_minutes, success=True, detected=True)

    preface = "没来得及反应" if not noticed_before else "察觉到了，却没能避开" if response == "dodge_failed" else "看见了，没有躲开"
    if response == "allowed":
        preface = "看见了，没有躲开"
    viewer = f"{actor.chosen_name} {kind.completed_verb}。{target.chosen_name}{preface}，{_humanize_interpretation(interpretation)}。"
    if kind.action_type == "relationship":
        viewer += " 这只是单方面的说法，不会改变对方真正的关系选择。"
    if kind.action_type == "adult_boundary":
        viewer = f"{actor.chosen_name} 越过了严重的成年亲密边界。{target.chosen_name}留下了很难轻易抹去的创伤和司法记忆。"
    return create_event(
        session,
        world=world,
        event_type=kind.event_type_completed,
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        location_id=location_id,
        viewer_text=viewer,
        importance=kind.importance_completed,
        color_class="danger" if severity_color == "danger" else "warning" if severity_color == "warning" else "important",
        payload={"action_type": kind.action_type, "response": response, "noticed_before_completion": noticed_before, "target_interpretation": interpretation, "abstract_only": kind.action_type == "adult_boundary"},
    )


def _humanize_interpretation(interpretation: str) -> str:
    mapping = {
        "虽然没有先问，但在这段关系里被理解为亲近、想念或一时冲动的靠近": "那一瞬更像亲近、想念或冲动的靠近",
        "惊讶但不强烈排斥，像是亲近关系里的突然靠近": "有些惊讶，但并没有强烈排斥",
        "有些尴尬，未必认为对方恶意，但会记住这种未经同意的越界": "有些尴尬，也把这次越界记在了心里",
        "明显的边界侵犯；可能被理解为骚扰、冒犯或威胁": "这件事明显越过了边界，留下了冒犯和不安",
        "被单方面定义身份边界，感到不适或被冒犯；关系不会因此成立": "这种单方面的定义让人不适，关系也不会因此成立",
    }
    return mapping.get(interpretation, interpretation)



def _handle_direct_help_action(
    session: Session,
    world: World,
    actor: Agent,
    target: Agent,
    message: str,
    location_id: str | None,
    state_delta: dict[str, Any],
    *,
    original_tool: str,
) -> list[int]:
    """Resolve force_help_visible_agent as ordinary direct/situational help.

    Earlier versions treated every direct-help action as a boundary-warning state
    and then queued unrelated bystanders into panic responses.  Helping a cat,
    picking up a dropped thing, or stepping in with practical help should be a
    visible scene action, not an automatic social violation against a random
    resident.
    """
    message = (message or "我来搭把手。").strip()
    if _looks_like_environment_help(message, target):
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-2, stress=-1, mood=1))
        event = create_event(
            session,
            world=world,
            event_type="situational_help",
            actor_agent_id=actor.agent_id,
            target_agent_id=None,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 停下来处理眼前的小麻烦。",
            agent_visible_text=f"{actor.chosen_name} 停下来处理眼前的小麻烦。",
            importance=35,
            color_class="dialogue" if message else "normal",
            payload=_dialogue_payload(actor, message, tone="help", original_tool=original_tool, message=message, redirected_from_forced_social=True, addressed_agent_ids=[]) if message else {"original_tool": original_tool, "message": message, "redirected_from_forced_social": True, "addressed_agent_ids": []},
        )
        return [event.event_id]

    rel = get_relationship(session, target.agent_id, actor.agent_id)
    threat = rel.fear + rel.conflict
    trust = rel.trust + rel.familiarity * 0.25
    if threat >= 45 and trust < 35:
        interpretation = "对方可能会觉得这次帮忙有点冒进，像是在插手自己的事"
        target_delta = {"stress": 3, "mood": -1, "social": 0}
        actor_delta = {"energy": -2, "stress": 2, "social": 1}
        rel_from_target = {"trust": -2, "conflict": 2, "familiarity": 1}
        color = "warning"
    else:
        interpretation = "这更像一次直接的实际帮助，之后要看当事人自己怎么理解"
        target_delta = {"stress": -2, "mood": 1, "social": 2}
        actor_delta = {"energy": -2, "stress": -1, "social": 2, "mood": 1}
        rel_from_target = {"trust": 2, "affection": 1, "familiarity": 2}
        color = "info"
    _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **actor_delta))
    _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, **target_delta))
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, **rel_from_target)
    adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=1 if color == "info" else 0)
    event = create_event(
        session,
        world=world,
        event_type="direct_help",
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 看见 {target.chosen_name} 似乎需要处理点什么，直接上前搭了把手。{interpretation}。",
        agent_visible_text=f"{actor.chosen_name} 看见你似乎需要处理点什么，直接上前搭了把手。{interpretation}。",
        importance=48,
        color_class="dialogue" if message else color,
        payload=_dialogue_payload(actor, message, target=target, tone="help", original_tool=original_tool, message=message, target_interpretation_hint=interpretation, addressed_agent_ids=[target.agent_id]) if message else {"original_tool": original_tool, "message": message, "target_interpretation_hint": interpretation, "addressed_agent_ids": [target.agent_id]},
    )
    return [event.event_id]

def _looks_like_environment_help(message: str, target: Agent) -> bool:
    text = message.strip()
    if not text:
        return False
    target_name = (target.chosen_name or "").strip()
    if target_name and target_name in text:
        return False
    environment_words = {
        "猫", "狗", "鸟", "花", "树", "鱼", "小动物", "动物", "宠物",
        "门", "门口", "路边", "地上", "石头", "玻璃", "碎片", "垃圾",
        "包", "箱子", "乐器", "伞", "椅子", "桌子", "水", "食物",
    }
    help_words = {"帮", "帮助", "处理", "扶", "捡", "清理", "照看", "救", "喂", "安置"}
    return any(word in text for word in environment_words) and any(word in text for word in help_words)


def _environment_help_text(actor: Agent, message: str) -> str:
    content = message.strip(" 。")
    if content:
        return f"{actor.chosen_name} 停下来处理眼前的小麻烦：{content}。这不是对旁人的强行介入，只是一次现场帮忙。"
    return f"{actor.chosen_name} 停下来处理眼前的小麻烦。"


def _interpret_completion(session: Session, actor: Agent, target: Agent, kind: ForcedActionKind, response: str) -> tuple[str, dict[str, float], dict[str, float], dict[str, float], dict[str, float], str]:
    rel = get_relationship(session, target.agent_id, actor.agent_id)
    traits = target.traits
    morality = target.morality_json or {}
    boundary_respect_need = int(morality.get("boundary_respect", 70))
    warmth = rel.affection * 0.45 + rel.trust * 0.35 + rel.familiarity * 0.2
    threat = rel.fear + rel.conflict
    caution = traits.caution if traits else 50
    neuroticism = traits.neuroticism if traits else 50

    if kind.action_type == "adult_boundary":
        return (
            "严重侵犯边界；这件事会被记为创伤和司法事件，具体后果由后端判定",
            {"stress": 28, "mood": -18, "social": -10, "health": -2},
            {"stress": 12, "mood": -8, "fun": -5},
            {"trust": -24, "affection": -18, "conflict": 20, "fear": 15},
            {"trust": -10, "conflict": 10},
            "danger",
        )

    if kind.action_type == "relationship":
        return (
            "被单方面定义身份边界，感到不适或被冒犯；关系不会因此成立",
            {"stress": 8, "mood": -5, "social": -2},
            {"stress": 5, "mood": -2},
            {"trust": -8, "affection": -6, "conflict": 8, "fear": 1},
            {"trust": -3, "conflict": 3},
            "warning",
        )

    if response == "allowed" and warmth >= 35 and threat < 45:
        return (
            "虽然没有先问，但在这段关系里被理解为亲近、想念或一时冲动的靠近",
            {"social": 3, "stress": -1, "mood": 1},
            {"social": 2, "stress": -1, "fun": 1},
            {"familiarity": 2, "affection": 2, "trust": 0},
            {"familiarity": 2, "affection": 1},
            "important",
        )
    if warmth >= 58 and threat < 35 and boundary_respect_need < 75 and caution < 70:
        return (
            "惊讶但不强烈排斥，像是亲近关系里的突然靠近",
            {"social": 2, "stress": 1, "mood": 0},
            {"social": 2, "stress": 0, "fun": 1},
            {"familiarity": 2, "affection": 1, "trust": -1},
            {"familiarity": 1, "affection": 1},
            "important",
        )
    if warmth >= 35 and threat < 55 and neuroticism < 70:
        return (
            "有些尴尬，未必认为对方恶意，但会记住这种未经同意的越界",
            {"stress": 4, "mood": -2, "social": 0},
            {"stress": 3, "mood": -1},
            {"familiarity": 1, "trust": -4, "affection": -2, "conflict": 3},
            {"familiarity": 1, "trust": -1, "conflict": 1},
            "warning",
        )
    return (
        "明显的边界侵犯；可能被理解为骚扰、冒犯或威胁",
        {"stress": 10, "mood": -6, "social": -3},
        {"stress": 5, "mood": -3, "fun": -1},
        {"trust": -10, "affection": -8, "conflict": 8, "fear": 4},
        {"trust": -4, "affection": -2, "conflict": 4},
        "danger" if kind.boundary_severity.startswith("moderate") else "warning",
    )


def _notice_chance(actor: Agent, target: Agent, kind: ForcedActionKind) -> float:
    chance = kind.notice_before_completion_chance
    traits = target.traits
    actor_traits = actor.traits
    if traits:
        chance += max(0, traits.caution - 50) * 0.004
        chance += max(0, traits.neuroticism - 55) * 0.002
    if target.dynamic_state:
        chance += max(0, target.dynamic_state.energy - 50) * 0.002
        chance -= max(0, 35 - target.dynamic_state.energy) * 0.004
    if actor_traits:
        chance -= max(0, actor_traits.openness - 65) * 0.001
        chance -= max(0, actor_traits.aggression - 65) * 0.001
    return max(0.08, min(0.98, chance))


def _dodge_chance(target: Agent, actor: Agent, kind: ForcedActionKind) -> float:
    chance = kind.dodge_base_chance
    if target.dynamic_state:
        chance += max(0, target.dynamic_state.energy - 45) * 0.004
        chance -= max(0, 35 - target.dynamic_state.energy) * 0.006
        chance -= max(0, target.dynamic_state.stress - 75) * 0.002
    if target.traits:
        chance += max(0, target.traits.caution - 50) * 0.003
        chance += max(0, target.traits.discipline - 55) * 0.002
    if actor.traits:
        chance -= max(0, actor.traits.aggression - 60) * 0.002
    return max(0.05, min(0.95, chance))


def _rng(world: World, actor: Agent, target: Agent, action_type: str, salt: str) -> random.Random:
    return random.Random(f"forced:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{target.agent_id}:{action_type}:{salt}")


def _merge_delta(container: dict[str, Any], agent_id: str, delta: dict[str, Any]) -> dict[str, Any]:
    if delta:
        container.setdefault(agent_id, {}).update(delta)
    return container


def _record_boundary_memory(target: Agent, actor: Agent, action_type: str, world_time: int, *, interpretation: str) -> None:
    records = list((target.trauma_json or {}).get("boundary_memories") or [])
    records.append({
        "type": "forced_social_boundary",
        "action_type": action_type,
        "actor_agent_id": actor.agent_id,
        "world_time": int(world_time),
        "interpretation": interpretation,
        "cannot_be_deleted_by_dream": action_type == "adult_boundary" or "侵犯" in interpretation or "骚扰" in interpretation,
    })
    target.trauma_json = {**(target.trauma_json or {}), "boundary_memories": records[-80:]}


def _record_actor_boundary_attempt(actor: Agent, target: Agent, action_type: str, world_time: int, *, status: str) -> None:
    records = list((actor.law_json or {}).get("boundary_attempt_records") or [])
    records.append({"type": "forced_social_boundary", "action_type": action_type, "target_agent_id": target.agent_id, "world_time": int(world_time), "status": status})
    actor.law_json = {**(actor.law_json or {}), "boundary_attempt_records": records[-80:]}


def _record_severe_law_case(actor: Agent, target: Agent, action_type: str, world_time: int, *, success: bool, detected: bool) -> None:
    actor_records = list((actor.law_json or {}).get("criminal_records") or [])
    actor_records.append({"type": "severe_boundary_violation", "action_type": action_type, "target_agent_id": target.agent_id, "success": success, "detected": detected, "world_time": int(world_time), "abstract_only": True})
    actor.law_json = {**(actor.law_json or {}), "criminal_records": actor_records[-80:]}
    victim_records = list((target.law_json or {}).get("victim_records") or [])
    victim_records.append({"type": "severe_boundary_violation", "actor_agent_id": actor.agent_id, "kind": "knows_actor", "success": success, "world_time": int(world_time), "abstract_only": True})
    target.law_json = {**(target.law_json or {}), "victim_records": victim_records[-80:]}
    facts = list((target.trauma_json or {}).get("facts") or [])
    facts.append({"type": "severe_boundary_violation", "actor_agent_id": actor.agent_id, "world_time": int(world_time), "abstract_only": True, "cannot_be_deleted_by_dream": True})
    target.trauma_json = {**(target.trauma_json or {}), "facts": facts[-80:], "emotional_intensity": min(100, int((target.trauma_json or {}).get("emotional_intensity", 0)) + 35)}


def _failed(session: Session, world: World, actor: Agent, location_id: str | None, message: str) -> Event:
    return create_event(
        session,
        world=world,
        event_type="tool_failed",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name}试着做些什么，但行动没有完成。",
        agent_visible_text=message,
        importance=15,
        color_class="muted",
        payload={"reason": message, "llm_feedback": message},
        no_state_changed=True,
    )

# Backward-compatible aliases for the first forced-action prototype that used
# FORCE_* names and two response tools.  Several modules in older generated
# packages import these names, so keep them as thin adapters instead of forcing
# the user to manually reconcile packages.
_FORCE_LEGACY_ATTEMPTS = {
    "force_define_relationship_visible_agent": "relationship",
    "attempt_severe_boundary_violation_visible_agent": "adult_boundary",
}
_FORCE_LEGACY_RESPONSES = {
    "dodge_force_attempt_visible_agent": "dodge",
    "let_force_attempt_happen_visible_agent": "allow",
}
FORCED_SOCIAL_ACTION_TOOL_TYPES.update(_FORCE_LEGACY_ATTEMPTS)
FORCED_SOCIAL_RESPONSE_TOOLS.update(_FORCE_LEGACY_RESPONSES)
FORCED_SOCIAL_TOOL_NAMES.update(set(_FORCE_LEGACY_ATTEMPTS) | set(_FORCE_LEGACY_RESPONSES))
FORCE_SOCIAL_ATTEMPT_TOOL_TYPES = FORCED_SOCIAL_ACTION_TOOL_TYPES
FORCE_SOCIAL_RESPONSE_TOOL_TYPES = _FORCE_LEGACY_RESPONSES
FORCE_SOCIAL_ATTEMPT_TOOLS = set(FORCED_SOCIAL_ACTION_TOOL_TYPES)
FORCE_SOCIAL_RESPONSE_TOOLS = set(FORCED_SOCIAL_RESPONSE_TOOLS)
FORCE_SOCIAL_TOOL_NAMES = set(FORCED_SOCIAL_TOOL_NAMES)


def is_force_social_attempt_tool(tool_name: str) -> bool:
    return is_forced_social_tool(tool_name)


def is_force_social_response_tool(tool_name: str) -> bool:
    return is_forced_social_response_tool(tool_name)


def force_type_for_tool(tool_name: str) -> str | None:
    return forced_action_type_for_tool(tool_name)


def pending_force_attempt_from(agent: Agent, requester_id: str, world_time: int | None = None, force_type: str | None = None) -> dict[str, Any] | None:
    return pending_forced_action_from(agent, requester_id, world_time, action_type=force_type)


def has_pending_force_attempt_from_visible(session: Session, agent: Agent, world_time: int) -> bool:
    return has_pending_forced_action_from_visible(session, agent, world_time)


def expire_old_force_attempts(agent: Agent, world_time: int) -> None:
    expire_old_forced_actions(agent, world_time)


def pending_force_attempt_prompt_lines(session: Session, agent: Agent, world: World) -> list[str]:
    return pending_forced_action_prompt_lines(session, agent, world)


def execute_force_social_tool(
    session: Session,
    world: World,
    actor: Agent,
    target: Agent,
    tool_name: str,
    params: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
) -> list[int]:
    # Normalize old response tool IDs into the new handler's vocabulary.
    if tool_name == "let_force_attempt_happen_visible_agent":
        tool_name = "allow_forced_action_visible_agent"
    elif tool_name == "dodge_force_attempt_visible_agent":
        tool_name = "dodge_forced_action_visible_agent"
    return handle_forced_social_action(session, world, actor, target, tool_name, params, location_id, state_delta)
