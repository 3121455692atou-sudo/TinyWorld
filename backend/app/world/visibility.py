from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import format_world_time
from app.core.models import Agent, AgentLocation, IdentityKnowledge, Location


@dataclass(slots=True)
class VisiblePerson:
    visible_ref: str
    target_agent_id: str
    appearance: str
    known_name: str
    known_gender: str
    obvious_state: str
    previous_seen_note: str | None = None


def _ref_name(index: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < len(letters):
        return f"附近人物{letters[index]}"
    return f"附近人物{index + 1}"


def same_location_agent_ids(session: Session, agent: Agent) -> list[str]:
    if not agent.location:
        return []
    rows = session.execute(
        select(AgentLocation.agent_id)
        .join(Agent, Agent.agent_id == AgentLocation.agent_id)
        .where(
            AgentLocation.location_id == agent.location.location_id,
            Agent.agent_id != agent.agent_id,
            Agent.lifecycle_state.in_(["alive", "critical"]),
        )
    ).scalars()
    return list(rows)


def visible_agents(session: Session, agent: Agent) -> list[Agent]:
    ids = same_location_agent_ids(session, agent)
    if not ids:
        return []
    return list(session.execute(select(Agent).where(Agent.agent_id.in_(ids))).scalars())


def adjacent_location_ids(session: Session, location: Location | None) -> list[str]:
    if not location:
        return []
    ids = list(location.neighbors_json or [])
    inbound = session.execute(select(Location).where(Location.world_id == location.world_id)).scalars()
    for candidate in inbound:
        if candidate.location_id != location.location_id and location.location_id in (candidate.neighbors_json or []):
            ids.append(candidate.location_id)
    return list(dict.fromkeys(ids))


def get_or_create_knowledge(session: Session, observer_id: str, target_id: str) -> IdentityKnowledge:
    knowledge = session.execute(
        select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == observer_id,
            IdentityKnowledge.target_agent_id == target_id,
        )
    ).scalar_one_or_none()
    if knowledge:
        return knowledge
    knowledge = IdentityKnowledge(observer_agent_id=observer_id, target_agent_id=target_id)
    session.add(knowledge)
    session.flush()
    return knowledge


def mark_visual_known(session: Session, observer: Agent, target: Agent, world_time: int) -> IdentityKnowledge:
    knowledge = get_or_create_knowledge(session, observer.agent_id, target.agent_id)
    previous = knowledge.visual_known
    knowledge.visual_known = True
    knowledge.appearance_snapshot = target.appearance_short or "外貌仍有些模糊的人"
    knowledge.appearance_confidence = max(knowledge.appearance_confidence, 80)
    if knowledge.first_seen_at is None:
        knowledge.first_seen_at = world_time
    knowledge.last_seen_at = world_time
    if not previous:
        knowledge.notes = (knowledge.notes or "") + "第一次见过这个人的外貌。"
    return knowledge


def mark_name_known(
    session: Session,
    observer_id: str,
    target: Agent,
    world_time: int,
    via: str,
    gender_revealed: bool = False,
) -> IdentityKnowledge:
    knowledge = get_or_create_knowledge(session, observer_id, target.agent_id)
    knowledge.name_known = True
    knowledge.known_name = target.chosen_name
    knowledge.name_confidence = 95
    knowledge.name_learned_via = via
    knowledge.first_name_learned_at = knowledge.first_name_learned_at or world_time
    if gender_revealed:
        mark_gender_known(session, observer_id, target, world_time, "self_intro")
    return knowledge


def mark_gender_known(session: Session, observer_id: str, target: Agent, world_time: int, via: str = "observed") -> IdentityKnowledge:
    knowledge = get_or_create_knowledge(session, observer_id, target.agent_id)
    knowledge.gender_known = True
    knowledge.known_gender_text = target.gender_custom_text or target.gender_identity or target.gender_expression or "未知"
    knowledge.last_seen_at = world_time
    if knowledge.first_seen_at is None:
        knowledge.first_seen_at = world_time
    note = f"通过{via}确认了性别/性别表达。"
    if note not in (knowledge.notes or ""):
        knowledge.notes = (knowledge.notes or "") + note
    return knowledge


def build_visible_people(session: Session, observer: Agent, world_time: int, *, persist: bool = True) -> list[VisiblePerson]:
    people: list[VisiblePerson] = []
    for idx, target in enumerate(sorted(visible_agents(session, observer), key=lambda a: a.agent_id)):
        if persist:
            knowledge = mark_visual_known(session, observer, target, world_time)
        else:
            knowledge = session.execute(
                select(IdentityKnowledge).where(
                    IdentityKnowledge.observer_agent_id == observer.agent_id,
                    IdentityKnowledge.target_agent_id == target.agent_id,
                )
            ).scalar_one_or_none()
        previous_seen_note = None
        if knowledge and knowledge.first_seen_at is not None and knowledge.first_seen_at < world_time and not knowledge.name_known:
            previous_seen_note = f"你似乎以前见过这个人: 记忆中的外貌是{knowledge.appearance_snapshot}。"
        state = target.dynamic_state
        obvious = []
        if state:
            if state.health < 40:
                obvious.append("看起来很虚弱")
            if state.energy < 20:
                obvious.append("明显疲惫")
            if state.stress > 80:
                obvious.append("神情紧张")
        try:
            sleep_until = int((target.desires_json or {}).get("sleep_until_world_time") or 0)
        except (TypeError, ValueError):
            sleep_until = 0
        if sleep_until > world_time:
            obvious.append(f"正在睡觉，预计{format_world_time(sleep_until)}醒来；如果确实要交流，应先叫醒，不要直接提问")
        people.append(
            VisiblePerson(
                visible_ref=_ref_name(idx),
                target_agent_id=target.agent_id,
                appearance=target.appearance_short or "外貌尚未清晰",
                known_name=knowledge.known_name if knowledge and knowledge.name_known else "未知",
                known_gender=knowledge.known_gender_text if knowledge and knowledge.gender_known else "未知",
                obvious_state="、".join(obvious) if obvious else "没有明显异常",
                previous_seen_note=previous_seen_note,
            )
        )
    return people


def resolve_visible_ref(session: Session, observer: Agent, visible_ref: str, world_time: int, *, persist: bool = True) -> Agent | None:
    for person in build_visible_people(session, observer, world_time, persist=persist):
        if person.visible_ref == visible_ref:
            return session.get(Agent, person.target_agent_id)
    return None


def location_public_name(session: Session, location_id: str | None) -> str:
    if not location_id:
        return "未知地点"
    location = session.get(Location, location_id)
    return location.public_name if location else "未知地点"
