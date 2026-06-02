from __future__ import annotations

from app.core.models import AgentDynamicState
from app.agents.traits import clamp
from app.simulation.difficulty import dynamic_effect_scale_for_state


DYNAMIC_FIELDS = ["health", "energy", "satiety", "hydration", "hygiene", "social", "fun", "stress", "mood"]


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
    mood_center: float = 68,
    mood_scale: float = 0.9,
    stress_coef: float = 0.18,
    survival_penalty_scale: float = 1.0,
    include_survival_needs: bool = True,
) -> None:
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
    state.mood = clamp((basic - mood_center) * mood_scale - state.stress * stress_coef - survival_penalty * survival_penalty_scale + event_modifier, -100, 100)


def state_snapshot(state: AgentDynamicState) -> dict[str, float]:
    return {field: round(float(getattr(state, field)), 2) for field in DYNAMIC_FIELDS}


def apply_delta(state: AgentDynamicState, **delta: float) -> dict[str, dict[str, float]]:
    before = state_snapshot(state)
    effect_scale = dynamic_effect_scale_for_state(state)
    for field, amount in delta.items():
        amount = amount * effect_scale
        if not hasattr(state, field):
            continue
        if field == "mood":
            setattr(state, field, clamp(getattr(state, field) + amount, -100, 100))
        elif field == "stress":
            setattr(state, field, clamp(getattr(state, field) + amount, 0, 100))
        else:
            setattr(state, field, clamp(getattr(state, field) + amount, 0, field_upper_bound(field)))
    recompute_mood(state, float(delta.get("mood", 0)) * effect_scale)
    after = state_snapshot(state)
    return {
        key: {"before": before[key], "after": after[key]}
        for key in before
        if abs(before[key] - after[key]) > 0.001
    }
