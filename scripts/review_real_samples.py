"""Explicit, paid targeted Prompt review on saved public snapshots; never mutates SQLite."""
import asyncio
import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

from backend.app.config import load_settings
from backend.app.contracts import InsightBatch, ModelRequest, ModelResultAdapter, Snapshot
from backend.app.deepseek_gateway import DeepSeekGateway, missing_configuration
from backend.app.engine import DiscussionEngine, ModelCallFailure, RunDeadline
from backend.app.model_gateway import InvalidModelResult, ModelServiceError


async def review(output_path='work/stage6a-targeted',synthesis_only=False,summaries_from=None):
    settings=load_settings()
    if settings.model_provider!='deepseek' or missing_configuration(settings):
        raise SystemExit('Missing model configuration: '+', '.join(missing_configuration(settings) or ['MODEL_PROVIDER']))
    output=Path(output_path);output.mkdir(parents=True,exist_ok=True)
    journal=output/'calls.jsonl'
    if journal.exists(): raise SystemExit('Existing targeted evidence retained; select another output directory before rerunning.')
    def export(metric):
        with journal.open('a',encoding='utf-8') as file: file.write(json.dumps(metric,ensure_ascii=False)+'\n')
    gateway=DeepSeekGateway(settings,metrics_sink=export)
    try:
        for index in (1,2):
            snapshot=Snapshot.model_validate(json.loads(Path(f'work/stage6a-real/topic-{index}.json').read_text(encoding='utf-8'))['snapshot'])
            d=snapshot.discussion;host=next(p for p in snapshot.participants if p.kind=='HOST')
            base=dict(discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,
                roster_revision=d.roster_revision,participants=snapshot.participants,messages=snapshot.messages)
            results=[]
            async def call(request):
                supervisor=SimpleNamespace(repository=None,_db_call=None,settings=settings,gateway_getter=lambda:gateway,
                    semaphore=asyncio.Semaphore(settings.model_max_concurrency),closing=False)
                engine=DiscussionEngine(supervisor)
                engine.deadline=time.monotonic()+(settings.insight_max_seconds if request.task=='insights' else settings.summary_max_seconds if request.task=='summary' else settings.model_timeout_seconds)
                result=await engine.call_model(request)
                results.append({'request':request.model_dump(mode='json'),'result':result.model_dump(mode='json')})
                (output/f'topic-{index}.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
                return result
            if summaries_from:
                prior=json.loads((Path(summaries_from)/f'topic-{index}.json').read_text(encoding='utf-8'))
                points=ModelResultAdapter.validate_python(next(item['result'] for item in prior if item['request']['task']=='insights'))
            else:
                points=await call(ModelRequest(**base,task='insights',through_turn=len(snapshot.messages),insight_version=snapshot.insights.version+1))
            await call(ModelRequest(**base,task='summary',actor_id=host.id,through_turn=len(snapshot.messages),
                insights=InsightBatch(version=snapshot.insights.version+1,through_turn=len(snapshot.messages),items=points.items)))
            if index==1 and not synthesis_only and not summaries_from:
                utterance=dict(base,messages=snapshot.messages[:1])
                await call(ModelRequest(**utterance,task='utterance',actor_id=snapshot.messages[1].participant_id,cycle=2,
                    participation_kind='SUPPLEMENT',target_message_id=snapshot.messages[0].id,public_focus='说明有条件使用的技术边界，不能引用尚未发言角色'))
                await call(ModelRequest(**base,task='host_control',actor_id=host.id,cycle=13))
        print(json.dumps({'completed_calls':len(gateway.metrics),'output':str(output)},ensure_ascii=False))
    except (ModelServiceError,InvalidModelResult,ModelCallFailure,RunDeadline,TimeoutError) as exc:
        raise SystemExit('Targeted review failed: '+str(exc)) from None
    finally: await gateway.aclose()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='work/stage6a-targeted')
    parser.add_argument('--only-synthesis',action='store_true')
    parser.add_argument('--summaries-from',help='Reuse prior validated insights; only call the two summaries')
    args=parser.parse_args()
    asyncio.run(review(args.output,args.only_synthesis,args.summaries_from))
