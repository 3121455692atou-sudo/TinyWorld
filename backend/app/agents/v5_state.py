from __future__ import annotations

from typing import Any

from app.agents.state import normalize_dynamic_state, recompute_mood
from app.agents.numeric import require_finite, safe_int
from app.content.toolsets import survival_needs_enabled
from app.core.models import Agent
from app.simulation.difficulty import profile_for_agent


STARTING_MONEY = 54


def default_wallet() -> dict[str, Any]:
    return {"money": STARTING_MONEY}


def default_work() -> dict[str, Any]:
    return {"job": None, "employed": False, "fatigue": 0, "burnout": 0, "shifts_worked": 0}


def default_family() -> dict[str, Any]:
    return {
        "partner_agent_id": None,
        "children_agent_ids": [],
        "guardian_agent_ids": [],
        "pregnancy_state": None,
        "pending_intimacy_requests": [],
        "pending_social_requests": [],
        "pending_forced_social_actions": [],
        "adult_intimacy_profile": {
            "sexual_boundary": "attraction_and_trust",
            "family_plan": "undecided",
            "contraception_policy": "prefers",
            "reproductive_profile": {
                "can_be_pregnant": True,
                "can_impregnate": True,
                "fertility_enabled": True,
            },
            "relationship_requirement_for_sex": "trust_threshold",
            "last_declined_intimacy_tick_by_agent": {},
            "boundary_violations_by_agent": {},
            "intimacy_cooldowns": {},
            "relationship_started_world_time_by_agent": {},
            "romance_need_by_partner": {},
            "intimacy_counts_by_agent": {},
        },
    }


def default_law() -> dict[str, Any]:
    return {"jailed": False, "jail_days_remaining": 0, "criminal_records": [], "victim_records": []}


def default_trauma() -> dict[str, Any]:
    return {"facts": [], "emotional_intensity": 0, "recovery_count": 0}


def default_desires() -> dict[str, Any]:
    return {
        "joy": 55,
        "sadness": 10,
        "anger": 5,
        "fear": 8,
        "anxiety": 15,
        "boredom": 20,
        "loneliness": 30,
        "romance_need": 15,
        "novelty_need": 35,
        "mastery_need": 35,
        "status_need": 25,
        "survival_pressure": 0,
        "moral_pressure": 20,
        "mood_formula_version": 2,
    }


def default_morality() -> dict[str, Any]:
    return {"justice": 55, "desire_for_reward": 45, "guilt_sensitivity": 55, "boundary_respect": 70}


def default_tool_learning() -> dict[str, Any]:
    return {"stage": "adult", "llm_enabled": True, "learned": ["adult_base"]}


def ensure_v5_agent_state(agent: Agent) -> None:
    if not agent.age_stage:
        agent.age_stage = "adult"
    raw_desires = _mapping(agent.desires_json)
    needs_mood_migration = raw_desires.get("mood_formula_version") != 2
    wallet = {**default_wallet(), **_mapping(agent.wallet_json)}
    wallet["money"] = max(0, safe_int(wallet.get("money")))
    _assign_changed(agent, "wallet_json", wallet)
    work = {**default_work(), **_mapping(agent.work_json)}
    for key in ("fatigue", "burnout"):
        work[key] = max(0, min(100, safe_int(work[key])))
    _assign_changed(agent, "work_json", work)
    family = {**default_family(), **_mapping(agent.family_json)}
    family["adult_intimacy_profile"] = {
        **default_family()["adult_intimacy_profile"],
        **_mapping(family.get("adult_intimacy_profile")),
    }
    family["adult_intimacy_profile"]["reproductive_profile"] = {
        **default_family()["adult_intimacy_profile"]["reproductive_profile"],
        **_mapping(family["adult_intimacy_profile"].get("reproductive_profile")),
    }
    _assign_changed(agent, "family_json", family)
    _assign_changed(agent, "law_json", {**default_law(), **_mapping(agent.law_json)})
    _assign_changed(agent, "trauma_json", {**default_trauma(), **_mapping(agent.trauma_json)})
    _assign_changed(agent, "desires_json", {**default_desires(), **raw_desires, "mood_formula_version": 2})
    if agent.dynamic_state:
        normalize_dynamic_state(agent.dynamic_state)
    if needs_mood_migration and agent.dynamic_state:
        recompute_mood(agent.dynamic_state)
    _assign_changed(agent, "morality_json", {**default_morality(), **_mapping(agent.morality_json)})
    _assign_changed(agent, "tool_learning_json", {**default_tool_learning(), **_mapping(agent.tool_learning_json)})
    sync_v5_derived(agent)


def sync_v5_derived(agent: Agent) -> None:
    state = agent.dynamic_state
    if not state:
        return
    normalize_dynamic_state(state)
    survival_enabled = survival_needs_enabled(agent.world)
    desires = {**default_desires(), **_mapping(agent.desires_json)}
    thresholds = profile_for_agent(agent).get("survival_pressure_thresholds", {})
    pressure_parts = [
        0,
        float(thresholds.get("energy", 42)) - state.energy,
        float(thresholds.get("health", 45)) - state.health,
    ]
    if survival_enabled:
        pressure_parts.extend(
            [
                float(thresholds.get("satiety", 58)) - state.satiety,
                float(thresholds.get("hydration", 58)) - state.hydration,
            ]
        )
    survival_pressure = max(pressure_parts)
    desires.update(
        {
            "joy": int(max(0, min(100, 50 + state.mood * 0.45 - state.stress * 0.15))),
            "sadness": int(max(0, min(100, 35 - state.mood * 0.25))),
            "anxiety": int(max(0, min(100, state.stress * 0.7 + survival_pressure * 0.4))),
            "boredom": int(max(0, min(100, 100 - state.fun))),
            "loneliness": int(max(0, min(100, 100 - state.social))),
            "survival_pressure": int(max(0, min(100, survival_pressure))),
        }
    )
    _assign_changed(agent, "desires_json", desires)


def wallet_money(agent: Agent) -> int:
    """Read money without migrations or unrelated writes during menu generation."""
    return max(0, safe_int(_mapping(agent.wallet_json).get("money", STARTING_MONEY)))


def add_money(agent: Agent, amount: int) -> None:
    number = require_finite(amount, "money delta")
    delta = amount if isinstance(amount, int) else int(number)
    agent.wallet_json = {**_mapping(agent.wallet_json), "money": max(0, wallet_money(agent) + delta)}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _assign_changed(agent: Agent, field: str, value: dict[str, Any]) -> None:
    if getattr(agent, field) != value:
        setattr(agent, field, value)
