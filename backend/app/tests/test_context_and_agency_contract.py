import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.models import Event, Memory
from app.knowledge.perception import build_turn_context, _memory_prompt_lines
from app.llm.context_budget import pack_text_context
from app.llm.openai_compatible import apply_haiku_context_guard
from app.llm.runtime import agent_llm_generation, normalize_llm_generation
from app.llm.action_protocol import ActionOption
from app.llm.provider_base import LLMResult
from app.simulation.turn_runner import TurnRunner
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world
from app.tests.test_werewolf_host_resolution import set_roles
from app.tools.registry import available_tools
from app.world.werewolf import sync_werewolf_phase


def test_context_defaults_overrides_and_haiku_cap():
    assert normalize_llm_generation()["context_window_tokens"] == 256000
    world = SimpleNamespace(settings_json={"llm_generation": {"context_window_tokens": 180000}})
    agent = SimpleNamespace(model_name="model", tool_learning_json={})
    assert agent_llm_generation(agent, world)["context_window_tokens"] == 180000
    agent.tool_learning_json = {"llm_generation": {"context_window_tokens": 64000}}
    assert agent_llm_generation(agent, world)["context_window_tokens"] == 64000
    agent.model_name = "anthropic/claude-haiku-5.5"
    agent.tool_learning_json = {}
    assert agent_llm_generation(agent, world)["context_window_tokens"] == 99000


def test_budget_keeps_recent_complete_memories_and_fixed_prompt():
    entries = [f"- 第{i}次亲历：" + "中文内容" * 100 for i in range(120)]
    payload = {"model": "anthropic/claude-haiku-5.5", "max_tokens": 32000, "messages": [
        {"role": "system", "content": "你是本人。"},
        {"role": "user", "content": "【身份】姓名不能变\n【记忆】\n" + "\n".join(entries) + "\n【记忆使用规则】\n只信有来源的经历\n【行动选项】[01]观察"},
    ]}
    assert pack_text_context(payload, 256000) is None
    text = payload["messages"][1]["content"]
    assert entries[-1] in text and entries[0] not in text
    assert "姓名不能变" in text and "[01]观察" in text
    assert payload["max_tokens"] == 8192
    assert apply_haiku_context_guard(payload) is None
    assert len(json.dumps(payload["messages"], ensure_ascii=False).encode()) + 2048 + 8192 < 99000


def test_memory_priority_is_age_not_old_importance():
    rows = [Memory(memory_id=i, content=f"完整经历{i}", created_world_time=i, importance=100 if i < 3 else 1) for i in range(6)]
    lines = _memory_prompt_lines(rows, limit=2)
    assert "完整经历4" in lines[0] and "完整经历5" in lines[1]


def test_context_does_not_cut_memories_to_legacy_24_or_drop_archive(db):
    world, agents = _make_werewolf_world(db)
    world.settings_json = {**world.settings_json, "prompt_settings": {"memory_limit": 24}}
    for i in range(60):
        db.add(Memory(agent_id=agents[0].agent_id, memory_type="short", content=f"自己的亲历记录{i}，" + "完整对话" * 90,
                      importance=50, created_world_time=500+i, archived=i < 30))
    db.flush()
    prompt, _ = build_turn_context(db, world, agents[0])
    assert all(f"自己的亲历记录{i}，" in prompt for i in range(60))
    assert "完整对话" * 90 in prompt
    assert "我叫椎名立希，住在5号小屋" not in prompt


@pytest.mark.parametrize("public", [False, True])
def test_hosted_night_sleeps_residents_and_keeps_role_actors_awake(db, public):
    from app.world.werewolf import werewolf_menu_tool_names
    from app.world.visibility import mark_name_known
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "seer", "villager"], public=public)
    # This save starts with everyone acquainted; secret-role assignment itself
    # must not grant a stranger's name merely to populate an attack menu.
    for target in agents[1:]:
        mark_name_known(db, agents[0].agent_id, target, 480, "test")
    world.current_world_time_minutes = 1320
    ids = sync_werewolf_phase(db, world)
    sleeping = agents[3:] if public else agents[1:]
    awake = agents[:3] if public else agents[:1]
    for agent in sleeping:
        assert agent.desires_json["sleep_until_world_time"] == 1920
        assert agent.location.location_id.endswith(":dormitory")
    for agent in awake:
        assert not agent.desires_json.get("sleep_until_world_time")
        assert werewolf_menu_tool_names(db, world, agent)
    assert agents[0].location.location_id.endswith(":wolf_den")
    assert any(db.get(Event, eid).event_type == "sleep_start" for eid in ids)
    sleep_starts = {a.agent_id:a.desires_json.get("sleep_started_world_time") for a in sleeping}
    world.current_world_time_minutes += 4
    repeated = sync_werewolf_phase(db, world)
    assert not any(db.get(Event, eid).event_type == "sleep_start" for eid in repeated)
    assert {a.agent_id:a.desires_json.get("sleep_started_world_time") for a in sleeping} == sleep_starts
    active = TurnRunner()._regular_agent_batch(db, world)
    assert {a.agent_id for a in active} == {a.agent_id for a in awake}
    db.flush()
    wolf_tools = {t.tool_name for t in available_tools(agents[0], agents[0].location.location, session=db)}
    assert "move_to_location" not in wolf_tools
    assert "werewolf_kill_by_name" in wolf_tools


