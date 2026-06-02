from __future__ import annotations

from typing import Any

from app.core.models import Agent, World


DEFAULT_DIFFICULTY = "NORMAL"
FAST_MODERN_WORLDVIEW_ID = "fast_modern_worldview"
FAST_MODERN_WORLD_TOOLSET_ID = "fast_modern_world_toolset"

CONVERSATION_TOOL_NAMES = {
    "say_to_visible_agent",
    "speak_to_nearby",
    "ask_visible_agent_to_introduce",
    "introduce_self",
    "compliment_visible_agent",
    "apologize_to_visible_agent",
    "seek_conversation",
    "comfort_visible_agent",
    "invite_visible_agent_to_walk",
    "invite_visible_agent_to_hot_spring",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "force_hug_visible_agent",
    "force_hold_hands_visible_agent",
    "force_comfort_visible_agent",
    "cry_for_comfort",
    "tool_social_invite_to_location",
    "tool_romance_request_hold_hands",
    "tool_romance_request_hug",
    "tool_social_accept_invite",
    "tool_social_decline_invite",
    "tool_romance_accept_hold_hands",
    "tool_romance_decline_hold_hands",
    "tool_romance_accept_hug",
    "tool_romance_decline_hug",
}



DIFFICULTY_LABELS: dict[str, str] = {
    "FAIRY": "童话",
    "NORMAL": "普通",
    "HARD": "困难",
    "HELL": "地狱",
}


