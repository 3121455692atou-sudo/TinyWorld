from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import apply_delta
from app.agents.traits import clamp
from app.core.models import Agent, Event, IdentityKnowledge, Location, Relationship, World
from app.events.event_store import create_event
from app.memory.memory_service import add_memory
from app.world.visibility import adjacent_location_ids, location_public_name, mark_visual_known

CORPSE_RECORDS_KEY = "corpse_records"
MODERN_WORLD_TOOLSET_IDS = {"fast_modern_world_toolset", "default_modern_world_toolset", "default_modern_toolset"}
CORPSE_TOOL_NAMES = {
    "inspect_visible_corpse",
    "mourn_visible_corpse",
    "report_visible_corpse",
    "bury_visible_corpse",
    "avoid_corpse_area",
}


def corpse_system_enabled(world: World | None) -> bool:
    if world is None:
        return False
    settings = world.settings_json or {}
    selected = settings.get("world_toolset_id") or settings.get("toolset_id")
    if selected:
        return str(selected) in MODERN_WORLD_TOOLSET_IDS
    return True


def ensure_corpse_for_dead_agent(session: Session, world: World, agent: Agent, *, location_id: str | None, cause: str) -> dict[str, Any]:
    if not corpse_system_enabled(world):
        return {}
    records = _records(world)
    existing = next((record for record in records if record.get("agent_id") == agent.agent_id), None)
    if existing:
        return _with_stage(existing, world.current_world_time_minutes)
    corpse_id = f"corpse:{agent.agent_id}"
    record = {
        "corpse_id": corpse_id,
        "agent_id": agent.agent_id,
        "name": agent.chosen_name or "未命名者",
        "appearance": agent.appearance_short or agent.appearance_full or "外貌难以辨认的人",
        "location_id": location_id,
        "death_world_time": world.current_world_time_minutes,
        "cause": cause,
        "buried": False,
        "buried_at_world_time": None,
        "buried_by_agent_id": None,
        "reported_by_agent_ids": [],
        "discovered_by_agent_ids": [],
        "mourned_by_agent_ids": [],
    }
    records.append(record)
    _save_records(world, records)
    return _with_stage(record, world.current_world_time_minutes)


def visible_corpses_at_location(session: Session, world: World, location_id: str | None) -> list[dict[str, Any]]:
    if not corpse_system_enabled(world) or not location_id:
        return []
    records = [record for record in _records(world) if not record.get("buried") and record.get("location_id") == location_id]
    records.sort(key=lambda item: (int(item.get("death_world_time") or 0), str(item.get("corpse_id") or "")))
    result: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        enriched = _with_stage(record, world.current_world_time_minutes)
        enriched["corpse_ref"] = _corpse_ref(index)
        result.append(enriched)
    return result


def has_visible_corpses(session: Session, world: World, agent: Agent) -> bool:
    return bool(agent.location and visible_corpses_at_location(session, world, agent.location.location_id))


def resolve_visible_corpse(session: Session, world: World, agent: Agent, corpse_ref: str | None) -> dict[str, Any] | None:
    corpses = visible_corpses_at_location(session, world, agent.location.location_id if agent.location else None)
    if not corpses:
        return None
    if not corpse_ref:
        return corpses[0]
    for corpse in corpses:
        if corpse.get("corpse_ref") == corpse_ref or corpse.get("corpse_id") == corpse_ref:
            return corpse
    return None


def visible_corpse_prompt_lines(session: Session, world: World, observer: Agent) -> list[str]:
    corpses = visible_corpses_at_location(session, world, observer.location.location_id if observer.location else None)
    lines: list[str] = []
    for corpse in corpses:
        dead_agent = session.get(Agent, corpse.get("agent_id"))
        known_name = _known_name(session, observer, dead_agent) if dead_agent else None
        relation_note = _relationship_corpse_note(session, observer, dead_agent) if dead_agent else ""
        identity = known_name or "未知姓名"
        line = (
            f"- {corpse['corpse_ref']}: 疑似身份={identity}; 外貌={corpse.get('appearance')}; "
            f"状态={corpse.get('stage_label')}; 气味等级={corpse.get('stench_level')}/5; 疾病风险={corpse.get('disease_risk_label')}。"
        )
        if relation_note:
            line += f" {relation_note}"
        lines.append(line)
    return lines


