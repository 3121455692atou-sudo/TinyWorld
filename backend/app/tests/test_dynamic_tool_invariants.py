from __future__ import annotations

from dataclasses import replace
from copy import deepcopy

import pytest

from app.core.models import IdentityKnowledge, Location
from app.llm.action_options import build_action_options
from app.tools.registry import available_tools
from app.tools.tool_specs import TOOL_SPECS
from app.tools.validators import validate_tool
from app.world.visibility import build_visible_people, mark_name_known
from conftest import make_world


def _refs(db, world, actor):
    return {
        person.visible_ref: person.target_agent_id
        for person in build_visible_people(db, actor, world.current_world_time_minutes, persist=False)
    }


def _validate(db, world, actor, tool_name, params, **kwargs):
    return validate_tool(
        db,
        actor=actor,
        tool_name=tool_name,
        params=params,
        world_time=world.current_world_time_minutes,
        persist_visibility=False,
        **kwargs,
    )


def test_disabled_module_blocks_direct_validation_and_action_menu(db):
    world, (actor,) = make_world(db, agent_count=1)
    name = "v6_read_market_news"
    assert _validate(db, world, actor, name, {}).ok
    world.settings_json = {**world.settings_json, "disabled_tool_modules": ["finance"]}

    validation = _validate(db, world, actor, name, {})
    assert not validation.ok
    assert validation.reason_code == "tool_module_disabled"
    assert name not in {spec.tool_name for spec in available_tools(actor, actor.location.location, session=db)}
    assert not build_action_options(db, world, actor, [TOOL_SPECS[name]], {})

    world.settings_json = {**world.settings_json, "disabled_tool_modules": []}
    assert _validate(db, world, actor, name, {}).ok


@pytest.mark.parametrize("params", [{}, {"location_id": ""}, {"location_id": "world"}, {"location_id": ":"}])
def test_movement_never_infers_missing_or_partial_location(db, params):
    world, (actor,) = make_world(db, agent_count=1)
    result = _validate(db, world, actor, "move_to_location", params)
    assert not result.ok
    assert result.reason_code in {"missing_location", "location_not_adjacent"}
    assert result.destination is None


def test_movement_accepts_exact_local_id_and_rejects_ambiguous_name(db):
    world, (actor,) = make_world(db, agent_count=1)
    location = actor.location.location
    destinations = [db.get(Location, value) for value in location.neighbors_json]
    destinations = [value for value in destinations if value and "private" not in (value.tags_json or [])]
    first, second = destinations[:2]
    result = _validate(db, world, actor, "move_to_location", {"location_id": first.location_id.split(":", 1)[1]})
    assert result.ok
    assert result.destination is first
    first.public_name = second.public_name = "同名广场"
    result = _validate(db, world, actor, "move_to_location", {"location_name": "同名广场"})
    assert not result.ok
    assert result.reason_code == "ambiguous_location"


def test_duplicate_known_names_require_an_explicit_menu_target(db):
    world, (actor, first, second) = make_world(db, agent_count=3)
    first.chosen_name = second.chosen_name = "同名居民"
    for target in (first, second):
        mark_name_known(db, actor.agent_id, target, 0, "test")
    db.flush()

    result = _validate(db, world, actor, "record_relationship_note_by_name", {"known_name": "同名居民", "note": "记录"})
    assert not result.ok
    assert result.reason_code == "ambiguous_known_name"

    options = build_action_options(db, world, actor, [TOOL_SPECS["record_relationship_note_by_name"]], {})
    assert len(options) == 1
    assert len(options[0].target_choices) == 2
    assert len({choice["label"] for choice in options[0].target_choices}) == 2
    for choice in options[0].target_choices:
        result = _validate(db, world, actor, options[0].tool_name, {**choice["params"], "note": "记录"})
        assert result.ok
        assert result.target_agent.agent_id == choice["target_agent_id"]


@pytest.mark.parametrize("params", [None, [], "location=library", 3])
def test_non_object_params_fail_without_crashing(db, params):
    world, (actor,) = make_world(db, agent_count=1)
    result = _validate(db, world, actor, "move_to_location", params)
    assert not result.ok
    assert result.reason_code == "invalid_params"


@pytest.mark.parametrize("speech", [True, 123, ["你好"], {"text": "你好"}])
def test_non_string_speech_is_not_converted_into_dialogue(db, speech):
    world, (actor,) = make_world(db, agent_count=1)
    result = _validate(db, world, actor, "speak_to_nearby", {"speech": speech})
    assert not result.ok
    assert result.reason_code == "invalid_param_type"


