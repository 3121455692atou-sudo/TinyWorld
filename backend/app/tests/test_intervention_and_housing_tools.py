from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.content.toolsets import FINANCE_INVESTING_TOOLSET_ID, REPRODUCTION_TOOLSET_ID, SURVIVAL_NEEDS_TOOLSET_ID
from app.core.models import Agent, Event, Location
from app.effects.death import apply_danger_checks
from app.effects.effect_engine import execute_tool, process_world_life_events
from app.economy.v6 import ensure_v6_agent_state, process_daily_economy_tick
from app.knowledge.perception import build_turn_context_with_options
from app.main import app
from app.social.intervention_crush import has_active_intervention_crush
from app.tools.registry import available_tools
from app.tools.validators import validate_tool
from app.world.housing import ensure_agent_home
from app.world.seed_world import private_home_location
from conftest import make_world


RENT_TOOLS = {
    "v6_pay_10_day_rent",
    "v6_ask_landlord_for_grace_period",
    "v6_negotiate_lower_rent",
    "v6_move_to_cheaper_room",
    "v6_offer_labor_for_rent",
}


def test_agent_tools_debug_endpoint_uses_current_registry_signature(db):
    world, agents = make_world(db, 2)
    db.commit()

    response = TestClient(app).get(f"/api/tools/agent/{world.world_id}/{agents[0].agent_id}")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] > 0
    assert not payload.get("error")
    assert any(tool["tool_name"] == "check_self_status" for tool in payload["tools"])


def test_agent_action_options_debug_endpoint_exposes_prompt_menu(db):
    world, agents = make_world(db, 2)
    db.commit()

    response = TestClient(app).get(f"/api/tools/agent/{world.world_id}/{agents[0].agent_id}/action-options")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["raw_tool_count"] > 0
    assert payload["option_count"] > 0
    assert payload["validation_failure_count"] == 0
    assert "action_menu" in payload
    assert any(tool["tool_name"] == "check_self_status" for tool in payload["raw_tools"])
    assert any(option["tool_name"] == "check_self_status" for option in payload["action_options"])


def test_mutual_love_intervention_sets_crush_and_unlocks_romance_tools(db):
    world, agents = make_world(db, 2)
    actor, target = agents
    db.commit()

    response = TestClient(app).post(
        f"/api/worlds/{world.world_id}/interventions",
        json={
            "action": "love_mutual",
            "actor_agent_id": actor.agent_id,
            "target_agent_id": target.agent_id,
        },
    )

    assert response.status_code == 200, response.text
    db.expire_all()
    actor = db.get(Agent, actor.agent_id)
    target = db.get(Agent, target.agent_id)
    assert actor is not None and target is not None
    assert has_active_intervention_crush(actor, target.agent_id, world)
    assert has_active_intervention_crush(target, actor.agent_id, world)

    tools = {spec.tool_name for spec in available_tools(actor, actor.location.location, session=db)}
    assert {
        "ask_date_visible_agent",
        "hold_hands_visible_agent",
        "hug_visible_agent",
        "confess_feelings_visible_agent",
    } <= tools
    assert (actor.family_json or {}).get("partner_agent_id") is None


def test_love_intervention_debug_menu_contains_bound_romance_options(db):
    world, agents = make_world(db, 2)
    actor, target = agents
    db.commit()
    response = TestClient(app).post(
        f"/api/worlds/{world.world_id}/interventions",
        json={
            "action": "love_mutual",
            "actor_agent_id": actor.agent_id,
            "target_agent_id": target.agent_id,
        },
    )
    assert response.status_code == 200, response.text

    menu_response = TestClient(app).get(f"/api/tools/agent/{world.world_id}/{actor.agent_id}/action-options")

    assert menu_response.status_code == 200, menu_response.text
    payload = menu_response.json()
    option_names = {option["tool_name"] for option in payload["action_options"]}
    assert "confess_feelings_visible_agent" in option_names
    confess = next(option for option in payload["action_options"] if option["tool_name"] == "confess_feelings_visible_agent")
    target_ids = {
        choice.get("target_agent_id")
        for choice in confess["target_choices"]
    }
    assert target.agent_id in target_ids
    assert payload["validation_failure_count"] == 0


