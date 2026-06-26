from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, IdentityKnowledge, Inventory, Item, Location, World
from app.agents.traits import trait_priority_bias
from app.economy import v6 as v6_economy
from app.llm.action_protocol import ActionOption
from app.llm.language import corpse_ref_label, english_safe_label, item_label, location_label, normalize_language, person_ref_label, world_language
from app.social.forced_actions import FORCED_SOCIAL_RESPONSE_TOOLS, forced_action_kind, incoming_forced_actions
from app.social.infidelity_responses import INFIDELITY_RESPONSE_TOOL_NAMES, pending_infidelity_response_from
from app.social.pending_requests import SOCIAL_REQUEST_RESPONSE_TOOLS, incoming_social_requests, is_accept_social_request_tool, social_request_kind, social_response_request_type_for_tool
from app.social.relationship_stage import (
    NEGATIVE_RELATIONSHIP_TOOL_NAMES,
    PARTNER_FAMILY_PLANNING_TOOL_NAMES,
    RELATIONSHIP_STAGE_TOOL_NAMES,
    relationship_option_priority,
    relationship_tool_allowed_for_target,
    target_sort_key_for_tool,
)
from app.tools.tool_specs import SOFT_EXPRESSION_CORE_TOOL_IDS, ToolSpec
from app.tools.validators import tool_requires_speech, validate_tool
from app.world.corpses import CORPSE_TOOL_NAMES, visible_corpses_at_location
from app.world.visibility import adjacent_location_ids, build_visible_people
from app.world.werewolf import werewolf_agent_facing_location_name


TEXT_SLOT_BY_TOOL = {
    "speak_to_nearby": "speech",
    "say_to_visible_agent": "speech",
    "wake_visible_agent": "speech",
    "ask_visible_agent_to_introduce": "speech",
    "introduce_self": "speech",
    "refuse_introduction": "speech",
    "compliment_visible_agent": "speech",
    "apologize_to_visible_agent": "speech",
    "casual_chat_visible_agent": "speech",
    "ask_about_needs": "speech",
    "comfort_visible_agent": "speech",
    "invite_visible_agent_to_walk": "speech",
    "ask_for_help_from_visible_agent": "speech",
    "set_boundary_visible_agent": "speech",
    "thank_visible_agent": "speech",
    "discuss_feelings_visible_agent": "speech",
    "express_dislike_visible_agent": "speech",
    "criticize_behavior_visible_agent": "speech",
    "reject_closeness_visible_agent": "speech",
    "accept_social_request_visible_agent": "speech",
    "decline_social_request_visible_agent": "speech",
    "protest_forced_action_visible_agent": "speech",
    "express_affection_visible_agent": "speech",
    "ask_date_visible_agent": "speech",
    "hold_hands_visible_agent": "speech",
    "hug_visible_agent": "speech",
    "confess_feelings_visible_agent": "speech",
    "define_relationship_visible_agent": "speech",
    "discuss_romantic_boundaries_visible_agent": "speech",
    "break_up_visible_agent": "speech",
    "repair_relationship_visible_agent": "speech",
    "force_hug_visible_agent": "speech",
    "force_hold_hands_visible_agent": "speech",
    "force_comfort_visible_agent": "speech",
    "force_help_visible_agent": "speech",
    "force_walk_together_visible_agent": "speech",
    "force_date_visible_agent": "speech",
    "force_relationship_claim_visible_agent": "speech",
    "attempt_forced_adult_boundary_visible_agent": "speech",
    "call_community_meeting": "content",
    "propose_social_rule": "content",
    "support_social_rule": "content",
    "oppose_social_rule": "content",
    "write_diary": "content",
    "write_private_note": "content",
    "post_notice": "content",
    "add_memory": "content",
    "tell_story_nearby": "speech",
    "sing_nearby": "speech",
    "mourn_visible_corpse": "speech",
    "request_adult_intimacy_visible_agent": "speech",
    "accept_adult_intimacy_visible_agent": "speech",
    "decline_adult_intimacy_visible_agent": "speech",
    "react_infidelity_angry_visible_agent": "speech",
    "react_infidelity_forgive_visible_agent": "speech",
    "react_infidelity_excited_visible_agent": "speech",
    "request_food_help": "speech",
    "request_water_help": "speech",
    "seek_help": "speech",
    "confront_visible_agent_about_crime": "speech",
    "werewolf_speak": "speech",
    "werewolf_rebut": "speech",
    "werewolf_reply_rebuttal": "speech",
    "werewolf_wolf_discuss": "speech",
    "werewolf_record_reasoning": "content",
    "werewolf_summarize_clues": "content",
    "market_search_goods": "item_query",
    "market_buy_goods": "item_query",
}

DISABLED_GROUP_CHAT_TOOLS = {"tool_group_start_chat", "tool_group_join_chat", "tool_group_leave_chat"}

VALUE_SLOT_BY_TOOL = {
    "sleep": ("sleep_hours", 1.0, 10.0, 8, "小时"),
    "sleep_rough": ("sleep_hours", 1.0, 10.0, 6, "小时"),
    "v6_deposit_to_broker": ("amount", 1, 9999, 20, "金额"),
    "v6_withdraw_from_broker": ("amount", 1, 9999, 20, "金额"),
    "v6_repay_extra_principal": ("amount", 1, 9999, 20, "金额"),
}

