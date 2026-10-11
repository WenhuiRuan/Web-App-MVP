"""Opt-in paid probes of preserved public records; never update the original database."""
import argparse
import asyncio
import json
from pathlib import Path
from backend.app.contracts import Snapshot
from scripts.review_quality_cases import review


def scenarios(snapshot_path=None):
    if snapshot_path:
        saved=json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
        snap=Snapshot.model_validate(saved.get('snapshot',saved))
        d=snap.discussion
        yield 'retained-run',dict(discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,
            roster_revision=d.roster_revision,participants=snap.participants,messages=snap.messages,insights=snap.insights), \
            '只重核保留的完整消息：合并同一原子主张，不以斜线串联不同对象；总结采用同一主张最新条件，保留真实未决保障，不覆盖原场。'
        return
    snap=Snapshot.model_validate(json.loads(Path('data/quality/stage6c-interaction/original/snapshot.json').read_text(encoding='utf-8')))
    d=snap.discussion
    base=dict(discussion_id=d.id,run_id=d.run_id,topic=d.topic,expert_count=d.expert_count,
        roster_revision=d.roster_revision,participants=snap.participants,messages=snap.messages)
    yield 'original-eight',dict(base,insights=snap.insights),'原场登记公示/优先领养重复须合并；第6/7条保障条件及第7/8条阈值仍未决，不能由部分共识推出全部解决。'
    yield 'natural-response',dict(base,task='utterance',messages=snap.messages[:5],cycle=6,
        actor_id=snap.messages[1].participant_id,participation_kind='REBUT',target_message_id=snap.messages[2].id,
        public_focus='澄清对方是否误读了政府购买服务与转介保障的关系'),'沿用真实公开上下文，回应作者和观点，不只换句首，不认证未知保障。'
    yield 'host-question',dict(base,task='utterance',messages=snap.messages[:7],cycle=8,
        actor_id=next(p.id for p in snap.participants if p.kind=='HOST'),host_task='followup',
        addressed_actor_id=snap.messages[6].participant_id,host_reference_message_id=snap.messages[6].id,
        public_focus='请提出比例建议的专家说明依据，并区分转介保障与可以包含转介的说法'),'主持就真实未决条件具体追问，不认证数字或制造假分歧。'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--cases',nargs='*')
    parser.add_argument('--snapshot',help='Read-only retained snapshot; run only affected extraction and summary')
    parser.add_argument('--summaries-from',help='Reuse retained reviewed insights; only call summary')
    args=parser.parse_args()
    asyncio.run(review(args.output,args.cases,summaries_from=args.summaries_from,scenario_cases=scenarios(args.snapshot)))
