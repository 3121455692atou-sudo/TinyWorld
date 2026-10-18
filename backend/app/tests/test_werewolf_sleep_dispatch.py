import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.models import Event
from app.knowledge.event_access import agent_can_access_event
from app.simulation.turn_runner import TurnRunner
from app.tests.test_werewolf_dialogue_survival_regression import _make_werewolf_world
from app.tests.test_werewolf_host_resolution import set_roles
from app.world import werewolf


def _sleep(agent, started=1200, until=1437):
    agent.desires_json = {**agent.desires_json, "sleep_started_world_time": started,
        "sleep_until_world_time": until, "sleep_planned_minutes": until - started,
        "sleep_requested_minutes": until - started, "sleep_quality": "normal"}


def _finish_night(db, world, agents, public):
    wolf, guard, seer, victim = agents
    if public:
        werewolf.handle_werewolf_tool(db, world, guard, "werewolf_guard_protect_by_name", {}, target=victim)
        werewolf.handle_werewolf_tool(db, world, seer, "werewolf_seer_check_by_name", {}, target=wolf)
    werewolf.handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)
    db.flush()


@pytest.mark.parametrize("public", [False, True])
def test_finished_night_roles_stay_asleep_across_repeated_sync(db, public):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "seer", "villager"], public=public)
    world.current_world_time_minutes = 1320
    werewolf.sync_werewolf_phase(db, world)
    _finish_night(db, world, agents, public)
    world.current_world_time_minutes = 1352
    werewolf.finish_werewolf_night_rest(db, world)
    living = [a for a in agents if a.lifecycle_state != "dead"]
    starts = {a.agent_id: a.desires_json["sleep_started_world_time"] for a in living}
    homes = {a.agent_id: a.wallet_json["housing"]["home_location_id"] for a in living}
    # Actual failing save: these were unrelated residents' old wake deadlines.
    for minute in [1437, 1568, 1628]:
        world.current_world_time_minutes = minute
        ids = werewolf.sync_werewolf_phase(db, world)
        ids += werewolf.finish_werewolf_night_rest(db, world)
        assert not any(db.get(Event, eid).event_type in {"wake", "sleep_start", "dream_summary"} for eid in ids)
        assert {a.agent_id: a.desires_json["sleep_started_world_time"] for a in living} == starts
        assert all(a.desires_json["sleep_until_world_time"] == 1920 for a in living)
        assert {a.agent_id: a.location.location_id for a in living} == homes


def test_existing_sleep_is_extended_through_hosted_night(db, monkeypatch):
    from app.simulation import turn_runner
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "villager", "villager", "villager"], public=False)
    for agent, until in zip(agents[1:], [1437, 1568, 1628]):
        _sleep(agent, until=until)
    world.current_world_time_minutes = 1320
    werewolf.sync_werewolf_phase(db, world)
    assert all(a.desires_json["sleep_until_world_time"] == 1920 for a in agents[1:])
    assert all(a.desires_json["sleep_started_world_time"] == 1200 for a in agents[1:])
    _finish_night(db, world, agents, False)
    world.current_world_time_minutes = 1352
    narrator = AsyncMock(return_value=[])
    monkeypatch.setattr(turn_runner, "maybe_create_narration", narrator)
    result = asyncio.run(TurnRunner()._no_active_agent_result(db, world, []))
    assert world.current_world_time_minutes == 1920
    wakes = [db.get(Event, eid) for eid in result.event_ids if db.get(Event, eid).event_type == "wake"]
    assert len(wakes) == 3
    assert all(not e.payload["interrupted"] for e in wakes)
    assert narrator.call_count == 1


@pytest.mark.parametrize("minute, reason", [(1320, "werewolf_night_action"),
    (2160, "werewolf_roundtable"), (2520, "werewolf_vote")])
def test_host_wake_has_reason_and_never_claims_another_resident_woke_them(db, minute, reason):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "guard", "seer", "villager"], public=True)
    guard = agents[1]
    _sleep(guard, started=minute-30, until=minute+90)
    world.current_world_time_minutes = minute
    ids = werewolf.sync_werewolf_phase(db, world)
    wake = next(db.get(Event, eid) for eid in ids if db.get(Event, eid).event_type == "wake")
    assert wake.payload["wake_reason"] == reason
    assert wake.payload["sleep_minutes"] == 30
    assert "被叫醒" not in wake.viewer_text
    assert wake.payload["interrupted"]
    if reason == "werewolf_night_action":
        assert not agent_can_access_event(db, world, agents[-1].agent_id, wake)
        assert werewolf.werewolf_menu_tool_names(db, world, guard)


def test_wolf_waiting_for_next_speaker_stays_awake(db):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "werewolf", "villager", "villager"], public=False)
    world.current_world_time_minutes = 1320
    werewolf.sync_werewolf_phase(db, world)
    werewolf.handle_werewolf_tool(db, world, agents[0], "werewolf_wolf_discuss", {"speech": "先商量目标。"})
    world.current_world_time_minutes += 4
    ids = werewolf.sync_werewolf_phase(db, world)
    assert all(not a.desires_json.get("sleep_until_world_time") for a in agents[:2])
    assert not any(db.get(Event, eid).event_type in {"sleep_start", "wake"} for eid in ids)
    assert [a.agent_id for a in TurnRunner()._regular_agent_batch(db, world)] == [agents[1].agent_id]


@pytest.mark.parametrize("public", [False, True])
def test_witch_wakes_once_when_attack_creates_a_real_decision(db, public):
    world, agents = _make_werewolf_world(db)
    set_roles(world, agents, ["werewolf", "witch", "villager", "villager"], public=public)
    wolf, witch, _, victim = agents
    world.current_world_time_minutes = 1320
    werewolf.sync_werewolf_phase(db, world)
    assert witch.desires_json["sleep_until_world_time"] == 1920
    attack_ids = werewolf.handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)
    world.current_world_time_minutes = 1330
    ids = werewolf.sync_werewolf_phase(db, world)
    # The attack itself wakes and privately informs the witch. Reconciliation
    # must not wake her again, nor put her back to sleep before her decision.
    prompts = [db.get(Event, eid) for eid in attack_ids if db.get(Event, eid).event_type == "werewolf_witch_save_prompt"]
    assert len(prompts) == 1 and prompts[0].actor_agent_id == witch.agent_id
    assert prompts[0].target_agent_id == victim.agent_id
    assert not agent_can_access_event(db, world, agents[2].agent_id, prompts[0])
    assert not any(db.get(Event, eid).event_type == "wake" for eid in ids)
    assert not witch.desires_json.get("sleep_until_world_time")
    assert "werewolf_witch_save_latest" in werewolf.werewolf_menu_tool_names(db, world, witch)
    werewolf.handle_werewolf_tool(db, world, witch, "werewolf_skip_night_action", {})
    werewolf.sync_werewolf_phase(db, world)
    assert witch.desires_json["sleep_until_world_time"] == 1920
    world.current_world_time_minutes = 1340
    assert not any(db.get(Event, eid).event_type == "wake" for eid in werewolf.sync_werewolf_phase(db, world))
