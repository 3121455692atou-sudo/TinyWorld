from __future__ import annotations

import random
from typing import Any

from app.llm.schemas import TRAIT_NAMES


def clamp(value: float, lower: float = 0, upper: float = 100) -> float:
    return max(lower, min(upper, value))


def clamp_int(value: int, lower: int = 0, upper: int = 100) -> int:
    return int(max(lower, min(upper, value)))


TRAIT_METADATA: dict[str, dict[str, str]] = {
    "openness": {"label": "开放", "short": "尝试新事物、接受陌生人、愿意改变原计划。", "high": "高开放会更常探索新地点、接受新关系、尝试创作/投资/世界观特殊行动。", "low": "低开放更守旧、依赖熟悉地点和熟人，遇到陌生选择更容易退回安全行为。", "increase": "探索、旅行、接受邀请、学习新技能、尝试没做过的世界观行动。", "decrease": "长期只待在家、反复拒绝新活动、创伤后持续回避陌生环境。"},
    "caution": {"label": "警惕", "short": "风险感知、边界感、预防损失和避免被伤害。", "high": "高警惕更会检查状态、设边界、避开尸体/犯罪/高杠杆，也更难接受突然亲密。", "low": "低警惕更冲动、容易相信别人、敢冒险，也更容易陷入债务、犯罪或被利用。", "increase": "做预算、研究股票、设边界、报警、避开危险、从被偷/受伤中学习。", "decrease": "频繁冒险、越界行动、无视债务/健康警告、冲动投资或犯罪。"},
    "sociability": {"label": "社交", "short": "主动聊天、公开表达、加入活动和维持关系的倾向。", "high": "高社交更常说话、邀约、参加会议、安慰或求助；孤独时更快找人。", "low": "低社交更偏独处、写日记、沉默或离开；被打扰时更容易冷处理。", "increase": "聊天、公开发言、参加会议、约会、互助、给孩子/朋友陪伴。", "decrease": "长期孤立、频繁忽视别人、反复离开对话、社交创伤。"},
    "empathy": {"label": "共情", "short": "理解他人痛苦、照护、分享资源和不愿伤害别人。", "high": "高共情更会帮助、安慰、照顾孩子、哀悼尸体、原谅或修复关系。", "low": "低共情更容易忽视他人痛苦、利用别人、伤害别人后缺少内疚。", "increase": "帮助、分享食物/水、照护孩子、安慰、埋葬尸体、认真道歉。", "decrease": "偷窃、攻击、强制行为、见死不救、反复利用别人。"},
    "curiosity": {"label": "好奇", "short": "观察、调查、学习、研究和推动未知剧情。", "high": "高好奇更会观察他人、阅读、研究市场、探索世界观机制和异常事件。", "low": "低好奇更少主动调查，除非生存或关系强迫它去做。", "increase": "观察、阅读、研究股票/公司、探索地图、练习新工具、调查尸体或事件。", "decrease": "长期重复低信息行为、只做机械生存、不愿调查明显异常。"},
    "discipline": {"label": "自律", "short": "睡眠、工作、清洁、还债、预算和延迟满足。", "high": "高自律更会睡觉、洗澡、工作、按时还款、做预算和抵抗奢侈冲动。", "low": "低自律更容易熬夜、拖延房租/债务、沉迷娱乐或冲动消费。", "increase": "按时睡觉、工作、学习、洗澡、做预算、还债、拒绝不必要消费。", "decrease": "连续熬夜、违约、冲动购物、无视清洁/健康、长期什么也不做。"},
    "aggression": {"label": "攻击", "short": "冲突推进、威胁、抢夺、防卫和越界风险。", "high": "高攻击更可能选择威胁、抢劫、攻击、强制动作，也更敢对抗危险。", "low": "低攻击更倾向协商、退让、求助或离开冲突。", "increase": "攻击、威胁、犯罪、强制动作、越狱、长期处于高压力冲突。", "decrease": "冥想、道歉、和解、照护、遵守边界、用谈判替代暴力。"},
    "honesty": {"label": "诚实", "short": "说真话、守约、承认错误、报告事实和公平交易。", "high": "高诚实更会自我介绍、道歉、举报、还债、兑现承诺和拒绝偷骗。", "low": "低诚实更可能隐瞒亏损、偷窃、违约、利用关系或撒谎。", "increase": "正式介绍、承认错误、道歉、举报犯罪、还款、信守承诺。", "decrease": "偷窃、抢劫、隐藏亏损、故意违约、背叛承诺。"},
    "creativity": {"label": "创造", "short": "写作、音乐、艺术、视频、解决问题和提出新规则。", "high": "高创造更会创作、讲故事、写公告、提出社会规则和使用世界观合成/艺术工具。", "low": "低创造更依赖常规生存、工作和简单社交。", "increase": "写日记/故事、唱歌、画画、拍视频、写博客、提出规则、练习技能。", "decrease": "长期机械重复、过度疲劳、创作倦怠、不再尝试表达。"},
    "neuroticism": {"label": "敏感", "short": "焦虑、痛苦放大、危机警觉和情绪波动。", "high": "高敏感更容易害怕、痛苦、应激、抱怨、求助或躲避；也更早察觉危险。", "low": "低敏感更稳定、抗压，但可能低估痛苦和风险。", "increase": "创伤、被偷/被攻击、尸臭暴露、长期欠债、高压力、熬夜。", "decrease": "睡眠、冥想、呼吸、稳定社交支持、解决债务、规律生活。"},
}


