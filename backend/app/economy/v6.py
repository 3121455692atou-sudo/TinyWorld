from __future__ import annotations

import math
import random
import uuid
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import apply_delta
from app.agents.traits import clamp
from app.agents.v5_state import ensure_v5_agent_state, wallet_money
from app.content.toolsets import finance_investing_enabled, survival_needs_enabled
from app.core.models import Agent, Event, Location, World
from app.events.event_store import create_event
from app.simulation.difficulty import profile_for_agent, profile_for_world


FOOD_PRICE = 6
MAX_SLEEP_MINUTES_PER_DAY = 10 * 60
RENT_PER_10_DAYS = 30
RENT_INTERVAL_DAYS = 10
RENT_GRACE_DAYS = 2
HOUSE_PRICE = 600
HOUSE_DOWN_PAYMENT = 120
MORTGAGE_DAILY_PAYMENT = 4
MARKET_TICKERS = {
    "MGL": ("微界物流", "生活服务", 18.0, 0.06),
    "YUN": ("云芽娱乐", "内容平台", 24.0, 0.11),
    "QSH": ("青石能源", "能源", 31.0, 0.08),
    "NOVA": ("新星工坊", "制造", 12.0, 0.13),
}

V6_CORE_TOOLS = {
    "v6_check_budget",
    "v6_review_spending_history",
    "v6_buy_basic_food_for_survival",
    "v6_buy_normal_meal",
    "v6_buy_premium_meal_for_dopamine",
    "v6_buy_luxury_meal",
    "v6_buy_status_drink",
    "v6_resist_luxury_craving",
    "v6_accept_plain_life",
    "v6_complain_about_downgrade",
    "v6_comfort_self_after_cheap_food",
    "v6_treat_friend_to_meal",
    "v6_buy_luxury_clothing",
    "v6_buy_jewelry_or_watch",
    "v6_show_off_luxury_item",
    "v6_hide_luxury_item",
    "v6_sell_luxury_item",
    "v6_pawn_luxury_item",
    "v6_track_dopamine_threshold",
    "v6_create_daily_budget",
    "v6_cut_food_spending_without_changing_satiety",
    "v6_cancel_luxury_plan",
    "v6_set_savings_goal",
    "v6_save_for_down_payment",
    "v6_build_emergency_fund",
    "v6_audit_debt_payments",
    "v6_compare_job_income_to_bills",
    "v6_choose_frugal_day",
    "v6_ask_friend_for_small_loan",
    "v6_borrow_from_bank_unsecured",
    "v6_borrow_from_loan_shark",
    "v6_take_new_loan_to_pay_old_debt",
    "v6_borrow_to_keep_luxury_life",
    "v6_request_loan_extension",
    "v6_repay_minimum_payment",
    "v6_repay_extra_principal",
    "v6_default_on_loan",
    "v6_declare_personal_bankruptcy",
    "v6_sell_asset_to_repay_debt",
    "v6_check_rent_due_date",
    "v6_pay_10_day_rent",
    "v6_ask_landlord_for_grace_period",
    "v6_negotiate_lower_rent",
    "v6_move_to_cheaper_room",
    "v6_search_temporary_shelter",
    "v6_sleep_rough_when_homeless",
    "v6_offer_labor_for_rent",
    "v6_view_house_market",
    "v6_apply_for_mortgage",
    "v6_prepay_mortgage",
    "v6_list_house_for_rent",
    "v6_enable_system_void_tenant",
    "v6_disable_system_void_tenant",
    "v6_collect_system_tenant_rent",
    "v6_walk_to_destination",
    "v6_take_bus",
    "v6_buy_bicycle",
    "v6_ride_bicycle",
    "v6_repair_bicycle",
    "v6_buy_cheap_car",
    "v6_buy_normal_car",
    "v6_buy_luxury_car",
    "v6_drive_car",
    "v6_fuel_vehicle",
    "v6_check_fuel_price",
    "v6_complain_about_fuel_price",
    "v6_perform_vehicle_maintenance",
    "v6_delay_vehicle_maintenance",
    "v6_sell_vehicle",
    "v6_show_off_vehicle",
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
}


def ensure_v6_agent_state(agent: Agent) -> dict[str, Any]:
    ensure_v5_agent_state(agent)
    wallet = dict(agent.wallet_json or {})
    wallet.setdefault("money", wallet_money(agent))
    wallet.setdefault("bank_balance", 0)
    wallet.setdefault("economy_ledger", [])
    wallet.setdefault("assets", [])
    wallet.setdefault("liabilities", [])
    wallet.setdefault("vehicles", [])
    current_housing = dict(wallet.get("housing") or {})
    wallet["housing"] = {**_default_housing(agent), **current_housing}
    if _is_dependent_minor(agent):
        wallet["housing"].update(_dependent_housing(agent, current_housing.get("home_location_id")))
    wallet.setdefault("hedonic_state", _default_hedonic())
    wallet.setdefault("creator_profile", _default_creator(agent))
    wallet.setdefault("broker_account", None)
    wallet.setdefault("social_status", _default_social_status(agent))
    profile = {**_default_profile(agent), **(wallet.get("economy_profile") or {})}
    wallet["economy_profile"] = profile
    agent.wallet_json = wallet
    update_derived_economy(agent)
    return agent.wallet_json


def update_derived_economy(agent: Agent) -> dict[str, Any]:
    wallet = dict(agent.wallet_json or {})
    assets = wallet.get("assets") or []
    liabilities = wallet.get("liabilities") or []
    broker = wallet.get("broker_account") or {}
    debt = sum(float(loan.get("principal_remaining", 0)) for loan in liabilities if loan.get("default_state") != "charged_off")
    asset_value = sum(float(asset.get("market_value", 0)) for asset in assets)
    broker_equity = float(broker.get("equity", 0)) if broker else 0
    ledger = wallet.get("economy_ledger") or []
    recent_income = [abs(float(item.get("amount", 0))) for item in ledger[-80:] if float(item.get("amount", 0)) > 0]
    recent_expense = [abs(float(item.get("amount", 0))) for item in ledger[-80:] if float(item.get("amount", 0)) < 0]
    profile = {**_default_profile(agent), **(wallet.get("economy_profile") or {})}
    profile.update(
        {
            "cash": int(wallet.get("money", 0)),
            "bank_balance": int(wallet.get("bank_balance", 0)),
            "daily_income_avg": round(sum(recent_income[-10:]) / 10, 2) if recent_income else 0,
            "daily_expense_avg": round(sum(recent_expense[-10:]) / 10, 2) if recent_expense else 0,
            "total_debt": round(debt, 2),
            "net_worth": round(int(wallet.get("money", 0)) + int(wallet.get("bank_balance", 0)) + asset_value + broker_equity - debt, 2),
            "minimum_payment_daily": round(sum(float(loan.get("minimum_payment_daily", 0)) for loan in liabilities if loan.get("default_state") in {None, "current", "late"}), 2),
        }
    )
    wallet["economy_profile"] = profile
    agent.wallet_json = wallet
    return profile


def v6_candidate_names(session: Session | None, agent: Agent, location: Location | None) -> set[str]:
    if agent.age_stage != "adult" or bool((agent.law_json or {}).get("jailed")):
        return set()
    wallet = ensure_v6_agent_state(agent)
    state = agent.dynamic_state
    money = wallet_money(agent)
    housing = wallet.get("housing") or {}
    profile = wallet.get("economy_profile") or {}
    hedonic = wallet.get("hedonic_state") or {}
    liabilities = wallet.get("liabilities") or []
    assets = wallet.get("assets") or []
    vehicles = wallet.get("vehicles") or []
    broker = wallet.get("broker_account")
    day = _day_from_agent_location(agent)
    names = {
        "v6_check_budget",
        "v6_review_spending_history",
        "v6_track_dopamine_threshold",
        "v6_create_daily_budget",
        "v6_compare_job_income_to_bills",
        "v6_check_rent_due_date",
        "v6_view_house_market",
        "v6_choose_frugal_day",
        "v6_choose_video_topic",
        "v6_write_story_or_blog",
        "v6_read_market_news",
    }
    tags = set(location.tags_json or []) if location else set()
    if "food_service" in tags or "trade" in tags:
        names.update({"v6_buy_basic_food_for_survival", "v6_buy_normal_meal"})
        if money >= 18:
            names.add("v6_buy_premium_meal_for_dopamine")
        if money >= 45:
            names.add("v6_buy_luxury_meal")
        if money >= 12:
            names.add("v6_buy_status_drink")
    if money >= 80:
        names.update({"v6_buy_luxury_clothing", "v6_buy_creator_equipment"})
    if money >= 160:
        names.add("v6_buy_jewelry_or_watch")
    if float(hedonic.get("luxury_threshold", 0)) >= 25:
        names.update({"v6_resist_luxury_craving", "v6_accept_plain_life", "v6_complain_about_downgrade", "v6_cut_food_spending_without_changing_satiety"})
    if _has_asset(wallet, "luxury_item"):
        names.update({"v6_show_off_luxury_item", "v6_hide_luxury_item", "v6_sell_luxury_item", "v6_pawn_luxury_item"})
    if liabilities:
        names.update({"v6_audit_debt_payments", "v6_repay_minimum_payment", "v6_repay_extra_principal", "v6_request_loan_extension", "v6_take_new_loan_to_pay_old_debt", "v6_default_on_loan", "v6_declare_personal_bankruptcy"})
    if money < 30 or float(profile.get("debt_stress", 0)) > 45:
        names.update({"v6_ask_friend_for_small_loan", "v6_borrow_from_bank_unsecured"})
    if money < 12 or float(profile.get("debt_stress", 0)) > 65:
        names.add("v6_borrow_from_loan_shark")
    next_due = int(housing.get("next_rent_due_day") or RENT_INTERVAL_DAYS)
    if day >= next_due - 2:
        names.update({"v6_pay_10_day_rent", "v6_ask_landlord_for_grace_period", "v6_negotiate_lower_rent", "v6_offer_labor_for_rent"})
    if housing.get("homeless"):
        names.update({"v6_search_temporary_shelter", "v6_sleep_rough_when_homeless", "v6_ask_friend_for_small_loan"})
    if money >= HOUSE_DOWN_PAYMENT:
        names.update({"v6_apply_for_mortgage", "v6_save_for_down_payment"})
    if _owns_house(wallet):
        names.update({"v6_prepay_mortgage", "v6_list_house_for_rent", "v6_enable_system_void_tenant", "v6_disable_system_void_tenant", "v6_collect_system_tenant_rent"})
    if money >= 60:
        names.add("v6_buy_bicycle")
    if money >= 260:
        names.add("v6_buy_cheap_car")
    if money >= 520:
        names.add("v6_buy_normal_car")
    if money >= 1100:
        names.add("v6_buy_luxury_car")
    if vehicles:
        names.update({"v6_ride_bicycle", "v6_drive_car", "v6_fuel_vehicle", "v6_check_fuel_price", "v6_complain_about_fuel_price", "v6_perform_vehicle_maintenance", "v6_delay_vehicle_maintenance", "v6_sell_vehicle", "v6_show_off_vehicle"})
    if state and state.energy >= 30:
        names.update({"v6_film_video", "v6_compose_music", "v6_paint_artwork", "v6_follow_trend", "v6_ignore_trend_make_personal_work", "v6_promote_creation"})
    creator = wallet.get("creator_profile") or {}
    if creator.get("drafts"):
        names.update({"v6_edit_video", "v6_upload_video", "v6_release_song", "v6_sell_artwork", "v6_publish_story_or_blog"})
    if int(creator.get("audience_size", 0)) > 20:
        names.update({"v6_livestream", "v6_monetize_audience"})
    world = session.get(World, agent.world_id) if session else agent.world
    finance_enabled = finance_investing_enabled(world)
    if not finance_enabled:
        names = {name for name in names if not _is_finance_investing_tool(name)}
    if not survival_needs_enabled(world):
        names = {name for name in names if not _is_survival_consumption_tool(name)}
    if finance_enabled:
        if money >= 20 and not broker:
            names.add("v6_open_broker_account")
        if broker:
            names.update({"v6_deposit_to_broker", "v6_withdraw_from_broker", "v6_research_company_fundamentals", "v6_review_price_chart", "v6_place_market_buy_order", "v6_place_market_sell_order", "v6_set_stop_loss_order", "v6_set_take_profit_order"})
            if broker.get("margin_enabled"):
                names.update({"v6_buy_stock_on_margin", "v6_add_margin_cash", "v6_reduce_leveraged_position", "v6_accept_margin_call", "v6_do_nothing_during_margin_call"})
            elif int(profile.get("risk_tolerance", 0)) > 55:
                names.add("v6_enable_margin_account")
            if broker.get("short_enabled"):
                names.update({"v6_short_sell_stock", "v6_buy_to_cover_short"})
            elif int(profile.get("financial_literacy", 0)) > 55 and int(profile.get("risk_tolerance", 0)) > 50:
                names.add("v6_enable_short_selling")
            if broker.get("realized_pnl", 0) > 0:
                names.add("v6_discuss_stock_win")
            if broker.get("realized_pnl", 0) < 0 or broker.get("unrealized_pnl", 0) < 0:
                names.update({"v6_hide_stock_loss", "v6_panic_sell", "v6_exit_market_after_loss", "v6_hold_long_term", "v6_take_profit_calmly"})
    if survival_needs_enabled(world) and state and (state.satiety < 35 or state.hydration < 35):
        names.difference_update({"v6_buy_luxury_meal", "v6_buy_luxury_clothing", "v6_buy_jewelry_or_watch", "v6_place_market_buy_order"})
    return names & V6_CORE_TOOLS


