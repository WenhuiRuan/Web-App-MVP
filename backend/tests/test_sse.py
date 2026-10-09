"""Stage 5 stream handover, replay, isolation and lifecycle boundaries."""
import asyncio
import json
import sqlite3
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from backend.tests.test_roster_tasks import setup
from backend.tests.test_insight_pipeline import prepared, statement, evidence


def terminal(setup):
    client, repo, did, rid = prepared(setup)
    repo.recover_unfinished()
    return client, repo, did, rid


def frames(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith('data: ')]


def test_replays_committed_events_in_order_and_closes_terminal(setup):
    client, repo, did, _ = terminal(setup)
    response = client.get(f'/api/discussions/{did}/events?after=1')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    data = frames(response.text)
    assert [e['seq'] for e in data] == list(range(2, repo.snapshot(did).last_event_seq + 1))
    assert all(e['discussion_id'] == str(did) for e in data)
    assert data[-1]['payload']['state'] == 'INTERRUPTED'
    assert data[-1]['payload']['failure_code'] == 'SERVICE_INTERRUPTED'
    assert f'id: {did}:2' in response.text
    assert frames(client.get(f'/api/discussions/{did}/events?after={data[-1]["seq"]}').text) == []


@pytest.mark.parametrize('cursor', ['bogus', 'wrong:1', '-1', '1.1'])
def test_malformed_header_rejected_before_streaming(setup, cursor):
    client, _, did, _ = terminal(setup)
    response = client.get(f'/api/discussions/{did}/events', headers={'Last-Event-ID': cursor})
    assert response.status_code == 409 and response.json()['error']['code'] == 'CURSOR_INVALID'


@pytest.mark.parametrize('after', ['-1', 'a', '999999999'])
def test_query_cursor_bounds(setup, after):
    client, _, did, _ = terminal(setup)
    response = client.get(f'/api/discussions/{did}/events?after={after}')
    assert response.status_code == (409 if after == '999999999' else 422)


def test_header_precedence_cross_discussion_and_unknown_scope(setup):
    client, repo, did, _ = terminal(setup)
    seq = repo.snapshot(did).last_event_seq
    response = client.get(f'/api/discussions/{did}/events?after=0', headers={'Last-Event-ID': f'{did}:{seq}'})
    assert response.status_code == 200 and frames(response.text) == []
    response = client.get(f'/api/discussions/{did}/events', headers={'Last-Event-ID': f'{uuid4()}:1'})
    assert response.status_code == 409
    assert client.get(f'/api/discussions/{uuid4()}/events').status_code == 404


def test_snapshot_handover_includes_events_committed_before_subscribe(setup):
    client, repo, did, rid = prepared(setup)
    before = repo.snapshot(did)
    statement(repo, did, rid, 2)
    repo.recover_unfinished()
    data = frames(client.get(f'/api/discussions/{did}/events?after={before.last_event_seq}').text)
    assert [e['seq'] for e in data] == list(range(before.last_event_seq + 1, repo.snapshot(did).last_event_seq + 1))
    assert sum(e['type'] == 'turn.committed' for e in data) == 1
    # Reconnection resumes from the last delivered id, without replaying it.
    later = frames(client.get(f'/api/discussions/{did}/events', headers={'Last-Event-ID': f'{did}:{data[1]["seq"]}'}).text)
    assert later == data[2:]


def test_insight_failure_status_is_durable_and_keeps_successful_batch(setup):
    client, repo, did, rid = prepared(setup)
    first = repo.claim_insights(did, rid)
    repo.complete_insights(first, evidence(first.request))
    old = repo.snapshot(did)
    statement(repo, did, rid, 2)
    claim = repo.claim_insights(did, rid)
    repo.fail_insights(claim, 'MODEL_TIMEOUT')
    repo.recover_unfinished()
    data = frames(client.get(f'/api/discussions/{did}/events?after={old.last_event_seq}').text)
    statuses = [e['payload'] for e in data if e['type'] == 'insights.status_changed']
    assert [s['state'] for s in statuses] == ['PENDING', 'FAILED']
    assert statuses[-1]['error_code'] == 'MODEL_TIMEOUT'
    assert repo.snapshot(did).insights == old.insights


def test_heartbeat_wait_releases_database_and_disconnect_only_closes_observer(setup):
    from backend.app.sse import event_stream
    _, repo, did, _ = prepared(setup)
    class Request:
        disconnected = False
        async def is_disconnected(self): return self.disconnected
    async def exercise():
        request = Request()
        stream = event_stream(request, repo, did, repo.snapshot(did).last_event_seq, poll_seconds=.001, heartbeat_seconds=.002)
        assert 'retry:' in await anext(stream)
        assert ': heartbeat' in await anext(stream)
        with repo.database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE'); conn.execute('ROLLBACK')
        request.disconnected = True
        with pytest.raises(StopAsyncIteration): await anext(stream)
        assert repo.snapshot(did).discussion.state == 'RUNNING'
    asyncio.run(exercise())


def test_upgrade_preserves_existing_events_high_water_and_immutable_guards(tmp_path):
    from backend.app.database import Database
    old = tmp_path / 'old'; old.mkdir()
    for file in Path('db/migrations').glob('00[1-4]_*.sql'): shutil.copyfile(file, old / file.name)
    db = Database(tmp_path / 'upgrade.db', migrations_dir=old)
    db.migrate()
    with db.connect() as conn:
        conn.execute("INSERT INTO discussions(id,topic,expert_count) VALUES ('a','迁移前讨论',4)")
        conn.execute("INSERT INTO events(discussion_id,seq,type,payload) VALUES ('a',1,'discussion.state_changed','{}')")
        before = [tuple(row) for row in conn.execute('SELECT * FROM events')]
    upgraded = Database(db.path)
    assert upgraded.migrate() == [5] and upgraded.migrate() == []
    with upgraded.connect() as conn:
        assert [tuple(row) for row in conn.execute('SELECT * FROM events')] == before
        assert conn.execute("SELECT last_event_seq FROM discussions WHERE id='a'").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError): conn.execute('DELETE FROM events')
        with pytest.raises(sqlite3.IntegrityError): conn.execute("INSERT INTO events(discussion_id,seq,type,payload) VALUES ('a',3,'insights.status_changed','{}')")
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()


def test_status_event_write_failure_rolls_back_job_and_retains_projection(setup):
    from backend.app.lifecycle import RepositoryUnavailable
    _, repo, did, rid = prepared(setup)
    claim = repo.claim_insights(did, rid); before = repo.snapshot(did)
    with repo.database.connect() as conn:
        conn.execute("CREATE TRIGGER reject_status BEFORE INSERT ON events WHEN NEW.type='insights.status_changed' BEGIN SELECT RAISE(ABORT,'fail'); END")
    with pytest.raises(RepositoryUnavailable): repo.fail_insights(claim, 'MODEL_TIMEOUT')
    assert repo.snapshot(did) == before


def test_stream_reads_more_than_one_page_without_gaps(setup):
    client, repo, did, _ = terminal(setup)
    before = repo.snapshot(did).last_event_seq
    with repo.transaction() as conn:
        for _ in range(205):
            row = repo._discussion(conn, did)
            repo._event(conn, did, 'discussion.state_changed', {'state':row['state'], 'version':row['version']}, row['current_run_id'])
    data = frames(client.get(f'/api/discussions/{did}/events?after={before}').text)
    assert [e['seq'] for e in data] == list(range(before+1, before+206))
