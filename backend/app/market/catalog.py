from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass
from importlib import resources
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import apply_delta
from app.agents.v5_state import add_money, wallet_money
from app.core.models import Agent, AgentLocation, Event, Inventory, Item, World
from app.events.event_store import create_event
from app.knowledge.relationships import adjust_relationship


CATALOG_PACKAGE = "app.content.market_catalog"
CATALOG_FILENAME = "items.json"
MARKET_META_MARKER = "[market_item_meta]"
MARKET_ITEM_TYPE_FOOD = "market_food"
MARKET_ITEM_TYPE_ITEM = "market_item"


@dataclass(frozen=True, slots=True)
class MarketCatalogItem:
    item_id: str
    kind: str
    name: str
    aliases: tuple[str, ...]
    description: str
    tags: tuple[str, ...]
    gift_tags: tuple[str, ...]
    price: int
    satiety_delta: float | None = None
    mood_delta: float | None = None
    spoil_after_hours: int | None = None

    @property
    def searchable_terms(self) -> tuple[str, ...]:
        return (self.item_id, self.name, *self.aliases, *self.tags, *self.gift_tags)


@dataclass(frozen=True, slots=True)
class MarketActionResult:
    ok: bool
    message: str
    event_id: int | None = None
    item_ids: tuple[str, ...] = ()
    verdict: str | None = None
    affection_delta: int = 0


def load_market_catalog() -> list[MarketCatalogItem]:
    raw = resources.files(CATALOG_PACKAGE).joinpath(CATALOG_FILENAME).read_text(encoding="utf-8")
    payload = json.loads(raw)
    return parse_market_catalog(payload)


def parse_market_catalog(payload: dict[str, Any]) -> list[MarketCatalogItem]:
    if int(payload.get("version") or 0) != 1:
        raise ValueError("market catalog version must be 1")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("market catalog items must be a list")
    seen: set[str] = set()
    items: list[MarketCatalogItem] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError(f"market catalog item #{index} must be an object")
        item = _parse_market_item(raw, index)
        if item.item_id in seen:
            raise ValueError(f"duplicate market item_id: {item.item_id}")
        seen.add(item.item_id)
        items.append(item)
    return items


def get_market_catalog_item(item_id: str, catalog: list[MarketCatalogItem] | None = None) -> MarketCatalogItem:
    for item in catalog or load_market_catalog():
        if item.item_id == item_id:
            return item
    raise KeyError(f"unknown market item_id: {item_id}")


def search_market_items(query: str, *, catalog: list[MarketCatalogItem] | None = None, limit: int = 20) -> list[MarketCatalogItem]:
    normalized_query = _normalize(query)
    if not normalized_query:
        return []
    scored: list[tuple[int, MarketCatalogItem]] = []
    for item in catalog or load_market_catalog():
        score = _match_score(normalized_query, item)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda row: (-row[0], row[1].price, row[1].name))
    return [item for _, item in scored[: max(0, limit)]]


def resolve_market_item_query(query: str, *, catalog: list[MarketCatalogItem] | None = None) -> MarketCatalogItem | None:
    matches = search_market_items(query, catalog=catalog, limit=1)
    return matches[0] if matches else None


def recommend_market_items(
    *,
    seed: int,
    world_time: int,
    agent_id: str,
    catalog: list[MarketCatalogItem] | None = None,
    count: int = 10,
) -> list[MarketCatalogItem]:
    items = list(catalog or load_market_catalog())
    rng = random.Random(f"market:{seed}:{world_time // 1440}:{agent_id}")
    rng.shuffle(items)
    return items[: max(0, min(count, len(items)))]


CAFETERIA_DAILY_FOOD_COUNT = 6


def _location_local_id(location_id: str | None) -> str:
    return str(location_id or "").split(":", 1)[-1]


