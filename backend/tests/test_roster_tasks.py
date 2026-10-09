"""Stage 4A-2: regulated real backend tasks, independent of frontend fixtures."""
import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import EventAdapter, Snapshot
from backend.app.main import create_app
from backend.app.model_gateway import DeterministicModelGateway
from backend.tests.test_lifecycle_api import create, headers


class ScenarioGateway(DeterministicModelGateway):
    def __init__(self, mode='valid', gate=False):
        self.mode = mode
        self.requests = []
        self.release = threading.Event()
        if not gate:
            self.release.set()
        self.active = self.max_active = 0

    async def generate(self, request):
        self.requests.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            while not self.release.is_set():
                await asyncio.sleep(.005)
            if self.mode == 'timeout':
                await asyncio.sleep(5)
            if self.mode == 'failure':
                raise RuntimeError('private-provider-secret-sentinel')
            raw = (await super().generate(request)).model_dump(mode='json')
            people = raw['participants']
            if self.mode == 'field': del people[0]['title']
            if self.mode == 'host': people[0]['kind'] = 'EXPERT'
            if self.mode == 'count': people.pop()
            if self.mode == 'scope': people[0]['discussion_id'] = str(uuid4())
            if self.mode == 'revision': people[0]['roster_revision'] = 99
            if self.mode == 'id': people[1]['id'] = people[0]['id']
            if self.mode == 'name': people[1]['name'] = people[0]['name']
            if self.mode == 'color': people[1]['color'] = people[0]['color']
            if self.mode == 'task': raw = {'task': 'summary', 'content': 'Wrong task'}
            return raw  # Deliberately untrusted provider result, validated by the task boundary.
        finally:
            self.active -= 1


@pytest.fixture
def setup(tmp_path):
    clients, gateways = [], []
    def build(gateway=None, **kwargs):
        gateway = gateway or ScenarioGateway()
        gateways.append(gateway)
        app = create_app(Settings(_env_file=None, database_path=tmp_path / f'{len(clients)}.sqlite3', model_provider='mock', model_timeout_seconds=1, **kwargs))
        context = TestClient(app, raise_server_exceptions=False)
        client = context.__enter__()
        clients.append(context)
        app.state.model_gateway = gateway
        return client, gateway
    yield build
    for gateway in gateways:
        gateway.release.set()
    for context in reversed(clients):
        context.__exit__(None,None,None)


def generate(client, did, key=None):
    response = client.post(f'/api/discussions/{did}/roster-generation', headers=headers(key))
    assert response.status_code == 202, response.text
    return response.json()


def wait_for(client, did, state, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        response = client.get(f'/api/discussions/{did}')
        assert response.status_code == 200, response.text
        body = response.json()
        Snapshot.model_validate(body)
        if body['discussion']['state'] == state:
            return body
        time.sleep(.01)
    raise AssertionError(f'{did}: expected {state}, last={body}')


def operation_row(client, op_id):
    with client.app.state.database.connect() as conn:
        return dict(conn.execute('SELECT * FROM operations WHERE id=?', (op_id,)).fetchone())


def events(client, did):
    with client.app.state.database.connect() as conn:
        stream = [dict(r) for r in conn.execute('SELECT * FROM events WHERE discussion_id=? ORDER BY seq', (did,))]
    for item in stream:
        item['payload'] = json.loads(item['payload'])
        EventAdapter.validate_python(item)
    return stream


def test_generation_is_background_and_duplicate_request_does_not_call_twice(setup):
    client, gateway = setup(ScenarioGateway(gate=True))
    did = create(client)['discussion']['id']
    key = uuid4()
    accepted = generate(client, did, key)
    assert accepted['state'] == 'GENERATING' and accepted['run_id'] is None
    pending = wait_for(client, did, 'GENERATING')
    assert pending['participants'] == []
    assert generate(client, did, key) == accepted
    conflict = client.post(f'/api/discussions/{did}/roster-generation', headers=headers())
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'INVALID_STATE'
    gateway.release.set()
    ready = wait_for(client, did, 'READY')
    assert len(gateway.requests) == 1
    assert len(ready['participants']) == 5
    assert ready['participants'][0]['name'] == '主持人'
    assert {p['discussion_id'] for p in ready['participants']} == {did}
    assert ready['discussion']['run_id'] is None
    assert operation_row(client, accepted['operation_id'])['status'] == 'SUCCEEDED'
    assert generate(client, did, key) == accepted  # Replay original 202 even after completion.
    stream = events(client, did)
    assert [e['type'] for e in stream] == ['discussion.state_changed','discussion.state_changed','roster.ready','discussion.state_changed']
    assert [e['seq'] for e in stream] == [1,2,3,4]
    denied = client.post(f'/api/discussions/{did}/roster-generation', headers=headers())
    assert denied.status_code == 409


@pytest.mark.parametrize('mode', ['field','host','count','scope','revision','id','name','color','task'])
def test_invalid_model_result_never_publishes_partial_roster(setup, mode):
    client, gateway = setup(ScenarioGateway(mode))
    did = create(client, '非法输出保留议题')['discussion']['id']
    accepted = generate(client, did)
    failed = wait_for(client, did, 'FAILED')
    assert failed['discussion']['failure_stage'] == 'roster'
    assert failed['discussion']['topic'] == '非法输出保留议题'
    assert failed['participants'] == []
    assert operation_row(client, accepted['operation_id'])['error_code'] == 'MODEL_RESULT_INVALID'
    assert all(e['type'] != 'roster.ready' for e in events(client, did))
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM rosters').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM participants').fetchone()[0] == 0


