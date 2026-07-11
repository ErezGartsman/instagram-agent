import { apiFetch } from './http'

// The Flows engine's read surface (the Playbooks page). The backend
// (routers/flows.py) ships flow definitions with their graph inline, plus
// per-flow run history where every run carries its executed steps — and a
// send step carries the full Verifier Loop panel that decided its fate.

// ── Graph shape (flow_definitions.graph) ─────────────────────────────────────

export type FlowNodeType =
  | 'trigger'
  | 'condition'
  | 'wait'
  | 'action:send_message'
  | 'action:notify_operator'
  | 'action:advance_stage'
  | 'action:add_note'
  | 'action:set_flag'

/** A node is {id, type, …type-specific fields}. We keep the extras loose —
 *  the playbook compiler reads a few known ones (body, note, hours, to_stage). */
export type FlowNodeDef = {
  id: string
  type: FlowNodeType | string
  body?: string
  note?: string
  flag?: string
  hours?: number
  to_stage?: string
  predicate?: unknown
}

export type FlowEdge = { from: string; to: string; when?: 'true' | 'false' }

export type FlowGraph = { nodes: FlowNodeDef[]; edges: FlowEdge[] }

export type FlowTrigger = {
  type: 'state' | 'event'
  kind?: string
  predicate?: unknown
}

export type FlowStatus = 'draft' | 'published' | 'paused' | 'archived'

export type FlowSummary = {
  id: string
  slug: string
  version: number
  status: FlowStatus
  /** false = shadow mode (the engine runs it and records what it WOULD do,
   *  but never performs the real outward action). The whole point of F2. */
  live: boolean
  name: string
  description: string | null
  trigger: FlowTrigger
  graph: FlowGraph
  created_at: string | null
  published_at: string | null
  run_count: number
  last_run_at: string | null
}

// ── Run shape (flow_runs + flow_run_steps) ───────────────────────────────────

export type RunStatus = 'running' | 'waiting' | 'success' | 'stopped' | 'failed'
export type StepStatus = 'success' | 'shadow' | 'blocked' | 'waiting' | 'failed'

/** One verifier's verdict inside the Verifier Loop panel. */
export type VerifierVerdict = {
  verifier: string
  decision: 'approve' | 'reject' | 'defer' | 'error'
  reason?: string
  detail?: string
  defer_hours?: number
}

export type Verification = {
  decision: 'approve' | 'reject' | 'defer'
  verdicts: VerifierVerdict[]
  blocking?: VerifierVerdict
}

/** A send/notify step's output may embed the verifier panel + a preview of
 *  what the engine would (or did) send. Other node types carry their own
 *  small output shapes (result, advanced, retry_at…). */
export type StepOutput = {
  would_send?: string
  would_notify?: string
  channel?: string
  verification?: Verification
  reason?: string
  detail?: string
  result?: boolean
  advanced?: boolean
  to_stage?: string
  fire_at?: string
  retry_at?: string
  provider_message_id?: string | null
}

export type FlowRunStep = {
  node_id: string
  node_type: string
  status: StepStatus
  output: StepOutput
  error: string | null
  at: string | null
}

export type FlowRun = {
  id: string
  person_id: string
  person_name: string
  status: RunStatus
  cursor_node: string | null
  started_at: string | null
  completed_at: string | null
  steps: FlowRunStep[]
}

// ── Fetchers ─────────────────────────────────────────────────────────────────

export type FlowsResponse = { enabled: boolean; flows: FlowSummary[] }

export async function fetchFlows(token: string, signal?: AbortSignal): Promise<FlowsResponse> {
  const data = await apiFetch<{ enabled?: boolean; flows?: FlowSummary[] }>(
    '/api/cockpit/flows', token, { signal },
  )
  return { enabled: !!data.enabled, flows: data.flows ?? [] }
}

export async function fetchFlowRuns(
  token: string, flowId: string, signal?: AbortSignal,
): Promise<FlowRun[]> {
  const data = await apiFetch<{ runs?: FlowRun[] }>(
    `/api/cockpit/flows/${encodeURIComponent(flowId)}/runs`, token, { signal },
  )
  return data.runs ?? []
}

export type SweepResult = {
  events_dispatched: number
  states_dispatched: number
  run: Record<string, number | string>
}

export async function triggerFlowsSweep(token: string): Promise<SweepResult | null> {
  try {
    return await apiFetch<SweepResult>('/api/cockpit/flows/sweep', token, { method: 'POST' })
  } catch {
    return null
  }
}

// ── Authoring (F3) ────────────────────────────────────────────────────────────

/** The 90-day simulation impact report (nexus/flows/simulate.py). */
export type SimulationReport = {
  window_days: number
  trigger_type: string
  fires: number
  actions: Record<string, number>
  blocked: number
  blocked_by: Record<string, number>
  sample: { person_name: string; at: string; outcome: string; reason: string | null }[]
  notes: string[]
}

type FlowDraftBody = {
  name?: string
  description?: string | null
  trigger?: FlowTrigger
  graph?: FlowGraph
}

export async function createFlow(token: string, body: FlowDraftBody): Promise<{ id: string }> {
  return apiFetch<{ id: string }>('/api/cockpit/flows', token, {
    method: 'POST', body: JSON.stringify(body),
  })
}