def cafeteria_daily_catalog(world: World) -> list[MarketCatalogItem]:
    """A small, daily-rotating selection of foods the cafeteria stocks for sale.

    The system database has many foods; rather than the cafeteria always offering
    the same one item, it puts a few different foods on the counter each day. The
    market keeps the full searchable catalog.
    """
    foods = [item for item in load_market_catalog() if item.kind == "food"]
    if not foods:
        return load_market_catalog()
    rng = random.Random(f"cafeteria:{world.seed}:{world.current_world_time_minutes // 1440}")
    rng.shuffle(foods)
    return foods[: min(CAFETERIA_DAILY_FOOD_COUNT, len(foods))]


def effective_market_catalog(world: World, location_id: str | None) -> list[MarketCatalogItem] | None:
    """Catalog scoped by location: the cafeteria only stocks a few rotating foods
    each day; everywhere else (market, vending) keeps the full catalog (None)."""
    if _location_local_id(location_id) == "cafeteria":
        return cafeteria_daily_catalog(world)
    return None


def inquire_market_items(session: Session, *, world: World, actor: Agent, item_query: str, limit: int = 10) -> MarketActionResult:
    location_id = actor.location.location_id if actor.location else None
    query = str(item_query or "").strip()
    if not query:
        return _market_failure(session, world, actor, location_id, "你需要说出想买什么，例如“抹茶”或“毛巾”。", "query_missing")
    matches = search_market_items(query, catalog=effective_market_catalog(world, location_id), limit=limit)
    if not matches:
        event = create_event(
            session,
            world=world,
            event_type="market_inquiry",
            actor_agent_id=actor.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 询问“{query}”，没有找到合适商品。",
            agent_visible_text=f"没有找到和“{query}”匹配的商品。可以换个关键词，或查看推荐。",
            importance=15,
            payload={"query": query, "matches": []},
            no_state_changed=True,
        )
        return MarketActionResult(False, "no_matches", event.event_id)
    text = f"{actor.chosen_name} 询问“{query}”，可购买 {_format_catalog_names(matches)}。"
    event = create_event(
        session,
        world=world,
        event_type="market_inquiry",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=text,
        agent_visible_text=_format_catalog_for_agent(matches),
        importance=20,
        payload={"query": query, "matches": [item.item_id for item in matches]},
    )
    return MarketActionResult(True, "matched", event.event_id, tuple(item.item_id for item in matches))


def recommend_market_items_for_actor(session: Session, *, world: World, actor: Agent, count: int = 10) -> MarketActionResult:
    location_id = actor.location.location_id if actor.location else None
    items = recommend_market_items(seed=world.seed, world_time=world.current_world_time_minutes, agent_id=actor.agent_id, count=count, catalog=effective_market_catalog(world, location_id))
    event = create_event(
        session,
        world=world,
        event_type="market_recommendation",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 查看可购买商品，列表里有 {_format_catalog_names(items)}。",
        agent_visible_text=_format_catalog_for_agent(items),
        importance=20,
        payload={"matches": [item.item_id for item in items]},
    )
    return MarketActionResult(True, "recommended", event.event_id, tuple(item.item_id for item in items))


def build_market_item_description(catalog_item: MarketCatalogItem, *, purchased_at_world_time: int) -> str:
    meta = market_item_metadata(catalog_item, purchased_at_world_time=purchased_at_world_time)
    return f"{catalog_item.description}\n\n{MARKET_META_MARKER}{json.dumps(meta, ensure_ascii=False, sort_keys=True)}"


def market_item_metadata(catalog_item: MarketCatalogItem, *, purchased_at_world_time: int) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "catalog_item_id": catalog_item.item_id,
        "kind": catalog_item.kind,
        "name": catalog_item.name,
        "aliases": list(catalog_item.aliases),
        "tags": list(catalog_item.tags),
        "gift_tags": list(catalog_item.gift_tags),
        "price": catalog_item.price,
        "purchased_at_world_time": int(purchased_at_world_time),
    }
    if catalog_item.kind == "food":
        meta.update(
            {
                "satiety_delta": catalog_item.satiety_delta,
                "mood_delta": catalog_item.mood_delta,
                "spoil_after_hours": catalog_item.spoil_after_hours,
            }
        )
    return meta


