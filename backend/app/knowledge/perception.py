from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.traits import mood_label, trait_prompt_lines
from app.agents.v5_state import ensure_v5_agent_state, wallet_money
from app.content.toolsets import survival_needs_enabled
from app.core.clock import format_world_time
from app.core.models import Agent, Event, IdentityKnowledge, Location, Memory, World
from app.economy.v6 import ensure_v6_agent_state, update_derived_economy
from app.effects.drive_system import drive_prompt_lines, write_drive_state
from app.knowledge.identity_knowledge import known_names, visual_only
from app.llm.language import action_language_instruction, cjk_count, english_safe_label, english_safe_sentence, gender_label, location_label, mood_label_text, person_ref_label, world_language
from app.simulation.difficulty import profile_for_agent
from app.social.forced_actions import pending_force_attempt_prompt_lines
from app.social.pending_requests import pending_social_request_prompt_lines
from app.llm.action_options import build_action_options
from app.llm.action_protocol import ActionOption, format_action_options_for_prompt
from app.tools.registry import TOOL_SPECS, available_tools, format_tools_for_prompt, is_pregnant
from app.world.corpses import corpse_rules_prompt_lines, visible_corpse_prompt_lines
from app.world.notice_board import notice_board_prompt_lines
from app.world.public_hygiene import location_hygiene_prompt_line
from app.world.visibility import adjacent_location_ids, build_visible_people, concise_person_label, mark_name_known
from app.world.werewolf import (
    werewolf_agent_facing_location_description,
    werewolf_agent_facing_location_name,
    werewolf_agent_text_locked,
    werewolf_enabled,
    werewolf_prompt_status_lines,
    werewolf_publicly_revealed,
)


@dataclass(slots=True)
class TurnContext:
    prompt: str
    ref_map: dict[str, str]
    action_options: list[ActionOption]


def _apply_identity_reveals_from_recent_events(session: Session, world: World, observer: Agent) -> None:
    """Persist self-introductions heard in the same scene before building prompts.

    Some older dialogue events contained a clear self-introduction, but the listener's
    identity cache was only updated for part of the room.  That produced prompts where
    one agent used “要乐奈” while another still said “黑色吊带的人”.  This pass is a
    generic short-term repair: if a visible resident recently introduced themselves in
    the same location or explicitly marked the observer as a listener, remember the name
    before formatting visible-person labels.
    """
    if not observer.location:
        return
    current_location_id = observer.location.location_id
    rows = list(
        session.execute(
            select(Event)
            .where(Event.world_id == world.world_id, Event.actor_agent_id.is_not(None))
            .where(Event.event_type.in_(["introduce_self", "dialogue", "conversation", "werewolf_speech", "werewolf_wolf_discussion"]))
            .order_by(Event.event_id.desc())
            .limit(80)
        ).scalars()
    )
    for event in rows:
        if event.actor_agent_id == observer.agent_id:
            continue
        actor = session.get(Agent, event.actor_agent_id) if event.actor_agent_id else None
        if not actor or not actor.chosen_name:
            continue
        payload = event.payload or {}
        heard_by = set(str(item) for item in (payload.get("heard_by_agent_ids") or payload.get("heard_by_agent_ids_json") or []))
        if observer.agent_id in heard_by:
            heard_here = True
        else:
            heard_here = bool(event.location_id and event.location_id == current_location_id and event.visibility_scope in {"public", "same_location", None, ""})
        if not heard_here:
            continue
        text_parts = [str(event.agent_visible_text or event.viewer_text or "")]
        for line in payload.get("dialogue_lines") or []:
            if isinstance(line, dict) and str(line.get("speaker_agent_id") or "") == actor.agent_id:
                text_parts.append(str(line.get("text") or ""))
        speech = "\n".join(part for part in text_parts if part)
        if event.event_type == "introduce_self" or payload.get("reveal_name") or _looks_like_self_intro(speech, actor.chosen_name):
            mark_name_known(session, observer.agent_id, actor, int(world.current_world_time_minutes or 0), "recent_self_intro", gender_revealed=False)


def _looks_like_self_intro(text: str, name: str) -> bool:
    if not text or not name or name not in text:
        return False
    intro_markers = ("我叫", "我是", "名字", "称呼", "叫我", "自我介绍")
    return any(marker in text for marker in intro_markers)


_WEREWOLF_LOCKED_LOCATION_NAMES_EN = {
    "discussion_hall": "village meeting hall",
    "voting_room": "quiet side room",
    "seer_room": "quiet cottage",
    "guard_room": "watch cottage",
    "morgue": "clinic back room",
    "wolf_den": "secluded forest clearing",
    "dormitory": "shared dormitory",
}


def _agent_facing_location_name_en(world: World, location: Location | None) -> str:
    if not location:
        return "unknown location"
    local_id = str(location.location_id or "").split(":")[-1]
    if werewolf_enabled(world) and not werewolf_publicly_revealed(world) and local_id in _WEREWOLF_LOCKED_LOCATION_NAMES_EN:
        return _WEREWOLF_LOCKED_LOCATION_NAMES_EN[local_id]
    return location_label(location, "en")


def build_turn_context(session: Session, world: World, agent: Agent, *, reaction: bool = False, trigger_text: str | None = None) -> tuple[str, dict[str, str]]:
    context = build_turn_context_with_options(session, world, agent, reaction=reaction, trigger_text=trigger_text)
    return context.prompt, context.ref_map


