"""Explicit paid final-batch probes; original evidence is never overwritten."""
import argparse
import asyncio
import json
from pathlib import Path

from backend.app.contracts import InsightBatch, Snapshot
from scripts.review_quality_cases import cases, review


def scenarios():
    yield from cases()
    saved=json.loads(Path('data/quality/stage6a-revision/complete-browser.json').read_text(encoding='utf-8'))
    snap=Snapshot.model_validate(saved['snapshot']); d=snap.discussion
    prior=InsightBatch.model_validate(saved['versions'][2]['insights'])
    base=dict(discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,
        roster_revision=d.roster_revision,participants=snap.participants)
    for boundary in (6,8,11):
        yield f'library-{boundary}',dict(base,messages=snap.messages[:boundary],insights=prior if boundary>6 else InsightBatch()), \
            '原场实际第4/6条共同采用两指标判断时段；单方协助/轮值条件须剔除，后续未撤回不应遗漏。'
    for name,line in (
        ('withdrawal','我撤回第4条通过老年读者使用率和人工求助次数判断是否调整时段的建议，不再支持这项共同主张。'),
        ('changed-condition','我改变第4条的建议：今后只依据老年读者使用率来考虑调整时段，不再认可把人工求助次数纳入这个决定。')):
        # Synthetic latest public message, deliberately not a mutation of the original DB.
        latest=snap.messages[-1].model_copy(update={'participant_id':snap.messages[3].participant_id,'content':line})
        yield name,dict(base,messages=(*snap.messages[:-1],latest),insights=prior), \
            '构造最新公开发言：第4条作者撤回/改条件，不能机械保留两指标共同决定；可呈现真实相反主张或更小交集。'


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--cases',nargs='*')
    args=parser.parse_args()
    asyncio.run(review(args.output,args.cases,scenario_cases=scenarios()))
