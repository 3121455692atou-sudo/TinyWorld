from __future__ import annotations

import random
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import apply_delta, recompute_mood
from app.agents.traits import clamp
from app.core.models import Agent, AgentLocation, Conversation, IdentityKnowledge, Location, Memory, World
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
}

DAY_SPEECH_LIMIT = 1
REBUTTAL_REPLY_LIMIT = 5
NO_EXECUTION_VOTE = "__no_execution__"

DEFAULT_GAME_START_MINUTE = 8 * 60
DEFAULT_MORNING_MINUTES = 4 * 60
DEFAULT_DISCUSSION_MINUTES = 6 * 60
DEFAULT_VOTING_MINUTES = 4 * 60
DEFAULT_NIGHT_MINUTES = 10 * 60
NIGHT_ACTION_ROLES = {"werewolf", "seer", "coroner", "guard"}

_CANONICAL_WEREWOLF_TOOL_NAMES = {
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


def werewolf_phase(world: World) -> tuple[int, str]:
    day, phase, _start_minute, _end_minute = werewolf_phase_window(world)
    return day, phase


def werewolf_phase_window(world: World) -> tuple[int, str, int, int]:
    """Return (game_day, phase, absolute_phase_start_minute, absolute_phase_end_minute).

    Day 1 is intentionally only free chat until dusk. Night abilities start on the
    first night, and the first structured round-table/vote happens on Day 2. This
    avoids the impossible story where a seer claims a Day-1 daytime result from a
    night that has not happened yet.
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


_LOCKED_LOCATION_NAMES = {
    "discussion_hall": "村庄会议厅",
    "voting_room": "议事侧厅",
    "seer_room": "安静小屋",
    "guard_room": "值守小屋",
    "morgue": "医务间",
    "wolf_den": "林间隐蔽处",
    "dormitory": "公共宿舍",
}

_LOCKED_LOCATION_DESCRIPTIONS = {
    "discussion_hall": "一间摆着长桌和长椅的普通会议厅，适合村民开会、休息和交换消息。",
    "voting_room": "会议厅旁边的安静侧厅，平时用于登记、等候或私下整理想法。",
    "seer_room": "一间安静的小屋，光线柔和，适合独处、阅读或整理思绪。",
    "guard_room": "一间靠近村口的值守小屋，里面有简单床铺和记录本。",
    "morgue": "医务间后侧的冷清小房间，用于临时处理伤病和突发事件。",
    "wolf_den": "林间一处隐蔽空地，平时只是偏僻、少有人来的地方。",
    "dormitory": "给临时住民休息的公共宿舍，房间简朴，能遮风避雨。",
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
    "阵营",
    "身份能力",
)


def _local_location_id(location_id: str | None) -> str:
    if not location_id:
        return ""
    return str(location_id).split(":")[-1]


def werewolf_publicly_revealed(world: World | None) -> bool:
    """Whether agent-facing prompts may mention Werewolf rules/roles.

    The host can keep an internal role/phase machine from minute 0, but residents are
    not told about the game on Day 1.  The public reveal happens after a body/night
    attack is discovered.  This separation prevents prompt leakage such as “今天要圆桌”
    before the characters have any in-world reason to know that.
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

    roles = _role_list_for_count(len(agents))
    rng = random.Random(f"werewolf:{world.seed}:{world.world_id}:{len(agents)}")
    rng.shuffle(roles)
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
        "winner": None,
        "public_revealed": False,
        "roles_revealed_to_agents": False,
        "hidden_first_night_attack_done": {},
    }
    settings["werewolf_state"] = state
    # Observer/UI debug data is allowed to know roles.  Agents themselves do not get
    # role memories or Werewolf vocabulary until a body is discovered.
    settings["werewolf_observer_roles"] = {agent_id: WEREWOLF_ROLE_LABELS.get(role, role) for agent_id, role in role_map.items()}
    world.settings_json = settings

    for agent in agents:
        desires = dict(agent.desires_json or {})
        desires.pop("werewolf", None)
        agent.desires_json = desires
    event = create_event(
        session,
        world=world,
        event_type="werewolf_setup",
        viewer_text="一套观察者可见的隐藏身份已经分配；居民暂时只知道自己来到普通村庄。",
        importance=90,
        color_class="important",
        visibility_scope="observer",
        payload={"role_count": _role_counts(role_map), "observer_can_see_roles": True, "agent_facing_locked": True},
        no_state_changed=True,
    )
    event_ids.append(event.event_id)
    return event_ids