def parse_market_item_metadata(description: str | None) -> dict[str, Any] | None:
    if not description or MARKET_META_MARKER not in description:
        return None
    raw = description.rsplit(MARKET_META_MARKER, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def is_market_food_spoiled(item: Item, *, current_world_time: int) -> bool:
    meta = parse_market_item_metadata(item.description)
    if not meta or meta.get("kind") != "food":
        return False
    try:
        purchased_at = int(meta.get("purchased_at_world_time"))
        spoil_after_hours = int(meta.get("spoil_after_hours"))
    except (TypeError, ValueError):
        return False
    return int(current_world_time) - purchased_at >= spoil_after_hours * 60


def buy_market_item(
    session: Session,
    *,
    world: World,
    actor: Agent,
    catalog_item_id: str,
    quantity: int = 1,
    catalog: list[MarketCatalogItem] | None = None,
) -> MarketActionResult:
    if quantity < 1:
        raise ValueError("quantity must be positive")
    catalog_item = get_market_catalog_item(catalog_item_id, catalog)
    cost = catalog_item.price * quantity
    location_id = actor.location.location_id if actor.location else None
    if wallet_money(actor) < cost:
        event = create_event(
            session,
            world=world,
            event_type="market_purchase_failed",
            actor_agent_id=actor.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 想买{catalog_item.name}，但钱不够。",
            agent_visible_text=f"购买失败：{catalog_item.name} 需要 {cost} 金钱，你现在只有 {wallet_money(actor)}。",
            importance=10,
            color_class="warning",
            payload={"catalog_item_id": catalog_item.item_id, "cost": cost, "money": wallet_money(actor)},
            no_state_changed=True,
        )
        return MarketActionResult(False, "money_not_enough", event.event_id)

    add_money(actor, -cost)
    item_ids: list[str] = []
    for _ in range(quantity):
        item = Item(
            item_id=_new_item_id(),
            world_id=world.world_id,
            name=catalog_item.name,
            description=build_market_item_description(catalog_item, purchased_at_world_time=world.current_world_time_minutes),
            item_type=MARKET_ITEM_TYPE_FOOD if catalog_item.kind == "food" else MARKET_ITEM_TYPE_ITEM,
        )
        session.add(item)
        session.flush()
        session.add(Inventory(agent_id=actor.agent_id, item_id=item.item_id, quantity=1))
        item_ids.append(item.item_id)
    event = create_event(
        session,
        world=world,
        event_type="market_purchase",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 花 {cost} 买下了{catalog_item.name}。",
        importance=25,
        payload={"catalog_item_id": catalog_item.item_id, "item_ids": item_ids, "quantity": quantity, "cost": cost, "money": wallet_money(actor)},
    )
    for item_id in item_ids:
        item = session.get(Item, item_id)
        if item:
            item.created_event_id = event.event_id
    return MarketActionResult(True, "bought", event.event_id, tuple(item_ids))


def consume_market_food(session: Session, *, world: World, actor: Agent, item_query: str) -> MarketActionResult:
    location_id = actor.location.location_id if actor.location else None
    found = _find_inventory_item(session, actor.agent_id, item_query)
    if not found:
        return _market_failure(session, world, actor, location_id, f"没有找到可食用或可饮用的 {item_query}。", "supply_not_found")
    inv, item = found
    meta = parse_market_item_metadata(item.description)
    consumption = _consumption_profile(item, meta)
    if not consumption:
        return _market_failure(session, world, actor, location_id, f"{item.name} 不是可食用或可饮用的补给。", "not_consumable")
    if consumption["kind"] == "food" and is_market_food_spoiled(item, current_world_time=world.current_world_time_minutes):
        return _market_failure(session, world, actor, location_id, f"{item.name} 已经腐败，不能再正常食用。", "food_spoiled")

    _remove_inventory_quantity(session, inv, item, 1, delete_item=True)
    state_delta = {
        actor.agent_id: apply_delta(
            actor.dynamic_state,
            satiety=float(consumption.get("satiety_delta") or 0),
            hydration=float(consumption.get("hydration_delta") or 0),
            mood=float(consumption.get("mood_delta") or 0),
        )
    }
    drinking = consumption["kind"] == "drink"
    event = create_event(
        session,
        world=world,
        event_type="market_drink_consumed" if drinking else "market_food_consumed",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} {'喝掉了' if drinking else '吃掉了'}{item.name}。",
        importance=25,
        state_delta=state_delta,
        payload={"item_id": item.item_id, "catalog_item_id": (meta or {}).get("catalog_item_id"), "state_delta": state_delta, "consumption_kind": consumption["kind"]},
    )
    return MarketActionResult(True, "consumed", event.event_id, (item.item_id,))


