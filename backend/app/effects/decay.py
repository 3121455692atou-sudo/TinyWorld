from __future__ import annotations

import math

from app.agents.numeric import require_finite, safe_int
from app.agents.state import field_upper_bound, normalize_dynamic_state, recompute_mood, state_snapshot
from app.agents.traits import clamp
from app.agents.v5_state import sync_v5_derived
from app.content.toolsets import survival_needs_enabled
from app.core.models import Agent, AgentDynamicState
from app.simulation.difficulty import profile_for_agent
from app.world.public_hygiene import apply_location_hygiene_exposure


DECAY_PER_HOUR = {
    "energy": -1.6, "satiety": -4.2, "hydration": -4.6,
    "hygiene": -0.6, "social": -0.6, "fun": -0.5, "stress": 0.15,
}


def apply_time_decay(agent: Agent, to_world_time: int, sleeping: bool = False) -> dict[str, dict[str, float]]:
    state = agent.dynamic_state
    if not state or agent.lifecycle_state == "dead":
        return {}
    to_world_time = int(require_finite(to_world_time, "world time"))
    start = safe_int(state.last_decay_world_time)
    if to_world_time <= start:
        return {}
    before = state_snapshot(state)
    normalize_dynamic_state(state)
    profile = profile_for_agent(agent)
    world_settings = (agent.world.settings_json or {}) if agent.world else {}
    survival_enabled = survival_needs_enabled(agent.world)
    if world_settings.get("no_basic_needs"):
        for field, minimum in (("energy", 85), ("satiety", 85), ("hydration", 85), ("hygiene", 80)):
            setattr(state, field, max(getattr(state, field), minimum))
        state.stress = min(state.stress, 35)
        state.zero_energy_since = state.zero_satiety_since = state.zero_hydration_since = None
        survival_enabled = False
    else:
        for segment_start, segment_end, is_sleeping in _decay_segments(agent, start, to_world_time, sleeping):
            hours = (segment_end - segment_start) / 60.0
            prefix = "sleep" if is_sleeping else "awake"
            fields = ["energy", "stress"]
            if survival_enabled:
                fields.extend(["satiety", "hydration"])
            if not is_sleeping:
                fields.extend(["hygiene", "social", "fun"])
            for field in fields:
                _advance_field(state, field, float(profile[f"{prefix}_{field}"]), segment_start, segment_end)
            apply_location_hygiene_exposure(agent, segment_end, hours, sleeping=is_sleeping)
        if not survival_enabled:
            state.zero_satiety_since = state.zero_hydration_since = None
    state.last_decay_world_time = to_world_time
    recompute_mood(
        state,
        mood_center=float(profile["mood_center"]),
        mood_scale=float(profile["mood_scale"]),
        stress_coef=float(profile["stress_coef"]),
        survival_penalty_scale=float(profile["survival_penalty_scale"]),
        include_survival_needs=survival_enabled,
    )
    sync_v5_derived(agent)
    after = state_snapshot(state)
    return {key: {"before": before[key], "after": after[key]} for key in before if abs(before[key] - after[key]) > 0.001}


def _advance_field(state: AgentDynamicState, field: str, rate: float, start: int, end: int) -> None:
    before = getattr(state, field)
    value = clamp(before + rate * ((end - start) / 60.0), 0, field_upper_bound(field))
    # Suppress only floating-point residue at the zero boundary. Display rounding
    # never feeds back into the simulation's accumulated values.
    setattr(state, field, 0.0 if value < 1e-10 else value)
    if field not in {"energy", "satiety", "hydration"}:
        return
    marker = f"zero_{field}_since"
    if getattr(state, field) > 0:
        setattr(state, marker, None)
    elif before > 0 and rate < 0:
        # Storage uses whole minutes. The first zero minute must be independent
        # of whether time was advanced in one jump or hundreds of small steps.
        crossing = math.ceil(start + before / -rate * 60 - 1e-8)
        setattr(state, marker, min(end, max(start, crossing)))
    elif getattr(state, marker) is None:
        setattr(state, marker, start)


def _decay_segments(agent: Agent, start: int, end: int, sleeping: bool) -> list[tuple[int, int, bool]]:
    """Integrate saved sleep windows even when another system advances time.

    Explicit ``sleeping=True`` remains supported for callers without a scheduled
    window. A delayed wake-up never awards sleep recovery after the saved end time.
    """
    desires = agent.desires_json if isinstance(agent.desires_json, dict) else {}
    windows: list[tuple[int, int]] = []
    for prefix in ("sleep", "unconscious"):
        raw_end = desires.get(f"{prefix}_until_world_time")
        if raw_end is None:
            continue
        window_end = safe_int(raw_end, start)
        window_start = safe_int(desires.get(f"{prefix}_started_world_time"), start)
        if window_end > window_start:
            windows.append((window_start, window_end))
    if not windows:
        return [(start, end, sleeping)]
    boundaries = sorted({start, end, *(point for window in windows for point in window if start < point < end)})
    return [(left, right, any(first <= left < last for first, last in windows)) for left, right in zip(boundaries, boundaries[1:])]
