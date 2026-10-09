"""Scoped synthesis claims and atomic projections, with no provider IO."""
from dataclasses import dataclass
from uuid import UUID, uuid4

from .contracts import InsightBatch, ModelRequest
from .model_gateway import validate_result
from .run_repository import RunRepository


@dataclass(frozen=True)
class SynthesisClaim:
    id: UUID
    request: ModelRequest


class SynthesisRepository(RunRepository):
    def _synthesis_run(self, conn, did, rid):
        return conn.execute("SELECT r.* FROM runs r JOIN discussions d ON d.id=r.discussion_id AND d.current_run_id=r.id WHERE r.discussion_id=? AND r.id=? AND r.status='ACTIVE' AND d.state IN ('RUNNING','SUMMARIZING')", (str(did),str(rid))).fetchone()

    def _insight_request(self, conn, job):
        snapshot = self._snapshot(conn,job['discussion_id'])
        d = snapshot.discussion
        return ModelRequest(task='insights', discussion_id=d.id, run_id=d.run_id, topic=d.topic, expert_count=d.expert_count, roster_revision=d.roster_revision,
                            participants=snapshot.participants, messages=tuple(m for m in snapshot.messages if m.turn_no<=job['through_turn']), through_turn=job['through_turn'], insight_version=job['version'])

    def claim_insights(self, did, rid):
        with self.transaction() as conn:
            run = self._synthesis_run(conn,did,rid)
            if run is None: return None
            count = conn.execute('SELECT count(*) FROM messages WHERE discussion_id=? AND run_id=?',(str(did),str(rid))).fetchone()[0]
            boundary = run['summary_through_turn'] if run['summary_through_turn'] is not None else count
            if boundary == 0 or conn.execute('SELECT 1 FROM insight_jobs WHERE discussion_id=? AND run_id=? AND through_turn=?',(str(did),str(rid),boundary)).fetchone(): return None
            previous = conn.execute('SELECT max(version) FROM (SELECT version FROM insight_jobs WHERE discussion_id=? AND run_id=? UNION ALL SELECT version FROM insight_batches WHERE discussion_id=? AND run_id=?)',(str(did),str(rid),str(did),str(rid))).fetchone()[0] or 0
            conn.execute("UPDATE insight_jobs SET state='SUPERSEDED' WHERE discussion_id=? AND run_id=? AND state='PENDING'",(str(did),str(rid)))
            jid=uuid4()
            conn.execute('INSERT INTO insight_jobs(id,discussion_id,run_id,version,through_turn) VALUES (?,?,?,?,?)',(str(jid),str(did),str(rid),previous+1,boundary))
            job=conn.execute('SELECT * FROM insight_jobs WHERE id=?',(str(jid),)).fetchone()
            return SynthesisClaim(jid,self._insight_request(conn,job))

    def _insight_guard(self, conn, claim):
        req=claim.request
        job=conn.execute("SELECT * FROM insight_jobs WHERE id=? AND discussion_id=? AND run_id=? AND state='PENDING'",(str(claim.id),str(req.discussion_id),str(req.run_id))).fetchone()
        if job is None or (job['version'],job['through_turn']) != (req.insight_version,req.through_turn): return None
        if self._synthesis_run(conn,req.discussion_id,req.run_id) is None: return None
        latest=conn.execute('SELECT max(version) FROM insight_jobs WHERE discussion_id=? AND run_id=?',(str(req.discussion_id),str(req.run_id))).fetchone()[0]
        return job if job['version']==latest else None

    def complete_insights(self, claim, raw):
        with self.transaction() as conn:
            job=self._insight_guard(conn,claim)
            if job is None: return False
            request=self._insight_request(conn,job)
            result=validate_result(request,raw)
            did,rid,version=job['discussion_id'],job['run_id'],job['version']
            batch=InsightBatch(version=version,through_turn=job['through_turn'],items=result.items)
            conn.execute('INSERT INTO insight_batches(discussion_id,run_id,version,through_turn) VALUES (?,?,?,?)',(did,rid,version,batch.through_turn))
            for item in batch.items:
                conn.execute('INSERT INTO insights(id,discussion_id,run_id,batch_version,kind,content) VALUES (?,?,?,?,?,?)',(str(item.id),did,rid,version,item.kind,item.content))
                for source in item.source_message_ids:
                    conn.execute('INSERT INTO insight_sources(discussion_id,run_id,batch_version,insight_id,message_id) VALUES (?,?,?,?,?)',(did,rid,version,str(item.id),str(source)))
            self._event(conn,did,'insights.updated',batch.model_dump(mode='json'),rid)
            conn.execute("UPDATE insight_jobs SET state='SUCCEEDED' WHERE id=?",(str(claim.id),))
            self._snapshot(conn,did)
            return True

    def fail_insights(self, claim, code):
        if code not in ('MODEL_TIMEOUT','MODEL_RESULT_INVALID','TASK_FAILED','DATABASE_UNAVAILABLE'): raise ValueError('invalid insight failure code')
        with self.transaction() as conn:
            if self._insight_guard(conn,claim) is None: return False
            conn.execute("UPDATE insight_jobs SET state='FAILED',error_code=? WHERE id=?",(code,str(claim.id)))
            return True
