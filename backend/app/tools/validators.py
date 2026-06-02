from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, Event, IdentityKnowledge, Location, World
from app.content.toolsets import agent_special_tool_allowed, survival_needs_enabled
from app.social.forced_actions import FORCED_SOCIAL_ACTION_TOOL_TYPES, FORCED_SOCIAL_RESPONSE_TOOLS, pending_forced_action_by_id, pending_forced_action_from
from app.social.pending_requests import SOCIAL_REQUEST_RESPONSE_TOOLS, SOCIAL_REQUEST_TOOL_NAMES, pending_social_request_by_id, pending_social_request_from, social_response_request_type_for_tool
from app.tools.registry import PREGNANCY_RESTRICTED_TOOLS, REPRODUCTION_TOOL_NAMES, catalog_reproduction_related, catalog_survival_need_related, get_tool, is_pregnant, reproduction_toolset_enabled
from app.agents.v5_state import wallet_money
from app.world.corpses import CORPSE_TOOL_NAMES, validate_corpse_tool
from app.world.visibility import adjacent_location_ids, resolve_visible_ref
from app.simulation.difficulty import profile_for_agent
from app.economy.work_schedule import can_apply_for_job, can_do_odd_job, can_start_overtime, can_start_work_shift


@dataclass(slots=True)
class ToolValidation:
    ok: bool
    tool_name: str
    reason_code: str | None = None
    message: str | None = None
    target_agent: Agent | None = None
    destination: Location | None = None


NAME_REQUIRED_MESSAGE = "你还不知道这个人的名字，不能执行需要姓名的行为。你可以先观察外貌、询问姓名或请对方自我介绍。"
MAX_SLEEP_MINUTES_PER_DAY = 10 * 60

SPEECH_REQUIRED_TOOLS = {
    "say_to_visible_agent",
    "wake_visible_agent",
    "compliment_visible_agent",
    "apologize_to_visible_agent",
    "casual_chat_visible_agent",
    "ask_about_needs",
    "comfort_visible_agent",
    "invite_visible_agent_to_walk",
    "invite_visible_agent_to_hot_spring",
    "ask_for_help_from_visible_agent",
    "set_boundary_visible_agent",
    "thank_visible_agent",
    "discuss_feelings_visible_agent",
    "accept_social_request_visible_agent",
    "decline_social_request_visible_agent",
    "protest_forced_action_visible_agent",
}

STALE_SPEECHES = {
    "我想随便聊聊，你现在感觉怎么样？",
    "你好，我想和你说句话。",
}

SLEEPING_TARGET_COMMUNICATION_TOOLS = SPEECH_REQUIRED_TOOLS | SOCIAL_REQUEST_TOOL_NAMES | {
    "ask_visible_agent_to_introduce",
    "introduce_self",
    "refuse_introduction",
    "wave_to_visible_agent",
    "move_closer_to_visible_agent",
}

BABY_STAGE_TARGET_ALLOWED_TOOLS = {
    "observe_visible_agent",
    "say_to_visible_agent",
    "comfort_visible_agent",
    "help_visible_agent",
    "move_closer_to_visible_agent",
    "walk_away_from_visible_agent",
    "share_food_with_visible_agent",
    "share_water_with_visible_agent",
    "check_child_status_visible_agent",
    "soothe_child_visible_agent",
    "feed_child_visible_agent",
    "carry_child_visible_agent",
    "put_child_to_sleep_visible_agent",
    "care_for_child_visible_agent",
    "teach_child_simple_skill_visible_agent",
}

CHILD_TARGET_BLOCKED_TOOLS = {
    "express_affection_visible_agent",
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
    "discuss_romantic_boundaries_visible_agent",
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
    "force_hug_visible_agent",
    "force_hold_hands_visible_agent",
    "force_date_visible_agent",
    "force_relationship_claim_visible_agent",
    "force_walk_together_visible_agent",
}


def _location_matches(location: Location, raw: str) -> bool:
    return raw == location.location_id or raw == location.public_name or raw in location.location_id