def _role_list_for_count(count: int) -> list[str]:
    if count <= 5:
        wolf_count = 1
    elif count <= 8:
        wolf_count = 2
    elif count <= 12:
        wolf_count = 3
    else:
        wolf_count = 4
    roles: list[str] = ["werewolf"] * min(wolf_count, max(1, count - 1))
    if len(roles) < count and count >= 3:
        roles.append("seer")
    if len(roles) < count and count >= 4:
        roles.append("coroner")
    if len(roles) < count and count >= 7:
        roles.append("guard")
    while len(roles) < count:
        roles.append("villager")
    return roles[:count]


def _role_counts(role_map: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for role in role_map.values():
        label = WEREWOLF_ROLE_LABELS.get(role, role)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _seed_public_name_knowledge(session: Session, world: World, agents: list[Agent]) -> None:
    for observer in agents:
        for target in agents:
            if observer.agent_id == target.agent_id:
                continue
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


def _ensure_werewolf_secret_defaults(session: Session, world: World, state: dict[str, Any]) -> None:
    state.setdefault("public_revealed", False)
    state.setdefault("roles_revealed_to_agents", bool(state.get("public_revealed")))
    state.setdefault("hidden_first_night_attack_done", {})
    state.setdefault("wolf_consensus_need_discussion", {})
    state.setdefault("wolf_consensus_mismatches", {})
    if state.get("public_revealed"):
        return
    # Migrate older saves that wrote roles into desires at setup.  The role map stays
    # in observer state, but agent prompts must not see it before the public reveal.
    for agent in session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")).scalars():
        desires = dict(agent.desires_json or {})
        if desires.pop("werewolf", None) is not None:
            agent.desires_json = desires


def _reveal_werewolf_to_agents(session: Session, world: World, state: dict[str, Any], *, day: int, reason: str) -> None:
    if state.get("roles_revealed_to_agents") and state.get("public_revealed"):
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
        existing.setdefault("game_notes", [])
        desires["werewolf"] = existing
        agent.desires_json = desires
        if role == "werewolf" and fellow_wolves:
            wolf_text = f" 你知道狼人同伴是：{_names(session, fellow_wolves)}。夜袭需要所有存活狼人选择同一目标；如果意见不一致，今晚不会立刻成功，需要先密会统一目标。"
        elif role == "werewolf":
            wolf_text = " 这局目前只有你一个狼人，没有狼人同伴；夜里无需密会，直接选择夜袭目标。"
        else:
            wolf_text = ""
        _add_werewolf_memory(session, world, agent, f"第{day}天因{reason}，你知道了隐藏身份规则。你的身份是：{WEREWOLF_ROLE_LABELS.get(role, role)}。{wolf_text}", importance=96)
    _seed_public_name_knowledge(session, world, agents)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_day"] = day
    state["role_reveal_reason"] = reason


def sync_werewolf_phase(session: Session, world: World) -> list[int]:
    event_ids: list[int] = []
    if not werewolf_enabled(world):
        return event_ids
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    if not state.get("roles"):
        event_ids.extend(initialize_werewolf_roles(session, world))
        settings = dict(world.settings_json or {})
        state = dict(settings.get("werewolf_state") or {})
    _ensure_werewolf_secret_defaults(session, world, state)
    settings["werewolf_state"] = state
    world.settings_json = settings
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
        viewer_text=_phase_viewer_text(day, phase, public_revealed=werewolf_publicly_revealed(world)),
        importance=85,
        color_class="important",
        payload={"day": day, "phase": phase, "hide_clock": phase == "discussion"},
    )
    event_ids.append(event.event_id)
    return event_ids


def _phase_viewer_text(day: int, phase: str, *, public_revealed: bool) -> str:
    if not public_revealed:
        if phase == "night":
            return "夜幕降临，村庄逐渐安静下来，居民们准备休息。"
        return "村庄的一天继续推进，居民们仍把这里当作普通村庄生活。"
    if day == 2 and phase == "morning":
        return "清晨发生的死亡事件让幸存者意识到村里可能存在隐藏威胁，大家开始交换线索。"
    return f"村庄进入第{day}天的{phase_label(phase)}阶段。"


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
            # Before the first body is found, residents do not know roles or night
            # abilities.  Everyone sleeps; the host may create a hidden first-night
            # attack so Day 2 has an in-world reason to reveal the rules.
            event_ids.extend(_start_werewolf_night_sleepers(session, world, state, day, roles, roles_awake=False))
            if initialize:
                event_ids.extend(_scripted_unrevealed_night_attack(session, world, state, day))
            return event_ids
        night_actor_ids = {agent_id for agent_id, role in roles.items() if role in NIGHT_ACTION_ROLES}
        if night_actor_ids:
            event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=night_actor_ids))
        _teleport_night_roles(session, world, roles)
        event_ids.extend(_start_werewolf_night_sleepers(session, world, state, day, roles, roles_awake=True))
    elif phase == "morning":
        _recover_after_werewolf_night(session, world, state, day)
        event_ids.extend(_announce_werewolf_body_found(session, world, state, day))
        if initialize:
            event_ids.extend(_interrupt_scheduled_sleep(session, world, agent_ids=set(_living_agent_ids(session, world))))
            _teleport_alive(session, world, "village_square")
    return event_ids


