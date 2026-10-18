"""Agent event access is based on recipients at event time, not current location."""
from sqlalchemy import select
from app.core.models import Agent, AgentLocation, Event, Location, Memory, World


MOVEMENT_EVENT_TYPES = {"move", "return_home", "door_opened", "room_entered_for_inspection"}


def movement_path(event_type, state_delta, payload):
    if event_type not in MOVEMENT_EVENT_TYPES:
        return []
    change = (state_delta or {}).get("location") or {}
    before, after = change.get("before"), change.get("after")
    if not before or not after or before == after:
        return []
    return list(dict.fromkeys([before, *(payload.get("path") or []), after]))


def isolated_world(world: World) -> bool:
    return bool((world.settings_json or {}).get("werewolf_mode_enabled"))


def event_recipients(session, world, *, event_type, visibility_scope, actor_agent_id, location_id, payload, state_delta=None):
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
    # "Visible" people may include sleeping residents; a listener list alone
    # must not turn a sleeping or unconscious resident into a witness.
    explicit_listeners = set(payload.get("heard_by_agent_ids") or [])
    locations = {location_id} if location_id else set()
    path = movement_path(event_type, state_delta, payload)
    locations.update(path)
    if event_type in {"knock_room", "room_lock_changed"}:
        room = session.get(Location, payload.get("destination_location_id"))
        if room and room.world_id == world.world_id:
            locations.add(room.location_id)
            if event_type == "room_lock_changed":
                locations.update(room.neighbors_json or [])
    public_announcement = event_type in {"werewolf_notice_board", "werewolf_phase", "werewolf_setup", "werewolf_game_over"}
    if locations or explicit_listeners or public_announcement:
        stmt = select(Agent.agent_id, Agent.desires_json, AgentLocation.location_id).join(AgentLocation).where(
            Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
        if not public_announcement:
            stmt = stmt.where((AgentLocation.location_id.in_(locations)) | (Agent.agent_id.in_(explicit_listeners)))
        observed_from = {}
        for agent_id, desires, observed_location in session.execute(stmt):
            sleeping = int((desires or {}).get("sleep_until_world_time") or 0) > world.current_world_time_minutes
            unconscious = int((desires or {}).get("unconscious_until_world_time") or 0) > world.current_world_time_minutes
            if public_announcement or not (sleeping or unconscious):
                recipients.add(agent_id)
                if path:
                    observed_from[agent_id] = observed_location
        if path:
            payload["movement_observers"] = observed_from
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