def test_reaction_validation_obeys_the_reaction_menu(db):
    world, (actor,) = make_world(db, agent_count=1)
    assert _validate(db, world, actor, "rest", {}).ok
    result = _validate(db, world, actor, "rest", {}, reaction=True)
    assert not result.ok
    assert result.reason_code == "reaction_tool_blocked"
    assert _validate(db, world, actor, "do_nothing", {}, reaction=True).ok


def test_stale_reference_map_never_targets_a_different_person(db):
    world, (actor, first, second) = make_world(db, agent_count=3)
    refs = _refs(db, world, actor)
    swapped = {ref: second.agent_id if target_id == first.agent_id else first.agent_id for ref, target_id in refs.items()}
    options = build_action_options(db, world, actor, [TOOL_SPECS["observe_visible_agent"]], swapped)
    assert not options


@pytest.mark.parametrize("persist_visibility", [False, True])
def test_selected_resident_id_survives_reference_renumbering(db, persist_visibility):
    from app.llm.action_protocol import parse_action_choice

    world, (actor, first, selected) = make_world(db, agent_count=3)
    refs = _refs(db, world, actor)
    options = build_action_options(db, world, actor, [TOOL_SPECS["observe_visible_agent"]], refs)
    choice = next(choice for choice in options[0].target_choices if choice["target_agent_id"] == selected.agent_id)
    parsed = parse_action_choice(f"[{options[0].option_id}:{choice['id']}]", options)
    assert parsed.action is not None
    original_ref = parsed.action.params["visible_ref"]

    first.location.location_id = f"{world.world_id}:library"
    first.location.location = db.get(Location, first.location.location_id)
    db.flush()
    new_refs = _refs(db, world, actor)
    assert new_refs.get(original_ref) != selected.agent_id
    result = validate_tool(db, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params,
                           world_time=world.current_world_time_minutes, persist_visibility=persist_visibility)
    assert result.ok
    assert result.target_agent is selected

    selected.location.location_id = f"{world.world_id}:library"
    selected.location.location = db.get(Location, selected.location.location_id)
    db.flush()
    result = validate_tool(db, actor=actor, tool_name=parsed.action.tool_name, params=parsed.action.params,
                           world_time=world.current_world_time_minutes, persist_visibility=persist_visibility)
    assert not result.ok
    assert result.reason_code == "target_not_visible"
    assert result.target_agent is None


def test_visible_people_are_materialized_once_per_menu(db, monkeypatch):
    from app.llm import action_options
    from app.tools import validators
    from app.world import visibility

    world, (actor, _first, _second, _third) = make_world(db, agent_count=4)
    refs = _refs(db, world, actor)
    original = visibility.build_visible_people
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(action_options, "build_visible_people", counted)
    monkeypatch.setattr(validators, "build_visible_people", counted)
    monkeypatch.setattr(visibility, "build_visible_people", counted)
    specs = [TOOL_SPECS[name] for name in ("observe_visible_agent", "say_to_visible_agent", "help_visible_agent")]
    options = build_action_options(db, world, actor, specs, refs)
    assert len(options) == 3
    assert len(calls) == 1


def test_invalid_do_nothing_is_not_reintroduced_after_validation(db):
    world, (actor,) = make_world(db, agent_count=1)
    actor.lifecycle_state = "dead"
    assert not build_action_options(db, world, actor, [TOOL_SPECS["do_nothing"]], {})


@pytest.mark.parametrize("effect", ["worldpack_declarative", "v5_catalog_generic"])
def test_external_tools_cannot_leak_between_world_toolsets(db, monkeypatch, effect):
    from app.content import worldpacks

    world, (actor,) = make_world(db, agent_count=1)
    name = "worldpack_test_attune"
    spec = replace(
        TOOL_SPECS["do_nothing"],
        tool_name=name,
        display_name="调整共鸣",
        hard_effect_id=effect,
        metadata={"source_kind": "worldpack", "toolset_id": "isolated_tools", "declarative_effect": {}},
    )
    monkeypatch.setitem(TOOL_SPECS, name, spec)
    monkeypatch.setattr(worldpacks, "_CACHE", [worldpacks.LoadedWorldPack(
        "isolated_pack", "隔离包", "1.0", "test.json",
        {"toolsets": [{"toolset_id": "isolated_tools", "tools": [{"tool_name": name}]}]},
    )])
    actor.location.location.available_tools_json = [*actor.location.location.available_tools_json, name]
    result = _validate(db, world, actor, name, {})
    assert not result.ok
    assert result.reason_code == "world_toolset_disabled"
    assert name not in {item.tool_name for item in available_tools(actor, actor.location.location, session=db)}

    world.settings_json = {**world.settings_json, "world_toolset_id": "isolated_tools"}
    assert _validate(db, world, actor, name, {}).ok


