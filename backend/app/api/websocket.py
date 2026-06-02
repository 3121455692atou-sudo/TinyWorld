from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, world_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active[world_id].add(websocket)

    def disconnect(self, world_id: str, websocket: WebSocket) -> None:
        self.active[world_id].discard(websocket)

    async def broadcast(self, world_id: str, message: dict[str, Any]) -> None:
        dead = []
        for websocket in list(self.active[world_id]):
            try:
                await websocket.send_json(message)
            except RuntimeError:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(world_id, websocket)


manager = ConnectionManager()


@router.websocket("/ws/worlds/{world_id}")
async def world_socket(websocket: WebSocket, world_id: str) -> None:
    await manager.connect(world_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(world_id, websocket)

