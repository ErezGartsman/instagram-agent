import { describe, expect, it } from 'vitest'
import { addNode, removeNode, updateNode, connect, disconnect } from './graphEdit'
import type { FlowGraph } from './flows'

const LINEAR: FlowGraph = {
  nodes: [
    { id: 'trigger', type: 'trigger' },
    { id: 'a', type: 'action:notify_operator', body: 'hi' },
  ],
  edges: [{ from: 'trigger', to: 'a' }],
}

describe('addNode', () => {
  it('inserts a node into the chain, rerouting the existing edge through it', () => {
    const { graph, id } = addNode(LINEAR, 'wait', 'trigger')
    // trigger → wait → a
    expect(graph.edges.find((e) => e.from === 'trigger')?.to).toBe(id)
    expect(graph.edges.find((e) => e.from === id)?.to).toBe('a')
    expect(graph.nodes.some((n) => n.id === id && n.type === 'wait')).toBe(true)
  })

  it('appends when the source has no outgoing edge', () => {
    const { graph, id } = addNode(LINEAR, 'action:add_note', 'a')
    expect(graph.edges.find((e) => e.from === 'a')?.to).toBe(id)
  })

  it('gives a new node sensible type defaults', () => {
    const { graph, id } = addNode(LINEAR, 'wait', 'a')
    expect(graph.nodes.find((n) => n.id === id)?.hours).toBe(24)
  })

  it('does not mutate the input graph', () => {
    const before = JSON.stringify(LINEAR)
    addNode(LINEAR, 'wait', 'trigger')
    expect(JSON.stringify(LINEAR)).toBe(before)
  })
})

describe('removeNode', () => {
  it('removes a node and heals the chain to its successor', () => {
    const three = addNode(LINEAR, 'wait', 'trigger') // trigger → wait → a
    const healed = removeNode(three.graph, three.id)  // remove wait → trigger → a
    expect(healed.nodes.some((n) => n.id === three.id)).toBe(false)
    expect(healed.edges.find((e) => e.from === 'trigger')?.to).toBe('a')
  })

  it('refuses to remove the trigger', () => {
    const g = removeNode(LINEAR, 'trigger')
    expect(g.nodes.some((n) => n.id === 'trigger')).toBe(true)
  })

  it('removing a leaf just drops it', () => {
    const g = removeNode(LINEAR, 'a')
    expect(g.nodes.map((n) => n.id)).toEqual(['trigger'])
    expect(g.edges).toEqual([])
  })
})

describe('updateNode', () => {
  it('patches config fields', () => {
    const g = updateNode(LINEAR, 'a', { body: 'new copy' })
    expect(g.nodes.find((n) => n.id === 'a')?.body).toBe('new copy')
  })
})

describe('connect / disconnect', () => {
  it('retargets a plain node’s single outgoing edge', () => {
    const withNote = addNode(LINEAR, 'action:add_note', 'a').graph
    const noteId = withNote.nodes[withNote.nodes.length - 1].id
    const g = connect(withNote, 'trigger', noteId) // trigger now → note directly
    expect(g.edges.filter((e) => e.from === 'trigger')).toHaveLength(1)
    expect(g.edges.find((e) => e.from === 'trigger')?.to).toBe(noteId)
  })

  it('a condition keeps separate true/false branches', () => {
    const g0: FlowGraph = {
      nodes: [
        { id: 'trigger', type: 'trigger' },
        { id: 'c', type: 'condition' },
        { id: 'x', type: 'action:add_note' },
        { id: 'y', type: 'action:add_note' },
      ],
      edges: [{ from: 'trigger', to: 'c' }],
    }
    let g = connect(g0, 'c', 'x', 'true')
    g = connect(g, 'c', 'y', 'false')
    expect(g.edges.find((e) => e.from === 'c' && e.when === 'true')?.to).toBe('x')
    expect(g.edges.find((e) => e.from === 'c' && e.when === 'false')?.to).toBe('y')
  })

  it('refuses a self-loop', () => {
    expect(connect(LINEAR, 'a', 'a')).toEqual(LINEAR)
  })

  it('disconnect drops the edge', () => {
    const g = disconnect(LINEAR, 'trigger', 'a')
    expect(g.edges).toEqual([])
  })
})
