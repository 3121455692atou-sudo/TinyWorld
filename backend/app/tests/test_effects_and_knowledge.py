from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.agents.identity_generation import create_agent_with_identity
from app.api.serializers import agent_list_item
from app.api.worlds import _delete_world_rows
from app.core.config import settings
from app.effects.decay import apply_time_decay
from app.effects.death import apply_danger_checks
from app.effects.effect_engine import complete_scheduled_sleep, execute_tool, process_world_life_events
from app.economy.v6 import ensure_v6_agent_state, process_daily_economy_tick
from app.events.event_store import create_event
from app.knowledge.identity_knowledge import observer_knows_name
from app.knowledge.relationships import adjust_relationship
from app.knowledge.perception import build_turn_context
from app.core.models import Agent, Event, Location, Memory, NarratorRun, World
from app.llm.provider_base import LLMResult
from app.llm.openai_compatible import provider
from app.narrator.narrator_service import create_narration
from app.tools.registry import available_tools
from app.tools.validators import validate_tool
from app.simulation.turn_runner import turn_runner
from app.world.corpses import apply_corpse_exposure

from conftest import make_world


def _packet_from_prompt(user_prompt: str, label_contains: str | tuple[str, ...], *, value: str = "-", text: str = "-") -> str:
    labels = (label_contains,) if isinstance(label_contains, str) else label_contains
    for wanted in labels:
        for line in str(user_prompt).splitlines():
            match = re.match(r"^\s*(\d{1,3})\s+(.+)$", line.strip())
            if match and wanted in match.group(2):
                return f"[{match.group(1)}:{value}]\n{text}" if value != "-" else f"[{match.group(1)}]\n{text}"
    raise AssertionError(f"未在行动菜单里找到: {labels}\n" + str(user_prompt)[-1800:])


