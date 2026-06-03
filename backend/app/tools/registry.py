from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.v5_state import ensure_v5_agent_state, wallet_money
from app.agents.traits import trait_priority_bias, trait_value
from app.core.models import Agent, IdentityKnowledge, Inventory, Item, Location, World
from app.content.toolsets import agent_special_tool_allowed, reproduction_enabled_from_settings, survival_needs_enabled
from app.content.worldpacks import external_tool_names_for_toolset
from app.economy.v6 import V6_CORE_TOOLS, v6_candidate_names, v6_tool_allowed
from app.economy.work_schedule import can_apply_for_job, can_do_odd_job, can_start_overtime, can_start_work_shift
from app.effects.drive_system import priority_tools_from_drive
from app.simulation.difficulty import profile_for_agent
from app.social.forced_actions import FORCED_SOCIAL_ACTION_TOOL_TYPES, FORCED_SOCIAL_RESPONSE_TOOLS, FORCED_SOCIAL_TOOL_NAMES, has_pending_forced_action_from_visible
from app.social.pending_requests import SOCIAL_REQUEST_RESPONSE_TOOLS, SOCIAL_REQUEST_TOOL_NAMES, has_pending_social_request_from_visible, social_response_request_type_for_tool
from app.tools.tool_specs import REACTION_TOOL_NAMES, TOOL_SPECS, ToolSpec
from app.world.corpses import CORPSE_TOOL_NAMES, corpse_system_enabled, has_visible_corpses
from app.world.visibility import same_location_agent_ids


BASE_TOOLS = {
    "look_around",
    "observe_visible_agent",
    "check_self_status",
    "move_to_location",
    "return_home",
    "knock_private_room",
    "wander",
    "say_to_visible_agent",
    "speak_to_nearby",
    "wake_visible_agent",
    "ask_visible_agent_to_introduce",
    "introduce_self",
    "refuse_introduction",
    "ignore",
    "wave_to_visible_agent",
    "compliment_visible_agent",
    "apologize_to_visible_agent",
    "help_visible_agent",
    "move_closer_to_visible_agent",
    "walk_away_from_visible_agent",
    "offer_item_to_visible_agent",
    "rest",
    "sleep_rough",
    "seek_help",
    "add_memory",
    "call_community_meeting",
    "propose_social_rule",
    "support_social_rule",
    "oppose_social_rule",
    "do_nothing",
    "panic_pause",
    "post_notice",
    "clear_notice_board",
    "send_private_letter_by_name",
    "invite_named_agent_to_event",
    "record_relationship_note_by_name",
    "make_public_accusation_by_name",
    "nominate_named_agent",
    "promise_to_named_agent",
    "introduce_other_agent",
    "clean_current_location",
    "check_supplies",
    "eat_portable_food",
    "drink_bottled_water",
    "fill_canteen",
    "pack_lunch",
    "buy_portable_food",
    "buy_bottled_water",
    "request_food_help",
    "request_water_help",
    "accept_community_aid",
    "request_more_candidate_tools",
    "explain_available_tools",
    "do_odd_job",
    "apply_for_job",
    "work_shift_cafeteria",
    "work_shift_cook",
    "work_shift_cleaner",
    "work_shift_night_guard",
    "work_overtime_shift",
    "take_work_break",
    "complain_about_work",
    "quit_job",
    "stretch_body",
    "plan_day",
    "meditate",
    "tidy_room",
    "read_quietly",
    "practice_skill",
    "enjoy_scenery",
    "hum_to_self",
    "review_recent_memory",
    "organize_inventory",
    "write_private_note",
    "plan_next_meal",
    "clean_clothes",
    "take_short_walk",
    "sketch_or_doodle",
    "breathe_fresh_air",
    "seek_conversation",
    "casual_chat_visible_agent",
    "ask_about_needs",
    "comfort_visible_agent",
    "invite_visible_agent_to_walk",
    "ask_for_help_from_visible_agent",
    "share_food_with_visible_agent",
    "share_water_with_visible_agent",
    "grant_personal_resource_permission_visible_agent",
    "set_boundary_visible_agent",
    "thank_visible_agent",
    "discuss_feelings_visible_agent",
    "accept_social_request_visible_agent",
    "decline_social_request_visible_agent",
    "force_hug_visible_agent",
    "force_hold_hands_visible_agent",
    "force_comfort_visible_agent",
    "force_help_visible_agent",
    "force_walk_together_visible_agent",
    "force_date_visible_agent",
    "force_relationship_claim_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
    "dodge_forced_action_visible_agent",
    "allow_forced_action_visible_agent",
    "protest_forced_action_visible_agent",
    "express_affection_visible_agent",
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
    "discuss_romantic_boundaries_visible_agent",
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
    "care_for_child_visible_agent",
    "teach_child_simple_skill_visible_agent",
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
    "buy_contraception",
    "buy_pregnancy_test",
    "take_pregnancy_test",
    "attempt_petty_theft_visible_agent",
    "attempt_burglary_private_room",
    "demand_money_visible_agent",
    "home_invasion_robbery_private_room",
    "attack_visible_agent",
    "report_unknown_theft",
    "confront_visible_agent_about_crime",
    "report_known_crime_by_name",
    "forgive_visible_agent_crime",
    "jail_rest",
    "jail_low_paid_work",
    "jail_reflect",
    "jail_write_letter",
    "jail_wait_release",
    "refuse_jail_work",
}


