from __future__ import annotations

from app.agents.state import field_upper_bound, recompute_mood
from app.agents.traits import clamp
from app.content.toolsets import survival_needs_enabled
from app.core.models import Agent, AgentDynamicState
from app.simulation.difficulty import profile_for_agent
from app.world.public_hygiene import apply_location_hygiene_exposure


DECAY_PER_HOUR = {
    "energy": -1.6,
    "satiety": -4.2,
    "hydration": -4.6,
    "hygiene": -0.6,
    "social": -0.6,
    "fun": -0.5,
    "stress": 0.15,
}


def apply_time_decay(agent: Agent, to_world_time: int, sleeping: bool = False) -> dict[str, dict[str, float]]:
    state = agent.dynamic_state
    if not state:
        return {}
    elapsed = max(0, to_world_time - state.last_decay_world_time)
    if elapsed <= 0:
        return {}
    hours = elapsed / 60
    before = _snapshot(state)
    profile = profile_for_agent(agent)
    survival_enabled = survival_needs_enabled(agent.world)
    if sleeping:
        state.energy = clamp(state.energy + float(profile["sleep_energy"]) * hours, 0, field_upper_bound("energy"))
        if survival_enabled:
            state.satiety = clamp(state.satiety + float(profile["sleep_satiety"]) * hours, 0, field_upper_bound("satiety"))
            state.hydration = clamp(state.hydration + float(profile["sleep_hydration"]) * hours, 0, field_upper_bound("hydration"))
        state.stress = clamp(state.stress + float(profile["sleep_stress"]) * hours)
    else:
        state.energy = clamp(state.energy + float(profile["awake_energy"]) * hours, 0, field_upper_bound("energy"))
        if survival_enabled:
            state.satiety = clamp(state.satiety + float(profile["awake_satiety"]) * hours, 0, field_upper_bound("satiety"))
            state.hydration = clamp(state.hydration + float(profile["awake_hydration"]) * hours, 0, field_upper_bound("hydration"))
        state.hygiene = clamp(state.hygiene + float(profile["awake_hygiene"]) * hours, 0, field_upper_bound("hygiene"))
        apply_location_hygiene_exposure(agent, to_world_time, hours)
        state.social = clamp(state.social + float(profile["awake_social"]) * hours, 0, field_upper_bound("social"))
        state.fun = clamp(state.fun + float(profile["awake_fun"]) * hours, 0, field_upper_bound("fun"))
        state.stress = clamp(state.stress + float(profile["awake_stress"]) * hours)
    state.last_decay_world_time = to_world_time
    _update_zero_markers(state, to_world_time, survival_enabled=survival_enabled)
    recompute_mood(
        state,
        mood_center=float(profile["mood_center"]),
        mood_scale=float(profile["mood_scale"]),
        stress_coef=float(profile["stress_coef"]),
        survival_penalty_scale=float(profile["survival_penalty_scale"]),
        include_survival_needs=survival_enabled,
    )
    after = _snapshot(state)
    return {
        key: {"before": before[key], "after": after[key]}
        for key in before
        if abs(before[key] - after[key]) > 0.001
    }


def _snapshot(state: AgentDynamicState) -> dict[str, float]:
    return {
        "health": round(state.health, 2),
        "energy": round(state.energy, 2),
        "satiety": round(state.satiety, 2),
        "hydration": round(state.hydration, 2),
        "hygiene": round(state.hygiene, 2),
        "social": round(state.social, 2),
        "fun": round(state.fun, 2),
        "stress": round(state.stress, 2),
        "mood": round(state.mood, 2),
    }


def _update_zero_markers(state: AgentDynamicState, world_time: int, *, survival_enabled: bool) -> None:
    if survival_enabled:
        state.zero_satiety_since = world_time if state.satiety <= 0 and state.zero_satiety_since is None else (None if state.satiety > 0 else state.zero_satiety_since)
        state.zero_hydration_since = world_time if state.hydration <= 0 and state.zero_hydration_since is None else (None if state.hydration > 0 else state.zero_hydration_since)
    else:
        state.zero_satiety_since = None
        state.zero_hydration_since = None
    state.zero_energy_since = world_time if state.energy <= 0 and state.zero_energy_since is None else (None if state.energy > 0 else state.zero_energy_since)
