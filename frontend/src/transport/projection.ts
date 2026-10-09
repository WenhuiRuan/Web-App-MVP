import { ClientError, type PanelEvent, type Snapshot } from './types'

// This is a public UI projection, not a domain scheduler. Unknown/gapped streams resnapshot.
export function projectEvent(previous: Snapshot, event: PanelEvent): Snapshot {
  if (event.discussion_id !== previous.discussion.id) return previous
  if (event.seq <= previous.last_event_seq) return previous
  if (event.schema_version !== 1 || event.seq !== previous.last_event_seq + 1) throw new ClientError('SNAPSHOT_REQUIRED', '事件序列已变化，请重新连接。', true)
  if (event.type !== 'discussion.state_changed' && event.type !== 'roster.ready' && event.run_id !== previous.discussion.run_id) throw new ClientError('CURSOR_INVALID', '收到过期运行的事件，请重新连接。', true)
  const next = structuredClone(previous)
  next.last_event_seq = event.seq
  next.discussion.updated_at = event.occurred_at
  switch (event.type) {
    case 'discussion.state_changed':
      if (event.payload.version >= next.discussion.version) {
        next.discussion = { ...next.discussion, ...event.payload, run_id: event.run_id }
        if (event.payload.state === 'RUNNING' && !next.role_states.length) next.role_states = next.participants.map(p => ({ participant_id: p.id, state: 'IDLE', public_focus: '', version: 0 }))
        if (['COMPLETED', 'FAILED', 'INTERRUPTED'].includes(event.payload.state)) next.role_states = next.role_states.map(s => ({ ...s, state: 'IDLE' }))
      }
      break
    case 'roster.ready':
      if (event.run_id !== null || event.payload.participants.some(p => p.discussion_id !== event.discussion_id)) throw new ClientError('SNAPSHOT_REQUIRED', '阵容归属不匹配。')
      next.discussion.roster_revision = event.payload.roster_revision
      next.participants = event.payload.participants
      break
    case 'participant.status_changed': {
      if (!next.participants.some(p => p.id === event.payload.participant_id)) throw new ClientError('SNAPSHOT_REQUIRED', '角色不在当前阵容。')
      const prior = next.role_states.find(s => s.participant_id === event.payload.participant_id)
      if (!prior || event.payload.version > prior.version) next.role_states = [...next.role_states.filter(s => s.participant_id !== event.payload.participant_id), event.payload]
      break
    }
    case 'turn.committed':
      if (event.payload.discussion_id !== next.discussion.id || event.payload.run_id !== next.discussion.run_id || !next.participants.some(p => p.id === event.payload.participant_id)) throw new ClientError('SNAPSHOT_REQUIRED', '发言归属不匹配。')
      if (!next.messages.some(m => m.id === event.payload.id)) {
        if (event.payload.turn_no !== next.messages.length + 1) throw new ClientError('SNAPSHOT_REQUIRED', '发言顺序不连续。')
        next.messages.push(event.payload)
      }
      break
    case 'insights.updated': {
      const ids = new Set(next.messages.filter(m => m.turn_no <= event.payload.through_turn).map(m => m.id))
      if (event.payload.through_turn > next.messages.length || event.payload.items.some(i => i.source_message_ids.some(id => !ids.has(id)))) throw new ClientError('SNAPSHOT_REQUIRED', '观点缺少当前讨论的发言依据。')
      if (event.payload.version > next.insights.version) next.insights = event.payload
      break
    }
    case 'summary.ready':
      if (event.payload.through_turn !== next.messages.length) throw new ClientError('SNAPSHOT_REQUIRED', '总结边界与发言不一致。')
      next.summary = event.payload
      break
    case 'operation.failed': break
  }
  return next
}
