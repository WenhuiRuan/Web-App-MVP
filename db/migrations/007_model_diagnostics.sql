CREATE UNIQUE INDEX scoped_turn_claim ON turn_claims(discussion_id,run_id,id);
CREATE TABLE model_diagnostics (
    id INTEGER PRIMARY KEY,
    discussion_id TEXT NOT NULL REFERENCES discussions(id),
    run_id TEXT,
    roster_revision INTEGER NOT NULL CHECK(roster_revision>=1),
    actor_id TEXT,
    turn_claim_id TEXT,
    call_id TEXT NOT NULL,
    task TEXT NOT NULL CHECK(task IN ('roster','intent','utterance','host_control','insights','summary')),
    host_task TEXT CHECK(host_task IN ('opening','followup','linking')),
    cycle INTEGER NOT NULL CHECK(cycle>=0),
    message_position INTEGER NOT NULL CHECK(message_position>=0),
    attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 3),
    stage TEXT CHECK(stage IN ('single','draft','review','repair')),
    outcome TEXT NOT NULL CHECK(outcome IN ('SUCCEEDED','FAILED','CANCELLED','DEADLINE','HOST_SKIPPED')),
    error_code TEXT,
    failure_type TEXT CHECK(failure_type IN ('EMPTY_CONTENT','OUTPUT_TRUNCATED','OUTPUT_REJECTED','JSON_PARSE','FIELD_STRUCTURE','SENTENCE_COUNT','SENTENCE_BOUNDARY','SENTENCE_LENGTH','UTTERANCE_LENGTH','RESULT_CONSTRAINT','MODEL_ERROR','INTERNAL_ERROR','CANCELLED','BUDGET_EXHAUSTED')),
    duration_ms INTEGER NOT NULL CHECK(duration_ms>=0),
    occurred_at TEXT NOT NULL,
    UNIQUE(call_id,attempt,outcome),
    CHECK(outcome!='HOST_SKIPPED' OR (turn_claim_id IS NOT NULL AND host_task IN ('followup','linking') AND error_code='MODEL_RESULT_INVALID')),
    FOREIGN KEY(discussion_id,run_id,roster_revision) REFERENCES runs(discussion_id,id,roster_revision),
    FOREIGN KEY(discussion_id,roster_revision,actor_id) REFERENCES participants(discussion_id,roster_revision,id),
    FOREIGN KEY(discussion_id,run_id,turn_claim_id) REFERENCES turn_claims(discussion_id,run_id,id)
) STRICT;
CREATE INDEX model_diagnostics_by_discussion ON model_diagnostics(discussion_id,id DESC);
CREATE UNIQUE INDEX one_host_skip_per_claim ON model_diagnostics(turn_claim_id) WHERE outcome='HOST_SKIPPED';