def corpse_rules_prompt_lines(session: Session, world: World, observer: Agent) -> list[str]:
    if not has_visible_corpses(session, world, observer):
        return []
    return [
        "眼前尸体是真实世界事实，不是背景装饰；它会长期留在地点，没人处理就会腐烂、发臭并带来疾病风险。",
        "你可以观察、哀悼、报警、离开或埋葬尸体。埋葬是纯负收益劳动：消耗体力、降低清洁、增加压力和悲伤，不会给钱、声望或快乐。是否管闲事由你自己决定。",
        "如果尸体属于你很亲近的人，你应该像普通人一样受到冲击；可以崩溃、麻木、逃走、报警、埋葬或强忍，但不要表现得像没看见。",
    ]


def apply_corpse_exposure(session: Session, world: World, agent: Agent) -> list[int]:
    if agent.lifecycle_state == "dead" or not agent.location or not agent.dynamic_state:
        return []
    corpses = visible_corpses_at_location(session, world, agent.location.location_id)
    if not corpses:
        return []
    event_ids: list[int] = []
    changed_records = False
    records = _records(world)
    discovered_now: list[dict[str, Any]] = []
    for corpse in corpses:
        record = _find_record(records, corpse["corpse_id"])
        if not record:
            continue
        discovered = list(record.get("discovered_by_agent_ids") or [])
        if agent.agent_id not in discovered:
            discovered.append(agent.agent_id)
            record["discovered_by_agent_ids"] = discovered[-200:]
            discovered_now.append(corpse)
            changed_records = True
            dead_agent = session.get(Agent, corpse.get("agent_id"))
            if dead_agent:
                mark_visual_known(session, agent, dead_agent, world.current_world_time_minutes)
    if changed_records:
        _save_records(world, records)

    for corpse in discovered_now:
        dead_agent = session.get(Agent, corpse.get("agent_id"))
        text = _first_sight_text(session, agent, dead_agent, corpse)
        delta = _corpse_first_sight_delta(session, agent, dead_agent)
        state_delta = {agent.agent_id: apply_delta(agent.dynamic_state, **delta)} if delta else {}
        event = create_event(
            session,
            world=world,
            event_type="corpse_seen",
            actor_agent_id=agent.agent_id,
            target_agent_id=dead_agent.agent_id if dead_agent else None,
            location_id=agent.location.location_id,
            viewer_text=text,
            agent_visible_text=text,
            importance=90 if _grief_score(session, agent, dead_agent) >= 80 else 75,
            color_class="danger",
            payload={"corpse_id": corpse.get("corpse_id"), "stage": corpse.get("stage"), "first_sight": True},
            state_delta=state_delta,
        )
        event_ids.append(event.event_id)
        if dead_agent and _grief_score(session, agent, dead_agent) >= 60:
            add_memory(
                session,
                agent_id=agent.agent_id,
                content=_trauma_memory_text(session, agent, dead_agent, corpse),
                world_time=world.current_world_time_minutes,
                importance=95,
            )

    undiscovered_ids = {str(corpse.get("corpse_id")) for corpse in discovered_now}
    seen_corpses = [corpse for corpse in corpses if str(corpse.get("corpse_id")) not in undiscovered_ids]
    if seen_corpses:
        desires = dict(agent.desires_json or {})
        raw_last_seen = desires.get("last_corpse_presence_world_time")
        try:
            last_seen = int(raw_last_seen) if raw_last_seen is not None else -10**9
        except (TypeError, ValueError):
            last_seen = -10**9
        if world.current_world_time_minutes - last_seen >= 240:
            desires["last_corpse_presence_world_time"] = world.current_world_time_minutes
            agent.desires_json = desires
            names = []
            for corpse in seen_corpses[:3]:
                dead_agent = session.get(Agent, corpse.get("agent_id"))
                names.append(_corpse_identity_label(session, agent, dead_agent))
            suffix = "，还有别的尸体" if len(seen_corpses) > 3 else ""
            location_name = location_public_name(session, agent.location.location_id)
            event = create_event(
                session,
                world=world,
                event_type="corpse_presence",
                actor_agent_id=agent.agent_id,
                location_id=agent.location.location_id,
                viewer_text=f"{agent.chosen_name} 仍然能看见 {location_name} 的尸体：{ '、'.join(names) }{suffix}。死亡没有因为习惯而消失，只是冲击比第一次轻了一些。",
                agent_visible_text=f"这里仍有尸体：{ '、'.join(names) }{suffix}。你已经见过，但它依旧是眼前的事实。",
                importance=45,
                color_class="warning",
                payload={"corpse_count": len(seen_corpses), "first_sight": False},
            )
            event_ids.append(event.event_id)

    max_stench = max(int(corpse.get("stench_level") or 0) for corpse in corpses)
    if max_stench <= 0:
        return event_ids
    desires = dict(agent.desires_json or {})
    raw_last = desires.get("last_corpse_exposure_world_time")
    try:
        last = int(raw_last) if raw_last is not None else -10**9
    except (TypeError, ValueError):
        last = -10**9
    interval = 180 if max_stench >= 3 else 300
    if world.current_world_time_minutes - last < interval:
        return event_ids
    desires["last_corpse_exposure_world_time"] = world.current_world_time_minutes
    exposure_count = int(desires.get("corpse_exposure_count") or 0) + 1
    desires["corpse_exposure_count"] = exposure_count
    illness_risk = int(desires.get("illness_risk") or 0)
    illness_risk = int(clamp(illness_risk + max_stench * 3, 0, 100))
    desires["illness_risk"] = illness_risk
    agent.desires_json = desires

    disease_hit = _corpse_disease_hit(world, agent, max_stench, exposure_count)
    delta = {
        "stress": 2 + max_stench * 2,
        "hygiene": -(2 + max_stench * 2),
        "mood": -(1 + max_stench),
    }
    if disease_hit:
        delta.update({"health": -max(1, max_stench - 1), "energy": -max_stench})
    state_delta = {agent.agent_id: apply_delta(agent.dynamic_state, **delta)}
    location_name = location_public_name(session, agent.location.location_id)
    disease_text = "，还感到一阵恶心和发冷，像是被腐败环境拖累了身体" if disease_hit else ""
    event = create_event(
        session,
        world=world,
        event_type="corpse_exposure",
        actor_agent_id=agent.agent_id,
        location_id=agent.location.location_id,
        viewer_text=f"{agent.chosen_name} 在 {location_name} 闻到尸体腐败的气味，心里和身体都很不舒服{disease_text}。",
        importance=65 + max_stench * 4,
        color_class="warning",
        payload={"max_stench_level": max_stench, "corpse_count": len(corpses), "disease_hit": disease_hit, "illness_risk": illness_risk},
        state_delta=state_delta,
    )
    event_ids.append(event.event_id)
    return event_ids