def validate_tool(
    session: Session,
    *,
    actor: Agent,
    tool_name: str,
    params: dict[str, Any],
    world_time: int,
    reaction: bool = False,
    persist_visibility: bool = True,
) -> ToolValidation:
    spec = get_tool(tool_name)
    if not spec:
        return ToolValidation(False, tool_name, "unknown_tool", "这个工具不存在。")
    if actor.lifecycle_state not in spec.allowed_lifecycle_states:
        return ToolValidation(False, tool_name, "bad_lifecycle", "当前生命状态不能执行这个行为。")
    world = session.get(World, actor.world_id)
    reproduction_enabled = reproduction_toolset_enabled(world)
    if not agent_special_tool_allowed(actor.tool_learning_json, tool_name):
        return ToolValidation(False, tool_name, "agent_toolset_disabled", "这个特殊工具集没有分配给当前 agent。")
    if not survival_needs_enabled(world) and catalog_survival_need_related(spec):
        return ToolValidation(False, tool_name, "toolset_disabled", "通用生存需求工具集未启用，当前世界不会开放饥饿、口渴、吃喝或补给相关工具。")
    if not reproduction_enabled and (tool_name in REPRODUCTION_TOOL_NAMES or (spec.hard_effect_id.endswith("catalog_generic") and catalog_reproduction_related(spec))):
        return ToolValidation(False, tool_name, "toolset_disabled", "通用生育与育儿工具集未启用，当前世界不会开放生育、怀孕、成年亲密或育儿相关工具。")
    if is_pregnant(actor) and tool_name in PREGNANCY_RESTRICTED_TOOLS:
        return ToolValidation(False, tool_name, "pregnancy_restricted", "你正在怀孕，身体不适合加班硬撑、冲突犯罪或强行拖拽别人。更现实的选择是休息、吃喝、求助、轻量工作或和别人说明自己的状态。")
    if tool_name in {"sleep", "sleep_rough"} or (tool_name == "return_home" and params.get("sleep_after_arrival")):
        if _remaining_sleep_minutes_today(actor, world_time) <= 0:
            return ToolValidation(False, tool_name, "daily_sleep_limit", "今天已经睡足十小时，身体暂时睡不着了。可以起床处理别的事，等到新的一天再睡。")
    if tool_name in {"request_adult_intimacy_visible_agent", "accept_adult_intimacy_visible_agent", "decline_adult_intimacy_visible_agent", "buy_contraception", "buy_pregnancy_test", "take_pregnancy_test"} and actor.age_stage != "adult":
        return ToolValidation(False, tool_name, "age_blocked", "只有成年居民可以使用这个工具。")
    if tool_name == "attempt_forced_adult_boundary_visible_agent" and actor.age_stage != "adult":
        return ToolValidation(False, tool_name, "age_blocked", "只有成年居民可以使用这个工具。")
    location = actor.location.location if actor.location else None
    if not location:
        return ToolValidation(False, tool_name, "no_location", "你现在没有有效位置。")
    tags = set(location.tags_json or [])
    if spec.required_location_tags and not any(tag in tags for tag in spec.required_location_tags):
        return ToolValidation(False, tool_name, "bad_location", "当前位置不适合执行这个行为。")
    food_price = int(profile_for_agent(actor)["food_price"])
    if tool_name in {"eat_food", "pack_lunch", "buy_portable_food"} and wallet_money(actor) < food_price:
        return ToolValidation(False, tool_name, "not_enough_money", "饭需要花钱购买。你现在的钱不够，应该先工作、求助或想办法获得食物。")
    if tool_name == "apply_for_job":
        ok, reason = can_apply_for_job(world, actor, location, world_time)
        if not ok:
            return ToolValidation(False, tool_name, "work_schedule_blocked", reason)
    if tool_name == "do_odd_job":
        ok, reason = can_do_odd_job(world, actor, location, world_time)
        if not ok:
            return ToolValidation(False, tool_name, "work_schedule_blocked", reason)
    if tool_name in {"work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner", "work_shift_night_guard"}:
        ok, reason, _role, _window, _duration = can_start_work_shift(world, actor, location, tool_name, world_time)
        if not ok:
            return ToolValidation(False, tool_name, "work_schedule_blocked", reason)
    if tool_name == "work_overtime_shift":
        ok, reason = can_start_overtime(world, actor, location, world_time)
        if not ok:
            return ToolValidation(False, tool_name, "work_schedule_blocked", reason)
    if tool_name in CORPSE_TOOL_NAMES:
        ok, reason, message = validate_corpse_tool(session, world, actor, tool_name, params)
        if not ok:
            return ToolValidation(False, tool_name, reason, message)
    if spec.hard_effect_id == "worldpack_declarative":
        from app.effects.worldpack_effects import validate_worldpack_declarative_tool

        ok, reason, message = validate_worldpack_declarative_tool(actor, spec, params)
        if not ok:
            return ToolValidation(False, tool_name, reason, message)
    if tool_name == "work_overtime_shift":
        state = actor.dynamic_state
        if not state or state.energy < 38 or state.hydration < 38 or state.satiety < 38:
            return ToolValidation(False, tool_name, "too_weak_for_overtime", "你现在的体力、饱腹或水分不足，不适合硬撑加班。")
        if int((actor.work_json or {}).get("burnout", 0)) >= 85:
            return ToolValidation(False, tool_name, "burnout_too_high", "你的工作倦怠已经太高，继续加班会非常危险。")

    target_agent = None
    destination = None
    if spec.target_policy == "visible_ref":
        ref = params.get("visible_ref") or params.get("target_ref") or params.get("receiver_ref")
        if not ref:
            return ToolValidation(False, tool_name, "missing_visible_ref", _usage_message(tool_name, "这个行动缺少当前可见目标。请从本回合行动菜单里选择已经写明目标的人物行动；附近没人时选择公开发言、观察、移动或等待类行动。"))
        target_agent = resolve_visible_ref(session, actor, str(ref), world_time, persist=persist_visibility)
        if not target_agent:
            return ToolValidation(False, tool_name, "target_not_visible", _usage_message(tool_name, f"{ref} 不是当前可见人物。请从本回合行动菜单里选择已经写明目标的人物行动。"))
        try:
            target_sleep_until = int((target_agent.desires_json or {}).get("sleep_until_world_time") or 0)
        except (TypeError, ValueError):
            target_sleep_until = 0
        target_is_sleeping = target_sleep_until > world_time
        if tool_name == "wake_visible_agent":
            if not target_is_sleeping:
                return ToolValidation(False, tool_name, "target_not_sleeping", "对方现在没有在睡觉，不需要叫醒。")
        elif target_is_sleeping and tool_name in SLEEPING_TARGET_COMMUNICATION_TOOLS:
            return ToolValidation(False, tool_name, "target_sleeping", _usage_message(tool_name, "对方正在睡觉，直接提问或邀请通常不会被回应。如果确实要现在交流，请先使用 wake_visible_agent；否则可以等待对方醒来或先做自己的事。"))
        if target_agent.age_stage in {"newborn", "infant", "toddler"} and tool_name not in BABY_STAGE_TARGET_ALLOWED_TOOLS:
            return ToolValidation(False, tool_name, "target_is_baby", "目标还是婴幼儿，不能把成人社交、恋爱、犯罪、强制互动或复杂请求套到 TA 身上。请改用查看状态、安抚、喂食、抱起、哄睡、综合照护，或只对婴儿温柔说话。")
        if target_agent.age_stage == "child" and tool_name in CHILD_TARGET_BLOCKED_TOOLS:
            return ToolValidation(False, tool_name, "target_is_child", "目标还是孩子，不能使用恋爱、成年亲密或强制边界类工具。请改用儿童照护、普通说话、分享食物/水、教学或陪伴。")
        if tool_name in {"request_adult_intimacy_visible_agent", "accept_adult_intimacy_visible_agent", "decline_adult_intimacy_visible_agent"} and target_agent.age_stage != "adult":
            return ToolValidation(False, tool_name, "age_blocked", "目标不是成年居民，不能使用成年亲密工具。")
        if tool_name == "attempt_forced_adult_boundary_visible_agent" and target_agent.age_stage != "adult":
            return ToolValidation(False, tool_name, "age_blocked", "目标不是成年居民，不能使用严重成年边界侵犯工具。")
        if tool_name in {"accept_adult_intimacy_visible_agent", "decline_adult_intimacy_visible_agent"} and not _has_pending_intimacy_from(actor, target_agent):
            return ToolValidation(False, tool_name, "missing_consent_request", "没有来自这个人的待处理成年亲密请求，不能同意或拒绝。")
        if tool_name in SOCIAL_REQUEST_RESPONSE_TOOLS:
            expected_type = social_response_request_type_for_tool(tool_name)
            request_id = str(params.get("request_id") or "")
            if request_id:
                request = pending_social_request_by_id(actor, request_id, world_time)
                if not request or request.get("from_agent_id") != target_agent.agent_id or (expected_type and request.get("request_type") != expected_type):
                    return ToolValidation(False, tool_name, "missing_social_request", "这个具体请求已经不存在、过期，或不是来自你选择回应的人。")
            elif not pending_social_request_from(actor, target_agent.agent_id, world_time, request_type=expected_type):
                expected = f"（类型 {expected_type}）" if expected_type else ""
                return ToolValidation(False, tool_name, "missing_social_request", f"没有来自这个人的待处理社交/亲密请求{expected}，不能同意或拒绝。")
        if tool_name in FORCED_SOCIAL_RESPONSE_TOOLS:
            forced_action_id = str(params.get("forced_action_id") or "")
            if forced_action_id:
                request = pending_forced_action_by_id(actor, forced_action_id, world_time)
                if not request or request.get("from_agent_id") != target_agent.agent_id:
                    return ToolValidation(False, tool_name, "missing_forced_action", "这个具体突然动作已经不存在、过期，或不是来自你选择回应的人。")
            elif not pending_forced_action_from(actor, target_agent.agent_id, world_time):
                return ToolValidation(False, tool_name, "missing_forced_action", "没有来自这个人的待处理强制动作，不能躲开、默许或抗议。")
        if tool_name in SPEECH_REQUIRED_TOOLS and not str(params.get("speech") or "").strip():
            return ToolValidation(False, tool_name, "missing_speech", _usage_message(tool_name, "这个说话类行动需要第二行开始写中文正文；请写出当前真正想说的话。"))
        if tool_name in SPEECH_REQUIRED_TOOLS:
            speech = str(params.get("speech") or "").strip()
            if speech in STALE_SPEECHES or _recently_repeated_speech(session, actor, speech):
                return ToolValidation(False, tool_name, "stale_speech", _usage_message(tool_name, "这句话太模板化或刚刚重复说过。请根据眼前状态、地点、需求或记忆改写一句具体的新话。"))

    if spec.target_policy == "known_name":
        name = params.get("known_name") or params.get("target_name") or params.get("name")
        if not name:
            return ToolValidation(False, tool_name, "missing_known_name", _usage_message(tool_name, "这个行动缺少已知姓名目标。请从行动菜单里选择已经写明姓名的行动；不知道姓名时先询问、自我介绍或用外貌编号互动。"))
        knowledge = session.execute(
            select(IdentityKnowledge).where(
                IdentityKnowledge.observer_agent_id == actor.agent_id,
                IdentityKnowledge.known_name == str(name),
                IdentityKnowledge.name_known.is_(True),
            )
        ).scalar_one_or_none()
        if not knowledge:
            return ToolValidation(False, tool_name, "name_unknown", NAME_REQUIRED_MESSAGE)
        target_agent = session.get(Agent, knowledge.target_agent_id)

    if spec.target_policy == "location":
        raw = str(params.get("location_id") or params.get("location_name") or "")
        neighbors = adjacent_location_ids(session, location)
        if tool_name == "wander" and not raw:
            raw = neighbors[0] if neighbors else ""
        for neighbor_id in neighbors:
            neighbor = session.get(Location, neighbor_id)
            if neighbor and _location_matches(neighbor, raw):
                destination = neighbor
                break
        if not destination:
            return ToolValidation(False, tool_name, "location_not_adjacent", _usage_message(tool_name, "移动工具必须指定相邻地点的 location_id 或地点名，不能越过地图移动。"))
        destination_tags = set(destination.tags_json or [])
        private_room_tools = {"knock_private_room", "attempt_burglary_private_room", "home_invasion_robbery_private_room"}
        if tool_name in private_room_tools and "private" not in destination_tags:
            return ToolValidation(False, tool_name, "not_private_room", _usage_message(tool_name, "这个工具只能指定相邻的私人小屋 location_id。"))
        if tool_name in private_room_tools and destination.location_id == _own_home_location_id(actor):
            return ToolValidation(False, tool_name, "own_private_room", _usage_message(tool_name, "这是你自己的小屋，不需要敲门或犯罪；直接移动进去再睡觉、休息或整理即可。"))
        if (
            tool_name not in private_room_tools
            and "private" in destination_tags
            and destination.location_id != _own_home_location_id(actor)
            and not _has_private_room_permission(session, actor, destination)
        ):
            return ToolValidation(False, tool_name, "private_room_blocked", _usage_message(tool_name, "这是别人的私人小屋，不能直接移动进去。可以敲门请求进入；如果对方授权过你使用，也可以正常进入；也可以选择入室盗窃/抢劫并承担后果。"))

    return ToolValidation(True, tool_name, target_agent=target_agent, destination=destination)


