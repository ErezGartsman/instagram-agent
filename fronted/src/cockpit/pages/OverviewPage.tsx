import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CSSProperties } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { Icon } from '../components/Icon'
import { StatCard } from '../components/StatCard'
import { SurfaceLoading, SurfaceEmpty, SurfaceError } from '../components/SurfaceStates'
import { useAuth } from '../auth/AuthProvider'
import { FEATURES } from '../lib/flags'
import { fetchPipeline, SAMPLE_PIPELINE } from '../lib/pipeline'
import { deriveKpis, type Kpi } from '../lib/analytics'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from '../lib/workqueue'

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; kpis: Kpi[]; top: QueueItem | null; pending: number; sample: boolean }

function greeting(displayName: string): string {
  const h = new Date().getHours()
  const salutation = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
  // Use only the first name so "Good afternoon, Erez" stays clean.
  const first = displayName.split(' ')[0]
  return first ? `${salutation}, ${first}` : salutation
}

const DATELINE = new Date().toLocaleDateString(undefined, {
  weekday: 'long',
  month: 'long',
  day: 'numeric',
})

export function OverviewPage() {
  const { session, devBypass, displayName } = useAuth()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const sigRef = useRef('')
  const retry = useCallback(() => {
    setState({ kind: 'loading' })
    setRetryNonce((n) => n + 1)
  }, [])

  // Initial load (shows loading state, error on failure).
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
        const kpis = deriveKpis(stages)
        sigRef.current = `${kpis.map((k) => k.value).join(',')}|${ranked[0]?.id ?? ''}:${ranked.length}`
        setState({
          kind: 'ready',
          kpis,
          top: ranked[0] ?? null,
          pending: ranked.length,
          sample: false,
        })
      })
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [session?.access_token, devBypass, retryNonce])

  // Background fetch — silent; never shows loading, never flashes error.
  // Signature-diff guard: skips setState when nothing changed.
  const bgFetch = useCallback(async () => {
    const token = session?.access_token
    if (!token || devBypass) return
    try {
      const [stages, items] = await Promise.all([
        fetchPipeline(token),
        fetchQueue(token),
      ])
      const ranked = rankQueue(items)
      const kpis = deriveKpis(stages)
      const newSig = `${kpis.map((k) => k.value).join(',')}|${ranked[0]?.id ?? ''}:${ranked.length}`
      if (newSig === sigRef.current) return
      sigRef.current = newSig
      setState({ kind: 'ready', kpis, top: ranked[0] ?? null, pending: ranked.length, sample: false })
    } catch {
      // Transient poll failures are silent — don't flash an error state.
    }
  }, [session?.access_token, devBypass])

  // 30s polling
  useEffect(() => {
    const id = setInterval(() => void bgFetch(), 30_000)
    return () => clearInterval(id)
  }, [bgFetch])

  // Aggressive focus + visibility refetch (debounced 500ms)
  useEffect(() => {
    let debounce: ReturnType<typeof setTimeout> | null = null
    const trigger = () => {
      if (debounce) clearTimeout(debounce)
      debounce = setTimeout(() => void bgFetch(), 500)
    }
    const onVisibility = () => { if (document.visibilityState === 'visible') trigger() }
    window.addEventListener('focus', trigger)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('focus', trigger)
      document.removeEventListener('visibilitychange', onVisibility)
      if (debounce) clearTimeout(debounce)
    }
  }, [bgFetch])

  return (
    <div className="mx-auto max-w-[1100px]">
      <header className="mb-8">
        {/* font-serif (Fraunces) is permitted here and ONLY here — the human voice */}
        <h2 className="font-serif text-3xl font-light leading-tight text-ink">{greeting(displayName)}.</h2>
        <p className="mt-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">{DATELINE}</p>
      </header>

      {state.kind === 'loading' && <SurfaceLoading variant="grid" />}
      {state.kind === 'error' && (
        <SurfaceError
          title="Couldn't load your overview"
          body="The pulse couldn't be reached. Check your connection and try again."
          onRetry={retry}
        />
      )}

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
            <SurfaceEmpty
              flavor="win"
              title="You're all caught up"
              body="No one is waiting on a next move right now."
              copilotSlot={null}
            />
          )}


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
      whileHover={reduce ? undefined : { y: -3, boxShadow: '0 0 36px rgba(184,134,11,0.24), inset 0 1px 0 rgba(255,235,180,0.10)' }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="group block rounded-card border border-line bg-surface p-5 backdrop-blur-xl transition-colors hover:bg-raised [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-[rgba(184,134,11,0.15)] border border-[rgba(212,168,67,0.30)] px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-glow">
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
          <span className="font-mono text-sm tabular-nums text-glow [text-shadow:0_0_8px_rgba(212,168,67,0.7)]">
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
          className="cq-grow block h-full rounded-full bg-gradient-to-r from-[#b8860b] to-[#d4a843] [box-shadow:0_0_8px_rgba(184,134,11,0.75)]"
          style={{ '--w': `${top.confidence}%` } as CSSProperties}
        />
      </span>
      <div className="mt-3 font-mono text-[10px] text-faint">
        {pending} {pending === 1 ? 'person' : 'people'} waiting on a next move
      </div>
    </MotionLink>
  )
}


