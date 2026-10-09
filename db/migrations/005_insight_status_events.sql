-- Add a public status event without rewriting historic payloads or cursors.
CREATE TABLE events_next (
    discussion_id TEXT NOT NULL REFERENCES discussions(id),
    seq INTEGER NOT NULL CHECK(seq >= 1),
    run_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version=1),
    type TEXT NOT NULL CHECK(type IN ('discussion.state_changed','roster.ready','participant.status_changed','turn.committed','insights.updated','insights.status_changed','summary.ready','operation.failed')),
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    payload TEXT NOT NULL CHECK(json_valid(payload)),
    PRIMARY KEY(discussion_id,seq),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id)
) STRICT;
INSERT INTO events_next SELECT * FROM events;
DROP TABLE events;
ALTER TABLE events_next RENAME TO events;
CREATE TRIGGER events_contiguous BEFORE INSERT ON events
BEGIN
    SELECT CASE WHEN NEW.seq != (SELECT last_event_seq+1 FROM discussions WHERE id=NEW.discussion_id)
    THEN RAISE(ABORT,'event sequence gap') END;
END;
CREATE TRIGGER events_advance AFTER INSERT ON events
BEGIN
    UPDATE discussions SET last_event_seq=NEW.seq WHERE id=NEW.discussion_id;
END;
CREATE TRIGGER events_immutable_update BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT,'events are append-only');
END;
CREATE TRIGGER events_immutable_delete BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT,'events are append-only');
END;
