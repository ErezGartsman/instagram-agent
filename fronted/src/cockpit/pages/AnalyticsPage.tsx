import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ResponsiveContainer, AreaChart, Area, Tooltip, YAxis } from 'recharts'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError } from '../components/SurfaceStates'
import { ContextTarget, pushAiContext } from '../components/GlowingAiAssistant'
import { useAuth } from '../auth/AuthProvider'
import { STAGE_LABELS } from '../lib/pipeline'
import {
  compact, fmtHours,
  fetchAnalytics, fetchFunnel, fetchSla,
  SAMPLE_ANALYTICS,
  type AnalyticsData, type FunnelData, type SlaData, type SlaStatus,
} from '../lib/analytics'

const BRONZE  = '#d4a843'
const SAGE    = '#8fbc8f'
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
  type State = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: AnalyticsData; sample: boolean }
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [nonce, setNonce] = useState(0)
  const retry = useCallback(() => { setState({ kind: 'loading' }); setNonce(n => n + 1) }, [])

  useEffect(() => {
    if (devBypass) { setState({ kind: 'ready', data: SAMPLE_ANALYTICS, sample: true }); return }
    if (!token) return
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchAnalytics(token, ctrl.signal)
      .then(data => setState({ kind: 'ready', data, sample: false }))
      .catch((err: unknown) => { if ((err as { name?: string })?.name !== 'AbortError') setState({ kind: 'error' }) })
    return () => ctrl.abort()
  }, [token, devBypass, nonce])

  if (state.kind === 'loading') return <SurfaceLoading variant="bento" />
  if (state.kind === 'error')   return <SurfaceError title="Couldn't load analytics" body="Check your connection and try again." onRetry={retry} />
  return (
    <>
      {state.sample && (
        <div className="mb-4 inline-flex items-center gap-2 rounded-control border border-line px-3 py-1 text-xs text-warn">
          <Icon name="alert" size={13} /> sample data
        </div>
      )}
      <Bento data={state.data} />
    </>
  )
}

