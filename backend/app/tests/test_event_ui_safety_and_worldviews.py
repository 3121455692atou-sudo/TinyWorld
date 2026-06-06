from __future__ import annotations

from app.api.serializers import event_to_dict
from app.content.presets import WEREWOLF_WORLDVIEW
from app.content.worldview_runtime import worldview_rule_parameters
from app.core.models import Memory
from app.events.event_store import create_event
from app.memory.memory_service import auto_memory_for_event
from app.tools.registry import get_tool


def test_public_event_stream_never_exposes_mechanical_tool_feedback(db):
    from app.tests.conftest import make_world

    world, agents = make_world(db, 2)
    event = create_event(
        db,
        world=world,
        event_type="tool_failed",
        actor_agent_id=agents[0].agent_id,
        location_id=agents[0].location.location_id,
        viewer_text="工具调用格式错误: 当前尝试的工具是 move_to_location。请重新选择一个参数完整且符合当前地点/目标的工具。",
        agent_visible_text="工具调用格式错误: 当前尝试的工具是 move_to_location。请重新选择一个参数完整且符合当前地点/目标的工具。",
        payload={
            "tool_name": "move_to_location",
            "failure_reason_code": "private_room_blocked",
            "llm_feedback": "工具调用格式错误: 当前尝试的工具是 move_to_location。",
            "debug_payload": {"raw_error": "validation.message"},
        },
        no_state_changed=True,
    )
    public = event_to_dict(event, db)
    serialized = str(public)

    assert "工具调用格式错误" not in public["viewer_text"]
    assert "当前尝试的工具" not in serialized
    assert "llm_feedback" not in serialized
    assert public["state_delta"] == {}
    assert public["payload"] == {}
    assert "别人房间" in public["viewer_text"] or "没有对自己开放" in public["viewer_text"]


def test_public_events_endpoint_hides_noop_and_tool_failed_events(db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.tests.conftest import make_world

    world, agents = make_world(db, 1)
    create_event(db, world=world, event_type="nothing", actor_agent_id=agents[0].agent_id, viewer_text=f"{agents[0].chosen_name} 安静地什么也没做。")
    create_event(db, world=world, event_type="tool_failed", actor_agent_id=agents[0].agent_id, viewer_text=f"{agents[0].chosen_name}试着做些什么，但行动没有完成。")
    visible = create_event(db, world=world, event_type="move", actor_agent_id=agents[0].agent_id, viewer_text=f"{agents[0].chosen_name} 走向广场。")
    db.commit()

    response = TestClient(app).get(f"/api/worlds/{world.world_id}/events", params={"latest": "false", "limit": 20})
    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["event_id"] for event in events] == [visible.event_id]


def test_dialogue_is_structured_and_not_left_inside_narration_or_message_content(db):
    from app.tests.conftest import make_world

    world, agents = make_world(db, 2)
    speech = "能不能给我一点吃的？我真的撑不住了。"
    event = create_event(
        db,
        world=world,
        event_type="aid_request",
        actor_agent_id=agents[0].agent_id,
        target_agent_id=agents[1].agent_id,
        location_id=agents[0].location.location_id,
        viewer_text=f"{agents[0].chosen_name}向附近的人请求食物：『{speech}』",
        payload={
            "speech": speech,
            "message": "这不是台词来源，前端不能把 message 当头像气泡。",
            "content": "这也不是台词来源。",
            "dialogue_lines": [
                {"speaker_agent_id": agents[0].agent_id, "target_agent_id": agents[1].agent_id, "text": speech, "tone": "pleading"}
            ],
        },
        importance=60,
        color_class="dialogue",
    )
    public = event_to_dict(event, db)

    assert speech not in public["viewer_text"]
    assert public["payload"]["speech"] == speech
    assert public["payload"]["dialogue_lines"] == [{"speaker_agent_id": agents[0].agent_id, "target_agent_id": agents[1].agent_id, "text": speech, "tone": "pleading"}]
    assert public["payload"]["message"] == "这不是台词来源，前端不能把 message 当头像气泡。"
    assert public["payload"]["content"] == "这也不是台词来源。"

    auto_memory_for_event(db, event, [agents[1].agent_id])
    memory = db.query(Memory).filter(Memory.agent_id == agents[1].agent_id).one()
    assert speech in memory.content
    assert "message 当头像气泡" not in memory.content


def test_default_and_werewolf_worldviews_have_three_day_family_cycles_and_guard_room():
    default_params = worldview_rule_parameters(None)
    assert default_params["pregnancy_duration_days"] == 3
    assert default_params["child_growth_days"] == 3

    locations = {item["location_id"]: item for item in WEREWOLF_WORLDVIEW["locations"]}
    assert "guard_room" in locations
    assert "werewolf_guard_protect_by_name" in locations["guard_room"]["available_tools"]
    assert "guard_room" in locations["dormitory"]["neighbors"]

    spec = get_tool("werewolf_guard_protect_by_name")
    assert spec is not None
    assert spec.hard_effect_id == "werewolf"
    assert spec.target_policy == "known_name"


