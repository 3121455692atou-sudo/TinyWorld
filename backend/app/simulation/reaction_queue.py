from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(slots=True)
class ReactionTask:
    agent_id: str
    trigger_text: str
    chain_depth: int = 0
    source_agent_id: str | None = None
    created_world_time: int | None = None
    event_ids: tuple[int, ...] = ()
    recipient_location_id: str | None = None
    source_location_id: str | None = None


class ReactionQueue:
    def __init__(self) -> None:
        self._queues: dict[str, deque[ReactionTask]] = defaultdict(deque)

    def push(self, world_id: str, task: ReactionTask, max_depth: int) -> None:
        if task.chain_depth > max_depth:
            return
        self._queues[world_id].append(task)

    def pop(self, world_id: str, current_world_time: int | None = None, *, max_age_minutes: int = 180) -> ReactionTask | None:
        if not self._queues[world_id]:
            return None
        if current_world_time is not None:
            fresh: deque[ReactionTask] = deque()
            for task in self._queues[world_id]:
                created = int(task.created_world_time if task.created_world_time is not None else current_world_time)
                if current_world_time - created <= max_age_minutes:
                    fresh.append(task)
            self._queues[world_id] = fresh
            if not self._queues[world_id]:
                return None
        first = self._queues[world_id].popleft()
        merged = [first.trigger_text]
        remaining: deque[ReactionTask] = deque()
        while self._queues[world_id]:
            task = self._queues[world_id].popleft()
            if current_world_time is not None:
                created = int(task.created_world_time if task.created_world_time is not None else current_world_time)
                if current_world_time - created > max_age_minutes:
                    continue
            if (task.agent_id == first.agent_id and task.source_agent_id == first.source_agent_id
                    and task.created_world_time == first.created_world_time
                    and task.recipient_location_id == first.recipient_location_id
                    and task.source_location_id == first.source_location_id and len(merged) < 4):
                merged.append(task.trigger_text)
                first.event_ids = tuple(dict.fromkeys((*first.event_ids, *task.event_ids)))
                first.chain_depth = max(first.chain_depth, task.chain_depth)
            else:
                remaining.append(task)
        self._queues[world_id] = remaining
        if len(merged) > 1:
            first.trigger_text = "同一时间记录的相关事件:\n" + "\n".join(f"- {text}" for text in merged)
        return first

    def clear(self, world_id: str) -> None:
        self._queues[world_id].clear()


reaction_queue = ReactionQueue()
