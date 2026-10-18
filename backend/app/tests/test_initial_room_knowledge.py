from sqlalchemy import select

from app.core.models import IdentityKnowledge
from app.events.event_store import create_event
from app.knowledge.experience import personal_experience_context
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world


def _initial_rooms(db):
    world, agents = _make_werewolf_world(db)
    for agent in agents:
        create_event(db, world=world, event_type="birth", actor_agent_id=agent.agent_id,
            viewer_text=f"{agent.chosen_name} 来到村庄。",
            payload={"home_location_id": agent.wallet_json["housing"]["home_location_id"]})
    observer, initial, later, unknown = agents
    for target, learned in [(initial, 480), (later, 500)]:
        knowledge = db.scalar(select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == observer.agent_id,
            IdentityKnowledge.target_agent_id == target.agent_id))
        if knowledge is None:
            knowledge = IdentityKnowledge(observer_agent_id=observer.agent_id, target_agent_id=target.agent_id)
            db.add(knowledge)
        knowledge.name_known = True
        knowledge.known_name = target.chosen_name
        knowledge.first_name_learned_at = learned
        # Subsequent introductions may update this tag; the initial date remains.
        knowledge.name_learned_via = "recent_self_intro"
    world.current_world_time_minutes = 2000
    db.flush()
    return world, agents


def test_initial_acquaintances_have_opening_room_allocation_without_live_tracking(db):
    world, (observer, initial, later, unknown) = _initial_rooms(db)
    initial.lifecycle_state = "dead"
    initial.wallet_json = {**initial.wallet_json, "housing": {"home_location_id": unknown.wallet_json["housing"]["home_location_id"]}}
    text = personal_experience_context(db, world, observer)
    room_line = next(line for line in text.splitlines() if line.startswith("【入住时的房间分配】"))
    assert f"{initial.chosen_name}：村民房间2" in room_line
    assert later.chosen_name not in room_line and unknown.chosen_name not in room_line
    assert "村民房间4" not in room_line
    assert "死亡" not in room_line and "尸体" not in room_line


def test_no_room_roster_is_invented_for_strangers_or_non_werewolf_world(db):
    world, agents = _initial_rooms(db)
    assert "【入住时的房间分配】" not in personal_experience_context(db, world, agents[-1])
    world.settings_json = {**world.settings_json, "werewolf_mode_enabled": False}
    assert "【入住时的房间分配】" not in personal_experience_context(db, world, agents[0])


def test_initial_room_allocation_uses_world_language(db):
    world, agents = _initial_rooms(db)
    world.settings_json = {**world.settings_json, "language": "en"}
    text = personal_experience_context(db, world, agents[0])
    line = next(line for line in text.splitlines() if line.startswith("[Initial room allocation]"))
    assert not any('\u4e00' <= c <= '\u9fff' for c in line)
