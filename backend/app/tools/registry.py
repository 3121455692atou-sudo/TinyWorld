from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.v5_state import ensure_v5_agent_state, wallet_money
from app.agents.traits import trait_priority_bias, trait_value
from app.core.models import Agent, IdentityKnowledge, Inventory, Item, Location, Relationship, World
from app.content.toolsets import agent_special_tool_allowed, modern_life_enabled, reproduction_enabled_from_settings, survival_needs_enabled
from app.content.worldpacks import external_tool_names_for_toolset
from app.economy.v6 import V6_CORE_TOOLS, v6_candidate_names, v6_tool_allowed
from app.economy.work_schedule import active_work_status, can_apply_for_job, can_do_odd_job, can_start_overtime, can_start_work_shift, work_blocks_tool
from app.effects.drive_system import priority_tools_from_drive
from app.simulation.difficulty import profile_for_agent
from app.social.forced_actions import FORCED_SOCIAL_ACTION_TOOL_TYPES, FORCED_SOCIAL_RESPONSE_TOOLS, FORCED_SOCIAL_TOOL_NAMES, has_pending_forced_action_from_visible
from app.social.infidelity_responses import INFIDELITY_RESPONSE_TOOL_NAMES, has_pending_infidelity_response_from_visible
from app.social.pending_requests import SOCIAL_REQUEST_RESPONSE_TOOLS, SOCIAL_REQUEST_TOOL_NAMES, has_pending_social_request_from_visible, social_response_request_type_for_tool
from app.social.relationship_stage import (
    NEGATIVE_RELATIONSHIP_TOOL_NAMES,
    PARTNER_FAMILY_PLANNING_TOOL_NAMES,
    RELATIONSHIP_STAGE_TOOL_NAMES,
    relationship_menu_context,
    relationship_tool_allowed_for_target,
)
from app.tools.tool_specs import REACTION_TOOL_NAMES, SOFT_EXPRESSION_CORE_TOOL_IDS, TOOL_SPECS, ToolSpec
from app.world.corpses import CORPSE_TOOL_NAMES, corpse_system_enabled, has_visible_corpses
from app.world.werewolf import WEREWOLF_TOOL_NAMES, werewolf_enabled, werewolf_menu_tool_names, werewolf_phase, werewolf_tool_allowed, werewolf_tool_menu_allowed, werewolf_vending_market_tool_allowed
from app.world.visibility import same_location_agent_ids

logger = logging.getLogger(__name__)

DISABLED_GROUP_CHAT_TOOLS = {"tool_group_start_chat", "tool_group_join_chat", "tool_group_leave_chat"}

NON_MODERN_BLOCKED_LIVELIHOOD_TOOLS = {
    "market_search_goods",
    "market_recommend_goods",
    "market_buy_goods",
    "place_inventory_item",
    "pick_up_placed_item",
    "transfer_item_to_visible_agent",
    "gift_item_to_visible_agent",
    "buy_portable_food",
    "buy_bottled_water",
    "apply_for_job",
    "do_odd_job",
    "work_shift_cafeteria",
    "work_shift_cook",
    "work_shift_cleaner",
    "work_shift_night_guard",
    "work_overtime_shift",
    "take_work_break",
    "complain_about_work",
    "quit_job",
    "jail_low_paid_work",
}


def _blocked_in_non_modern_life_world(world: World | None, tool_name: str, location: Location | None = None) -> bool:
    """Modern-world livelihood/economy tools must not leak into other worldviews."""
    if not world or modern_life_enabled(world):
        return False
    name = str(tool_name or "")
    if name == "eat_inventory_food":
        return False
    if werewolf_vending_market_tool_allowed(world, location, name):
        return False
    return name in NON_MODERN_BLOCKED_LIVELIHOOD_TOOLS or name.startswith(("market_", "tool_market_", "tool_work_", "v6_"))


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
    "transfer_item_to_visible_agent",
    "gift_item_to_visible_agent",
    "eat_inventory_food",
    "place_inventory_item",
    "pick_up_placed_item",
    "rest",
    "sleep_rough",
    "seek_help",
    "medical_checkup",
    "buy_nutrition_infusion",
    "free_medical_wash",
    "treat_visible_agent_medical",
    "feed_visible_agent_meal",
    "escort_visible_agent_to_medical",
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
    "express_dislike_visible_agent",
    "criticize_behavior_visible_agent",
    "reject_closeness_visible_agent",
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
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
    "check_child_status_visible_agent",
    "soothe_child_visible_agent",
    "feed_child_visible_agent",
    "carry_child_visible_agent",
    "put_child_to_sleep_visible_agent",
    "care_for_child_visible_agent",
    "teach_child_simple_skill_visible_agent",
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
    "react_infidelity_angry_visible_agent",
    "react_infidelity_forgive_visible_agent",
    "react_infidelity_excited_visible_agent",
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


# Tools listed here remain in TOOL_SPECS for archive/backward compatibility, but they
# should not be offered to agents nor executed from free-form tool names. They are
# either system/meta controls, or old generic catalog duplicates whose names imply
# concrete state changes while the current generic handler only produces an abstract
# event. Concrete hard-coded tools such as move_to_location/return_home/knock_private_room
# are used instead.
AGENT_FACING_DISABLED_TOOL_NAMES = {
    "request_more_candidate_tools",
    "explain_available_tools",
    "tool_meta_request_more_candidates",
    "tool_meta_explain_available_tools",
    "tool_meta_focus_survival",
    "tool_meta_focus_romance",
    "tool_meta_focus_parenting",
    "tool_meta_focus_work",
    "tool_meta_focus_social",
    "tool_meta_focus_learning",
    "tool_move_to_location",
    "tool_location_enter_room",
    "tool_location_leave_room",
    "tool_location_knock_door",
    "tool_location_open_door",
    "tool_location_close_door",
    "tool_move_wander",
    "tool_move_flee_location",
} | set(SOFT_EXPRESSION_CORE_TOOL_IDS)

SOFT_EXPRESSION_REDIRECT_MESSAGE = (
    "这个工具只是表达情绪、喜好、态度或寒暄的旧式细分项。"
    "请改用“说一句话 / 向附近说话 / 写私人笔记 / 记录记忆”，把具体情绪和意图直接写在台词或正文里。"
)


def is_agent_facing_disabled_tool(tool_name: str | None) -> bool:
    name = str(tool_name or "")
    return (
        name in AGENT_FACING_DISABLED_TOOL_NAMES
        or name.startswith("system_")
        or name.startswith("tool_meta_")
        or name.startswith("system_filter_")
        or name.startswith("v6_system_")
    )


ADULT_INTIMACY_TOOLS = {
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
}

CORE_RELATIONSHIP_CONTEXT_TOOLS = {
    "express_affection_visible_agent",
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
}

NEGATIVE_RELATIONSHIP_CONTEXT_TOOLS = set(NEGATIVE_RELATIONSHIP_TOOL_NAMES)