def test_child_and_danger_events_enter_reaction_queue_even_from_adjacent_room(db):
    from app.core.models import Location
    from app.events.event_store import create_event
    from app.simulation.reaction_queue import reaction_queue
    from app.simulation.turn_runner import _enqueue_danger_reactions
    from conftest import make_world

    world, agents = make_world(db, 2)
    child, guardian = agents
    child.age_stage = "newborn"
    child.family_json = {"guardian_agent_ids": [guardian.agent_id]}
    child_location = db.get(Location, f"{world.world_id}:cabin")
    guardian_location = db.get(Location, f"{world.world_id}:central_square")
    child.location.location_id = child_location.location_id
    child.location.location = child_location
    guardian.location.location_id = guardian_location.location_id
    guardian.location.location = guardian_location

    event = create_event(
        db,
        world=world,
        event_type="warning",
        actor_agent_id=child.agent_id,
        location_id=child_location.location_id,
        viewer_text=f"{child.chosen_name}不安地哭了起来，像是在提醒附近的人自己需要照顾。",
        payload={"warning": "child_need"},
        importance=78,
        color_class="warning",
    )
    db.flush()

    _enqueue_danger_reactions(db, world, child, [event.event_id])
    task = reaction_queue.pop(world.world_id)

    assert task is not None
    assert task.agent_id == guardian.agent_id
    assert "需要照顾" in task.trigger_text or "哭" in task.trigger_text



def test_candidate_tool_debug_request_is_system_only_and_sanitized(db):
    from app.core.models import Event
    from app.effects.effect_engine import _v5_meta_or_child_action
    from app.tests.conftest import make_world

    world, agents = make_world(db, 1)
    event_ids = _v5_meta_or_child_action(db, world, agents[0], "request_more_candidate_tools", agents[0].location.location_id, {})
    event = db.get(Event, event_ids[0])

    assert event is not None
    assert event.visibility_scope == "system"
    public = event_to_dict(event, db)
    serialized = str(public)
    assert "当前工具可能不足" not in serialized
    assert "隐藏候选" not in serialized
    assert "解释过滤原因" not in serialized
    assert public["payload"] == {}


def test_werewolf_schedule_keeps_morning_until_noon_even_for_legacy_fast_cycle(db):
    from app.tests.conftest import make_world
    from app.world.werewolf import werewolf_phase

    world, _agents = make_world(db, 2)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "worldview_rule_parameters": {
            "werewolf": {
                "game_start_minute": 8 * 60,
                "morning_minutes": 20,
                "discussion_minutes": 45,
                "voting_minutes": 25,
                "night_minutes": 90,
            }
        },
    }

    world.current_world_time_minutes = 8 * 60 + 38
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 11 * 60 + 59
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 12 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 16 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 18 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 22 * 60
    assert werewolf_phase(world) == (1, "night")
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    assert werewolf_phase(world) == (2, "morning")
    world.current_world_time_minutes = 24 * 60 + 12 * 60
    assert werewolf_phase(world) == (2, "discussion")


def test_werewolf_roundtable_auto_rotates_without_end_or_rebuttal_tools(db):
    from app.tests.conftest import make_world
    from app.world.werewolf import handle_werewolf_tool, werewolf_current_discussion_actor_id, werewolf_tool_allowed

    world, agents = make_world(db, 2)
    world.current_world_time_minutes = 24 * 60 + 12 * 60
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_state": {
            "roles": {agents[0].agent_id: "villager", agents[1].agent_id: "werewolf"},
            "winner": None,
            "public_revealed": True,
            "roles_revealed_to_agents": True,
            "speech_order": [agents[0].agent_id, agents[1].agent_id],
            "current_speaker_index": 0,
            "speech_counts": {"2": {}},
            "speech_ended": {"2": {}},
        },
    }

    ok, reason, message = werewolf_tool_allowed(db, world, agents[0], "werewolf_end_speech")
    assert not ok
    assert reason == "werewolf_legacy_discussion_tool"
    assert "自动轮转" in message

    for legacy_tool in ["werewolf_rebut", "werewolf_skip_rebuttal", "werewolf_reply_rebuttal", "werewolf_drop_debate"]:
        ok, reason, _message = werewolf_tool_allowed(db, world, agents[0], legacy_tool)
        assert not ok
        assert reason == "werewolf_legacy_discussion_tool"

    ok, _, _ = werewolf_tool_allowed(db, world, agents[0], "werewolf_speak")
    assert ok
    assert werewolf_current_discussion_actor_id(db, world) == agents[0].agent_id
    handle_werewolf_tool(db, world, agents[0], "werewolf_speak", {"speech": "我发言一次，然后主持应该自动换人。"})
    assert werewolf_current_discussion_actor_id(db, world) == agents[1].agent_id

    ok, reason, _message = werewolf_tool_allowed(db, world, agents[0], "werewolf_end_speech")
    assert not ok
    assert reason == "werewolf_legacy_discussion_tool"


def test_werewolf_discussion_batch_only_runs_current_speaker(db):
    from app.simulation.turn_runner import TurnRunner
    from app.tests.conftest import make_world

    world, agents = make_world(db, 3)
    world.current_world_time_minutes = 24 * 60 + 12 * 60
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_state": {
            "roles": {agent.agent_id: "villager" for agent in agents},
            "winner": None,
            "public_revealed": True,
            "roles_revealed_to_agents": True,
            "speech_order": [agent.agent_id for agent in agents],
            "current_speaker_index": 1,
            "speech_counts": {"2": {agents[0].agent_id: 1}},
            "speech_ended": {"2": {agents[0].agent_id: True}},
        },
    }

    batch = TurnRunner()._regular_agent_batch(db, world)
    assert [agent.agent_id for agent in batch] == [agents[1].agent_id]