ADULT_INTIMACY_TOOLS = {
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
}

PREGNANCY_TOOLS = {"buy_contraception", "buy_pregnancy_test", "take_pregnancy_test"}

PREGNANCY_RESTRICTED_TOOLS = {
    "work_overtime_shift",
    "attempt_jail_escape",
    "attempt_petty_theft_visible_agent",
    "attempt_burglary_private_room",
    "demand_money_visible_agent",
    "home_invasion_robbery_private_room",
    "attack_visible_agent",
    "force_walk_together_visible_agent",
    "force_date_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
}


def is_pregnant(agent: Agent | None) -> bool:
    if not agent:
        return False
    pregnancy = ((agent.family_json or {}).get("pregnancy_state") or {})
    return bool(isinstance(pregnancy, dict) and pregnancy.get("pregnant"))

ROMANCE_TOOLS = {
    "express_affection_visible_agent",
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
    "discuss_romantic_boundaries_visible_agent",
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
}

CRIME_TOOLS = {
    "attempt_petty_theft_visible_agent",
    "attempt_burglary_private_room",
    "demand_money_visible_agent",
    "home_invasion_robbery_private_room",
    "attack_visible_agent",
    "report_unknown_theft",
    "confront_visible_agent_about_crime",
    "report_known_crime_by_name",
    "forgive_visible_agent_crime",
}

JAIL_TOOLS = {"jail_rest", "jail_low_paid_work", "jail_reflect", "jail_write_letter", "jail_wait_release", "refuse_jail_work", "attempt_jail_escape"}

CRIMINAL_ACTION_TOOLS = {
    "attempt_petty_theft_visible_agent",
    "attempt_burglary_private_room",
    "demand_money_visible_agent",
    "home_invasion_robbery_private_room",
    "attack_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
    "attempt_jail_escape",
}

CHILD_CARE_TOOLS = {
    "check_child_status_visible_agent",
    "soothe_child_visible_agent",
    "feed_child_visible_agent",
    "carry_child_visible_agent",
    "put_child_to_sleep_visible_agent",
    "care_for_child_visible_agent",
    "teach_child_simple_skill_visible_agent",
}
REPRODUCTION_TOOL_NAMES = ADULT_INTIMACY_TOOLS | PREGNANCY_TOOLS | CHILD_CARE_TOOLS

SURVIVAL_NEED_TOOL_NAMES = {
    "eat_food",
    "drink_water",
    "check_supplies",
    "eat_portable_food",
    "drink_bottled_water",
    "fill_canteen",
    "pack_lunch",
    "buy_portable_food",
    "buy_bottled_water",
    "request_food_help",
    "request_water_help",
    "accept_community_aid",
}

CHILD_STAGE_TOOLS = {
    "newborn": {"cry_for_food", "cry_for_comfort", "child_sleep", "be_carried", "signal_need", "observe_parent", "request_more_candidate_tools", "explain_available_tools"},
    "infant": {"cry_for_food", "cry_for_comfort", "child_sleep", "be_carried", "observe_parent", "reach_item", "signal_need", "request_more_candidate_tools"},
    "toddler": {"cry_for_comfort", "child_sleep", "observe_parent", "signal_need", "ask_help_child", "follow_guardian", "learn_simple_words", "request_more_candidate_tools"},
    "child": {
        "cry_for_comfort",
        "child_sleep",
        "observe_parent",
        "signal_need",
        "ask_help_child",
        "follow_guardian",
        "learn_simple_words",
        "practice_child_tool",
        "look_around",
        "check_self_status",
        "eat_food",
        "drink_water",
        "say_to_visible_agent",
        "speak_to_nearby",
        "play_simple_game",
        "read_quietly",
        "practice_skill",
        "request_more_candidate_tools",
        "explain_available_tools",
    },
}


def get_tool(tool_name: str) -> ToolSpec | None:
    return TOOL_SPECS.get(tool_name)


def reproduction_toolset_enabled(world: World | None) -> bool:
    return reproduction_enabled_from_settings(world)