def _consumption_profile(item: Item, meta: dict[str, Any] | None) -> dict[str, Any] | None:
    terms = _consumption_terms(item, meta)
    if meta:
        if meta.get("kind") != "food":
            return None
        if _looks_drink(terms) and not _looks_food(terms):
            return {
                "kind": "drink",
                "satiety_delta": float(meta.get("satiety_delta") or 0),
                "hydration_delta": 30,
                "mood_delta": float(meta.get("mood_delta") or 0),
            }
        return {
            "kind": "food",
            "satiety_delta": float(meta.get("satiety_delta") or 0),
            "hydration_delta": 0,
            "mood_delta": float(meta.get("mood_delta") or 0),
        }
    if str(item.item_type or "").lower() in {"water", "drink", "beverage"}:
        return {"kind": "drink", "satiety_delta": 0, "hydration_delta": 35, "mood_delta": 1}
    if str(item.item_type or "").lower() in {"food", "portable_food"} or _looks_food(terms):
        return {"kind": "food", "satiety_delta": 30, "hydration_delta": 0, "mood_delta": 1}
    return None


def _consumption_terms(item: Item, meta: dict[str, Any] | None) -> tuple[str, ...]:
    if meta:
        raw = [item.name, meta.get("name")]
        for key in ("aliases", "tags", "gift_tags"):
            value = meta.get(key)
            if isinstance(value, list):
                raw.extend(str(term) for term in value)
    else:
        raw = [item.name, item.item_type, item.description]
    return tuple(_normalize(term) for term in raw if _normalize(term))


def _looks_drink(terms: tuple[str, ...]) -> bool:
    drink_tokens = ("饮品", "饮料", "水", "茶", "咖啡", "拿铁", "牛奶", "汽水", "果汁", "可乐", "苏打", "soda", "water", "tea", "coffee", "latte", "milk", "juice")
    return any(any(token in term for token in drink_tokens) for term in terms)


def _looks_food(terms: tuple[str, ...]) -> bool:
    food_tokens = ("食物", "食品", "便携食物", "饭", "餐", "面包", "饼", "糕", "麻薯", "糖", "巧克力", "便当", "food", "meal", "bread", "cookie", "cake")
    return any(any(token in term for token in food_tokens) for term in terms)


def _inventory_match_score(normalized_query: str, item: Item) -> int:
    meta = parse_market_item_metadata(item.description)
    best = 0
    for term in _consumption_terms(item, meta):
        if normalized_query == term:
            best = max(best, 100)
        elif normalized_query in term:
            best = max(best, 80)
        elif term in normalized_query:
            best = max(best, 60)
    return best


def place_inventory_item(
    session: Session,
    *,
    world: World,
    actor: Agent,
    item_query: str,
    location_id: str | None = None,
) -> MarketActionResult:
    target_location_id = location_id or (actor.location.location_id if actor.location else None)
    if not target_location_id:
        return _market_failure(session, world, actor, None, "没有可放置物品的位置。", "location_missing")
    item = _take_one_inventory_item(session, world, actor.agent_id, item_query)
    if not item:
        return _market_failure(session, world, actor, target_location_id, f"没有找到可放置的 {item_query}。", "item_not_found")
    item.location_id = target_location_id
    witness_ids = _agent_ids_at_location(session, target_location_id)
    event = create_event(
        session,
        world=world,
        event_type="market_item_placed",
        actor_agent_id=actor.agent_id,
        location_id=target_location_id,
        viewer_text=f"{actor.chosen_name} 把{item.name}放在了这里。",
        importance=20,
        payload={"placed_item_id": item.item_id, "placed_by_agent_id": actor.agent_id, "witness_agent_ids": witness_ids},
    )
    return MarketActionResult(True, "placed", event.event_id, (item.item_id,))