def build_turn_context_with_options(session: Session, world: World, agent: Agent, *, reaction: bool = False, trigger_text: str | None = None) -> TurnContext:
    ensure_v5_agent_state(agent)
    ensure_v6_agent_state(agent)
    write_drive_state(world, agent)
    location = agent.location.location if agent.location else None
    _apply_identity_reveals_from_recent_events(session, world, agent)
    visible = build_visible_people(session, agent, world.current_world_time_minutes, persist=False)
    tools = available_tools(agent, location, reaction=reaction, session=session)
    state = agent.dynamic_state
    survival_enabled = survival_needs_enabled(world)
    prompt_settings = _prompt_settings(world)
    language = world_language(world)
    output_language_rule = action_language_instruction(language)
    memory_limit = _prompt_int(prompt_settings, "memory_limit", 48, 0, 240)
    recent_event_limit = _prompt_int(prompt_settings, "recent_event_limit", 22, 0, 240)
    recent_self_event_limit = _prompt_int(prompt_settings, "recent_self_event_limit", 14, 0, 120)
    action_option_limit = min(60, _prompt_int(prompt_settings, "action_option_limit", 60, 20, 500))
    traits = agent.traits
    desires = agent.desires_json or {}
    economy = update_derived_economy(agent)
    wallet = agent.wallet_json or {}
    housing = wallet.get("housing") or {}
    home_location_id = housing.get("home_location_id")
    home_location = session.get(Location, home_location_id) if home_location_id else None
    current_location_name = werewolf_agent_facing_location_name(world, location)
    current_location_description = werewolf_agent_facing_location_description(world, location)
    home_location_name = werewolf_agent_facing_location_name(world, home_location) if home_location else "未知"
    hedonic = wallet.get("hedonic_state") or {}
    broker = wallet.get("broker_account") or {}
    memory_pool_limit = 0 if memory_limit <= 0 else min(320, max(memory_limit * 6, 60))
    if memory_pool_limit:
        recent_memories = list(
            session.execute(
                select(Memory)
                .where(Memory.agent_id == agent.agent_id, Memory.archived.is_(False))
                .order_by(Memory.memory_id.desc())
                .limit(memory_pool_limit)
            ).scalars()
        )
        important_memories = list(
            session.execute(
                select(Memory)
                .where(Memory.agent_id == agent.agent_id, Memory.archived.is_(False), Memory.importance >= 45)
                .order_by(Memory.importance.desc(), Memory.memory_id.desc())
                .limit(memory_pool_limit)
            ).scalars()
        )
        memory_by_id = {memory.memory_id: memory for memory in recent_memories + important_memories}
        memories = list(memory_by_id.values())
    else:
        memories = []
    if werewolf_enabled(world) and not werewolf_publicly_revealed(world):
        memories = [memory for memory in memories if not _memory_leaks_locked_werewolf(world, memory)]
    memory_lines = _memory_prompt_lines(memories, limit=memory_limit, language=language)
    recent_events = list(
        session.execute(
            select(Event)
            .where(Event.world_id == world.world_id)
            .where((Event.location_id == (agent.location.location_id if agent.location else "")) | (Event.actor_agent_id == agent.agent_id) | (Event.target_agent_id == agent.agent_id))
            .order_by(Event.event_id.desc())
            .limit(recent_event_limit)
        ).scalars()
    )
    recent_self_events = list(
        session.execute(
            select(Event)
            .where(Event.world_id == world.world_id, Event.actor_agent_id == agent.agent_id)
            .where(Event.event_type.not_in(["narration", "narrator_failed", "tool_failed", "birth", "dream_summary"]))
            .order_by(Event.event_id.desc())
            .limit(recent_self_event_limit)
        ).scalars()
    )
    known = known_names(session, agent.agent_id)
    visual = visual_only(session, agent.agent_id)
    ref_map = {person.visible_ref: person.target_agent_id for person in visible}
    alive_count = session.execute(
        select(func.count(Agent.agent_id)).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
    ).scalar_one()
    dead_count = session.execute(
        select(func.count(Agent.agent_id)).where(Agent.world_id == world.world_id, Agent.lifecycle_state == "dead")
    ).scalar_one()
    population_note = f"活着的居民数: {alive_count}; 已死亡居民数: {dead_count}。"
    if alive_count == 1 and agent.lifecycle_state in {"alive", "critical"}:
        population_note += " 你确认这个世界里只剩你一个活着的居民。"
    werewolf_status_lines = werewolf_prompt_status_lines(session, world, agent)

    visible_lines = []
    for person in visible:
        call_hint = person.known_name if person.known_name and person.known_name != "未知" else person.short_label
        line = f"- {person.visible_ref}: 外貌={person.appearance}; 称呼建议={call_hint}; 已知姓名={person.known_name}; 已知性别={person.known_gender}; 明显状态={person.obvious_state}"
        if person.previous_seen_note:
            line += f"; {person.previous_seen_note}"
        visible_lines.append(line)
    body_drive_lines = drive_prompt_lines(agent)
    corpse_lines = visible_corpse_prompt_lines(session, world, agent)
    corpse_rule_lines = corpse_rules_prompt_lines(session, world, agent)
    pending_social_lines = pending_social_request_prompt_lines(session, agent, world)
    pending_force_lines = pending_force_attempt_prompt_lines(session, agent, world)

    needs = []
    if survival_enabled and state.satiety < 20:
        needs.append("你非常饥饿")
    if survival_enabled and state.hydration < 20:
        needs.append("你非常口渴")
    if state.energy < 15:
        needs.append("你非常疲惫")
    if state.social < 20:
        needs.append("你感到孤独")
    if state.fun < 20:
        needs.append("你感到无聊")
    if state.stress > 80:
        needs.append("你极度紧张")
    meal_note = _meal_note(world.current_world_time_minutes, agent) if survival_enabled else ""
    routine_notes = _routine_notes(session, world, agent, visible, economy, housing, survival_enabled=survival_enabled)
    pregnancy_notes = _pregnancy_prompt_lines(session, world, agent, visible)
    motivation_notes = _motivation_notes(world, agent, economy, housing)
    social_order_notes = _social_order_notes(session, world, agent, list(recent_events))
    worldview_lines = _worldview_prompt_lines(world, agent)
    notice_board_lines = notice_board_prompt_lines(world, location)
    hygiene_note = location_hygiene_prompt_line(world, location.location_id if location else None)
    working_note = _working_prompt_line(agent, world.current_world_time_minutes, language=language)
    trait_lines = trait_prompt_lines(traits)
    tool_context_mode = str((agent.tool_learning_json or {}).get("tool_context_mode") or "dynamic")
    action_options = build_action_options(session, world, agent, tools, ref_map, reaction=reaction, limit=action_option_limit)
    action_menu = format_action_options_for_prompt(action_options, language=language)
    if tool_context_mode == "all":
        fixed_catalog = format_tools_for_prompt(list(sorted(TOOL_SPECS.values(), key=lambda item: item.tool_name)))
        top_tool_section = (
            "【固定工具集】\n"
            "这是稳定的完整工具目录，用于让模型理解这个世界全部工具语义并提高提示词缓存命中率。"
            "不要直接输出工具名、JSON 或参数；真正可执行的本回合选择仍在后文【当前地点】的 AOHP 行动编号里。\n"
            f"{output_language_rule}\n"
            f"{fixed_catalog}\n"
        )
        location_tool_section = f"固定工具目录: 见顶部【固定工具集】。\n【行动编号协议 AOHP】\n本回合可执行 AOHP 行动选项:\n{action_menu}"
    else:
        top_tool_section = ""
        location_tool_section = (
            "【行动编号协议 AOHP】\n"
            "本回合真正能做的事只在下面这些行动选项中；你只能选一个编号。"
            "后端负责解释编号、校验规则和结算结果；你负责决定意图和写出真实中文表达。\n"
            f"{output_language_rule}\n"
            f"行动选项:\n{action_menu}"
        )
    survival_basics = [
        "你像普通人一样需要稳定吃饭、喝水、睡觉、清洁身体、维持一点社交和娱乐；这些不是额外任务，而是日常生活的一部分。",
        "水通常免费，但饭需要花钱；钱不够时，找工作、打零工、求助、借钱或领取援助都比硬撑更现实。",
    ] if survival_enabled else [
        "这个世界关闭了饥饿和口渴系统；你不需要为了生存吃饭喝水，也不会因饥饿口渴衰减或死亡。",
        "食物和饮品可以作为社交、约会、消费或氛围选择存在，但不是维持生命的硬需求。",
    ]
    meal_rule_line = (
        "饭点到了会出现在当前状态里。水是免费的，但饭需要花钱购买；没钱吃饭时要优先工作、找工作、打零工或向别人求助。"
        if survival_enabled
        else "餐饮在这个世界只作为生活氛围、社交或约会场景存在，不是生存压力。"
    )
    survival_rule_line = (
        "身体需求优先级高于空转：水分/饱腹/体力偏低时，优先喝水、吃饭、使用随身补给、去食堂/水源、求助或领取社区援助。"
        if survival_enabled
        else "身体需求优先级高于空转：体力、清洁、压力、社交和乐趣偏低时，优先睡眠、休息、清洁、换地点、社交或娱乐；饥饿口渴不会成为硬性威胁。"
    )

    shared_prompt = str((world.settings_json or {}).get("collective_core_prompt") or "").strip()
    shared_section = f"【全体核心提示词】\n{shared_prompt[:20000]}\n" if shared_prompt else ""

    if language == "en":
        prompt = _build_english_turn_prompt(
            session=session,
            world=world,
            agent=agent,
            location=location,
            home_location=home_location,
            current_location_name=current_location_name,
            current_location_description=current_location_description,
            home_location_name=home_location_name,
            state=state,
            traits=traits,
            desires=desires,
            economy=economy,
            wallet=wallet,
            housing=housing,
            hedonic=hedonic,
            broker=broker,
            visible=visible,
            visible_lines=visible_lines,
            memories=memories,
            memory_lines=memory_lines,
            recent_events=recent_events,
            recent_self_events=recent_self_events,
            known=known,
            visual=visual,
            alive_count=alive_count,
            dead_count=dead_count,
            body_drive_lines=body_drive_lines,
            corpse_lines=corpse_lines,
            corpse_rule_lines=corpse_rule_lines,
            pending_social_lines=pending_social_lines,
            pending_force_lines=pending_force_lines,
            needs=needs,
            routine_notes=routine_notes,
            pregnancy_notes=pregnancy_notes,
            motivation_notes=motivation_notes,
            social_order_notes=social_order_notes,
            worldview_lines=worldview_lines,
            trait_lines=trait_lines,
            action_menu=action_menu,
            shared_prompt=shared_prompt,
            trigger_text=trigger_text,
            survival_enabled=survival_enabled,
            working_note=working_note,
        )
        return TurnContext(prompt=prompt, ref_map=ref_map, action_options=action_options)

    prompt = f"""{top_tool_section}
{shared_section}
【身份】
姓名: {agent.chosen_name}
性别身份: {agent.gender_identity if agent.gender_publicity else '不愿公开'}
外貌: {agent.appearance_full}
说话风格: {agent.speaking_style}
自我外貌认知: 你清楚知道自己现在的外貌是“{agent.appearance_full}”。这不是旁观者秘密，而是你对自己身体、衣着和可被看见特征的基本认知。
人格倾向: openness={traits.openness}, caution={traits.caution}, sociability={traits.sociability}, empathy={traits.empathy}, curiosity={traits.curiosity}, discipline={traits.discipline}, aggression={traits.aggression}, honesty={traits.honesty}, creativity={traits.creativity}, neuroticism={traits.neuroticism}
属性作用:
{chr(10).join('- ' + note for note in trait_lines)}
初始目标: {agent.initial_goal}
intro_policy: {agent.intro_policy}

【当前状态】
时间: {format_world_time(world.current_world_time_minutes)}
地点: {current_location_name}
你的住所: {home_location_name}
地点公共卫生: {hygiene_note}
动态属性: health={state.health:.0f}, energy={state.energy:.0f}, satiety={state.satiety:.0f}, hydration={state.hydration:.0f}, hygiene={state.hygiene:.0f}, social={state.social:.0f}, fun={state.fun:.0f}, stress={state.stress:.0f}, mood={mood_label(state.mood)}
世界人口: {population_note}
特殊状态:
{chr(10).join('- ' + note for note in werewolf_status_lines) if werewolf_status_lines else '- 当前没有公开特殊规则状态。'}
钱包/工作: money={wallet_money(agent)}, job={(agent.work_json or {}).get('job') or '无'}, work_fatigue={(agent.work_json or {}).get('fatigue', 0)}, burnout={(agent.work_json or {}).get('burnout', 0)}, overtime_shifts={(agent.work_json or {}).get('overtime_shifts', 0)}, sleep_debt_minutes={desires.get('sleep_debt_minutes', 0)}
工作状态: {working_note or '当前不在工作中'}
经济压力: net_worth={economy.get('net_worth')}, total_debt={economy.get('total_debt')}, credit_score={economy.get('credit_score')}, debt_stress={economy.get('debt_stress')}, rent_due_day={housing.get('next_rent_due_day')}, rent_per_10_days={housing.get('rent_per_10_days')}, homeless={housing.get('homeless')}, luxury_threshold={hedonic.get('luxury_threshold')}, deprivation_pain={hedonic.get('deprivation_pain')}, broker_equity={broker.get('equity') if broker else '未开户'}
欲望压力: joy={desires.get('joy', 50)}, boredom={desires.get('boredom', 0)}, loneliness={desires.get('loneliness', 0)}, survival_pressure={desires.get('survival_pressure', 0)}

【内部动机/奖惩倾向】
{chr(10).join('- ' + note for note in motivation_notes) or '- 当前没有特别强的奖惩压力，可以按性格和目标自由行动。'}

【内在奖惩/痛苦感知】
{chr(10).join('- ' + note for note in body_drive_lines) or '- 当前身体没有明显痛苦。'}

【社会观察】
{chr(10).join('- ' + note for note in social_order_notes) or '- 社区暂时没有明显秩序危机；你仍然可以主动发起活动或提出规则。'}

【世界观特有规则】
{chr(10).join('- ' + note for note in worldview_lines) or '- 当前世界观没有额外规则说明。'}

【需求压力】
{('；'.join(needs) if needs else '没有压倒性的身体需求，但仍要照顾长期状态。')}
{meal_note}

【基础生活常识】
{chr(10).join('- ' + note for note in survival_basics)}
- 夜里 22:00 之后通常该准备睡觉，睡眠非常重要；如果不在住所，通常可以用 return_home 回家再 sleep；如果无家可归、回不去、或你主动选择在外面将就，也可以用 sleep_rough 露宿睡觉。系统不会替你强制睡觉，但不睡会承担后果。
- 睡不够 8 小时会逐渐影响体力、压力和健康；连续清醒太久会很危险。
- 加班可以一次赚更多钱，但会透支体力、饱腹、水分、情绪和睡眠；这是一种“用健康换钱”的选择，只在你觉得值得时才做。
- 清洁低时要洗澡或清洁；长期不清洁会增加生病风险。
- 公共卫生不是强制义务：人流多、无人打扫的地点会变脏，脏地点会让在场居民更容易变脏。你可以自愿打扫当前地点，也可以提出轮流打扫、雇清洁员或互助维护的社区规则；别人可以同意、拒绝或无视。
- 你可以有自己的性格和选择，也可以熬夜、拒绝社交或冒险，但要意识到这些选择会带来后果。

【生活提醒】
{chr(10).join('- ' + note for note in routine_notes) or '- 暂时没有特别提醒。你可以按自己的想法行动。'}

【孕期与照护提醒】
{chr(10).join('- ' + note for note in pregnancy_notes) or '- 当前没有需要特别提醒的孕期或照护状态。'}

【记忆】
{chr(10).join(memory_lines) or '暂无可用记忆。'}

【记忆使用规则】
- 这些记忆按“长期/摘要/重要事实 + 最近事件”筛选，目的是保持连续性和准确性，不是把所有旧事都塞进上下文。
- 最近清晰发生的事实优先于较旧、较模糊的摘要；摘要是压缩过的人生背景，不要把它当成刚刚发生的新事件。

【身份知识】
已知姓名: {', '.join(k.known_name for k in known if k.known_name) or '暂无'}
只知道外貌: {', '.join(concise_person_label(v.appearance_snapshot, fallback='某个陌生人') for v in visual) or '暂无'}

【附近可见人物】
{chr(10).join(visible_lines) or '附近没有其他可见居民。'}

【当前地点公示牌】
{chr(10).join('- ' + note for note in notice_board_lines) or '- 当前地点没有可读取的公示牌内容。'}

【多人空间规则】
- 同地点的人都可能听见公开话语，但听见不等于被点名；只有被行动编号绑定、被叫到已知姓名/可见编号，或明显属于“大家/谁能帮我”这类群体发言的人，才更应该立刻回应。
- 你想让某个人更清楚意识到是在叫 TA，可以在正文里写出你已知的姓名；不知道名字时不要编造姓名，要使用【附近可见人物】里的短外貌称呼。
- 对某个具体人物说话时，尽量喊已知姓名；不知道姓名时，先面对面询问姓名。未知姓名时优先使用【附近可见人物】里的“称呼建议”，不要在台词里说“附近人物A/B”，也不要复述整段外貌。称呼必须像普通人说话一样短，尽量不超过10个字，例如“那个蓝色头发的人”“那个黑色长直发的人”。多人同场景时，不要只说“你/您”来指某个人。
- 如果你同时收到多个人的邀请/请求，每个请求都是独立事件；你可以选择先回应其中一个、拒绝其中一个、暂时忽略，不能把 A 的请求误当成 B 的请求。

【待回应请求】
{chr(10).join('- ' + note for note in pending_social_lines) or '当前没有同地点可回应的待处理请求。'}

【待处理突然动作/边界事件】
{chr(10).join('- ' + note for note in pending_force_lines) or '当前没有同地点需要你立刻处理的突然动作或边界事件。'}

【附近可见尸体】
{chr(10).join(corpse_lines) or '当前地点没有可见尸体。'}

【尸体与环境规则】
{chr(10).join('- ' + note for note in corpse_rule_lines) or '- 当前没有尸体环境规则需要特别处理。'}

【当前地点】
描述: {current_location_description}
可达地点: {', '.join(werewolf_agent_facing_location_name(world, session.get(Location, loc_id)) for loc_id in adjacent_location_ids(session, location) if session.get(Location, loc_id))}
{location_tool_section}

【最近公开事件】
{chr(10).join('- ' + sanitize_event_for_agent(session, agent, event)[:180] for event in reversed(recent_events)) or '暂无最近事件。'}

【你最近做过的行动】
{chr(10).join('- ' + event.event_type + ': ' + sanitize_event_for_agent(session, agent, event)[:160] for event in reversed(recent_self_events)) or '暂无。'}

【规则】
- 只从【行动选项】中选一个编号；不要编造编号外的行动。
- 不要自己决定数值变化、成败、伤害、怀孕、犯罪、收益或世界状态；这些都由后端硬规则结算。
- 行动菜单可能把多个目标折叠到同一个行动下；如果选项标注“目标=编号”，第一行必须写 [编号:目标编号]，目标编号只能从该选项下面的目标列表里选。
- 不知道姓名不得假装知道；可以按外貌认人。需要姓名的行动只有在菜单里出现时才能选。
- 对同地点所有人公开说话时，选“公开说话”；对某个可见人物行动时，选带目标列表的对应行动并在第一行写目标编号。普通聊天、请求、安慰、邀请、告别、设边界都应该在第二行开始写出你真实想说的话。
- 公开说话同地点的人都可能听见；如果你想让某个具体的人更容易意识到你在叫 TA，请在正文里喊对方已知姓名或短外貌称呼。你不知道姓名时不要硬编，也不要把“附近人物A/B”当成台词里的自然称呼。
- 不要把中文代词、临时编号或短外貌称呼和敬称混用；禁止写“你さん”“TAさん”“他さん”“她さん”“附近人物Aさん”“那个棕色长发的人小姐”。不知道名字时用【附近可见人物】里的短外貌称呼；要么说“那个棕色长发的人”，要么说“那个棕色长发的小姐”，不要复述“粉色及腰长直发；灰色眼瞳 | ...”这类完整外貌档案。
- 请求类行为和突然/强制类行为含义不同：请求是等待对方接受/拒绝；突然/强制是未先询问就尝试行动，可能被察觉、躲开、抗议或事后造成关系/司法后果。普通安慰和实际帮忙不是默认犯罪或骚扰，只有当事人/被点名者才需要重点判断是否越界；旁观者可以听见和误解，但不要无缘无故把自己当成目标。同一个事实的含义由当事人的关系、性格、记忆和后续理解决定。
- 连续重复同类行动会无聊并降低体验。已经观察/自检/闲聊过时，优先换成移动、吃喝、睡眠、清洁、工作、写记忆、阅读、娱乐、求助或处理关系。
- {survival_rule_line}
- 痛苦不是装饰文本：当你严重脱水、饥饿、困倦、濒死、肮脏、被尸臭影响或情绪崩溃时，可以硬撑、苦笑或嘴硬，但不能像完全没事一样轻松快乐。
- 睡觉必须选 sleep、return_home 后睡觉或 sleep_rough；只在台词里说“我要睡了”不会让身体休息。rest 只是短休，不能代替长睡眠。
- 犯罪结果和司法后果由后端硬规则判定；越界、股票、借贷、房租、工作、怀孕、生子、尸体腐烂等后果也由后端判定。你可以追求欲望和幸福，也可以冒险或作恶，但世界会记录代价。
- 如果同地点多个人说话，你可以公开回应所有人，也可以先回应最急的一人并说明稍后再答。离开前礼貌告别通常能减少冷落感。
- 如果刚才有人直接问你的名字、请求你回应、点到你的姓名或短外貌称呼，优先处理这个问题；不要在没有解释的情况下突然移动离开。
- 一次发言只推进一个主要话题。先回应对方刚才的话，再开启新话题；不要在同一句里同时发起多个无关议题。
- 刚刚在同地点听到的自我介绍、请求、拒绝、约定和地点状态属于短期记忆；不要下一轮马上装作完全不知道。
- 如果附近有人正在睡觉，普通说话不一定能被听清；确实有急事才叫醒。
- 婴儿/幼儿不是小号成人：他们不会理解复杂恋爱、犯罪、债务或成人社交请求；对他们优先使用查看状态、喂食、安抚、抱起、哄睡、照护和简单教学。
- {meal_rule_line}
- {f'【刚才发生了什么】{trigger_text}' if trigger_text else ''}

【输出行动头】
不要解释，不要 Markdown，不要使用大括号结构。
- 第一行只写行动头，编号必须来自【行动选项】。
- 如果行动带 [目标=编号]，第一行写 [编号:目标编号]，例如 [66:1]；也可以写 [66 1]。
- 如果行动带 [值=小时] / [值=金额] / [值=数量]，第一行写 [编号:数值]。
- 如果行动带 [台词] 或 [正文]，从第二行开始直接写正文；不要加引号，不要写成键值对。
- {output_language_rule}
- 如果行动带 [台词]，第二行之后只能写“你这个角色亲口说出来的话”。只能是第一人称自然发言，不能夹旁白、动作描写、心理描写、舞台指示或第三人称叙述；未知姓名时使用短外貌称呼，禁止把完整外貌资料复制进台词。
- 不要写成 “……。”我撩头发，目光扫过众人，“……。” 这种混合格式；动作会由后端根据工具生成，你只负责说出口的句子。
- 不要在台词外层再套中文引号或英文引号；也不要写“我说：”“她说：”“旁白：”。如果你想沉默，就选择不需要台词的行动。
- 后端只解析第一行行动头，第二行之后会作为原始台词/正文保存。
示例:
[03]
我想认真问你一件事。
示例:
[04]
早上好。我刚搬到这里，想和大家打个招呼。我叫椎名立希，住在5号小屋。
示例:
[08:8]
"""
    return TurnContext(prompt=prompt, ref_map=ref_map, action_options=action_options)



