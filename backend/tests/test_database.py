import sqlite3
from pathlib import Path

import pytest

from backend.app.database import Database, MigrationError


def seed(db):
    with db.connect() as conn:
        for d in ('a', 'b'):
            conn.execute('INSERT INTO discussions(id,topic,expert_count) VALUES (?,?,4)', (d, d))
            conn.execute('INSERT INTO rosters(discussion_id,revision) VALUES (?,1)', (d,))
            conn.execute("INSERT INTO participants(id,discussion_id,roster_revision,kind,name,title,stance,color) VALUES (?,?,1,'EXPERT',?,'研究员','审慎','#123456')", (d + '-p', d, d))
            conn.execute("INSERT INTO runs(id,discussion_id,roster_revision) VALUES (?,?,1)", (d + '-r', d))


def test_migration_repeat_keeps_data_and_constraints(tmp_path):
    db = Database(tmp_path / 'test.sqlite3')
    assert db.migrate() == [1]
    seed(db)
    assert db.migrate() == []
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM discussions').fetchone()[0] == 2
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO runs(id,discussion_id,roster_revision) VALUES ('a-r2','a',1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO messages(id,discussion_id,run_id,roster_revision,participant_id,turn_no,kind,content) VALUES ('m','a','a-r',1,'b-p',1,'statement','不能串场。')")


def test_events_order_and_role_state_uniqueness(tmp_path):
    db = Database(tmp_path / 'test.db')
    db.migrate()
    seed(db)
    with db.connect() as conn:
        conn.execute("INSERT INTO events(discussion_id,seq,type,payload) VALUES ('a',1,'discussion.state_changed','{}')")
        assert conn.execute("SELECT last_event_seq FROM discussions WHERE id='a'").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO events(discussion_id,seq,type,payload) VALUES ('a',3,'discussion.state_changed','{}')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO events(discussion_id,run_id,seq,type,payload) VALUES ('a','b-r',2,'turn.committed','{}')")
        conn.execute("INSERT INTO participants(id,discussion_id,roster_revision,kind,name,title,stance,color) VALUES ('a-p2','a',1,'EXPERT','其他','研究员','审慎','#654321')")
        conn.execute("INSERT INTO role_states(discussion_id,run_id,roster_revision,participant_id,state) VALUES ('a','a-r',1,'a-p','SPEAKING')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO role_states(discussion_id,run_id,roster_revision,participant_id,state) VALUES ('a','a-r',1,'a-p2','SPEAKING')")


def test_migration_failure_is_atomic_and_modified_history_rejected(tmp_path):
    migrations = tmp_path / 'migrations'
    migrations.mkdir()
    first = migrations / '001_initial.sql'
    first.write_text('CREATE TABLE sample (id INTEGER PRIMARY KEY);', encoding='utf-8')
    bad = migrations / '002_bad.sql'
    bad.write_text('CREATE TABLE partial (id INTEGER);\nTHIS IS INVALID;', encoding='utf-8')
    db = Database(tmp_path / 'test.db', migrations_dir=migrations)
    with pytest.raises(MigrationError):
        db.migrate()
    with db.connect() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name IN ('sample','partial')").fetchall() == []
    bad.unlink()
    assert db.migrate() == [1]
    first.write_text('CREATE TABLE sample (id TEXT);', encoding='utf-8')
    with pytest.raises(MigrationError):
        db.migrate()


def test_insight_and_intent_sources_cannot_cross_discussions(tmp_path):
    db = Database(tmp_path / 'sources.db')
    db.migrate()
    seed(db)
    with db.connect() as conn:
        for d in ('a', 'b'):
            conn.execute("INSERT INTO messages(id,discussion_id,run_id,roster_revision,participant_id,turn_no,kind,content) VALUES (?,?,?,1,?,1,'statement','公开发言。')", (d + '-m', d, d + '-r', d + '-p'))
        conn.execute("INSERT INTO insight_batches(discussion_id,run_id,version,through_turn) VALUES ('a','a-r',1,1)")
        conn.execute("INSERT INTO insights(id,discussion_id,run_id,batch_version,kind,content) VALUES ('i','a','a-r',1,'consensus','共同观点')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO insight_sources VALUES ('a','a-r',1,'i','b-m')")
        conn.execute("INSERT INTO insight_sources VALUES ('a','a-r',1,'i','a-m')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO speaking_intents VALUES ('intent','a','a-r',1,'a-p',1,1,'REBUT','b-m',70,'反驳')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE discussions SET current_run_id='b-r' WHERE id='a'")


def test_event_and_high_watermark_rollback_together(tmp_path):
    db = Database(tmp_path / 'events.db')
    db.migrate()
    seed(db)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("INSERT INTO events(discussion_id,seq,type,payload) VALUES ('a',1,'discussion.state_changed','{}')")
        conn.execute('ROLLBACK')
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0] == 0
        assert conn.execute("SELECT last_event_seq FROM discussions WHERE id='a'").fetchone()[0] == 0
        conn.execute("INSERT INTO events(discussion_id,seq,type,payload) VALUES ('a',1,'discussion.state_changed','{}')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM events WHERE discussion_id='a'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE events SET payload='[]' WHERE discussion_id='a'")
