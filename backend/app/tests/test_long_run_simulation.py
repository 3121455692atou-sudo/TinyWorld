from __future__ import annotations

import asyncio
from dataclasses import asdict

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agents.state import state_snapshot
from app.core import database
from app.core.models import Agent, Base, Event, Inventory, World
from app.effects.effect_engine import execute_tool
from app.knowledge.perception import build_turn_context_with_options
from app.llm.action_protocol import parse_action_choice
from app.llm.provider_base import LLMResult
from app.simulation.reaction_queue import ReactionTask, reaction_queue
from app.simulation.difficulty import profile_for_world
from app.tools.validators import validate_tool
from app.tests.simulation_harness import (
    DeterministicResidentProvider,
    assert_world_invariants,
    menu_packet,
    offline_simulation,
    run_simulation,
    seed_simulation_world,
)


@pytest.mark.parametrize(("seed", "mode"), [(7, "batch"), (29, "per_agent"), (101, "parallel")])
def test_multiday_real_scheduler_survival_and_persistence(db, seed, mode):
    report = asyncio.run(run_simulation(seed=seed, rounds=96, mode=mode))

    details = asdict(report)
    assert report.rounds == 96, details
    # The scenario begins at 08:00, so crossing two day boundaries also exercises
    # daily economy and sleep quota resets without assuming an action duration.
    assert report.calendar_days_crossed >= 2, details
    assert report.provider_calls >= 96, details
    assert report.protocol_faults >= 1, details
    assert report.repair_calls >= report.protocol_faults, details
    assert report.max_menu_options <= 140, details
    assert report.persisted_clock_regressions == 0, details
    assert report.max_consecutive_no_time_advance_rounds < 10, details
    assert report.failed_actions_by_tool.get("accept_community_aid", 0) == 0, details
    assert len(report.selected_actions) >= 8, details
    assert report.event_types.get("eat", 0) >= 4, details
    assert report.event_types.get("drink", 0) >= 4, details
    assert all(agent["lifecycle"] in {"alive", "critical"} for agent in report.final_agents), details


def test_same_seed_replays_after_recreating_the_database(db, tmp_path, monkeypatch):
    first = asyncio.run(run_simulation(seed=41, rounds=6))
    engine = database._make_engine(f"sqlite:///{tmp_path / 'independent_replay.sqlite3'}")
    Base.metadata.create_all(engine)
    try:
        with monkeypatch.context() as context:
            context.setattr(database, "engine", engine)
            context.setattr(database, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))
            second = asyncio.run(run_simulation(seed=41, rounds=6))
        assert asdict(first) == asdict(second)
    finally:
        engine.dispose()


def test_queued_foreign_world_resident_cannot_act_in_another_world(db):
    world, _ = seed_simulation_world(db, world_id="world_queue_a", seed=17, residents=2)
    foreign, (other,) = seed_simulation_world(db, world_id="world_queue_b", seed=18, residents=1)
    before = state_snapshot(other.dynamic_state)
    before_money = dict(other.wallet_json)
    before_time = foreign.current_world_time_minutes
    reaction_queue.push(world.world_id, ReactionTask(other.agent_id, "A stale queue entry", created_world_time=before_time), max_depth=3)
    stub = DeterministicResidentProvider(17, malformed_every=0)

    async def step():
        with offline_simulation(stub) as manager:
            return await manager.step(world.world_id)

    try:
        result = asyncio.run(step())
        db.expire_all()
        actual = db.get(Agent, other.agent_id)
        assert actual is not None
        assert state_snapshot(actual.dynamic_state) == before
        assert actual.wallet_json == before_money
        assert db.get(World, foreign.world_id).current_world_time_minutes == before_time
        assert other.agent_id not in result["acted_agent_ids"]
        assert_world_invariants(db, world.world_id, min_time=before_time, event_ids=result["event_ids"])
        assert db.scalar(select(Event.event_id).where(Event.world_id == world.world_id, Event.actor_agent_id == other.agent_id).limit(1)) is None
    finally:
        reaction_queue.clear(world.world_id)
        reaction_queue.clear(foreign.world_id)


def test_stale_menu_visible_ref_never_retargets_the_next_resident(db):
    world, (actor, chosen, replacement) = seed_simulation_world(db, world_id="world_stale", seed=33, residents=3)
    context = build_turn_context_with_options(db, world, actor)
    option = next(item for item in context.action_options if item.tool_name == "say_to_visible_agent")
    target = next(item for item in option.target_choices if item["target_agent_id"] == chosen.agent_id)
    parsed = parse_action_choice(f"[{option.option_id}:{target['id']}]\n你现在方便说句话吗？", context.action_options, agent=actor)
    assert parsed.action is not None
    original_ref = parsed.action.params["visible_ref"]
    assert parsed.action.params.get("visible_agent_id") == chosen.agent_id

    movement = execute_tool(db, world=world, actor=chosen, tool_name="move_to_location", params={"location_id": f"{world.world_id}:garden"})
    assert movement.ok
    db.flush()
    current_context = build_turn_context_with_options(db, world, actor)
    assert current_context.ref_map[original_ref] == replacement.agent_id
    before = state_snapshot(replacement.dynamic_state)
    result = execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params)

    assert not result.ok
    assert state_snapshot(replacement.dynamic_state) == before
    events = [db.get(Event, event_id) for event_id in result.event_ids]
    assert not any(event and event.event_type == "dialogue" for event in events)
    assert not any(event and event.target_agent_id == replacement.agent_id for event in events)