LOCATION_PARAM_TOOLS = {"move_to_location", "wander", "knock_private_room", "attempt_burglary_private_room", "home_invasion_robbery_private_room", "v6_walk_to_destination", "v6_take_bus", "v6_ride_bicycle", "v6_drive_car"}
CATALOG_LOCATION_PARAM_TOOLS = {
    "tool_perceive_mark_location",
    "tool_location_knock_door",
    "tool_location_open_door",
    "tool_location_close_door",
    "tool_move_flee_location",
}
HIDDEN_ACTION_MENU_TOOLS = {
    # System/meta rollout helpers are hard-rule internals, never agent-facing choices.
    "system_crime_roll_success",
    "system_crime_roll_detection",
    "system_crime_roll_identification",
    "system_crime_apply_secret_theft",
    "system_crime_create_unknown_loss",
    "system_crime_roll_later_notice_loss",
    "system_crime_generate_suspicion",
    "system_crime_witness_awareness",
    "system_crime_victim_awareness",
    "system_crime_secret_viewer_log",
    "system_crime_guilt_paranoia_after_secret",
    "system_crime_confession_candidate",
    "system_crime_failed_attempt_record",
    "system_crime_minor_case_priority",
    "system_crime_violent_mandatory_case",
    # Abstract v5 duplicates that conflict with stronger hard-coded survival/move tools.
    "tool_body_sleep",
    "tool_body_wake_up",
    "tool_body_rest_short",
    "tool_body_nap",
    "tool_body_eat_raw_food",
    "tool_body_eat_meal",
    "tool_body_drink_water",
    "tool_body_bathe",
    "tool_perceive_look_around",
    "tool_move_to_location",
    "tool_location_enter_room",
    "tool_location_leave_room",
    "tool_location_knock_door",
    "tool_location_open_door",
    "tool_location_close_door",
    "tool_move_flee_location",
    "tool_work_start_shift",
    "request_more_candidate_tools",
    "explain_available_tools",
} | set(SOFT_EXPRESSION_CORE_TOOL_IDS)
STOCK_PARAM_TOOLS = {
    "v6_read_market_news",
    "v6_research_company_fundamentals",
    "v6_review_price_chart",
    "v6_place_market_buy_order",
    "v6_place_market_sell_order",
    "v6_set_stop_loss_order",
    "v6_set_take_profit_order",
    "v6_buy_stock_on_margin",
    "v6_short_sell_stock",
    "v6_buy_to_cover_short",
    "v6_panic_sell",
    "v6_take_profit_calmly",
    "v6_reduce_leveraged_position",
}
ITEM_FROM_INVENTORY_TOOLS = {"give_item_to_visible_agent", "offer_item_to_visible_agent", "eat_inventory_food", "place_inventory_item", "transfer_item_to_visible_agent", "gift_item_to_visible_agent"}
ITEM_FROM_LOCATION_TOOLS = {"pick_up_item", "pick_up_placed_item"}
ITEM_FREE_NAME_TOOLS = {"craft_simple_item"}
MARKET_ACTION_TOOLS = {"market_search_goods", "market_recommend_goods", "market_buy_goods", "eat_inventory_food", "place_inventory_item", "pick_up_placed_item", "transfer_item_to_visible_agent", "gift_item_to_visible_agent"}
RISK_TOOLS_PREFIXES = ("force_", "attempt_", "demand_", "attack_", "home_invasion")
NEGATIVE_TOOLS = {"bury_visible_corpse", "work_overtime_shift", "jail_low_paid_work"}

EN_TOOL_LABELS: dict[str, str] = {
    "look_around": "look around",
    "check_self_status": "check myself",
    "do_nothing": "do nothing",
    "speak_to_nearby": "speak publicly",
    "say_to_visible_agent": "speak to",
    "wake_visible_agent": "wake",
    "introduce_self": "introduce myself to",
    "refuse_introduction": "refuse to introduce myself to",
    "ask_visible_agent_to_introduce": "ask for an introduction from",
    "move_to_location": "go to",
    "wander": "go to",
    "return_home": "return home",
    "sleep": "sleep",
    "sleep_rough": "sleep rough",
    "rest": "rest",
    "eat_food": "eat a meal",
    "drink_water": "drink water",
    "go_eat_food": "go eat",
    "go_drink_water": "go drink water",
    "wash": "wash",
    "check_supplies": "check supplies",
    "eat_portable_food": "eat portable food",
    "drink_bottled_water": "drink bottled water",
    "fill_canteen": "fill canteen",
    "pack_lunch": "pack food",
    "buy_portable_food": "buy portable food",
    "buy_bottled_water": "take bottled water",
    "request_food_help": "ask for food help",
    "request_water_help": "ask for water help",
    "accept_community_aid": "accept community aid",
    "apply_for_job": "apply for a job",
    "do_odd_job": "do odd work",
    "work_shift_cafeteria": "work cafeteria shift",
    "work_shift_cook": "work kitchen shift",
    "work_shift_cleaner": "work cleaning shift",
    "work_shift_night_guard": "work night guard shift",
    "work_overtime_shift": "work overtime",
    "take_work_break": "take a work break",
    "complain_about_work": "complain about work",
    "quit_job": "quit job",
    "compliment_visible_agent": "compliment",
    "apologize_to_visible_agent": "apologize to",
    "casual_chat_visible_agent": "chat with",
    "ask_about_needs": "ask about needs of",
    "comfort_visible_agent": "comfort",
    "invite_visible_agent_to_walk": "invite for a walk",
    "ask_for_help_from_visible_agent": "ask help from",
    "set_boundary_visible_agent": "set boundary with",
    "thank_visible_agent": "thank",
    "discuss_feelings_visible_agent": "discuss feelings with",
    "express_dislike_visible_agent": "express dislike to",
    "criticize_behavior_visible_agent": "criticize behavior of",
    "reject_closeness_visible_agent": "reject closeness with",
    "accept_social_request_visible_agent": "accept request from",
    "decline_social_request_visible_agent": "decline request from",
    "dodge_forced_action_visible_agent": "dodge sudden action from",
    "allow_forced_action_visible_agent": "allow sudden action from",
    "protest_forced_action_visible_agent": "protest to",
    "express_affection_visible_agent": "express affection to",
    "ask_date_visible_agent": "ask on a date",
    "hold_hands_visible_agent": "ask to hold hands with",
    "hug_visible_agent": "ask to hug",
    "confess_feelings_visible_agent": "confess feelings to",
    "define_relationship_visible_agent": "define relationship with",
    "discuss_romantic_boundaries_visible_agent": "discuss romantic boundaries with",
    "break_up_visible_agent": "break up with",
    "repair_relationship_visible_agent": "repair relationship with",
    "force_hug_visible_agent": "suddenly hug",
    "force_hold_hands_visible_agent": "suddenly hold hands with",
    "force_comfort_visible_agent": "actively comfort",
    "force_help_visible_agent": "actively help",
    "force_walk_together_visible_agent": "pull into walking together with",
    "force_date_visible_agent": "push into a date-like interaction with",
    "force_relationship_claim_visible_agent": "claim relationship with",
    "attempt_forced_adult_boundary_visible_agent": "attempt severe adult-boundary violation against",
    "request_adult_intimacy_visible_agent": "request private adult intimacy with",
    "accept_adult_intimacy_visible_agent": "accept private adult intimacy with",
    "decline_adult_intimacy_visible_agent": "decline private adult intimacy with",
    "react_infidelity_angry_visible_agent": "react angrily to infidelity by",
    "react_infidelity_forgive_visible_agent": "forgive infidelity by",
    "react_infidelity_excited_visible_agent": "react excitedly to infidelity by",
    "call_community_meeting": "call a community meeting",
    "propose_social_rule": "propose a social rule",
    "support_social_rule": "support a social rule",
    "oppose_social_rule": "oppose a social rule",
    "market_search_goods": "search purchasable goods",
    "market_recommend_goods": "view recommended goods",
    "market_buy_goods": "buy goods",
    "eat_inventory_food": "use inventory supply",
    "place_inventory_item": "put down",
    "pick_up_placed_item": "pick up",
    "transfer_item_to_visible_agent": "hand item to",
    "gift_item_to_visible_agent": "gift item to",
    "write_diary": "write diary",
    "write_private_note": "write private note",
    "post_notice": "post notice",
    "add_memory": "record memory",
    "clear_notice_board": "clear notice board",
    "tell_story_nearby": "tell a story nearby",
    "sing_nearby": "sing nearby",
    "walk_by_lake": "walk by the lake",
    "clean_current_location": "clean this location",
    "play_simple_game": "play a simple game",
    "read_quietly": "read quietly",
    "practice_skill": "practice a skill",
    "enjoy_scenery": "enjoy the scenery",
    "hum_to_self": "hum to myself",
    "review_recent_memory": "review recent memory",
    "organize_inventory": "organize inventory",
    "plan_day": "plan the day",
    "meditate": "meditate",
    "tidy_room": "tidy room",
    "clean_clothes": "clean clothes",
    "take_short_walk": "take a short walk",
    "sketch_or_doodle": "sketch or doodle",
    "breathe_fresh_air": "breathe fresh air",
    "inspect_visible_corpse": "inspect",
    "mourn_visible_corpse": "mourn",
    "report_visible_corpse": "report",
    "bury_visible_corpse": "bury",
    "avoid_corpse_area": "avoid corpse area",
    "check_child_status_visible_agent": "check child status of",
    "soothe_child_visible_agent": "soothe",
    "feed_child_visible_agent": "feed",
    "carry_child_visible_agent": "carry",
    "put_child_to_sleep_visible_agent": "put to sleep",
    "care_for_child_visible_agent": "care for",
    "teach_child_simple_skill_visible_agent": "teach simple skill to",
    "werewolf_summarize_clues": "summarize Werewolf clues",
    "werewolf_record_reasoning": "record Werewolf reasoning",
    "werewolf_speak": "speak in Werewolf meeting",
    "werewolf_end_speech": "end Werewolf speech",
    "werewolf_rebut": "rebut",
    "werewolf_skip_rebuttal": "skip rebuttal",
    "werewolf_reply_rebuttal": "reply to rebuttal",
    "werewolf_drop_debate": "drop debate",
    "werewolf_vote_by_name": "vote against",
    "werewolf_review_vote_history": "review vote history",
    "werewolf_wolf_discuss": "discuss as werewolf",
    "werewolf_kill_by_name": "night kill",
    "werewolf_seer_check_by_name": "seer check",
    "werewolf_coroner_check_latest": "check latest dead role",
    "werewolf_guard_protect_by_name": "guard protect",
    "werewolf_witch_save_latest": "witch save latest victim",
    "werewolf_witch_reveal_saved_attack": "witch reveal saved attack",
    "werewolf_witch_poison_by_name": "witch poison",
    "werewolf_hunter_shoot_by_name": "hunter shoot",
    "werewolf_medium_check_latest": "medium check latest dead alignment",
    "werewolf_idiot_reveal_self": "idiot reveal role",
    "cry_for_food": "cry for food",
    "cry_for_comfort": "cry for comfort",
    "child_sleep": "sleep as a child",
    "observe_parent": "observe guardian",
    "signal_need": "signal need",
    "ask_help_child": "ask for help as a child",
}