def _memory_leaks_locked_werewolf(world: World, memory: Memory) -> bool:
    if str(memory.memory_type or "") == "werewolf":
        return True
    return werewolf_agent_text_locked(world, memory.content or "")


def _memory_prompt_lines(memories: list[Memory], *, limit: int, language: str = "zh") -> list[str]:
    if limit <= 0:
        return []
    deduped: list[Memory] = []
    seen: set[str] = set()
    for memory in memories:
        key = _memory_prompt_key(memory.content or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(memory)
    if not deduped:
        return []

    important_types = {"summary", "long", "relationship", "werewolf", "identity", "pregnancy", "birth", "childcare", "diary"}
    persistent_keywords = (
        "死亡", "死", "昏", "晕倒", "危急", "救", "偷", "抢", "攻击", "监狱", "怀孕", "孕", "出生", "孩子", "婴儿", "宝宝", "照护", "监护",
        "表白", "恋爱", "喜欢", "分手", "道歉", "拒绝", "承诺", "约定", "求助", "名字", "自我介绍", "房租", "无家可归",
        "规则", "会议", "投票", "票型", "狼人", "预言家", "验尸", "守卫", "阵营", "查验", "出局", "夜袭",
    )

    def score(memory: Memory) -> tuple[float, int, int]:
        text = memory.content or ""
        kind_score = 0.0
        if memory.memory_type in important_types:
            kind_score += 80.0
        if any(keyword in text for keyword in persistent_keywords):
            kind_score += 45.0
        # 重要度和最近性同时起作用：高重要旧记忆不会被挤掉，刚发生的事也不会丢。
        recency = min(80.0, max(0.0, int(memory.created_world_time or 0) / 120.0))
        return (kind_score + float(memory.importance or 0) * 1.7 + recency, int(memory.created_world_time or 0), int(memory.memory_id or 0))

    # 先取重要连续事实，再用最近事实补齐。最后按世界时间排列，让上下文像连续经历而不是乱序碎片。
    selected: list[Memory] = []
    selected_ids: set[int] = set()
    for memory in sorted(deduped, key=score, reverse=True):
        if len(selected) >= max(4, limit // 2):
            break
        selected.append(memory)
        selected_ids.add(int(memory.memory_id or 0))
    for memory in deduped:  # deduped 原本按 memory_id desc，补最近。
        if len(selected) >= limit:
            break
        mid = int(memory.memory_id or 0)
        if mid in selected_ids:
            continue
        selected.append(memory)
        selected_ids.add(mid)
    selected = selected[:limit]
    selected.sort(key=lambda m: (int(m.created_world_time or 0), int(m.memory_id or 0)))
    return [_format_memory_prompt_line(memory, language=language) for memory in selected]


def _memory_prompt_key(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    cleaned = cleaned.replace("『", "").replace("』", "").replace("“", "").replace("”", "")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in "一二三四五六七八九十百千万年月日天点分时：:，,。.!?！？")
    return cleaned[:120]


def _format_memory_prompt_line(memory: Memory, *, language: str = "zh") -> str:
    kind_map = {
        "summary": "摘要",
        "long": "长期",
        "short": "近期",
        "relationship": "关系",
        "werewolf": "狼人杀",
        "identity": "身份",
        "diary": "日记",
        "pregnancy": "孕育",
        "birth": "出生",
        "childcare": "育儿",
        "event": "事件",
    }
    kind = kind_map.get(str(memory.memory_type or "short"), str(memory.memory_type or "近期"))
    when = format_world_time(int(memory.created_world_time or 0))
    text = _clip_prompt_text(memory.content or "", 320)
    if language == "en":
        return f"- [{memory.memory_type or 'memory'} · {when} · importance {int(memory.importance or 0)}] {text}"
    return f"- [{kind} · {when} · 重要度{int(memory.importance or 0)}] {text}"


def _clip_prompt_text(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)] + "…"

def _prompt_settings(world: World) -> dict:
    raw = (world.settings_json or {}).get("prompt_settings")
    return dict(raw) if isinstance(raw, dict) else {}


def _prompt_int(settings_json: dict, key: str, fallback: int, minimum: int, maximum: int) -> int:
    try:
        value = int(settings_json.get(key, fallback))
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))



