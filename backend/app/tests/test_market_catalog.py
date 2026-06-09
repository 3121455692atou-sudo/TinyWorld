from __future__ import annotations

from sqlalchemy import select

from app.agents.v5_state import add_money, wallet_money
from app.core.models import Event, Inventory, Item, Location
from app.effects.effect_engine import execute_tool
from app.knowledge.perception import build_turn_context_with_options
from app.knowledge.relationships import get_relationship
from app.market.catalog import (
    buy_market_item,
    consume_market_food,
    inquire_market_items,
    is_market_food_spoiled,
    load_market_catalog,
    parse_market_item_metadata,
    pick_up_placed_item,
    place_inventory_item,
    recommend_market_items,
    search_market_items,
    transfer_inventory_item,
    visible_placed_items,
)
from app.tests.conftest import make_world
from app.tools.registry import available_tools
from app.world.seed_world import world_location_id
from app.world.werewolf import initialize_werewolf_game


def test_market_catalog_loads_and_searches_tea_family():
    catalog = load_market_catalog()

    assert len(catalog) >= 10
    assert all(item.price >= 0 for item in catalog)
    assert all(item.spoil_after_hours == 24 for item in catalog if item.kind == "food")

    names = [item.name for item in search_market_items("抹茶", catalog=catalog)]
    assert "抹茶麻薯" in names
    assert "抹茶咖啡" in names
    assert "绿茶饼干" in names

    tea_names = [item.name for item in search_market_items("茶", catalog=catalog)]
    assert {"抹茶麻薯", "抹茶咖啡", "绿茶饼干"}.issubset(set(tea_names))


def test_market_recommendations_are_deterministic_and_return_ten_items():
    catalog = load_market_catalog()

    first = recommend_market_items(seed=1234, world_time=3 * 1440 + 20, agent_id="agent_0", catalog=catalog)
    second = recommend_market_items(seed=1234, world_time=3 * 1440 + 20, agent_id="agent_0", catalog=catalog)

    assert len(first) == 10
    assert [item.item_id for item in first] == [item.item_id for item in second]


def test_market_inquiry_text_is_vendor_neutral(db):
    world, agents = make_world(db, agent_count=1)
    actor = agents[0]

    result = inquire_market_items(db, world=world, actor=actor, item_query="抹茶")
    db.flush()

    assert result.ok is True
    event = db.get(Event, result.event_id)
    assert event.viewer_text.startswith(f"{actor.chosen_name} 询问“抹茶”，可购买 抹茶麻薯(8)")
    assert "摊主" not in event.viewer_text
    assert "向摊主" not in event.viewer_text


def test_market_purchase_creates_inventory_item_with_metadata(db):
    world, agents = make_world(db, agent_count=1)
    actor = agents[0]
    before_money = wallet_money(actor)

    result = buy_market_item(db, world=world, actor=actor, catalog_item_id="food.matcha_mochi")
    db.flush()

    assert result.ok is True
    assert wallet_money(actor) == before_money - 8
    item = db.get(Item, result.item_ids[0])
    assert item is not None
    assert item.name == "抹茶麻薯"
    assert item.item_type == "market_food"
    assert parse_market_item_metadata(item.description)["spoil_after_hours"] == 24
    inv = db.execute(select(Inventory).where(Inventory.agent_id == actor.agent_id, Inventory.item_id == item.item_id)).scalar_one()
    assert inv.quantity == 1


def test_market_tools_are_available_and_execute_through_game_chain(db):
    world, agents = make_world(db, agent_count=2)
    actor, target = agents
    market = db.get(Location, f"{world.world_id}:market")
    assert market is not None
    market.available_tools_json = ["speak_to_nearby"]
    actor.location.location_id = market.location_id
    target.location.location_id = market.location_id
    add_money(actor, 100)
    db.flush()
    db.expire(actor.location, ["location"])
    db.expire(target.location, ["location"])

    tool_names = {tool.tool_name for tool in available_tools(actor, market, session=db)}
    assert {"market_search_goods", "market_recommend_goods", "market_buy_goods"}.issubset(tool_names)

    context = build_turn_context_with_options(db, world, actor)
    buy_options = [option for option in context.action_options if option.tool_name == "market_buy_goods"]
    assert buy_options
    assert buy_options[0].label == "购买商品"
    assert buy_options[0].text_slot == "item_query"
    assert buy_options[0].text_required is True

    purchase = execute_tool(db, world=world, actor=actor, tool_name="market_buy_goods", params={"item_query": "茶"})
    db.flush()

    assert purchase.ok is True
    event = db.get(Event, purchase.event_ids[0])
    assert event is not None
    assert event.event_type == "market_purchase"
    bought_name = db.execute(
        select(Item.name)
        .join(Inventory, Inventory.item_id == Item.item_id)
        .where(Inventory.agent_id == actor.agent_id)
    ).scalar_one()
    assert "茶" in bought_name

    context = build_turn_context_with_options(db, world, actor)
    gift_options = [option for option in context.action_options if option.tool_name == "gift_item_to_visible_agent"]
    assert gift_options
    choice_params = [choice["params"] for choice in gift_options[0].target_choices]
    assert any(params.get("item_name") == bought_name and params.get("visible_ref") in context.ref_map for params in choice_params)