CORE_NEED_HELP_TOOLS = {"request_food_help", "request_water_help", "accept_community_aid"}

PREGNANCY_TOOLS = {"buy_contraception", "buy_pregnancy_test", "take_pregnancy_test"}

# Keep ordinary survival/life actions available during pregnancy, but do not expose
# extreme-risk actions that are implausible to treat as normal routine choices.
PREGNANCY_RESTRICTED_TOOLS: set[str] = {
    "work_overtime_shift",
    "attempt_petty_theft_visible_agent",
    "attempt_burglary_private_room",
    "demand_money_visible_agent",
    "home_invasion_robbery_private_room",
    "attack_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
    "attempt_jail_escape",
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
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
}

INFIDELITY_RESPONSE_TOOLS = set(INFIDELITY_RESPONSE_TOOL_NAMES)

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

PRIVATE_ROOM_ENTRY_TOOLS = {
    "knock_private_room",
    "attempt_burglary_private_room",
    "home_invasion_robbery_private_room",
}

MARKET_ACTION_TOOLS = {
    "market_search_goods",
    "market_recommend_goods",
    "market_buy_goods",
    "eat_inventory_food",
    "place_inventory_item",
    "pick_up_placed_item",
    "transfer_item_to_visible_agent",
    "gift_item_to_visible_agent",
}

WEREWOLF_TOOL_NAMES = set(WEREWOLF_TOOL_NAMES)

CHILD_CARE_TOOLS = {
    "check_child_status_visible_agent",
    "soothe_child_visible_agent",
    "feed_child_visible_agent",
    "carry_child_visible_agent",
    "put_child_to_sleep_visible_agent",
    "care_for_child_visible_agent",
    "teach_child_simple_skill_visible_agent",
}
# Reproduction setup tools are gated by the reproduction toggle. Child-care tools are deliberately
# kept separate: an existing child/newborn must remain careable even in worlds where new conception
# is disabled, or imported/test worlds can strand babies with no valid care actions.
REPRODUCTION_SETUP_TOOL_NAMES = ADULT_INTIMACY_TOOLS | PREGNANCY_TOOLS
REPRODUCTION_TOOL_NAMES = REPRODUCTION_SETUP_TOOL_NAMES | CHILD_CARE_TOOLS