// ── Funnel tab ─────────────────────────────────────────────────────────────────
function FunnelTab({ token, days }: { token: string | null; days: Days }) {
  type State = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: FunnelData }
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [nonce, setNonce] = useState(0)
  const retry = useCallback(() => { setState({ kind: 'loading' }); setNonce(n => n + 1) }, [])

  useEffect(() => {
    if (!token) return
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchFunnel(token, days, ctrl.signal)
      .then(data => setState({ kind: 'ready', data }))
      .catch((err: unknown) => { if ((err as { name?: string })?.name !== 'AbortError') setState({ kind: 'error' }) })
    return () => ctrl.abort()
  }, [token, days, nonce])

  if (state.kind === 'loading') return <SurfaceLoading variant="bento" />
  if (state.kind === 'error')   return <SurfaceError title="Couldn't load funnel" body="Check your connection and try again." onRetry={retry} />

  const stages = state.data.stages ?? []
  const pairs  = state.data.pairs  ?? []

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
        <div className="mb-5 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
          Pipeline funnel · all-time flow
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
        <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
          Stage velocity · avg time before advancing
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {pipelineStages.map((s, i) => {
            const isEntry    = i === 0
            const isTerminal = i === pipelineStages.length - 1
            const hasData    = s.avg_hours !== null
            return (
              <div key={s.stage} className="rounded-control border border-line bg-raised p-3">
                <div className="font-mono text-[9px] uppercase tracking-wider text-faint">{s.label}</div>
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
                  <tr key={i} className="border-b border-line/50 last:border-0">
                    <td className="py-2 pr-4 font-mono text-muted">{STAGE_LABELS[p.from_stage] ?? p.from_stage}</td>
                    <td className="py-2 pr-4 font-mono text-muted">{STAGE_LABELS[p.to_stage]   ?? p.to_stage}</td>
                    <td className="py-2 pr-4 font-mono tabular-nums text-ink">{p.unique_leads}</td>
                    <td className={`py-2 pr-4 font-mono tabular-nums ${
                      p.conversion_pct === null ? 'text-faint' :
                      p.conversion_pct >= 60    ? 'text-success' :
                      p.conversion_pct >= 30    ? 'text-warn'    : 'text-danger'
                    }`}>{p.conversion_pct !== null ? `${p.conversion_pct}%` : '—'}</td>
                    <td className="py-2 pr-4 font-mono tabular-nums text-muted">{fmtHours(p.avg_hours_in_stage)}</td>
                    <td className="py-2 font-mono tabular-nums text-muted">{fmtHours(p.median_hours_in_stage)}</td>
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

function LeadsTab({ token }: { token: string | null }) {
  type State = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: SlaData }
  const [state,   setState]   = useState<State>({ kind: 'loading' })
  const [nonce,   setNonce]   = useState(0)
  const [search,  setSearch]  = useState('')
  const [filter,  setFilter]  = useState<SlaStatus | 'all'>('all')
  const navigate = useNavigate()
  const retry    = useCallback(() => { setState({ kind: 'loading' }); setNonce(n => n + 1) }, [])

  useEffect(() => {
    if (!token) return
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchSla(token, ctrl.signal)
      .then(data => setState({ kind: 'ready', data }))
      .catch((err: unknown) => { if ((err as { name?: string })?.name !== 'AbortError') setState({ kind: 'error' }) })
    return () => ctrl.abort()
  }, [token, nonce])

  const visibleLeads = useMemo(() => {
    if (state.kind !== 'ready') return []
    return state.data.leads.filter(l => {
      const matchesFilter = filter === 'all' || l.sla_status === filter
      const matchesSearch = !search || l.person_name.toLowerCase().includes(search.toLowerCase())
      return matchesFilter && matchesSearch
    })
  }, [state, filter, search])

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
        <div className="rounded-card border border-line bg-surface [box-shadow:var(--shadow-card)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line">
                {['Lead', 'Stage', 'Time in stage', 'Target', 'SLA', ''].map((h, i) => (
                  <th key={i} className="px-4 py-3 text-left font-mono text-[9px] uppercase tracking-wider text-faint">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleLeads.map(lead => {
                const chip = SLA_CHIP[lead.sla_status]
                return (
                  <tr
                    key={lead.opportunity_id}
                    className="group border-b border-line/50 transition-colors last:border-0 hover:bg-raised"
                  >
                    <td
                      className="cursor-pointer px-4 py-3 font-medium text-ink"
                      onClick={() => navigate(`/app/queue?focus=${lead.opportunity_id}`)}
                    >
                      {lead.person_name}
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-muted">
                      {STAGE_LABELS[lead.stage] ?? lead.stage}
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-ink">
                      {fmtHours(lead.hours_in_stage)}
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-faint">
                      {lead.target_hours !== null ? `${lead.target_hours}h` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-control px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider ${chip.cls}`}>
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
                        className="inline-flex items-center gap-1.5 rounded-control border border-glow/25 px-3 py-1.5 font-mono text-[10px] text-glow opacity-0 transition-all duration-150 group-hover:opacity-100 hover:bg-glow/10"
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
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Tile i={0} span={2} signature>
        <Label>Community · followers</Label>
        <div className="mt-1.5 font-mono text-4xl tabular-nums leading-none text-accent">{compact(community.size)}</div>
        <div className="mt-1.5 font-mono text-[10px] text-faint">{compact(community.followers_tracked)} tracked · IG + TikTok</div>
        <div className="mt-auto pt-3"><Spark data={community.growth} /></div>
      </Tile>

      <StatTile i={1} label="Reach · likes"    value={compact(community.likes)} />
      <StatTile i={2} label="Conversation"      value={compact(community.comments)} note="comments" />

      {/* Growth chart — fix: auto-scaled Y-axis so sparse data isn't flat */}
      <Tile i={3} span={2} className="min-h-[200px]">
        <div className="flex items-center gap-1.5">
          <Label>Follower growth · weekly tracked</Label>
          <ContextTarget label="Follower Growth Chart" />
        </div>
        <div className="mt-2 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={community.growth} margin={{ top: 6, right: 2, bottom: 0, left: 2 }}>
              <YAxis domain={['dataMin * 0.95', 'dataMax * 1.02']} hide />
              <Area type="monotone" dataKey="followers" stroke={BRONZE} strokeWidth={1.6}
                fill={BRONZE} fillOpacity={0.07} dot={false}
                isAnimationActive={!REDUCED} animationDuration={900} />
              <Tooltip
                cursor={{ stroke: 'rgba(242,235,224,0.15)' }}
                contentStyle={{ background: '#0e0b08', border: '0.5px solid rgba(255,235,180,0.08)',
                  borderRadius: 8, fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#fff' }}
                labelStyle={{ color: '#52525b' }}
                formatter={(v) => [compact(Number(v)), 'followers']}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Tile>

      {/* Top posts */}
      <Tile i={4} span={2} className="min-h-[200px]">
        <Label>Top posts · by likes</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {community.top_posts.slice(0, 5).map((p, i) => (
            <div key={p.shortcode} className="flex items-center gap-2">
              <a href={`https://instagram.com/p/${p.shortcode}`}
                target="_blank" rel="noreferrer"
                className="flex flex-1 items-center gap-3 text-sm text-muted transition-colors hover:text-ink">
                <span className="w-5 shrink-0 font-mono text-[10px] tabular-nums text-faint">#{i + 1}</span>
                <span className="flex-1 truncate font-mono text-[11px] text-muted">{p.shortcode}</span>
                <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] tabular-nums">
                  <span className="text-accent">{compact(p.likes)} ♥</span>
                  <span className="text-faint">{compact(p.comments)} ✦</span>
                </span>
              </a>
              <ContextTarget label={`Top Post #${i + 1} · ${p.shortcode}`} className="shrink-0" />
            </div>
          ))}
        </div>
      </Tile>

      <Tile i={5} span={2}>
        <Label>CRM pipeline</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {pipeline.map((s) => {
            const max = Math.max(...pipeline.map((x) => x.count), 1)
            return (
              <div key={s.stage} className="flex items-center gap-2.5">
                <span className="w-16 shrink-0 font-mono text-[10px] text-muted">{STAGE_LABELS[s.stage] ?? s.stage}</span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                  <span className="block h-full rounded-full transition-[width] duration-700"
                    style={{ width: `${(s.count / max) * 100}%`, background: s.stage === 'booked' ? BRONZE : SAGE }} />
                </span>
                <span className="w-5 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted">{s.count}</span>
              </div>
            )
          })}
        </div>
      </Tile>

      <StatTile i={6} label="Content · posts"     value={compact(community.posts)} />
      <StatTile i={7} label="Booked · north star" value={String(booked)} signature />
    </div>
  )
}

function Spark({ data }: { data: AnalyticsData['community']['growth'] }) {
  return (
    <div className="h-9 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <YAxis domain={['dataMin * 0.95', 'dataMax * 1.02']} hide />
          <Area type="monotone" dataKey="followers" stroke={BRONZE} strokeWidth={1.4}
            fill={BRONZE} fillOpacity={0.08} dot={false}
            isAnimationActive={!REDUCED} animationDuration={900} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function Tile({ children, i, span = 1, signature = false, className = '' }: {
  children: ReactNode; i: number; span?: 1 | 2; signature?: boolean; className?: string
}) {
  return (
    <div className={`cq-rise flex flex-col rounded-card border bg-surface p-4 transition-colors hover:bg-raised ${
      signature ? 'border-accent/30' : 'border-line'
    } ${span === 2 ? 'sm:col-span-2' : ''} ${className}`}
      style={{ animationDelay: `${i * 55}ms` }}>
      {children}
    </div>
  )
}

function StatTile({ label, value, note, i, signature = false }: {
  label: string; value: string; note?: string; i: number; signature?: boolean
}) {
  return (
    <Tile i={i} signature={signature}>
      <Label>{label}</Label>
      <div className={`mt-1.5 font-mono text-3xl tabular-nums leading-none ${signature ? 'text-accent' : 'text-ink'}`}>{value}</div>
      {note && <div className="mt-1.5 font-mono text-[10px] text-faint">{note}</div>}
    </Tile>
  )
}

function Label({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{children}</span>
}
