from __future__ import annotations

import random
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import apply_delta, recompute_mood
from app.agents.traits import clamp
from app.core.models import Agent, AgentLocation, Conversation, Event, IdentityKnowledge, Location, Memory, World
from app.events.event_store import create_event
from app.simulation.difficulty import profile_for_agent
from app.world.corpses import ensure_corpse_for_dead_agent
from app.world.seed_world import world_location_id

WEREWOLF_ROLE_LABELS = {
    "villager": "平民",
    "werewolf": "狼人",
    "seer": "预言家",
    "coroner": "验尸官",
    "guard": "守卫",
    "witch": "女巫",
    "hunter": "猎人",
    "medium": "灵媒",
    "idiot": "白痴",
}

WEREWOLF_ROLE_PERSONALITY_TILTS = {
    "villager": "被赋予平民身份之后，你的人设只会向普通村民的现实感倾斜：更重视活下去、听懂别人说法、保护自己和亲近的人。你没有秘密能力，不要假装有系统给你的超自然知识；但你原本的性格、说话风格、胆量、善良或自私都必须保留，只是在危机里用这些原有人格去判断谁可信。",
    "werewolf": "被赋予狼人身份之后，你的人设会向隐秘、伪装、捕猎和操纵局势倾斜：你知道自己与普通居民立场不同，会本能地隐藏真实身份，试着把怀疑引向别人，夜里寻找目标，白天维持可信的普通人样子。这个倾向不能顶掉原本人设；如果你原本温和，就用温和方式骗人，如果你原本冲动，就更容易冒险露出破绽，但绝不能忘记自己是狼人。",
    "seer": "被赋予预言家身份之后，你的人设会向谨慎观察、追求真相和承担秘密压力倾斜：你更在意谁在撒谎、谁的说法互相矛盾，也会担心过早公开身份引来危险。这个倾向不能顶掉原本人设；你仍然按原本的胆量、表达习惯和人际关系说话，只是会把查验与怀疑放进判断里。",
    "coroner": "被赋予验尸官身份之后，你的人设会向冷静、细节、尸体线索和死亡事实倾斜：你更愿意从死亡顺序、死者身份、遗体位置和公开反应里寻找矛盾。这个倾向不能顶掉原本人设；胆小的人仍会害怕尸体，温柔的人仍会哀悼，只是会被职业责任推着整理线索。",
    "guard": "被赋予守卫身份之后，你的人设会向保护、责任、夜间警觉和牺牲感倾斜：你会更自然地考虑谁最需要保护、谁死掉会让局势崩坏，以及自己是否该承担风险。这个倾向不能顶掉原本人设；你原本谨慎就会保守守护，原本热血就可能主动保护别人，但不要把自己写成没有恐惧的工具人。",
    "witch": "被赋予女巫身份之后，你的人设会向秘密决断、药剂代价和道德压力倾斜：救人与毒杀都很重，你会反复权衡是否用掉机会，以及用在谁身上才对局势负责。这个倾向不能顶掉原本人设；你原本善良会更抗拒毒杀，原本强硬会更敢下手，但仍要承认这是沉重选择。",
    "hunter": "被赋予猎人身份之后，你的人设会向警觉、对峙、最后反击和公开威慑倾斜：你知道自己有一次强硬带走别人的机会，因此更容易在关键时刻要求别人给出明确解释。这个倾向不能顶掉原本人设；冷静的人会压住枪口等证据，冲动的人更可能急于开枪，但不能无视原本的关系和情绪。",
    "medium": "被赋予灵媒身份之后，你的人设会向安静、敏感、死者残留线索和阵营直觉倾斜：你更容易把注意力放到最近死者、临终线索、沉默和异常反应上。这个倾向不能顶掉原本人设；你原本开朗仍可以开朗，只是会被死亡信息拉得更沉、更警觉。",
    "idiot": "被赋予白痴身份之后，你的人设会向傻傻的、迟钝的、天然的、容易抓错重点但偶尔说出直觉真话的方向倾斜：你可能理解慢半拍，说话更直、更绕，容易被别人带偏，也可能因为不按常理反而戳中矛盾。这个倾向不能顶掉原本人设；不要把自己写成完全无智商、不能行动或只会胡闹，你仍然保留原本的善恶、胆量、关系和目标，只是表达和判断明显更笨拙。",
}

DAY_SPEECH_LIMIT = 1
REBUTTAL_REPLY_LIMIT = 5
NO_EXECUTION_VOTE = "__no_execution__"

DEFAULT_GAME_START_MINUTE = 8 * 60
DEFAULT_MORNING_MINUTES = 4 * 60
DEFAULT_DISCUSSION_MINUTES = 6 * 60
DEFAULT_VOTING_MINUTES = 4 * 60
DEFAULT_NIGHT_MINUTES = 10 * 60
NIGHT_ACTION_ROLES = {"werewolf", "seer", "coroner", "guard", "witch", "medium"}
WEREWOLF_ROLE_NAMES = set(WEREWOLF_ROLE_LABELS)
PUBLIC_DEFAULT_SPECIAL_ROLE_ORDER = ("seer", "coroner", "guard")
PUBLIC_SPECIAL_ROLE_ORDER = ("seer", "coroner", "guard", "witch", "hunter", "medium", "idiot")
AUTO_ROLE_ORDER = ("werewolf", "seer", "coroner", "guard", "witch", "hunter", "medium", "idiot", "villager")
DEFAULT_AUTO_ROLES = ("villager", "werewolf", "seer", "coroner", "guard")
COUNT_ROLE_ORDER = ("werewolf", "seer", "coroner", "guard", "witch", "hunter", "medium", "idiot", "villager")
AUTO_ROLE_MIN_PLAYERS = {
    "villager": 1,
    "werewolf": 3,
    "seer": 3,
    "coroner": 4,
    "guard": 5,
    "witch": 6,
    "hunter": 6,
    "medium": 7,
    "idiot": 8,
}
WEREWOLF_REASONING_MEMORY_TYPE = "werewolf_reasoning"

WEREWOLF_VENDING_MARKET_TOOL_NAMES = {
    "market_search_goods",
    "market_recommend_goods",
    "market_buy_goods",
    "eat_inventory_food",
}

_CANONICAL_WEREWOLF_TOOL_NAMES = {
    "werewolf_record_reasoning",
    "werewolf_summarize_clues",
    "werewolf_speak",
    "werewolf_end_speech",
    "werewolf_rebut",
    "werewolf_skip_rebuttal",
    "werewolf_reply_rebuttal",
    "werewolf_drop_debate",
    "werewolf_vote_by_name",
    "werewolf_vote_no_execution",
    "werewolf_review_vote_history",
    "werewolf_wolf_discuss",
    "werewolf_kill_by_name",
    "werewolf_seer_check_by_name",
    "werewolf_coroner_check_latest",
    "werewolf_guard_protect_by_name",
    "werewolf_witch_save_latest",
    "werewolf_witch_reveal_saved_attack",
    "werewolf_witch_poison_by_name",
    "werewolf_hunter_shoot_by_name",
    "werewolf_medium_check_latest",
    "werewolf_idiot_reveal_self",
}

_WEREWOLF_TOOL_ALIASES = {
    "werewolf_prepare_notes": "werewolf_summarize_clues",
    "werewolf_speech": "werewolf_speak",
    "werewolf_counter_speech": "werewolf_reply_rebuttal",
    "werewolf_rebuttal": "werewolf_rebut",
    "werewolf_vote": "werewolf_vote_by_name",
    "werewolf_vote_visible_agent": "werewolf_vote_by_name",
    "werewolf_view_vote_history": "werewolf_review_vote_history",
    "werewolf_check_vote_history_visible_agent": "werewolf_review_vote_history",
    "werewolf_wolf_kill": "werewolf_kill_by_name",
    "werewolf_kill_named_agent": "werewolf_kill_by_name",
    "werewolf_seer_check_named_agent": "werewolf_seer_check_by_name",
    "werewolf_coroner_review_death": "werewolf_coroner_check_latest",
    "werewolf_guard_protect": "werewolf_guard_protect_by_name",
    "werewolf_witch_save": "werewolf_witch_save_latest",
    "werewolf_witch_reveal_save": "werewolf_witch_reveal_saved_attack",
    "werewolf_witch_poison": "werewolf_witch_poison_by_name",
    "werewolf_medium_check": "werewolf_medium_check_latest",
}

# Keep old names in the accepted set so saved menus/worlds from previous builds do not crash,
# but menu generation uses the canonical names above.
WEREWOLF_TOOL_NAMES = set(_CANONICAL_WEREWOLF_TOOL_NAMES) | set(_WEREWOLF_TOOL_ALIASES)


def _canonical_tool_name(tool_name: str) -> str:
    return _WEREWOLF_TOOL_ALIASES.get(tool_name, tool_name)


def werewolf_enabled(world: World | None) -> bool:
    return bool(world and (world.settings_json or {}).get("werewolf_mode_enabled"))


def is_werewolf_world(world: World | None) -> bool:
    return werewolf_enabled(world)


def werewolf_vending_market_tool_allowed(world: World | None, location: Location | None, tool_name: str) -> bool:
    """Allow only the tiny vending-machine market surface inside Werewolf worlds."""
    if not werewolf_enabled(world) or not location:
        return False
    name = str(tool_name or "")
    if name not in WEREWOLF_VENDING_MARKET_TOOL_NAMES:
        return False
    tags = set(location.tags_json or [])
    local_id = _local_location_id(location.location_id)
    return local_id == "vending_machine" or bool(tags & {"vending_machine", "werewolf_vending"})


def werewolf_phase(world: World) -> tuple[int, str]:
    day, phase, _start_minute, _end_minute = werewolf_phase_window(world)
    return day, phase


def werewolf_phase_window(world: World) -> tuple[int, str, int, int]:
    """Return (game_day, phase, absolute_phase_start_minute, absolute_phase_end_minute).

    Day 1 is intentionally only free chat until the normal 22:00 night boundary.
    Night abilities start on the first night, and the first structured
    round-table/vote happens on Day 2. The vote is hosted at 18:00 immediately
    after the round-table and consumes no world time; once resolved, 18:00-22:00
    returns to ordinary free activity. This avoids the impossible story where a
    seer claims a Day-1 daytime result from a night that has not happened yet.
    """
    minute = int(world.current_world_time_minutes or 0)
    start, morning_minutes, discussion_minutes, voting_minutes, night_minutes = _phase_schedule(world)
    day_minutes = morning_minutes + discussion_minutes + voting_minutes
    cycle_minutes = max(1, day_minutes + night_minutes)
    elapsed = max(0, minute - start)
    day = elapsed // cycle_minutes + 1
    clock = elapsed % cycle_minutes
    base = start + (day - 1) * cycle_minutes

    if day == 1:
        if clock < day_minutes:
            return day, "morning", base, base + day_minutes
        return day, "night", base + day_minutes, base + cycle_minutes

    if clock < morning_minutes:
        return day, "morning", base, base + morning_minutes
    discussion_start = base + morning_minutes
    if clock < morning_minutes + discussion_minutes:
        return day, "discussion", discussion_start, discussion_start + discussion_minutes
    voting_start = discussion_start + discussion_minutes
    if clock < morning_minutes + discussion_minutes + voting_minutes:
        state = werewolf_state(world)
        if ((state.get("vote_resolved") or {}).get(str(day))):
            return day, "morning", voting_start, voting_start + voting_minutes
        return day, "voting", voting_start, voting_start + voting_minutes
    night_start = voting_start + voting_minutes
    return day, "night", night_start, base + cycle_minutes


def werewolf_current_phase_end_minute(world: World) -> int:
    return werewolf_phase_window(world)[3]


def _phase_schedule(world: World) -> tuple[int, int, int, int, int]:
    params = ((world.settings_json or {}).get("worldview_rule_parameters") or {}).get("werewolf") or {}

    def _minutes(key: str, default: int) -> int:
        try:
            return max(1, int(params.get(key) or default))
        except (TypeError, ValueError):
            return default

    try:
        start = int(params.get("game_start_minute") or DEFAULT_GAME_START_MINUTE)
    except (TypeError, ValueError):
        start = DEFAULT_GAME_START_MINUTE
    morning = _minutes("morning_minutes", DEFAULT_MORNING_MINUTES)
    discussion = _minutes("discussion_minutes", DEFAULT_DISCUSSION_MINUTES)
    voting = _minutes("voting_minutes", DEFAULT_VOTING_MINUTES)
    night = _minutes("night_minutes", DEFAULT_NIGHT_MINUTES)
    # Earlier builds wrote short fast-debug cycles or the old 18:00-night rhythm
    # into saved worlds. Treat them as legacy data at read time so hosted Werewolf
    # keeps a human rhythm: 08:00 free chat, 12:00 round-table, 18:00 vote,
    # 22:00 night actions.
    if (
        (morning, discussion, voting, night) in {(20, 45, 25, 90), (4 * 60, 4 * 60, 2 * 60, 14 * 60)}
        or (morning + discussion + voting + night) < 12 * 60
    ):
        morning = DEFAULT_MORNING_MINUTES
        discussion = DEFAULT_DISCUSSION_MINUTES
        voting = DEFAULT_VOTING_MINUTES
        night = DEFAULT_NIGHT_MINUTES
    return (start, morning, discussion, voting, night)


def current_phase_for_time(world: World) -> str:
    return werewolf_phase(world)[1]


def phase_label(phase: str) -> str:
    return {"morning": "自由交流", "discussion": "圆桌发言", "voting": "公开投票", "night": "夜间行动"}.get(phase, phase)


def werewolf_state(world: World | None) -> dict[str, Any]:
    if not world:
        return {}
    state = (world.settings_json or {}).get("werewolf_state")
    return dict(state) if isinstance(state, dict) else {}


def ensure_werewolf_agent_context(session: Session, world: World | None) -> None:
    if not werewolf_enabled(world) or not world:
        return
    state = werewolf_state(world)
    if not state.get("roles"):
        return
    _ensure_werewolf_secret_defaults(session, world, state)
    settings = dict(world.settings_json or {})
    settings["werewolf_state"] = state
    world.settings_json = settings


_LOCKED_LOCATION_NAMES = {
    "vending_machine": "自动售货机",
    "discussion_hall": "村庄会议厅",
    "voting_room": "议事侧厅",
    "seer_room": "安静小屋",
    "guard_room": "值守小屋",
    "morgue": "医务间",
    "wolf_den": "林间隐蔽处",
    "dormitory": "公共宿舍",
}

_LOCKED_LOCATION_DESCRIPTIONS = {
    "vending_machine": "村庄广场旁的旧式自动售货机，只出售少量包装食物、饮料和日用品，不连接现代工作、金融或完整集市。",
    "discussion_hall": "一间摆着长桌和长椅的普通会议厅，适合村民开会、休息和交换消息。",
    "voting_room": "会议厅旁边的安静侧厅，平时用于登记、等候或私下整理想法。",
    "seer_room": "一间安静的小屋，光线柔和，适合独处、阅读或整理思绪。",
    "guard_room": "一间靠近村口的值守小屋，里面有简单床铺和记录本。",
    "morgue": "医务间后侧的冷清小房间，用于临时处理伤病和突发事件。",
    "wolf_den": "林间一处隐蔽空地，平时只是偏僻、少有人来的地方。",
    "dormitory": "给临时住民休息的公共宿舍，房间简朴，能遮风避雨。",
}

_WEREWOLF_LOCATION_SPECS = {
    "village_square": {
        "neighbors": ["discussion_hall", "dormitory", "vending_machine"],
        "tools": ["look_around", "speak_to_nearby", "observe_visible_agent"],
        "tags": ["social", "open_view", "werewolf_day"],
        "radius": 1,
    },
    "vending_machine": {
        "neighbors": ["village_square", "cafeteria"],
        "tools": ["market_search_goods", "market_recommend_goods", "market_buy_goods", "eat_inventory_food"],
        "tags": ["trade", "food", "water", "vending_machine", "werewolf_vending"],
        "radius": 0,
    },
    "discussion_hall": {
        "neighbors": ["village_square", "voting_room"],
        "tools": ["speak_to_nearby", "werewolf_summarize_clues", "werewolf_speak", "werewolf_hunter_shoot_by_name", "werewolf_idiot_reveal_self"],
        "tags": ["social", "vote", "werewolf_day"],
        "radius": 1,
    },
    "voting_room": {
        "neighbors": ["discussion_hall", "morgue"],
        "tools": ["speak_to_nearby", "werewolf_vote_by_name", "werewolf_review_vote_history", "werewolf_hunter_shoot_by_name", "werewolf_idiot_reveal_self"],
        "tags": ["vote", "werewolf_day"],
        "radius": 1,
    },
    "seer_room": {
        "neighbors": ["dormitory", "morgue", "guard_room"],
        "tools": ["werewolf_seer_check_by_name", "werewolf_witch_save_latest", "werewolf_witch_poison_by_name", "review_recent_memory", "write_private_note"],
        "tags": ["quiet", "werewolf_night", "role_room"],
        "radius": 0,
    },
    "guard_room": {
        "neighbors": ["dormitory", "seer_room", "morgue"],
        "tools": ["werewolf_guard_protect_by_name", "review_recent_memory", "write_private_note"],
        "tags": ["quiet", "werewolf_night", "role_room"],
        "radius": 0,
    },
    "morgue": {
        "neighbors": ["voting_room", "seer_room", "guard_room"],
        "tools": ["werewolf_coroner_check_latest", "werewolf_medium_check_latest", "inspect_visible_corpse", "report_visible_corpse"],
        "tags": ["medical", "corpse", "werewolf_night"],
        "radius": 0,
    },
    "wolf_den": {
        "neighbors": ["dormitory"],
        "tools": ["werewolf_wolf_discuss", "werewolf_kill_by_name", "speak_to_nearby", "review_recent_memory"],
        "tags": ["secret", "quiet", "werewolf_night"],
        "radius": 0,
    },
    "dormitory": {
        "neighbors": ["village_square", "seer_room", "guard_room", "wolf_den"],
        "tools": ["sleep", "rest", "write_private_note"],
        "tags": ["home", "quiet", "werewolf_night"],
        "radius": 0,
    },
}

_LOCKED_WEREWOLF_TERMS = (
    "狼人杀",
    "狼人",
    "圆桌",
    "投票",
    "票型",
    "出局",
    "夜袭",
    "预言家",
    "验尸官",
    "守卫",
    "女巫",
    "猎人",
    "灵媒",
    "白痴",
    "阵营",
    "身份能力",
)


def _local_location_id(location_id: str | None) -> str:
    if not location_id:
        return ""
    return str(location_id).split(":")[-1]


