"""Consent-bound, local private dialogue. Invitation text remains public."""
from app.core.models import Agent, Conversation
from app.events.event_store import create_event

PRIVATE_TALK_KEY = "private_talk"


def private_talk_peer(session, world, actor):
    record = (actor.family_json or {}).get(PRIVATE_TALK_KEY) or {}
    peer = session.get(Agent, record.get("peer_id")) if record.get("peer_id") else None
    other = ((peer.family_json or {}).get(PRIVATE_TALK_KEY) or {}) if peer else {}
    if (not peer or peer.world_id != world.world_id or peer.lifecycle_state not in {"alive", "critical"}
        or actor.lifecycle_state not in {"alive", "critical"}
        or not actor.location or not peer.location or actor.location.location_id != peer.location.location_id
        or record.get("location_id") != actor.location.location_id
        or int(record.get("expires_at") or 0) < world.current_world_time_minutes
        or other.get("session_id") != record.get("session_id") or other.get("peer_id") != actor.agent_id
        or int((peer.desires_json or {}).get("sleep_until_world_time") or 0) > world.current_world_time_minutes):
        return None
    return peer


def open_private_talk(world, first, second, request):
    for actor, peer in ((first, second), (second, first)):
        actor.family_json = {**(actor.family_json or {}), PRIVATE_TALK_KEY: {
            "session_id": request["request_id"], "peer_id": peer.agent_id,
            "location_id": actor.location.location_id,
            "expires_at": world.current_world_time_minutes + 240,
        }}


def handle_private_talk(session, world, actor, tool_name, params):
    peer = private_talk_peer(session, world, actor)
    if peer is None:
        raise ValueError("private talk is no longer active")
    audience = [actor.agent_id, peer.agent_id]
    speech = str(params.get("speech") or "").strip()
    ending = tool_name == "end_private_talk"
    if ending:
        for resident in (actor, peer):
            resident.family_json = {**(resident.family_json or {}), PRIVATE_TALK_KEY: {}}
    event = create_event(session, world=world,
        event_type="private_talk_closed" if ending else "private_dialogue",
        actor_agent_id=actor.agent_id, target_agent_id=peer.agent_id,
        location_id=actor.location.location_id, visibility_scope="private",
        viewer_text=f"{actor.chosen_name}结束了与{peer.chosen_name}的私聊。" if ending else f"{actor.chosen_name}向{peer.chosen_name}私下说：{speech}",
        importance=45, color_class="dialogue",
        payload={"private_audience_ids": audience, "heard_by_agent_ids": audience,
                 "dialogue_lines": [] if ending else [{"speaker_agent_id": actor.agent_id, "target_agent_id": peer.agent_id, "text": speech}]})
    if not ending:
        session.add(Conversation(event_id=event.event_id, speaker_agent_id=actor.agent_id,
            target_agent_id=peer.agent_id, location_id=event.location_id, content_zh=speech,
            tone="neutral", heard_by_agent_ids_json=audience, world_time=world.current_world_time_minutes))
    return event.event_id, peer.agent_id
