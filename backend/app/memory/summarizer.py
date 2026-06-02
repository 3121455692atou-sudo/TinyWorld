from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Memory
from app.memory.memory_service import add_memory


def summarize_if_needed(session: Session, agent_id: str, world_time: int) -> None:
    memories = list(
        session.execute(
            select(Memory).where(
                Memory.agent_id == agent_id,
                Memory.memory_type == "long",
                Memory.archived.is_(False),
            )
        ).scalars()
    )
    if len(memories) <= 120:
        return
    chunk = memories[:80]
    summary = "；".join(memory.content[:60] for memory in chunk)
    add_memory(
        session,
        agent_id=agent_id,
        content=f"长期记忆摘要: {summary}",
        world_time=world_time,
        memory_type="summary",
        importance=70,
    )
    for memory in chunk:
        memory.archived = True

