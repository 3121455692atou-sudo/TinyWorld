from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import current_day, format_world_time
from app.core.models import Agent, Event, Memory, Relationship, World
from app.world.visibility import location_public_name


def build_story_markdown(session: Session, world: World) -> str:
    agents = list(session.execute(select(Agent).where(Agent.world_id == world.world_id).order_by(Agent.agent_id)).scalars())
    events = list(session.execute(select(Event).where(Event.world_id == world.world_id).order_by(Event.event_id)).scalars())
    by_day: dict[int, list[Event]] = defaultdict(list)
    for event in events:
        by_day[current_day(event.world_time)].append(event)

    lines = [
        f"# {world.name}",
        "",
        "## 世界设置摘要",
        f"- 状态: {world.status}",
        f"- 种子: {world.seed}",
        f"- 最终时间: {format_world_time(world.current_world_time_minutes)}",
        "",
        "## 角色表",
    ]
    for agent in agents:
        location = location_public_name(session, agent.location.location_id if agent.location else None)
        lines.append(f"- {agent.chosen_name}: {agent.gender_identity or '未知'}，{agent.appearance_short or '外貌未知'}。状态: {agent.lifecycle_state}，最终地点: {location}。")

    lines.extend(["", "## 时间线概览"])
    for event in events:
        if event.importance >= 45 or event.event_type in {"dialogue", "death", "narration", "introduce_self"}:
            lines.append(f"- {format_world_time(event.world_time)} [{event.event_id}] {event.viewer_text}")

    for day, day_events in sorted(by_day.items()):
        lines.extend(["", f"## 第{day}天"])
        lines.append("### 事件摘要")
        for event in day_events:
            if event.importance >= 15 or event.event_type == "death":
                lines.append(f"- {format_world_time(event.world_time)} [{event.event_id}] {event.viewer_text}")
        lines.append("### 关键对话")
        for event in day_events:
            if event.event_type == "dialogue":
                lines.append(f"- [{event.event_id}] {event.viewer_text}")
        lines.append("### 解说")
        for event in day_events:
            if event.event_type == "narration":
                lines.append(f"- [{event.event_id}] {event.viewer_text}")
        lines.append("### 状态变化")
        for event in day_events:
            if event.state_delta:
                lines.append(f"- [{event.event_id}] {event.state_delta}")
        lines.append("### 日记摘录")
        for memory in session.execute(select(Memory).where(Memory.memory_type == "diary")).scalars():
            if current_day(memory.created_world_time) == day:
                author = session.get(Agent, memory.agent_id)
                lines.append(f"- {author.chosen_name if author else memory.agent_id}: {memory.content[:240]}")

    lines.extend(["", "## 死亡记录"])
    deaths = [agent for agent in agents if agent.lifecycle_state == "dead"]
    if deaths:
        for agent in deaths:
            lines.append(f"- {agent.chosen_name}: {format_world_time(agent.death_at_world_time or 0)}，原因: {agent.death_cause}")
    else:
        lines.append("- 暂无死亡。")

    lines.extend(["", "## 最终关系图"])
    relationships = list(session.execute(select(Relationship)).scalars())
    for rel in relationships:
        observer = session.get(Agent, rel.observer_agent_id)
        target = session.get(Agent, rel.target_agent_id)
        if observer and target and observer.world_id == world.world_id:
            lines.append(f"- {observer.chosen_name} -> {target.chosen_name}: {rel.relationship_label}，熟悉{rel.familiarity:.0f}，信任{rel.trust:.0f}，好感{rel.affection:.0f}，恐惧{rel.fear:.0f}，冲突{rel.conflict:.0f}")

    lines.extend(["", "## 附录: 全量事件索引"])
    for event in events:
        lines.append(f"- [{event.event_id}] {format_world_time(event.world_time)} {event.event_type}: {event.viewer_text}")
    return "\n".join(lines) + "\n"