def test_miracle_birth_child_gets_guardian_home_and_care_tools(db):
    world, agents = make_world(db, 2)
    world.settings_json = {**(world.settings_json or {}), "reproduction_enabled": True}
    parent, co_parent = agents
    db.merge(private_home_location(world.world_id, 0))
    db.merge(private_home_location(world.world_id, 1))
    db.flush()
    parent_home = ensure_agent_home(db, world, parent)
    ensure_agent_home(db, world, co_parent)
    db.commit()

    response = TestClient(app).post(
        f"/api/worlds/{world.world_id}/interventions",
        json={
            "action": "miracle_birth",
            "actor_agent_id": parent.agent_id,
            "target_agent_id": co_parent.agent_id,
        },
    )

    assert response.status_code == 200, response.text
    db.expire_all()
    children = db.execute(
        select(Agent).where(Agent.world_id == world.world_id, Agent.age_stage == "newborn")
    ).scalars().all()
    assert len(children) == 1
    child = children[0]
    housing = (child.wallet_json or {}).get("housing") or {}
    assert housing["status"] == "dependent"
    assert housing["guardian_dependent"] is True
    assert housing["home_location_id"] == parent_home
    assert set((child.family_json or {}).get("guardian_agent_ids") or []) == {parent.agent_id, co_parent.agent_id}

    parent = db.get(Agent, parent.agent_id)
    assert parent is not None
    tools = {spec.tool_name for spec in available_tools(parent, parent.location.location, session=db)}
    assert {
        "check_child_status_visible_agent",
        "feed_child_visible_agent",
        "care_for_child_visible_agent",
    } <= tools


def test_homeowner_mortgage_clears_rent_tools_and_daily_rent_conflict(db):
    world, agents = make_world(db, 1)
    actor = agents[0]
    ensure_agent_home(db, world, actor)
    wallet = ensure_v6_agent_state(actor)
    wallet["money"] = 1000
    wallet["economy_profile"] = {
        **(wallet.get("economy_profile") or {}),
        "credit_score": 95,
        "daily_income_avg": 90,
        "minimum_payment_daily": 0,
    }
    actor.wallet_json = wallet

    result = execute_tool(db, world=world, actor=actor, tool_name="v6_apply_for_mortgage", params={})

    assert result.ok, result.message
    housing = (actor.wallet_json or {}).get("housing") or {}
    assert housing["status"] == "homeowner"
    assert housing["quality_tier"] == "owned_apartment"
    assert housing["rent_per_10_days"] == 0
    assert housing["next_rent_due_day"] is None
    assert housing["rent_late_count"] == 0

    tools = {spec.tool_name for spec in available_tools(actor, actor.location.location, session=db)}
    assert not (tools & RENT_TOOLS)
    assert {"v6_prepay_mortgage", "v6_list_house_for_rent"} <= tools

    rent_attempt = execute_tool(db, world=world, actor=actor, tool_name="v6_pay_10_day_rent", params={})
    assert not rent_attempt.ok
    assert "不需要再处理小屋房租" in rent_attempt.message

    world.current_world_time_minutes = 10 * 1440
    event_ids = process_daily_economy_tick(db, world)
    event_types = [db.get(Event, event_id).event_type for event_id in event_ids]
    assert "v6_rent_payment" not in event_types
    assert "v6_rent_late" not in event_types
    assert "v6_eviction" not in event_types


