from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.agents.numeric import require_finite, safe_int
from app.agents.state import DYNAMIC_FIELDS, apply_delta
from app.agents.v5_state import add_money, ensure_v5_agent_state, wallet_money
from app.core.models import Agent, World
from app.events.event_store import create_event
from app.tools.tool_specs import ToolSpec
from app.world.visibility import resolve_visible_ref, visible_agents


WORLD_PACK_STATE_KEY = "worldpack_state"


def validate_worldpack_declarative_tool(actor: Agent, spec: ToolSpec, params: dict[str, Any] | None = None) -> tuple[bool, str | None, str | None]:
    """Validate declarative content-pack gates that the generic ToolSpec cannot know.

    This deliberately checks only local actor state. Location/target/lifecycle checks stay in
    validators.py so external world authors cannot bypass core validation and visibility rules.
    """
    effect = _effect_for_spec(spec)
    try:
        _validate_effect_numbers(effect, spec)
    except ValueError as exc:
        return False, "worldpack_invalid_effect", f"世界观行动配置无效: {exc}"
    return _validate_effect_requirements(actor, spec, effect)


def _validate_effect_requirements(actor: Agent, spec: ToolSpec, effect: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    state = _worldpack_state(actor, spec)
    progress = state.setdefault("progress", {"level": 1, "exp": 0})
    level = int(progress.get("level") or 1)
    required_level = _integer(effect.get("required_level") or effect.get("min_level") or 0, "required level")
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
    money_cost = _integer(effect.get("money_cost") or 0, "money cost")
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
    effect: dict[str, Any] = {}
    if ok:
        effect = _choose_effect(world, actor, spec)
        # Outcomes may override the price or prerequisites. Check the selected
        # branch before granting rewards or charging any part of its cost.
        ok, reason, message = _validate_effect_requirements(actor, spec, effect)
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
            viewer_text=f"{_name(actor)}试着进行一个世界观行动，但这次没有完成。",
            agent_visible_text=message or "世界观工具失败。",
            payload={"tool_name": spec.tool_name, "failure_reason_code": reason, "pack_id": spec.metadata.get("pack_id"), "llm_feedback": message},
            no_state_changed=True,
        )
        return [event.event_id]

    target = _target_from_params(session, world, actor, spec, params)
    if spec.target_policy == "visible_ref" and (not target or target.world_id != world.world_id or target.lifecycle_state == "dead"):
        raise ValueError("worldpack target is no longer available")
    if effect.get("target_delta") and (not target or not target.dynamic_state):
        raise ValueError("worldpack target has no dynamic state")
    if effect.get("agent_delta") and not actor.dynamic_state:
        raise ValueError("worldpack actor has no dynamic state")
    ensure_v5_agent_state(actor)
    state = _worldpack_state(actor, spec)
    before_state = deepcopy(state)
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

    money_delta = _integer(effect.get("money_delta") or 0, "money delta") - _integer(effect.get("money_cost") or 0, "money cost")
    if money_delta:
        add_money(actor, money_delta)

    exp_delta = _integer(effect.get("exp_delta") or 0, "experience delta")
    progress["last_level_ups"] = 0
    if exp_delta:
        progress["exp"] = max(0, int(progress.get("exp") or 0) + exp_delta)
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
    importance = max(0, min(100, _integer(effect.get("event_importance") or spec.event_importance or 35, "event importance")))
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
    candidates = [(require_finite(outcome.get("weight", 1), "outcome weight"), outcome) for outcome in outcomes if isinstance(outcome, dict)]
    maximum = max((weight for weight, _ in candidates), default=0)
    weighted: list[tuple[float, dict[str, Any]]] = []
    total = 0.0
    for weight, outcome in candidates:
        if weight <= 0:
            continue
        total += weight / maximum
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
    wallet = actor.wallet_json if isinstance(actor.wallet_json, dict) else {}
    all_state = wallet.get(WORLD_PACK_STATE_KEY)
    all_state = all_state if isinstance(all_state, dict) else {}
    key = _worldpack_id(spec)
    raw = all_state.get(key)
    # Only copy the requested pack, not the entire wallet and every other pack's
    # histories, inventories, investments and extension data for each menu gate.
    current = deepcopy(raw) if isinstance(raw, dict) else {}
    if "progress" not in current or not isinstance(current["progress"], dict):
        current["progress"] = {"level": 1, "exp": 0}
    if "resources" not in current or not isinstance(current["resources"], dict):
        current["resources"] = {}
    if "flags" not in current or not isinstance(current["flags"], list):
        current["flags"] = []
    if "history" not in current or not isinstance(current["history"], list):
        current["history"] = []
    current["progress"]["level"] = max(1, safe_int(current["progress"].get("level"), 1))
    current["progress"]["exp"] = max(0, safe_int(current["progress"].get("exp")))
    current["resources"] = {key: max(0, value) for key, value in _int_map(current["resources"]).items()}
    current["flags"] = [str(flag) for flag in current["flags"] if isinstance(flag, (str, int))]
    return current


