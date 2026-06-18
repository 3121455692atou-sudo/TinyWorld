from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.agents.v5_state import wallet_money
from app.core.clock import format_world_time
from app.core.models import Agent, Location, World
from app.simulation.difficulty import profile_for_agent, tool_time_cost

MINUTE = int


@dataclass(frozen=True, slots=True)
class WorkWindow:
    start: MINUTE
    end: MINUTE
    label: str


@dataclass(frozen=True, slots=True)
class WorkRoleSpec:
    role_id: str
    job_name: str
    tool_name: str
    location_tags_any: tuple[str, ...]
    windows: tuple[WorkWindow, ...]
    min_continuous_minutes: int
    wage_multiplier: float = 1.0
    note: str = ""


WORK_ROLES: dict[str, WorkRoleSpec] = {
    "cafeteria_service": WorkRoleSpec(
        role_id="cafeteria_service",
        job_name="食堂服务员",
        tool_name="work_shift_cafeteria",
        location_tags_any=("food_service",),
        windows=(
            WorkWindow(6 * 60 + 30, 10 * 60 + 30, "早餐服务班"),
            WorkWindow(11 * 60, 15 * 60, "午餐服务班"),
            WorkWindow(16 * 60, 20 * 60, "晚餐服务班"),
        ),
        min_continuous_minutes=180,
        note="食堂服务必须卡饭点连续站班，错过窗口就没有客流。",
    ),
    "cook": WorkRoleSpec(
        role_id="cook",
        job_name="厨房帮工",
        tool_name="work_shift_cook",
        location_tags_any=("food_service",),
        windows=(
            WorkWindow(5 * 60, 9 * 60 + 30, "清晨备餐班"),
            WorkWindow(9 * 60 + 30, 14 * 60, "午间备餐班"),
            WorkWindow(14 * 60 + 30, 19 * 60, "晚间备餐班"),
        ),
        min_continuous_minutes=180,
        note="厨房工作要连续备料和收尾，不能只干十几分钟就算完成。",
    ),
    "cleaner": WorkRoleSpec(
        role_id="cleaner",
        job_name="清洁工",
        tool_name="work_shift_cleaner",
        location_tags_any=("food_service", "work", "trade", "social", "medical", "notice", "quiet", "nature", "water", "hot_spring", "home", "learning", "fun", "public_record", "private"),
        windows=(
            WorkWindow(5 * 60, 10 * 60, "清晨清洁班"),
            WorkWindow(20 * 60, 24 * 60 + 2 * 60, "夜间清洁班"),
        ),
        min_continuous_minutes=150,
        note="清洁工作通常在开门前或闭店后，白天客流正旺时不一定有班。",
    ),
    "night_guard": WorkRoleSpec(
        role_id="night_guard",
        job_name="夜间安保",
        tool_name="work_shift_night_guard",
        location_tags_any=("social", "open_view", "trade", "work", "jail", "night"),
        windows=(WorkWindow(21 * 60, 24 * 60 + 6 * 60, "夜间巡逻班"),),
        min_continuous_minutes=240,
        wage_multiplier=1.2,
        note="夜间安保只能夜里上班，通常要连续巡逻几个小时。",
    ),
}

JOB_NAME_TO_ROLE_ID = {spec.job_name: role_id for role_id, spec in WORK_ROLES.items()}
JOB_NAME_TO_ROLE_ID.update({"食堂服务": "cafeteria_service", "厨房工作": "cook", "清洁工作": "cleaner", "安保": "night_guard"})
WORK_TOOL_TO_ROLE_ID = {spec.tool_name: role_id for role_id, spec in WORK_ROLES.items()}
FORMAL_WORK_SHIFT_TOOLS = frozenset(WORK_TOOL_TO_ROLE_ID)
HIRING_LOCATION_TAGS = {"food_service", "work", "trade", "notice", "social", "medical", "quiet", "nature", "water", "hot_spring", "home", "learning", "fun", "public_record", "private"}
ODD_JOB_LOCATION_TAGS = {"food_service", "work", "trade", "social", "nature", "medical", "quiet", "water", "hot_spring", "home", "learning", "fun", "public_record", "private"}
HIRING_WINDOWS = (WorkWindow(8 * 60, 12 * 60, "上午招工"), WorkWindow(13 * 60, 18 * 60, "下午招工"))
ODD_JOB_WINDOWS = (WorkWindow(7 * 60, 12 * 60, "上午零工"), WorkWindow(13 * 60, 19 * 60, "下午零工"))
WORK_MOVEMENT_BLOCKED_TOOLS = frozenset(
    {
        "move_to_location",
        "wander",
        "return_home",
        "walk_away_from_visible_agent",
        "knock_private_room",
        "attempt_burglary_private_room",
        "home_invasion_robbery_private_room",
        "go_eat_food",
        "go_drink_water",
        "invite_visible_agent_to_walk",
        "invite_visible_agent_to_hot_spring",
    }
)


