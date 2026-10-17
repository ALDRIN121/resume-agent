"""Disconnected browser clients must not cause server-side close errors."""
from starlette.websockets import WebSocket

from resume_agent.api.events import LogLineEvent
from resume_agent.api.routers import ws


async def test_run_socket_disconnect_does_not_close_twice(monkeypatch):
    async def subscribe(thread_id):
        yield LogLineEvent(line="next event")

    monkeypatch.setattr(ws.run_manager, "subscribe", subscribe)
    sent = []

    async def send(message):
        sent.append(message["type"])
        if message["type"] == "websocket.send":
            raise OSError("browser navigated away")

    async def receive():
        return {"type": "websocket.connect"}

    socket = WebSocket({"type": "websocket", "headers": [
        (b"host", b"127.0.0.1:8000"), (b"origin", b"http://127.0.0.1:8000"),
    ]}, receive, send)
    await ws.run_events(socket, "sample")
    assert sent == ["websocket.accept", "websocket.send"]


async def test_restarted_completed_run_replays_terminal_event(tmp_path, monkeypatch):
    import importlib
    import json

    manager_module = importlib.import_module("resume_agent.api.run_manager")
    history = tmp_path / "history.jsonl"
    history.write_text(json.dumps({
        "thread_id": "saved", "status": "complete", "company": "TechCorp",
        "pdf_path": "/sample.pdf", "duration_s": 42,
    }) + "\n")
    monkeypatch.setattr(manager_module, "_HISTORY_FILE", history)
    manager = object.__new__(manager_module.RunManager)
    manager._sessions = {}
    manager._load_history()
    events = [event async for event in manager.subscribe("saved")]
    assert len(events) == 1
    assert events[0].type == "complete"
    assert events[0].pdf_url == "/api/runs/saved/pdf"
    assert events[0].duration_s == 42