def build_action_options(
    session: Session,
    world: World,
    agent: Agent,
    tools: list[ToolSpec],
    ref_map: dict[str, str],
    *,
    reaction: bool = False,
    limit: int | None = None,
) -> list[ActionOption]:
    location = agent.location.location if agent.location else None
    options: list[ActionOption] = []
    for spec in tools:
        options.extend(_expand_spec(session, world, agent, location, spec, ref_map, reaction=reaction))
    filtered = _dedupe_options(_filter_valid_options(session, world, agent, options, reaction=reaction))
    ordered = _order_options(session, world, agent, filtered)
    if world_language(world) == "en":
        ordered = [_englishize_option(option) for option in ordered]
    max_count = limit or _default_limit(agent, reaction=reaction)
    capped = _cap_action_options(agent, ordered, max_count)
    return [option_with_id(option, idx) for idx, option in enumerate(capped)]


def option_with_id(option: ActionOption, idx: int) -> ActionOption:
    option.option_id = idx
    return option


def _expand_spec(
    session: Session,
    world: World,
    agent: Agent,
    location: Location | None,
    spec: ToolSpec,
    ref_map: dict[str, str],
    *,
    reaction: bool,
) -> list[ActionOption]:
    name = spec.tool_name
    if name.startswith(("system_", "tool_meta_", "system_filter_", "v6_system_")) or name in HIDDEN_ACTION_MENU_TOOLS:
        return []
    if not location:
        return [_base_option(spec, "什么也不做", {})] if name == "do_nothing" else []
    if name in CORPSE_TOOL_NAMES:
        return _corpse_options(session, world, agent, spec)
    if name in LOCATION_PARAM_TOOLS or (spec.target_policy == "location" and name in CATALOG_LOCATION_PARAM_TOOLS):
        return _location_options(session, agent, location, spec)
    if spec.target_policy == "location":
        return []
    if name in STOCK_PARAM_TOOLS:
        return _stock_options(world, spec)
    if spec.target_policy == "visible_ref":
        return _visible_ref_options(session, world, agent, spec, ref_map)
    if spec.target_policy == "known_name":
        return _known_name_options(session, agent, spec)
    if spec.target_policy == "item":
        return _item_options(session, agent, location, spec)
    return _none_options(spec)


def _none_options(spec: ToolSpec) -> list[ActionOption]:
    name = spec.tool_name
    label = _label_for_tool(spec)
    if name == "return_home":
        return [
            _base_option(spec, "回到自己的住所", {}),
            _base_option(
                spec,
                "回家后直接睡觉",
                {"sleep_after_arrival": True},
                value_slot="sleep_hours",
                min_value=1,
                max_value=10,
                default_value=8,
                value_hint="小时",
            ),
        ]
    kwargs = _slot_kwargs(name)
    return [_base_option(spec, label, {}, **kwargs)]


