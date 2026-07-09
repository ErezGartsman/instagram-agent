import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ResponsiveContainer, AreaChart, Area, Tooltip, YAxis } from 'recharts'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError, SampleNotice } from '../components/SurfaceStates'
import { pushAiContext } from '../components/GlowingAiAssistant'
import { useAuth } from '../auth/AuthProvider'
import { queryKeys } from '../lib/queryClient'
import { STAGE_LABELS } from '../lib/pipeline'
import {
  compact, fmtHours,
  fetchAnalytics, fetchFunnel, fetchSla,
  SAMPLE_ANALYTICS,
  type AnalyticsData, type SlaData, type SlaStatus, type WaitingOn,
} from '../lib/analytics'

const ELECTRIC = '#60a5fa'
const TEAL     = '#2dd4bf'
const REDUCED = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const PIPELINE = ['engaged', 'qualified', 'captured', 'briefed', 'booked'] as const

type Tab  = 'overview' | 'funnel' | 'leads'
type Days = 7 | 30 | 90 | null   // null = all-time

// ── Date preset bar ───────────────────────────────────────────────────────────
function DatePresets({ days, onChange }: { days: Days; onChange: (d: Days) => void }) {
  const opts: { label: string; value: Days }[] = [
    { label: '7d',       value: 7  },
    { label: '30d',      value: 30 },
    { label: '90d',      value: 90 },
    { label: 'All time', value: null },
  ]
  return (
    <div className="flex items-center gap-1 rounded-control border border-line bg-bg/60 p-0.5">
      {opts.map(({ label, value }) => (
        <button
          key={label}
          type="button"
          onClick={() => onChange(value)}
          className={`rounded px-2.5 py-1 font-mono text-[10px] transition-colors ${
            days === value ? 'bg-accent/20 text-accent' : 'text-faint hover:text-muted'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export function AnalyticsPage() {
  const { session, devBypass } = useAuth()
  const [tab,  setTab]  = useState<Tab>('overview')
  const [days, setDays] = useState<Days>(30)
  const token = session?.access_token ?? null

  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Analytics" subtitle="Community reach, pipeline conversion, and SLA health." />

      {/* Tab bar + date presets */}
      <div className="mb-6 flex items-center justify-between border-b border-line">
        <div className="flex items-center gap-1">
          {(['overview', 'funnel', 'leads'] as Tab[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`px-4 py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors ${
                tab === t ? 'border-b-2 border-accent text-accent' : 'text-faint hover:text-muted'
              }`}
            >
              {t === 'overview' ? 'Overview' : t === 'funnel' ? 'Funnel' : 'Leads'}
            </button>
          ))}
        </div>
        {tab !== 'overview' && <DatePresets days={days} onChange={setDays} />}
      </div>

      {tab === 'overview' && <OverviewTab token={token} devBypass={devBypass} />}
      {tab === 'funnel'   && <FunnelTab   token={token} days={days} />}
      {tab === 'leads'    && <LeadsTab    token={token} />}
    </div>
  )
}

// ── Overview tab ──────────────────────────────────────────────────────────────
function OverviewTab({ token, devBypass }: { token: string | null; devBypass: boolean }) {
  const query = useQuery({
    queryKey: queryKeys.analytics,
    queryFn: ({ signal }) => fetchAnalytics(token!, signal),
    enabled: !!token && !devBypass,
  })

  if (devBypass) {
    return (
      <>
        <SampleNotice />
        <Bento data={SAMPLE_ANALYTICS} />
      </>
    )
  }
  if (query.data) return <Bento data={query.data} />
  if (query.isError && !query.isFetching) {
    return (
      <SurfaceError
        title="Couldn't load analytics"
        body="Check your connection and try again."
        onRetry={() => void query.refetch()}
      />
    )
  }
  return <SurfaceLoading variant="bento" />
}

// ── Funnel tab ─────────────────────────────────────────────────────────────────
function FunnelTab({ token, days }: { token: string | null; days: Days }) {
  const query = useQuery({
    queryKey: queryKeys.funnel(days ?? 0),  // 0 = all-time
    queryFn: ({ signal }) => fetchFunnel(token!, days, signal),
    enabled: !!token,
  })

  if (query.isError && !query.isFetching) {
    return (
      <SurfaceError
        title="Couldn't load funnel"
        body="Check your connection and try again."
        onRetry={() => void query.refetch()}
      />
    )
  }
  if (!query.data) return <SurfaceLoading variant="bento" />

  const stages = query.data.stages ?? []
  const pairs  = query.data.pairs  ?? []

  const pipelineStages = PIPELINE.map((stage) => {
    const s         = stages.find(x => x.stage === stage)
    const nextStage = PIPELINE[PIPELINE.indexOf(stage) + 1]
    // Use the adjacent-stage pair for the connector conversion label
    const pair      = nextStage ? pairs.find(p => p.from_stage === stage && p.to_stage === nextStage) : null
    // Use ANY pair from this stage for velocity (picks the first / highest-traffic one)
    const velPair   = pairs.find(p => p.from_stage === stage)
    return {
      stage,
      label:          STAGE_LABELS[stage] ?? stage,
      ever_entered:   s?.ever_entered ?? 0,
      open_now:       s?.open_now ?? 0,
      conversion_pct: pair?.conversion_pct ?? null,
      avg_hours:      velPair?.avg_hours_in_stage ?? null,
    }
  })

  const maxEntered = Math.max(...pipelineStages.map(s => s.ever_entered), 1)

  // ── SVG horizontal stream funnel ──────────────────────────────────────────
  const W = 1000, H = 190, CY = H / 2, MAX_H = H * 0.42

  const fPts = pipelineStages.map((s, i) => ({
    x: Math.round((i / (pipelineStages.length - 1)) * W),
    h: Math.max((s.ever_entered / maxEntered) * MAX_H, MAX_H * 0.055),
    s,
  }))

  // Build a smooth SVG stream path at a given vertical scale factor
  const buildStream = (scale: number): string => {
    const ph = fPts.map(p => ({ ...p, h: p.h * scale }))
    // Top edge — left to right
    const top = ph.reduce((acc, pt, i) => {
      if (i === 0) return `M${pt.x},${CY - pt.h}`
      const prev = ph[i - 1]
      const cpx  = (prev.x + pt.x) / 2
      return `${acc} C${cpx},${CY - prev.h} ${cpx},${CY - pt.h} ${pt.x},${CY - pt.h}`
    }, '')
    // Bottom edge — right to left
    const rev = [...ph].reverse()
    const bot = rev.reduce((acc, pt, i) => {
      if (i === 0) return `L${pt.x},${CY + pt.h}`
      const prev = rev[i - 1]
      const cpx  = (prev.x + pt.x) / 2
      return `${acc} C${cpx},${CY + prev.h} ${cpx},${CY + pt.h} ${pt.x},${CY + pt.h}`
    }, '')
    return `${top} ${bot}Z`
  }

  return (
    <div className="flex flex-col gap-6">
      {/* ── Horizontal stream funnel ─────────────────────────────────────────── */}
      <div className="rounded-card border border-line bg-surface p-5 [box-shadow:var(--shadow-card)]">
        <div className="mb-5 flex items-center">
          <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
            Pipeline funnel · all-time flow
          </span>
          <InsightBtn context="Pipeline funnel — conversion rates and drop-off between stages" />
        </div>

        {/* SVG stream */}
        <div className="relative w-full overflow-hidden rounded-control" style={{ height: H }}>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            width="100%"
            height={H}
            className="absolute inset-0"
          >
            <defs>
              <linearGradient id="sf-grad" x1="0%" x2="100%">
                <stop offset="0%"   stopColor="var(--color-accent)" stopOpacity="0.95" />
                <stop offset="100%" stopColor="var(--color-glow)"   stopOpacity="0.75" />
              </linearGradient>
            </defs>
            {/* Three layered paths — outer body + mid glow + inner core */}
            <path d={buildStream(1.00)} fill="url(#sf-grad)" opacity="0.88" />
            <path d={buildStream(0.68)} fill="url(#sf-grad)" opacity="0.42" />
            <path d={buildStream(0.36)} fill="url(#sf-grad)" opacity="0.22" />

            {/* Stage boundary vertical dividers */}
            {fPts.slice(1).map(pt => (
              <line key={pt.s.stage}
                x1={pt.x} y1={0} x2={pt.x} y2={H}
                stroke="rgba(255,255,255,0.10)" strokeWidth="1.5" />
            ))}

            {/* Count badges (dark pill at each stage control point) */}
            {fPts.map(pt => {
              const pct  = Math.round((pt.s.ever_entered / maxEntered) * 100)
              const bx   = Math.max(pt.x, 28)   // clamp so left badge is visible
              const bxR  = Math.min(bx, W - 28)
              return (
                <g key={pt.s.stage}>
                  <rect x={bxR - 26} y={CY - 14} width="52" height="28" rx="14"
                    fill="rgba(0,0,0,0.72)" />
                  <text x={bxR} y={CY - 1} textAnchor="middle"
                    fill="white" fontSize="13" fontFamily="monospace" fontWeight="700">
                    {pt.s.ever_entered}
                  </text>
                  <text x={bxR} y={CY + 12} textAnchor="middle"
                    fill="rgba(255,255,255,0.50)" fontSize="8" fontFamily="monospace">
                    {pct}%
                  </text>
                </g>
              )
            })}
          </svg>
        </div>

        {/* Stage labels row */}
        <div className="mt-3 flex">
          {pipelineStages.map((s, i) => {
            const convPct = s.conversion_pct
            const convCls = convPct === null ? 'text-faint'
              : convPct >= 60 ? 'text-success'
              : convPct >= 30 ? 'text-warn'
              : 'text-danger'
            return (
              <div key={s.stage} className="flex flex-1 flex-col items-center gap-0.5">
                <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-muted">
                  {s.label}
                </span>
                <span className="font-mono text-[9px] text-faint">
                  {s.open_now > 0 ? `${s.open_now} open` : ''}
                </span>
                {i < pipelineStages.length - 1 && (
                  <span className={`mt-0.5 font-mono text-[9px] tabular-nums ${convCls}`}>
                    {convPct !== null ? `${convPct}%→` : '—'}
                  </span>
                )}
              </div>
            )
          })}
        </div>
        <p className="mt-3 font-mono text-[9px] text-faint">
          Stream width = proportion of all-time leads · % = conversion to next stage
        </p>
      </div>

      {/* ── Velocity grid ─────────────────────────────────────────────────────── */}
      <div className="rounded-card border border-line bg-surface p-5 [box-shadow:var(--shadow-card)]">
        <div className="mb-4 flex items-center">
          <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
            Stage velocity · avg time before advancing
          </span>
          <InsightBtn context="Stage velocity — time leads spend in each pipeline stage before advancing" label="Analyse Velocity" />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {pipelineStages.map((s, i) => {
            const isEntry    = i === 0
            const isTerminal = i === pipelineStages.length - 1
            const hasData    = s.avg_hours !== null
            const ctx = hasData
              ? `${s.label} velocity: avg ${fmtHours(s.avg_hours)} before advancing`
              : `${s.label} stage — ${isEntry ? 'pipeline entry point' : 'no velocity data yet'}`
            return (
              <div
                key={s.stage}
                className="group relative cursor-pointer rounded-control border border-line bg-raised p-3 transition-colors hover:border-glow/25 hover:bg-raised"
                onClick={() => pushAiContext(ctx)}
                title="Click to ask AI about this stage"
              >
                <div className="flex items-start justify-between">
                  <div className="font-mono text-[9px] uppercase tracking-wider text-faint">{s.label}</div>
                  <span className="font-mono text-[7px] text-glow opacity-0 transition-opacity group-hover:opacity-100">
                    ✦
                  </span>
                </div>
                {isEntry ? (
                  <>
                    <div className="mt-1.5 font-mono text-sm text-faint">entry</div>
                    <div className="mt-0.5 font-mono text-[9px] text-faint">first contact</div>
                  </>
                ) : isTerminal && !hasData ? (
                  <>
                    <div className="mt-1.5 font-mono text-sm text-faint">—</div>
                    <div className="mt-0.5 font-mono text-[9px] text-faint">terminal stage</div>
                  </>
                ) : (
                  <>
                    <div className={`mt-1.5 font-mono text-lg tabular-nums ${hasData ? 'text-ink' : 'text-faint'}`}>
                      {fmtHours(s.avg_hours)}
                    </div>
                    <div className="mt-0.5 font-mono text-[9px] text-faint">avg to advance</div>
                  </>
                )}
              </div>
            )
          })}
        </div>
        {days !== null && (
          <p className="mt-3 font-mono text-[9px] text-faint">
            Velocity data only available on All time view
          </p>
        )}
      </div>

      {/* ── Transition detail table ──────────────────────────────────────────── */}
      {pairs.length > 0 && (
        <div className="rounded-card border border-line bg-surface p-5 [box-shadow:var(--shadow-card)]">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">All transitions</div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line text-left">
                  {['From', 'To', 'Leads', 'Conv %', 'Avg time', 'Median'].map(h => (
                    <th key={h} className="pb-2 pr-4 font-mono text-[9px] uppercase tracking-wider text-faint">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pairs.map((p, i) => (
                  <tr key={i} className="group border-b border-line/50 last:border-0 transition-colors hover:bg-raised/40">
                    <td className="py-2 pr-4 font-mono text-muted">{STAGE_LABELS[p.from_stage] ?? p.from_stage}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{STAGE_LABELS[p.to_stage]   ?? p.to_stage}</td>
                    <td className="py-2 pr-4 font-mono tabular-nums text-ink">{p.unique_leads}</td>
                    <td className={`py-2 pr-4 font-mono tabular-nums ${
                      p.conversion_pct === null ? 'text-faint' :
                      p.conversion_pct >= 60    ? 'text-success' :
                      p.conversion_pct >= 30    ? 'text-warn'    : 'text-danger'
                    }`}>{p.conversion_pct !== null ? `${p.conversion_pct}%` : '—'}</td>
                    <td className="py-2 pr-4 font-mono tabular-nums text-muted">{fmtHours(p.avg_hours_in_stage)}</td>
                    <td className="py-2 font-mono tabular-nums text-muted">
                      <div className="flex items-center gap-3">
                        <span>{fmtHours(p.median_hours_in_stage)}</span>
                        <button
                          type="button"
                          onClick={() => pushAiContext(
                            `${STAGE_LABELS[p.from_stage] ?? p.from_stage} → ${STAGE_LABELS[p.to_stage] ?? p.to_stage}: ${p.unique_leads} leads, ${p.conversion_pct ?? '—'}% conversion, avg ${fmtHours(p.avg_hours_in_stage)}`
                          )}
                          className="ml-auto opacity-0 transition-opacity group-hover:opacity-100 font-mono text-[9px] text-glow/70 hover:text-glow whitespace-nowrap"
                        >
                          Ask AI ✦
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Leads / SLA tab ───────────────────────────────────────────────────────────
const SLA_CHIP: Record<SlaStatus, { label: string; cls: string }> = {
  ok:      { label: 'On track', cls: 'text-success bg-success/10' },
  warn:    { label: 'At risk',  cls: 'text-warn bg-warn/10' },
  breach:  { label: 'Breached', cls: 'text-danger bg-danger/10' },
  unknown: { label: 'Unknown',  cls: 'text-faint bg-raised' },
}

// "Who does the system need action from" — the accountability read, separate
// from the SLA breach/warn/ok severity chip.
const MOVE_CHIP: Record<WaitingOn, { label: string; cls: string }> = {
  operator:  { label: 'Your move',  cls: 'text-glow bg-glow/10' },
  lead:      { label: 'Their move', cls: 'text-success bg-success/10' },
  untouched: { label: 'New',        cls: 'text-accent bg-accent/10' },
}

const SLA_REFETCH_DEBOUNCE_MS = 500

function LeadsTab({ token }: { token: string | null }) {
  const [search,  setSearch]  = useState('')
  const [filter,  setFilter]  = useState<SlaStatus | 'all'>('all')
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Four-state lifecycle on the spine: focus refetch comes from the query
  // layer; 'nexus:sla-changed' (fired by the AI panel after an outreach click
  // logs an interaction) invalidates so the table never needs a remount to
  // see the new accountable_since. Background failures keep the last data.
  const query = useQuery({
    queryKey: queryKeys.sla,
    queryFn: ({ signal }) => fetchSla(token!, signal),
    enabled: !!token,
  })
  useEffect(() => {
    let debounce: ReturnType<typeof setTimeout> | null = null
    const trigger = () => {
      if (debounce) clearTimeout(debounce)
      debounce = setTimeout(
        () => void queryClient.invalidateQueries({ queryKey: queryKeys.sla }),
        SLA_REFETCH_DEBOUNCE_MS,
      )
    }
    window.addEventListener('nexus:sla-changed', trigger)
    return () => {
      window.removeEventListener('nexus:sla-changed', trigger)
      if (debounce) clearTimeout(debounce)
    }
  }, [queryClient])

  const state: { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: SlaData } =
    query.data
      ? { kind: 'ready', data: query.data }
      : query.isError && !query.isFetching
        ? { kind: 'error' }
        : { kind: 'loading' }
  const retry = () => void query.refetch()

  const leads = query.data?.leads
  const visibleLeads = useMemo(() => {
    return (leads ?? []).filter(l => {
      const matchesFilter = filter === 'all' || l.sla_status === filter
      const matchesSearch = !search || l.person_name.toLowerCase().includes(search.toLowerCase())
      return matchesFilter && matchesSearch
    })
  }, [leads, filter, search])

  if (state.kind === 'loading') return <SurfaceLoading variant="bento" />
  if (state.kind === 'error')   return <SurfaceError title="Couldn't load SLA data" body="Check your connection and try again." onRetry={retry} />

  const { summary } = state.data

  return (
    <div className="flex flex-col gap-4">
      {/* Summary chips */}
      <div className="flex flex-wrap gap-3">
        {[
          { label: 'Breached', count: summary.breach, cls: 'border-danger/30 text-danger'  },
          { label: 'At risk',  count: summary.warn,   cls: 'border-warn/30 text-warn'      },
          { label: 'On track', count: summary.ok,     cls: 'border-success/30 text-success' },
          { label: 'Total',    count: summary.total,  cls: 'border-line text-muted'         },
        ].map(({ label, count, cls }) => (
          <div key={label} className={`rounded-card border px-4 py-2.5 ${cls}`}>
            <div className="font-mono text-2xl tabular-nums leading-none">{count}</div>
            <div className="mt-1 font-mono text-[9px] uppercase tracking-wider opacity-70">{label}</div>
          </div>
        ))}
      </div>

      {/* Search + filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-1 items-center gap-2 rounded-control border border-line bg-bg/60 px-3 py-2 focus-within:border-accent/40">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-faint" aria-hidden><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name…"
            className="flex-1 bg-transparent font-mono text-[11px] text-ink outline-none placeholder:text-faint"
          />
          {search && (
            <button type="button" onClick={() => setSearch('')} className="text-faint hover:text-muted">
              <Icon name="x" size={12} />
            </button>
          )}
        </div>

        <div className="flex items-center gap-1 rounded-control border border-line bg-bg/60 p-0.5">
          {(['all', 'breach', 'warn', 'ok'] as const).map(f => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded px-2.5 py-1 font-mono text-[10px] transition-colors ${
                filter === f
                  ? f === 'breach' ? 'bg-danger/15 text-danger'
                  : f === 'warn'   ? 'bg-warn/15 text-warn'
                  : f === 'ok'     ? 'bg-success/15 text-success'
                  :                  'bg-accent/15 text-accent'
                  : 'text-faint hover:text-muted'
              }`}
            >
              {f === 'all' ? 'All' : f === 'breach' ? 'Breached' : f === 'warn' ? 'At risk' : 'On track'}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {visibleLeads.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">
          {search || filter !== 'all' ? 'No leads match the current filters.' : 'No open leads right now.'}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line bg-surface [box-shadow:var(--shadow-card)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line">
                {['Lead', 'Stage', 'Move', 'Accountability', 'Target', 'SLA', ''].map((h, i) => (
                  <th key={i} className="whitespace-nowrap px-4 py-3 text-left font-mono text-[9px] uppercase tracking-wider text-faint">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleLeads.map(lead => {
                const chip = SLA_CHIP[lead.sla_status]
                const moveChip = MOVE_CHIP[lead.waiting_on]
                const accountabilityCls =
                  lead.sla_status === 'breach' ? 'text-danger'
                  : lead.sla_status === 'warn'  ? 'text-warn'
                  : lead.sla_status === 'ok'    ? 'text-ink'
                  : 'text-faint'
                return (
                  <tr
                    key={lead.opportunity_id}
                    className="group border-b border-line/50 transition-colors last:border-0 hover:bg-raised"
                  >
                    <td
                      className="relative cursor-pointer px-4 py-3 font-medium text-ink"
                      onClick={() => navigate(`/app/queue?focus=${lead.opportunity_id}`)}
                    >
                      {/* Breach filament — a quiet pulse on the rows that owe a move */}
                      {lead.sla_status === 'breach' && (
                        <span
                          aria-hidden
                          className="cq-sla-pulse absolute left-0 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-full bg-danger [box-shadow:0_0_8px_rgba(224,112,92,0.8)]"
                        />
                      )}
                      {lead.person_name}
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-muted">
                      {STAGE_LABELS[lead.stage] ?? lead.stage}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-control px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider ${moveChip.cls}`}>
                        {/* "Your move" carries a live pip — the ball is in Erez's court */}
                        {lead.waiting_on === 'operator' && (
                          <span
                            aria-hidden
                            className="cq-sla-pulse inline-block h-1 w-1 rounded-full bg-glow [box-shadow:0_0_6px_rgba(96,165,250,0.9)]"
                          />
                        )}
                        {moveChip.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-0.5">
                        <span className={`font-mono text-[11px] tabular-nums ${accountabilityCls}`}>
                          {fmtHours(lead.hours_since_touch)}
                        </span>
                        <span className="whitespace-nowrap font-mono text-[9px] text-faint">
                          in {STAGE_LABELS[lead.stage] ?? lead.stage} {fmtHours(lead.hours_in_stage)}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-faint">
                      {lead.target_hours !== null ? `${lead.target_hours}h` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`whitespace-nowrap rounded-control px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider ${chip.cls}`}>
                        {chip.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => pushAiContext(
                          `${lead.sla_status === 'breach' ? 'SLA Breach'
                            : lead.sla_status === 'warn'   ? 'SLA At Risk'
                            : 'Lead'} · ${lead.person_name}`
                        )}
                        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-control border border-glow/25 px-3 py-1.5 font-mono text-[10px] text-glow opacity-0 transition-all duration-150 group-hover:opacity-100 hover:bg-glow/10"
                        style={{ background: 'color-mix(in srgb, var(--color-glow) 5%, transparent)' }}
                      >
                        <span className="text-[8px]">✦</span> Ask AI
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Overview Bento ─────────────────────────────────────────────────────────────
function Bento({ data }: { data: AnalyticsData }) {
  const { community, pipeline, booked } = data
  const navigate = useNavigate()

  // Week-over-week follower delta from the last 2 data points
  const lastTwo   = community.growth.slice(-2)
  const weekDelta = lastTwo.length >= 2 ? lastTwo[1].followers - lastTwo[0].followers : null
  const pipeMax   = Math.max(...pipeline.map(x => x.count), 1)

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">

      {/* ── Community · followers — with live week delta ─────────────────── */}
      <Tile i={0} span={2} signature>
        <div className="flex items-start justify-between">
          <Label>Community · followers</Label>
          {weekDelta !== null && (
            <span
              className={`rounded-full px-2 py-0.5 font-mono text-[9px] tabular-nums ${
                weekDelta >= 0 ? 'text-success' : 'text-danger'
              }`}
              style={{
                background: weekDelta >= 0
                  ? 'color-mix(in srgb, var(--color-success) 12%, transparent)'
                  : 'color-mix(in srgb, var(--color-danger) 12%, transparent)',
              }}
            >
              {weekDelta >= 0 ? '+' : ''}{compact(Math.abs(weekDelta))} this week
            </span>
          )}
        </div>
        <div className="mt-1.5 font-mono text-4xl tabular-nums leading-none text-accent">
          {compact(community.size)}
        </div>
        <div className="mt-1.5 font-mono text-[10px] text-faint">
          {compact(community.followers_tracked)} tracked · IG + TikTok
        </div>
        <div className="mt-auto pt-3"><Spark data={community.growth} /></div>
      </Tile>

      {/* ── Reach + Conversation — clickable StatTiles ──────────────────── */}
      <StatTile i={1} label="Reach · likes"
        value={compact(community.likes)}
        context="Community reach — total post likes" />
      <StatTile i={2} label="Conversation"
        value={compact(community.comments)}
        note="comments"
        context="Community conversation — comment volume and engagement" />

      {/* ── Follower growth chart — InsightBtn in header ─────────────────── */}
      <Tile i={3} span={2} className="min-h-[200px]">
        <div className="flex items-center">
          <Label>Follower growth · weekly tracked</Label>
          <InsightBtn context="Follower growth trend — weekly follower progression" />
        </div>
        <div className="mt-2 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={community.growth} margin={{ top: 6, right: 2, bottom: 0, left: 2 }}>
              <YAxis domain={['dataMin * 0.95', 'dataMax * 1.02']} hide />
              <Area type="monotone" dataKey="followers" stroke={ELECTRIC} strokeWidth={1.6}
                fill={ELECTRIC} fillOpacity={0.07} dot={false}
                isAnimationActive={!REDUCED} animationDuration={900} />
              <Tooltip
                cursor={{ stroke: 'rgba(190,214,255,0.18)' }}
                contentStyle={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-line)',
                  borderRadius: 8, fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#fff',
                  boxShadow: 'var(--shadow-card)',
                }}
                labelStyle={{ color: 'var(--color-faint)', marginBottom: 2 }}
                formatter={(v: unknown) => [compact(Number(v)), 'followers']}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Tile>

      {/* ── Top posts — full-row hover action menu ───────────────────────── */}
      <Tile i={4} span={2} className="min-h-[200px]">
        <Label>Top posts · by likes</Label>
        <div className="mt-3 flex flex-col gap-1">
          {community.top_posts.slice(0, 5).map((p, idx) => (
            <div
              key={p.shortcode}
              className="group relative flex items-center gap-3 rounded-control px-2 py-1.5 transition-colors hover:bg-raised"
            >
              <span className="w-5 shrink-0 font-mono text-[10px] tabular-nums text-faint">#{idx + 1}</span>
              <span className="flex-1 truncate font-mono text-[11px] text-muted">{p.shortcode}</span>
              <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] tabular-nums">
                <span className="text-accent">{compact(p.likes)} ♥</span>
                <span className="text-faint">{compact(p.comments)} ✦</span>
              </span>
              <HoverMenu>
                <MenuBtn
                  label="Ask AI ✦"
                  onClick={() => pushAiContext(`Post ${p.shortcode} · ${compact(p.likes)} likes`)}
                  accent
                />
                <MenuBtn
                  label="View ↗"
                  onClick={() => window.open(`https://instagram.com/p/${p.shortcode}`, '_blank')}
                />
                <MenuBtn
                  label="Copy URL"
                  onClick={() => navigator.clipboard.writeText(`https://instagram.com/p/${p.shortcode}`)}
                />
              </HoverMenu>
            </div>
          ))}
        </div>
      </Tile>

      {/* ── CRM pipeline — clickable rows with hover nav ─────────────────── */}
      <Tile i={5} span={2}>
        <div className="flex items-center">
          <Label>CRM pipeline</Label>
          <InsightBtn context="CRM pipeline — stage distribution and lead volume" />
        </div>
        <div className="mt-3 flex flex-col gap-1">
          {pipeline.map((s) => (
            <div
              key={s.stage}
              className="group relative flex cursor-pointer items-center gap-2.5 rounded-control px-2 py-1.5 transition-colors hover:bg-raised"
              onClick={() => navigate(`/app/queue?stage=${s.stage}`)}
            >
              <span className="w-16 shrink-0 font-mono text-[10px] text-muted">
                {STAGE_LABELS[s.stage] ?? s.stage}
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                <span className="block h-full rounded-full transition-[width] duration-700"
                  style={{
                    width: `${(s.count / pipeMax) * 100}%`,
                    background: s.stage === 'booked' ? ELECTRIC : TEAL,
                  }} />
              </span>
              <span className="w-5 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted">
                {s.count}
              </span>
              <HoverMenu>
                <MenuBtn
                  label="View leads →"
                  onClick={() => navigate(`/app/queue?stage=${s.stage}`)}
                />
                <MenuBtn
                  label="Ask AI ✦"
                  onClick={() => pushAiContext(`${STAGE_LABELS[s.stage] ?? s.stage} pipeline — ${s.count} leads`)}
                  accent
                />
              </HoverMenu>
            </div>
          ))}
        </div>
      </Tile>

      {/* ── Bottom row StatTiles ─────────────────────────────────────────── */}
      <StatTile i={6} label="Content · posts"
        value={compact(community.posts)}
        context="Content library — total published posts" />
      <StatTile i={7} label="Booked · north star"
        value={String(booked)}
        signature
        context="Booked sessions — the key conversion north star metric" />
    </div>
  )
}

function Spark({ data }: { data: AnalyticsData['community']['growth'] }) {
  return (
    <div className="h-9 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <YAxis domain={['dataMin * 0.95', 'dataMax * 1.02']} hide />
          <Area type="monotone" dataKey="followers" stroke={ELECTRIC} strokeWidth={1.4}
            fill={ELECTRIC} fillOpacity={0.08} dot={false}
            isAnimationActive={!REDUCED} animationDuration={900} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Interaction primitives ────────────────────────────────────────────────────

/** Glassmorphic slide-in menu — place inside a `group` div. */
function HoverMenu({ children }: { children: ReactNode }) {
  return (
    <div
      className="absolute right-1 top-1/2 z-10 flex -translate-y-1/2 translate-x-2 items-center gap-px rounded-control border border-line opacity-0 pointer-events-none transition-all duration-150 group-hover:translate-x-0 group-hover:opacity-100 group-hover:pointer-events-auto"
      style={{
        background: 'color-mix(in srgb, var(--color-bg) 90%, transparent)',
        backdropFilter: 'blur(8px)',
        boxShadow: 'var(--shadow-card)',
        padding: '2px',
      }}
      onClick={e => e.stopPropagation()}
    >
      {children}
    </div>
  )
}

function MenuBtn({ label, onClick, accent = false }: {
  label: string; onClick: (e: React.MouseEvent) => void; accent?: boolean
}) {
  return (
    <button
      type="button"
      onClick={e => { e.stopPropagation(); onClick(e) }}
      className={`whitespace-nowrap rounded px-2 py-1 font-mono text-[9px] transition-colors hover:bg-raised ${
        accent ? 'text-glow' : 'text-muted hover:text-ink'
      }`}
    >
      {label}
    </button>
  )
}

/** Subtle always-visible "✦ Generate Insight" trigger for chart/section headers. */
function InsightBtn({ context, label = 'Generate Insight' }: { context: string; label?: string }) {
  return (
    <button
      type="button"
      onClick={() => pushAiContext(context)}
      className="ml-auto inline-flex items-center gap-1 rounded-control border border-glow/18 px-2 py-0.5 font-mono text-[8px] text-glow/50 transition-all hover:border-glow/40 hover:text-glow"
      style={{ background: 'color-mix(in srgb, var(--color-accent) 6%, transparent)' }}
    >
      <span className="text-[7px]">✦</span> {label}
    </button>
  )
}

function Tile({ children, i, span = 1, signature = false, className = '', onClick }: {
  children: ReactNode; i: number; span?: 1 | 2; signature?: boolean; className?: string; onClick?: () => void
}) {
  return (
    <div
      className={`cq-rise flex flex-col rounded-card border bg-surface p-4 transition-colors hover:bg-raised ${
        signature ? 'border-accent/30' : 'border-line'
      } ${span === 2 ? 'sm:col-span-2' : ''} ${onClick ? 'cursor-pointer' : ''} ${className}`}
      style={{ animationDelay: `${i * 55}ms` }}
      onClick={onClick}
    >
      {children}
    </div>
  )
}

function StatTile({ label, value, note, i, signature = false, context }: {
  label: string; value: string; note?: string; i: number; signature?: boolean; context?: string
}) {
  return (
    <Tile i={i} signature={signature} onClick={context ? () => pushAiContext(context) : undefined}
      className={context ? 'group relative' : ''}>
      <div className="flex items-start justify-between">
        <Label>{label}</Label>
        {context && (
          <span className="font-mono text-[8px] text-glow opacity-0 transition-opacity group-hover:opacity-100">
            ✦ Ask AI
          </span>
        )}
      </div>
      <div className={`mt-1.5 font-mono text-3xl tabular-nums leading-none ${signature ? 'text-accent' : 'text-ink'}`}>
        {value}
      </div>
      {note && <div className="mt-1.5 font-mono text-[10px] text-faint">{note}</div>}
    </Tile>
  )
}

function Label({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{children}</span>
}