@pytest.mark.anyio
async def test_due_pregnancy_birth_then_backend_selected_childcare_rescues_newborn(db):
    world, agents = make_world(db, 2)
    world.settings_json = {
        **(world.settings_json or {}),
        "enabled_optional_toolset_ids": [SURVIVAL_NEEDS_TOOLSET_ID, REPRODUCTION_TOOLSET_ID],
        "reproduction_enabled": True,
        "baby_model_pool": [],
    }
    parent, co_parent = agents
    db.merge(private_home_location(world.world_id, 0))
    db.merge(private_home_location(world.world_id, 1))
    db.flush()
    parent_home = ensure_agent_home(db, world, parent)
    ensure_agent_home(db, world, co_parent)
    parent.family_json = {
        **(parent.family_json or {}),
        "pregnancy_state": {
            "pregnant": True,
            "co_parent_agent_id": co_parent.agent_id,
            "started_world_time": 0,
            "due_world_time": world.current_world_time_minutes,
            "discovered": True,
        },
        "children_agent_ids": [],
    }
    db.flush()

    event_ids = await process_world_life_events(db, world, parent)

    birth_event = next(db.get(Event, event_id) for event_id in event_ids if db.get(Event, event_id).event_type == "birth")
    child = db.get(Agent, birth_event.payload["child_agent_id"])
    assert child is not None
    assert child.age_stage == "newborn"
    assert child.location.location_id == parent.location.location_id
    assert (child.wallet_json or {}).get("housing", {}).get("status") == "dependent"
    assert (child.wallet_json or {}).get("housing", {}).get("home_location_id") == parent_home
    assert set((child.family_json or {}).get("guardian_agent_ids") or []) == {parent.agent_id, co_parent.agent_id}
    assert ((parent.family_json or {}).get("pregnancy_state") or None) is None

    state = child.dynamic_state
    state.satiety = 0
    state.hydration = 0
    state.health = 8
    state.energy = 4
    state.zero_satiety_since = world.current_world_time_minutes - 14 * 60
    state.zero_hydration_since = world.current_world_time_minutes - 10 * 60
    child.lifecycle_state = "critical"
    state.critical_reason = "婴幼儿长期缺水"

    warning_ids = apply_danger_checks(db, world, child)
    warning_events = [db.get(Event, event_id) for event_id in warning_ids]
    assert child.lifecycle_state != "dead"
    assert any(event and event.payload and event.payload.get("warning") == "child_need" for event in warning_events)

    context = build_turn_context_with_options(db, world, parent, reaction=True, trigger_text=warning_events[0].viewer_text)
    feed = next(option for option in context.action_options if option.tool_name == "feed_child_visible_agent")
    child_choice = next(choice for choice in feed.target_choices if choice.get("target_agent_id") == child.agent_id)

    result = execute_tool(db, world=world, actor=parent, tool_name=feed.tool_name, params=child_choice["params"], reaction=True)

    assert result.ok, result.message
    assert child.lifecycle_state == "alive"
    assert state.satiety >= 32
    assert state.hydration >= 28
    assert state.health > 20
    assert any(db.get(Event, event_id).event_type == "child_feed" for event_id in result.event_ids)


def test_pregnancy_keeps_survival_tools_but_blocks_extreme_risk_actions(db):
    world, agents = make_world(db, 2)
    world.settings_json = {
        **(world.settings_json or {}),
        "enabled_optional_toolset_ids": [SURVIVAL_NEEDS_TOOLSET_ID, REPRODUCTION_TOOLSET_ID],
        "reproduction_enabled": True,
    }
    actor, target = agents
    actor.family_json = {
        **(actor.family_json or {}),
        "pregnancy_state": {
            "pregnant": True,
            "co_parent_agent_id": target.agent_id,
            "started_world_time": 0,
            "due_world_time": 3 * 1440,
            "discovered": True,
        },
    }
    actor.dynamic_state.energy = 80
    actor.dynamic_state.satiety = 80
    actor.dynamic_state.hydration = 80
    actor.location.location_id = f"{world.world_id}:cafeteria"
    actor.location.location = db.get(Location, actor.location.location_id)

    drink = validate_tool(db, actor=actor, tool_name="drink_water", params={}, world_time=world.current_world_time_minutes)
    attack = validate_tool(db, actor=actor, tool_name="attack_visible_agent", params={"visible_ref": "居民A"}, world_time=world.current_world_time_minutes)
    overtime = validate_tool(db, actor=actor, tool_name="work_overtime_shift", params={}, world_time=world.current_world_time_minutes)

    assert drink.ok, drink.message
    assert attack.reason_code == "pregnancy_restricted"
    assert overtime.reason_code == "pregnancy_restricted"

    actor.location.location_id = f"{world.world_id}:workshop"
    actor.location.location = db.get(Location, actor.location.location_id)
    actor.work_json = {"job": "工坊", "job_role": "workshop", "employed": True, "fatigue": 0}
    tool_names = {spec.tool_name for spec in available_tools(actor, actor.location.location, session=db)}
    assert "work_overtime_shift" not in tool_names