def _visible_ref_options(session: Session, world: World, agent: Agent, spec: ToolSpec, ref_map: dict[str, str]) -> list[ActionOption]:
    options: list[ActionOption] = []
    labels = _visible_ref_labels(session, world, agent)
    if spec.tool_name in SOCIAL_REQUEST_RESPONSE_TOOLS:
        expected_type = social_response_request_type_for_tool(spec.tool_name)
        action_label = "接受" if is_accept_social_request_tool(spec.tool_name) else "拒绝"
        pending_requests = incoming_social_requests(agent, world.current_world_time_minutes)
        for ref in sorted(ref_map):
            target_label = labels.get(ref, ref)
            target_id = ref_map[ref]
            for request in pending_requests:
                if request.get("from_agent_id") != target_id:
                    continue
                request_type = str(request.get("request_type") or "")
                if expected_type and request_type != expected_type:
                    continue
                kind = social_request_kind(request_type)
                params: dict[str, Any] = {"visible_ref": ref, "request_id": request.get("request_id"), "request_type": request_type}
                options.append(_base_option(spec, f"{action_label}{target_label}的{kind.title}请求", params, **_slot_kwargs(spec.tool_name)))
        return options
    if spec.tool_name in FORCED_SOCIAL_RESPONSE_TOOLS:
        action_label = "躲开" if spec.tool_name == "dodge_forced_action_visible_agent" else "默许" if spec.tool_name == "allow_forced_action_visible_agent" else "抗议"
        pending_forced = incoming_forced_actions(agent, world.current_world_time_minutes)
        for ref in sorted(ref_map):
            target_label = labels.get(ref, ref)
            target_id = ref_map[ref]
            for request in pending_forced:
                if request.get("from_agent_id") != target_id:
                    continue
                action_type = str(request.get("action_type") or "hug")
                kind = forced_action_kind(action_type)
                params = {"visible_ref": ref, "forced_action_id": request.get("forced_action_id"), "action_type": action_type}
                options.append(_base_option(spec, f"{action_label}{target_label}的{kind.title}", params, **_slot_kwargs(spec.tool_name)))
        return options
    if spec.tool_name in ITEM_FROM_INVENTORY_TOOLS:
        item_names = _inventory_item_names(session, agent, limit=8)
        if not item_names:
            return []
        target_choices: list[dict[str, Any]] = []
        for ref in sorted(ref_map):
            target_label = labels.get(ref, ref)
            target_id = ref_map[ref]
            for item_name in item_names:
                target_choices.append(
                    {
                        "id": 0,
                        "label": f"{target_label} <- {item_name}",
                        "params": {"visible_ref": ref, "item_name": item_name},
                        "target_agent_id": target_id,
                    }
                )
        for idx, choice in enumerate(target_choices[:24], start=1):
            choice["id"] = idx
        target_choices = [choice for choice in target_choices if choice.get("id")]
        if not target_choices:
            return []
        return [
            _base_option(
                spec,
                _label_for_tool(spec),
                {},
                target_choices=tuple(target_choices),
                **_slot_kwargs(spec.tool_name),
            )
        ]
    target_choices: list[dict[str, Any]] = []
    refs = list(sorted(ref_map))
    if spec.tool_name in RELATIONSHIP_STAGE_TOOL_NAMES:
        refs.sort(key=lambda ref: target_sort_key_for_tool(session, agent, ref_map.get(ref, ""), spec.tool_name))
    for ref in refs:
        target_id = ref_map.get(ref)
        target = session.get(Agent, target_id) if target_id else None
        if spec.tool_name in RELATIONSHIP_STAGE_TOOL_NAMES and not relationship_tool_allowed_for_target(session, world, agent, target, spec.tool_name):
            continue
        params: dict[str, Any] = {"visible_ref": ref}
        if spec.tool_name in INFIDELITY_RESPONSE_TOOL_NAMES:
            if not target_id:
                continue
            pending = pending_infidelity_response_from(agent, target_id, world.current_world_time_minutes)
            if not pending:
                continue
            params["response_id"] = pending.get("response_id")
        if spec.tool_name == "introduce_self":
            params.update({"reveal_name": True, "reveal_gender": True})
        if spec.tool_name == "grant_personal_resource_permission_visible_agent":
            params.update({"resource_scope": "home", "resource_label": "我的小屋"})
        target_choices.append({"id": 0, "label": labels.get(ref, ref), "params": params, "target_agent_id": target_id})
    if not target_choices:
        return []
    for idx, choice in enumerate(target_choices, start=1):
        choice["id"] = idx
    return [
        _base_option(
            spec,
            _label_for_tool(spec),
            {},
            target_choices=tuple(target_choices),
            **_slot_kwargs(spec.tool_name),
        )
    ]


def _visible_ref_labels(session: Session, world: World, agent: Agent) -> dict[str, str]:
    labels: dict[str, str] = {}
    for person in build_visible_people(session, agent, world.current_world_time_minutes, persist=False):
        labels[person.visible_ref] = person.known_name if person.known_name != "未知" else person.short_label
    return labels


def _inventory_item_names(session: Session, agent: Agent, *, limit: int = 12) -> list[str]:
    rows = session.execute(
        select(Item.name)
        .join(Inventory, Inventory.item_id == Item.item_id)
        .where(Inventory.agent_id == agent.agent_id, Inventory.quantity > 0)
        .order_by(Item.name.asc())
        .limit(limit)
    )
    return [name for (name,) in rows if name]


def _known_name_options(session: Session, agent: Agent, spec: ToolSpec) -> list[ActionOption]:
    rows = session.execute(
        select(IdentityKnowledge)
        .where(IdentityKnowledge.observer_agent_id == agent.agent_id, IdentityKnowledge.name_known.is_(True))
        .order_by(IdentityKnowledge.last_seen_at.desc().nullslast(), IdentityKnowledge.known_name.asc())
        .limit(12)
    ).scalars()
    target_choices: list[dict[str, Any]] = []
    for idx, row in enumerate([row for row in rows if row.known_name], start=1):
        target_choices.append({"id": idx, "label": row.known_name, "params": {"known_name": row.known_name}})
    if not target_choices:
        return []
    return [
        _base_option(
            spec,
            _label_for_tool(spec),
            {},
            target_choices=tuple(target_choices),
            **_slot_kwargs(spec.tool_name),
        )
    ]


