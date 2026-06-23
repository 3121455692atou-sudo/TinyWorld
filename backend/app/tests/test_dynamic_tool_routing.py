from __future__ import annotations

from app.core.models import Location, Relationship
from app.knowledge.perception import build_turn_context, build_turn_context_with_options
from app.llm.action_options import build_action_options
from app.simulation.turn_runner import _experimental_tool_router_config, _parse_router_option_ids
from app.llm.action_protocol import ActionOption
from app.content.toolsets import FINANCE_INVESTING_TOOLSET_ID, REPRODUCTION_TOOLSET_ID, SURVIVAL_NEEDS_TOOLSET_ID
from app.tools.registry import available_tools, catalog_generic_disabled_for_agent
from app.tools.tool_specs import TOOL_SPECS
from app.tools.validators import validate_tool
from app.social.intervention_crush import set_intervention_crush
from conftest import make_world


def _move_agent(db, world, agent, local_location_id: str):
    location = db.get(Location, f"{world.world_id}:{local_location_id}")
    assert location is not None
    agent.location.location_id = location.location_id
    agent.location.location = location
    db.flush()
    return location


def _options_for(db, world, agent):
    _prompt, refs = build_turn_context(db, world, agent)
    specs = available_tools(agent, agent.location.location, session=db)
    options = build_action_options(db, world, agent, specs, refs)
    return specs, options


def _option_names(options):
    return [option.tool_name for option in options]


def test_catalog_target_policy_does_not_misread_no_name_or_location_visibility(db):
    # Abstract duplicates of core sleep/move/work tools are pruned before registration;
    # the concrete core tools carry the real effects.
    assert "tool_body_rest_short" not in TOOL_SPECS
    assert "tool_work_start_shift" not in TOOL_SPECS
    assert "tool_location_enter_room" not in TOOL_SPECS
    assert TOOL_SPECS["tool_social_greet_visible"].target_policy == "visible_ref"
    assert TOOL_SPECS["tool_body_treat_wound_other"].target_policy == "visible_ref"
    assert TOOL_SPECS["tool_learn_read_book"].target_policy == "none"


def test_dynamic_menu_surfaces_catalog_social_tools_without_meta_noise(db):
    world, agents = make_world(db, agent_count=4)
    db.commit()
    _specs, options = _options_for(db, world, agents[0])
    names = _option_names(options)

    assert "tool_social_greet_visible" in names
    assert "speak_to_nearby" in names or "say_to_visible_agent" in names
    assert "tool_group_start_chat" not in names
    assert "tool_group_join_chat" not in names
    assert "tool_group_leave_chat" not in names
    assert "request_more_candidate_tools" not in names
    assert "explain_available_tools" not in names
    assert not any("candidate" in name or name.startswith("tool_meta_") for name in names)
    assert len(options) <= 140
    # First-contact plaza menus should not be crowded by adult/private-life catalog actions
    # or reply-only catalog entries that need a missing conversation/invite state.
    assert not any(name.startswith("tool_adult_") for name in names)
    assert "request_adult_intimacy_visible_agent" not in names
    assert "request_food_help" not in names
    assert "request_water_help" not in names
    assert "tool_comm_end_private_talk" not in names
    assert "tool_romance_accept_confession" not in names


def test_cafeteria_hungry_routes_food_and_cafeteria_tools(db):
    world, agents = make_world(db, agent_count=4)
    actor = agents[0]
    _move_agent(db, world, actor, "cafeteria")
    actor.dynamic_state.satiety = 12
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "eat_food" in names
    assert "request_food_help" in names
    assert any(name.startswith("tool_food_") or name.startswith("tool_cafeteria_") for name in names)
    assert "tool_market_buy_baby_supplies" not in names
    assert "tool_create_code_small_tool" not in names
    assert not any(name.startswith(("tool_victim_", "tool_police_", "tool_court_")) for name in names)


def test_medical_room_routes_body_and_medical_tools_without_cafeteria_market_noise(db):
    world, agents = make_world(db, agent_count=4)
    actor = agents[0]
    _move_agent(db, world, actor, "medical_room")
    actor.dynamic_state.health = 30
    actor.dynamic_state.energy = 20
    actor.dynamic_state.satiety = 65
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "medical_checkup" in names
    assert "free_medical_wash" in names
    assert "tool_body_treat_self" in names or "tool_body_sit_down" in names
    assert not any(name.startswith(("tool_cafeteria_", "tool_market_", "tool_service_", "tool_victim_", "tool_police_", "tool_court_")) for name in names)
    assert "v6_open_broker_account" not in names
    assert "v6_read_market_news" not in names
    assert "tool_econ_trade_item" not in names


