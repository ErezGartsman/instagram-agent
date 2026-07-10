import type { FlowRun, FlowSummary } from './flows'

// Dev-bypass sample so the Flows canvas is populated during local UI work.
// Guarded by import.meta.env.DEV → the literal (and all this content) is
// dead-code-eliminated from production builds; no sample data ever ships.
// Mirrors the two seeded system flows (migration 009) and realistic
// shadow-mode runs whose Verifier Loop panels exercise every verdict:
// approved, blocked-by-staleness, deferred, circuit-broken.

function ago(secs: number): string {
  return new Date(Date.now() - secs * 1000).toISOString()
}

const COOLING_GRAPH = {
  nodes: [
    { id: 't1', type: 'trigger' as const },
    {
      id: 'n1',
      type: 'action:notify_operator' as const,
      body: 'A qualified lead has gone quiet 36h+ and needs a check-in — see the Work Queue.',
    },
  ],
  edges: [{ from: 't1', to: 'n1' }],
}

const BOOKING_GRAPH = {
  nodes: [
    { id: 't1', type: 'trigger' as const },
    {
      id: 'n1',
      type: 'action:notify_operator' as const,
      body: 'A booking was just canceled — worth a personal follow-up while it is fresh.',
    },
  ],
  edges: [{ from: 't1', to: 'n1' }],
}

export const SAMPLE_FLOWS: FlowSummary[] = import.meta.env.DEV
  ? [
      {
        id: 'flow-cooling',
        slug: 'cooling-lead-nudge',
        version: 1,
        status: 'published',
        live: false,
        name: 'Cooling lead → notify operator',
        description:
          'A qualified/captured/briefed lead who has gone quiet for 36h+ notifies Erez to reach out — the highest-value state trigger this business has.',
        trigger: {
          type: 'state',
          predicate: {
            all: [
              { field: 'stage', op: 'in', value: ['qualified', 'captured', 'briefed'] },
              { field: 'hours_since_last', op: 'gte', value: 36 },
            ],
          },
        },
        graph: COOLING_GRAPH,
        created_at: ago(5 * 86400),
        published_at: ago(5 * 86400),
        run_count: 34,
        last_run_at: ago(22 * 60),
      },
      {
        id: 'flow-booking',
        slug: 'booking-canceled-reengage',
        version: 1,
        status: 'published',
        live: false,
        name: 'Booking canceled → notify operator',
        description:
          'A canceled booking notifies Erez to personally re-engage — a canceled consultation is a live wire, not a bot conversation.',
        trigger: { type: 'event', kind: 'booking_canceled' },
        graph: BOOKING_GRAPH,
        created_at: ago(5 * 86400),
        published_at: ago(5 * 86400),
        run_count: 6,
        last_run_at: ago(3 * 3600),
      },
    ]
  : []

// ── Runs, keyed by flow id ───────────────────────────────────────────────────

const APPROVE_PANEL = {
  decision: 'approve' as const,
  verdicts: [
    { verifier: 'staleness', decision: 'approve' as const },
    { verifier: 'duplicate_content', decision: 'approve' as const },
    { verifier: 'upcoming_booking', decision: 'approve' as const },
    { verifier: 'recent_inbound', decision: 'approve' as const },
    { verifier: 'circuit_breaker', decision: 'approve' as const },
  ],
}

const STALE_PANEL = {
  decision: 'reject' as const,
  verdicts: [
    {
      verifier: 'staleness',
      decision: 'reject' as const,
      reason: 'stale_trigger',
      detail: 'trigger predicate no longer holds against live signals',
    },
    { verifier: 'duplicate_content', decision: 'approve' as const },
    { verifier: 'upcoming_booking', decision: 'approve' as const },
    { verifier: 'recent_inbound', decision: 'approve' as const },
    { verifier: 'circuit_breaker', decision: 'approve' as const },
  ],
  blocking: {
    verifier: 'staleness',
    decision: 'reject' as const,
    reason: 'stale_trigger',
    detail: 'trigger predicate no longer holds against live signals',
  },
}

const DEFER_PANEL = {
  decision: 'defer' as const,
  verdicts: [
    { verifier: 'staleness', decision: 'approve' as const },
    { verifier: 'duplicate_content', decision: 'approve' as const },
    { verifier: 'upcoming_booking', decision: 'approve' as const },
    {
      verifier: 'recent_inbound',
      decision: 'defer' as const,
      reason: 'recent_inbound_activity',
      detail: 'inbound within 2h — the conversation is live',
      defer_hours: 2,
    },
    { verifier: 'circuit_breaker', decision: 'approve' as const },
  ],
  blocking: {
    verifier: 'recent_inbound',
    decision: 'defer' as const,
    reason: 'recent_inbound_activity',
    detail: 'inbound within 2h — the conversation is live',
    defer_hours: 2,
  },
}

