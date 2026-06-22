import { API_BASE } from './api'

// The Work Queue is the Decision Engine's surface: a priority-ranked list of
// people, each carrying the Action / Confidence / Reason it was surfaced for,
// a V1 activity timeline (the signal log — raw conversations stay out-of-system
// in V1), and the memory-first Person-360. One row, one recommended next move.

export type TimelineEvent = {
  kind: string
  /** Human-readable label for the signal (server-provided). */
  label: string
  at: string | null
}

export type QueueItem = {
  id: string
  person_id: string
  name: string
  initials: string
  channel: string | null
  /** Masked contact reference shown under the name (wa ref / @handle). */
  handle: string | null
  /** One-line reason the row is in the queue (shown in the dense left list). */
  teaser: string
  /** The single recommended next move — the Action half of the trust trio. */
  action: string
  /** Engine confidence in that action, 0–100 — the Confidence half. */
  confidence: number
  /** Why the engine ranked + recommended this — the Reason half. */
  reason: string
  last_contacted: string | null
  /** When this person first entered the system, for the Memory header. */
  first_seen_at: string | null
  /** V1 activity timeline: signal-log events, most recent first. */
  timeline: TimelineEvent[]
  /** The Memory layer: the core human problem, in narrative form. The one
   *  place the Fraunces serif speaks. Null until a profile summary exists. */
  essence: string | null
  goal: string | null
  tension: string | null
}

export async function fetchQueue(token: string, signal?: AbortSignal): Promise<QueueItem[]> {
  const res = await fetch(`${API_BASE}/api/cockpit/queue`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`queue ${res.status}`)
  const data = (await res.json()) as { items?: QueueItem[] }
  return data.items ?? []
}

/** The Action Loop moves an operator can take on a queued lead. */
export type QueueActionType = 'send' | 'done' | 'snooze' | 'dismiss'

/**
 * Apply one Work Queue action. Resolves on success; THROWS on any non-2xx so the
 * optimistic UI can roll the card back (the backend returns real status codes for
 * exactly this reason). `snoozeHours` only applies to 'snooze' (server defaults it).
 */
export async function postQueueAction(
  token: string,
  id: string,
  type: QueueActionType,
  opts: { snoozeHours?: number } = {},
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/cockpit/queue/${id}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ type, snooze_hours: opts.snoozeHours ?? null }),
  })
  if (!res.ok) throw new Error(`action ${res.status}`)
}

/** Highest confidence first — a stable client-side fallback ordering. The
 *  server already ranks by the rule-engine priority; this only re-sorts if a
 *  caller hands us an unranked list. */
export function rankQueue(items: QueueItem[]): QueueItem[] {
  return [...items].sort((a, b) => b.confidence - a.confidence)
}

function ago(secs: number): string {
  return new Date(Date.now() - secs * 1000).toISOString()
}

// Dev-bypass sample so the queue is populated during local UI work. Guarded by
// `import.meta.env.DEV` so the literal — and all this content — is dead-code-
// eliminated from production builds; no sample data ever ships.
export const SAMPLE_QUEUE: QueueItem[] = import.meta.env.DEV
  ? rankQueue([
      {
        id: 'q1', person_id: 'p1', name: 'Maya Goren', initials: 'MG',
        channel: 'whatsapp', handle: 'BR-1188',
        teaser: 'shared their context — ready to book',
        action: 'Send the booking link',
        confidence: 88,
        reason: 'shared their context — ready to book',
        last_contacted: ago(4 * 60), first_seen_at: ago(11 * 86400),
        timeline: [
          { kind: 'outreach_click', label: 'Clicked the outreach link', at: ago(4 * 60) },
          { kind: 'captured', label: 'Shared their context', at: ago(3 * 3600) },
          { kind: 'qualified', label: 'Qualified', at: ago(2 * 86400) },
          { kind: 'session_started', label: 'Started a conversation', at: ago(11 * 86400) },
        ],
        essence: "She isn't afraid of leaving. She's afraid of being the one who broke it.",
        goal: 'Decide before the anniversary, Jul 2',
        tension: 'Guilt vs. relief',
      },
      {
        id: 'q2', person_id: 'p2', name: 'Daniel Roth', initials: 'DR',
        channel: 'telegram', handle: '@daniel_r',
        teaser: 'qualified, then quiet 1d',
        action: 'Re-engage with a check-in',
        confidence: 66,
        reason: 'qualified, then quiet 1d',
        last_contacted: ago(26 * 3600), first_seen_at: ago(4 * 86400),
        timeline: [
          { kind: 'contacted', label: 'Was contacted', at: ago(26 * 3600) },
          { kind: 'qualified', label: 'Qualified', at: ago(2 * 86400) },
          { kind: 'session_started', label: 'Started a conversation', at: ago(4 * 86400) },
        ],
        essence: 'He keeps replaying the moment he lost her trust — and rehearsing an apology she will not hear.',
        goal: 'Earn one more conversation',
        tension: 'Shame vs. hope',
      },
      {
        id: 'q3', person_id: 'p3', name: 'Noa Levi', initials: 'NL',
        channel: 'whatsapp', handle: 'BR-4471',
        teaser: 'newly engaged',
        action: 'Open the conversation',
        confidence: 60,
        reason: 'newly engaged',
        last_contacted: ago(20 * 60), first_seen_at: ago(3 * 3600),
        timeline: [
          { kind: 'trigger_hit', label: 'Hit an interest trigger', at: ago(20 * 60) },
          { kind: 'session_started', label: 'Started a conversation', at: ago(3 * 3600) },
        ],
        essence: "The distance stopped hurting. That's the part that scares her.",
        goal: 'Find out if it is worth fighting for',
        tension: 'Sunk cost vs. drift',
      },
      {
        id: 'q4', person_id: 'p4', name: 'Ofir Ben-David', initials: 'OB',
        channel: 'whatsapp', handle: 'BR-9023',
        teaser: 'booked — confirm and prep',
        action: 'Confirm the upcoming session',
        confidence: 80,
        reason: 'booked — confirm and prep',
        last_contacted: ago(1 * 86400), first_seen_at: ago(6 * 86400),
        timeline: [
          { kind: 'booking_created', label: 'Booked a consultation', at: ago(1 * 86400) },
          { kind: 'captured', label: 'Shared their context', at: ago(3 * 86400) },
          { kind: 'session_started', label: 'Started a conversation', at: ago(6 * 86400) },
        ],
        essence: "He's not unsure about the relationship. He's unsure he's allowed to ask for help.",
        goal: 'Show up to the first session',
        tension: 'Pride vs. need',
      },
      {
        id: 'q5', person_id: 'p5', name: 'Tamar Shaked', initials: 'TS',
        channel: 'whatsapp', handle: 'BR-7781',
        teaser: 'went quiet 3w after first contact',
        action: 'Reopen with a gentle nudge',
        confidence: 52,
        reason: 'went quiet after first contact',
        last_contacted: ago(2 * 86400), first_seen_at: ago(21 * 86400),
        timeline: [
          { kind: 'contacted', label: 'Was contacted', at: ago(2 * 86400) },
          { kind: 'session_started', label: 'Started a conversation', at: ago(21 * 86400) },
        ],
        essence: 'She wants it to be fine. Saying it out loud is how she keeps it that way.',
        goal: 'Re-open the conversation later',
        tension: 'Avoidance vs. readiness',
      },
    ])
  : []