def normalize_traits(raw: dict[str, int] | None, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    raw = raw or {}
    traits: dict[str, int] = {}
    for name in TRAIT_NAMES:
        base = int(raw.get(name, 50))
        traits[name] = clamp_int(base + rng.randint(-5, 5))
    return traits


def normalize_traits_to_budget(raw: dict[str, int] | None, seed: int, budget: int) -> dict[str, int]:
    rng = random.Random(seed)
    raw = raw or {}
    values = [max(0, int(raw.get(name, 50))) for name in TRAIT_NAMES]
    total = sum(values)
    if total <= 0:
        values = [1 for _ in TRAIT_NAMES]
        total = len(values)
    scaled = [int(value * budget / total) for value in values]
    remainder = max(0, budget - sum(scaled))
    order = list(range(len(TRAIT_NAMES)))
    rng.shuffle(order)
    for idx in order[:remainder]:
        scaled[idx] += 1
    return {name: clamp_int(value) for name, value in zip(TRAIT_NAMES, scaled)}


def random_traits_with_budget(seed: int, budget: int) -> dict[str, int]:
    rng = random.Random(seed)
    weights = [rng.randint(1, 100) for _ in TRAIT_NAMES]
    return normalize_traits_to_budget(dict(zip(TRAIT_NAMES, weights)), seed, budget)


def mood_label(mood: float) -> str:
    if mood >= 60:
        return "很愉快"
    if mood >= 30:
        return "开心"
    if mood >= 5:
        return "普通"
    if mood >= -20:
        return "有些低落"
    if mood >= -60:
        return "难受"
    return "崩溃边缘"


def trait_value(agent_or_traits: Any, key: str, default: int = 50) -> int:
    traits = getattr(agent_or_traits, "traits", agent_or_traits)
    try:
        return int(getattr(traits, key, default))
    except Exception:
        return default


def trait_prompt_lines(traits: Any) -> list[str]:
    values = {key: trait_value(traits, key) for key in TRAIT_NAMES}
    top = sorted(values.items(), key=lambda item: item[1], reverse=True)[:3]
    low = sorted(values.items(), key=lambda item: item[1])[:2]
    lines = [
        "这些点数不是装饰，会影响候选工具排序、自动回应、风险判定、关系变化和长期成长；高点数是倾向，不是强制命令。",
        "强项: " + "、".join(f"{TRAIT_METADATA[k]['label']}={v}({TRAIT_METADATA[k]['short']})" for k, v in top),
        "弱项: " + "、".join(f"{TRAIT_METADATA[k]['label']}={v}" for k, v in low),
    ]
    for key, _value in top:
        meta = TRAIT_METADATA[key]
        lines.append(f"{meta['label']}高: {meta['high']}")
    return lines[:6]


def trait_growth_reference_lines() -> list[str]:
    return [f"{meta['label']}: ↑{meta['increase']}；↓{meta['decrease']}" for meta in TRAIT_METADATA.values()]


def trait_priority_bias(traits: Any, tool_name: str) -> int:
    """Negative values make a tool appear earlier in the action menu."""
    t = {key: trait_value(traits, key) for key in TRAIT_NAMES}
    name = tool_name.lower()
    bias = 0

    def high(key: str, threshold: int = 65) -> bool:
        return t[key] >= threshold

    def low(key: str, threshold: int = 35) -> bool:
        return t[key] <= threshold

    if high("discipline") and any(x in name for x in ["sleep", "wash", "work", "budget", "repay", "plan", "clean"]):
        bias -= 12
    if low("discipline") and any(x in name for x in ["do_nothing", "play", "hum", "luxury", "status_drink"]):
        bias -= 5
    if high("sociability") and any(x in name for x in ["speak", "say", "chat", "meeting", "invite", "date", "compliment", "thank"]):
        bias -= 10
    if low("sociability") and any(x in name for x in ["write_private", "diary", "read", "walk_away", "ignore"]):
        bias -= 5
    if high("empathy") and any(x in name for x in ["help", "comfort", "share", "care", "child", "mourn", "bury", "apologize", "forgive"]):
        bias -= 12
    if high("curiosity") and any(x in name for x in ["look", "observe", "read", "research", "review", "explore", "market_news", "chart"]):
        bias -= 9
    if high("creativity") and any(x in name for x in ["write", "story", "blog", "sing", "sketch", "doodle", "music", "song", "paint", "video", "create", "propose"]):
        bias -= 10
    if high("caution") and any(x in name for x in ["check", "budget", "research", "set_boundary", "avoid", "report", "stop_loss", "take_profit"]):
        bias -= 9
    if high("caution") and any(x in name for x in ["force", "attack", "robbery", "theft", "margin", "short_sell", "loan_shark"]):
        bias += 10
    if high("aggression") and any(x in name for x in ["attack", "demand", "force", "theft", "robbery", "escape", "protest", "confront"]):
        bias -= 10
    if low("aggression") and any(x in name for x in ["attack", "demand", "force", "robbery"]):
        bias += 8
    if high("honesty") and any(x in name for x in ["introduce", "apologize", "report", "repay", "promise", "confess"]):
        bias -= 8
    if high("honesty") and any(x in name for x in ["theft", "robbery", "hide", "default_on_loan"]):
        bias += 8
    if high("neuroticism") and any(x in name for x in ["panic", "seek_help", "check_self", "set_boundary", "avoid", "complain"]):
        bias -= 7
    if high("neuroticism") and any(x in name for x in ["meditate", "breathe", "sleep", "rest"]):
        bias -= 5
    return bias


_EXPERIENCE_RULES: list[tuple[tuple[str, ...], dict[str, int]]] = [
    (("move_to_location", "wander", "invite_visible_agent_to_walk", "walk_by_lake"), {"openness": 1, "curiosity": 1}),
    (("look_around", "observe_visible_agent", "read_quietly", "research", "review_price_chart", "read_market_news"), {"curiosity": 1}),
    (("speak", "say_to", "chat", "meeting", "invite", "date", "compliment", "thank"), {"sociability": 1}),
    (("help", "comfort", "share", "care_for_child", "soothe_child", "feed_child", "mourn", "bury", "apologize", "forgive"), {"empathy": 1, "aggression": -1}),
    (("sleep", "wash", "work_shift", "do_odd_job", "budget", "repay", "plan_day", "clean_clothes", "tidy_room"), {"discipline": 1}),
    (("attack", "demand_money", "force_", "theft", "robbery", "burglary", "escape"), {"aggression": 1, "empathy": -1, "honesty": -1}),
    (("introduce_self", "report", "promise", "repay", "confess", "apologize"), {"honesty": 1}),
    (("hide_stock_loss", "default_on_loan", "pawn", "theft", "robbery", "burglary"), {"honesty": -1}),
    (("write", "story", "blog", "sing", "sketch", "doodle", "music", "song", "paint", "video", "propose_social_rule"), {"creativity": 1}),
    (("panic", "complain", "avoid_corpse", "report_visible_corpse"), {"neuroticism": 1}),
    (("meditate", "breathe", "sleep", "rest", "plan_day", "accept_plain_life"), {"neuroticism": -1}),
    (("check", "budget", "set_boundary", "avoid", "research", "stop_loss", "take_profit"), {"caution": 1}),
    (("margin", "short_sell", "loan_shark", "force_", "attack"), {"caution": -1}),
]


def trait_deltas_for_tool(tool_name: str) -> dict[str, int]:
    name = tool_name.lower()
    deltas: dict[str, int] = {}
    for needles, changes in _EXPERIENCE_RULES:
        if any(needle in name for needle in needles):
            for key, amount in changes.items():
                deltas[key] = deltas.get(key, 0) + amount
    return {key: max(-1, min(1, value)) for key, value in deltas.items() if key in TRAIT_NAMES and value}


def apply_trait_experience(agent: Any, tool_name: str, world_time: int, *, min_interval_minutes: int = 240) -> dict[str, dict[str, int]]:
    traits = getattr(agent, "traits", None)
    if not traits:
        return {}
    raw_deltas = trait_deltas_for_tool(tool_name)
    if not raw_deltas:
        return {}
    learning = dict(getattr(agent, "tool_learning_json", None) or {})
    cooldowns = dict(learning.get("trait_growth_cooldowns") or {})
    changes: dict[str, dict[str, int]] = {}
    for key, amount in raw_deltas.items():
        last = cooldowns.get(key)
        try:
            last_time = int(last) if last is not None else None
        except (TypeError, ValueError):
            last_time = None
        if last_time is not None and world_time - last_time < min_interval_minutes:
            continue
        before = trait_value(traits, key)
        after = clamp_int(before + amount)
        if after == before:
            continue
        setattr(traits, key, after)
        cooldowns[key] = world_time
        changes[key] = {"before": before, "after": after}
    if changes:
        log = list(learning.get("trait_growth_log") or [])
        for key, pair in changes.items():
            log.append({"world_time": world_time, "trait": key, "before": pair["before"], "after": pair["after"], "tool_name": tool_name})
        learning["trait_growth_cooldowns"] = cooldowns
        learning["trait_growth_log"] = log[-80:]
        agent.tool_learning_json = learning
    return changes
