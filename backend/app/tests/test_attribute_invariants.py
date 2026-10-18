from __future__ import annotations

from copy import deepcopy
import math
import random

import pytest

from app.agents.state import DYNAMIC_FIELDS, apply_delta, state_snapshot
from app.agents.v5_state import add_money, ensure_v5_agent_state, wallet_money
from app.effects.decay import apply_time_decay
from app.effects.death import apply_danger_checks
from app.effects.effect_engine import _catalog_hard_delta, _catalog_viewer_text, execute_tool
from app.effects.drive_system import compute_drive, write_drive_state
from app.effects.worldpack_effects import _apply_level_curve, _choose_effect, handle_worldpack_declarative_tool, validate_worldpack_declarative_tool
from app.tools.tool_specs import TOOL_SPECS, V5_CATALOG_BY_ID, ToolSpec
from app.core.models import Event, Location
from app.simulation.difficulty import profile_for_world, tool_time_cost
from app.world.public_hygiene import HYGIENE_KEY, apply_location_hygiene_exposure, clean_location, location_cleanliness, record_location_traffic

from conftest import make_world


def test_dynamic_deltas_cannot_change_clock_or_zero_markers(db):
    _, agents = make_world(db, 1)
    state = agents[0].dynamic_state
    state.last_decay_world_time = 400
    state.zero_energy_since = 120
    apply_delta(state, last_decay_world_time=-200, zero_energy_since=20)
    assert state.last_decay_world_time == 400
    assert state.zero_energy_since == 120


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf, "nan", "bad", None, True])
def test_invalid_delta_is_rejected_before_any_attribute_changes(db, invalid):
    _, agents = make_world(db, 1)
    state = agents[0].dynamic_state
    before = state_snapshot(state)
    with pytest.raises(ValueError):
        apply_delta(state, energy=-12, hydration=invalid)
    assert state_snapshot(state) == before


@pytest.mark.parametrize("difficulty", ["FAIRY", "HARD", "HELL"])
def test_mood_uses_same_difficulty_after_decay_and_action(db, difficulty):
    world, agents = make_world(db, 1)
    world.settings_json = {"difficulty": difficulty}
    agent = agents[0]
    apply_time_decay(agent, 60)
    before = agent.dynamic_state.mood
    apply_delta(agent.dynamic_state, energy=0)
    assert agent.dynamic_state.mood == pytest.approx(before)


