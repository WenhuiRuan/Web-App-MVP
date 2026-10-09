"""Pure arbitration of public intent: no database, network or fixed speaker order."""
from collections import Counter

from .lifecycle import LifecycleError


def validate_intents(snapshot, candidates):
    experts={p.id for p in snapshot.participants if p.kind=='EXPERT'}
    messages={m.id:m for m in snapshot.messages}
    for actor,result in candidates.items():
        target=messages.get(result.target_message_id)
        if actor not in experts or (result.target_message_id and (target is None or target.participant_id==actor)):
            raise LifecycleError('INVALID_INTENT','参与者或回应目标不属于有效公开上下文。')
        if (result.kind in ('SUPPLEMENT','REBUT') and target is None) or (result.kind=='PASS' and result.target_message_id):
            raise LifecycleError('INVALID_INTENT','参与类型与回应目标不一致。')


def choose_speaker(snapshot, candidates):
    validate_intents(snapshot,candidates)
    last_actor=snapshot.messages[-1].participant_id if snapshot.messages else None
    recent=Counter(m.participant_id for m in snapshot.messages[-3:])
    bonuses={'REQUEST':0,'INTERRUPT':8,'SUPPLEMENT':12,'REBUT':20}
    eligible={actor:result for actor,result in candidates.items() if result.kind!='PASS' and actor!=last_actor}
    if not eligible:
        return None
    positions={m.id:m.turn_no for m in snapshot.messages}
    def rank(actor):
        result=eligible[actor]
        freshness=max(0,5-(len(snapshot.messages)-positions[result.target_message_id])) if result.target_message_id else 0
        return (-(result.relevance+bonuses[result.kind]+freshness-25*recent[actor]),str(actor))
    return min(eligible,key=rank)


def stop_reason(count,max_turns,elapsed,max_seconds):
    if count>=max_turns: return 'turn_limit'
    if elapsed>=max_seconds: return 'time_limit'
    return None
