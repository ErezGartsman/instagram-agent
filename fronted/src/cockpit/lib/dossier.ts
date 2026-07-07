import { API_BASE } from './api'

// The proactive layer's data spine (Phase 3): the Morning Briefing diff and
// the Person Dossier narrative. Both are deterministic backend payloads —
// nexus/dossier.py shapes them from data the spine already records; no LLM
// call happens per view. The scoped dossier chat reuses the existing
// /api/cockpit/ai/chat planner seam with a person chip.

// ── Morning briefing ───────────────────────────────────────────────────────────

export type BriefingTone = 'signal' | 'warn' | 'danger'

export type BriefingItem = {
  id: string
  tone: BriefingTone
  headline: string
  detail: string
  href: string
  cta: string
}

export type BriefingData = {
  compiled_at: string
  items: BriefingItem[]
}

export async function fetchBriefing(token: string, signal?: AbortSignal): Promise<BriefingData> {
  const res = await fetch(`${API_BASE}/api/cockpit/briefing`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`briefing ${res.status}`)
  const data = await res.json() as { status?: string; compiled_at?: string; items?: BriefingItem[] }
  if (data.status !== 'success' || !Array.isArray(data.items)) {
    throw new Error('briefing returned error payload')
  }
  return { compiled_at: data.compiled_at ?? '', items: data.items }
}

// ── Person dossier ─────────────────────────────────────────────────────────────

export type DossierPerson = {
  id: string
  name: string
  initials: string
  channel: string | null
  handle: string | null
  stage: string | null
  held_since: string | null
  /** The lead essence — person_profile.summary, the one Fraunces line. */
  essence: string | null
  goal: string | null
  tension: string | null
  /** Held facts + formed session summaries — "items in living memory". */
  memory_count: number
}

export type DossierChapter = {
  id: string
  range: string
  title: string
  summary: string
  signals: string[]
  at: string | null
}

export type TrajectoryPoint = { label: string; value: number; at: string | null }

export type DossierTimelineEvent = { kind: string; label: string; at: string | null }

export type DossierData = {
  person: DossierPerson
  chapters: DossierChapter[]
  trajectory: TrajectoryPoint[]
  timeline: DossierTimelineEvent[]
}

/** Thrown for a clean "no dossier formed yet / unknown person" state. */
export class DossierNotFound extends Error {}

export async function fetchDossier(
  token: string,
  personId: string,
  signal?: AbortSignal,
): Promise<DossierData> {
  const res = await fetch(`${API_BASE}/api/cockpit/person/${encodeURIComponent(personId)}/dossier`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`dossier ${res.status}`)
  const data = await res.json() as { status?: string; detail?: string } & Partial<DossierData>
  if (data.status !== 'success' || !data.person) {
    if ((data.detail ?? '').includes('not found')) throw new DossierNotFound()
    throw new Error('dossier returned error payload')
  }
  return {
    person: data.person,
    chapters: data.chapters ?? [],
    trajectory: data.trajectory ?? [],
    timeline: data.timeline ?? [],
  }
}

// ── Scoped chat — the existing planner seam, scoped by a person chip ───────────

export type ScopedChatTurn = { role: 'user' | 'ai'; text: string }

export async function askScopedMemory(
  token: string,
  personName: string,
  message: string,
  history: ScopedChatTurn[],
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/cockpit/ai/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      message,
      chips: [`Person: ${personName}`],
      history: history.slice(-6).map((m) => ({
        role: m.role === 'ai' ? 'assistant' : 'user',
        content: m.text,
      })),
    }),
    signal: AbortSignal.timeout(35_000),
  })
  if (!res.ok) throw new Error(`chat ${res.status}`)
  const data = await res.json() as { reply?: string }
  if (!data.reply) throw new Error('chat returned no reply')
  return data.reply
}

/** 'Jun 8' from an ISO date — the dossier's quiet date voice. */
export function fmtDay(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.toLocaleDateString('en-US', { month: 'short' })} ${d.getDate()}`
}
