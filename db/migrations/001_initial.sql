CREATE TABLE discussions (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL CHECK(length(trim(topic)) BETWEEN 1 AND 500),
    expert_count INTEGER NOT NULL DEFAULT 4 CHECK(expert_count BETWEEN 2 AND 6),
    state TEXT NOT NULL DEFAULT 'DRAFT' CHECK(state IN ('DRAFT','GENERATING','READY','RUNNING','SUMMARIZING','COMPLETED','FAILED','INTERRUPTED')),
    version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0),
    roster_revision INTEGER NOT NULL DEFAULT 0 CHECK(roster_revision >= 0),
    current_run_id TEXT,
    failure_stage TEXT CHECK(failure_stage IN ('roster','discussion','summary')),
    last_event_seq INTEGER NOT NULL DEFAULT 0 CHECK(last_event_seq >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(id,current_run_id) REFERENCES runs(discussion_id,id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE rosters (
    discussion_id TEXT NOT NULL REFERENCES discussions(id),
    revision INTEGER NOT NULL CHECK(revision >= 1),
    confirmed_at TEXT,
    PRIMARY KEY(discussion_id,revision)
) STRICT;
CREATE TABLE participants (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    roster_revision INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('HOST','EXPERT')),
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 50),
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 100),
    stance TEXT NOT NULL CHECK(length(trim(stance)) BETWEEN 1 AND 140),
    color TEXT NOT NULL CHECK(color GLOB '#[0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F][0-9A-F]'),
    UNIQUE(discussion_id,roster_revision,id),
    UNIQUE(discussion_id,roster_revision,name),
    UNIQUE(discussion_id,roster_revision,color),
    FOREIGN KEY(discussion_id,roster_revision) REFERENCES rosters(discussion_id,revision)
) STRICT;
CREATE UNIQUE INDEX one_host_per_roster ON participants(discussion_id,roster_revision) WHERE kind='HOST';
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    roster_revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','COMPLETED','FAILED','INTERRUPTED')),
    max_turns INTEGER NOT NULL DEFAULT 20 CHECK(max_turns > 0),
    max_seconds INTEGER NOT NULL DEFAULT 300 CHECK(max_seconds > 0),
    summary_through_turn INTEGER CHECK(summary_through_turn >= 0),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at TEXT,
    UNIQUE(discussion_id,id),
    UNIQUE(discussion_id,id,roster_revision),
    UNIQUE(discussion_id,roster_revision),
    FOREIGN KEY(discussion_id,roster_revision) REFERENCES rosters(discussion_id,revision)
) STRICT;
CREATE UNIQUE INDEX one_active_run ON runs(discussion_id) WHERE status='ACTIVE';
CREATE TABLE role_states (
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    roster_revision INTEGER NOT NULL,
    participant_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'IDLE' CHECK(state IN ('IDLE','PREPARING','SPEAKING')),
    public_focus TEXT NOT NULL DEFAULT '' CHECK(length(public_focus) <= 140),
    version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0),
    PRIMARY KEY(discussion_id,run_id,participant_id),
    FOREIGN KEY(discussion_id,run_id,roster_revision) REFERENCES runs(discussion_id,id,roster_revision),
    FOREIGN KEY(discussion_id,roster_revision,participant_id) REFERENCES participants(discussion_id,roster_revision,id)
) STRICT;
CREATE UNIQUE INDEX one_speaker ON role_states(discussion_id,run_id) WHERE state='SPEAKING';
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    roster_revision INTEGER NOT NULL,
    participant_id TEXT NOT NULL,
    turn_no INTEGER NOT NULL CHECK(turn_no >= 1),
    kind TEXT NOT NULL CHECK(kind IN ('opening','statement','followup','linking')),
    content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 400),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(discussion_id,run_id,id),
    UNIQUE(discussion_id,run_id,turn_no),
    FOREIGN KEY(discussion_id,run_id,roster_revision) REFERENCES runs(discussion_id,id,roster_revision),
    FOREIGN KEY(discussion_id,roster_revision,participant_id) REFERENCES participants(discussion_id,roster_revision,id)
) STRICT;
CREATE TABLE speaking_intents (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    roster_revision INTEGER NOT NULL,
    participant_id TEXT NOT NULL,
    cycle INTEGER NOT NULL CHECK(cycle >= 1),
    based_on_turn INTEGER NOT NULL CHECK(based_on_turn >= 0),
    kind TEXT NOT NULL CHECK(kind IN ('PASS','REQUEST','INTERRUPT','SUPPLEMENT','REBUT')),
    target_message_id TEXT,
    relevance INTEGER NOT NULL CHECK(relevance BETWEEN 0 AND 100),
    public_focus TEXT NOT NULL CHECK(length(trim(public_focus)) BETWEEN 1 AND 140),
    UNIQUE(discussion_id,run_id,participant_id,cycle),
    CHECK(kind NOT IN ('SUPPLEMENT','REBUT') OR target_message_id IS NOT NULL),
    FOREIGN KEY(discussion_id,run_id,roster_revision) REFERENCES runs(discussion_id,id,roster_revision),
    FOREIGN KEY(discussion_id,roster_revision,participant_id) REFERENCES participants(discussion_id,roster_revision,id),
    FOREIGN KEY(discussion_id,run_id,target_message_id) REFERENCES messages(discussion_id,run_id,id)
) STRICT;
CREATE TABLE insight_batches (
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    through_turn INTEGER NOT NULL CHECK(through_turn >= 0),
    PRIMARY KEY(discussion_id,run_id,version),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id)
) STRICT;
CREATE TABLE insights (
    id TEXT NOT NULL,
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    batch_version INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('consensus','disagreement')),
    content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 500),
    PRIMARY KEY(discussion_id,run_id,batch_version,id),
    FOREIGN KEY(discussion_id,run_id,batch_version) REFERENCES insight_batches(discussion_id,run_id,version)
) STRICT;
CREATE TABLE insight_sources (
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    batch_version INTEGER NOT NULL,
    insight_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    PRIMARY KEY(discussion_id,run_id,batch_version,insight_id,message_id),
    FOREIGN KEY(discussion_id,run_id,batch_version,insight_id) REFERENCES insights(discussion_id,run_id,batch_version,id),
    FOREIGN KEY(discussion_id,run_id,message_id) REFERENCES messages(discussion_id,run_id,id)
) STRICT;
CREATE TABLE summaries (
    discussion_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 4000),
    through_turn INTEGER NOT NULL CHECK(through_turn >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(discussion_id,run_id),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id)
) STRICT;
CREATE TABLE operations (
    id TEXT PRIMARY KEY,
    discussion_id TEXT REFERENCES discussions(id),
    scope TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('create','roster-generation','start','summary-retry')),
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
    status TEXT NOT NULL CHECK(status IN ('ACCEPTED','RUNNING','SUCCEEDED','FAILED','INTERRUPTED')),
    response_status INTEGER NOT NULL CHECK(response_status BETWEEN 100 AND 599),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    error_code TEXT,
    UNIQUE(scope,kind,idempotency_key),
    CHECK((kind='create' AND scope='global') OR (kind!='create' AND discussion_id IS NOT NULL AND scope=discussion_id))
) STRICT;
CREATE TABLE events (
    discussion_id TEXT NOT NULL REFERENCES discussions(id),
    seq INTEGER NOT NULL CHECK(seq >= 1),
    run_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version=1),
    type TEXT NOT NULL CHECK(type IN ('discussion.state_changed','roster.ready','participant.status_changed','turn.committed','insights.updated','summary.ready','operation.failed')),
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    payload TEXT NOT NULL CHECK(json_valid(payload)),
    PRIMARY KEY(discussion_id,seq),
    FOREIGN KEY(discussion_id,run_id) REFERENCES runs(discussion_id,id)
) STRICT;
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
CREATE INDEX discussion_listing ON discussions(state,created_at,id);
