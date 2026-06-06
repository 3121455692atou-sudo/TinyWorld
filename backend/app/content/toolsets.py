from __future__ import annotations

from typing import Any


SURVIVAL_NEEDS_TOOLSET_ID = "survival_needs_toolset"
REPRODUCTION_TOOLSET_ID = "reproduction_lifecycle_toolset"
FINANCE_INVESTING_TOOLSET_ID = "finance_investing_toolset"
AGENT_SOCIAL_TOOLSET_ID = "agent_social_toolset"
AGENT_WORK_TOOLSET_ID = "agent_work_toolset"
AGENT_CREATIVE_TOOLSET_ID = "agent_creative_toolset"
AGENT_GOVERNANCE_TOOLSET_ID = "agent_governance_toolset"
AGENT_ROMANCE_TOOLSET_ID = "agent_romance_toolset"
AGENT_CAREGIVING_TOOLSET_ID = "agent_caregiving_toolset"
AGENT_CRIME_TOOLSET_ID = "agent_crime_toolset"
AGENT_FINANCE_TOOLSET_ID = "agent_finance_toolset"

DEFAULT_OPTIONAL_TOOLSET_IDS = [
    SURVIVAL_NEEDS_TOOLSET_ID,
    REPRODUCTION_TOOLSET_ID,
    FINANCE_INVESTING_TOOLSET_ID,
]