def werewolf_publicly_revealed(world: World | None) -> bool:
    """Whether agent-facing prompts may mention Werewolf rules/roles.

    New games keep the crisis hidden until a night death creates an in-world
    discovery.  The body-found fallback keeps older saves coherent if they were
    created before the explicit public_revealed flag existed.
    """
    if not werewolf_enabled(world):
        return True
    state = werewolf_state(world)
    if state.get("public_revealed"):
        return True
    announced = state.get("body_found_announced") or {}
    if isinstance(announced, dict):
        for value in announced.values():
            if isinstance(value, dict) and value.get("target_agent_id"):
                return True
    return False


def werewolf_prompt_status_lines(session: Session, world: World, agent: Agent) -> list[str]:
    if not werewolf_enabled(world):
        return []
    state = werewolf_state(world)
    roles = state.get("roles") if isinstance(state.get("roles"), dict) else {}
    day, phase = werewolf_phase(world)
    own_role = roles.get(agent.agent_id) or (agent.desires_json or {}).get("werewolf", {}).get("role") or "villager"
    if not werewolf_publicly_revealed(world):
        lines = [
            f"村庄房间里的传单只写着：本轮特殊职业数量为{_public_special_role_count_text(roles, world.settings_json or {})}；传单没有解释这些称号的用途，也没有写任何人的身份。",
        ]
        if own_role == "werewolf":
            living = [
                item
                for item in session.execute(
                    select(Agent)
                    .where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
                    .order_by(Agent.created_at_world_time, Agent.agent_id)
                ).scalars()
            ]
            living_wolves = [item for item in living if roles.get(item.agent_id) == "werewolf"]
            living_targets = [item for item in living if roles.get(item.agent_id) != "werewolf"]
            lines.extend(
                [
                    "只有你知道：你的隐藏身份是狼人。其他居民还不知道狼人存在，也不知道这里会发生隐藏身份危机；公开发言前要把他们当成普通村民来骗过。",
                    "你的夜间身份私密事实：你当前存活的狼人同伴是："
                    f"{'、'.join(item.chosen_name for item in living_wolves if item.agent_id != agent.agent_id) or '无'}；"
                    f"今晚可夜袭目标只能从当前存活且不是狼人同伴的人里选：{'、'.join(item.chosen_name for item in living_targets) or '无'}。",
                    _role_personality_tilt_line(own_role),
                ]
            )
        elif own_role == "witch":
            saveable = _saveable_night_kill(state, day) if phase == "night" else None
            saved_attack = _latest_revealable_witch_saved_attack(state, day, phase, agent.agent_id)
            if saveable:
                target = session.get(Agent, str(saveable.get("target_agent_id") or ""))
                lines.extend(
                    [
                        f"只有你知道：今晚{target.chosen_name if target else '有人'}被未知夜袭命中；你可以使用解药救回这个人。这个事实还没有公开，不能说成所有居民已经知道有狼人存在。",
                        _role_personality_tilt_line(own_role),
                    ]
                )
            elif saved_attack:
                target = session.get(Agent, str(saved_attack.get("target_agent_id") or ""))
                lines.extend(
                    [
                        f"只有你知道：你在第{saved_attack.get('night')}夜用解药救回了{target.chosen_name if target else '一名遇袭者'}。你可以选择公开这次夜袭事实，也可以继续保密；保密时其他居民仍只会把这里当作普通村庄。",
                        _role_personality_tilt_line(own_role),
                    ]
                )
        return lines
    _ensure_public_revealed_agent_state(session, world, state, day=day, reason=str(state.get("role_reveal_reason") or "公开危机事实"))
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id)
            .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    )
    living = [item for item in agents if item.lifecycle_state != "dead"]
    dead = [item for item in agents if item.lifecycle_state == "dead"]
    living_names = "、".join(item.chosen_name for item in living) or "无"
    dead_names = "、".join(f"{item.chosen_name}({item.death_cause or '已出局'})" for item in dead) or "无"
    lines = [
        f"村庄房间里的传单只写着：本轮特殊职业数量为{_public_special_role_count_text(roles, world.settings_json or {})}；传单没有解释这些称号的用途，也没有写任何人的身份。",
        "村庄广场告示牌上出现血红字：狼人存在于村中。",
        f"你的隐藏身份固定事实：你的身份是：{WEREWOLF_ROLE_LABELS.get(own_role, own_role)}。这个事实优先级高于任何人的自称或猜测，不要因为别人跳身份就忘记自己的真实身份。",
        _role_personality_tilt_line(own_role),
        "身份数量推理规则：传单上的特殊职业数量是真实上限；如果本轮某职业只有1个，而你自己就是该职业，另一个人自称同职业就是强冲突线索，不能同时都是真身份。",
        f"村庄危机当前事实：第{day}天{phase_label(phase)}；当前还活着的人只有：{living_names}；已死亡或被放逐者：{dead_names}。",
        "已死亡或被放逐者不能再发言、投票、被投票、被夜袭、被查验或被守护；不要把他们当成今晚或今天的可行动目标。",
    ]
    if own_role == "werewolf":
        living_wolves = [item for item in living if roles.get(item.agent_id) == "werewolf"]
        living_targets = [item for item in living if roles.get(item.agent_id) != "werewolf"]
        lines.append(
            "你的夜间身份私密事实：你当前存活的狼人同伴是："
            f"{'、'.join(item.chosen_name for item in living_wolves if item.agent_id != agent.agent_id) or '无'}；"
            f"今晚可夜袭目标只能从当前存活且不是狼人同伴的人里选：{'、'.join(item.chosen_name for item in living_targets) or '无'}。"
        )
    return lines


def _role_personality_tilt_line(role: str) -> str:
    return "身份对人设的倾向影响：" + WEREWOLF_ROLE_PERSONALITY_TILTS.get(role, WEREWOLF_ROLE_PERSONALITY_TILTS["villager"])


def _public_special_role_count_text(role_map: dict[str, str], settings: dict[str, Any] | None = None) -> str:
    counts = Counter(role_map.values())
    return "、".join(
        f"{WEREWOLF_ROLE_LABELS[role]}{int(counts.get(role) or 0)}个"
        for role in _public_special_roles_for_game(role_map, settings or {})
    )


def _public_special_roles_for_game(role_map: dict[str, str], settings: dict[str, Any]) -> tuple[str, ...]:
    config = settings.get("werewolf_role_assignment")
    roles: list[str] = []
    if isinstance(config, dict):
        mode = str(config.get("mode") or "auto")
        if mode != "auto":
            roles.extend(PUBLIC_DEFAULT_SPECIAL_ROLE_ORDER)
        auto_roles = config.get("auto_roles") or config.get("autoRoles")
        counts = config.get("counts") if isinstance(config.get("counts"), dict) else {}
        if isinstance(auto_roles, list):
            roles.extend(_auto_role_pool_for_count(int(settings.get("agent_count") or len(role_map) or 1), {str(role) for role in auto_roles}))
        roles.extend(str(role) for role, value in counts.items() if value)
        manual_roles = config.get("manual_roles") or config.get("manualRoles")
        if isinstance(manual_roles, list):
            roles.extend(str(role) for role in manual_roles)
    else:
        roles.extend(PUBLIC_DEFAULT_SPECIAL_ROLE_ORDER)
    roles.extend(str(role) for role in role_map.values())
    result: list[str] = []
    for role in PUBLIC_SPECIAL_ROLE_ORDER:
        if role in {"villager", "werewolf"}:
            continue
        if role in roles and role not in result:
            result.append(role)
    return tuple(result or PUBLIC_DEFAULT_SPECIAL_ROLE_ORDER)


def werewolf_agent_facing_location_name(world: World | None, location: Location | None) -> str:
    if not location:
        return "未知地点"
    if werewolf_enabled(world) and not werewolf_publicly_revealed(world):
        return _LOCKED_LOCATION_NAMES.get(_local_location_id(location.location_id), location.public_name or "未知地点")
    return location.public_name or "未知地点"


def werewolf_agent_facing_location_description(world: World | None, location: Location | None) -> str:
    if not location:
        return "未知"
    if werewolf_enabled(world) and not werewolf_publicly_revealed(world):
        return _LOCKED_LOCATION_DESCRIPTIONS.get(_local_location_id(location.location_id), location.description or "未知")
    return location.description or "未知"


def werewolf_agent_text_locked(world: World | None, text: str | None) -> bool:
    if not werewolf_enabled(world) or werewolf_publicly_revealed(world):
        return False
    return any(term in str(text or "") for term in _LOCKED_WEREWOLF_TERMS)


def initialize_werewolf_game(session: Session, world: World) -> list[int]:
    return initialize_werewolf_roles(session, world)


def initialize_werewolf_roles(session: Session, world: World) -> list[int]:
    event_ids: list[int] = []
    if not werewolf_enabled(world):
        return event_ids
    _ensure_werewolf_locations(session, world)
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
            .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    )
    if not agents:
        return event_ids
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    role_map = state.get("roles") if isinstance(state.get("roles"), dict) else {}
    if set(role_map.keys()) == {agent.agent_id for agent in agents}:
        _ensure_werewolf_secret_defaults(session, world, state)
        settings["werewolf_state"] = state
        world.settings_json = settings
        return event_ids

    rng = random.Random(f"werewolf:{world.seed}:{world.world_id}:{len(agents)}")
    roles = _configured_role_list(settings, len(agents), rng)
    role_map = {agent.agent_id: roles[index] for index, agent in enumerate(agents)}
    day, phase = werewolf_phase(world)
    state = {
        "roles": role_map,
        "day": day,
        "phase": phase,
        "speech_order": [agent.agent_id for agent in agents],
        "current_speaker_index": 0,
        "speech_counts": {},
        "speech_ended": {},
        "votes": {},
        "vote_history": [],
        "night_kills": {},
        "wolf_kill_nominations": {},
        "wolf_discussions": {},
        "wolf_consensus_need_discussion": {},
        "wolf_consensus_mismatches": {},
        "seer_checks": {},
        "coroner_reports": {},
        "guard_protects": {},
        "witch_saves": {},
        "witch_saved_attack_reveals": {},
        "witch_poisons": {},
        "hunter_shots": {},
        "medium_reports": {},
        "idiot_reveals": {},
        "winner": None,
        "public_revealed": False,
        "roles_revealed_to_agents": False,
        "wolves_revealed_to_agents": False,
        "hidden_first_night_attack_done": {},
    }
    settings["werewolf_state"] = state
    settings["werewolf_observer_roles"] = {agent_id: WEREWOLF_ROLE_LABELS.get(role, role) for agent_id, role in role_map.items()}
    world.settings_json = settings

    for agent in agents:
        desires = dict(agent.desires_json or {})
        desires.pop("werewolf", None)
        agent.desires_json = desires
    _reveal_wolves_to_agents(session, world, state, day=day)
    settings = dict(world.settings_json or {})
    settings["werewolf_state"] = state
    world.settings_json = settings
    event = create_event(
        session,
        world=world,
        event_type="werewolf_setup",
        viewer_text=f"开局时，所有居民都在村庄房间看到一张传单：本轮特殊职业数量为{_public_special_role_count_text(role_map, settings)}；传单没有解释这些称号的用途，也没有写任何人的身份。",
        importance=90,
        color_class="important",
        visibility_scope="public",
        payload={"public_special_role_count": _public_special_role_counts(role_map, settings), "wolf_count_public": False, "observer_can_see_roles": False},
        no_state_changed=True,
    )
    event_ids.append(event.event_id)
    return event_ids


def _role_list_for_count(count: int, allowed_roles: set[str] | None = None) -> list[str]:
    allowed_roles = set(_auto_role_pool_for_count(count, allowed_roles))
    if count <= 5:
        wolf_count = 1
    elif count <= 8:
        wolf_count = 2
    elif count <= 12:
        wolf_count = 3
    else:
        wolf_count = 4
    roles: list[str] = ["werewolf"] * min(wolf_count, max(1, count - 1))
    for role in AUTO_ROLE_ORDER:
        if role in {"villager", "werewolf"}:
            continue
        if role in allowed_roles and len(roles) < count:
            roles.append(role)
    while len(roles) < count:
        roles.append("villager")
    return roles[:count]


def _auto_role_pool_for_count(count: int, allowed_roles: set[str] | None = None) -> tuple[str, ...]:
    requested = {role for role in set(allowed_roles or DEFAULT_AUTO_ROLES) if role in WEREWOLF_ROLE_NAMES}
    requested.update({"villager", "werewolf"})
    if count <= 5:
        wolf_slots = 1
    elif count <= 8:
        wolf_slots = 2
    elif count <= 12:
        wolf_slots = 3
    else:
        wolf_slots = 4
    used_slots = min(count, wolf_slots)
    roles: list[str] = []
    for role in AUTO_ROLE_ORDER:
        if role not in requested:
            continue
        if role in {"villager", "werewolf"}:
            roles.append(role)
            continue
        if count < AUTO_ROLE_MIN_PLAYERS.get(role, 1):
            continue
        if used_slots + 1 > count:
            continue
        used_slots += 1
        roles.append(role)
    return tuple(roles or DEFAULT_AUTO_ROLES)


def _configured_role_list(settings: dict[str, Any], count: int, rng: random.Random) -> list[str]:
    config = settings.get("werewolf_role_assignment")
    if not isinstance(config, dict):
        config = {}
    mode = str(config.get("mode") or "auto")
    if mode == "manual":
        raw_roles = config.get("manual_roles")
        if isinstance(raw_roles, list):
            roles = [role if role in WEREWOLF_ROLE_NAMES else "villager" for role in map(str, raw_roles[:count])]
            while len(roles) < count:
                roles.append("villager")
            return roles[:count]
    if mode == "counts":
        counts = config.get("counts") if isinstance(config.get("counts"), dict) else {}
        roles: list[str] = []
        remaining = count
        for role in COUNT_ROLE_ORDER:
            try:
                role_count = min(remaining, max(0, int(counts.get(role) or 0)))
            except (TypeError, ValueError):
                role_count = 0
            roles.extend([role] * role_count)
            remaining -= role_count
            if remaining <= 0:
                break
        if len(roles) < count:
            roles.extend(["villager"] * (count - len(roles)))
        roles = roles[:count]
        rng.shuffle(roles)
        return roles
    raw_auto_roles = config.get("auto_roles") or config.get("autoRoles")
    if isinstance(raw_auto_roles, list):
        allowed_roles = {str(role) for role in raw_auto_roles if str(role) in WEREWOLF_ROLE_NAMES}
    else:
        allowed_roles = set(DEFAULT_AUTO_ROLES)
    roles = _role_list_for_count(count, allowed_roles)
    rng.shuffle(roles)
    return roles


def _role_counts(role_map: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for role in role_map.values():
        label = WEREWOLF_ROLE_LABELS.get(role, role)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _public_special_role_counts(role_map: dict[str, str], settings: dict[str, Any] | None = None) -> dict[str, int]:
    counts = Counter(role_map.values())
    return {
        WEREWOLF_ROLE_LABELS[role]: int(counts.get(role) or 0)
        for role in _public_special_roles_for_game(role_map, settings or {})
    }


def _seed_opening_notice_board(world: World) -> None:
    location_id = world_location_id(world.world_id, "village_square")
    settings = dict(world.settings_json or {})
    boards = settings.get("location_notice_boards")
    boards = dict(boards) if isinstance(boards, dict) else {}
    entries = list(boards.get(location_id) or [])
    fixed_text = "血红字：狼人存在于村中。"
    if not any(isinstance(entry, dict) and str(entry.get("content") or "") == fixed_text for entry in entries):
        entries.append({"content": fixed_text, "author_agent_id": "werewolf_host", "world_time": world.current_world_time_minutes, "fixed": True})
    boards[location_id] = entries[-20:]
    settings["location_notice_boards"] = boards
    world.settings_json = settings


def _seed_public_name_knowledge(session: Session, world: World, agents: list[Agent]) -> None:
    for observer in agents:
        for target in agents:
            if observer.agent_id == target.agent_id:
                continue
            existing = next(
                (
                    item
                    for item in session.new
                    if isinstance(item, IdentityKnowledge)
                    and item.observer_agent_id == observer.agent_id
                    and item.target_agent_id == target.agent_id
                ),
                None,
            )
            if existing is None:
                existing = session.execute(
                    select(IdentityKnowledge).where(
                        IdentityKnowledge.observer_agent_id == observer.agent_id,
                        IdentityKnowledge.target_agent_id == target.agent_id,
                    )
                ).scalar_one_or_none()
            if existing:
                existing.visual_known = True
                existing.name_known = True
                existing.known_name = target.chosen_name
                existing.name_confidence = max(existing.name_confidence or 0, 95)
                existing.last_seen_at = world.current_world_time_minutes
            else:
                session.add(
                    IdentityKnowledge(
                        observer_agent_id=observer.agent_id,
                        target_agent_id=target.agent_id,
                        visual_known=True,
                        name_known=True,
                        known_name=target.chosen_name,
                        name_confidence=95,
                        first_seen_at=world.current_world_time_minutes,
                        first_name_learned_at=world.current_world_time_minutes,
                        last_seen_at=world.current_world_time_minutes,
                        appearance_snapshot=target.appearance_short,
                        notes="死亡事件后的会议名册。",
                    )
                )
    session.flush()


def _ensure_werewolf_secret_defaults(session: Session, world: World, state: dict[str, Any]) -> None:
    state.setdefault("public_revealed", False)
    state.setdefault("roles_revealed_to_agents", bool(state.get("public_revealed")))
    state.setdefault("wolves_revealed_to_agents", False)
    state.setdefault("hidden_first_night_attack_done", {})
    state.setdefault("wolf_consensus_need_discussion", {})
    state.setdefault("wolf_consensus_mismatches", {})
    state.setdefault("witch_saves", {})
    state.setdefault("witch_saved_attack_reveals", {})
    state.setdefault("witch_poisons", {})
    state.setdefault("hunter_shots", {})
    state.setdefault("medium_reports", {})
    state.setdefault("idiot_reveals", {})
    if not state.get("public_revealed"):
        _reveal_wolves_to_agents(session, world, state, day=int(state.get("day") or werewolf_phase(world)[0]))
    if state.get("public_revealed"):
        _ensure_public_revealed_agent_state(session, world, state, day=int(state.get("day") or werewolf_phase(world)[0]), reason=str(state.get("role_reveal_reason") or "公开危机事实"))
        return
    # Migrate older saves that wrote roles into desires at setup.  The role map stays
    # in observer state, but non-wolf prompts must not see it before the public reveal.
    roles = dict(state.get("roles") or {})
    for agent in session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")).scalars():
        desires = dict(agent.desires_json or {})
        if roles.get(agent.agent_id) == "werewolf":
            continue
        if desires.pop("werewolf", None) is not None:
            agent.desires_json = desires


def _reveal_wolves_to_agents(session: Session, world: World, state: dict[str, Any], *, day: int) -> None:
    if state.get("wolves_revealed_to_agents"):
        return
    roles = dict(state.get("roles") or {})
    if not roles:
        return
    wolves = [agent_id for agent_id, role in roles.items() if role == "werewolf"]
    if not wolves:
        state["wolves_revealed_to_agents"] = True
        return
    for agent_id in wolves:
        agent = session.get(Agent, agent_id)
        if not agent or agent.lifecycle_state == "dead":
            continue
        fellow_wolves = [wolf_id for wolf_id in wolves if wolf_id != agent.agent_id]
        desires = dict(agent.desires_json or {})
        existing = dict(desires.get("werewolf") or {})
        existing.update(
            {
                "role": "werewolf",
                "role_label": WEREWOLF_ROLE_LABELS["werewolf"],
                "known_wolves": fellow_wolves,
                "revealed_day": day,
                "private_until_public_board": True,
            }
        )
        existing.setdefault("crisis_notes", [])
        desires["werewolf"] = existing
        agent.desires_json = desires
        if fellow_wolves:
            wolf_text = f"你知道狼人同伴是：{_names(session, fellow_wolves)}。夜袭需要所有存活狼人选择同一目标；如果意见不一致，今晚不会立刻成功，需要先密会统一目标。"
        else:
            wolf_text = "目前只有你一个狼人，没有狼人同伴；夜里无需密会，直接选择夜袭目标。"
        _add_werewolf_memory(
            session,
            world,
            agent,
            f"第{day}天私密事实：只有你知道自己是狼人，其他居民还不知道狼人存在，也不知道这里会发生隐藏身份危机。{wolf_text}",
            importance=98,
        )
    state["wolves_revealed_to_agents"] = True


def _ensure_public_revealed_agent_state(session: Session, world: World, state: dict[str, Any], *, day: int, reason: str) -> None:
    roles = dict(state.get("roles") or {})
    if not roles:
        return
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
            .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    )
    wolves = [agent_id for agent_id, role in roles.items() if role == "werewolf"]
    changed = False
    for agent in agents:
        role = roles.get(agent.agent_id, "villager")
        fellow_wolves = [wolf_id for wolf_id in wolves if wolf_id != agent.agent_id]
        desires = dict(agent.desires_json or {})
        existing = dict(desires.get("werewolf") or {})
        before = dict(existing)
        existing.update(
            {
                "role": role,
                "role_label": WEREWOLF_ROLE_LABELS.get(role, role),
                "known_wolves": fellow_wolves if role == "werewolf" else [],
                "revealed_day": int(existing.get("revealed_day") or day),
                "public_reason": str(existing.get("public_reason") or reason),
            }
        )
        existing.setdefault("crisis_notes", [])
        desires["werewolf"] = existing
        if before != existing:
            agent.desires_json = desires
            changed = True
    _seed_public_name_knowledge(session, world, agents)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state.setdefault("role_reveal_day", day)
    state.setdefault("role_reveal_reason", reason)
    if changed:
        _persist_werewolf_state(world, state)


