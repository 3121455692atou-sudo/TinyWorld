from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.traits import clamp
from app.agents.v5_state import wallet_money
from app.content.toolsets import modern_life_enabled, survival_needs_enabled
from app.core.models import Agent, World


@dataclass(slots=True)
class DriveSnapshot:
    pain_score: int
    survival_pressure: int
    pleasure_pressure: int
    dominant_need: str
    components: dict[str, int]
    lines: list[str]
    reward_hints: list[str]
    priority_tools: list[str]

    def as_json(self) -> dict[str, Any]:
        return {
            "pain_score": self.pain_score,
            "survival_pressure": self.survival_pressure,
            "pleasure_pressure": self.pleasure_pressure,
            "dominant_need": self.dominant_need,
            "components": self.components,
            "lines": self.lines,
            "reward_hints": self.reward_hints,
            "priority_tools": self.priority_tools,
        }


def compute_drive(world: World, agent: Agent) -> DriveSnapshot:
    """把身体和欲望翻译成 LLM 能感到的内在奖惩信号。

    注意：这里不替 agent 决定行动，只把“做某事会缓解什么痛苦 / 带来什么奖励”显式化。
    数值仍由硬规则决定，LLM 只能看到这些主观感受和行动倾向。
    """

    state = agent.dynamic_state
    if not state:
        return DriveSnapshot(0, 0, 0, "none", {}, ["你暂时感受不到明确身体信号。"], [], [])

    desires = agent.desires_json or {}
    housing = (agent.wallet_json or {}).get("housing") or {}
    hedonic = (agent.wallet_json or {}).get("hedonic_state") or {}
    morality = agent.morality_json or {}
    survival_enabled = survival_needs_enabled(world)
    modern_life = modern_life_enabled(world)

    awake_hours = _awake_hours(world, agent)
    current_day = world.current_world_time_minutes // 1440 + 1
    due_day = _safe_int(housing.get("next_rent_due_day"), 999)
    rent = _safe_int(housing.get("rent_per_10_days"), 0)
    money = wallet_money(agent)

    components = {
        "thirst": int(clamp((65 - state.hydration) * 1.7, 0, 100)) if survival_enabled else 0,
        "hunger": int(clamp((62 - state.satiety) * 1.45, 0, 100)) if survival_enabled else 0,
        "fatigue": int(clamp((45 - state.energy) * 1.3 + max(0, awake_hours - 14) * 7, 0, 100)),
        "unclean": int(clamp((45 - state.hygiene) * 1.15, 0, 100)),
        "injury": int(clamp((70 - state.health) * 1.4, 0, 100)),
        "stress": int(clamp(state.stress * 0.85, 0, 100)),
        "loneliness": int(clamp((45 - state.social) * 1.1 + _safe_int(desires.get("loneliness"), 0) * 0.5, 0, 100)),
        "boredom": int(clamp((48 - state.fun) * 1.05 + _safe_int(desires.get("boredom"), 0) * 0.5, 0, 100)),
        "poverty": 0,
        "housing": 0,
        "luxury_deprivation": int(clamp(_safe_int(hedonic.get("deprivation_pain"), 0), 0, 100)),
        "guilt_or_moral": int(clamp(_safe_int(morality.get("guilt"), 0), 0, 100)),
    }
    if modern_life:
        if money < 6:
            components["poverty"] = 70
        elif money < 18:
            components["poverty"] = 42
        elif money < 40:
            components["poverty"] = 18
        if rent and money < rent and due_day - current_day <= 2:
            components["housing"] = int(clamp(35 + (2 - (due_day - current_day)) * 20, 0, 100))
        if housing.get("homeless"):
            components["housing"] = max(components["housing"], 75)
    else:
        components["luxury_deprivation"] = 0

    survival_keys = ["thirst", "hunger", "fatigue", "unclean", "injury", "poverty", "housing"]
    survival_pressure = max(components[k] for k in survival_keys)
    pain_score = int(
        clamp(
            max(components.values()) * 0.55
            + sum(sorted(components.values(), reverse=True)[:4]) * 0.16,
            0,
            100,
        )
    )
    pleasure_pressure = max(components["loneliness"], components["boredom"], components["luxury_deprivation"])
    dominant_need = max(components, key=lambda key: components[key])

    lines = _body_lines(world, agent, components, awake_hours)
    reward_hints = _reward_hints(world, agent, components, awake_hours)
    priority_tools = _priority_tools(agent, components, world)

    return DriveSnapshot(
        pain_score=pain_score,
        survival_pressure=int(clamp(survival_pressure, 0, 100)),
        pleasure_pressure=int(clamp(pleasure_pressure, 0, 100)),
        dominant_need=dominant_need,
        components={k: int(v) for k, v in components.items()},
        lines=lines,
        reward_hints=reward_hints,
        priority_tools=priority_tools,
    )


