from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import Item, Location
from app.world.locations import INITIAL_LOCATIONS


INITIAL_ITEMS = [
    ("cafeteria", "水", "公共食堂里的清水。", "water", 12),
    ("cafeteria", "简餐", "可以快速恢复饱腹的热食。", "food", 10),
    ("garden", "野果", "花园里能采到的酸甜野果。", "food", 8),
    ("garden", "草药", "气味清苦的草药。", "medical", 4),
    ("workshop", "木料", "适合制作简单物品的木料。", "craft", 6),
    ("workshop", "布料", "柔软耐用的布料。", "craft", 5),
    ("workshop", "工具箱", "共用工具箱。", "tool", 1),
    ("library", "空白笔记本", "适合记录日记或长期记忆的笔记本。", "book", 6),
    ("library", "旧书", "内容庞杂的旧书。", "book", 8),
    ("campfire", "木柴", "给篝火使用的干燥木柴。", "fuel", 8),
]


def world_location_id(world_id: str, raw_location_id: str) -> str:
    raw = str(raw_location_id)
    if raw.startswith(f"{world_id}:"):
        return raw
    if ":" in raw and raw.split(":", 1)[0].startswith("world_"):
        return raw
    return f"{world_id}:{raw}"


def local_location_key(raw_location_id: str) -> str:
    return str(raw_location_id).split(":", 1)[-1]


def seed_world_content(session: Session, world_id: str, worldview: dict[str, Any] | None = None) -> None:
    seed_locations(session, world_id, worldview=worldview)
    seed_items(session, world_id, worldview=worldview)


def seed_locations(session: Session, world_id: str, worldview: dict[str, Any] | None = None) -> None:
    custom_locations = (worldview or {}).get("locations") if isinstance(worldview, dict) else None
    if custom_locations:
        for raw in custom_locations:
            if not isinstance(raw, dict):
                continue
            local_id = str(raw.get("location_id") or "")
            if not local_id:
                continue
            neighbors = [world_location_id(world_id, item) for item in raw.get("neighbors") or []]
            session.merge(
                Location(
                    location_id=world_location_id(world_id, local_id),
                    world_id=world_id,
                    public_name=str(raw.get("name") or raw.get("public_name") or local_id),
                    description=str(raw.get("description") or ""),
                    neighbors_json=neighbors,
                    available_tools_json=[str(x) for x in raw.get("available_tools") or []],
                    visibility_radius=int(raw.get("visibility_radius") or 1),
                    capacity=int(raw.get("capacity") or 12),
                    tags_json=[str(x) for x in raw.get("tags") or []],
                )
            )
        return
    for spec in INITIAL_LOCATIONS:
        session.merge(
            Location(
                location_id=f"{world_id}:{spec.location_id}",
                world_id=world_id,
                public_name=spec.public_name,
                description=spec.description,
                neighbors_json=[f"{world_id}:{neighbor}" for neighbor in spec.neighbors],
                available_tools_json=spec.available_tools,
                visibility_radius=spec.visibility_radius,
                capacity=spec.capacity,
                tags_json=spec.tags,
            )
        )


def seed_items(session: Session, world_id: str, worldview: dict[str, Any] | None = None) -> None:
    custom_items = (worldview or {}).get("initial_items") if isinstance(worldview, dict) else None
    if custom_items:
        for raw in custom_items:
            if not isinstance(raw, dict):
                continue
            quantity = int(raw.get("quantity") or 1)
            for _ in range(max(1, quantity)):
                session.add(
                    Item(
                        item_id=f"item_{uuid.uuid4().hex[:12]}",
                        world_id=world_id,
                        name=str(raw.get("name") or raw.get("item_name") or "未命名物品"),
                        description=str(raw.get("description") or ""),
                        item_type=str(raw.get("item_type") or raw.get("type") or "worldpack"),
                        location_id=world_location_id(world_id, raw.get("location_id") or raw.get("location") or "central_square"),
                    )
                )
        return
    if isinstance(worldview, dict) and worldview.get("locations"):
        # Special worldviews own their item economy. Falling back to the modern-town
        # item table would spawn supplies in nonexistent places such as central_square.
        return
    for location_key, name, description, item_type, quantity in INITIAL_ITEMS:
        for _ in range(quantity):
            session.add(
                Item(
                    item_id=f"item_{uuid.uuid4().hex[:12]}",
                    world_id=world_id,
                    name=name,
                    description=description,
                    item_type=item_type,
                    location_id=f"{world_id}:{location_key}",
                )
            )


def private_home_location_id(world_id: str, index: int, worldview: dict[str, Any] | None = None) -> str:
    template = _private_template(worldview)
    prefix = str(template.get("id_prefix") or "private_cabin")
    number = index + 1
    return world_location_id(world_id, f"{prefix}_{number}")


def private_home_location(world_id: str, index: int, worldview: dict[str, Any] | None = None) -> Location:
    template = _private_template(worldview)
    number = index + 1
    name_template = str(template.get("name_template") or "{number}号小屋")
    public_name = _format_template(name_template, number=number)
    raw_neighbors = template.get("neighbors") or _default_private_neighbors(worldview)
    return Location(
        location_id=private_home_location_id(world_id, index, worldview),
        world_id=world_id,
        public_name=public_name,
        description=str(template.get("description") or "一间只属于自己的住所，安静、安全，适合睡觉、整理记忆和准备出门。"),
        neighbors_json=[world_location_id(world_id, item) for item in raw_neighbors],
        available_tools_json=[
            str(x)
            for x in template.get("available_tools")
            or [
                "sleep",
                "rest",
                "wash",
                "drink_water",
                "write_diary",
                "add_memory",
                "work_shift_cleaner",
                "check_child_status_visible_agent",
                "soothe_child_visible_agent",
                "feed_child_visible_agent",
                "carry_child_visible_agent",
                "put_child_to_sleep_visible_agent",
                "care_for_child_visible_agent",
            ]
        ],
        visibility_radius=int(template.get("visibility_radius") or 0),
        capacity=int(template.get("capacity") or 1),
        tags_json=[str(x) for x in template.get("tags") or ["home", "quiet", "water", "private"]],
    )


def _private_template(worldview: dict[str, Any] | None) -> dict[str, Any]:
    template = (worldview or {}).get("private_home_template") if isinstance(worldview, dict) else None
    return deepcopy(template) if isinstance(template, dict) else {}


def _default_private_neighbors(worldview: dict[str, Any] | None) -> list[str]:
    """Pick existing public anchors when a custom world omits a home template."""
    locations = (worldview or {}).get("locations") if isinstance(worldview, dict) else None
    local_ids = [str(item.get("location_id")) for item in locations or [] if isinstance(item, dict) and item.get("location_id")]
    if not local_ids:
        return ["central_square", "cabin"]
    for preferred in ("central_square", "heart_plaza", "feeling_lounge", "village_square", "dormitory", "family_nest"):
        if preferred in local_ids:
            neighbors = [preferred]
            for extra in ("cabin", "family_nest", "quiet_cloud_room", "dormitory"):
                if extra in local_ids and extra not in neighbors:
                    neighbors.append(extra)
                    break
            return neighbors
    return [local_ids[0]]


def _format_template(template: str, **values: Any) -> str:
    try:
        return template.format(**values)
    except Exception:
        return template
