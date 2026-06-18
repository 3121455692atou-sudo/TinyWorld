from __future__ import annotations

from app.api.worlds import get_left_snapshot
from app.core.models import Event, Item, Location
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


def test_left_snapshot_returns_visible_location_items(db):
    world, _agents = make_world(db, agent_count=1)
    square = db.get(Location, f"{world.world_id}:central_square")
    assert square is not None
    db.add(
        Item(
            item_id="item_note",
            world_id=world.world_id,
            name="折好的纸条",
            description="写着一行留言。\n\n[market_item_meta]{\"internal\": true}",
            item_type="note",
            location_id=square.location_id,
        )
    )
    db.commit()

    snapshot = get_left_snapshot(world.world_id, db=db)

    square_row = next(item for item in snapshot["locations"] if item["location_id"] == square.location_id)
    assert square_row["item_count"] == 1
    assert square_row["items"] == [
        {
            "item_id": "item_note",
            "name": "折好的纸条",
            "description": "写着一行留言。",
            "item_type": "note",
        }
    ]


def test_event_refresh_response_carries_left_snapshot(db):
    from app.api.worlds import list_events

    world, agents = make_world(db, agent_count=1)
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    assert cafeteria is not None
    actor = agents[0]
    actor.location.location_id = cafeteria.location_id
    create_event(
        db,
        world=world,
        event_type="move",
        actor_agent_id=actor.agent_id,
        location_id=cafeteria.location_id,
        viewer_text=f"{actor.chosen_name} 移动到食堂。",
        importance=30,
    ).world_time = 510
    db.commit()

    payload = list_events(world.world_id, limit=5, latest=True, db=db)

    assert payload["left_snapshot"]["latest_event_world_time"] == 510
    row = next(item for item in payload["left_snapshot"]["locations"] if item["location_id"] == cafeteria.location_id)
    assert any(item["agent_id"] == actor.agent_id for item in row["occupants"])



def test_unified_refresh_payload_keeps_events_and_left_state_together(db):
    from app.api.worlds import refresh_world_state

    world, agents = make_world(db, agent_count=2)
    actor = agents[0]
    lake = db.get(Location, f"{world.world_id}:lake")
    assert lake is not None
    actor.location.location_id = lake.location_id
    event = create_event(
        db,
        world=world,
        event_type="move",
        actor_agent_id=actor.agent_id,
        location_id=lake.location_id,
        viewer_text=f"{actor.chosen_name} 来到湖边。",
        importance=30,
    )
    event.world_time = 574
    db.commit()

    payload = refresh_world_state(world.world_id, limit=20, latest=True, db=db)

    assert payload["events"][-1]["world_time"] == 574
    assert payload["world"]["current_world_time_minutes"] == 574
    assert payload["left_snapshot"]["world"]["current_world_time_minutes"] == 574
    agent_row = next(item for item in payload["agents"] if item["agent_id"] == actor.agent_id)
    assert agent_row["location_id"] == lake.location_id
    lake_row = next(item for item in payload["locations"] if item["location_id"] == lake.location_id)
    assert any(item["agent_id"] == actor.agent_id for item in lake_row["occupants"])
    assert payload["event_delete_state"]["undo_available"] is False


def test_unified_refresh_uses_one_event_stream_and_private_locations(db):
    from app.api.worlds import refresh_world_state

    world, agents = make_world(db, agent_count=2)
    actor = agents[0]
    home_location_id = actor.location.location_id
    lake = db.get(Location, f"{world.world_id}:lake")
    assert lake is not None
    create_event(
        db,
        world=world,
        event_type="move",
        actor_agent_id=actor.agent_id,
        location_id=lake.location_id,
        viewer_text=f"{actor.chosen_name} 来到湖边。",
        importance=30,
    ).world_time = 510
    create_event(
        db,
        world=world,
        event_type="observe",
        actor_agent_id=agents[1].agent_id,
        location_id=home_location_id,
        viewer_text=f"{agents[1].chosen_name} 在家里观察四周。",
        importance=5,
    ).world_time = 515
    db.commit()

    payload = refresh_world_state(
        world.world_id,
        limit=20,
        latest=True,
        include_private=True,
        db=db,
    )

    assert "location_events" not in payload
    assert {lake.location_id, home_location_id} <= {event["location_id"] for event in payload["events"]}
    assert home_location_id in {location["location_id"] for location in payload["locations"]}