def _reveal_werewolf_to_agents(session: Session, world: World, state: dict[str, Any], *, day: int, reason: str) -> None:
    if state.get("roles_revealed_to_agents") and state.get("public_revealed"):
        _ensure_public_revealed_agent_state(session, world, state, day=day, reason=reason)
        return
    roles = dict(state.get("roles") or {})
    if not roles:
        return
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
            .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    )
    wolves = [agent_id for agent_id, role in roles.items() if role == "werewolf"]
    for agent in agents:
        role = roles.get(agent.agent_id, "villager")
        fellow_wolves = [wolf_id for wolf_id in wolves if wolf_id != agent.agent_id]
        desires = dict(agent.desires_json or {})
        existing = dict(desires.get("werewolf") or {})
        existing.update(
            {
                "role": role,
                "role_label": WEREWOLF_ROLE_LABELS.get(role, role),
                "known_wolves": fellow_wolves if role == "werewolf" else [],
                "revealed_day": day,
                "public_reason": reason,
            }
        )
        existing.setdefault("crisis_notes", [])
        desires["werewolf"] = existing
        agent.desires_json = desires
        if role == "werewolf" and fellow_wolves:
            wolf_text = f" 你知道狼人同伴是：{_names(session, fellow_wolves)}。夜袭需要所有存活狼人选择同一目标；如果意见不一致，今晚不会立刻成功，需要先密会统一目标。"
        elif role == "werewolf":
            wolf_text = " 目前只有你一个狼人，没有狼人同伴；夜里无需密会，直接选择夜袭目标。"
        else:
            wolf_text = ""
        _add_werewolf_memory(session, world, agent, f"第{day}天因{reason}，你知道了村庄里的隐藏身份事实。你的身份是：{WEREWOLF_ROLE_LABELS.get(role, role)}。{wolf_text}", importance=96)
    _seed_public_name_knowledge(session, world, agents)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_day"] = day
    state["role_reveal_reason"] = reason


def sync_werewolf_phase(session: Session, world: World) -> list[int]:
    event_ids: list[int] = []
    if not werewolf_enabled(world):
        return event_ids
    _ensure_werewolf_locations(session, world)
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    if not state.get("roles"):
        event_ids.extend(initialize_werewolf_roles(session, world))
        settings = dict(world.settings_json or {})
        state = dict(settings.get("werewolf_state") or {})
    _ensure_werewolf_secret_defaults(session, world, state)
    settings["werewolf_state"] = state
    world.settings_json = settings
    if state.get("winner"):
        if state.get("final_speeches_complete"):
            world.status = "ended"
        else:
            event_ids.extend(_prepare_werewolf_final_speeches(session, world))
        return event_ids
    day, phase = werewolf_phase(world)
    old_phase = state.get("phase")
    old_day = int(state.get("day") or day)
    if old_phase == phase and old_day == day:
        event_ids.extend(_reconcile_werewolf_phase(session, world, state, day, phase, initialize=False))
        settings = dict(world.settings_json or {})
        settings["werewolf_state"] = state
        world.settings_json = settings
        return event_ids

    if old_phase == "voting":
        event_ids.extend(_resolve_day_vote(session, world, old_day, force=True))
        settings = dict(world.settings_json or {})
        state = dict(settings.get("werewolf_state") or {})
        if state.get("winner"):
            event_ids.extend(_prepare_werewolf_final_speeches(session, world))
            settings["werewolf_state"] = state
            world.settings_json = settings
            return event_ids

    state["day"] = day
    state["phase"] = phase
    event_ids.extend(_reconcile_werewolf_phase(session, world, state, day, phase, initialize=True))

    settings = dict(world.settings_json or {})
    settings["werewolf_state"] = state
    world.settings_json = settings
    event = create_event(
        session,
        world=world,
        event_type="werewolf_phase",
        viewer_text=_phase_viewer_text(world, day, phase, public_revealed=werewolf_publicly_revealed(world)),
        importance=85,
        color_class="important",
        payload={"day": day, "phase": phase, "hide_clock": phase == "discussion"},
    )
    event_ids.append(event.event_id)
    return event_ids


def _ensure_werewolf_locations(session: Session, world: World) -> None:
    for local_id, spec in _WEREWOLF_LOCATION_SPECS.items():
        location_id = world_location_id(world.world_id, local_id)
        location = session.get(Location, location_id)
        neighbors = [world_location_id(world.world_id, item) for item in spec["neighbors"]]
        tools = [str(item) for item in spec["tools"]]
        tags = [str(item) for item in spec["tags"]]
        if not location:
            session.add(
                Location(
                    location_id=location_id,
                    world_id=world.world_id,
                    public_name=_LOCKED_LOCATION_NAMES.get(local_id, local_id),
                    description=_LOCKED_LOCATION_DESCRIPTIONS.get(local_id, ""),
                    neighbors_json=neighbors,
                    available_tools_json=tools,
                    visibility_radius=int(spec["radius"]),
                    tags_json=tags,
                )
            )
            continue
        location.neighbors_json = sorted(set(location.neighbors_json or []) | set(neighbors))
        location.available_tools_json = sorted(set(location.available_tools_json or []) | set(tools))
        location.tags_json = sorted(set(location.tags_json or []) | set(tags))
        if not location.public_name:
            location.public_name = _LOCKED_LOCATION_NAMES.get(local_id, local_id)
        if not location.description:
            location.description = _LOCKED_LOCATION_DESCRIPTIONS.get(local_id, "")

    # Older saved Werewolf worlds may already have a cafeteria from the preset.
    # Keep the new vending-machine edge reciprocal without creating a full modern
    # market or widening the Werewolf tool surface.
    for local_id, spec in _WEREWOLF_LOCATION_SPECS.items():
        location_id = world_location_id(world.world_id, local_id)
        for neighbor_local_id in spec["neighbors"]:
            neighbor = session.get(Location, world_location_id(world.world_id, neighbor_local_id))
            if not neighbor:
                continue
            neighbor.neighbors_json = sorted(set(neighbor.neighbors_json or []) | {location_id})


def _prepare_werewolf_final_speeches(session: Session, world: World) -> list[int]:
    event_ids = _interrupt_scheduled_sleep(session, world, agent_ids=set(_living_agent_ids(session, world)))
    _teleport_alive(session, world, "discussion_hall")
    _stabilize_hosted_phase_players(session, world)
    return event_ids


def _phase_viewer_text(world: World, day: int, phase: str, *, public_revealed: bool) -> str:
    if _is_post_vote_free_activity(world, day, phase):
        return f"第{day}天投票已经结束，18:00到22:00恢复自由活动。"
    if not public_revealed:
        if phase == "night":
            return "夜幕降临，村庄逐渐安静下来，居民们准备休息。"
        return "村庄的一天继续推进，居民们仍把这里当作普通村庄生活。"
    if phase == "morning":
        return f"第{day}天清晨，幸存者在村庄里自由交流，整理昨夜留下的事实。"
    if phase == "voting":
        return f"第{day}天圆桌会议结束，幸存者立刻在18:00公开投票。"
    return f"村庄进入第{day}天的{phase_label(phase)}阶段。"


def _is_post_vote_free_activity(world: World, day: int, phase: str) -> bool:
    if day <= 1 or phase != "morning":
        return False
    start, morning_minutes, discussion_minutes, voting_minutes, night_minutes = _phase_schedule(world)
    cycle_minutes = max(1, morning_minutes + discussion_minutes + voting_minutes + night_minutes)
    base = start + (day - 1) * cycle_minutes
    voting_start = base + morning_minutes + discussion_minutes
    voting_end = voting_start + voting_minutes
    minute = int(world.current_world_time_minutes or 0)
    return voting_start <= minute < voting_end


def _reconcile_werewolf_phase(
    session: Session,
    world: World,
    state: dict[str, Any],
    day: int,
    phase: str,
    *,
    initialize: bool,
) -> list[int]:
    """Keep the hosted Werewolf phase authoritative over free-sim sleep/location state.

    The normal life sim may put everyone to sleep shortly before noon.  A hosted
    Werewolf phase must still convene the public table/vote, otherwise the turn
    runner sees no active agents and jumps over the whole phase.  Reconciliation is
    intentionally run both on phase transitions and on repeated sync calls so old
    saves that already entered a phase with sleeping players can recover.
    """
    event_ids: list[int] = []
    if state.get("winner"):
        if not state.get("final_speeches_complete"):
            event_ids.extend(_prepare_werewolf_final_speeches(session, world))
        return event_ids
    if not werewolf_publicly_revealed(world) and phase in {"discussion", "voting"}:
        return event_ids
    if phase == "discussion":
        event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=set(_living_agent_ids(session, world))))
        _teleport_alive(session, world, "discussion_hall")
        _stabilize_hosted_phase_players(session, world)
        if initialize:
            order = _living_agent_ids(session, world)
            state["speech_order"] = order
            state["current_speaker_index"] = 0
            state.setdefault("speech_counts", {})[str(day)] = {}
            state.setdefault("speech_ended", {})[str(day)] = {}
        # Drop legacy rebuttal windows even for already-entered saves; otherwise one
        # player can get trapped producing “没有提出反驳” forever.
        state.pop("rebuttal_window", None)
        _normalize_discussion_state(session, world, state, day)
    elif phase == "voting":
        event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=set(_living_agent_ids(session, world))))
        _teleport_alive(session, world, "voting_room")
        _stabilize_hosted_phase_players(session, world)
        if initialize:
            state.setdefault("votes", {})[str(day)] = {}
    elif phase == "night":
        roles = state.get("roles") or {}
        if initialize:
            state.setdefault("night_kills", {})[str(day)] = None
            state.setdefault("wolf_kill_nominations", {})[str(day)] = {}
            state.setdefault("wolf_discussions", {})[str(day)] = []
            state.setdefault("wolf_consensus_need_discussion", {})[str(day)] = False
            state.setdefault("guard_protects", {})[str(day)] = {}
        if not werewolf_publicly_revealed(world):
            # Before the first body is found, only wolves know the crisis exists.
            # Other residents sleep as if this were an ordinary village night.
            wolf_ids = set(_living_wolf_ids(session, world, roles))
            if wolf_ids:
                event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=wolf_ids))
            _teleport_unrevealed_wolves(session, world, roles)
            event_ids.extend(_start_werewolf_night_sleepers(session, world, state, day, roles, awake_roles={"werewolf"}))
            return event_ids
        night_actor_ids = {agent_id for agent_id, role in roles.items() if role in NIGHT_ACTION_ROLES}
        if night_actor_ids:
            event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=night_actor_ids))
        _teleport_night_roles(session, world, roles)
        event_ids.extend(_start_werewolf_night_sleepers(session, world, state, day, roles, roles_awake=True))
    elif phase == "morning":
        if _is_post_vote_free_activity(world, day, phase):
            return event_ids
        event_ids.extend(_recover_after_werewolf_night(session, world, state, day))
        event_ids.extend(_announce_werewolf_notice_board(session, world, state, day))
        if state.get("winner"):
            return event_ids
        event_ids.extend(_announce_werewolf_body_found(session, world, state, day))
        if initialize:
            event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=set(_living_agent_ids(session, world))))
            _teleport_alive(session, world, "village_square")
    return event_ids


def _recover_after_werewolf_night(session: Session, world: World, state: dict[str, Any], day: int) -> list[int]:
    """Apply the implicit overnight rest that the Werewolf host represents.

    During night phases the host often advances straight to dawn after role tools
    resolve.  If we leave the ordinary life-sim awake timers untouched, players
    wake up as if they stood awake for fourteen hours and the next round-table is
    swallowed by hunger/fatigue collapse.  Werewolf night should still leave
    people hungry enough to seek breakfast, but not too broken to talk.
    """
    if day <= 1:
        return []
    recovered = dict(state.get("overnight_recovered") or {})
    key = str(day)
    if recovered.get(key):
        return []
    event_ids: list[int] = []
    from app.effects.effect_engine import complete_scheduled_sleep

    for agent in session.execute(
        select(Agent)
        .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
        .order_by(Agent.created_at_world_time, Agent.agent_id)
    ).scalars():
        if _sleep_until_world_time(agent) <= int(world.current_world_time_minutes or 0) and (agent.desires_json or {}).get("sleep_started_world_time") is not None:
            event_ids.extend(complete_scheduled_sleep(session, world, agent))
        _stabilize_werewolf_player(agent, world, minimum_energy=72, minimum_satiety=38, minimum_hydration=38, clear_unconscious=True)
    recovered[key] = True
    state["overnight_recovered"] = recovered
    return event_ids