def _location_options(session: Session, agent: Agent, location: Location, spec: ToolSpec) -> list[ActionOption]:
    options: list[ActionOption] = []
    for loc_id in adjacent_location_ids(session, location):
        loc = session.get(Location, loc_id)
        if not loc:
            continue
        if not _location_candidate_allowed(session, agent, loc, spec):
            continue
        if spec.tool_name == "wander":
            action = "漫步到"
        elif spec.tool_name == "move_to_location" or spec.tool_name.startswith("v6_"):
            action = "去"
        else:
            action = _label_for_tool(spec)
        params = {"location_id": loc.location_id}
        world = session.get(World, agent.world_id)
        visible_name = werewolf_agent_facing_location_name(world, loc)
        options.append(_base_option(spec, f"{action}{visible_name}", params, **_slot_kwargs(spec.tool_name)))
    return options


def _location_candidate_allowed(session: Session, agent: Agent, loc: Location, spec: ToolSpec) -> bool:
    """Keep private-room and abstract-door choices out of ordinary movement menus.

    A private residence is not a normal public destination. Earlier menus exposed every
    adjacent villager room as ``move_to_location`` from the shared dormitory, so agents
    repeatedly selected other people's rooms and the event feed devolved into vague
    "private space" failures. The menu should only show: own/permitted rooms for
    ordinary movement, other people's rooms for explicit knock/crime tools, and no
    half-implemented catalog door controls.
    """
    tags = set(loc.tags_json or [])
    tool = spec.tool_name
    if "private" not in tags:
        return True
    own_home = _own_home_location_id(agent)
    if tool in {"move_to_location", "wander", "v6_walk_to_destination", "v6_take_bus", "v6_ride_bicycle", "v6_drive_car"}:
        return loc.location_id == own_home or _has_private_room_permission_for_menu(session, agent, loc)
    if tool == "knock_private_room":
        return loc.location_id != own_home
    if tool in {"attempt_burglary_private_room", "home_invasion_robbery_private_room"}:
        return loc.location_id != own_home
    # Catalog room/door tools are abstract descriptors unless explicitly hard-coded;
    # do not let them target private homes as if they were real access-control tools.
    if tool.startswith("tool_location_") or tool.startswith("tool_move_"):
        return False
    return loc.location_id == own_home


def _own_home_location_id(agent: Agent) -> str | None:
    return ((agent.wallet_json or {}).get("housing") or {}).get("home_location_id")


def _has_private_room_permission_for_menu(session: Session, agent: Agent, loc: Location) -> bool:
    owner = _private_home_owner_for_menu(session, agent.world_id, loc.location_id)
    if not owner or owner.agent_id == agent.agent_id:
        return False
    for grant in (owner.wallet_json or {}).get("permissions_granted") or []:
        if grant.get("to_agent_id") != agent.agent_id or grant.get("active") is False:
            continue
        scope = str(grant.get("resource_scope") or "")
        if scope == "all_personal_resources":
            return True
        if scope in {"home", "private_room"} and grant.get("resource_id") == loc.location_id:
            return True
    return False


def _private_home_owner_for_menu(session: Session, world_id: str, location_id: str) -> Agent | None:
    rows = session.execute(select(Agent).where(Agent.world_id == world_id, Agent.lifecycle_state.in_(["alive", "critical"]))).scalars()
    for candidate in rows:
        if ((candidate.wallet_json or {}).get("housing") or {}).get("home_location_id") == location_id:
            return candidate
    return None


def _corpse_options(session: Session, world: World, agent: Agent, spec: ToolSpec) -> list[ActionOption]:
    corpses = visible_corpses_at_location(session, world, agent.location.location_id if agent.location else None)
    options: list[ActionOption] = []
    for corpse in corpses:
        ref = str(corpse.get("corpse_ref") or corpse.get("corpse_id") or "尸体A")
        label = f"{_label_for_tool(spec)} {ref}"
        options.append(_base_option(spec, label, {"corpse_ref": ref}, **_slot_kwargs(spec.tool_name)))
    return options


def _item_options(session: Session, agent: Agent, location: Location, spec: ToolSpec) -> list[ActionOption]:
    names: list[str] = []
    if spec.tool_name in ITEM_FROM_LOCATION_TOOLS:
        rows = session.execute(select(Item).where(Item.location_id == location.location_id).order_by(Item.name.asc()).limit(12)).scalars()
        names = [item.name for item in rows if item.name]
    elif spec.tool_name in ITEM_FROM_INVENTORY_TOOLS:
        names = _inventory_item_names(session, agent)
    elif spec.tool_name in ITEM_FREE_NAME_TOOLS:
        names = ["手作小物"]
    return [_base_option(spec, f"{_label_for_tool(spec)} {item_name}", {"item_name": item_name}, **_slot_kwargs(spec.tool_name)) for item_name in names]


def _stock_options(world: World, spec: ToolSpec) -> list[ActionOption]:
    try:
        market = v6_economy._market(world)  # noqa: SLF001 - game-internal helper; used only to expose fictional tickers.
        tickers = sorted((market.get("stocks") or {}).keys()) or sorted(v6_economy.MARKET_TICKERS.keys())
    except Exception:
        tickers = sorted(v6_economy.MARKET_TICKERS.keys())
    options = []
    for ticker in tickers[:8]:
        options.append(_base_option(spec, f"{_label_for_tool(spec)} {ticker}", {"ticker": ticker}, **_slot_kwargs(spec.tool_name)))
    return options


def _base_option(
    spec: ToolSpec,
    label: str,
    params: dict[str, Any],
    *,
    value_slot: str | None = None,
    text_slot: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    default_value: Any | None = None,
    value_hint: str | None = None,
    target_choices: tuple[dict[str, Any], ...] = (),
) -> ActionOption:
    tags: list[str] = []
    if any(spec.tool_name.startswith(prefix) for prefix in RISK_TOOLS_PREFIXES) or "crime" in (spec.catalog_category or "").lower():
        tags.append("风险")
    if spec.tool_name in NEGATIVE_TOOLS:
        tags.append("负收益")
    if spec.hard_effect_id == "worldpack_declarative":
        tags.append("世界观")
    resolved_text_slot = text_slot or _text_slot_for_spec(spec)
    return ActionOption(
        option_id=-1,
        label=_short_label(label),
        tool_name=spec.tool_name,
        params=dict(params),
        value_slot=value_slot,
        text_slot=resolved_text_slot,
        min_value=min_value,
        max_value=max_value,
        default_value=default_value,
        value_hint=value_hint,
        text_required=bool(resolved_text_slot and (tool_requires_speech(spec.tool_name, spec) or resolved_text_slot in {"content", "item_query"})),
        tags=tuple(tags),
        target_choices=target_choices,
    )