def _recover_after_werewolf_night(session: Session, world: World, state: dict[str, Any], day: int) -> None:
    """Apply the implicit overnight rest that the Werewolf host represents.

    During night phases the host often advances straight to dawn after role tools
    resolve.  If we leave the ordinary life-sim awake timers untouched, players
    wake up as if they stood awake for fourteen hours and the next round-table is
    swallowed by hunger/fatigue collapse.  Werewolf night should still leave
    people hungry enough to seek breakfast, but not too broken to talk.
    """
    if day <= 1:
        return
    recovered = dict(state.get("overnight_recovered") or {})
    key = str(day)
    if recovered.get(key):
        return
    for agent in session.execute(
        select(Agent)
        .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
        .order_by(Agent.created_at_world_time, Agent.agent_id)
    ).scalars():
        _stabilize_werewolf_player(agent, world, minimum_energy=72, minimum_satiety=38, minimum_hydration=38, clear_unconscious=True)
    recovered[key] = True
    state["overnight_recovered"] = recovered


def _start_werewolf_night_sleepers(session: Session, world: World, state: dict[str, Any], day: int, roles: dict[str, str], *, roles_awake: bool = True) -> list[int]:
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
        if roles_awake and role in NIGHT_ACTION_ROLES:
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
    event_ids = [event.event_id]
    if not hidden:
        event_ids.extend(_check_werewolf_win(session, world))
    return event_ids


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
        return []
    if kill.get("blocked"):
        announced[key] = {"blocked": True}
        state["body_found_announced"] = announced
        return []
    target_id = str(kill.get("target_agent_id") or "")
    target = session.get(Agent, target_id) if target_id else None
    if not target:
        announced[key] = {"missing_target": target_id}
        state["body_found_announced"] = announced
        return []
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
    return [event.event_id]


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
        else:
            local = "dormitory"
        location_id = world_location_id(world.world_id, local)
        location = session.get(Location, location_id)
        if agent.location and location:
            agent.location.location_id = location_id
            agent.location.location = location
            agent.location.arrived_at_world_time = world.current_world_time_minutes


def werewolf_menu_tool_names(session: Session, world: World, agent: Agent) -> set[str]:
    if not werewolf_enabled(world) or agent.lifecycle_state == "dead":
        return set()
    if not werewolf_publicly_revealed(world):
        return set()
    state = werewolf_state(world)
    if state.get("winner"):
        return set()
    roles = state.get("roles") or {}
    role = roles.get(agent.agent_id) or (agent.desires_json or {}).get("werewolf", {}).get("role") or "villager"
    day, phase = werewolf_phase(world)
    names: set[str] = set()
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
        return False, "werewolf_disabled", "当前世界不是狼人杀模式。"
    if not werewolf_publicly_revealed(world):
        return False, "werewolf_not_revealed", "当前居民还不知道隐藏身份规则，不能使用狼人杀专用行动。"
    state = werewolf_state(world)
    if state.get("winner"):
        return False, "werewolf_ended", "这局狼人杀已经结束。"
    roles = state.get("roles") or {}
    role = roles.get(agent.agent_id) or (agent.desires_json or {}).get("werewolf", {}).get("role") or "villager"
    day, phase = werewolf_phase(world)
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
    return True, "", ""


