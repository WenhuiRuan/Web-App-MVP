"""Real TCP observer remains open while the production server shuts down."""
import asyncio
import socket
import threading
import time
from uuid import uuid4

import httpx

from backend.app.config import Settings
from backend.app.model_gateway import DeterministicModelGateway
from backend.app.server import build_server


def test_open_observer_does_not_prevent_shutdown_and_task_interruption(tmp_path):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    server = build_server(Settings(_env_file=None, database_path=tmp_path / 'shutdown.db', backend_port=port, log_level='ERROR'))
    app = server.config.app
    class SlowGateway(DeterministicModelGateway):
        async def generate(self, request):
            if request.task != 'roster': await asyncio.sleep(60)
            return await super().generate(request)
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    deadline = time.monotonic()+10
    while not server.started and time.monotonic() < deadline: time.sleep(.01)
    assert server.started
    try:
        app.state.model_gateway = SlowGateway()
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10) as client:
            key = lambda: {'Idempotency-Key':str(uuid4())}
            did = client.post('/api/discussions', json={'topic':'关闭时仍有观察者'}, headers=key()).json()['discussion']['id']
            client.post(f'/api/discussions/{did}/roster-generation', json={}, headers=key())
            deadline = time.monotonic()+5
            while client.get(f'/api/discussions/{did}').json()['discussion']['state'] != 'READY':
                assert time.monotonic() < deadline; time.sleep(.01)
            assert client.post(f'/api/discussions/{did}/start', json={'roster_revision':1}, headers=key()).status_code == 202
            with client.stream('GET', f'/api/discussions/{did}/events') as response:
                assert response.status_code == 200
                iterator = response.iter_lines()
                assert next(iterator).startswith('retry:')
                assert not response.is_closed
                server.should_exit = True
                thread.join(8)
                assert not thread.is_alive(), 'open SSE prevented shutdown'
            saved = app.state.repository.snapshot(did)
            assert saved.discussion.state == 'INTERRUPTED'
            assert saved.discussion.failure_stage == 'discussion'
            assert saved.discussion.failure_code == 'SERVICE_INTERRUPTED'
            assert app.state.tasks.closing
    finally:
        server.should_exit = True; thread.join(8)
