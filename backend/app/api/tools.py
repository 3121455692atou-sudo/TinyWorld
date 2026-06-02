from __future__ import annotations

from fastapi import APIRouter

from app.tools.tool_specs import TOOL_SPECS, V5_CATALOG_BY_ID, V6_CATALOG_BY_ID


router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
def list_tools() -> dict:
    tools = [
        {
            "tool_name": spec.tool_name,
            "display_name": spec.display_name,
            "target_policy": spec.target_policy,
            "time_cost_minutes": spec.time_cost_minutes,
            "event_importance": spec.event_importance,
            "catalog_category": spec.catalog_category,
            "source_version": spec.source_version,
        }
        for spec in sorted(TOOL_SPECS.values(), key=lambda item: item.tool_name)
    ]
    return {
        "count": len(tools),
        "v5_catalog_count": len(V5_CATALOG_BY_ID),
        "v6_catalog_count": len(V6_CATALOG_BY_ID),
        "runtime_local_count": len(tools) - len(V5_CATALOG_BY_ID) - len(V6_CATALOG_BY_ID),
        "tools": tools,
    }
