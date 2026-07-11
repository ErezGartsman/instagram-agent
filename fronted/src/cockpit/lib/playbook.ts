import type { FlowGraph, FlowNodeDef, FlowTrigger } from './flows'

/**
 * playbook — the F3 authoring model. A playbook is a flow whose graph is a
 * single linear chain: trigger → step → step → … Every editor gesture works
 * on a flat PlaybookStep[] (no nodes, no edges, no canvas); this module
 * compiles that list to/from the engine's graph format losslessly, so the
 * backend contract (validate_graph, the runner, the simulator) is untouched.
 *
 * Graphs that don't fit the linear shape (hand-authored branches) degrade
 * gracefully: graphToSteps returns null and the UI shows a read-only notice
 * instead of pretending it can edit them.
 */

// ── Step model ────────────────────────────────────────────────────────────────

export type PlaybookStep =
  | { kind: 'wait'; hours: number }
  | { kind: 'if'; predicate: unknown }
  | { kind: 'send'; body: string }
  | { kind: 'notify'; body: string }
  | { kind: 'advance'; to_stage: string }
  | { kind: 'note'; note: string }
  | { kind: 'flag'; flag: string }

export type StepKind = PlaybookStep['kind']

/** step kind ↔ engine node type. */
export const KIND_TO_NODE: Record<StepKind, string> = {
  wait: 'wait',
  if: 'condition',
  send: 'action:send_message',
  notify: 'action:notify_operator',
  advance: 'action:advance_stage',
  note: 'action:add_note',
  flag: 'action:set_flag',
}

const NODE_TO_KIND: Record<string, StepKind> = Object.fromEntries(
  Object.entries(KIND_TO_NODE).map(([k, v]) => [v, k as StepKind]),
) as Record<string, StepKind>

export const STAGES = ['engaged', 'qualified', 'captured', 'briefed', 'booked'] as const

export const EVENT_KINDS = [
  'booking_canceled', 'booking_created', 'captured', 'qualified',
  'outreach_click', 'contacted', 'stage_change',
] as const

/** A fresh step of each kind, with sane defaults (mirrors the engine's expectations). */
export function newStep(kind: StepKind): PlaybookStep {
  switch (kind) {
    case 'wait': return { kind, hours: 24 }
    case 'if': return { kind, predicate: buildPredicate({ stages: ['qualified'], hours: null }) }
    case 'send': return { kind, body: '' }
    case 'notify': return { kind, body: 'A lead needs your attention.' }
    case 'advance': return { kind, to_stage: 'qualified' }
    case 'note': return { kind, note: '' }
    case 'flag': return { kind, flag: '' }
  }
}

/** The default recipe for a brand-new playbook. */
export function blankSteps(): PlaybookStep[] {
  return [{ kind: 'notify', body: 'A lead needs your attention.' }]
}

// ── Compiler: steps ↔ graph ──────────────────────────────────────────────────

function nodeToStep(node: FlowNodeDef): PlaybookStep | null {
  const kind = NODE_TO_KIND[node.type]
  if (!kind) return null
  switch (kind) {
    case 'wait': return { kind, hours: node.hours ?? 24 }
    case 'if': return { kind, predicate: node.predicate ?? {} }
    case 'send': return { kind, body: node.body ?? '' }
    case 'notify': return { kind, body: node.body ?? '' }
    case 'advance': return { kind, to_stage: node.to_stage ?? 'qualified' }
    case 'note': return { kind, note: node.note ?? '' }
    case 'flag': return { kind, flag: node.flag ?? '' }
  }
}

function stepToNode(step: PlaybookStep, id: string): FlowNodeDef {
  switch (step.kind) {
    case 'wait': return { id, type: 'wait', hours: step.hours }
    case 'if': return { id, type: 'condition', predicate: step.predicate }
    case 'send': return { id, type: 'action:send_message', body: step.body }
    case 'notify': return { id, type: 'action:notify_operator', body: step.body }
    case 'advance': return { id, type: 'action:advance_stage', to_stage: step.to_stage }
    case 'note': return { id, type: 'action:add_note', note: step.note }
    case 'flag': return { id, type: 'action:set_flag', flag: step.flag }
  }
}

/**
 * Flatten a graph into an ordered step list, or null if it isn't a single
 * linear chain from the trigger (branching false-edges, orphan nodes, or a
 * cycle all disqualify it — those graphs stay read-only in the UI).
 */
export function graphToSteps(graph: FlowGraph): PlaybookStep[] | null {
  const triggers = graph.nodes.filter((n) => n.type === 'trigger')
  if (triggers.length !== 1) return null

  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const steps: PlaybookStep[] = []
  const visited = new Set<string>([triggers[0].id])
  let current = triggers[0].id

  for (;;) {
    const out = graph.edges.filter((e) => e.from === current)
    if (out.length === 0) break
    // A condition may only follow its true-branch; a false-branch means a
    // real fork, which the linear model can't express.
    const next = out.length === 1 && (out[0].when === undefined || out[0].when === 'true')
      ? out[0].to
      : null
    if (!next || visited.has(next)) return null
    const node = byId.get(next)
    if (!node) return null
    const step = nodeToStep(node)
    if (!step) return null
    steps.push(step)
    visited.add(next)
    current = next
  }

  // Orphan nodes outside the chain mean this wasn't the whole graph.
  if (visited.size !== graph.nodes.length) return null
  return steps
}

