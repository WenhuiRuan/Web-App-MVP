-- Preserve v5 tasks and their ownership/uniqueness while extending safe error codes.
-- SQLite cannot alter CHECK constraints; rebuild both child tables transactionally.
CREATE TABLE insight_jobs_next (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    through_turn INTEGER NOT NULL CHECK(through_turn >= 0),
    state TEXT NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','SUCCEEDED','FAILED','INTERRUPTED','SUPERSEDED')),
    error_code TEXT CHECK(error_code IN ('MODEL_TIMEOUT','MODEL_RESULT_INVALID','TASK_FAILED','DATABASE_UNAVAILABLE','SERVICE_INTERRUPTED','MODEL_REQUEST_INVALID','MODEL_AUTH_FAILED','MODEL_BALANCE_EXHAUSTED','MODEL_NOT_FOUND','MODEL_RATE_LIMITED','MODEL_SERVICE_UNAVAILABLE','MODEL_CONNECTION_FAILED')),
    UNIQUE(discussion_id,run_id,version),
    UNIQUE(discussion_id,run_id,through_turn),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id)
) STRICT;
INSERT INTO insight_jobs_next SELECT * FROM insight_jobs;
DROP TABLE insight_jobs;
ALTER TABLE insight_jobs_next RENAME TO insight_jobs;

CREATE TABLE summary_jobs_next (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt >= 1),
    through_turn INTEGER NOT NULL CHECK(through_turn >= 0),
    insight_version INTEGER NOT NULL CHECK(insight_version >= 0),
    operation_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','SUCCEEDED','FAILED','INTERRUPTED')),
    error_code TEXT CHECK(error_code IN ('MODEL_TIMEOUT','MODEL_RESULT_INVALID','TASK_FAILED','DATABASE_UNAVAILABLE','SERVICE_INTERRUPTED','MODEL_REQUEST_INVALID','MODEL_AUTH_FAILED','MODEL_BALANCE_EXHAUSTED','MODEL_NOT_FOUND','MODEL_RATE_LIMITED','MODEL_SERVICE_UNAVAILABLE','MODEL_CONNECTION_FAILED')),
    UNIQUE(discussion_id,run_id,attempt),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id),
    FOREIGN KEY(discussion_id,operation_id) REFERENCES operations(discussion_id,id)
) STRICT;
INSERT INTO summary_jobs_next SELECT * FROM summary_jobs;
DROP TABLE summary_jobs;
ALTER TABLE summary_jobs_next RENAME TO summary_jobs;
CREATE UNIQUE INDEX one_pending_summary ON summary_jobs(discussion_id,run_id) WHERE status='PENDING';