def _own_home_location_id(actor: Agent) -> str | None:
    return ((actor.wallet_json or {}).get("housing") or {}).get("home_location_id")


def _has_private_room_permission(session: Session, actor: Agent, destination: Location) -> bool:
    owner = _private_home_owner(session, actor.world_id, destination.location_id)
    if not owner or owner.agent_id == actor.agent_id:
        return False
    for grant in (owner.wallet_json or {}).get("permissions_granted") or []:
        if grant.get("to_agent_id") != actor.agent_id or grant.get("active") is False:
            continue
        scope = str(grant.get("resource_scope") or "")
        resource_id = grant.get("resource_id")
        if scope == "all_personal_resources":
            return True
        if scope in {"home", "private_room"} and resource_id == destination.location_id:
            return True
    return False


def _private_home_owner(session: Session, world_id: str, location_id: str) -> Agent | None:
    for candidate in session.execute(select(Agent).where(Agent.world_id == world_id, Agent.lifecycle_state.in_(["alive", "critical"]))).scalars():
        if ((candidate.wallet_json or {}).get("housing") or {}).get("home_location_id") == location_id:
            return candidate
    return None


def _has_pending_intimacy_from(actor: Agent, requester: Agent) -> bool:
    for request in (actor.family_json or {}).get("pending_intimacy_requests", []):
        if request.get("from_agent_id") == requester.agent_id and request.get("status") == "pending":
            return True
    return False


def _recently_repeated_speech(session: Session, actor: Agent, speech: str) -> bool:
    if not speech:
        return False
    recent = session.execute(
        select(Event)
        .where(Event.world_id == actor.world_id, Event.actor_agent_id == actor.agent_id, Event.event_type == "dialogue")
        .order_by(Event.event_id.desc())
        .limit(6)
    ).scalars()
    return any((event.payload or {}).get("speech") == speech for event in recent)


def _usage_message(tool_name: str, detail: str) -> str:
    return f"工具调用格式错误: {detail} 当前尝试的工具是 {tool_name}。请重新选择一个参数完整且符合当前地点/目标的工具。"


def _remaining_sleep_minutes_today(actor: Agent, world_time: int) -> int:
    desires = actor.desires_json or {}
    day = world_time // 1440 + 1
    try:
        recorded_day = int(desires.get("sleep_quota_day") or -1)
    except (TypeError, ValueError):
        recorded_day = -1
    if recorded_day != day:
        return MAX_SLEEP_MINUTES_PER_DAY
    try:
        used = int(desires.get("sleep_minutes_today") or 0)
    except (TypeError, ValueError):
        used = 0
    return max(0, MAX_SLEEP_MINUTES_PER_DAY - used)
