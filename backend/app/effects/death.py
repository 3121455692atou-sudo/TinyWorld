from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.agents.lifecycle import mark_dead
from app.agents.traits import clamp
from app.content.toolsets import survival_needs_enabled
from app.core.models import Agent, World
from app.effects.decay import apply_time_decay
from app.effects.drive_system import write_drive_state
from app.events.event_store import create_event
from app.events.render_text import render_death
from app.simulation.difficulty import profile_for_world
from app.world.corpses import apply_corpse_exposure, ensure_corpse_for_dead_agent
from app.world.visibility import same_location_agent_ids


def apply_danger_checks(session: Session, world: World, agent: Agent) -> list[int]:
    state = agent.dynamic_state
    if not state or agent.lifecycle_state == "dead":
        return []
    event_ids: list[int] = []
    location_id = agent.location.location_id if agent.location else None
    profile = profile_for_world(world)
    survival_enabled = survival_needs_enabled(world)
    desires = agent.desires_json or {}
    raw_unconscious_until = desires.get("unconscious_until_world_time")
    unconscious_until = int(raw_unconscious_until) if raw_unconscious_until is not None else 0
    if unconscious_until:
        if world.current_world_time_minutes < unconscious_until:
            return []
        raw_started = desires.get("unconscious_started_world_time")
        started = int(raw_started) if raw_started is not None else unconscious_until - 8 * 60
        apply_time_decay(agent, world.current_world_time_minutes, sleeping=True)
        duration = max(0, world.current_world_time_minutes - started)
        agent.desires_json = {
            **desires,
            "unconscious_until_world_time": None,
            "unconscious_started_world_time": None,
            "awake_since_world_time": world.current_world_time_minutes,
            "last_sleep_end_world_time": world.current_world_time_minutes,
            "last_sleep_duration_minutes": duration,
        }
        agent.lifecycle_state = "alive" if agent.lifecycle_state == "critical" and state.health > 20 else agent.lifecycle_state
        state.critical_reason = None if agent.lifecycle_state == "alive" else state.critical_reason
        event = create_event(
            session,
            world=world,
            event_type="unconscious_sleep",
            actor_agent_id=agent.agent_id,
            location_id=location_id,
            viewer_text=f"{agent.chosen_name} 昏睡了很久，直到这时才慢慢恢复意识。",
            importance=80,
            color_class="important",
        )
        return [event.event_id]

    def warn(kind: str, message: str, importance: int, cooldown_minutes: int = 120) -> None:
        current_desires = agent.desires_json or {}
        key = f"last_{kind}_warning_world_time"
        raw_last_warning = current_desires.get(key)
        last_warning = int(raw_last_warning) if raw_last_warning is not None else -10**9
        if world.current_world_time_minutes - last_warning < cooldown_minutes:
            return
        agent.desires_json = {**current_desires, key: world.current_world_time_minutes}
        event = create_event(
            session,
            world=world,
            event_type="warning",
            actor_agent_id=agent.agent_id,
            location_id=location_id,
            viewer_text=message,
            importance=importance,
            color_class="warning",
            payload={"warning": kind},
        )
        event_ids.append(event.event_id)

    def periodic(key: str, interval_minutes: int = 60) -> bool:
        current_desires = agent.desires_json or {}
        full_key = f"last_{key}_penalty_world_time"
        raw_last_penalty = current_desires.get(full_key)
        last_penalty = int(raw_last_penalty) if raw_last_penalty is not None else -10**9
        if world.current_world_time_minutes - last_penalty < interval_minutes:
            return False
        agent.desires_json = {**current_desires, full_key: world.current_world_time_minutes}
        return True

    if survival_enabled and state.satiety < 18:
        warn("hunger", f"{agent.chosen_name} 看起来很饿，动作比刚才迟缓。", 35)
    if survival_enabled and state.hydration < 18:
        warn("thirst", f"{agent.chosen_name} 嘴唇发干，明显需要喝水。", 40)
    if state.energy <= 2 and state.health > 0 and not (agent.desires_json or {}).get("unconscious_until_world_time"):
        rng = random.Random(f"energy-collapse:{world.seed}:{world.current_world_time_minutes}:{agent.agent_id}")
        if state.health <= 8 and rng.random() < float(profile["sleep_death_chance"]):
            state.health = 0
            state.critical_reason = "体力完全耗尽导致猝死"
        else:
            event_ids.append(_set_unconscious(session, world, agent, state, location_id, "体力完全耗尽后昏倒", duration_minutes=8 * 60).event_id)
            return event_ids
    if state.energy < 15 and agent.lifecycle_state == "alive":
        warn("fatigue", f"{agent.chosen_name} 已经非常疲惫。", 35)
    if state.energy < 5 and (agent.lifecycle_state != "critical" or state.critical_reason != "体力接近耗尽"):
        agent.lifecycle_state = "critical"
        state.critical_reason = "体力接近耗尽"
        event = create_event(
            session,
            world=world,
            event_type="critical",
            actor_agent_id=agent.agent_id,
            location_id=location_id,
            viewer_text=f"{agent.chosen_name} 进入危急状态: 体力接近耗尽。",
            importance=85,
            color_class="danger",
        )
        event_ids.append(event.event_id)

    satiety_zero_since = state.zero_satiety_since if state.zero_satiety_since is not None else world.current_world_time_minutes
    hydration_zero_since = state.zero_hydration_since if state.zero_hydration_since is not None else world.current_world_time_minutes
    energy_zero_since = state.zero_energy_since if state.zero_energy_since is not None else world.current_world_time_minutes
    elapsed_satiety_zero = world.current_world_time_minutes - satiety_zero_since
    elapsed_hydration_zero = world.current_world_time_minutes - hydration_zero_since
    elapsed_energy_zero = world.current_world_time_minutes - energy_zero_since
    if survival_enabled and state.satiety <= 0 and periodic("zero_satiety"):
        state.energy = clamp(state.energy - 6, 0, 100)
        state.stress = clamp(state.stress + 3, 0, 100)
        state.critical_reason = "长期饥饿" if elapsed_satiety_zero >= 24 * 60 else state.critical_reason
        if elapsed_satiety_zero >= int(profile["sat_zero_death_h"]) * 60:
            state.health = 0
        elif elapsed_satiety_zero >= 48 * 60:
            state.health = clamp(state.health - (6 if elapsed_satiety_zero >= 96 * 60 else 2), 0, 100)
    if survival_enabled and state.hydration <= 0 and periodic("zero_hydration"):
        state.energy = clamp(state.energy - 8, 0, 100)
        state.stress = clamp(state.stress + 4, 0, 100)
        state.critical_reason = "长期脱水" if elapsed_hydration_zero >= 12 * 60 else state.critical_reason
        if elapsed_hydration_zero >= int(profile["hyd_zero_death_h"]) * 60:
            state.health = 0
        elif elapsed_hydration_zero >= 18 * 60:
            state.health = clamp(state.health - (12 if elapsed_hydration_zero >= 36 * 60 else 4), 0, 100)
    if state.energy <= 0 and (not survival_enabled or (state.satiety > 0 and state.hydration > 0)) and elapsed_energy_zero >= 12 * 60 and periodic("zero_energy"):
        state.health = clamp(state.health - 3, 0, 100)
    if state.hygiene < 15:
        state.stress = clamp(state.stress + 1, 0, 100)
        warn("hygiene", f"{agent.chosen_name} 的清洁状态很差，身体开始更容易生病。", 35, cooldown_minutes=8 * 60)
        if state.hygiene < 5 and periodic("critical_hygiene", interval_minutes=12 * 60):
            state.health = clamp(state.health - float(profile["hygiene_health_loss"]), 0, 100)

    raw_awake_since = (agent.desires_json or {}).get("awake_since_world_time")
    if raw_awake_since is None:
        raw_awake_since = agent.created_at_world_time if agent.created_at_world_time is not None else world.current_world_time_minutes
    awake_since = int(raw_awake_since)
    awake_minutes = max(0, world.current_world_time_minutes - awake_since)
    if awake_minutes >= int(profile["awake_sleep_trigger_hours"]) * 60:
        if periodic("sleep_deprivation"):
            state.stress = clamp(state.stress + (10 if awake_minutes >= int(profile["sleep_collapse_start_h"]) * 60 else 4), 0, 100)
            state.energy = clamp(state.energy - (12 if awake_minutes >= int(profile["sleep_collapse_start_h"]) * 60 else 5), 0, 100)
        raw_last_sleep_warning = (agent.desires_json or {}).get("last_sleep_warning_world_time")
        last_warning = int(raw_last_sleep_warning) if raw_last_sleep_warning is not None else -10**9
        if world.current_world_time_minutes - last_warning >= 4 * 60:
            agent.desires_json = {**(agent.desires_json or {}), "last_sleep_warning_world_time": world.current_world_time_minutes}
            warn("sleep_deprivation", f"{agent.chosen_name} 已经太久没有睡觉，反应明显变慢。", 55 if awake_minutes < int(profile["sleep_collapse_start_h"]) * 60 else 75)
    if awake_minutes >= int(profile["sleep_collapse_start_h"]) * 60 and not (agent.desires_json or {}).get("unconscious_until_world_time"):
        rng = random.Random(f"sleep-collapse:{world.seed}:{world.current_world_time_minutes}:{agent.agent_id}")
        if awake_minutes >= int(profile["sleep_death_start_h"]) * 60 and state.health <= 12 and rng.random() < float(profile["sleep_death_chance"]):
            state.health = 0
            state.critical_reason = "连续清醒过久且身体极度虚弱导致死亡"
        elif rng.random() < float(profile["sleep_collapse_chance"]) or awake_minutes >= int(profile["sleep_death_start_h"]) * 60:
            event_ids.append(_set_unconscious(session, world, agent, state, location_id, "连续清醒过久后身体强制昏睡", duration_minutes=24 * 60).event_id)

    if state.health <= 0 and agent.lifecycle_state != "dead":
        cause = state.critical_reason or "生命值耗尽"
        mark_dead(agent, world.current_world_time_minutes, cause)
        corpse = ensure_corpse_for_dead_agent(session, world, agent, location_id=location_id, cause=cause)
        corpse_id = corpse.get("corpse_id") if corpse else None
        text = render_death(session, agent.agent_id, location_id, cause)
        if corpse_id:
            text += " 遗体留在了原地，直到有人愿意处理。"
        payload = {"cause": cause}
        if corpse_id:
            payload.update({"corpse_id": corpse_id, "corpse_persistent": True})
        event = create_event(
            session,
            world=world,
            event_type="death",
            actor_agent_id=agent.agent_id,
            location_id=location_id,
            viewer_text=text,
            importance=100,
            color_class="death",
            payload=payload,
        )
        exposure_event_ids: list[int] = []
        for survivor_id in same_location_agent_ids(session, agent):
            survivor = session.get(Agent, survivor_id)
            if survivor:
                exposure_event_ids.extend(apply_corpse_exposure(session, world, survivor))
        event_ids.extend(exposure_event_ids)
        event_ids.append(event.event_id)
    if agent.lifecycle_state != "dead":
        write_drive_state(world, agent)
    return event_ids


def _set_unconscious(session: Session, world: World, agent: Agent, state, location_id: str | None, reason: str, *, duration_minutes: int):
    until = world.current_world_time_minutes + duration_minutes
    agent.lifecycle_state = "critical"
    state.critical_reason = reason
    agent.desires_json = {
        **(agent.desires_json or {}),
        "unconscious_until_world_time": until,
        "unconscious_started_world_time": world.current_world_time_minutes,
    }
    return create_event(
        session,
        world=world,
        event_type="unconscious",
        actor_agent_id=agent.agent_id,
        location_id=location_id,
        viewer_text=f"{agent.chosen_name} 终于支撑不住，昏了过去。",
        importance=90,
        color_class="danger",
        payload={"unconscious_until_world_time": until, "reason": reason},
    )