def catalog_reproduction_related(spec: ToolSpec) -> bool:
    text = f"{spec.tool_name} {spec.display_name} {spec.catalog_category or ''} {spec.effect_summary or ''}".lower()
    precise_tokens = [
        "adult_intimacy",
        "sexual",
        "sex",
        "性行为",
        "成年亲密",
        "避孕",
        "pregnancy",
        "怀孕",
        "pregnant",
        "birth",
        "生育",
        "生产",
        "生子",
        "分娩",
        "育儿",
        "baby",
        "婴儿",
    ]
    return any(token in text for token in precise_tokens)


def catalog_survival_need_related(spec: ToolSpec) -> bool:
    text = f"{spec.tool_name} {spec.display_name} {spec.catalog_category or ''} {spec.effect_summary or ''}".lower()
    return spec.tool_name in SURVIVAL_NEED_TOOL_NAMES or any(
        token in text
        for token in ["hunger", "thirst", "satiety", "hydration", "饥", "饿", "口渴", "喝水", "饮水", "吃饭", "食物", "补给"]
    )


def available_tools(agent: Agent, location: Location | None, *, reaction: bool = False, session: Session | None = None) -> list[ToolSpec]:
    if agent.lifecycle_state == "dead":
        return []
    if not location:
        return [TOOL_SPECS["do_nothing"]]
    ensure_v5_agent_state(agent)
    world = session.get(World, agent.world_id) if session else None
    core_toolset_enabled = bool((world.settings_json or {}).get("core_toolset_enabled", True)) if world else True
    reproduction_enabled = reproduction_toolset_enabled(world)
    survival_enabled = survival_needs_enabled(world)
    jailed = bool((agent.law_json or {}).get("jailed"))
    location_tool_names = set(location.available_tools_json or [])
    context_mode = str((agent.tool_learning_json or {}).get("tool_context_mode") or "dynamic")
    if context_mode == "all":
        names = _all_candidate_names_for_enabled_toolsets(
            agent=agent,
            location_tool_names=location_tool_names,
            core_toolset_enabled=core_toolset_enabled,
            jailed=jailed,
            world_toolset_id=(world.settings_json or {}).get("world_toolset_id") if world else None,
        )
    else:
        if agent.age_stage in {"newborn", "infant", "toddler"}:
            names = set(CHILD_STAGE_TOOLS[agent.age_stage]) if core_toolset_enabled else set(location_tool_names)
        elif agent.age_stage == "child":
            names = (set(CHILD_STAGE_TOOLS["child"]) if core_toolset_enabled else set()) | location_tool_names
        elif jailed:
            jail_core_names = {"check_self_status", "add_memory", "write_private_note", "meditate", "breathe_fresh_air"} if core_toolset_enabled else set()
            names = set(JAIL_TOOLS) | jail_core_names | location_tool_names
        else:
            names = (set(BASE_TOOLS) if core_toolset_enabled else set()) | location_tool_names
    if agent.age_stage not in {"newborn", "infant", "toddler"}:
        names |= {"post_notice", "clear_notice_board", "clean_current_location"}
    tags = set(location.tags_json or [])
    specs: list[ToolSpec] = []
    has_visible = bool(session and same_location_agent_ids(session, agent))
    has_known_names = bool(
        session
        and session.execute(
            select(IdentityKnowledge).where(IdentityKnowledge.observer_agent_id == agent.agent_id, IdentityKnowledge.name_known.is_(True))
        ).first()
    )
    if context_mode != "all":
        names |= _v5_catalog_candidate_names(session, agent, location, has_visible=has_visible, has_known_names=has_known_names)
    if session:
        names |= v6_candidate_names(session, agent, location)
        if world:
            names |= external_tool_names_for_toolset((world.settings_json or {}).get("world_toolset_id")) & location_tool_names
        if world and corpse_system_enabled(world) and has_visible_corpses(session, world, agent):
            names |= CORPSE_TOOL_NAMES
        if world and has_pending_social_request_from_visible(session, agent, world.current_world_time_minutes):
            names |= SOCIAL_REQUEST_RESPONSE_TOOLS
        if world and has_pending_forced_action_from_visible(session, agent, world.current_world_time_minutes):
            names |= FORCED_SOCIAL_RESPONSE_TOOLS
    for name in sorted(names):
        spec = TOOL_SPECS.get(name)
        if not spec:
            continue
        if reaction and spec.tool_name not in REACTION_TOOL_NAMES:
            continue
        if not survival_enabled and catalog_survival_need_related(spec):
            continue
        if not agent_special_tool_allowed(agent.tool_learning_json, spec.tool_name):
            continue
        if is_pregnant(agent) and spec.tool_name in PREGNANCY_RESTRICTED_TOOLS:
            continue
        if not reproduction_enabled and (spec.tool_name in REPRODUCTION_TOOL_NAMES or (spec.hard_effect_id.endswith("catalog_generic") and catalog_reproduction_related(spec))):
            continue
        if agent.lifecycle_state not in spec.allowed_lifecycle_states:
            continue
        if spec.target_policy == "visible_ref" and session and not has_visible:
            continue
        if spec.target_policy == "known_name" and session and not has_known_names:
            continue
        if spec.required_location_tags and not any(tag in tags for tag in spec.required_location_tags):
            continue
        if session and not _passes_v5_gates(session, agent, spec, has_visible=has_visible):
            continue
        specs.append(spec)
    if agent.age_stage not in {"newborn", "infant", "toddler"} and TOOL_SPECS["do_nothing"] not in specs:
        specs.append(TOOL_SPECS["do_nothing"])
    prioritized = _prioritize_tools(agent, specs, world=world)
    if context_mode != "all" and agent.age_stage == "adult" and len(prioritized) > 80:
        return _cap_dynamic_tool_specs(agent, prioritized, limit=80, world=world)
    return prioritized


