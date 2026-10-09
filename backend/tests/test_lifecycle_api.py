"""Stage 4A-1: real FastAPI + SQLite creation/query acceptance, specified first."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.contracts import Snapshot
from backend.app.main import create_app


def headers(key=None):
    return {'Idempotency-Key': str(key or uuid4())}


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_path=tmp_path / 'panel.sqlite3', model_provider='mock')
    with TestClient(create_app(settings), raise_server_exceptions=False) as value:
        yield value


def create(client, topic='  应该如何改进团队协作？  ', count=None, key=None):
    body = {'topic': topic}
    if count is not None:
        body['expert_count'] = count
    response = client.post('/api/discussions', json=body, headers=headers(key))
    assert response.status_code == 201, response.text
    Snapshot.model_validate(response.json())
    return response.json()


def test_create_defaults_trim_and_durable_snapshot(client):
    result = create(client)
    discussion = result['discussion']
    assert discussion['topic'] == '应该如何改进团队协作？'
    assert discussion['expert_count'] == 4
    assert discussion['state'] == 'DRAFT'
    assert discussion['run_id'] is None
    assert result['participants'] == result['messages'] == []
    assert result['last_event_seq'] == 1
    assert client.get('/api/discussions/' + discussion['id']).json() == result
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM discussions').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM operations').fetchone()[0] == 1
        assert conn.execute('SELECT type FROM events').fetchone()[0] == 'discussion.state_changed'


@pytest.mark.parametrize('body', [
    {'topic': ''}, {'topic': ' \n\t'}, {'topic': '题' * 501},
    {'topic': '议题', 'expert_count': 1}, {'topic': '议题', 'expert_count': 7},
    {'topic': '议题', 'expert_count': True}, {'topic': '议题', 'expert_count': '4'},
    {'topic': '议题', 'unknown': 'not allowed'},
])
def test_invalid_create_never_writes(client, body):
    response = client.post('/api/discussions', json=body, headers=headers())
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    with client.app.state.database.connect() as conn:
        for table in ('discussions', 'operations', 'events'):
            assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


@pytest.mark.parametrize('count', [2, 6])
def test_input_boundaries_use_unicode_codepoints(client, count):
    result = create(client, topic='😀' * 500, count=count)
    assert result['discussion']['expert_count'] == count
    assert len(result['discussion']['topic']) == 500


def test_idempotency_normalizes_defaults_and_trim_and_rejects_different_body(client):
    key = uuid4()
    first = create(client, '  相同话题  ', key=key)
    replay = create(client, '相同话题', count=4, key=key)
    assert first == replay
    conflict = client.post('/api/discussions', json={'topic': '另一个话题'}, headers=headers(key))
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_concurrent_same_create_command_produces_one_discussion(client):
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(client, '同一请求', key=key), range(2)))
    assert results[0] == results[1]
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM discussions').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM operations').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0] == 1


def test_list_filter_stable_sort_cursor_and_invalid_queries(client):
    records = [create(client, f'议题{i}')['discussion'] for i in range(3)]
    with client.app.state.database.connect() as conn:
        conn.execute("UPDATE discussions SET created_at='2026-10-09T00:00:00.000000Z'")
        conn.execute("UPDATE discussions SET state='RUNNING' WHERE id=?", (records[0]['id'],))
    active = client.get('/api/discussions').json()
    assert [d['id'] for d in active['items']] == [records[0]['id']]
    first = client.get('/api/discussions?status=all&limit=2').json()
    assert len(first['items']) == 2 and first['next_cursor']
    second = client.get('/api/discussions', params={'status': 'all', 'limit': 2, 'cursor': first['next_cursor']}).json()
    assert second['next_cursor'] is None
    assert [d['id'] for d in first['items'] + second['items']] == sorted([d['id'] for d in records], reverse=True)
    for params in [{'status': 'bad'}, {'limit': 0}, {'limit': 101}, {'cursor': 'broken'}]:
        response = client.get('/api/discussions', params=params)
        assert response.status_code == 422


def test_missing_snapshot_and_idempotency_header_are_explicit(client):
    response = client.get('/api/discussions/' + str(uuid4()))
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'DISCUSSION_NOT_FOUND'
    for value in [None, 'not-uuid']:
        response = client.post('/api/discussions', json={'topic': '议题'}, headers={} if value is None else {'Idempotency-Key': value})
        assert response.status_code == 422


def test_create_data_operation_event_rollback_and_key_can_retry(client):
    db = client.app.state.database
    with db.connect() as conn:
        conn.execute("CREATE TRIGGER reject_create BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected-write-failure'); END")
    key = uuid4()
    response = client.post('/api/discussions', json={'topic': '写入失败也不留半条数据'}, headers=headers(key))
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DATABASE_UNAVAILABLE'
    assert 'injected-write-failure' not in response.text
    with db.connect() as conn:
        for table in ('discussions', 'operations', 'events'):
            assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_create')
    assert create(client, '写入失败也不留半条数据', key=key)['last_event_seq'] == 1


def test_committed_draft_survives_application_restart(tmp_path):
    config = Settings(_env_file=None, database_path=tmp_path / 'restart.sqlite3', model_provider='mock')
    key = uuid4()
    with TestClient(create_app(config)) as one:
        before = create(one, '重启保留', key=key)
    with TestClient(create_app(config)) as two:
        assert two.get('/api/discussions/' + before['discussion']['id']).json() == before
        assert create(two, '重启保留', key=key) == before