def _save_worldpack_state(actor: Agent, spec: ToolSpec, state: dict[str, Any]) -> None:
    wallet = dict(actor.wallet_json or {})
    raw = wallet.get(WORLD_PACK_STATE_KEY)
    all_state = dict(raw) if isinstance(raw, dict) else {}
    all_state[_worldpack_id(spec)] = deepcopy(state)
    wallet[WORLD_PACK_STATE_KEY] = all_state
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
            result[str(key)] = _integer(value, str(key))
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def _float_delta(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = require_finite(value, str(key))
        except ValueError:
            continue
    return result


def _apply_level_curve(progress: dict[str, Any], effect: dict[str, Any]) -> None:
    level = max(1, safe_int(progress.get("level"), 1))
    exp = max(0, safe_int(progress.get("exp")))
    base = _integer(effect.get("level_curve_base") or 24, "level curve base")
    scale = _integer(effect.get("level_curve_scale") or 12, "level curve scale")
    max_level = _integer(effect.get("max_level") or 99, "max level")
    # Sum the same clamped arithmetic progression in O(1), then find the
    # affordable level count in O(log n). Large authored rewards cannot stall
    # the simulation in a level-by-level loop.
    def cost(count: int) -> int:
        first = base + level * scale
        if scale == 0:
            return count * max(1, first)
        if scale > 0:
            flat = min(count, max(0, (1 - first + scale - 1) // scale))
            rising = count - flat
            return flat + rising * (2 * (first + flat * scale) + (rising - 1) * scale) // 2
        falling = min(count, max(0, (first - 1) // -scale + 1))
        return falling * (2 * first + (falling - 1) * scale) // 2 + count - falling

    lower, upper = 0, max(0, min(max_level - level, exp))
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if cost(middle) <= exp:
            lower = middle
        else:
            upper = middle - 1
    progress["level"] = level + lower
    progress["exp"] = max(0, exp - cost(lower))
    progress["last_level_ups"] = lower


def _validate_effect_numbers(effect: dict[str, Any], spec: ToolSpec) -> None:
    for key, value in (spec.resource_cost or {}).items():
        if _integer(value, f"resource_cost.{key}") < 0:
            raise ValueError("resource costs must be nonnegative")
    outcomes = effect.get("outcomes")
    if outcomes is not None and not isinstance(outcomes, list):
        raise ValueError("outcomes must be a list")
    for branch in [effect, *(outcomes or [])]:
        if not isinstance(branch, dict):
            raise ValueError("each outcome must be an object")
        for key in ("money_delta", "money_cost", "exp_delta", "required_level", "min_level", "level_curve_base", "level_curve_scale", "max_level", "event_importance"):
            if key not in branch or branch[key] is None:
                continue
            number = _integer(branch[key], key)
            if key in {"money_cost", "required_level", "min_level", "max_level"} and number < 0:
                raise ValueError(f"{key} must be nonnegative")
        if "weight" in branch and require_finite(branch["weight"], "outcome weight") < 0:
            raise ValueError("outcome weight must be nonnegative")
        for key in ("resource_cost", "requires_resources", "resource_caps", "worldpack_resources_delta", "resource_delta"):
            values = branch.get(key)
            if values is None:
                continue
            if not isinstance(values, dict):
                raise ValueError(f"{key} must be an object")
            for resource, value in values.items():
                number = _integer(value, f"{key}.{resource}")
                if key in {"resource_cost", "requires_resources", "resource_caps"} and number < 0:
                    raise ValueError(f"{key}.{resource} must be nonnegative")
        for key in ("agent_delta", "target_delta"):
            values = branch.get(key)
            if values is None:
                continue
            if not isinstance(values, dict):
                raise ValueError(f"{key} must be an object")
            for field, value in values.items():
                if field not in DYNAMIC_FIELDS:
                    raise ValueError(f"unsupported dynamic attribute: {field}")
                require_finite(value, f"{key}.{field}")


def _integer(value: Any, name: str) -> int:
    number = require_finite(value, name)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer")
    return value if isinstance(value, int) else int(number)


def _target_from_params(session: Session, world: World, actor: Agent, spec: ToolSpec, params: dict[str, Any]) -> Agent | None:
    if spec.target_policy != "visible_ref":
        return None
    expected_id = params.get("visible_agent_id")
    if expected_id:
        # A menu binds an identity, while the display letter may be reassigned
        # after somebody leaves. Revalidate visibility without rebinding to the
        # new occupant of that letter; an absent stable target stays absent.
        return next((candidate for candidate in visible_agents(session, actor) if candidate.agent_id == expected_id and candidate.world_id == world.world_id), None)
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
