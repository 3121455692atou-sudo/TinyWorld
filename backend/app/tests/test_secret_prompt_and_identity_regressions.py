from __future__ import annotations

from app.events.event_store import create_event
from app.knowledge.perception import build_turn_context
from app.tests.conftest import make_world


def test_recent_self_intro_turns_visual_label_into_known_name(db):
    world, agents = make_world(db, 2)
    listener, speaker = agents[0], agents[1]
    world.current_world_time_minutes = 30
    create_event(
        db,
        world=world,
        event_type="dialogue",
        actor_agent_id=speaker.agent_id,
        location_id=speaker.location.location_id,
        viewer_text=f"{speaker.chosen_name}自我介绍。",
        payload={
            "dialogue_lines": [
                {
                    "speaker_agent_id": speaker.agent_id,
                    "text": f"我是{speaker.chosen_name}，你之后可以直接叫我{speaker.chosen_name}。",
                }
            ]
        },
    )
    db.commit()

    prompt, _refs = build_turn_context(db, world, listener)

    assert f"称呼建议={speaker.chosen_name}" in prompt
    assert f"已知姓名={speaker.chosen_name}" in prompt
    visible_line = next(line for line in prompt.splitlines() if f"已知姓名={speaker.chosen_name}" in line)
    assert "称呼建议=那个" not in visible_line
