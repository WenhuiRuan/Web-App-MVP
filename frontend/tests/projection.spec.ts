import { test, expect } from '@playwright/test'
import demo from '../../data/samples/frontend-demo.json' with { type: 'json' }
import { projectEvent } from '../src/transport/projection'
import type { PanelEvent, Snapshot } from '../src/transport/types'
const initial = demo.initial as unknown as Snapshot
const run = demo.groups[0][0].run_id
const started: PanelEvent = { schema_version: 1, discussion_id: initial.discussion.id, run_id: run, seq: 5, occurred_at: initial.discussion.updated_at, type: 'discussion.state_changed', payload: { state: 'RUNNING', version: 3, failure_stage: null } }
const events = demo.groups.flat() as unknown as PanelEvent[]

test('public UI projection applies the complete fixture and rejects duplicate/gapped/foreign events', () => {
  let state = projectEvent(initial, started)
  expect(projectEvent(state, started)).toBe(state)
  expect(projectEvent(state, { ...events[0], discussion_id: 'unrelated' })).toBe(state)
  expect(() => projectEvent(state, { ...events[0], seq: 9 })).toThrow('事件序列')
  for (const event of events) state = projectEvent(state, event)
  expect(state.discussion.state).toBe('COMPLETED')
  expect(state.messages).toHaveLength(16)
  expect(state.insights.items).toHaveLength(4)
  expect(state.summary?.through_turn).toBe(16)
})

test('public UI projection rejects stale run and insight evidence from outside the snapshot', () => {
  const state = projectEvent(initial, started)
  expect(() => projectEvent(state, { ...events[0], run_id: 'old-run' })).toThrow('过期运行')
  const insight = structuredClone(events.find(e => e.type === 'insights.updated')!)
  insight.seq = 6
  expect(() => projectEvent(state, insight)).toThrow('发言依据')
})
