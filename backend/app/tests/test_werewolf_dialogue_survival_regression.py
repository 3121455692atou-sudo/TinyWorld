from __future__ import annotations

import pytest

from app.agents.v5_state import default_wallet
from app.content.presets import (
    DEFAULT_CORE_TOOLSET_ID,
    DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID,
    WEREWOLF_WORLD_TOOLSET_ID,
    WEREWOLF_WORLDVIEW_ID,
    worldview_by_id,
)
from app.core.config import settings
from app.core.models import Event, Location
from app.llm.openai_compatible import provider
from app.llm.provider_base import LLMResult
from app.simulation.turn_runner import TurnRunner
from app.tests.conftest import make_world
from app.world.seed_world import seed_items, seed_locations, world_location_id
from app.world.werewolf import initialize_werewolf_game, sync_werewolf_phase, werewolf_current_discussion_actor_id, werewolf_phase, werewolf_state


def _make_werewolf_world(session, agent_count: int = 4):
    world, agents = make_world(session, agent_count)
    worldview = worldview_by_id(WEREWOLF_WORLDVIEW_ID)
    seed_locations(session, world.world_id, worldview=worldview)
    seed_items(session, world.world_id, worldview=worldview)
    session.flush()
    world.current_world_time_minutes = 8 * 60
    world.settings_json = {
        "worldview_id": WEREWOLF_WORLDVIEW_ID,
        "worldview_rule_parameters": worldview["rule_parameters"],
        "speed": "fast",
        "survival_difficulty": "NORMAL",
        "core_toolset_enabled": True,
        "core_toolset_id": DEFAULT_CORE_TOOLSET_ID,
        "optional_toolset_ids": [DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID],
        "world_toolset_id": WEREWOLF_WORLD_TOOLSET_ID,
        "initial_location_id": "village_square",
        "werewolf_mode_enabled": True,
    }
    square_id = world_location_id(world.world_id, "village_square")
    square = session.get(Location, square_id)
    assert square is not None
    for index, agent in enumerate(agents):
        agent.wallet_json = {**default_wallet(), "housing": {"home_location_id": world_location_id(world.world_id, f"villager_room_{index + 1}")}}
        agent.desires_json = {"awake_since_world_time": world.current_world_time_minutes}
        agent.location.location_id = square_id
        agent.location.location = square
        agent.dynamic_state.energy = 80
        agent.dynamic_state.satiety = 80
        agent.dynamic_state.hydration = 80
        agent.dynamic_state.health = 100
        agent.dynamic_state.last_decay_world_time = world.current_world_time_minutes
    initialize_werewolf_game(session, world)
    session.flush()
    return world, agents


def test_day_two_morning_sync_does_not_keep_dragging_players_back_from_cafeteria(db):
    world, agents = _make_werewolf_world(db, 4)
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "morning")

    cafeteria_id = world_location_id(world.world_id, "cafeteria")
    cafeteria = db.get(Location, cafeteria_id)
    assert cafeteria is not None
    moved = agents[0]
    moved.location.location_id = cafeteria_id
    moved.location.location = cafeteria
    db.flush()

    # The previous fix reconciled every morning tick by teleporting everyone back
    # to village_square.  That made agents choose "go to cafeteria" forever and
    # never actually eat.  Same-phase sync may recover overnight needs, but it must
    # not override normal breakfast movement.
    sync_werewolf_phase(db, world)

    assert moved.location.location_id == cafeteria_id


def test_day_two_morning_recovery_also_repairs_saves_already_inside_morning_phase(db):
    world, agents = _make_werewolf_world(db, 4)
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    state = werewolf_state(world)
    state["day"] = 2
    state["phase"] = "morning"
    state.pop("overnight_recovered", None)
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}

    exhausted = agents[0]
    exhausted.lifecycle_state = "critical"
    exhausted.dynamic_state.energy = 0
    exhausted.dynamic_state.satiety = 0
    exhausted.dynamic_state.hydration = 0
    exhausted.dynamic_state.health = 5
    exhausted.dynamic_state.zero_energy_since = 24 * 60
    exhausted.dynamic_state.zero_satiety_since = 24 * 60
    exhausted.dynamic_state.zero_hydration_since = 24 * 60
    exhausted.dynamic_state.last_decay_world_time = 18 * 60
    exhausted.desires_json = {
        **(exhausted.desires_json or {}),
        "awake_since_world_time": 8 * 60,
        "unconscious_until_world_time": world.current_world_time_minutes + 300,
        "unconscious_started_world_time": world.current_world_time_minutes - 20,
    }

    sync_werewolf_phase(db, world)
    recovered_state = werewolf_state(world)

    assert recovered_state["overnight_recovered"]["2"] is True
    assert exhausted.lifecycle_state == "alive"
    assert exhausted.dynamic_state.energy >= 72
    assert exhausted.dynamic_state.satiety >= 38
    assert exhausted.dynamic_state.hydration >= 38
    assert exhausted.dynamic_state.last_decay_world_time == world.current_world_time_minutes
    assert exhausted.desires_json["awake_since_world_time"] == world.current_world_time_minutes
    assert "unconscious_until_world_time" not in exhausted.desires_json


