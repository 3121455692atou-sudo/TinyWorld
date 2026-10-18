from itertools import permutations

import pytest
from sqlalchemy import select

from app.core.models import Event, Memory
from app.knowledge.event_access import agent_can_access_event
from app.knowledge.perception import build_turn_context
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world
from app.world.werewolf import (
    _resolve_day_vote, handle_werewolf_tool, sync_werewolf_phase,
    werewolf_current_discussion_actor_id, werewolf_menu_tool_names, werewolf_state,
)


def set_roles(world, agents, roles, public=False):
    state = werewolf_state(world)
    state.update(roles=dict(zip((a.agent_id for a in agents), roles)),
                 public_revealed=public, roles_revealed_to_agents=public)
    world.settings_json = {**world.settings_json, "werewolf_state": state}


def reload_world(db, world):
    db.commit()
    db.expire_all()
    db.refresh(world)


def test_notice_reveal_survives_commit_and_repairs_pending_checkpoint(db):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "seer", "villager"])
    world.current_world_time_minutes = 1920
    sync_werewolf_phase(db, world)
    reload_world(db, world)
    assert werewolf_state(world)["public_revealed"] is True
    assert "pending" not in werewolf_state(world)["wolf_notice_announced"]["2"]
    state = werewolf_state(world)
    state.update(public_revealed=False, roles_revealed_to_agents=False)
    state["wolf_notice_announced"]["2"] = {"pending": True, "wolves_alive": True}
    world.settings_json = {**world.settings_json, "werewolf_state": state}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(world, "settings_json")
    reload_world(db, world)
    sync_werewolf_phase(db, world)
    reload_world(db, world)
    assert werewolf_state(world)["public_revealed"] is True
    assert "pending" not in werewolf_state(world)["wolf_notice_announced"]["2"]
    assert len(db.scalars(select(Event).where(Event.event_type == "werewolf_notice_board")).all()) == 1


def test_roundtable_announces_death_only_when_host_convenes(db):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "villager", "villager", "villager"])
    wolf, witness, other, victim = agents
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)
    world.current_world_time_minutes = 1920
    sync_werewolf_phase(db, world)
    text = f"为{victim.chosen_name}的死召开圆桌讨论"
    assert text not in build_turn_context(db, world, witness)[0]
    world.current_world_time_minutes = 2160
    sync_werewolf_phase(db, world)
    reload_world(db, world)
    announcements = db.scalars(select(Event).where(Event.event_type == "werewolf_roundtable_called")).all()
    assert len(announcements) == 1
    announcement = announcements[0]
    assert text in announcement.agent_visible_text
    assert werewolf_current_discussion_actor_id(db, world)
    assert all(agent_can_access_event(db, world, a.agent_id, announcement) for a in (wolf, witness, other))
    assert text in build_turn_context(db, world, witness)[0]
    assert not any(c["discovered_by_agent_ids"] for c in world.settings_json["corpse_records"])
    sync_werewolf_phase(db, world)
    assert len(db.scalars(select(Event).where(Event.event_type == "werewolf_roundtable_called")).all()) == 1


@pytest.mark.parametrize("order", list(permutations(["wolf", "guard", "seer"])))
def test_night_result_is_independent_of_model_completion_order(db, order):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "seer", "villager"], public=True)
    wolf, guard, seer, victim = agents
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    actions = {
        "wolf": (wolf, "werewolf_kill_by_name", victim),
        "guard": (guard, "werewolf_guard_protect_by_name", victim),
        "seer": (seer, "werewolf_seer_check_by_name", wolf),
    }
    for name in order:
        actor, tool, target = actions[name]
        handle_werewolf_tool(db, world, actor, tool, {}, target=target)
        reload_world(db, world)
        sync_werewolf_phase(db, world)
        assert victim.lifecycle_state == "alive"
    reload_world(db, world)
    assert werewolf_state(world)["night_kills"]["1"]["blocked"] is True
    assert not werewolf_state(world).get("winner")
    assert "werewolf_kill_by_name" not in werewolf_menu_tool_names(db, world, wolf)


def test_pending_attack_cannot_treat_failed_guard_call_as_a_voluntary_pass(db):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "villager", "villager"], public=True)
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, agents[0], "werewolf_kill_by_name", {}, target=agents[3])
    agents[1].tool_learning_json = {"last_llm_result_ok": False, "last_llm_world_time": 1350}
    world.current_world_time_minutes = 1920
    sync_werewolf_phase(db, world)
    assert agents[3].lifecycle_state == "alive"
    assert world.status == "paused"
    assert werewolf_state(world)["phase"] == "night"


def test_force_empty_vote_never_exiles_a_database_order_target(db):
    world, agents = _make_werewolf_world(db)
    world.current_world_time_minutes = 2520
    events = _resolve_day_vote(db, world, 2, force=True)
    assert all(a.lifecycle_state == "alive" for a in agents)
    assert world.status == "paused"
    assert not werewolf_state(world).get("vote_resolved", {}).get("2")
    assert any(db.get(Event, eid).event_type == "werewolf_host_incomplete" for eid in events)


@pytest.mark.anyio
@pytest.mark.parametrize("no_active_agents", [False, True])
async def test_incomplete_host_stops_before_any_paid_generation(db, monkeypatch, no_active_agents):
    from unittest.mock import AsyncMock
    from app.llm.openai_compatible import provider
    from app.simulation.turn_runner import TurnRunner
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "villager", "villager"], public=True)
    world.status = "running"
    world.current_world_time_minutes = 1320
    sync_werewolf_phase(db, world)
    handle_werewolf_tool(db, world, agents[0], "werewolf_kill_by_name", {}, target=agents[3])
    agents[1].tool_learning_json = {"last_llm_result_ok": False, "last_llm_world_time": 1350}
    world.current_world_time_minutes = 1919 if no_active_agents else 1920
    no_calls = AsyncMock(side_effect=AssertionError("Host failure must stop paid requests"))
    monkeypatch.setattr(provider, "complete_text", no_calls)
    if no_active_agents:
        result = await TurnRunner()._no_active_agent_result(db, world, [])
    else:
        result = await TurnRunner().run_one_step(db, world.world_id)
    assert result.status == "werewolf_host_incomplete"
    assert world.status == "paused"
    no_calls.assert_not_called()