SURVIVAL_NEED_TOOL_NAMES = {
    "eat_food",
    "drink_water",
    "go_eat_food",
    "go_drink_water",
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
    "newborn": {"cry_for_food", "cry_for_comfort", "child_sleep", "be_carried", "signal_need", "observe_parent"},
    "infant": {"cry_for_food", "cry_for_comfort", "child_sleep", "be_carried", "observe_parent", "reach_item", "signal_need"},
    "toddler": {"cry_for_comfort", "child_sleep", "observe_parent", "signal_need", "ask_help_child", "follow_guardian", "learn_simple_words"},
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


def _blocked_by_reproduction_toggle(spec: ToolSpec) -> bool:
    """Return True for tools that create/advance reproduction when that optional toolset is off.

    Child-care tools are not blocked here because care is a safety/continuity action for children
    who already exist in the world. Blocking them made babies in private rooms effectively uncared for.
    """
    if spec.tool_name in CHILD_CARE_TOOLS:
        return False
    if spec.tool_name in REPRODUCTION_SETUP_TOOL_NAMES:
        return True
    return bool(spec.hard_effect_id.endswith("catalog_generic") and catalog_reproduction_related(spec))


# Phase 2D: user-toggleable tool modules for the modern default worldview.
# Each module groups v5/v6 catalog categories (matched as a substring of
# spec.catalog_category) that a world can switch off through
# settings_json["disabled_tool_modules"]. Default is empty (everything on) so
# existing worlds behave exactly as before. Werewolf and core/survival tools are
# never grouped here and can never be disabled through this mechanism.
TOGGLEABLE_TOOL_MODULES: dict[str, tuple[str, ...]] = {
    "finance": ("stock_market", "budgeting", "borrowing_repayment", "housing_landlord"),
    "creator_economy": ("creator_economy",),
    "transportation": ("transportation",),
    "luxury_consumption": ("hedonic_consumption", "status_social_emergency"),
    "service_work": ("ordinary_service_work",),
}


def _spec_in_disabled_module(spec: ToolSpec, disabled_modules: set[str]) -> bool:
    category = (spec.catalog_category or "").lower()
    if not category:
        return False
    for module_id in disabled_modules:
        if any(token in category for token in TOGGLEABLE_TOOL_MODULES.get(module_id, ())):
            return True
    return False


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
    disabled_modules = {str(m) for m in ((world.settings_json or {}).get("disabled_tool_modules") or [])} if world else set()
    jailed = bool((agent.law_json or {}).get("jailed"))
    working = active_work_status(agent, world.current_world_time_minutes if world else None) if world else None
    location_tool_names = set(location.available_tools_json or [])
    if str(location.location_id or "").split(":", 1)[-1] == "market":
        location_tool_names |= {
            "market_search_goods",
            "market_recommend_goods",
            "market_buy_goods",
            "gift_item_to_visible_agent",
            "transfer_item_to_visible_agent",
            "place_inventory_item",
            "pick_up_placed_item",
        }
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
    tags = set(location.tags_json or []) if location else set()
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
        if world and werewolf_enabled(world):
            names |= werewolf_menu_tool_names(session, world, agent)
        if world:
            names |= external_tool_names_for_toolset((world.settings_json or {}).get("world_toolset_id")) & location_tool_names
        if world and corpse_system_enabled(world) and has_visible_corpses(session, world, agent):
            names |= CORPSE_TOOL_NAMES
        if world and has_pending_social_request_from_visible(session, agent, world.current_world_time_minutes):
            names |= SOCIAL_REQUEST_RESPONSE_TOOLS
        if world and has_pending_forced_action_from_visible(session, agent, world.current_world_time_minutes):
            names |= FORCED_SOCIAL_RESPONSE_TOOLS
        if world and has_pending_infidelity_response_from_visible(session, agent, world.current_world_time_minutes):
            names |= INFIDELITY_RESPONSE_TOOLS
    if session and world and werewolf_enabled(world):
        _day, werewolf_current_phase = werewolf_phase(world)
        if werewolf_current_phase in {"discussion", "voting", "night"}:
            focused_names = werewolf_menu_tool_names(session, world, agent) | {"check_self_status", "do_nothing"}
            if werewolf_current_phase == "voting":
                focused_names.add("look_around")
            # Do not surface the internal candidate-debug tools during structured
            # Werewolf phases; otherwise agents may spend the round-table asking the
            # system for hidden tools instead of speaking/voting. Restrict the menu
            # to exactly the focused phase tools.
            names = set(focused_names)
    for name in sorted(names):
        spec = TOOL_SPECS.get(name)
        if not spec:
            continue
        if _blocked_in_non_modern_life_world(world, spec.tool_name, location):
            continue
        if is_agent_facing_disabled_tool(spec.tool_name):
            continue
        if working and work_blocks_tool(spec.tool_name):
            continue
        if reaction and spec.tool_name not in REACTION_TOOL_NAMES:
            continue
        if not survival_enabled and catalog_survival_need_related(spec):
            continue
        if not agent_special_tool_allowed(agent.tool_learning_json, spec.tool_name):
            continue
        if is_pregnant(agent) and spec.tool_name in PREGNANCY_RESTRICTED_TOOLS:
            continue
        if not reproduction_enabled and _blocked_by_reproduction_toggle(spec):
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
        if world and spec.tool_name in WEREWOLF_TOOL_NAMES and not werewolf_tool_menu_allowed(session, world, agent, spec.tool_name, location):
            continue
        if disabled_modules and spec.tool_name not in WEREWOLF_TOOL_NAMES and _spec_in_disabled_module(spec, disabled_modules):
            continue
        specs.append(spec)
    if agent.age_stage not in {"newborn", "infant", "toddler"} and TOOL_SPECS["do_nothing"] not in specs:
        specs.append(TOOL_SPECS["do_nothing"])
    prioritized = _prioritize_tools(session, agent, specs, world=world)
    if context_mode != "all" and agent.age_stage == "adult" and len(prioritized) > 60:
        return _cap_dynamic_tool_specs(session, agent, prioritized, limit=80, world=world)
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
        if spec.hard_effect_id == "v5_catalog_generic" and not catalog_generic_disabled_for_agent(spec):
            names.add(spec.tool_name)
    names |= V6_CORE_TOOLS
    names |= external_tool_names_for_toolset(world_toolset_id)
    return {name for name in names if not is_agent_facing_disabled_tool(name)}


def _passes_v5_gates(session: Session, agent: Agent, spec: ToolSpec, *, has_visible: bool) -> bool:
    if is_agent_facing_disabled_tool(spec.tool_name) or catalog_generic_disabled_for_agent(spec):
        return False
    world = session.get(World, agent.world_id)
    reproduction_enabled = reproduction_toolset_enabled(world)
    if not agent_special_tool_allowed(agent.tool_learning_json, spec.tool_name):
        return False
    if not survival_needs_enabled(world) and catalog_survival_need_related(spec):
        return False
    if not reproduction_enabled and _blocked_by_reproduction_toggle(spec):
        return False
    if is_pregnant(agent) and spec.tool_name in PREGNANCY_RESTRICTED_TOOLS:
        return False
    jailed = bool((agent.law_json or {}).get("jailed"))
    if spec.tool_name.startswith("werewolf_"):
        if not world or not werewolf_enabled(world):
            return False
        ok, _reason, _message = werewolf_tool_allowed(session, world, agent, spec.tool_name)
        return ok
    if spec.tool_name.startswith("v6_"):
        return v6_tool_allowed(session, agent, spec.tool_name)
    if spec.tool_name in WEREWOLF_TOOL_NAMES:
        return bool(world and werewolf_tool_menu_allowed(session, world, agent, spec.tool_name, agent.location.location if agent.location else None))
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
    if spec.tool_name in CORE_NEED_HELP_TOOLS and not _core_need_help_allowed(agent, spec.tool_name):
        return False
    if spec.tool_name == "seek_help" and not _seek_help_allowed(agent):
        return False
    if spec.tool_name in {"post_notice", "clear_notice_board", "call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule"}:
        location = agent.location.location if agent.location else None
        tags = set(location.tags_json or []) if location else set()
        if "notice" not in tags and not (world and _recent_social_instability(world, agent)):
            return False
    if spec.tool_name in CORE_RELATIONSHIP_CONTEXT_TOOLS and not _core_relationship_tool_allowed(session, world, agent, spec.tool_name, has_visible=has_visible):
        return False
    if spec.tool_name in NEGATIVE_RELATIONSHIP_CONTEXT_TOOLS and not _negative_relationship_tool_allowed(session, world, agent, has_visible=has_visible):
        return False
    if spec.tool_name in INFIDELITY_RESPONSE_TOOLS and not (world and has_pending_infidelity_response_from_visible(session, agent, world.current_world_time_minutes)):
        return False
    if spec.tool_name == "request_adult_intimacy_visible_agent" and not _adult_catalog_context_allows(session, agent, agent.location.location if agent.location else None, spec, has_visible=has_visible):
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
    """Pick v5 catalog tools by context instead of first-N catalog order.

    The v5 catalog is intentionally huge. Showing every generic tool would drown the
    AOHP menu, but taking the first 32 entries made most tools practically
    unreachable. This router scores the whole v5 catalog, blocks only impossible
    options, and then keeps a diverse high-score slice. Hard validation still runs
    later; this layer decides what is worth offering *now*.
    """
    candidates: list[tuple[int, str, str, str]] = []
    for spec in TOOL_SPECS.values():
        if spec.hard_effect_id != "v5_catalog_generic":
            continue
        if not _catalog_quick_allows(session, agent, location, spec, has_visible=has_visible, has_known_names=has_known_names):
            continue
        score = _catalog_context_score(session, agent, location, spec, has_visible=has_visible, has_known_names=has_known_names)
        if score <= -900:
            continue
        candidates.append((score, _catalog_domain(spec), spec.catalog_category or "", spec.tool_name))
    return set(_select_diverse_catalog_tools(candidates, limit=_catalog_candidate_limit(agent)))


def _catalog_candidate_limit(agent: Agent) -> int:
    if agent.age_stage in {"newborn", "infant", "toddler"}:
        return 20
    if agent.age_stage == "child":
        return 28
    return 32


def _catalog_text(spec: ToolSpec) -> str:
    return f"{spec.tool_name} {spec.display_name} {spec.catalog_category or ''} {spec.effect_summary or ''}".lower()


_DESCRIPTOR_TOKENS = (
    "显示", "列出", "查看可用", "可用工具", "工具候选", "候选工具", "菜单", "选项", "options", "candidate", "available tools",
)


def _catalog_is_noop_descriptor(spec: ToolSpec) -> bool:
    text = _catalog_text(spec)
    if spec.hard_effect_id != "v5_catalog_generic":
        return False
    # These are not character actions; they are catalog/meta descriptors that the
    # generic handler used to turn into meaningless events such as “认真处理工作”.
    if any(token in text for token in _DESCRIPTOR_TOKENS):
        return True
    if "价格" in text and any(token in text for token in ["显示", "查看", "列出"]):
        return True
    return False


def _catalog_is_generic_work_noop(spec: ToolSpec) -> bool:
    if spec.hard_effect_id != "v5_catalog_generic":
        return False
    text = _catalog_text(spec)
    name = str(spec.tool_name or "").lower()
    # Concrete work_shift/do_odd_job tools have real scheduling and money effects.  The
    # generic v5 work catalog only emits a vague v5_work event and should never be
    # offered/executed as a real action.
    if name.startswith("tool_work_") or " work" in f" {name}" or "工作" in text or "job" in text or "shift" in text:
        return True
    return False


def catalog_generic_disabled_for_agent(spec: ToolSpec) -> bool:
    return bool(_catalog_is_noop_descriptor(spec) or _catalog_is_generic_work_noop(spec))


def _catalog_quick_allows(
    session: Session | None,
    agent: Agent,
    location: Location | None,
    spec: ToolSpec,
    *,
    has_visible: bool,
    has_known_names: bool,
) -> bool:
    if is_agent_facing_disabled_tool(spec.tool_name) or catalog_generic_disabled_for_agent(spec):
        return False
    text = _catalog_text(spec)
    category = spec.catalog_category or ""
    age = agent.age_stage
    jailed = bool((agent.law_json or {}).get("jailed"))
    if spec.tool_name.startswith("system_") or spec.tool_name.startswith("tool_meta_") or "工具候选" in category:
        return False
    if spec.target_policy == "visible_ref" and not has_visible:
        return False
    if spec.target_policy == "known_name" and not has_known_names:
        return False
    if spec.allowed_lifecycle_states and agent.lifecycle_state not in spec.allowed_lifecycle_states:
        return False
    if _catalog_stateful_response_without_state(session, agent, spec):
        return False
    if _catalog_requires_family_context(session, agent, spec):
        return False
    if _catalog_requires_inventory_context(session, agent, spec):
        return False
    if _catalog_requires_social_context(session, agent, spec):
        return False
    if not _catalog_scene_allows(agent, location, spec):
        return False
    if jailed:
        return "jail" in text or "监狱" in category or spec.tool_name in JAIL_TOOLS
    if "jail" in text or "监狱" in category:
        return False
    family_or_adult_text = any(token in text for token in ["adult", "成年", "性行为", "sexual", "intimacy", "亲密", "怀孕", "pregnancy", "birth", "生产", "分娩", "避孕"])
    if age != "adult" and family_or_adult_text:
        return False
    if any(token in text for token in ["birth", "生产", "分娩", "give_birth"]):
        # Birth-stage catalog tools should not be casually available to non-pregnant agents.
        # The automatic pregnancy/birth engine will still create births when due.
        if not is_pregnant(agent):
            return False
    if spec.tool_name.startswith("tool_adult_"):
        # Contextual routing only: adult/reproduction tools should be reachable when a
        # relationship or private-life context exists, but should not crowd out ordinary
        # plaza/clinic/library actions on first contact.
        if age != "adult" or not _adult_catalog_context_allows(session, agent, location, spec, has_visible=has_visible):
            return False
    if spec.tool_name in {"tool_relationship_label_revise", "tool_goal_revise"}:
        if not (session and _has_visible_relationship_context(session, agent)):
            return False
    if "儿童" in category or "child" in spec.tool_name or "parent_" in spec.tool_name:
        if age in {"newborn", "infant", "toddler", "child"}:
            return any(token in spec.tool_name for token in ["tool_child_", "observe", "learn", "play", "ask", "request", "follow", "sleep", "signal", "cry"])
        return bool(session and _has_visible_child(session, agent) and any(token in spec.tool_name for token in ["parent", "community", "welfare", "feed", "comfort", "teach", "childcare"]))
    if any(token in text for token in ["crime", "犯罪", "偷", "抢", "攻击", "violent"]):
        state = agent.dynamic_state
        survival_crisis = bool(state and (state.satiety < 18 or state.hydration < 18 or state.health < 35 or state.energy < 12))
        return age == "adult" and (survival_crisis or _crime_pressure(agent, minimum=35))
    if spec.target_policy == "item" and session:
        if not _location_or_inventory_has_items(session, agent, location):
            return False
    return True



def _core_need_help_allowed(agent: Agent, tool_name: str) -> bool:
    state = agent.dynamic_state
    money = wallet_money(agent)
    if tool_name == "request_food_help":
        return bool(state and state.satiety < 45) or money < 8
    if tool_name == "request_water_help":
        return bool(state and state.hydration < 45) or money < 6
    if tool_name == "accept_community_aid":
        return bool(state and (state.satiety < 35 or state.hydration < 35 or state.health < 45)) or money < 10
    return True


def _seek_help_allowed(agent: Agent) -> bool:
    state = agent.dynamic_state
    if not state:
        return False
    return bool(state.health < 60 or state.energy < 25 or state.satiety < 35 or state.hydration < 35 or state.stress > 75)


def _romance_friendly_world(world: World | None) -> bool:
    worldview_id = str((world.settings_json or {}).get("worldview_id") or "") if world else ""
    return worldview_id in {"sweet_romance_worldview", "pure_emotion_worldview"}


def _core_relationship_tool_allowed(
    session: Session,
    world: World | None,
    agent: Agent,
    tool_name: str,
    *,
    has_visible: bool,
) -> bool:
    if not has_visible:
        return False
    if tool_name in {"hold_hands_visible_agent", "hug_visible_agent"} and _has_pending_social_or_forced_request(session, agent, world):
        return True
    # Relationship tools are target-stage gated.  A romance-friendly worldview can
    # lower narrative reluctance, but it must not make "请求确认关系" appear for a
    # stranger with affection=0.
    return _has_visible_target_allowed_for_relationship_tool(session, world, agent, tool_name)


def _negative_relationship_tool_allowed(session: Session, world: World | None, agent: Agent, *, has_visible: bool) -> bool:
    if not has_visible:
        return False
    ctx = relationship_menu_context(session, agent, set(same_location_agent_ids(session, agent)))
    state = agent.dynamic_state
    stress = int(state.stress) if state else 0
    aggression = trait_value(agent, "aggression", 50)
    honesty = trait_value(agent, "honesty", 50)
    neuroticism = trait_value(agent, "neuroticism", 50)
    return bool(ctx.has_relationship_tension or stress >= 55 or aggression >= 58 or honesty >= 68 or neuroticism >= 72)


def _has_visible_target_allowed_for_relationship_tool(session: Session, world: World | None, agent: Agent, tool_name: str) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    if not visible_ids:
        return False
    for target_id in visible_ids:
        target = session.get(Agent, target_id)
        if target and relationship_tool_allowed_for_target(session, world, agent, target, tool_name):
            return True
    return False


def _has_pending_social_or_forced_request(session: Session, agent: Agent, world: World | None) -> bool:
    now = world.current_world_time_minutes if world else 0
    return bool(
        has_pending_social_request_from_visible(session, agent, now)
        or has_pending_forced_action_from_visible(session, agent, now)
        or _has_pending_intimacy_request_from_visible(session, agent)
    )


def _has_visible_relationship_tension(session: Session, agent: Agent) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    if not visible_ids:
        return False
    rows = session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == agent.agent_id,
            Relationship.target_agent_id.in_(visible_ids),
        )
    ).scalars()
    for rel in rows:
        if rel.conflict >= 25 or rel.fear >= 35 or rel.trust <= 25 or rel.affection <= -10:
            return True
    return False


