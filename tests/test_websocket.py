"""Sockets reconstruct durable state and tolerate disconnected clients."""
from types import SimpleNamespace

from starlette.websockets import WebSocket

from resume_agent.api.events import LogLineEvent
from resume_agent.api.routers import ws


async def test_run_socket_disconnect_does_not_close_twice():
    async def subscribe(run_id):
        yield LogLineEvent(line='next event')
    sent = []
    async def send(message):
        sent.append(message['type'])
        if message['type'] == 'websocket.send':
            raise OSError('browser navigated away')
    import asyncio
    first_receive = True
    async def receive():
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {'type': 'websocket.connect'}
        await asyncio.Event().wait()
    app = SimpleNamespace(state=SimpleNamespace(run_manager=SimpleNamespace(subscribe=subscribe)))
    socket = WebSocket({'type': 'websocket', 'app': app, 'headers': [
        (b'host', b'127.0.0.1:8000'), (b'origin', b'http://127.0.0.1:8000'),
    ]}, receive, send)
    await ws.run_events(socket, 'sample')
    assert sent == ['websocket.accept', 'websocket.send']


async def test_restarted_completed_run_replays_canonical_legacy_snapshot(tmp_path):
    import json

    from resume_agent import library
    from resume_agent.api.v2_manager import V2RunManager
    from resume_agent.config import ResumeAgentSettings
    from resume_agent.runtime import Runtime
    from tests.test_pdf_content_check import make_pdf
    pdf = make_pdf(tmp_path / 'sample.pdf', 'Legacy content')
    history = tmp_path / 'run_history.jsonl'
    history.write_text(json.dumps({'thread_id': 'saved', 'status': 'complete', 'company': 'TechCorp',
                                  'pdf_path': str(pdf), 'duration_s': 42}) + '\n')
    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings())
    # A later JSONL edit cannot replace canonical DB state after restart.
    history.write_text(json.dumps({'thread_id': 'saved', 'company': 'Wrong'}) + '\n')
    runtime = Runtime(root=tmp_path, settings=ResumeAgentSettings())
    events = [event async for event in V2RunManager(runtime).subscribe('saved')]
    assert events[0]['type'] == 'run_state'
    assert events[0]['run']['company'] == 'TechCorp'
    assert events[0]['run']['artifact_status'] == 'legacy_unverified'
    assert events[1]['type'] == 'complete'
    assert events[1]['pdf_url'] == '/api/runs/saved/pdf'
    assert events[1]['duration_s'] == 42
    library.delete_resume('saved', library_path=runtime.store.library_path)
    restarted = Runtime(root=tmp_path, settings=ResumeAgentSettings())
    assert V2RunManager(restarted).list_runs() == []


def test_live_paused_socket_does_not_starve_repeated_http_reads(tmp_path):
    """Use an actual local HTTP/socket server, not TestClient's separate portals."""
    import socket
    import threading
    import time

    import httpx
    import pytest
    import uvicorn
    from websockets.sync.client import connect

    from resume_agent.api.app import create_app
    from resume_agent.contracts import RunRequest
    from tests.test_v2_api import services

    runtime, _ = services(tmp_path)
    import asyncio
    run = runtime.create_run(RunRequest(job_input='Complete JD', input_type='text'))
    asyncio.run(runtime.runs.drive(run.id))
    server = uvicorn.Server(uvicorn.Config(create_app(services=runtime), log_level='error', lifespan='on'))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with connect(f'ws://127.0.0.1:{port}/ws/runs/{run.id}', open_timeout=2) as socket_client:
            import json
            state = json.loads(socket_client.recv(timeout=2))
            assert state['type'] == 'run_state'
            assert state['run']['pending']['kind'] == 'present_suggestions'
            assert json.loads(socket_client.recv(timeout=2))['type'] == 'run_state'
            assert json.loads(socket_client.recv(timeout=2))['type'] == 'hitl_pending'
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=1) as client:
                for _ in range(5):
                    response = client.get(f'/api/runs/{run.id}')
                    assert response.status_code == 200
                    assert response.json()['pending']['kind'] == 'present_suggestions'
            with pytest.raises(TimeoutError):
                socket_client.recv(timeout=0.1)
    finally:
        server.should_exit = True
        worker.join(timeout=3)
        listener.close()
        assert not worker.is_alive()
