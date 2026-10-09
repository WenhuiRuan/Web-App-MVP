"""Transactional run progression. All provider IO belongs outside this module."""
from dataclasses import dataclass
from datetime import datetime,timezone
from uuid import UUID,uuid4

from .contracts import Message,ModelRequest,Snapshot
from .lifecycle import LifecycleError
from .model_gateway import validate_result,utterance_text
from .repository import DiscussionRepository,timestamp
from .scheduling import stop_reason,validate_intents


@dataclass(frozen=True)
class RunContext:
    snapshot: Snapshot
    cycle: int
    remaining_seconds: float


@dataclass(frozen=True)
class TurnClaim:
    id: UUID
    request: ModelRequest


class RunRepository(DiscussionRepository):
    def _active(self,conn,did,rid):
        return conn.execute("SELECT r.* FROM runs r JOIN discussions d ON d.id=r.discussion_id AND d.current_run_id=r.id WHERE r.discussion_id=? AND r.id=? AND r.status='ACTIVE' AND d.state='RUNNING'",(str(did),str(rid))).fetchone()

    def _budget(self,conn,row):
        count=conn.execute('SELECT count(*) FROM messages WHERE discussion_id=? AND run_id=?',(row['discussion_id'],row['id'])).fetchone()[0]
        elapsed=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(row['started_at'])).total_seconds())
        reason=stop_reason(count,row['max_turns'],elapsed,row['max_seconds'])
        if reason: self._finish(conn,row,reason,count)
        return reason,count,max(0,row['max_seconds']-elapsed)

    def _guard(self,conn,context):
        d=context.snapshot.discussion
        row=self._active(conn,d.id,d.run_id)
        if row is None or row['cycle']!=context.cycle or row['roster_revision']!=d.roster_revision: return None
        count=conn.execute('SELECT count(*) FROM messages WHERE discussion_id=? AND run_id=?',(str(d.id),str(d.run_id))).fetchone()[0]
        if count!=len(context.snapshot.messages): return None
        reason,_,_=self._budget(conn,row)
        return None if reason else row

    def begin_cycle(self,did,rid):
        with self.transaction() as conn:
            row=self._active(conn,did,rid)
            if row is None: return None
            reason,count,remaining=self._budget(conn,row)
            if reason: return None
            if conn.execute("SELECT 1 FROM turn_claims WHERE discussion_id=? AND run_id=? AND status IN ('PREPARING','SPEAKING')",(str(did),str(rid))).fetchone(): return None
            cycle=row['cycle']+1
            conn.execute('UPDATE runs SET cycle=? WHERE discussion_id=? AND id=?',(cycle,str(did),str(rid)))
            if count:
                for person in conn.execute("SELECT id FROM participants WHERE discussion_id=? AND roster_revision=? AND kind='EXPERT'",(str(did),row['roster_revision'])):
                    self._role(conn,did,rid,person['id'],'PREPARING','正在评估是否参与')
            return RunContext(self._snapshot(conn,did),cycle,remaining)

    def record_intents(self,context,values):
        validate_intents(context.snapshot,values)
        d=context.snapshot.discussion
        with self.transaction() as conn:
            if self._guard(conn,context) is None: return False
            if conn.execute('SELECT 1 FROM speaking_intents WHERE discussion_id=? AND run_id=? AND cycle=?',(str(d.id),str(d.run_id),context.cycle)).fetchone(): return False
            for actor,result in values.items():
                conn.execute('INSERT INTO speaking_intents(id,discussion_id,run_id,roster_revision,participant_id,cycle,based_on_turn,kind,target_message_id,relevance,public_focus) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                             (str(uuid4()),str(d.id),str(d.run_id),d.roster_revision,str(actor),context.cycle,len(context.snapshot.messages),result.kind,str(result.target_message_id) if result.target_message_id else None,result.relevance,result.public_focus))
            for p in context.snapshot.participants:
                if p.kind=='EXPERT': self._role(conn,d.id,d.run_id,p.id,'IDLE',values[p.id].public_focus if p.id in values else '本轮参与评估未成功')
            return True

    def prepare_turn(self,context,actor,**task):
        d=context.snapshot.discussion
        request=ModelRequest(task='utterance',discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,roster_revision=d.roster_revision,actor_id=actor,participants=context.snapshot.participants,messages=context.snapshot.messages,cycle=context.cycle,**task)
        with self.transaction() as conn:
            if self._guard(conn,context) is None: return None
            if conn.execute('SELECT 1 FROM turn_claims WHERE discussion_id=? AND run_id=? AND cycle=?',(str(d.id),str(d.run_id),context.cycle)).fetchone():
                raise LifecycleError('TURN_IN_PROGRESS','本轮已经领取发言。')
            if request.participation_kind:
                intent=conn.execute('SELECT kind,target_message_id FROM speaking_intents WHERE discussion_id=? AND run_id=? AND cycle=? AND participant_id=?',(str(d.id),str(d.run_id),context.cycle,str(actor))).fetchone()
                target=str(request.target_message_id) if request.target_message_id else None
                if intent is None or (intent['kind'],intent['target_message_id'])!=(request.participation_kind,target):
                    raise LifecycleError('INVALID_INTENT','发言必须对应本轮已验证意图。')
            claim_id=uuid4()
            conn.execute("INSERT INTO turn_claims(id,discussion_id,run_id,roster_revision,cycle,based_on_turn,participant_id,participation_kind,target_message_id,host_task,public_focus,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,'PREPARING')",(str(claim_id),str(d.id),str(d.run_id),d.roster_revision,context.cycle,len(context.snapshot.messages),str(actor),request.participation_kind,str(request.target_message_id) if request.target_message_id else None,request.host_task,request.public_focus))
            self._role(conn,d.id,d.run_id,actor,'PREPARING',request.public_focus)
            return TurnClaim(claim_id,request)

    def _claim(self,conn,context,claim_id,status):
        d=context.snapshot.discussion
        if self._guard(conn,context) is None: return None
        return conn.execute('SELECT * FROM turn_claims WHERE id=? AND discussion_id=? AND run_id=? AND cycle=? AND based_on_turn=? AND status=?',(str(claim_id),str(d.id),str(d.run_id),context.cycle,len(context.snapshot.messages),status)).fetchone()

    def mark_speaking(self,context,claim_id):
        with self.transaction() as conn:
            claim=self._claim(conn,context,claim_id,'PREPARING')
            if claim is None: return False
            conn.execute("UPDATE turn_claims SET status='SPEAKING' WHERE id=?",(str(claim_id),))
            self._role(conn,claim['discussion_id'],claim['run_id'],claim['participant_id'],'SPEAKING',claim['public_focus'])
            return True

    def commit_turn(self,context,claim_id,raw):
        d=context.snapshot.discussion
        with self.transaction() as conn:
            claim=self._claim(conn,context,claim_id,'SPEAKING')
            if claim is None: return False
            request=ModelRequest(task='utterance',discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,roster_revision=d.roster_revision,actor_id=claim['participant_id'],participants=context.snapshot.participants,messages=context.snapshot.messages,cycle=context.cycle,host_task=claim['host_task'],participation_kind=claim['participation_kind'],target_message_id=claim['target_message_id'],public_focus=claim['public_focus'])
            result=validate_result(request,raw)
            message=Message(id=claim_id,discussion_id=d.id,run_id=d.run_id,participant_id=claim['participant_id'],turn_no=len(context.snapshot.messages)+1,kind=claim['host_task'] or 'statement',content=utterance_text(result),created_at=timestamp())
            conn.execute('INSERT INTO messages(id,discussion_id,run_id,roster_revision,participant_id,turn_no,kind,content,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(str(message.id),str(d.id),str(d.run_id),d.roster_revision,str(message.participant_id),message.turn_no,message.kind,message.content,message.created_at.isoformat()))
            self._event(conn,d.id,'turn.committed',message.model_dump(mode='json'),d.run_id)
            self._role(conn,d.id,d.run_id,message.participant_id,'IDLE',claim['public_focus'])
            conn.execute("UPDATE turn_claims SET status='COMMITTED' WHERE id=?",(str(claim_id),))
            row=self._active(conn,d.id,d.run_id)
            self._budget(conn,row)
            self._snapshot(conn,d.id)
            return True

    def _finish(self,conn,row,reason,count):
        self._reset_roles(conn,row['discussion_id'],row['id'])
        conn.execute('UPDATE runs SET summary_through_turn=?,stop_reason=? WHERE discussion_id=? AND id=?',(count,reason,row['discussion_id'],row['id']))
        self._transition(conn,row['discussion_id'],'SUMMARIZING')

    def finish_run(self,did,rid,reason):
        if reason not in ('turn_limit','time_limit','host_end'): raise ValueError('invalid stop reason')
        with self.transaction() as conn:
            row=self._active(conn,did,rid)
            if row is None: return False
            count=conn.execute('SELECT count(*) FROM messages WHERE discussion_id=? AND run_id=?',(str(did),str(rid))).fetchone()[0]
            self._finish(conn,row,reason,count)
            return True

    def fail_run(self,did,rid,code):
        if code not in ('MODEL_TIMEOUT','MODEL_RESULT_INVALID','TASK_FAILED','DATABASE_UNAVAILABLE'): raise ValueError('invalid failure code')
        with self.transaction() as conn:
            row=self._active(conn,did,rid)
            if row is None: return False
            self._reset_roles(conn,did,rid)
            conn.execute("UPDATE runs SET status='FAILED',error_code=?,ended_at=? WHERE discussion_id=? AND id=?",(code,timestamp(),str(did),str(rid)))
            op=conn.execute("SELECT id FROM operations WHERE discussion_id=? AND kind='start' AND json_extract(response_json,'$.run_id')=? ORDER BY rowid LIMIT 1",(str(did),str(rid))).fetchone()
            self._event(conn,did,'operation.failed',{'operation_id':op['id'],'stage':'discussion','code':code,'message':'讨论推进失败，已提交发言保留。','retryable':False},rid)
            self._transition(conn,did,'FAILED','discussion',code)
            return True
