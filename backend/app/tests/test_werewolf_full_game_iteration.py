from __future__ import annotations

import pytest

from app.core.models import Event, Memory
from app.knowledge.perception import build_turn_context
from app.tests.conftest import make_world
from app.world.werewolf import (
    handle_werewolf_tool,
    initialize_werewolf_game,
    sync_werewolf_phase,
    werewolf_current_discussion_actor_id,
    werewolf_final_speech_actor_id,
    werewolf_menu_tool_names,
    werewolf_phase,
    werewolf_state,
    werewolf_tool_allowed,
)


def _agent_by_role(world, agents, role: str):
    roles = werewolf_state(world)["roles"]
    return next(agent for agent in agents if roles.get(agent.agent_id) == role)


def test_day_one_agent_prompt_has_no_werewolf_or_meeting_leaks(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    db.commit()

    prompt, _refs = build_turn_context(db, world, agents[0])

    leaked_terms = ["狼人杀", "狼人", "圆桌", "投票", "预言家", "守卫", "验尸官", "狼人密会", "村庄会议厅"]
    assert not [term for term in leaked_terms if term in prompt]
    assert "普通村庄" in prompt
    assert not ((agents[0].desires_json or {}).get("werewolf"))
    assert not werewolf_menu_tool_names(db, world, agents[0])


def test_wolf_pack_mismatch_requires_shared_discussion_before_retry(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "werewolf",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {
        **(world.settings_json or {}),
        "werewolf_state": state,
        "werewolf_observer_roles": state["roles"],
    }
    db.commit()

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "night")

    wolf_a, wolf_b = agents[0], agents[1]
    target_a, target_b = agents[2], agents[3]
    assert werewolf_menu_tool_names(db, world, wolf_a) == {"werewolf_wolf_discuss"}
    ok, reason, _message = werewolf_tool_allowed(db, world, wolf_a, "werewolf_kill_by_name")
    assert not ok
    assert reason == "werewolf_discussion_required"

    handle_werewolf_tool(db, world, wolf_a, "werewolf_wolf_discuss", {"speech": f"我觉得可以先看{target_a.chosen_name}，但要听你的判断。"})
    assert werewolf_menu_tool_names(db, world, wolf_a) == set()
    handle_werewolf_tool(db, world, wolf_b, "werewolf_wolf_discuss", {"speech": f"我更怀疑{target_b.chosen_name}，先提名看看是否一致。"})
    assert "werewolf_kill_by_name" in werewolf_menu_tool_names(db, world, wolf_a)

    first_events = handle_werewolf_tool(db, world, wolf_a, "werewolf_kill_by_name", {}, target=target_a)
    assert not first_events or not any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_night_kill" for event_id in first_events)

    mismatch_events = handle_werewolf_tool(db, world, wolf_b, "werewolf_kill_by_name", {}, target=target_b)
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_wolf_consensus_failed" for event_id in mismatch_events)
    assert target_a.lifecycle_state != "dead"
    assert target_b.lifecycle_state != "dead"
    assert werewolf_state(world).get("wolf_consensus_need_discussion", {}).get("2") is True
    assert werewolf_menu_tool_names(db, world, wolf_a) == {"werewolf_wolf_discuss"}

    handle_werewolf_tool(db, world, wolf_a, "werewolf_wolf_discuss", {"speech": f"刚才我选的是{target_a.chosen_name}，但我们不一致，所以这次必须统一。"})
    assert werewolf_menu_tool_names(db, world, wolf_a) == set()
    handle_werewolf_tool(db, world, wolf_b, "werewolf_wolf_discuss", {"speech": f"我同意统一选{target_a.chosen_name}，不要再各选各的。"})
    assert werewolf_state(world).get("wolf_consensus_need_discussion", {}).get("2") is False
    assert "werewolf_kill_by_name" in werewolf_menu_tool_names(db, world, wolf_a)

    handle_werewolf_tool(db, world, wolf_a, "werewolf_kill_by_name", {}, target=target_a)
    kill_events = handle_werewolf_tool(db, world, wolf_b, "werewolf_kill_by_name", {}, target=target_a)
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_night_kill" for event_id in kill_events)
    assert target_a.lifecycle_state == "dead"


def test_wolf_night_kill_win_preserves_final_speech_state(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "werewolf",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {
        **(world.settings_json or {}),
        "werewolf_state": state,
        "werewolf_observer_roles": state["roles"],
    }
    db.commit()

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    sync_werewolf_phase(db, world)
    wolf_a, wolf_b = agents[0], agents[1]
    target = agents[2]
    handle_werewolf_tool(db, world, wolf_a, "werewolf_wolf_discuss", {"speech": f"我提议今晚选{target.chosen_name}。"})
    handle_werewolf_tool(db, world, wolf_b, "werewolf_wolf_discuss", {"speech": f"同意，今晚统一选{target.chosen_name}。"})
    handle_werewolf_tool(db, world, wolf_a, "werewolf_kill_by_name", {}, target=target)
    kill_events = handle_werewolf_tool(db, world, wolf_b, "werewolf_kill_by_name", {}, target=target)

    event_types = {db.get(Event, event_id).event_type for event_id in kill_events if db.get(Event, event_id)}
    assert "werewolf_night_kill" in event_types
    assert "werewolf_game_decided" in event_types
    assert target.lifecycle_state == "dead"
    assert werewolf_state(world).get("winner") == "狼人阵营"
    assert werewolf_final_speech_actor_id(db, world) in {wolf_a.agent_id, wolf_b.agent_id}
    assert world.status != "ended"

    world.current_world_time_minutes = 2 * 24 * 60 + 8 * 60
    followup_events = sync_werewolf_phase(db, world)
    followup_types = {db.get(Event, event_id).event_type for event_id in followup_events if db.get(Event, event_id)}
    assert "werewolf_body_found" not in followup_types
    assert "werewolf_phase" not in followup_types
    assert werewolf_state(world).get("winner") == "狼人阵营"


def test_exiled_player_is_remembered_and_removed_from_wolf_targets(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    world.current_world_time_minutes = 24 * 60 + 18 * 60
    sync_werewolf_phase(db, world)
    target = agents[1]
    for voter in agents:
        handle_werewolf_tool(db, world, voter, "werewolf_vote_by_name", {}, target=target)
    db.commit()

    assert target.lifecycle_state == "dead"
    wolf_memory_text = "\n".join(
        memory.content
        for memory in db.query(Memory).filter(Memory.agent_id == agents[0].agent_id).order_by(Memory.memory_id).all()
    )
    assert f"第2天投票结果：{target.chosen_name}已经被白天投票放逐出局" in wolf_memory_text
    assert "不要再把这个人当作可行动目标" in wolf_memory_text

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    prompt, _refs = build_turn_context(db, world, agents[0])
    assert f"{target.chosen_name}(白天投票放逐出局)" in prompt
    assert "已出局者不能再发言、投票、被投票、被夜袭、被查验或被守护" in prompt
    private_line = next(line for line in prompt.splitlines() if "今晚可夜袭目标只能从当前存活且不是狼人同伴的人里选" in line)
    assert target.chosen_name not in private_line
    assert agents[2].chosen_name in private_line
    assert agents[3].chosen_name in private_line


@pytest.mark.parametrize(
    "role_order",
    [
        ["werewolf", "seer", "coroner", "villager"],
        ["seer", "werewolf", "villager", "coroner"],
        ["villager", "coroner", "seer", "werewolf"],
    ],
)
def test_iterated_werewolf_game_flow_keeps_day_one_secret_then_reveals_after_body(db, role_order):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {agent.agent_id: role_order[index] for index, agent in enumerate(agents)}
    state["public_revealed"] = False
    state["roles_revealed_to_agents"] = False
    world.settings_json = {
        **(world.settings_json or {}),
        "werewolf_state": state,
        "werewolf_observer_roles": {agent.agent_id: role_order[index] for index, agent in enumerate(agents)},
    }
    db.commit()

    wolf = _agent_by_role(world, agents, "werewolf")
    seer = _agent_by_role(world, agents, "seer")

    world.current_world_time_minutes = 12 * 60
    assert werewolf_phase(world) == (1, "morning")
    assert not werewolf_menu_tool_names(db, world, seer)
    assert not ((seer.desires_json or {}).get("werewolf"))

    world.current_world_time_minutes = 22 * 60
    night_events = sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (1, "night")
    assert not werewolf_menu_tool_names(db, world, seer)
    assert not werewolf_menu_tool_names(db, world, wolf)
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "sleep_start" for event_id in night_events)
    hidden_kill = ((werewolf_state(world).get("night_kills") or {}).get("1") or {})
    victim_id = hidden_kill.get("target_agent_id")
    victim = next((agent for agent in agents if agent.agent_id == victim_id), None)
    assert victim is not None
    assert victim.lifecycle_state == "dead"
    assert victim.agent_id != wolf.agent_id

    world.current_world_time_minutes = 24 * 60 + 8 * 60
    morning_events = sync_werewolf_phase(db, world)
    morning_events += sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "morning")
    body_events = [db.get(Event, event_id) for event_id in morning_events if db.get(Event, event_id) and db.get(Event, event_id).event_type == "werewolf_body_found"]
    assert body_events
    assert body_events[0].target_agent_id == victim.agent_id
    assert (world.settings_json or {}).get("corpse_records")
    assert werewolf_state(world).get("public_revealed") is True
    assert ((wolf.desires_json or {}).get("werewolf") or {}).get("role") == "werewolf"

    world.current_world_time_minutes = 24 * 60 + 12 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "discussion")
    living_order = [agent.agent_id for agent in agents if agent.lifecycle_state != "dead"]
    spoken_order: list[str] = []
    while True:
        current_id = werewolf_current_discussion_actor_id(db, world)
        if not current_id:
            break
        speaker = next(agent for agent in agents if agent.agent_id == current_id)
        spoken_order.append(speaker.agent_id)
        menu = werewolf_menu_tool_names(db, world, speaker)
        assert menu == {"werewolf_speak"}
        speech_events = handle_werewolf_tool(
            db,
            world,
            speaker,
            "werewolf_speak",
            {"speech": f"昨晚{victim.chosen_name}遇害，尸体是今天的核心线索。我要听完所有人的说法再投票。"},
        )
        assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_speech" for event_id in speech_events)
        assert "werewolf_end_speech" not in werewolf_menu_tool_names(db, world, speaker)
        assert "werewolf_rebut" not in werewolf_menu_tool_names(db, world, speaker)
    assert spoken_order == living_order
    assert world.current_world_time_minutes == 24 * 60 + 12 * 60

    world.current_world_time_minutes = 24 * 60 + 18 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "voting")
    for agent in agents:
        if agent.lifecycle_state != "dead":
            handle_werewolf_tool(db, world, agent, "werewolf_vote_by_name", {}, target=wolf)
    db.commit()
    assert wolf.lifecycle_state == "dead"
    state = werewolf_state(world)
    assert state.get("winner") == "人类阵营"
    assert world.status != "ended"