def _working_prompt_line(agent: Agent, world_time_minutes: int, *, language: str = "zh") -> str:
    work_json = agent.work_json or {}
    status = work_json.get("working_status") if isinstance(work_json, dict) else None
    if not isinstance(status, dict) or not status.get("active"):
        return ""
    until = int(status.get("until_world_time") or 0)
    if until and world_time_minutes > until:
        return ""
    job_name = str(status.get("job_name") or work_json.get("job") or "工作").strip() or "工作"
    location_id = str(status.get("location_id") or "").strip()
    remaining = max(0, until - int(world_time_minutes)) if until else 0
    hours = remaining / 60 if remaining else 0
    tone = str(status.get("employee_tone_hint") or "工作时请保持符合岗位的口吻，并在需要时像员工一样服务、回应、维持秩序。").strip()
    public_facing = bool(status.get("public_facing", True))
    if language == "en":
        location_note = f" at {location_id}" if location_id else ""
        time_note = f" About {hours:.1f} hours remain." if hours else ""
        service_note = " This is public-facing work; speak and act like staff when interacting with visitors." if public_facing else ""
        return f"On duty: {job_name}{location_note}.{time_note}{service_note} {english_safe_sentence(tone, fallback='Keep a suitable employee tone while working.')}".strip()
    location_note = f"，岗位地点={location_id}" if location_id else ""
    time_note = f"，剩余约 {hours:.1f} 小时" if hours else ""
    service_note = "；这是对外服务岗位，和来访者交流时要自然带有员工/店员/工作人员口吻" if public_facing else ""
    return f"正在工作中：{job_name}{location_note}{time_note}{service_note}。{tone}"