def test_wallet_and_drive_reads_do_not_rewrite_agent_state(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.wallet_json = {"money": 19, "extension": {"opaque": [1, 2, 3]}}
    agent.desires_json = {"custom_desire": 12}
    before = deepcopy((agent.wallet_json, agent.desires_json, agent.work_json, agent.family_json))
    assert wallet_money(agent) == 19
    compute_drive(world, agent)
    assert (agent.wallet_json, agent.desires_json, agent.work_json, agent.family_json) == before


def test_decay_tracks_zero_crossing_inside_long_interval(db):
    _, agents = make_world(db, 1)
    state = agents[0].dynamic_state
    state.satiety = 3.8
    state.hydration = 4.0
    apply_time_decay(agents[0], 180)
    assert state.zero_satiety_since == 60
    assert state.zero_hydration_since == 60


def test_restoring_need_resets_zero_duration_immediately(db):
    world, agents = make_world(db, 1)
    world.current_world_time_minutes = 600
    state = agents[0].dynamic_state
    state.hydration = 0
    state.zero_hydration_since = 50
    apply_delta(state, hydration=15)
    assert state.zero_hydration_since is None


def test_dead_agents_do_not_decay_or_recover(db):
    _, agents = make_world(db, 1)
    agent = agents[0]
    agent.lifecycle_state = "dead"
    agent.dynamic_state.health = 0
    before = state_snapshot(agent.dynamic_state)
    assert apply_time_decay(agent, 24 * 60, sleeping=True) == {}
    assert state_snapshot(agent.dynamic_state) == before


def test_unconscious_time_is_sleep_even_during_default_decay(db):
    _, agents = make_world(db, 1)
    agent = agents[0]
    agent.dynamic_state.energy = 0
    agent.desires_json = {"unconscious_started_world_time": 0, "unconscious_until_world_time": 480}
    apply_time_decay(agent, 240)
    assert agent.dynamic_state.energy == pytest.approx(36)
    apply_time_decay(agent, 600)
    assert agent.dynamic_state.energy == pytest.approx(72 - 2 * 1.55)


def test_public_hygiene_clock_is_shared_between_residents(db):
    world, agents = make_world(db, 2)
    location_id = agents[0].location.location_id
    world.settings_json = {HYGIENE_KEY: {location_id: {"cleanliness": 40, "traffic": 30, "last_decay_world_time": 0}}}
    apply_location_hygiene_exposure(agents[0], 60, 1)
    first_score = location_cleanliness(world, location_id)
    apply_location_hygiene_exposure(agents[1], 60, 1)
    assert location_cleanliness(world, location_id) == first_score
    assert agents[0].dynamic_state.hygiene == agents[1].dynamic_state.hygiene


def test_repeated_danger_check_does_not_add_hygiene_stress(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.dynamic_state.hygiene = 10
    apply_danger_checks(db, world, agent)
    first = state_snapshot(agent.dynamic_state)
    assert apply_danger_checks(db, world, agent) == []
    assert state_snapshot(agent.dynamic_state) == first


def test_terminal_dehydration_cannot_be_postponed_by_exhaustion(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    world.current_world_time_minutes = 48 * 60
    state = agent.dynamic_state
    state.energy = 0
    state.hydration = 0
    state.zero_hydration_since = 0
    apply_danger_checks(db, world, agent)
    assert agent.lifecycle_state == "dead"


def test_unconscious_agent_can_die_from_existing_fatal_health(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.dynamic_state.health = 0
    agent.desires_json = {"unconscious_started_world_time": 0, "unconscious_until_world_time": 480}
    apply_danger_checks(db, world, agent)
    assert agent.lifecycle_state == "dead"


def _pack_spec(effect, **kwargs):
    return ToolSpec("pack_action", "Test action", "Test", hard_effect_id="worldpack_declarative", metadata={"worldview_id": "test_pack", "declarative_effect": effect}, **kwargs)


@pytest.mark.parametrize("effect", [
    {"money_cost": -5}, {"resource_cost": {"ore": -1}}, {"resource_caps": {"ore": -3}},
    {"agent_delta": {"energy": math.nan}}, {"target_delta": {"health": math.inf}},
    {"exp_delta": math.inf}, {"outcomes": [{"weight": math.nan, "money_delta": 10}]},
])
def test_malformed_worldpack_numbers_fail_before_mutation(db, effect):
    _, agents = make_world(db, 1)
    agent = agents[0]
    before = deepcopy((agent.wallet_json, agent.desires_json, state_snapshot(agent.dynamic_state)))
    ok, reason, _ = validate_worldpack_declarative_tool(agent, _pack_spec(effect))
    assert not ok and reason == "worldpack_invalid_effect"
    assert (agent.wallet_json, agent.desires_json, state_snapshot(agent.dynamic_state)) == before


def test_zero_weight_worldpack_outcome_is_never_selected(db):
    world, agents = make_world(db, 1)
    spec = _pack_spec({"outcomes": [{"weight": 0, "money_delta": 999}, {"weight": 1, "money_delta": 1}]})
    for minute in range(100):
        world.current_world_time_minutes = minute
        assert _choose_effect(world, agents[0], spec)["money_delta"] == 1


def test_worldpack_outcome_rechecks_its_actual_cost(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.wallet_json = {"money": 3}
    spec = _pack_spec({"outcomes": [{"weight": 1, "money_cost": 10, "exp_delta": 10}]})
    before = deepcopy(agent.wallet_json)
    handle_worldpack_declarative_tool(db, world, agent, spec, {}, agent.location.location_id, {})
    assert agent.wallet_json == before


def test_failed_worldpack_outcome_does_not_receive_success_rewards(db, monkeypatch):
    world, agents = make_world(db, 1)
    agent = agents[0]
    ensure_v5_agent_state(agent)
    agent.wallet_json = {"money": 3}
    spec = _pack_spec({"outcomes": [{"weight": 1, "money_cost": 10, "exp_delta": 5, "agent_delta": {"energy": 5}}]})
    monkeypatch.setitem(TOOL_SPECS, spec.tool_name, spec)
    before = state_snapshot(agent.dynamic_state)
    result = execute_tool(db, world=world, actor=agent, tool_name=spec.tool_name, params={"speech": "尝试一下。情绪：开心"})
    events = [db.get(Event, event_id) for event_id in result.event_ids]
    assert any(event.event_type == "worldpack_tool_failed" for event in events)
    assert not result.ok
    assert agent.wallet_json == {"money": 3}
    assert state_snapshot(agent.dynamic_state) == before
    assert not agent.desires_json.get("recent_action_rewards")
    assert not any("trait_growth" in (event.payload or {}) for event in events)


def test_worldpack_target_stays_bound_when_visible_letters_are_reassigned(db, monkeypatch):
    world, (actor, leaving, selected, other) = make_world(db, 4)
    for agent in (actor, leaving, selected, other):
        ensure_v5_agent_state(agent)
    selected.dynamic_state.health = other.dynamic_state.health = 80
    spec = _pack_spec({"target_delta": {"health": -5}}, target_policy="visible_ref")
    monkeypatch.setitem(TOOL_SPECS, spec.tool_name, spec)
    # Before departure selected was B. Afterwards selected is A and other is B.
    leaving.location.location_id = f"{world.world_id}:workshop"
    db.flush()
    result = execute_tool(db, world=world, actor=actor, tool_name=spec.tool_name, params={"visible_ref": "附近人物B", "visible_agent_id": selected.agent_id})
    assert result.ok, result.message
    assert selected.dynamic_state.health == 75
    assert other.dynamic_state.health == 80
    assert all(db.get(Event, event_id).target_agent_id == selected.agent_id for event_id in result.event_ids)


def test_level_up_notification_is_not_repeated_when_no_level_is_gained():
    progress = {"level": 2, "exp": 1, "last_level_ups": 1}
    _apply_level_curve(progress, {})
    assert progress.get("last_level_ups", 0) == 0


@pytest.mark.parametrize("difficulty", ["FAIRY", "NORMAL", "HARD", "HELL"])
@pytest.mark.parametrize("sleep_window", [False, True])
def test_decay_partition_and_clock_invariants_over_multiple_days(db, difficulty, sleep_window):
    world, agents = make_world(db, 4)
    world.settings_json = {"difficulty": difficulty}
    for agent, step in zip(agents, (1, 7, 60, 4320)):
        # Isolate physiology; changing environments have their own integration
        # tests below. The exact saved sleep window crosses coarse tick edges.
        agent.location = None
        if sleep_window:
            agent.desires_json = {"sleep_started_world_time": 187, "sleep_until_world_time": 697}
        for minute in range(step, 4320, step):
            apply_time_decay(agent, minute)
        apply_time_decay(agent, 4320)
        before = state_snapshot(agent.dynamic_state)
        assert apply_time_decay(agent, 4320) == {}
        assert apply_time_decay(agent, 12) == {}
        assert agent.dynamic_state.last_decay_world_time == 4320
        assert state_snapshot(agent.dynamic_state) == before
    reference = agents[0].dynamic_state
    for agent in agents[1:]:
        for field in DYNAMIC_FIELDS:
            assert getattr(agent.dynamic_state, field) == pytest.approx(getattr(reference, field), abs=1e-8)
        for field in ("energy", "hydration", "satiety"):
            assert getattr(agent.dynamic_state, f"zero_{field}_since") == getattr(reference, f"zero_{field}_since")


def test_hygiene_integral_agrees_for_minute_hour_and_day_steps(db):
    world, agents = make_world(db, 3)
    location_id = agents[0].location.location_id
    world.settings_json = {HYGIENE_KEY: {location_id: {"cleanliness": 80, "traffic": 4, "last_decay_world_time": 0}}}
    for agent, step in zip(agents, (1, 60, 1440)):
        for minute in range(step, 1440 + 1, step):
            apply_time_decay(agent, minute)
    for agent in agents[1:]:
        assert agent.dynamic_state.hygiene == pytest.approx(agents[0].dynamic_state.hygiene, abs=1e-8)


def test_hygiene_exposure_integrates_across_mid_interval_cleaning(db):
    world, agents = make_world(db, 2)
    location_id = agents[0].location.location_id
    world.settings_json = {HYGIENE_KEY: {location_id: {"cleanliness": 20, "traffic": 8, "last_decay_world_time": 0}}}
    apply_time_decay(agents[0], 30)
    world.current_world_time_minutes = 30
    clean_location(world, location_id, amount=45)
    apply_time_decay(agents[0], 60)
    apply_time_decay(agents[1], 60)
    assert agents[0].dynamic_state.hygiene == pytest.approx(agents[1].dynamic_state.hygiene, abs=1e-8)


def test_exposure_cursor_survives_many_environment_changes_and_no_double_charge(db):
    world, agents = make_world(db, 2)
    location_id = agents[0].location.location_id
    world.settings_json = {HYGIENE_KEY: {location_id: {"cleanliness": 20, "traffic": 8, "last_decay_world_time": 0}}}
    for agent in agents:
        apply_time_decay(agent, 1)
    for minute in range(2, 102):
        world.current_world_time_minutes = minute
        record_location_traffic(world, location_id, amount=0.1)
        apply_time_decay(agents[0], minute)
    apply_time_decay(agents[1], 101)
    assert agents[0].dynamic_state.hygiene == pytest.approx(agents[1].dynamic_state.hygiene, abs=1e-8)
    before = state_snapshot(agents[1].dynamic_state)
    assert apply_location_hygiene_exposure(agents[1], 101, 100 / 60) == {}
    assert state_snapshot(agents[1].dynamic_state) == before
    assert len(world.settings_json[HYGIENE_KEY][location_id]["decay_history"]) <= 64


def test_wallet_large_integer_arithmetic_and_read_only_legacy_defaults(db):
    _, agents = make_world(db, 1)
    agent = agents[0]
    assert wallet_money(agent) == 54
    assert agent.wallet_json == {}
    agent.wallet_json = {"money": 2**60 + 1, "plugin_data": [1, 2]}
    add_money(agent, 2**60 + 1)
    assert wallet_money(agent) == 2**61 + 2
    assert agent.wallet_json["plugin_data"] == [1, 2]


def test_legacy_state_normalization_preserves_extension_data_and_is_idempotent(db):
    _, agents = make_world(db, 1)
    agent = agents[0]
    agent.wallet_json = {"money": "17", "custom_wallet": {"items": ["keepsake"]}}
    agent.family_json = {"adult_intimacy_profile": ["broken old shape"], "custom_family": "retained"}
    agent.dynamic_state.energy = math.nan
    agent.dynamic_state.satiety = 500
    agent.dynamic_state.mood = -500
    ensure_v5_agent_state(agent)
    assert agent.wallet_json["custom_wallet"] == {"items": ["keepsake"]}
    assert agent.family_json["custom_family"] == "retained"
    assert agent.wallet_json["money"] == 17
    assert agent.dynamic_state.satiety == 110
    assert all(math.isfinite(value) for value in state_snapshot(agent.dynamic_state).values())
    db.flush()
    ensure_v5_agent_state(agent)
    assert not db.is_modified(agent)
    assert not db.is_modified(agent.dynamic_state)


def test_drive_refresh_does_not_ratchet_needs_or_keep_stale_survival_pressure(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.dynamic_state.social = 30
    agent.dynamic_state.fun = 30
    agent.dynamic_state.hydration = 0
    first = write_drive_state(world, agent)
    for _ in range(20):
        assert write_drive_state(world, agent) == first
    apply_delta(agent.dynamic_state, hydration=100, social=70, fun=70)
    after = write_drive_state(world, agent)
    assert after["survival_pressure"] < first["survival_pressure"]
    assert agent.desires_json["loneliness"] == 0
    assert agent.desires_json["boredom"] == 0
    assert agent.desires_json["survival_pressure"] == after["survival_pressure"]


def test_worldpack_missing_target_never_charges_resources(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    before = deepcopy(agent.wallet_json)
    spec = _pack_spec({"money_cost": 2, "target_delta": {"energy": 5}}, target_policy="visible_ref")
    with pytest.raises(ValueError, match="target"):
        handle_worldpack_declarative_tool(db, world, agent, spec, {"visible_ref": "does_not_exist"}, agent.location.location_id, {})
    assert agent.wallet_json == before


def test_level_curve_matches_reference_and_handles_huge_rewards():
    rng = random.Random(2701)
    for _ in range(300):
        initial = {"level": rng.randint(1, 20), "exp": rng.randint(0, 10000)}
        effect = {"level_curve_base": rng.randint(-50, 50), "level_curve_scale": rng.randint(-10, 30), "max_level": rng.randint(21, 500)}
        expected = dict(initial)
        leveled = 0
        while expected["level"] < effect["max_level"]:
            threshold = max(1, (effect["level_curve_base"] or 24) + expected["level"] * (effect["level_curve_scale"] or 12))
            if expected["exp"] < threshold:
                break
            expected["exp"] -= threshold
            expected["level"] += 1
            leveled += 1
        actual = dict(initial)
        _apply_level_curve(actual, effect)
        assert actual == {**expected, "last_level_ups": leveled}
    huge = {"level": 1, "exp": 10**24}
    _apply_level_curve(huge, {"max_level": 10**12})
    assert 1 < huge["level"] <= 10**12
    assert 0 <= huge["exp"] < 24 + huge["level"] * 12


def test_long_simulation_keeps_attributes_and_derived_desires_finite(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location = None
    rng = random.Random(7001)
    for hour in range(1, 12001):
        world.current_world_time_minutes = hour * 60
        apply_time_decay(agent, hour * 60, sleeping=hour % 24 < 8)
        if hour % 8 == 0:
            apply_delta(agent.dynamic_state, satiety=40, hydration=45)
        if hour % 24 == 0:
            apply_delta(agent.dynamic_state, hygiene=45, fun=rng.uniform(4, 12), social=rng.uniform(5, 14), stress=-3)
        if hour % 240 == 0:
            write_drive_state(world, agent)
            for field in DYNAMIC_FIELDS:
                value = getattr(agent.dynamic_state, field)
                assert math.isfinite(value)
                assert (-100 if field == "mood" else 0) <= value <= (110 if field == "satiety" else 100)
            assert agent.desires_json["boredom"] == int(100 - agent.dynamic_state.fun)
            assert agent.desires_json["loneliness"] == int(100 - agent.dynamic_state.social)


def test_long_unattended_life_eventually_dies_and_death_is_idempotent(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    for hour in range(1, 240):
        world.current_world_time_minutes = hour * 60
        apply_time_decay(agent, hour * 60)
        apply_danger_checks(db, world, agent)
        if agent.lifecycle_state == "dead":
            break
    assert agent.lifecycle_state == "dead"
    death_time = agent.death_at_world_time
    for hour in range(240, 500):
        world.current_world_time_minutes = hour * 60
        assert apply_time_decay(agent, hour * 60) == {}
        assert apply_danger_checks(db, world, agent) == []
    assert agent.death_at_world_time == death_time


@pytest.mark.parametrize("tool_name", [
    "tool_body_treat_self", "tool_body_treat_wound_other",
    "tool_perceive_check_weather_local", "tool_body_cool_down",
    "tool_police_mandatory_arrest_violent", "tool_court_sentence_theft_restitution",
    "tool_life_wash_dishes", "tool_life_make_bed",
    "tool_child_request_food", "tool_parent_give_child_water", "tool_parent_put_child_to_sleep",
    "tool_food_ask_eat_together", "tool_food_cook_simple_meal", "tool_food_make_drink",
])
def test_catalog_topics_and_partial_words_do_not_grant_body_recovery(db, tool_name):
    _, (actor, target) = make_world(db, 2)
    spec = TOOL_SPECS[tool_name]
    assert _catalog_hard_delta(spec) == {}
    text = _catalog_viewer_text(actor, target, spec, "v5_catalog_action")
    assert not any(phrase in text for phrase in ("简单吃了", "找了点水喝", "安静的地方睡下", "停下来休息"))


def test_catalog_forest_is_not_rest_and_breathing_is_not_eating(db):
    _, (actor,) = make_world(db, 1)
    forest = ToolSpec("tool_env_explore_forest", "探索森林", "探索附近的森林。", hard_effect_id="v5_catalog_generic")
    assert _catalog_hard_delta(forest) == {}
    assert "休息" not in _catalog_viewer_text(actor, None, forest, "v5_catalog_action")
    breathing = TOOL_SPECS["tool_body_breathe_calm"]
    assert _catalog_hard_delta(breathing) == {"stress": -3, "mood": 1}
    assert "吃" not in _catalog_viewer_text(actor, None, breathing, "v5_body")


@pytest.mark.parametrize(("tool_name", "delta", "phrase"), [
    ("tool_body_eat_meal", {"satiety": 12, "mood": 1}, "简单吃了"),
    ("tool_body_drink_water", {"hydration": 12, "mood": 1}, "找了点水喝"),
    ("tool_body_rest_short", {"energy": 8, "stress": -3}, "停下来休息"),
    ("tool_body_sleep", {"energy": 18, "stress": -6, "satiety": -2, "hydration": -2}, "安静的地方睡下"),
])
def test_catalog_actual_body_actions_keep_existing_effects(db, tool_name, delta, phrase):
    _, (actor,) = make_world(db, 1)
    # These duplicate catalog actions are no longer exposed; their metadata
    # still describes actual self-care, unlike a topic or an invitation.
    raw = V5_CATALOG_BY_ID[tool_name]
    spec = ToolSpec(tool_name, raw["name_zh"], "", catalog_category=raw["category"], effect_summary=raw["implementation"]["effect_summary"], metadata={"raw": raw})
    assert _catalog_hard_delta(spec) == delta
    assert phrase in _catalog_viewer_text(actor, None, spec, "v5_body")


@pytest.mark.parametrize("tool_name", ["tool_create_write_diary", "tool_create_write_poem", "tool_create_draw_picture"])
def test_catalog_creative_execution_does_not_create_food_or_drink(db, tool_name):
    world, (actor,) = make_world(db, 1)
    location = db.get(Location, f"{world.world_id}:library")
    actor.location.location_id = location.location_id
    actor.location.location = location
    actor.dynamic_state.satiety = 30
    actor.dynamic_state.hydration = 40
    actor.dynamic_state.energy = 40
    ensure_v5_agent_state(actor)
    before = state_snapshot(actor.dynamic_state)
    money = wallet_money(actor)
    result = execute_tool(db, world=world, actor=actor, tool_name=tool_name, params={"content": "我记下今天看见的事情。"})
    assert result.ok, result.message
    assert state_snapshot(actor.dynamic_state) == before
    assert wallet_money(actor) == money
    assert world.current_world_time_minutes == tool_time_cost(world, tool_name, TOOL_SPECS[tool_name].time_cost_minutes)
    events = [db.get(Event, event_id) for event_id in result.event_ids]
    assert any(TOOL_SPECS[tool_name].display_name in event.viewer_text for event in events)
    assert not any("简单吃了" in event.viewer_text or "satiety" in (event.state_delta or {}).get(actor.agent_id, {}) for event in events)


@pytest.mark.parametrize(("tool_name", "field", "gain", "event_type"), [
    ("eat_food", "satiety", 34, "eat"),
    ("drink_water", "hydration", 40, "drink"),
    ("rest", "energy", 15, "rest"),
])
def test_actual_eat_drink_and_rest_execution_keeps_effects_and_costs(db, tool_name, field, gain, event_type):
    world, (actor,) = make_world(db, 1)
    location = db.get(Location, f"{world.world_id}:cafeteria")
    actor.location.location_id = location.location_id
    actor.location.location = location
    actor.dynamic_state.satiety = 30
    actor.dynamic_state.hydration = 30
    actor.dynamic_state.energy = 30
    ensure_v5_agent_state(actor)
    money = wallet_money(actor)
    result = execute_tool(db, world=world, actor=actor, tool_name=tool_name, params={})
    assert result.ok, result.message
    assert getattr(actor.dynamic_state, field) == 30 + gain
    assert wallet_money(actor) == money - (int(profile_for_world(world)["food_price"]) if tool_name == "eat_food" else 0)
    assert world.current_world_time_minutes == tool_time_cost(world, tool_name, TOOL_SPECS[tool_name].time_cost_minutes)
    assert any(db.get(Event, event_id).event_type == event_type for event_id in result.event_ids)