def _start_werewolf_night_sleepers(
    session: Session,
    world: World,
    state: dict[str, Any],
    day: int,
    roles: dict[str, str],
    *,
    roles_awake: bool = True,
    awake_roles: set[str] | None = None,
) -> list[int]:
    """Put non-role-action players to sleep when the hosted night begins.

    The role actors may still use night abilities, but villagers should not sit awake
    in the log doing nothing.  This creates real sleep schedules/events and prevents
    the visual story of “everyone ignores nighttime”.
    """
    key = str(day)
    started = dict(state.get("night_sleep_started") or {})
    if started.get(key):
        return []
    dormitory_id = world_location_id(world.world_id, "dormitory")
    dormitory = session.get(Location, dormitory_id)
    phase_end = werewolf_current_phase_end_minute(world)
    now = int(world.current_world_time_minutes or 0)
    sleep_until = max(now + 60, int(phase_end or now + DEFAULT_NIGHT_MINUTES))
    event_ids: list[int] = []
    for agent in session.execute(
        select(Agent)
        .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
        .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars():
        role = roles.get(agent.agent_id, "villager")
        if awake_roles is not None and role in awake_roles:
            continue
        if awake_roles is None and roles_awake and role in NIGHT_ACTION_ROLES:
            continue
        if dormitory and agent.location:
            agent.location.location_id = dormitory_id
            agent.location.location = dormitory
            agent.location.arrived_at_world_time = now
        desires = dict(agent.desires_json or {})
        # If they were already sleeping past dawn, do not duplicate the schedule/event.
        try:
            existing_until = int(desires.get("sleep_until_world_time") or 0)
        except (TypeError, ValueError):
            existing_until = 0
        if existing_until > now:
            continue
        desires.update(
            {
                "sleep_until_world_time": sleep_until,
                "sleep_started_world_time": now,
                "sleep_planned_minutes": max(1, sleep_until - now),
                "sleep_requested_minutes": max(1, sleep_until - now),
                "sleep_quality": "werewolf_night",
                "rough_sleep_location_id": None,
            }
        )
        agent.desires_json = desires
        event = create_event(
            session,
            world=world,
            event_type="sleep_start",
            actor_agent_id=agent.agent_id,
            location_id=agent.location.location_id if agent.location else dormitory_id,
            viewer_text=f"{agent.chosen_name} 在夜晚回到宿舍睡下，等待天亮。",
            importance=40,
            color_class="info",
            payload={"day": day, "phase": "night", "werewolf_night_sleep": True, "sleep_until_world_time": sleep_until},
        )
        event_ids.append(event.event_id)
    started[key] = True
    state["night_sleep_started"] = started
    return event_ids


def _scripted_unrevealed_night_attack(session: Session, world: World, state: dict[str, Any], day: int) -> list[int]:
    key = str(day)
    done = dict(state.get("hidden_first_night_attack_done") or {})
    if done.get(key) or (state.get("night_kills") or {}).get(key):
        return []
    roles = dict(state.get("roles") or {})
    living = [agent_id for agent_id in _living_agent_ids(session, world) if roles.get(agent_id) != "werewolf"]
    if not living:
        return []
    rng = random.Random(f"werewolf-hidden-kill:{world.seed}:{world.world_id}:{day}")
    target_id = sorted(living)[rng.randrange(len(living))]
    target = session.get(Agent, target_id)
    if not target:
        return []
    event_ids = _perform_werewolf_night_kill(
        session,
        world,
        state,
        day,
        target,
        hidden=True,
        actor_agent_id=None,
        reason="第一夜未知袭击",
    )
    done[key] = target.agent_id
    state["hidden_first_night_attack_done"] = done
    return event_ids


def _perform_werewolf_night_kill(
    session: Session,
    world: World,
    state: dict[str, Any],
    day: int,
    target: Agent,
    *,
    hidden: bool = False,
    actor_agent_id: str | None = None,
    reason: str = "狼人夜间袭击出局",
) -> list[int]:
    if _is_guarded(state, day, target.agent_id):
        state.setdefault("night_kills", {})[str(day)] = {"target_agent_id": target.agent_id, "blocked": True}
        event = create_event(
            session,
            world=world,
            event_type="werewolf_night_kill_blocked" if not hidden else "werewolf_night_kill_hidden_blocked",
            target_agent_id=target.agent_id,
            location_id=target.location.location_id if target.location else None,
            visibility_scope="public" if not hidden else "observer",
            viewer_text="夜里有人遇袭，但被守护住了，没有人出局。" if not hidden else "夜色里发生了一次未公开的袭击，但没有造成出局。",
            importance=95,
            color_class="warning",
            payload={"day": day, "target_agent_id": target.agent_id, "blocked": True, "agent_facing_locked": hidden},
        )
        _persist_werewolf_state(world, state)
        return [event.event_id]
    kill_location_id = target.location.location_id if target.location else None
    kill_payload = {"target_agent_id": target.agent_id, "blocked": False, "location_id": kill_location_id, "hidden_until_body_found": hidden}
    state.setdefault("night_kills", {})[str(day)] = kill_payload
    _eliminate_agent(target, world, reason)
    if target.dynamic_state:
        apply_delta(target.dynamic_state, health=-100, energy=-100, mood=-20, stress=30)
    corpse = ensure_corpse_for_dead_agent(session, world, target, location_id=kill_location_id, cause="狼人夜间袭击" if not hidden else "未知夜间袭击")
    kill_payload["corpse_id"] = corpse.get("corpse_id")
    state.setdefault("night_kills", {})[str(day)] = kill_payload
    event_ids: list[int] = []
    if hidden:
        event_ids.extend(_wake_unrevealed_witches_for_save(session, world, state, day, target))
    event = create_event(
        session,
        world=world,
        event_type="werewolf_night_kill" if not hidden else "werewolf_night_kill_hidden",
        actor_agent_id=actor_agent_id,
        target_agent_id=target.agent_id,
        location_id=kill_location_id,
        visibility_scope="public" if not hidden else "observer",
        viewer_text=f"夜里过去后，{target.chosen_name}出局了。" if not hidden else "夜色里发生了一起未公开的袭击；居民要到清晨发现尸体后才会知道。",
        importance=100,
        color_class="danger",
        payload={"day": day, "target_agent_id": target.agent_id, "location_id": kill_location_id, "corpse_id": corpse.get("corpse_id"), "agent_facing_locked": hidden},
    )
    event_ids.append(event.event_id)
    _persist_werewolf_state(world, state)
    if not hidden:
        deciding_events = _check_werewolf_win(session, world)
        event_ids.extend(deciding_events)
        if deciding_events:
            state.update(werewolf_state(world))
            _persist_werewolf_state(world, state)
    return event_ids


def _wake_unrevealed_witches_for_save(session: Session, world: World, state: dict[str, Any], day: int, target: Agent) -> list[int]:
    roles = dict(state.get("roles") or {})
    location_id = world_location_id(world.world_id, "seer_room")
    location = session.get(Location, location_id)
    event_ids: list[int] = []
    for witch_id, role in roles.items():
        if role != "witch":
            continue
        witch = session.get(Agent, witch_id)
        if not witch or witch.lifecycle_state == "dead":
            continue
        if witch.location and location:
            witch.location.location_id = location_id
            witch.location.location = location
            witch.location.arrived_at_world_time = world.current_world_time_minutes
        elif location:
            session.add(AgentLocation(agent_id=witch.agent_id, location_id=location_id, location=location, arrived_at_world_time=world.current_world_time_minutes))
        desires = dict(witch.desires_json or {})
        for key in [
            "sleep_until_world_time",
            "sleep_started_world_time",
            "sleep_planned_minutes",
            "sleep_requested_minutes",
            "sleep_quality",
            "rough_sleep_location_id",
        ]:
            desires.pop(key, None)
        desires["awake_since_world_time"] = int(world.current_world_time_minutes or 0)
        witch.desires_json = desires
        _add_werewolf_memory(
            session,
            world,
            witch,
            f"第{day}夜私密事实：你突然知道{target.chosen_name}被未知夜袭命中。你可以用解药救回，也可以不救；这条信息还没有公开。",
            importance=92,
        )
        event = create_event(
            session,
            world=world,
            event_type="werewolf_witch_save_prompt",
            actor_agent_id=witch.agent_id,
            target_agent_id=target.agent_id,
            location_id=witch.location.location_id if witch.location else location_id,
            visibility_scope="private",
            viewer_text=f"{witch.chosen_name}在夜里惊醒，得知一名遇袭者可以被救回。",
            agent_visible_text=f"你知道{target.chosen_name}今晚被未知夜袭命中；可以使用解药救回，也可以保留秘密。",
            importance=75,
            color_class="info",
            payload={"day": day, "target_agent_id": target.agent_id},
        )
        event_ids.append(event.event_id)
    return event_ids


def _persist_werewolf_state(world: World, state: dict[str, Any]) -> None:
    settings = dict(world.settings_json or {})
    settings["werewolf_state"] = state
    world.settings_json = settings


def _existing_werewolf_announcement_event(
    session: Session,
    world: World,
    *,
    event_type: str,
    day: int,
    target_agent_id: str | None = None,
) -> Event | None:
    for event in session.execute(
        select(Event)
        .where(Event.world_id == world.world_id, Event.event_type == event_type)
        .order_by(Event.event_id.asc())
    ).scalars():
        payload = dict(event.payload or {})
        try:
            event_day = int(payload.get("day") or 0)
        except (TypeError, ValueError):
            event_day = 0
        if event_day != day:
            continue
        if target_agent_id is not None and str(payload.get("target_agent_id") or "") != str(target_agent_id):
            continue
        return event
    return None


def _announce_werewolf_body_found(session: Session, world: World, state: dict[str, Any], day: int) -> list[int]:
    """Create the public morning fact that a night-kill victim was found.

    Night kills used to only set a dead lifecycle + hidden-ish kill event.  The
    survivors then had no strong fact in memory, so round-table speeches ignored the
    body.  A hosted Werewolf morning needs an explicit public discovery event.
    """
    if day <= 1:
        return []
    key = str(day)
    announced = dict(state.get("body_found_announced") or {})
    if announced.get(key):
        return []
    previous_key = str(day - 1)
    kill = (state.get("night_kills") or {}).get(previous_key)
    if not isinstance(kill, dict):
        announced[key] = {"none": True}
        state["body_found_announced"] = announced
        _persist_werewolf_state(world, state)
        return []
    if kill.get("blocked"):
        announced[key] = {"blocked": True}
        state["body_found_announced"] = announced
        _persist_werewolf_state(world, state)
        return []
    target_id = str(kill.get("target_agent_id") or "")
    target = session.get(Agent, target_id) if target_id else None
    if not target:
        announced[key] = {"missing_target": target_id}
        state["body_found_announced"] = announced
        _persist_werewolf_state(world, state)
        return []
    existing_event = _existing_werewolf_announcement_event(
        session,
        world,
        event_type="werewolf_body_found",
        day=day,
        target_agent_id=target.agent_id,
    )
    if existing_event:
        announced[key] = {
            "target_agent_id": target.agent_id,
            "event_id": existing_event.event_id,
            "corpse_id": (existing_event.payload or {}).get("corpse_id"),
        }
        state["body_found_announced"] = announced
        _persist_werewolf_state(world, state)
        return []
    announced[key] = {"pending": True, "target_agent_id": target.agent_id}
    state["body_found_announced"] = announced
    _persist_werewolf_state(world, state)
    location_id = str(kill.get("location_id") or "") or (target.location.location_id if target.location else None)
    corpse = ensure_corpse_for_dead_agent(session, world, target, location_id=location_id, cause="狼人夜间袭击")
    location_name = _location_name(session, location_id)
    if not werewolf_publicly_revealed(world):
        _reveal_werewolf_to_agents(session, world, state, day=day, reason=f"发现{target.chosen_name}的尸体")
    event = create_event(
        session,
        world=world,
        event_type="werewolf_body_found",
        target_agent_id=target.agent_id,
        location_id=location_id,
        viewer_text=f"清晨，幸存者发现{target.chosen_name}昨夜遭到狼人袭击出局，遗体在{location_name}。这件事成为今天圆桌必须讨论的核心线索。",
        importance=100,
        color_class="danger",
        payload={
            "day": day,
            "night": day - 1,
            "target_agent_id": target.agent_id,
            "location_id": location_id,
            "corpse_id": corpse.get("corpse_id"),
            "must_discuss": True,
        },
    )
    for agent_id in _living_agent_ids(session, world):
        observer = session.get(Agent, agent_id)
        if observer:
            _add_werewolf_memory(
                session,
                world,
                observer,
                f"第{day}天早晨公开事实：{target.chosen_name}昨夜遭到狼人袭击出局，遗体在{location_name}；今天圆桌必须讨论这具尸体、昨夜谁可能动手、以及之后的投票。",
                importance=95,
            )
    announced[key] = {"target_agent_id": target.agent_id, "event_id": event.event_id, "corpse_id": corpse.get("corpse_id")}
    state["body_found_announced"] = announced
    _persist_werewolf_state(world, state)
    return [event.event_id] + _check_werewolf_win(session, world)


def _announce_werewolf_notice_board(session: Session, world: World, state: dict[str, Any], day: int) -> list[int]:
    if day <= 1:
        return []
    key = str(day)
    announced = dict(state.get("wolf_notice_announced") or {})
    if announced.get(key):
        return []
    if not werewolf_publicly_revealed(world) and not _previous_night_has_unblocked_kill(state, day):
        announced[key] = {"no_public_death": True}
        state["wolf_notice_announced"] = announced
        _persist_werewolf_state(world, state)
        return []
    roles = dict(state.get("roles") or {})
    living_wolves = _living_wolf_ids(session, world, roles)
    if not living_wolves:
        announced[key] = {"wolves_alive": False}
        state["wolf_notice_announced"] = announced
        _persist_werewolf_state(world, state)
        event_ids = _check_werewolf_win(session, world)
        state.clear()
        state.update(werewolf_state(world))
        return event_ids

    existing_event = _existing_werewolf_announcement_event(
        session,
        world,
        event_type="werewolf_notice_board",
        day=day,
    )
    if existing_event:
        announced[key] = {"wolves_alive": True, "event_id": existing_event.event_id, "wolf_count": len(living_wolves)}
        state["wolf_notice_announced"] = announced
        _persist_werewolf_state(world, state)
        return []
    announced[key] = {"pending": True, "wolves_alive": True, "wolf_count": len(living_wolves)}
    state["wolf_notice_announced"] = announced
    _persist_werewolf_state(world, state)

    if not werewolf_publicly_revealed(world):
        _reveal_werewolf_to_agents(session, world, state, day=day, reason="村庄广场告示牌出现“狼人存在于村中”的血红字")

    location_id = world_location_id(world.world_id, "village_square")
    _seed_opening_notice_board(world)
    event = create_event(
        session,
        world=world,
        event_type="werewolf_notice_board",
        location_id=location_id,
        viewer_text="清晨，村庄广场告示牌上出现血红字：狼人存在于村中。",
        importance=100,
        color_class="danger",
        payload={"day": day, "wolves_alive": True, "wolf_count": len(living_wolves), "must_discuss": True},
    )
    for agent_id in _living_agent_ids(session, world):
        observer = session.get(Agent, agent_id)
        if observer:
            _add_werewolf_memory(
                session,
                world,
                observer,
                f"第{day}天清晨公开事实：村庄广场告示牌上出现血红字：狼人存在于村中。",
                importance=96,
            )
    announced[key] = {"wolves_alive": True, "event_id": event.event_id, "wolf_count": len(living_wolves)}
    state["wolf_notice_announced"] = announced
    _persist_werewolf_state(world, state)
    return [event.event_id]


def _previous_night_has_unblocked_kill(state: dict[str, Any], day: int) -> bool:
    kill = (state.get("night_kills") or {}).get(str(day - 1))
    return isinstance(kill, dict) and bool(kill.get("target_agent_id")) and not bool(kill.get("blocked"))


def _saveable_night_kill(state: dict[str, Any], day: int) -> dict[str, Any] | None:
    kill = (state.get("night_kills") or {}).get(str(day))
    if isinstance(kill, dict) and kill.get("target_agent_id") and not kill.get("blocked"):
        return dict(kill)
    return None


def _latest_revealable_witch_saved_attack(state: dict[str, Any], day: int, phase: str, actor_agent_id: str) -> dict[str, Any] | None:
    candidate_nights = [day - 1] if phase == "morning" else []
    if phase == "night":
        candidate_nights.insert(0, day)
    reveals = state.get("witch_saved_attack_reveals") if isinstance(state.get("witch_saved_attack_reveals"), dict) else {}
    for night in candidate_nights:
        if night <= 0:
            continue
        night_key = str(night)
        if night_key in reveals:
            continue
        kill = (state.get("night_kills") or {}).get(night_key)
        if not isinstance(kill, dict) or not kill.get("saved"):
            continue
        if str(kill.get("saved_by_agent_id") or "") != str(actor_agent_id):
            continue
        return {**dict(kill), "night": night}
    return None


def _location_name(session: Session, location_id: str | None) -> str:
    if not location_id:
        return "未知地点"
    location = session.get(Location, location_id)
    return location.public_name if location and location.public_name else "未知地点"


def _record_public_werewolf_speech_memory(session: Session, world: World, actor: Agent, speech: str, day: int) -> None:
    text = f"第{day}天圆桌发言：{actor.chosen_name}说：{speech}"
    for agent_id in _living_agent_ids(session, world):
        observer = session.get(Agent, agent_id)
        if observer:
            _add_werewolf_memory(session, world, observer, text, importance=62)


def _stabilize_hosted_phase_players(session: Session, world: World) -> None:
    for agent in session.execute(
        select(Agent)
        .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
        .order_by(Agent.created_at_world_time, Agent.agent_id)
    ).scalars():
        _stabilize_werewolf_player(agent, world, minimum_energy=42, minimum_satiety=25, minimum_hydration=25, clear_unconscious=True)


def _stabilize_werewolf_player(
    agent: Agent,
    world: World,
    *,
    minimum_energy: float,
    minimum_satiety: float,
    minimum_hydration: float,
    clear_unconscious: bool,
) -> None:
    state = agent.dynamic_state
    if not state:
        return
    state.energy = clamp(max(float(state.energy or 0), minimum_energy), 0, 100)
    state.satiety = clamp(max(float(state.satiety or 0), minimum_satiety), 0, 100)
    state.hydration = clamp(max(float(state.hydration or 0), minimum_hydration), 0, 100)
    state.health = clamp(max(float(state.health or 0), 35), 0, 100)
    state.zero_energy_since = None if state.energy > 0 else state.zero_energy_since
    state.zero_satiety_since = None if state.satiety > 0 else state.zero_satiety_since
    state.zero_hydration_since = None if state.hydration > 0 else state.zero_hydration_since
    state.last_decay_world_time = int(world.current_world_time_minutes or 0)
    profile = profile_for_agent(agent)
    recompute_mood(
        state,
        mood_center=float(profile["mood_center"]),
        mood_scale=float(profile["mood_scale"]),
        stress_coef=float(profile["stress_coef"]),
        survival_penalty_scale=float(profile["survival_penalty_scale"]),
        include_survival_needs=True,
    )
    desires = dict(agent.desires_json or {})
    desires["awake_since_world_time"] = int(world.current_world_time_minutes or 0)
    for key in [
        "sleep_until_world_time",
        "sleep_started_world_time",
        "sleep_planned_minutes",
        "sleep_requested_minutes",
        "sleep_quality",
        "rough_sleep_location_id",
    ]:
        desires.pop(key, None)
    if clear_unconscious:
        desires.pop("unconscious_until_world_time", None)
        desires.pop("unconscious_started_world_time", None)
        if agent.lifecycle_state == "critical" and state.health >= 35 and state.energy >= minimum_energy:
            agent.lifecycle_state = "alive"
            state.critical_reason = None
    agent.desires_json = desires


def _interrupt_scheduled_sleep(session: Session, world: World, *, agent_ids: set[str] | None = None) -> list[int]:
    rows = session.execute(
        select(Agent)
        .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
        .order_by(Agent.created_at_world_time, Agent.agent_id)
    ).scalars()
    event_ids: list[int] = []
    for agent in rows:
        if agent_ids is not None and agent.agent_id not in agent_ids:
            continue
        if _sleep_until_world_time(agent) <= int(world.current_world_time_minutes or 0):
            continue
        from app.effects.effect_engine import complete_scheduled_sleep

        event_ids.extend(complete_scheduled_sleep(session, world, agent, interrupted=True))
    return event_ids


def _sleep_until_world_time(agent: Agent) -> int:
    try:
        return int((agent.desires_json or {}).get("sleep_until_world_time") or 0)
    except (TypeError, ValueError):
        return 0


def _teleport_alive(session: Session, world: World, local_location_id: str) -> None:
    location_id = world_location_id(world.world_id, local_location_id)
    location = session.get(Location, location_id)
    if not location:
        return
    agents = session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")).scalars()
    for agent in agents:
        if not agent.location:
            session.add(AgentLocation(agent_id=agent.agent_id, location_id=location_id, location=location, arrived_at_world_time=world.current_world_time_minutes))
        else:
            agent.location.location_id = location_id
            agent.location.location = location
            agent.location.arrived_at_world_time = world.current_world_time_minutes


def _teleport_night_roles(session: Session, world: World, roles: dict[str, str]) -> None:
    for agent in session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")).scalars():
        role = roles.get(agent.agent_id, "villager")
        if role == "werewolf":
            local = "wolf_den"
        elif role == "seer":
            local = "seer_room"
        elif role == "coroner":
            local = "morgue"
        elif role == "guard":
            local = "guard_room"
        elif role == "witch":
            local = "seer_room"
        elif role == "medium":
            local = "morgue"
        else:
            local = "dormitory"
        location_id = world_location_id(world.world_id, local)
        location = session.get(Location, location_id)
        if agent.location and location:
            agent.location.location_id = location_id
            agent.location.location = location
            agent.location.arrived_at_world_time = world.current_world_time_minutes


def _teleport_unrevealed_wolves(session: Session, world: World, roles: dict[str, str]) -> None:
    location_id = world_location_id(world.world_id, "wolf_den")
    location = session.get(Location, location_id)
    if not location:
        return
    for agent in session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")).scalars():
        if roles.get(agent.agent_id) != "werewolf" or not agent.location:
            continue
        agent.location.location_id = location_id
        agent.location.location = location
        agent.location.arrived_at_world_time = world.current_world_time_minutes


def werewolf_menu_tool_names(session: Session, world: World, agent: Agent) -> set[str]:
    if not werewolf_enabled(world) or agent.lifecycle_state == "dead":
        return set()
    state = werewolf_state(world)
    if state.get("winner"):
        return set()
    roles = state.get("roles") or {}
    role = roles.get(agent.agent_id) or (agent.desires_json or {}).get("werewolf", {}).get("role") or "villager"
    day, phase = werewolf_phase(world)
    if werewolf_publicly_revealed(world):
        _ensure_public_revealed_agent_state(session, world, state, day=day, reason=str(state.get("role_reveal_reason") or "公开危机事实"))
    names: set[str] = set()
    if not werewolf_publicly_revealed(world):
        if role == "werewolf" and phase == "night":
            day_key = str(day)
            if not ((state.get("night_kills") or {}).get(day_key)):
                living_wolves = _living_wolf_ids(session, world, roles)
                if len(living_wolves) >= 2 and (
                    _wolf_consensus_needs_discussion(state, day)
                    or not _all_living_wolves_discussed(state, day, living_wolves)
                ):
                    if agent.agent_id not in _wolf_discussion_speakers(state, day):
                        names.add("werewolf_wolf_discuss")
                    return names
                names.add("werewolf_kill_by_name")
                if len(living_wolves) >= 2 and _wolf_discussion_count(state, day, agent.agent_id) < _wolf_discussion_limit(world):
                    names.add("werewolf_wolf_discuss")
        elif role == "witch":
            if phase == "night" and _saveable_night_kill(state, day):
                witch_saves = ((state.get("witch_saves") or {}).get(str(day))) or {}
                if agent.agent_id not in witch_saves:
                    names.add("werewolf_witch_save_latest")
            if phase == "morning" and _latest_revealable_witch_saved_attack(state, day, phase, agent.agent_id):
                names.add("werewolf_witch_reveal_saved_attack")
        return names
    if phase in {"morning", "voting"}:
        names.add("werewolf_record_reasoning")
    if phase == "discussion":
        # Real Werewolf video games do not ask every player to pick a separate
        # "end speech" or "skip rebuttal" action.  The host grants one speaking
        # turn to each living player, then automatically rotates.
        if _current_speaker_id(session, world, state, day) == agent.agent_id and werewolf_speech_count(world, agent.agent_id, day) < _speech_limit(world):
            names.add("werewolf_speak")
    elif phase == "voting":
        names.update({"werewolf_vote_by_name", "werewolf_review_vote_history"})
    elif phase == "night":
        day_key = str(day)
        if role == "werewolf":
            if not ((state.get("night_kills") or {}).get(day_key)):
                living_wolves = _living_wolf_ids(session, world, roles)
                if len(living_wolves) >= 2 and (
                    _wolf_consensus_needs_discussion(state, day)
                    or not _all_living_wolves_discussed(state, day, living_wolves)
                ):
                    if agent.agent_id not in _wolf_discussion_speakers(state, day):
                        names.add("werewolf_wolf_discuss")
                    return names
                names.add("werewolf_kill_by_name")
                if len(living_wolves) >= 2 and _wolf_discussion_count(state, day, agent.agent_id) < _wolf_discussion_limit(world):
                    names.add("werewolf_wolf_discuss")
        elif role == "seer":
            if agent.agent_id not in (((state.get("seer_checks") or {}).get(day_key)) or {}):
                names.add("werewolf_seer_check_by_name")
        elif role == "coroner":
            if agent.agent_id not in (((state.get("coroner_reports") or {}).get(day_key)) or {}):
                names.add("werewolf_coroner_check_latest")
        elif role == "guard":
            if agent.agent_id not in (((state.get("guard_protects") or {}).get(day_key)) or {}):
                names.add("werewolf_guard_protect_by_name")
        elif role == "witch":
            witch_saves = ((state.get("witch_saves") or {}).get(day_key)) or {}
            witch_poisons = ((state.get("witch_poisons") or {}).get(day_key)) or {}
            kill = ((state.get("night_kills") or {}).get(day_key)) or {}
            if agent.agent_id not in witch_saves and isinstance(kill, dict) and kill.get("target_agent_id") and not kill.get("blocked"):
                names.add("werewolf_witch_save_latest")
            if agent.agent_id not in witch_poisons:
                names.add("werewolf_witch_poison_by_name")
        elif role == "medium":
            if agent.agent_id not in (((state.get("medium_reports") or {}).get(day_key)) or {}):
                names.add("werewolf_medium_check_latest")
    if phase in {"morning", "discussion", "voting"}:
        if role == "hunter" and agent.agent_id not in (state.get("hunter_shots") or {}):
            names.add("werewolf_hunter_shoot_by_name")
        if role == "idiot" and agent.agent_id not in (state.get("idiot_reveals") or {}):
            names.add("werewolf_idiot_reveal_self")
    return names


def werewolf_current_speaker_id(session: Session, world: World) -> str | None:
    if not werewolf_enabled(world) or not werewolf_publicly_revealed(world):
        return None
    state = werewolf_state(world)
    if state.get("winner"):
        return None
    day, phase = werewolf_phase(world)
    if phase != "discussion":
        return None
    return _current_speaker_id(session, world, state, day)


def werewolf_current_discussion_actor_id(session: Session, world: World) -> str | None:
    if not werewolf_enabled(world) or not werewolf_publicly_revealed(world):
        return None
    state = werewolf_state(world)
    day, phase = werewolf_phase(world)
    if phase != "discussion" or state.get("winner"):
        return None
    # Discussion is a simple hosted queue: current speaker only.  Legacy rebuttal
    # windows are deliberately ignored and are cleared by phase reconciliation.
    return _current_speaker_id(session, world, state, day)


def _active_rebuttal_window(state: dict[str, Any], day: int) -> dict[str, Any] | None:
    window = state.get("rebuttal_window")
    if not isinstance(window, dict):
        return None
    try:
        if int(window.get("day")) != int(day):
            return None
    except (TypeError, ValueError):
        return None
    return window


def _rebuttal_turn_actor_id(session: Session, world: World, state: dict[str, Any], day: int) -> str | None:
    window = _active_rebuttal_window(state, day)
    if not window:
        return None
    if window.get("mode") == "debate":
        turn_id = str(window.get("turn_agent_id") or "")
        agent = session.get(Agent, turn_id) if turn_id else None
        return turn_id if agent and agent.lifecycle_state != "dead" else None
    candidates = list(window.get("candidate_ids") or [])
    try:
        index = int(window.get("index") or 0)
    except (TypeError, ValueError):
        index = 0
    while index < len(candidates):
        candidate_id = str(candidates[index])
        agent = session.get(Agent, candidate_id)
        if agent and agent.lifecycle_state != "dead":
            window["index"] = index
            return candidate_id
        index += 1
    state.pop("rebuttal_window", None)
    _after_rebuttal_window_finished(session, world, state, day)
    return None


def _open_rebuttal_window(session: Session, world: World, state: dict[str, Any], day: int, speaker_id: str) -> None:
    candidates = [agent_id for agent_id in _living_agent_ids(session, world) if agent_id != speaker_id]
    if not candidates:
        _after_rebuttal_window_finished(session, world, state, day)
        return
    state["rebuttal_window"] = {
        "day": day,
        "speaker_id": speaker_id,
        "candidate_ids": candidates,
        "index": 0,
        "mode": "ask",
        "reply_count": 0,
        "max_replies": _rebuttal_reply_limit(world),
    }


def _advance_rebuttal_candidate(session: Session, world: World, state: dict[str, Any], day: int) -> None:
    window = _active_rebuttal_window(state, day)
    if not window:
        _after_rebuttal_window_finished(session, world, state, day)
        return
    window["mode"] = "ask"
    window["reply_count"] = 0
    window.pop("rebutter_id", None)
    window.pop("turn_agent_id", None)
    try:
        window["index"] = int(window.get("index") or 0) + 1
    except (TypeError, ValueError):
        window["index"] = 1
    candidates = list(window.get("candidate_ids") or [])
    if int(window.get("index") or 0) >= len(candidates):
        state.pop("rebuttal_window", None)
        _after_rebuttal_window_finished(session, world, state, day)


def _after_rebuttal_window_finished(session: Session, world: World, state: dict[str, Any], day: int) -> None:
    speaker_id = _current_speaker_id(session, world, state, day)
    if not speaker_id:
        return
    counts = ((state.get("speech_counts") or {}).get(str(day)) or {})
    if int(counts.get(speaker_id) or 0) >= _speech_limit(world):
        ended_all = dict(state.get("speech_ended") or {})
        ended = dict(ended_all.get(str(day)) or {})
        ended[speaker_id] = True
        ended_all[str(day)] = ended
        state["speech_ended"] = ended_all
        _advance_discussion_speaker(session, world, state, day)


def werewolf_speech_count(world: World, agent_id: str, day: int | None = None) -> int:
    state = werewolf_state(world)
    if day is None:
        day, _phase = werewolf_phase(world)
    counts = ((state.get("speech_counts") or {}).get(str(day)) or {})
    try:
        return int(counts.get(agent_id) or 0)
    except (TypeError, ValueError):
        return 0


def _wolf_consensus_needs_discussion(state: dict[str, Any], day: int) -> bool:
    flags = state.get("wolf_consensus_need_discussion") or {}
    return bool(isinstance(flags, dict) and flags.get(str(day)))


def _set_wolf_consensus_needs_discussion(state: dict[str, Any], day: int, value: bool) -> None:
    flags = dict(state.get("wolf_consensus_need_discussion") or {})
    flags[str(day)] = bool(value)
    state["wolf_consensus_need_discussion"] = flags


def _wolf_discussion_speakers(state: dict[str, Any], day: int) -> set[str]:
    discussions = ((state.get("wolf_discussions") or {}).get(str(day)) or [])
    if not isinstance(discussions, list):
        return set()
    return {str(item.get("speaker_agent_id")) for item in discussions if isinstance(item, dict) and item.get("speaker_agent_id")}


def _all_living_wolves_discussed(state: dict[str, Any], day: int, living_wolves: list[str]) -> bool:
    if len(living_wolves) < 2:
        return True
    speakers = _wolf_discussion_speakers(state, day)
    return all(wolf_id in speakers for wolf_id in living_wolves)


def _wolf_nomination_summary(session: Session, nominations: dict[str, str]) -> str:
    if not nominations:
        return "暂无狼人提出目标。"
    parts = []
    for wolf_id, target_id in sorted(nominations.items()):
        wolf = session.get(Agent, wolf_id)
        target = session.get(Agent, target_id)
        parts.append(f"{wolf.chosen_name if wolf else wolf_id}→{target.chosen_name if target else target_id}")
    return "；".join(parts)


def _add_wolf_pack_memory(session: Session, world: World, state: dict[str, Any], text: str, *, importance: int = 75) -> None:
    roles = state.get("roles") or {}
    for wolf_id in _living_wolf_ids(session, world, roles):
        wolf = session.get(Agent, wolf_id)
        if wolf:
            _add_werewolf_memory(session, world, wolf, text, importance=importance)


def _wolf_discussion_count(state: dict[str, Any], day: int, agent_id: str) -> int:
    discussions = ((state.get("wolf_discussions") or {}).get(str(day)) or [])
    if not isinstance(discussions, list):
        return 0
    return sum(1 for item in discussions if isinstance(item, dict) and item.get("speaker_agent_id") == agent_id)


def _wolf_discussion_limit(world: World) -> int:
    params = ((world.settings_json or {}).get("worldview_rule_parameters") or {}).get("werewolf") or {}
    try:
        return max(0, int(params.get("wolf_discussion_limit_per_night") or 1))
    except (TypeError, ValueError):
        return 1


def werewolf_speech_limit(world: World) -> int:
    return _speech_limit(world)


def werewolf_tool_menu_allowed(session: Session, world: World, agent: Agent, tool_name: str, location: Location | None = None) -> bool:
    return _canonical_tool_name(tool_name) in werewolf_menu_tool_names(session, world, agent)


def werewolf_tool_allowed(session: Session, world: World, agent: Agent, tool_name: str) -> tuple[bool, str, str]:
    tool_name = _canonical_tool_name(tool_name)
    if not tool_name.startswith("werewolf_"):
        return True, "", ""
    if not werewolf_enabled(world):
        return False, "werewolf_disabled", "当前世界没有启用村庄危机规则。"
    state = werewolf_state(world)
    if state.get("winner"):
        return False, "werewolf_ended", "这场村庄危机已经结束。"
    roles = state.get("roles") or {}
    role = roles.get(agent.agent_id) or (agent.desires_json or {}).get("werewolf", {}).get("role") or "villager"
    day, phase = werewolf_phase(world)
    public_revealed = werewolf_publicly_revealed(world)
    if public_revealed:
        _ensure_public_revealed_agent_state(session, world, state, day=day, reason=str(state.get("role_reveal_reason") or "公开危机事实"))
    if not public_revealed:
        if role == "werewolf" and phase == "night" and tool_name in {"werewolf_wolf_discuss", "werewolf_kill_by_name"}:
            pass
        elif role == "witch" and phase == "night" and tool_name == "werewolf_witch_save_latest" and _saveable_night_kill(state, day):
            pass
        elif role == "witch" and phase == "morning" and tool_name == "werewolf_witch_reveal_saved_attack" and _latest_revealable_witch_saved_attack(state, day, phase, agent.agent_id):
            pass
        else:
            return False, "werewolf_not_revealed", "当前居民还不知道隐藏身份事实，不能使用这些夜间或会议行动。"
    if tool_name == "werewolf_record_reasoning":
        if phase not in {"morning", "voting"}:
            return False, "werewolf_reasoning_phase_blocked", "记录推理只在自由交流或投票阶段开放；圆桌发言和夜间能力阶段要优先完成主持流程。"
        return True, "", ""
    if tool_name == "werewolf_summarize_clues":
        if phase not in {"discussion", "voting"}:
            return False, "werewolf_phase_blocked", "只有讨论和投票阶段适合整理公开线索。"
        return True, "", ""
    if tool_name in {"werewolf_end_speech", "werewolf_rebut", "werewolf_skip_rebuttal", "werewolf_reply_rebuttal", "werewolf_drop_debate"}:
        return False, "werewolf_legacy_discussion_tool", "当前圆桌已改为主持自动轮转：轮到你时只需要圆桌发言一次，系统会自动交给下一个人。"
    if tool_name == "werewolf_speak":
        if phase != "discussion":
            return False, "werewolf_phase_blocked", "现在不是圆桌发言阶段。"
        if _current_speaker_id(session, world, state, day) != agent.agent_id:
            return False, "werewolf_not_current_speaker", "还没有轮到你发言。"
        count = werewolf_speech_count(world, agent.agent_id, day)
        if count >= _speech_limit(world):
            return False, "werewolf_speech_limit", "你本轮已经完成发言，主持会自动交给下一个人。"
        return True, "", ""
    if tool_name in {"werewolf_vote_by_name", "werewolf_review_vote_history", "werewolf_vote_no_execution"}:
        if phase != "voting":
            return False, "werewolf_phase_blocked", "投票和票型分析只能在公开投票阶段使用。"
        if tool_name == "werewolf_vote_no_execution":
            return False, "werewolf_no_execution_removed", "当前规则不再使用无人出局投票；第2天起必须投票给一名幸存者。"
        if day == 1:
            return False, "werewolf_first_day_no_vote", "第1天只有自由交流和第一夜，没有公开投票。"
        return True, "", ""
    if tool_name in {"werewolf_wolf_discuss", "werewolf_kill_by_name"}:
        if phase != "night":
            return False, "werewolf_phase_blocked", "狼人能力只能在夜间使用。"
        if role != "werewolf":
            return False, "werewolf_role_blocked", "只有狼人能使用这个夜间能力。"
        if tool_name == "werewolf_wolf_discuss":
            living_wolves = _living_wolf_ids(session, world, roles)
            if len(living_wolves) < 2:
                return False, "werewolf_single_wolf_no_discussion", "今晚只有你一个狼人，不会召开狼人密会；请直接选择夜袭目标。"
            if _wolf_consensus_needs_discussion(state, day):
                if agent.agent_id in _wolf_discussion_speakers(state, day):
                    return False, "werewolf_wolf_discussion_done", "你已经参与了本轮统一目标讨论，请等待其他狼人发言或重新表态。"
            elif not _all_living_wolves_discussed(state, day, living_wolves):
                if agent.agent_id in _wolf_discussion_speakers(state, day):
                    return False, "werewolf_wolf_discussion_done", "你已经完成今晚的狼人密会发言，请等待其他狼人先发言。"
            elif _wolf_discussion_count(state, day, agent.agent_id) >= _wolf_discussion_limit(world):
                return False, "werewolf_wolf_discussion_done", "你今晚已经完成狼人密会发言，请推动夜袭结算。"
        if tool_name == "werewolf_kill_by_name":
            if ((state.get("night_kills") or {}).get(str(day))):
                return False, "werewolf_night_kill_used", "今晚已经结算过夜袭，不能再次夜袭。"
            living_wolves = _living_wolf_ids(session, world, roles)
            if len(living_wolves) >= 2 and not _all_living_wolves_discussed(state, day, living_wolves):
                return False, "werewolf_discussion_required", "多名狼人必须先完成一次狼人密会，再选择夜袭目标。"
            if _wolf_consensus_needs_discussion(state, day):
                return False, "werewolf_consensus_discussion_required", "狼人刚才意见不一致，所有狼人需要先密会并统一目标，不能继续机械重复提名。"
        return True, "", ""
    if tool_name == "werewolf_seer_check_by_name":
        if phase != "night" or role != "seer":
            return False, "werewolf_role_blocked", "预言家查验只能由预言家在夜间使用。"
        checks = ((state.get("seer_checks") or {}).get(str(day)) or {})
        if agent.agent_id in checks:
            return False, "werewolf_once_per_night", "今晚已经查验过了。"
        return True, "", ""
    if tool_name == "werewolf_coroner_check_latest":
        if phase != "night" or role != "coroner":
            return False, "werewolf_role_blocked", "验尸官只能在夜间整理死亡线索。"
        reports = ((state.get("coroner_reports") or {}).get(str(day)) or {})
        if agent.agent_id in reports:
            return False, "werewolf_once_per_night", "今晚已经整理过死亡线索了。"
        return True, "", ""
    if tool_name == "werewolf_guard_protect_by_name":
        if phase != "night" or role != "guard":
            return False, "werewolf_role_blocked", "守卫只能在夜间守护一名幸存者。"
        protects = ((state.get("guard_protects") or {}).get(str(day)) or {})
        if agent.agent_id in protects:
            return False, "werewolf_once_per_night", "今晚已经守护过了。"
        return True, "", ""
    if tool_name in {"werewolf_witch_save_latest", "werewolf_witch_poison_by_name"}:
        if phase != "night" or role != "witch":
            return False, "werewolf_role_blocked", "女巫能力只能由女巫在夜间使用。"
        day_key = str(day)
        if tool_name == "werewolf_witch_save_latest":
            saves = ((state.get("witch_saves") or {}).get(day_key)) or {}
            if agent.agent_id in saves:
                return False, "werewolf_once_per_night", "今晚已经使用过解药。"
            kill = ((state.get("night_kills") or {}).get(day_key)) or {}
            if not isinstance(kill, dict) or not kill.get("target_agent_id") or kill.get("blocked"):
                return False, "werewolf_no_save_target", "今晚没有可救的夜间遇袭者。"
        else:
            poisons = ((state.get("witch_poisons") or {}).get(day_key)) or {}
            if agent.agent_id in poisons:
                return False, "werewolf_once_per_night", "今晚已经使用过毒药。"
        return True, "", ""
    if tool_name == "werewolf_witch_reveal_saved_attack":
        if phase != "morning" or role != "witch":
            return False, "werewolf_role_blocked", "女巫只能在救人后的清晨选择是否公开昨夜夜袭事实。"
        if not _latest_revealable_witch_saved_attack(state, day, phase, agent.agent_id):
            return False, "werewolf_no_saved_attack", "你没有尚未公开的救人夜袭事实。"
        return True, "", ""
    if tool_name == "werewolf_medium_check_latest":
        if phase != "night" or role != "medium":
            return False, "werewolf_role_blocked", "灵媒只能在夜间查看最近死者线索。"
        reports = ((state.get("medium_reports") or {}).get(str(day)) or {})
        if agent.agent_id in reports:
            return False, "werewolf_once_per_night", "今晚已经通灵过了。"
        return True, "", ""
    if tool_name == "werewolf_hunter_shoot_by_name":
        if phase not in {"morning", "discussion", "voting"} or role != "hunter":
            return False, "werewolf_role_blocked", "猎人只能在白天公开危机阶段开枪。"
        if agent.agent_id in (state.get("hunter_shots") or {}):
            return False, "werewolf_once_per_game", "你已经开过枪了。"
        return True, "", ""
    if tool_name == "werewolf_idiot_reveal_self":
        if phase not in {"morning", "discussion", "voting"} or role != "idiot":
            return False, "werewolf_role_blocked", "白痴只能在白天公开危机阶段亮明身份。"
        if agent.agent_id in (state.get("idiot_reveals") or {}):
            return False, "werewolf_once_per_game", "你已经亮明过身份了。"
        return True, "", ""
    return True, "", ""


def validate_werewolf_tool(session: Session, world: World, actor: Agent, tool_name: str, target: Agent | None = None) -> tuple[bool, str, str]:
    tool_name = _canonical_tool_name(tool_name)
    ok, reason, message = werewolf_tool_allowed(session, world, actor, tool_name)
    if not ok:
        return ok, reason, message
    state = werewolf_state(world)
    roles = state.get("roles") or {}
    if tool_name in {"werewolf_record_reasoning", "werewolf_vote_by_name", "werewolf_kill_by_name", "werewolf_seer_check_by_name", "werewolf_guard_protect_by_name", "werewolf_witch_poison_by_name", "werewolf_hunter_shoot_by_name"}:
        if target is None:
            return False, "missing_known_name", "这个危机行动需要一个已知姓名目标，请从菜单里选择带姓名的行动。"
        if target.lifecycle_state == "dead":
            return False, "target_dead", "目标已经出局，不能再作为本次行动目标。"
        if target.agent_id == actor.agent_id and tool_name in {"werewolf_vote_by_name", "werewolf_kill_by_name", "werewolf_seer_check_by_name", "werewolf_witch_poison_by_name", "werewolf_hunter_shoot_by_name"}:
            return False, "target_self_blocked", "这个危机行动不能选择自己作为目标。"
    if tool_name == "werewolf_kill_by_name" and target is not None and roles.get(target.agent_id) == "werewolf":
        return False, "werewolf_target_is_wolf", "狼人夜袭不能选择狼人同伴。"
    return True, "", ""


def handle_werewolf_tool(
    session: Session,
    world: World,
    actor: Agent,
    tool_name: str,
    params: dict[str, Any],
    target: Agent | None = None,
    location_id: str | None = None,
    state_delta: dict[str, Any] | None = None,
) -> list[int]:
    del location_id, state_delta
    tool_name = _canonical_tool_name(tool_name)
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    day, phase = werewolf_phase(world)
    event_ids: list[int] = []

    if tool_name == "werewolf_record_reasoning" and target:
        content = str(params.get("content") or params.get("speech") or params.get("note") or "").strip()
        if not content:
            event = create_event(
                session,
                world=world,
                event_type="tool_failed",
                actor_agent_id=actor.agent_id,
                location_id=actor.location.location_id if actor.location else None,
                viewer_text=f"{actor.chosen_name}没有写下具体推理。",
                agent_visible_text="记录推理需要写出具体身份判断和理由；如果要删除旧推理，正文写“删除”。",
                importance=10,
                color_class="warning",
                payload={"llm_feedback": "记录推理需要具体正文。"},
                no_state_changed=True,
            )
            return [event.event_id]
        changed, message = _upsert_werewolf_reasoning(session, world, actor, target, content)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_reasoning_memory",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}更新了关于{target.chosen_name}的身份推理。" if changed else f"{actor.chosen_name}尝试整理关于{target.chosen_name}的身份推理。",
            agent_visible_text=message,
            importance=45,
            color_class="info",
            payload={"day": day, "phase": phase, "target_agent_id": target.agent_id, "changed": changed},
        )
        return [event.event_id]

    if tool_name == "werewolf_summarize_clues":
        content = str(params.get("content") or params.get("speech") or params.get("note") or "").strip()
        if not content:
            event = create_event(
                session,
                world=world,
                event_type="tool_failed",
                actor_agent_id=actor.agent_id,
                location_id=actor.location.location_id if actor.location else None,
                viewer_text=f"{actor.chosen_name}没有整理出具体线索。",
                agent_visible_text="整理线索需要由 LLM 写出具体正文；系统不会补默认文本。",
                importance=10,
                color_class="warning",
                payload={"llm_feedback": "整理线索需要具体正文。"},
                no_state_changed=True,
            )
            return [event.event_id]
        _add_werewolf_memory(session, world, actor, f"第{day}天线索整理：{content}", importance=65)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_clue_summary",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}整理了自己的危机线索。",
            importance=45,
            color_class="info",
            payload={"day": day, "phase": phase},
        )
        return [event.event_id]

    if tool_name in {"werewolf_speak", "werewolf_wolf_discuss"}:
        speech = str(params.get("speech") or "").strip()
        if not speech:
            event = create_event(
                session,
                world=world,
                event_type="tool_failed",
                actor_agent_id=actor.agent_id,
                location_id=actor.location.location_id if actor.location else None,
                viewer_text=f"{actor.chosen_name}没有说出具体内容。",
                agent_visible_text="发言行动需要由 LLM 写出具体台词；系统不会补默认台词。",
                importance=10,
                color_class="warning",
                payload={"llm_feedback": "发言行动需要具体台词。"},
                no_state_changed=True,
            )
            return [event.event_id]
        event_type = "werewolf_wolf_discussion" if tool_name == "werewolf_wolf_discuss" else "werewolf_speech"
        viewer = f"{actor.chosen_name}{'在狼人密会中' if tool_name == 'werewolf_wolf_discuss' else '在圆桌上'}开口发言。"
        heard_by = _listeners_in_current_location(session, actor)
        event = create_event(
            session,
            world=world,
            event_type=event_type,
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="observer" if tool_name == "werewolf_wolf_discuss" else "public",
            viewer_text=viewer,
            importance=80 if tool_name == "werewolf_speak" else 70,
            color_class="dialogue",
            payload={
                "speech": speech,
                "tone": "analytical",
                "day": day,
                "phase": phase,
                "hide_clock": tool_name == "werewolf_speak",
                "dialogue_lines": [{"speaker_agent_id": actor.agent_id, "target_agent_id": None, "text": speech, "tone": "analytical"}],
            },
        )
        session.add(
            Conversation(
                event_id=event.event_id,
                speaker_agent_id=actor.agent_id,
                target_agent_id=None,
                location_id=actor.location.location_id if actor.location else None,
                content_zh=speech,
                tone="analytical",
                heard_by_agent_ids_json=heard_by,
                world_time=world.current_world_time_minutes,
            )
        )
        if tool_name == "werewolf_speak":
            counts_all = dict(state.get("speech_counts") or {})
            counts = dict(counts_all.get(str(day)) or {})
            counts[actor.agent_id] = int(counts.get(actor.agent_id) or 0) + 1
            counts_all[str(day)] = counts
            state["speech_counts"] = counts_all
            ended_all = dict(state.get("speech_ended") or {})
            ended = dict(ended_all.get(str(day)) or {})
            ended[actor.agent_id] = True
            ended_all[str(day)] = ended
            state["speech_ended"] = ended_all
            state.pop("rebuttal_window", None)
            _record_public_werewolf_speech_memory(session, world, actor, speech, day)
            _advance_discussion_speaker(session, world, state, day)
            _persist_werewolf_state(world, state)
        else:
            discussions_all = dict(state.get("wolf_discussions") or {})
            discussion = list(discussions_all.get(str(day)) or [])
            discussion.append({"speaker_agent_id": actor.agent_id, "speech": speech, "world_time": world.current_world_time_minutes})
            discussions_all[str(day)] = discussion[-20:]
            state["wolf_discussions"] = discussions_all
            living_wolves = _living_wolf_ids(session, world, state.get("roles") or {})
            if _wolf_consensus_needs_discussion(state, day) and living_wolves and all(wolf_id in _wolf_discussion_speakers(state, day) for wolf_id in living_wolves):
                _set_wolf_consensus_needs_discussion(state, day, False)
                nominations_all = dict(state.get("wolf_kill_nominations") or {})
                nominations_all[str(day)] = {}
                state["wolf_kill_nominations"] = nominations_all
                _add_wolf_pack_memory(session, world, state, f"第{day}夜狼人密会已经重新讨论完毕；现在必须选择同一个夜袭目标，否则仍不会结算夜袭。", importance=78)
            _persist_werewolf_state(world, state)
        return [event.event_id]

    if tool_name in {"werewolf_rebut", "werewolf_skip_rebuttal", "werewolf_reply_rebuttal", "werewolf_drop_debate"}:
        window = _active_rebuttal_window(state, day) or {}
        speaker_id = str(window.get("speaker_id") or "")
        speaker = session.get(Agent, speaker_id) if speaker_id else None
        speech = str(params.get("speech") or params.get("content") or "").strip()

        if tool_name == "werewolf_skip_rebuttal":
            _advance_rebuttal_candidate(session, world, state, day)
            _persist_werewolf_state(world, state)
            event = create_event(
                session,
                world=world,
                event_type="werewolf_skip_rebuttal",
                actor_agent_id=actor.agent_id,
                location_id=actor.location.location_id if actor.location else None,
                viewer_text=f"{actor.chosen_name}没有提出反驳。",
                importance=5,
                color_class="muted",
                payload={"day": day, "phase": phase, "hide_clock": True},
                no_state_changed=True,
            )
            return [event.event_id]

        if tool_name == "werewolf_rebut":
            if not speech:
                return []
            window["mode"] = "debate"
            window["rebutter_id"] = actor.agent_id
            window["turn_agent_id"] = speaker_id
            window["reply_count"] = 0
            state["rebuttal_window"] = window
            _persist_werewolf_state(world, state)
            event = _werewolf_dialogue_event(
                session, world, actor, speech,
                event_type="werewolf_rebuttal",
                target=speaker,
                viewer_text=f"{actor.chosen_name}对{speaker.chosen_name if speaker else '刚才的发言'}提出反驳。",
                day=day, phase=phase, importance=75,
            )
            return [event.event_id]

        if tool_name == "werewolf_reply_rebuttal":
            if not speech:
                return []
            rebutter_id = str(window.get("rebutter_id") or "")
            rebutter = session.get(Agent, rebutter_id) if rebutter_id else None
            target_agent = rebutter if actor.agent_id == speaker_id else speaker
            reply_count = int(window.get("reply_count") or 0) + 1
            window["reply_count"] = reply_count
            max_replies = int(window.get("max_replies") or _rebuttal_reply_limit(world))
            state["rebuttal_window"] = window
            event = _werewolf_dialogue_event(
                session, world, actor, speech,
                event_type="werewolf_rebuttal_reply",
                target=target_agent,
                viewer_text=f"{actor.chosen_name}回应了圆桌反驳。",
                day=day, phase=phase, importance=70,
            )
            event_ids.append(event.event_id)
            if reply_count >= max_replies:
                pause = create_event(
                    session,
                    world=world,
                    event_type="werewolf_debate_paused",
                    actor_agent_id=None,
                    location_id=actor.location.location_id if actor.location else None,
                    viewer_text="两人的争论已经说得太多，暂时收住了这个话题。",
                    importance=55,
                    color_class="info",
                    payload={"day": day, "phase": phase, "hide_clock": True},
                )
                event_ids.append(pause.event_id)
                _advance_rebuttal_candidate(session, world, state, day)
            else:
                window["turn_agent_id"] = rebutter_id if actor.agent_id == speaker_id else speaker_id
                state["rebuttal_window"] = window
            _persist_werewolf_state(world, state)
            return event_ids

        if tool_name == "werewolf_drop_debate":
            _advance_rebuttal_candidate(session, world, state, day)
            _persist_werewolf_state(world, state)
            event = create_event(
                session,
                world=world,
                event_type="werewolf_debate_paused",
                actor_agent_id=actor.agent_id,
                location_id=actor.location.location_id if actor.location else None,
                viewer_text=f"{actor.chosen_name}暂时不再纠缠这点。",
                importance=45,
                color_class="info",
                payload={"day": day, "phase": phase, "hide_clock": True},
            )
            return [event.event_id]

    if tool_name == "werewolf_end_speech":
        ended_all = dict(state.get("speech_ended") or {})
        ended = dict(ended_all.get(str(day)) or {})
        ended[actor.agent_id] = True
        ended_all[str(day)] = ended
        state["speech_ended"] = ended_all
        _advance_discussion_speaker(session, world, state, day)
        _persist_werewolf_state(world, state)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_end_speech",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}结束了这一轮发言。",
            importance=50,
            color_class="info",
            payload={"day": day, "phase": phase, "hide_clock": True},
        )
        return [event.event_id]

    if tool_name == "werewolf_vote_by_name" and target:
        _record_vote(world, state, day, actor.agent_id, target.agent_id)
        settings = dict(world.settings_json or {})
        state = dict(settings.get("werewolf_state") or {})
        event = create_event(
            session,
            world=world,
            event_type="werewolf_vote",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}把票投给了{target.chosen_name}。",
            importance=90,
            color_class="important",
            payload={"day": day, "voter_agent_id": actor.agent_id, "target_agent_id": target.agent_id},
        )
        event_ids.append(event.event_id)
        event_ids.extend(_maybe_resolve_vote(session, world, day))
        return event_ids

    if tool_name == "werewolf_vote_no_execution":
        _record_vote(world, state, day, actor.agent_id, NO_EXECUTION_VOTE)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_vote",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}投给了今天不放逐任何人。",
            importance=85,
            color_class="important",
            payload={"day": day, "voter_agent_id": actor.agent_id, "target_agent_id": None, "no_execution": True},
        )
        event_ids.append(event.event_id)
        event_ids.extend(_maybe_resolve_vote(session, world, day))
        return event_ids

    if tool_name == "werewolf_review_vote_history":
        summary = _vote_history_text(session, list(state.get("vote_history") or [])[-20:])
        _add_werewolf_memory(session, world, actor, f"查看票型：{summary}", importance=55)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_vote_history",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}翻看了历史票型。",
            importance=35,
            color_class="info",
            payload={"history_summary": summary},
        )
        return [event.event_id]

    if tool_name == "werewolf_kill_by_name" and target:
        nominations_all = dict(state.get("wolf_kill_nominations") or {})
        nominations = dict(nominations_all.get(str(day)) or {})
        nominations[actor.agent_id] = target.agent_id
        nominations_all[str(day)] = nominations
        state["wolf_kill_nominations"] = nominations_all
        living_wolves = _living_wolf_ids(session, world, state.get("roles") or {})
        unique_targets = {target_id for wolf_id, target_id in nominations.items() if wolf_id in set(living_wolves)}
        all_nominated = bool(living_wolves) and all(wolf_id in nominations for wolf_id in living_wolves)
        consensus = all_nominated and len(unique_targets) == 1 and target.agent_id in unique_targets
        _persist_werewolf_state(world, state)
        if not consensus:
            summary = _wolf_nomination_summary(session, {wolf_id: nominations[wolf_id] for wolf_id in living_wolves if wolf_id in nominations})
            if all_nominated and len(unique_targets) > 1:
                mismatches = dict(state.get("wolf_consensus_mismatches") or {})
                mismatch_count = int(mismatches.get(str(day)) or 0) + 1
                mismatches[str(day)] = mismatch_count
                state["wolf_consensus_mismatches"] = mismatches
                if mismatch_count >= 3:
                    counter = Counter(nominations[wolf_id] for wolf_id in living_wolves if wolf_id in nominations)
                    locked_target_id = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]
                    locked_target = session.get(Agent, locked_target_id)
                    if locked_target:
                        _add_wolf_pack_memory(session, world, state, f"第{day}夜狼人连续多轮目标不一致，主持按多数/固定规则锁定夜袭目标：{locked_target.chosen_name}。此前意见：{summary}", importance=85)
                        event_ids.extend(_perform_werewolf_night_kill(session, world, state, day, locked_target, actor_agent_id=None, hidden=not werewolf_publicly_revealed(world)))
                        _persist_werewolf_state(world, state)
                        return event_ids
                _set_wolf_consensus_needs_discussion(state, day, True)
                nominations_all[str(day)] = {}
                state["wolf_kill_nominations"] = nominations_all
                discussions_all = dict(state.get("wolf_discussions") or {})
                discussions_all[str(day)] = []
                state["wolf_discussions"] = discussions_all
                _add_wolf_pack_memory(session, world, state, f"第{day}夜狼人夜袭意见不一致：{summary}。夜袭没有执行；所有狼人必须重新密会，公开说清自己赞成的目标，并统一选择同一个人。", importance=88)
                _persist_werewolf_state(world, state)
                event = create_event(
                    session,
                    world=world,
                    event_type="werewolf_wolf_consensus_failed",
                    actor_agent_id=actor.agent_id,
                    location_id=actor.location.location_id if actor.location else None,
                    visibility_scope="private",
                    viewer_text=f"狼人们的夜袭目标不一致，密会被迫重新讨论。当前意见：{summary}",
                    importance=75,
                    color_class="warning",
                    payload={"day": day, "nominations": nominations, "summary": summary, "discussion_required": True, "mismatch_count": mismatch_count},
                )
                return [event.event_id]
            event = create_event(
                session,
                world=world,
                event_type="werewolf_kill_nomination",
                actor_agent_id=actor.agent_id,
                target_agent_id=target.agent_id,
                location_id=actor.location.location_id if actor.location else None,
                visibility_scope="private",
                viewer_text=f"{actor.chosen_name}在狼人密会中提出了一个夜袭目标。当前意见：{summary}",
                importance=60,
                color_class="warning",
                payload={"day": day, "target_agent_id": target.agent_id, "wolf_consensus": False, "nominations": nominations, "summary": summary},
            )
            _add_wolf_pack_memory(session, world, state, f"第{day}夜狼人当前夜袭意见：{summary}。必须所有存活狼人选择同一个目标才会结算。", importance=70)
            return [event.event_id]
        event_ids.extend(_perform_werewolf_night_kill(session, world, state, day, target, actor_agent_id=None, hidden=not werewolf_publicly_revealed(world)))
        _persist_werewolf_state(world, state)
        return event_ids

    if tool_name == "werewolf_seer_check_by_name" and target:
        roles = state.get("roles") or {}
        role = roles.get(target.agent_id, "villager")
        alignment = "狼人阵营" if role == "werewolf" else "人类阵营"
        checks_all = dict(state.get("seer_checks") or {})
        checks = dict(checks_all.get(str(day)) or {})
        checks[actor.agent_id] = {"target_agent_id": target.agent_id, "alignment": alignment, "role": role}
        checks_all[str(day)] = checks
        state["seer_checks"] = checks_all
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"第{day}夜查验：{target.chosen_name}属于{alignment}。", importance=90)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_seer_check",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}在夜里查验了一个人的阵营。",
            agent_visible_text=f"你查验了{target.chosen_name}：{alignment}。",
            importance=60,
            color_class="info",
            payload={"day": day, "target_agent_id": target.agent_id, "alignment": alignment},
        )
        return [event.event_id]

    if tool_name == "werewolf_coroner_check_latest":
        latest = _latest_dead_agent(session, world)
        if latest:
            roles = state.get("roles") or {}
            label = WEREWOLF_ROLE_LABELS.get(roles.get(latest.agent_id, "villager"), "平民")
            content = f"最近出局的是{latest.chosen_name}，身份是{label}。"
        else:
            content = "目前还没有可整理的夜间死亡线索。"
        reports_all = dict(state.get("coroner_reports") or {})
        reports = dict(reports_all.get(str(day)) or {})
        reports[actor.agent_id] = content
        reports_all[str(day)] = reports
        state["coroner_reports"] = reports_all
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"验尸官记录：{content}", importance=85)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_coroner_report",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}在验尸间整理了死亡线索。",
            agent_visible_text=content,
            importance=60,
            color_class="info",
            payload={"day": day, "summary": content},
        )
        return [event.event_id]

    if tool_name == "werewolf_guard_protect_by_name" and target:
        protects_all = dict(state.get("guard_protects") or {})
        protects = dict(protects_all.get(str(day)) or {})
        protects[actor.agent_id] = target.agent_id
        protects_all[str(day)] = protects
        state["guard_protects"] = protects_all
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"第{day}夜守护：{target.chosen_name}。", importance=80)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_guard_protect",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}在夜里守护了一名幸存者。",
            agent_visible_text=f"你守护了{target.chosen_name}。",
            importance=60,
            color_class="info",
            payload={"day": day, "target_agent_id": target.agent_id},
        )
        return [event.event_id]

    if tool_name == "werewolf_witch_save_latest":
        day_key = str(day)
        kill = dict(((state.get("night_kills") or {}).get(day_key)) or {})
        target_id = str(kill.get("target_agent_id") or "")
        target = session.get(Agent, target_id) if target_id else None
        if not target:
            return []
        _revive_agent_after_witch_save(target, world)
        _remove_corpse_record(world, target.agent_id)
        kill["blocked"] = True
        kill["saved_by_agent_id"] = actor.agent_id
        kill["saved"] = True
        night_kills = dict(state.get("night_kills") or {})
        night_kills[day_key] = kill
        state["night_kills"] = night_kills
        saves_all = dict(state.get("witch_saves") or {})
        saves = dict(saves_all.get(day_key) or {})
        saves[actor.agent_id] = target.agent_id
        saves_all[day_key] = saves
        state["witch_saves"] = saves_all
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"第{day}夜女巫解药：你救回了{target.chosen_name}。", importance=90)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_witch_save",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}在夜里救回了一名遇袭者。",
            agent_visible_text=f"你使用解药救回了{target.chosen_name}；如果今晚没有其他人死亡，明天早上村庄仍不会知道狼人存在。",
            importance=80,
            color_class="info",
            payload={"day": day, "target_agent_id": target.agent_id},
        )
        return [event.event_id]

    if tool_name == "werewolf_witch_reveal_saved_attack":
        saved_attack = _latest_revealable_witch_saved_attack(state, day, phase, actor.agent_id)
        if not saved_attack:
            return []
        night = int(saved_attack.get("night") or max(1, day - 1))
        target_id = str(saved_attack.get("target_agent_id") or "")
        target = session.get(Agent, target_id) if target_id else None
        reveals = dict(state.get("witch_saved_attack_reveals") or {})
        reveals[str(night)] = {
            "day": day,
            "night": night,
            "saved_by_agent_id": actor.agent_id,
            "target_agent_id": target_id,
            "world_time": world.current_world_time_minutes,
        }
        state["witch_saved_attack_reveals"] = reveals
        reason = f"{actor.chosen_name}公开第{night}夜救回{target.chosen_name if target else '遇袭者'}的事实"
        _reveal_werewolf_to_agents(session, world, state, day=day, reason=reason)
        _persist_werewolf_state(world, state)
        _seed_opening_notice_board(world)
        location_id = world_location_id(world.world_id, "village_square")
        roles = dict(state.get("roles") or {})
        living_wolves = _living_wolf_ids(session, world, roles)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_notice_board",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id if target else None,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name}公开说第{night}夜{target.chosen_name if target else '有人'}遭到夜袭并被自己救回；村庄广场告示牌上出现血红字：狼人存在于村中。",
            importance=100,
            color_class="danger",
            payload={
                "day": day,
                "night": night,
                "wolves_alive": bool(living_wolves),
                "wolf_count": len(living_wolves),
                "must_discuss": True,
                "reveal_reason": "witch_saved_attack",
                "saved_by_agent_id": actor.agent_id,
                "saved_target_agent_id": target_id,
            },
        )
        announced = dict(state.get("wolf_notice_announced") or {})
        announced[str(day)] = {"wolves_alive": bool(living_wolves), "event_id": event.event_id, "wolf_count": len(living_wolves), "reveal_reason": "witch_saved_attack"}
        state["wolf_notice_announced"] = announced
        _persist_werewolf_state(world, state)
        for observer_id in _living_agent_ids(session, world):
            observer = session.get(Agent, observer_id)
            if observer:
                _add_werewolf_memory(
                    session,
                    world,
                    observer,
                    f"第{day}天清晨公开事实：{actor.chosen_name}公开第{night}夜{target.chosen_name if target else '有人'}遭到夜袭并被救回；村庄广场告示牌写着“狼人存在于村中”。",
                    importance=96,
                )
        return [event.event_id]

    if tool_name == "werewolf_witch_poison_by_name" and target:
        poisons_all = dict(state.get("witch_poisons") or {})
        poisons = dict(poisons_all.get(str(day)) or {})
        poisons[actor.agent_id] = target.agent_id
        poisons_all[str(day)] = poisons
        state["witch_poisons"] = poisons_all
        _eliminate_agent(target, world, "女巫夜间毒药出局")
        if target.dynamic_state:
            apply_delta(target.dynamic_state, health=-100, energy=-100, mood=-20, stress=25)
        corpse = ensure_corpse_for_dead_agent(session, world, target, location_id=target.location.location_id if target.location else None, cause="女巫夜间毒药")
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"第{day}夜女巫毒药：你毒死了{target.chosen_name}。", importance=90)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_witch_poison",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=target.location.location_id if target.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}在夜里使用了毒药。",
            agent_visible_text=f"你使用毒药杀死了{target.chosen_name}。",
            importance=90,
            color_class="danger",
            payload={"day": day, "target_agent_id": target.agent_id, "corpse_id": corpse.get("corpse_id")},
        )
        return [event.event_id] + _check_werewolf_win(session, world)

    if tool_name == "werewolf_medium_check_latest":
        latest = _latest_dead_agent(session, world)
        if latest:
            roles = state.get("roles") or {}
            role = roles.get(latest.agent_id, "villager")
            alignment = "狼人阵营" if role == "werewolf" else "人类阵营"
            content = f"最近死者是{latest.chosen_name}，阵营是{alignment}。"
        else:
            content = "目前还没有可通灵的死者线索。"
        reports_all = dict(state.get("medium_reports") or {})
        reports = dict(reports_all.get(str(day)) or {})
        reports[actor.agent_id] = content
        reports_all[str(day)] = reports
        state["medium_reports"] = reports_all
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"灵媒记录：{content}", importance=84)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_medium_report",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name}在夜里整理了死者残留线索。",
            agent_visible_text=content,
            importance=60,
            color_class="info",
            payload={"day": day, "summary": content},
        )
        return [event.event_id]

    if tool_name == "werewolf_hunter_shoot_by_name" and target:
        shots = dict(state.get("hunter_shots") or {})
        shots[actor.agent_id] = {"target_agent_id": target.agent_id, "day": day}
        state["hunter_shots"] = shots
        _eliminate_agent(target, world, "猎人开枪带走")
        if target.dynamic_state:
            apply_delta(target.dynamic_state, health=-100, energy=-100, mood=-30, stress=35)
        corpse = ensure_corpse_for_dead_agent(session, world, target, location_id=target.location.location_id if target.location else None, cause="猎人开枪")
        _persist_werewolf_state(world, state)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_hunter_shot",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}以猎人身份开枪，带走了{target.chosen_name}。",
            importance=100,
            color_class="danger",
            payload={"day": day, "target_agent_id": target.agent_id, "corpse_id": corpse.get("corpse_id")},
        )
        return [event.event_id] + _check_werewolf_win(session, world)

    if tool_name == "werewolf_idiot_reveal_self":
        reveals = dict(state.get("idiot_reveals") or {})
        reveals[actor.agent_id] = {"day": day, "world_time": world.current_world_time_minutes}
        state["idiot_reveals"] = reveals
        _persist_werewolf_state(world, state)
        _add_werewolf_memory(session, world, actor, f"第{day}天你亮明了白痴身份；如果当天投票指向你，你不会被放逐，但会成为强公共信息。", importance=88)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_idiot_reveal",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}亮明了白痴身份，要求大家重新判断投票。",
            importance=85,
            color_class="important",
            payload={"day": day},
        )
        return [event.event_id]

    event = create_event(
        session,
        world=world,
        event_type="werewolf_action",
        actor_agent_id=actor.agent_id,
        location_id=actor.location.location_id if actor.location else None,
        viewer_text=f"{actor.chosen_name}处理了一次村庄危机行动。",
        importance=20,
        color_class="info",
    )
    return [event.event_id]