def _worldview_prompt_lines(world: World, agent: Agent) -> list[str]:
    settings_json = world.settings_json or {}
    lines: list[str] = []
    locked_werewolf = werewolf_enabled(world) and not werewolf_publicly_revealed(world)
    name = settings_json.get("worldview_name")
    if name and not locked_werewolf:
        lines.append(f"当前世界观: {name}。你应该把地点、工具和行动理解成这个世界的规则，而不是默认现代小镇。")
    elif locked_werewolf:
        lines.append("当前你只知道这里是一个普通村庄；没有人向你公开说明过任何特殊规则或隐藏安排。")
    if settings_json.get("worldview_id") and settings_json.get("worldview_id") != "default_modern_worldview":
        lines.append(
            "基础作息继承默认现代世界观：世界观剧情、探索、恋爱或战斗不会覆盖睡眠。22:00 后如果没有紧急收尾，优先回到【你的住所】真正 sleep；"
            "当前地点名称里带“家”也不一定是你的私人住所，以【当前状态】里的“你的住所”为准。"
        )
    for block in settings_json.get("worldview_prompt_blocks") or []:
        if isinstance(block, str):
            text = block.strip()
        elif isinstance(block, dict):
            title = str(block.get("title") or block.get("name") or "世界规则").strip()
            body = str(block.get("body") or block.get("content") or "").strip()
            text = f"{title}: {body}" if body else title
        else:
            continue
        if text and not (locked_werewolf and werewolf_agent_text_locked(world, text)):
            lines.append(text[:260])
    wallet = agent.wallet_json or {}
    state = wallet.get("worldpack_state") or {}
    world_key = str(settings_json.get("worldview_id") or settings_json.get("world_toolset_id") or "")
    if isinstance(state, dict):
        current = state.get(world_key)
        if current is None:
            for key, value in state.items():
                if str(key).startswith(world_key) or world_key.startswith(str(key)):
                    current = value
                    break
        if isinstance(current, dict):
            resources = current.get("resources") or {}
            progress = current.get("progress") or {}
            flags = current.get("flags") or []
            if resources and not locked_werewolf:
                lines.append("世界观资源: " + "、".join(f"{key}={value}" for key, value in sorted(resources.items())))
            if progress and not locked_werewolf:
                lines.append(f"世界观成长: level={progress.get('level', 1)}, exp={progress.get('exp', 0)}。")
            if flags and not locked_werewolf:
                lines.append("已触发世界观状态: " + "、".join(str(x) for x in flags[-8:]))
    if settings_json.get("werewolf_mode_enabled") and not locked_werewolf:
        try:
            from app.world.werewolf import werewolf_phase

            day, phase = werewolf_phase(world)
        except Exception:
            day, phase = 0, ""
        lines.append("当前村庄死亡事件已公开：讨论流程由主持推进，每名存活者按顺序发言一次；说完系统自动换人，不需要结束发言、反驳或跳过反驳工具。")
        lines.append("核心行动只有夜间身份能力、会议发言、公开投票。反驳、质疑、站边、弃疑都应写在自然发言里。")
        if day >= 2 and phase in {"morning", "discussion", "voting"}:
            lines.append("若昨夜有人遇害或发现尸体，这就是今天最重要的公共线索；发言和投票必须把尸体、夜袭、反应、票型放进去考虑。")
        if phase == "night":
            lines.append("夜晚：没有夜间能力的人会睡觉/离场等待天亮；有夜间能力的人应直接使用身份能力，不要空转闲聊。")
    return lines[:12]

def _motivation_notes(world: World, agent: Agent, economy: dict, housing: dict) -> list[str]:
    state = agent.dynamic_state
    desires = agent.desires_json or {}
    morality = agent.morality_json or {}
    survival_enabled = survival_needs_enabled(world)
    notes: list[str] = []
    if not state:
        return notes
    raw_awake_since = desires.get("awake_since_world_time")
    if raw_awake_since is None:
        raw_awake_since = agent.created_at_world_time if agent.created_at_world_time is not None else world.current_world_time_minutes
    awake_hours = max(0, world.current_world_time_minutes - int(raw_awake_since)) / 60
    sleep_pressure = max(0, int((awake_hours - 14) * 8)) + max(0, int(45 - state.energy))
    money = wallet_money(agent)
    rent = int(housing.get("rent_per_10_days") or 0)
    current_day = world.current_world_time_minutes // 1440 + 1
    due_day = int(housing.get("next_rent_due_day") or 999)
    money_pressure = 0
    if money < 6:
        money_pressure += 45
    elif money < 18:
        money_pressure += 25
    if rent and money < rent and due_day - current_day <= 2:
        money_pressure += 35
    moral_pressure = int(morality.get("justice", 55)) + int(morality.get("guilt_sensitivity", 55)) - int(morality.get("desire_for_reward", 45))
    if int(desires.get("survival_pressure", 0)) >= 35:
        if survival_enabled:
            notes.append("生存压力正在上升：吃饭、喝水、睡觉会带来明确的痛苦下降；硬撑、空转、加班或冒险会让身体账单继续累积。")
        else:
            notes.append("身体压力正在上升：睡眠、清洁、休息和调整节奏会带来明确的痛苦下降；硬撑、空转、加班或冒险会继续累积代价。")
    if sleep_pressure >= 35:
        notes.append(f"睡眠压力很强：你已连续清醒约 {awake_hours:.1f} 小时，睡觉会显著恢复体力并降低压力；不睡可能换来金钱、社交或刺激，但长期风险很高。")
    if money_pressure >= 35:
        notes.append("经济压力很强：工作、借贷、求助、节俭或犯罪都可能解决短期钱的问题，但它们分别会带来疲劳、债务、人情、痛苦或司法风险。")
    if int(desires.get("boredom", 0)) >= 55:
        notes.append("无聊感在推你寻找娱乐、创作、探索或社交；重复观察/自检不会给你多少奖励。")
    if int(desires.get("loneliness", 0)) >= 55:
        notes.append("孤独感在推你靠近别人、聊天、求助或建立关系；你也可以因警惕选择独处，但孤独不会凭空消失。")
    if state.stress >= 65:
        notes.append("压力已经很高：冥想、休息、说出不满、整理记忆或寻求帮助会降低痛苦；冲动行为可能短期释放但会留下后果。")
    if moral_pressure >= 70:
        notes.append("你的道德/内疚系统较强：帮助、守信、道歉、报警或提出互助建议更容易带来自我一致感；伤害别人会更容易形成愧疚和压力。")
    elif moral_pressure <= 35:
        notes.append("你对即时奖励更敏感：高收益、高刺激或越界行为会更有诱惑，但后端仍会记录犯罪、信任损失和司法风险。")
    return notes[:8]


def _social_order_notes(session: Session, world: World, agent: Agent, recent_events: list[Event]) -> list[str]:
    notes: list[str] = []
    instability_events = [event for event in recent_events if any(token in event.event_type for token in ["crime", "theft", "jail", "death", "critical", "eviction"])]
    if instability_events:
        notes.append("近期出现了犯罪、死亡、危机、驱逐或司法事件。关心秩序的居民可以召集社区讨论，提出普通安全建议、互助约定或做事办法；这只是提议，不会自动强制所有人服从。")
    law = agent.law_json or {}
    if law.get("victim_records"):
        notes.append("你自己有受害/损失记录。你可以报警、对质、原谅、寻求保护，也可以发起公共安全建议。")
    if law.get("criminal_records"):
        notes.append("你有犯罪记录。你可以隐藏、辩解、补偿、反思、再次犯罪或推动规则改革，但世界会继续记录这些选择。")
    alive_count = session.execute(select(func.count(Agent.agent_id)).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))).scalar_one()
    homeless_count = 0
    for other in session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))).scalars():
        if ((other.wallet_json or {}).get("housing") or {}).get("homeless"):
            homeless_count += 1
    if homeless_count and alive_count:
        notes.append(f"当前约有 {homeless_count}/{alive_count} 名居民处于无家可归状态。善良、理性或重视稳定的居民可能会提出临时庇护、免费出租、互助食物或治安规则。")
    return notes[:6]