def positive_world_time(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def active_work_status(agent: Agent, world_time: int | None) -> dict[str, Any] | None:
    work = agent.work_json or {}
    if not isinstance(work, dict):
        return None
    status = work.get("working_status")
    if not isinstance(status, dict) or not status.get("active"):
        return None
    until = positive_world_time(status.get("until_world_time"))
    if not until:
        return None
    if world_time is not None and until <= int(world_time):
        return None
    return status


def due_work_status(agent: Agent, world_time: int) -> dict[str, Any] | None:
    work = agent.work_json or {}
    if not isinstance(work, dict):
        return None
    status = work.get("working_status")
    if not isinstance(status, dict) or not status.get("active"):
        return None
    until = positive_world_time(status.get("until_world_time"))
    if until and until <= int(world_time):
        return status
    return None


def work_status_until(agent: Agent) -> int | None:
    work = agent.work_json or {}
    if not isinstance(work, dict):
        return None
    status = work.get("working_status")
    if not isinstance(status, dict) or not status.get("active"):
        return None
    return positive_world_time(status.get("until_world_time"))


def work_blocks_tool(tool_name: str) -> bool:
    return tool_name in WORK_MOVEMENT_BLOCKED_TOOLS


def work_block_message(agent: Agent, world_time: int) -> str:
    status = active_work_status(agent, world_time) or {}
    job_name = str(status.get("job_name") or (agent.work_json or {}).get("job") or "工作")
    until = positive_world_time(status.get("until_world_time"))
    suffix = f"，预计 {format_world_time(until)} 下班" if until else ""
    return f"你正在{job_name}工作中{suffix}，下班前不能离岗移动。可以留在岗位上回应别人、检查状态或做工作间歇。"


def role_for_agent(agent: Agent) -> WorkRoleSpec | None:
    work = agent.work_json or {}
    role_id = str(work.get("job_role") or "")
    if role_id in WORK_ROLES:
        return WORK_ROLES[role_id]
    job = str(work.get("job") or "")
    role_id = JOB_NAME_TO_ROLE_ID.get(job)
    return WORK_ROLES.get(role_id) if role_id else None


def role_for_tool(tool_name: str) -> WorkRoleSpec | None:
    role_id = WORK_TOOL_TO_ROLE_ID.get(tool_name)
    return WORK_ROLES.get(role_id) if role_id else None


def effective_work_duration_minutes(world: World, agent: Agent, tool_name: str, fallback_minutes: int) -> int:
    base = tool_time_cost(world, tool_name, fallback_minutes)
    role = role_for_tool(tool_name)
    if role:
        return max(base, role.min_continuous_minutes)
    return base


def window_contains(window: WorkWindow, minute: int, duration: int = 0) -> bool:
    start = int(window.start)
    end = int(window.end)
    current = int(minute)
    if end <= start:
        end += 1440
    if current < start and end > 1440:
        current += 1440
    return start <= current and current + max(0, int(duration)) <= end


def active_window(windows: tuple[WorkWindow, ...], world_time: int, duration: int = 0) -> WorkWindow | None:
    minute = int(world_time) % 1440
    for window in windows:
        if window_contains(window, minute, duration):
            return window
    return None


def next_window_label(windows: tuple[WorkWindow, ...], world_time: int) -> str:
    minute = int(world_time) % 1440
    candidates: list[tuple[int, WorkWindow]] = []
    for window in windows:
        start = window.start
        delta = (start - minute) % 1440
        candidates.append((delta, window))
    _delta, window = min(candidates, key=lambda item: item[0])
    return f"{window.label} {format_minutes_of_day(window.start)}-{format_minutes_of_day(window.end)}"


def format_minutes_of_day(value: int) -> str:
    value = int(value) % 1440
    return f"{value // 60:02d}:{value % 60:02d}"


def _tags(location: Location | None) -> set[str]:
    return set(location.tags_json or []) if location else set()


def location_matches_role(location: Location | None, role: WorkRoleSpec) -> bool:
    tags = _tags(location)
    return bool(tags.intersection(role.location_tags_any))


def can_apply_for_job(world: World, agent: Agent, location: Location | None, world_time: int) -> tuple[bool, str]:
    if active_work_status(agent, world_time):
        return False, work_block_message(agent, world_time)
    if bool((agent.work_json or {}).get("employed")):
        return False, "你已经有正式工作了，不能一边说找工作一边无限叠工作。"
    tags = _tags(location)
    if not tags.intersection(HIRING_LOCATION_TAGS):
        return False, "这里暂时没有正式岗位；通常可以去人多地点、食堂、集市、工作坊、医务室、温泉、公共设施或住所维护点询问工作。"
    if not active_window(HIRING_WINDOWS, world_time, 15):
        return False, f"现在不是招工时间。下一段招工大约是 {next_window_label(HIRING_WINDOWS, world_time)}。"
    if agent.dynamic_state and agent.dynamic_state.hygiene < 35:
        return False, "你现在看起来太脏太疲惫，服务岗位会让你先洗洗澡、换身干净衣服再来。"
    return True, ""


def job_offer_for_application(world: World, agent: Agent, location: Location | None, world_time: int) -> WorkRoleSpec | None:
    ok, _reason = can_apply_for_job(world, agent, location, world_time)
    if not ok:
        return None
    learning = agent.work_json or {}
    last_failed = learning.get("last_job_application_failed_world_time")
    try:
        if last_failed is not None and int(world_time) - int(last_failed) < 180:
            return None
    except (TypeError, ValueError):
        pass
    tags = _tags(location)
    chance = 48
    if "food_service" in tags or "work" in tags:
        chance += 18
    if "trade" in tags or "notice" in tags:
        chance += 10
    if wallet_money(agent) < 12:
        chance += 8
    if agent.traits:
        chance += max(-8, min(10, (int(agent.traits.discipline) - 50) // 5))
        chance += max(-6, min(8, (int(agent.traits.sociability) - 50) // 7))
    if agent.dynamic_state and agent.dynamic_state.stress > 82:
        chance -= 8
    chance = max(15, min(88, chance))
    bucket = int(world_time) // 240
    if stable_percent(world.seed, agent.agent_id, location.location_id if location else "none", bucket, "job_offer") >= chance:
        return None
    candidates = available_job_roles_for_location(location)
    if not candidates:
        candidates = list(WORK_ROLES.values())
    idx = stable_percent(world.seed, agent.agent_id, location.location_id if location else "none", bucket, "job_role") % len(candidates)
    return candidates[idx]


def available_job_roles_for_location(location: Location | None) -> list[WorkRoleSpec]:
    tags = _tags(location)
    roles = []
    if "food_service" in tags:
        roles.extend([WORK_ROLES["cafeteria_service"], WORK_ROLES["cook"], WORK_ROLES["cleaner"]])
    if "work" in tags:
        roles.extend([WORK_ROLES["cleaner"], WORK_ROLES["night_guard"]])
    if "trade" in tags or "notice" in tags or "social" in tags:
        roles.extend([WORK_ROLES["cafeteria_service"], WORK_ROLES["cleaner"], WORK_ROLES["night_guard"]])
    if tags.intersection(WORK_ROLES["cleaner"].location_tags_any):
        roles.append(WORK_ROLES["cleaner"])
    if tags.intersection({"social", "open_view", "trade", "work", "jail", "night", "hot_spring"}):
        roles.append(WORK_ROLES["night_guard"])
    unique: dict[str, WorkRoleSpec] = {}
    for role in roles:
        unique[role.role_id] = role
    return list(unique.values())


def can_do_odd_job(world: World, agent: Agent, location: Location | None, world_time: int) -> tuple[bool, str]:
    if active_work_status(agent, world_time):
        return False, work_block_message(agent, world_time)
    tags = _tags(location)
    if not tags.intersection(ODD_JOB_LOCATION_TAGS):
        return False, "这里没有临时零工。去集市、食堂、工作坊、医务室、花园、温泉、住所维护点或公共地点问问更合理。"
    duration = tool_time_cost(world, "do_odd_job", int(profile_for_agent(agent)["odd_time_min"]))
    if not active_window(ODD_JOB_WINDOWS, world_time, min(duration, 90)):
        return False, f"现在没有临时零工可接。下一段零工时间大约是 {next_window_label(ODD_JOB_WINDOWS, world_time)}。"
    bucket = int(world_time) // 180
    chance = 55
    if wallet_money(agent) < 10:
        chance += 12
    if "trade" in tags or "work" in tags:
        chance += 12
    if agent.dynamic_state and (agent.dynamic_state.energy < 35 or agent.dynamic_state.hydration < 35 or agent.dynamic_state.satiety < 35):
        chance -= 20
    chance = max(10, min(85, chance))
    roll = stable_percent(world.seed, agent.agent_id, location.location_id if location else "none", bucket, "odd_job")
    if roll >= chance:
        return False, "这一时段刚好没人招临时工；可以等下一段时间、换地点或找正式工作。"
    return True, ""


def can_start_work_shift(world: World, agent: Agent, location: Location | None, tool_name: str, world_time: int) -> tuple[bool, str, WorkRoleSpec | None, WorkWindow | None, int]:
    role = role_for_tool(tool_name)
    if not role:
        return False, "这个工具不是正式工作班次。", None, None, 0
    if active_work_status(agent, world_time):
        return False, work_block_message(agent, world_time), role, None, 0
    current_role = role_for_agent(agent)
    if not bool((agent.work_json or {}).get("employed")) or not current_role:
        return False, "你还没有正式工作，不能想上班就凭空出现一份班。先在招工时间找工作。", role, None, 0
    if current_role.role_id != role.role_id:
        return False, f"你的工作是{current_role.job_name}，不能直接去做{role.job_name}的班。", role, None, 0
    if not location_matches_role(location, role):
        return False, f"{role.job_name}不能在这里开工。需要去合适地点：{''.join(role.location_tags_any)}。", role, None, 0
    duration = effective_work_duration_minutes(world, agent, tool_name, fallback_minutes=60)
    window = active_window(role.windows, world_time, duration)
    if not window:
        return False, f"现在不是{role.job_name}的可上班时段，或剩余时间不够连续工作 {duration} 分钟。下一段班是 {next_window_label(role.windows, world_time)}。", role, None, duration
    if agent.dynamic_state and (agent.dynamic_state.energy < 25 or agent.dynamic_state.hydration < 25 or agent.dynamic_state.satiety < 25):
        return False, "你的体力、饱腹或水分太低，撑不完整段连续工作。先吃喝或休息。", role, window, duration
    return True, "", role, window, duration


def can_start_overtime(world: World, agent: Agent, location: Location | None, world_time: int) -> tuple[bool, str]:
    if active_work_status(agent, world_time):
        return False, work_block_message(agent, world_time)
    if not bool((agent.work_json or {}).get("employed")):
        return False, "你还没有正式工作，不能凭空加班。先找正式工作。"
    role = role_for_agent(agent)
    if role and not location_matches_role(location, role):
        tags = _tags(location)
        if not tags.intersection({"work", "food_service", "trade", "social"}):
            return False, "这里不适合加班。先去和自己工作有关的地点。"
    minute = int(world_time) % 1440
    evening_or_night = minute >= 18 * 60 or minute < 5 * 60
    housing = (agent.wallet_json or {}).get("housing") or {}
    current_day = int(world_time) // 1440 + 1
    rent_pressure = bool(housing.get("rent_per_10_days")) and wallet_money(agent) < int(housing.get("rent_per_10_days") or 0) and int(housing.get("next_rent_due_day") or 99) - current_day <= 2
    money_pressure = wallet_money(agent) < 18 or rent_pressure
    if not (evening_or_night or money_pressure):
        return False, "现在没有明显的晚间加班或经济压力；如果只是正常赚钱，可以选择自己排班内的普通工作。"
    return True, ""


def work_prompt_lines(world: World, agent: Agent, location: Location | None) -> list[str]:
    lines: list[str] = []
    work = agent.work_json or {}
    current_role = role_for_agent(agent)
    if current_role:
        duration = effective_work_duration_minutes(world, agent, current_role.tool_name, fallback_minutes=60)
        window = active_window(current_role.windows, world.current_world_time_minutes, duration)
        if window and location_matches_role(location, current_role):
            lines.append(f"你的工作是{current_role.job_name}，当前可以上{window.label}，需要连续工作约 {duration} 分钟。")
        else:
            loc_note = "当前位置不适合这份工作" if not location_matches_role(location, current_role) else "当前不在班次窗口或剩余窗口不够"
            lines.append(f"你的工作是{current_role.job_name}；{loc_note}。下一段班: {next_window_label(current_role.windows, world.current_world_time_minutes)}。")
    else:
        ok, reason = can_apply_for_job(world, agent, location, world.current_world_time_minutes)
        if ok:
            lines.append("你现在可以尝试找正式工作，但录用不是必然；职位取决于地点、时间、卫生、性格和当前空缺。")
        else:
            lines.append(f"你目前没有正式工作；找工作也受地点和招工时间限制：{reason}")
    odd_ok, odd_reason = can_do_odd_job(world, agent, location, world.current_world_time_minutes)
    if odd_ok:
        lines.append("当前地点/时段有临时零工可试，但零工不稳定，之后换时段可能就没有。")
    else:
        lines.append(f"零工状态: {odd_reason}")
    return lines[:4]


def stable_percent(*parts: Any) -> int:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100