def v6_tool_allowed(session: Session, agent: Agent, tool_name: str) -> bool:
    if not tool_name.startswith("v6_"):
        return True
    if agent.age_stage != "adult":
        return False
    world = session.get(World, agent.world_id)
    if _is_finance_investing_tool(tool_name) and not finance_investing_enabled(world):
        return False
    if _is_survival_consumption_tool(tool_name) and not survival_needs_enabled(world):
        return False
    wallet = ensure_v6_agent_state(agent)
    money = wallet_money(agent)
    food_price = int(profile_for_agent(agent)["food_price"])
    if tool_name == "v6_buy_basic_food_for_survival":
        return money >= food_price
    if tool_name == "v6_buy_normal_meal":
        return money >= food_price + 2
    if tool_name == "v6_buy_premium_meal_for_dopamine":
        return money >= 18
    if tool_name == "v6_buy_luxury_meal":
        return money >= 45
    if tool_name == "v6_buy_status_drink":
        return money >= 12
    if tool_name == "v6_buy_luxury_clothing":
        return money >= 80
    if tool_name == "v6_buy_jewelry_or_watch":
        return money >= 160
    if tool_name in {"v6_sell_luxury_item", "v6_pawn_luxury_item", "v6_show_off_luxury_item", "v6_hide_luxury_item"}:
        return _has_asset(wallet, "luxury_item")
    if tool_name in {"v6_repay_minimum_payment", "v6_repay_extra_principal", "v6_request_loan_extension", "v6_default_on_loan"}:
        return bool(wallet.get("liabilities"))
    if tool_name == "v6_pay_10_day_rent":
        return not (wallet.get("housing") or {}).get("homeless")
    if tool_name in {"v6_search_temporary_shelter", "v6_sleep_rough_when_homeless"}:
        if tool_name == "v6_sleep_rough_when_homeless" and _remaining_sleep_minutes_today(agent, world.current_world_time_minutes if world else 0) <= 0:
            return False
        return bool((wallet.get("housing") or {}).get("homeless"))
    if tool_name == "v6_apply_for_mortgage":
        return money >= HOUSE_DOWN_PAYMENT and not _owns_house(wallet)
    if tool_name in {"v6_prepay_mortgage", "v6_list_house_for_rent", "v6_enable_system_void_tenant", "v6_disable_system_void_tenant", "v6_collect_system_tenant_rent"}:
        return _owns_house(wallet)
    if tool_name == "v6_buy_bicycle":
        return money >= 60
    if tool_name == "v6_buy_cheap_car":
        return money >= 260
    if tool_name == "v6_buy_normal_car":
        return money >= 520
    if tool_name == "v6_buy_luxury_car":
        return money >= 1100
    if tool_name in {"v6_ride_bicycle", "v6_repair_bicycle", "v6_drive_car", "v6_fuel_vehicle", "v6_perform_vehicle_maintenance", "v6_delay_vehicle_maintenance", "v6_sell_vehicle", "v6_show_off_vehicle"}:
        return bool(wallet.get("vehicles"))
    if tool_name == "v6_buy_creator_equipment":
        return money >= 80
    if tool_name == "v6_open_broker_account":
        return money >= 20 and not wallet.get("broker_account")
    if tool_name in {"v6_deposit_to_broker", "v6_place_market_buy_order", "v6_place_market_sell_order", "v6_enable_margin_account", "v6_enable_short_selling", "v6_short_sell_stock", "v6_buy_stock_on_margin"}:
        return bool(wallet.get("broker_account"))
    return True


def handle_v6_tool(
    session: Session,
    world: World,
    actor: Agent,
    tool_name: str,
    params: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
) -> list[int]:
    ensure_v6_agent_state(actor)
    if tool_name in {"v6_check_budget", "v6_review_spending_history", "v6_track_dopamine_threshold", "v6_audit_debt_payments", "v6_compare_job_income_to_bills", "v6_check_rent_due_date"}:
        return [_overview_event(session, world, actor, tool_name, location_id).event_id]
    if tool_name in {"v6_buy_basic_food_for_survival", "v6_buy_normal_meal", "v6_buy_premium_meal_for_dopamine", "v6_buy_luxury_meal", "v6_buy_status_drink"}:
        return [_buy_hedonic_food(session, world, actor, tool_name, location_id, state_delta).event_id]
    if tool_name in {"v6_resist_luxury_craving", "v6_accept_plain_life", "v6_complain_about_downgrade", "v6_comfort_self_after_cheap_food", "v6_create_daily_budget", "v6_cut_food_spending_without_changing_satiety", "v6_cancel_luxury_plan", "v6_set_savings_goal", "v6_save_for_down_payment", "v6_build_emergency_fund", "v6_choose_frugal_day"}:
        return [_budget_or_desire_action(session, world, actor, tool_name, location_id, state_delta).event_id]
    if tool_name in {"v6_buy_luxury_clothing", "v6_buy_jewelry_or_watch", "v6_show_off_luxury_item", "v6_hide_luxury_item", "v6_sell_luxury_item", "v6_pawn_luxury_item"}:
        return [_luxury_asset_action(session, world, actor, tool_name, location_id, state_delta).event_id]
    if tool_name in {"v6_ask_friend_for_small_loan", "v6_borrow_from_bank_unsecured", "v6_borrow_from_loan_shark", "v6_take_new_loan_to_pay_old_debt", "v6_borrow_to_keep_luxury_life", "v6_request_loan_extension", "v6_repay_minimum_payment", "v6_repay_extra_principal", "v6_default_on_loan", "v6_declare_personal_bankruptcy", "v6_sell_asset_to_repay_debt"}:
        return [_loan_action(session, world, actor, tool_name, location_id, state_delta).event_id]
    if tool_name.startswith("v6_") and any(token in tool_name for token in ["rent", "house", "mortgage", "shelter", "homeless", "landlord", "tenant", "lodging"]):
        return [_housing_action(session, world, actor, tool_name, location_id, state_delta, params).event_id]
    if tool_name.startswith("v6_") and any(token in tool_name for token in ["vehicle", "bicycle", "car", "bus", "walk", "fuel", "ride", "drive"]):
        return [_transport_action(session, world, actor, tool_name, params, location_id, state_delta).event_id]
    if tool_name.startswith("v6_") and any(token in tool_name for token in ["video", "music", "song", "art", "story", "blog", "trend", "creator", "audience", "livestream", "sponsor", "performance"]):
        return [_creator_action(session, world, actor, tool_name, location_id, state_delta).event_id]
    if tool_name.startswith("v6_") and any(token in tool_name for token in ["stock", "broker", "market", "margin", "short", "profit", "loss", "chart", "company"]):
        return [_stock_action(session, world, actor, tool_name, params, location_id, state_delta).event_id]
    return [_generic_v6_event(session, world, actor, tool_name, location_id).event_id]


def process_daily_economy_tick(session: Session, world: World) -> list[int]:
    current_day = world.current_world_time_minutes // 1440
    settings = dict(world.settings_json or {})
    last_day = settings.get("v6_last_economy_day")
    if last_day is None:
        # 首次经济 tick 不能直接把 last_day 跳到 current_day；否则长时间运行后第一次触发会漏掉第10天房租等每日事件。
        for agent in session.execute(select(Agent).where(Agent.world_id == world.world_id)).scalars():
            ensure_v6_agent_state(agent)
        last_day = 0
    event_ids: list[int] = []
    for day in range(int(last_day) + 1, current_day + 1):
        if finance_investing_enabled(world):
            _update_world_markets(world, day)
        agents = list(session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))).scalars())
        for agent in agents:
            event_ids.extend(_daily_agent_economy(session, world, agent, day))
    settings = dict(world.settings_json or {})
    settings["v6_last_economy_day"] = current_day
    world.settings_json = settings
    return event_ids


def economy_metrics(agents: list[Agent], events: list[Event]) -> dict[str, Any]:
    for agent in agents:
        ensure_v6_agent_state(agent)
    alive = [agent for agent in agents if agent.lifecycle_state in {"alive", "critical"}]
    cash_values = [wallet_money(agent) for agent in alive]
    profiles = [(agent.wallet_json or {}).get("economy_profile") or {} for agent in alive]
    debts = [float(profile.get("total_debt", 0)) for profile in profiles]
    net_worth = [float(profile.get("net_worth", 0)) for profile in profiles]
    homeless = [agent for agent in alive if ((agent.wallet_json or {}).get("housing") or {}).get("homeless")]
    landlords = [agent for agent in alive if _owns_house(agent.wallet_json or {})]
    return {
        "avg_cash": round(sum(cash_values) / len(cash_values), 2) if cash_values else 0,
        "median_cash": median(cash_values) if cash_values else 0,
        "avg_net_worth": round(sum(net_worth) / len(net_worth), 2) if net_worth else 0,
        "gini_net_worth": round(_gini(net_worth), 3),
        "landlord_rate": round(len(landlords) / len(alive), 3) if alive else 0,
        "homeless_rate": round(len(homeless) / len(alive), 3) if alive else 0,
        "total_debt": round(sum(debts), 2),
        "avg_debt_stress": round(sum(float(profile.get("debt_stress", 0)) for profile in profiles) / len(profiles), 2) if profiles else 0,
        "luxury_purchase_count": _count_events(events, "v6_luxury"),
        "premium_food_count": _count_events(events, "v6_hedonic_food"),
        "borrow_to_consume_count": sum(1 for event in events if event.event_type == "v6_loan" and (event.payload or {}).get("purpose") == "luxury"),
        "rent_late_count": sum(1 for event in events if event.event_type == "v6_rent_late"),
        "eviction_count": sum(1 for event in events if event.event_type == "v6_eviction"),
        "mortgage_late_count": sum(1 for event in events if event.event_type == "v6_mortgage_late"),
        "foreclosure_count": sum(1 for event in events if event.event_type == "v6_foreclosure"),
        "system_tenant_contracts": sum(1 for agent in alive for asset in (agent.wallet_json or {}).get("assets", []) if asset.get("system_tenant_enabled")),
        "creator_work_count": sum(1 for event in events if event.event_type == "v6_creator_work"),
        "creator_viral_count": sum(1 for event in events if event.event_type == "v6_creator_viral"),
        "stock_account_count": sum(1 for agent in alive if (agent.wallet_json or {}).get("broker_account")),
        "stock_trade_count": sum(1 for event in events if event.event_type == "v6_stock_trade"),
        "margin_call_count": sum(1 for event in events if event.event_type == "v6_margin_call"),
        "liquidation_count": sum(1 for event in events if event.event_type == "v6_forced_liquidation"),
    }


def _overview_event(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None) -> Event:
    wallet = ensure_v6_agent_state(actor)
    profile = update_derived_economy(actor)
    housing = wallet.get("housing") or {}
    hedonic = wallet.get("hedonic_state") or {}
    broker = wallet.get("broker_account") or {}
    text = (
        f"{actor.chosen_name} 翻看了自己的账本: 现金 {wallet_money(actor)}，净资产 {profile.get('net_worth')}，"
        f"债务 {profile.get('total_debt')}，信用 {profile.get('credit_score')}，十天房租 {housing.get('rent_per_10_days')}，"
        f"下次房租在第 {housing.get('next_rent_due_day')} 天，享乐阈值 {hedonic.get('luxury_threshold'):.1f}。"
    )
    if broker:
        text += f" 证券账户权益 {broker.get('equity', 0):.1f}。"
    return _econ_event(session, world, actor, "v6_budget", text, 25, "info", location_id, {"tool_name": tool_name, "profile": profile})