def test_day_two_body_found_announcement_is_idempotent_on_same_morning_sync(db):
    world, agents = _make_werewolf_world(db, 4)
    target = agents[1]
    target.lifecycle_state = "dead"
    target.death_cause = "狼人夜间袭击出局"
    target.death_at_world_time = 24 * 60 + 5 * 60
    state = werewolf_state(world)
    state["night_kills"] = {
        "1": {
            "target_agent_id": target.agent_id,
            "blocked": False,
            "location_id": target.location.location_id,
        }
    }
    state["public_revealed"] = False
    state["roles_revealed_to_agents"] = False
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    world.current_world_time_minutes = 24 * 60 + 8 * 60

    first_ids = sync_werewolf_phase(db, world)
    second_ids = sync_werewolf_phase(db, world)

    first_types = [db.get(Event, event_id).event_type for event_id in first_ids if db.get(Event, event_id)]
    second_types = [db.get(Event, event_id).event_type for event_id in second_ids if db.get(Event, event_id)]
    assert first_types.count("werewolf_body_found") == 1
    assert "werewolf_body_found" not in second_types
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_body_found").count() == 1
    assert werewolf_state(world)["body_found_announced"]["2"]["target_agent_id"] == target.agent_id


def test_werewolf_hosted_night_sleep_completes_with_dream_summary_at_morning(db):
    world, agents = _make_werewolf_world(db, 4)
    world.current_world_time_minutes = 22 * 60
    night_ids = sync_werewolf_phase(db, world)
    night_types = [db.get(Event, event_id).event_type for event_id in night_ids if db.get(Event, event_id)]
    assert "sleep_start" in night_types

    world.current_world_time_minutes = 24 * 60 + 8 * 60
    morning_ids = sync_werewolf_phase(db, world)
    morning_types = [db.get(Event, event_id).event_type for event_id in morning_ids if db.get(Event, event_id)]

    assert "wake" in morning_types
    assert "dream_summary" in morning_types
    assert werewolf_state(world)["overnight_recovered"]["2"] is True
    assert any((agent.desires_json or {}).get("last_sleep_end_world_time") == world.current_world_time_minutes for agent in agents if agent.lifecycle_state != "dead")


@pytest.mark.anyio
async def test_roundtable_turn_does_not_create_fallback_dialogue_when_model_action_parse_fails(db, monkeypatch):
    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = _make_werewolf_world(db, 4)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    world.current_world_time_minutes = 24 * 60 + 12 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "discussion")
    current_id = werewolf_current_discussion_actor_id(db, world)
    assert current_id

    # Simulate a bad/empty model response.  The hosted phase must not create
    # avatar dialogue unless the LLM produced the actual spoken text.
    async def fail_complete_text(*args, **kwargs):
        return LLMResult("", None, {}, 1, "test", "forced parse failure")

    monkeypatch.setattr(provider, "complete_text", fail_complete_text)
    turn = await TurnRunner().run_one_step(db, world.world_id)

    event_types = [db.get(Event, event_id).event_type for event_id in turn.event_ids if db.get(Event, event_id)]
    assert "werewolf_speech" not in event_types
    assert current_id not in turn.acted_agent_ids


def test_discussion_sync_revives_unconscious_living_players_for_hosted_speech(db):
    world, agents = _make_werewolf_world(db, 4)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    world.current_world_time_minutes = 24 * 60 + 12 * 60
    troubled = agents[0]
    troubled.lifecycle_state = "critical"
    troubled.dynamic_state.energy = 0
    troubled.dynamic_state.satiety = 0
    troubled.dynamic_state.hydration = 0
    troubled.dynamic_state.health = 2
    troubled.dynamic_state.last_decay_world_time = 18 * 60
    troubled.desires_json = {
        **(troubled.desires_json or {}),
        "unconscious_until_world_time": world.current_world_time_minutes + 600,
        "unconscious_started_world_time": world.current_world_time_minutes - 30,
    }

    sync_werewolf_phase(db, world)

    assert troubled.lifecycle_state == "alive"
    assert troubled.dynamic_state.energy >= 42
    assert troubled.dynamic_state.satiety >= 25
    assert troubled.dynamic_state.hydration >= 25
    assert "unconscious_until_world_time" not in troubled.desires_json
    assert troubled.location.location_id == world_location_id(world.world_id, "discussion_hall")