@pytest.mark.parametrize('mode,code', [('timeout','MODEL_TIMEOUT'), ('failure','TASK_FAILED')])
def test_model_failure_is_sanitized_and_retry_uses_a_new_key(setup, caplog, mode, code):
    client, gateway = setup(ScenarioGateway(mode))
    did = create(client, '可重试')['discussion']['id']
    key = uuid4()
    with caplog.at_level(logging.INFO, logger='panel'):
        accepted = generate(client, did, key)
        failed = wait_for(client, did, 'FAILED')
    assert operation_row(client, accepted['operation_id'])['error_code'] == code
    assert 'private-provider-secret-sentinel' not in caplog.text + json.dumps(failed) + json.dumps(events(client, did))
    assert generate(client, did, key) == accepted
    assert len(gateway.requests) == 1
    gateway.mode = 'valid'
    retry = generate(client, did)
    ready = wait_for(client, did, 'READY')
    assert len(ready['participants']) == 5 and len(gateway.requests) == 2
    assert retry['operation_id'] != accepted['operation_id']
    assert operation_row(client, accepted['operation_id'])['status'] == 'FAILED'


@pytest.mark.parametrize('target', ['participants', 'event'])
def test_roster_and_ready_events_rollback_together_then_retry(setup, target):
    client, gateway = setup()
    db = client.app.state.database
    did = create(client)['discussion']['id']
    with db.connect() as conn:
        if target == 'participants':
            conn.execute("CREATE TRIGGER reject_roster BEFORE INSERT ON participants WHEN NEW.name='陈谨' BEGIN SELECT RAISE(ABORT,'private-write-sentinel'); END")
        else:
            conn.execute("CREATE TRIGGER reject_roster BEFORE INSERT ON events WHEN NEW.type='roster.ready' BEGIN SELECT RAISE(ABORT,'private-write-sentinel'); END")
    accepted = generate(client, did)
    failed = wait_for(client, did, 'FAILED')
    assert failed['participants'] == []
    assert operation_row(client, accepted['operation_id'])['error_code'] == 'DATABASE_UNAVAILABLE'
    stream = events(client, did)
    assert all(e['type'] != 'roster.ready' and e['payload'].get('state') != 'READY' for e in stream)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM participants').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM rosters').fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_roster')
    generate(client, did)
    assert len(wait_for(client, did, 'READY')['participants']) == 5


def test_two_discussions_generate_concurrently_without_crossed_results(setup):
    client, gateway = setup(ScenarioGateway(gate=True))
    a = create(client, 'A独立话题', count=2)['discussion']['id']
    b = create(client, 'B独立话题', count=6)['discussion']['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(lambda did: generate(client,did), [a,b]))
    end = time.monotonic()+3
    while len(gateway.requests)<2 and time.monotonic()<end: time.sleep(.01)
    assert len(gateway.requests) == 2 and gateway.max_active == 2
    gateway.release.set()
    snapshots = [wait_for(client,did,'READY') for did in [a,b]]
    assert [len(s['participants']) for s in snapshots] == [3,7]
    assert not {p['id'] for p in snapshots[0]['participants']} & {p['id'] for p in snapshots[1]['participants']}
    for did, accepted, snapshot in zip([a,b],accepted,snapshots):
        assert {p['discussion_id'] for p in snapshot['participants']} == {did}
        assert operation_row(client, accepted['operation_id'])['discussion_id'] == did
        assert all(e['discussion_id'] == did and e['run_id'] is None for e in events(client,did))
    assert {r.topic for r in gateway.requests} == {'A独立话题','B独立话题'}


def test_global_model_semaphore_and_generation_capacity(setup):
    client, gateway = setup(ScenarioGateway(gate=True), model_max_concurrency=1, discussion_max_active=2)
    dids = [create(client, f'议题{i}')['discussion']['id'] for i in range(3)]
    generate(client, dids[0]); generate(client, dids[1])
    response = client.post(f'/api/discussions/{dids[2]}/roster-generation', headers=headers())
    assert response.status_code == 503 and response.json()['error']['code'] == 'CAPACITY_EXCEEDED'
    gateway.release.set()
    for did in dids[:2]: wait_for(client,did,'READY')
    assert gateway.max_active == 1
    generate(client,dids[2]); wait_for(client,dids[2],'READY')


def test_external_provider_not_configured_never_admits_generation(tmp_path):
    app = create_app(Settings(_env_file=None, database_path=tmp_path/'external.db', model_provider='external'))
    with TestClient(app) as client:
        did = create(client)['discussion']['id']
        response = client.post(f'/api/discussions/{did}/roster-generation', headers=headers())
        assert response.status_code == 503 and response.json()['error']['code'] == 'MODEL_NOT_CONFIGURED'
        assert client.get(f'/api/discussions/{did}').json()['discussion']['state'] == 'DRAFT'