def _buy_hedonic_food(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> Event:
    food_price = int(profile_for_world(world)["food_price"])
    tiers = {
        "v6_buy_basic_food_for_survival": ("便宜食物", food_price, 8, "basic"),
        "v6_buy_normal_meal": ("普通餐", food_price + 2, 18, "normal"),
        "v6_buy_premium_meal_for_dopamine": ("高级餐", 18, 45, "premium"),
        "v6_buy_luxury_meal": ("奢侈餐", 45, 75, "luxury"),
        "v6_buy_status_drink": ("展示型饮品", 12, 30, "symbolic"),
    }
    label, price, pleasure, tier = tiers[tool_name]
    if wallet_money(actor) < price:
        return _tool_failed(session, world, actor, location_id, f"钱不够，买不起{label}。")
    _change_money(actor, -price)
    delta: dict[str, float] = {"mood": 1}
    if tool_name != "v6_buy_status_drink":
        delta.update({"satiety": 34, "hydration": -2})
    else:
        delta.update({"hydration": 8, "fun": 2})
    hedonic_delta = _apply_hedonic(actor, pleasure, tier=tier)
    delta.update(hedonic_delta)
    if actor.dynamic_state:
        state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, **delta))
    _ledger(actor, world, "spending", -price, label, {"tier": tier})
    text_by_tier = {
        "basic": f"{actor.chosen_name} 买了便宜食物。味道很普通，但至少胃里重新有了踏实感。",
        "normal": f"{actor.chosen_name} 买了一份普通餐，坐下来认真吃完，脸色比刚才松了一点。",
        "premium": f"{actor.chosen_name} 犒劳自己吃了一顿高级餐，热乎的香气让疲惫短暂退后。",
        "luxury": f"{actor.chosen_name} 点了一顿奢侈餐，像是把今天的压力暂时挡在了餐桌外。",
        "symbolic": f"{actor.chosen_name} 买了杯展示型饮品，更多是在给自己一点体面和心情。",
    }
    text = text_by_tier.get(tier, f"{actor.chosen_name} 买了{label}。")
    color = "luxury" if tier in {"premium", "luxury", "symbolic"} else "economy"
    return _econ_event(session, world, actor, "v6_hedonic_food", text, 45 if tier in {"premium", "luxury"} else 25, color, location_id, {"price": price, "tier": tier, "pleasure_score": pleasure, "money": wallet_money(actor), "tool_name": tool_name})


def _budget_or_desire_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> Event:
    wallet = ensure_v6_agent_state(actor)
    hedonic = {**_default_hedonic(), **(wallet.get("hedonic_state") or {})}
    profile = {**_default_profile(actor), **(wallet.get("economy_profile") or {})}
    if tool_name in {"v6_resist_luxury_craving", "v6_accept_plain_life", "v6_cut_food_spending_without_changing_satiety", "v6_choose_frugal_day", "v6_cancel_luxury_plan"}:
        hedonic["luxury_threshold"] = max(0, float(hedonic.get("luxury_threshold", 0)) - 1.2)
        hedonic["deprivation_pain"] = max(0, float(hedonic.get("deprivation_pain", 0)) - 2)
        delta = apply_delta(actor.dynamic_state, stress=-3, mood=1, fun=-1) if actor.dynamic_state else {}
        text = f"{actor.chosen_name} 决定把消费欲望压下来，先过得朴素一点。"
    elif tool_name == "v6_complain_about_downgrade":
        hedonic["deprivation_pain"] = min(100, float(hedonic.get("deprivation_pain", 0)) + 4)
        delta = apply_delta(actor.dynamic_state, stress=-1, social=1, mood=-1) if actor.dynamic_state else {}
        text = f"{actor.chosen_name} 忍不住抱怨消费降级带来的落差。"
    else:
        profile["financial_literacy"] = min(100, int(profile.get("financial_literacy", 50)) + 1)
        profile["status_anxiety"] = max(0, int(profile.get("status_anxiety", 30)) - 1)
        delta = apply_delta(actor.dynamic_state, stress=-2, mood=1) if actor.dynamic_state else {}
        text = f"{actor.chosen_name} 给自己做了预算，试着把账单、房租和欲望放在同一张纸上看。"
    wallet["hedonic_state"] = hedonic
    wallet["economy_profile"] = profile
    actor.wallet_json = wallet
    if delta:
        state_delta.setdefault(actor.agent_id, {}).update(delta)
    return _econ_event(session, world, actor, "v6_budget", text, 25, "economy", location_id, {"tool_name": tool_name, "hedonic_state": hedonic})


def _luxury_asset_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> Event:
    wallet = ensure_v6_agent_state(actor)
    if tool_name in {"v6_buy_luxury_clothing", "v6_buy_jewelry_or_watch"}:
        price = 80 if tool_name == "v6_buy_luxury_clothing" else 160
        name = "奢侈服装" if tool_name == "v6_buy_luxury_clothing" else "首饰或名表"
        if wallet_money(actor) < price:
            return _tool_failed(session, world, actor, location_id, f"钱不够买{name}。")
        _change_money(actor, -price)
        asset = _asset("luxury_item", name, price, status_value=18 if price < 100 else 32, can_collateralize=True)
        _add_asset(actor, asset)
        _apply_hedonic(actor, 55 if price < 100 else 70, tier="symbolic")
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, mood=4, fun=5, stress=-2))
        _ledger(actor, world, "spending", -price, name, {"asset_id": asset["asset_id"]})
        text = f"{actor.chosen_name} 买下了{name}。这是一件资产，也是一种阶层信号。"
        return _econ_event(session, world, actor, "v6_luxury", text, 55, "luxury", location_id, {"asset": asset, "money": wallet_money(actor), "tool_name": tool_name})
    asset = _first_asset(wallet, "luxury_item")
    if not asset:
        return _tool_failed(session, world, actor, location_id, "没有可处理的奢侈品。")
    if tool_name in {"v6_sell_luxury_item", "v6_pawn_luxury_item"}:
        amount = int(asset.get("liquidation_value", 0) if tool_name == "v6_pawn_luxury_item" else asset.get("market_value", 0) * 0.75)
        _remove_asset(actor, asset["asset_id"])
        _change_money(actor, amount)
        _ledger(actor, world, "income", amount, "出售/典当奢侈品", {"asset_id": asset["asset_id"]})
        text = f"{actor.chosen_name} 把{asset.get('display_name_zh')}换成了 {amount} 现金。"
        return _econ_event(session, world, actor, "v6_asset_sale", text, 45, "economy", location_id, {"amount": amount, "tool_name": tool_name})
    text = f"{actor.chosen_name} 低调收起了{asset.get('display_name_zh')}。" if tool_name == "v6_hide_luxury_item" else f"{actor.chosen_name} 展示了{asset.get('display_name_zh')}，有人可能会注意到这种阶层信号。"
    if actor.dynamic_state:
        state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, mood=1 if tool_name != "v6_hide_luxury_item" else 0, stress=-1 if tool_name == "v6_hide_luxury_item" else 1))
    return _econ_event(session, world, actor, "v6_status_signal", text, 40, "luxury", location_id, {"asset": asset, "tool_name": tool_name})


def _loan_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> Event:
    wallet = ensure_v6_agent_state(actor)
    loans = wallet.get("liabilities") or []
    if tool_name in {"v6_repay_minimum_payment", "v6_repay_extra_principal"}:
        if not loans:
            return _tool_failed(session, world, actor, location_id, "现在没有需要偿还的债务。")
        amount = int(sum(float(loan.get("minimum_payment_daily", 0)) for loan in loans)) if tool_name == "v6_repay_minimum_payment" else min(wallet_money(actor), 20)
        if amount <= 0 or wallet_money(actor) < amount:
            return _tool_failed(session, world, actor, location_id, "现金不够偿还这笔债。")
        remaining = amount
        for loan in loans:
            pay = min(remaining, float(loan.get("principal_remaining", 0)))
            loan["principal_remaining"] = round(float(loan.get("principal_remaining", 0)) - pay, 2)
            loan["missed_payment_count"] = 0
            loan["default_state"] = "current"
            remaining -= int(pay)
            if remaining <= 0:
                break
        wallet["liabilities"] = [loan for loan in loans if float(loan.get("principal_remaining", 0)) > 0.1]
        actor.wallet_json = wallet
        _change_money(actor, -amount)
        _ledger(actor, world, "debt_payment", -amount, "还款", {"tool_name": tool_name})
        _adjust_debt_stress(actor, -6)
        text = f"{actor.chosen_name} 偿还了 {amount} 债务，压力稍微降了一点。"
        return _econ_event(session, world, actor, "v6_debt_payment", text, 40, "debt", location_id, {"amount": amount, "tool_name": tool_name})
    if tool_name == "v6_request_loan_extension":
        for loan in loans:
            loan["minimum_payment_daily"] = max(1, round(float(loan.get("minimum_payment_daily", 1)) * 0.75, 2))
            loan["interest_rate_daily"] = round(float(loan.get("interest_rate_daily", 0.01)) + 0.002, 4)
        wallet["liabilities"] = loans
        actor.wallet_json = wallet
        _adjust_credit(actor, -3)
        _adjust_debt_stress(actor, -3)
        return _econ_event(session, world, actor, "v6_debt_extension", f"{actor.chosen_name} 请求了贷款延期，短期压力下降，但利息变高。", 45, "debt", location_id, {"tool_name": tool_name})
    if tool_name == "v6_default_on_loan":
        for loan in loans:
            loan["default_state"] = "defaulted"
            loan["missed_payment_count"] = int(loan.get("missed_payment_count", 0)) + 1
        wallet["liabilities"] = loans
        actor.wallet_json = wallet
        _adjust_credit(actor, -15)
        _adjust_debt_stress(actor, 18)
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, stress=8, mood=-5))
        return _econ_event(session, world, actor, "v6_debt_default", f"{actor.chosen_name} 无力或拒绝继续还款，信用和情绪都受到了冲击。", 75, "danger", location_id, {"tool_name": tool_name})
    if tool_name == "v6_declare_personal_bankruptcy":
        forgiven = int(sum(float(loan.get("principal_remaining", 0)) for loan in loans) * 0.55)
        wallet["liabilities"] = []
        profile = {**_default_profile(actor), **(wallet.get("economy_profile") or {})}
        profile["bankruptcy_count"] = int(profile.get("bankruptcy_count", 0)) + 1
        profile["credit_score"] = max(0, int(profile.get("credit_score", 60)) - 35)
        profile["debt_stress"] = max(25, int(profile.get("debt_stress", 0)) - 20)
        wallet["economy_profile"] = profile
        actor.wallet_json = wallet
        return _econ_event(session, world, actor, "v6_bankruptcy", f"{actor.chosen_name} 申请了个人破产，部分债务被清掉，但信用几乎塌了一截。", 85, "danger", location_id, {"forgiven": forgiven})
    source = "bank"
    amount = 50
    rate = 0.01
    purpose = "cash"
    if tool_name == "v6_ask_friend_for_small_loan":
        source, amount, rate = "friend", 24, 0.002
    elif tool_name == "v6_borrow_from_loan_shark":
        source, amount, rate = "loan_shark", 90, 0.045
    elif tool_name == "v6_take_new_loan_to_pay_old_debt":
        source, amount, rate = "bank", max(40, int(sum(float(loan.get("minimum_payment_daily", 0)) for loan in loans) * 6)), 0.018
    elif tool_name == "v6_borrow_to_keep_luxury_life":
        source, amount, rate, purpose = "bank", 80, 0.018, "luxury"
    limit = _loan_limit(actor, source)
    if amount > limit:
        if limit < 12:
            _adjust_credit(actor, -2)
            return _tool_failed(session, world, actor, location_id, "额度不足，贷款被拒。")
        amount = int(limit)
    loan = {
        "loan_id": f"loan_{uuid.uuid4().hex[:10]}",
        "lender_type": source,
        "principal_remaining": amount,
        "interest_rate_daily": rate,
        "minimum_payment_daily": max(1, round(amount * 0.035 + amount * rate, 2)),
        "missed_payment_count": 0,
        "default_state": "current",
        "purpose": purpose,
        "created_world_time": world.current_world_time_minutes,
    }
    wallet["liabilities"] = [*loans, loan]
    actor.wallet_json = wallet
    _change_money(actor, amount)
    _ledger(actor, world, "loan_disbursement", amount, f"{source} 借款", {"loan_id": loan["loan_id"], "purpose": purpose})
    _adjust_debt_stress(actor, 8 if source != "loan_shark" else 20)
    text = f"{actor.chosen_name} 从{_lender_label(source)}借到 {amount}。钱到账了，债务也一起落到了账本上。"
    return _econ_event(session, world, actor, "v6_loan", text, 60 if source != "loan_shark" else 75, "debt", location_id, {"loan": loan, "purpose": purpose, "tool_name": tool_name})


