from __future__ import annotations

import json
import os
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import apply_delta
from app.core.models import Agent, Location, World
from app.events.event_store import create_event
from app.knowledge.relationships import adjust_relationship


INTERVENTION_PACK_FORMAT = "aiworld.intervention_pack.v1"


class InterventionPackError(ValueError):
    """Raised when an intervention ability pack is malformed."""


@dataclass(frozen=True, slots=True)
class InterventionAbility:
    ability_id: str
    name: str
    description: str
    requires_actor: bool = True
    requires_target: bool = False
    requires_location: bool = False
    event_type: str = "player_intervention_plugin"
    importance: int = 65
    color_class: str = "important"
    viewer_text_template: str = "{actor} 身上发生了一件无法解释的事。{note}"
    actor_delta: dict[str, float] | None = None
    target_delta: dict[str, float] | None = None
    relationship_delta_actor_to_target: dict[str, float] | None = None
    relationship_delta_target_to_actor: dict[str, float] | None = None
    move_actor_to_selected_location: bool = False
    move_target_to_selected_location: bool = False
    source_path: str = "builtin"


BUILTIN_ABILITIES = [
    InterventionAbility(
        ability_id="move_agent",
        name="移动居民",
        description="把一个居民移动到指定地点；私人地点仍按世界规则记录后果。",
        requires_location=True,
    ),
    InterventionAbility(
        ability_id="meteor_kill",
        name="陨石坠落",
        description="让陨石坠落杀死指定居民。",
    ),
    InterventionAbility(
        ability_id="love_one_way",
        name="单向心动",
        description="让指定居民对另一个居民产生影响世界专属的临时强制心动状态，并提高恋爱行动倾向。",
        requires_target=True,
    ),
    InterventionAbility(
        ability_id="love_mutual",
        name="相互心动",
        description="让两名居民彼此产生影响世界专属的临时强制心动状态，并提高恋爱行动倾向。",
        requires_target=True,
    ),
    InterventionAbility(
        ability_id="miracle_pregnancy",
        name="奇迹怀孕",
        description="让指定居民怀孕；对象会作为伴侣/共同父母记录。",
        requires_target=True,
    ),
    InterventionAbility(
        ability_id="miracle_birth",
        name="奇迹诞生",
        description="让指定怀孕人生下孩子。",
        requires_target=False,
    ),
]

_CACHE: list[InterventionAbility] | None = None
_ERRORS: list[dict[str, str]] = []


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def imported_intervention_dir() -> Path:
    return Path(os.getenv("AIWORLD_IMPORTED_INTERVENTION_DIR", str(project_root() / "worldpacks" / "interventions"))).expanduser()


def load_intervention_abilities(*, force: bool = False) -> list[InterventionAbility]:
    global _CACHE, _ERRORS
    if _CACHE is not None and not force:
        return _CACHE
    abilities = list(BUILTIN_ABILITIES)
    errors: list[dict[str, str]] = []
    directory = imported_intervention_dir()
    if directory.exists():
        for path in sorted(directory.glob("*")):
            if path.suffix.lower() not in {".json", ".zip"} and not path.name.endswith(".aiworld.intervention.json"):
                continue
            try:
                abilities.extend(load_intervention_pack_file(path))
            except Exception as exc:
                errors.append({"source_path": str(path), "error": str(exc)})
    deduped: dict[str, InterventionAbility] = {}
    for ability in abilities:
        deduped[ability.ability_id] = ability
    _CACHE = list(deduped.values())
    _ERRORS = errors
    return _CACHE


def intervention_pack_errors() -> list[dict[str, str]]:
    load_intervention_abilities()
    return list(_ERRORS)


def save_imported_intervention_pack(filename: str, content: bytes) -> list[InterventionAbility]:
    abilities = load_intervention_pack_bytes(filename, content)
    target_dir = imported_intervention_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename, default="intervention_pack.aiworld.intervention.json")
    target = target_dir / safe_name
    if target.exists():
        stem = target.stem
        suffix = "".join(target.suffixes) or ".json"
        target = target_dir / f"{stem}_{len(list(target_dir.glob(stem + '*')))}{suffix}"
    target.write_bytes(content)
    load_intervention_abilities(force=True)
    return load_intervention_pack_file(target)


def load_intervention_pack_file(path: Path) -> list[InterventionAbility]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            name = "manifest.json" if "manifest.json" in zf.namelist() else next((item for item in zf.namelist() if item.endswith(".json")), None)
            if not name:
                raise InterventionPackError("zip 影响世界能力包缺少 JSON manifest")
            raw = json.loads(zf.read(name).decode("utf-8"))
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
    return _parse_pack(raw, source_path=str(path))