DIFFICULTY_PROFILES: dict[str, dict[str, Any]] = {
    "FAIRY": {
        "start_money": 120,
        "food_price": 6,
        "rent_per_10": 20,
        "rent_grace_days": 5,
        "awake_energy": -1.25,
        "awake_satiety": -2.8,
        "awake_hydration": -3.0,
        "awake_hygiene": -0.3,
        "awake_social": -0.3,
        "awake_fun": -0.28,
        "awake_stress": 0.08,
        "sleep_energy": 10.0,
        "sleep_satiety": -1.5,
        "sleep_hydration": -1.7,
        "sleep_stress": -2.2,
        "urgent_hydration": 62,
        "urgent_satiety": 58,
        "urgent_energy": 35,
        "reaction_hydration": 45,
        "reaction_satiety": 40,
        "reaction_energy": 25,
        "work_time_min": 120,
        "work_wage": 50,
        "work_energy": -8,
        "work_satiety": -4,
        "work_hydration": -5,
        "work_stress": 3,
        "work_fun": -3,
        "odd_time_min": 45,
        "odd_wage": 22,
        "odd_energy": -6,
        "odd_satiety": -3,
        "odd_hydration": -4,
        "odd_stress": 2,
        "odd_fun": -2,
        "aid_food_cooldown_h": 12,
        "aid_satiety": 34,
        "aid_hydration": 25,
        "hyd_zero_death_h": 72,
        "sat_zero_death_h": 288,
        "awake_sleep_trigger_hours": 24,
        "sleep_collapse_start_h": 72,
        "sleep_death_start_h": 96,
        "sleep_death_chance": 0.01,
        "sleep_collapse_chance": 0.25,
        "hygiene_health_loss": 0.25,
        "mood_center": 64,
        "mood_scale": 0.85,
        "stress_coef": 0.12,
        "survival_penalty_scale": 0.60,
        "survival_pressure_thresholds": {"satiety": 55, "hydration": 55, "energy": 40, "health": 40},
    },
    "NORMAL": {
        "start_money": 72,
        "food_price": 6,
        "rent_per_10": 36,
        "rent_grace_days": 2,
        "awake_energy": -1.55,
        "awake_satiety": -3.8,
        "awake_hydration": -4.0,
        "awake_hygiene": -0.45,
        "awake_social": -0.45,
        "awake_fun": -0.45,
        "awake_stress": 0.18,
        "sleep_energy": 9.0,
        "sleep_satiety": -2.1,
        "sleep_hydration": -2.5,
        "sleep_stress": -1.4,
        "urgent_hydration": 55,
        "urgent_satiety": 52,
        "urgent_energy": 28,
        "reaction_hydration": 35,
        "reaction_satiety": 32,
        "reaction_energy": 18,
        "work_time_min": 180,
        "work_wage": 42,
        "work_energy": -12,
        "work_satiety": -6,
        "work_hydration": -8,
        "work_stress": 7,
        "work_fun": -5,
        "odd_time_min": 60,
        "odd_wage": 14,
        "odd_energy": -9,
        "odd_satiety": -4,
        "odd_hydration": -5,
        "odd_stress": 5,
        "odd_fun": -3,
        "aid_food_cooldown_h": 24,
        "aid_satiety": 34,
        "aid_hydration": 20,
        "hyd_zero_death_h": 48,
        "sat_zero_death_h": 216,
        "awake_sleep_trigger_hours": 20,
        "sleep_collapse_start_h": 48,
        "sleep_death_start_h": 72,
        "sleep_death_chance": 0.03,
        "sleep_collapse_chance": 0.45,
        "hygiene_health_loss": 0.5,
        "mood_center": 68,
        "mood_scale": 0.90,
        "stress_coef": 0.18,
        "survival_penalty_scale": 1.00,
        "survival_pressure_thresholds": {"satiety": 58, "hydration": 58, "energy": 42, "health": 45},
    },
    "HARD": {
        "start_money": 54,
        "food_price": 6,
        "rent_per_10": 45,
        "rent_grace_days": 2,
        "awake_energy": -1.7,
        "awake_satiety": -4.05,
        "awake_hydration": -4.25,
        "awake_hygiene": -0.55,
        "awake_social": -0.55,
        "awake_fun": -0.55,
        "awake_stress": 0.22,
        "sleep_energy": 8.6,
        "sleep_satiety": -2.45,
        "sleep_hydration": -2.8,
        "sleep_stress": -1.0,
        "urgent_hydration": 50,
        "urgent_satiety": 48,
        "urgent_energy": 25,
        "reaction_hydration": 32,
        "reaction_satiety": 28,
        "reaction_energy": 16,
        "work_time_min": 180,
        "work_wage": 38,
        "work_energy": -15,
        "work_satiety": -8,
        "work_hydration": -10,
        "work_stress": 9,
        "work_fun": -7,
        "odd_time_min": 75,
        "odd_wage": 12,
        "odd_energy": -12,
        "odd_satiety": -6,
        "odd_hydration": -7,
        "odd_stress": 7,
        "odd_fun": -5,
        "aid_food_cooldown_h": 36,
        "aid_satiety": 28,
        "aid_hydration": 14,
        "hyd_zero_death_h": 42,
        "sat_zero_death_h": 192,
        "awake_sleep_trigger_hours": 18,
        "sleep_collapse_start_h": 44,
        "sleep_death_start_h": 68,
        "sleep_death_chance": 0.06,
        "sleep_collapse_chance": 0.55,
        "hygiene_health_loss": 0.8,
        "mood_center": 70,
        "mood_scale": 0.95,
        "stress_coef": 0.22,
        "survival_penalty_scale": 1.20,
        "survival_pressure_thresholds": {"satiety": 62, "hydration": 62, "energy": 45, "health": 50},
    },
    "HELL": {
        "start_money": 36,
        "food_price": 6,
        "rent_per_10": 54,
        "rent_grace_days": 1,
        "awake_energy": -1.95,
        "awake_satiety": -4.45,
        "awake_hydration": -4.85,
        "awake_hygiene": -0.75,
        "awake_social": -0.75,
        "awake_fun": -0.75,
        "awake_stress": 0.3,
        "sleep_energy": 7.8,
        "sleep_satiety": -2.95,
        "sleep_hydration": -3.3,
        "sleep_stress": -0.6,
        "urgent_hydration": 45,
        "urgent_satiety": 42,
        "urgent_energy": 22,
        "reaction_hydration": 26,
        "reaction_satiety": 24,
        "reaction_energy": 14,
        "work_time_min": 240,
        "work_wage": 32,
        "work_energy": -20,
        "work_satiety": -12,
        "work_hydration": -15,
        "work_stress": 13,
        "work_fun": -10,
        "odd_time_min": 90,
        "odd_wage": 9,
        "odd_energy": -15,
        "odd_satiety": -8,
        "odd_hydration": -10,
        "odd_stress": 10,
        "odd_fun": -8,
        "aid_food_cooldown_h": 48,
        "aid_satiety": 20,
        "aid_hydration": 8,
        "hyd_zero_death_h": 36,
        "sat_zero_death_h": 168,
        "awake_sleep_trigger_hours": 16,
        "sleep_collapse_start_h": 40,
        "sleep_death_start_h": 60,
        "sleep_death_chance": 0.10,
        "sleep_collapse_chance": 0.65,
        "hygiene_health_loss": 1.2,
        "mood_center": 72,
        "mood_scale": 1.05,
        "stress_coef": 0.28,
        "survival_penalty_scale": 1.50,
        "survival_pressure_thresholds": {"satiety": 68, "hydration": 68, "energy": 50, "health": 55},
    },
}


def normalize_difficulty(value: Any) -> str:
    key = str(value or DEFAULT_DIFFICULTY).upper()
    return key if key in DIFFICULTY_PROFILES else DEFAULT_DIFFICULTY


def difficulty_from_settings(settings_json: dict[str, Any] | None) -> str:
    settings = settings_json or {}
    return normalize_difficulty(settings.get("survival_difficulty") or settings.get("difficulty"))