def test_market_food_consumption_applies_satiety_and_blocks_spoiled_food(db):
    world, agents = make_world(db, agent_count=1)
    actor = agents[0]
    actor.dynamic_state.satiety = 40
    actor.dynamic_state.mood = -10
    fresh = buy_market_item(db, world=world, actor=actor, catalog_item_id="food.matcha_mochi")
    db.flush()

    result = consume_market_food(db, world=world, actor=actor, item_query="抹茶")
    db.flush()

    assert result.ok is True
    assert actor.dynamic_state.satiety > 40

    stale = buy_market_item(db, world=world, actor=actor, catalog_item_id="food.green_tea_cookie")
    world.current_world_time_minutes = 24 * 60
    stale_item = db.get(Item, stale.item_ids[0])
    assert stale_item is not None
    assert is_market_food_spoiled(stale_item, current_world_time=world.current_world_time_minutes)

    spoiled_result = consume_market_food(db, world=world, actor=actor, item_query="绿茶")
    db.flush()

    assert spoiled_result.ok is False
    assert spoiled_result.message == "food_spoiled"
    still_owned = db.execute(select(Inventory).where(Inventory.agent_id == actor.agent_id, Inventory.item_id == stale_item.item_id)).scalar_one()
    assert still_owned.quantity == 1


def test_inventory_consumption_uses_item_properties_for_drinks(db):
    world, agents = make_world(db, agent_count=1)
    actor = agents[0]
    actor.dynamic_state.hydration = 25
    drink = buy_market_item(db, world=world, actor=actor, catalog_item_id="food.bottled_water")
    db.flush()

    result = consume_market_food(db, world=world, actor=actor, item_query="瓶装水")
    db.flush()

    assert result.ok is True
    assert actor.dynamic_state.hydration > 25
    event = db.get(Event, result.event_id)
    assert event.event_type == "market_drink_consumed"
    assert "喝掉了" in event.viewer_text
    assert db.get(Item, drink.item_ids[0]) is None


def test_inventory_consumption_supports_legacy_water_items(db):
    world, agents = make_world(db, agent_count=1)
    actor = agents[0]
    actor.dynamic_state.hydration = 30
    item = Item(item_id="legacy_water", world_id=world.world_id, name="瓶装水", description="旧生存系统生成的随身水。", item_type="water")
    db.add(item)
    db.flush()
    db.add(Inventory(agent_id=actor.agent_id, item_id=item.item_id, quantity=1))
    db.flush()

    result = consume_market_food(db, world=world, actor=actor, item_query="瓶装水")
    db.flush()

    assert result.ok is True
    assert actor.dynamic_state.hydration > 30
    event = db.get(Event, result.event_id)
    assert event.event_type == "market_drink_consumed"
    assert "喝掉了" in event.viewer_text