def _maybe_resolve_vote(session: Session, world: World, day: int) -> list[int]:
    return _resolve_day_vote(session, world, day, force=False)


def _resolve_day_vote(session: Session, world: World, day: int, *, force: bool) -> list[int]:
    state = werewolf_state(world)
    if ((state.get("vote_resolved") or {}).get(str(day))):
        return []
    votes = ((state.get("votes") or {}).get(str(day)) or {})
    living = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
            .order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    )
    if not force and len(votes) < len(living):
        return []
    tally: dict[str, int] = {}
    for target_id in votes.values():
        tally[target_id] = tally.get(target_id, 0) + 1
    if day == 1:
        _mark_vote_resolved(world, day)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_no_vote_first_day",
            viewer_text="第1天没有公开投票。大家只是自由交流，等待第一夜过去。",
            importance=80,
            color_class="warning",
            payload={"day": day, "reason": "first_day_chat_only"},
        )
        return [event.event_id]

    tally.pop(NO_EXECUTION_VOTE, None)
    target_id = _mandatory_vote_target_id(living, tally)
    if not target_id:
        _mark_vote_resolved(world, day)
        return []
    target = session.get(Agent, target_id)
    if not target or target.lifecycle_state == "dead":
        _mark_vote_resolved(world, day)
        return []
    roles = state.get("roles") or {}
    if roles.get(target.agent_id) == "idiot" and target.agent_id in (state.get("idiot_reveals") or {}):
        _mark_vote_resolved(world, day)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_idiot_spared",
            target_agent_id=target.agent_id,
            location_id=target.location.location_id if target.location else None,
            viewer_text=f"投票指向了{target.chosen_name}，但其已亮明白痴身份；今天没有人被放逐。",
            importance=95,
            color_class="warning",
            payload={"day": day, "target_agent_id": target.agent_id, "tally": tally},
        )
        return [event.event_id]
    _eliminate_agent(target, world, "白天投票放逐出局")
    _mark_vote_resolved(world, day)
    event = create_event(
        session,
        world=world,
        event_type="werewolf_exile",
        target_agent_id=target.agent_id,
        location_id=target.location.location_id if target.location else None,
        viewer_text=f"投票结束，{target.chosen_name}被放逐出局。",
        importance=100,
        color_class="danger",
        payload={"day": day, "target_agent_id": target.agent_id, "tally": tally},
    )
    _record_exile_result_memory(session, world, target, day, tally)
    return [event.event_id] + _check_werewolf_win(session, world)