def load_intervention_pack_bytes(filename: str, content: bytes) -> list[InterventionAbility]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            return load_intervention_pack_file(tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
    return _parse_pack(json.loads(content.decode("utf-8")), source_path=filename)


def summarize_abilities(abilities: list[InterventionAbility]) -> list[dict[str, Any]]:
    return [ability_to_dict(ability) for ability in abilities]


def ability_to_dict(ability: InterventionAbility) -> dict[str, Any]:
    return {
        "ability_id": ability.ability_id,
        "name": ability.name,
        "description": ability.description,
        "requires_actor": ability.requires_actor,
        "requires_target": ability.requires_target,
        "requires_location": ability.requires_location,
        "source_path": ability.source_path,
    }


def apply_intervention_ability(
    session: Session,
    world: World,
    *,
    ability_id: str,
    actor: Agent | None,
    target: Agent | None,
    location: Location | None,
    note: str = "",
) -> list[int] | None:
    ability = next((item for item in load_intervention_abilities() if item.ability_id == ability_id and item.source_path != "builtin"), None)
    if ability is None:
        return None
    if ability.requires_actor and actor is None:
        raise InterventionPackError("这个能力需要选择居民。")
    if ability.requires_target and target is None:
        raise InterventionPackError("这个能力需要选择对象。")
    if ability.requires_location and location is None:
        raise InterventionPackError("这个能力需要选择地点。")
    if actor and actor.world_id != world.world_id:
        raise InterventionPackError("居民不属于当前世界。")
    if target and target.world_id != world.world_id:
        raise InterventionPackError("对象不属于当前世界。")
    if location and location.world_id != world.world_id:
        raise InterventionPackError("地点不属于当前世界。")

    state_delta: dict[str, Any] = {}
    if ability.actor_delta and actor and actor.dynamic_state:
        state_delta[actor.agent_id] = apply_delta(actor.dynamic_state, **ability.actor_delta)
    if ability.target_delta and target and target.dynamic_state:
        state_delta[target.agent_id] = apply_delta(target.dynamic_state, **ability.target_delta)
    if ability.relationship_delta_actor_to_target and actor and target:
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, **ability.relationship_delta_actor_to_target)
    if ability.relationship_delta_target_to_actor and actor and target:
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, **ability.relationship_delta_target_to_actor)
    if ability.move_actor_to_selected_location and actor and location:
        _move_agent(actor, location, world)
    if ability.move_target_to_selected_location and target and location:
        _move_agent(target, location, world)

    text = _render_template(ability.viewer_text_template, actor=actor, target=target, location=location, note=note)
    event = create_event(
        session,
        world=world,
        event_type=ability.event_type,
        actor_agent_id=actor.agent_id if actor else None,
        target_agent_id=target.agent_id if target else None,
        location_id=location.location_id if location else actor.location.location_id if actor and actor.location else None,
        viewer_text=text,
        importance=ability.importance,
        color_class=ability.color_class,
        state_delta=state_delta,
        payload={"intervention": ability.ability_id, "plugin": True, "note": note},
    )
    return [event.event_id]


def _parse_pack(raw: dict[str, Any], *, source_path: str) -> list[InterventionAbility]:
    if not isinstance(raw, dict):
        raise InterventionPackError("能力包必须是 JSON 对象")
    fmt = str(raw.get("format") or "")
    if fmt and fmt != INTERVENTION_PACK_FORMAT:
        raise InterventionPackError(f"不支持的能力包格式: {fmt}")
    entries = raw.get("abilities") or raw.get("intervention_abilities") or []
    if not isinstance(entries, list):
        raise InterventionPackError("abilities 必须是数组")
    abilities = [_parse_ability(item, source_path=source_path) for item in entries if isinstance(item, dict)]
    if not abilities:
        raise InterventionPackError("能力包里没有可用 abilities")
    return abilities


def _parse_ability(raw: dict[str, Any], *, source_path: str) -> InterventionAbility:
    ability_id = str(raw.get("ability_id") or raw.get("id") or "").strip()
    if not ability_id:
        raise InterventionPackError("ability_id 不能为空")
    return InterventionAbility(
        ability_id=ability_id,
        name=str(raw.get("name") or ability_id).strip(),
        description=str(raw.get("description") or "").strip(),
        requires_actor=bool(raw.get("requires_actor", True)),
        requires_target=bool(raw.get("requires_target", False)),
        requires_location=bool(raw.get("requires_location", False)),
        event_type=str(raw.get("event_type") or "player_intervention_plugin").strip(),
        importance=_safe_int(raw.get("importance"), 0, 100, 65),
        color_class=str(raw.get("color_class") or "important").strip(),
        viewer_text_template=str(raw.get("viewer_text_template") or raw.get("text_template") or "{actor} 身上发生了一件无法解释的事。{note}"),
        actor_delta=_float_delta(raw.get("actor_delta")),
        target_delta=_float_delta(raw.get("target_delta")),
        relationship_delta_actor_to_target=_float_delta(raw.get("relationship_delta_actor_to_target")),
        relationship_delta_target_to_actor=_float_delta(raw.get("relationship_delta_target_to_actor")),
        move_actor_to_selected_location=bool(raw.get("move_actor_to_selected_location", False)),
        move_target_to_selected_location=bool(raw.get("move_target_to_selected_location", False)),
        source_path=source_path,
    )


def _render_template(template: str, *, actor: Agent | None, target: Agent | None, location: Location | None, note: str) -> str:
    values = {
        "actor": actor.chosen_name if actor else "某位居民",
        "target": target.chosen_name if target else "某个人",
        "location": location.public_name if location else "某个地点",
        "note": note,
    }
    try:
        return template.format(**values).strip()
    except Exception:
        return f"{values['actor']} 身上发生了一件无法解释的事。{note}".strip()


def _move_agent(agent: Agent, location: Location, world: World) -> None:
    if agent.location:
        agent.location.location_id = location.location_id
        agent.location.arrived_at_world_time = world.current_world_time_minutes


def _float_delta(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    result: dict[str, float] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result or None


def _safe_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _safe_filename(filename: str, *, default: str) -> str:
    name = Path(filename or default).name
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
    return cleaned or default
