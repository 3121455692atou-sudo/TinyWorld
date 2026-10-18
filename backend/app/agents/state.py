from __future__ import annotations

from app.core.models import AgentDynamicState
from app.agents.traits import clamp
from app.agents.numeric import finite_float, require_finite, safe_int
from app.content.toolsets import survival_needs_enabled
from app.simulation.difficulty import dynamic_effect_scale_for_state, profile_for_world


DYNAMIC_FIELDS = ["health", "energy", "satiety", "hydration", "hygiene", "social", "fun", "stress", "mood"]
_FIELD_DEFAULTS = {"health": 100, "energy": 80, "satiety": 75, "hydration": 75, "hygiene": 70, "social": 50, "fun": 50, "stress": 20, "mood": 10}


def field_upper_bound(field: str) -> float:
    if field == "satiety":
        return 110
    return 100


def initial_dynamic_state(agent_id: str, world_time: int = 0) -> AgentDynamicState:
    return AgentDynamicState(
        agent_id=agent_id,
        health=100,
        energy=80,
        satiety=88,
        hydration=90,
        hygiene=70,
        social=62,
        fun=60,
        stress=12,
        mood=6,
        last_decay_world_time=world_time,
    )


def recompute_mood(
    state: AgentDynamicState,
    event_modifier: float = 0,
    *,
    mood_center: float | None = None,
    mood_scale: float | None = None,
    stress_coef: float | None = None,
    survival_penalty_scale: float | None = None,
    include_survival_needs: bool | None = None,
) -> None:
    normalize_dynamic_state(state)
    agent = state.agent
    world = agent.world if agent else None
    profile = profile_for_world(world)
    mood_center = finite_float(mood_center, float(profile["mood_center"]))
    mood_scale = finite_float(mood_scale, float(profile["mood_scale"]))
    stress_coef = finite_float(stress_coef, float(profile["stress_coef"]))
    survival_penalty_scale = finite_float(survival_penalty_scale, float(profile["survival_penalty_scale"]))
    if include_survival_needs is None:
        include_survival_needs = survival_needs_enabled(world) and not bool((world.settings_json or {}).get("no_basic_needs") if world else False)
    basic = (
        state.energy * 0.18
        + state.satiety * 0.24
        + state.hydration * 0.24
        + state.hygiene * 0.08
        + state.social * 0.12
        + state.fun * 0.14
    )
    survival_penalty = max(0, 24 - state.energy) * 0.6 + max(0, 20 - state.health) * 1.0
    if include_survival_needs:
        survival_penalty += max(0, 32 - state.satiety) * 0.9 + max(0, 32 - state.hydration) * 1.1
    state.mood = clamp((basic - mood_center) * mood_scale - state.stress * stress_coef - survival_penalty * survival_penalty_scale + finite_float(event_modifier), -100, 100)


def normalize_dynamic_state(state: AgentDynamicState) -> None:
    """Repair missing/invalid legacy numbers without changing valid save values."""
    for field in DYNAMIC_FIELDS:
        value = finite_float(getattr(state, field), _FIELD_DEFAULTS[field])
        lower = -100 if field == "mood" else 0
        normalized = clamp(value, lower, field_upper_bound(field))
        if getattr(state, field) != normalized:
            setattr(state, field, normalized)


def state_snapshot(state: AgentDynamicState) -> dict[str, float]:
    return {field: round(finite_float(getattr(state, field), _FIELD_DEFAULTS[field]), 2) for field in DYNAMIC_FIELDS}


def apply_delta(state: AgentDynamicState, **delta: float) -> dict[str, dict[str, float]]:
    # Validate the entire request before mutating anything. ORM attributes such as
    # clocks, IDs and zero-need markers are not dynamic effects.
    effect_scale = finite_float(dynamic_effect_scale_for_state(state), 1.0)
    amounts = {
        field: require_finite(require_finite(amount, field) * effect_scale, field)
        for field, amount in delta.items() if field in DYNAMIC_FIELDS
    }
    if not amounts:
        return {}
    before = state_snapshot(state)
    normalize_dynamic_state(state)
    for field, amount in amounts.items():
        lower = -100 if field == "mood" else 0
        setattr(state, field, clamp(getattr(state, field) + amount, lower, field_upper_bound(field)))
    agent = state.agent
    world = agent.world if agent else None
    now = max(safe_int(state.last_decay_world_time), safe_int(world.current_world_time_minutes) if world else 0)
    for field in ("satiety", "hydration", "energy"):
        if field not in amounts:
            continue
        marker = f"zero_{field}_since"
        if getattr(state, field) > 0:
            setattr(state, marker, None)
        elif before[field] > 0 or getattr(state, marker) is None:
            setattr(state, marker, now)
    recompute_mood(state, amounts.get("mood", 0))
    if agent:
        from app.agents.v5_state import sync_v5_derived
        sync_v5_derived(agent)
    after = state_snapshot(state)
    return {
        key: {"before": before[key], "after": after[key]}
        for key in before
        if abs(before[key] - after[key]) > 0.001
    }