def test_single_wolf_night_skips_private_discussion_after_public_reveal(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)

    wolf = _agent_by_role(world, agents, "werewolf")
    world.current_world_time_minutes = 22 * 60
    sync_werewolf_phase(db, world)
    assert not werewolf_menu_tool_names(db, world, wolf)

    world.current_world_time_minutes = 24 * 60 + 8 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_state(world).get("public_revealed") is True

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    sync_werewolf_phase(db, world)
    menu = werewolf_menu_tool_names(db, world, wolf)
    assert "werewolf_kill_by_name" in menu
    assert "werewolf_wolf_discuss" not in menu
    ok, reason, _message = werewolf_tool_allowed(db, world, wolf, "werewolf_wolf_discuss")
    assert not ok
    assert reason == "werewolf_single_wolf_no_discussion"
    assert ((wolf.desires_json or {}).get("werewolf") or {}).get("known_wolves") == []


@pytest.mark.anyio
async def test_werewolf_win_runs_final_llm_speech_before_ending(db, monkeypatch):
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 3)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 24 * 60 + 18 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    for voter in agents:
        if voter.lifecycle_state != "dead":
            handle_werewolf_tool(db, world, voter, "werewolf_vote_by_name", {}, target=agents[0])
    db.commit()

    assert werewolf_state(world).get("winner") == "人类阵营"
    assert world.status == "running"

    async def complete_text(**kwargs):
        return LLMResult("终于结束了。我们至少把最后的危险挡下来了。", None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    runner = TurnRunner()
    result = await runner.run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech"
    assert db.get(type(world), world.world_id).status == "running"
    result = await runner.run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech"
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_final_speech").count() == 2
    assert db.get(type(world), world.world_id).status == "ended"


@pytest.mark.anyio
async def test_werewolf_final_speech_empty_llm_does_not_use_fallback(db, monkeypatch):
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 3)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 24 * 60 + 22 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["winner"] = "狼人阵营"
    state["final_speech_order"] = [agent.agent_id for agent in agents]
    state["final_speeches"] = {}
    state["final_speeches_complete"] = False
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    async def complete_text(**kwargs):
        return LLMResult("", None, {}, 1, "test", "timeout")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    result = await TurnRunner().run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech_retry"
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_final_speech").count() == 0
    assert werewolf_final_speech_actor_id(db, world) == agents[0].agent_id
    assert db.get(type(world), world.world_id).status == "running"