def pick_up_placed_item(session: Session, *, world: World, actor: Agent, item_query: str) -> MarketActionResult:
    location_id = actor.location.location_id if actor.location else None
    if not location_id:
        return _market_failure(session, world, actor, None, "没有可捡起物品的位置。", "location_missing")
    item = session.execute(
        select(Item).where(Item.world_id == world.world_id, Item.location_id == location_id, Item.name.like(f"%{item_query}%")).limit(1)
    ).scalar_one_or_none()
    if not item:
        return _market_failure(session, world, actor, location_id, f"没有找到可捡起的 {item_query}。", "placed_item_not_found")
    item.location_id = None
    _add_inventory_item(session, actor.agent_id, item)
    event = create_event(
        session,
        world=world,
        event_type="market_item_picked_up",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 捡起了{item.name}。",
        importance=20,
        payload={"item_id": item.item_id},
    )
    return MarketActionResult(True, "picked_up", event.event_id, (item.item_id,))


def transfer_inventory_item(
    session: Session,
    *,
    world: World,
    actor: Agent,
    target: Agent,
    item_query: str,
    as_gift: bool = False,
    require_same_location: bool = True,
) -> MarketActionResult:
    location_id = actor.location.location_id if actor.location else None
    if require_same_location and actor.location and target.location and actor.location.location_id != target.location.location_id:
        return _market_failure(session, world, actor, location_id, f"{target.chosen_name} 不在附近，不能移交物品。", "target_not_nearby")
    item = _take_one_inventory_item(session, world, actor.agent_id, item_query)
    if not item:
        return _market_failure(session, world, actor, location_id, f"没有找到可移交的 {item_query}。", "item_not_found")
    item.location_id = None
    _add_inventory_item(session, target.agent_id, item)

    verdict = None
    affection_delta = 0
    event_type = "market_item_transferred"
    if as_gift:
        verdict, affection_delta = _gift_verdict(item, target)
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, affection=affection_delta)
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1)
        event_type = "market_gift"

    event = create_event(
        session,
        world=world,
        event_type=event_type,
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 把{item.name}交给了{target.chosen_name}。",
        importance=45 if as_gift else 25,
        payload={"item_id": item.item_id, "as_gift": as_gift, "gift_verdict": verdict, "affection_delta": affection_delta},
    )
    return MarketActionResult(True, "gifted" if as_gift else "transferred", event.event_id, (item.item_id,), verdict, affection_delta)


def visible_placed_items(session: Session, *, world: World, observer: Agent, location_id: str | None = None) -> list[dict[str, Any]]:
    target_location_id = location_id or (observer.location.location_id if observer.location else None)
    if not target_location_id:
        return []
    items = list(session.execute(select(Item).where(Item.world_id == world.world_id, Item.location_id == target_location_id).order_by(Item.name)).scalars())
    placement_events = list(
        session.execute(
            select(Event)
            .where(Event.world_id == world.world_id, Event.location_id == target_location_id, Event.event_type == "market_item_placed")
            .order_by(Event.event_id.desc())
        ).scalars()
    )
    placement_by_item = {
        str(event.payload.get("placed_item_id")): event
        for event in placement_events
        if isinstance(event.payload, dict) and event.payload.get("placed_item_id")
    }
    views: list[dict[str, Any]] = []
    for item in items:
        meta = parse_market_item_metadata(item.description) or {}
        event = placement_by_item.get(item.item_id)
        placed_by_agent_id = None
        placed_by_name = None
        if event and observer.agent_id in (event.payload.get("witness_agent_ids") or []):
            placed_by_agent_id = event.payload.get("placed_by_agent_id")
            placed_by = session.get(Agent, placed_by_agent_id) if placed_by_agent_id else None
            placed_by_name = placed_by.chosen_name if placed_by else None
        views.append(
            {
                "item_id": item.item_id,
                "name": item.name,
                "description": _strip_market_meta(item.description),
                "kind": meta.get("kind") or item.item_type,
                "placed_by_agent_id": placed_by_agent_id,
                "placed_by_name": placed_by_name,
            }
        )
    return views