def _adult_catalog_context_allows(
    session: Session | None,
    agent: Agent,
    location: Location | None,
    spec: ToolSpec,
    *,
    has_visible: bool,
) -> bool:
    name = spec.tool_name
    tags = set(location.tags_json or [])
    family = agent.family_json or {}
    if name == "tool_adult_buy_condom":
        return "trade" in tags
    if name == "tool_adult_carry_condom":
        inventory = (agent.inventory_json or {}) if hasattr(agent, "inventory_json") else {}
        return bool(inventory.get("contraception") or inventory.get("condom") or inventory.get("避孕套"))
    if family.get("intimacy_session") or family.get("recent_intimacy_event"):
        return True
    if session and _has_pending_intimacy_request_from_visible(session, agent):
        return True
    if not has_visible or not session:
        return False
    return _has_visible_relationship_context(session, agent)


def _has_visible_relationship_context(session: Session, agent: Agent) -> bool:
    visible_ids = set(same_location_agent_ids(session, agent))
    if not visible_ids:
        return False
    rows = session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == agent.agent_id,
            Relationship.target_agent_id.in_(visible_ids),
        )
    ).scalars()
    labels = {"朋友", "好友", "恋人", "伴侣", "约会", "暧昧", "家人", "夫妻", "亲密"}
    for rel in rows:
        label = rel.relationship_label or ""
        if rel.affection >= 20 or rel.familiarity >= 35 or rel.trust >= 70 or any(token in label for token in labels):
            return True
    return False