def test_pending_inventory_action_cannot_consume_a_depleted_supply_twice(db):
    world, (actor,) = seed_simulation_world(db, world_id="world_supply", seed=34, residents=1)
    context = build_turn_context_with_options(db, world, actor)
    option = next(item for item in context.action_options if item.tool_name == "eat_portable_food")
    parsed = parse_action_choice(f"[{option.option_id}]\n-", context.action_options, agent=actor)
    assert parsed.action is not None
    first = execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params)
    assert first.ok
    before = state_snapshot(actor.dynamic_state)
    learned = dict(actor.tool_learning_json or {})
    second = execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params)
    db.commit()

    assert not second.ok
    assert state_snapshot(actor.dynamic_state) == before
    assert (actor.tool_learning_json or {}).get("trait_experience") == learned.get("trait_experience")
    assert not any(db.get(Event, event_id).event_type == "eat" for event_id in second.event_ids)
    with database.SessionLocal() as observer:
        row = observer.scalar(select(Inventory).where(Inventory.agent_id == actor.agent_id, Inventory.item_id == f"{actor.agent_id}_food"))
        assert row is None or row.quantity == 0
        stored = observer.get(Agent, actor.agent_id)
        assert stored is not None and state_snapshot(stored.dynamic_state) == before


def test_real_community_aid_cooldown_hides_menu_and_rejects_a_pending_replay(db):
    world, (actor,) = seed_simulation_world(db, world_id="world_aid_retry", seed=36, residents=1)
    context = build_turn_context_with_options(db, world, actor)
    option = next(item for item in context.action_options if item.tool_name == "accept_community_aid")
    parsed = parse_action_choice(f"[{option.option_id}]\n我需要一份基础食物和饮水援助。", context.action_options, agent=actor)
    assert parsed.action is not None
    first = execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params)
    assert first.ok
    assert any(db.get(Event, event_id).event_type == "aid" for event_id in first.event_ids)
    last_aid = actor.desires_json["last_community_aid_world_time"]
    before = state_snapshot(actor.dynamic_state)
    before_items = list(db.execute(select(Inventory.item_id, Inventory.quantity).where(Inventory.agent_id == actor.agent_id).order_by(Inventory.item_id)))

    # The model selected this action before the first one executed. A stale
    # pending choice must not grant a second package or spend action time.
    blocked = build_turn_context_with_options(db, world, actor)
    assert not any(item.tool_name == "accept_community_aid" for item in blocked.action_options)
    failure = execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params)
    db.commit()
    assert not failure.ok
    assert world.current_world_time_minutes == last_aid
    assert state_snapshot(actor.dynamic_state) == before
    assert db.get(Event, failure.event_ids[0]).payload["failure_reason_code"] == "community_aid_cooldown"
    with database.SessionLocal() as observer:
        after_items = list(observer.execute(select(Inventory.item_id, Inventory.quantity).where(Inventory.agent_id == actor.agent_id).order_by(Inventory.item_id)))
        assert after_items == before_items
        assert observer.get(Agent, actor.agent_id).desires_json["last_community_aid_world_time"] == last_aid

    # Start just before the expiry boundary; a normal real action crosses it.
    cooldown = int(profile_for_world(world)["aid_food_cooldown_h"]) * 60
    world.current_world_time_minutes = last_aid + cooldown - 1
    validation = validate_tool(db, actor=actor, tool_name="accept_community_aid", params={}, world_time=world.current_world_time_minutes)
    assert not validation.ok and validation.reason_code == "community_aid_cooldown"
    assert execute_tool(db, world=world, actor=actor, tool_name="look_around", params={}).ok
    available = build_turn_context_with_options(db, world, actor)
    option = next(item for item in available.action_options if item.tool_name == "accept_community_aid")
    parsed = parse_action_choice(f"[{option.option_id}]\n我想再领取一份基础援助。", available.action_options, agent=actor)
    assert parsed.action is not None
    assert execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params).ok