def _record_vote(world: World, state: dict[str, Any], day: int, voter_agent_id: str, target_agent_id: str) -> None:
    settings = dict(world.settings_json or {})
    votes_all = dict(state.get("votes") or {})
    votes = dict(votes_all.get(str(day)) or {})
    votes[voter_agent_id] = target_agent_id
    votes_all[str(day)] = votes
    history = list(state.get("vote_history") or [])
    history.append({"day": day, "voter_agent_id": voter_agent_id, "target_agent_id": target_agent_id, "world_time": world.current_world_time_minutes})
    state["votes"] = votes_all
    state["vote_history"] = history[-200:]
    settings["werewolf_state"] = state
    world.settings_json = settings


def _resolve_optional_first_day_vote(session: Session, world: World, day: int, tally: dict[str, int]) -> list[int]:
    player_tally = {target_id: count for target_id, count in tally.items() if target_id != NO_EXECUTION_VOTE}
    no_execution_votes = int(tally.get(NO_EXECUTION_VOTE) or 0)
    if not player_tally:
        event = create_event(session, world=world, event_type="werewolf_no_exile", viewer_text="第一天投票结束，大家选择暂时不放逐任何人。", importance=90, color_class="warning", payload={"day": day, "tally": tally, "reason": "no_execution"})
        return [event.event_id]
    max_votes = max(player_tally.values())
    candidates = [target_id for target_id, count in player_tally.items() if count == max_votes]
    if no_execution_votes >= max_votes:
        event = create_event(session, world=world, event_type="werewolf_no_exile", viewer_text="第一天投票结束，不放逐的票数占优，没有人出局。", importance=90, color_class="warning", payload={"day": day, "tally": tally, "reason": "no_execution_won"})
        return [event.event_id]
    if len(candidates) != 1:
        event = create_event(session, world=world, event_type="werewolf_vote_tie", viewer_text="第一天投票出现平票，没有人被放逐。", importance=90, color_class="warning", payload={"day": day, "tally": tally})
        return [event.event_id]
    target = session.get(Agent, candidates[0])
    if not target or target.lifecycle_state == "dead":
        return []
    _eliminate_agent(target, world, "白天投票放逐出局")
    event = create_event(
        session,
        world=world,
        event_type="werewolf_exile",
        target_agent_id=target.agent_id,
        location_id=target.location.location_id if target.location else None,
        viewer_text=f"第一天投票结束，{target.chosen_name}被放逐出局。",
        importance=100,
        color_class="danger",
        payload={"day": day, "target_agent_id": target.agent_id, "tally": tally},
    )
    _record_exile_result_memory(session, world, target, day, tally)
    return [event.event_id] + _check_werewolf_win(session, world)


