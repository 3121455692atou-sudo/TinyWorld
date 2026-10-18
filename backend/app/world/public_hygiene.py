from __future__ import annotations

import math
from typing import Any

from app.agents.numeric import finite_float, safe_int
from app.agents.state import apply_delta
from app.agents.traits import clamp
from app.core.models import Agent, World


HYGIENE_KEY = "location_public_hygiene"
DEFAULT_CLEANLINESS = 100.0


def location_cleanliness(world: World, location_id: str | None) -> float:
    state = _entry(world, location_id)
    return clamp(finite_float(state.get("cleanliness"), DEFAULT_CLEANLINESS))


def location_hygiene_prompt_line(world: World, location_id: str | None) -> str:
    score = location_cleanliness(world, location_id)
    if score >= 85:
        return f"当前地点公共清洁度 {score:.0f}/100，很干净，不会额外弄脏在场居民。"
    if score >= 65:
        return f"当前地点公共清洁度 {score:.0f}/100，基本可接受，但人流多时需要有人维护。"
    if score >= 40:
        return f"当前地点公共清洁度 {score:.0f}/100，已经偏脏；久待会让居民清洁值下降，适合有人自愿打扫或提出轮流清洁规则。"
    return f"当前地点公共清洁度 {score:.0f}/100，很脏；在这里久待会明显降低居民清洁值，也会带来公共卫生压力。"


def record_location_traffic(world: World, location_id: str | None, *, amount: float = 1.0) -> None:
    if not location_id:
        return
    _advance_location_decay(world, location_id, safe_int(world.current_world_time_minutes), elapsed_hours=0)
    settings, boards, entry = _mutable_entry(world, location_id)
    entry["traffic"] = min(80.0, finite_float(entry.get("traffic")) + max(0.0, finite_float(amount)))
    _reset_decay_anchor(entry)
    boards[location_id] = entry
    settings[HYGIENE_KEY] = boards
    world.settings_json = settings


def clean_location(world: World, location_id: str | None, *, amount: float = 45.0) -> float:
    if not location_id:
        return DEFAULT_CLEANLINESS
    _advance_location_decay(world, location_id, safe_int(world.current_world_time_minutes), elapsed_hours=0)
    settings, boards, entry = _mutable_entry(world, location_id)
    entry["cleanliness"] = clamp(finite_float(entry.get("cleanliness"), DEFAULT_CLEANLINESS) + max(0.0, finite_float(amount)))
    entry["traffic"] = max(0.0, finite_float(entry.get("traffic")) - 12.0)
    _reset_decay_anchor(entry)
    entry["last_cleaned_world_time"] = int(getattr(world, "current_world_time_minutes", 0) or 0)
    boards[location_id] = entry
    settings[HYGIENE_KEY] = boards
    world.settings_json = settings
    return float(entry["cleanliness"])


def apply_location_hygiene_exposure(agent: Agent, to_world_time: int, elapsed_hours: float, *, sleeping: bool = False) -> dict[str, Any]:
    world = agent.world
    location_id = agent.location.location_id if agent.location else None
    if not world or not location_id or not agent.dynamic_state or elapsed_hours <= 0:
        return {}
    desires = agent.desires_json if isinstance(agent.desires_json, dict) else {}
    cursor = desires.get("public_hygiene_cursor")
    cursor = cursor if isinstance(cursor, dict) and cursor.get("location_id") == location_id else {}
    if safe_int(cursor.get("world_time"), -1) >= to_world_time:
        return {}
    _advance_location_decay(world, location_id, to_world_time, elapsed_hours=elapsed_hours)
    entry = _entry(world, location_id)
    start = max(to_world_time - elapsed_hours * 60, safe_int(agent.location.arrived_at_world_time))
    total = _integral_at(entry, to_world_time)
    if cursor and safe_int(cursor.get("world_time"), -1) >= start:
        before = finite_float(cursor.get("integral"))
    else:
        before = _integral_at(entry, start)
    agent.desires_json = {**desires, "public_hygiene_cursor": {"location_id": location_id, "world_time": to_world_time, "integral": total}}
    penalty = -max(0, total - before)
    if sleeping or start >= to_world_time or penalty >= 0:
        return {}
    return apply_delta(agent.dynamic_state, hygiene=penalty)


def _advance_location_decay(world: World, location_id: str, to_world_time: int, *, elapsed_hours: float) -> float:
    settings, boards, entry = _mutable_entry(world, location_id)
    last = safe_int(entry.get("last_decay_world_time"), max(0, int(to_world_time - elapsed_hours * 60)))
    if "decay_anchor_world_time" not in entry:
        entry["last_decay_world_time"] = last
        _reset_decay_anchor(entry)
    if to_world_time < last:
        return clamp(finite_float(entry.get("cleanliness"), DEFAULT_CLEANLINESS))
    anchor = safe_int(entry.get("decay_anchor_world_time"), last)
    hours = max(0, (to_world_time - anchor) / 60.0)
    traffic = clamp(finite_float(entry.get("decay_anchor_traffic")), 0, 80)
    initial = clamp(finite_float(entry.get("decay_anchor_cleanliness"), DEFAULT_CLEANLINESS))
    cleanliness = max(0.0, initial - _cleanliness_loss(traffic, hours))
    entry["cleanliness"] = cleanliness
    entry["traffic"] = max(0.0, traffic - hours * 0.7)
    entry["last_decay_world_time"] = int(to_world_time)
    boards[location_id] = entry
    settings[HYGIENE_KEY] = boards
    world.settings_json = settings
    return cleanliness


