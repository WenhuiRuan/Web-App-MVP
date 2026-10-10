"""Opt-in paid semantic review. Retain inputs/final answers; never rewrite original runs."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import httpx

from backend.app.config import load_settings
from backend.app.contracts import InsightBatch, ModelRequest, ModelResultAdapter, Snapshot
from backend.app.deepseek_gateway import DeepSeekGateway, missing_configuration, public_context
from backend.app.engine import DiscussionEngine, ModelCallFailure, RunDeadline


def cases(live_snapshot=None):
    for index in (1, 2):
        saved = json.loads(Path(f'data/quality/stage6a/topic-{index}.json').read_text(encoding='utf-8'))
        snapshot = Snapshot.model_validate(saved['original_browser_run']['snapshot'])
        d = snapshot.discussion
        yield f'original-{index}', dict(discussion_id=d.id, run_id=d.run_id, topic=d.topic,
            expert_count=d.expert_count, roster_revision=d.roster_revision, participants=snapshot.participants,
            messages=snapshot.messages), '复核原失败：支持者、对象、提案属性与总结一致性；不能覆盖旧结果。'
    examples = [
        ('explicit-support', '社区共享工具柜是否试点预约借用？', [
            '请比较是否应该开展预约借用试点。',
            '我建议仅对登记成员开展预约借用试点，前提是不增加志愿者值班时间。',
            '我支持对登记成员试点预约借用，但必须不增加志愿者值班时间。'],
            '甲乙明确支持同一范围和前提下的提案，可提共识，不能写成正式决策。'),
        ('different-objects', '资料服务如何记录使用情况？', [
            '请说明不同资料的使用记录口径。',
            '对于公开资料的访问次数，我建议按整个机构汇总，且不记录个人身份。',
            '对于受限资料的授权申请次数，我建议按项目汇总，并保留授权责任人。'],
            '对象为访问次数与授权申请次数，不同范围和记录条件可并存；共识和分歧都应为空。'),
        ('single-proposal', '配送站是否改变领取流程？', [
            '请给出方案并说明证据。',
            '我提出一个待试验的规则：若排队超过八分钟就临时开放第二个窗口，这个阈值没有验证。',
            '我还没有判断这个方案，需要先看到实际排队记录。'],
            '单方八分钟阈值提案，另一人未表态，不能形成共识或分歧。'),
        ('unanswered-host', '居民活动室如何安排开放时段？', [
            '是否周末开放、需要几位志愿者，大家更支持哪一个选项？',
            '我需要先了解现有人手，暂时不提出方案。',
            '在知道使用需求前，我也暂不判断是否周末开放。'],
            '主持问题与专家尚未形成意见，不能直接提观点，允许双空。'),
    ]
    for name, topic, lines, criterion in examples:
        did = uuid5(NAMESPACE_URL, 'panel-quality:' + name)
        run = uuid5(did, 'run')
        people = [dict(id=uuid5(did, f'person:{i}'), discussion_id=did, roster_revision=1,
            kind='HOST' if i == 0 else 'EXPERT', name=['主持人', '甲', '乙'][i],
            title=['讨论主持', '服务运营研究员', '流程设计研究员'][i],
            stance='人设预设支持全面实施，但这不是已发表意见', color=['#64748B', '#2563EB', '#D97706'][i]) for i in range(3)]
        messages = [dict(id=uuid5(run, str(i)), discussion_id=did, run_id=run, participant_id=people[i]['id'],
            turn_no=i+1, kind='opening' if i == 0 else 'statement', content=line,
            created_at='2026-10-10T00:00:00Z') for i, line in enumerate(lines)]
        yield name, dict(discussion_id=did, run_id=run, topic=topic, expert_count=2,
            participants=people, messages=messages), criterion
    if live_snapshot:
        snapshot=Snapshot.model_validate(json.loads(Path(live_snapshot).read_text(encoding='utf-8'))['snapshot'])
        d=snapshot.discussion
        base=dict(discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,
            roster_revision=d.roster_revision,participants=snapshot.participants,messages=snapshot.messages)
        for boundary in (8,10,len(snapshot.messages)):
            yield f'live-{boundary}',dict(base,messages=snapshot.messages[:boundary]), '本场相关边界：未认可不是分歧，复核原消息并保留诊断结果。'
        yield 'live-host',dict(base,messages=snapshot.messages[:9]), '主持串联任务含错误作者提示，必须依据实际第9条纠正。'


async def review(output_path, selected, live_snapshot=None, summaries_from=None):
    settings = load_settings()
    missing = missing_configuration(settings)
    if settings.model_provider != 'deepseek' or missing:
        raise SystemExit('Missing variables: ' + ', '.join(missing or ['MODEL_PROVIDER']))
    output = Path(output_path)
    output.mkdir(parents=True, exist_ok=True)
    journal = output / 'calls.jsonl'
    if journal.exists(): raise SystemExit('Evidence already exists; use a new output directory.')
    active = {}
    def metric_sink(metric):
        with journal.open('a', encoding='utf-8') as file:
            file.write(json.dumps(dict(metric, case=active.get('case')), ensure_ascii=False) + '\n')
    async def final_answer(response):
        await response.aread()
        if response.status_code == 200:
            body=json.loads(response.request.content)
            active.setdefault('provider_inputs',[]).append({key:body[key] for key in
                ('model','thinking','response_format','stream','max_tokens','messages')})
            # Deliberately select only the public final answer, never reasoning or headers.
            value = response.json()['choices'][0]['message'].get('content')
            active.setdefault('provider_final_answers', []).append(value)
    async with httpx.AsyncClient(timeout=settings.model_timeout_seconds, follow_redirects=False,
        event_hooks={'response': [final_answer]}) as client:
        gateway = DeepSeekGateway(settings, client=client, metrics_sink=metric_sink)
        for name, base, criterion in cases(live_snapshot):
            if selected and name not in selected: continue
            record = dict(case=name, criterion=criterion, calls=[])
            def save():
                (output / f'{name}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            async def call(req):
                active.clear(); active.update(case=name, provider_final_answers=[],provider_inputs=[])
                entry = dict(request=req.model_dump(mode='json'), public_context=public_context(req),
                    provider_final_answers=active['provider_final_answers'],provider_inputs=active['provider_inputs'])
                record['calls'].append(entry); save()
                supervisor = SimpleNamespace(repository=None, _db_call=None, settings=settings,
                    gateway_getter=lambda: gateway, semaphore=asyncio.Semaphore(settings.model_max_concurrency), closing=False)
                engine = DiscussionEngine(supervisor)
                engine.deadline = time.monotonic() + (settings.insight_max_seconds if req.task == 'insights' else settings.summary_max_seconds if req.task=='summary' else settings.model_timeout_seconds)
                try:
                    result = await engine.call_model(req)
                    entry['result'] = result.model_dump(mode='json')
                    return result
                except (ModelCallFailure, RunDeadline, TimeoutError) as exc:
                    entry['failure'] = type(exc).__name__ + ': ' + str(exc)
                    raise
                finally: save()
            try:
                if name=='live-host':
                    full=json.loads(Path(live_snapshot).read_text(encoding='utf-8'))['snapshot']
                    await call(ModelRequest(**base,task='utterance',actor_id=next(p.id for p in base['participants'] if p.kind=='HOST'),cycle=10,
                        host_task='linking',public_focus=full['messages'][9]['content'][:140]))
                    continue
                if summaries_from:
                    prior=json.loads((Path(summaries_from)/f'{name}.json').read_text(encoding='utf-8'))
                    points=ModelResultAdapter.validate_python(next(c['result'] for c in prior['calls'] if c['request']['task']=='insights'))
                else:
                    points = await call(ModelRequest(**base, task='insights', through_turn=len(base['messages']), insight_version=7))
                if name in ('live-8','live-10'): continue
                people = ModelRequest(**base, task='insights', through_turn=len(base['messages']), insight_version=7).participants
                await call(ModelRequest(**base, task='summary', actor_id=people[0].id,
                    through_turn=len(base['messages']), insights=InsightBatch(version=7, through_turn=len(base['messages']), items=points.items)))
            except (ModelCallFailure, RunDeadline, TimeoutError): pass
            print(json.dumps({'case': name, 'tasks': len(record['calls']),
                'failures': sum('failure' in c for c in record['calls'])}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--cases', nargs='*')
    parser.add_argument('--live-snapshot')
    parser.add_argument('--summaries-from',help='Reuse saved insights; only review affected summaries')
    args = parser.parse_args()
    asyncio.run(review(args.output, args.cases, args.live_snapshot, args.summaries_from))
