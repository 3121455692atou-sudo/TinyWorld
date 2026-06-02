from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.models import Agent
from app.memory.memory_service import add_memory


def write_diary_entry(session: Session, agent: Agent, world_time: int, title: str | None, content: str | None) -> None:
    title = title or "今天的记录"
    content = content or f"{agent.chosen_name}写下: 今天的世界仍在继续，我需要记得照顾身体，也要谨慎认识别人。"
    add_memory(
        session,
        agent_id=agent.agent_id,
        content=f"# {title}\n\n{content}",
        world_time=world_time,
        memory_type="diary",
        importance=45,
        visibility="private",
    )