AGENT_SPECIAL_TOOLSETS = [
    {
        "toolset_id": AGENT_SOCIAL_TOOLSET_ID,
        "name": "特殊社交工具集",
        "description": "让该 agent 使用更细的社交、求助、安慰、边界、赠送、书信和关系记录工具。基础说话仍属于自带基础工具。",
        "tool_names": [
            "compliment_visible_agent",
            "apologize_to_visible_agent",
            "help_visible_agent",
            "move_closer_to_visible_agent",
            "walk_away_from_visible_agent",
            "offer_item_to_visible_agent",
            "give_item_to_visible_agent",
            "grant_personal_resource_permission_visible_agent",
            "seek_conversation",
            "casual_chat_visible_agent",
            "ask_about_needs",
            "comfort_visible_agent",
            "invite_visible_agent_to_walk",
            "ask_for_help_from_visible_agent",
            "share_food_with_visible_agent",
            "share_water_with_visible_agent",
            "set_boundary_visible_agent",
            "thank_visible_agent",
            "discuss_feelings_visible_agent",
            "accept_social_request_visible_agent",
            "decline_social_request_visible_agent",
            "record_relationship_note_by_name",
            "introduce_other_agent",
            "send_private_letter_by_name",
            "invite_named_agent_to_event",
            "promise_to_named_agent",
        ],
    },
    {
        "toolset_id": AGENT_WORK_TOOLSET_ID,
        "name": "特殊工作劳动工具集",
        "description": "让该 agent 找工作、打工、加班、休息、抱怨工作或辞职。",
        "tool_names": [
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
            "v6_offer_labor_for_rent",
        ],
    },
    {
        "toolset_id": AGENT_CREATIVE_TOOLSET_ID,
        "name": "特殊创作娱乐工具集",
        "description": "让该 agent 写作、唱歌、讲故事、练技能、画画、拍视频、直播或发布作品。",
        "tool_names": [
            "tell_story_nearby",
            "sing_nearby",
            "play_simple_game",
            "write_diary",
            "practice_skill",
            "sketch_or_doodle",
            "write_private_note",
            "v6_choose_video_topic",
            "v6_film_video",
            "v6_edit_video",
            "v6_upload_video",
            "v6_livestream",
            "v6_compose_music",
            "v6_release_song",
            "v6_paint_artwork",
            "v6_sell_artwork",
            "v6_write_story_or_blog",
            "v6_publish_story_or_blog",
            "v6_follow_trend",
            "v6_ignore_trend_make_personal_work",
            "v6_promote_creation",
            "v6_rest_from_burnout",
            "v6_buy_creator_equipment",
            "v6_sell_creator_equipment",
            "v6_monetize_audience",
        ],
    },
    {
        "toolset_id": AGENT_GOVERNANCE_TOOLSET_ID,
        "name": "特殊治理公共事务工具集",
        "description": "让该 agent 召集会议、提出规则、支持/反对规则、公开指控或提名。",
        "tool_names": [
            "call_community_meeting",
            "propose_social_rule",
            "support_social_rule",
            "oppose_social_rule",
            "make_public_accusation_by_name",
            "nominate_named_agent",
            "report_unknown_theft",
            "confront_visible_agent_about_crime",
            "report_known_crime_by_name",
            "forgive_visible_agent_crime",
        ],
    },
    {
        "toolset_id": AGENT_ROMANCE_TOOLSET_ID,
        "name": "特殊恋爱亲密工具集",
        "description": "让该 agent 使用好感、约会、牵手、拥抱、表白、确认关系、分手、修复关系和抽象成年亲密工具。",
        "tool_names": [
            "express_affection_visible_agent",
            "ask_date_visible_agent",
            "hold_hands_visible_agent",
            "hug_visible_agent",
            "accept_social_request_visible_agent",
            "decline_social_request_visible_agent",
            "force_hug_visible_agent",
            "force_hold_hands_visible_agent",
            "force_comfort_visible_agent",
            "force_help_visible_agent",
            "force_walk_together_visible_agent",
            "force_date_visible_agent",
            "force_relationship_claim_visible_agent",
            "dodge_forced_action_visible_agent",
            "allow_forced_action_visible_agent",
            "protest_forced_action_visible_agent",
            "confess_feelings_visible_agent",
            "define_relationship_visible_agent",
            "discuss_romantic_boundaries_visible_agent",
            "break_up_visible_agent",
            "repair_relationship_visible_agent",
            "request_adult_intimacy_visible_agent",
            "accept_adult_intimacy_visible_agent",
            "decline_adult_intimacy_visible_agent",
        ],
    },
    {
        "toolset_id": AGENT_CAREGIVING_TOOLSET_ID,
        "name": "特殊照护育儿工具集",
        "description": "让该 agent 照顾孩子、教孩子简单技能，并更容易使用主动帮助类工具。",
        "tool_names": [
            "check_child_status_visible_agent",
            "soothe_child_visible_agent",
            "feed_child_visible_agent",
            "carry_child_visible_agent",
            "put_child_to_sleep_visible_agent",
            "care_for_child_visible_agent",
            "teach_child_simple_skill_visible_agent",
            "help_visible_agent",
            "ask_about_needs",
            "comfort_visible_agent",
            "share_food_with_visible_agent",
            "share_water_with_visible_agent",
            "feed_visible_agent_meal",
            "escort_visible_agent_to_medical",
            "treat_visible_agent_medical",
        ],
    },
    {
        "toolset_id": AGENT_CRIME_TOOLSET_ID,
        "name": "特殊犯罪越界工具集",
        "description": "让该 agent 使用偷窃、入室盗窃、威胁索要、入室抢劫、攻击和越狱等高风险工具；结果由系统硬规则判定。",
        "tool_names": [
            "attempt_petty_theft_visible_agent",
            "attempt_burglary_private_room",
            "demand_money_visible_agent",
            "home_invasion_robbery_private_room",
            "attack_visible_agent",
            "attempt_forced_adult_boundary_visible_agent",
            "attempt_jail_escape",
        ],
    },
    {
        "toolset_id": AGENT_FINANCE_TOOLSET_ID,
        "name": "特殊金融投资工具集",
        "description": "让该 agent 使用证券账户、市场新闻、股票研究、买卖、保证金和做空工具；仍受通用金融投资工具集总开关限制。",
        "tool_names": [
            "v6_open_broker_account",
            "v6_deposit_to_broker",
            "v6_withdraw_from_broker",
            "v6_read_market_news",
            "v6_research_company_fundamentals",
            "v6_review_price_chart",
            "v6_place_market_buy_order",
            "v6_place_market_sell_order",
            "v6_set_stop_loss_order",
            "v6_set_take_profit_order",
            "v6_enable_margin_account",
            "v6_buy_stock_on_margin",
            "v6_add_margin_cash",
            "v6_reduce_leveraged_position",
            "v6_enable_short_selling",
            "v6_short_sell_stock",
            "v6_buy_to_cover_short",
            "v6_accept_margin_call",
            "v6_do_nothing_during_margin_call",
            "v6_panic_sell",
            "v6_take_profit_calmly",
            "v6_hold_long_term",
            "v6_exit_market_after_loss",
            "v6_borrow_money_to_trade",
            "v6_discuss_stock_win",
            "v6_hide_stock_loss",
        ],
    },
]

