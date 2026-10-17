import asyncio
import importlib
from unittest.mock import AsyncMock

import pytest

from app.llm.action_protocol import ActionOption
from app.llm.provider_base import LLMResult
from conftest import make_world

runner = importlib.import_module("app.simulation.turn_runner")


@pytest.mark.parametrize("phase", ["普通行动", "村庄公开会议", "夜间行动"])
def test_identity_and_custom_prompt_survive_action_format_retry(db, monkeypatch, phase):
    world, agents = make_world(db, 1)
    agent = agents[0]
    agent.chosen_name = "要乐奈"
    agent.custom_system_prompt = "你是要乐奈。说话简短。"
    world.settings_json = {"collective_core_prompt": "大家原本就认识。"}
    complete = AsyncMock(side_effect=[
        LLMResult("没有行动头", "没有行动头", {}, 1, "test"),
        LLMResult("[01]\n我想选祥子。", "[01]\n我想选祥子。", {}, 1, "test"),
    ])
    monkeypatch.setattr(runner.provider, "complete_text", complete)
    result = asyncio.run(runner.TurnRunner()._request_action_choice(
        agent, world=world, system_prompt=phase, user_prompt="请选择行动",
        options=[ActionOption(1, "发言", "werewolf_wolf_discuss", text_slot="speech", text_required=True)],
        temperature=0.5,
    ))
    assert result.parsed_object is not None
    assert complete.await_count == 2
    prompts = [call.kwargs["system_prompt"] for call in complete.await_args_list]
    assert prompts[0] == prompts[1]
    assert prompts[0].startswith("你是要乐奈，")
    assert "不要用“她”“他”“TA”指代自己" in prompts[0]
    assert "说话简短。" in prompts[0]
    assert "大家原本就认识。" in prompts[0]
    assert prompts[0].endswith(phase)