def test_backend_selected_hard_to_trigger_v6_tools_execute_real_effects(db):
    world, agents = make_world(db, 1)
    world.settings_json = {
        **(world.settings_json or {}),
        "enabled_optional_toolset_ids": [SURVIVAL_NEEDS_TOOLSET_ID, FINANCE_INVESTING_TOOLSET_ID],
    }
    actor = agents[0]
    actor.location.location_id = f"{world.world_id}:library"
    actor.location.location = db.get(Location, actor.location.location_id)
    actor.dynamic_state.satiety = 82
    actor.dynamic_state.hydration = 82
    actor.dynamic_state.health = 90
    actor.dynamic_state.energy = 80
    wallet = ensure_v6_agent_state(actor)
    wallet["money"] = 800
    wallet["economy_profile"] = {
        **(wallet.get("economy_profile") or {}),
        "credit_score": 95,
        "daily_income_avg": 90,
        "minimum_payment_daily": 0,
        "financial_literacy": 80,
        "risk_tolerance": 75,
    }
    wallet["housing"] = {**(wallet.get("housing") or {}), "homeless": True, "status": "homeless"}
    actor.wallet_json = wallet

    sleep_result = execute_tool(db, world=world, actor=actor, tool_name="v6_sleep_rough_when_homeless", params={"sleep_hours": 3})
    sleep_event = db.get(Event, sleep_result.event_ids[0])
    assert sleep_result.ok, sleep_result.message
    assert sleep_event.payload["sleep_is_real_schedule"] is True
    assert (actor.desires_json or {}).get("sleep_until_world_time") == world.current_world_time_minutes + 180

    actor.desires_json = {
        **(actor.desires_json or {}),
        "sleep_until_world_time": None,
        "sleep_started_world_time": None,
        "sleep_planned_minutes": None,
    }
    wallet = ensure_v6_agent_state(actor)
    wallet["housing"] = {**(wallet.get("housing") or {}), "homeless": False, "status": "renter", "next_rent_due_day": None}
    actor.wallet_json = wallet

    open_result = execute_tool(db, world=world, actor=actor, tool_name="v6_open_broker_account", params={})
    deposit_result = execute_tool(db, world=world, actor=actor, tool_name="v6_deposit_to_broker", params={"amount": 200})
    assert open_result.ok, open_result.message
    assert deposit_result.ok, deposit_result.message

    action_context = build_turn_context_with_options(db, world, actor)
    stock_buy_options = [option for option in action_context.action_options if option.tool_name == "v6_place_market_buy_order"]
    assert any(option.params.get("ticker") == "MGL" for option in stock_buy_options)
    stock_validation = validate_tool(
        db,
        actor=actor,
        tool_name="v6_place_market_buy_order",
        params=next(option.params for option in stock_buy_options if option.params.get("ticker") == "MGL"),
        world_time=world.current_world_time_minutes,
        persist_visibility=False,
    )
    assert stock_validation.ok, stock_validation.message

    buy_result = execute_tool(db, world=world, actor=actor, tool_name="v6_place_market_buy_order", params={"ticker": "MGL"})
    sell_result = execute_tool(db, world=world, actor=actor, tool_name="v6_place_market_sell_order", params={"ticker": "MGL"})

    assert buy_result.ok, buy_result.message
    assert sell_result.ok, sell_result.message
    broker = (actor.wallet_json or {}).get("broker_account") or {}
    assert broker
    assert float(broker.get("cash_available", 0)) > 0
    assert any(db.get(Event, event_id).event_type == "v6_stock_trade" for event_id in [*buy_result.event_ids, *sell_result.event_ids])

    mortgage_result = execute_tool(db, world=world, actor=actor, tool_name="v6_apply_for_mortgage", params={})
    assert mortgage_result.ok, mortgage_result.message
    list_result = execute_tool(db, world=world, actor=actor, tool_name="v6_list_house_for_rent", params={})
    enable_result = execute_tool(db, world=world, actor=actor, tool_name="v6_enable_system_void_tenant", params={})
    wallet = dict(actor.wallet_json or {})
    assets = [dict(asset) for asset in wallet.get("assets", [])]
    house = next(asset for asset in assets if asset.get("asset_type") == "house")
    house["next_system_rent_day"] = world.current_world_time_minutes // 1440
    wallet["assets"] = assets
    actor.wallet_json = wallet
    money_before = int((actor.wallet_json or {}).get("money", 0))
    collect_result = execute_tool(db, world=world, actor=actor, tool_name="v6_collect_system_tenant_rent", params={})

    assert list_result.ok, list_result.message
    assert enable_result.ok, enable_result.message
    assert collect_result.ok, collect_result.message
    assert int((actor.wallet_json or {}).get("money", 0)) > money_before
    assert any(db.get(Event, event_id).event_type == "v6_landlord" for event_id in collect_result.event_ids)
