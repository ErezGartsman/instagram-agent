import { API_BASE } from './api'

export type Lead = {
  id: string
  person_id: string
  name: string
  wa_ref: string | null
  channel: string | null
  intent: string | null
  last_contacted: string | null
  stage_entered_at: string | null
}

export type Stage = { stage: string; count: number; leads: Lead[] }

export const STAGE_LABELS: Record<string, string> = {
  engaged: 'Engaged',
  qualified: 'Qualified',
  captured: 'Captured',
  briefed: 'Briefed',
  booked: 'Booked',
}

export const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: 'WhatsApp',
  instagram: 'Instagram',
  telegram: 'Telegram',
  phone: 'Phone',
  web: 'Web',
}

export async function fetchPipeline(token: string, signal?: AbortSignal): Promise<Stage[]> {
  const res = await fetch(`${API_BASE}/api/cockpit/pipeline`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`pipeline ${res.status}`)
  const data = (await res.json()) as { stages?: Stage[] }
  return data.stages ?? []
}

/** Compact relative time for "last contacted" (e.g. "now", "2h", "3d", "1w"). */
export function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 60) return 'now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h`
  const days = Math.round(hrs / 24)
  if (days < 7) return `${days}d`
  return `${Math.round(days / 7)}w`
}

// Dev-bypass sample so the board is populated during local UI work. The
// `import.meta.env.DEV` guard makes this an empty array in a production build
// (the literal is dead-code-eliminated), so no sample data ever ships.
function ago(secs: number): string {
  return new Date(Date.now() - secs * 1000).toISOString()
}

export const SAMPLE_PIPELINE: Stage[] = import.meta.env.DEV
  ? [
      {
        stage: 'engaged',
        count: 3,
        leads: [
          { id: 's1', person_id: 'p1', name: 'Dana K.', wa_ref: 'BR-7F2A', channel: 'whatsapp',
            intent: 'Reaching out about couples therapy; feeling stuck after a rough few months.',
            last_contacted: ago(2 * 3600), stage_entered_at: ago(2 * 3600) },
          { id: 's2', person_id: 'p2', name: 'Lead BR-91C2', wa_ref: 'BR-91C2', channel: 'instagram',
            intent: 'Asked what the process looks like and whether sessions are remote.',
            last_contacted: ago(5 * 3600), stage_entered_at: ago(5 * 3600) },
          { id: 's3', person_id: 'p3', name: 'Noa L.', wa_ref: 'BR-22A0', channel: 'telegram',
            intent: 'Curious but hesitant; mentioned a previous bad experience with therapy.',
            last_contacted: ago(26 * 3600), stage_entered_at: ago(26 * 3600) },
        ],
      },
      {
        stage: 'qualified',
        count: 2,
        leads: [
          { id: 's4', person_id: 'p4', name: 'Yossi M.', wa_ref: 'BR-3D8E', channel: 'whatsapp',
            intent: 'Ready to start; wants to understand pricing and the therapist match.',
            last_contacted: ago(1 * 3600), stage_entered_at: ago(3 * 3600) },
          { id: 's5', person_id: 'p5', name: 'Tamar B.', wa_ref: 'BR-77F1', channel: 'whatsapp',
            intent: 'Individual anxiety support; flexible on timing, prefers evenings.',
            last_contacted: ago(9 * 3600), stage_entered_at: ago(9 * 3600) },
        ],
      },
      {
        stage: 'captured',
        count: 1,
        leads: [
          { id: 's6', person_id: 'p6', name: 'Avi S.', wa_ref: 'BR-5C13', channel: 'whatsapp',
            intent: 'Shared phone and context; waiting on a consultation slot.',
            last_contacted: ago(30 * 3600), stage_entered_at: ago(30 * 3600) },
        ],
      },
      {
        stage: 'briefed',
        count: 1,
        leads: [
          { id: 's7', person_id: 'p7', name: 'Maya R.', wa_ref: 'BR-0F44', channel: 'whatsapp',
            intent: 'Fully briefed on the process; deciding between two time options.',
            last_contacted: ago(2 * 86400), stage_entered_at: ago(2 * 86400) },
        ],
      },
      {
        stage: 'booked',
        count: 1,
        leads: [
          { id: 's8', person_id: 'p8', name: 'Gal P.', wa_ref: 'BR-9E20', channel: 'whatsapp',
            intent: 'Consultation booked for Thursday — first couples session.',
            last_contacted: ago(4 * 3600), stage_entered_at: ago(4 * 3600) },
        ],
      },
    ]
  : []