def _all_candidate_names_for_enabled_toolsets(
    *,
    agent: Agent,
    location_tool_names: set[str],
    core_toolset_enabled: bool,
    jailed: bool,
    world_toolset_id: str | None = None,
) -> set[str]:
    names = set(location_tool_names)
    if agent.age_stage in {"newborn", "infant", "toddler"}:
        return names | (set(CHILD_STAGE_TOOLS[agent.age_stage]) if core_toolset_enabled else set())
    if agent.age_stage == "child":
        return names | (set(CHILD_STAGE_TOOLS["child"]) if core_toolset_enabled else set())
    if jailed:
        jail_core_names = {"check_self_status", "add_memory", "write_private_note", "meditate", "breathe_fresh_air"} if core_toolset_enabled else set()
        return names | set(JAIL_TOOLS) | jail_core_names
    if core_toolset_enabled:
        names |= BASE_TOOLS
    for spec in TOOL_SPECS.values():
        if spec.hard_effect_id == "v5_catalog_generic":
            names.add(spec.tool_name)
    names |= V6_CORE_TOOLS
    names |= external_tool_names_for_toolset(world_toolset_id)
    return names


def _passes_v5_gates(session: Session, agent: Agent, spec: ToolSpec, *, has_visible: bool) -> bool:
    world = session.get(World, agent.world_id)
    reproduction_enabled = reproduction_toolset_enabled(world)
    if not agent_special_tool_allowed(agent.tool_learning_json, spec.tool_name):
        return False
    if not survival_needs_enabled(world) and catalog_survival_need_related(spec):
        return False
    if not reproduction_enabled and (spec.tool_name in REPRODUCTION_TOOL_NAMES or (spec.hard_effect_id.endswith("catalog_generic") and catalog_reproduction_related(spec))):
        return False
    if is_pregnant(agent) and spec.tool_name in PREGNANCY_RESTRICTED_TOOLS:
        return False
    jailed = bool((agent.law_json or {}).get("jailed"))
    if spec.tool_name.startswith("v6_"):
        return v6_tool_allowed(session, agent, spec.tool_name)
    if spec.hard_effect_id == "worldpack_declarative":
        from app.effects.worldpack_effects import validate_worldpack_declarative_tool

        ok, _reason, _message = validate_worldpack_declarative_tool(agent, spec, {})
        return ok
    if spec.tool_name in CORPSE_TOOL_NAMES:
        return bool(world and corpse_system_enabled(world) and has_visible_corpses(session, world, agent))
    if jailed and spec.tool_name not in JAIL_TOOLS | {"check_self_status", "add_memory", "write_private_note", "meditate", "breathe_fresh_air"}:
        return False
    if not jailed and spec.tool_name in JAIL_TOOLS:
        return False
    if spec.tool_name in ADULT_INTIMACY_TOOLS | PREGNANCY_TOOLS and agent.age_stage != "adult":
        return False
    if spec.tool_name == "attempt_forced_adult_boundary_visible_agent" and agent.age_stage != "adult":
        return False
    if spec.tool_name in {"accept_adult_intimacy_visible_agent", "decline_adult_intimacy_visible_agent"} and not _has_pending_intimacy_request_from_visible(session, agent):
        return False
    if spec.tool_name in SOCIAL_REQUEST_RESPONSE_TOOLS:
        request_type = social_response_request_type_for_tool(spec.tool_name)
        if not has_pending_social_request_from_visible(session, agent, world.current_world_time_minutes if world else 0, request_type=request_type):
            return False
    if spec.tool_name in FORCED_SOCIAL_RESPONSE_TOOLS:
        if not has_pending_forced_action_from_visible(session, agent, world.current_world_time_minutes if world else 0):
            return False
    if spec.tool_name in ROMANCE_TOOLS | ADULT_INTIMACY_TOOLS | SOCIAL_REQUEST_TOOL_NAMES | FORCED_SOCIAL_TOOL_NAMES and not has_visible:
        return False
    if spec.tool_name in CHILD_CARE_TOOLS and not _has_visible_child(session, agent):
        return False
    if spec.tool_name in {"follow_guardian"} and not _has_visible_guardian(session, agent):
        return False
    if spec.tool_name == "return_home":
        home_id = _home_location_id(agent)
        return bool(home_id and (not agent.location or agent.location.location_id != home_id))
    if spec.tool_name == "sleep_rough":
        world = session.get(World, agent.world_id)
        location = agent.location.location if agent.location else None
        tags = set(location.tags_json or []) if location else set()
        if "home" in tags or "jail" in tags:
            return False
        minute = (world.current_world_time_minutes if world else 0) % 1440
        night_or_late = minute >= 20 * 60 or minute < 7 * 60
        desires = agent.desires_json or {}
        raw_awake = desires.get("awake_since_world_time")
        if raw_awake is None:
            raw_awake = agent.created_at_world_time if agent.created_at_world_time is not None else (world.current_world_time_minutes if world else 0)
        try:
            awake_since = int(raw_awake)
        except (TypeError, ValueError):
            awake_since = world.current_world_time_minutes if world else 0
        awake_minutes = max(0, (world.current_world_time_minutes if world else 0) - awake_since)
        housing = (agent.wallet_json or {}).get("housing") or {}
        homeless_or_no_home = bool(housing.get("homeless")) or not housing.get("home_location_id")
        tired = bool(agent.dynamic_state and agent.dynamic_state.energy <= 42) or awake_minutes >= 16 * 60
        return bool(homeless_or_no_home or night_or_late or tired)
    if spec.tool_name in CRIME_TOOLS and agent.age_stage != "adult":
        return False
    if spec.tool_name == "attempt_forced_adult_boundary_visible_agent":
        state = agent.dynamic_state
        morality = agent.morality_json or {}
        desire = int(morality.get("desire_for_reward", 45))
        boundary = int(morality.get("boundary_respect", 70))
        aggression = agent.traits.aggression if agent.traits else 20
        stress = state.stress if state else 0
        if not (aggression >= 82 or stress >= 88 or (desire >= 75 and boundary <= 35)):
            return False
    if spec.tool_name in {"attempt_petty_theft_visible_agent", "demand_money_visible_agent", "attack_visible_agent", "confront_visible_agent_about_crime", "forgive_visible_agent_crime"} and not has_visible:
        return False
    if spec.tool_name in CRIMINAL_ACTION_TOOLS and not _criminal_temperament_allows(agent, spec.tool_name):
        return False
    if spec.tool_name == "attempt_petty_theft_visible_agent" and not _crime_pressure(agent, minimum=35):
        return False
    if spec.tool_name == "attempt_burglary_private_room" and not _crime_pressure(agent, minimum=35):
        return False
    if spec.tool_name == "demand_money_visible_agent" and not _crime_pressure(agent, minimum=55):
        return False
    if spec.tool_name == "home_invasion_robbery_private_room" and not _crime_pressure(agent, minimum=50):
        return False
    if spec.tool_name == "attack_visible_agent" and not (agent.traits and (agent.traits.aggression >= 75 or agent.dynamic_state.stress >= 80)):
        return False
    if spec.tool_name == "report_unknown_theft" and not _has_victim_loss(agent):
        return False
    if spec.tool_name == "report_known_crime_by_name" and not _has_victim_record_with_actor(agent):
        return False
    food_price = int(profile_for_agent(agent)["food_price"])
    if spec.tool_name in {"eat_food", "pack_lunch"}:
        return wallet_money(agent) >= food_price
    if spec.tool_name == "eat_portable_food":
        return _inventory_quantity(session, agent.agent_id, "便携食物") > 0
    if spec.tool_name == "drink_bottled_water":
        return _inventory_quantity(session, agent.agent_id, "瓶装水") + _inventory_quantity(session, agent.agent_id, "水壶") > 0
    if spec.tool_name in {"share_food_with_visible_agent"}:
        return _inventory_quantity(session, agent.agent_id, "便携食物") > 0
    if spec.tool_name in {"share_water_with_visible_agent"}:
        return _inventory_quantity(session, agent.agent_id, "瓶装水") + _inventory_quantity(session, agent.agent_id, "水壶") > 0
    if spec.tool_name == "buy_portable_food":
        return wallet_money(agent) >= food_price
    if spec.tool_name == "buy_contraception":
        return wallet_money(agent) >= 12
    if spec.tool_name == "buy_pregnancy_test":
        return wallet_money(agent) >= 10
    if spec.tool_name == "take_pregnancy_test":
        return _inventory_quantity(session, agent.agent_id, "怀孕检测") > 0
    if spec.tool_name == "apply_for_job":
        world = session.get(World, agent.world_id)
        ok, _reason = can_apply_for_job(world, agent, agent.location.location if agent.location else None, world.current_world_time_minutes if world else 0) if world else (False, "")
        return ok
    if spec.tool_name == "do_odd_job":
        world = session.get(World, agent.world_id)
        ok, _reason = can_do_odd_job(world, agent, agent.location.location if agent.location else None, world.current_world_time_minutes if world else 0) if world else (False, "")
        return ok
    if spec.tool_name in {"work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner", "work_shift_night_guard"}:
        world = session.get(World, agent.world_id)
        ok, _reason, _role, _window, _duration = can_start_work_shift(world, agent, agent.location.location if agent.location else None, spec.tool_name, world.current_world_time_minutes if world else 0) if world else (False, "", None, None, 0)
        return ok
    if spec.tool_name == "work_overtime_shift":
        world = session.get(World, agent.world_id)
        ok, _reason = can_start_overtime(world, agent, agent.location.location if agent.location else None, world.current_world_time_minutes if world else 0) if world else (False, "")
        state = agent.dynamic_state
        return bool(
            ok
            and state
            and state.energy >= 38
            and state.hydration >= 38
            and state.satiety >= 38
            and int((agent.work_json or {}).get("burnout", 0)) < 85
        )
    if spec.tool_name == "quit_job":
        return bool((agent.work_json or {}).get("employed"))
    return True


