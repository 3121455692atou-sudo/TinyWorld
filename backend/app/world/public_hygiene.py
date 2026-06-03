from __future__ import annotations

from typing import Any

from app.agents.state import apply_delta
from app.core.models import Agent, World


HYGIENE_KEY = "location_public_hygiene"
DEFAULT_CLEANLINESS = 100.0


def location_cleanliness(world: World, location_id: str | None) -> float:
    state = _entry(world, location_id)
    return float(state.get("cleanliness", DEFAULT_CLEANLINESS))


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
    settings, boards, entry = _mutable_entry(world, location_id)
    entry["traffic"] = min(80.0, float(entry.get("traffic", 0.0)) + max(0.0, amount))
    boards[location_id] = entry
    settings[HYGIENE_KEY] = boards
    world.settings_json = settings


def clean_location(world: World, location_id: str | None, *, amount: float = 45.0) -> float:
    if not location_id:
        return DEFAULT_CLEANLINESS
    settings, boards, entry = _mutable_entry(world, location_id)
    entry["cleanliness"] = min(DEFAULT_CLEANLINESS, float(entry.get("cleanliness", DEFAULT_CLEANLINESS)) + max(0.0, amount))
    entry["traffic"] = max(0.0, float(entry.get("traffic", 0.0)) - 12.0)
    entry["last_cleaned_world_time"] = int(getattr(world, "current_world_time_minutes", 0) or 0)
    boards[location_id] = entry
    settings[HYGIENE_KEY] = boards
    world.settings_json = settings
    return float(entry["cleanliness"])


def apply_location_hygiene_exposure(agent: Agent, to_world_time: int, elapsed_hours: float) -> dict[str, Any]:
    world = agent.world
    location_id = agent.location.location_id if agent.location else None
    if not world or not location_id or not agent.dynamic_state or elapsed_hours <= 0:
        return {}
    score = _advance_location_decay(world, location_id, to_world_time, elapsed_hours=elapsed_hours)
    if score >= 65:
        return {}
    penalty = -min(10.0, ((65.0 - score) / 65.0) * elapsed_hours * 4.0)
    if abs(penalty) < 0.05:
        return {}
    return apply_delta(agent.dynamic_state, hygiene=penalty)


def _advance_location_decay(world: World, location_id: str, to_world_time: int, *, elapsed_hours: float) -> float:
    settings, boards, entry = _mutable_entry(world, location_id)
    traffic = float(entry.get("traffic", 0.0))
    cleanliness = float(entry.get("cleanliness", DEFAULT_CLEANLINESS))
    decay = min(50.0, elapsed_hours * (0.08 + traffic * 0.18))
    cleanliness = max(0.0, cleanliness - decay)
    entry["cleanliness"] = cleanliness
    entry["traffic"] = max(0.0, traffic - elapsed_hours * 0.7)
    entry["last_decay_world_time"] = int(to_world_time)
    boards[location_id] = entry
    settings[HYGIENE_KEY] = boards
    world.settings_json = settings
    return cleanliness


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