/** Compile a step list to the engine's graph shape. Inverse of graphToSteps. */
export function stepsToGraph(steps: PlaybookStep[]): FlowGraph {
  const nodes: FlowNodeDef[] = [{ id: 'trigger', type: 'trigger' }]
  const edges: FlowGraph['edges'] = []
  let prev = 'trigger'
  let prevKind: StepKind | null = null
  steps.forEach((step, i) => {
    const id = `s${i + 1}`
    nodes.push(stepToNode(step, id))
    edges.push(prevKind === 'if' ? { from: prev, to: id, when: 'true' } : { from: prev, to: id })
    prev = id
    prevKind = step.kind
  })
  return { nodes, edges }
}

// ── Predicate model (shared by state triggers and 'if' steps) ────────────────
//
// The bounded, safe subset the visual builder edits: "stage is one of [...]
// AND quiet ≥ N hours". Anything else parses to null and stays read-only.

export type PredicateModel = { stages: string[]; hours: number | null }

export function parsePredicate(pred: unknown): PredicateModel | null {
  if (!pred || typeof pred !== 'object') return { stages: [], hours: null }
  const p = pred as Record<string, unknown>
  if (Object.keys(p).length === 0) return { stages: [], hours: null }
  const clauses = Array.isArray(p.all) ? (p.all as Record<string, unknown>[]) : [p]
  const model: PredicateModel = { stages: [], hours: null }
  let recognized = 0
  for (const c of clauses) {
    if (c.field === 'stage' && c.op === 'in' && Array.isArray(c.value)) {
      model.stages = (c.value as string[]).filter((s) => (STAGES as readonly string[]).includes(s))
      recognized++
    } else if (c.field === 'stage' && c.op === 'eq' && typeof c.value === 'string') {
      model.stages = [c.value]
      recognized++
    } else if (c.field === 'hours_since_last' && c.op === 'gte' && typeof c.value === 'number') {
      model.hours = c.value
      recognized++
    } else {
      return null // an unrecognized clause — don't pretend we can edit it
    }
  }
  return recognized > 0 || Object.keys(p).length === 0 ? model : null
}

export function buildPredicate(model: PredicateModel): Record<string, unknown> {
  const clauses: Record<string, unknown>[] = []
  if (model.stages.length) clauses.push({ field: 'stage', op: 'in', value: model.stages })
  if (model.hours != null) clauses.push({ field: 'hours_since_last', op: 'gte', value: model.hours })
  if (clauses.length === 1) return clauses[0]
  return { all: clauses }
}

// ── Natural language: the sentence a playbook card reads as ─────────────────

const EVENT_PHRASE: Record<string, string> = {
  booking_canceled: 'a booking is canceled',
  booking_created: 'a booking is made',
  captured: 'a lead is captured',
  qualified: 'a lead becomes qualified',
  outreach_click: 'a lead clicks an outreach link',
  contacted: 'a lead is contacted',
  stage_change: 'a lead changes stage',
}

export function eventPhrase(kind: string): string {
  return EVENT_PHRASE[kind] ?? `${kind.replace(/_/g, ' ')} happens`
}

function listPhrase(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  return `${items.slice(0, -1).join(', ')} or ${items[items.length - 1]}`
}

export function predicatePhrase(pred: unknown): string {
  const model = parsePredicate(pred)
  if (!model) return 'a custom condition holds'
  const parts: string[] = []
  if (model.stages.length) parts.push(`a lead in ${listPhrase(model.stages)}`)
  else parts.push('a lead')
  if (model.hours != null) parts.push(`has been quiet for ${model.hours}+ hours`)
  return parts.length > 1 ? parts.join(' ') : `${parts[0]} matches`
}

export function triggerPhrase(trigger: FlowTrigger): string {
  if (trigger.type === 'event') return eventPhrase(trigger.kind ?? 'event')
  return predicatePhrase(trigger.predicate)
}

export function stepPhrase(step: PlaybookStep): string {
  switch (step.kind) {
    case 'wait': return step.hours === 1 ? 'wait an hour' : `wait ${step.hours} hours`
    case 'if': return `only if ${predicatePhrase(step.predicate)}`
    case 'send': return 'message the lead'
    case 'notify': return 'notify Erez'
    case 'advance': return `move them to ${step.to_stage}`
    case 'note': return 'add a note'
    case 'flag': return step.flag ? `flag as ${step.flag.replace(/_/g, ' ')}` : 'set a flag'
  }
}

/** The full card sentence: When …, then … */
export function playbookSentence(trigger: FlowTrigger, steps: PlaybookStep[] | null): {
  when: string
  then: string[]
} {
  const when = triggerPhrase(trigger)
  if (steps === null) return { when, then: ['run custom branching logic'] }
  if (steps.length === 0) return { when, then: ['do nothing yet'] }
  return { when, then: steps.map(stepPhrase) }
}
