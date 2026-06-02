from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.core.models import Agent, Conversation, Event, Memory, NarratorRun, Relationship, World
from app.export.html_exporter import markdown_to_simple_html
from app.export.markdown_exporter import build_story_markdown


EXPORT_DIR = DATA_DIR / "exports"


def _json_default(obj: Any) -> str:
    return str(obj)


def _row_dict(obj: Any) -> dict[str, Any]:
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def export_world_zip(session: Session, world_id: str) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    world = session.get(World, world_id)
    if not world:
        raise ValueError("world not found")
    story_md = build_story_markdown(session, world)
    story_html = markdown_to_simple_html(story_md, world.name)
    events = list(session.execute(select(Event).where(Event.world_id == world_id).order_by(Event.event_id)).scalars())
    agents = list(session.execute(select(Agent).where(Agent.world_id == world_id)).scalars())
    conversations = list(session.execute(select(Conversation).join(Event, Conversation.event_id == Event.event_id).where(Event.world_id == world_id).order_by(Conversation.utterance_id)).scalars())
    relationships = list(session.execute(select(Relationship)).scalars())
    memories = list(session.execute(select(Memory).join(Agent, Agent.agent_id == Memory.agent_id).where(Agent.world_id == world_id)).scalars())
    narrations = list(session.execute(select(NarratorRun).where(NarratorRun.world_id == world_id)).scalars())
    metrics = _metrics_summary(agents, events)

    zip_path = EXPORT_DIR / f"{world_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("story.md", story_md)
        zf.writestr("story.html", story_html)
        zf.writestr("events.jsonl", "\n".join(json.dumps(_row_dict(event), ensure_ascii=False, default=_json_default) for event in events) + "\n")
        zf.writestr("world_state_final.json", json.dumps(_row_dict(world), ensure_ascii=False, indent=2, default=_json_default))
        zf.writestr("agents.json", json.dumps([_row_dict(agent) for agent in agents], ensure_ascii=False, indent=2, default=_json_default))
        zf.writestr("conversations.jsonl", "\n".join(json.dumps(_row_dict(item), ensure_ascii=False, default=_json_default) for item in conversations) + "\n")
        diary_lines = []
        for memory in memories:
            if memory.memory_type == "diary":
                diary_lines.append(memory.content)
        zf.writestr("diaries.md", "\n\n---\n\n".join(diary_lines) + "\n")
        zf.writestr("relationships.json", json.dumps([_row_dict(rel) for rel in relationships], ensure_ascii=False, indent=2, default=_json_default))
        zf.writestr("narrator.md", "\n\n".join(f"## {run.summary_title}\n\n{run.narration}" for run in narrations if run.narration) + "\n")
        zf.writestr("metrics_summary.json", json.dumps(metrics, ensure_ascii=False, indent=2, default=_json_default))
    return zip_path


def _metrics_summary(agents: list[Agent], events: list[Event]) -> dict[str, Any]:
    alive = [agent for agent in agents if agent.lifecycle_state in {"alive", "critical"}]
    deaths = [event for event in events if event.event_type == "death"]
    births = [event for event in events if event.event_type == "birth"]
    work_events = [event for event in events if event.event_type in {"work", "work_break"}]
    economy_events = [event for event in events if event.event_type in {"economy", "aid", "supply"}]
    return {
        "population": len(agents),
        "alive": len(alive),
        "births": len(births),
        "deaths": len(deaths),
        "work_events": len(work_events),
        "economy_events": len(economy_events),
        "tool_failed_events": len([event for event in events if event.event_type == "tool_failed"]),
    }