def _v5_catalog_candidate_names(session: Session | None, agent: Agent, location: Location, *, has_visible: bool, has_known_names: bool) -> set[str]:
    state = agent.dynamic_state
    tags = set(location.tags_json or [])
    selected: list[str] = []
    for spec in TOOL_SPECS.values():
        if spec.hard_effect_id != "v5_catalog_generic":
            continue
        category = spec.catalog_category or ""
        tool_id = spec.tool_name
        text = f"{tool_id} {spec.display_name} {category} {spec.effect_summary or ''}"
        if spec.target_policy == "visible_ref" and not has_visible:
            continue
        if spec.target_policy == "known_name" and not has_known_names:
            continue
        if agent.age_stage != "adult" and ("adult" in tool_id or "成年" in text or "亲密" in text):
            continue
        if "crime" in tool_id or "犯罪" in category:
            if not state or state.stress < 70:
                continue
        if "jail" in tool_id or "监狱" in category:
            if not (agent.law_json or {}).get("jailed"):
                continue
        if any(token in category for token in ["生存", "身体", "感知", "认知"]):
            selected.append(tool_id)
        elif any(token in category for token in ["社交", "情绪", "关系"]):
            if has_visible or state and (state.social < 45 or state.fun < 45):
                selected.append(tool_id)
        elif any(token in category for token in ["物品", "背包", "货币", "工作", "市场"]):
            if "trade" in tags or "work" in tags or "food" in tags or wallet_money(agent) < 20:
                selected.append(tool_id)
        elif any(token in category for token in ["儿童", "成长"]):
            if session and _has_visible_child(session, agent):
                selected.append(tool_id)
        elif len(selected) < 18:
            selected.append(tool_id)
        if len(selected) >= 32:
            break
    return set(selected)


