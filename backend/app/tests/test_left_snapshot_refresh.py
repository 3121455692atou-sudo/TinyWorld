from __future__ import annotations

from app.api.worlds import get_left_snapshot
from app.core.models import Event, Location
from app.events.event_store import create_event
from conftest import make_world


def test_left_snapshot_returns_fresh_clock_agents_and_location_occupants(db):
    world, agents = make_world(db, agent_count=3)
    actor = agents[0]
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    assert cafeteria is not None
    actor.location.location_id = cafeteria.location_id
    actor.location.location = cafeteria
    world.current_world_time_minutes = 480
    create_event(
        db,
        world=world,
        event_type="move",
        actor_agent_id=actor.agent_id,
        location_id=cafeteria.location_id,
        viewer_text=f"{actor.chosen_name} 走向了公共食堂。",
        importance=30,
    ).world_time = 615
    db.commit()

    snapshot = get_left_snapshot(world.world_id, db=db)

    assert snapshot["world"]["current_world_time_minutes"] == 615
    agent_row = next(item for item in snapshot["agents"] if item["agent_id"] == actor.agent_id)
    assert agent_row["location_id"] == cafeteria.location_id
    cafeteria_row = next(item for item in snapshot["locations"] if item["location_id"] == cafeteria.location_id)
    assert any(item["agent_id"] == actor.agent_id for item in cafeteria_row["occupants"])
    square_row = next(item for item in snapshot["locations"] if item["location_id"].endswith(":central_square"))
    assert all(item["agent_id"] != actor.agent_id for item in square_row["occupants"])