def _location_or_inventory_has_items(session: Session, agent: Agent, location: Location) -> bool:
    if session.execute(select(Item.item_id).where(Item.location_id == location.location_id).limit(1)).first():
        return True
    if session.execute(select(Inventory.agent_id).where(Inventory.agent_id == agent.agent_id, Inventory.quantity > 0).limit(1)).first():
        return True
    return False



def _catalog_stateful_response_without_state(session: Session | None, agent: Agent, spec: ToolSpec) -> bool:
    raw = (spec.metadata or {}).get("raw") or {}
    target_rule = str(raw.get("target_rule") or "")
    # These catalog entries are replies to a conversation/promise/trade/invite state, but
    # the current generic handler does not bind such state. Keep concrete pending-request
    # tools instead, and do not offer these as free-floating actions.
    stateful_rules = {
        "conversation",
        "promise",
        "confession",
        "date_invitation",
        "consent_request",
        "trade_offer",
        "pending_item_offer",
        "invitation",
        "borrowed_item",
        "debt",
        "group_activity",
    }
    if target_rule in stateful_rules:
        return True
    if spec.tool_name in {
        "tool_comm_end_private_talk",
        "tool_comm_break_promise",
        "tool_econ_accept_trade",
        "tool_econ_reject_trade",
        "tool_item_accept",
        "tool_item_refuse",
        "tool_romance_accept_confession",
        "tool_romance_reject_confession",
        "tool_romance_accept_date",
        "tool_romance_decline_date",
        "tool_romance_accept_hold_hands",
        "tool_romance_decline_hold_hands",
        "tool_romance_accept_hug",
        "tool_romance_decline_hug",
        "tool_social_accept_invite",
        "tool_social_decline_invite",
    }:
        return True
    return False


def _catalog_requires_family_context(session: Session | None, agent: Agent, spec: ToolSpec) -> bool:
    name = spec.tool_name
    text = _catalog_text(spec)
    if name == "tool_market_buy_baby_supplies" or any(token in text for token in ["baby_supplies", "儿童用品"]):
        return not (is_pregnant(agent) or (session is not None and _has_visible_child(session, agent)))
    return False


def _catalog_requires_inventory_context(session: Session | None, agent: Agent, spec: ToolSpec) -> bool:
    if not session:
        return False
    name = spec.tool_name
    if name.startswith("tool_inventory_") and any(token in name for token in ["share", "throw", "take", "pack", "ration"]):
        return not _agent_inventory_has_items(session, agent)
    return False


def _catalog_requires_social_context(session: Session | None, agent: Agent, spec: ToolSpec) -> bool:
    if not session:
        return False
    visible_ids = set(same_location_agent_ids(session, agent))
    name = spec.tool_name
    if name == "tool_social_introduce_third":
        return len(visible_ids) < 2
    if name.startswith("tool_conflict_") and name not in {"tool_conflict_deescalate", "tool_conflict_leave_argument"}:
        state = agent.dynamic_state
        if not (state and state.stress >= 55) and not _has_visible_relationship_tension(session, agent):
            return True
    return False


def _agent_inventory_has_items(session: Session, agent: Agent) -> bool:
    return bool(session.execute(select(Inventory.agent_id).where(Inventory.agent_id == agent.agent_id, Inventory.quantity > 0).limit(1)).first())


def _catalog_scene_allows(agent: Agent, location: Location, spec: ToolSpec) -> bool:
    tags = set(location.tags_json or [])
    name = spec.tool_name.lower()
    visible_when = str((spec.metadata or {}).get("visible_when_zh") or "").lower()
    combined = f"{name} {visible_when} {spec.catalog_category or ''}".lower()
    if name.startswith("tool_cafeteria_") and "food_service" not in tags:
        return False
    if name.startswith("tool_market_") and not ({"trade", "food_service"} & tags):
        return False
    if name.startswith("tool_jail_") and "jail" not in tags:
        return False
    if name.startswith("tool_work_"):
        employed = bool((agent.work_json or {}).get("employed") or (agent.work_json or {}).get("current_shift"))
        if not (employed or {"food_service", "trade", "craft", "notice"} & tags):
            return False
    if name.startswith("tool_service_") and not ({"food_service", "trade"} & tags):
        return False
    if name.startswith("tool_econ_"):
        state = agent.dynamic_state
        money_pressure = wallet_money(agent) < 20 or bool(state and (state.satiety < 30 or state.hydration < 30))
        if not ({"trade", "food_service"} & tags or (money_pressure and {"social", "open_view", "work"} & tags)):
            return False
    if name.startswith("tool_inventory_pack_"):
        employed = bool((agent.work_json or {}).get("employed") or (agent.work_json or {}).get("current_shift"))
        state = agent.dynamic_state
        survival_preparation = bool(state and (state.satiety < 55 or state.hydration < 55))
        if not (employed or survival_preparation or {"food_service", "trade", "home"} & tags):
            return False
    if name.startswith(("tool_victim_", "tool_police_", "tool_court_")):
        law = agent.law_json or {}
        has_case = bool(law.get("victim_records") or law.get("criminal_records") or law.get("known_crimes") or law.get("recent_case"))
        if not has_case:
            return False
    if name.startswith("tool_food_") and not ({"food_service", "food", "natural_food", "home", "campfire", "nature"} & tags):
        # Asking for food and inventory rationing have separate tool families; food preparation
        # itself should not appear in a random clinic/library just because the agent is hungry.
        return False
    if name.startswith("tool_water_") and not ({"water", "food_service", "medical", "home", "nature"} & tags):
        return False
    if name.startswith("tool_life_") and not ({"home", "food_service", "quiet", "water"} & tags):
        return False
    if name.startswith("tool_env_") and not ({"nature", "craft", "home", "social", "open_view"} & tags):
        return False
    if name.startswith(("tool_create_", "tool_project_")) and not ({"learning", "quiet", "craft", "home"} & tags):
        return False
    if name.startswith(("tool_goal_", "tool_memory_")) and not ({"learning", "quiet", "home", "social", "open_view"} & tags):
        return False
    if "food_service" in tags and name.startswith(("tool_create_", "tool_project_", "tool_goal_")):
        state = agent.dynamic_state
        if state and (state.satiety < 55 or state.hydration < 55):
            return False
    if name.startswith("tool_learn_") and "library" in combined and not ({"learning", "quiet"} & tags):
        return False
    if name.startswith("tool_birth_") and not ({"medical", "home", "quiet"} & tags):
        return False
    if "cafeteria" in combined and "food_service" not in tags:
        return False
    if "market" in combined and not ({"trade", "food_service"} & tags):
        return False
    return True