const BOOKING_PANEL = {
  decision: 'reject' as const,
  verdicts: [
    { verifier: 'staleness', decision: 'approve' as const },
    { verifier: 'duplicate_content', decision: 'approve' as const },
    {
      verifier: 'upcoming_booking',
      decision: 'reject' as const,
      reason: 'upcoming_booking',
      detail: 'a scheduled booking exists — nothing to chase',
    },
    { verifier: 'recent_inbound', decision: 'approve' as const },
    { verifier: 'circuit_breaker', decision: 'approve' as const },
  ],
  blocking: {
    verifier: 'upcoming_booking',
    decision: 'reject' as const,
    reason: 'upcoming_booking',
    detail: 'a scheduled booking exists — nothing to chase',
  },
}

const COOLING_BODY =
  'A qualified lead has gone quiet 36h+ and needs a check-in — see the Work Queue.'

export const SAMPLE_RUNS: Record<string, FlowRun[]> = import.meta.env.DEV
  ? {
      'flow-cooling': [
        {
          id: 'run-1', person_id: 'p1', person_name: 'Maya Goren', status: 'success',
          cursor_node: null, started_at: ago(22 * 60), completed_at: ago(22 * 60 - 1),
          steps: [
            { node_id: 't1', node_type: 'trigger', status: 'success', output: {}, error: null, at: ago(22 * 60) },
            {
              node_id: 'n1', node_type: 'action:notify_operator', status: 'shadow',
              output: { would_notify: COOLING_BODY, verification: APPROVE_PANEL },
              error: null, at: ago(22 * 60 - 1),
            },
          ],
        },
        {
          id: 'run-2', person_id: 'p2', person_name: 'Daniel Roth', status: 'success',
          cursor_node: null, started_at: ago(2 * 3600), completed_at: ago(2 * 3600 - 1),
          steps: [
            { node_id: 't1', node_type: 'trigger', status: 'success', output: {}, error: null, at: ago(2 * 3600) },
            {
              node_id: 'n1', node_type: 'action:notify_operator', status: 'blocked',
              output: { reason: 'verifier:stale_trigger', detail: 'lead replied since dispatch', verification: STALE_PANEL },
              error: null, at: ago(2 * 3600 - 1),
            },
          ],
        },
        {
          id: 'run-3', person_id: 'p3', person_name: 'Noa Levi', status: 'waiting',
          cursor_node: 'n1', started_at: ago(6 * 3600), completed_at: null,
          steps: [
            { node_id: 't1', node_type: 'trigger', status: 'success', output: {}, error: null, at: ago(6 * 3600) },
            {
              node_id: 'n1', node_type: 'action:notify_operator', status: 'waiting',
              output: { would_notify: COOLING_BODY, verification: DEFER_PANEL, retry_at: ago(-2 * 3600) },
              error: null, at: ago(6 * 3600 - 1),
            },
          ],
        },
        {
          id: 'run-4', person_id: 'p5', person_name: 'Tamar Shaked', status: 'success',
          cursor_node: null, started_at: ago(26 * 3600), completed_at: ago(26 * 3600 - 1),
          steps: [
            { node_id: 't1', node_type: 'trigger', status: 'success', output: {}, error: null, at: ago(26 * 3600) },
            {
              node_id: 'n1', node_type: 'action:notify_operator', status: 'shadow',
              output: { would_notify: COOLING_BODY, verification: APPROVE_PANEL },
              error: null, at: ago(26 * 3600 - 1),
            },
          ],
        },
      ],
      'flow-booking': [
        {
          id: 'run-b1', person_id: 'p4', person_name: 'Ofir Ben-David', status: 'success',
          cursor_node: null, started_at: ago(3 * 3600), completed_at: ago(3 * 3600 - 1),
          steps: [
            { node_id: 't1', node_type: 'trigger', status: 'success', output: {}, error: null, at: ago(3 * 3600) },
            {
              node_id: 'n1', node_type: 'action:notify_operator', status: 'blocked',
              output: { reason: 'verifier:upcoming_booking', verification: BOOKING_PANEL },
              error: null, at: ago(3 * 3600 - 1),
            },
          ],
        },
      ],
    }
  : {}
