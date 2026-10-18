from __future__ import annotations

from copy import deepcopy
import math

import pytest
from sqlalchemy import func, select

from app.agents.state import initial_dynamic_state, state_snapshot
from app.agents.v5_state import ensure_v5_agent_state
from app.core.models import Agent, Event, World
from app.effects import effect_engine
from app.simulation.difficulty import profile_for_world, tool_time_cost
from app.tests.conftest import make_world


def _foreign_agent(db):
    world = World(world_id="foreign_world", name="隔离世界", seed=99, settings_json={}, current_world_time_minutes=0)
    agent = Agent(agent_id="foreign_agent", world=world, chosen_name="外部居民", lifecycle_state="alive")
    agent.dynamic_state = initial_dynamic_state(agent.agent_id)
    db.add_all([world, agent])
    db.flush()
    return world, agent


def test_execution_rejects_foreign_actor_without_mutation(db):
    world, _ = make_world(db, agent_count=1)
    foreign_world, actor = _foreign_agent(db)
    before = deepcopy(actor.wallet_json)
    result = effect_engine.execute_tool(db, world=world, actor=actor, tool_name="do_nothing")
    assert not result.ok
    assert not result.event_ids
    assert world.current_world_time_minutes == foreign_world.current_world_time_minutes == 0
    assert actor.wallet_json == before
    assert db.scalar(select(func.count()).select_from(Event)) == 0


def test_ignore_cannot_change_a_foreign_reaction_source(db):
    world, (actor,) = make_world(db, agent_count=1)
    _, foreign = _foreign_agent(db)
    before = state_snapshot(foreign.dynamic_state)
    result = effect_engine.execute_tool(
        db, world=world, actor=actor, tool_name="ignore", reaction=True,
        params={"_ignored_source_agent_id": foreign.agent_id, "speech": "我暂时不想接话。"},
    )
    assert result.ok
    assert state_snapshot(foreign.dynamic_state) == before
    assert all(db.get(Event, event_id).target_agent_id is None for event_id in result.event_ids)


def test_handler_exception_rolls_back_only_the_failed_action(db, monkeypatch):
    world, (actor,) = make_world(db, agent_count=1)
    ensure_v5_agent_state(actor)
    db.commit()
    before_state = state_snapshot(actor.dynamic_state)
    before_learning = deepcopy(actor.tool_learning_json)
    world.name = "此前已准备好的世界名称"

    def fail_after_effects(*args, **kwargs):
        raise RuntimeError("injected failure after event creation")

    monkeypatch.setattr(effect_engine, "_apply_repetition_penalty", fail_after_effects)
    with pytest.raises(RuntimeError, match="injected failure"):
        effect_engine.execute_tool(db, world=world, actor=actor, tool_name="do_nothing")
    db.commit()
    db.expire_all()
    assert world.name == "此前已准备好的世界名称"
    assert world.current_world_time_minutes == 0
    assert state_snapshot(actor.dynamic_state) == before_state
    assert actor.tool_learning_json == before_learning
    assert db.scalar(select(func.count()).select_from(Event)) == 0


def test_downstream_failure_is_not_a_successful_learned_action(db):
    world, (actor,) = make_world(db, agent_count=1)
    ensure_v5_agent_state(actor)
    actor.wallet_json = {**actor.wallet_json, "housing": {}}
    result = effect_engine.execute_tool(db, world=world, actor=actor, tool_name="return_home")
    assert result.event_ids
    assert all(db.get(Event, event_id).event_type == "tool_failed" for event_id in result.event_ids)
    assert not result.ok
    assert result.message
    assert not (actor.desires_json or {}).get("recent_action_rewards")
    assert all("trait_growth" not in (db.get(Event, event_id).payload or {}) for event_id in result.event_ids)


def test_unmatched_market_purchase_is_not_rewarded_as_success(db):
    world, (actor,) = make_world(db, agent_count=1)
    ensure_v5_agent_state(actor)
    actor.location.location_id = f"{world.world_id}:market"
    before = deepcopy(actor.wallet_json)
    result = effect_engine.execute_tool(
        db, world=world, actor=actor, tool_name="market_buy_goods",
        params={"item_query": "不存在的模拟测试商品", "speech": "情绪：开心"},
    )
    events = [db.get(Event, event_id) for event_id in result.event_ids]
    assert any(event.event_type == "market_purchase_failed" for event in events)
    assert not result.ok
    assert result.message
    assert actor.wallet_json == before
    assert not (actor.desires_json or {}).get("recent_action_rewards")
    assert all("trait_growth" not in (event.payload or {}) for event in events)


