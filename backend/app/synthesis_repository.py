"""Scoped synthesis claims and atomic projections, with no provider IO."""
from .model_gateway import MODEL_FAILURE_CODES
from dataclasses import dataclass
from uuid import UUID, uuid4

from .contracts import InsightBatch, ModelRequest, Summary
from .model_gateway import validate_result
from .run_repository import RunRepository
from .repository import timestamp, StoredResponse
from .lifecycle import LifecycleError


@dataclass(frozen=True)
class SynthesisClaim:
    id: UUID
    request: ModelRequest


class SynthesisRepository(RunRepository):
    def _insight_status_event(self, conn, job_id):
        job = conn.execute('SELECT * FROM insight_jobs WHERE id=?', (str(job_id),)).fetchone()
        self._event(conn, job['discussion_id'], 'insights.status_changed',
                    {k: job[k] for k in ('state', 'version', 'through_turn', 'error_code')}, job['run_id'])

    def _synthesis_run(self, conn, did, rid):
        return conn.execute("SELECT r.* FROM runs r JOIN discussions d ON d.id=r.discussion_id AND d.current_run_id=r.id WHERE r.discussion_id=? AND r.id=? AND r.status='ACTIVE' AND d.state IN ('RUNNING','SUMMARIZING')", (str(did),str(rid))).fetchone()

    def _insight_request(self, conn, job):
        snapshot = self._snapshot(conn,job['discussion_id'])
        d = snapshot.discussion
        return ModelRequest(task='insights', discussion_id=d.id, run_id=d.run_id, topic=d.topic, expert_count=d.expert_count, roster_revision=d.roster_revision,
                            participants=snapshot.participants, messages=tuple(m for m in snapshot.messages if m.turn_no<=job['through_turn']), through_turn=job['through_turn'], insight_version=job['version'], insights=snapshot.insights)

    def claim_insights(self, did, rid, through_turn=None):
        with self.transaction() as conn:
            run = self._synthesis_run(conn,did,rid)
            if run is None: return None
            count = conn.execute('SELECT count(*) FROM messages WHERE discussion_id=? AND run_id=?',(str(did),str(rid))).fetchone()[0]
            boundary = run['summary_through_turn'] if run['summary_through_turn'] is not None else count
            if through_turn is not None:
                if through_turn<1 or through_turn>boundary: raise ValueError('invalid insight boundary')
                boundary=through_turn
            if boundary == 0 or conn.execute('SELECT 1 FROM insight_jobs WHERE discussion_id=? AND run_id=? AND through_turn=?',(str(did),str(rid),boundary)).fetchone(): return None
            previous = conn.execute('SELECT max(version) FROM (SELECT version FROM insight_jobs WHERE discussion_id=? AND run_id=? UNION ALL SELECT version FROM insight_batches WHERE discussion_id=? AND run_id=?)',(str(did),str(rid),str(did),str(rid))).fetchone()[0] or 0
            conn.execute("UPDATE insight_jobs SET state='SUPERSEDED' WHERE discussion_id=? AND run_id=? AND state='PENDING'",(str(did),str(rid)))
            jid=uuid4()
            conn.execute('INSERT INTO insight_jobs(id,discussion_id,run_id,version,through_turn) VALUES (?,?,?,?,?)',(str(jid),str(did),str(rid),previous+1,boundary))
            job=conn.execute('SELECT * FROM insight_jobs WHERE id=?',(str(jid),)).fetchone()
            self._insight_status_event(conn, jid)
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
            self._insight_status_event(conn, claim.id)
            self._snapshot(conn,did)
            return True

    def fail_insights(self, claim, code):
        if code not in MODEL_FAILURE_CODES: raise ValueError('invalid insight failure code')
        with self.transaction() as conn:
            if self._insight_guard(conn,claim) is None: return False
            conn.execute("UPDATE insight_jobs SET state='FAILED',error_code=? WHERE id=?",(code,str(claim.id)))
            self._insight_status_event(conn, claim.id)
            return True

    def _summary_request(self,conn,job):
        snapshot=self._snapshot(conn,job['discussion_id']); d=snapshot.discussion
        batch=InsightBatch()
        if job['insight_version']:
            row=conn.execute('SELECT * FROM insight_batches WHERE discussion_id=? AND run_id=? AND version=?',(job['discussion_id'],job['run_id'],job['insight_version'])).fetchone()
            items=[]
            for item in conn.execute('SELECT id,kind,content FROM insights WHERE discussion_id=? AND run_id=? AND batch_version=? ORDER BY id',(job['discussion_id'],job['run_id'],job['insight_version'])):
                sources=[r['message_id'] for r in conn.execute('SELECT message_id FROM insight_sources WHERE discussion_id=? AND run_id=? AND batch_version=? AND insight_id=? ORDER BY message_id',(job['discussion_id'],job['run_id'],job['insight_version'],item['id']))]
                items.append(dict(item)|{'source_message_ids':sources})
            batch=InsightBatch(version=row['version'],through_turn=row['through_turn'],items=items)
        return ModelRequest(task='summary',discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,roster_revision=d.roster_revision,
                            actor_id=next(p.id for p in snapshot.participants if p.kind=='HOST'),participants=snapshot.participants,
                            messages=tuple(m for m in snapshot.messages if m.turn_no<=job['through_turn']),through_turn=job['through_turn'],insights=batch)

    def _new_summary_job(self,conn,did,rid,operation_id=None):
        row=self._discussion(conn,did)
        run=conn.execute('SELECT * FROM runs WHERE discussion_id=? AND id=?',(str(did),str(rid))).fetchone()
        snapshot=self._snapshot(conn,did)
        if row['state']!='SUMMARIZING' or run is None or row['current_run_id']!=str(rid) or run['status']!='ACTIVE' or run['summary_through_turn'] is None: return None
        if conn.execute("SELECT 1 FROM summary_jobs WHERE discussion_id=? AND run_id=? AND status='PENDING'",(str(did),str(rid))).fetchone(): return None
        attempt=(conn.execute('SELECT max(attempt) FROM summary_jobs WHERE discussion_id=? AND run_id=?',(str(did),str(rid))).fetchone()[0] or 0)+1
        jid=uuid4()
        conn.execute('INSERT INTO summary_jobs(id,discussion_id,run_id,attempt,through_turn,insight_version,operation_id) VALUES (?,?,?,?,?,?,?)',
                     (str(jid),str(did),str(rid),attempt,run['summary_through_turn'],
                      snapshot.insights.version if snapshot.insights.through_turn==run['summary_through_turn'] else 0,
                      str(operation_id) if operation_id else None))
        job=conn.execute('SELECT * FROM summary_jobs WHERE id=?',(str(jid),)).fetchone()
        return SynthesisClaim(jid,self._summary_request(conn,job))

    def claim_summary(self,did,rid):
        with self.transaction() as conn:
            if conn.execute('SELECT 1 FROM summary_jobs WHERE discussion_id=? AND run_id=?',(str(did),str(rid))).fetchone(): return None
            return self._new_summary_job(conn,did,rid)

    def _summary_guard(self,conn,claim):
        req=claim.request
        job=conn.execute("SELECT j.* FROM summary_jobs j JOIN runs r ON r.discussion_id=j.discussion_id AND r.id=j.run_id JOIN discussions d ON d.id=j.discussion_id AND d.current_run_id=j.run_id WHERE j.id=? AND j.discussion_id=? AND j.run_id=? AND j.status='PENDING' AND d.state='SUMMARIZING' AND r.status='ACTIVE' AND j.through_turn=r.summary_through_turn",(str(claim.id),str(req.discussion_id),str(req.run_id))).fetchone()
        return job if job is not None and job['through_turn']==req.through_turn else None

    def complete_summary(self,claim,raw):
        with self.transaction() as conn:
            job=self._summary_guard(conn,claim)
            if job is None: return False
            result=validate_result(self._summary_request(conn,job),raw)
            summary=Summary(content=result.content,through_turn=job['through_turn'],created_at=timestamp())
            did,rid=job['discussion_id'],job['run_id']
            conn.execute('INSERT INTO summaries(discussion_id,run_id,content,through_turn,created_at) VALUES (?,?,?,?,?)',(did,rid,summary.content,summary.through_turn,summary.created_at.isoformat()))
            self._event(conn,did,'summary.ready',summary.model_dump(mode='json'),rid)
            conn.execute("UPDATE summary_jobs SET status='SUCCEEDED' WHERE id=?",(str(claim.id),))
            if job['operation_id']: conn.execute("UPDATE operations SET status='SUCCEEDED',error_code=NULL WHERE discussion_id=? AND kind='summary-retry' AND json_extract(response_json,'$.operation_id')=?",(did,job['operation_id']))
            conn.execute("UPDATE runs SET status='COMPLETED',error_code=NULL,ended_at=? WHERE discussion_id=? AND id=?",(timestamp(),did,rid))
            self._transition(conn,did,'COMPLETED')
            self._snapshot(conn,did)
            return True

    def fail_summary(self,claim,code):
        if code not in MODEL_FAILURE_CODES: raise ValueError('invalid summary failure code')
        with self.transaction() as conn:
            job=self._summary_guard(conn,claim)
            if job is None: return False
            did,rid=job['discussion_id'],job['run_id']
            conn.execute("UPDATE summary_jobs SET status='FAILED',error_code=? WHERE id=?",(code,str(claim.id)))
            conn.execute("UPDATE runs SET status='FAILED',error_code=?,ended_at=? WHERE discussion_id=? AND id=?",(code,timestamp(),did,rid))
            op=job['operation_id']
            if op: conn.execute("UPDATE operations SET status='FAILED',error_code=? WHERE discussion_id=? AND kind='summary-retry' AND json_extract(response_json,'$.operation_id')=?",(code,did,op))
            else: op=conn.execute("SELECT id FROM operations WHERE discussion_id=? AND kind='start' AND json_extract(response_json,'$.run_id')=? ORDER BY rowid LIMIT 1",(did,rid)).fetchone()['id']
            self._event(conn,did,'operation.failed',{'operation_id':op,'stage':'summary','code':code,'message':'总结生成失败，消息和观点已保留，可以重试总结。','retryable':True},rid)
            self._transition(conn,did,'FAILED','summary',code)
            return True

    def admit_summary_retry(self,did,key,settings,gateway_available):
        did=str(did)
        with self.transaction() as conn:
            cached,digest=self._replay(conn,did,'summary-retry',key,{})
            if cached:
                job=conn.execute("SELECT * FROM summary_jobs WHERE discussion_id=? AND operation_id=? AND status='PENDING'",(did,cached.body['operation_id'])).fetchone()
                return cached,SynthesisClaim(UUID(job['id']),self._summary_request(conn,job)) if job else None
            row=self._discussion(conn,did); rid=row['current_run_id']
            pending=conn.execute("SELECT * FROM summary_jobs WHERE discussion_id=? AND run_id=? AND status='PENDING'",(did,rid)).fetchone()
            if row['state']=='SUMMARIZING' and pending and pending['operation_id']:
                op=conn.execute('SELECT response_status,response_json FROM operations WHERE discussion_id=? AND id=?',(did,pending['operation_id'])).fetchone()
                import json
                response=StoredResponse(op['response_status'],json.loads(op['response_json']))
                self._save_operation(conn,uuid4(),did,did,'summary-retry',key,digest,'RUNNING',response)
                return response,SynthesisClaim(UUID(pending['id']),self._summary_request(conn,pending))
            if row['state'] not in ('FAILED','INTERRUPTED') or row['failure_stage']!='summary' or rid is None:
                raise LifecycleError('INVALID_STATE','只有总结失败或中断后才能重试；进行中的重试请使用原操作。')
            run=conn.execute('SELECT * FROM runs WHERE discussion_id=? AND id=?',(did,rid)).fetchone()
            if run is None or run['summary_through_turn'] is None or pending is not None:
                raise LifecycleError('INVALID_STATE','总结消息边界或任务状态不完整。')
            if not gateway_available: raise LifecycleError('MODEL_NOT_CONFIGURED','模型尚未配置，请检查后端 MODEL_PROVIDER、MODEL_BASE_URL、MODEL_NAME 和 MODEL_API_KEY。')
            self._capacity(conn,settings.discussion_max_active)
            conn.execute("UPDATE runs SET status='ACTIVE',error_code=NULL,ended_at=NULL WHERE discussion_id=? AND id=?",(did,rid))
            self._transition(conn,did,'SUMMARIZING')
            op_id=uuid4()
            response=StoredResponse(202,{'operation_id':str(op_id),'discussion_id':did,'state':'SUMMARIZING','run_id':rid})
            self._save_operation(conn,op_id,did,did,'summary-retry',key,digest,'RUNNING',response)
            claim=self._new_summary_job(conn,did,rid,op_id)
            if claim is None: raise LifecycleError('INVALID_STATE','总结任务无法领取。')
            self._snapshot(conn,did)
            return response,claim