def test_werewolf_inventory_supplies_can_be_used_after_leaving_vending_machine(db):
    world, agents = make_world(db, agent_count=1)
    world.settings_json = {"werewolf_mode_enabled": True, "core_toolset_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    actor = agents[0]
    add_money(actor, 100)
    actor.dynamic_state.satiety = 20
    actor.dynamic_state.hydration = 20
    vending = db.get(Location, world_location_id(world.world_id, "vending_machine"))
    square = db.get(Location, world_location_id(world.world_id, "village_square"))
    assert vending is not None
    assert square is not None
    actor.location.location_id = vending.location_id
    actor.location.location = vending
    buy_market_item(db, world=world, actor=actor, catalog_item_id="food.matcha_mochi")
    buy_market_item(db, world=world, actor=actor, catalog_item_id="food.bottled_water")
    actor.location.location_id = square.location_id
    actor.location.location = square
    db.flush()

    tool_names = {tool.tool_name for tool in available_tools(actor, square, session=db)}
    assert "eat_inventory_food" in tool_names
    assert not {"market_search_goods", "market_recommend_goods", "market_buy_goods"} & tool_names
    context = build_turn_context_with_options(db, world, actor)
    consume_options = [option for option in context.action_options if option.tool_name == "eat_inventory_food"]
    consume_item_names = {option.params.get("item_name") for option in consume_options}
    assert {"抹茶麻薯", "矿泉水"}.issubset(consume_item_names)

    eat = execute_tool(db, world=world, actor=actor, tool_name="eat_inventory_food", params={"item_name": "抹茶麻薯"})
    drink = execute_tool(db, world=world, actor=actor, tool_name="eat_inventory_food", params={"item_name": "矿泉水"})
    db.flush()

    assert eat.ok is True
    assert drink.ok is True
    assert actor.dynamic_state.satiety > 20
    assert actor.dynamic_state.hydration > 20
    drink_event = db.get(Event, drink.event_ids[0])
    assert drink_event.event_type == "market_drink_consumed"
    assert "喝掉了矿泉水" in drink_event.viewer_text


def test_werewolf_vending_machine_shows_purchase_action_option(db):
    world, agents = make_world(db, agent_count=1)
    world.settings_json = {"werewolf_mode_enabled": True, "core_toolset_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    actor = agents[0]
    vending = db.get(Location, world_location_id(world.world_id, "vending_machine"))
    assert vending is not None
    actor.location.location_id = vending.location_id
    actor.location.location = vending
    db.flush()

    context = build_turn_context_with_options(db, world, actor)
    buy_options = [option for option in context.action_options if option.tool_name == "market_buy_goods"]
    assert buy_options
    assert buy_options[0].label == "购买商品"
    assert buy_options[0].text_slot == "item_query"
    assert buy_options[0].text_required is True


def test_inventory_consumption_failure_text_is_not_mechanical(db):
    world, agents = make_world(db, agent_count=1)
    actor = agents[0]
    bought = buy_market_item(db, world=world, actor=actor, catalog_item_id="item.cotton_towel")
    db.flush()

    result = consume_market_food(db, world=world, actor=actor, item_query="毛巾")
    db.flush()

    assert result.ok is False
    assert result.message == "not_consumable"
    event = db.get(Event, result.event_id)
    assert "集市行动" not in event.viewer_text
    assert "工具" not in event.viewer_text
    assert "没有入口" in event.viewer_text
    assert db.execute(select(Inventory).where(Inventory.agent_id == actor.agent_id, Inventory.item_id == bought.item_ids[0])).scalar_one().quantity == 1


def test_placed_item_visibility_records_witness_only(db):
    world, agents = make_world(db, agent_count=3)
    actor, witness, absent = agents
    absent.location.location_id = f"{world.world_id}:market"
    buy_market_item(db, world=world, actor=actor, catalog_item_id="item.cotton_towel")
    db.flush()

    placed = place_inventory_item(db, world=world, actor=actor, item_query="毛巾")
    db.flush()

    assert placed.ok is True
    assert db.get(Item, placed.item_ids[0]).location_id == actor.location.location_id
    witness_view = visible_placed_items(db, world=world, observer=witness)
    assert witness_view[0]["name"] == "棉毛巾"
    assert witness_view[0]["placed_by_agent_id"] == actor.agent_id
    assert witness_view[0]["placed_by_name"] == actor.chosen_name

    absent.location.location_id = actor.location.location_id
    absent_view = visible_placed_items(db, world=world, observer=absent)
    assert absent_view[0]["name"] == "棉毛巾"
    assert absent_view[0]["placed_by_agent_id"] is None
    assert absent_view[0]["placed_by_name"] is None


def test_pick_up_and_transfer_gift_apply_target_preference(db):
    world, agents = make_world(db, agent_count=3)
    owner, giver, target = agents
    target.desires_json = {**(target.desires_json or {}), "gift_preferences": {"likes": ["实用"], "dislikes": ["苦味"]}}

    buy_market_item(db, world=world, actor=owner, catalog_item_id="item.small_flashlight")
    place_inventory_item(db, world=world, actor=owner, item_query="手电")
    picked = pick_up_placed_item(db, world=world, actor=giver, item_query="手电")
    db.flush()

    assert picked.ok is True
    assert db.execute(select(Inventory).where(Inventory.agent_id == giver.agent_id)).scalar_one().quantity == 1

    gift = transfer_inventory_item(db, world=world, actor=giver, target=target, item_query="手电", as_gift=True)
    db.flush()

    assert gift.ok is True
    assert gift.verdict == "liked"
    assert gift.affection_delta == 5
    rel = get_relationship(db, target.agent_id, giver.agent_id)
    assert rel.affection == 5

    add_money(giver, 20)
    buy_market_item(db, world=world, actor=giver, catalog_item_id="food.matcha_coffee")
    disliked = transfer_inventory_item(db, world=world, actor=giver, target=target, item_query="咖啡", as_gift=True)
    db.flush()

    assert disliked.ok is True
    assert disliked.verdict == "disliked"
    assert disliked.affection_delta == -5
    assert get_relationship(db, target.agent_id, giver.agent_id).affection == 0
