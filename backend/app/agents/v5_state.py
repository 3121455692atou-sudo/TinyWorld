from __future__ import annotations

from typing import Any

from app.agents.state import recompute_mood
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
    agent.age_stage = agent.age_stage or "adult"
    raw_desires = agent.desires_json or {}
    needs_mood_migration = raw_desires.get("mood_formula_version") != 2
    agent.wallet_json = {**default_wallet(), **(agent.wallet_json or {})}
    agent.work_json = {**default_work(), **(agent.work_json or {})}
    family = {**default_family(), **(agent.family_json or {})}
    family["adult_intimacy_profile"] = {
        **default_family()["adult_intimacy_profile"],
        **(family.get("adult_intimacy_profile") or {}),
    }
    family["adult_intimacy_profile"]["reproductive_profile"] = {
        **default_family()["adult_intimacy_profile"]["reproductive_profile"],
        **(family["adult_intimacy_profile"].get("reproductive_profile") or {}),
    }
    agent.family_json = family
    agent.law_json = {**default_law(), **(agent.law_json or {})}
    agent.trauma_json = {**default_trauma(), **(agent.trauma_json or {})}
    agent.desires_json = {**default_desires(), **raw_desires, "mood_formula_version": 2}
    if needs_mood_migration and agent.dynamic_state:
        recompute_mood(agent.dynamic_state)
    agent.morality_json = {**default_morality(), **(agent.morality_json or {})}
    agent.tool_learning_json = {**default_tool_learning(), **(agent.tool_learning_json or {})}
    sync_v5_derived(agent)


def sync_v5_derived(agent: Agent) -> None:
    state = agent.dynamic_state
    if not state:
        return
    survival_enabled = survival_needs_enabled(agent.world)
    desires = {**default_desires(), **(agent.desires_json or {})}
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
    agent.desires_json = desires


def wallet_money(agent: Agent) -> int:
    ensure_v5_agent_state(agent)
    return int(agent.wallet_json.get("money", 0))


def add_money(agent: Agent, amount: int) -> None:
    ensure_v5_agent_state(agent)
    agent.wallet_json = {**agent.wallet_json, "money": max(0, wallet_money(agent) + int(amount))}