def _crime_pressure(agent: Agent, *, minimum: int) -> bool:
    desires = agent.desires_json or {}
    morality = agent.morality_json or {}
    state = agent.dynamic_state
    pressure = int(desires.get("survival_pressure", 0))
    if wallet_money(agent) < 8:
        pressure += 25
    if state and (state.satiety < 35 or state.hydration < 35):
        pressure += 20
    if agent.traits:
        pressure += max(0, agent.traits.aggression - 50) // 2
    pressure += max(0, int(morality.get("desire_for_reward", 45)) - 60)
    pressure -= max(0, int(morality.get("guilt_sensitivity", 55)) - 50) // 2
    return pressure >= minimum


def _criminal_temperament_allows(agent: Agent, tool_name: str) -> bool:
    state = agent.dynamic_state
    aggression = trait_value(agent, "aggression", 50)
    honesty = trait_value(agent, "honesty", 50)
    caution = trait_value(agent, "caution", 50)
    stress = int(state.stress) if state else 0
    desperate = _crime_pressure(agent, minimum=60)
    if tool_name in {"attack_visible_agent", "attempt_forced_adult_boundary_visible_agent", "home_invasion_robbery_private_room"}:
        return aggression >= 72 or stress >= 88 or (honesty <= 25 and caution <= 35 and desperate)
    if tool_name in {"demand_money_visible_agent", "attempt_jail_escape"}:
        return aggression >= 66 or stress >= 82 or (honesty <= 32 and desperate)
    return aggression >= 58 or stress >= 76 or honesty <= 35 or (caution <= 30 and desperate)