def _catalog_context_score(
    session: Session | None,
    agent: Agent,
    location: Location,
    spec: ToolSpec,
    *,
    has_visible: bool,
    has_known_names: bool,
) -> int:
    state = agent.dynamic_state
    tags = set(location.tags_json or [])
    text = _catalog_text(spec)
    score = 10
    if spec.tool_name in (location.available_tools_json or []):
        score += 45
    if spec.target_policy == "visible_ref" and has_visible:
        score += 18
    if spec.target_policy == "known_name" and has_known_names:
        score += 12
    if spec.target_policy == "item":
        score += 8

    if state:
        if state.hydration < 45 and any(token in text for token in ["water", "drink", "喝", "水", "口渴"]):
            score += 90 if state.hydration < 25 else 55
        if state.satiety < 45 and any(token in text for token in ["food", "eat", "meal", "cook", "吃", "食物", "饭", "饥", "饿"]):
            score += 90 if state.satiety < 25 else 55
        if state.energy < 45 and any(token in text for token in ["sleep", "rest", "nap", "睡", "休息", "坐下"]):
            score += 80 if state.energy < 25 else 45
        if state.hygiene < 45 and any(token in text for token in ["wash", "bathe", "clean", "清洁", "洗", "换衣"]):
            score += 70 if state.hygiene < 25 else 40
        if state.health < 70 and any(token in text for token in ["medical", "medicine", "treat", "wound", "care", "医", "药", "治疗", "伤"]):
            score += 85 if state.health < 40 else 45
        if state.social < 55 and any(token in text for token in ["social", "greet", "talk", "chat", "社交", "打招呼", "聊天", "交流"]):
            score += 40
        if state.fun < 50 and any(token in text for token in ["game", "play", "story", "sing", "joke", "fun", "玩", "唱", "故事", "笑话"]):
            score += 42
        if state.stress > 60 and any(token in text for token in ["comfort", "reassure", "meditate", "breathe", "relax", "安慰", "放松", "呼吸", "冥想"]):
            score += 45

    if "food_service" in tags or "food" in tags:
        score += _keyword_bonus(text, ["food", "meal", "cook", "serve", "eat", "market", "食物", "饭", "烹饪", "餐", "厨房"], 35)
    if "water" in tags or "hot_spring" in tags:
        score += _keyword_bonus(text, ["water", "drink", "wash", "bathe", "hot", "spring", "水", "喝", "洗", "温泉", "清洁"], 32)
    if "medical" in tags:
        score += _keyword_bonus(text, ["medical", "medicine", "treat", "wound", "health", "pregnancy", "baby", "医", "药", "治疗", "伤", "护理", "怀孕", "婴儿"], 42)
    if "work" in tags or "craft" in tags:
        score += _keyword_bonus(text, ["work", "job", "shift", "craft", "repair", "工作", "班次", "劳动", "制作", "修理"], 38)
    if "trade" in tags:
        score += _keyword_bonus(text, ["market", "trade", "buy", "sell", "money", "item", "货币", "市场", "购买", "出售", "交易", "背包"], 38)
    if "learning" in tags or "quiet" in tags:
        score += _keyword_bonus(text, ["learn", "read", "study", "diary", "memory", "write", "project", "学习", "读", "书", "日记", "记忆", "写", "项目"], 34)
    if "social" in tags or "open_view" in tags:
        score += _keyword_bonus(text, ["social", "greet", "talk", "chat", "meeting", "group", "romance", "社交", "打招呼", "聊天", "会议", "群体", "关系", "恋爱"], 30)
    if "nature" in tags or "natural_food" in tags:
        score += _keyword_bonus(text, ["forage", "walk", "scenery", "nature", "gather", "采", "散步", "风景", "自然", "花园"], 34)
    if "notice" in tags or "public_record" in tags:
        score += _keyword_bonus(text, ["notice", "post", "public", "rule", "meeting", "公告", "公示", "规则", "会议", "记录"], 36)
    if "home" in tags:
        score += _keyword_bonus(text, ["sleep", "rest", "diary", "clean", "clothes", "pregnancy", "baby", "睡", "休息", "日记", "整理", "怀孕", "婴儿"], 34)

    money = wallet_money(agent)
    if money < 18:
        score += _keyword_bonus(text, ["work", "job", "market", "sell", "money", "loan", "aid", "工作", "赚钱", "市场", "出售", "求助", "贷款"], 42)
        if state and (state.satiety < 25 or state.hydration < 25):
            score += _keyword_bonus(text, ["crime", "theft", "steal", "burglary", "rob", "偷", "抢", "犯罪"], 25)
    if has_visible:
        score += _keyword_bonus(text, ["social", "greet", "talk", "help", "comfort", "share", "romance", "社交", "打招呼", "帮助", "安慰", "分享", "关系", "恋爱"], 20)
    if has_known_names:
        score += _keyword_bonus(text, ["known", "name", "gossip", "letter", "名字", "姓名", "熟人", "写信"], 12)

    traits = agent.traits
    if traits:
        if traits.curiosity >= 60:
            score += _keyword_bonus(text, ["observe", "inspect", "learn", "research", "read", "market", "观察", "检查", "学习", "研究", "阅读"], 20)
        if traits.creativity >= 60:
            score += _keyword_bonus(text, ["create", "write", "draw", "song", "craft", "story", "创作", "写", "画", "歌", "制作", "故事"], 20)
        if traits.discipline >= 60:
            score += _keyword_bonus(text, ["work", "plan", "clean", "organize", "budget", "工作", "计划", "清洁", "整理", "预算"], 18)
        if traits.sociability >= 60:
            score += _keyword_bonus(text, ["social", "talk", "greet", "meeting", "group", "社交", "聊天", "打招呼", "会议", "群体"], 18)
        if traits.empathy >= 60:
            score += _keyword_bonus(text, ["help", "comfort", "care", "share", "reassure", "帮助", "安慰", "照顾", "分享"], 20)
        if traits.aggression >= 70:
            score += _keyword_bonus(text, ["crime", "conflict", "protest", "confront", "attack", "犯罪", "冲突", "抗议", "对质", "攻击"], 18)

    # Keep dull broad entries below concrete context tools, but do not delete them.
    if any(token in spec.tool_name for token in ["debug", "system"]):
        score -= 200
    return score


