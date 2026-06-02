from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(slots=True)
class ReactionTask:
    agent_id: str
    trigger_text: str
    chain_depth: int = 0
    source_agent_id: str | None = None


class ReactionQueue:
    def __init__(self) -> None:
        self._queues: dict[str, deque[ReactionTask]] = defaultdict(deque)

    def push(self, world_id: str, task: ReactionTask, max_depth: int) -> None:
        if task.chain_depth > max_depth:
            return
        self._queues[world_id].append(task)

    def pop(self, world_id: str) -> ReactionTask | None:
        if not self._queues[world_id]:
            return None
        first = self._queues[world_id].popleft()
        merged = [first.trigger_text]
        remaining: deque[ReactionTask] = deque()
        while self._queues[world_id]:
            task = self._queues[world_id].popleft()
            if task.agent_id == first.agent_id and len(merged) < 4:
                merged.append(task.trigger_text)
                first.chain_depth = max(first.chain_depth, task.chain_depth)
            else:
                remaining.append(task)
        self._queues[world_id] = remaining
        if len(merged) > 1:
            first.trigger_text = "你几乎同时需要回应这些事:\n" + "\n".join(f"- {text}" for text in merged)
        return first

    def clear(self, world_id: str) -> None:
        self._queues[world_id].clear()


reaction_queue = ReactionQueue()