def _meal_note(world_time: int, agent: Agent) -> str:
    minute = world_time % 1440
    meal = None
    if 7 * 60 <= minute <= 9 * 60:
        meal = "早饭"
    elif 12 * 60 <= minute <= 14 * 60:
        meal = "午饭"
    elif 18 * 60 <= minute <= 20 * 60:
        meal = "晚饭"
    if not meal:
        return ""
    last_meal = int((agent.desires_json or {}).get("last_meal_world_time") or -10**9)
    eaten_recently = world_time - last_meal <= 90
    if eaten_recently:
        return f"现在接近{meal}时间，但你刚吃过，可以自行决定是否继续吃。"
    return f"现在接近{meal}时间。你可以按饭点吃饭，也可以等真正饿了再吃；长期不规律会让身体状态变差。"


def _routine_notes(session: Session, world: World, agent: Agent, visible, economy: dict, housing: dict, *, survival_enabled: bool) -> list[str]:
    state = agent.dynamic_state
    if not state:
        return []
    notes: list[str] = []
    minute = world.current_world_time_minutes % 1440
    desires = agent.desires_json or {}
    raw_awake_since = desires.get("awake_since_world_time")
    if raw_awake_since is None:
        raw_awake_since = agent.created_at_world_time if agent.created_at_world_time is not None else world.current_world_time_minutes
    awake_since = int(raw_awake_since)
    awake_hours = max(0, world.current_world_time_minutes - awake_since) / 60
    location = agent.location.location if agent.location else None
    tags = set(location.tags_json or [])
    food_price = int(profile_for_agent(agent)["food_price"])

    is_sleep_time = minute >= 22 * 60 or minute < 6 * 60
    late_evening = 21 * 60 <= minute < 22 * 60
    if is_sleep_time:
        if "home" in tags:
            notes.append("现在已经是睡觉时间。你可以继续做自己的事，但长期熬夜会损害体力、心情和健康；如果没有更重要的理由，睡觉是合理选择。")
        else:
            notes.append("现在已经是睡觉时间。你不在住所；如果没有更重要的安排，可以考虑 return_home 回家睡，也可以在无家可归/不愿回家时用 sleep_rough 露宿。")
    elif late_evening:
        notes.append("现在接近睡觉时间。如果还想社交或工作，可以先安排收尾；睡不够 8 小时会逐渐带来负面效果。")
    if awake_hours >= 20:
        notes.append(f"你已经连续清醒约 {awake_hours:.1f} 小时。继续不睡会有严重负面效果，甚至可能昏倒或猝死。")
    elif awake_hours >= 15:
        notes.append(f"你已经连续清醒约 {awake_hours:.1f} 小时。现在适合开始考虑今晚睡多久。")
    if _recent_sleep_intent(session, world, agent):
        notes.append("你刚才说过想回去休息或睡觉。如果这仍是你的决定，下一步需要实际使用 return_home 回到住所并 sleep；如果不回家，也要用 sleep_rough 才会真正睡着。只说出来不会让身体休息。")

    if survival_enabled and state.hydration < 70:
        notes.append("水分已经下降。水是免费的，看到水源或随身有水时，及时喝水通常比拖到口渴更稳妥。")
    if survival_enabled and state.satiety < 70:
        if wallet_money(agent) >= food_price:
            notes.append("饱腹值已经下降。饭需要花钱买；正常吃饭能避免之后进入饥饿状态。")
        else:
            notes.append("饱腹值已经下降，但你钱不够买饭。可以考虑工作、打零工、求助或寻找社区援助。")
    if state.hygiene < 45:
        notes.append("清洁偏低，长期不清洁会提高生病风险；有水或住所时可以考虑清洁。")

    money = wallet_money(agent)
    rent = int(housing.get("rent_per_10_days") or 0)
    due_day = housing.get("next_rent_due_day")
    current_day = world.current_world_time_minutes // 1440 + 1
    if survival_enabled and money < food_price:
        notes.append("你现在的钱连一顿饭都不够。可以考虑找工作、做零工、求助、借款或其他你认为合适的办法。")
    elif rent and money < rent:
        notes.append("你手里的钱还不够下一次房租。继续不处理会带来住房压力。")
    if isinstance(due_day, int) and rent and due_day - current_day <= 1:
        notes.append("房租很快到期。你可以选择交租、赚钱、借钱、协商或承担拖欠后果。")
    if float(economy.get("total_debt") or 0) > 0:
        notes.append("你有债务。可以忽略、最低还款、提前还款或想办法增加收入；不同选择会影响压力和信用。")
    if _can_consider_overtime(world, agent, housing):
        notes.append("你现在可以考虑加班换更多钱，但这会挤压睡眠、增加疲劳和睡眠债，并可能伤害健康。是否值得由你自己决定。")

    if visible:
        notes.append("附近有人。你可以自然聊天，也可以不聊；如果要离开或不回应，礼貌说明通常能减少被冷落感。")
    return notes