def _keyword_bonus(text: str, tokens: list[str], amount: int) -> int:
    return amount if any(token in text for token in tokens) else 0


def _catalog_domain(spec: ToolSpec) -> str:
    text = _catalog_text(spec)
    if any(token in text for token in ["child", "儿童", "婴儿", "parent", "成长"]):
        return "childcare"
    if any(token in text for token in ["pregnancy", "birth", "怀孕", "生产", "避孕"]):
        return "family"
    if any(token in text for token in ["romance", "relationship", "亲密", "恋爱", "关系"]):
        return "relationship"
    if any(token in text for token in ["social", "greet", "talk", "chat", "社交", "交流", "聊天", "打招呼"]):
        return "social"
    if any(token in text for token in ["food", "water", "sleep", "rest", "wash", "medical", "eat", "drink", "身体", "吃", "喝", "睡", "休息", "清洁", "治疗"]):
        return "survival"
    if any(token in text for token in ["work", "job", "shift", "劳动", "工作", "班次"]):
        return "work"
    if any(token in text for token in ["market", "money", "trade", "inventory", "item", "货币", "市场", "背包", "物品", "交易"]):
        return "economy"
    if any(token in text for token in ["crime", "jail", "law", "犯罪", "监狱", "司法"]):
        return "law"
    if any(token in text for token in ["learn", "read", "study", "create", "write", "story", "skill", "学习", "阅读", "创作", "写", "技能"]):
        return "learning"
    if any(token in text for token in ["move", "location", "door", "地点", "移动", "房间", "门"]):
        return "space"
    return "general"


def _select_diverse_catalog_tools(candidates: list[tuple[int, str, str, str]], *, limit: int) -> list[str]:
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: (-item[0], item[1], item[3]))
    selected: list[str] = []
    seen: set[str] = set()
    domain_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    def add(item: tuple[int, str, str, str]) -> bool:
        if len(selected) >= limit:
            return False
        _score, domain, category, tool_name = item
        if tool_name in seen:
            return False
        selected.append(tool_name)
        seen.add(tool_name)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        return True

    # Pass 1: ensure major domains get representation if they have high-scoring tools.
    domain_quota = {
        "survival": 8,
        "social": 5,
        "relationship": 4,
        "work": 6,
        "economy": 6,
        "learning": 5,
        "childcare": 4,
        "family": 4,
        "law": 4,
        "space": 3,
        "general": 3,
    }
    for item in ordered:
        score, domain, category, _tool_name = item
        if score < 30:
            continue
        if domain_counts.get(domain, 0) >= domain_quota.get(domain, 8):
            continue
        if category and category_counts.get(category, 0) >= 6:
            continue
        add(item)
        if len(selected) >= limit:
            return selected

    # Pass 2: fill by raw score with looser category caps, but do not pad the menu
    # with every merely-valid catalog entry. A score below 22 usually means the tool is
    # only generically possible, not actually relevant to this location/state.
    for item in ordered:
        score, _domain, category, _tool_name = item
        if score < 22:
            continue
        if category and category_counts.get(category, 0) >= 8:
            continue
        add(item)
        if len(selected) >= limit:
            return selected
    return selected


def _crime_pressure(agent: Agent, *, minimum: int) -> bool:
    desires = agent.desires_json or {}
    morality = agent.morality_json or {}
    state = agent.dynamic_state
    pressure = int(desires.get("survival_pressure", 0))
    if wallet_money(agent) < 8:
        pressure += 25
    if state and (state.satiety < 35 or state.hydration < 35):
        pressure += 20
    if state:
        pressure += max(0, int(state.stress) - 55) // 2
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


def _prioritize_tools(session: Session | None, agent: Agent, specs: list[ToolSpec], *, world: World | None = None) -> list[ToolSpec]:
    state = agent.dynamic_state
    urgent_names = set(priority_tools_from_drive(agent))
    if state:
        profile = profile_for_agent(agent)
        if state.hydration < float(profile["urgent_hydration"]):
            urgent_names.update({"go_drink_water", "drink_water", "drink_bottled_water", "fill_canteen", "buy_bottled_water", "request_water_help", "accept_community_aid"})
        if state.satiety < float(profile["urgent_satiety"]):
            urgent_names.update({"go_eat_food", "eat_food", "eat_portable_food", "pack_lunch", "buy_portable_food", "request_food_help", "accept_community_aid"})
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
        if money_pressure and (world is None or modern_life_enabled(world)):
            urgent_names.update({"apply_for_job", "do_odd_job", "work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner", "work_shift_night_guard"})
            urgent_names.update({"attempt_burglary_private_room", "attempt_petty_theft_visible_agent"})
            if agent.traits and (agent.traits.aggression >= 70 or state.stress >= 70):
                urgent_names.update({"home_invasion_robbery_private_room", "demand_money_visible_agent"})
        if money_pressure and world and modern_life_enabled(world):
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
            if werewolf_enabled(world):
                urgent_names.update({"werewolf_summarize_clues", "werewolf_speak", "werewolf_vote_by_name", "werewolf_review_vote_history", "werewolf_wolf_discuss", "werewolf_kill_by_name", "werewolf_seer_check_by_name", "werewolf_coroner_check_latest", "werewolf_guard_protect_by_name"})
        if session:
            ctx = relationship_menu_context(session, agent, set(same_location_agent_ids(session, agent)))
            if ctx.has_intervention_crush_candidate:
                urgent_names.update({"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent"})
            if ctx.has_high_affection_candidate:
                urgent_names.update({"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent", "define_relationship_visible_agent"})
            elif ctx.has_romance_candidate:
                urgent_names.update({"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent"})
            if ctx.has_visible_partner:
                urgent_names.update({"request_adult_intimacy_visible_agent", "buy_contraception", "buy_pregnancy_test", "take_pregnancy_test"})
                urgent_names.update(PARTNER_FAMILY_PLANNING_TOOL_NAMES)
            if ctx.has_relationship_tension:
                urgent_names.update({"repair_relationship_visible_agent", "break_up_visible_agent", "set_boundary_visible_agent", *NEGATIVE_RELATIONSHIP_CONTEXT_TOOLS})
            if world and has_pending_infidelity_response_from_visible(session, agent, world.current_world_time_minutes):
                urgent_names.update(INFIDELITY_RESPONSE_TOOLS)
        if world and _recent_social_instability(world, agent):
            urgent_names.update({"call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule"})
    return sorted(specs, key=lambda spec: (0 if spec.tool_name in urgent_names else 1, trait_priority_bias(agent.traits, spec.tool_name), spec.tool_name))