def test_library_curiosity_routes_learning_and_memory_not_law_noise(db):
    world, agents = make_world(db, agent_count=4)
    actor = agents[0]
    _move_agent(db, world, actor, "library")
    actor.dynamic_state.curiosity = 90
    actor.dynamic_state.satiety = 80
    actor.dynamic_state.hydration = 80
    actor.dynamic_state.energy = 80
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "tool_learn_read_book" in names or "read_quietly" in names
    assert "write_diary" in names or "tool_memory_summarize_day" in names or "tool_create_write_diary" in names
    assert not any(name.startswith(("tool_victim_", "tool_police_", "tool_court_", "tool_cafeteria_", "tool_market_")) for name in names)
    assert "tool_romance_accept_confession" not in names
    assert "tool_comm_end_private_talk" not in names


def test_catalog_visible_ref_options_bind_targets_and_validate(db):
    world, agents = make_world(db, agent_count=4)
    actor = agents[0]
    db.commit()

    _specs, options = _options_for(db, world, actor)
    option = next((item for item in options if item.tool_name == "tool_social_greet_visible"), None)
    assert option is not None
    assert option.text_slot == "speech"
    assert option.text_required
    assert option.target_choices
    params = dict(option.target_choices[0]["params"])
    params["speech"] = "早上好，我想先打个招呼。"

    validation = validate_tool(
        db,
        actor=actor,
        tool_name=option.tool_name,
        params=params,
        world_time=world.current_world_time_minutes,
    )
    assert validation.ok, validation.message
    assert validation.target_agent is not None


def test_zero_affection_hides_commitment_and_intimacy_tools(db):
    world, agents = make_world(db, agent_count=3)
    actor, target = agents[0], agents[1]
    db.add(
        Relationship(
            observer_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            familiarity=70,
            trust=70,
            affection=0,
            relationship_label="普通熟人",
        )
    )
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "define_relationship_visible_agent" not in names
    assert "request_adult_intimacy_visible_agent" not in names
    assert not any(name.startswith(("tool_adult_", "tool_romance_")) for name in names)


def test_high_affection_prioritizes_commitment_request_and_filters_targets(db):
    world, agents = make_world(db, agent_count=3)
    actor, beloved, stranger = agents[0], agents[1], agents[2]
    db.add_all(
        [
            Relationship(
                observer_agent_id=actor.agent_id,
                target_agent_id=beloved.agent_id,
                familiarity=82,
                trust=86,
                affection=94,
                relationship_label="亲密朋友",
            ),
            Relationship(
                observer_agent_id=actor.agent_id,
                target_agent_id=stranger.agent_id,
                familiarity=5,
                trust=50,
                affection=0,
                relationship_label="陌生",
            ),
        ]
    )
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "define_relationship_visible_agent" in names
    assert names.index("define_relationship_visible_agent") < 18
    define_option = next(option for option in options if option.tool_name == "define_relationship_visible_agent")
    target_ids = {choice.get("target_agent_id") for choice in define_option.target_choices}
    assert target_ids == {beloved.agent_id}


def test_intervention_crush_surfaces_prompt_and_frontloads_romance_tools(db):
    world, (actor, target, stranger) = make_world(db, agent_count=3)
    set_intervention_crush(actor, target, world.current_world_time_minutes)
    db.commit()

    context = build_turn_context_with_options(db, world, actor)
    names = _option_names(context.action_options)

    assert "强制心动" in context.prompt
    assert target.chosen_name in context.prompt
    assert "confess_feelings_visible_agent" in names
    assert names.index("confess_feelings_visible_agent") < 18
    confess_option = next(option for option in context.action_options if option.tool_name == "confess_feelings_visible_agent")
    target_ids = {choice.get("target_agent_id") for choice in confess_option.target_choices}
    assert target_ids == {target.agent_id}
    assert stranger.agent_id not in target_ids


def test_negative_relationship_tools_surface_under_stress(db):
    world, (actor, target) = make_world(db, agent_count=2)
    actor.dynamic_state.stress = 70
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "express_dislike_visible_agent" in names
    assert "criticize_behavior_visible_agent" in names
    assert "reject_closeness_visible_agent" in names


