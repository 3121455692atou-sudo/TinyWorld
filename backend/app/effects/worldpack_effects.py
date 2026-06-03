from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import apply_delta
from app.agents.v5_state import add_money, ensure_v5_agent_state, wallet_money
from app.core.models import Agent, World
from app.events.event_store import create_event
from app.tools.tool_specs import ToolSpec
from app.world.visibility import resolve_visible_ref


WORLD_PACK_STATE_KEY = "worldpack_state"


def validate_worldpack_declarative_tool(actor: Agent, spec: ToolSpec, params: dict[str, Any] | None = None) -> tuple[bool, str | None, str | None]:
    """Validate declarative content-pack gates that the generic ToolSpec cannot know.

    This deliberately checks only local actor state. Location/target/lifecycle checks stay in
    validators.py so external world authors cannot bypass core validation and visibility rules.
    """
    effect = _effect_for_spec(spec)
    if not effect:
        return True, None, None
    ensure_v5_agent_state(actor)
    state = _worldpack_state(actor, spec)
    progress = state.setdefault("progress", {"level": 1, "exp": 0})
    level = int(progress.get("level") or 1)
    required_level = int(effect.get("required_level") or effect.get("min_level") or 0)
    if required_level and level < required_level:
        return False, "worldpack_level_too_low", f"这个世界观行动需要等级 {required_level}，你现在只有等级 {level}。"
    flags = set(state.get("flags") or [])
    missing_flags = [str(flag) for flag in effect.get("requires_flags") or [] if str(flag) not in flags]
    if missing_flags:
        return False, "worldpack_missing_flag", "这个世界观行动还缺少前置剧情/状态: " + "、".join(missing_flags)
    resources = _int_map(state.get("resources") or {})
    required_resources = _merged_costs(spec, effect)
    for resource, amount in _int_map(effect.get("requires_resources") or {}).items():
        required_resources[resource] = max(required_resources.get(resource, 0), amount)
    missing = []
    for resource, amount in required_resources.items():
        if resources.get(resource, 0) < amount:
            missing.append(f"{resource} {resources.get(resource, 0)}/{amount}")
    if missing:
        return False, "worldpack_resource_not_enough", "这个世界观行动资源不足: " + "、".join(missing)
    money_cost = int(effect.get("money_cost") or 0)
    if money_cost and wallet_money(actor) < money_cost:
        return False, "worldpack_money_not_enough", f"这个行动需要 {money_cost} 金钱，你现在只有 {wallet_money(actor)}。"
    return True, None, None


