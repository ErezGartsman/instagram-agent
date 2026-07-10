import { useCallback, useEffect } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../lib/queryClient'
import { Icon } from '../components/Icon'
import { MorningBriefing } from '../components/MorningBriefing'
import { SurfaceLoading, SurfaceError } from '../components/SurfaceStates'
import { useAuth } from '../auth/AuthProvider'
import { setNavSignals } from '../lib/navSignals'
import { fetchPipeline, SAMPLE_PIPELINE, STAGE_LABELS, type Stage } from '../lib/pipeline'
import {
  compact, deriveKpis, fetchAnalytics, fetchSla, fmtHours,
  SAMPLE_ANALYTICS,
  type AnalyticsData, type Kpi, type SlaData, type SlaLead,
} from '../lib/analytics'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from '../lib/workqueue'

/**
 * Command — the unified dense dashboard (rebuilt 2026-07-06, Erez's directive).
 *
 * One screen = the whole business. The accountability list ("Your move") owns
 * the spotlight; an ultra-dense KPI bento surrounds it. ONE data cycle feeds
 * every widget (Promise.allSettled over pipeline + queue + SLA + analytics),
 * so the numbers on this screen can never disagree with each other — and the
 * same cycle publishes { yourMove, breach } to the Sidebar badge via navSignals.
 *
 * SLA and analytics are optional citizens: if either endpoint fails, its
 * widgets step aside instead of taking the page down.
 */

function greeting(displayName: string): string {
  const h = new Date().getHours()
  const salutation = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
  const first = displayName.split(' ')[0]
  return first ? `${salutation}, ${first}` : salutation
}

const DATELINE = new Date().toLocaleDateString(undefined, {
  weekday: 'long',
  month: 'long',
  day: 'numeric',
})

// Dev-bypass sample SLA — mirrors SAMPLE_QUEUE people. DEV-only, dead-code-
// eliminated from production builds.
const SAMPLE_SLA: SlaData = import.meta.env.DEV
  ? {
      leads: [
        { opportunity_id: 'q1', person_id: 'p1', person_name: 'Maya Goren', stage: 'captured', stage_entered_at: null, hours_in_stage: 30, target_hours: 24, warn_hours: 18, sla_status: 'breach', hours_since_touch: 26, waiting_on: 'operator' },
        { opportunity_id: 'q2', person_id: 'p2', person_name: 'Daniel Roth', stage: 'qualified', stage_entered_at: null, hours_in_stage: 20, target_hours: 24, warn_hours: 18, sla_status: 'warn', hours_since_touch: 19, waiting_on: 'operator' },
        { opportunity_id: 'q5', person_id: 'p5', person_name: 'Tamar Shaked', stage: 'engaged', stage_entered_at: null, hours_in_stage: 9, target_hours: 48, warn_hours: 36, sla_status: 'ok', hours_since_touch: 6, waiting_on: 'operator' },
        { opportunity_id: 'q3', person_id: 'p3', person_name: 'Noa Levi', stage: 'engaged', stage_entered_at: null, hours_in_stage: 3, target_hours: 48, warn_hours: 36, sla_status: 'ok', hours_since_touch: 3, waiting_on: 'untouched' },
        { opportunity_id: 'q4', person_id: 'p4', person_name: 'Ofir Ben-David', stage: 'booked', stage_entered_at: null, hours_in_stage: 24, target_hours: 72, warn_hours: 48, sla_status: 'ok', hours_since_touch: 12, waiting_on: 'lead' },
      ],
      summary: { breach: 1, warn: 1, ok: 3, unknown: 0, total: 5 },
    }
  : { leads: [], summary: { breach: 0, warn: 0, ok: 0, unknown: 0, total: 0 } }

type Ready = {
  kind: 'ready'
  kpis: Kpi[]
  stages: Stage[]
  top: QueueItem | null
  pending: number
  sla: SlaData | null
  analytics: AnalyticsData | null
  sample: boolean
}
type State = { kind: 'loading' } | { kind: 'error' } | Ready