def write_drive_state(world: World, agent: Agent) -> dict[str, Any]:
    snapshot = compute_drive(world, agent)
    desires = dict(agent.desires_json or {})
    desires["embodied_drive"] = snapshot.as_json()
    desires["survival_pressure"] = max(_safe_int(desires.get("survival_pressure"), 0), snapshot.survival_pressure)
    desires["loneliness"] = max(_safe_int(desires.get("loneliness"), 0), snapshot.components.get("loneliness", 0))
    desires["boredom"] = max(_safe_int(desires.get("boredom"), 0), snapshot.components.get("boredom", 0))
    if snapshot.pain_score >= 70:
        desires["pain_tone_lock"] = {
            "world_time": world.current_world_time_minutes,
            "reason": snapshot.dominant_need,
            "pain_score": snapshot.pain_score,
            "instruction": "严重痛苦时，外放台词可以坚强、麻木、烦躁、求助、强颜欢笑，但不能像完全没事一样轻松愉快。",
        }
    else:
        desires.pop("pain_tone_lock", None)
    agent.desires_json = desires
    return snapshot.as_json()


def drive_prompt_lines(agent: Agent) -> list[str]:
    drive = (agent.desires_json or {}).get("embodied_drive") or {}
    lines = list(drive.get("lines") or [])
    hints = list(drive.get("reward_hints") or [])
    if not lines:
        return ["当前身体和欲望没有发出特别强的信号。"]
    result = [*lines[:8]]
    if hints:
        result.append("可预期奖惩：" + "；".join(hints[:8]))
    pain_score = _safe_int(drive.get("pain_score"), 0)
    if pain_score >= 75:
        result.append("你现在不是轻松状态。可以逞强或苦笑，但台词和计划必须承认身体痛苦、虚弱、恐惧或麻木。")
    return result[:10]


def priority_tools_from_drive(agent: Agent) -> set[str]:
    drive = (agent.desires_json or {}).get("embodied_drive") or {}
    return set(drive.get("priority_tools") or [])


def drive_action_snapshot(world: World, agent: Agent) -> dict[str, Any]:
    return compute_drive(world, agent).as_json()


def record_action_reward(session: Session, world: World, agent: Agent, tool_name: str, before: dict[str, Any] | None) -> None:
    if not agent.dynamic_state or agent.lifecycle_state == "dead":
        return
    before = before or {}
    after = compute_drive(world, agent).as_json()
    before_pain = _safe_int(before.get("pain_score"), 0)
    after_pain = _safe_int(after.get("pain_score"), 0)
    pain_delta = before_pain - after_pain
    before_pleasure = _safe_int(before.get("pleasure_pressure"), 0)
    after_pleasure = _safe_int(after.get("pleasure_pressure"), 0)
    pleasure_delta = before_pleasure - after_pleasure
    before_survival = _safe_int(before.get("survival_pressure"), 0)
    after_survival = _safe_int(after.get("survival_pressure"), 0)
    survival_delta = before_survival - after_survival
    valence = int(clamp(pain_delta * 0.7 + pleasure_delta * 0.25 + survival_delta * 0.45, -100, 100))
    if valence >= 18:
        note = "这个行动明显缓解了痛苦或压力，身体会把它记成正反馈。"
    elif valence <= -18:
        note = "这个行动让身体账单更重，之后会更难忽视相关痛苦。"
    elif tool_name in {"do_nothing", "look_around", "check_self_status"} and after_pain >= 55:
        note = "这个行动没有真正处理痛苦，身体不会把它当作有效解决。"
        valence = min(valence, -8)
    else:
        note = "这个行动的奖惩变化不大，更多取决于你的长期目标和性格。"
    record = {
        "world_time": world.current_world_time_minutes,
        "tool_name": tool_name,
        "before_pain": before_pain,
        "after_pain": after_pain,
        "pain_delta": pain_delta,
        "survival_delta": survival_delta,
        "pleasure_delta": pleasure_delta,
        "valence": valence,
        "note": note,
        "dominant_need_after": after.get("dominant_need"),
    }
    desires = dict(agent.desires_json or {})
    recent = list(desires.get("recent_action_rewards") or [])
    recent.append(record)
    desires["last_action_reward"] = record
    desires["recent_action_rewards"] = recent[-8:]
    desires["embodied_drive"] = after
    desires["survival_pressure"] = after.get("survival_pressure", desires.get("survival_pressure", 0))
    agent.desires_json = desires