def _pregnancy_prompt_lines(session: Session, world: World, agent: Agent, visible) -> list[str]:
    lines: list[str] = []
    if is_pregnant(agent):
        pregnancy = ((agent.family_json or {}).get("pregnancy_state") or {})
        started = int(pregnancy.get("started_world_time") or world.current_world_time_minutes)
        due = int(pregnancy.get("due_world_time") or (started + 10 * 1440))
        days = max(0, (world.current_world_time_minutes - started) // 1440)
        due_days = max(0, (due - world.current_world_time_minutes + 1439) // 1440)
        lines.append(
            f"你正在怀孕，已经大约第 {days + 1} 天，预计还剩约 {due_days} 天临近生产。怀孕会影响体力、风险和他人反应，但不会自动禁止工作、冲突、冒险或犯罪；是否硬撑、求助、休息、说明状态或做坏事，都按你的性格和处境选择，后果由后端规则结算。"
        )
    for person in visible:
        other = session.get(Agent, person.target_agent_id)
        if not other or other.agent_id == agent.agent_id or not is_pregnant(other):
            continue
        pregnancy = ((other.family_json or {}).get("pregnancy_state") or {})
        started = int(pregnancy.get("started_world_time") or world.current_world_time_minutes)
        days = max(0, (world.current_world_time_minutes - started) // 1440)
        known_name = person.known_name or other.chosen_name or person.visible_ref
        lines.append(
            f"{known_name} 正在怀孕，已经大约第 {days + 1} 天。你可以无视、照顾、询问、陪伴、调侃、嫉妒或按自己的性格反应，但不要把 TA 当成普通状态下完全不受影响的人。"
        )
    return lines[:8]


def _recent_sleep_intent(session: Session, world: World, agent: Agent) -> bool:
    recent = session.execute(
        select(Event)
        .where(Event.world_id == world.world_id, Event.actor_agent_id == agent.agent_id)
        .order_by(Event.event_id.desc())
        .limit(4)
    ).scalars()
    intent_words = ["睡", "休息", "回家", "回去", "小屋", "累了"]
    for event in recent:
        speech = str((event.payload or {}).get("speech") or "")
        if speech and any(word in speech for word in intent_words):
            return True
    return False


def _can_consider_overtime(world: World, agent: Agent, housing: dict) -> bool:
    state = agent.dynamic_state
    if not state:
        return False
    minute = world.current_world_time_minutes % 1440
    evening_or_night = minute >= 18 * 60 or minute < 5 * 60
    current_day = world.current_world_time_minutes // 1440 + 1
    rent = int(housing.get("rent_per_10_days") or 0)
    due_day = int(housing.get("next_rent_due_day") or 99)
    rent_pressure = bool(rent) and wallet_money(agent) < rent and due_day - current_day <= 2
    money_pressure = wallet_money(agent) < 18 or rent_pressure
    return bool(
        state.energy >= 38
        and state.hydration >= 38
        and state.satiety >= 38
        and int((agent.work_json or {}).get("burnout", 0)) < 85
        and (evening_or_night or money_pressure)
    )


def sanitize_event_for_agent(session: Session, observer: Agent, event: Event) -> str:
    world = session.get(World, observer.world_id)
    if world and werewolf_enabled(world) and not werewolf_publicly_revealed(world):
        if str(event.event_type or "").startswith("werewolf_") or werewolf_agent_text_locked(world, event.agent_visible_text):
            return "村庄里暂时没有公开解释清楚的异常消息。"
    text = event.agent_visible_text
    candidates = []
    for agent_id in [event.actor_agent_id, event.target_agent_id]:
        if agent_id and agent_id != observer.agent_id:
            target = session.get(Agent, agent_id)
            if target and target.chosen_name:
                knowledge = session.execute(
                    select(IdentityKnowledge).where(
                        IdentityKnowledge.observer_agent_id == observer.agent_id,
                        IdentityKnowledge.target_agent_id == agent_id,
                        IdentityKnowledge.name_known.is_(True),
                    )
                ).scalar_one_or_none()
                if not knowledge:
                    label = f"那个{target.appearance_short or '外貌可辨'}的人"
                    candidates.append((target.chosen_name, label))
    for name, label in candidates:
        text = text.replace(name, label)
    return text


def _format_world_time_en(minutes: int) -> str:
    day = minutes // 1440 + 1
    minute_of_day = minutes % 1440
    hour = minute_of_day // 60
    minute = minute_of_day % 60
    return f"Day {day} {hour:02d}:{minute:02d}"


def _safe_en_list(lines: list[str], *, fallback: str, limit: int = 8) -> str:
    cleaned: list[str] = []
    for line in lines[:limit]:
        safe = english_safe_sentence(line, fallback="").strip()
        if safe:
            cleaned.append(f"- {safe[:220]}")
    return "\n".join(cleaned) or f"- {fallback}"


def _safe_event_line_en(event: Event) -> str:
    text = event.agent_visible_text or event.viewer_text or event.event_type
    if cjk_count(text):
        actor = event.actor_agent_id or "system"
        target = f" -> {event.target_agent_id}" if event.target_agent_id else ""
        return f"{_format_world_time_en(event.world_time)} {event.event_type} ({actor}{target})"
    return f"{_format_world_time_en(event.world_time)} {text[:180]}"


def _visible_lines_en(visible) -> list[str]:
    lines: list[str] = []
    for person in visible:
        ref = person_ref_label(person.visible_ref, "en")
        appearance = english_safe_sentence(person.appearance, fallback="appearance is visible but not described in English")
        name = english_safe_label(person.known_name, fallback="unknown") if person.known_name and person.known_name != "未知" else "unknown"
        gender = gender_label(person.known_gender, "en")
        state = english_safe_sentence(person.obvious_state, fallback="no obvious abnormal state")
        note = english_safe_sentence(person.previous_seen_note, fallback="") if person.previous_seen_note else ""
        short_label = english_safe_sentence(person.known_name if person.known_name and person.known_name != "未知" else person.short_label, fallback="a visually identifiable person")
        line = f"- {ref}: appearance={appearance}; suggested_short_address={short_label}; known_name={name}; known_gender={gender}; obvious_state={state}"
        if note:
            line += f"; {note}"
        lines.append(line)
    return lines


def _build_english_turn_prompt(**ctx) -> str:
    session: Session = ctx["session"]
    world: World = ctx["world"]
    agent: Agent = ctx["agent"]
    location: Location | None = ctx["location"]
    home_location: Location | None = ctx["home_location"]
    state = ctx["state"]
    traits = ctx["traits"]
    desires = ctx["desires"]
    economy = ctx["economy"]
    wallet = ctx["wallet"]
    housing = ctx["housing"]
    hedonic = ctx["hedonic"]
    broker = ctx["broker"]
    visible = ctx["visible"]
    memories = ctx["memories"]
    memory_lines = ctx.get("memory_lines") or []
    recent_events = ctx["recent_events"]
    recent_self_events = ctx["recent_self_events"]
    known = ctx["known"]
    visual = ctx["visual"]
    alive_count = ctx["alive_count"]
    dead_count = ctx["dead_count"]
    action_menu = ctx["action_menu"]
    shared_prompt = ctx["shared_prompt"]
    trigger_text = ctx["trigger_text"]
    survival_enabled = ctx["survival_enabled"]
    working_note = str(ctx.get("working_note") or "")

    current_location_name = str(ctx.get("current_location_name") or location_label(location, "en"))
    current_location_description = str(ctx.get("current_location_description") or (location.description if location else ""))
    home_location_name = str(ctx.get("home_location_name") or location_label(home_location, "en"))
    public_gender = gender_label(agent.gender_identity if agent.gender_publicity else "private", "en")
    appearance = english_safe_sentence(agent.appearance_full, fallback="This resident's appearance is visible, but no English description is available.")
    speak_style = english_safe_sentence(agent.speaking_style, fallback="speaks naturally according to the situation")
    initial_goal = english_safe_sentence(agent.initial_goal, fallback="take care of basic needs and understand the world")
    name = english_safe_label(agent.chosen_name, fallback="Resident")
    shared_section = f"GLOBAL PROMPT FOR ALL AGENTS:\n{english_safe_sentence(shared_prompt, fallback=shared_prompt)[:20000]}\n\n" if shared_prompt else ""
    trait_lines = ctx["trait_lines"]
    trait_block = _safe_en_list(trait_lines, fallback="Traits affect tool priority, risk, social choices, and self-control.", limit=12)
    body_drive_block = _safe_en_list(ctx["body_drive_lines"], fallback="No strong bodily pain right now.", limit=10)
    motivation_block = _safe_en_list(ctx["motivation_notes"], fallback="No overwhelming reward or punishment pressure; act by personality and goals.", limit=8)
    routine_block = _safe_en_list(ctx["routine_notes"], fallback="No urgent reminder. You may act freely.", limit=10)
    pregnancy_block = _safe_en_list(ctx["pregnancy_notes"], fallback="No pregnancy or childcare state needs special attention.", limit=8)
    social_order_block = _safe_en_list(ctx["social_order_notes"], fallback="No obvious public-order crisis right now.", limit=6)
    worldview_block = _safe_en_list(ctx["worldview_lines"], fallback="No extra worldview rules are available in English.", limit=8)
    corpse_block = _safe_en_list(ctx["corpse_lines"], fallback="No visible corpses at this location.", limit=8)
    corpse_rule_block = _safe_en_list(ctx["corpse_rule_lines"], fallback="No corpse-related environmental rule needs attention right now.", limit=8)
    pending_social_block = _safe_en_list(ctx["pending_social_lines"], fallback="No pending social requests at this location.", limit=8)
    pending_force_block = _safe_en_list(ctx["pending_force_lines"], fallback="No sudden action or boundary event needs immediate handling.", limit=8)

    need_map = {
        "你非常饥饿": "you are very hungry",
        "你非常口渴": "you are very thirsty",
        "你非常疲惫": "you are very tired",
        "你感到孤独": "you feel lonely",
        "你感到无聊": "you feel bored",
        "你极度紧张": "you are extremely stressed",
    }
    needs_en = [need_map.get(item, english_safe_label(item, fallback="need pressure")) for item in ctx["needs"]]
    needs_text = "; ".join(needs_en) if needs_en else "No overwhelming bodily need, but long-term self-care still matters."

    visible_block = "\n".join(_visible_lines_en(visible)) or "No other visible residents nearby."
    known_names = [english_safe_label(k.known_name, fallback="known person") for k in known if k.known_name]
    visual_only_people = [english_safe_label(v.appearance_snapshot, fallback="a visually remembered person") for v in visual]
    adjacent_names = []
    if location:
        for loc_id in adjacent_location_ids(session, location):
            loc = session.get(Location, loc_id)
            if loc:
                adjacent_names.append(_agent_facing_location_name_en(world, loc))

    if memory_lines:
        memory_lines = [english_safe_sentence(line, fallback=line) for line in memory_lines]
    else:
        memory_lines = []
    recent_event_lines = [f"- {english_safe_sentence(sanitize_event_for_agent(session, agent, event), fallback=_safe_event_line_en(event))}" for event in reversed(recent_events)]
    self_event_lines = [f"- {event.event_type}: {english_safe_sentence(sanitize_event_for_agent(session, agent, event), fallback=_safe_event_line_en(event))}" for event in reversed(recent_self_events)]

    survival_basics = (
        "- You need regular food, water, long sleep, hygiene, some social contact, and some fun. These are daily life, not optional UI chores.\n"
        "- Water is usually free, but food costs money. If you cannot afford food or rent, work, odd jobs, requests for help, loans, or community aid are more realistic than simply enduring it."
        if survival_enabled
        else
        "- Hunger and thirst survival are disabled in this world. Food and drinks may still matter as social atmosphere, dates, or comfort, but they are not lethal needs.\n"
        "- Energy, hygiene, stress, social connection, and fun still matter."
    )
    meal_rule = (
        "Meal times may appear in the current status. Water is free, food costs money; if you cannot afford food, consider work, odd jobs, or asking for help."
        if survival_enabled else
        "Food and drinks are ambience, social, or date choices in this world, not hard survival pressure."
    )
    survival_rule = (
        "When water, fullness, or energy is low, prioritize drinking, eating, supplies, cafeteria/water locations, asking for help, or community aid."
        if survival_enabled else
        "When energy, hygiene, stress, social contact, or fun is low, prioritize sleep, rest, hygiene, movement, social contact, or play. Hunger and thirst are not hard threats."
    )

    trigger_line = f"\nWHAT JUST HAPPENED:\n{english_safe_sentence(trigger_text, fallback=str(trigger_text or ''))}\n" if trigger_text else ""

    return f"""ACTION OPTION CACHE PREFIX
AOHP ACTION-NUMBER PROTOCOL
This turn's executable actions have already been expanded into numbered options by the backend. Choose one number only. The number binds the tool, target, location, corpse, item, stock ticker, and hard-rule parameters.
All free text after the action header must be natural English. If the action requires speech, write only first-person spoken English from this character's mouth. Do not include narration, stage directions, thoughts, Chinese quotation marks, or third-person description.

{shared_section}IDENTITY
Name: {name}
Gender identity: {public_gender}
Appearance: {appearance}
Speaking style: {speak_style}
Trait sliders: openness={traits.openness}, caution={traits.caution}, sociability={traits.sociability}, empathy={traits.empathy}, curiosity={traits.curiosity}, discipline={traits.discipline}, aggression={traits.aggression}, honesty={traits.honesty}, creativity={traits.creativity}, neuroticism={traits.neuroticism}
Trait effects:
{trait_block}
Initial goal: {initial_goal}
intro_policy: {agent.intro_policy}

CURRENT STATUS
Time: {_format_world_time_en(world.current_world_time_minutes)}
Location: {english_safe_label(current_location_name, fallback=location_label(location, 'en'))}
Your home: {english_safe_label(home_location_name, fallback=location_label(home_location, 'en'))}
Dynamic stats: health={state.health:.0f}, energy={state.energy:.0f}, satiety={state.satiety:.0f}, hydration={state.hydration:.0f}, hygiene={state.hygiene:.0f}, social={state.social:.0f}, fun={state.fun:.0f}, stress={state.stress:.0f}, mood={mood_label_text(mood_label(state.mood), 'en')}
Population: alive residents={alive_count}; dead residents={dead_count}.
Wallet/work: money={wallet_money(agent)}, job={(agent.work_json or {}).get('job') or 'none'}, work_fatigue={(agent.work_json or {}).get('fatigue', 0)}, burnout={(agent.work_json or {}).get('burnout', 0)}, overtime_shifts={(agent.work_json or {}).get('overtime_shifts', 0)}, sleep_debt_minutes={desires.get('sleep_debt_minutes', 0)}
Work status: {working_note or 'Not currently on duty.'}
Economic pressure: net_worth={economy.get('net_worth')}, total_debt={economy.get('total_debt')}, credit_score={economy.get('credit_score')}, debt_stress={economy.get('debt_stress')}, rent_due_day={housing.get('next_rent_due_day')}, rent_per_10_days={housing.get('rent_per_10_days')}, homeless={housing.get('homeless')}, luxury_threshold={hedonic.get('luxury_threshold')}, deprivation_pain={hedonic.get('deprivation_pain')}, broker_equity={broker.get('equity') if broker else 'not opened'}
Desire pressure: joy={desires.get('joy', 50)}, boredom={desires.get('boredom', 0)}, loneliness={desires.get('loneliness', 0)}, survival_pressure={desires.get('survival_pressure', 0)}

MOTIVATION / REWARD-PUNISHMENT PRESSURE
{motivation_block}

EMBODIED PAIN AND DRIVE
{body_drive_block}

SOCIAL OBSERVATION
{social_order_block}

WORLDVIEW-SPECIFIC RULES
{worldview_block}

NEED PRESSURE
{needs_text}

BASIC LIFE COMMON SENSE
{survival_basics}
- After 22:00 it is usually time to prepare for sleep. Use return_home and then sleep if you want to truly sleep at home; use sleep_rough if homeless, unable to go home, or deliberately sleeping outside.
- Not sleeping enough gradually harms energy, stress, and health; staying awake too long is dangerous.
- Overtime can earn more money at once but trades away sleep, health, mood, water, and fullness.
- Low hygiene should be handled by washing or cleaning; long-term filth increases illness risk.
- You can act by your own personality, stay up late, refuse social contact, take risks, or commit crimes, but consequences are recorded by backend rules.

ROUTINE REMINDERS
{routine_block}

PREGNANCY AND CARE REMINDERS
{pregnancy_block}

MEMORY
{chr(10).join(memory_lines) or '- No available memories.'}

MEMORY USE RULES
- Memories are selected for continuity and accuracy: long-term facts, summaries, important events, and recent events are mixed deliberately.
- Recent concrete facts override older vague summaries. Summaries are compressed life context, not brand-new events.

IDENTITY KNOWLEDGE
Known names: {', '.join(known_names) or 'none'}
Visual-only knowledge: {', '.join(visual_only_people) or 'none'}

VISIBLE PEOPLE NEARBY
{visible_block}

MULTI-PERSON SPACE RULES
- People in the same location may hear public speech, but hearing does not mean being addressed. The person bound by the action option, a known name/ref named in the body, or an explicit group call should be prioritized for reaction.
- If you want someone to know you are calling them, say their known name. If you do not know a name, use a very short appearance-based address from suggested_short_address; do not invent a name, and do not copy a full appearance profile into speech.
- If several people invite or request something from you, each request is separate. You may accept one, decline another, answer one first, or ignore some of them.

PENDING REQUESTS
{pending_social_block}

PENDING SUDDEN ACTIONS / BOUNDARY EVENTS
{pending_force_block}

VISIBLE CORPSES NEARBY
{corpse_block}

CORPSE AND ENVIRONMENT RULES
{corpse_rule_block}

CURRENT LOCATION
Description: {english_safe_sentence(current_location_description, fallback='No English location description is available.')}
Reachable locations: {', '.join(adjacent_names) or 'none'}
Action options:
{action_menu}

RECENT PUBLIC EVENTS
{chr(10).join(recent_event_lines) or '- No recent events.'}

YOUR RECENT ACTIONS
{chr(10).join(self_event_lines) or '- None.'}

RULES
- Choose exactly one number from Action options; do not invent actions outside the menu.
- Do not decide numeric changes, success, damage, pregnancy, crime result, income, or world state. Backend rules settle those.
- Some actions collapse multiple targets under one option. If an option shows target=number, first line must be [number:target-number], and that target number must come from that option's target list.
- Do not pretend to know names you have not learned. You may recognize people by appearance. Name-required actions only appear when allowed.
- Public speech may be heard by everyone in the same location. To address someone clearly, call their known name or a short appearance-based address. Do not invent names or use Person A/B as a natural spoken nickname.
- If someone just asked your name, requested a response, called your known name, or used a short visual address for you, answer that before moving away unless you deliberately refuse or excuse yourself.
- Keep one main topic per utterance. Respond to what was just said before starting a new unrelated topic.
- Names, requests, refusals, promises, and location facts just heard in the same scene are short-term memory; do not immediately act as if you never heard them.
- Requests and sudden/forced actions are different. Requests wait for acceptance/decline. Sudden/forced actions try something without asking first and may be noticed, dodged, protested, or cause relationship/legal consequences. Comfort and practical help are not automatically crimes or harassment; the involved person evaluates whether it crosses a boundary.
- Repeating the same kind of action too much becomes boring. If you have already observed, checked yourself, or chatted repeatedly, consider movement, food/water, sleep, hygiene, work, writing, reading, play, asking for help, or relationship handling.
- {survival_rule}
- Pain is not decorative. If you are dehydrated, hungry, exhausted, dying, filthy, affected by corpse stench, or emotionally broken, you may endure, joke bitterly, or pretend toughness, but you cannot sound completely carefree.
- To actually sleep, choose sleep, return_home with sleep, or sleep_rough. Saying "I will sleep" in dialogue does not rest the body. rest is only a short break.
- Babies and toddlers are not miniature adults. Use status check, feeding, soothing, carrying, putting to sleep, care, and simple teaching for them.
- {meal_rule}
{trigger_line}
OUTPUT ACTION HEADER
Do not explain. Do not use Markdown. Do not use braces or JSON-like objects.
- First line is only the action header. The number must be from Action options.
- If the option has [target=number], first line: [number:target-number], for example [66:1].
- If the option has [value=hours] / [value=amount] / [value=quantity], first line: [number:value].
- If the option has [speech] or [body], write the body directly from the second line onward. Do not wrap it in quotes or key-value syntax.
- If the option has [speech], the body must contain only first-person words this character says aloud. No narration, stage directions, thoughts, or third-person description.
- Backend parses only the first line; all later lines are preserved as raw speech/body.
Examples:
[03]
I want to ask you something seriously.
[04]
Good morning. I just moved here and wanted to greet everyone. My name is Rikki, and I live in Cabin 5.
[08:8]
"""