def _reset_decay_anchor(entry: dict[str, Any]) -> None:
    # An immutable anchor between traffic/cleaning changes makes integration
    # independent of resident iteration order and time-step subdivision.
    now = safe_int(entry.get("last_decay_world_time"))
    if "decay_anchor_world_time" in entry:
        old_time = safe_int(entry["decay_anchor_world_time"])
        if old_time < now:
            history = entry.get("decay_history")
            history = list(history) if isinstance(history, list) else []
            history.append({"world_time": old_time, "cleanliness": entry.get("decay_anchor_cleanliness", 100), "traffic": entry.get("decay_anchor_traffic", 0), "integral": entry.get("decay_anchor_integral", 0)})
            # Resident cursors preserve cumulative exposure across any number of
            # edits. This bounded history handles first observation and arrival
            # within a recent interval without growing old save files forever.
            entry["decay_history"] = history[-64:]
            entry["decay_anchor_integral"] = _integral_at(entry, now)
    entry.setdefault("decay_anchor_integral", 0.0)
    entry["decay_anchor_world_time"] = now
    entry["decay_anchor_cleanliness"] = clamp(finite_float(entry.get("cleanliness"), DEFAULT_CLEANLINESS))
    entry["decay_anchor_traffic"] = clamp(finite_float(entry.get("traffic")), 0, 80)


def _integral_at(entry: dict[str, Any], world_time: float) -> float:
    anchor = {"world_time": entry.get("decay_anchor_world_time", world_time), "cleanliness": entry.get("decay_anchor_cleanliness", 100), "traffic": entry.get("decay_anchor_traffic", 0), "integral": entry.get("decay_anchor_integral", 0)}
    if world_time < safe_int(anchor["world_time"]):
        history = entry.get("decay_history")
        history = [item for item in history if isinstance(item, dict)] if isinstance(history, list) else []
        for item in reversed(history):
            anchor = item
            if safe_int(item.get("world_time")) <= world_time:
                break
    hours = max(0, (world_time - safe_int(anchor.get("world_time"))) / 60)
    return finite_float(anchor.get("integral")) + _exposure_integral(clamp(finite_float(anchor.get("cleanliness"), 100)), clamp(finite_float(anchor.get("traffic")), 0, 80), hours)


def _cleanliness_loss(traffic: float, hours: float) -> float:
    active = min(hours, traffic / 0.7)
    return 0.08 * hours + 0.18 * (traffic * active - 0.35 * active * active)


def _time_to_loss(traffic: float, loss: float) -> float:
    if loss <= 0:
        return 0.0
    active = traffic / 0.7
    active_loss = _cleanliness_loss(traffic, active)
    if loss >= active_loss:
        return active + (loss - active_loss) / 0.08
    coefficient = 0.08 + 0.18 * traffic
    return 2 * loss / (coefficient + math.sqrt(max(0, coefficient * coefficient - 4 * 0.063 * loss)))


def _exposure_integral(cleanliness: float, traffic: float, hours: float) -> float:
    # The burden curve is quadratic while traffic drains, then linear, then
    # constant after cleanliness reaches zero. Simpson is exact per segment.
    points = sorted({0.0, hours, *(t for t in (traffic / 0.7, _time_to_loss(traffic, cleanliness - 65), _time_to_loss(traffic, cleanliness)) if 0 < t < hours)})

    def burden(at: float) -> float:
        return max(0.0, 65 - max(0, cleanliness - _cleanliness_loss(traffic, at))) * 4 / 65

    return sum((right - left) * (burden(left) + 4 * burden((left + right) / 2) + burden(right)) / 6 for left, right in zip(points, points[1:]))


def _entry(world: World, location_id: str | None) -> dict[str, Any]:
    if not location_id:
        return {"cleanliness": DEFAULT_CLEANLINESS, "traffic": 0.0}
    boards = (world.settings_json or {}).get(HYGIENE_KEY)
    if not isinstance(boards, dict):
        return {"cleanliness": DEFAULT_CLEANLINESS, "traffic": 0.0}
    entry = boards.get(location_id)
    return dict(entry) if isinstance(entry, dict) else {"cleanliness": DEFAULT_CLEANLINESS, "traffic": 0.0}


def _mutable_entry(world: World, location_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    settings = dict(world.settings_json or {})
    boards = settings.get(HYGIENE_KEY)
    boards = dict(boards) if isinstance(boards, dict) else {}
    entry = boards.get(location_id)
    entry = dict(entry) if isinstance(entry, dict) else {"cleanliness": DEFAULT_CLEANLINESS, "traffic": 0.0}
    entry.setdefault("cleanliness", DEFAULT_CLEANLINESS)
    entry.setdefault("traffic", 0.0)
    return settings, boards, entry
