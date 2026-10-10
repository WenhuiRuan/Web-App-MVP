import json
from pathlib import Path

import pytest

from backend.app.database import Database
from backend.app.repository import DiscussionRepository
from backend.app.lifecycle import RepositoryUnavailable
from scripts.final_samples import load_samples, import_samples

ROOT = Path(__file__).resolve().parents[2]


def test_samples_cover_five_distinct_topics_and_scoped_rosters():
    samples = load_samples(ROOT / 'data/samples/final/rosters.json')
    assert len(samples) >= 5
    assert len({s['create']['topic'] for s in samples}) == len(samples)
    assert all(s['source'] and s['quality'] for s in samples)


def test_import_is_repeatable_and_creates_current_snapshots(tmp_path):
    database = Database(tmp_path / 'samples.sqlite3')
    database.migrate()
    samples = load_samples(ROOT / 'data/samples/final/rosters.json')
    assert import_samples(database, samples) == {'imported': 5, 'skipped': 0}
    assert import_samples(database, samples) == {'imported': 0, 'skipped': 5}
    repo = DiscussionRepository(database)
    for sample in samples:
        snapshot = repo.snapshot(sample['discussion_id'])
        assert snapshot.discussion.state == 'READY'
        assert snapshot.last_event_seq == 3
        assert len(snapshot.participants) == 5
        assert not snapshot.messages and snapshot.discussion.run_id is None
        assert len(repo.event_page(sample['discussion_id'], 0)[0]) == 3


def test_all_samples_rollback_when_a_roster_write_fails(tmp_path):
    database = Database(tmp_path / 'samples.sqlite3')
    database.migrate()
    samples = load_samples(ROOT / 'data/samples/final/rosters.json')
    with database.connect() as conn:
        conn.execute("CREATE TRIGGER reject_sample BEFORE INSERT ON participants BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(RepositoryUnavailable):
        import_samples(database, samples)
    with database.connect() as conn:
        for table in ('discussions', 'rosters', 'participants', 'events'):
            assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


def test_import_never_overwrites_existing_discussion(tmp_path):
    database = Database(tmp_path / 'samples.sqlite3')
    database.migrate()
    samples = load_samples(ROOT / 'data/samples/final/rosters.json')
    import_samples(database, samples)
    with database.connect() as conn:
        conn.execute('UPDATE discussions SET topic=? WHERE id=?', ('用户修改后的议题', samples[0]['discussion_id']))
    with pytest.raises(ValueError, match='conflict'):
        import_samples(database, samples)
    assert DiscussionRepository(database).snapshot(samples[0]['discussion_id']).discussion.topic == '用户修改后的议题'


def test_invalid_cross_discussion_roster_is_rejected_before_writing(tmp_path):
    raw = json.loads((ROOT / 'data/samples/final/rosters.json').read_text(encoding='utf-8'))
    raw['samples'][0]['participants'][1]['discussion_id'] = raw['samples'][1]['discussion_id']
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError):
        load_samples(path)
