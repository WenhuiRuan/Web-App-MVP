CREATE TABLE insight_jobs (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    through_turn INTEGER NOT NULL CHECK(through_turn >= 0),
    state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','SUCCEEDED','FAILED','INTERRUPTED','SUPERSEDED')),
    error_code TEXT CHECK(error_code IN ('MODEL_TIMEOUT','MODEL_RESULT_INVALID','TASK_FAILED','DATABASE_UNAVAILABLE','SERVICE_INTERRUPTED')),
    UNIQUE(discussion_id,run_id,version),
    UNIQUE(discussion_id,run_id,through_turn),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id)
) STRICT;
CREATE TRIGGER insight_source_boundary BEFORE INSERT ON insight_sources
BEGIN
    SELECT CASE WHEN (SELECT turn_no FROM messages WHERE discussion_id=NEW.discussion_id AND run_id=NEW.run_id AND id=NEW.message_id) >
    (SELECT through_turn FROM insight_batches WHERE discussion_id=NEW.discussion_id AND run_id=NEW.run_id AND version=NEW.batch_version)
    THEN RAISE(ABORT,'insight source beyond boundary') END;
END;
