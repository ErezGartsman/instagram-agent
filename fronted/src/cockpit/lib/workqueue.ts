import { API_BASE } from './api'

// The Work Queue is the Decision Engine's surface: a priority-ranked list of
// people, each carrying the Action / Confidence / Reason it was surfaced for,
// the conversation thread, and the memory-first Person-360. One row, one
// recommended next move.

export type ThreadMessage = { from: 'them' | 'me'; text: string }

export type QueueItem = {
  id: string
  person_id: string
  name: string
  initials: string
  channel: string | null
  /** Masked contact reference shown under the name (phone / @handle). */
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
  /** Human-readable first-contact recency for the Memory header. */
  firstContactAgo: string
  thread: ThreadMessage[]
  /** The Memory layer: the core human problem, in the operator's own words.
   *  This is the one place the Fraunces serif speaks. */
  essence: string
  goal: string
  tension: string
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

/** Highest confidence first — the queue is a ranking, not a chat list. */
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
        channel: 'whatsapp', handle: '+972 54-•••-1188',
        teaser: 'Asked about pricing before the deadline',
        action: 'Offer the Saturday clarity call',
        confidence: 92,
        reason: 're-engaged after 3 days; asked about pricing',
        last_contacted: ago(4 * 60), firstContactAgo: '11 days ago',
        thread: [
          { from: 'them', text: 'I keep starting the conversation in my head and then deleting it.' },
          { from: 'me', text: "That rehearsal is information — it's telling you what you're protecting." },
          { from: 'them', text: 'Do you do single sessions? I think I need help before the 2nd.' },
        ],
        essence: "She isn't afraid of leaving. She's afraid of being the one who broke it.",
        goal: 'Decide before the anniversary, Jul 2',
        tension: 'Guilt vs. relief',
      },
      {
        id: 'q2', person_id: 'p2', name: 'Daniel Roth', initials: 'DR',
        channel: 'telegram', handle: '@daniel_r',
        teaser: 'Opened, no reply for 26h',
        action: 'Send the trust-repair primer',
        confidence: 78,
        reason: 'opened last 2 messages; no reply for 26h',
        last_contacted: ago(1 * 3600), firstContactAgo: '4 days ago',
        thread: [
          { from: 'them', text: "She read it. She didn't reply. I don't know what that means." },
          { from: 'me', text: 'Silence after a rupture is rarely a verdict — usually it is self-protection.' },
          { from: 'them', text: "I'll wait. But I can't keep doing this on my own." },
        ],
        essence: 'He keeps replaying the moment he lost her trust — and rehearsing an apology she will not hear.',
        goal: 'Earn one more conversation',
        tension: 'Shame vs. hope',
      },
      {
        id: 'q3', person_id: 'p3', name: 'Noa Levi', initials: 'NL',
        channel: 'whatsapp', handle: '+972 52-•••-4471',
        teaser: 'New lead · high-intent language',
        action: 'Ask the one diagnostic question',
        confidence: 64,
        reason: 'new lead; high-intent language',
        last_contacted: ago(20 * 60), firstContactAgo: 'today',
        thread: [
          { from: 'them', text: "We used to talk for hours. Now it's just 'goodnight'." },
          { from: 'me', text: "When did 'goodnight' start doing the work of the whole conversation?" },
          { from: 'them', text: '…honestly? Months ago. I just didn\'t want to say it out loud.' },
        ],
        essence: "The distance stopped hurting. That's the part that scares her.",
        goal: 'Find out if it is worth fighting for',
        tension: 'Sunk cost vs. drift',
      },
      {
        id: 'q4', person_id: 'p4', name: 'Ofir Ben-David', initials: 'OB',
        channel: 'whatsapp', handle: '+972 50-•••-9023',
        teaser: 'Booked · mild cold feet',
        action: 'Confirm the Thursday intake',
        confidence: 55,
        reason: 'booked; mild cold-feet signal',
        last_contacted: ago(1 * 86400), firstContactAgo: '6 days ago',
        thread: [
          { from: 'them', text: "We booked the intake, but I'm second-guessing whether we're 'bad enough' to need this." },
          { from: 'me', text: "Needing help early isn't a sign it's bad — it's a sign you're paying attention." },
          { from: 'them', text: "Okay. We'll keep the Thursday slot." },
        ],
        essence: "He's not unsure about the relationship. He's unsure he's allowed to ask for help.",
        goal: 'Show up to the first session',
        tension: 'Pride vs. need',
      },
      {
        id: 'q5', person_id: 'p5', name: 'Tamar Shaked', initials: 'TS',
        channel: 'whatsapp', handle: '+972 53-•••-7781',
        teaser: 'Cooled · door left open',
        action: 'Nudge gently in 2 days',
        confidence: 41,
        reason: 'cooled; left the door open',
        last_contacted: ago(2 * 86400), firstContactAgo: '3 weeks ago',
        thread: [
          { from: 'them', text: 'Thanks — I think we are okay for now.' },
          { from: 'me', text: "Understood. I'll leave the door open; reach out whenever the timing is right." },
          { from: 'them', text: 'Appreciate it.' },
        ],
        essence: 'She wants it to be fine. Saying it out loud is how she keeps it that way.',
        goal: 'Re-open the conversation later',
        tension: 'Avoidance vs. readiness',
      },
    ])
  : []
