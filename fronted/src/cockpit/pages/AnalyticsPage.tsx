import { useEffect, useMemo, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { StatCard } from '../components/StatCard'
import { Icon } from '../components/Icon'
import { useAuth } from '../auth/AuthProvider'
import { fetchPipeline, SAMPLE_PIPELINE } from '../lib/pipeline'
import {
  deriveKpis,
  embedUrlForView,
  fetchPowerBiEmbed,
  REPORT_VIEWS,
  type Kpi,
} from '../lib/analytics'

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; kpis: Kpi[]; embedUrl: string | null; sample: boolean }

/**
 * Ticket 5.5 — the Analytics pillar. Executive KPI strip (real CRM data, the
 * Instrument voice) over a single framed, segmented Power BI embed. Graphite
 * Atelier discipline: density framed in obsidian negative space, one signature.
 */
export function AnalyticsPage() {
  const { session, devBypass } = useAuth()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [view, setView] = useState(REPORT_VIEWS[0])

  useEffect(() => {
    if (devBypass) {
      // No Power BI / backend locally — show the real sample KPIs and the calm
      // "connect" state for the embed.
      setState({ kind: 'ready', kpis: deriveKpis(SAMPLE_PIPELINE), embedUrl: null, sample: true })
      return
    }
    const token = session?.access_token
    if (!token) {
      setState({ kind: 'loading' })
      return
    }
    const controller = new AbortController()
    setState({ kind: 'loading' })
    Promise.all([
      fetchPipeline(token, controller.signal),
      fetchPowerBiEmbed(token, controller.signal),
    ])
      .then(([stages, embedUrl]) =>
        setState({ kind: 'ready', kpis: deriveKpis(stages), embedUrl, sample: false }),
      )
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [session?.access_token, devBypass])

  const iframeSrc = useMemo(
    () => (state.kind === 'ready' && state.embedUrl ? embedUrlForView(state.embedUrl, view) : null),
    [state, view],
  )

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Analytics" subtitle="Pipeline and community performance, in one calm view." />

      {state.kind === 'ready' && state.sample && (
        <div className="mb-4 inline-flex items-center gap-2 rounded-control border border-line px-3 py-1 text-xs text-warn">
          <Icon name="alert" size={13} />
          sample KPIs (dev bypass) — live data + Power BI load when you&rsquo;re signed in
        </div>
      )}

      {/* Segmented report selector — one report in focus at a time. */}
      <div className="mb-5 flex items-center justify-between gap-4">
        <div className="inline-flex overflow-hidden rounded-control border border-line">
          {REPORT_VIEWS.map((v) => {
            const active = v.key === view.key
            return (
              <button
                key={v.key}
                onClick={() => setView(v)}
                aria-pressed={active}
                className={`px-3.5 py-1.5 text-xs transition-colors ${
                  active ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-raised hover:text-ink'
                }`}
              >
                {v.label}
              </button>
            )
          })}
        </div>
      </div>

      {state.kind === 'loading' && <AnalyticsSkeleton />}
      {state.kind === 'error' && <AnalyticsError />}
      {state.kind === 'ready' && (
        <>
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {state.kpis.map((k) => (
              <StatCard key={k.label} {...k} />
            ))}
          </div>

          <div className="h-[70vh] min-h-[480px] overflow-hidden rounded-card border border-line bg-surface">
            {iframeSrc ? (
              <iframe
                key={view.key}
                title={`Power BI · ${view.label}`}
                src={iframeSrc}
                className="h-full w-full border-0"
                allowFullScreen
              />
            ) : (
              <PowerBiConnect />
            )}
          </div>
        </>
      )}
    </div>
  )
}

function PowerBiConnect() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-accent">
        <Icon name="chart" size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">Connect Power BI</h3>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
        Set <span className="font-mono text-xs text-ink">POWERBI_REPORT_ID</span> and{' '}
        <span className="font-mono text-xs text-ink">POWERBI_TENANT_ID</span> on the backend, then
        sign in to Power BI in this browser. Apply the Graphite Atelier theme inside the report so it
        matches the cockpit.
      </p>
    </div>
  )
}

function AnalyticsSkeleton() {
  return (
    <div aria-hidden>
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-card border border-line bg-surface" />
        ))}
      </div>
      <div className="h-[70vh] min-h-[480px] animate-pulse rounded-card border border-line bg-surface" />
    </div>
  )
}

function AnalyticsError() {
  return (
    <div className="flex flex-col items-center rounded-card border border-line bg-surface px-8 py-16 text-center">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-danger">
        <Icon name="alert" size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">Couldn&rsquo;t load analytics</h3>
      <p className="mt-2 max-w-md text-sm text-muted">
        The metrics couldn&rsquo;t be reached. Check your connection and reload.
      </p>
    </div>
  )
}
