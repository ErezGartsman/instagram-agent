import { API_BASE } from './api'
import type { Stage } from './pipeline'

// The Analytics pillar — a NATIVE Bento dashboard (no Power BI embed). The data
// lives in our own Supabase (social + CRM); the frontend draws every card and
// chart by hand in the Graphite Atelier language.

export type GrowthPoint = { week: string; followers: number }
export type TopPost = { shortcode: string; likes: number; comments: number; caption?: string | null }
export type PipelineStage = { stage: string; count: number }

export type AnalyticsData = {
  community: {
    /** Operator-maintained real follower total (IG + TikTok); the others are live SQL. */
    size: number
    followers_tracked: number
    likes: number
    comments: number
    posts: number
    growth: GrowthPoint[]
    top_posts: TopPost[]
  }
  pipeline: PipelineStage[]
  booked: number
}

export async function fetchAnalytics(token: string, signal?: AbortSignal): Promise<AnalyticsData> {
  const res = await fetch(`${API_BASE}/api/cockpit/analytics`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`analytics ${res.status}`)
  return (await res.json()) as AnalyticsData
}

/** Compact number for KPI tiles: 709 · 11k · 75.2k · 268k. */
export function compact(n: number): string {
  if (n < 1000) return String(n)
  const v = n / 1000
  const d = v >= 100 || Number.isInteger(v) ? 0 : 1
  return `${v.toFixed(d)}k`
}

export type Kpi = { label: string; value: string; note?: string; href?: string }

/**
 * Executive KPIs derived from the live pipeline board — real counts only (used
 * by the Overview pulse). No invented rates.
 */
export function deriveKpis(stages: Stage[]): Kpi[] {
  const count = (s: string) => stages.find((x) => x.stage === s)?.count ?? 0
  const total = stages.reduce((n, s) => n + s.count, 0)
  const booked = count('booked')
  const qualifiedPlus = count('qualified') + count('captured') + count('briefed') + booked
  return [
    { label: 'Open opportunities', value: String(total), note: 'across all stages', href: '/app/queue' },
    { label: 'Engaged', value: String(count('engaged')), note: 'top of funnel', href: '/app/pipeline' },
    { label: 'Qualified+', value: String(qualifiedPlus), note: 'qualified → booked', href: '/app/pipeline' },
    { label: 'Booked', value: String(booked), note: 'north-star metric', href: '/app/pipeline' },
  ]
}

// ── Funnel analytics ──────────────────────────────────────────────────────────

export type FunnelPair = {
  from_stage: string
  to_stage: string
  transition_count: number
  unique_leads: number
  total_entered_from_stage: number
  conversion_pct: number | null
  avg_hours_in_stage: number | null
  median_hours_in_stage: number | null
  last_transition_at: string | null
}

export type FunnelStage = {
  stage: string
  ever_entered: number
  open_now: number
}

export type FunnelData = {
  pairs: FunnelPair[]
  stages: FunnelStage[]
}

export type SlaStatus = 'ok' | 'warn' | 'breach' | 'unknown'

export type SlaLead = {
  opportunity_id: string
  person_id: string
  person_name: string
  stage: string
  stage_entered_at: string | null
  hours_in_stage: number | null
  target_hours: number | null
  warn_hours: number | null
  sla_status: SlaStatus
}

export type SlaData = {
  leads: SlaLead[]
  summary: { breach: number; warn: number; ok: number; unknown: number; total: number }
}

export async function fetchFunnel(
  token: string,
  days: number | null,
  signal?: AbortSignal,
): Promise<FunnelData> {
  const url = days
    ? `${API_BASE}/api/cockpit/analytics/funnel?days=${days}`
    : `${API_BASE}/api/cockpit/analytics/funnel`
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, signal })
  if (!res.ok) throw new Error(`funnel ${res.status}`)
  return (await res.json()) as FunnelData
}

export async function fetchSla(token: string, signal?: AbortSignal): Promise<SlaData> {
  const res = await fetch(`${API_BASE}/api/cockpit/analytics/sla`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`sla ${res.status}`)
  return (await res.json()) as SlaData
}

/** Format hours into a readable string: 2h, 1d 6h, 3d */
export function fmtHours(h: number | null): string {
  if (h === null) return '—'
  if (h < 1) return '<1h'
  if (h < 24) return `${Math.round(h)}h`
  const d = Math.floor(h / 24)
  const rem = Math.round(h % 24)
  return rem > 0 ? `${d}d ${rem}h` : `${d}d`
}

// ── Dev-bypass sample so the Bento is populated during local UI work. Guarded by
// import.meta.env.DEV → dead-code-eliminated from production builds.
const sampleGrowth: GrowthPoint[] = import.meta.env.DEV
  ? [62, 65, 64, 70, 72, 78, 80, 88, 92, 101, 108, 120].map((followers, i) => ({
      week: `2026-${String(4 + Math.floor(i / 4)).padStart(2, '0')}-${String((i % 4) * 7 + 1).padStart(2, '0')}`,
      followers: followers * 600,
    }))
  : []

export const SAMPLE_ANALYTICS: AnalyticsData = {
  community: {
    size: 75200,
    followers_tracked: 20000,
    likes: 268000,
    comments: 11000,
    posts: 709,
    growth: sampleGrowth,
    top_posts: [
      { shortcode: 'C8aXk2Lp', likes: 4120, comments: 318 },
      { shortcode: 'C7mQ9rTe', likes: 3340, comments: 271 },
      { shortcode: 'C6vB1nWq', likes: 2890, comments: 204 },
      { shortcode: 'C5pL7yHd', likes: 2410, comments: 188 },
      { shortcode: 'C4kR3zSx', likes: 1980, comments: 142 },
    ],
  },
  pipeline: [
    { stage: 'engaged', count: 3 },
    { stage: 'qualified', count: 2 },
    { stage: 'captured', count: 1 },
    { stage: 'briefed', count: 1 },
    { stage: 'booked', count: 1 },
  ],
  booked: 3,
}
