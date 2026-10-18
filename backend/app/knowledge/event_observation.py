"""Render recorded observations, including spoken words and their actual time/place."""
from sqlalchemy import select

from app.core.clock import format_world_time
from app.core.models import Agent, IdentityKnowledge, Location, World
from app.knowledge.event_access import agent_can_access_event, movement_path


def observation_text(session, observer, event, *, include_time=True):
    world = session.get(World, observer.world_id)
    if not world or not agent_can_access_event(session, world, observer.agent_id, event):
        return ""

    def person(agent_id):
        target = session.get(Agent, agent_id) if agent_id else None
        if not target:
            return "某位居民"
        if agent_id == observer.agent_id:
            return target.chosen_name or "你"
        known = session.scalar(select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == observer.agent_id,
            IdentityKnowledge.target_agent_id == agent_id,
            IdentityKnowledge.name_known.is_(True)))
        return (known.known_name or target.chosen_name) if known else f"那个{target.appearance_short or '外貌可辨'}的人"

    def place(location_id):
        location = session.get(Location, location_id) if location_id else None
        return location.public_name if location and location.world_id == world.world_id else ""

    payload = event.payload or {}
    text = event.agent_visible_text or event.viewer_text or ""
    for agent_id in {event.actor_agent_id, event.target_agent_id} - {None, observer.agent_id}:
        target = session.get(Agent, agent_id)
        if target and target.chosen_name:
            text = text.replace(target.chosen_name, person(agent_id))
    path = movement_path(event.event_type, event.state_delta, payload)
    observed_location = (payload.get("movement_observers") or {}).get(observer.agent_id)
    if path and observer.agent_id != event.actor_agent_id and observed_location in path and len(path) > 2:
        # A return-home route is not omniscient knowledge for someone who only
        # witnessed one part of it. Describe the adjacent segment they saw.
        index = path.index(observed_location)
        if index == 0:
            text = f"{person(event.actor_agent_id)}离开{place(path[0])}，向{place(path[1])}走去。"
        elif index == len(path) - 1:
            text = f"{person(event.actor_agent_id)}从{place(path[-2])}进入{place(path[-1])}。"
        else:
            text = f"{person(event.actor_agent_id)}从{place(path[index - 1])}来到{place(path[index])}，继续向{place(path[index + 1])}走去。"
    elif path and event.event_type == "move":
        text = f"{person(event.actor_agent_id)}从{place(path[0])}离开，进入{place(path[-1])}。"

    lines = payload.get("dialogue_lines") or []
    if not lines and payload.get("speech"):
        lines = [{"speaker_agent_id": event.actor_agent_id, "target_agent_id": event.target_agent_id,
                  "text": payload["speech"]}]
    parts = [text] if text else []
    for line in lines:
        if not isinstance(line, dict) or not (line.get("text") or line.get("speech")):
            continue
        speaker = person(line.get("speaker_agent_id") or event.actor_agent_id)
        target_id = line.get("target_agent_id") or event.target_agent_id
        address = f"对{person(target_id)}" if target_id else ""
        # Preserve the actual utterance. Labels are evidence; claims inside a
        # quote remain claims and are never rewritten into executed actions.
        parts.append(f"{speaker}{address}说：『{line.get('text') or line.get('speech')}』")
    where = place(observed_location or event.location_id)
    context = [format_world_time(event.world_time)] if include_time else []
    if where:
        context.append(where)
    prefix = f"[{' · '.join(context)}] " if context else ""
    return prefix + "；".join(parts)
