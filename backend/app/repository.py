"""Scoped SQLite reads and atomic commands/events; never wait for a model here."""
import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .contracts import CreateDiscussion, Discussion, DiscussionList, EventAdapter, Snapshot
from .database import Database
from .lifecycle import LifecycleError, RepositoryUnavailable


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


@dataclass(frozen=True)
class StoredResponse:
    status: int
    body: dict


class DiscussionRepository:
    def __init__(self, database: Database):
        self.database = database

    @contextmanager
    def transaction(self, *, write=True):
        try:
            with self.database.connect(create=False) as conn:
                conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                try:
                    yield conn
                    conn.execute('COMMIT')
                except BaseException:
                    if conn.in_transaction:
                        conn.execute('ROLLBACK')
                    raise
        except sqlite3.Error:
            raise RepositoryUnavailable() from None

    def _discussion(self, conn, discussion_id):
        row = conn.execute('SELECT * FROM discussions WHERE id=?', (str(discussion_id),)).fetchone()
        if row is None:
            raise LifecycleError('DISCUSSION_NOT_FOUND', '讨论不存在。')
        return row

    def _public_discussion(self, row):
        return Discussion.model_validate({k: row[k] for k in ('id','topic','expert_count','state','version','roster_revision','failure_stage','created_at','updated_at')} | {'run_id': row['current_run_id']})

    def _replay(self, conn, scope, kind, key, body):
        digest = hashlib.sha256(encoded(body).encode('utf-8')).hexdigest()
        row = conn.execute('SELECT * FROM operations WHERE scope=? AND kind=? AND idempotency_key=?', (scope, kind, str(key))).fetchone()
        if row and row['request_hash'] != digest:
            raise LifecycleError('IDEMPOTENCY_CONFLICT', '同一操作标识不能用于不同参数。')
        return (StoredResponse(row['response_status'], json.loads(row['response_json'])) if row else None), digest

    def _save_operation(self, conn, operation_id, discussion_id, scope, kind, key, digest, status, response):
        conn.execute('INSERT INTO operations(id,discussion_id,scope,kind,idempotency_key,request_hash,status,response_status,response_json) VALUES (?,?,?,?,?,?,?,?,?)',
                     (str(operation_id), str(discussion_id), scope, kind, str(key), digest, status, response.status, encoded(response.body)))

    def _event(self, conn, discussion_id, kind, payload, run_id=None):
        row = self._discussion(conn, discussion_id)
        event = EventAdapter.validate_python(dict(schema_version=1, discussion_id=discussion_id, run_id=run_id, seq=row['last_event_seq'] + 1, type=kind, occurred_at=timestamp(), payload=payload))
        value = event.model_dump(mode='json')
        conn.execute('INSERT INTO events(discussion_id,seq,run_id,schema_version,type,occurred_at,payload) VALUES (?,?,?,?,?,?,?)',
                     (value['discussion_id'], value['seq'], value['run_id'], value['schema_version'], value['type'], value['occurred_at'], encoded(value['payload'])))

    def _snapshot(self, conn, discussion_id):
        row = self._discussion(conn, discussion_id)
        did, revision, run_id = row['id'], row['roster_revision'], row['current_run_id']
        people = [dict(r) for r in conn.execute('SELECT id,discussion_id,roster_revision,kind,name,title,stance,color FROM participants WHERE discussion_id=? AND roster_revision=? ORDER BY CASE kind WHEN \'HOST\' THEN 0 ELSE 1 END,id', (did, revision))]
        roles, messages, insights, summary = [], [], {'version': 0, 'through_turn': 0, 'items': []}, None
        if run_id:
            roles = [dict(r) for r in conn.execute('SELECT participant_id,state,public_focus,version FROM role_states WHERE discussion_id=? AND run_id=? ORDER BY participant_id', (did, run_id))]
            messages = [dict(r) for r in conn.execute('SELECT id,discussion_id,run_id,participant_id,turn_no,kind,content,created_at FROM messages WHERE discussion_id=? AND run_id=? ORDER BY turn_no', (did, run_id))]
            batch = conn.execute('SELECT version,through_turn FROM insight_batches WHERE discussion_id=? AND run_id=? ORDER BY version DESC LIMIT 1', (did, run_id)).fetchone()
            if batch:
                items = []
                for r in conn.execute('SELECT id,kind,content FROM insights WHERE discussion_id=? AND run_id=? AND batch_version=? ORDER BY id', (did, run_id, batch['version'])):
                    sources = [s['message_id'] for s in conn.execute('SELECT message_id FROM insight_sources WHERE discussion_id=? AND run_id=? AND batch_version=? AND insight_id=? ORDER BY message_id', (did, run_id, batch['version'], r['id']))]
                    items.append(dict(r) | {'source_message_ids': sources})
                insights = dict(batch) | {'items': items}
            value = conn.execute('SELECT content,through_turn,created_at FROM summaries WHERE discussion_id=? AND run_id=?', (did, run_id)).fetchone()
            summary = dict(value) if value else None
        return Snapshot.model_validate(dict(discussion=self._public_discussion(row), participants=people, role_states=roles, messages=messages, insights=insights, summary=summary, last_event_seq=row['last_event_seq']))

    def create(self, body: CreateDiscussion, key: UUID):
        with self.transaction() as conn:
            cached, digest = self._replay(conn, 'global', 'create', key, body.model_dump(mode='json'))
            if cached:
                return cached
            did, op_id, at = uuid4(), uuid4(), timestamp()
            conn.execute('INSERT INTO discussions(id,topic,expert_count,created_at,updated_at) VALUES (?,?,?,?,?)', (str(did), body.topic, body.expert_count, at, at))
            self._event(conn, did, 'discussion.state_changed', {'state':'DRAFT','version':0,'failure_stage':None})
            response = StoredResponse(201, self._snapshot(conn, did).model_dump(mode='json'))
            self._save_operation(conn, op_id, did, 'global', 'create', key, digest, 'SUCCEEDED', response)
            return response

    def snapshot(self, discussion_id: UUID):
        with self.transaction(write=False) as conn:
            return self._snapshot(conn, discussion_id)

    def listing(self, status='active', limit=20, cursor=None):
        boundary = None
        if cursor is not None:
            try:
                raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
                boundary = json.loads(raw)
                if not isinstance(boundary, list) or len(boundary) != 2 or not all(isinstance(x,str) for x in boundary):
                    raise ValueError()
                if datetime.fromisoformat(boundary[0]).tzinfo is None:
                    raise ValueError()
                boundary[1] = str(UUID(boundary[1]))
            except (ValueError, TypeError, UnicodeError):
                raise LifecycleError('VALIDATION_ERROR', '列表游标格式无效。') from None
        where, args = [], []
        if status == 'active':
            where.append("state IN ('RUNNING','SUMMARIZING')")
        if boundary:
            where.append('(created_at < ? OR (created_at = ? AND id < ?))')
            args.extend([boundary[0], boundary[0], boundary[1]])
        sql = 'SELECT * FROM discussions' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY created_at DESC,id DESC LIMIT ?'
        with self.transaction(write=False) as conn:
            rows = list(conn.execute(sql, [*args, limit + 1]))
            selected = rows[:limit]
            next_cursor = None
            if len(rows) > limit:
                last = selected[-1]
                next_cursor = base64.urlsafe_b64encode(encoded([last['created_at'], last['id']]).encode()).decode().rstrip('=')
            return DiscussionList(items=[self._public_discussion(row) for row in selected], next_cursor=next_cursor)

    def _transition(self, conn, discussion_id, state, failure_stage=None):
        row = self._discussion(conn, discussion_id)
        version = row['version'] + 1
        conn.execute('UPDATE discussions SET state=?,failure_stage=?,version=?,updated_at=? WHERE id=?', (state, failure_stage, version, timestamp(), str(discussion_id)))
        self._event(conn, discussion_id, 'discussion.state_changed', {'state':state,'version':version,'failure_stage':failure_stage}, row['current_run_id'])

    def _capacity(self, conn, max_active):
        from .lifecycle import require_capacity
        count = conn.execute("SELECT count(*) FROM discussions WHERE state IN ('GENERATING','RUNNING','SUMMARIZING')").fetchone()[0]
        require_capacity(count, max_active)

    def admit_generation(self, discussion_id, key, max_active, gateway_available):
        from .lifecycle import generation_revision
        did = str(discussion_id)
        with self.transaction() as conn:
            cached, digest = self._replay(conn, did, 'roster-generation', key, {})
            if cached:
                op = conn.execute('SELECT status FROM operations WHERE id=? AND discussion_id=?', (cached.body['operation_id'], did)).fetchone()
                return cached, op['status'] == 'ACCEPTED'
            row = self._discussion(conn, did)
            generation_revision(row['state'], row['failure_stage'], row['roster_revision'])
            if not gateway_available:
                raise LifecycleError('MODEL_NOT_CONFIGURED', '真实模型适配尚未实现，请使用 mock 模式。')
            self._capacity(conn, max_active)
            op_id = uuid4()
            self._transition(conn, did, 'GENERATING')
            response = StoredResponse(202, {'operation_id':str(op_id),'discussion_id':did,'state':'GENERATING','run_id':None})
            self._save_operation(conn, op_id, did, did, 'roster-generation', key, digest, 'ACCEPTED', response)
            return response, True

    def claim_generation(self, operation_id):
        from .contracts import ModelRequest
        with self.transaction() as conn:
            op = conn.execute("SELECT * FROM operations WHERE id=? AND kind='roster-generation' AND status='ACCEPTED'", (str(operation_id),)).fetchone()
            if not op:
                return None
            row = self._discussion(conn, op['discussion_id'])
            if row['state'] != 'GENERATING':
                return None
            conn.execute("UPDATE operations SET status='RUNNING' WHERE id=? AND discussion_id=? AND status='ACCEPTED'", (str(operation_id), row['id']))
            return ModelRequest(task='roster', discussion_id=row['id'], topic=row['topic'], expert_count=row['expert_count'], roster_revision=row['roster_revision']+1)

    def complete_generation(self, operation_id, request, result):
        from .model_gateway import validate_result
        result = validate_result(request, result)
        with self.transaction() as conn:
            op = conn.execute("SELECT * FROM operations WHERE id=? AND discussion_id=? AND kind='roster-generation' AND status='RUNNING'", (str(operation_id), str(request.discussion_id))).fetchone()
            if not op:
                return False
            row = self._discussion(conn, request.discussion_id)
            if row['state'] != 'GENERATING' or row['roster_revision']+1 != request.roster_revision:
                return False
            did, revision = row['id'], request.roster_revision
            conn.execute('INSERT INTO rosters(discussion_id,revision) VALUES (?,?)', (did, revision))
            for person in result.participants:
                conn.execute('INSERT INTO participants(id,discussion_id,roster_revision,kind,name,title,stance,color) VALUES (?,?,?,?,?,?,?,?)',
                             (str(person.id),str(person.discussion_id),person.roster_revision,person.kind,person.name,person.title,person.stance,person.color))
            conn.execute('UPDATE discussions SET roster_revision=? WHERE id=?', (revision,did))
            self._event(conn, did, 'roster.ready', {'roster_revision':revision,'participants':[p.model_dump(mode='json') for p in result.participants]})
            self._transition(conn, did, 'READY')
            conn.execute("UPDATE operations SET status='SUCCEEDED',error_code=NULL WHERE id=? AND discussion_id=?", (str(operation_id),did))
            self._snapshot(conn,did)  # Validate the entire public projection before commit.
            return True

    def fail_generation(self, operation_id, code, message):
        with self.transaction() as conn:
            op = conn.execute("SELECT * FROM operations WHERE id=? AND kind='roster-generation' AND status IN ('ACCEPTED','RUNNING')", (str(operation_id),)).fetchone()
            if not op:
                return False
            row = self._discussion(conn, op['discussion_id'])
            if row['state'] != 'GENERATING':
                return False
            conn.execute("UPDATE operations SET status='FAILED',error_code=? WHERE id=? AND discussion_id=?", (code,str(operation_id),row['id']))
            self._event(conn,row['id'],'operation.failed',{'operation_id':str(operation_id),'stage':'roster','code':code,'message':message,'retryable':True})
            self._transition(conn,row['id'],'FAILED','roster')
            return True