def test_external_refresh_updates_removes_and_never_overwrites_builtins(monkeypatch):
    from app.content import worldpacks
    from app.tools import tool_specs

    monkeypatch.setattr(tool_specs, "TOOL_SPECS", dict(tool_specs.TOOL_SPECS))
    original_builtin = tool_specs.TOOL_SPECS["look_around"]
    name = "external_refresh_test"
    definitions = [{
        "tool_name": name, "display_name": "第一版", "toolset_id": "refresh_tools",
        "time_cost_minutes": 5, "declarative_effect": {"money_delta": 3},
    }, {"tool_name": "look_around", "display_name": "非法覆盖"}]
    monkeypatch.setattr(worldpacks, "load_all_worldpacks", lambda **kwargs: [])
    monkeypatch.setattr(worldpacks, "iter_external_tool_definitions", lambda: iter(deepcopy(definitions)))

    tool_specs.refresh_external_worldpack_tools()
    assert tool_specs.TOOL_SPECS[name].time_cost_minutes == 5
    assert tool_specs.TOOL_SPECS["look_around"] is original_builtin
    definitions[0].update(display_name="第二版", time_cost_minutes=18, cooldown_minutes="invalid", declarative_effect={"money_delta": -7})
    assert tool_specs.refresh_external_worldpack_tools() == 1
    assert tool_specs.TOOL_SPECS[name].display_name == "第二版"
    assert tool_specs.TOOL_SPECS[name].metadata["declarative_effect"] == {"money_delta": -7}
    assert tool_specs.TOOL_SPECS[name].cooldown_minutes == 0
    assert tool_specs.refresh_external_worldpack_tools() == 0

    definitions.clear()
    assert tool_specs.refresh_external_worldpack_tools() == 1
    assert name not in tool_specs.TOOL_SPECS
    assert tool_specs.TOOL_SPECS["look_around"] is original_builtin


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), "NaN", "Infinity", True, [], {}])
def test_invalid_numbers_are_rejected_before_state_changes(db, value):
    world, (actor,) = make_world(db, agent_count=1)
    result = _validate(db, world, actor, "sleep_rough", {"sleep_hours": value})
    assert not result.ok
    assert result.reason_code == "invalid_number"


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_sleep_flag_requires_a_real_boolean(db, value):
    world, (actor,) = make_world(db, agent_count=1)
    result = _validate(db, world, actor, "return_home", {"sleep_after_arrival": value})
    assert not result.ok
    assert result.reason_code == "invalid_param_type"


@pytest.mark.parametrize("raw", ["[0:-1]", "[0:1.5]", "[0:one1]", "[0:1 or 2]", "[0:1000]", "[0:0]"])
def test_malformed_target_numbers_never_choose_someone(raw):
    from app.llm.action_protocol import ActionOption, parse_action_choice

    option = ActionOption(
        0, "观察", "observe_visible_agent",
        target_choices=({"id": 1, "label": "甲", "params": {"visible_ref": "附近人物A"}, "target_agent_id": "person_a"},),
    )
    assert parse_action_choice(raw, [option]).action is None
    parsed = parse_action_choice("[0:1]", [option])
    assert parsed.action.params["visible_agent_id"] == "person_a"


def test_only_displayed_target_numbers_are_accepted():
    from app.llm.action_protocol import ActionOption, format_action_options_for_prompt, parse_action_choice

    option = ActionOption(0, "观察", "observe_visible_agent", target_choices=tuple(
        {"id": idx, "label": f"target-{idx}", "params": {"visible_ref": f"ref-{idx}"}}
        for idx in range(1, 30)
    ))
    assert "target-25" not in format_action_options_for_prompt([option])
    assert parse_action_choice("[0:25]", [option]).action is None
    assert parse_action_choice("[0:24]", [option]).action is not None


@pytest.mark.parametrize("attribute,expected_tool", [("hydration", "request_water_help"), ("satiety", "request_food_help"), ("energy", "rest")])
def test_capped_menu_preserves_need_priority_and_diary(db, attribute, expected_tool):
    world, agents = make_world(db, agent_count=4)
    actor = agents[0]
    actor.dynamic_state.hydration = actor.dynamic_state.satiety = actor.dynamic_state.energy = 80
    setattr(actor.dynamic_state, attribute, 8)
    specs = available_tools(actor, actor.location.location, session=db)
    options = build_action_options(db, world, actor, specs, _refs(db, world, actor))
    names = [option.tool_name for option in options]
    assert len(options) <= 60
    assert expected_tool in names
    assert names.index(expected_tool) < names.index("say_to_visible_agent")
    assert "write_diary" in names
    assert "rest" in names