def _cap_dynamic_tool_specs(
    session_or_agent: Session | Agent | None,
    agent_or_specs: Agent | list[ToolSpec],
    specs: list[ToolSpec] | None = None,
    *,
    limit: int,
    world: World | None,
) -> list[ToolSpec]:
    """动态工具裁剪：根据 agent 状态优先级排序，裁剪到指定数量。

    注意：此函数不替 agent 做选择，只是按优先级排序让 agent 能看到更相关的工具。
    agent/LLM 最终决定使用哪个工具。
    """
    if specs is None:
        session = None
        agent = session_or_agent  # type: ignore[assignment]
        specs = agent_or_specs  # type: ignore[assignment]
    else:
        session = session_or_agent  # type: ignore[assignment]
        agent = agent_or_specs  # type: ignore[assignment]
    if not isinstance(agent, Agent):
        return [spec for spec in specs if spec.tool_name not in DISABLED_GROUP_CHAT_TOOLS]
    specs = [spec for spec in specs if spec.tool_name not in DISABLED_GROUP_CHAT_TOOLS]
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

    # 基础工具：状态检查、观察、移动、说话 - 给予较高配额
    add_matching(lambda spec: spec.tool_name in {"do_nothing", "check_self_status", "look_around"}, 3)
    add_matching(lambda spec: spec.tool_name in {"move_to_location", "wander", "return_home", "go_eat_food", "go_drink_water"}, 8)
    add_matching(lambda spec: spec.tool_name in PRIVATE_ROOM_ENTRY_TOOLS, 3)
    add_matching(lambda spec: spec.tool_name in {"speak_to_nearby", "say_to_visible_agent", "tool_social_greet_visible"}, 8)

    # 市场和经济工具
    add_matching(lambda spec: spec.tool_name in MARKET_ACTION_TOOLS, 8)

    # 根据 agent 状态添加相关工具（不是强制保留，只是优先排列）
    # 高压力或低生存状态时，添加应对工具
    if trait_value(agent, "aggression", 50) >= 65 or (agent.dynamic_state and (agent.dynamic_state.stress >= 75 or agent.dynamic_state.satiety < 16 or agent.dynamic_state.hydration < 16)):
        add_matching(lambda spec: spec.tool_name in CRIMINAL_ACTION_TOOLS or any(token in spec.tool_name for token in ["force_", "confront", "protest"]), 10)

    # drive 系统建议的工具
    add_matching(lambda spec: spec.tool_name in set(priority_tools_from_drive(agent)), 10)

    # 关系工具
    relationship_priority: set[str] = set()
    if session:
        ctx = relationship_menu_context(session, agent, set(same_location_agent_ids(session, agent)))
        if ctx.has_intervention_crush_candidate:
            relationship_priority.update({"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent"})
        if ctx.has_high_affection_candidate:
            relationship_priority.update({"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent", "define_relationship_visible_agent"})
        elif ctx.has_romance_candidate:
            relationship_priority.update({"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent"})
        if ctx.has_visible_partner:
            relationship_priority.update(PARTNER_FAMILY_PLANNING_TOOL_NAMES)
        if ctx.has_relationship_tension:
            relationship_priority.update({"repair_relationship_visible_agent", "break_up_visible_agent", "set_boundary_visible_agent"})
            relationship_priority.update(NEGATIVE_RELATIONSHIP_CONTEXT_TOOLS)
        if world and has_pending_infidelity_response_from_visible(session, agent, world.current_world_time_minutes):
            relationship_priority.update(INFIDELITY_RESPONSE_TOOLS)
    add_matching(lambda spec: spec.tool_name in relationship_priority, 12)

    # v5 catalog 工具：按域分配配额
    add_matching(lambda spec: spec.hard_effect_id == "v5_catalog_generic" and _catalog_domain(spec) == "survival", 12)
    add_matching(lambda spec: spec.hard_effect_id == "v5_catalog_generic" and _catalog_domain(spec) in {"work", "economy"}, 10)
    add_matching(lambda spec: spec.hard_effect_id == "v5_catalog_generic" and _catalog_domain(spec) in {"social", "relationship"}, 10)
    add_matching(lambda spec: spec.hard_effect_id == "v5_catalog_generic" and _catalog_domain(spec) in {"learning", "space", "general"}, 10)
    add_matching(lambda spec: spec.hard_effect_id == "v5_catalog_generic" and _catalog_domain(spec) in {"childcare", "family", "law"}, 6)

    # 关系确认和状态转换工具
    add_matching(
        lambda spec: spec.tool_name
        in ADULT_INTIMACY_TOOLS
        | PREGNANCY_TOOLS
        | {
            "ask_date_visible_agent",
            "hold_hands_visible_agent",
            "hug_visible_agent",
            "confess_feelings_visible_agent",
            "define_relationship_visible_agent",
            "discuss_romantic_boundaries_visible_agent",
            "break_up_visible_agent",
            "repair_relationship_visible_agent",
        }
        | NEGATIVE_RELATIONSHIP_CONTEXT_TOOLS
        | INFIDELITY_RESPONSE_TOOLS,
        10,
    )

    # 根据性格添加相关工具
    if trait_value(agent, "aggression", 50) >= 65 or (agent.dynamic_state and agent.dynamic_state.stress >= 75):
        add_matching(lambda spec: spec.tool_name in CRIMINAL_ACTION_TOOLS or any(token in spec.tool_name for token in ["force_", "confront", "protest"]), 10)
    if trait_value(agent, "sociability", 50) >= 62 or trait_value(agent, "empathy", 50) >= 62:
        add_matching(lambda spec: spec.target_policy == "visible_ref" and any(token in spec.tool_name for token in ["chat", "help", "comfort", "thank", "ask_", "invite", "share", "relationship"]), 12)
    if trait_value(agent, "creativity", 50) >= 62 or trait_value(agent, "curiosity", 50) >= 62:
        add_matching(lambda spec: any(token in spec.tool_name for token in ["write", "story", "sing", "read", "practice", "sketch", "research", "observe", "look"]), 10)
    if trait_value(agent, "discipline", 50) >= 62:
        add_matching(lambda spec: any(token in spec.tool_name for token in ["work", "sleep", "wash", "clean", "plan", "repay", "budget"]), 10)

    # 社会不稳定时的治理工具
    if world and _recent_social_instability(world, agent):
        add_matching(lambda spec: spec.tool_name in {"call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule", "report_unknown_theft", "report_known_crime_by_name"}, 8)

    # 剩余配额：填充其他工具
    add_matching(lambda _spec: True, limit - len(selected))

    # 审计日志：记录被裁剪的工具（便于调试，不影响 agent 决策）
    pruned = [spec.tool_name for spec in specs if spec.tool_name not in seen]
    if pruned:
        logger.debug(
            "agent %s: tools available %d/%d, pruned: %s",
            getattr(agent, "agent_id", "?"),
            len(selected),
            len(specs),
            ", ".join(pruned[:10]) + ("..." if len(pruned) > 10 else ""),
        )

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
