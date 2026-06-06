from __future__ import annotations

from sqlalchemy import select

from app.api.serializers import location_to_dict
from app.core.models import Event, Location
from app.effects.effect_engine import execute_tool
from app.economy.v6 import ensure_v6_agent_state
from app.knowledge.perception import build_turn_context
from app.llm.action_options import build_action_options
from app.llm.action_protocol import format_action_options_for_prompt, packet_to_action_choice, parse_action_packet
from app.tools.registry import available_tools, get_tool
from conftest import make_world


def _visible_ref_for(refs: dict[str, str], agent_id: str) -> str:
    for ref, target_id in refs.items():
        if target_id == agent_id:
            return ref
    raise AssertionError(f"未找到可见目标 {agent_id}: {refs}")


def test_locations_api_payload_lists_current_occupants(db):
    world, agents = make_world(db, 2)
    loc = db.get(Location, f"{world.world_id}:central_square")

    payload = location_to_dict(loc, db)

    names = {row["display_name"] for row in payload["occupants"]}
    assert names == {agents[0].chosen_name, agents[1].chosen_name}
    assert payload["occupant_count"] == 2
    assert all(row["activity_label"] in {"在场", "昏迷"} for row in payload["occupants"])


def test_visible_ref_tools_are_compacted_into_target_choices(db):
    world, agents = make_world(db, 3)
    actor = agents[0]
    _prompt, refs = build_turn_context(db, world, actor)
    spec = get_tool("ask_visible_agent_to_introduce")
    assert spec is not None

    options = build_action_options(db, world, actor, [spec], refs, limit=20)

    assert len(options) == 1
    option = options[0]
    assert option.tool_name == "ask_visible_agent_to_introduce"
    assert len(option.target_choices) == 2
    menu = format_action_options_for_prompt(options)
    assert "目标:" in menu
    assert "[目标=编号 / 台词]" in menu

    packet = parse_action_packet(f"[{option.option_id}:2]\n请问怎么称呼你？")
    action = packet_to_action_choice(packet, options, agent=actor) if packet else None
    assert action is not None
    assert action.params["speech"] == "请问怎么称呼你？"
    assert action.params["visible_ref"] == option.target_choices[1]["params"]["visible_ref"]


def test_finance_market_research_does_not_require_broker_account(db):
    world, agents = make_world(db, 1)
    actor = agents[0]
    actor.wallet_json = {"money": 12}
    ensure_v6_agent_state(actor)
    assert not (actor.wallet_json or {}).get("broker_account")

    result = execute_tool(db, world=world, actor=actor, tool_name="v6_read_market_news", params={"ticker": "MGL"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "v6_stock_research"
    assert event.payload["broker_exists"] is False
    assert "还没有证券账户" in event.viewer_text


def test_child_care_can_stabilize_critical_newborn_in_same_room(db):
    world, agents = make_world(db, 2)
    caregiver, child = agents
    child.age_stage = "newborn"
    child.lifecycle_state = "critical"
    child.dynamic_state.health = 8
    child.dynamic_state.energy = 2
    child.dynamic_state.satiety = 4
    child.dynamic_state.hydration = 4
    child.dynamic_state.critical_reason = "hunger_thirst"
    caregiver.location.location_id = f"{world.world_id}:cabin"
    child.location.location_id = f"{world.world_id}:cabin"
    caregiver.location.location = db.get(Location, f"{world.world_id}:cabin")
    child.location.location = caregiver.location.location
    db.flush()

    _prompt, refs = build_turn_context(db, world, caregiver)
    ref = _visible_ref_for(refs, child.agent_id)
    result = execute_tool(db, world=world, actor=caregiver, tool_name="feed_child_visible_agent", params={"visible_ref": ref})

    assert result.ok
    assert child.lifecycle_state == "alive"
    assert child.dynamic_state.satiety > 25
    assert child.dynamic_state.hydration > 25
    assert child.dynamic_state.health > 20
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "child_feed"
    assert event.payload["child_stage"] == "newborn"


def test_unconscious_agent_can_be_escorted_to_medical_and_fed(db):
    world, agents = make_world(db, 2)
    helper, patient = agents
    helper.wallet_json = {"money": 100}
    helper.location.location_id = f"{world.world_id}:cafeteria"
    patient.location.location_id = f"{world.world_id}:cafeteria"
    helper.location.location = db.get(Location, f"{world.world_id}:cafeteria")
    patient.location.location = helper.location.location
    db.flush()
    patient.lifecycle_state = "critical"
    patient.dynamic_state.health = 10
    patient.dynamic_state.energy = 3
    patient.dynamic_state.satiety = 5
    patient.dynamic_state.hydration = 5
    patient.dynamic_state.critical_reason = "fainted"

    _prompt, refs = build_turn_context(db, world, helper)
    ref = _visible_ref_for(refs, patient.agent_id)
    escort = execute_tool(db, world=world, actor=helper, tool_name="escort_visible_agent_to_medical", params={"visible_ref": ref})

    assert escort.ok
    assert helper.location.location_id == f"{world.world_id}:medical_room"
    assert patient.location.location_id == f"{world.world_id}:medical_room"
    assert helper.dynamic_state.energy < 80

    _prompt, refs = build_turn_context(db, world, helper)
    ref = _visible_ref_for(refs, patient.agent_id)
    fed = execute_tool(db, world=world, actor=helper, tool_name="feed_visible_agent_meal", params={"visible_ref": ref})

    assert fed.ok
    assert patient.dynamic_state.satiety > 35
    assert patient.dynamic_state.hydration > 30
    assert patient.dynamic_state.energy > 8
    assert patient.lifecycle_state in {"alive", "critical"}
    assisted_event = db.get(Event, fed.event_ids[0])
    assert assisted_event.event_type == "assisted_meal"


def test_reaction_tools_prioritize_real_child_and_survival_help(db):
    world, agents = make_world(db, 2)
    actor, newborn = agents
    newborn.age_stage = "newborn"
    newborn.dynamic_state.satiety = 8
    newborn.dynamic_state.hydration = 8
    actor.location.location_id = f"{world.world_id}:cabin"
    newborn.location.location_id = f"{world.world_id}:cabin"
    actor.location.location = db.get(Location, f"{world.world_id}:cabin")
    newborn.location.location = actor.location.location
    db.flush()

    _prompt, refs = build_turn_context(db, world, actor, reaction=True)
    specs = available_tools(actor, actor.location.location, reaction=True, session=db)
    tool_names = {spec.tool_name for spec in specs}
    assert {"feed_child_visible_agent", "care_for_child_visible_agent", "check_child_status_visible_agent"}.issubset(tool_names)

    options = build_action_options(db, world, actor, [spec for spec in specs if spec.tool_name in {"feed_child_visible_agent", "care_for_child_visible_agent"}], refs, reaction=True, limit=20)
    assert options
    assert all(option.target_choices for option in options)
