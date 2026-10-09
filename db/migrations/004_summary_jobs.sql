CREATE UNIQUE INDEX scoped_operation_identity ON operations(discussion_id,id);
CREATE TABLE summary_jobs (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt >= 1),
    through_turn INTEGER NOT NULL CHECK(through_turn >= 0),
    insight_version INTEGER NOT NULL CHECK(insight_version >= 0),
    operation_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','SUCCEEDED','FAILED','INTERRUPTED')),
    error_code TEXT CHECK(error_code IN ('MODEL_TIMEOUT','MODEL_RESULT_INVALID','TASK_FAILED','DATABASE_UNAVAILABLE','SERVICE_INTERRUPTED')),
    UNIQUE(discussion_id,run_id,attempt),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id),
    FOREIGN KEY(discussion_id,operation_id) REFERENCES operations(discussion_id,id)
) STRICT;
CREATE UNIQUE INDEX one_pending_summary ON summary_jobs(discussion_id,run_id) WHERE status='PENDING';
CREATE TRIGGER summary_frozen_boundary BEFORE INSERT ON summaries
BEGIN
    SELECT CASE WHEN NEW.through_turn IS NOT (SELECT summary_through_turn FROM runs WHERE discussion_id=NEW.discussion_id AND id=NEW.run_id)
    THEN RAISE(ABORT,'summary boundary mismatch') END;
END;
CREATE TRIGGER completion_requires_summary BEFORE UPDATE OF state ON discussions
WHEN NEW.state='COMPLETED'
BEGIN
    SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM summaries WHERE discussion_id=NEW.id AND run_id=NEW.current_run_id)
    THEN RAISE(ABORT,'completed without summary') END;
END;
