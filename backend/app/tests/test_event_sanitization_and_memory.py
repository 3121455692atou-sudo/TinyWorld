from __future__ import annotations

from app.api.serializers import event_to_dict
from app.content.presets import WEREWOLF_WORLDVIEW, WORLDVIEWS
from app.core.models import Memory
from app.events.event_store import create_event
from app.knowledge.perception import _memory_prompt_lines
from app.tests.conftest import make_world


def test_public_failure_text_is_natural_but_llm_feedback_stays_private(db):
    world, agents = make_world(db, agent_count=2)
    actor = agents[0]
    raw = (
        "工具调用格式错误: 这是别人的私人小屋，不能直接移动进去。"
        "当前尝试的工具是 move_to_location。请重新选择一个参数完整且符合当前地点/目标的工具。"
    )
    event = create_event(
        db,
        world=world,
        event_type="tool_failed",
        viewer_text=raw,
        agent_visible_text=raw,
        actor_agent_id=actor.agent_id,
        payload={
            "tool_name": "move_to_location",
            "failure_reason_code": "private_room_blocked",
            "llm_feedback": raw,
            "speech": raw,
            "dialogue_lines": [{"speaker_agent_id": actor.agent_id, "text": raw}],
        },
    )
    db.commit()

    assert "工具调用格式错误" not in event.viewer_text
    assert "当前尝试的工具" not in event.viewer_text
    assert "私人空间" not in event.viewer_text
    assert "没有对自己开放" in event.viewer_text or "别人房间" in event.viewer_text
    # LLM 反馈仍然保留在私有可见文本中，方便下一轮修正；公开接口会删掉。
    assert "工具调用格式错误" in event.agent_visible_text

    public = event_to_dict(event, db)
    dumped = str(public)
    assert "工具调用格式错误" not in dumped
    assert "当前尝试的工具" not in dumped
    assert "llm_feedback" not in dumped
    assert public["payload"].get("dialogue_lines", []) == []
    assert "speech" not in public["payload"]


def test_dialogue_payload_keeps_speech_out_of_narration(db):
    world, agents = make_world(db, agent_count=2)
    actor, target = agents[0], agents[1]
    event = create_event(
        db,
        world=world,
        event_type="aid_request",
        viewer_text=f"{actor.chosen_name} 请求 {target.chosen_name}：『能分我一点吃的吗？』",
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        payload={
            "speech": "能分我一点吃的吗？",
            "dialogue_lines": [
                {"speaker_agent_id": actor.agent_id, "target_agent_id": target.agent_id, "text": "能分我一点吃的吗？"}
            ],
        },
    )
    db.commit()

    assert "能分我一点吃的吗" not in event.viewer_text
    assert event.payload["dialogue_lines"][0]["text"] == "能分我一点吃的吗？"
    public = event_to_dict(event, db)
    assert "能分我一点吃的吗" not in public["viewer_text"]
    assert public["payload"]["dialogue_lines"][0]["text"] == "能分我一点吃的吗？"


def test_reasoning_blocks_are_removed_from_dialogue_events_and_public_api(db):
    world, agents = make_world(db, agent_count=2)
    actor, target = agents[0], agents[1]
    speech = "海铃，那我们先去看看有什么可以吃的吧？"
    raw = f"""[01:2]
<thought>
I should talk to the target.
Format check:
[01:2]
{speech}
</thought>

[01:2]
{speech}"""
    event = create_event(
        db,
        world=world,
        event_type="dialogue",
        viewer_text=raw,
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        payload={"speech": raw},
    )
    db.commit()

    assert event.viewer_text == f"{actor.chosen_name}开口说话。"
    assert event.payload["speech"] == speech
    assert event.payload["dialogue_lines"][0]["text"] == speech

    event.viewer_text = raw
    event.payload = {"speech": raw, "dialogue_lines": [{"speaker_agent_id": actor.agent_id, "text": raw}]}
    db.commit()

    public = event_to_dict(event, db)
    dumped = str(public)
    assert "<thought>" not in dumped
    assert "Format check" not in dumped
    assert "[01:2]" not in dumped
    assert public["payload"]["dialogue_lines"][0]["text"] == speech


def test_memory_prompt_mixes_important_and_recent_in_chronological_order(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    rows = [
        Memory(agent_id=agent.agent_id, memory_type="short", content="第1天在广场看云。", importance=10, created_world_time=10),
        Memory(agent_id=agent.agent_id, memory_type="summary", content="长期摘要：已经和桃枝约定一起照顾孩子。", importance=50, created_world_time=20),
        Memory(agent_id=agent.agent_id, memory_type="short", content="很普通的路过记录。", importance=5, created_world_time=30),
        Memory(agent_id=agent.agent_id, memory_type="werewolf", content="狼人杀笔记：桃枝白天投给许澈。", importance=65, created_world_time=40),
        Memory(agent_id=agent.agent_id, memory_type="short", content="刚刚听到有人求助，需要回应。", importance=35, created_world_time=50),
    ]
    db.add_all(rows)
    db.commit()

    lines = _memory_prompt_lines(list(reversed(rows)), limit=3, language="zh")
    joined = "\n".join(lines)
    assert "长期摘要" in joined
    assert "狼人杀笔记" in joined
    assert "刚刚听到有人求助" in joined
    assert joined.index("长期摘要") < joined.index("狼人杀笔记") < joined.index("刚刚听到有人求助")


def test_packaged_worldviews_include_distinct_werewolf_guard_room():
    worldview_ids = {worldview["worldview_id"] for worldview in WORLDVIEWS}
    assert {"sweet_romance_worldview", "pure_emotion_worldview", "werewolf_game_worldview"}.issubset(worldview_ids)
    location_ids = {location["location_id"] for location in WEREWOLF_WORLDVIEW["locations"]}
    assert {"village_square", "discussion_hall", "voting_room", "wolf_den", "seer_room", "morgue", "guard_room"}.issubset(location_ids)
    assert "central_square" not in location_ids