def test_menu_snapshot_is_not_reused_after_same_clock_state_changes(db):
    world, (actor, target) = make_world(db, agent_count=2)
    refs = _refs(db, world, actor)
    specs = [TOOL_SPECS["observe_visible_agent"], TOOL_SPECS["wake_visible_agent"]]
    first = build_action_options(db, world, actor, specs, refs)
    assert {option.tool_name for option in first} == {"observe_visible_agent"}
    target.desires_json = {**target.desires_json, "sleep_until_world_time": 60}
    second = build_action_options(db, world, actor, specs, refs)
    assert {option.tool_name for option in second} == {"observe_visible_agent", "wake_visible_agent"}
    target.location.location_id = f"{world.world_id}:library"
    target.location.location = db.get(Location, target.location.location_id)
    db.flush()
    assert not build_action_options(db, world, actor, specs, refs)


@pytest.mark.parametrize("last_aid", [0, 120])
def test_community_aid_cooldown_is_identical_in_menu_and_validation(db, last_aid):
    from app.simulation.difficulty import profile_for_world

    world, (actor,) = make_world(db, agent_count=1)
    spec = TOOL_SPECS["accept_community_aid"]
    params = {"speech": "申请领取一份食物和饮用水。"}
    assert _validate(db, world, actor, spec.tool_name, params).ok
    cooldown = int(profile_for_world(world)["aid_food_cooldown_h"]) * 60
    actor.desires_json = {**actor.desires_json, "last_community_aid_world_time": last_aid}
    world.current_world_time_minutes = last_aid + cooldown - 1
    result = _validate(db, world, actor, spec.tool_name, params)
    assert not result.ok
    assert result.reason_code == "community_aid_cooldown"
    assert not build_action_options(db, world, actor, [spec], {})

    world.current_world_time_minutes += 1
    assert _validate(db, world, actor, spec.tool_name, params).ok
    assert len(build_action_options(db, world, actor, [spec], {})) == 1


def test_known_name_and_id_must_refer_to_the_same_known_resident(db):
    world, (actor, known, unknown) = make_world(db, agent_count=3)
    mark_name_known(db, actor.agent_id, known, 0, "test")
    result = _validate(db, world, actor, "record_relationship_note_by_name", {
        "known_name": known.chosen_name, "known_agent_id": unknown.agent_id, "note": "不能偷换目标",
    })
    assert not result.ok
    assert result.reason_code == "name_unknown"


def test_duplicate_heard_names_do_not_reveal_unknown_appearance(db):
    world, (actor, first, second) = make_world(db, agent_count=3)
    for target in (first, second):
        db.add(IdentityKnowledge(observer_agent_id=actor.agent_id, target_agent_id=target.agent_id,
                                 name_known=True, known_name="同名居民", visual_known=False))
    db.flush()
    options = build_action_options(db, world, actor, [TOOL_SPECS["record_relationship_note_by_name"]], {})
    labels = [choice["label"] for choice in options[0].target_choices]
    assert len(set(labels)) == 2
    assert all("外貌未记录" in label for label in labels)
    assert all(target.appearance_short not in label for target in (first, second) for label in labels)


def test_introducing_someone_requires_known_third_person_and_binds_both_ids(db):
    world, (actor, receiver, third) = make_world(db, agent_count=3)
    refs = _refs(db, world, actor)
    receiver_ref = next(ref for ref, target_id in refs.items() if target_id == receiver.agent_id)
    bad = _validate(db, world, actor, "introduce_other_agent", {
        "visible_ref": receiver_ref, "known_name": third.chosen_name,
        "speech": "那边的居民可以介绍给大家。",
    })
    assert not bad.ok
    assert bad.reason_code == "name_unknown"
    mark_name_known(db, actor.agent_id, third, 0, "test")
    options = build_action_options(db, world, actor, [TOOL_SPECS["introduce_other_agent"]], refs)
    assert len(options) == 1
    assert len(options[0].target_choices) == 1
    params = options[0].target_choices[0]["params"]
    assert params["visible_agent_id"] == receiver.agent_id
    assert params["known_agent_id"] == third.agent_id
    assert _validate(db, world, actor, "introduce_other_agent", {**params, "speech": "向眼前的居民介绍认识的人。"}).ok