def test_successful_savepoint_still_belongs_to_the_callers_transaction(db):
    world, (actor,) = make_world(db, agent_count=1)
    ensure_v5_agent_state(actor)
    db.commit()
    assert effect_engine.execute_tool(db, world=world, actor=actor, tool_name="do_nothing").ok
    db.rollback()
    assert world.current_world_time_minutes == 0
    assert db.scalar(select(func.count()).select_from(Event)) == 0


def test_multiple_effects_preserve_the_original_before_value(db):
    world, (actor,) = make_world(db, agent_count=1)
    ensure_v5_agent_state(actor)
    before = state_snapshot(actor.dynamic_state)
    result = effect_engine.execute_tool(
        db, world=world, actor=actor, tool_name="speak_to_nearby", params={"speech": "天气很好。情绪：开心"},
    )
    assert result.ok
    event = db.get(Event, result.event_ids[0])
    delta = event.state_delta[actor.agent_id]
    for field, change in delta.items():
        assert change["before"] == before[field]
        assert change["after"] == state_snapshot(actor.dynamic_state)[field]


def test_expressed_emotion_survives_the_action_effect(db):
    world, (actor,) = make_world(db, agent_count=1)
    initial = state_snapshot(actor.dynamic_state)
    plain = effect_engine.execute_tool(db, world=world, actor=actor, tool_name="speak_to_nearby", params={"speech": "天气很好。"})
    assert plain.ok
    plain_mood = actor.dynamic_state.mood
    for name, value in initial.items():
        setattr(actor.dynamic_state, name, value)
    happy = effect_engine.execute_tool(db, world=world, actor=actor, tool_name="speak_to_nearby", params={"speech": "天气很好。情绪：开心"})
    assert happy.ok
    assert actor.dynamic_state.mood > plain_mood + 1


@pytest.mark.parametrize("elapsed, expected_minutes", [(0, 0), (120, 120), (360, 240)])
@pytest.mark.parametrize("quality", ["normal", "rough"])
def test_sleep_completion_accounts_only_for_the_real_sleep_window(db, elapsed, expected_minutes, quality):
    world, (actor,) = make_world(db, agent_count=1)
    ensure_v5_agent_state(actor)
    actor.dynamic_state.energy = 20
    actor.dynamic_state.last_decay_world_time = 100
    actor.desires_json = {
        "sleep_started_world_time": 100, "sleep_until_world_time": 340,
        "sleep_planned_minutes": 240, "sleep_quality": quality,
        "sleep_quota_day": 1, "sleep_minutes_today": 0,
        "awake_since_world_time": 10,
    }
    world.current_world_time_minutes = 100 + elapsed
    before = state_snapshot(actor.dynamic_state)
    event_ids = effect_engine.complete_scheduled_sleep(db, world, actor, interrupted=elapsed < 240)
    wake = db.get(Event, event_ids[0])
    assert wake.payload["sleep_minutes"] == expected_minutes
    assert actor.desires_json["sleep_minutes_today"] == expected_minutes
    if expected_minutes:
        assert actor.desires_json["last_sleep_duration_minutes"] == expected_minutes
        assert actor.desires_json["awake_since_world_time"] == 100 + expected_minutes
        assert any(db.get(Event, event_id).event_type == "dream_summary" for event_id in event_ids)
    else:
        assert actor.desires_json["awake_since_world_time"] == 10
        assert state_snapshot(actor.dynamic_state) == before
        assert len(event_ids) == 1
    after = state_snapshot(actor.dynamic_state)
    assert effect_engine.complete_scheduled_sleep(db, world, actor) == []
    assert state_snapshot(actor.dynamic_state) == after


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), True, "bad"])
def test_nonfinite_runtime_overrides_cannot_poison_the_world_clock(db, invalid):
    world, _ = make_world(db, agent_count=1)
    world.settings_json = {"worldview_rule_parameters": {"runtime": {
        "tool_time_scale": invalid, "conversation_time_scale": invalid,
        "dynamic_effect_scale": invalid, "awake_hydration": invalid,
    }}}
    profile = profile_for_world(world)
    assert profile["tool_time_scale"] == 1.0
    assert profile["dynamic_effect_scale"] == 1.0
    assert profile["awake_hydration"] == -4.0
    assert math.isfinite(tool_time_cost(world, "rest", 10))
    assert tool_time_cost(world, "speak_to_nearby", 2) == 2


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), "bad"])
def test_nonfinite_werewolf_time_settings_have_safe_defaults(db, invalid):
    world, _ = make_world(db, agent_count=1)
    world.settings_json = {"werewolf_mode_enabled": True, "worldview_rule_parameters": {"werewolf": {
        "tool_time_scale": invalid, "conversation_minutes": invalid,
    }}}
    assert tool_time_cost(world, "werewolf_wolf_discuss", 2) == 4
    assert tool_time_cost(world, "speak_to_nearby", 2) == 6