def validate_werewolf_tool(session: Session, world: World, actor: Agent, tool_name: str, target: Agent | None = None) -> tuple[bool, str, str]:
    tool_name = _canonical_tool_name(tool_name)
    ok, reason, message = werewolf_tool_allowed(session, world, actor, tool_name)
    if not ok:
        return ok, reason, message
    state = werewolf_state(world)
    roles = state.get("roles") or {}
    if tool_name in {"werewolf_vote_by_name", "werewolf_kill_by_name", "werewolf_seer_check_by_name", "werewolf_guard_protect_by_name"}:
        if target is None:
            return False, "missing_known_name", "这个狼人杀行动需要一个已知姓名目标，请从菜单里选择带姓名的行动。"
        if target.lifecycle_state == "dead":
            return False, "target_dead", "目标已经出局，不能再作为本次行动目标。"
        if target.agent_id == actor.agent_id and tool_name in {"werewolf_vote_by_name", "werewolf_kill_by_name", "werewolf_seer_check_by_name"}:
            return False, "target_self_blocked", "这个狼人杀行动不能选择自己作为目标。"
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

    if tool_name == "werewolf_summarize_clues":
        content = str(params.get("content") or params.get("speech") or params.get("note") or "整理今天听到的发言、票型和可疑点。 ").strip()
        _add_werewolf_memory(session, world, actor, f"第{day}天线索整理：{content}", importance=65)
        event = create_event(
            session,
            world=world,
            event_type="werewolf_clue_summary",
            actor_agent_id=actor.agent_id,
            location_id=actor.location.location_id if actor.location else None,
            viewer_text=f"{actor.chosen_name}整理了自己的狼人杀视角。",
            importance=45,
            color_class="info",
            payload={"day": day, "phase": phase},
        )
        return [event.event_id]

    if tool_name in {"werewolf_speak", "werewolf_wolf_discuss"}:
        speech = str(params.get("speech") or "我先说一下我的想法。").strip()
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
            settings["werewolf_state"] = state
            world.settings_json = settings
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
            settings["werewolf_state"] = state
            world.settings_json = settings
        return [event.event_id]

    if tool_name in {"werewolf_rebut", "werewolf_skip_rebuttal", "werewolf_reply_rebuttal", "werewolf_drop_debate"}:
        window = _active_rebuttal_window(state, day) or {}
        speaker_id = str(window.get("speaker_id") or "")
        speaker = session.get(Agent, speaker_id) if speaker_id else None
        speech = str(params.get("speech") or params.get("content") or "").strip()

        if tool_name == "werewolf_skip_rebuttal":
            _advance_rebuttal_candidate(session, world, state, day)
            settings["werewolf_state"] = state
            world.settings_json = settings
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
            speech = speech or "我想反驳一下刚才这点。"
            window["mode"] = "debate"
            window["rebutter_id"] = actor.agent_id
            window["turn_agent_id"] = speaker_id
            window["reply_count"] = 0
            state["rebuttal_window"] = window
            settings["werewolf_state"] = state
            world.settings_json = settings
            event = _werewolf_dialogue_event(
                session, world, actor, speech,
                event_type="werewolf_rebuttal",
                target=speaker,
                viewer_text=f"{actor.chosen_name}对{speaker.chosen_name if speaker else '刚才的发言'}提出反驳。",
                day=day, phase=phase, importance=75,
            )
            return [event.event_id]

        if tool_name == "werewolf_reply_rebuttal":
            speech = speech or "我回应一下这个反驳。"
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
            settings["werewolf_state"] = state
            world.settings_json = settings
            return event_ids

        if tool_name == "werewolf_drop_debate":
            _advance_rebuttal_candidate(session, world, state, day)
            settings["werewolf_state"] = state
            world.settings_json = settings
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
        settings["werewolf_state"] = state
        world.settings_json = settings
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
        settings["werewolf_state"] = state
        world.settings_json = settings
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
                        event_ids.extend(_perform_werewolf_night_kill(session, world, state, day, locked_target, actor_agent_id=None))
                        settings["werewolf_state"] = state
                        world.settings_json = settings
                        return event_ids
                _set_wolf_consensus_needs_discussion(state, day, True)
                nominations_all[str(day)] = {}
                state["wolf_kill_nominations"] = nominations_all
                discussions_all = dict(state.get("wolf_discussions") or {})
                discussions_all[str(day)] = []
                state["wolf_discussions"] = discussions_all
                _add_wolf_pack_memory(session, world, state, f"第{day}夜狼人夜袭意见不一致：{summary}。夜袭没有执行；所有狼人必须重新密会，公开说清自己赞成的目标，并统一选择同一个人。", importance=88)
                settings["werewolf_state"] = state
                world.settings_json = settings
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
        event_ids.extend(_perform_werewolf_night_kill(session, world, state, day, target, actor_agent_id=None))
        settings["werewolf_state"] = state
        world.settings_json = settings
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
        settings["werewolf_state"] = state
        world.settings_json = settings
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
        settings["werewolf_state"] = state
        world.settings_json = settings
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
        settings["werewolf_state"] = state
        world.settings_json = settings
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

    event = create_event(
        session,
        world=world,
        event_type="werewolf_action",
        actor_agent_id=actor.agent_id,
        location_id=actor.location.location_id if actor.location else None,
        viewer_text=f"{actor.chosen_name}处理了一次狼人杀行动。",
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
    return [event.event_id] + _check_werewolf_win(session, world)


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
    event = create_event(
        session,
        world=world,
        event_type="werewolf_game_decided",
        viewer_text=f"狼人杀胜负已定，{winner}获胜。幸存者即将说出最后的话。",
        importance=100,
        color_class="important",
        payload={"winner": winner, "final_speech_pending": True},
    )
    return [event.event_id]


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
    system_prompt = "你正在扮演狼人杀世界里的角色。只输出角色最终发言正文，不要输出动作编号、JSON、解释或旁白。"
    if winner == "狼人阵营" and role == "werewolf":
        user_prompt = (
            f"你是{agent.chosen_name}，你的隐藏身份是狼人。狼人阵营已经获胜：狼人数量已经不少于人类数量，人类无法再打赢你们。"
            "现在可以自爆身份，向剩下的人类说一段胜利后的话。语气可以炫耀、讽刺、冷静或得意，但保持角色感。80字以内。"
        )
    elif winner == "狼人阵营":
        revealed = "\n".join(wolf_lines) if wolf_lines else "狼人已经公开承认胜利。"
        user_prompt = (
            f"你是{agent.chosen_name}，你是幸存的人类阵营成员。狼人阵营已经获胜。你刚听到狼人公开说：\n{revealed}\n"
            "请直接回应这件事，说出震惊、愤怒、后悔、恐惧或不甘中的一种真实反应。80字以内。"
        )
    else:
        user_prompt = (
            f"你是{agent.chosen_name}，人类阵营已经获胜，狼人都已经出局。"
            "请说一段庆幸、松一口气或悼念出局者的最终发言。80字以内。"
        )
    return system_prompt, user_prompt


def record_werewolf_final_speech(session: Session, world: World, agent: Agent, speech: str) -> list[int]:
    settings = dict(world.settings_json or {})
    state = dict(settings.get("werewolf_state") or {})
    winner = str(state.get("winner") or "")
    text = str(speech or "").strip() or _fallback_final_speech(agent, state)
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
            viewer_text=f"狼人杀结束，{winner}获胜。",
            importance=100,
            color_class="important",
            payload={"winner": winner},
        )
        event_ids.append(end_event.event_id)
        world.status = "ended"
    settings["werewolf_state"] = state
    world.settings_json = settings
    return event_ids


