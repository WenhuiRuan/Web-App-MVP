"""Author a prerecorded UI demonstration, not a model or backend engine."""
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid5

from backend.app.contracts import EventAdapter, Snapshot

ROOT = Path(__file__).resolve().parents[1]
D = UUID('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
R = UUID('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
STAMP = '2026-10-09T03:00:00Z'


def build_demo():
    profiles = [('文澜', '圆桌主持人', '梳理议题，推动不同观点相互回应', '#64748B'),
                ('顾言', '组织行为研究员', '支持用试点验证效率与协作收益', '#20857A'),
                ('林澈', '企业经营顾问', '关注服务覆盖、交付与执行成本', '#B76D40'),
                ('沈知', '劳动经济学者', '关注岗位公平与隐性的劳动强度', '#8168A1'),
                ('许衡', '产品与工程负责人', '主张按岗位分层、可撤回的试点', '#4679AA'),
                ('周朔', '公共服务设计师', '关注不同人群的服务可及性', '#B75D82'),
                ('陈序', '战略研究员', '关注长期效果与评估边界', '#798C46')]
    people = [dict(id=str(uuid5(D, f'role-{i}')), discussion_id=str(D), roster_revision=1,
                   kind='HOST' if i == 0 else 'EXPERT', name=n, title=t, stance=s, color=c)
              for i, (n, t, s, c) in enumerate(profiles)]
    snapshot = dict(discussion=dict(id=str(D), topic='我们该推行四天工作制吗？', expert_count=4,
                    state='READY', version=2, roster_revision=1, run_id=None, failure_stage=None,
                    created_at=STAMP, updated_at=STAMP), participants=people[:5], role_states=[],
                    messages=[], insights=dict(version=0, through_turn=0, items=[]), summary=None, last_event_seq=4)
    turns = [
        (0, 'opening', '今天讨论四天工作制，我们先把效率、服务覆盖和岗位公平放到同一张桌上。请先说明你支持或担忧的条件。', '明确讨论边界'),
        (1, 'statement', '我支持先做小范围试点，因为缩短工作周可能促使团队减少低效会议。判断标准应是产出和协作质量，而不是在线时长。', '用试点验证产出'),
        (2, 'statement', '我不同意把减少会议直接等同于可减少一个工作日，客户支持和交付窗口并不会同步缩短。若靠加班补齐，成本可能只是被转移。', '反驳效率与工时的直接等同'),
        (3, 'statement', '我补充一个公平问题：可以远程工作的岗位更容易受益，轮班岗位却可能承担补位压力。试点必须同时记录加班和岗位之间的负担变化。', '补充岗位公平与隐性加班'),
        (4, 'statement', '服务覆盖的担忧可以通过错峰排班来检验，但不应假设所有岗位都适用。建议先选择边界清楚的团队，并保留现有客户服务时段。', '提出分层与错峰试点'),
        (0, 'followup', '目前分歧不在是否减少低效工作，而在效率收益能否覆盖服务与公平成本。什么证据能让各位调整判断？', '追问判断改变的证据'),
        (1, 'statement', '若试点中产出保持、协作等待减少，而且加班没有上升，我会支持继续扩大。这个判断也需要与未参加试点的团队比较。', '提出对照与扩大的条件'),
        (2, 'statement', '这些条件还应加上客户响应时间和交付稳定性，否则内部效率可能掩盖外部损失。我可以接受可撤回的试点，但暂不支持统一推广。', '回应并增加外部服务指标'),
        (3, 'statement', '我同意设置对照组，还需要按岗位拆开数据，避免平均值掩盖个别群体的额外负担。员工反馈也要能匿名表达。', '回应并增加岗位分层指标'),
        (4, 'statement', '我们可以把产出、响应时间、加班和岗位反馈一起作为试点评估项。任何一项明显恶化，都应触发复盘或暂停扩展。', '整合可检查的试点指标'),
        (0, 'linking', '各位已经形成了关于试点与多维评估的共同方向，但对适用范围仍有保留。接下来请回应是否应该让所有岗位采用同一制度。', '串联共识并定位剩余分歧'),
        (1, 'statement', '我倾向在验证有效后逐步扩大，而不是长期停留在少数团队。扩大前仍需保留已经明确的评估门槛。', '支持有条件地逐步扩大'),
        (3, 'statement', '我反对把同一形式当作公平的唯一答案，有些岗位可能更需要排班自主权而不是少一天出勤。扩大时应比较不同安排带来的实际收益。', '反驳统一形式等于公平'),
        (2, 'statement', '我赞同按实际服务责任区分方案，这比统一制度更容易控制风险。具体阈值还需要结合每个团队的历史数据确定。', '支持按服务责任区分方案'),
        (4, 'statement', '可以先公布试点边界、评价方法和退出条件，再邀请不同岗位共同设计安排。这样既能继续探索，也不把试点结论夸大为普遍结论。', '将范围和退出条件落到方案'),
        (0, 'linking', '我们保留了推广范围与制度形式两项分歧，也明确了试点不能以加班和服务下降为代价。下面整理本场结论与尚待验证的问题。', '保留分歧并进入总结'),
    ]
    groups, seq, versions = [], 5, {p['id']: 0 for p in people}
    def ev(kind, payload):
        nonlocal seq
        seq += 1
        return dict(schema_version=1, discussion_id=str(D), run_id=str(R), seq=seq,
                    type=kind, occurred_at=STAMP, payload=payload)
    def role(i, state, focus):
        versions[people[i]['id']] += 1
        return ev('participant.status_changed', dict(participant_id=people[i]['id'], state=state,
                  public_focus=focus, version=versions[people[i]['id']]))
    def insight(key, kind, text, sources):
        return dict(id=str(uuid5(D, key)), kind=kind, content=text,
                    source_message_ids=[str(uuid5(D, f'message-{i}')) for i in sources])
    differences = [insight('difference-1', 'disagreement', '效率改善能否抵消服务覆盖与执行成本，仍需证据验证。', [2, 3])]
    consensus = []
    batch_version = 0
    previous = None
    for number, (actor, kind, content, focus) in enumerate(turns, 1):
        preparing = []
        if previous is not None:
            preparing.append(role(previous, 'IDLE', turns[number - 2][3]))
        preparing.append(role(actor, 'PREPARING', focus))
        groups.append(preparing)
        message = dict(id=str(uuid5(D, f'message-{number}')), discussion_id=str(D), run_id=str(R),
                       participant_id=people[actor]['id'], turn_no=number, kind=kind, content=content, created_at=STAMP)
        speaking = [role(actor, 'SPEAKING', focus), ev('turn.committed', message)]
        if number in (3, 5, 10, 14, 15):
            batch_version += 1
            if number >= 5:
                consensus = [insight('consensus-1', 'consensus', '先开展有明确边界的试点，避免直接统一推广。', [2, 5])]
            if number >= 10:
                consensus.append(insight('consensus-2', 'consensus', '评估应同时覆盖产出、客户响应、加班与岗位公平，而非只看平均效率。', [7, 8, 9, 10]))
            if number == 14:
                differences.append(insight('difference-2', 'disagreement', '有效试点之后是否采用统一形式、如何扩大范围，尚未形成一致意见。', [12, 13, 14]))
            speaking.append(ev('insights.updated', dict(version=batch_version, through_turn=number,
                             items=deepcopy(consensus + differences))))
        groups.append(speaking)
        previous = actor
    groups.append([role(previous, 'IDLE', '本场讨论结束'), ev('discussion.state_changed', dict(state='SUMMARIZING', version=4, failure_stage=None))])
    summary = dict(content='本场讨论没有给出四天工作制应当全面推广的结论，而是形成了一个有边界的探索方向：先做可撤回的试点，再根据证据决定是否扩展。\n\n共同认可的评估维度包括产出与协作质量、客户响应与交付稳定性、实际加班，以及不同岗位的负担和反馈。减少低效工作不能以额外加班或服务下降为代价。\n\n仍然存在两项分歧：效率收益能否覆盖执行成本；有效试点之后应采用统一制度，还是为不同岗位提供不同安排。接下来的任务是明确试点范围、基线数据和退出条件，而不是把预设讨论当作已验证的现实结论。', through_turn=len(turns), created_at=STAMP)
    groups.append([ev('summary.ready', summary), ev('discussion.state_changed', dict(state='COMPLETED', version=5, failure_stage=None))])
    for group in groups:
        for event in group:
            EventAdapter.validate_python(event)
    Snapshot.model_validate(snapshot)
    return dict(description='预设前端演示台本，不来自真实模型。', initial=snapshot,
                profiles=people, groups=groups, summary=summary)


if __name__ == '__main__':
    path = ROOT / 'data/samples/frontend-demo.json'
    path.write_text(json.dumps(build_demo(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('Frontend demonstration fixture exported and validated.')
