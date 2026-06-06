from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.models import Agent
from app.world.visibility import location_public_name


def agent_name(session: Session, agent_id: str | None) -> str:
    if not agent_id:
        return "系统"
    agent = session.get(Agent, agent_id)
    return agent.chosen_name if agent and agent.chosen_name else "未命名者"


def render_move(session: Session, actor_id: str, from_location_id: str, to_location_id: str) -> str:
    return f"{agent_name(session, actor_id)} 从 {location_public_name(session, from_location_id)} 走向了 {location_public_name(session, to_location_id)}。"


def render_say(actor: str, target: str, speech: str) -> str:
    # The actual line must live in event.payload.dialogue_lines so the frontend can render
    # it as an avatar bubble. Narration should never quote role speech directly.
    return f"{actor}向{target or '附近的人'}开口说话。"


def render_death(session: Session, actor_id: str, location_id: str | None, cause: str) -> str:
    return f"【死亡】{agent_name(session, actor_id)} 在 {location_public_name(session, location_id)} 死去。原因: {cause}。"