@pytest.mark.anyio
async def test_werewolf_final_speech_truncated_text_is_retried(db, monkeypatch):
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 3)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 24 * 60 + 22 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["winner"] = "狼人阵营"
    state["final_speech_order"] = [agent.agent_id for agent in agents]
    state["final_speeches"] = {}
    state["final_speeches_complete"] = False
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    async def complete_text(**kwargs):
        return LLMResult("哎呀呀，果然最后留下的还是我呢，真的", "哎呀呀，果然最后留下的还是我呢，真的", {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    result = await TurnRunner().run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech_retry"
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_final_speech").count() == 0
    assert werewolf_final_speech_actor_id(db, world) == agents[0].agent_id


def test_roundtable_sync_wakes_sleepers_so_discussion_can_run(db):
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}

    world.current_world_time_minutes = 24 * 60 + 12 * 60
    for agent in agents:
        agent.desires_json = {
            **(agent.desires_json or {}),
            "sleep_until_world_time": world.current_world_time_minutes + 300,
            "sleep_started_world_time": world.current_world_time_minutes - 60,
            "sleep_planned_minutes": 360,
        }
    db.flush()

    event_ids = sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "discussion")
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "wake" for event_id in event_ids)
    assert all(not ((agent.desires_json or {}).get("sleep_until_world_time")) for agent in agents)

    current_id = werewolf_current_discussion_actor_id(db, world)
    batch = TurnRunner()._regular_agent_batch(db, world)
    assert current_id
    assert [agent.agent_id for agent in batch] == [current_id]