def _has_pending_intimacy_request_from_visible(session: Session, agent: Agent) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    for request in (agent.family_json or {}).get("pending_intimacy_requests", []):
        if request.get("from_agent_id") in visible_ids and request.get("status") == "pending":
            return True
    return False


def _has_visible_child(session: Session, agent: Agent) -> bool:
    for target_id in same_location_agent_ids(session, agent):
        target = session.get(Agent, target_id)
        if target and target.age_stage in {"newborn", "infant", "toddler", "child"}:
            return True
    return False


def _has_visible_guardian(session: Session, agent: Agent) -> bool:
    guardians = set((agent.family_json or {}).get("guardian_agent_ids") or [])
    return any(target_id in guardians for target_id in same_location_agent_ids(session, agent))


def _has_victim_loss(agent: Agent) -> bool:
    return any(record.get("kind") in {"loss_only", "unknown_theft"} for record in (agent.law_json or {}).get("victim_records", []))


def _has_victim_record_with_actor(agent: Agent) -> bool:
    return any(record.get("actor_agent_id") for record in (agent.law_json or {}).get("victim_records", []))


def _inventory_quantity(session: Session, agent_id: str, item_name: str) -> int:
    rows = session.execute(
        select(Inventory)
        .join(Item, Item.item_id == Inventory.item_id)
        .where(Inventory.agent_id == agent_id, Item.name == item_name)
    ).scalars()
    return sum(inv.quantity for inv in rows)


def _home_location_id(agent: Agent) -> str | None:
    return ((agent.wallet_json or {}).get("housing") or {}).get("home_location_id")


