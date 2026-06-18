from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.clock import format_world_time
from app.core.database import get_db
from app.core.models import Agent, World
from app.knowledge.perception import build_turn_context_with_options
from app.llm.action_protocol import ActionOption, format_action_options_for_prompt
from app.tools.tool_specs import TOOL_SPECS, V5_CATALOG_BY_ID, V6_CATALOG_BY_ID
from app.tools.registry import available_tools
from app.tools.validators import validate_tool


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


@router.get("/agent/{world_id}/{agent_id}")
def list_agent_tools(world_id: str, agent_id: str, db: Session = Depends(get_db)) -> dict:
    """获取特定 agent 在当前世界状态下可用的工具列表。

    这可用于调试和审计，了解 agent 能看到哪些工具选项。
    注意：实际可用工具可能因 agent 状态、位置、关系等因素变化。
    """
    world = db.get(World, world_id)
    agent = db.get(Agent, agent_id)
    if not world or not agent:
        return {"error": "world or agent not found", "tools": [], "count": 0}

    if agent.world_id != world_id:
        return {"error": "agent does not belong to this world", "tools": [], "count": 0}

    # 获取 agent 可用的工具
    location = agent.location.location if agent.location else None
    specs = available_tools(agent, location, reaction=False, session=db)

    tools = [
        {
            "tool_name": spec.tool_name,
            "display_name": spec.display_name,
            "target_policy": spec.target_policy,
            "time_cost_minutes": spec.time_cost_minutes,
            "catalog_category": spec.catalog_category,
            "hard_effect_id": spec.hard_effect_id,
        }
        for spec in specs
    ]

    # 按类别分组统计
    categories: dict[str, int] = {}
    for tool in tools:
        cat = tool.get("catalog_category") or "core"
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "agent_id": agent_id,
        "agent_name": agent.chosen_name,
        "world_id": world_id,
        "count": len(tools),
        "categories": categories,
        "tools": tools,
    }


@router.get("/agent/{world_id}/{agent_id}/action-options")
def list_agent_action_options(
    world_id: str,
    agent_id: str,
    reaction: bool = Query(False, description="是否按反应回合构建菜单"),
    include_prompt: bool = Query(False, description="是否返回完整 prompt，默认只返回行动菜单"),
    validate_options: bool = Query(True, description="是否二次校验每个行动选项"),
    db: Session = Depends(get_db),
) -> dict:
    """返回真实发送给 agent 的 AOHP 行动编号菜单。

    raw_tools 是 registry 当前暴露的工具规格；action_options 是经过目标展开、
    上下文门禁、去重、排序和数量上限后，实际进入 prompt 的编号菜单。
    """
    world = db.get(World, world_id)
    agent = db.get(Agent, agent_id)
    if not world or not agent:
        return {"error": "world or agent not found", "raw_tools": [], "action_options": [], "raw_tool_count": 0, "option_count": 0}
    if agent.world_id != world_id:
        return {"error": "agent does not belong to this world", "raw_tools": [], "action_options": [], "raw_tool_count": 0, "option_count": 0}

    location = agent.location.location if agent.location else None
    raw_specs = available_tools(agent, location, reaction=reaction, session=db)
    context = build_turn_context_with_options(db, world, agent, reaction=reaction)
    language = str((world.settings_json or {}).get("language") or (world.settings_json or {}).get("ui_language") or "zh")
    action_menu = format_action_options_for_prompt(context.action_options, language=language)

    raw_tools = [_serialize_tool_spec(spec) for spec in raw_specs]
    action_options = [_serialize_action_option(option) for option in context.action_options]
    option_tool_names = {option.tool_name for option in context.action_options}
    raw_tool_names = {spec.tool_name for spec in raw_specs}
    validation_failures = (
        _validate_action_options(db, world, agent, context.action_options, reaction=reaction)
        if validate_options
        else []
    )

    payload: dict[str, Any] = {
        "agent_id": agent.agent_id,
        "agent_name": agent.chosen_name,
        "world_id": world.world_id,
        "world_time": world.current_world_time_minutes,
        "world_time_label": format_world_time(world.current_world_time_minutes),
        "reaction": reaction,
        "location_id": agent.location.location_id if agent.location else None,
        "location_name": location.public_name if location else None,
        "raw_tool_count": len(raw_tools),
        "option_count": len(action_options),
        "raw_tools": raw_tools,
        "action_options": action_options,
        "action_menu": action_menu,
        "ref_map": context.ref_map,
        "option_tool_names": sorted(option_tool_names),
        "raw_tools_not_in_action_menu": sorted(raw_tool_names - option_tool_names),
        "validation_failure_count": len(validation_failures),
        "validation_failures": validation_failures,
    }
    if include_prompt:
        payload["prompt"] = context.prompt
    return payload