def _parse_market_item(raw: dict[str, Any], index: int) -> MarketCatalogItem:
    item_id = _required_str(raw, "item_id", index)
    kind = _required_str(raw, "kind", index)
    if kind not in {"food", "item"}:
        raise ValueError(f"market item {item_id} kind must be food or item")
    food_keys = {"satiety_delta", "mood_delta", "spoil_after_hours"}
    if kind == "item" and any(key in raw for key in food_keys):
        raise ValueError(f"market item {item_id} is not food and must not define food fields")
    satiety_delta = None
    mood_delta = None
    spoil_after_hours = None
    if kind == "food":
        missing = [key for key in food_keys if key not in raw]
        if missing:
            raise ValueError(f"market food {item_id} missing fields: {', '.join(sorted(missing))}")
        satiety_delta = _number(raw["satiety_delta"], f"{item_id}.satiety_delta")
        mood_delta = _number(raw["mood_delta"], f"{item_id}.mood_delta")
        spoil_after_hours = _positive_int(raw["spoil_after_hours"], f"{item_id}.spoil_after_hours")
    return MarketCatalogItem(
        item_id=item_id,
        kind=kind,
        name=_required_str(raw, "name", index),
        aliases=_string_tuple(raw.get("aliases") or [], f"{item_id}.aliases"),
        description=_required_str(raw, "description", index),
        tags=_string_tuple(raw.get("tags") or [], f"{item_id}.tags"),
        gift_tags=_string_tuple(raw.get("gift_tags") or [], f"{item_id}.gift_tags"),
        price=_non_negative_int(raw.get("price"), f"{item_id}.price"),
        satiety_delta=satiety_delta,
        mood_delta=mood_delta,
        spoil_after_hours=spoil_after_hours,
    )


def _market_failure(session: Session, world: World, actor: Agent, location_id: str | None, text: str, message: str) -> MarketActionResult:
    event = create_event(
        session,
        world=world,
        event_type="market_action_failed",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=_market_failure_viewer_text(actor, message),
        agent_visible_text=text,
        importance=10,
        color_class="warning",
        payload={"failure_reason_code": message, "llm_feedback": text},
        no_state_changed=True,
    )
    return MarketActionResult(False, message, event.event_id)


def _market_failure_viewer_text(actor: Agent, message: str) -> str:
    name = actor.chosen_name or "某位居民"
    if message in {"supply_not_found", "food_not_found", "item_not_found", "placed_item_not_found"}:
        return f"{name}翻了翻背包，没有找到想用的那件东西。"
    if message == "not_consumable":
        return f"{name}拿起一件东西看了看，最后还是没有入口。"
    if message == "food_spoiled":
        return f"{name}闻了闻手里的食物，发现已经不适合吃了。"
    if message == "money_not_enough":
        return f"{name}想买点东西，但身上的钱不够。"
    if message == "target_not_nearby":
        return f"{name}想把东西递给别人，但对方不在身边。"
    if message == "location_missing":
        return f"{name}拿着东西犹豫了一下，没有找到合适的地方处理。"
    return f"{name}试着处理背包里的东西，但这次没有办成。"


def _format_catalog_names(items: list[MarketCatalogItem]) -> str:
    names = [f"{item.name}({item.price})" for item in items[:10]]
    return "、".join(names) if names else "一些商品"


def _format_catalog_for_agent(items: list[MarketCatalogItem]) -> str:
    lines = ["可购买这些商品；购买时写商品名或关键词："]
    for item in items[:10]:
        kind = "食物" if item.kind == "food" else "物品"
        spoil = f"，约 {item.spoil_after_hours} 小时后腐败" if item.kind == "food" and item.spoil_after_hours else ""
        lines.append(f"- {item.name} [{kind}] 价格 {item.price}{spoil}：{item.description}")
    return "\n".join(lines)


