"""WebSocket routes."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..events import dump_event
from ..run_manager import run_manager
from ..security import request_is_loopback

router = APIRouter()


@router.websocket("/ws/runs/{thread_id}")
async def run_events(websocket: WebSocket, thread_id: str) -> None:
    if not request_is_loopback(websocket.headers.get("host"), websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        async for event in run_manager.subscribe(thread_id):
            await websocket.send_json(dump_event(event))
    except (KeyError, WebSocketDisconnect):
        await websocket.close()