@pytest.mark.parametrize("kind", ["introduction", "intimacy"])
@pytest.mark.parametrize("leave_selected", [False, True])
@pytest.mark.parametrize("move_before_conversion", [False, True])
def test_intent_conversion_keeps_selected_resident_through_actual_execution(db, kind, leave_selected, move_before_conversion):
    from app.core.models import Event
    from app.effects.effect_engine import execute_tool
    from app.llm.action_protocol import parse_action_choice
    from app.simulation.turn_runner import _align_adult_intimacy_intent_to_tool, _align_intro_request_intent_to_tool

    world, (actor, first, selected, replacement) = make_world(db, agent_count=4)
    world.settings_json = {**world.settings_json, "reproduction_enabled": True}
    actor.family_json = {**actor.family_json, "partner_agent_id": selected.agent_id}
    selected.family_json = {**selected.family_json, "partner_agent_id": actor.agent_id}
    options = build_action_options(db, world, actor, [TOOL_SPECS["say_to_visible_agent"]], _refs(db, world, actor))
    choice = next(choice for choice in options[0].target_choices if choice["target_agent_id"] == selected.agent_id)
    speech = "怎么称呼，方便告诉我吗？" if kind == "introduction" else "希望进一步成年亲密相处。"
    parsed = parse_action_choice(f"[{options[0].option_id}:{choice['id']}]\n{speech}", options)
    assert parsed.action is not None
    expected_tool = "ask_visible_agent_to_introduce" if kind == "introduction" else "request_adult_intimacy_visible_agent"
    allowed = {"say_to_visible_agent", expected_tool}

    def depart():
        moving = selected if leave_selected else first
        moved = execute_tool(db, world=world, actor=moving, tool_name="move_to_location",
                             params={"location_id": f"{world.world_id}:library"})
        assert moved.ok

    if move_before_conversion:
        depart()
    if kind == "introduction":
        aligned = _align_intro_request_intent_to_tool(db, world, actor, parsed.action, allowed=allowed)
    else:
        aligned = _align_adult_intimacy_intent_to_tool(db, world, actor, parsed.action, allowed=allowed, reaction=False)
    assert aligned.params.get("visible_agent_id") == selected.agent_id
    if not leave_selected:
        assert aligned.tool_name == expected_tool
    if not move_before_conversion:
        depart()
    before_time = world.current_world_time_minutes
    result = execute_tool(db, world=world, actor=actor, tool_name=aligned.tool_name, params=aligned.params)
    events = [db.get(Event, event_id) for event_id in result.event_ids]
    if leave_selected:
        assert not result.ok
        assert world.current_world_time_minutes == before_time
        assert any((event.payload or {}).get("failure_reason_code") == "target_not_visible" for event in events)
    else:
        assert result.ok, result.message
        event_type = "ask_introduction" if kind == "introduction" else "adult_intimacy_request"
        relevant = [event for event in events if event.event_type == event_type]
        assert relevant and all(event.target_agent_id == selected.agent_id for event in relevant)
        assert replacement.agent_id not in result.reaction_agent_ids


@pytest.mark.parametrize("kind", ["introduction", "intimacy"])
def test_unbound_explicit_name_intent_gets_a_stable_target_id(db, kind):
    from app.llm.schemas import ActionChoice
    from app.simulation.turn_runner import _align_adult_intimacy_intent_to_tool, _align_intro_request_intent_to_tool

    world, (actor, first, selected) = make_world(db, agent_count=3)
    world.settings_json = {**world.settings_json, "reproduction_enabled": True}
    actor.family_json = {**actor.family_json, "partner_agent_id": selected.agent_id}
    mark_name_known(db, actor.agent_id, selected, 0, "test")
    refs = _refs(db, world, actor)
    first_ref = next(ref for ref, target_id in refs.items() if target_id == first.agent_id)
    speech = f"{selected.chosen_name}，" + ("怎么称呼？" if kind == "introduction" else "希望进一步成年亲密相处。")
    action = ActionChoice(tool_name="say_to_visible_agent", params={"visible_ref": first_ref, "speech": speech})
    expected_tool = "ask_visible_agent_to_introduce" if kind == "introduction" else "request_adult_intimacy_visible_agent"
    if kind == "introduction":
        aligned = _align_intro_request_intent_to_tool(db, world, actor, action, allowed={expected_tool})
    else:
        aligned = _align_adult_intimacy_intent_to_tool(db, world, actor, action, allowed={expected_tool}, reaction=False)
    assert aligned.tool_name == expected_tool
    assert aligned.params["visible_agent_id"] == selected.agent_id
    assert refs[aligned.params["visible_ref"]] == selected.agent_id