def _record_exile_result_memory(session: Session, world: World, target: Agent, day: int, tally: dict[str, int]) -> None:
    text = (
        f"第{day}天投票结果：{target.chosen_name}已经被白天投票放逐出局，"
        "之后不能再发言、投票、被投票、被夜袭、被查验或被守护；不要再把这个人当作可行动目标。"
        f"票数：{_tally_text(session, tally)}"
    )
    for observer in session.execute(
        select(Agent)
        .where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
        .order_by(Agent.created_at_world_time, Agent.agent_id)
    ).scalars():
        _add_werewolf_memory(session, world, observer, text, importance=98)


def _tally_text(session: Session, tally: dict[str, int]) -> str:
    if not tally:
        return "无票数记录。"
    parts: list[str] = []
    for target_id, count in sorted(tally.items(), key=lambda item: (-int(item[1] or 0), str(item[0]))):
        if target_id == NO_EXECUTION_VOTE:
            target_name = "不放逐任何人"
        else:
            target = session.get(Agent, target_id)
            target_name = target.chosen_name if target else "某人"
        parts.append(f"{target_name}{count}票")
    return "、".join(parts)


def _mandatory_vote_target_id(living: list[Agent], tally: dict[str, int]) -> str | None:
    living_ids = [agent.agent_id for agent in living]
    tally = {target_id: count for target_id, count in tally.items() if target_id in set(living_ids)}
    if not tally:
        return living_ids[0] if living_ids else None
    max_votes = max(tally.values())
    candidates = {target_id for target_id, count in tally.items() if count == max_votes}
    for agent_id in living_ids:
        if agent_id in candidates:
            return agent_id
    return None


def _mark_vote_resolved(world: World, day: int) -> None:
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    resolved = dict(state.get("vote_resolved") or {})
    resolved[str(day)] = True
    state["vote_resolved"] = resolved
    settings["werewolf_state"] = state
    world.settings_json = settings


