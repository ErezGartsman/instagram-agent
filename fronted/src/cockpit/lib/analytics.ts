import { API_BASE } from './api'
import type { Stage } from './pipeline'

// The Analytics pillar: an Executive KPI strip (our own, from real CRM data)
// over a single framed, segmented Power BI embed. The dense social + report
// richness lives inside Power BI; the calm at-a-glance numbers are ours.

/**
 * Fetch the cockpit Power BI embed URL. Returns null when Power BI isn't
 * configured (HTTP 503) so the surface can degrade to a calm "connect" state
 * rather than erroring. Throws only on unexpected failures.
 */
export async function fetchPowerBiEmbed(token: string, signal?: AbortSignal): Promise<string | null> {
  const res = await fetch(`${API_BASE}/api/cockpit/powerbi`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (res.status === 503) return null
  if (!res.ok) throw new Error(`powerbi ${res.status}`)
  const data = (await res.json()) as { embed_url?: string }
  return data.embed_url ?? null
}

export type ReportView = { key: string; label: string; pageName: string }

// The segmented report selector. `pageName` deep-links a Power BI report page
// (its section ObjectId) — set these to your report's page names to make each
// segment jump to its view; empty = the report's default page. Find the IDs via
// the Power BI REST API: GET /reports/{reportId}/pages.
export const REPORT_VIEWS: ReportView[] = [
  { key: 'pipeline', label: 'Pipeline', pageName: '' },
  { key: 'community', label: 'Community', pageName: '' },
  { key: 'bookings', label: 'Bookings', pageName: '' },
]

/** Append a Power BI page deep-link to the embed URL when one is configured. */
export function embedUrlForView(embedUrl: string, view: ReportView): string {
  return view.pageName ? `${embedUrl}&pageName=${encodeURIComponent(view.pageName)}` : embedUrl
}

export type Kpi = { label: string; value: string; note?: string }

/**
 * Executive KPIs derived from the live pipeline board — real counts only, no
 * invented rates. (The 75k IG/TikTok community analytics live inside the Power
 * BI report, not here, since we don't track them server-side yet.)
 */
export function deriveKpis(stages: Stage[]): Kpi[] {
  const count = (s: string) => stages.find((x) => x.stage === s)?.count ?? 0
  const total = stages.reduce((n, s) => n + s.count, 0)
  const booked = count('booked')
  const qualifiedPlus = count('qualified') + count('captured') + count('briefed') + booked
  return [
    { label: 'Open opportunities', value: String(total), note: 'across all stages' },
    { label: 'Engaged', value: String(count('engaged')), note: 'top of funnel' },
    { label: 'Qualified+', value: String(qualifiedPlus), note: 'qualified → booked' },
    { label: 'Booked', value: String(booked), note: 'north-star metric' },
  ]
}