def _housing_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any], params: dict[str, Any] | None = None) -> Event:
    params = params or {}
    wallet = ensure_v6_agent_state(actor)
    housing = {**_default_housing(actor), **(wallet.get("housing") or {})}
    day = world.current_world_time_minutes // 1440
    if tool_name == "v6_pay_10_day_rent":
        rent = int(housing.get("rent_per_10_days", RENT_PER_10_DAYS))
        if wallet_money(actor) < rent:
            return _tool_failed(session, world, actor, location_id, "现金不够支付十天房租。")
        _change_money(actor, -rent)
        housing["next_rent_due_day"] = max(day, int(housing.get("next_rent_due_day", day))) + RENT_INTERVAL_DAYS
        housing["rent_late_count"] = 0
        housing["homeless"] = False
        wallet["housing"] = housing
        actor.wallet_json = wallet
        _ledger(actor, world, "rent_payment", -rent, "支付房租", {})
        return _econ_event(session, world, actor, "v6_rent_payment", f"{actor.chosen_name} 支付了接下来十天的房租。", 45, "debt", location_id, {"rent": rent, "housing": housing})
    if tool_name in {"v6_ask_landlord_for_grace_period", "v6_negotiate_lower_rent"}:
        if tool_name == "v6_ask_landlord_for_grace_period":
            housing["next_rent_due_day"] = int(housing.get("next_rent_due_day", day)) + 1
            text = f"{actor.chosen_name} 向系统房东请求宽限，获得了一天缓冲。"
        else:
            old = int(housing.get("rent_per_10_days", RENT_PER_10_DAYS))
            housing["rent_per_10_days"] = max(18, old - 3)
            text = f"{actor.chosen_name} 协商降低房租，十天租金从 {old} 降到 {housing['rent_per_10_days']}。"
        wallet["housing"] = housing
        actor.wallet_json = wallet
        _adjust_credit(actor, -1)
        return _econ_event(session, world, actor, "v6_rent_negotiation", text, 45, "debt", location_id, {"housing": housing})
    if tool_name == "v6_move_to_cheaper_room":
        housing["rent_per_10_days"] = 20
        housing["quality_tier"] = "small_room"
        wallet["housing"] = housing
        actor.wallet_json = wallet
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, mood=-2, stress=-2))
        return _econ_event(session, world, actor, "v6_housing_move", f"{actor.chosen_name} 搬去了更便宜的小房间，生活体面下降，但账单轻了一些。", 55, "debt", location_id, {"housing": housing})
    if tool_name in {"v6_search_temporary_shelter", "v6_sleep_rough_when_homeless"}:
        if tool_name == "v6_search_temporary_shelter":
            housing["temporary_shelter_until_day"] = day + 2
            delta = apply_delta(actor.dynamic_state, stress=-8, mood=2) if actor.dynamic_state else {}
            text = f"{actor.chosen_name} 找到了一处临时庇护，可以暂时不用露宿。"
            payload_extra: dict[str, Any] = {}
        else:
            # 露宿不能再是立即 +8 体力的“假睡”。这里直接登记真实睡眠调度，醒来时由 complete_scheduled_sleep 统一恢复体力、整理梦境并结算露宿风险。
            raw_hours = params.get("sleep_hours") or params.get("hours") or 8
            try:
                hours = max(1.0, min(10.0, round(float(raw_hours) * 2) / 2))
            except (TypeError, ValueError):
                hours = 8.0
            requested_duration = int(hours * 60)
            remaining = _remaining_sleep_minutes_today(actor, world.current_world_time_minutes)
            used_today = max(0, MAX_SLEEP_MINUTES_PER_DAY - remaining)
            duration = max(0, min(requested_duration, remaining))
            if duration <= 0:
                return _econ_event(
                    session,
                    world,
                    actor,
                    "sleep_failed",
                    f"{actor.chosen_name} 想找个角落继续睡，但今天已经睡得太久，只能清醒地坐起来。",
                    25,
                    "info",
                    location_id,
                    {"sleep_blocked_by_daily_limit": True, "sleep_is_real_schedule": False},
                )
            actor.desires_json = {
                **(actor.desires_json or {}),
                "sleep_until_world_time": world.current_world_time_minutes + duration,
                "sleep_started_world_time": world.current_world_time_minutes,
                "sleep_planned_minutes": duration,
                "sleep_requested_minutes": requested_duration,
                "sleep_quality": "rough",
                "rough_sleep_location_id": location_id,
                "sleep_quota_day": _sleep_quota_day(world.current_world_time_minutes),
                "sleep_minutes_today": used_today,
                "sleep_capped_by_daily_limit": duration < requested_duration,
            }
            delta = {}
            actual_hours = round(duration / 60, 1)
            text = f"{actor.chosen_name} 找了个角落露宿，真正进入睡眠调度，预计睡约 {actual_hours:g} 小时。"
            if duration < requested_duration:
                text += " 原本想睡得更久，但身体最多只能睡到自然醒。"
            payload_extra = {"sleep_hours": actual_hours, "sleep_requested_hours": hours, "sleep_until_world_time": world.current_world_time_minutes + duration, "sleep_is_real_schedule": True, "sleep_capped_by_daily_limit": duration < requested_duration}
        wallet["housing"] = housing
        actor.wallet_json = wallet
        if delta:
            state_delta.setdefault(actor.agent_id, {}).update(delta)
        return _econ_event(session, world, actor, "v6_homeless_survival", text, 60, "warning", location_id, {"housing": housing, "tool_name": tool_name, **payload_extra})
    if tool_name == "v6_offer_labor_for_rent":
        housing["next_rent_due_day"] = int(housing.get("next_rent_due_day", day)) + 2
        wallet["housing"] = housing
        actor.wallet_json = wallet
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, energy=-8, stress=2))
        return _econ_event(session, world, actor, "v6_labor_for_rent", f"{actor.chosen_name} 用额外劳动换来了两天房租缓冲。", 50, "debt", location_id, {"housing": housing})
    if tool_name == "v6_apply_for_mortgage":
        profile = wallet.get("economy_profile") or {}
        if wallet_money(actor) < HOUSE_DOWN_PAYMENT:
            return _tool_failed(session, world, actor, location_id, "首付不够，房贷流程无法开始。")
        approval = int(profile.get("credit_score", 60)) * 0.6 + int(profile.get("daily_income_avg", 0)) * 0.8 - int(profile.get("minimum_payment_daily", 0)) * 2
        if approval < 38:
            _adjust_credit(actor, -3)
            return _econ_event(session, world, actor, "v6_mortgage_denied", f"{actor.chosen_name} 申请房贷被拒，银行认为收入、信用或负债不够稳。", 60, "warning", location_id, {"approval_score": approval})
        _change_money(actor, -HOUSE_DOWN_PAYMENT)
        asset = _asset("house", "小公寓", HOUSE_PRICE, status_value=45, can_collateralize=True, can_rent_out=True)
        _add_asset(actor, asset)
        mortgage = {
            "loan_id": f"mortgage_{uuid.uuid4().hex[:10]}",
            "lender_type": "mortgage_bank",
            "principal_remaining": HOUSE_PRICE - HOUSE_DOWN_PAYMENT,
            "interest_rate_daily": 0.002,
            "minimum_payment_daily": MORTGAGE_DAILY_PAYMENT,
            "missed_payment_count": 0,
            "default_state": "current",
            "collateral_asset_ids": [asset["asset_id"]],
        }
        wallet = ensure_v6_agent_state(actor)
        wallet["liabilities"] = [*(wallet.get("liabilities") or []), mortgage]
        wallet["housing"] = {**housing, "status": "homeowner", "owned_home_asset_id": asset["asset_id"], "homeless": False}
        actor.wallet_json = wallet
        _ledger(actor, world, "house_down_payment", -HOUSE_DOWN_PAYMENT, "买房首付", {"asset_id": asset["asset_id"]})
        return _econ_event(session, world, actor, "v6_mortgage_approved", f"{actor.chosen_name} 付了首付，买下一套小公寓，同时背上了每天还款的房贷。", 85, "important", location_id, {"asset": asset, "mortgage": mortgage})
    if tool_name == "v6_prepay_mortgage":
        return _loan_action(session, world, actor, "v6_repay_extra_principal", location_id, state_delta)
    if tool_name in {"v6_list_house_for_rent", "v6_enable_system_void_tenant", "v6_disable_system_void_tenant", "v6_collect_system_tenant_rent"}:
        house = _first_asset(wallet, "house")
        if not house:
            return _tool_failed(session, world, actor, location_id, "名下没有可出租的房产。")
        if tool_name == "v6_list_house_for_rent":
            house["is_listed_for_rent"] = True
            house["asking_rent_per_10_days"] = 42
            text = f"{actor.chosen_name} 把名下房屋挂牌出租，十天租金标为 42。"
        elif tool_name == "v6_enable_system_void_tenant":
            house["system_tenant_enabled"] = True
            house["system_tenant_rent_per_10_days"] = 30
            house["next_system_rent_day"] = day + RENT_INTERVAL_DAYS
            text = f"{actor.chosen_name} 启用了系统虚空租客。系统租客不会进入故事，只会按固定租金付款。"
        elif tool_name == "v6_disable_system_void_tenant":
            house["system_tenant_enabled"] = False
            text = f"{actor.chosen_name} 停止了系统虚空出租。"
        else:
            due = int(house.get("next_system_rent_day") or 0)
            if not house.get("system_tenant_enabled"):
                return _tool_failed(session, world, actor, location_id, "这套房没有启用系统租客。")
            if day < due:
                return _econ_event(session, world, actor, "v6_void_rent_wait", f"{actor.chosen_name} 查看系统租客租金，但还没到固定付款日。", 25, "economy", location_id, {"house": house})
            rent = int(house.get("system_tenant_rent_per_10_days", 30))
            _change_money(actor, rent)
            house["next_system_rent_day"] = day + RENT_INTERVAL_DAYS
            _ledger(actor, world, "rent_income", rent, "系统租客固定租金", {"asset_id": house["asset_id"]})
            text = f"系统租客向 {actor.chosen_name} 支付了 {rent} 固定租金，没有产生任何对话或剧情互动。"
        _replace_asset(actor, house)
        return _econ_event(session, world, actor, "v6_landlord", text, 55, "economy", location_id, {"house": house, "tool_name": tool_name})
    return _econ_event(session, world, actor, "v6_housing", f"{actor.chosen_name} 认真考虑了一下住房和房租压力。", 30, "economy", location_id, {"tool_name": tool_name})


def _transport_action(session: Session, world: World, actor: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> Event:
    if tool_name in {"v6_buy_bicycle", "v6_buy_cheap_car", "v6_buy_normal_car", "v6_buy_luxury_car"}:
        specs = {
            "v6_buy_bicycle": ("自行车", "bicycle", 60, 8, 0),
            "v6_buy_cheap_car": ("廉价汽车", "cheap_car", 260, 22, 6),
            "v6_buy_normal_car": ("普通汽车", "normal_car", 520, 35, 8),
            "v6_buy_luxury_car": ("豪车", "luxury_car", 1100, 85, 18),
        }
        name, vehicle_type, price, status, fuel = specs[tool_name]
        if wallet_money(actor) < price:
            return _tool_failed(session, world, actor, location_id, f"钱不够买{name}。")
        _change_money(actor, -price)
        vehicle = _asset("vehicle", name, price, status_value=status, can_collateralize=True)
        vehicle.update({"vehicle_type": vehicle_type, "fuel": fuel, "maintenance_due": 0})
        wallet = ensure_v6_agent_state(actor)
        wallet["vehicles"] = [*(wallet.get("vehicles") or []), vehicle]
        wallet["assets"] = [*(wallet.get("assets") or []), vehicle]
        actor.wallet_json = wallet
        _ledger(actor, world, "vehicle_purchase", -price, name, {"vehicle_id": vehicle["asset_id"]})
        _apply_hedonic(actor, 25 if status < 40 else 70, tier="symbolic")
        return _econ_event(session, world, actor, "v6_vehicle", f"{actor.chosen_name} 买下了{name}。移动会更快，但维护、折旧和阶层信号也随之出现。", 65 if status >= 80 else 45, "luxury" if status >= 80 else "economy", location_id, {"vehicle": vehicle})
    if tool_name == "v6_check_fuel_price":
        return _econ_event(session, world, actor, "v6_fuel_price", f"{actor.chosen_name} 查看了今日油价: {(_market(world).get('fuel_price') or 4):.2f}。", 20, "economy", location_id, {"market": _market(world)})
    if tool_name == "v6_complain_about_fuel_price":
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, stress=-2, social=1))
        return _econ_event(session, world, actor, "v6_fuel_complaint", f"{actor.chosen_name} 抱怨油价让出行和工作成本变高。", 30, "economy", location_id, {"fuel_price": _market(world).get("fuel_price")})
    wallet = ensure_v6_agent_state(actor)
    vehicles = wallet.get("vehicles") or []
    vehicle = vehicles[0] if vehicles else None
    if tool_name in {"v6_fuel_vehicle", "v6_perform_vehicle_maintenance", "v6_repair_bicycle"}:
        if not vehicle:
            return _tool_failed(session, world, actor, location_id, "没有交通工具。")
        cost = 12 if tool_name == "v6_fuel_vehicle" else 18 if vehicle.get("vehicle_type") != "bicycle" else 8
        if wallet_money(actor) < cost:
            return _tool_failed(session, world, actor, location_id, "钱不够支付这次保养或加油。")
        _change_money(actor, -cost)
        vehicle["fuel"] = max(float(vehicle.get("fuel", 0)), 20)
        vehicle["maintenance_due"] = max(0, float(vehicle.get("maintenance_due", 0)) - 30)
        _replace_vehicle(actor, vehicle)
        return _econ_event(session, world, actor, "v6_vehicle_service", f"{actor.chosen_name} 花 {cost} 处理了交通工具的燃料或维护。", 35, "economy", location_id, {"vehicle": vehicle, "cost": cost})
    if tool_name == "v6_sell_vehicle":
        if not vehicle:
            return _tool_failed(session, world, actor, location_id, "没有交通工具可卖。")
        amount = int(float(vehicle.get("market_value", 0)) * 0.7)
        _remove_asset(actor, vehicle["asset_id"])
        wallet = ensure_v6_agent_state(actor)
        wallet["vehicles"] = [item for item in (wallet.get("vehicles") or []) if item.get("asset_id") != vehicle["asset_id"]]
        actor.wallet_json = wallet
        _change_money(actor, amount)
        _ledger(actor, world, "vehicle_sale", amount, "出售车辆", {"vehicle_id": vehicle["asset_id"]})
        return _econ_event(session, world, actor, "v6_vehicle_sale", f"{actor.chosen_name} 卖掉了{vehicle.get('display_name_zh')}，换回 {amount}。", 45, "economy", location_id, {"amount": amount})
    if tool_name == "v6_show_off_vehicle" and vehicle:
        _apply_hedonic(actor, 40, tier="symbolic")
        return _econ_event(session, world, actor, "v6_status_signal", f"{actor.chosen_name} 展示了自己的{vehicle.get('display_name_zh')}，这会成为别人评价她生活状态的一个信号。", 45, "luxury", location_id, {"vehicle": vehicle})
    return _travel_event(session, world, actor, tool_name, params, location_id, state_delta, vehicle)


