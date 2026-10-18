"""Agent event access is based on recipients at event time, not current location."""
from sqlalchemy import select
from app.core.models import Agent, AgentLocation, Event, Memory, World


def isolated_world(world: World) -> bool:
    return bool((world.settings_json or {}).get("werewolf_mode_enabled"))


def event_recipients(session, world, *, event_type, visibility_scope, actor_agent_id, location_id, payload):
    if visibility_scope in {"observer", "viewer_only"} or payload.get("agent_facing_locked"):
        return []
    if event_type.startswith("werewolf_wolf_") or event_type == "werewolf_kill_nomination":
        roles = ((world.settings_json or {}).get("werewolf_state") or {}).get("roles") or {}
        return sorted(agent_id for agent_id, role in roles.items() if role == "werewolf")
    if event_type in {"private_dialogue", "private_talk_closed"}:
        return list(payload.get("private_audience_ids") or [])
    if visibility_scope == "private":
        return [actor_agent_id] if actor_agent_id else []
    recipients = {actor_agent_id} if actor_agent_id else set()
    recipients.update(payload.get("heard_by_agent_ids") or [])
    public_announcement = event_type in {"werewolf_notice_board", "werewolf_phase", "werewolf_setup", "werewolf_game_over"}
    if location_id or public_announcement:
        stmt = select(Agent.agent_id, Agent.desires_json).where(Agent.world_id == world.world_id, Agent.lifecycle_state != "dead")
        if not public_announcement:
            stmt = stmt.join(AgentLocation).where(AgentLocation.location_id == location_id)
        for agent_id, desires in session.execute(stmt):
            sleeping = int((desires or {}).get("sleep_until_world_time") or 0) > world.current_world_time_minutes
            if public_announcement or not sleeping:
                recipients.add(agent_id)
    return sorted(recipients)


def agent_can_access_event(session, world: World, agent_id: str, event: Event) -> bool:
    if event.world_id != world.world_id:
        return False
    if event.event_type in {"private_dialogue", "private_talk_closed"}:
        return agent_id in ((event.payload or {}).get("private_audience_ids") or [])
    if not isolated_world(world):
        return True
    payload = event.payload or {}
    if event.visibility_scope in {"observer", "viewer_only"} or payload.get("agent_facing_locked"):
        return False
    # Private results belong to the actor, not to a target being investigated.
    if event.visibility_scope == "private":
        if event.event_type.startswith("werewolf_wolf_") or event.event_type == "werewolf_kill_nomination":
            roles = ((world.settings_json or {}).get("werewolf_state") or {}).get("roles") or {}
            return roles.get(agent_id) == "werewolf"
        return event.actor_agent_id == agent_id
    if "perceived_by_agent_ids" in payload:
        return agent_id in payload["perceived_by_agent_ids"]
    # Legacy saves: a stored memory or explicit listener is evidence of access.
    # Being in the same room now is not evidence of witnessing its past events.
    if agent_id == event.actor_agent_id or agent_id in (payload.get("heard_by_agent_ids") or []):
        return True
    return session.execute(select(Memory.memory_id).where(
        Memory.agent_id == agent_id, Memory.source_event_id == event.event_id,
    ).limit(1)).scalar_one_or_none() is not None
