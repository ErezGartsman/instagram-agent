import { describe, expect, it } from 'vitest'
import {
  graphToSteps, stepsToGraph, newStep, blankSteps,
  parsePredicate, buildPredicate,
  triggerPhrase, stepPhrase, playbookSentence,
  type PlaybookStep,
} from './playbook'
import type { FlowGraph } from './flows'

const LINEAR_GRAPH: FlowGraph = {
  nodes: [
    { id: 'trigger', type: 'trigger' },
    { id: 'w1', type: 'wait', hours: 24 },
    { id: 's1', type: 'action:send_message', body: 'hey' },
  ],
  edges: [
    { from: 'trigger', to: 'w1' },
    { from: 'w1', to: 's1' },
  ],
}

describe('graphToSteps', () => {
  it('flattens a linear chain in order', () => {
    expect(graphToSteps(LINEAR_GRAPH)).toEqual([
      { kind: 'wait', hours: 24 },
      { kind: 'send', body: 'hey' },
    ])
  })

  it('follows a condition true-branch (linear "only if")', () => {
    const graph: FlowGraph = {
      nodes: [
        { id: 'trigger', type: 'trigger' },
        { id: 'c1', type: 'condition', predicate: { field: 'stage', op: 'eq', value: 'qualified' } },
        { id: 'n1', type: 'action:notify_operator', body: 'go' },
      ],
      edges: [
        { from: 'trigger', to: 'c1' },
        { from: 'c1', to: 'n1', when: 'true' },
      ],
    }
    expect(graphToSteps(graph)).toEqual([
      { kind: 'if', predicate: { field: 'stage', op: 'eq', value: 'qualified' } },
      { kind: 'notify', body: 'go' },
    ])
  })

  it('rejects a real fork (condition with a false branch)', () => {
    const graph: FlowGraph = {
      nodes: [
        { id: 'trigger', type: 'trigger' },
        { id: 'c1', type: 'condition', predicate: {} },
        { id: 'a', type: 'action:add_note', note: 'x' },
        { id: 'b', type: 'action:add_note', note: 'y' },
      ],
      edges: [
        { from: 'trigger', to: 'c1' },
        { from: 'c1', to: 'a', when: 'true' },
        { from: 'c1', to: 'b', when: 'false' },
      ],
    }
    expect(graphToSteps(graph)).toBeNull()
  })

  it('rejects orphan nodes outside the chain', () => {
    const graph: FlowGraph = {
      ...LINEAR_GRAPH,
      nodes: [...LINEAR_GRAPH.nodes, { id: 'orphan', type: 'wait', hours: 1 }],
    }
    expect(graphToSteps(graph)).toBeNull()
  })

  it('rejects a cycle without looping forever', () => {
    const graph: FlowGraph = {
      nodes: [
        { id: 'trigger', type: 'trigger' },
        { id: 'a', type: 'wait', hours: 1 },
        { id: 'b', type: 'wait', hours: 2 },
      ],
      edges: [
        { from: 'trigger', to: 'a' },
        { from: 'a', to: 'b' },
        { from: 'b', to: 'a' },
      ],
    }
    expect(graphToSteps(graph)).toBeNull()
  })

  it('handles the seeded single-notify flows (trigger → notify)', () => {
    const graph: FlowGraph = {
      nodes: [
        { id: 't1', type: 'trigger' },
        { id: 'n1', type: 'action:notify_operator', body: 'check the queue' },
      ],
      edges: [{ from: 't1', to: 'n1' }],
    }
    expect(graphToSteps(graph)).toEqual([{ kind: 'notify', body: 'check the queue' }])
  })
})

describe('stepsToGraph', () => {
  it('round-trips every step kind through the graph shape', () => {
    const steps: PlaybookStep[] = [
      { kind: 'if', predicate: { field: 'stage', op: 'in', value: ['briefed'] } },
      { kind: 'wait', hours: 48 },
      { kind: 'send', body: 'shalom' },
      { kind: 'notify', body: 'ping' },
      { kind: 'advance', to_stage: 'booked' },
      { kind: 'note', note: 'n' },
      { kind: 'flag', flag: 'vip' },
    ]
    expect(graphToSteps(stepsToGraph(steps))).toEqual(steps)
  })

  it("a condition's outgoing edge is its true-branch", () => {
    const graph = stepsToGraph([newStep('if'), newStep('notify')])
    const out = graph.edges.find((e) => e.from === 's1')
    expect(out?.when).toBe('true')
  })

  it('an empty recipe is just the trigger', () => {
    expect(stepsToGraph([])).toEqual({
      nodes: [{ id: 'trigger', type: 'trigger' }],
      edges: [],
    })
  })

  it('blankSteps compiles to a valid notify chain', () => {
    const graph = stepsToGraph(blankSteps())
    expect(graph.nodes).toHaveLength(2)
    expect(graph.edges).toEqual([{ from: 'trigger', to: 's1' }])
  })
})

describe('predicate model', () => {
  it('parses the canonical cooling predicate', () => {
    const model = parsePredicate({
      all: [
        { field: 'stage', op: 'in', value: ['qualified', 'captured'] },
        { field: 'hours_since_last', op: 'gte', value: 36 },
      ],
    })
    expect(model).toEqual({ stages: ['qualified', 'captured'], hours: 36 })
  })

  it('returns null for a predicate it cannot safely edit', () => {
    expect(parsePredicate({ field: 'channel', op: 'eq', value: 'whatsapp' })).toBeNull()
  })

  it('round-trips with buildPredicate', () => {
    const model = { stages: ['qualified', 'briefed'], hours: 48 }
    expect(parsePredicate(buildPredicate(model))).toEqual(model)
  })
})

describe('sentences', () => {
  it('phrases an event trigger', () => {
    expect(triggerPhrase({ type: 'event', kind: 'booking_canceled' }))
      .toBe('a booking is canceled')
  })

  it('phrases the cooling state trigger', () => {
    const phrase = triggerPhrase({
      type: 'state',
      predicate: {
        all: [
          { field: 'stage', op: 'in', value: ['qualified', 'captured', 'briefed'] },
          { field: 'hours_since_last', op: 'gte', value: 36 },
        ],
      },
    })
    expect(phrase).toBe('a lead in qualified, captured or briefed has been quiet for 36+ hours')
  })

  it('falls back gracefully on an advanced predicate', () => {
    expect(triggerPhrase({ type: 'state', predicate: { field: 'x', op: 'y', value: 1 } }))
      .toBe('a custom condition holds')
  })

  it('phrases each step kind', () => {
    expect(stepPhrase({ kind: 'wait', hours: 24 })).toBe('wait 24 hours')
    expect(stepPhrase({ kind: 'send', body: 'x' })).toBe('message the lead')
    expect(stepPhrase({ kind: 'notify', body: 'x' })).toBe('notify Erez')
    expect(stepPhrase({ kind: 'advance', to_stage: 'booked' })).toBe('move them to booked')
    expect(stepPhrase({ kind: 'flag', flag: 'hot_lead' })).toBe('flag as hot lead')
  })

  it('builds the full card sentence, including the advanced fallback', () => {
    expect(playbookSentence({ type: 'event', kind: 'booking_canceled' }, [{ kind: 'notify', body: 'x' }]))
      .toEqual({ when: 'a booking is canceled', then: ['notify Erez'] })
    expect(playbookSentence({ type: 'event', kind: 'booking_canceled' }, null))
      .toEqual({ when: 'a booking is canceled', then: ['run custom branching logic'] })
  })
})
