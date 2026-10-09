ALTER TABLE runs ADD COLUMN cycle INTEGER NOT NULL DEFAULT 0 CHECK(cycle >= 0);
ALTER TABLE runs ADD COLUMN stop_reason TEXT CHECK(stop_reason IN ('turn_limit','time_limit','host_end'));
ALTER TABLE runs ADD COLUMN error_code TEXT;
ALTER TABLE discussions ADD COLUMN failure_code TEXT;
CREATE TABLE turn_claims (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    roster_revision INTEGER NOT NULL,
    cycle INTEGER NOT NULL CHECK(cycle >= 1),
    based_on_turn INTEGER NOT NULL CHECK(based_on_turn >= 0),
    participant_id TEXT NOT NULL,
    participation_kind TEXT CHECK(participation_kind IN ('REQUEST','INTERRUPT','SUPPLEMENT','REBUT')),
    target_message_id TEXT,
    host_task TEXT CHECK(host_task IN ('opening','followup','linking')),
    public_focus TEXT NOT NULL DEFAULT '' CHECK(length(public_focus) <= 140),
    status TEXT NOT NULL CHECK(status IN ('PREPARING','SPEAKING','COMMITTED','CANCELLED')),
    UNIQUE(discussion_id,run_id,cycle),
    CHECK((host_task IS NOT NULL AND participation_kind IS NULL AND target_message_id IS NULL) OR (host_task IS NULL AND participation_kind IS NOT NULL)),
    CHECK(participation_kind NOT IN ('SUPPLEMENT','REBUT') OR target_message_id IS NOT NULL),
    FOREIGN KEY(discussion_id,run_id,roster_revision) REFERENCES runs(discussion_id,id,roster_revision),
    FOREIGN KEY(discussion_id,roster_revision,participant_id) REFERENCES participants(discussion_id,roster_revision,id),
    FOREIGN KEY(discussion_id,run_id,target_message_id) REFERENCES messages(discussion_id,run_id,id)
) STRICT;
CREATE UNIQUE INDEX one_pending_turn ON turn_claims(discussion_id,run_id) WHERE status IN ('PREPARING','SPEAKING');
