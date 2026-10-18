"""Persisted room locks. Observers see local lock state, never its hidden cause."""
from app.core.models import Location
from app.llm.language import location_label, world_language
from app.world.visibility import adjacent_location_ids


def room_door_locked(world, location_id):
    return bool(((world.settings_json or {}).get('room_doors') or {}).get(location_id, False))


def set_room_door_lock(world, location_id, locked):
    world.settings_json = {**(world.settings_json or {}), 'room_doors': {
        **((world.settings_json or {}).get('room_doors') or {}), location_id: bool(locked)}}


def unlock_home_after_death(world, agent):
    home = ((agent.wallet_json or {}).get('housing') or {}).get('home_location_id')
    if home and agent.world_id == world.world_id and agent.lifecycle_state == 'dead':
        set_room_door_lock(world, home, False)


def manageable_home_door(session, world, agent):
    home = ((agent.wallet_json or {}).get('housing') or {}).get('home_location_id')
    location = session.get(Location, home) if home else None
    current = agent.location.location if agent.location else None
    if (location and location.world_id == world.world_id and 'private' in (location.tags_json or [])
            and current and (current.location_id == home or home in adjacent_location_ids(session, current))):
        return location
    return None


def nearby_door_prompt_lines(session, world, agent):
    current = agent.location.location if agent.location else None
    if not current:
        return []
    english = world_language(world) == 'en'
    lines = []
    for location_id in [current.location_id, *adjacent_location_ids(session, current)]:
        location = session.get(Location, location_id)
        if not location or location.world_id != world.world_id or not {'home', 'private'} <= set(location.tags_json or []):
            continue
        locked = room_door_locked(world, location_id)
        state = ('locked' if locked else 'unlocked') if english else ('已上锁' if locked else '未锁')
        lines.append(f"{location_label(location, 'en') if english else location.public_name}: {state}")
    if not lines:
        return []
    prefix = '[Nearby doors] ' if english else '【眼前房门】'
    rule = (' An unlocked door does not prove that a room is empty. You can enter your own home with your key.'
            if english else '。未锁不代表房间无人；房主可用钥匙正常进出自己的住所。')
    return [prefix + '；'.join(lines) + rule]