def _prioritize_tools(agent: Agent, specs: list[ToolSpec], *, world: World | None = None) -> list[ToolSpec]:
    state = agent.dynamic_state
    urgent_names = set(priority_tools_from_drive(agent))
    if state:
        profile = profile_for_agent(agent)
        if state.hydration < float(profile["urgent_hydration"]):
            urgent_names.update({"drink_water", "drink_bottled_water", "fill_canteen", "buy_bottled_water", "request_water_help", "accept_community_aid"})
        if state.satiety < float(profile["urgent_satiety"]):
            urgent_names.update({"eat_food", "eat_portable_food", "pack_lunch", "buy_portable_food", "request_food_help", "accept_community_aid"})
        if state.energy < float(profile["urgent_energy"]):
            urgent_names.update({"return_home", "sleep", "sleep_rough", "rest", "take_work_break"})
        if world:
            minute = world.current_world_time_minutes % 1440
            if minute >= 21 * 60 or minute < 6 * 60:
                urgent_names.update({"return_home", "sleep", "sleep_rough"})
        wallet = agent.wallet_json or {}
        housing = wallet.get("housing") or {}
        current_day = (world.current_world_time_minutes // 1440 + 1) if world else 1
        rent_pressure = (
            bool(housing.get("rent_per_10_days"))
            and wallet_money(agent) < int(housing.get("rent_per_10_days") or 0)
            and int(housing.get("next_rent_due_day") or 99) - current_day <= 2
        )
        money_pressure = wallet_money(agent) < 18 or rent_pressure
        if money_pressure:
            urgent_names.update({"apply_for_job", "do_odd_job", "work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner", "work_shift_night_guard"})
            urgent_names.update({"attempt_burglary_private_room", "attempt_petty_theft_visible_agent"})
            if agent.traits and (agent.traits.aggression >= 70 or state.stress >= 70):
                urgent_names.update({"home_invasion_robbery_private_room", "demand_money_visible_agent"})
        if money_pressure and world:
            minute = world.current_world_time_minutes % 1440
            if minute >= 18 * 60 or minute < 5 * 60:
                urgent_names.add("work_overtime_shift")
        if state.fun < 35:
            urgent_names.update({"hum_to_self", "read_quietly", "practice_skill", "enjoy_scenery", "sketch_or_doodle", "take_short_walk", "play_simple_game"})
        if bool((agent.law_json or {}).get("jailed")):
            urgent_names.update({"jail_rest", "jail_reflect", "jail_wait_release"})
        if (agent.family_json or {}).get("pending_forced_social_actions"):
            urgent_names.update(FORCED_SOCIAL_RESPONSE_TOOLS)
        if world:
            urgent_names.update({"inspect_visible_corpse", "mourn_visible_corpse", "report_visible_corpse", "avoid_corpse_area", "bury_visible_corpse"})
        if world and _recent_social_instability(world, agent):
            urgent_names.update({"call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule"})
    return sorted(specs, key=lambda spec: (0 if spec.tool_name in urgent_names else 1, trait_priority_bias(agent.traits, spec.tool_name), spec.tool_name))


def _cap_dynamic_tool_specs(agent: Agent, specs: list[ToolSpec], *, limit: int, world: World | None) -> list[ToolSpec]:
    if len(specs) <= limit:
        return specs
    selected: list[ToolSpec] = []
    seen: set[str] = set()

    def add_matching(predicate, quota: int) -> None:
        for spec in specs:
            if len(selected) >= limit or quota <= 0:
                return
            if spec.tool_name in seen or not predicate(spec):
                continue
            selected.append(spec)
            seen.add(spec.tool_name)
            quota -= 1

    add_matching(lambda spec: spec.tool_name in {"do_nothing", "check_self_status", "look_around"}, 3)
    add_matching(lambda spec: spec.tool_name in set(priority_tools_from_drive(agent)), 10)
    if trait_value(agent, "aggression", 50) >= 65 or (agent.dynamic_state and agent.dynamic_state.stress >= 75):
        add_matching(lambda spec: spec.tool_name in CRIMINAL_ACTION_TOOLS or any(token in spec.tool_name for token in ["force_", "confront", "protest"]), 10)
    if trait_value(agent, "sociability", 50) >= 62 or trait_value(agent, "empathy", 50) >= 62:
        add_matching(lambda spec: spec.target_policy == "visible_ref" and any(token in spec.tool_name for token in ["chat", "help", "comfort", "thank", "ask_", "invite", "share", "relationship"]), 12)
    if trait_value(agent, "creativity", 50) >= 62 or trait_value(agent, "curiosity", 50) >= 62:
        add_matching(lambda spec: any(token in spec.tool_name for token in ["write", "story", "sing", "read", "practice", "sketch", "research", "observe", "look"]), 10)
    if trait_value(agent, "discipline", 50) >= 62:
        add_matching(lambda spec: any(token in spec.tool_name for token in ["work", "sleep", "wash", "clean", "plan", "repay", "budget"]), 10)
    if world and _recent_social_instability(world, agent):
        add_matching(lambda spec: spec.tool_name in {"call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule", "report_unknown_theft", "report_known_crime_by_name"}, 8)
    add_matching(lambda _spec: True, limit - len(selected))
    return selected


def _recent_social_instability(world: World, agent: Agent) -> bool:
    # 轻量启发式：世界近期出现死亡/受害记录/流浪时，把治理类工具排前面；不硬性要求 agent 使用。
    if agent.dynamic_state and (agent.dynamic_state.stress >= 65 or agent.dynamic_state.social < 35):
        return True
    law = agent.law_json or {}
    if law.get("victim_records") or law.get("criminal_records"):
        return True
    housing = (agent.wallet_json or {}).get("housing") or {}
    if housing.get("homeless"):
        return True
    return False


def format_tools_for_prompt(specs: list[ToolSpec]) -> str:
    """Legacy debug formatter kept for API compatibility.

    Runtime prompts use AOHP action options, not raw tool schemas. This formatter avoids
    object-shaped examples so it cannot reintroduce JSON-style action output.
    """
    lines = []
    for spec in specs:
        hint = _text_hint(spec)
        lines.append(f"- {spec.tool_name}: {spec.description_for_llm}; {hint}; time={spec.time_cost_minutes}分钟")
    return "\n".join(lines)


def _text_hint(spec: ToolSpec) -> str:
    if spec.target_policy == "visible_ref":
        return "目标由 AOHP 行动编号绑定；需要说话时写在行动头下一行正文"
    if spec.target_policy == "known_name":
        return "姓名由 AOHP 行动编号绑定；不可临时编造"
    if spec.target_policy == "location":
        return "地点由 AOHP 行动编号绑定"
    if spec.target_policy == "item":
        return "物品由 AOHP 行动编号绑定"
    if spec.tool_name in {"sleep", "sleep_rough"}:
        return "需要小时数时写在行动头内，例如 [08:8]"
    if spec.tool_name in {"call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule", "write_diary", "post_notice", "add_memory"}:
        return "需要文字时写在行动头下一行正文"
    if spec.tool_name in CORPSE_TOOL_NAMES:
        return "尸体目标由 AOHP 行动编号绑定"
    if spec.tool_name in {"v6_deposit_to_broker", "v6_withdraw_from_broker"}:
        return "金额由 AOHP 行动编号或行动头数值绑定"
    if spec.tool_name in {"v6_place_market_buy_order", "v6_place_market_sell_order", "v6_short_sell_stock", "v6_buy_to_cover_short"}:
        return "股票标的由 AOHP 行动编号绑定"
    return "无额外正文或数值字段"