def test_decay_changes_dynamic_state(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    apply_time_decay(agent, 60)
    assert round(agent.dynamic_state.energy, 1) == 78.5
    assert round(agent.dynamic_state.satiety, 1) == 84.2
    assert round(agent.dynamic_state.hydration, 1) == 86.0


def test_eat_food_hard_effect(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:cafeteria"
    agent.dynamic_state.satiety = 40
    result = execute_tool(db, world=world, actor=agent, tool_name="eat_food", params={})
    assert result.ok
    assert agent.dynamic_state.satiety > 70
    assert world.current_world_time_minutes == 20


def test_overtime_shift_trades_sleep_and_health_for_more_money(db):
    world, agents = make_world(db, 1)
    world.current_world_time_minutes = 21 * 60
    agent = agents[0]
    work_location = db.get(Location, f"{world.world_id}:workshop")
    agent.location.location_id = work_location.location_id
    agent.location.location = work_location
    agent.wallet_json = {"money": 0}
    agent.work_json = {"job": "夜间安保", "job_role": "night_guard", "employed": True, "fatigue": 0}
    agent.desires_json = {"awake_since_world_time": 8 * 60}
    agent.dynamic_state.energy = 80
    agent.dynamic_state.satiety = 85
    agent.dynamic_state.hydration = 85
    agent.dynamic_state.health = 100
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    result = execute_tool(db, world=world, actor=agent, tool_name="work_overtime_shift", params={})

    assert result.ok
    assert world.current_world_time_minutes == 23 * 60
    assert agent.wallet_json["money"] == 70
    assert agent.dynamic_state.health == 98
    assert agent.desires_json["sleep_debt_minutes"] == 60
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "work_overtime"
    assert event.payload["tradeoff"] == "money_for_health_and_sleep"


@pytest.mark.anyio
async def test_financial_pressure_allows_llm_to_choose_overtime_at_bedtime(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 1)
    turn_runner._round_robin_index.pop(world.world_id, None)
    world.current_world_time_minutes = 22 * 60
    agent = agents[0]
    work_location = db.get(Location, f"{world.world_id}:workshop")
    agent.location.location_id = work_location.location_id
    agent.location.location = work_location
    agent.wallet_json = {"money": 0}
    agent.work_json = {"job": "夜间安保", "job_role": "night_guard", "employed": True, "fatigue": 0}
    agent.desires_json = {"awake_since_world_time": 8 * 60}
    agent.dynamic_state.energy = 80
    agent.dynamic_state.satiety = 85
    agent.dynamic_state.hydration = 85
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    async def choose_overtime(*args, **kwargs):
        return LLMResult(_packet_from_prompt(kwargs["user_prompt"], "加班换钱"), None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", choose_overtime)

    turn = await turn_runner.run_one_step(db, world.world_id)

    assert turn.acted_agent_id == agent.agent_id
    assert agent.wallet_json["money"] == 70
    assert agent.desires_json["sleep_debt_minutes"] == 120
    assert agent.location.location_id == f"{world.world_id}:workshop"


@pytest.mark.anyio
async def test_regular_agents_act_in_same_simulated_time_slice(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 3)
    turn_runner._round_robin_index.pop(world.world_id, None)
    world.current_world_time_minutes = 8 * 60
    for agent in agents:
        agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    async def choose_nothing(*args, **kwargs):
        return LLMResult(_packet_from_prompt(kwargs["user_prompt"], "什么也不做"), None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", choose_nothing)

    turn = await turn_runner.run_one_step(db, world.world_id)

    assert turn.status == "batch_ok"
    assert set(turn.acted_agent_ids) == {agent.agent_id for agent in agents}
    assert world.current_world_time_minutes == 8 * 60 + 10
    nothing_events = list(db.execute(select(Event).where(Event.world_id == world.world_id, Event.event_type == "nothing")).scalars())
    assert len(nothing_events) == 3
    assert {event.world_time for event in nothing_events} == {8 * 60 + 10}


def test_v6_premium_food_keeps_old_fullness_but_changes_hedonic_state(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:cafeteria"
    agent.wallet_json = {"money": 100}
    agent.dynamic_state.satiety = 40
    ensure_v6_agent_state(agent)
    before_threshold = agent.wallet_json["hedonic_state"]["luxury_threshold"]

    result = execute_tool(db, world=world, actor=agent, tool_name="v6_buy_premium_meal_for_dopamine", params={})

    assert result.ok
    assert round(agent.dynamic_state.satiety, 1) == 74
    assert agent.wallet_json["hedonic_state"]["luxury_threshold"] > before_threshold
    assert agent.wallet_json["money"] == 82


@pytest.mark.anyio
async def test_long_sleep_schedules_and_world_skips_to_wake_time(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:cabin"

    result = execute_tool(db, world=world, actor=agent, tool_name="sleep", params={"sleep_hours": 9})
    assert result.ok
    assert world.current_world_time_minutes == 0
    assert agent.desires_json["sleep_until_world_time"] == 9 * 60

    turn = await turn_runner.run_one_step(db, world.world_id)

    assert turn.status == "sleep_advanced"
    assert world.current_world_time_minutes == 9 * 60
    assert not agent.desires_json.get("sleep_until_world_time")


def test_sleep_request_caps_at_ten_hours_and_blocks_extra_sleep_same_day(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:cabin"

    result = execute_tool(db, world=world, actor=agent, tool_name="sleep", params={"sleep_hours": 16})

    assert result.ok
    start_event = db.get(Event, result.event_ids[0])
    assert start_event.payload["sleep_requested_hours"] == 10
    assert start_event.payload["sleep_hours"] == 10
    assert agent.desires_json["sleep_until_world_time"] == 10 * 60
    assert agent.desires_json["sleep_capped_by_daily_limit"] is False

    world.current_world_time_minutes = agent.desires_json["sleep_until_world_time"]
    wake_ids = complete_scheduled_sleep(db, world, agent)
    wake_event = db.get(Event, wake_ids[0])
    assert wake_event.payload["sleep_minutes"] == 10 * 60
    assert "睡够了" in wake_event.viewer_text
    assert agent.desires_json["sleep_minutes_today"] == 10 * 60

    validation = validate_tool(db, actor=agent, tool_name="sleep", params={"sleep_hours": 1}, world_time=world.current_world_time_minutes)
    assert not validation.ok
    assert validation.reason_code == "daily_sleep_limit"


def test_identity_anti_omniscience_and_name_gate(db):
    world, (a, b, c) = make_world(db, 3)
    prompt, refs = build_turn_context(db, world, a)
    assert b.appearance_short in prompt
    assert b.chosen_name not in prompt

    first_ref = next(ref for ref, target_id in refs.items() if target_id == b.agent_id)
    say_result = execute_tool(db, world=world, actor=a, tool_name="say_to_visible_agent", params={"visible_ref": first_ref, "speech": "你好，我想认识你。"})
    assert say_result.ok

    promise_validation = validate_tool(db, actor=a, tool_name="promise_to_named_agent", params={"known_name": b.chosen_name}, world_time=world.current_world_time_minutes)
    assert not promise_validation.ok
    assert promise_validation.reason_code == "name_unknown"

    b_prompt, b_refs = build_turn_context(db, world, b, reaction=True, trigger_text="有人请求你介绍自己。")
    a_ref_for_b = next(ref for ref, target_id in b_refs.items() if target_id == a.agent_id)
    refuse_result = execute_tool(db, world=world, actor=b, tool_name="refuse_introduction", params={"visible_ref": a_ref_for_b})
    assert refuse_result.ok
    assert not observer_knows_name(db, a.agent_id, b.agent_id)

    intro_result = execute_tool(db, world=world, actor=b, tool_name="introduce_self", params={"visible_ref": a_ref_for_b, "reveal_name": True, "speech": "你好，我愿意正式介绍自己。"})
    assert intro_result.ok
    intro_event = db.get(Event, intro_result.event_ids[0])
    assert intro_event.payload["speech"]
    assert observer_knows_name(db, a.agent_id, b.agent_id)
    assert observer_knows_name(db, c.agent_id, b.agent_id)

    refuse_after_known = execute_tool(db, world=world, actor=b, tool_name="refuse_introduction", params={"visible_ref": a_ref_for_b})
    assert refuse_after_known.ok
    refuse_event = db.get(Event, refuse_after_known.event_ids[0])
    assert "没有继续自我介绍" in refuse_event.viewer_text
    assert "没有透露姓名" not in refuse_event.viewer_text

    c_prompt, _ = build_turn_context(db, world, c)
    assert b.chosen_name in c_prompt

    promise_validation_after = validate_tool(db, actor=a, tool_name="promise_to_named_agent", params={"known_name": b.chosen_name}, world_time=world.current_world_time_minutes)
    assert promise_validation_after.ok


def test_private_rooms_are_visible_but_not_directly_enterable(db):
    world, (a, b) = make_world(db, 2)
    a_home = Location(location_id=f"{world.world_id}:private_a", world_id=world.world_id, public_name="A的小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    b_home = Location(location_id=f"{world.world_id}:private_b", world_id=world.world_id, public_name="B的小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    db.add_all([a_home, b_home])
    db.flush()
    a.wallet_json = {"money": 54, "housing": {"home_location_id": a_home.location_id}}
    b.wallet_json = {"money": 54, "housing": {"home_location_id": b_home.location_id}}

    prompt, _ = build_turn_context(db, world, a)
    assert "你的住所: A的小屋" in prompt
    assert "B的小屋" in prompt

    direct = validate_tool(db, actor=a, tool_name="move_to_location", params={"location_id": b_home.location_id}, world_time=world.current_world_time_minutes)
    assert not direct.ok
    assert direct.reason_code == "private_room_blocked"

    knock = execute_tool(db, world=world, actor=a, tool_name="knock_private_room", params={"location_id": b_home.location_id})
    assert knock.ok
    assert a.location.location_id == f"{world.world_id}:central_square"
    event = db.get(Event, knock.event_ids[0])
    assert event.event_type == "knock_room"


def test_social_request_acceptance_completes_real_interaction(db):
    world, (requester, accepter) = make_world(db, 2)
    requester.location.location_id = f"{world.world_id}:central_square"
    accepter.location.location_id = f"{world.world_id}:central_square"
    _prompt, refs = build_turn_context(db, world, requester)
    ref_accepter = next(ref for ref, target_id in refs.items() if target_id == accepter.agent_id)

    request = execute_tool(db, world=world, actor=requester, tool_name="hug_visible_agent", params={"visible_ref": ref_accepter, "speech": "可以抱一下吗？"})

    assert request.ok
    request_event = db.get(Event, request.event_ids[0])
    assert "等待对方接受或拒绝" not in request_event.viewer_text
    assert request_event.payload["speech"] == "可以抱一下吗？"
    assert any(item.get("request_type") == "hug" and item.get("status") == "pending" for item in (accepter.family_json or {}).get("pending_social_requests", []))

    _prompt, refs = build_turn_context(db, world, accepter, reaction=True)
    ref_requester = next(ref for ref, target_id in refs.items() if target_id == requester.agent_id)
    accepted = execute_tool(db, world=world, actor=accepter, tool_name="accept_social_request_visible_agent", params={"visible_ref": ref_requester, "speech": "可以。"})

    assert accepted.ok
    event = db.get(Event, accepted.event_ids[0])
    assert event.event_type == "hug_accepted"
    assert not [item for item in (accepter.family_json or {}).get("pending_social_requests", []) if item.get("status") == "pending"]


def test_sleeping_target_requires_wake_before_talking(db):
    world, (actor, target) = make_world(db, 2)
    world.current_world_time_minutes = 120
    actor.location.location_id = f"{world.world_id}:central_square"
    target.location.location_id = f"{world.world_id}:central_square"
    target.desires_json = {
        **(target.desires_json or {}),
        "sleep_started_world_time": 0,
        "sleep_planned_minutes": 480,
        "sleep_until_world_time": 480,
        "sleep_quality": "normal",
    }
    _prompt, refs = build_turn_context(db, world, actor)
    ref_target = next(ref for ref, target_id in refs.items() if target_id == target.agent_id)

    blocked = execute_tool(db, world=world, actor=actor, tool_name="say_to_visible_agent", params={"visible_ref": ref_target, "speech": "醒着吗？"})

    assert not blocked.ok
    assert "wake_visible_agent" in blocked.message

    woken = execute_tool(db, world=world, actor=actor, tool_name="wake_visible_agent", params={"visible_ref": ref_target, "speech": "醒醒，我有事想和你说。"})

    assert woken.ok
    assert target.agent_id in woken.reaction_agent_ids
    assert not (target.desires_json or {}).get("sleep_until_world_time")
    assert {db.get(Event, event_id).event_type for event_id in woken.event_ids} >= {"wake_request", "wake"}


def test_forced_action_notice_can_be_protested(db, monkeypatch):
    from app.social import forced_actions

    monkeypatch.setattr(forced_actions, "_notice_chance", lambda *args, **kwargs: 1.0)
    world, (actor, target) = make_world(db, 2)
    actor.location.location_id = f"{world.world_id}:central_square"
    target.location.location_id = f"{world.world_id}:central_square"
    target.traits.caution = 100
    _prompt, refs = build_turn_context(db, world, actor)
    ref_target = next(ref for ref, target_id in refs.items() if target_id == target.agent_id)

    attempt = execute_tool(db, world=world, actor=actor, tool_name="force_hug_visible_agent", params={"visible_ref": ref_target})

    assert attempt.ok
    assert any(item.get("action_type") == "hug" and item.get("status") == "pending_notice" for item in (target.family_json or {}).get("pending_forced_social_actions", []))

    _prompt, refs = build_turn_context(db, world, target, reaction=True)
    ref_actor = next(ref for ref, target_id in refs.items() if target_id == actor.agent_id)
    protest = execute_tool(db, world=world, actor=target, tool_name="protest_forced_action_visible_agent", params={"visible_ref": ref_actor, "speech": "先问我。"})

    assert protest.ok
    event = db.get(Event, protest.event_ids[0])
    assert event.event_type == "forced_social_protested"
    assert event.payload["action_type"] == "hug"
    assert event.payload["response"] == "protested"


def test_private_room_burglary_uses_hard_rules(db):
    world, (a, b) = make_world(db, 2)
    b_home = Location(location_id=f"{world.world_id}:private_b", world_id=world.world_id, public_name="B的小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    db.add(b_home)
    db.flush()
    b.wallet_json = {"money": 54, "housing": {"home_location_id": b_home.location_id}}
    a.wallet_json = {"money": 0}

    result = execute_tool(db, world=world, actor=a, tool_name="attempt_burglary_private_room", params={"location_id": b_home.location_id})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "crime_home_burglary"
    assert event.target_agent_id == b.agent_id
    assert event.payload["destination_location_id"] == b_home.location_id


def test_return_home_moves_toward_own_private_room_and_sleep_works(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    home = Location(location_id=f"{world.world_id}:private_a", world_id=world.world_id, public_name="A的小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    db.add(home)
    db.flush()
    agent.wallet_json = {"money": 54, "housing": {"home_location_id": home.location_id}}
    agent.location.location_id = f"{world.world_id}:central_square"
    agent.location.location = db.get(Location, f"{world.world_id}:central_square")

    result = execute_tool(db, world=world, actor=agent, tool_name="return_home", params={})

    assert result.ok
    assert agent.location.location_id == home.location_id
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "return_home"
    sleep = execute_tool(db, world=world, actor=agent, tool_name="sleep", params={"sleep_hours": 8})
    assert sleep.ok
    assert agent.desires_json["sleep_until_world_time"] == world.current_world_time_minutes + 8 * 60


def test_return_home_walks_full_route_instead_of_stopping_at_square(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    home = Location(location_id=f"{world.world_id}:private_a", world_id=world.world_id, public_name="A的小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    db.add(home)
    db.flush()
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    agent.wallet_json = {"money": 54, "housing": {"home_location_id": home.location_id}}
    agent.location.location_id = cafeteria.location_id
    agent.location.location = cafeteria

    result = execute_tool(db, world=world, actor=agent, tool_name="return_home", params={})

    assert result.ok
    assert agent.location.location_id == home.location_id
    assert world.current_world_time_minutes == 30
    event = db.get(Event, result.event_ids[0])
    assert event.payload["path"] == [f"{world.world_id}:central_square", home.location_id]


def test_critical_survival_tools_and_danger_checks_do_not_loop_same_minute(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    agent.location.location_id = cafeteria.location_id
    agent.location.location = cafeteria
    agent.lifecycle_state = "critical"
    agent.dynamic_state.energy = 4
    agent.dynamic_state.hydration = 20
    agent.dynamic_state.critical_reason = "体力接近耗尽"

    first = apply_danger_checks(db, world, agent)
    second = apply_danger_checks(db, world, agent)
    drink = execute_tool(db, world=world, actor=agent, tool_name="drink_water", params={})

    assert first == []
    assert second == []
    assert drink.ok
    assert agent.dynamic_state.hydration > 50


def test_zero_energy_causes_unconscious_state_and_time_can_advance(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.dynamic_state.energy = 1
    agent.dynamic_state.health = 80

    events = apply_danger_checks(db, world, agent)

    assert events
    assert db.get(Event, events[0]).event_type == "unconscious"
    assert (agent.desires_json or {}).get("unconscious_until_world_time") == 8 * 60


def test_permission_grant_allows_private_room_entry(db):
    world, (owner, guest) = make_world(db, 2)
    owner_home = Location(location_id=f"{world.world_id}:private_owner", world_id=world.world_id, public_name="主人的小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    db.add(owner_home)
    db.flush()
    owner.wallet_json = {"money": 54, "housing": {"home_location_id": owner_home.location_id}}
    guest.wallet_json = {"money": 54}

    blocked = validate_tool(db, actor=guest, tool_name="move_to_location", params={"location_id": owner_home.location_id}, world_time=world.current_world_time_minutes)
    assert not blocked.ok
    assert blocked.reason_code == "private_room_blocked"

    _, refs = build_turn_context(db, world, owner)
    guest_ref = next(ref for ref, target_id in refs.items() if target_id == guest.agent_id)
    grant = execute_tool(db, world=world, actor=owner, tool_name="grant_personal_resource_permission_visible_agent", params={"visible_ref": guest_ref, "resource_scope": "home"})

    assert grant.ok
    allowed = validate_tool(db, actor=guest, tool_name="move_to_location", params={"location_id": owner_home.location_id}, world_time=world.current_world_time_minutes)
    assert allowed.ok
    move = execute_tool(db, world=world, actor=guest, tool_name="move_to_location", params={"location_id": owner_home.location_id})
    assert move.ok
    assert guest.location.location_id == owner_home.location_id


def test_market_history_is_recorded_for_stock_details(db):
    world, _ = make_world(db, 0)
    world.current_world_time_minutes = 0
    process_daily_economy_tick(db, world)
    world.current_world_time_minutes = 2 * 1440
    process_daily_economy_tick(db, world)

    market = world.settings_json["v6_market"]
    stock = market["stocks"]["MGL"]
    assert len(stock["history"]) >= 2
    assert "change_pct" in stock


@pytest.mark.anyio
async def test_bedtime_no_longer_forces_sleep_and_uses_llm_choice(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 1)
    turn_runner._round_robin_index.pop(world.world_id, None)
    world.current_world_time_minutes = 22 * 60
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:central_square"
    agent.dynamic_state.satiety = 90
    agent.dynamic_state.hydration = 90
    agent.dynamic_state.energy = 70
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    async def choose_look(*args, **kwargs):
        return LLMResult(_packet_from_prompt(kwargs["user_prompt"], "环顾四周"), None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", choose_look)
    turn = await turn_runner.run_one_step(db, world.world_id)

    assert turn.acted_agent_id == agent.agent_id
    assert agent.location.location_id == f"{world.world_id}:central_square"
    assert not (agent.desires_json or {}).get("sleep_until_world_time")
    event = db.get(Event, turn.event_ids[-1])
    assert event.event_type == "look"


@pytest.mark.anyio
async def test_night_can_choose_theft_instead_of_forcing_sleep(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 2)
    turn_runner._round_robin_index.pop(world.world_id, None)
    world.current_world_time_minutes = 22 * 60
    actor, target = agents
    actor.wallet_json = {"money": 0}
    actor.traits.aggression = 80
    actor.dynamic_state.satiety = 90
    actor.dynamic_state.hydration = 90
    actor.dynamic_state.energy = 70
    actor.dynamic_state.last_decay_world_time = world.current_world_time_minutes
    target.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    async def choose_theft(*args, **kwargs):
        return LLMResult(_packet_from_prompt(kwargs["user_prompt"], ("尝试小额偷窃", "什么也不做")), None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", choose_theft)
    turn = await turn_runner.run_one_step(db, world.world_id)

    assert turn.acted_agent_id == actor.agent_id
    assert not (actor.desires_json or {}).get("sleep_until_world_time")
    events = [db.get(Event, event_id) for event_id in turn.event_ids]
    assert any(event and event.event_type == "crime_petty_theft" and event.actor_agent_id == actor.agent_id for event in events)


@pytest.mark.anyio
async def test_night_low_hydration_survival_still_happens_without_forced_sleep(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)

    async def fail_complete_text(*args, **kwargs):
        raise AssertionError("low hydration should be handled before calling the LLM")

    monkeypatch.setattr(provider, "complete_text", fail_complete_text)
    world, agents = make_world(db, 1)
    turn_runner._round_robin_index.pop(world.world_id, None)
    world.current_world_time_minutes = 22 * 60
    agent = agents[0]
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    agent.location.location_id = cafeteria.location_id
    agent.location.location = cafeteria
    agent.dynamic_state.satiety = 90
    agent.dynamic_state.hydration = 30
    agent.dynamic_state.energy = 70
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    turn = await turn_runner.run_one_step(db, world.world_id)

    assert agent.dynamic_state.hydration > 45
    assert agent.location.location_id == f"{world.world_id}:cafeteria"
    assert not (agent.desires_json or {}).get("sleep_until_world_time")
    event = db.get(Event, turn.event_ids[-1])
    assert event.event_type == "drink"


def test_bedtime_prompt_warns_without_forcing_sleep(db):
    world, agents = make_world(db, 1)
    world.current_world_time_minutes = 22 * 60
    prompt, _ = build_turn_context(db, world, agents[0])
    assert "系统不会替你强制睡觉" in prompt
    assert "睡眠非常重要" in prompt
    assert "后端判定" in prompt and "犯罪" in prompt


def test_external_worldview_inherits_modern_sleep_routine_prompt(db):
    world, agents = make_world(db, 1)
    world.settings_json = {
        "worldview_id": "sample_external_worldview",
        "worldview_name": "外部测试世界观",
        "worldview_prompt_blocks": [
            {"title": "核心循环", "body": "探索地点，收集情绪资源。"},
        ],
    }
    world.current_world_time_minutes = 22 * 60

    prompt, _ = build_turn_context(db, world, agents[0])

    assert "基础作息继承默认现代世界观" in prompt
    assert "世界观剧情、探索、恋爱或战斗不会覆盖睡眠" in prompt
    assert "核心循环: 探索地点，收集情绪资源。" in prompt


def test_delete_world_rows_removes_save_and_dependents(db):
    world, agents = make_world(db, 1)
    event = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="测试事件。")
    db.add(Memory(agent_id=agents[0].agent_id, source_event_id=event.event_id, memory_type="event", content="测试记忆。"))
    db.add(NarratorRun(world_id=world.world_id, input_event_ids_json=[event.event_id], narration="测试解说。"))
    db.flush()

    deleted = _delete_world_rows(db, world.world_id)
    db.commit()

    assert deleted["worlds"] == 1
    assert db.get(World, world.world_id) is None
    assert db.get(Agent, agents[0].agent_id) is None
    assert db.execute(select(Event).where(Event.world_id == world.world_id)).first() is None
    assert db.execute(select(Location).where(Location.world_id == world.world_id)).first() is None
    assert db.execute(select(Memory).where(Memory.agent_id == agents[0].agent_id)).first() is None
    assert db.execute(select(NarratorRun).where(NarratorRun.world_id == world.world_id)).first() is None


@pytest.mark.anyio
async def test_collective_core_prompt_is_prepended_to_agent_llm(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 1)
    world.status = "running"
    world.settings_json = {"collective_core_prompt": "所有居民都要记住：先观察，再行动。"}
    captured: dict[str, str] = {}

    async def choose_action(*args, **kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return LLMResult(_packet_from_prompt(kwargs["user_prompt"], "什么也不做"), None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", choose_action)

    result = await turn_runner.run_one_step(db, world.world_id)

    assert result.status == "batch_ok"
    assert captured["system_prompt"].startswith("【集体核心提示词】\n所有居民都要记住：先观察，再行动。")


@pytest.mark.anyio
async def test_narrator_llm_failure_is_silent_and_does_not_pause_world(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", True)
    world, agents = make_world(db, 1)
    world.status = "running"
    world.settings_json = {
        "narrator_enabled": True,
        "narrator_config": {"provider_name": "bad", "base_url": "http://127.0.0.1:9/v1", "api_key": "bad", "model_name": "bad"},
    }
    event = create_event(db, world=world, event_type="daily", actor_agent_id=agents[0].agent_id, viewer_text="测试事件。", importance=70)

    async def narrator_timeout(*args, **kwargs):
        return LLMResult("", None, {}, 60_000, "test", "request timed out")

    monkeypatch.setattr(provider, "complete_text", narrator_timeout)

    narration_ids = await create_narration(db, world, [event.event_id], trigger_type="manual")

    assert narration_ids == []
    assert world.status == "running"
    assert db.execute(select(Event).where(Event.event_type == "narrator_failed")).first() is None
    assert db.execute(select(NarratorRun)).first() is None


@pytest.mark.anyio
async def test_repeated_agent_llm_failure_pauses_world(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 1)
    world.status = "running"
    agent = agents[0]
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes
    turn_runner._round_robin_index.pop(world.world_id, None)

    async def timeout_result(*args, **kwargs):
        return LLMResult("", None, {}, 60_000, "test", "request timed out")

    monkeypatch.setattr(provider, "complete_text", timeout_result)

    first = await turn_runner.run_one_step(db, world.world_id)
    second = await turn_runner.run_one_step(db, world.world_id)
    third = await turn_runner.run_one_step(db, world.world_id)

    assert first.status != "llm_stalled"
    assert second.status != "llm_stalled"
    assert third.status == "llm_stalled"
    assert world.status == "paused"
    assert agent.tool_learning_json["llm_consecutive_failures"] == 3
    event = db.get(Event, third.event_ids[0])
    assert event.event_type == "llm_stalled"
    assert "游戏已自动暂停" in event.viewer_text


def test_tool_failure_writes_event(db):
    world, agents = make_world(db, 2)
    a, b = agents
    result = execute_tool(db, world=world, actor=a, tool_name="promise_to_named_agent", params={"known_name": b.chosen_name})
    assert not result.ok
    event = db.execute(select(Event).where(Event.event_type == "tool_failed")).scalar_one()
    assert event.no_state_changed
    assert "还不知道" in event.viewer_text


@pytest.mark.anyio
async def test_configured_identity_skips_llm_generation(db, monkeypatch):
    world, _ = make_world(db, 0)

    async def fail_complete_text(*args, **kwargs):
        raise AssertionError("configured identity should not call identity LLM")

    monkeypatch.setattr(provider, "complete_text", fail_complete_text)
    agent = await create_agent_with_identity(
        db,
        world,
        index=0,
        model_alias="world_agent",
        initial_location_id=f"{world.world_id}:central_square",
        custom_system_prompt="你正在扮演测试角色。说话习惯: 简短、冷静、直接。",
        preset_name="测试灯",
        preset_appearance="灰色短发，粉色眼瞳，穿宽大的蓝白色卫衣，气质安静而谨慎。",
        trait_mode="agent",
        trait_budget=500,
        user_trait_sliders={"openness": 80, "caution": 20, "sociability": 30},
    )

    assert agent.chosen_name == "测试灯"
    assert agent.appearance_full == "灰色短发，粉色眼瞳，穿宽大的蓝白色卫衣，气质安静而谨慎。"
    assert agent.custom_system_prompt == "你正在扮演测试角色。说话习惯: 简短、冷静、直接。"
    assert agent.avatar_hint_json["identity_source"] == "user_config"


@pytest.mark.anyio
async def test_birth_uses_baby_model_pool_and_generated_identity(db, monkeypatch):
    world, agents = make_world(db, 2)
    world.settings_json = {
        "enabled_optional_toolset_ids": ["reproduction_lifecycle_toolset"],
        "reproduction_enabled": True,
        "trait_budget": 500,
        "baby_model_pool": [
            {
                "provider_id": "baby",
                "provider_name": "宝宝池",
                "base_url": "https://example.test/v1",
                "api_key": "test",
                "model_name": "example-pro-model",
            }
        ],
    }
    parent, co_parent = agents
    parent.family_json = {
        "pregnancy_state": {
            "pregnant": True,
            "co_parent_agent_id": co_parent.agent_id,
            "due_world_time": 0,
        },
        "children_agent_ids": [],
    }

    calls = {"n": 0}

    async def fake_complete_text(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResult("NAME=小澄", None, {}, 1, "test")
        return LLMResult(
            "\n".join(
                [
                    "NAME=小澄",
                    "GENDER=不愿公开",
                    "GENDER_PUBLIC=0",
                    "GENDER_EXPR=安静的新生儿",
                    "LOOK_SHORT=安静柔软的小新生儿",
                    "LOOK_FULL=小澄是刚出生的小婴儿，眼睛还没有完全适应光，只会靠哭声和细小动作表达需要。",
                    "AVATAR_COLOR=#88aacc",
                    "AVATAR_TAGS=newborn",
                    "SPEAK=现在不会说话，未来会先学简单词。",
                    "SEED=对声音和拥抱有最早的反应，未来可能形成安静敏感的性格。",
                    "GOAL=被照顾并活下去。",
                    "INTRO=secretive",
                    "TRAITS=openness:50,caution:50,sociability:50,empathy:50,curiosity:50,discipline:50,aggression:20,honesty:50,creativity:50,neuroticism:50",
                ]
            ),
            None,
            {},
            1,
            "test",
        )

    monkeypatch.setattr(provider, "complete_text", fake_complete_text)
    event_ids = await process_world_life_events(db, world, parent)

    assert event_ids
    child = db.execute(select(Agent).where(Agent.chosen_name == "小澄")).scalar_one()
    assert child.model_provider_name == "宝宝池"
    assert child.model_name == "example-pro-model"
    assert child.tool_learning_json["llm_enabled"] is False
    assert child.tool_learning_json["growth_locked"] is False
    assert child.appearance_short == "安静柔软的小新生儿"


@pytest.mark.anyio
async def test_birth_locks_baby_when_all_candidate_models_are_full(db, monkeypatch):
    world, agents = make_world(db, 1)
    world.settings_json = {
        "enabled_optional_toolset_ids": ["reproduction_lifecycle_toolset"],
        "reproduction_enabled": True,
        "trait_budget": 500,
        "baby_model_pool": [
            {
                "provider_id": "baby",
                "provider_name": "宝宝池",
                "base_url": "https://example.test/v1",
                "api_key": "test",
                "model_name": "example-model",
            }
        ],
    }
    parent = agents[0]
    parent.family_json = {
        "pregnancy_state": {
            "pregnant": True,
            "co_parent_agent_id": None,
            "due_world_time": 0,
        },
        "children_agent_ids": [],
    }

    monkeypatch.setattr(provider, "model_has_capacity_now", lambda **kwargs: False)

    async def fail_complete_text(*args, **kwargs):
        raise AssertionError("capacity-exhausted birth should not call LLM")

    monkeypatch.setattr(provider, "complete_text", fail_complete_text)
    await process_world_life_events(db, world, parent)

    child = db.execute(select(Agent).where(Agent.agent_id != parent.agent_id, Agent.world_id == world.world_id)).scalar_one()
    assert child.model_name is None
    assert child.tool_learning_json["growth_locked"] is True
    assert child.tool_learning_json["llm_enabled"] is False
    world.current_world_time_minutes = 31 * 1440
    await process_world_life_events(db, world, child)
    assert child.age_stage == "newborn"


@pytest.mark.anyio
async def test_child_growth_refreshes_baby_appearance_terms(db):
    world, agents = make_world(db, 1)
    child = agents[0]
    child.age_stage = "newborn"
    child.created_at_world_time = 0
    child.appearance_short = "银发女婴"
    child.appearance_full = "这个女婴刚出生不久，脸颊很软，看起来还是小宝宝。"
    child.tool_learning_json = {"growth_locked": False, "llm_enabled": False, "learned": []}
    world.current_world_time_minutes = 31 * 1440

    event_ids = await process_world_life_events(db, world, child)

    assert event_ids
    assert child.age_stage == "adult"
    combined = f"{child.appearance_short}\n{child.appearance_full}"
    assert "女婴" not in combined
    assert "小宝宝" not in combined
    assert "成人" in combined


@pytest.mark.anyio
async def test_sleep_intent_is_aligned_to_real_sleep_tool_without_forcing_other_choices(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 1)
    turn_runner._round_robin_index.pop(world.world_id, None)
    world.current_world_time_minutes = 22 * 60
    agent = agents[0]
    agent.dynamic_state.satiety = 90
    agent.dynamic_state.hydration = 90
    agent.dynamic_state.energy = 70
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    async def choose_sleepy_speech(*args, **kwargs):
        return LLMResult(
            _packet_from_prompt(kwargs["user_prompt"], "公开说话", text="我困得不行，想回家睡觉。"),
            None,
            {},
            1,
            "test",
        )

    monkeypatch.setattr(provider, "complete_text", choose_sleepy_speech)
    turn = await turn_runner.run_one_step(db, world.world_id)

    assert turn.acted_agent_id == agent.agent_id
    assert (agent.desires_json or {}).get("sleep_until_world_time")
    assert agent.location.location_id == ((agent.wallet_json or {}).get("housing") or {}).get("home_location_id")
    assert any(db.get(Event, event_id).event_type == "sleep_start" for event_id in turn.event_ids)


def test_sleep_rough_is_real_scheduled_sleep_and_resets_awake(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.desires_json = {"awake_since_world_time": 0}
    agent.dynamic_state.energy = 20
    agent.dynamic_state.last_decay_world_time = 0

    result = execute_tool(db, world=world, actor=agent, tool_name="sleep_rough", params={"sleep_hours": 4})

    assert result.ok
    assert agent.desires_json["sleep_quality"] == "rough"
    assert agent.desires_json["sleep_until_world_time"] == 4 * 60
    world.current_world_time_minutes = 4 * 60
    event_ids = complete_scheduled_sleep(db, world, agent)

    assert agent.desires_json["awake_since_world_time"] == 4 * 60
    assert not agent.desires_json.get("sleep_until_world_time")
    assert db.get(Event, event_ids[0]).payload["sleep_quality"] == "rough"
    assert any(db.get(Event, event_id).event_type == "dream_summary" for event_id in event_ids)


def test_sleep_activity_status_shows_current_sleep_window(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    world.current_world_time_minutes = 8 * 60
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes
    agent.location.location_id = f"{world.world_id}:cabin"

    result = execute_tool(db, world=world, actor=agent, tool_name="sleep", params={"sleep_hours": 7})

    assert result.ok
    item = agent_list_item(db, agent)
    status = item["activity_status"]
    assert status["is_sleeping"] is True
    assert status["sleep_started_label"] == "第1天 08:00"
    assert status["sleep_until_label"] == "第1天 15:00"
    assert "第1天 08:00 入睡" in status["label"]
    assert "第1天 15:00 醒来" in status["label"]


def test_sleep_activity_status_ignores_stale_schedule_after_wake_event(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    world.current_world_time_minutes = 100
    agent.desires_json = {
        "sleep_started_world_time": 100,
        "sleep_until_world_time": 1000,
        "sleep_planned_minutes": 900,
    }
    create_event(db, world=world, event_type="sleep_start", actor_agent_id=agent.agent_id, viewer_text="测试入睡")
    world.current_world_time_minutes = 500
    create_event(db, world=world, event_type="wake", actor_agent_id=agent.agent_id, viewer_text="测试醒来")
    world.current_world_time_minutes = 600

    item = agent_list_item(db, agent)

    assert item["activity_status"] == {"state": "awake", "label": "清醒", "is_sleeping": False}


def test_return_home_can_chain_sleep_after_arrival(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    home = Location(location_id=f"{world.world_id}:private_chain", world_id=world.world_id, public_name="链式睡眠小屋", description="私人小屋。", neighbors_json=[f"{world.world_id}:central_square"], available_tools_json=["sleep"], tags_json=["home", "private", "water"])
    db.add(home)
    db.flush()
    agent.wallet_json = {"money": 54, "housing": {"home_location_id": home.location_id}}
    agent.location.location_id = f"{world.world_id}:central_square"
    agent.location.location = db.get(Location, f"{world.world_id}:central_square")

    result = execute_tool(db, world=world, actor=agent, tool_name="return_home", params={"sleep_after_arrival": True, "sleep_hours": 8})

    assert result.ok
    assert agent.location.location_id == home.location_id
    assert agent.desires_json["sleep_until_world_time"] == world.current_world_time_minutes + 8 * 60
    assert any(db.get(Event, event_id).event_type == "sleep_start" for event_id in result.event_ids)


def test_governance_proposal_records_public_rule_without_forcing_law(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:central_square"
    agent.location.location = db.get(Location, f"{world.world_id}:central_square")

    result = execute_tool(db, world=world, actor=agent, tool_name="propose_social_rule", params={"content": "建议制定临时宪法：夜间守望、互助食物、犯罪公开记录。"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "governance_proposal"
    assert "不会自动变成强制规则" in event.payload["note"]
    proposals = world.settings_json["governance"]["proposals"]
    assert proposals[-1]["status"] == "proposed"
    assert "临时宪法" in proposals[-1]["content"]


def test_dream_summary_archives_low_importance_short_memory_but_keeps_trauma(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    from app.memory.memory_service import add_memory, create_sleep_dream_summary

    for index in range(12):
        add_memory(db, agent_id=agent.agent_id, content=f"普通散步记忆 {index}", world_time=index, importance=20)
    trauma = add_memory(db, agent_id=agent.agent_id, content="我被偷了钱，这件事造成了创伤。", world_time=99, importance=80)

    summary = create_sleep_dream_summary(db, agent=agent, world_time=120)

    assert "醒来后仍清楚的事" in summary.content
    assert "被偷" in summary.content
    db.flush()
    refreshed_trauma = db.get(Memory, trauma.memory_id)
    assert refreshed_trauma.archived is False
    archived_count = db.execute(select(Memory).where(Memory.agent_id == agent.agent_id, Memory.archived.is_(True))).all()
    assert archived_count


def test_death_creates_visible_persistent_corpse_with_grief_prompt(db):
    world, (observer, dying) = make_world(db, 2)
    adjust_relationship(db, observer.agent_id, dying.agent_id, world_time=0, familiarity=80, trust=85, affection=90)
    dying.dynamic_state.health = 0
    dying.dynamic_state.critical_reason = "测试死亡"

    event_ids = apply_danger_checks(db, world, dying)

    assert event_ids
    assert dying.lifecycle_state == "dead"
    death_event = db.get(Event, event_ids[-1])
    assert death_event.payload["corpse_persistent"] is True
    prompt, _ = build_turn_context(db, world, observer)
    assert "【附近可见尸体】" in prompt
    assert "尸体A" in prompt
    assert "分明曾经" in prompt or "明显冲击" in prompt


def test_corpse_exposure_and_burial_are_local_negative_rules(db):
    world, (observer, dying) = make_world(db, 2)
    dying.dynamic_state.health = 0
    dying.dynamic_state.critical_reason = "测试死亡"
    apply_danger_checks(db, world, dying)

    settings = dict(world.settings_json or {})
    records = list(settings["corpse_records"])
    records[0] = {**records[0], "death_world_time": world.current_world_time_minutes - 3 * 1440}
    settings["corpse_records"] = records
    world.settings_json = settings

    observer.dynamic_state.stress = 10
    observer.dynamic_state.hygiene = 70
    exposure_ids = apply_corpse_exposure(db, world, observer)
    assert exposure_ids
    assert any(db.get(Event, event_id).event_type in {"corpse_seen", "corpse_exposure"} for event_id in exposure_ids)
    assert observer.dynamic_state.stress > 10
    assert observer.dynamic_state.hygiene < 70

    before_energy = observer.dynamic_state.energy
    before_hygiene = observer.dynamic_state.hygiene
    result = execute_tool(db, world=world, actor=observer, tool_name="bury_visible_corpse", params={"corpse_ref": "尸体A"})

    assert result.ok
    burial_event = db.get(Event, result.event_ids[0])
    assert burial_event.event_type == "corpse_buried"
    assert burial_event.payload["negative_only"] is True
    assert observer.dynamic_state.energy < before_energy
    assert observer.dynamic_state.hygiene < before_hygiene
    prompt, _ = build_turn_context(db, world, observer)
    assert "当前地点没有可见尸体" in prompt


def test_body_drive_prompt_and_reward_record_make_cleaning_understandable(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:cabin"
    agent.location.location = db.get(Location, f"{world.world_id}:cabin")
    agent.dynamic_state.hygiene = 8
    agent.dynamic_state.stress = 20

    prompt, _ = build_turn_context(db, world, agent)
    assert "【内在奖惩/痛苦感知】" in prompt
    assert "清洁痛苦" in prompt or "清洁感变差" in prompt
    assert "wash" in prompt or "clean_clothes" in prompt

    before_pain = agent.desires_json["embodied_drive"]["pain_score"]
    result = execute_tool(db, world=world, actor=agent, tool_name="wash", params={})

    assert result.ok
    reward = agent.desires_json["last_action_reward"]
    assert reward["tool_name"] == "wash"
    assert reward["after_pain"] <= before_pain
    assert reward["valence"] >= 0


def test_agent_special_toolsets_gate_special_tools(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    work_location = db.get(Location, f"{world.world_id}:workshop")
    agent.location.location_id = work_location.location_id
    agent.location.location = work_location
    agent.tool_learning_json = {**(agent.tool_learning_json or {}), "agent_toolset_ids": []}

    blocked = validate_tool(db, actor=agent, tool_name="work_overtime_shift", params={}, world_time=world.current_world_time_minutes)
    assert not blocked.ok
    assert blocked.reason_code == "agent_toolset_disabled"

    agent.tool_learning_json = {**(agent.tool_learning_json or {}), "agent_toolset_ids": ["agent_work_toolset"]}
    allowed = validate_tool(db, actor=agent, tool_name="work_overtime_shift", params={}, world_time=world.current_world_time_minutes)
    assert allowed.reason_code != "agent_toolset_disabled"


def test_tool_context_mode_places_fixed_or_dynamic_prefix(db):
    world, agents = make_world(db, 1)
    agent = agents[0]

    agent.tool_learning_json = {**(agent.tool_learning_json or {}), "tool_context_mode": "dynamic"}
    dynamic_prompt, _ = build_turn_context(db, world, agent)
    assert dynamic_prompt.startswith("【动态工具缓存前缀】")
    assert "【行动编号协议 AOHP】" in dynamic_prompt
    assert "行动选项:" in dynamic_prompt

    agent.tool_learning_json = {**(agent.tool_learning_json or {}), "tool_context_mode": "all"}
    fixed_prompt, _ = build_turn_context(db, world, agent)
    assert fixed_prompt.startswith("【固定工具集】")
    assert "【行动编号协议 AOHP】" in fixed_prompt
    assert "可用工具: 见顶部【固定工具集】。" in fixed_prompt


def _ref_for(refs: dict[str, str], agent_id: str) -> str:
    return next(ref for ref, target_id in refs.items() if target_id == agent_id)


def test_speech_known_name_retargets_wrong_visible_ref_and_keeps_bystander_out(db):
    from app.world.visibility import mark_name_known

    world, (a, b, c) = make_world(db, 3)
    mark_name_known(db, a.agent_id, b, world.current_world_time_minutes, "test")
    _prompt, refs = build_turn_context(db, world, a)
    ref_c = _ref_for(refs, c.agent_id)

    result = execute_tool(db, world=world, actor=a, tool_name="say_to_visible_agent", params={"visible_ref": ref_c, "speech": f"{b.chosen_name}，我其实是在叫你，不是在叫旁边的人。"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.target_agent_id == b.agent_id
    assert event.payload["retargeted_by_speech"]["to_agent_id"] == b.agent_id
    assert b.agent_id in result.reaction_agent_ids
    assert c.agent_id not in result.reaction_agent_ids


def test_unknown_leaked_name_does_not_retarget_or_grant_omniscience(db):
    world, (a, b, c) = make_world(db, 3)
    _prompt, refs = build_turn_context(db, world, a)
    ref_c = _ref_for(refs, c.agent_id)

    result = execute_tool(db, world=world, actor=a, tool_name="say_to_visible_agent", params={"visible_ref": ref_c, "speech": f"{b.chosen_name}，我是在叫你。"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.target_agent_id == c.agent_id
    assert b.chosen_name not in event.payload["speech"]
    assert c.agent_id in result.reaction_agent_ids
    assert b.agent_id not in result.reaction_agent_ids


def test_group_speech_addresses_every_listener_but_direct_comfort_addresses_only_target(db):
    world, (a, b, c) = make_world(db, 3)

    group = execute_tool(db, world=world, actor=a, tool_name="speak_to_nearby", params={"speech": "大家，谁能帮我看一下现在该怎么办？"})
    assert group.ok
    assert set(group.reaction_agent_ids) == {b.agent_id, c.agent_id}

    _prompt, refs = build_turn_context(db, world, a)
    ref_b = _ref_for(refs, b.agent_id)
    direct = execute_tool(db, world=world, actor=a, tool_name="comfort_visible_agent", params={"visible_ref": ref_b, "speech": "我在旁边陪你缓一缓。"})
    assert direct.ok
    assert b.agent_id in direct.reaction_agent_ids
    assert c.agent_id not in direct.reaction_agent_ids


def test_request_speech_known_name_retargets_pending_request_to_real_target(db):
    from app.world.visibility import mark_name_known

    world, (a, b, c) = make_world(db, 3)
    mark_name_known(db, a.agent_id, b, world.current_world_time_minutes, "test")
    _prompt, refs = build_turn_context(db, world, a)
    ref_c = _ref_for(refs, c.agent_id)

    result = execute_tool(db, world=world, actor=a, tool_name="hug_visible_agent", params={"visible_ref": ref_c, "speech": f"{b.chosen_name}，我想抱你一下，可以吗？"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.target_agent_id == b.agent_id
    assert any(req.get("from_agent_id") == a.agent_id and req.get("request_type") == "hug" for req in (b.family_json or {}).get("pending_social_requests", []))
    assert not (c.family_json or {}).get("pending_social_requests")


def test_simultaneous_requests_to_same_agent_are_separate_menu_options(db):
    from app.knowledge.perception import build_turn_context_with_options

    world, (a, b, c) = make_world(db, 3)
    _prompt, refs_a = build_turn_context(db, world, a)
    _prompt, refs_b = build_turn_context(db, world, b)
    execute_tool(db, world=world, actor=a, tool_name="hug_visible_agent", params={"visible_ref": _ref_for(refs_a, c.agent_id), "speech": "可以抱一下吗？"})
    execute_tool(db, world=world, actor=b, tool_name="hug_visible_agent", params={"visible_ref": _ref_for(refs_b, c.agent_id), "speech": "我也想抱你一下。"})
    pending = (c.family_json or {}).get("pending_social_requests", [])
    assert len([req for req in pending if req.get("status") == "pending"]) == 2

    context = build_turn_context_with_options(db, world, c, reaction=True)
    assert "同时收到了多个请求" in context.prompt
    accept_options = [option for option in context.action_options if option.tool_name == "accept_social_request_visible_agent"]
    request_ids = {option.params.get("request_id") for option in accept_options}
    assert {req.get("request_id") for req in pending} <= request_ids

    b_req = next(req for req in pending if req.get("from_agent_id") == b.agent_id)
    ref_b = _ref_for(context.ref_map, b.agent_id)
    accepted = execute_tool(db, world=world, actor=c, tool_name="accept_social_request_visible_agent", params={"visible_ref": ref_b, "request_id": b_req["request_id"], "request_type": "hug", "speech": "我先回应你。"})

    assert accepted.ok
    event = db.get(Event, accepted.event_ids[0])
    assert event.event_type == "hug_accepted"
    assert event.payload["request_id"] == b_req["request_id"]
    still_pending = [req for req in (c.family_json or {}).get("pending_social_requests", []) if req.get("status") == "pending"]
    assert len(still_pending) == 1
    assert still_pending[0].get("from_agent_id") == a.agent_id


def test_simultaneous_forced_actions_are_separate_response_options(db, monkeypatch):
    from app.knowledge.perception import build_turn_context_with_options
    from app.social import forced_actions

    monkeypatch.setattr(forced_actions, "_notice_chance", lambda *args, **kwargs: 1.0)
    world, (a, b, c) = make_world(db, 3)
    _prompt, refs_a = build_turn_context(db, world, a)
    _prompt, refs_b = build_turn_context(db, world, b)
    execute_tool(db, world=world, actor=a, tool_name="force_hug_visible_agent", params={"visible_ref": _ref_for(refs_a, c.agent_id), "speech": "我想直接抱一下。"})
    execute_tool(db, world=world, actor=b, tool_name="force_hold_hands_visible_agent", params={"visible_ref": _ref_for(refs_b, c.agent_id), "speech": "我想直接牵住你。"})
    pending = (c.family_json or {}).get("pending_forced_social_actions", [])
    assert len([req for req in pending if req.get("status") == "pending_notice"]) == 2

    context = build_turn_context_with_options(db, world, c, reaction=True)
    assert "同时注意到多个突然动作" in context.prompt
    dodge_options = [option for option in context.action_options if option.tool_name == "dodge_forced_action_visible_agent"]
    forced_ids = {option.params.get("forced_action_id") for option in dodge_options}
    assert {req.get("forced_action_id") for req in pending} <= forced_ids

    b_req = next(req for req in pending if req.get("from_agent_id") == b.agent_id)
    ref_b = _ref_for(context.ref_map, b.agent_id)
    dodged = execute_tool(db, world=world, actor=c, tool_name="dodge_forced_action_visible_agent", params={"visible_ref": ref_b, "forced_action_id": b_req["forced_action_id"], "action_type": b_req["action_type"]})
    assert dodged.ok
    event = db.get(Event, dodged.event_ids[0])
    assert event.payload["action_type"] == "hold_hands"
    remaining = [req for req in (c.family_json or {}).get("pending_forced_social_actions", []) if req.get("status") == "pending_notice"]
    assert len(remaining) == 1
    assert remaining[0].get("from_agent_id") == a.agent_id


def test_trait_metadata_growth_and_priority_are_active(db):
    from app.agents.traits import TRAIT_METADATA, trait_growth_reference_lines, trait_priority_bias

    assert TRAIT_METADATA["discipline"]["label"] == "自律"
    assert any("共情" in line and "照护" in line for line in trait_growth_reference_lines())
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.location.location_id = f"{world.world_id}:cabin"
    agent.location.location = db.get(Location, f"{world.world_id}:cabin")
    before = agent.traits.discipline
    result = execute_tool(db, world=world, actor=agent, tool_name="wash", params={})
    assert result.ok
    assert agent.traits.discipline == min(100, before + 1)
    event = db.get(Event, result.event_ids[0])
    assert "trait_growth" in (event.payload or {})
    agent.traits.discipline = 90
    agent.traits.caution = 90
    agent.traits.aggression = 10
    assert trait_priority_bias(agent.traits, "wash") < 0
    assert trait_priority_bias(agent.traits, "attack_visible_agent") > 0


def test_response_tool_retargets_request_id_when_speech_names_other_requester(db):
    from app.world.visibility import mark_name_known

    world, (a, b, c) = make_world(db, 3)
    mark_name_known(db, c.agent_id, a, world.current_world_time_minutes, "test")
    mark_name_known(db, c.agent_id, b, world.current_world_time_minutes, "test")
    _prompt, refs_a = build_turn_context(db, world, a)
    _prompt, refs_b = build_turn_context(db, world, b)
    execute_tool(db, world=world, actor=a, tool_name="hug_visible_agent", params={"visible_ref": _ref_for(refs_a, c.agent_id), "speech": "可以抱一下吗？"})
    execute_tool(db, world=world, actor=b, tool_name="hug_visible_agent", params={"visible_ref": _ref_for(refs_b, c.agent_id), "speech": "我也想抱你一下。"})
    pending = [req for req in (c.family_json or {}).get("pending_social_requests", []) if req.get("status") == "pending"]
    a_req = next(req for req in pending if req.get("from_agent_id") == a.agent_id)
    b_req = next(req for req in pending if req.get("from_agent_id") == b.agent_id)

    _prompt, refs_c = build_turn_context(db, world, c, reaction=True)
    # 故意把 visible_ref/request_id 绑到 B，但正文明确叫 A；后端应修正为 A 的请求，而不是错误接受 B。
    result = execute_tool(db, world=world, actor=c, tool_name="accept_social_request_visible_agent", params={"visible_ref": _ref_for(refs_c, b.agent_id), "request_id": b_req["request_id"], "request_type": "hug", "speech": f"{a.chosen_name}，我先回应你。"})
    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.payload["request_id"] == a_req["request_id"]
    remaining = [req for req in (c.family_json or {}).get("pending_social_requests", []) if req.get("status") == "pending"]
    assert len(remaining) == 1 and remaining[0].get("request_id") == b_req["request_id"]


def test_event_lists_are_chronological_even_when_event_ids_are_not(db):
    from app.api.worlds import list_events
    from app.events.event_store import events_after, latest_events

    world, agents = make_world(db, 1)
    world.current_world_time_minutes = 12 * 60 + 4
    later_by_time = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="12:04 的事件先被写入。")
    world.current_world_time_minutes = 12 * 60 + 1
    earlier_by_time = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="12:01 的事件后被写入。")
    world.current_world_time_minutes = 12 * 60 + 6
    latest_by_time = create_event(db, world=world, event_type="note", actor_agent_id=agents[0].agent_id, viewer_text="12:06 的事件。")

    assert later_by_time.event_id < earlier_by_time.event_id < latest_by_time.event_id
    assert [event.event_id for event in latest_events(db, world.world_id, limit=10)][-3:] == [earlier_by_time.event_id, later_by_time.event_id, latest_by_time.event_id]
    assert [event.event_id for event in events_after(db, world.world_id, later_by_time.event_id, limit=10)] == [earlier_by_time.event_id, latest_by_time.event_id]
    payload = list_events(world.world_id, limit=10, latest=True, db=db)
    ordered_ids = [item["event_id"] for item in payload["events"]]
    assert ordered_ids[-3:] == [earlier_by_time.event_id, later_by_time.event_id, latest_by_time.event_id]


def test_direct_help_and_comfort_do_not_drag_bystanders_into_interaction(db):
    world, (a, b, c) = make_world(db, 3)
    _prompt, refs = build_turn_context(db, world, a)
    ref_b = _ref_for(refs, b.agent_id)

    help_result = execute_tool(db, world=world, actor=a, tool_name="help_visible_agent", params={"visible_ref": ref_b})
    assert help_result.ok
    assert help_result.reaction_agent_ids == [b.agent_id]
    help_event = db.get(Event, help_result.event_ids[0])
    assert help_event.event_type == "help"
    assert "强行" not in help_event.viewer_text
    assert c.agent_id not in help_result.reaction_agent_ids

    comfort_result = execute_tool(db, world=world, actor=a, tool_name="comfort_visible_agent", params={"visible_ref": ref_b, "speech": "我就在旁边，先陪你缓一缓。"})
    assert comfort_result.ok
    assert b.agent_id in comfort_result.reaction_agent_ids
    assert c.agent_id not in comfort_result.reaction_agent_ids
    comfort_event = db.get(Event, comfort_result.event_ids[0])
    assert "未经同意" not in comfort_event.viewer_text
    assert "强行" not in comfort_event.viewer_text


def test_environment_help_is_scene_action_not_random_person_violation(db):
    world, (a, b, c) = make_world(db, 3)
    _prompt, refs = build_turn_context(db, world, a)
    ref_b = _ref_for(refs, b.agent_id)

    result = execute_tool(db, world=world, actor=a, tool_name="force_help_visible_agent", params={"visible_ref": ref_b, "speech": "我帮路边的小猫喂点水，再把水碗放稳。"})

    assert result.ok
    assert result.reaction_agent_ids == []
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "situational_help"
    assert event.target_agent_id is None
    assert event.payload["addressed_agent_ids"] == []
    assert b.agent_id not in result.reaction_agent_ids
    assert c.agent_id not in result.reaction_agent_ids


def test_public_speech_naming_one_person_only_addresses_that_person(db):
    from app.world.visibility import mark_name_known

    world, (a, b, c) = make_world(db, 3)
    mark_name_known(db, a.agent_id, b, world.current_world_time_minutes, "test")
    mark_name_known(db, a.agent_id, c, world.current_world_time_minutes, "test")

    result = execute_tool(db, world=world, actor=a, tool_name="speak_to_nearby", params={"speech": f"{b.chosen_name}，我刚才那句话是专门对你说的。", "tone": "neutral"})

    assert result.ok
    assert result.reaction_agent_ids == [b.agent_id]
    event = db.get(Event, result.event_ids[0])
    assert set(event.payload["heard_by_agent_ids"]) == {b.agent_id, c.agent_id}
    assert event.payload["addressed_agent_ids"] == [b.agent_id]


def test_formal_work_shift_requires_role_time_window_and_continuous_duration(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    agent.location.location_id = cafeteria.location_id
    agent.location.location = cafeteria
    agent.work_json = {"job": "食堂服务员", "job_role": "cafeteria_service", "employed": True, "fatigue": 0}
    world.current_world_time_minutes = 11 * 60
    agent.dynamic_state.energy = 90
    agent.dynamic_state.satiety = 90
    agent.dynamic_state.hydration = 90
    agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes

    result = execute_tool(db, world=world, actor=agent, tool_name="work_shift_cafeteria", params={})

    assert result.ok
    assert world.current_world_time_minutes == 14 * 60
    event = db.get(Event, result.event_ids[0])
    assert event.payload["scheduled_duration_minutes"] >= 180
    assert "午餐服务班" in event.viewer_text

    world.current_world_time_minutes = 23 * 60
    blocked = validate_tool(db, actor=agent, tool_name="work_shift_cafeteria", params={}, world_time=world.current_world_time_minutes)
    assert not blocked.ok
    assert "可上班时段" in (blocked.message or "") or "下一段班" in (blocked.message or "")


def test_night_job_only_appears_at_night_for_matching_role(db):
    world, agents = make_world(db, 1)
    agent = agents[0]
    workshop = db.get(Location, f"{world.world_id}:workshop")
    agent.location.location_id = workshop.location_id
    agent.location.location = workshop
    agent.work_json = {"job": "夜间安保", "job_role": "night_guard", "employed": True, "fatigue": 0}
    agent.dynamic_state.energy = 90
    agent.dynamic_state.satiety = 90
    agent.dynamic_state.hydration = 90

    world.current_world_time_minutes = 12 * 60
    day_blocked = validate_tool(db, actor=agent, tool_name="work_shift_night_guard", params={}, world_time=world.current_world_time_minutes)
    assert not day_blocked.ok

    world.current_world_time_minutes = 21 * 60
    night_allowed = validate_tool(db, actor=agent, tool_name="work_shift_night_guard", params={}, world_time=world.current_world_time_minutes)
    assert night_allowed.ok


def test_adult_intimacy_intent_in_speech_aligns_to_request_tool(db):
    from app.simulation.turn_runner import _align_adult_intimacy_intent_to_tool
    from app.llm.schemas import ActionChoice

    world, (a, b) = make_world(db, 2)
    _prompt, refs = build_turn_context(db, world, a)
    ref_b = _ref_for(refs, b.agent_id)
    allowed = {tool.tool_name for tool in available_tools(a, a.location.location, session=db)}
    action = ActionChoice(tool_name="say_to_visible_agent", params={"visible_ref": ref_b, "speech": "今晚我想和你更亲密地一起过夜，可以吗？"}, plan_summary="台词已经进入成年亲密语义")

    aligned = _align_adult_intimacy_intent_to_tool(db, world, a, action, allowed=allowed, reaction=False)

    assert aligned.tool_name == "request_adult_intimacy_visible_agent"
    result = execute_tool(db, world=world, actor=a, tool_name=aligned.tool_name, params=aligned.params)
    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "adult_intimacy_request"


def test_adult_intimacy_updates_mutual_gender_knowledge_even_when_not_public(db):
    from app.world.visibility import get_or_create_knowledge

    world, (a, b) = make_world(db, 2)
    a.gender_identity = "男性"
    b.gender_identity = "女性"
    a.gender_publicity = False
    b.gender_publicity = False
    adjust_relationship(db, b.agent_id, a.agent_id, world_time=world.current_world_time_minutes, familiarity=80, trust=80, affection=80)
    adjust_relationship(db, a.agent_id, b.agent_id, world_time=world.current_world_time_minutes, familiarity=80, trust=80, affection=80)
    _prompt_a, refs_a = build_turn_context(db, world, a)
    result_request = execute_tool(db, world=world, actor=a, tool_name="request_adult_intimacy_visible_agent", params={"visible_ref": _ref_for(refs_a, b.agent_id), "speech": "我想和你抽象地进入更亲密相处。"})
    assert result_request.ok
    _prompt_b, refs_b = build_turn_context(db, world, b, reaction=True)
    result_accept = execute_tool(db, world=world, actor=b, tool_name="accept_adult_intimacy_visible_agent", params={"visible_ref": _ref_for(refs_b, a.agent_id), "speech": "我愿意。"})

    assert result_accept.ok
    event = db.get(Event, result_accept.event_ids[0])
    assert event.event_type == "adult_intimacy"
    assert get_or_create_knowledge(db, a.agent_id, b.agent_id).gender_known
    assert get_or_create_knowledge(db, b.agent_id, a.agent_id).gender_known
