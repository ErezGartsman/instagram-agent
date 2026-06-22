import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CSSProperties } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { Icon } from '../components/Icon'
import type { IconName } from '../components/Icon'
import { StatCard } from '../components/StatCard'
import { useAuth } from '../auth/AuthProvider'
import { FEATURES } from '../lib/flags'
import { fetchPipeline, SAMPLE_PIPELINE } from '../lib/pipeline'
import { deriveKpis, type Kpi } from '../lib/analytics'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from '../lib/workqueue'

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; kpis: Kpi[]; top: QueueItem | null; pending: number; sample: boolean }

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

const DATELINE = new Date().toLocaleDateString(undefined, {
  weekday: 'long',
  month: 'long',
  day: 'numeric',
})

export function OverviewPage() {
  const { session, devBypass } = useAuth()
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    if (devBypass) {
      const ranked = rankQueue(SAMPLE_QUEUE)
      setState({
        kind: 'ready',
        kpis: deriveKpis(SAMPLE_PIPELINE),
        top: ranked[0] ?? null,
        pending: ranked.length,
        sample: true,
      })
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
      fetchQueue(token, controller.signal),
    ])
      .then(([stages, items]) => {
        const ranked = rankQueue(items)
        setState({
          kind: 'ready',
          kpis: deriveKpis(stages),
          top: ranked[0] ?? null,
          pending: ranked.length,
          sample: false,
        })
      })
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [session?.access_token, devBypass])

  return (
    <div className="mx-auto max-w-[1100px]">
      <header className="mb-8">
        {/* font-serif (Fraunces) is permitted here and ONLY here — the human voice */}
        <h2 className="font-serif text-3xl font-light leading-tight text-ink">{greeting()}.</h2>
        <p className="mt-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">{DATELINE}</p>
      </header>

      {state.kind === 'loading' && <PulseSkeleton />}
      {state.kind === 'error' && <PulseError />}

      {state.kind === 'ready' && (
        <>
          <div className="mb-9 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {state.kpis.map((k, i) => (
              <StatCard key={k.label} {...k} index={i} />
            ))}
          </div>

          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
            Where to start
          </div>
          {state.top ? (
            <NextMove top={state.top} pending={state.pending} />
          ) : (
            <ClearState />
          )}

          <div className="mt-9 flex flex-wrap gap-3">
            <QuickJump to="/app/pipeline" icon="columns" label="Pipeline" />
            {FEATURES.content && <QuickJump to="/app/content" icon="sparkle" label="Content Studio" />}
            {FEATURES.analytics && <QuickJump to="/app/analytics" icon="chart" label="Analytics" />}
          </div>
        </>
      )}
    </div>
  )
}

const MotionLink = motion(Link)

function NextMove({ top, pending }: { top: QueueItem; pending: number }) {
  const queueLive = FEATURES.workQueue
  const to = queueLive ? '/app/queue' : '/app/pipeline'
  const reduce = useReducedMotion()
  return (
    <MotionLink
      to={to}
      whileHover={reduce ? undefined : { y: -3, boxShadow: '0 0 36px rgba(124,58,237,0.28), inset 0 1px 0 rgba(255,255,255,0.12)' }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="group block rounded-card border border-line bg-surface p-5 backdrop-blur-xl transition-colors hover:bg-raised [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-[rgba(124,58,237,0.20)] border border-[rgba(167,139,250,0.25)] px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-glow">
              Next
            </span>
            <span className="truncate text-sm font-medium text-ink">{top.name}</span>
          </div>
          <div className="mt-2 text-base text-ink">{top.action}</div>
          <div className="mt-1.5 text-xs leading-relaxed text-muted">
            <span className="text-faint">Reason · </span>
            {top.reason}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2.5">
          <span className="font-mono text-sm tabular-nums text-glow [text-shadow:0_0_8px_rgba(167,139,250,0.6)]">
            {top.confidence}%
          </span>
          <span className="flex items-center gap-1 text-xs text-muted transition-colors group-hover:text-ink">
            {queueLive ? 'Open the queue' : 'Open the board'}
            <Icon name="arrowRight" size={13} />
          </span>
        </div>
      </div>
      {/* Neon confidence bar */}
      <span className="mt-4 block h-[3px] w-full overflow-hidden rounded-full bg-white/[0.08]">
        <span
          className="cq-grow block h-full rounded-full bg-gradient-to-r from-[#7c3aed] to-[#a78bfa] [box-shadow:0_0_8px_rgba(124,58,237,0.70)]"
          style={{ '--w': `${top.confidence}%` } as CSSProperties}
        />
      </span>
      <div className="mt-3 font-mono text-[10px] text-faint">
        {pending} {pending === 1 ? 'person' : 'people'} waiting on a next move
      </div>
    </MotionLink>
  )
}

function QuickJump({ to, icon, label }: { to: string; icon: IconName; label: string }) {
  const reduce = useReducedMotion()
  return (
    <MotionLink
      to={to}
      whileHover={reduce ? undefined : { scale: 1.04, y: -1 }}
      whileTap={reduce ? undefined : { scale: 0.97 }}
      transition={{ duration: 0.14, ease: 'easeOut' }}
      className="inline-flex items-center gap-2 rounded-control border border-line px-3.5 py-2 text-sm text-muted transition-colors hover:bg-raised hover:text-ink"
    >
      <Icon name={icon} size={15} />
      {label}
    </MotionLink>
  )
}

function ClearState() {
  return (
    <div className="flex flex-col items-center rounded-card border border-line bg-surface px-8 py-12 backdrop-blur-xl text-center [box-shadow:var(--shadow-card)]">
      <span className="mb-3 grid h-11 w-11 place-items-center rounded-control border border-line bg-raised text-success">
        <Icon name="check" size={20} />
      </span>
      <h3 className="text-sm font-semibold text-ink">You&rsquo;re all caught up</h3>
      <p className="mt-1.5 max-w-sm text-sm text-muted">No one is waiting on a next move right now.</p>
    </div>
  )
}

function PulseSkeleton() {
  return (
    <div aria-hidden>
      <div className="mb-9 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-card border border-line bg-white/[0.04]" />
        ))}
      </div>
      <div className="h-28 animate-pulse rounded-card border border-line bg-white/[0.04]" />
    </div>
  )
}

function PulseError() {
  return (
    <div className="flex flex-col items-center rounded-card border border-line bg-surface px-8 py-16 backdrop-blur-xl text-center [box-shadow:var(--shadow-card)]">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-danger">
        <Icon name="alert" size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">Couldn&rsquo;t load your overview</h3>
      <p className="mt-2 max-w-md text-sm text-muted">
        The pulse couldn&rsquo;t be reached. Check your connection and reload.
      </p>
    </div>
  )
}