def _serialize_tool_spec(spec) -> dict[str, Any]:
    return {
        "tool_name": spec.tool_name,
        "display_name": spec.display_name,
        "target_policy": spec.target_policy,
        "time_cost_minutes": spec.time_cost_minutes,
        "event_importance": spec.event_importance,
        "catalog_category": spec.catalog_category,
        "hard_effect_id": spec.hard_effect_id,
        "required_location_tags": list(spec.required_location_tags or []),
        "visibility": spec.visibility,
        "source_version": spec.source_version,
    }


def _serialize_action_option(option: ActionOption) -> dict[str, Any]:
    return {
        "option_id": option.option_id,
        "label": option.label,
        "tool_name": option.tool_name,
        "params": option.params,
        "value_slot": option.value_slot,
        "text_slot": option.text_slot,
        "text_required": option.text_required,
        "min_value": option.min_value,
        "max_value": option.max_value,
        "default_value": option.default_value,
        "value_hint": option.value_hint,
        "tone": option.tone,
        "risk_note": option.risk_note,
        "tags": list(option.tags or ()),
        "target_choices": list(option.target_choices or ()),
    }


def _validate_action_options(
    db: Session,
    world: World,
    agent: Agent,
    options: list[ActionOption],
    *,
    reaction: bool,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for option in options:
        if option.target_choices:
            for choice in option.target_choices:
                choice_params = choice.get("params") if isinstance(choice, dict) else None
                params = _params_for_option_validation(option, choice_params if isinstance(choice_params, dict) else None)
                result = validate_tool(
                    db,
                    actor=agent,
                    tool_name=option.tool_name,
                    params=params,
                    world_time=world.current_world_time_minutes,
                    reaction=reaction,
                    persist_visibility=False,
                )
                if not result.ok:
                    failures.append(
                        {
                            "option_id": option.option_id,
                            "tool_name": option.tool_name,
                            "target_choice": choice,
                            "reason_code": result.reason_code,
                            "message": result.message,
                        }
                    )
            continue

        params = _params_for_option_validation(option)
        result = validate_tool(
            db,
            actor=agent,
            tool_name=option.tool_name,
            params=params,
            world_time=world.current_world_time_minutes,
            reaction=reaction,
            persist_visibility=False,
        )
        if not result.ok:
            failures.append(
                {
                    "option_id": option.option_id,
                    "tool_name": option.tool_name,
                    "reason_code": result.reason_code,
                    "message": result.message,
                }
            )
    return failures


def _params_for_option_validation(option: ActionOption, override_params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(option.params or {})
    if override_params:
        params.update(override_params)
    if option.value_slot:
        params[option.value_slot] = option.default_value if option.default_value is not None else 1
    if option.text_slot:
        text = "我会把这件事认真说清楚。" if option.text_slot == "speech" else "记录当前发生的具体事情。"
        params[option.text_slot] = text
        if option.text_slot == "speech":
            params.setdefault("tone", "neutral")
    if option.tool_name == "write_diary":
        params.setdefault("title", "今天的记录")
        params.setdefault("content", "今天发生的事值得记下来。")
    return params