def action_conflicts_with_pain(agent: Agent, text: str) -> bool:
    if not text:
        return False
    drive = (agent.desires_json or {}).get("embodied_drive") or {}
    pain_score = _safe_int(drive.get("pain_score"), 0)
    if pain_score < 70:
        return False
    lowered = text.lower()
    cheerful_tokens = [
        "笑眯眯",
        "开心地",
        "轻松地",
        "愉快地",
        "悠闲地",
        "惬意",
        "若无其事",
        "没什么大不了",
        "cheerfully",
        "happily",
        "carefree",
    ]
    allowed_tokens = ["苦笑", "惨笑", "强颜欢笑", "硬挤出", "虚弱地笑", "勉强笑"]
    if any(token in lowered for token in allowed_tokens):
        return False
    return any(token in lowered for token in cheerful_tokens)


def pain_repair_reason(agent: Agent) -> str:
    drive = (agent.desires_json or {}).get("embodied_drive") or {}
    dominant = drive.get("dominant_need") or "pain"
    pain_score = _safe_int(drive.get("pain_score"), 0)
    lines = "；".join((drive.get("lines") or [])[:3])
    return (
        f"你的生理痛苦分数是 {pain_score}/100，主导痛苦是 {dominant}。{lines} "
        "你仍然可以选择任何行动，包括逞强、拒绝求助、继续冒险或说话，但台词不能像完全没事一样笑眯眯/悠闲/轻松。"
        "请改成承认痛苦、虚弱、恐惧、麻木、烦躁、求助，或明确写成强颜欢笑。"
    )


def _body_lines(world: World, agent: Agent, components: dict[str, int], awake_hours: float) -> list[str]:
    state = agent.dynamic_state
    assert state is not None
    lines: list[str] = []
    if state.health <= 15:
        lines.append("生命值已经极低：身体像被抽空一样，视野发暗，任何继续硬撑都像是在赌命。")
    elif state.health <= 35:
        lines.append("生命值偏低：身体持续不舒服，动作变慢，必须把恢复和避险当成真实需求。")
    if components["thirst"] >= 70:
        lines.append("脱水痛苦很强：喉咙发干、嘴唇疼，喝水会立刻带来强烈缓解。")
    elif components["thirst"] >= 35:
        lines.append("水分正在下降：现在喝水会让身体舒服很多，拖延会变成危机。")
    if components["hunger"] >= 70:
        lines.append("饥饿痛苦很强：胃部空得发痛，吃东西会立刻降低痛苦。")
    elif components["hunger"] >= 35:
        lines.append("饱腹感不足：吃饭或准备随身食物会让接下来的行动更稳。")
    if components["fatigue"] >= 75:
        lines.append(f"睡眠压力极强：你已连续清醒约 {awake_hours:.1f} 小时，身体在逼近昏倒或崩溃。")
    elif components["fatigue"] >= 40:
        lines.append(f"疲惫感明显：你已连续清醒约 {awake_hours:.1f} 小时，真正睡觉会带来高额恢复。")
    if components["unclean"] >= 70:
        lines.append("清洁痛苦很强：皮肤黏腻、气味刺鼻、羞耻和疾病风险都在上升，清洁会明显解除这种不适。")
    elif components["unclean"] >= 35:
        lines.append("清洁感变差：洗澡、清理衣物或回到有水地点会给身体明显正反馈。")
    if components["stress"] >= 70:
        lines.append("压力很高：你更容易冲动、逃避或崩溃，休息、倾诉、整理记忆会降低痛苦。")
    modern_life = modern_life_enabled(world)
    if modern_life and components["poverty"] >= 50:
        lines.append("金钱压力刺痛你：钱不够会直接威胁食物、房租和安全，但赚钱、借钱和犯罪都有不同代价。")
    if modern_life and components["housing"] >= 60:
        lines.append("住房压力很强：拖欠房租或无家可归会让安全感下降，也更容易被卷入危险。")
    if components["loneliness"] >= 55:
        lines.append("孤独感在发酵：靠近别人、求助、聊天或建立关系会有社交奖励；你也可以因警惕选择独处。")
    if components["boredom"] >= 55:
        lines.append("无聊感在推你寻找新鲜感：探索、游戏、阅读、创作或社交会比反复观察更有奖励。")
    if modern_life and components["luxury_deprivation"] >= 50:
        lines.append("享乐阈值在拉扯你：你已经习惯更好的消费，降级生活会带来失落；节制、借贷或继续奢侈都由你承担后果。")
    if not lines:
        lines.append("身体没有压倒性痛苦，但仍会偏好吃喝规律、睡眠、清洁、社交和一点乐趣。")
    return lines[:9]