def _check_werewolf_win(session: Session, world: World) -> list[int]:
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    if state.get("winner"):
        return []
    roles = state.get("roles") or {}
    living = list(session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")).scalars())
    wolves = [agent for agent in living if roles.get(agent.agent_id) == "werewolf"]
    humans = [agent for agent in living if roles.get(agent.agent_id) != "werewolf"]
    winner = None
    if not wolves:
        winner = "人类阵营"
    elif len(wolves) >= len(humans):
        winner = "狼人阵营"
    if not winner:
        return []
    state["winner"] = winner
    state["final_speech_order"] = _werewolf_final_speech_order(living, roles, winner)
    state["final_speeches"] = {}
    state["final_speeches_complete"] = False
    settings["werewolf_state"] = state
    world.settings_json = settings
    if winner == "人类阵营":
        viewer_text = "村庄广场告示牌上的血红字消失了，人类阵营意识到狼人已经不复存在。幸存者即将说出最后的话。"
    else:
        viewer_text = f"村庄危机局势已定，{_winner_in_world_label(winner)}已经占据最终优势。幸存者即将说出最后的话。"
    event = create_event(
        session,
        world=world,
        event_type="werewolf_game_decided",
        viewer_text=viewer_text,
        importance=100,
        color_class="important",
        payload={"winner": winner, "final_speech_pending": True},
    )
    return [event.event_id]


def _winner_in_world_label(winner: str) -> str:
    return "狼人" if winner == "狼人阵营" else "人类"


def _werewolf_final_speech_order(living: list[Agent], roles: dict[str, str], winner: str) -> list[str]:
    if winner == "狼人阵营":
        wolves = [agent.agent_id for agent in living if roles.get(agent.agent_id) == "werewolf"]
        humans = [agent.agent_id for agent in living if roles.get(agent.agent_id) != "werewolf"]
        return wolves + humans
    return [agent.agent_id for agent in living if roles.get(agent.agent_id) != "werewolf"]


def werewolf_final_speech_actor_id(session: Session, world: World) -> str | None:
    if not werewolf_enabled(world):
        return None
    state = werewolf_state(world)
    if not state.get("winner") or state.get("final_speeches_complete"):
        return None
    spoken = state.get("final_speeches") if isinstance(state.get("final_speeches"), dict) else {}
    for agent_id in list(state.get("final_speech_order") or []):
        agent = session.get(Agent, str(agent_id))
        if agent and agent.lifecycle_state != "dead" and str(agent_id) not in spoken:
            return str(agent_id)
    return None


def werewolf_final_speech_prompt(session: Session, world: World, agent: Agent) -> tuple[str, str]:
    state = werewolf_state(world)
    roles = state.get("roles") if isinstance(state.get("roles"), dict) else {}
    winner = str(state.get("winner") or "")
    role = roles.get(agent.agent_id, "villager")
    spoken = state.get("final_speeches") if isinstance(state.get("final_speeches"), dict) else {}
    wolf_lines: list[str] = []
    for item in spoken.values():
        if isinstance(item, dict) and roles.get(str(item.get("agent_id") or "")) == "werewolf":
            name = str(item.get("agent_name") or "狼人")
            speech = str(item.get("speech") or "").strip()
            if speech:
                wolf_lines.append(f"{name}：{speech}")
    system_prompt = (
        "你就是这个村庄里的居民，只输出角色最终发言正文，不要输出动作编号、JSON、解释或旁白。"
        "绝对不要使用任何场外娱乐视角或重来视角；你必须把夜袭、身份、放逐和死亡当作真实发生的村庄危机。"
    )
    if winner == "狼人阵营" and role == "werewolf":
        user_prompt = (
            f"你是{agent.chosen_name}，你的真实隐藏身份是狼人。现在局势已经无法逆转：狼人数量已经不少于普通人类，剩下的人无法再阻止你们。"
            "现在可以公开身份，向剩下的人说最后的话。可以炫耀、讽刺、冷静、得意，也可以说出这几天伪装成人类时真正的心情。"
            "禁止使用任何场外娱乐视角、重来视角或轻飘飘安慰；这是一场真实发生的村庄危机。"
            "请用角色自己的语气写一段完整发言，120到260字左右，不要写成列表。"
        )
    elif winner == "狼人阵营":
        revealed = "\n".join(wolf_lines) if wolf_lines else "狼人已经公开承认一切无法挽回。"
        user_prompt = (
            f"你是{agent.chosen_name}，你是幸存的人类。狼人已经占据无法逆转的优势。你刚听到狼人公开说：\n{revealed}\n"
            "请直接回应这些话，说出震惊、愤怒、后悔、恐惧、不甘或对出局同伴的想法。"
            "禁止使用任何场外娱乐视角、重来视角或轻飘飘安慰；这是一场真实发生的村庄危机。"
            "请用角色自己的语气写一段完整发言，120到260字左右，不要写成列表。"
        )
    else:
        user_prompt = (
            f"你是{agent.chosen_name}，村庄危机终于结束，狼人都已经死亡或被放逐。"
            "请说出庆幸、松一口气、悼念出局者或重新面对幸存者的最终发言。"
            "禁止使用任何场外娱乐视角、重来视角或轻飘飘安慰；这是一场真实发生的村庄危机。"
            "请用角色自己的语气写一段完整发言，120到260字左右，不要写成列表。"
        )
    return system_prompt, user_prompt


def record_werewolf_final_speech(session: Session, world: World, agent: Agent, speech: str) -> list[int]:
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    winner = str(state.get("winner") or "")
    text = str(speech or "").strip()
    if not text:
        return []
    event = create_event(
        session,
        world=world,
        event_type="werewolf_final_speech",
        actor_agent_id=agent.agent_id,
        location_id=agent.location.location_id if agent.location else None,
        viewer_text=f"{agent.chosen_name}说出了最后的话。",
        importance=100,
        color_class="dialogue",
        payload={
            "winner": winner,
            "speech": text,
            "dialogue_lines": [{"speaker_agent_id": agent.agent_id, "target_agent_id": None, "text": text, "tone": "final"}],
        },
    )
    session.add(
        Conversation(
            event_id=event.event_id,
            speaker_agent_id=agent.agent_id,
            target_agent_id=None,
            location_id=agent.location.location_id if agent.location else None,
            content_zh=text,
            tone="final",
            heard_by_agent_ids_json=_living_agent_ids(session, world),
            world_time=world.current_world_time_minutes,
        )
    )
    spoken = dict(state.get("final_speeches") or {})
    spoken[agent.agent_id] = {"agent_id": agent.agent_id, "agent_name": agent.chosen_name, "speech": text}
    state["final_speeches"] = spoken
    event_ids = [event.event_id]
    settings["werewolf_state"] = state
    world.settings_json = settings
    if werewolf_final_speech_actor_id(session, world) is None:
        state["final_speeches_complete"] = True
        end_event = create_event(
            session,
            world=world,
            event_type="werewolf_game_end",
            viewer_text=f"村庄危机结束，{_winner_in_world_label(winner)}占据最终优势。",
            importance=100,
            color_class="important",
            payload={"winner": winner},
        )
        event_ids.append(end_event.event_id)
        world.status = "ended"
    settings["werewolf_state"] = state
    world.settings_json = settings
    return event_ids

def _living_agent_ids(session: Session, world: World) -> list[str]:
    return [
        agent.agent_id
        for agent in session.execute(
            select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead").order_by(Agent.created_at_world_time, Agent.agent_id)
        ).scalars()
    ]


def _living_wolf_ids(session: Session, world: World, roles: dict[str, str]) -> list[str]:
    return [agent_id for agent_id in _living_agent_ids(session, world) if roles.get(agent_id) == "werewolf"]


def _current_speaker_id(session: Session, world: World, state: dict[str, Any], day: int) -> str | None:
    order = [agent_id for agent_id in (state.get("speech_order") or _living_agent_ids(session, world)) if session.get(Agent, agent_id) and session.get(Agent, agent_id).lifecycle_state != "dead"]
    if not order:
        return None
    ended = ((state.get("speech_ended") or {}).get(str(day)) or {})
    counts = ((state.get("speech_counts") or {}).get(str(day)) or {})
    index = int(state.get("current_speaker_index") or 0)
    while index < len(order) and (ended.get(order[index]) or int(counts.get(order[index]) or 0) >= _speech_limit(world)):
        index += 1
    if index >= len(order):
        return None
    return order[index]


def _advance_discussion_speaker(session: Session, world: World, state: dict[str, Any], day: int) -> None:
    order = [agent_id for agent_id in (state.get("speech_order") or _living_agent_ids(session, world)) if session.get(Agent, agent_id) and session.get(Agent, agent_id).lifecycle_state != "dead"]
    ended = ((state.get("speech_ended") or {}).get(str(day)) or {})
    counts = ((state.get("speech_counts") or {}).get(str(day)) or {})
    index = int(state.get("current_speaker_index") or 0)
    index += 1
    while index < len(order) and (ended.get(order[index]) or int(counts.get(order[index]) or 0) >= _speech_limit(world)):
        index += 1
    state["speech_order"] = order
    state["current_speaker_index"] = min(index, len(order))


def _normalize_discussion_state(session: Session, world: World, state: dict[str, Any], day: int) -> None:
    living = _living_agent_ids(session, world)
    counts_all = dict(state.get("speech_counts") or {})
    ended_all = dict(state.get("speech_ended") or {})
    day_key = str(day)
    day_initialized = day_key in counts_all or day_key in ended_all

    if day_initialized:
        old_order = [agent_id for agent_id in (state.get("speech_order") or []) if agent_id in set(living)]
        order = old_order + [agent_id for agent_id in living if agent_id not in set(old_order)]
        counts = dict(counts_all.get(day_key) or {})
        ended = dict(ended_all.get(day_key) or {})
        try:
            index = int(state.get("current_speaker_index") or 0)
        except (TypeError, ValueError):
            index = 0
        if order and not counts and not ended and index >= len(order):
            # Recovery for saves that already wrote empty Day N speech buckets but
            # kept Day N-1's exhausted index.  An empty current-day bucket means no
            # hosted speech has actually consumed a slot yet.
            index = 0
    else:
        # Same-phase recovery for saves that already say "Day N discussion" but
        # only carry Day N-1 speech keys.  Without this, the old exhausted speaker
        # index can make the host think Day N has no speaker, so free actions eat
        # the round-table window.
        order = list(living)
        counts = {}
        ended = {}
        index = 0
    for agent_id in order:
        if int(counts.get(agent_id) or 0) >= _speech_limit(world):
            ended[agent_id] = True
    index = max(0, min(index, len(order)))
    while index < len(order) and (ended.get(order[index]) or int(counts.get(order[index]) or 0) >= _speech_limit(world)):
        index += 1
    counts_all[day_key] = {agent_id: int(counts.get(agent_id) or 0) for agent_id in order if int(counts.get(agent_id) or 0) > 0}
    ended_all[day_key] = {agent_id: bool(ended.get(agent_id)) for agent_id in order if bool(ended.get(agent_id))}
    state["speech_order"] = order
    state["current_speaker_index"] = min(index, len(order))
    state["speech_counts"] = counts_all
    state["speech_ended"] = ended_all


def _speech_limit(world: World) -> int:
    # The hosted Werewolf loop grants exactly one main speech per living player.
    # More back-and-forth belongs inside that speech text, not in extra tools.
    return DAY_SPEECH_LIMIT


def _rebuttal_reply_limit(world: World) -> int:
    params = ((world.settings_json or {}).get("worldview_rule_parameters") or {}).get("werewolf") or {}
    try:
        return max(1, int(params.get("rebuttal_reply_limit") or REBUTTAL_REPLY_LIMIT))
    except (TypeError, ValueError):
        return REBUTTAL_REPLY_LIMIT


def _is_guarded(state: dict[str, Any], day: int, target_agent_id: str) -> bool:
    protects = ((state.get("guard_protects") or {}).get(str(day)) or {})
    return target_agent_id in set(protects.values())


def _werewolf_dialogue_event(
    session: Session,
    world: World,
    actor: Agent,
    speech: str,
    *,
    event_type: str,
    target: Agent | None,
    viewer_text: str,
    day: int,
    phase: str,
    importance: int,
):
    heard_by = _listeners_in_current_location(session, actor)
    event = create_event(
        session,
        world=world,
        event_type=event_type,
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id if target else None,
        location_id=actor.location.location_id if actor.location else None,
        viewer_text=viewer_text,
        importance=importance,
        color_class="dialogue",
        payload={
            "speech": speech,
            "tone": "analytical",
            "day": day,
            "phase": phase,
            "hide_clock": True,
            "dialogue_lines": [{"speaker_agent_id": actor.agent_id, "target_agent_id": target.agent_id if target else None, "text": speech, "tone": "analytical"}],
        },
    )
    session.add(
        Conversation(
            event_id=event.event_id,
            speaker_agent_id=actor.agent_id,
            target_agent_id=target.agent_id if target else None,
            location_id=actor.location.location_id if actor.location else None,
            content_zh=speech,
            tone="analytical",
            heard_by_agent_ids_json=heard_by,
            world_time=world.current_world_time_minutes,
        )
    )
    return event


def _listeners_in_current_location(session: Session, actor: Agent) -> list[str]:
    if not actor.location:
        return []
    rows = session.execute(
        select(Agent)
        .join(AgentLocation, AgentLocation.agent_id == Agent.agent_id)
        .where(
            Agent.world_id == actor.world_id,
            Agent.agent_id != actor.agent_id,
            Agent.lifecycle_state != "dead",
            AgentLocation.location_id == actor.location.location_id,
        )
    ).scalars()
    return [row.agent_id for row in rows]


def _add_werewolf_memory(session: Session, world: World, agent: Agent, content: str, *, importance: int = 60) -> None:
    session.add(Memory(agent_id=agent.agent_id, memory_type="werewolf", content=content, importance=importance, visibility="private", created_world_time=world.current_world_time_minutes))
    desires = dict(agent.desires_json or {})
    ww = dict(desires.get("werewolf") or {})
    notes = list(ww.get("crisis_notes") or ww.get("game_notes") or [])
    notes.append({"world_time": world.current_world_time_minutes, "content": content})
    ww["crisis_notes"] = notes[-16:]
    desires["werewolf"] = ww
    agent.desires_json = desires


def _upsert_werewolf_reasoning(session: Session, world: World, actor: Agent, target: Agent, content: str) -> tuple[bool, str]:
    prefix = f"对{target.chosen_name}的身份推理："
    existing = [
        memory
        for memory in session.execute(
            select(Memory)
            .where(
                Memory.agent_id == actor.agent_id,
                Memory.memory_type == WEREWOLF_REASONING_MEMORY_TYPE,
                Memory.archived.is_(False),
            )
            .order_by(Memory.memory_id.desc())
        ).scalars()
        if str(memory.content or "").startswith(prefix)
    ]
    normalized = " ".join(str(content or "").split())
    delete_markers = ("删除", "清除", "抹除", "忘记", "移除")
    wants_delete = normalized in delete_markers or any(
        normalized.startswith(marker + " ") or normalized.startswith(marker + "：") or normalized.startswith(marker + ":")
        for marker in delete_markers
    )
    desires = dict(actor.desires_json or {})
    ww = dict(desires.get("werewolf") or {})
    reasoning = dict(ww.get("reasoning_notes") or {})
    if wants_delete:
        for memory in existing:
            memory.archived = True
        reasoning.pop(target.agent_id, None)
        ww["reasoning_notes"] = reasoning
        desires["werewolf"] = ww
        actor.desires_json = desires
        if existing:
            return True, f"已删除关于{target.chosen_name}的旧身份推理。"
        return False, f"没有找到关于{target.chosen_name}的旧身份推理可删除。"

    text = f"{prefix}{normalized}"
    if existing:
        primary = existing[0]
        primary.content = text
        primary.importance = max(int(primary.importance or 0), 74)
        primary.created_world_time = world.current_world_time_minutes
        for duplicate in existing[1:]:
            duplicate.archived = True
    else:
        session.add(
            Memory(
                agent_id=actor.agent_id,
                memory_type=WEREWOLF_REASONING_MEMORY_TYPE,
                content=text,
                importance=74,
                visibility="private",
                created_world_time=world.current_world_time_minutes,
            )
        )
    reasoning[target.agent_id] = {"target_name": target.chosen_name, "content": normalized, "world_time": world.current_world_time_minutes}
    ww["reasoning_notes"] = reasoning
    desires["werewolf"] = ww
    actor.desires_json = desires
    return True, f"已记录关于{target.chosen_name}的身份推理：{normalized}"


def _names(session: Session, agent_ids: list[str]) -> str:
    names = []
    for agent_id in agent_ids:
        agent = session.get(Agent, agent_id)
        names.append(agent.chosen_name if agent and agent.chosen_name else agent_id)
    return "、".join(names)


def _vote_history_text(session: Session, records: list[dict[str, Any]]) -> str:
    if not records:
        return "暂无相关投票记录。"
    parts = []
    for record in records:
        voter = session.get(Agent, record.get("voter_agent_id"))
        if record.get("target_agent_id") == NO_EXECUTION_VOTE:
            target_name = "不放逐任何人"
        else:
            target = session.get(Agent, record.get("target_agent_id"))
            target_name = target.chosen_name if target else "某人"
        parts.append(f"第{record.get('day')}天：{voter.chosen_name if voter else '某人'}投给{target_name}")
    return "；".join(parts)


def _latest_dead_agent(session: Session, world: World) -> Agent | None:
    return (
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id, Agent.lifecycle_state == "dead")
            .order_by(Agent.death_at_world_time.desc().nullslast())
        )
        .scalars()
        .first()
    )


def _eliminate_agent(agent: Agent, world: World, cause: str) -> None:
    agent.lifecycle_state = "dead"
    agent.death_at_world_time = world.current_world_time_minutes
    agent.death_cause = cause


def _revive_agent_after_witch_save(agent: Agent, world: World) -> None:
    agent.lifecycle_state = "alive"
    agent.death_at_world_time = None
    agent.death_cause = None
    if agent.dynamic_state:
        agent.dynamic_state.health = clamp(max(float(agent.dynamic_state.health or 0), 35), 0, 100)
        agent.dynamic_state.energy = clamp(max(float(agent.dynamic_state.energy or 0), 25), 0, 100)
        agent.dynamic_state.stress = clamp(max(float(agent.dynamic_state.stress or 0), 20), 0, 100)
        agent.dynamic_state.last_decay_world_time = int(world.current_world_time_minutes or 0)


def _remove_corpse_record(world: World, agent_id: str) -> None:
    settings = dict(world.settings_json or {})
    records = settings.get("corpse_records")
    if not isinstance(records, list):
        return
    settings["corpse_records"] = [
        record
        for record in records
        if not (isinstance(record, dict) and str(record.get("agent_id") or "") == str(agent_id))
    ]
    world.settings_json = settings
