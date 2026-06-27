import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ResponsiveContainer, AreaChart, Area, Tooltip } from 'recharts'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError } from '../components/SurfaceStates'
import { useAuth } from '../auth/AuthProvider'
import { STAGE_LABELS } from '../lib/pipeline'
import {
  compact, fmtHours,
  fetchAnalytics, fetchFunnel, fetchSla,
  SAMPLE_ANALYTICS,
  type AnalyticsData, type FunnelData, type SlaData, type SlaStatus,
} from '../lib/analytics'

// ── Design tokens (warm luxury) ───────────────────────────────────────────────
const BRONZE  = '#d4a843'
const SAGE    = '#8fbc8f'
const REDUCED = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

// Pipeline order for the funnel chart
const PIPELINE = ['engaged', 'qualified', 'captured', 'briefed', 'booked'] as const

type Tab = 'overview' | 'funnel' | 'leads'

// ── Top-level page ─────────────────────────────────────────────────────────────
export function AnalyticsPage() {
  const { session, devBypass } = useAuth()
  const [tab, setTab]   = useState<Tab>('overview')
  const token           = session?.access_token ?? null

  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader
        title="Analytics"
        subtitle="Community reach, pipeline conversion, and SLA health."
      />

      {/* Tab bar */}
      <div className="mb-6 flex items-center gap-1 border-b border-line">
        {(['overview', 'funnel', 'leads'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-4 py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors ${
              tab === t
                ? 'border-b-2 border-accent text-accent'
                : 'text-faint hover:text-muted'
            }`}
          >
            {t === 'overview' ? 'Overview' : t === 'funnel' ? 'Funnel' : 'Leads'}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab token={token} devBypass={devBypass} />}
      {tab === 'funnel'   && <FunnelTab   token={token} />}
      {tab === 'leads'    && <LeadsTab    token={token} />}
    </div>
  )
}

// ── Overview tab (existing bento, unchanged) ───────────────────────────────────
function OverviewTab({ token, devBypass }: { token: string | null; devBypass: boolean }) {
  type State = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: AnalyticsData; sample: boolean }
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const retry = useCallback(() => { setState({ kind: 'loading' }); setRetryNonce((n) => n + 1) }, [])

  useEffect(() => {
    if (devBypass) { setState({ kind: 'ready', data: SAMPLE_ANALYTICS, sample: true }); return }
    if (!token)    { setState({ kind: 'loading' }); return }
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchAnalytics(token, ctrl.signal)
      .then((data) => setState({ kind: 'ready', data, sample: false }))
      .catch((err: unknown) => { if ((err as { name?: string })?.name !== 'AbortError') setState({ kind: 'error' }) })
    return () => ctrl.abort()
  }, [token, devBypass, retryNonce])

  if (state.kind === 'loading') return <SurfaceLoading variant="bento" />
  if (state.kind === 'error')   return <SurfaceError title="Couldn't load analytics" body="Check your connection and try again." onRetry={retry} />
  return (
    <>
      {state.sample && (
        <div className="mb-4 inline-flex items-center gap-2 rounded-control border border-line px-3 py-1 text-xs text-warn">
          <Icon name="alert" size={13} /> sample data — live data loads when signed in
        </div>
      )}
      <Bento data={state.data} />
    </>
  )
}

// ── Funnel tab ─────────────────────────────────────────────────────────────────
function FunnelTab({ token }: { token: string | null }) {
  type State = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: FunnelData }
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const retry = useCallback(() => { setState({ kind: 'loading' }); setRetryNonce((n) => n + 1) }, [])

  useEffect(() => {
    if (!token) { setState({ kind: 'loading' }); return }
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchFunnel(token, ctrl.signal)
      .then((data) => setState({ kind: 'ready', data }))
      .catch((err: unknown) => { if ((err as { name?: string })?.name !== 'AbortError') setState({ kind: 'error' }) })
    return () => ctrl.abort()
  }, [token, retryNonce])

  if (state.kind === 'loading') return <SurfaceLoading variant="bento" />
  if (state.kind === 'error')   return <SurfaceError title="Couldn't load funnel" body="Check your connection and try again." onRetry={retry} />

  const { stages, pairs } = state.data

  // Build conversion % for each consecutive stage pair
  const pipelineStages = PIPELINE.map((stage) => {
    const stageData = stages.find((s) => s.stage === stage)
    // Forward conversion: from this stage to the next pipeline stage
    const nextStage = PIPELINE[PIPELINE.indexOf(stage) + 1]
    const pair = nextStage ? pairs.find((p) => p.from_stage === stage && p.to_stage === nextStage) : null
    // Avg velocity from funnel_metrics (forward pairs only)
    const velocityPair = pairs.find((p) => p.from_stage === stage)
    return {
      stage,
      label:       STAGE_LABELS[stage] ?? stage,
      ever_entered: stageData?.ever_entered ?? 0,
      open_now:    stageData?.open_now ?? 0,
      conversion_pct: pair?.conversion_pct ?? null,
      avg_hours:   velocityPair?.avg_hours_in_stage ?? null,
    }
  })

  const maxEntered = Math.max(...pipelineStages.map((s) => s.ever_entered), 1)

  return (
    <div className="flex flex-col gap-6">
      {/* Stepped funnel */}
      <div className="rounded-card border border-line bg-surface p-5 [box-shadow:var(--shadow-card)]">
        <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
          Pipeline funnel · all-time conversion
        </div>
        <div className="flex flex-col gap-2">
          {pipelineStages.map((s, i) => {
            const pct = s.ever_entered > 0 ? (s.ever_entered / maxEntered) * 100 : 0
            return (
              <div key={s.stage} className="flex items-center gap-3">
                <span className="w-20 shrink-0 font-mono text-[10px] text-muted">{s.label}</span>
                <div className="relative flex-1 overflow-hidden rounded-full" style={{ height: 10 }}>
                  <div className="absolute inset-0 rounded-full bg-raised" />
                  <div
                    className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700"
                    style={{
                      width: `${pct}%`,
                      background: i === PIPELINE.length - 1
                        ? BRONZE
                        : `linear-gradient(90deg, ${BRONZE}cc, ${BRONZE}66)`,
                    }}
                  />
                </div>
                <span className="w-8 shrink-0 text-right font-mono text-xs tabular-nums text-ink">
                  {s.ever_entered}
                </span>
                {s.conversion_pct !== null ? (
                  <span className={`w-14 shrink-0 text-right font-mono text-[10px] tabular-nums ${
                    s.conversion_pct >= 60 ? 'text-success' :
                    s.conversion_pct >= 30 ? 'text-warn'    : 'text-danger'
                  }`}>
                    {s.conversion_pct}%→
                  </span>
                ) : (
                  <span className="w-14 shrink-0 text-right font-mono text-[10px] text-faint">—</span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Stage velocity */}
      <div className="rounded-card border border-line bg-surface p-5 [box-shadow:var(--shadow-card)]">
        <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
          Stage velocity · avg time before advancing
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {pipelineStages.map((s) => (
            <div key={s.stage} className="rounded-control border border-line bg-raised p-3">
              <div className="font-mono text-[9px] uppercase tracking-wider text-faint">{s.label}</div>
              <div className="mt-1.5 font-mono text-lg tabular-nums text-ink">
                {fmtHours(s.avg_hours)}
              </div>
              <div className="mt-0.5 font-mono text-[9px] text-faint">avg to advance</div>
            </div>
          ))}
        </div>
      </div>

      {/* All transition pairs (detail table) */}
      {pairs.length > 0 && (
        <div className="rounded-card border border-line bg-surface p-5 [box-shadow:var(--shadow-card)]">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
            All transitions
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-line text-left">
                  {['From', 'To', 'Leads', 'Conv %', 'Avg time', 'Median time'].map((h) => (
                    <th key={h} className="pb-2 font-mono text-[9px] uppercase tracking-wider text-faint pr-4">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pairs.map((p, i) => (
                  <tr key={i} className="border-b border-line/50 last:border-0">
                    <td className="py-1.5 pr-4 font-mono text-muted">{STAGE_LABELS[p.from_stage] ?? p.from_stage}</td>
                    <td className="py-1.5 pr-4 font-mono text-muted">{STAGE_LABELS[p.to_stage] ?? p.to_stage}</td>
                    <td className="py-1.5 pr-4 font-mono tabular-nums text-ink">{p.unique_leads}</td>
                    <td className={`py-1.5 pr-4 font-mono tabular-nums ${
                      p.conversion_pct !== null && p.conversion_pct >= 60 ? 'text-success' :
                      p.conversion_pct !== null && p.conversion_pct >= 30 ? 'text-warn'    : 'text-danger'
                    }`}>
                      {p.conversion_pct !== null ? `${p.conversion_pct}%` : '—'}
                    </td>
                    <td className="py-1.5 pr-4 font-mono tabular-nums text-muted">{fmtHours(p.avg_hours_in_stage)}</td>
                    <td className="py-1.5 font-mono tabular-nums text-muted">{fmtHours(p.median_hours_in_stage)}</td>
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
function LeadsTab({ token }: { token: string | null }) {
  type State = { kind: 'loading' } | { kind: 'error' } | { kind: 'ready'; data: SlaData }
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const retry    = useCallback(() => { setState({ kind: 'loading' }); setRetryNonce((n) => n + 1) }, [])
  const navigate = useNavigate()

  useEffect(() => {
    if (!token) { setState({ kind: 'loading' }); return }
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchSla(token, ctrl.signal)
      .then((data) => setState({ kind: 'ready', data }))
      .catch((err: unknown) => { if ((err as { name?: string })?.name !== 'AbortError') setState({ kind: 'error' }) })
    return () => ctrl.abort()
  }, [token, retryNonce])

  if (state.kind === 'loading') return <SurfaceLoading variant="bento" />
  if (state.kind === 'error')   return <SurfaceError title="Couldn't load SLA data" body="Check your connection and try again." onRetry={retry} />

  const { leads, summary } = state.data

  const SLA_CHIP: Record<SlaStatus, { label: string; cls: string }> = {
    ok:      { label: 'On track', cls: 'text-success bg-success/10' },
    warn:    { label: 'At risk',  cls: 'text-warn bg-warn/10' },
    breach:  { label: 'Breached', cls: 'text-danger bg-danger/10' },
    unknown: { label: 'Unknown',  cls: 'text-faint bg-raised' },
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Summary chips */}
      <div className="flex flex-wrap gap-3">
        {[
          { label: 'Breached', count: summary.breach, cls: 'border-danger/30 text-danger' },
          { label: 'At risk',  count: summary.warn,   cls: 'border-warn/30 text-warn' },
          { label: 'On track', count: summary.ok,     cls: 'border-success/30 text-success' },
          { label: 'Total',    count: summary.total,  cls: 'border-line text-muted' },
        ].map(({ label, count, cls }) => (
          <div key={label} className={`rounded-card border px-4 py-2.5 ${cls}`}>
            <div className="font-mono text-2xl tabular-nums leading-none">{count}</div>
            <div className="mt-1 font-mono text-[9px] uppercase tracking-wider opacity-70">{label}</div>
          </div>
        ))}
      </div>

      {/* Leads table */}
      {leads.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted">No open leads right now.</p>
      ) : (
        <div className="rounded-card border border-line bg-surface [box-shadow:var(--shadow-card)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line">
                {['Lead', 'Stage', 'Time in stage', 'Target', 'SLA'].map((h) => (
                  <th key={h} className="px-4 py-3 text-left font-mono text-[9px] uppercase tracking-wider text-faint">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => {
                const chip = SLA_CHIP[lead.sla_status]
                return (
                  <tr
                    key={lead.opportunity_id}
                    onClick={() => navigate(`/app/queue?focus=${lead.opportunity_id}`)}
                    className="cursor-pointer border-b border-line/50 transition-colors last:border-0 hover:bg-raised"
                  >
                    <td className="px-4 py-3 font-medium text-ink">{lead.person_name}</td>
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

// ── Overview Bento (unchanged from existing implementation) ────────────────────
function Bento({ data }: { data: AnalyticsData }) {
  const { community, pipeline, booked } = data
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Tile i={0} span={2} signature>
        <Label>Community · followers</Label>
        <div className="mt-1.5 font-mono text-4xl tabular-nums leading-none text-accent">
          {compact(community.size)}
        </div>
        <div className="mt-1.5 font-mono text-[10px] text-faint">
          {compact(community.followers_tracked)} tracked · IG + TikTok
        </div>
        <div className="mt-auto pt-3"><Spark data={community.growth} /></div>
      </Tile>

      <StatTile i={1} label="Reach · likes"    value={compact(community.likes)} />
      <StatTile i={2} label="Conversation"      value={compact(community.comments)} note="comments" />

      <Tile i={3} span={2} className="min-h-[200px]">
        <Label>Follower growth · tracked</Label>
        <div className="mt-2 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={community.growth} margin={{ top: 6, right: 2, bottom: 0, left: 2 }}>
              <Area type="monotone" dataKey="followers" stroke={BRONZE} strokeWidth={1.6}
                fill={BRONZE} fillOpacity={0.07} dot={false}
                isAnimationActive={!REDUCED} animationDuration={900} />
              <Tooltip cursor={{ stroke: 'rgba(242,235,224,0.15)' }}
                contentStyle={{ background: '#0e0b08', border: '0.5px solid rgba(255,235,180,0.08)',
                  borderRadius: 8, fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#ffffff' }}
                labelStyle={{ color: '#52525b' }}
                formatter={(v) => [compact(Number(v)), 'followers']} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Tile>

      <Tile i={4} span={2} className="min-h-[200px]">
        <Label>Top posts · by likes</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {community.top_posts.slice(0, 5).map((p) => (
            <a key={p.shortcode} href={`https://instagram.com/p/${p.shortcode}`}
              target="_blank" rel="noreferrer"
              className="flex items-center justify-between gap-3 text-sm text-muted transition-colors hover:text-ink">
              <span className="truncate font-mono text-xs text-muted">/{p.shortcode}</span>
              <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] tabular-nums">
                <span className="text-accent">{compact(p.likes)} likes</span>
                <span className="text-faint">{compact(p.comments)}</span>
              </span>
            </a>
          ))}
        </div>
      </Tile>

      <Tile i={5} span={2}>
        <Label>CRM pipeline</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {pipeline.map((s) => {
            const max = Math.max(...pipeline.map((x) => x.count), 1)
            const isBooked = s.stage === 'booked'
            return (
              <div key={s.stage} className="flex items-center gap-2.5">
                <span className="w-16 shrink-0 font-mono text-[10px] text-muted">
                  {STAGE_LABELS[s.stage] ?? s.stage}
                </span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                  <span className="block h-full rounded-full transition-[width] duration-700"
                    style={{ width: `${(s.count / max) * 100}%`, background: isBooked ? BRONZE : SAGE }} />
                </span>
                <span className="w-5 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted">
                  {s.count}
                </span>
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