def _text_slot_for_spec(spec: ToolSpec) -> str | None:
    explicit = TEXT_SLOT_BY_TOOL.get(spec.tool_name)
    if explicit:
        return explicit
    if tool_requires_speech(spec.tool_name, spec):
        return "speech"
    return None


def _slot_kwargs(tool_name: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if tool_name in VALUE_SLOT_BY_TOOL:
        slot, min_value, max_value, default_value, hint = VALUE_SLOT_BY_TOOL[tool_name]
        kwargs.update(value_slot=slot, min_value=min_value, max_value=max_value, default_value=default_value, value_hint=hint)
    if tool_name in TEXT_SLOT_BY_TOOL:
        kwargs["text_slot"] = TEXT_SLOT_BY_TOOL[tool_name]
    return kwargs


def _filter_valid_options(session: Session, world: World, agent: Agent, options: Iterable[ActionOption], *, reaction: bool) -> list[ActionOption]:
    option_list = list(options)
    valid: list[ActionOption] = []
    for option in option_list:
        if option.target_choices:
            filtered_choices: list[dict[str, Any]] = []
            for choice in option.target_choices:
                choice_params = choice.get("params") if isinstance(choice, dict) else None
                params = _params_for_validation(option, choice_params if isinstance(choice_params, dict) else None)
                result = validate_tool(
                    session,
                    actor=agent,
                    tool_name=option.tool_name,
                    params=params,
                    world_time=world.current_world_time_minutes,
                    reaction=reaction,
                    persist_visibility=False,
                )
                if result.ok:
                    filtered_choices.append(choice)
            if filtered_choices:
                valid.append(replace(option, target_choices=tuple(filtered_choices)))
            continue

        params = _params_for_validation(option)
        result = validate_tool(
            session,
            actor=agent,
            tool_name=option.tool_name,
            params=params,
            world_time=world.current_world_time_minutes,
            reaction=reaction,
            persist_visibility=False,
        )
        if result.ok:
            valid.append(option)
    if not valid:
        fallback = next((option for option in option_list if option.tool_name == "do_nothing"), None)
        if fallback:
            valid.append(fallback)
    return valid


def _params_for_validation(option: ActionOption, override_params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(option.params or {})
    if override_params:
        params.update(override_params)
    if option.value_slot:
        params[option.value_slot] = option.default_value if option.default_value is not None else 1
    if option.text_slot:
        params[option.text_slot] = "我想根据眼前情况认真回应。"
        if option.text_slot == "speech":
            params.setdefault("tone", "neutral")
    if option.tool_name == "write_diary":
        params.setdefault("title", "今天的记录")
        params.setdefault("content", "今天发生的事让我想记下来，这些细节可能会影响我之后怎么生活和理解别人。")
    return params


def _englishize_option(option: ActionOption) -> ActionOption:
    params = dict(option.params or {})
    label = _english_label(option.tool_name, params, option.label)
    tags = tuple({"风险": "risk", "负收益": "costly", "世界观": "world"}.get(tag, english_safe_label(tag, fallback="tag")) for tag in option.tags)
    hint = option.value_hint
    if hint in {"小时", "hour"}:
        hint = "hours"
    elif hint in {"金额", "money"}:
        hint = "amount"
    elif hint in {"数量", "shares"}:
        hint = "quantity"
    return ActionOption(
        option_id=option.option_id,
        label=_short_label(label),
        tool_name=option.tool_name,
        params=params,
        value_slot=option.value_slot,
        text_slot=option.text_slot,
        text_required=option.text_required,
        min_value=option.min_value,
        max_value=option.max_value,
        default_value=option.default_value,
        value_hint=hint,
        tone=option.tone,
        risk_note="risk" if option.risk_note else None,
        tags=tags,
        target_choices=tuple(_englishize_target_choice(choice) for choice in option.target_choices),
    )


def _englishize_target_choice(choice: dict[str, Any]) -> dict[str, Any]:
    params = dict(choice.get("params") or {})
    label = str(choice.get("label") or choice.get("id") or "target")
    if "visible_ref" in params:
        label = person_ref_label(str(params.get("visible_ref")), "en")
        if "item_name" in params:
            label = f"{label} <- {item_label(str(params.get('item_name')), 'en')}"
    elif "known_name" in params:
        label = english_safe_label(label, fallback="known person")
    result = {"id": choice.get("id"), "label": label, "params": params}
    if choice.get("target_agent_id"):
        result["target_agent_id"] = choice.get("target_agent_id")
    return result


def _english_label(tool_name: str, params: dict[str, Any], original: str) -> str:
    base = EN_TOOL_LABELS.get(tool_name) or _humanize_tool_name(tool_name)
    if tool_name == "return_home" and params.get("sleep_after_arrival"):
        return "return home and sleep"
    if "visible_ref" in params:
        return f"{base} {person_ref_label(str(params.get('visible_ref')), 'en')}"
    if "known_name" in params:
        return f"{base} {english_safe_label(params.get('known_name'), fallback='known person')}"
    if "location_id" in params:
        key = str(params.get("location_id") or "").split(":", 1)[-1]
        fake_loc = type("_Loc", (), {"location_id": params.get("location_id"), "public_name": key})()
        return f"{base} {location_label(fake_loc, 'en')}"
    if "corpse_ref" in params:
        return f"{base} {corpse_ref_label(str(params.get('corpse_ref')), 'en')}"
    if "item_name" in params:
        return f"{base} {item_label(str(params.get('item_name')), 'en')}"
    if "ticker" in params:
        return f"{base} {params.get('ticker')}"
    return english_safe_label(base or original, fallback=_humanize_tool_name(tool_name))


def _humanize_tool_name(tool_name: str) -> str:
    name = str(tool_name or "action")
    for prefix in ["tool_", "v6_", "v5_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.replace("_visible_agent", "").replace("_", " ")


def _dedupe_options(options: list[ActionOption]) -> list[ActionOption]:
    seen: set[tuple[str, tuple[tuple[str, str], ...], str | None, str | None]] = set()
    result: list[ActionOption] = []
    for option in options:
        key = (
            option.tool_name,
            tuple(sorted((key, str(value)) for key, value in (option.params or {}).items())),
            option.value_slot,
            option.text_slot,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(option)
    return result


def _order_options(session: Session, world: World, agent: Agent, options: list[ActionOption]) -> list[ActionOption]:
    state = agent.dynamic_state

    def option_target_ids(option: ActionOption) -> list[str]:
        ids: list[str] = []
        for choice in option.target_choices:
            if not isinstance(choice, dict):
                continue
            target_id = choice.get("target_agent_id")
            if target_id:
                ids.append(str(target_id))
        return ids

    def score(option: ActionOption) -> tuple[int, str]:
        name = option.tool_name
        priority = 50
        if state and state.hydration < 65 and name in {"go_drink_water", "drink_water", "drink_bottled_water", "buy_bottled_water", "fill_canteen", "request_water_help", "accept_community_aid"}:
            priority = 0
        elif state and state.satiety < 60 and name in {"go_eat_food", "eat_food", "eat_portable_food", "buy_portable_food", "pack_lunch", "request_food_help", "accept_community_aid"}:
            priority = 1
        elif state and state.energy < 40 and name in {"sleep", "sleep_rough", "return_home", "rest", "take_work_break"}:
            priority = 2
        elif state and state.hygiene < 35 and name in {"wash", "clean_clothes", "tidy_room", "return_home"}:
            priority = 3
        elif name in {"accept_social_request_visible_agent", "decline_social_request_visible_agent", "dodge_forced_action_visible_agent", "allow_forced_action_visible_agent", "protest_forced_action_visible_agent"} | INFIDELITY_RESPONSE_TOOL_NAMES:
            priority = 4
        else:
            relationship_priority = relationship_option_priority(session, agent, name, option_target_ids(option))
            if relationship_priority is not None:
                priority = relationship_priority
            elif name in NEGATIVE_RELATIONSHIP_TOOL_NAMES:
                stress = state.stress if state else 0
                aggression = agent.traits.aggression if agent.traits else 50
                honesty = agent.traits.honesty if agent.traits else 50
                priority = 13 if stress >= 55 or aggression >= 58 or honesty >= 68 else 22
            elif name in CORPSE_TOOL_NAMES:
                priority = 5
            elif name in {"attempt_petty_theft_visible_agent", "demand_money_visible_agent", "attack_visible_agent", "attempt_burglary_private_room", "home_invasion_robbery_private_room", "attempt_forced_adult_boundary_visible_agent"}:
                money_pressure = False
                survival_crisis = bool(state and (state.health < 35 or state.energy < 12 or state.satiety < 14 or state.hydration < 14))
                try:
                    from app.agents.v5_state import wallet_money
                    money_pressure = wallet_money(agent) < 8
                except Exception:
                    money_pressure = False
                aggression = agent.traits.aggression if agent.traits else 20
                stress = state.stress if state else 0
                priority = 5 if survival_crisis else 6 if (money_pressure or aggression >= 70 or stress >= 70) else 35
            elif name in {"v6_read_market_news", "v6_open_broker_account", "v6_research_company_fundamentals", "v6_review_price_chart", "v6_check_budget"}:
                curiosity = agent.traits.curiosity if agent.traits else 50
                priority = 12 if curiosity >= 55 else 28
            elif option.text_slot == "speech":
                priority = 20
            elif option.text_slot:
                priority = 25
        return (priority + trait_priority_bias(agent.traits, name), option.label)

    return sorted(options, key=score)

def _default_limit(agent: Agent, *, reaction: bool) -> int:
    if agent.age_stage in {"newborn", "infant", "toddler"}:
        return 25
    if reaction:
        return 55
    return 60


def _cap_action_options(agent: Agent, options: list[ActionOption], limit: int) -> list[ActionOption]:
    options = [option for option in options if option.tool_name not in DISABLED_GROUP_CHAT_TOOLS]
    if len(options) <= limit:
        return options
    selected: list[ActionOption] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...], str | None, str | None]] = set()
    visible_variant_counts: dict[str, int] = {}

    def key(option: ActionOption) -> tuple[str, tuple[tuple[str, str], ...], str | None, str | None]:
        return (
            option.tool_name,
            tuple(sorted((name, str(value)) for name, value in (option.params or {}).items())),
            option.value_slot,
            option.text_slot,
        )

    def visible_variant_limit(option: ActionOption) -> int | None:
        params = option.params or {}
        if not any(name in params for name in ("visible_ref", "target_ref", "receiver_ref")):
            return None
        if option.tool_name in {"accept_social_request_visible_agent", "decline_social_request_visible_agent", "dodge_forced_action_visible_agent", "allow_forced_action_visible_agent", "protest_forced_action_visible_agent", "feed_child_visible_agent", "care_for_child_visible_agent", "carry_child_visible_agent"}:
            return 8
        if option.tool_name in {"observe_visible_agent", "help_visible_agent", "share_food_with_visible_agent", "share_water_with_visible_agent"}:
            return 5
        return 3

    def can_add(option: ActionOption) -> bool:
        limit_for_visible = visible_variant_limit(option)
        if limit_for_visible is None:
            return True
        count = visible_variant_counts.get(option.tool_name, 0)
        return count < limit_for_visible

    def mark_added(option: ActionOption) -> None:
        if visible_variant_limit(option) is not None:
            visible_variant_counts[option.tool_name] = visible_variant_counts.get(option.tool_name, 0) + 1

    def add_matching(predicate, quota: int) -> None:
        for option in options:
            if len(selected) >= limit or quota <= 0:
                return
            option_key = key(option)
            if option_key in seen or not predicate(option) or not can_add(option):
                continue
            selected.append(option)
            seen.add(option_key)
            mark_added(option)
            quota -= 1

    def add_first_for_tools(tool_names: Iterable[str]) -> None:
        for tool_name in tool_names:
            if len(selected) >= limit:
                return
            for option in options:
                option_key = key(option)
                if option_key in seen or option.tool_name != tool_name or not can_add(option):
                    continue
                selected.append(option)
                seen.add(option_key)
                mark_added(option)
                break

    add_matching(lambda option: option.tool_name in {"check_self_status", "look_around", "do_nothing"}, 3)
    # Reserve movement before broad survival entries. Otherwise a small menu can be filled by
    # eat/drink/sleep variants and lose wander/route choices, trapping agents in place.
    add_first_for_tools(["move_to_location", "wander", "return_home", "go_eat_food", "go_drink_water", "knock_private_room"])
    add_first_for_tools(["speak_to_nearby", "say_to_visible_agent", "tool_social_greet_visible"])
    add_matching(lambda option: option.tool_name in MARKET_ACTION_TOOLS, 8)
    relationship_front_names = set(PARTNER_FAMILY_PLANNING_TOOL_NAMES) | {
        "ask_date_visible_agent",
        "hold_hands_visible_agent",
        "hug_visible_agent",
        "confess_feelings_visible_agent",
        "define_relationship_visible_agent",
        "break_up_visible_agent",
        "repair_relationship_visible_agent",
        "accept_adult_intimacy_visible_agent",
        "decline_adult_intimacy_visible_agent",
    } | set(NEGATIVE_RELATIONSHIP_TOOL_NAMES) | set(INFIDELITY_RESPONSE_TOOL_NAMES)
    add_matching(lambda option: option.tool_name in relationship_front_names, 14)
    add_matching(lambda option: option.tool_name in {"move_to_location", "wander", "return_home", "go_eat_food", "go_drink_water", "knock_private_room"}, 12)
    add_matching(lambda option: option.tool_name in {"speak_to_nearby", "say_to_visible_agent", "tool_social_greet_visible"}, 8)
    add_matching(lambda option: option.tool_name in {"go_drink_water", "drink_water", "drink_bottled_water", "go_eat_food", "eat_food", "eat_portable_food", "sleep", "sleep_rough", "return_home", "wash", "clean_current_location", "request_food_help", "request_water_help", "accept_community_aid"}, 12)
    # Practical rescue/care tools must survive the final display cap. Dynamic catalog
    # diversity is useful, but it must not hide “carry the collapsed person to clinic”.
    add_matching(
        lambda option: option.tool_name in {
            "help_visible_agent",
            "escort_visible_agent_to_medical",
            "treat_visible_agent_medical",
            "feed_visible_agent_meal",
            "share_food_with_visible_agent",
            "share_water_with_visible_agent",
            "wake_visible_agent",
            "check_child_status_visible_agent",
            "soothe_child_visible_agent",
            "feed_child_visible_agent",
            "carry_child_visible_agent",
            "put_child_to_sleep_visible_agent",
            "care_for_child_visible_agent",
        },
        14,
    )
    add_matching(lambda option: option.tool_name in {"v6_read_market_news", "v6_open_broker_account", "v6_research_company_fundamentals", "v6_review_price_chart", "v6_check_budget"}, 6)
    # Reserve visible menu space for dynamically selected catalog tools. The 900+
    # registered tools should not be erased again by the final AOHP display cap.
    add_matching(lambda option: option.tool_name.startswith("tool_") and _menu_catalog_domain(option.tool_name) == "survival", 8)
    add_matching(lambda option: option.tool_name.startswith("tool_") and _menu_catalog_domain(option.tool_name) in {"work", "economy"}, 9)
    add_matching(lambda option: option.tool_name.startswith("tool_") and _menu_catalog_domain(option.tool_name) in {"social", "relationship"}, 8)
    add_matching(lambda option: option.tool_name.startswith("tool_") and _menu_catalog_domain(option.tool_name) in {"learning", "space", "general"}, 8)
    add_matching(lambda option: option.tool_name.startswith("tool_") and _menu_catalog_domain(option.tool_name) in {"family", "childcare", "law"}, 7)
    if agent.traits and (agent.traits.aggression >= 65 or (agent.dynamic_state and (agent.dynamic_state.stress >= 75 or agent.dynamic_state.satiety < 16 or agent.dynamic_state.hydration < 16))):
        add_matching(lambda option: "风险" in option.tags or any(token in option.tool_name for token in ["attack", "demand", "force", "theft", "robbery", "burglary", "escape", "confront", "protest"]), 10)
    if agent.traits and (agent.traits.sociability >= 62 or agent.traits.empathy >= 62):
        add_matching(lambda option: option.text_slot == "speech" or any(token in option.tool_name for token in ["help", "comfort", "share", "care", "ask_", "invite"]), 12)
    if agent.traits and (agent.traits.creativity >= 62 or agent.traits.curiosity >= 62):
        add_matching(lambda option: any(token in option.tool_name for token in ["write", "story", "sing", "read", "practice", "observe", "research", "look", "market", "budget"]), 10)
    add_matching(lambda _option: True, limit - len(selected))
    # If diversity caps were too strict, fill any remaining slots without the per-tool target cap.
    for option in options:
        if len(selected) >= limit:
            break
        option_key = key(option)
        if option_key in seen:
            continue
        selected.append(option)
        seen.add(option_key)
    return selected



def _menu_catalog_domain(tool_name: str) -> str:
    text = str(tool_name or "").lower()
    if any(token in text for token in ["child", "parent", "baby"]):
        return "childcare"
    if any(token in text for token in ["pregnancy", "birth", "adult"]):
        return "family"
    if any(token in text for token in ["romance", "relationship", "affection", "intimacy"]):
        return "relationship"
    if any(token in text for token in ["social", "comm", "greet", "talk", "meeting"]):
        return "social"
    if any(token in text for token in ["body", "food", "water", "medical", "cafeteria"]):
        return "survival"
    if any(token in text for token in ["work", "job", "shift"]):
        return "work"
    if any(token in text for token in ["econ", "market", "inventory", "item", "money"]):
        return "economy"
    if any(token in text for token in ["crime", "jail", "police", "court", "victim"]):
        return "law"
    if any(token in text for token in ["learn", "create", "project", "goal", "memory", "diary"]):
        return "learning"
    if any(token in text for token in ["move", "location", "env", "perceive"]):
        return "space"
    return "general"

def _label_for_tool(spec: ToolSpec) -> str:
    label = spec.display_name or spec.tool_name
    replacements = {
        "移动到地点": "去",
        "说一句话": "对人说话",
        "向附近说话": "向附近说话/公开说话",
        "正式自我介绍": "自我介绍给",
        "拒绝介绍": "拒绝向其介绍",
        "请求更多候选工具": "询问更多工具",
    }
    return replacements.get(label, label)


def _short_label(label: str) -> str:
    return " ".join(str(label).strip().split())[:34]
