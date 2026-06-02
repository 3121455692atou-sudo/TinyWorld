from __future__ import annotations

import pytest

from app.agents.state import initial_dynamic_state
from app.core import database
from app.core.models import Agent, AgentLocation, AgentTrait, World
from app.simulation.reaction_queue import reaction_queue
from app.world.seed_world import seed_items, seed_locations


@pytest.fixture()
def db(tmp_path):
    database.configure_database(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    database.init_db(drop=True)
    reaction_queue.clear("world_test")
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def make_world(session, agent_count: int = 3):
    world = World(world_id="world_test", name="测试世界", status="paused", seed=1234, current_world_time_minutes=0, settings_json={})
    session.add(world)
    session.flush()
    seed_locations(session, world.world_id)
    seed_items(session, world.world_id)
    names = ["林见舟", "桃枝", "许澈", "南枝"]
    appearances = ["白发、红围巾、灰色长外套", "短发、黄围裙、眼神明亮", "戴圆眼镜、深色斗篷、动作轻", "银色短发、旧靴子、袖口别着羽毛"]
    agents = []
    for index in range(agent_count):
        agent = Agent(
            agent_id=f"agent_{index}",
            world_id=world.world_id,
            lifecycle_state="alive",
            model_alias="world_agent",
            chosen_name=names[index],
            gender_identity="不愿公开",
            gender_publicity=False,
            gender_expression="中性",
            appearance_full=f"{names[index]}看起来{appearances[index]}，神情安静，正在观察周围。",
            appearance_short=appearances[index],
            avatar_hint_json={"color": "#2364aa", "tags": appearances[index].split("、")[:2]},
            speaking_style="简短温和",
            personality_seed="谨慎但愿意交流。",
            initial_goal="先了解世界。",
            intro_policy="open" if index == 1 else "selective",
        )
        session.add(agent)
        session.flush()
        session.add(AgentTrait(agent_id=agent.agent_id))
        session.add(initial_dynamic_state(agent.agent_id, 0))
        session.add(AgentLocation(agent_id=agent.agent_id, location_id=f"{world.world_id}:central_square", arrived_at_world_time=0))
        agents.append(agent)
    session.flush()
    return world, agents