export async function updateFlow(token: string, id: string, body: FlowDraftBody): Promise<void> {
  await apiFetch(`/api/cockpit/flows/${encodeURIComponent(id)}`, token, {
    method: 'PATCH', body: JSON.stringify(body),
  })
}

export async function forkFlow(token: string, id: string): Promise<{ id: string }> {
  return apiFetch<{ id: string }>(`/api/cockpit/flows/${encodeURIComponent(id)}/fork`, token, { method: 'POST' })
}

export async function simulateFlow(
  token: string, id: string, body?: { graph?: FlowGraph; trigger?: FlowTrigger },
): Promise<SimulationReport> {
  const data = await apiFetch<{ report: SimulationReport }>(
    `/api/cockpit/flows/${encodeURIComponent(id)}/simulate`, token,
    { method: 'POST', body: JSON.stringify(body ?? {}) },
  )
  return data.report
}

export async function publishFlow(token: string, id: string): Promise<SimulationReport> {
  const data = await apiFetch<{ report: SimulationReport }>(
    `/api/cockpit/flows/${encodeURIComponent(id)}/publish`, token, { method: 'POST' },
  )
  return data.report
}

export async function setFlowStatus(
  token: string, id: string, action: 'pause' | 'resume' | 'archive',
): Promise<void> {
  await apiFetch(`/api/cockpit/flows/${encodeURIComponent(id)}/status`, token, {
    method: 'POST', body: JSON.stringify({ action }),
  })
}

export async function setFlowLive(token: string, id: string, live: boolean): Promise<void> {
  await apiFetch(`/api/cockpit/flows/${encodeURIComponent(id)}/live`, token, {
    method: 'POST', body: JSON.stringify({ live }),
  })
}

export async function updateFlowSettings(
  token: string, body: { enabled?: boolean; pressure_budget?: number },
): Promise<{ enabled: boolean; pressure_budget: number }> {
  return apiFetch<{ enabled: boolean; pressure_budget: number }>(
    '/api/cockpit/flow-settings', token, { method: 'PATCH', body: JSON.stringify(body) },
  )
}

/** Reason-code → plain language for the simulation's blocked breakdown. */
export const BLOCK_REASON_LABEL: Record<string, string> = {
  crisis: 'Crisis signal',
  pressure_budget: 'Pressure budget',
  quiet_hours: 'Quiet hours',
}

export function blockReasonLabel(reason: string): string {
  return BLOCK_REASON_LABEL[reason] ?? reason.replace(/_/g, ' ')
}

// ── Presentation helpers (single source of truth for status → meaning) ───────

/** Human label + a semantic tone token for a node type. Tone maps to the
 *  Midnight Instrument palette; the composer + inspector both read this. */
export const NODE_META: Record<string, { label: string; tone: string; icon: string }> = {
  trigger:                  { label: 'Trigger',        tone: 'sage',   icon: 'zap' },
  condition:                { label: 'Condition',      tone: 'glow',   icon: 'branch' },
  wait:                     { label: 'Wait',           tone: 'warn',   icon: 'clock' },
  'action:send_message':    { label: 'Send message',   tone: 'accent', icon: 'send' },
  'action:notify_operator': { label: 'Notify Erez',    tone: 'accent', icon: 'bell' },
  'action:advance_stage':   { label: 'Advance stage',  tone: 'glow',   icon: 'arrowRight' },
  'action:add_note':        { label: 'Add note',       tone: 'muted',  icon: 'sparkle' },
  'action:set_flag':        { label: 'Set flag',       tone: 'muted',  icon: 'flag' },
}

export function nodeMeta(type: string) {
  return NODE_META[type] ?? { label: type, tone: 'muted', icon: 'sparkle' }
}

export const RUN_STATUS_TONE: Record<RunStatus, string> = {
  running: 'glow', waiting: 'warn', success: 'success', stopped: 'faint', failed: 'danger',
}

/** A run step's status → the palette tone the node ring + inspector chip use.
 *  'shadow' is deliberately accent (electric blue) — "this is what it WOULD
 *  have done", the signature of shadow mode. */
export const STEP_STATUS_TONE: Record<StepStatus, string> = {
  success: 'success', shadow: 'accent', blocked: 'danger', waiting: 'warn', failed: 'danger',
}

export const STEP_STATUS_LABEL: Record<StepStatus, string> = {
  success: 'Ran', shadow: 'Would run', blocked: 'Blocked', waiting: 'Parked', failed: 'Failed',
}

export const VERDICT_TONE: Record<VerifierVerdict['decision'], string> = {
  approve: 'success', reject: 'danger', defer: 'warn', error: 'faint',
}

/** Plain-language names for the five verifiers — the panel reads them so
 *  Erez never sees a raw snake_case identifier. */
export const VERIFIER_LABEL: Record<string, string> = {
  staleness: 'Still relevant?',
  duplicate_content: 'Not a repeat?',
  upcoming_booking: 'No booking already?',
  recent_inbound: 'Not mid-conversation?',
  circuit_breaker: 'Pattern not failing?',
}

export function verifierLabel(name: string): string {
  return VERIFIER_LABEL[name] ?? name
}