def _reward_hints(world: World, agent: Agent, components: dict[str, int], awake_hours: float) -> list[str]:
    state = agent.dynamic_state
    assert state is not None
    hints: list[str] = []
    if components["thirst"] >= 35:
        hints.append("喝水/随身水=快速止渴正反馈")
    if components["hunger"] >= 35:
        hints.append("吃饭/随身食物=缓解胃部痛苦")
    if components["fatigue"] >= 40:
        hints.append("sleep/return_home/sleep_rough=高额恢复；rest 不能代替整晚睡眠")
    if components["unclean"] >= 35:
        hints.append("wash/clean_clothes/回有水地点=解除黏腻、异味和疾病焦虑")
    modern_life = modern_life_enabled(world)
    if modern_life and components["poverty"] >= 35:
        hints.append("工作=钱增加但疲劳；求助=人情；犯罪=高风险高后果")
    if components["stress"] >= 55:
        hints.append("冥想/倾诉/整理记忆=降低压力；冲动行为可能短爽长痛")
    if components["loneliness"] >= 45:
        hints.append("真诚交流/互助=社交奖励；被无视会加重孤独")
    if components["boredom"] >= 45:
        hints.append("探索/娱乐/创作=新鲜感奖励；重复自检/观察奖励很低")
    if state.health < 35:
        hints.append("低生命值时继续硬撑会被身体记成强负反馈")
    return hints[:8]


def _priority_tools(agent: Agent, components: dict[str, int], world: World) -> list[str]:
    tools: list[str] = []
    modern_life = modern_life_enabled(world)
    if components["thirst"] >= 35:
        tools.extend(["drink_water", "drink_bottled_water", "fill_canteen", "buy_bottled_water", "request_water_help", "accept_community_aid"])
    if components["hunger"] >= 35:
        tools.extend(["eat_food", "eat_portable_food", "pack_lunch", "buy_portable_food", "request_food_help"])
    if components["fatigue"] >= 35:
        tools.extend(["return_home", "sleep", "sleep_rough", "rest", "take_work_break"])
    if components["unclean"] >= 30:
        tools.extend(["wash", "clean_clothes", "tidy_room", "return_home", "move_to_location"])
    if modern_life and (components["poverty"] >= 35 or components["housing"] >= 35):
        tools.extend(["apply_for_job", "do_odd_job", "work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner", "request_food_help", "request_water_help"])
    if components["stress"] >= 55:
        tools.extend(["meditate", "breathe_fresh_air", "review_recent_memory", "write_private_note", "panic_pause", "ask_for_help_from_visible_agent"])
    if components["loneliness"] >= 45:
        tools.extend(["seek_conversation", "speak_to_nearby", "casual_chat_visible_agent", "ask_about_needs", "ask_for_help_from_visible_agent"])
    if components["boredom"] >= 45:
        tools.extend(["read_quietly", "practice_skill", "enjoy_scenery", "sketch_or_doodle", "take_short_walk", "play_simple_game", "move_to_location"])
    minute = world.current_world_time_minutes % 1440
    if minute >= 21 * 60 or minute < 7 * 60:
        tools.extend(["return_home", "sleep", "sleep_rough"])
    return list(dict.fromkeys(tools))[:30]


def _awake_hours(world: World, agent: Agent) -> float:
    desires = agent.desires_json or {}
    raw_awake = desires.get("awake_since_world_time")
    if raw_awake is None:
        raw_awake = agent.created_at_world_time if agent.created_at_world_time is not None else world.current_world_time_minutes
    try:
        awake_since = int(raw_awake)
    except (TypeError, ValueError):
        awake_since = world.current_world_time_minutes
    return max(0.0, (world.current_world_time_minutes - awake_since) / 60.0)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