def handle_worldpack_declarative_tool(
    session: Session,
    world: World,
    actor: Agent,
    spec: ToolSpec,
    params: dict[str, Any] | None,
    before_location_id: str | None,
    state_delta: dict[str, Any],
) -> list[int]:
    params = params or {}
    ok, reason, message = validate_worldpack_declarative_tool(actor, spec, params)
    if not ok:
        event = create_event(
            session,
            world=world,
            event_type="worldpack_tool_failed",
            actor_agent_id=actor.agent_id,
            location_id=before_location_id,
            visibility_scope="public",
            importance=20,
            color_class="warning",
            viewer_text=f"{_name(actor)} 没能执行 {spec.display_name}: {message}",
            agent_visible_text=message or "世界观工具失败。",
            payload={"tool_name": spec.tool_name, "failure_reason_code": reason, "pack_id": spec.metadata.get("pack_id")},
            no_state_changed=True,
        )
        return [event.event_id]

    effect = _choose_effect(world, actor, spec)
    ensure_v5_agent_state(actor)
    target = _target_from_params(session, world, actor, spec, params)
    before_state = deepcopy(_worldpack_state(actor, spec))
    state = _worldpack_state(actor, spec)
    resources = _int_map(state.setdefault("resources", {}))
    progress = state.setdefault("progress", {"level": 1, "exp": 0})
    flags = set(state.setdefault("flags", []))

    costs = _merged_costs(spec, effect)
    for resource, amount in costs.items():
        resources[resource] = max(0, resources.get(resource, 0) - amount)
    for resource, amount in _int_map(effect.get("worldpack_resources_delta") or effect.get("resource_delta") or {}).items():
        resources[resource] = max(0, resources.get(resource, 0) + amount)
    for resource, limit in _int_map(effect.get("resource_caps") or {}).items():
        resources[resource] = min(resources.get(resource, 0), limit)
    state["resources"] = resources

    money_delta = int(effect.get("money_delta") or 0) - int(effect.get("money_cost") or 0)
    if money_delta:
        add_money(actor, money_delta)

    exp_delta = int(effect.get("exp_delta") or 0)
    if exp_delta:
        progress["exp"] = int(progress.get("exp") or 0) + exp_delta
        _apply_level_curve(progress, effect)
    for flag in effect.get("worldpack_flags_add") or effect.get("flags_add") or []:
        flags.add(str(flag))
    for flag in effect.get("worldpack_flags_remove") or effect.get("flags_remove") or []:
        flags.discard(str(flag))
    state["flags"] = sorted(flags)
    state["progress"] = progress
    state.setdefault("history", []).append(
        {
            "world_time": world.current_world_time_minutes,
            "tool_name": spec.tool_name,
            "display_name": spec.display_name,
            "resources_after": deepcopy(resources),
            "progress_after": deepcopy(progress),
            "flags_after": sorted(flags),
        }
    )
    state["history"] = state["history"][-40:]
    _save_worldpack_state(actor, spec, state)

    if actor.dynamic_state and isinstance(effect.get("agent_delta"), dict):
        state_delta.setdefault(actor.agent_id, {})
        delta = apply_delta(actor.dynamic_state, **_float_delta(effect.get("agent_delta")))
        state_delta[actor.agent_id] = {**state_delta.get(actor.agent_id, {}), **delta}
    if target and target.dynamic_state and isinstance(effect.get("target_delta"), dict):
        state_delta.setdefault(target.agent_id, {})
        delta = apply_delta(target.dynamic_state, **_float_delta(effect.get("target_delta")))
        state_delta[target.agent_id] = {**state_delta.get(target.agent_id, {}), **delta}

    text = _render_text(effect, spec, actor, target, before_location_id, resources, progress, exp_delta, money_delta)
    importance = int(effect.get("event_importance") or spec.event_importance or 35)
    color_class = str(effect.get("color_class") or ("important" if importance >= 70 else "normal"))
    event = create_event(
        session,
        world=world,
        event_type=str(effect.get("event_type") or "worldpack_action"),
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id if target else None,
        location_id=before_location_id,
        viewer_text=text,
        agent_visible_text=text,
        importance=importance,
        color_class=color_class,
        payload={
            "tool_name": spec.tool_name,
            "display_name": spec.display_name,
            "pack_id": spec.metadata.get("pack_id"),
            "toolset_id": spec.metadata.get("toolset_id"),
            "worldview_id": spec.metadata.get("worldview_id"),
            "before_worldpack_state": before_state,
            "after_worldpack_state": deepcopy(state),
            "chosen_effect": deepcopy(effect),
            "params": params,
        },
    )
    return [event.event_id]


def _effect_for_spec(spec: ToolSpec) -> dict[str, Any]:
    raw = spec.metadata.get("declarative_effect") if isinstance(spec.metadata, dict) else None
    return deepcopy(raw) if isinstance(raw, dict) else {}


def _choose_effect(world: World, actor: Agent, spec: ToolSpec) -> dict[str, Any]:
    effect = _effect_for_spec(spec)
    outcomes = effect.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return effect
    rng = random.Random(f"{getattr(world, 'seed', 0)}:{world.current_world_time_minutes}:{actor.agent_id}:{spec.tool_name}")
    weighted: list[tuple[float, dict[str, Any]]] = []
    total = 0.0
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        weight = float(outcome.get("weight", 1) or 1)
        if weight <= 0:
            continue
        total += weight
        weighted.append((total, outcome))
    if not weighted:
        return effect
    roll = rng.random() * total
    selected = weighted[-1][1]
    for threshold, outcome in weighted:
        if roll <= threshold:
            selected = outcome
            break
    merged = deepcopy(effect)
    merged.pop("outcomes", None)
    merged.update(deepcopy(selected))
    return merged


