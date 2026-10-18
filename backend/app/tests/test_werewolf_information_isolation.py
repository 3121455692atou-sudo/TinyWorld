from sqlalchemy import select

from app.core.models import Event, Location, Memory
from app.events.event_store import create_event
from app.knowledge.event_access import agent_can_access_event
from app.knowledge.perception import build_turn_context
from app.memory.memory_service import auto_memory_for_event
from app.world.corpses import apply_corpse_exposure
from app.world.werewolf import handle_werewolf_tool, sync_werewolf_phase, werewolf_state, werewolf_current_discussion_actor_id
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world


def move(db, agent, world, local):
    agent.location.location_id = f"{world.world_id}:{local}"
    agent.location.location = db.get(Location, agent.location.location_id)


def test_dawn_is_not_discovery_and_meeting_still_convenes(db):
    world, agents = _make_werewolf_world(db, 4)
    state = werewolf_state(world)
    state["roles"] = {agent.agent_id: "werewolf" if i == 0 else "villager" for i, agent in enumerate(agents)}
    world.settings_json = {**world.settings_json, "werewolf_state": state}
    wolf, witness, remote, victim = agents
    # The victim chose this location; the host no longer moves everyone there.
    move(db, victim, world, "dormitory")
    world.current_world_time_minutes = 22 * 60
    sync_werewolf_phase(db, world)
    kill_ids = handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)
    kill = next(db.get(Event, eid) for eid in kill_ids if db.get(Event, eid).event_type == "werewolf_night_kill_hidden")
    assert victim.lifecycle_state == "dead"
    world.current_world_time_minutes = 1920
    morning = sync_werewolf_phase(db, world)
    assert not any(db.get(Event, eid).event_type == "werewolf_body_found" for eid in morning)
    for agent in [witness, remote]:
        prompt, _ = build_turn_context(db, world, agent)
        assert "狼人存在于村中" in prompt
        assert "死亡事件已公开" not in prompt
        assert "已经成为这里真实发生" not in prompt
        assert "已死亡居民数" not in prompt
        assert "当前还活着的人只有" not in prompt
        assert "已死亡或被放逐者：" not in prompt
        assert "昨夜遭到狼人袭击出局" not in prompt
        assert not agent_can_access_event(db, world, agent.agent_id, kill)
        memories = db.scalars(select(Memory).where(Memory.agent_id == agent.agent_id)).all()
        assert not any("私密行动结果" in memory.content for memory in memories)
    # The actual killer retains its private result.
    assert any("私密行动结果" in memory.content for memory in db.scalars(select(Memory).where(Memory.agent_id == wolf.agent_id)))
    # No discovery is needed for the scheduled meeting.
    world.current_world_time_minutes = 2160
    sync_werewolf_phase(db, world)
    assert werewolf_current_discussion_actor_id(db, world) is not None
    assert all(not record["discovered_by_agent_ids"] for record in world.settings_json["corpse_records"])
    # Only the person who goes to the body gets this observation.
    move(db, witness, world, "dormitory")
    found = apply_corpse_exposure(db, world, witness)
    seen = next(db.get(Event, eid) for eid in found if db.get(Event, eid).event_type == "corpse_seen")
    assert agent_can_access_event(db, world, witness.agent_id, seen)
    assert not agent_can_access_event(db, world, remote.agent_id, seen)
    assert any(memory.source_event_id == seen.event_id for memory in db.scalars(select(Memory).where(Memory.agent_id == witness.agent_id)))
    prompt, _ = build_turn_context(db, world, remote)
    assert seen.agent_visible_text not in prompt
    # Knowledge propagates only when the witness actually tells a listener.
    move(db, witness, world, "discussion_hall")
    report = f"我在集体宿舍发现了{victim.chosen_name}的尸体。"
    spoken = create_event(db, world=world, event_type="dialogue", actor_agent_id=witness.agent_id,
        location_id=witness.location.location_id, viewer_text="发现者向大家说话。",
        payload={"speech": report}, importance=60)
    auto_memory_for_event(db, spoken, [witness.agent_id])
    assert agent_can_access_event(db, world, remote.agent_id, spoken)
    prompt, _ = build_turn_context(db, world, remote)
    assert report in prompt


def test_private_checks_and_past_local_speech_do_not_leak(db):
    world, agents = _make_werewolf_world(db, 4)
    actor, target, listener, later = agents
    state = werewolf_state(world)
    state["public_revealed"] = True
    world.settings_json = {**world.settings_json, "werewolf_state": state}
    secret = create_event(db, world=world, event_type="werewolf_seer_check", actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id, location_id=actor.location.location_id, visibility_scope="private",
        viewer_text="private sentinel result", importance=90)
    auto_memory_for_event(db, secret, [actor.agent_id, target.agent_id, listener.agent_id])
    assert agent_can_access_event(db, world, actor.agent_id, secret)
    for outsider in [target, listener, later]:
        assert not agent_can_access_event(db, world, outsider.agent_id, secret)
        assert not db.scalar(select(Memory).where(Memory.agent_id == outsider.agent_id, Memory.source_event_id == secret.event_id))
    move(db, later, world, "dormitory")
    speech = create_event(db, world=world, event_type="dialogue", actor_agent_id=actor.agent_id,
        location_id=actor.location.location_id, viewer_text="local witness sentinel", importance=60)
    auto_memory_for_event(db, speech, [actor.agent_id])
    assert agent_can_access_event(db, world, listener.agent_id, speech)
    move(db, later, world, "village_square")
    assert not agent_can_access_event(db, world, later.agent_id, speech)
    prompt, _ = build_turn_context(db, world, later)
    assert "local witness sentinel" not in prompt
    assert "private sentinel result" not in prompt