def profile_for_world(world: World | None) -> dict[str, Any]:
    settings = world.settings_json if world else None
    profile = dict(DIFFICULTY_PROFILES[difficulty_from_settings(settings)])
    _apply_worldview_runtime_overrides(profile, settings)
    if _is_fast_modern(settings):
        work_compression = 4.0
        profile.update(
            {
                "awake_satiety": -1.15,
                "awake_hydration": -1.25,
                "sleep_satiety": -0.85,
                "sleep_hydration": -0.95,
                "urgent_satiety": 36,
                "urgent_hydration": 38,
                "reaction_satiety": 24,
                "reaction_hydration": 25,
                "work_time_min": max(1, int(round(float(profile.get("work_time_min", 180)) / work_compression))),
                "odd_time_min": max(1, int(round(float(profile.get("odd_time_min", 60)) / work_compression))),
                "work_energy": float(profile.get("work_energy", -12)) / 2.0,
                "work_satiety": float(profile.get("work_satiety", -6)) / 2.0,
                "work_hydration": float(profile.get("work_hydration", -8)) / 2.0,
                "work_stress": float(profile.get("work_stress", 7)) / 2.0,
                "work_fun": float(profile.get("work_fun", -5)) / 2.0,
                "odd_energy": float(profile.get("odd_energy", -9)) / 2.0,
                "odd_satiety": float(profile.get("odd_satiety", -4)) / 2.0,
                "odd_hydration": float(profile.get("odd_hydration", -5)) / 2.0,
                "odd_stress": float(profile.get("odd_stress", 5)) / 2.0,
                "odd_fun": float(profile.get("odd_fun", -3)) / 2.0,
                "tool_time_scale": 2.0,
                "conversation_time_scale": 1.0,
                "dynamic_effect_scale": 1.5,
                "survival_cadence": "one_meal_one_drink_per_day",
            }
        )
    profile.setdefault("tool_time_scale", 1.0)
    profile.setdefault("dynamic_effect_scale", 1.0)
    return profile


def _apply_worldview_runtime_overrides(profile: dict[str, Any], settings_json: dict[str, Any] | None) -> None:
    settings = settings_json or {}
    rule_parameters = settings.get("worldview_rule_parameters")
    runtime = rule_parameters.get("runtime") if isinstance(rule_parameters, dict) else None
    if not isinstance(runtime, dict):
        return
    numeric_keys = {
        "awake_energy", "awake_satiety", "awake_hydration", "awake_hygiene", "awake_social", "awake_fun", "awake_stress",
        "sleep_energy", "sleep_satiety", "sleep_hydration", "sleep_stress",
        "urgent_satiety", "urgent_hydration", "urgent_energy",
        "reaction_satiety", "reaction_hydration", "reaction_energy",
        "tool_time_scale", "conversation_time_scale", "dynamic_effect_scale",
    }
    for key in numeric_keys:
        if key not in runtime:
            continue
        try:
            profile[key] = float(runtime[key])
        except (TypeError, ValueError):
            continue
    if isinstance(runtime.get("survival_cadence"), str):
        profile["survival_cadence"] = runtime["survival_cadence"]


def _is_fast_modern(settings_json: dict[str, Any] | None) -> bool:
    settings = settings_json or {}
    return (
        settings.get("worldview_id") == FAST_MODERN_WORLDVIEW_ID
        or settings.get("world_toolset_id") == FAST_MODERN_WORLD_TOOLSET_ID
        or settings.get("toolset_id") == FAST_MODERN_WORLD_TOOLSET_ID
    )


def dynamic_effect_scale_for_state(state: Any) -> float:
    try:
        agent = getattr(state, "agent", None)
        world = getattr(agent, "world", None)
        profile = profile_for_world(world)
        value = float(profile.get("dynamic_effect_scale", 1.0))
    except Exception:
        value = 1.0
    if value < 0:
        return 1.0
    return value


def profile_for_agent(agent: Agent) -> dict[str, Any]:
    return profile_for_world(agent.world)


def difficulty_label(key: str) -> str:
    return DIFFICULTY_LABELS.get(normalize_difficulty(key), DIFFICULTY_LABELS[DEFAULT_DIFFICULTY])


def tool_time_cost(world: World, tool_name: str, fallback_minutes: int) -> int:
    profile = profile_for_world(world)
    if tool_name in {"work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner"}:
        base = int(profile["work_time_min"])
    elif tool_name == "do_odd_job":
        base = int(profile["odd_time_min"])
    else:
        base = int(fallback_minutes)
    if tool_name in CONVERSATION_TOOL_NAMES:
        conversation_scale = float(profile.get("conversation_time_scale", 1.0) or 1.0)
        return max(1, int(round(min(base, 2) * max(0.1, conversation_scale))))
    scale = float(profile.get("tool_time_scale", 1.0) or 1.0)
    if scale <= 0:
        scale = 1.0
    if base <= 0:
        return 0
    return max(1, int(round(base * scale)))