def _worldpack_id(spec: ToolSpec) -> str:
    return str(spec.metadata.get("worldview_id") or spec.metadata.get("toolset_id") or spec.metadata.get("pack_id") or "external_world")


def _worldpack_state(actor: Agent, spec: ToolSpec) -> dict[str, Any]:
    ensure_v5_agent_state(actor)
    wallet = deepcopy(actor.wallet_json or {})
    all_state = wallet.setdefault(WORLD_PACK_STATE_KEY, {})
    key = _worldpack_id(spec)
    current = all_state.setdefault(key, {"resources": {}, "progress": {"level": 1, "exp": 0}, "flags": [], "history": []})
    if "progress" not in current or not isinstance(current["progress"], dict):
        current["progress"] = {"level": 1, "exp": 0}
    if "resources" not in current or not isinstance(current["resources"], dict):
        current["resources"] = {}
    if "flags" not in current or not isinstance(current["flags"], list):
        current["flags"] = []
    if "history" not in current or not isinstance(current["history"], list):
        current["history"] = []
    return current


def _save_worldpack_state(actor: Agent, spec: ToolSpec, state: dict[str, Any]) -> None:
    wallet = deepcopy(actor.wallet_json or {})
    all_state = wallet.setdefault(WORLD_PACK_STATE_KEY, {})
    all_state[_worldpack_id(spec)] = deepcopy(state)
    actor.wallet_json = wallet


def _merged_costs(spec: ToolSpec, effect: dict[str, Any]) -> dict[str, int]:
    costs = _int_map(spec.resource_cost or {})
    costs.update(_int_map(effect.get("resource_cost") or {}))
    return costs


def _int_map(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _float_delta(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _apply_level_curve(progress: dict[str, Any], effect: dict[str, Any]) -> None:
    level = int(progress.get("level") or 1)
    exp = int(progress.get("exp") or 0)
    base = int(effect.get("level_curve_base") or 24)
    scale = int(effect.get("level_curve_scale") or 12)
    max_level = int(effect.get("max_level") or 99)
    leveled = 0
    while level < max_level:
        threshold = max(1, base + level * scale)
        if exp < threshold:
            break
        exp -= threshold
        level += 1
        leveled += 1
    progress["level"] = level
    progress["exp"] = exp
    if leveled:
        progress["last_level_ups"] = leveled


def _target_from_params(session: Session, world: World, actor: Agent, spec: ToolSpec, params: dict[str, Any]) -> Agent | None:
    if spec.target_policy != "visible_ref":
        return None
    ref = params.get("visible_ref") or params.get("target_ref") or params.get("receiver_ref")
    if not ref:
        return None
    return resolve_visible_ref(session, actor, str(ref), world.current_world_time_minutes, persist=True)


def _render_text(
    effect: dict[str, Any],
    spec: ToolSpec,
    actor: Agent,
    target: Agent | None,
    location_id: str | None,
    resources: dict[str, int],
    progress: dict[str, Any],
    exp_delta: int,
    money_delta: int,
) -> str:
    template = str(effect.get("viewer_text") or effect.get("text") or "{actor} 执行了 {tool}。")
    values = {
        "actor": _name(actor),
        "target": _name(target) if target else "附近的人",
        "tool": spec.display_name,
        "location": location_id or "当前位置",
        "level": progress.get("level", 1),
        "exp": progress.get("exp", 0),
        "exp_delta": exp_delta,
        "money_delta": money_delta,
        "resources": "、".join(f"{k}:{v}" for k, v in sorted(resources.items())) or "无",
    }
    try:
        return template.format(**values)
    except Exception:
        return f"{_name(actor)} 执行了 {spec.display_name}。"


def _name(agent: Agent | None) -> str:
    if not agent:
        return "某人"
    return agent.chosen_name or getattr(agent, "agent_id", None) or "某人"