DEFAULT_AGENT_SPECIAL_TOOLSET_IDS = [toolset["toolset_id"] for toolset in AGENT_SPECIAL_TOOLSETS]
AGENT_SPECIAL_TOOLSET_BY_ID = {toolset["toolset_id"]: toolset for toolset in AGENT_SPECIAL_TOOLSETS}
AGENT_SPECIAL_CONTROLLED_TOOL_NAMES = {
    tool_name for toolset in AGENT_SPECIAL_TOOLSETS for tool_name in toolset.get("tool_names", [])
}


def settings_from_world(world_or_settings: Any) -> dict[str, Any]:
    if isinstance(world_or_settings, dict):
        return world_or_settings
    return getattr(world_or_settings, "settings_json", None) or {}


def enabled_optional_toolset_ids(world_or_settings: Any) -> set[str]:
    settings = settings_from_world(world_or_settings)
    raw_ids = settings.get("enabled_optional_toolset_ids")
    if isinstance(raw_ids, list):
        return {str(item) for item in raw_ids}

    # Legacy worlds predate modular optional toolsets. Keep food/water and finance on
    # so old saves do not suddenly lose core modern-world behavior.
    ids = {SURVIVAL_NEEDS_TOOLSET_ID, FINANCE_INVESTING_TOOLSET_ID}
    if settings.get("reproduction_enabled"):
        ids.add(REPRODUCTION_TOOLSET_ID)
    return ids


def optional_toolset_enabled(world_or_settings: Any, toolset_id: str, *, legacy_default: bool = True) -> bool:
    settings = settings_from_world(world_or_settings)
    if "enabled_optional_toolset_ids" not in settings:
        return legacy_default
    return toolset_id in enabled_optional_toolset_ids(settings)


def survival_needs_enabled(world_or_settings: Any) -> bool:
    return optional_toolset_enabled(world_or_settings, SURVIVAL_NEEDS_TOOLSET_ID, legacy_default=True)


def finance_investing_enabled(world_or_settings: Any) -> bool:
    return optional_toolset_enabled(world_or_settings, FINANCE_INVESTING_TOOLSET_ID, legacy_default=True)


def reproduction_enabled_from_settings(world_or_settings: Any) -> bool:
    settings = settings_from_world(world_or_settings)
    if "reproduction_enabled" in settings:
        return bool(settings.get("reproduction_enabled"))
    return optional_toolset_enabled(settings, REPRODUCTION_TOOLSET_ID, legacy_default=True)


def agent_special_toolset_ids(tool_learning: dict[str, Any] | None) -> set[str]:
    raw_ids = (tool_learning or {}).get("agent_toolset_ids")
    if not isinstance(raw_ids, list):
        return set(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS)
    return {str(item) for item in raw_ids if str(item) in AGENT_SPECIAL_TOOLSET_BY_ID}


def agent_special_tool_names(tool_learning: dict[str, Any] | None) -> set[str]:
    names: set[str] = set()
    for toolset_id in agent_special_toolset_ids(tool_learning):
        names.update(AGENT_SPECIAL_TOOLSET_BY_ID[toolset_id].get("tool_names", []))
    return names


def agent_special_tool_allowed(tool_learning: dict[str, Any] | None, tool_name: str) -> bool:
    if tool_name not in AGENT_SPECIAL_CONTROLLED_TOOL_NAMES:
        return True
    return tool_name in agent_special_tool_names(tool_learning)