export function OverviewPage() {
  const { session, devBypass, displayName } = useAuth()
  const queryClient = useQueryClient()

  // ── The single data cycle — every widget drinks from this one well ────────
  const runCycle = useCallback(async (signal?: AbortSignal): Promise<Ready> => {
    if (devBypass) {
      const ranked = rankQueue(SAMPLE_QUEUE)
      return {
        kind: 'ready',
        kpis: deriveKpis(SAMPLE_PIPELINE),
        stages: SAMPLE_PIPELINE,
        top: ranked[0] ?? null,
        pending: ranked.length,
        sla: SAMPLE_SLA,
        analytics: SAMPLE_ANALYTICS,
        sample: true,
      }
    }
    const token = session?.access_token
    if (!token) throw new Error('no token')
    const [pipelineR, queueR, slaR, analyticsR] = await Promise.allSettled([
      fetchPipeline(token, signal),
      fetchQueue(token, signal),
      fetchSla(token, signal),
      fetchAnalytics(token, signal),
    ])
    // Pipeline + queue are the page's spine; SLA/analytics degrade gracefully.
    if (pipelineR.status === 'rejected' || queueR.status === 'rejected') {
      throw pipelineR.status === 'rejected' ? pipelineR.reason : (queueR as PromiseRejectedResult).reason
    }
    const ranked = rankQueue(queueR.value)
    // fetchSla casts without validating — the backend can return an error JSON
    // or a partial payload with no `summary`/`leads`. Sanitize at the single
    // entry point so no widget ever dereferences undefined.
    const rawSla = slaR.status === 'fulfilled' ? slaR.value : null
    const sla: SlaData | null =
      rawSla && Array.isArray(rawSla.leads)
        ? {
            leads: rawSla.leads,
            summary: rawSla.summary ?? { breach: 0, warn: 0, ok: 0, unknown: 0, total: rawSla.leads.length },
          }
        : null
    return {
      kind: 'ready',
      kpis: deriveKpis(pipelineR.value),
      stages: pipelineR.value,
      top: ranked[0] ?? null,
      pending: ranked.length,
      sla,
      analytics: analyticsR.status === 'fulfilled' ? analyticsR.value : null,
      sample: false,
    }
  }, [devBypass, session?.access_token])

  // The one data cycle on the TanStack spine (E1 §A2): 30s interval + focus
  // refetch come from the query layer; error state only when there is no data
  // to keep on screen (background failures silently keep the last snapshot —
  // same posture as before, minus 50 lines of hand-rolled machinery).
  const query = useQuery({
    queryKey: queryKeys.overview,
    queryFn: ({ signal }) => runCycle(signal),
    enabled: devBypass || !!session?.access_token,
    refetchInterval: 30_000,
  })
  const state: State = query.data
    ? query.data
    : query.isError && !query.isFetching
      ? { kind: 'error' }
      : { kind: 'loading' }
  const retry = () => void query.refetch()

  // Publish accountability counts to the Sidebar badge on every ready state.
  useEffect(() => {
    if (state.kind !== 'ready' || !state.sla) return
    setNavSignals({
      yourMove: (state.sla.leads ?? []).filter((l) => l?.waiting_on === 'operator').length,
      breach: state.sla.summary?.breach ?? 0,
    })
  }, [state])

  // The Action Loop's SLA event → invalidate this screen's cycle.
  useEffect(() => {
    const onSlaChanged = () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.overview })
    window.addEventListener('nexus:sla-changed', onSlaChanged)
    return () => window.removeEventListener('nexus:sla-changed', onSlaChanged)
  }, [queryClient])

  return (
    <div className="mx-auto max-w-[1360px]">
      <header className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          {/* font-serif (Fraunces) is permitted here + essence lines ONLY */}
          <h2 className="font-serif text-3xl font-light leading-tight text-ink">{greeting(displayName)}.</h2>
          <p className="mt-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">{DATELINE}</p>
        </div>
        {state.kind === 'ready' && state.sla?.summary && (
          <div className="flex items-center gap-2">
            {state.sample && (
              <span className="rounded-control border border-line px-2 py-1 font-mono text-[10px] text-warn">sample</span>
            )}
            <SummaryChip label="Breached" count={state.sla.summary.breach ?? 0} tone="danger" />
            <SummaryChip label="At risk" count={state.sla.summary.warn ?? 0} tone="warn" />
            <SummaryChip label="On track" count={state.sla.summary.ok ?? 0} tone="success" />
          </div>
        )}
      </header>

      {state.kind === 'loading' && <SurfaceLoading variant="grid" />}
      {state.kind === 'error' && (
        <SurfaceError
          title="Couldn't load the command screen"
          body="The pulse couldn't be reached. Check your connection and try again."
          onRetry={retry}
        />
      )}

      {/* The proactive layer: speaks first, before the operator asks anything.
          Live on GET /api/cockpit/briefing; renders nothing on a quiet night. */}
      {state.kind === 'ready' && <MorningBriefing />}

      {state.kind === 'ready' && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          {/* ── The spotlight: accountability ─────────────────────────────── */}
          <div className="flex flex-col gap-4 xl:col-span-7">
            <YourMovePanel sla={state.sla} />
            {state.top && <NextMove top={state.top} pending={state.pending} />}
          </div>

          {/* ── The bento: the whole state of the business ─────────────────── */}
          <div className="grid grid-cols-2 content-start gap-4 xl:col-span-5">
            {state.kpis.map((k) => (
              <KpiTile key={k.label} kpi={k} signature={k.label === 'Booked'} />
            ))}
            {state.analytics && <CommunityTile data={state.analytics} />}
            <FunnelTile stages={state.stages} />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Summary chip ───────────────────────────────────────────────────────────────
const CHIP_TONES = {
  danger: 'border-danger/30 text-danger',
  warn: 'border-warn/30 text-warn',
  success: 'border-success/30 text-success',
} as const

function SummaryChip({ label, count, tone }: { label: string; count: number; tone: keyof typeof CHIP_TONES }) {
  return (
    <span className={`flex items-baseline gap-1.5 rounded-control border px-2.5 py-1 ${CHIP_TONES[tone]}`}>
      <span className="font-mono text-sm tabular-nums leading-none">{count}</span>
      <span className="font-mono text-[9px] uppercase tracking-wider opacity-70">{label}</span>
    </span>
  )
}

// ── Your move — the product's first answer ─────────────────────────────────────
function YourMovePanel({ sla }: { sla: SlaData | null }) {
  const navigate = useNavigate()
  if (!sla) {
    return (
      <section className="rounded-card border border-line bg-surface p-5 backdrop-blur-xl [box-shadow:var(--shadow-card)]">
        <PanelLabel>Your move</PanelLabel>
        <p className="mt-3 text-sm text-muted">Accountability data is unavailable right now.</p>
      </section>
    )
  }

  const rank: Record<string, number> = { breach: 0, warn: 1, ok: 2, unknown: 3 }
  const yours = (sla.leads ?? [])
    .filter((l) => l && (l.waiting_on === 'operator' || l.waiting_on === 'untouched'))
    .sort((a, b) =>
      rank[a.sla_status] - rank[b.sla_status] ||
      (b.hours_since_touch ?? 0) - (a.hours_since_touch ?? 0),
    )
    .slice(0, 8)

  return (
    <section
      aria-label="Your move"
      className="overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <PanelLabel>Your move</PanelLabel>
        <span className="font-mono text-[10px] tabular-nums text-faint">
          {yours.length === 0 ? 'no one waiting' : `${yours.length} waiting on you`}
        </span>
      </div>

      {yours.length === 0 ? (
        <div className="flex items-center gap-2.5 px-5 py-6">
          <Icon name="check" size={15} className="text-success" />
          <p className="text-sm text-muted">No one is waiting on you. The clock is theirs.</p>
        </div>
      ) : (
        <ul>
          {yours.map((l) => (
            <AccountabilityRow
              key={l.opportunity_id}
              lead={l}
              onOpen={() => navigate(`/app/queue?focus=${l.opportunity_id}`)}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function AccountabilityRow({ lead, onOpen }: { lead: SlaLead; onOpen: () => void }) {
  const isBreach = lead.sla_status === 'breach'
  const isWarn = lead.sla_status === 'warn'
  const clockCls = isBreach ? 'text-danger' : isWarn ? 'text-warn' : 'text-ink'
  const barColor = isBreach ? 'var(--color-danger)' : isWarn ? 'var(--color-warn)' : 'var(--color-success)'
  const pct = lead.target_hours
    ? Math.min(((lead.hours_since_touch ?? 0) / lead.target_hours) * 100, 100)
    : 0
  const initials = lead.person_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <li
      className="group relative flex cursor-pointer items-center gap-3 border-b border-line/50 px-5 py-2.5 transition-colors last:border-0 hover:bg-raised"
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') onOpen() }}
    >
      {isBreach && (
        <span
          aria-hidden
          className="cq-sla-pulse absolute left-0 top-1/2 h-7 w-0.5 -translate-y-1/2 rounded-full bg-danger [box-shadow:0_0_8px_rgba(224,112,92,0.8)]"
        />
      )}
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/12 font-mono text-[11px] font-medium text-glow">
        {initials}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{lead.person_name}</span>
          {lead.waiting_on === 'untouched' && (
            <span className="shrink-0 rounded-full bg-accent/15 px-1.5 py-px font-mono text-[8px] uppercase tracking-wider text-accent">
              New
            </span>
          )}
        </span>
        <span className="mt-0.5 block font-mono text-[10px] text-faint">
          in {STAGE_LABELS[lead.stage] ?? lead.stage} · {fmtHours(lead.hours_in_stage)}
        </span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1">
        <span className={`font-mono text-sm tabular-nums leading-none ${clockCls}`}>
          {fmtHours(lead.hours_since_touch)}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-[3px] w-14 overflow-hidden rounded-full bg-raised">
            <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: barColor }} />
          </span>
          <span className="font-mono text-[9px] tabular-nums text-faint">
            {lead.target_hours !== null ? `${lead.target_hours}h` : '—'}
          </span>
        </span>
      </span>
      <Icon
        name="arrowRight"
        size={13}
        className="shrink-0 text-faint opacity-0 transition-opacity group-hover:opacity-100"
      />
    </li>
  )
}

// ── Next move — the engine's recommendation, with the human voice ─────────────
function NextMove({ top, pending }: { top: QueueItem; pending: number }) {
  return (
    <Link
      to="/app/queue"
      className="group block rounded-card border border-line bg-surface p-5 backdrop-blur-xl transition-colors hover:bg-raised [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-accent/15 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-glow">
              Next
            </span>
            <span className="truncate text-sm font-medium text-ink">{top.name}</span>
          </div>
          <div className="mt-2 text-[15px] text-ink">{top.action}</div>
          {top.essence && (
            <p className="mt-2 border-l-2 border-accent/60 pl-3 font-serif text-[15px] font-light italic leading-snug text-muted">
              {top.essence}
            </p>
          )}
          <div className="mt-2 text-xs leading-relaxed text-muted">
            <span className="text-faint">Reason · </span>
            {top.reason}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2.5">
          <span className="font-mono text-sm tabular-nums text-glow [text-shadow:0_0_8px_rgba(96,165,250,0.7)]">
            {top.confidence}%
          </span>
          <span className="flex items-center gap-1 text-xs text-muted transition-colors group-hover:text-ink">
            Open the queue <Icon name="arrowRight" size={13} />
          </span>
        </div>
      </div>
      <div className="mt-3 font-mono text-[10px] text-faint">
        {pending} {pending === 1 ? 'person' : 'people'} in the queue
      </div>
    </Link>
  )
}

// ── Bento tiles ────────────────────────────────────────────────────────────────
function PanelLabel({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{children}</span>
}

function KpiTile({ kpi, signature = false }: { kpi: Kpi; signature?: boolean }) {
  const inner = (
    <>
      <PanelLabel>{kpi.label}</PanelLabel>
      <div
        className={`mt-2 font-mono text-[28px] font-light leading-none tabular-nums ${
          signature ? 'text-accent' : 'text-ink'
        }`}
      >
        {kpi.value}
      </div>
      {kpi.note && <div className="mt-1.5 font-mono text-[9px] text-faint">{kpi.note}</div>}
    </>
  )
  const cls = `block rounded-card border bg-surface p-4 backdrop-blur-xl transition-colors hover:bg-raised [box-shadow:var(--shadow-card)] ${
    signature ? 'border-accent/30' : 'border-line'
  }`
  return kpi.href ? (
    <Link to={kpi.href} className={cls}>
      {inner}
    </Link>
  ) : (
    <div className={cls}>{inner}</div>
  )
}

function CommunityTile({ data }: { data: AnalyticsData }) {
  const { community } = data
  const lastTwo = community.growth.slice(-2)
  const delta = lastTwo.length >= 2 ? lastTwo[1].followers - lastTwo[0].followers : null
  return (
    <div className="col-span-2 rounded-card border border-line bg-surface p-4 backdrop-blur-xl [box-shadow:var(--shadow-card)]">
      <div className="flex items-start justify-between">
        <PanelLabel>Community</PanelLabel>
        {delta !== null && (
          <span
            className={`rounded-full px-2 py-0.5 font-mono text-[9px] tabular-nums ${
              delta >= 0 ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'
            }`}
          >
            {delta >= 0 ? '+' : ''}{compact(Math.abs(delta))} this week
          </span>
        )}
      </div>
      <div className="mt-1.5 flex items-end justify-between gap-4">
        <span className="font-mono text-[28px] font-light leading-none tabular-nums text-ink">
          {compact(community.size)}
        </span>
        <Spark points={community.growth.map((g) => g.followers)} className="h-9 w-40" />
      </div>
      <div className="mt-2.5 flex items-center gap-3 font-mono text-[9px] tabular-nums text-faint">
        <span>{compact(community.likes)} likes</span>
        <span>·</span>
        <span>{compact(community.comments)} comments</span>
        <span>·</span>
        <span>{compact(community.posts)} posts</span>
      </div>
    </div>
  )
}

function FunnelTile({ stages }: { stages: Stage[] }) {
  const max = Math.max(...stages.map((s) => s.count), 1)
  const navigate = useNavigate()
  return (
    <div className="col-span-2 rounded-card border border-line bg-surface p-4 backdrop-blur-xl [box-shadow:var(--shadow-card)]">
      <PanelLabel>Pipeline</PanelLabel>
      <div className="mt-3 flex flex-col gap-1.5">
        {stages.map((s) => (
          <div
            key={s.stage}
            className="flex cursor-pointer items-center gap-2.5 rounded-control px-1 py-0.5 transition-colors hover:bg-raised"
            onClick={() => navigate(`/app/queue?stage=${s.stage}`)}
          >
            <span className="w-16 shrink-0 font-mono text-[10px] text-muted">
              {STAGE_LABELS[s.stage] ?? s.stage}
            </span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
              <span
                className="block h-full rounded-full transition-[width] duration-700"
                style={{
                  width: `${(s.count / max) * 100}%`,
                  background: s.stage === 'booked' ? 'var(--color-accent)' : 'var(--color-sage)',
                  opacity: s.stage === 'booked' ? 1 : 0.75,
                }}
              />
            </span>
            <span className="w-6 shrink-0 text-right font-mono text-[11px] tabular-nums text-ink">{s.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Inline SVG sparkline — no chart library ships on the index route. */
function Spark({ points, className = '' }: { points: number[]; className?: string }) {
  if (points.length < 2) return null
  const min = Math.min(...points)
  const max = Math.max(...points)
  const coords = points.map((p, i) => [
    (i / (points.length - 1)) * 100,
    max === min ? 50 : 94 - ((p - min) / (max - min)) * 86,
  ])
  const d = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className={className} aria-hidden>
      <path d={`${d} L100,100 L0,100 Z`} fill="rgba(59,130,246,0.10)" />
      <path d={d} fill="none" stroke="#60a5fa" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