def _fallback_final_speech(agent: Agent, state: dict[str, Any]) -> str:
    roles = state.get("roles") if isinstance(state.get("roles"), dict) else {}
    winner = str(state.get("winner") or "")
    role = roles.get(agent.agent_id, "villager")
    if winner == "狼人阵营" and role == "werewolf":
        return "已经结束了。你们再怎么怀疑、投票，也追不上今晚的结果。"
    if winner == "狼人阵营":
        return "原来已经来不及了……我们一直在猜，却还是没能拦住你们。"
    return "终于结束了。能活到现在，已经不是一个人能做到的事。"


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
    old_order = [agent_id for agent_id in (state.get("speech_order") or []) if agent_id in set(living)]
    order = old_order + [agent_id for agent_id in living if agent_id not in set(old_order)]
    counts_all = dict(state.get("speech_counts") or {})
    counts = dict(counts_all.get(str(day)) or {})
    ended_all = dict(state.get("speech_ended") or {})
    ended = dict(ended_all.get(str(day)) or {})
    for agent_id in order:
        if int(counts.get(agent_id) or 0) >= _speech_limit(world):
            ended[agent_id] = True
    try:
        index = int(state.get("current_speaker_index") or 0)
    except (TypeError, ValueError):
        index = 0
    index = max(0, min(index, len(order)))
    while index < len(order) and (ended.get(order[index]) or int(counts.get(order[index]) or 0) >= _speech_limit(world)):
        index += 1
    counts_all[str(day)] = {agent_id: int(counts.get(agent_id) or 0) for agent_id in order if int(counts.get(agent_id) or 0) > 0}
    ended_all[str(day)] = {agent_id: bool(ended.get(agent_id)) for agent_id in order if bool(ended.get(agent_id))}
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
    notes = list(ww.get("game_notes") or [])
    notes.append({"world_time": world.current_world_time_minutes, "content": content})
    ww["game_notes"] = notes[-16:]
    desires["werewolf"] = ww
    agent.desires_json = desires


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
