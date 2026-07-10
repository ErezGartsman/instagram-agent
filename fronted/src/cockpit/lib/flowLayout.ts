import type { FlowGraph } from './flows'

/**
 * flowLayout — a pure, deterministic layered layout for flow graphs (F2
 * canvas). No React, no DOM: graph in → positioned nodes + bezier edge paths
 * out, so it's unit-tested in isolation.
 *
 * Algorithm (Sugiyama-lite, left-to-right for DAGs):
 *   1. depth(node) = longest path from any root (a node with no incoming
 *      edge). Longest-path layering keeps every edge pointing forward and
 *      avoids back-edges visually.
 *   2. Group by depth into columns; order within a column by first appearance
 *      (stable — the seeded flows render identically every load).
 *   3. x from depth, y centered per column against the tallest column.
 *   4. Edges: cubic bezier from a source's right-center to a target's
 *      left-center, control points pulled horizontally for a smooth S.
 *
 * Cycles (which the runner guards against at execution time but a malformed
 * graph could still contain) are handled defensively: the longest-path pass
 * is depth-bounded so it always terminates.
 */

export const NODE_W = 208
export const NODE_H = 76
const COL_GAP = 96 // horizontal space between columns
const ROW_GAP = 40 // vertical space between stacked nodes
const PAD = 28 // canvas padding around the content

export type PositionedNode = {
  id: string
  x: number
  y: number
  w: number
  h: number
}

export type PositionedEdge = {
  from: string
  to: string
  when?: 'true' | 'false'
  /** SVG cubic-bezier `d`. */
  path: string
  /** Midpoint, for an optional edge label (branch when=true/false). */
  labelX: number
  labelY: number
}

export type Layout = {
  nodes: Record<string, PositionedNode>
  edges: PositionedEdge[]
  width: number
  height: number
}

function computeDepths(graph: FlowGraph): Map<string, number> {
  const ids = graph.nodes.map((n) => n.id)
  const incoming = new Map<string, number>(ids.map((id) => [id, 0]))
  const adj = new Map<string, string[]>(ids.map((id) => [id, []]))
  for (const e of graph.edges) {
    if (!adj.has(e.from) || !incoming.has(e.to)) continue
    adj.get(e.from)!.push(e.to)
    incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1)
  }

  const depth = new Map<string, number>(ids.map((id) => [id, 0]))
  // Longest-path via relaxation, bounded to node-count iterations so a cycle
  // (should never happen post-runner-guard, but be safe) can't loop forever.
  const maxIter = ids.length + 1
  for (let i = 0; i < maxIter; i++) {
    let changed = false
    for (const e of graph.edges) {
      if (!depth.has(e.from) || !depth.has(e.to)) continue
      const cand = depth.get(e.from)! + 1
      if (cand > depth.get(e.to)!) {
        depth.set(e.to, cand)
        changed = true
      }
    }
    if (!changed) break
  }
  return depth
}

export function layoutFlow(graph: FlowGraph): Layout {
  if (!graph.nodes.length) return { nodes: {}, edges: [], width: PAD * 2, height: PAD * 2 }

  const depth = computeDepths(graph)

  // Columns, preserving first-appearance order within each.
  const columns = new Map<number, string[]>()
  for (const n of graph.nodes) {
    const d = depth.get(n.id) ?? 0
    if (!columns.has(d)) columns.set(d, [])
    columns.get(d)!.push(n.id)
  }

  const maxRows = Math.max(...[...columns.values()].map((c) => c.length))
  const contentH = maxRows * NODE_H + (maxRows - 1) * ROW_GAP

  const nodes: Record<string, PositionedNode> = {}
  const sortedDepths = [...columns.keys()].sort((a, b) => a - b)
  for (const d of sortedDepths) {
    const col = columns.get(d)!
    const colH = col.length * NODE_H + (col.length - 1) * ROW_GAP
    const yStart = PAD + (contentH - colH) / 2 // center this column vertically
    col.forEach((id, row) => {
      nodes[id] = {
        id,
        x: PAD + d * (NODE_W + COL_GAP),
        y: yStart + row * (NODE_H + ROW_GAP),
        w: NODE_W,
        h: NODE_H,
      }
    })
  }

  const edges: PositionedEdge[] = graph.edges
    .filter((e) => nodes[e.from] && nodes[e.to])
    .map((e) => {
      const a = nodes[e.from]
      const b = nodes[e.to]
      const x1 = a.x + a.w
      const y1 = a.y + a.h / 2
      const x2 = b.x
      const y2 = b.y + b.h / 2
      const dx = Math.max(40, (x2 - x1) * 0.5)
      return {
        from: e.from,
        to: e.to,
        when: e.when,
        path: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
        labelX: (x1 + x2) / 2,
        labelY: (y1 + y2) / 2 - 8,
      }
    })

  const cols = sortedDepths.length
  const width = PAD * 2 + cols * NODE_W + (cols - 1) * COL_GAP
  const height = PAD * 2 + contentH

  return { nodes, edges, width, height }
}

/**
 * The set of nodes a run actually visited, derived from its steps — the
 * canvas lights exactly these on replay. Returns node_id → step status
 * (the last status if a node ran more than once, e.g. a retried send).
 */
export function runPath(steps: { node_id: string; status: string }[]): Map<string, string> {
  const path = new Map<string, string>()
  for (const s of steps) path.set(s.node_id, s.status)
  return path
}

/** Edges on the taken path: both endpoints were visited. Used to light the
 *  traversed connectors on replay. */
export function activeEdges(
  edges: PositionedEdge[],
  visited: Map<string, string>,
): Set<string> {
  const active = new Set<string>()
  for (const e of edges) {
    if (visited.has(e.from) && visited.has(e.to)) active.add(`${e.from}->${e.to}`)
  }
  return active
}