def _creator_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> Event:
    wallet = ensure_v6_agent_state(actor)
    creator = {**_default_creator(actor), **(wallet.get("creator_profile") or {})}
    rng = random.Random(f"creator:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{tool_name}")
    if tool_name == "v6_buy_creator_equipment":
        if wallet_money(actor) < 80:
            return _tool_failed(session, world, actor, location_id, "钱不够买创作设备。")
        _change_money(actor, -80)
        asset = _asset("tool", "基础创作设备", 80, status_value=8)
        _add_asset(actor, asset)
        creator["equipment_level"] = max(int(creator.get("equipment_level", 0)), 1)
        wallet["creator_profile"] = creator
        actor.wallet_json = wallet
        return _econ_event(session, world, actor, "v6_creator_equipment", f"{actor.chosen_name} 买了基础创作设备，创作上限稍微提高。", 45, "economy", location_id, {"asset": asset})
    if tool_name == "v6_sell_creator_equipment":
        asset = _first_asset(wallet, "tool")
        if not asset:
            return _tool_failed(session, world, actor, location_id, "没有创作设备可卖。")
        amount = int(float(asset.get("market_value", 0)) * 0.65)
        _remove_asset(actor, asset["asset_id"])
        _change_money(actor, amount)
        creator["equipment_level"] = 0
        wallet = ensure_v6_agent_state(actor)
        wallet["creator_profile"] = creator
        actor.wallet_json = wallet
        return _econ_event(session, world, actor, "v6_creator_equipment_sale", f"{actor.chosen_name} 卖掉创作设备换了 {amount}，短期现金回来了，创作能力却下降。", 45, "economy", location_id, {"amount": amount})
    if tool_name in {"v6_choose_video_topic", "v6_film_video", "v6_edit_video", "v6_compose_music", "v6_paint_artwork", "v6_write_story_or_blog", "v6_follow_trend", "v6_ignore_trend_make_personal_work"}:
        skill_key = "creator_skill_video" if "video" in tool_name or "trend" in tool_name else "creator_skill_music" if "music" in tool_name or "song" in tool_name else "creator_skill_art" if "art" in tool_name else "creator_skill_video"
        creator[skill_key] = min(100, int(creator.get(skill_key, 35)) + 2)
        creator["drafts"] = int(creator.get("drafts", 0)) + 1
        creator["burnout"] = min(100, int(creator.get("burnout", 0)) + 4)
        wallet["creator_profile"] = creator
        actor.wallet_json = wallet
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, energy=-8, fun=5, stress=2))
        return _econ_event(session, world, actor, "v6_creator_work", f"{actor.chosen_name} 投入了一段创作。作品还没变现，但技能和草稿都增加了。", 40, "creator", location_id, {"creator_profile": creator, "tool_name": tool_name})
    if tool_name in {"v6_upload_video", "v6_release_song", "v6_sell_artwork", "v6_publish_story_or_blog", "v6_livestream", "v6_promote_creation", "v6_monetize_audience"}:
        drafts = int(creator.get("drafts", 0))
        quality = (int(creator.get("creator_skill_video", 35)) + int(creator.get("creator_skill_music", 35)) + int(creator.get("creator_skill_art", 35))) / 3
        quality += int(creator.get("equipment_level", 0)) * 8 + rng.randint(-20, 25)
        if drafts <= 0 and tool_name != "v6_livestream":
            return _tool_failed(session, world, actor, location_id, "没有可以发布或出售的作品草稿。")
        viral = rng.random() < max(0.02, min(0.18, quality / 650))
        if viral:
            income = rng.randint(120, 420)
            audience = rng.randint(80, 600)
            event_type = "v6_creator_viral"
            text = f"{actor.chosen_name} 的作品突然爆红，带来 {income} 收入和一批新观众。"
            importance = 90
            color = "creator"
            _apply_hedonic(actor, 80, tier="symbolic")
        elif quality > 55:
            income = rng.randint(18, 80)
            audience = rng.randint(10, 90)
            event_type = "v6_creator_income"
            text = f"{actor.chosen_name} 发布的作品有了一点回响，赚到 {income}。"
            importance = 55
            color = "economy"
        else:
            income = rng.randint(0, 8)
            audience = rng.randint(0, 8)
            event_type = "v6_creator_work"
            text = f"{actor.chosen_name} 的作品几乎没有水花，只带来 {income} 收入。"
            importance = 35
            color = "normal"
        _change_money(actor, income)
        creator["drafts"] = max(0, drafts - 1)
        creator["audience_size"] = int(creator.get("audience_size", 0)) + audience
        creator["last_viral_day"] = world.current_world_time_minutes // 1440 if viral else creator.get("last_viral_day")
        wallet = ensure_v6_agent_state(actor)
        wallet["creator_profile"] = creator
        actor.wallet_json = wallet
        if income:
            _ledger(actor, world, "creator_income", income, "创作收入", {"viral": viral})
        return _econ_event(session, world, actor, event_type, text, importance, color, location_id, {"income": income, "audience_gain": audience, "creator_profile": creator, "tool_name": tool_name})
    if tool_name == "v6_rest_from_burnout":
        creator["burnout"] = max(0, int(creator.get("burnout", 0)) - 15)
        wallet["creator_profile"] = creator
        actor.wallet_json = wallet
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, stress=-8, energy=8))
        return _econ_event(session, world, actor, "v6_creator_rest", f"{actor.chosen_name} 暂停创作休息，倦怠感下降。", 30, "normal", location_id, {"creator_profile": creator})
    return _generic_v6_event(session, world, actor, tool_name, location_id)


