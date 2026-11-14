"""WebSocket adapters that release subscriptions on disconnect and completion."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..events import dump_event
from ..security import request_is_loopback

router = APIRouter()


@router.websocket('/ws/runs/{thread_id}')
async def run_events(websocket: WebSocket, thread_id: str) -> None:
    if not request_is_loopback(websocket.headers.get('host'), websocket.headers.get('origin')):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    stream = websocket.app.state.run_manager.subscribe(thread_id)
    receiving = asyncio.create_task(websocket.receive())
    next_event = None
    try:
        while True:
            if next_event is None:
                next_event = asyncio.create_task(anext(stream))
            finished, _ = await asyncio.wait((receiving, next_event), return_when=asyncio.FIRST_COMPLETED)
            if receiving in finished:
                message = receiving.result()
                if message['type'] == 'websocket.disconnect':
                    return
                receiving = asyncio.create_task(websocket.receive())
            if next_event in finished:
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    await websocket.close()
                    return
                next_event = None
                await websocket.send_json(event if isinstance(event, dict) else dump_event(event))
    except WebSocketDisconnect:
        return
    except KeyError:
        await websocket.close(code=1008)
    finally:
        tasks = [task for task in (receiving, next_event) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await stream.aclose()
