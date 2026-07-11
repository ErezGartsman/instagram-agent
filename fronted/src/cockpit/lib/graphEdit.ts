import type { FlowGraph, FlowNodeDef } from './flows'

/**
 * graphEdit — pure graph mutations for the F3 authoring canvas. Every editor
 * gesture (add/remove/connect/configure) is a pure (graph) → graph function,
 * so the editor stays thin and the mutation logic is unit-tested. All return
 * a NEW graph (immutable) — never mutate the input.
 */

let _seq = 0
/** Stable-enough unique node id for a session. */
export function newNodeId(type: string): string {
  _seq += 1
  const base = type.replace(/^action:/, '').replace(/[^a-z]/g, '')
  return `${base}_${Date.now().toString(36)}_${_seq}`
}

const DEFAULTS: Record<string, Partial<FlowNodeDef>> = {
  condition: { predicate: { field: 'stage', op: 'eq', value: 'qualified' } },
  wait: { hours: 24 },
  'action:send_message': { body: '' },
  'action:notify_operator': { body: 'A lead needs your attention.' },
  'action:advance_stage': { to_stage: 'qualified' },
  'action:add_note': { note: '' },
  'action:set_flag': { flag: '' },
}

/**
 * Add a node of `type`, wiring it in after `afterId` (its outgoing edge is
 * rerouted through the new node so the chain stays connected). If `afterId`
 * has no outgoing edge, the new node just becomes its successor.
 */
export function addNode(graph: FlowGraph, type: string, afterId: string): { graph: FlowGraph; id: string } {
  const id = newNodeId(type)
  const node: FlowNodeDef = { id, type, ...(DEFAULTS[type] ?? {}) }
  const nodes = [...graph.nodes, node]

  // Reroute afterId's existing single outgoing edge through the new node.
  const outgoing = graph.edges.find((e) => e.from === afterId && !e.when)
  let edges = graph.edges
  if (outgoing) {
    edges = graph.edges.map((e) =>
      e === outgoing ? { ...e, from: id } : e,
    )
    edges = [{ from: afterId, to: id }, ...edges]
  } else {
    edges = [...graph.edges, { from: afterId, to: id }]
  }
  return { graph: { nodes, edges }, id }
}

/** Remove a node (never the trigger) and heal the chain: edges into it are
 *  rerouted to its first successor so the flow doesn't fracture. */
export function removeNode(graph: FlowGraph, id: string): FlowGraph {
  const node = graph.nodes.find((n) => n.id === id)
  if (!node || node.type === 'trigger') return graph

  const successor = graph.edges.find((e) => e.from === id && !e.when)?.to
  const nodes = graph.nodes.filter((n) => n.id !== id)
  let edges = graph.edges.filter((e) => e.from !== id && e.to !== id)
  // Reroute incoming edges to the removed node's successor (if any).
  if (successor) {
    edges = edges.concat(
      graph.edges
        .filter((e) => e.to === id && e.from !== id)
        .map((e) => ({ ...e, to: successor })),
    )
  }
  // Dedup identical edges.
  const seen = new Set<string>()
  edges = edges.filter((e) => {
    const k = `${e.from}->${e.to}:${e.when ?? ''}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
  return { nodes, edges }
}

/** Patch a node's config fields (body/hours/predicate/etc). */
export function updateNode(graph: FlowGraph, id: string, patch: Partial<FlowNodeDef>): FlowGraph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)),
  }
}

/**
 * Connect `from` → `to`. For a plain (non-condition) source, a node has a
 * single outgoing edge, so this REPLACES it (retarget). For a condition
 * source, `when` distinguishes the true/false branches. Refuses self-loops.
 */
export function connect(graph: FlowGraph, from: string, to: string, when?: 'true' | 'false'): FlowGraph {
  if (from === to) return graph
  if (!graph.nodes.some((n) => n.id === from) || !graph.nodes.some((n) => n.id === to)) return graph
  const src = graph.nodes.find((n) => n.id === from)
  const isCondition = src?.type === 'condition'

  let edges: FlowGraph['edges']
  if (isCondition) {
    // Replace the same-branch edge, keep the other branch.
    edges = graph.edges.filter((e) => !(e.from === from && (e.when ?? undefined) === when))
    edges = [...edges, { from, to, when: when ?? 'true' }]
  } else {
    edges = graph.edges.filter((e) => e.from !== from)
    edges = [...edges, { from, to }]
  }
  return { ...graph, edges }
}

/** Remove the edge from→to (any branch). */
export function disconnect(graph: FlowGraph, from: string, to: string): FlowGraph {
  return { ...graph, edges: graph.edges.filter((e) => !(e.from === from && e.to === to)) }
}