def _stock_action(session: Session, world: World, actor: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> Event:
    wallet = ensure_v6_agent_state(actor)
    market = _market(world)
    broker = wallet.get("broker_account")
    if tool_name == "v6_open_broker_account":
        if wallet_money(actor) < 20:
            return _tool_failed(session, world, actor, location_id, "开户至少需要 20 现金。")
        _change_money(actor, -20)
        broker = {"cash_available": 20, "positions": {}, "short_positions": {}, "equity": 20, "margin_enabled": False, "short_enabled": False, "margin_debt": 0, "realized_pnl": 0, "unrealized_pnl": 0, "liquidation_warning_level": "none"}
        wallet = ensure_v6_agent_state(actor)
        wallet["broker_account"] = broker
        actor.wallet_json = wallet
        _ledger(actor, world, "broker_deposit", -20, "证券开户入金", {})
        return _econ_event(session, world, actor, "v6_stock_account", f"{actor.chosen_name} 开通了游戏内模拟证券账户。这里的股票全是虚构市场，不是现实投资建议。", 55, "stock", location_id, {"broker": broker, "market": market})
    if not broker:
        return _tool_failed(session, world, actor, location_id, "还没有证券账户。")
    if tool_name == "v6_deposit_to_broker":
        amount = min(wallet_money(actor), int(params_amount(params, 20)))
        if amount <= 0:
            return _tool_failed(session, world, actor, location_id, "没有现金可转入证券账户。")
        _change_money(actor, -amount)
        broker["cash_available"] = round(float(broker.get("cash_available", 0)) + amount, 2)
        _update_broker_equity(broker, market)
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_stock_cash", f"{actor.chosen_name} 向证券账户转入 {amount}。", 35, "stock", location_id, {"broker": broker})
    if tool_name == "v6_withdraw_from_broker":
        amount = int(min(float(broker.get("cash_available", 0)), params_amount(params, 20)))
        if amount <= 0:
            return _tool_failed(session, world, actor, location_id, "证券账户没有可取现金。")
        broker["cash_available"] = round(float(broker.get("cash_available", 0)) - amount, 2)
        _change_money(actor, amount)
        _update_broker_equity(broker, market)
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_stock_cash", f"{actor.chosen_name} 从证券账户取回 {amount} 现金。", 35, "stock", location_id, {"broker": broker})
    if tool_name in {"v6_read_market_news", "v6_research_company_fundamentals", "v6_review_price_chart"}:
        ticker, company = _pick_ticker(market, actor, tool_name, params)
        text = f"{actor.chosen_name} 研究了虚构股票 {ticker}（{company['name_zh']}），看到当前价格 {company['price']:.2f}，市场状态是 {market.get('regime')}。未来仍然不可知。"
        return _econ_event(session, world, actor, "v6_stock_research", text, 30, "stock", location_id, {"ticker": ticker, "company": company, "market": market})
    if tool_name in {"v6_enable_margin_account", "v6_enable_short_selling"}:
        if tool_name == "v6_enable_margin_account":
            broker["margin_enabled"] = True
            text = f"{actor.chosen_name} 开通了保证金账户，未来可以用杠杆，但也可能被强制平仓。"
        else:
            broker["short_enabled"] = True
            text = f"{actor.chosen_name} 开通了做空权限。价格上涨会让空头亏损，风险没有上限。"
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_stock_permission", text, 65, "stock", location_id, {"broker": broker})
    ticker, company = _pick_ticker(market, actor, tool_name, params)
    price = float(company["price"])
    fee_rate = 0.012
    slippage = max(0.02, price * 0.008)
    if tool_name in {"v6_place_market_buy_order", "v6_buy_stock_on_margin"}:
        budget = min(float(broker.get("cash_available", 0)), 30.0)
        if tool_name == "v6_buy_stock_on_margin" and broker.get("margin_enabled"):
            budget += min(60.0, max(0.0, float(broker.get("equity", 0))))
            broker["margin_debt"] = round(float(broker.get("margin_debt", 0)) + max(0, budget - float(broker.get("cash_available", 0))), 2)
        qty = max(0, int(budget // (price + slippage)))
        cost = round(qty * (price + slippage) * (1 + fee_rate), 2)
        if qty <= 0 or (cost > float(broker.get("cash_available", 0)) and not broker.get("margin_enabled")):
            return _tool_failed(session, world, actor, location_id, "证券账户现金或保证金不足，买入失败。")
        broker["cash_available"] = round(float(broker.get("cash_available", 0)) - min(cost, float(broker.get("cash_available", 0))), 2)
        positions = broker.setdefault("positions", {})
        old = positions.get(ticker, {"quantity": 0, "avg_price": price})
        new_qty = int(old.get("quantity", 0)) + qty
        old_cost = int(old.get("quantity", 0)) * float(old.get("avg_price", price))
        positions[ticker] = {"quantity": new_qty, "avg_price": round((old_cost + qty * (price + slippage)) / max(1, new_qty), 2)}
        _update_broker_equity(broker, market)
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_stock_trade", f"{actor.chosen_name} 买入了 {qty} 股 {ticker}。成交包含手续费和滑点，未来涨跌未知。", 60, "stock", location_id, {"ticker": ticker, "quantity": qty, "price": price, "cost": cost, "broker": broker})
    if tool_name in {"v6_place_market_sell_order", "v6_panic_sell", "v6_take_profit_calmly", "v6_reduce_leveraged_position"}:
        positions = broker.setdefault("positions", {})
        pos = positions.get(ticker) or next(iter(positions.values()), None)
        if not pos:
            return _tool_failed(session, world, actor, location_id, "没有可卖出的持仓。")
        sell_ticker = ticker if ticker in positions else next(iter(positions.keys()))
        pos = positions[sell_ticker]
        qty = max(1, int(pos.get("quantity", 0) // 2 or pos.get("quantity", 0)))
        proceeds = round(qty * max(0.01, price - slippage) * (1 - fee_rate), 2)
        pnl = round((price - float(pos.get("avg_price", price))) * qty, 2)
        pos["quantity"] = int(pos.get("quantity", 0)) - qty
        if pos["quantity"] <= 0:
            positions.pop(sell_ticker, None)
        broker["cash_available"] = round(float(broker.get("cash_available", 0)) + proceeds, 2)
        broker["realized_pnl"] = round(float(broker.get("realized_pnl", 0)) + pnl, 2)
        if broker.get("margin_debt", 0) and tool_name == "v6_reduce_leveraged_position":
            repay = min(float(broker.get("margin_debt", 0)), proceeds * 0.5)
            broker["cash_available"] -= repay
            broker["margin_debt"] = round(float(broker.get("margin_debt", 0)) - repay, 2)
        _update_broker_equity(broker, market)
        _save_broker(actor, broker)
        color = "stock_gain" if pnl >= 0 else "danger"
        return _econ_event(session, world, actor, "v6_stock_trade", f"{actor.chosen_name} 卖出 {qty} 股 {sell_ticker}，本次已实现盈亏 {pnl:.2f}。", 65 if abs(pnl) > 10 else 45, color, location_id, {"ticker": sell_ticker, "quantity": qty, "pnl": pnl, "broker": broker})
    if tool_name in {"v6_short_sell_stock", "v6_buy_to_cover_short"}:
        if not broker.get("short_enabled"):
            return _tool_failed(session, world, actor, location_id, "尚未开通做空权限。")
        if tool_name == "v6_short_sell_stock":
            qty = 2
            proceeds = round(qty * max(0.01, price - slippage) * (1 - fee_rate), 2)
            broker.setdefault("short_positions", {})[ticker] = {"quantity": qty, "avg_price": price}
            broker["cash_available"] = round(float(broker.get("cash_available", 0)) + proceeds, 2)
            text = f"{actor.chosen_name} 做空了 {ticker}。如果价格上涨，这笔交易会迅速亏损。"
        else:
            shorts = broker.setdefault("short_positions", {})
            short = shorts.get(ticker) or next(iter(shorts.values()), None)
            if not short:
                return _tool_failed(session, world, actor, location_id, "没有空头仓位可平。")
            cover_ticker = ticker if ticker in shorts else next(iter(shorts.keys()))
            short = shorts[cover_ticker]
            qty = int(short.get("quantity", 0))
            cost = round(qty * (price + slippage) * (1 + fee_rate), 2)
            pnl = round((float(short.get("avg_price", price)) - price) * qty, 2)
            if float(broker.get("cash_available", 0)) < cost:
                return _tool_failed(session, world, actor, location_id, "现金不够买回平空。")
            broker["cash_available"] = round(float(broker.get("cash_available", 0)) - cost, 2)
            broker["realized_pnl"] = round(float(broker.get("realized_pnl", 0)) + pnl, 2)
            shorts.pop(cover_ticker, None)
            text = f"{actor.chosen_name} 买回平空 {cover_ticker}，本次盈亏 {pnl:.2f}。"
        _update_broker_equity(broker, market)
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_stock_trade", text, 75, "stock", location_id, {"broker": broker, "tool_name": tool_name})
    if tool_name in {"v6_add_margin_cash", "v6_accept_margin_call"}:
        amount = min(wallet_money(actor), 20)
        if amount <= 0:
            return _tool_failed(session, world, actor, location_id, "没有现金可追加保证金。")
        _change_money(actor, -amount)
        broker["cash_available"] = round(float(broker.get("cash_available", 0)) + amount, 2)
        broker["liquidation_warning_level"] = "none"
        _update_broker_equity(broker, market)
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_margin_call", f"{actor.chosen_name} 追加了 {amount} 保证金，暂时压住爆仓风险。", 70, "stock", location_id, {"broker": broker})
    if tool_name == "v6_do_nothing_during_margin_call":
        broker["liquidation_warning_level"] = "danger"
        _save_broker(actor, broker)
        return _econ_event(session, world, actor, "v6_margin_call", f"{actor.chosen_name} 无视了保证金警告，下一次结算可能被强制平仓。", 80, "danger", location_id, {"broker": broker})
    return _generic_v6_event(session, world, actor, tool_name, location_id)


def _daily_agent_economy(session: Session, world: World, agent: Agent, day: int) -> list[int]:
    ensure_v6_agent_state(agent)
    event_ids: list[int] = []
    wallet = ensure_v6_agent_state(agent)
    if _is_dependent_minor(agent):
        update_derived_economy(agent)
        return []
    housing = {**_default_housing(agent), **(wallet.get("housing") or {})}
    hedonic = {**_default_hedonic(), **(wallet.get("hedonic_state") or {})}
    hedonic["luxury_threshold"] = max(0, float(hedonic.get("luxury_threshold", 0)) - 0.18)
    hedonic["deprivation_pain"] = max(0, float(hedonic.get("deprivation_pain", 0)) - 0.35)
    wallet["hedonic_state"] = hedonic
    wallet["housing"] = housing
    agent.wallet_json = wallet
    event_ids.extend(_daily_rent(session, world, agent, day))
    event_ids.extend(_daily_debt(session, world, agent, day))
    event_ids.extend(_daily_mortgage(session, world, agent, day))
    event_ids.extend(_daily_landlord(session, world, agent, day))
    if finance_investing_enabled(world):
        event_ids.extend(_daily_stock(session, world, agent))
    _daily_depreciation(agent)
    update_derived_economy(agent)
    return event_ids


def _is_finance_investing_tool(tool_name: str) -> bool:
    return tool_name.startswith("v6_") and any(
        token in tool_name
        for token in ["stock", "broker", "market", "margin", "short", "profit", "loss", "chart", "company"]
    )


def _is_survival_consumption_tool(tool_name: str) -> bool:
    return tool_name in {
        "v6_buy_basic_food_for_survival",
        "v6_buy_normal_meal",
        "v6_buy_premium_meal_for_dopamine",
        "v6_buy_luxury_meal",
        "v6_buy_status_drink",
        "v6_cut_food_spending_without_changing_satiety",
    }


def _daily_rent(session: Session, world: World, agent: Agent, day: int) -> list[int]:
    wallet = ensure_v6_agent_state(agent)
    if _is_dependent_minor(agent):
        return []
    housing = {**_default_housing(agent), **(wallet.get("housing") or {})}
    if housing.get("status") == "homeowner" or housing.get("homeless"):
        if housing.get("homeless"):
            profile = wallet.get("economy_profile") or {}
            profile["homeless_days"] = int(profile.get("homeless_days", 0)) + 1
            wallet["economy_profile"] = profile
            agent.wallet_json = wallet
        return []
    due_day = int(housing.get("next_rent_due_day") or RENT_INTERVAL_DAYS)
    if day < due_day:
        return []
    rent = int(housing.get("rent_per_10_days", RENT_PER_10_DAYS))
    if wallet_money(agent) >= rent:
        _change_money(agent, -rent)
        housing["next_rent_due_day"] = day + RENT_INTERVAL_DAYS
        housing["rent_late_count"] = 0
        wallet = ensure_v6_agent_state(agent)
        wallet["housing"] = housing
        agent.wallet_json = wallet
        _ledger(agent, world, "rent_payment", -rent, "自动支付房租", {})
        event = _econ_event(session, world, agent, "v6_rent_payment", f"{agent.chosen_name} 在到期日自动支付了十天房租。", 35, "debt", agent.location.location_id if agent.location else None, {"rent": rent, "day": day})
        return [event.event_id]
    debt_stress = float((wallet.get("economy_profile") or {}).get("debt_stress", 0))
    if debt_stress < 95:
        loan = {
            "loan_id": f"loan_{uuid.uuid4().hex[:10]}",
            "lender_type": "rent_credit",
            "principal_remaining": rent,
            "interest_rate_daily": 0.012,
            "minimum_payment_daily": max(1, round(rent * 0.045, 2)),
            "missed_payment_count": 0,
            "default_state": "current",
            "purpose": "rent",
            "created_world_time": world.current_world_time_minutes,
        }
        housing["next_rent_due_day"] = day + RENT_INTERVAL_DAYS
        housing["rent_late_count"] = 0
        wallet["housing"] = housing
        wallet["liabilities"] = [*(wallet.get("liabilities") or []), loan]
        agent.wallet_json = wallet
        _ledger(agent, world, "rent_credit", -rent, "房租转为债务", {"loan_id": loan["loan_id"]})
        _adjust_debt_stress(agent, 10)
        event = _econ_event(
            session,
            world,
            agent,
            "v6_rent_debt",
            f"{agent.chosen_name} 没有足够现金交房租，只能把这期房租记成债务，暂时保住了住所。",
            75,
            "warning",
            agent.location.location_id if agent.location else None,
            {"rent": rent, "loan": loan, "housing": housing, "day": day},
        )
        return [event.event_id]

    late = int(housing.get("rent_late_count", 0)) + 1
    housing["rent_late_count"] = late
    wallet["housing"] = housing
    agent.wallet_json = wallet
    _adjust_debt_stress(agent, 8)
    events = [_econ_event(session, world, agent, "v6_rent_late", f"{agent.chosen_name} 没能按时交房租，已经逾期 {late} 天。", 65, "warning", agent.location.location_id if agent.location else None, {"rent": rent, "late": late}).event_id]
    if late > RENT_GRACE_DAYS:
        housing["homeless"] = True
        housing["status"] = "homeless"
        housing["evicted_day"] = day
        wallet = ensure_v6_agent_state(agent)
        wallet["housing"] = housing
        agent.wallet_json = wallet
        if agent.location:
            central = f"{world.world_id}:central_square"
            destination = session.get(Location, central)
            if destination:
                agent.location.location_id = central
                agent.location.location = destination
                agent.location.arrived_at_world_time = world.current_world_time_minutes
        if agent.dynamic_state:
            apply_delta(agent.dynamic_state, stress=20, mood=-12, energy=-8)
        events.append(_econ_event(session, world, agent, "v6_eviction", f"{agent.chosen_name} 因连续拖欠房租被系统房东驱逐，失去了稳定住所。", 90, "danger", agent.location.location_id if agent.location else None, {"housing": housing}).event_id)
    return events


def _daily_debt(session: Session, world: World, agent: Agent, day: int) -> list[int]:
    wallet = ensure_v6_agent_state(agent)
    loans = wallet.get("liabilities") or []
    events: list[int] = []
    changed = False
    for loan in loans:
        if loan.get("lender_type") == "mortgage_bank" or loan.get("default_state") == "charged_off":
            continue
        principal = float(loan.get("principal_remaining", 0))
        interest = round(principal * float(loan.get("interest_rate_daily", 0.01)), 2)
        loan["principal_remaining"] = round(principal + interest, 2)
        min_pay = int(math.ceil(float(loan.get("minimum_payment_daily", 1))))
        if wallet_money(agent) >= min_pay:
            _change_money(agent, -min_pay)
            loan["principal_remaining"] = max(0, round(float(loan.get("principal_remaining", 0)) - min_pay, 2))
            loan["missed_payment_count"] = 0
            loan["default_state"] = "current"
            _ledger(agent, world, "debt_payment", -min_pay, "自动最低还款", {"loan_id": loan.get("loan_id")})
        else:
            loan["missed_payment_count"] = int(loan.get("missed_payment_count", 0)) + 1
            loan["default_state"] = "late" if loan["missed_payment_count"] < 3 else "defaulted"
            _adjust_credit(agent, -2 if loan["default_state"] == "late" else -6)
            _adjust_debt_stress(agent, 7 if loan["default_state"] == "late" else 14)
            events.append(_econ_event(session, world, agent, "v6_debt_late", f"{agent.chosen_name} 没能偿还一笔最低还款，债务压力继续上升。", 65 if loan["default_state"] == "late" else 80, "warning" if loan["default_state"] == "late" else "danger", agent.location.location_id if agent.location else None, {"loan": loan, "day": day}).event_id)
        changed = True
    if changed:
        wallet = ensure_v6_agent_state(agent)
        wallet["liabilities"] = [loan for loan in loans if float(loan.get("principal_remaining", 0)) > 0.1]
        agent.wallet_json = wallet
    return events


def _daily_mortgage(session: Session, world: World, agent: Agent, day: int) -> list[int]:
    wallet = ensure_v6_agent_state(agent)
    loans = wallet.get("liabilities") or []
    mortgages = [loan for loan in loans if loan.get("lender_type") == "mortgage_bank"]
    events = []
    for loan in mortgages:
        loan["principal_remaining"] = round(float(loan.get("principal_remaining", 0)) * (1 + float(loan.get("interest_rate_daily", 0.002))), 2)
        pay = int(math.ceil(float(loan.get("minimum_payment_daily", MORTGAGE_DAILY_PAYMENT))))
        if wallet_money(agent) >= pay:
            _change_money(agent, -pay)
            loan["principal_remaining"] = round(float(loan.get("principal_remaining", 0)) - pay, 2)
            loan["missed_payment_count"] = 0
            loan["default_state"] = "current"
            _ledger(agent, world, "mortgage_payment", -pay, "每日房贷", {"loan_id": loan.get("loan_id")})
        else:
            loan["missed_payment_count"] = int(loan.get("missed_payment_count", 0)) + 1
            loan["default_state"] = "late"
            _adjust_debt_stress(agent, 12)
            events.append(_econ_event(session, world, agent, "v6_mortgage_late", f"{agent.chosen_name} 今天没能支付房贷，房子开始压得更沉。", 75, "warning", agent.location.location_id if agent.location else None, {"loan": loan, "day": day}).event_id)
            if int(loan.get("missed_payment_count", 0)) >= 5:
                wallet = ensure_v6_agent_state(agent)
                collateral = set(loan.get("collateral_asset_ids") or [])
                wallet["assets"] = [asset for asset in (wallet.get("assets") or []) if asset.get("asset_id") not in collateral]
                wallet["liabilities"] = [item for item in (wallet.get("liabilities") or []) if item.get("loan_id") != loan.get("loan_id")]
                housing = {**_default_housing(agent), **(wallet.get("housing") or {})}
                housing["status"] = "homeless"
                housing["homeless"] = True
                wallet["housing"] = housing
                agent.wallet_json = wallet
                _adjust_credit(agent, -25)
                events.append(_econ_event(session, world, agent, "v6_foreclosure", f"{agent.chosen_name} 连续断供，房屋被止赎收回。", 95, "danger", agent.location.location_id if agent.location else None, {"loan": loan}).event_id)
    wallet = ensure_v6_agent_state(agent)
    wallet["liabilities"] = [loan for loan in loans if float(loan.get("principal_remaining", 0)) > 0.1]
    agent.wallet_json = wallet
    return events


def _daily_landlord(session: Session, world: World, agent: Agent, day: int) -> list[int]:
    wallet = ensure_v6_agent_state(agent)
    events = []
    for house in list(wallet.get("assets") or []):
        if house.get("asset_type") != "house" or not house.get("system_tenant_enabled"):
            continue
        due = int(house.get("next_system_rent_day") or day + RENT_INTERVAL_DAYS)
        if day < due:
            continue
        rent = int(house.get("system_tenant_rent_per_10_days", 30))
        _change_money(agent, rent)
        house["next_system_rent_day"] = day + RENT_INTERVAL_DAYS
        _replace_asset(agent, house)
        _ledger(agent, world, "rent_income", rent, "系统租客固定租金", {"asset_id": house.get("asset_id")})
        events.append(_econ_event(session, world, agent, "v6_void_tenant_rent", f"系统租客按固定合约向 {agent.chosen_name} 支付 {rent} 租金。", 40, "economy", agent.location.location_id if agent.location else None, {"house": house}).event_id)
    return events


def _daily_stock(session: Session, world: World, agent: Agent) -> list[int]:
    wallet = ensure_v6_agent_state(agent)
    broker = wallet.get("broker_account")
    if not broker:
        return []
    market = _market(world)
    _update_broker_equity(broker, market)
    _save_broker(agent, broker)
    gross = _gross_position_value(broker, market)
    equity = float(broker.get("equity", 0))
    if gross > 0 and equity < gross * 0.22:
        broker["liquidation_warning_level"] = "danger"
        _save_broker(agent, broker)
        if equity < gross * 0.12:
            loss = _liquidate_broker(broker, market)
            _save_broker(agent, broker)
            _adjust_debt_stress(agent, 25)
            event = _econ_event(session, world, agent, "v6_forced_liquidation", f"{agent.chosen_name} 的保证金账户被强制平仓，已实现损失 {loss:.2f}。", 95, "danger", agent.location.location_id if agent.location else None, {"broker": broker, "loss": loss})
            return [event.event_id]
        event = _econ_event(session, world, agent, "v6_margin_call", f"{agent.chosen_name} 收到保证金警告，如果不追加资金或降低仓位，可能被强制平仓。", 80, "warning", agent.location.location_id if agent.location else None, {"broker": broker})
        return [event.event_id]
    return []


def _daily_depreciation(agent: Agent) -> None:
    wallet = ensure_v6_agent_state(agent)
    for asset in wallet.get("assets") or []:
        asset["market_value"] = round(float(asset.get("market_value", 0)) * (1 - float(asset.get("depreciation_rate_daily", 0.001))), 2)
    for vehicle in wallet.get("vehicles") or []:
        vehicle["maintenance_due"] = min(100, float(vehicle.get("maintenance_due", 0)) + 1.2)
    agent.wallet_json = wallet


def _update_world_markets(world: World, day: int) -> None:
    settings = dict(world.settings_json or {})
    market = settings.get("v6_market") or _default_market(world)
    rng = random.Random(f"market:{world.seed}:{day}")
    regime = str(market.get("regime", "sideways"))
    if rng.random() < 0.08:
        regime = rng.choices(["bull", "bear", "sideways", "bubble", "crash", "recovery"], weights=[22, 18, 35, 8, 5, 12])[0]
    drift = {"bull": 0.012, "bear": -0.012, "sideways": 0.0, "bubble": 0.024, "crash": -0.065, "recovery": 0.016}.get(regime, 0)
    stocks = market.get("stocks") or {}
    for ticker, company in stocks.items():
        volatility = float(company.get("volatility", 0.08))
        move = drift + rng.gauss(0, volatility / 2.5)
        if rng.random() < float(company.get("fraud_risk", 0.01)):
            move -= rng.uniform(0.12, 0.35)
            market["news"] = f"{company['name_zh']} 出现黑天鹅传闻，市场剧烈波动。"
        old_price = float(company.get("price", 10))
        price = max(1.0, min(300.0, old_price * math.exp(move)))
        company["previous_price"] = round(old_price, 2)
        company["price"] = round(price, 2)
        company["day_change"] = round((company["price"] - old_price) / max(0.01, old_price), 4)
        company["change"] = round(company["price"] - old_price, 2)
        company["change_pct"] = round(company["day_change"] * 100, 2)
        history = list(company.get("history") or [])
        if not history:
            history.append({"day": max(0, day - 1), "price": round(old_price, 2)})
        history.append({"day": day, "price": company["price"]})
        company["history"] = history[-90:]
    fuel = float(market.get("fuel_price", 4.0))
    market["fuel_price"] = round(max(2.2, min(9.5, fuel * (1 + rng.gauss(0, 0.035)))), 2)
    market["regime"] = regime
    market["day"] = day
    settings["v6_market"] = market
    world.settings_json = settings


def _default_profile(agent: Agent) -> dict[str, Any]:
    traits = agent.traits
    desires = agent.desires_json or {}
    discipline = traits.discipline if traits else 50
    caution = traits.caution if traits else 50
    creativity = traits.creativity if traits else 50
    openness = traits.openness if traits else 50
    return {
        "cash": wallet_money(agent),
        "bank_balance": 0,
        "daily_income_avg": 0,
        "daily_expense_avg": 0,
        "net_worth": wallet_money(agent),
        "total_debt": 0,
        "minimum_payment_daily": 0,
        "credit_score": 62,
        "risk_tolerance": int((openness + max(0, 100 - caution)) / 2),
        "frugality": int((discipline + caution) / 2),
        "materialism": int(desires.get("status_need", 25)),
        "self_control": discipline,
        "financial_literacy": int((discipline + creativity) / 2),
        "debt_stress": 0,
        "luxury_expectation": 8,
        "status_anxiety": int(desires.get("status_need", 25)),
        "homeless_days": 0,
        "bankruptcy_count": 0,
    }


def _default_hedonic() -> dict[str, Any]:
    return {"recent_dopamine": 0, "hedonic_baseline": 12, "luxury_threshold": 8.0, "deprivation_pain": 0.0, "adaptation_rate": 0.18, "recovery_rate": 0.04, "luxury_memory_tags": []}


def _default_housing(agent: Agent) -> dict[str, Any]:
    if _is_dependent_minor(agent):
        return _dependent_housing(agent, agent.location.location_id if agent.location else None)
    profile = profile_for_agent(agent)
    return {
        "status": "renter",
        "quality_tier": "small_room",
        "rent_per_10_days": int(profile["rent_per_10"]),
        "next_rent_due_day": RENT_INTERVAL_DAYS,
        "rent_grace_days": int(profile["rent_grace_days"]),
        "rent_late_count": 0,
        "homeless": False,
        "home_location_id": agent.location.location_id if agent.location else None,
    }


def _is_dependent_minor(agent: Agent) -> bool:
    return agent.age_stage in {"newborn", "infant", "toddler", "child", "teen"}


def _dependent_housing(agent: Agent, home_location_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "dependent",
        "quality_tier": "guardian_home",
        "rent_per_10_days": 0,
        "next_rent_due_day": None,
        "rent_late_count": 0,
        "homeless": False,
        "home_location_id": home_location_id or (agent.location.location_id if agent.location else None),
        "guardian_dependent": True,
    }


def _default_creator(agent: Agent) -> dict[str, Any]:
    creativity = agent.traits.creativity if agent.traits else 50
    return {"creator_skill_video": max(10, creativity - 10), "creator_skill_music": max(10, creativity - 5), "creator_skill_art": creativity, "audience_size": 0, "audience_loyalty": 20, "trend_fit": 50, "burnout": 0, "last_viral_day": None, "income_volatility": 1.0, "drafts": 0, "equipment_level": 0}


def _default_social_status(agent: Agent) -> dict[str, Any]:
    traits = agent.traits
    return {"wealth_preference": 45, "romantic_idealism": 55, "security_need": 45, "anti_materialism": traits.honesty if traits else 50, "jealousy_sensitivity": traits.neuroticism if traits else 50, "dependency_fear": 35, "generosity_preference": 55}


def _default_market(world: World) -> dict[str, Any]:
    return {
        "regime": "sideways",
        "fuel_price": 4.0,
        "day": 0,
        "news": "虚构交易所今日正常开盘。游戏内模拟市场不提供现实投资建议。",
        "stocks": {
            ticker: {
                "ticker": ticker,
                "name_zh": name,
                "sector": sector,
                "price": price,
                "previous_price": price,
                "change": 0,
                "change_pct": 0,
                "day_change": 0,
                "history": [{"day": 0, "price": price}],
                "fundamental_value": round(price * 0.95, 2),
                "volatility": vol,
                "liquidity": 60,
                "sentiment": 0,
                "fraud_risk": round(vol / 8, 4),
            }
            for ticker, (name, sector, price, vol) in MARKET_TICKERS.items()
        },
    }


def _market(world: World) -> dict[str, Any]:
    settings = dict(world.settings_json or {})
    market = settings.get("v6_market") or _default_market(world)
    day = int(market.get("day") or 0)
    for ticker, company in (market.get("stocks") or {}).items():
        price = round(float(company.get("price", 0) or 0), 2)
        previous = round(float(company.get("previous_price", price) or price), 2)
        company.setdefault("ticker", ticker)
        company.setdefault("previous_price", previous)
        company.setdefault("change", round(price - previous, 2))
        company.setdefault("change_pct", round((price - previous) / max(0.01, previous) * 100, 2))
        company.setdefault("day_change", round((price - previous) / max(0.01, previous), 4))
        history = list(company.get("history") or [])
        if not history:
            history.append({"day": day, "price": price})
        company["history"] = history[-90:]
    settings["v6_market"] = market
    world.settings_json = settings
    return market


def _change_money(agent: Agent, amount: int) -> None:
    ensure_v5_agent_state(agent)
    wallet = dict(agent.wallet_json or {})
    wallet["money"] = max(0, int(wallet.get("money", 0)) + int(amount))
    agent.wallet_json = wallet


def _ledger(agent: Agent, world: World, kind: str, amount: float, label: str, extra: dict[str, Any]) -> None:
    wallet = ensure_v6_agent_state(agent)
    ledger = list(wallet.get("economy_ledger") or [])
    ledger.append({"world_time": world.current_world_time_minutes, "kind": kind, "amount": round(amount, 2), "label": label, **extra})
    wallet["economy_ledger"] = ledger[-120:]
    agent.wallet_json = wallet


def _econ_event(session: Session, world: World, actor: Agent, event_type: str, text: str, importance: int, color: str, location_id: str | None, payload: dict[str, Any]) -> Event:
    update_derived_economy(actor)
    return create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=importance, color_class=color, payload=payload)


def _tool_failed(session: Session, world: World, actor: Agent, location_id: str | None, text: str) -> Event:
    return create_event(session, world=world, event_type="tool_failed", actor_agent_id=actor.agent_id, location_id=location_id, visibility_scope="system", viewer_text=f"{actor.chosen_name} 没能执行 v6 经济工具: {text}", agent_visible_text=text, importance=20, color_class="warning", no_state_changed=True)


def _generic_v6_event(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None) -> Event:
    return _econ_event(session, world, actor, "v6_generic", f"{actor.chosen_name} 考虑了一个经济相关行动，但当前只记录为抽象计划，实际资产和账本没有被 LLM 改写。", 15, "economy", location_id, {"tool_name": tool_name, "no_direct_llm_effect": True})


def _apply_hedonic(agent: Agent, pleasure: float, *, tier: str) -> dict[str, float]:
    wallet = ensure_v6_agent_state(agent)
    hedonic = {**_default_hedonic(), **(wallet.get("hedonic_state") or {})}
    threshold = float(hedonic.get("luxury_threshold", 0))
    gap = pleasure - threshold
    if gap >= 0:
        mood = min(8, 1 + gap / 15)
        fun = min(10, 2 + gap / 12)
        hedonic["luxury_threshold"] = min(100, threshold + float(hedonic.get("adaptation_rate", 0.18)) * gap)
        hedonic["deprivation_pain"] = max(0, float(hedonic.get("deprivation_pain", 0)) - 1)
    else:
        mood = -min(8, abs(gap) / 10)
        fun = -min(5, abs(gap) / 20)
        hedonic["deprivation_pain"] = min(100, float(hedonic.get("deprivation_pain", 0)) + abs(gap) * 0.08)
    hedonic["recent_dopamine"] = pleasure
    if tier in {"premium", "luxury", "symbolic"}:
        tags = list(hedonic.get("luxury_memory_tags") or [])
        tags.append(tier)
        hedonic["luxury_memory_tags"] = tags[-12:]
    wallet["hedonic_state"] = hedonic
    profile = {**_default_profile(agent), **(wallet.get("economy_profile") or {})}
    profile["luxury_expectation"] = round(hedonic["luxury_threshold"], 2)
    wallet["economy_profile"] = profile
    agent.wallet_json = wallet
    return {"mood": mood, "fun": fun, "stress": -1 if gap >= 0 else 2}


def _adjust_credit(agent: Agent, delta: int) -> None:
    wallet = ensure_v6_agent_state(agent)
    profile = {**_default_profile(agent), **(wallet.get("economy_profile") or {})}
    profile["credit_score"] = int(clamp(int(profile.get("credit_score", 60)) + delta, 0, 100))
    wallet["economy_profile"] = profile
    agent.wallet_json = wallet


def _adjust_debt_stress(agent: Agent, delta: int) -> None:
    wallet = ensure_v6_agent_state(agent)
    profile = {**_default_profile(agent), **(wallet.get("economy_profile") or {})}
    profile["debt_stress"] = int(clamp(int(profile.get("debt_stress", 0)) + delta, 0, 100))
    wallet["economy_profile"] = profile
    agent.wallet_json = wallet


def _loan_limit(agent: Agent, source: str) -> int:
    profile = update_derived_economy(agent)
    income = float(profile.get("daily_income_avg", 0))
    credit = int(profile.get("credit_score", 60))
    debt = float(profile.get("total_debt", 0))
    if source == "friend":
        return 35
    if source == "loan_shark":
        stress = int(profile.get("debt_stress", 0))
        return max(25, min(140, 60 + stress - debt * 0.15))
    return max(0, int(25 + income * 3.5 + credit * 0.45 - debt * 0.18))


def _lender_label(source: str) -> str:
    return {"friend": "朋友", "bank": "银行", "loan_shark": "高利贷方"}.get(source, source)


def _asset(asset_type: str, name: str, price: float, *, status_value: int = 0, can_collateralize: bool = False, can_rent_out: bool = False) -> dict[str, Any]:
    return {
        "asset_id": f"asset_{uuid.uuid4().hex[:10]}",
        "asset_type": asset_type,
        "display_name_zh": name,
        "purchase_price": price,
        "market_value": round(price * 0.92, 2),
        "liquidation_value": round(price * 0.55, 2),
        "status_value": status_value,
        "maintenance_cost_daily": 0.2 if asset_type in {"vehicle", "house"} else 0,
        "depreciation_rate_daily": 0.0015 if asset_type == "vehicle" else 0.0002 if asset_type == "house" else 0.002,
        "can_collateralize": can_collateralize,
        "can_rent_out": can_rent_out,
        "is_repossessable": asset_type in {"vehicle", "house"},
    }


def _add_asset(agent: Agent, asset: dict[str, Any]) -> None:
    wallet = ensure_v6_agent_state(agent)
    wallet["assets"] = [*(wallet.get("assets") or []), asset]
    agent.wallet_json = wallet


def _remove_asset(agent: Agent, asset_id: str) -> None:
    wallet = ensure_v6_agent_state(agent)
    wallet["assets"] = [asset for asset in (wallet.get("assets") or []) if asset.get("asset_id") != asset_id]
    wallet["vehicles"] = [asset for asset in (wallet.get("vehicles") or []) if asset.get("asset_id") != asset_id]
    agent.wallet_json = wallet


def _replace_asset(agent: Agent, asset: dict[str, Any]) -> None:
    wallet = ensure_v6_agent_state(agent)
    wallet["assets"] = [asset if item.get("asset_id") == asset.get("asset_id") else item for item in (wallet.get("assets") or [])]
    agent.wallet_json = wallet


def _replace_vehicle(agent: Agent, vehicle: dict[str, Any]) -> None:
    wallet = ensure_v6_agent_state(agent)
    wallet["vehicles"] = [vehicle if item.get("asset_id") == vehicle.get("asset_id") else item for item in (wallet.get("vehicles") or [])]
    wallet["assets"] = [vehicle if item.get("asset_id") == vehicle.get("asset_id") else item for item in (wallet.get("assets") or [])]
    agent.wallet_json = wallet


def _has_asset(wallet: dict[str, Any], asset_type: str) -> bool:
    return any(asset.get("asset_type") == asset_type for asset in wallet.get("assets") or [])


def _first_asset(wallet: dict[str, Any], asset_type: str) -> dict[str, Any] | None:
    return next((asset for asset in wallet.get("assets") or [] if asset.get("asset_type") == asset_type), None)


def _owns_house(wallet: dict[str, Any]) -> bool:
    return _has_asset(wallet, "house")


def _travel_event(session: Session, world: World, actor: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any], vehicle: dict[str, Any] | None) -> Event:
    cost = 0
    speed_note = "步行慢但免费"
    if tool_name == "v6_take_bus":
        cost = 2
        speed_note = "公交比步行快，但需要车费"
    elif tool_name in {"v6_drive_car", "v6_ride_bicycle"} and vehicle:
        fuel_price = float(_market(world).get("fuel_price", 4))
        cost = 0 if vehicle.get("vehicle_type") == "bicycle" else max(1, int(fuel_price * 1.5))
        speed_note = "交通工具节省了时间，也增加了维护负担"
        vehicle["maintenance_due"] = min(100, float(vehicle.get("maintenance_due", 0)) + 5)
        if vehicle.get("vehicle_type") != "bicycle":
            vehicle["fuel"] = max(0, float(vehicle.get("fuel", 0)) - 2)
        _replace_vehicle(actor, vehicle)
    if cost and wallet_money(actor) < cost:
        return _tool_failed(session, world, actor, location_id, "钱不够支付这次出行成本。")
    if cost:
        _change_money(actor, -cost)
    destination = _optional_destination(session, actor, params)
    before = location_id
    if destination and actor.location:
        actor.location.location_id = destination.location_id
        actor.location.location = destination
        actor.location.arrived_at_world_time = world.current_world_time_minutes
    if actor.dynamic_state:
        state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, energy=-2 if cost else -5, stress=-1))
    text = f"{actor.chosen_name} 选择出行方式: {speed_note}。"
    if destination:
        text += f" 她从{_loc_name(session, before)}到了{destination.public_name}。"
    return _econ_event(session, world, actor, "v6_transport", text, 30, "economy", destination.location_id if destination else location_id, {"tool_name": tool_name, "cost": cost, "vehicle": vehicle})


def _optional_destination(session: Session, actor: Agent, params: dict[str, Any]) -> Location | None:
    if not actor.location:
        return None
    raw = str(params.get("location_id") or params.get("location_name") or "")
    if not raw:
        return None
    for loc_id in actor.location.location.neighbors_json or []:
        loc = session.get(Location, loc_id)
        if loc and (raw == loc.location_id or raw == loc.public_name or raw in loc.location_id):
            return loc
    return None


def _loc_name(session: Session, location_id: str | None) -> str:
    loc = session.get(Location, location_id) if location_id else None
    return loc.public_name if loc else "未知地点"


def _save_broker(agent: Agent, broker: dict[str, Any]) -> None:
    wallet = ensure_v6_agent_state(agent)
    wallet["broker_account"] = broker
    agent.wallet_json = wallet


def _pick_ticker(market: dict[str, Any], actor: Agent, salt: str, params: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    stocks = market.get("stocks") or {}
    tickers = sorted(stocks)
    requested = str((params or {}).get("ticker") or "").upper()
    if requested in stocks:
        return requested, stocks[requested]
    ticker = random.Random(f"{actor.agent_id}:{salt}").choice(tickers)
    return ticker, stocks[ticker]


def _update_broker_equity(broker: dict[str, Any], market: dict[str, Any]) -> None:
    stocks = market.get("stocks") or {}
    long_value = 0.0
    cost_basis = 0.0
    for ticker, pos in (broker.get("positions") or {}).items():
        price = float((stocks.get(ticker) or {}).get("price", pos.get("avg_price", 0)))
        qty = int(pos.get("quantity", 0))
        long_value += price * qty
        cost_basis += float(pos.get("avg_price", price)) * qty
    short_liability = 0.0
    short_basis = 0.0
    for ticker, pos in (broker.get("short_positions") or {}).items():
        price = float((stocks.get(ticker) or {}).get("price", pos.get("avg_price", 0)))
        qty = int(pos.get("quantity", 0))
        short_liability += price * qty
        short_basis += float(pos.get("avg_price", price)) * qty
    broker["unrealized_pnl"] = round((long_value - cost_basis) + (short_basis - short_liability), 2)
    broker["equity"] = round(float(broker.get("cash_available", 0)) + long_value - short_liability - float(broker.get("margin_debt", 0)), 2)


def _gross_position_value(broker: dict[str, Any], market: dict[str, Any]) -> float:
    stocks = market.get("stocks") or {}
    total = 0.0
    for positions in [broker.get("positions") or {}, broker.get("short_positions") or {}]:
        for ticker, pos in positions.items():
            total += int(pos.get("quantity", 0)) * float((stocks.get(ticker) or {}).get("price", pos.get("avg_price", 0)))
    return total


def _liquidate_broker(broker: dict[str, Any], market: dict[str, Any]) -> float:
    _update_broker_equity(broker, market)
    before = float(broker.get("equity", 0))
    broker["positions"] = {}
    broker["short_positions"] = {}
    broker["margin_debt"] = max(0, -before)
    broker["cash_available"] = max(0, before)
    broker["equity"] = max(0, before)
    broker["liquidation_warning_level"] = "liquidated"
    broker["realized_pnl"] = round(float(broker.get("realized_pnl", 0)) + min(0, before), 2)
    return abs(min(0, before))


def params_amount(params: dict[str, Any], fallback: int) -> int:
    try:
        return max(1, int(params.get("amount") or fallback))
    except (TypeError, ValueError):
        return fallback


def _sleep_quota_day(world_time: int) -> int:
    return world_time // 1440 + 1


def _remaining_sleep_minutes_today(actor: Agent, world_time: int) -> int:
    desires = actor.desires_json or {}
    day = _sleep_quota_day(world_time)
    try:
        recorded_day = int(desires.get("sleep_quota_day") or -1)
    except (TypeError, ValueError):
        recorded_day = -1
    if recorded_day != day:
        return MAX_SLEEP_MINUTES_PER_DAY
    try:
        used = int(desires.get("sleep_minutes_today") or 0)
    except (TypeError, ValueError):
        used = 0
    return max(0, MAX_SLEEP_MINUTES_PER_DAY - used)


def _day_from_agent_location(agent: Agent) -> int:
    if agent.dynamic_state:
        return max(0, agent.dynamic_state.last_decay_world_time // 1440)
    return 0


def _gini(values: list[float]) -> float:
    clean = sorted(max(0.0, float(value)) for value in values)
    if not clean or sum(clean) == 0:
        return 0.0
    n = len(clean)
    weighted = sum((idx + 1) * value for idx, value in enumerate(clean))
    return (2 * weighted) / (n * sum(clean)) - (n + 1) / n


def _count_events(events: list[Event], event_type: str) -> int:
    return sum(1 for event in events if event.event_type == event_type)
