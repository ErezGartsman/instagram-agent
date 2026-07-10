import { describe, expect, it } from 'vitest'
import { layoutFlow, runPath, activeEdges } from './flowLayout'
import type { FlowGraph } from './flows'

const LINEAR: FlowGraph = {
  nodes: [
    { id: 't1', type: 'trigger' },
    { id: 'n1', type: 'action:notify_operator', body: 'hi' },
  ],
  edges: [{ from: 't1', to: 'n1' }],
}

const BRANCHING: FlowGraph = {
  nodes: [
    { id: 't1', type: 'trigger' },
    { id: 'c1', type: 'condition' },
    { id: 'a', type: 'action:add_note' },
    { id: 'b', type: 'action:add_note' },
  ],
  edges: [
    { from: 't1', to: 'c1' },
    { from: 'c1', to: 'a', when: 'true' },
    { from: 'c1', to: 'b', when: 'false' },
  ],
}

describe('layoutFlow', () => {
  it('returns a bare canvas for an empty graph', () => {
    const l = layoutFlow({ nodes: [], edges: [] })
    expect(l.edges).toEqual([])
    expect(Object.keys(l.nodes)).toHaveLength(0)
  })

  it('places a linear chain left-to-right by depth', () => {
    const l = layoutFlow(LINEAR)
    expect(l.nodes.n1.x).toBeGreaterThan(l.nodes.t1.x)
    // Same column depth = same-ish row; a 2-node chain sits on one row.
    expect(l.nodes.t1.y).toBeCloseTo(l.nodes.n1.y, 0)
  })

  it('produces one bezier path per edge, anchored right→left', () => {
    const l = layoutFlow(LINEAR)
    expect(l.edges).toHaveLength(1)
    const e = l.edges[0]
    expect(e.path.startsWith('M ')).toBe(true)
    expect(e.path).toContain('C') // cubic bezier
  })

  it('stacks the two branches of a condition in the same deeper column', () => {
    const l = layoutFlow(BRANCHING)
    // a and b are both one step past the condition → same x, different y.
    expect(l.nodes.a.x).toBe(l.nodes.b.x)
    expect(l.nodes.a.y).not.toBe(l.nodes.b.y)
    // and deeper than the condition, which is deeper than the trigger.
    expect(l.nodes.c1.x).toBeGreaterThan(l.nodes.t1.x)
    expect(l.nodes.a.x).toBeGreaterThan(l.nodes.c1.x)
  })

  it('carries the branch label (when) onto the edge', () => {
    const l = layoutFlow(BRANCHING)
    const trueEdge = l.edges.find((e) => e.from === 'c1' && e.to === 'a')
    expect(trueEdge?.when).toBe('true')
  })

  it('ignores edges to unknown nodes instead of crashing', () => {
    const l = layoutFlow({
      nodes: [{ id: 't1', type: 'trigger' }],
      edges: [{ from: 't1', to: 'ghost' }],
    })
    expect(l.edges).toHaveLength(0)
    expect(l.nodes.t1).toBeDefined()
  })

  it('terminates on a cyclic graph (depth pass is bounded)', () => {
    const cyclic: FlowGraph = {
      nodes: [{ id: 'a', type: 'trigger' }, { id: 'b', type: 'action:add_note' }],
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'a' }],
    }
    // Just needs to return, not hang.
    const l = layoutFlow(cyclic)
    expect(Object.keys(l.nodes)).toHaveLength(2)
  })
})

describe('runPath / activeEdges', () => {
  it('maps node id → its (last) step status', () => {
    const visited = runPath([
      { node_id: 't1', status: 'success' },
      { node_id: 'n1', status: 'shadow' },
    ])
    expect(visited.get('t1')).toBe('success')
    expect(visited.get('n1')).toBe('shadow')
  })

  it('a re-run node keeps its latest status', () => {
    const visited = runPath([
      { node_id: 'n1', status: 'waiting' },
      { node_id: 'n1', status: 'success' },
    ])
    expect(visited.get('n1')).toBe('success')
  })

  it('lights only edges whose both endpoints were visited', () => {
    const l = layoutFlow(BRANCHING)
    const visited = runPath([
      { node_id: 't1', status: 'success' },
      { node_id: 'c1', status: 'success' },
      { node_id: 'a', status: 'success' },
    ])
    const active = activeEdges(l.edges, visited)
    expect(active.has('t1->c1')).toBe(true)
    expect(active.has('c1->a')).toBe(true)
    expect(active.has('c1->b')).toBe(false) // the untaken branch stays dark
  })
})