def test_partner_context_prioritizes_family_planning_tools_without_catalog_noise(db):
    world, agents = make_world(db, agent_count=2)
    world.settings_json = {
        **(world.settings_json or {}),
        "enabled_optional_toolset_ids": [
            SURVIVAL_NEEDS_TOOLSET_ID,
            FINANCE_INVESTING_TOOLSET_ID,
            REPRODUCTION_TOOLSET_ID,
        ],
        "reproduction_enabled": True,
    }
    actor, partner = agents[0], agents[1]
    actor.family_json = {**(actor.family_json or {}), "partner_agent_id": partner.agent_id}
    partner.family_json = {**(partner.family_json or {}), "partner_agent_id": actor.agent_id}
    db.add(
        Relationship(
            observer_agent_id=actor.agent_id,
            target_agent_id=partner.agent_id,
            familiarity=90,
            trust=88,
            affection=92,
            relationship_label="恋人",
        )
    )
    _move_agent(db, world, actor, "market")
    _move_agent(db, world, partner, "market")
    db.commit()

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)

    assert "request_adult_intimacy_visible_agent" in names
    assert names.index("request_adult_intimacy_visible_agent") < 18
    assert "buy_contraception" in names
    assert names.index("buy_contraception") < 30
    assert not any(name.startswith(("tool_adult_", "tool_romance_")) for name in names)


def test_generic_work_catalog_noops_are_not_agent_facing(db):
    world, agents = make_world(db, agent_count=4)
    actor = agents[0]
    _move_agent(db, world, actor, "cafeteria")
    db.commit()

    # These legacy catalog entries only generated vague text like "收回注意力去工作"
    # and did not perform a concrete job/meal/state change, so they should neither
    # appear in menus nor validate if called directly.
    assert "tool_work_assign_chore" in TOOL_SPECS
    assert catalog_generic_disabled_for_agent(TOOL_SPECS["tool_work_assign_chore"])
    validation = validate_tool(db, actor=actor, tool_name="tool_work_assign_chore", params={}, world_time=world.current_world_time_minutes)
    assert not validation.ok
    assert validation.reason_code == "generic_catalog_noop_disabled"

    _specs, options = _options_for(db, world, actor)
    names = _option_names(options)
    assert not any(name.startswith("tool_work_") for name in names)
    assert not any(name in {"tool_cafeteria_worker_take_order", "tool_cafeteria_worker_offer_discount"} for name in names)


def test_experimental_llm_tool_router_is_default_off_and_parses_suggestions(db):
    world, _agents = make_world(db, agent_count=1)

    assert _experimental_tool_router_config(world) == {"enabled": False, "max_suggestions": 0, "max_tokens": 0}

    world.settings_json = {"experimental_llm_tool_router": {"enabled": True, "max_suggestions": 2, "max_tokens": 120}}
    config = _experimental_tool_router_config(world)
    assert config["enabled"] is True
    assert config["max_suggestions"] == 2
    assert config["max_tokens"] == 120

    options = [
        ActionOption(option_id=1, label="说话", tool_name="speak_to_nearby"),
        ActionOption(option_id=2, label="吃饭", tool_name="eat_food"),
        ActionOption(option_id=3, label="睡觉", tool_name="sleep"),
    ]
    parsed = _parse_router_option_ids("优先 [02]，再考虑 speak_to_nearby，最后 [03]", options, 2)
    assert [option.tool_name for option in parsed] == ["eat_food", "sleep"]


def test_disabled_tool_modules_unit_logic():
    # Phase 2D: per-world category disabling never touches core tools (no
    # catalog_category) and is a no-op when the disabled set is empty.
    from app.tools.registry import _spec_in_disabled_module
    from app.tools.tool_specs import ToolSpec

    stock = ToolSpec("x_stock", "炒股", "d", catalog_category="stock_market")
    core = ToolSpec("x_core", "核心", "d", catalog_category=None)
    creator = ToolSpec("x_creator", "创作", "d", catalog_category="creator_economy")

    assert _spec_in_disabled_module(stock, {"finance"}) is True
    assert _spec_in_disabled_module(creator, {"creator_economy"}) is True
    assert _spec_in_disabled_module(stock, {"creator_economy"}) is False
    assert _spec_in_disabled_module(core, {"finance"}) is False
    assert _spec_in_disabled_module(stock, set()) is False


def test_disabled_tool_modules_only_shrinks_menu_and_keeps_core(db):
    # Phase 2D: switching modern-worldview modules off removes every tool whose
    # catalog category belongs to a disabled module, while core tools survive.
    # (Disabling modules can free capped slots for other tools, so the menu is
    # not a strict subset; the real invariant is "no disabled-module tool left".)
    from app.tools.registry import _spec_in_disabled_module

    world, agents = make_world(db, agent_count=4)
    db.commit()
    agent = agents[0]

    disabled = {
        "finance",
        "creator_economy",
        "transportation",
        "luxury_consumption",
        "service_work",
    }
    world.settings_json = {
        **(world.settings_json or {}),
        "disabled_tool_modules": sorted(disabled),
    }
    db.flush()
    after_specs = available_tools(agent, agent.location.location, session=db)
    after = {s.tool_name for s in after_specs}

    assert all(not _spec_in_disabled_module(s, disabled) for s in after_specs)
    assert "do_nothing" in after  # core tool always survives