def test_dawn_does_not_relocate_or_invent_body_recovery(db):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "seer", "villager"], public=True)
    # No night was actually simulated: a morning sync must not fabricate rest.
    before = [(a.location.location_id, a.dynamic_state.energy) for a in agents]
    world.current_world_time_minutes = 1920
    sync_werewolf_phase(db, world)
    assert [(a.location.location_id, a.dynamic_state.energy) for a in agents] == before
    assert TurnRunner()._werewolf_phase_agent_batch(db, world, agents) is None
    tools = {t.tool_name for t in available_tools(agents[-1], agents[-1].location.location, session=db)}
    assert "move_to_location" in tools or "return_home" in tools


def test_choice_uses_personal_identity_and_grounding_including_format_retry(db, monkeypatch):
    from app.llm.openai_compatible import provider
    world, agents = _make_werewolf_world(db)
    agent = agents[0]
    agent.custom_system_prompt = "说话简短。"
    fake = AsyncMock(side_effect=[LLMResult("格式错误", None, {}, 1, "test"), LLMResult("[01]", None, {}, 1, "test")])
    monkeypatch.setattr(provider, "complete_text", fake)
    asyncio.run(TurnRunner()._request_action_choice(agent, world=world, system_prompt="投票协议", user_prompt="已知经历",
        options=[ActionOption(option_id=1, tool_name="do_nothing", label="等待")], temperature=0.5))
    for call in fake.call_args_list:
        system = call.kwargs["system_prompt"]
        assert system.startswith(f"你是{agent.chosen_name}。")
        assert "不是替一群人物续写故事的作者" in system
        assert "说话简短。" in system and "投票协议" in system
        assert call.kwargs["context_window_tokens"] == 256000


def test_night_host_wakes_sleeping_guard_and_does_not_skip_guard_resolution(db):
    from app.world.werewolf import handle_werewolf_tool, werewolf_state
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "villager", "villager"], public=True)
    world.status = "running"
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, agents[0], "werewolf_kill_by_name", {}, target=agents[-1])
    assert agents[-1].lifecycle_state == "alive"
    agents[1].desires_json = {**agents[1].desires_json, "sleep_until_world_time": 2100, "sleep_started_world_time": 1320}
    sync_werewolf_phase(db, world)
    assert not agents[1].desires_json.get("sleep_until_world_time")
    assert agents[1] in TurnRunner()._regular_agent_batch(db, world)
    world.current_world_time_minutes = 1920
    ids = sync_werewolf_phase(db, world)
    assert agents[-1].lifecycle_state == "alive"
    assert any(db.get(Event, eid).event_type == "werewolf_host_incomplete" for eid in ids)
    assert world.status == "paused"


@pytest.mark.parametrize("finished_at", [1330, 1915])
def test_finished_night_roles_really_sleep_before_dawn(db, monkeypatch, finished_at):
    from app.world import werewolf
    from app.simulation import turn_runner as runner_module
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "villager", "villager", "villager"], public=False)
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    world.current_world_time_minutes = finished_at
    state = werewolf.werewolf_state(world)
    state.setdefault("night_kills", {})["1"] = {"blocked": True}
    world.settings_json = {**world.settings_json, "werewolf_state": state}
    monkeypatch.setattr(runner_module, "maybe_create_narration", AsyncMock(return_value=[]))
    runner = TurnRunner()
    assert runner._regular_agent_batch(db, world) == []
    assert world.current_world_time_minutes == finished_at
    result = asyncio.run(runner._no_active_agent_result(db, world, []))
    assert world.current_world_time_minutes == 1920
    events = [db.get(Event, eid) for eid in result.event_ids]
    assert any(e.event_type == "sleep_start" and e.actor_agent_id == agents[0].agent_id for e in events)
    assert any(e.event_type == "wake" and e.actor_agent_id == agents[0].agent_id and e.payload["sleep_minutes"] == 1920 - finished_at for e in events)
    assert not agents[0].desires_json.get("sleep_until_world_time")
    assert agents[0].location.location_id.endswith(":dormitory")


def test_unrevealed_wolves_get_private_discussion_while_other_residents_sleep(db):
    from app.knowledge.event_access import agent_can_access_event
    from app.world.werewolf import handle_werewolf_tool, werewolf_menu_tool_names
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "werewolf", "villager", "villager"], public=False)
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    assert {a.agent_id for a in TurnRunner()._regular_agent_batch(db, world)} == {a.agent_id for a in agents[:2]}
    assert all("werewolf_wolf_discuss" in werewolf_menu_tool_names(db, world, a) for a in agents[:2])
    ids = handle_werewolf_tool(db, world, agents[0], "werewolf_wolf_discuss", {"speech": "今晚先商量目标。"})
    for eid in ids:
        event = db.get(Event, eid)
        assert not agent_can_access_event(db, world, agents[-1].agent_id, event)