def handle_corpse_tool(session: Session, world: World, actor: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    corpse = resolve_visible_corpse(session, world, actor, str(params.get("corpse_ref") or "") or None)
    if not corpse:
        event = create_event(
            session,
            world=world,
            event_type="tool_failed",
            actor_agent_id=actor.agent_id,
            location_id=location_id,
            visibility_scope="system",
            viewer_text=f"{actor.chosen_name} 没能处理尸体：当前位置没有可见尸体。",
            importance=10,
            color_class="warning",
            payload={"tool_name": tool_name, "failure_reason_code": "corpse_not_visible"},
            no_state_changed=True,
        )
        return [event.event_id]
    dead_agent = session.get(Agent, corpse.get("agent_id"))
    if dead_agent:
        mark_visual_known(session, actor, dead_agent, world.current_world_time_minutes)
    if tool_name == "inspect_visible_corpse":
        delta = {"stress": 5, "mood": -3, "hygiene": -2}
        if _grief_score(session, actor, dead_agent) >= 70:
            delta.update({"stress": 10, "mood": -8})
        state_delta[actor.agent_id] = apply_delta(actor.dynamic_state, **delta)
        text = _inspect_text(session, actor, dead_agent, corpse)
        event = create_event(
            session,
            world=world,
            event_type="corpse_inspect",
            actor_agent_id=actor.agent_id,
            target_agent_id=dead_agent.agent_id if dead_agent else None,
            location_id=location_id,
            viewer_text=text,
            importance=70,
            color_class="warning",
            payload={"corpse_id": corpse.get("corpse_id"), "corpse_ref": corpse.get("corpse_ref")},
            state_delta=state_delta,
        )
        return [event.event_id]
    if tool_name == "mourn_visible_corpse":
        grief = _grief_score(session, actor, dead_agent)
        delta = {"energy": -3, "stress": 5, "mood": -6}
        if grief >= 70:
            delta = {"energy": -5, "stress": 12, "mood": -14, "social": -2}
        state_delta[actor.agent_id] = apply_delta(actor.dynamic_state, **delta)
        _mark_corpse_list_value(world, corpse["corpse_id"], "mourned_by_agent_ids", actor.agent_id)
        text = _mourn_text(session, actor, dead_agent, corpse)
        event = create_event(
            session,
            world=world,
            event_type="corpse_mourn",
            actor_agent_id=actor.agent_id,
            target_agent_id=dead_agent.agent_id if dead_agent else None,
            location_id=location_id,
            viewer_text=text,
            importance=85 if grief >= 70 else 65,
            color_class="warning",
            payload={"corpse_id": corpse.get("corpse_id"), "grief_score": grief},
            state_delta=state_delta,
        )
        return [event.event_id]
    if tool_name == "report_visible_corpse":
        _mark_corpse_list_value(world, corpse["corpse_id"], "reported_by_agent_ids", actor.agent_id)
        state_delta[actor.agent_id] = apply_delta(actor.dynamic_state, stress=3, mood=-1)
        identity = _corpse_identity_label(session, actor, dead_agent)
        event = create_event(
            session,
            world=world,
            event_type="corpse_report",
            actor_agent_id=actor.agent_id,
            target_agent_id=dead_agent.agent_id if dead_agent else None,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 报告了 {location_public_name(session, location_id)} 的尸体：{identity}，要求社区注意腐烂、疾病和死亡原因。",
            importance=80,
            color_class="warning",
            payload={"corpse_id": corpse.get("corpse_id"), "reported": True},
            state_delta=state_delta,
        )
        return [event.event_id]
    if tool_name == "bury_visible_corpse":
        return [_bury_corpse(session, world, actor, dead_agent, corpse, location_id, state_delta).event_id]
    if tool_name == "avoid_corpse_area":
        return [_avoid_corpse_area(session, world, actor, corpse, location_id, state_delta).event_id]
    event = create_event(session, world=world, event_type="system", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 面对尸体僵住了。", importance=20)
    return [event.event_id]


def _bury_corpse(session: Session, world: World, actor: Agent, dead_agent: Agent | None, corpse: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> Event:
    records = _records(world)
    record = _find_record(records, corpse["corpse_id"])
    if record:
        record["buried"] = True
        record["buried_at_world_time"] = world.current_world_time_minutes
        record["buried_by_agent_id"] = actor.agent_id
        _save_records(world, records)
    grief = _grief_score(session, actor, dead_agent)
    delta = {
        "energy": -24,
        "satiety": -4,
        "hydration": -6,
        "hygiene": -24,
        "stress": 14,
        "mood": -10,
        "fun": -4,
    }
    if grief >= 70:
        delta.update({"stress": 24, "mood": -20, "energy": -28})
    state_delta[actor.agent_id] = apply_delta(actor.dynamic_state, **delta)
    text = _bury_text(session, actor, dead_agent, corpse, grief)
    return create_event(
        session,
        world=world,
        event_type="corpse_buried",
        actor_agent_id=actor.agent_id,
        target_agent_id=dead_agent.agent_id if dead_agent else None,
        location_id=location_id,
        viewer_text=text,
        importance=95,
        color_class="danger",
        payload={
            "corpse_id": corpse.get("corpse_id"),
            "negative_only": True,
            "no_money_reward": True,
            "no_reputation_reward": True,
            "note": "埋葬尸体只有硬规则负收益；agent 愿不愿意承担由其自行决定。",
        },
        state_delta=state_delta,
    )


def _avoid_corpse_area(session: Session, world: World, actor: Agent, corpse: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> Event:
    before = location_id
    after = before
    if actor.location:
        neighbors = adjacent_location_ids(session, actor.location.location)
        if neighbors:
            after = neighbors[0]
            destination = session.get(Location, after)
            actor.location.location_id = after
            if destination:
                actor.location.location = destination
            actor.location.arrived_at_world_time = world.current_world_time_minutes
    state_delta[actor.agent_id] = apply_delta(actor.dynamic_state, energy=-2, stress=3, mood=-1)
    if after != before:
        text = f"{actor.chosen_name} 受不了尸体的气味和压迫感，离开 {location_public_name(session, before)}，走向 {location_public_name(session, after)}。"
    else:
        text = f"{actor.chosen_name} 想避开尸体，却一时找不到合适的去处，只能和那股气味保持距离。"
    return create_event(
        session,
        world=world,
        event_type="corpse_avoid",
        actor_agent_id=actor.agent_id,
        location_id=after,
        viewer_text=text,
        importance=55,
        color_class="warning",
        payload={"corpse_id": corpse.get("corpse_id"), "from_location_id": before, "to_location_id": after},
        state_delta=state_delta,
    )


def validate_corpse_tool(session: Session, world: World | None, actor: Agent, tool_name: str, params: dict[str, Any]) -> tuple[bool, str, str]:
    if tool_name not in CORPSE_TOOL_NAMES:
        return True, "", ""
    if world is None:
        return False, "no_world", "世界不存在，无法确认尸体。"
    corpse_ref = str(params.get("corpse_ref") or "") or None
    corpse = resolve_visible_corpse(session, world, actor, corpse_ref)
    if not corpse:
        return False, "corpse_not_visible", "当前位置没有可见尸体；只有同地点可见的尸体才能被查看、哀悼、报告或埋葬。"
    return True, "", ""


def _records(world: World) -> list[dict[str, Any]]:
    settings = world.settings_json or {}
    records = settings.get(CORPSE_RECORDS_KEY) or []
    return [dict(record) for record in records if isinstance(record, dict)]


def _save_records(world: World, records: list[dict[str, Any]]) -> None:
    settings = dict(world.settings_json or {})
    settings[CORPSE_RECORDS_KEY] = records
    world.settings_json = settings


def _find_record(records: list[dict[str, Any]], corpse_id: str) -> dict[str, Any] | None:
    return next((record for record in records if record.get("corpse_id") == corpse_id), None)


def _mark_corpse_list_value(world: World, corpse_id: str, key: str, value: str) -> None:
    records = _records(world)
    record = _find_record(records, corpse_id)
    if not record:
        return
    values = list(record.get(key) or [])
    if value not in values:
        values.append(value)
    record[key] = values[-200:]
    _save_records(world, records)


def _with_stage(record: dict[str, Any], now: int) -> dict[str, Any]:
    enriched = dict(record)
    age_minutes = max(0, now - int(enriched.get("death_world_time") or now))
    stage, label, stench, disease = _corpse_stage(age_minutes)
    enriched.update(
        {
            "age_minutes": age_minutes,
            "stage": stage,
            "stage_label": label,
            "stench_level": stench,
            "disease_risk": disease,
            "disease_risk_label": _disease_label(disease),
        }
    )
    return enriched


def _corpse_stage(age_minutes: int) -> tuple[str, str, int, float]:
    if age_minutes < 6 * 60:
        return "fresh", "刚死亡不久，身体还没有明显腐烂", 0, 0.00
    if age_minutes < 24 * 60:
        return "cold", "身体已经冰冷，死亡感很明显", 1, 0.01
    if age_minutes < 48 * 60:
        return "odor", "开始出现异味，空气让人不安", 2, 0.03
    if age_minutes < 4 * 1440:
        return "rot", "明显腐烂，臭味让人反胃", 3, 0.06
    if age_minutes < 8 * 1440:
        return "heavy_rot", "严重腐烂，靠近会伤害身心", 4, 0.10
    return "remains", "腐败遗骸，长期污染附近环境", 5, 0.14


def _disease_label(risk: float) -> str:
    if risk <= 0:
        return "无明显"
    if risk < 0.03:
        return "很低"
    if risk < 0.07:
        return "中等"
    if risk < 0.12:
        return "偏高"
    return "高"


def _corpse_ref(index: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < len(letters):
        return f"尸体{letters[index]}"
    return f"尸体{index + 1}"


def _known_name(session: Session, observer: Agent, target: Agent | None) -> str | None:
    if not target:
        return None
    if target.agent_id == observer.agent_id:
        return target.chosen_name
    knowledge = session.execute(
        select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == observer.agent_id,
            IdentityKnowledge.target_agent_id == target.agent_id,
            IdentityKnowledge.name_known.is_(True),
        )
    ).scalar_one_or_none()
    if knowledge and knowledge.known_name:
        return knowledge.known_name
    return None


def _relationship(session: Session, observer: Agent, target: Agent | None) -> Relationship | None:
    if not target:
        return None
    return session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == observer.agent_id,
            Relationship.target_agent_id == target.agent_id,
        )
    ).scalar_one_or_none()


def _grief_score(session: Session, observer: Agent, target: Agent | None) -> int:
    if not target or target.agent_id == observer.agent_id:
        return 0
    score = 0
    rel = _relationship(session, observer, target)
    if rel:
        score = max(score, int(rel.affection * 0.65 + rel.trust * 0.25 + rel.familiarity * 0.35))
        if rel.relationship_label in {"亲近", "朋友"}:
            score += 10
    family = observer.family_json or {}
    if family.get("partner_agent_id") == target.agent_id:
        score = max(score, 95)
    if target.agent_id in (family.get("children_agent_ids") or []) or target.agent_id in (family.get("guardian_agent_ids") or []):
        score = max(score, 90)
    return int(clamp(score, 0, 100))


def _relationship_corpse_note(session: Session, observer: Agent, target: Agent | None) -> str:
    if not target:
        return ""
    grief = _grief_score(session, observer, target)
    known_name = _known_name(session, observer, target)
    label = known_name or f"这个{target.appearance_short or '外貌熟悉的人'}"
    if grief >= 90:
        return f"强烈冲击：{label}曾经和你非常亲近，分明曾经那么亲昵/重要，可现在再也不会回应你了。"
    if grief >= 70:
        return f"明显冲击：你对{label}有很深的好感或信任，看到这具尸体会让你难以平静。"
    if grief >= 40:
        return f"你对{label}并不陌生，看到尸体会带来悲伤和不安。"
    return ""


def _corpse_identity_label(session: Session, observer: Agent, target: Agent | None) -> str:
    if not target:
        return "身份不明的尸体"
    known = _known_name(session, observer, target)
    if known:
        return known
    return f"那个{target.appearance_short or '外貌可辨'}的人"


def _first_sight_text(session: Session, observer: Agent, target: Agent | None, corpse: dict[str, Any]) -> str:
    identity = _corpse_identity_label(session, observer, target)
    grief = _grief_score(session, observer, target)
    location_name = location_public_name(session, observer.location.location_id if observer.location else None)
    if grief >= 90:
        return f"{observer.chosen_name} 在 {location_name} 看见了{identity}的尸体，整个人像被钉在原地：分明曾经那么亲昵，可是现在再也见不到对方回应了。"
    if grief >= 70:
        return f"{observer.chosen_name} 在 {location_name} 认出了{identity}的尸体，胸口猛地发紧，眼前的死亡不再只是陌生事件。"
    return f"{observer.chosen_name} 在 {location_name} 看见了一具尸体：{identity}，{corpse.get('stage_label')}。"


def _trauma_memory_text(session: Session, observer: Agent, target: Agent, corpse: dict[str, Any]) -> str:
    identity = _corpse_identity_label(session, observer, target)
    if _grief_score(session, observer, target) >= 90:
        return f"我看见了{identity}的尸体。分明曾经那么亲昵、那么重要，可现在再也见不到回应了。这不是普通记忆，不能在梦里被轻易抹掉。"
    return f"我看见了{identity}的尸体。这件事让我痛苦、不安，应该被当作重要记忆保留。"


def _corpse_first_sight_delta(session: Session, observer: Agent, target: Agent | None) -> dict[str, float]:
    grief = _grief_score(session, observer, target)
    if grief >= 90:
        return {"stress": 26, "mood": -24, "social": -5, "energy": -6}
    if grief >= 70:
        return {"stress": 18, "mood": -14, "energy": -4}
    return {"stress": 8, "mood": -5, "energy": -1}


def _inspect_text(session: Session, actor: Agent, target: Agent | None, corpse: dict[str, Any]) -> str:
    identity = _corpse_identity_label(session, actor, target)
    grief = _grief_score(session, actor, target)
    if grief >= 90:
        return f"{actor.chosen_name} 强忍着靠近查看{identity}的尸体。越是确认，越觉得那段亲近关系被死亡硬生生截断了。"
    stench = int(corpse.get("stench_level") or 0)
    smell = "空气里还没有明显腐败气味" if stench <= 0 else "气味已经让人本能地想退开" if stench >= 3 else "空气里开始有不舒服的异味"
    return f"{actor.chosen_name} 靠近查看了{identity}的尸体：{corpse.get('stage_label')}，{smell}。"


def _mourn_text(session: Session, actor: Agent, target: Agent | None, corpse: dict[str, Any]) -> str:
    identity = _corpse_identity_label(session, actor, target)
    grief = _grief_score(session, actor, target)
    if grief >= 90:
        return f"{actor.chosen_name} 守在{identity}的尸体旁，声音几乎发不出来：分明曾经那么亲昵，可是以后再也见不到对方醒来、说话、靠近了。"
    if grief >= 70:
        return f"{actor.chosen_name} 在{identity}的尸体旁停留哀悼，悲伤和不真实感压得人喘不过气。"
    return f"{actor.chosen_name} 在尸体旁低头默哀了一会儿。"


def _bury_text(session: Session, actor: Agent, target: Agent | None, corpse: dict[str, Any], grief: int) -> str:
    identity = _corpse_identity_label(session, actor, target)
    if grief >= 90:
        return f"{actor.chosen_name} 亲手埋葬了{identity}。泥土盖下去时，那个曾经亲昵又鲜活的人彻底沉默了；这件事没有任何奖励，只有疲惫、污秽和更深的悲伤。"
    if grief >= 70:
        return f"{actor.chosen_name} 埋葬了{identity}。这是一件沉重的苦差，没有钱、没有快乐，只有体力消耗和心里的压迫感。"
    return f"{actor.chosen_name} 花很久处理并埋葬了一具尸体。这个举动没有带来任何报酬或正反馈，只留下疲惫、污秽和不安。"


def _corpse_disease_hit(world: World, agent: Agent, stench: int, exposure_count: int) -> bool:
    if stench < 2:
        return False
    chance = min(0.30, 0.025 * stench + 0.01 * max(0, exposure_count - 1))
    if agent.dynamic_state and agent.dynamic_state.hygiene < 25:
        chance += 0.04
    rng = random.Random(f"corpse-disease:{world.seed}:{world.current_world_time_minutes}:{agent.agent_id}:{stench}:{exposure_count}")
    return rng.random() < chance
