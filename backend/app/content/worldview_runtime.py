from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.world.locations import INITIAL_LOCATIONS
from app.world.seed_world import world_location_id


LOCATION_PALETTE = [
    "#2f80ed",
    "#27ae60",
    "#f2994a",
    "#9b51e0",
    "#00a6a6",
    "#b8860b",
    "#eb5757",
    "#4f6f52",
    "#d94888",
    "#c66a31",
    "#6c7a89",
    "#607d8b",
    "#8e6f3e",
    "#00897b",
    "#c2185b",
    "#7cb342",
    "#5e35b1",
    "#039be5",
]

DEFAULT_RULE_PARAMETERS = {
    "relationship": {
        "familiarity_multiplier": 1.0,
        "trust_multiplier": 1.0,
        "affection_positive_multiplier": 1.0,
        "affection_negative_multiplier": 1.0,
        "fear_multiplier": 1.0,
        "conflict_multiplier": 1.0,
    },
    "dynamic_state": {
        "visible_fields": ["health", "energy", "satiety", "hydration", "hygiene", "social", "fun", "stress", "mood"],
    },
}


def worldview_locations(worldview: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw_locations = (worldview or {}).get("locations") if isinstance(worldview, dict) else None
    if isinstance(raw_locations, list) and raw_locations:
        return [deepcopy(item) for item in raw_locations if isinstance(item, dict)]
    return [
        {
            "location_id": spec.location_id,
            "name": spec.public_name,
            "description": spec.description,
            "neighbors": list(spec.neighbors),
            "available_tools": list(spec.available_tools),
            "tags": list(spec.tags),
            "visibility_radius": spec.visibility_radius,
            "capacity": spec.capacity,
        }
        for spec in INITIAL_LOCATIONS
    ]


def location_color_map(world_id: str, worldview: dict[str, Any] | None) -> dict[str, str]:
    colors: dict[str, str] = {}
    for index, raw in enumerate(worldview_locations(worldview)):
        local_id = str(raw.get("location_id") or "").strip()
        if not local_id:
            continue
        color = str(raw.get("color") or raw.get("ui_color") or raw.get("location_color") or LOCATION_PALETTE[index % len(LOCATION_PALETTE)])
        colors[local_id] = color
        colors[world_location_id(world_id, local_id)] = color
    return colors


def location_order(world_id: str, worldview: dict[str, Any] | None) -> list[str]:
    return [world_location_id(world_id, raw["location_id"]) for raw in worldview_locations(worldview) if raw.get("location_id")]


def worldview_rule_parameters(worldview: dict[str, Any] | None) -> dict[str, Any]:
    params = deepcopy(DEFAULT_RULE_PARAMETERS)
    for key in ["rule_parameters", "rules", "runtime_parameters", "mechanics_parameters"]:
        raw = (worldview or {}).get(key) if isinstance(worldview, dict) else None
        if isinstance(raw, dict):
            _deep_merge(params, raw)
    mechanics = (worldview or {}).get("mechanics") if isinstance(worldview, dict) else None
    if isinstance(mechanics, dict):
        _deep_merge(params, mechanics)
    return params


def worldview_ui_schema(
    worldview: dict[str, Any] | None,
    *,
    survival_enabled: bool,
    finance_enabled: bool = False,
    reproduction_enabled: bool = False,
    world_toolset_id: str | None = None,
) -> dict[str, Any]:
    ui = deepcopy((worldview or {}).get("ui") if isinstance(worldview, dict) and isinstance((worldview or {}).get("ui"), dict) else {})
    worldview_id = str((worldview or {}).get("worldview_id") or "") if isinstance(worldview, dict) else ""
    toolset_id = str(world_toolset_id or "")
    modern_worldview_ids = {"fast_modern_worldview", "default_modern_worldview"}
    modern_toolset_ids = {"fast_modern_world_toolset", "default_modern_world_toolset", "default_modern_toolset"}
    is_default_modern = worldview_id in modern_worldview_ids or toolset_id in modern_toolset_ids

    state_display = deepcopy(ui.get("state_display") if isinstance(ui.get("state_display"), dict) else {})
    dynamic_fields = state_display.get("dynamic_fields")
    if not isinstance(dynamic_fields, list):
        dynamic_fields = ["health", "energy", "hygiene", "social", "fun", "stress", "mood"]
        if survival_enabled:
            dynamic_fields[2:2] = ["satiety", "hydration"]
    state_display["dynamic_fields"] = [str(item) for item in dynamic_fields]
    worldpack = deepcopy(state_display.get("worldpack") if isinstance(state_display.get("worldpack"), dict) else {})
    worldpack.setdefault("show_progress", True)
    worldpack.setdefault("show_resources", True)
    worldpack.setdefault("show_flags", True)
    state_display["worldpack"] = worldpack
    ui["state_display"] = state_display

    panels = deepcopy(ui.get("panels") if isinstance(ui.get("panels"), dict) else {})
    panels.setdefault("world_runtime_settings", True)
    panels.setdefault("map", True)
    panels.setdefault("agents", True)
    panels.setdefault("status", True)
    panels.setdefault("metrics", True)
    panels.setdefault("narrator", True)
    panels.setdefault("agent_detail", True)
    panels.setdefault("worldpack_state", True)
    panels.setdefault("survival", bool(survival_enabled))
    panels.setdefault("reproduction", bool(reproduction_enabled))
    panels.setdefault("adult_intimacy", bool(reproduction_enabled))
    panels.setdefault("work", bool(is_default_modern))
    panels.setdefault("law", True)
    panels.setdefault("housing", bool(is_default_modern))
    panels.setdefault("debt", bool(is_default_modern))
    panels.setdefault("hedonic_consumption", bool(is_default_modern))
    panels.setdefault("creator_economy", bool(is_default_modern))
    panels.setdefault("finance", bool(finance_enabled))
    panels.setdefault("economy", bool(is_default_modern or finance_enabled))
    panels.setdefault("agent_economy", bool(is_default_modern or finance_enabled))
    ui["panels"] = panels

    metric_groups = deepcopy(ui.get("metric_groups") if isinstance(ui.get("metric_groups"), dict) else {})
    metric_groups.setdefault("base", True)
    metric_groups.setdefault("survival", bool(survival_enabled))
    metric_groups.setdefault("family", bool(reproduction_enabled))
    metric_groups.setdefault("adult_intimacy", bool(reproduction_enabled))
    metric_groups.setdefault("work", bool(is_default_modern))
    metric_groups.setdefault("law", True)
    metric_groups.setdefault("economy", bool(is_default_modern or finance_enabled))
    metric_groups.setdefault("housing", bool(is_default_modern))
    metric_groups.setdefault("hedonic", bool(is_default_modern))
    metric_groups.setdefault("creator", bool(is_default_modern))
    metric_groups.setdefault("finance", bool(finance_enabled))
    ui["metric_groups"] = metric_groups
    return ui


def infer_worldpack_state_schema(worldview: dict[str, Any] | None, world_toolset: dict[str, Any] | None) -> dict[str, Any]:
    schema = deepcopy((worldview or {}).get("worldpack_state_schema") if isinstance(worldview, dict) and isinstance((worldview or {}).get("worldpack_state_schema"), dict) else {})
    resources: dict[str, str] = {str(k): str(v) for k, v in (schema.get("resources") or {}).items()} if isinstance(schema.get("resources"), dict) else {}
    for tool in (world_toolset or {}).get("tools") or []:
        if not isinstance(tool, dict):
            continue
        effect = tool.get("declarative_effect") or tool.get("effect") or {}
        if not isinstance(effect, dict):
            continue
        for container in [
            effect.get("worldpack_resources_delta"),
            effect.get("resource_delta"),
            effect.get("requires_resources"),
            effect.get("resource_cost"),
        ]:
            if isinstance(container, dict):
                for key in container:
                    resources.setdefault(str(key), str(key))
    schema["resources"] = resources
    schema.setdefault("progress", {"level": "等级", "exp": "经验"})
    schema.setdefault("flags_label", "世界状态")
    return schema


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = deepcopy(value)