def _find_inventory_item(session: Session, agent_id: str, item_query: str) -> tuple[Inventory, Item] | None:
    normalized_query = _normalize(item_query)
    if not normalized_query:
        return None
    rows = list(
        session.execute(
            select(Inventory, Item)
            .join(Item, Item.item_id == Inventory.item_id)
            .where(Inventory.agent_id == agent_id, Inventory.quantity > 0)
            .order_by(Item.name.asc(), Item.item_id.asc())
        ).all()
    )
    best: tuple[int, Inventory, Item] | None = None
    for inv, item in rows:
        score = _inventory_match_score(normalized_query, item)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, inv, item)
    return (best[1], best[2]) if best else None


def _take_one_inventory_item(session: Session, world: World, agent_id: str, item_query: str) -> Item | None:
    found = _find_inventory_item(session, agent_id, item_query)
    if not found:
        return None
    inv, item = found
    if inv.quantity > 1:
        inv.quantity -= 1
        clone = Item(
            item_id=_new_item_id(),
            world_id=world.world_id,
            name=item.name,
            description=item.description,
            item_type=item.item_type,
            created_event_id=item.created_event_id,
        )
        session.add(clone)
        session.flush()
        return clone
    session.delete(inv)
    return item


def _remove_inventory_quantity(session: Session, inv: Inventory, item: Item, quantity: int, *, delete_item: bool = False) -> None:
    inv.quantity -= quantity
    if inv.quantity <= 0:
        session.delete(inv)
        if delete_item and item.location_id is None:
            session.delete(item)


def _add_inventory_item(session: Session, agent_id: str, item: Item) -> None:
    existing = session.execute(select(Inventory).where(Inventory.agent_id == agent_id, Inventory.item_id == item.item_id)).scalar_one_or_none()
    if existing:
        existing.quantity += 1
        return
    session.add(Inventory(agent_id=agent_id, item_id=item.item_id, quantity=1))


def _agent_ids_at_location(session: Session, location_id: str) -> list[str]:
    return list(
        session.execute(
            select(AgentLocation.agent_id).where(AgentLocation.location_id == location_id).order_by(AgentLocation.agent_id)
        ).scalars()
    )


def _gift_verdict(item: Item, target: Agent) -> tuple[str, int]:
    meta = parse_market_item_metadata(item.description) or {}
    item_terms = _preference_terms(item, meta)
    preferences = (target.desires_json or {}).get("gift_preferences") or {}
    likes = [_normalize(value) for value in preferences.get("likes") or [] if _normalize(value)]
    dislikes = [_normalize(value) for value in preferences.get("dislikes") or [] if _normalize(value)]
    if _any_term_matches(dislikes, item_terms):
        return "disliked", -5
    if _any_term_matches(likes, item_terms):
        return "liked", 5
    return "neutral", 0


def _preference_terms(item: Item, meta: dict[str, Any]) -> tuple[str, ...]:
    raw_terms = [item.name]
    for key in ("aliases", "tags", "gift_tags"):
        value = meta.get(key)
        if isinstance(value, list):
            raw_terms.extend(str(term) for term in value)
    return tuple(_normalize(term) for term in raw_terms if _normalize(term))


def _any_term_matches(preferences: list[str], item_terms: tuple[str, ...]) -> bool:
    for preference in preferences:
        if any(preference in term or term in preference for term in item_terms):
            return True
    return False


def _match_score(normalized_query: str, item: MarketCatalogItem) -> int:
    best = 0
    for term in item.searchable_terms:
        normalized_term = _normalize(term)
        if not normalized_term:
            continue
        if normalized_query == normalized_term:
            best = max(best, 100)
        elif normalized_query in normalized_term:
            best = max(best, 80)
        elif normalized_term in normalized_query:
            best = max(best, 60)
    return best


def _strip_market_meta(description: str | None) -> str:
    if not description:
        return ""
    return description.split(MARKET_META_MARKER, 1)[0].strip()


def _normalize(value: Any) -> str:
    return "".join(str(value).casefold().split())


def _required_str(raw: dict[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"market item #{index} missing string field {key}")
    return value.strip()


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    result: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{label} entries must be non-empty strings")
        result.append(entry.strip())
    return tuple(result)


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _new_item_id() -> str:
    return f"item_{uuid.uuid4().hex[:12]}"
