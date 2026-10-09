"""4C-2 frozen summary boundary, independent deadline and atomic completion."""
from uuid import UUID,uuid4

import pytest

from backend.app.lifecycle import RepositoryUnavailable
from backend.app.model_gateway import InvalidModelResult
from backend.tests.test_insight_pipeline import (SynthesisGateway, synthesis_client, prepared, evidence, wait_projection)
from backend.tests.test_roster_tasks import setup, events
from backend.tests.test_discussion_engine import start_ready


def summarizing(setup):
    client,repo,did,rid=prepared(setup)
    insight=repo.claim_insights(did,rid)
    assert repo.complete_insights(insight,evidence(insight.request))
    assert repo.finish_run(did,rid,'host_end')
    return client,repo,did,rid


def test_summary_uses_host_frozen_messages_and_commits_complete_with_event(setup):
    client,repo,did,rid=summarizing(setup)
    claim=repo.claim_summary(did,rid)
    req=claim.request
    assert req.through_turn==3 and [m.turn_no for m in req.messages]==[1,2,3]
    assert req.actor_id==next(p.id for p in req.participants if p.kind=='HOST')
    assert req.insights.version==1 and req.insights.through_turn==3
    assert repo.claim_summary(did,rid) is None
    assert repo.complete_summary(claim,{'task':'summary','content':'主要观点是先试点。共识是验证后推广，成本仍需讨论。'})
    assert repo.complete_summary(claim,{'task':'summary','content':'迟到覆盖'}) is False
    snapshot=repo.snapshot(did)
    assert snapshot.discussion.state=='COMPLETED' and snapshot.summary.through_turn==3
    assert len(snapshot.messages)==3
    stream=events(client,str(did))
    assert stream[-2]['type']=='summary.ready' and stream[-1]['payload']['state']=='COMPLETED'
    assert sum(e['type']=='summary.ready' for e in stream)==1
    with repo.database.connect() as conn:
        run=conn.execute('SELECT status,summary_through_turn,ended_at FROM runs WHERE id=?',(str(rid),)).fetchone()
        assert tuple(run)[:2]==('COMPLETED',3) and run['ended_at']


@pytest.mark.parametrize('content',['', '  ', '{"content":"原始JSON"}', '["原始JSON"]', '```json\n{}\n```', '长'*4001],ids=['empty','blank','object','array','code','long'])
def test_summary_rejects_non_natural_body_without_completion(setup,content):
    client,repo,did,rid=summarizing(setup); claim=repo.claim_summary(did,rid)
    with pytest.raises(InvalidModelResult): repo.complete_summary(claim,{'task':'summary','content':content})
    assert repo.snapshot(did).discussion.state=='SUMMARIZING' and repo.snapshot(did).summary is None


@pytest.mark.parametrize('location',['summary','summary_event','completed_event'])
def test_summary_transaction_failure_does_not_leave_completed_or_partial_summary(setup,location):
    client,repo,did,rid=summarizing(setup); claim=repo.claim_summary(did,rid); before=repo.snapshot(did)
    with repo.database.connect() as conn:
        table='summaries' if location=='summary' else 'events'
        condition='' if location=='summary' else "WHEN NEW.type='summary.ready'" if location=='summary_event' else "WHEN NEW.type='discussion.state_changed' AND json_extract(NEW.payload,'$.state')='COMPLETED'"
        conn.execute(f"CREATE TRIGGER break_summary BEFORE INSERT ON {table} {condition} BEGIN SELECT RAISE(ABORT,'test summary write failure'); END")
    with pytest.raises(RepositoryUnavailable): repo.complete_summary(claim,{'task':'summary','content':'观点保留，尚有未解决问题。'})
    assert repo.snapshot(did)==before
    with repo.database.connect() as conn:
        assert conn.execute('SELECT count(*) FROM summaries').fetchone()[0]==0
        assert conn.execute('SELECT status FROM runs WHERE id=?',(str(rid),)).fetchone()[0]=='ACTIVE'


def test_summary_cannot_be_claimed_while_running_or_after_interruption(setup):
    client,repo,did,rid=prepared(setup)
    assert repo.claim_summary(did,rid) is None
    repo.finish_run(did,rid,'host_end'); claim=repo.claim_summary(did,rid)
    repo.recover_unfinished()
    assert repo.complete_summary(claim,{'task':'summary','content':'迟到总结。'}) is False
    assert repo.snapshot(did).summary is None


class FinalGateway(SynthesisGateway):
    def __init__(self, reason='turn_limit', summary_mode='valid'):
        super().__init__()
        self.reason=reason; self.summary_mode=summary_mode; self.summary_release.set()
        if reason=='time_limit': self.mode='time'

    async def generate(self,request):
        if request.task=='host_control' and self.reason=='host_end' and len(request.messages)>=7:
            return {'task':'host_control','action':'end','public_focus':'收束与总结'}
        if request.task=='summary':
            self.summary_calls.append(request)
            import asyncio
            await asyncio.sleep(.02)
            if self.summary_mode=='timeout': await asyncio.sleep(3)
            if self.summary_mode=='invalid': return {'task':'summary','content':'{"raw":"JSON"}'}
            if self.summary_mode=='exception': raise RuntimeError('private-provider-sentinel')
            with self.repository.database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE'); conn.execute('ROLLBACK')
            return {'task':'summary','content':'主要观点是先验证适用条件。共识以具体来源为准；成本边界仍有分歧，下一步开展试点。'}
        return await super().generate(request)


@pytest.mark.parametrize('reason',['host_end','turn_limit','time_limit'])
def test_automatic_summary_after_each_end_condition_uses_independent_budget(synthesis_client,reason):
    client,gateway=synthesis_client(FinalGateway(reason),discussion_max_turns=20 if reason=='host_end' else 7)
    did,accepted=start_ready(client)
    snapshot=wait_projection(client,did,lambda s:s['discussion']['state']=='COMPLETED')
    req=gateway.summary_calls[0]
    assert req.through_turn==len(snapshot['messages'])==snapshot['summary']['through_turn']
    assert len(gateway.summary_calls)==1
    assert all(m.turn_no<=req.through_turn for m in req.messages)
    with client.app.state.database.connect() as conn:
        assert conn.execute('SELECT stop_reason FROM runs WHERE id=?',(accepted['run_id'],)).fetchone()[0]==reason
    assert client.get('/api/discussions').json()['items']==[]


@pytest.mark.parametrize('mode,code',[('timeout','MODEL_TIMEOUT'),('invalid','MODEL_RESULT_INVALID'),('exception','TASK_FAILED')])
def test_summary_error_is_bounded_and_retains_transcript_insights(synthesis_client,mode,code):
    client,gateway=synthesis_client(FinalGateway(summary_mode=mode),summary_max_seconds=3)
    did,_=start_ready(client)
    snapshot=wait_projection(client,did,lambda s:s['discussion']['state']=='FAILED')
    assert snapshot['discussion']['failure_stage']=='summary' and snapshot['discussion']['failure_code']==code
    assert snapshot['summary'] is None and len(snapshot['messages'])==7
    assert snapshot['insights']['through_turn']==7
    assert len(gateway.summary_calls)==2
    assert not any(e['type']=='summary.ready' for e in events(client,did))
