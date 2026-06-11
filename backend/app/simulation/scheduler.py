from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from contextlib import suppress
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app.api.websocket import manager
from app.api.serializers import world_summary
from app.core.database import SessionLocal
from app.core.models import World
from app.simulation.reaction_queue import reaction_queue
from app.simulation.turn_runner import turn_runner


logger = logging.getLogger(__name__)
SPEED_SECONDS = {"slow": 3.0, "fast": 0.5}
MAX_CONSECUTIVE_STEP_FAILURES = 3


class SimulationManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._step_locks: dict[str, asyncio.Lock] = {}

    async def step(self, world_id: str) -> dict:
        lock = self._step_locks.setdefault(world_id, asyncio.Lock())
        async with lock:
            with SessionLocal() as session:
                result = await turn_runner.run_one_step(session, world_id)
                session.commit()
                world = session.get(World, world_id)
                payload = {
                    "status": result.status,
                    "event_ids": result.event_ids,
                    "narration_event_ids": result.narration_event_ids,
                    "acted_agent_id": result.acted_agent_id,
                    "acted_agent_ids": result.acted_agent_ids,
                }
                message = {"type": "world_state_updated", "world_id": world_id, "result": payload}
                if world:
                    message["world"] = world_summary(world, session)
                await manager.broadcast(world_id, message)
                return payload

    def start(self, world_id: str, speed: str = "slow") -> None:
        if world_id in self._tasks and not self._tasks[world_id].done():
            return
        self._tasks[world_id] = asyncio.create_task(self._run_loop(world_id, speed))

    def is_running(self, world_id: str) -> bool:
        task = self._tasks.get(world_id)
        return bool(task and not task.done())

    def world_lock(self, world_id: str) -> asyncio.Lock:
        return self._step_locks.setdefault(world_id, asyncio.Lock())

    @asynccontextmanager
    async def mutation_lock(self, world_id: str) -> AsyncIterator[None]:
        lock = self.world_lock(world_id)
        async with lock:
            yield

    async def pause(self, world_id: str) -> None:
        task = self._tasks.get(world_id)
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def stop(self, world_id: str) -> None:
        await self.pause(world_id)
        reaction_queue.clear(world_id)

    async def _run_loop(self, world_id: str, speed: str) -> None:
        delay = SPEED_SECONDS.get(speed, SPEED_SECONDS["slow"])
        consecutive_failures = 0
        while True:
            with SessionLocal() as session:
                world = session.get(World, world_id)
                if not world or world.status != "running":
                    return
                settings_json = world.settings_json or {}
                delay = SPEED_SECONDS.get(str(settings_json.get("speed") or speed), SPEED_SECONDS["slow"])
                if settings_json.get("werewolf_mode_enabled"):
                    delay = SPEED_SECONDS["fast"]
            try:
                result = await self.step(world_id)
                consecutive_failures = 0
                if result.get("status") == "llm_stalled":
                    return
            except Exception:
                consecutive_failures += 1
                logger.exception("simulation step failed for world %s", world_id)
                if consecutive_failures >= MAX_CONSECUTIVE_STEP_FAILURES:
                    with SessionLocal() as session:
                        world = session.get(World, world_id)
                        if world and world.status == "running":
                            world.status = "paused"
                            session.commit()
                            await manager.broadcast(
                                world_id,
                                {
                                    "type": "simulation_status_changed",
                                    "status": "paused",
                                    "error": f"simulation step failed {consecutive_failures} times; world paused",
                                    "world": world_summary(world, session),
                                },
                            )
                    return
                await asyncio.sleep(delay)
            await asyncio.sleep(delay)


simulation_manager = SimulationManager()