def test_real_insomnia_cannot_freeze_the_scheduler_at_one_timestamp(db):
    world, (actor,) = seed_simulation_world(db, world_id="world_insomnia", seed=0, residents=1)
    world.current_world_time_minutes = 22 * 60
    actor.dynamic_state.energy = 90
    actor.dynamic_state.last_decay_world_time = world.current_world_time_minutes
    actor.desires_json = {
        "awake_since_world_time": 21 * 60,
        "last_sleep_end_world_time": 21 * 60,
    }
    context = build_turn_context_with_options(db, world, actor)
    sleep = next(item for item in context.action_options if item.tool_name == "sleep_rough")
    parsed = parse_action_choice(f"[{sleep.option_id}:8]\n-", context.action_options, agent=actor)
    assert parsed.action is not None
    before_time = world.current_world_time_minutes
    failure = execute_tool(db, world=world, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params)
    db.commit()

    # This seed takes the real stochastic insomnia branch. Previously it cost
    # zero time and rerolled with the same seed/time, creating an endless loop.
    assert not failure.ok
    events = [db.get(Event, event_id) for event_id in failure.event_ids]
    assert any(event and event.event_type == "sleep_failed" for event in events)
    assert world.current_world_time_minutes >= before_time + 15
    assert not any((event.payload or {}).get("trait_growth") for event in events)
    assert not validate_tool(db, actor=actor, tool_name="sleep_rough", params={"sleep_hours": 8}, world_time=world.current_world_time_minutes).ok
    blocked = build_turn_context_with_options(db, world, actor)
    assert not any(item.tool_name in {"sleep", "sleep_rough"} or item.params.get("sleep_after_arrival") for item in blocked.action_options)

    class AwakeProvider:
        async def complete_text(self, *args, **kwargs):
            return LLMResult(menu_packet(kwargs["user_prompt"], "环顾四周"), None, {}, 1, "offline-regression")

    async def step():
        with offline_simulation(AwakeProvider()) as manager:
            return await manager.step(world.world_id)

    try:
        after_attempt = world.current_world_time_minutes
        result = asyncio.run(step())
        db.expire_all()
        assert result["acted_agent_ids"] == [actor.agent_id]
        assert world.current_world_time_minutes > after_attempt
        rest = execute_tool(db, world=world, actor=actor, tool_name="rest", params={})
        assert rest.ok
        assert validate_tool(db, actor=actor, tool_name="sleep_rough", params={"sleep_hours": 8}, world_time=world.current_world_time_minutes).ok
    finally:
        reaction_queue.clear(world.world_id)


def test_survival_route_does_not_stall_after_two_consecutive_moves(db):
    world, (actor,) = seed_simulation_world(db, world_id="world_route_retry", seed=97, residents=1)
    actor.dynamic_state.hydration = 5
    actor.dynamic_state.satiety = 80
    actor.dynamic_state.energy = 80
    assert execute_tool(db, world=world, actor=actor, tool_name="drink_bottled_water", params={}).ok
    for destination in ("garden", "central_square"):
        assert execute_tool(db, world=world, actor=actor, tool_name="move_to_location", params={"location_id": f"{world.world_id}:{destination}"}).ok
    db.commit()
    before_time = world.current_world_time_minutes
    stub = DeterministicResidentProvider(97, malformed_every=0)

    async def step():
        with offline_simulation(stub) as manager:
            return await manager.step(world.world_id)

    try:
        result = asyncio.run(step())
        db.expire_all()
        # The same public menu previously offered another route to water, then
        # rejected both the first route and its repair as repeated movement.
        # No action meant no new history or time to ever unblock the next turn.
        assert result["acted_agent_ids"] == [actor.agent_id], result
        assert world.current_world_time_minutes > before_time, result
    finally:
        reaction_queue.clear(world.world_id)


def test_repeated_target_failures_are_hidden_for_one_turn_then_recover(db):
    world, (actor, _other) = seed_simulation_world(db, world_id="world_retry", seed=35, residents=2)
    initial_time = world.current_world_time_minutes
    for _ in range(3):
        failure = execute_tool(db, world=world, actor=actor, tool_name="say_to_visible_agent", params={"visible_ref": "missing-person", "speech": "等等。"})
        assert not failure.ok
    assert world.current_world_time_minutes == initial_time
    db.commit()

    class LookProvider:
        def __init__(self):
            self.seen = set()

        async def complete_text(self, *args, **kwargs):
            actor_key = kwargs["model_name"]
            label = "检查自身状态" if actor_key in self.seen else "环顾四周"
            self.seen.add(actor_key)
            return LLMResult(menu_packet(kwargs["user_prompt"], label), None, {}, 1, "offline-regression")

    async def two_turns():
        with offline_simulation(LookProvider()) as manager:
            first = await manager.step(world.world_id)
            with database.SessionLocal() as observer:
                stored = observer.get(Agent, actor.agent_id)
                menu = stored.tool_learning_json["tool_audit_history"][-1]["menu"]
                assert "say_to_visible_agent" not in {item["tool_name"] for item in menu}
            second = await manager.step(world.world_id)
            return first, second

    try:
        results = asyncio.run(two_turns())
        db.expire_all()
        actor = db.get(Agent, actor.agent_id)
        menu = actor.tool_learning_json["tool_audit_history"][-1]["menu"]
        assert "say_to_visible_agent" in {item["tool_name"] for item in menu}
        assert all(actor.agent_id in result["acted_agent_ids"] for result in results)
    finally:
        reaction_queue.clear(world.world_id)
