from __future__ import annotations

from app.core.models import Event, Location
from app.effects.death import apply_danger_checks
from app.effects.effect_engine import execute_tool
from app.events.event_store import create_event
from app.llm.action_protocol import ActionOption
from app.simulation.turn_runner import (
    _child_need_reaction_ids,
    _current_turn_failed_tool_entries,
    _current_turn_failed_tool_messages,
    _failed_tools_prompt,
    _format_failure_instruction,
    _replace_action_menu,
    _urgent_survival_action,
)
from app.tools.validators import validate_tool

from conftest import make_world


def test_urgent_survival_does_not_choose_odd_job_outside_work_window(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    world.current_world_time_minutes = 15
    agent.wallet_json = {"money": 0}
    agent.dynamic_state.satiety = 0
    agent.dynamic_state.hydration = 90
    agent.dynamic_state.energy = 80
    workshop = db.get(Location, f"{world.world_id}:workshop")
    assert workshop is not None
    agent.location.location_id = workshop.location_id
    agent.location.location = workshop
    db.flush()

    action = _urgent_survival_action(db, agent, reaction=False)

    assert action is not None
    assert action.tool_name != "do_odd_job"



def test_composite_go_eat_food_moves_to_cafeteria_and_eats_in_one_tool(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    agent.wallet_json = {"money": 20}
    agent.dynamic_state.satiety = 8
    agent.dynamic_state.hydration = 70
    agent.dynamic_state.energy = 70
    start_location_id = agent.location.location_id
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    assert cafeteria is not None

    result = execute_tool(db, world=world, actor=agent, tool_name="go_eat_food", params={})

    assert result.ok
    assert agent.location.location_id == cafeteria.location_id
    assert agent.dynamic_state.satiety > 8
    events = [db.get(Event, event_id) for event_id in result.event_ids]
    assert any(event and event.event_type == "move" and event.payload.get("composite_tool") == "go_eat_food" for event in events)
    assert any(event and event.event_type == "eat" for event in events)
    assert start_location_id != agent.location.location_id

def test_current_turn_failed_tool_is_removed_from_action_menu(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    world.current_world_time_minutes = 30
    create_event(
        db,
        world=world,
        event_type="tool_failed",
        actor_agent_id=agent.agent_id,
        viewer_text="林见舟 没能执行 do_odd_job: 现在没有临时零工可接。",
        agent_visible_text="现在没有临时零工可接。",
        payload={"tool_name": "do_odd_job"},
    )
    db.flush()

    blocked = _current_turn_failed_tool_messages(db, world, agent)
    prompt = """【当前地点】
行动选项:
01 做零工
02 阅读

【最近公开事件】
暂无。"""
    filtered = _replace_action_menu(
        prompt,
        [
            ActionOption(option_id=2, label="阅读", tool_name="read_quietly"),
        ],
        "zh",
    )

    assert blocked["do_odd_job"] == "现在没有临时零工可接。"
    assert "做零工" not in filtered
    assert "02 阅读" in filtered


def test_previous_turn_failed_tool_is_not_blocked(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    world.current_world_time_minutes = 30
    create_event(
        db,
        world=world,
        event_type="tool_failed",
        actor_agent_id=agent.agent_id,
        viewer_text="林见舟 没能执行 do_odd_job: 现在没有临时零工可接。",
        agent_visible_text="现在没有临时零工可接。",
        payload={"tool_name": "do_odd_job"},
    )
    db.flush()
    world.current_world_time_minutes = 31

    blocked = _current_turn_failed_tool_messages(db, world, agent)

    assert "do_odd_job" not in blocked


def test_single_format_failure_warns_without_blocking_tool(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    world.current_world_time_minutes = 30
    create_event(
        db,
        world=world,
        event_type="tool_failed",
        actor_agent_id=agent.agent_id,
        viewer_text="林见舟 没能执行 write_private_note: 这个行动需要第二行开始写正文。",
        agent_visible_text="这个行动需要第二行开始写正文。",
        payload={"tool_name": "write_private_note", "failure_reason_code": "missing_text"},
    )
    db.flush()

    blocked = _current_turn_failed_tool_messages(db, world, agent)

    assert "write_private_note" not in blocked


def test_repeated_format_failure_blocks_tool_for_current_turn(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    world.current_world_time_minutes = 30
    for _ in range(3):
        create_event(
            db,
            world=world,
            event_type="tool_failed",
            actor_agent_id=agent.agent_id,
            viewer_text="林见舟 没能执行 write_private_note: 这个行动需要第二行开始写正文。",
            agent_visible_text="这个行动需要第二行开始写正文。",
            payload={"tool_name": "write_private_note", "failure_reason_code": "missing_text"},
        )
    db.flush()

    blocked = _current_turn_failed_tool_messages(db, world, agent)

    assert blocked["write_private_note"] == "这个行动需要第二行开始写正文。"


def test_second_format_failure_gives_reference_before_blocking(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    world.current_world_time_minutes = 30
    for _ in range(2):
        create_event(
            db,
            world=world,
            event_type="tool_failed",
            actor_agent_id=agent.agent_id,
            viewer_text="林见舟 没能执行 write_private_note: 这个行动需要第二行开始写正文。",
            agent_visible_text="这个行动需要第二行开始写正文。",
            payload={"tool_name": "write_private_note", "failure_reason_code": "missing_text"},
        )
    db.flush()
    option = ActionOption(option_id=7, label="写私人笔记", tool_name="write_private_note", text_required=True)

    blocked = _current_turn_failed_tool_messages(db, world, agent)
    prompt = _failed_tools_prompt(_current_turn_failed_tool_entries(db, world, agent), [option])

    assert "write_private_note" not in blocked
    assert "正确工具调用应该这样写" in prompt
    assert "[07]\\n今天发生的事" in prompt
    assert "本轮才会禁用" in prompt


def test_format_failure_instruction_shows_two_line_aohp_shape(db):
    world, agents = make_world(db, agent_count=1)
    agent = agents[0]
    validation = validate_tool(
        db,
        actor=agent,
        tool_name="write_private_note",
        params={},
        world_time=world.current_world_time_minutes,
        persist_visibility=False,
    )
    option = ActionOption(option_id=7, label="写私人笔记", tool_name="write_private_note", text_required=True)

    instruction = _format_failure_instruction("write_private_note", [option], validation)

    assert "不能只输出 [07]" in instruction
    assert "[07]\n今天发生的事" in instruction


def test_newborn_zero_need_window_warns_before_fatal_death(db):
    world, agents = make_world(db, agent_count=1)
    child = agents[0]
    child.age_stage = "newborn"
    state = child.dynamic_state
    state.health = 36
    state.energy = 80
    state.satiety = 0
    state.hydration = 0
    state.zero_satiety_since = 0
    state.zero_hydration_since = 0
    world.current_world_time_minutes = 49 * 60

    event_ids = apply_danger_checks(db, world, child)

    assert child.lifecycle_state != "dead"
    assert state.health > 0
    events = [db.get(Event, event_id) for event_id in event_ids]
    assert any(event and event.payload and event.payload.get("warning") == "child_need" for event in events)


def test_child_need_reaction_reaches_awake_guardian_even_outside_adjacent_scene(db):
    world, agents = make_world(db, agent_count=2)
    child, guardian = agents[0], agents[1]
    child.age_stage = "newborn"
    child.family_json = {"guardian_agent_ids": [guardian.agent_id]}
    medical_room = db.get(Location, f"{world.world_id}:medical_room")
    assert medical_room is not None
    guardian.location.location_id = medical_room.location_id
    guardian.location.location = medical_room
    event = create_event(
        db,
        world=world,
        event_type="child_need",
        actor_agent_id=child.agent_id,
        location_id=child.location.location_id,
        viewer_text=f"{child.chosen_name} 哭得很急，明显需要照顾。",
        importance=75,
    )
    db.flush()

    reaction_ids = _child_need_reaction_ids(db, world, child, [event.event_id])

    assert guardian.agent_id in reaction_ids
