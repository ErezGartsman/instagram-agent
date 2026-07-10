import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Icon } from './Icon'
import { useAuth } from '../auth/AuthProvider'
import { queryKeys } from '../lib/queryClient'
import { fetchBriefing, type BriefingTone } from '../lib/dossier'

/**
 * Morning briefing — the cockpit's proactive "push" surface (live since Phase 3).
 *
 * The Command screen's widgets all ANSWER questions; this card is the one
 * surface that SPEAKS FIRST. GET /api/cockpit/briefing compiles a deterministic
 * diff of the last 24h (reopens after silence, new leads, SLA accountability);
 * this component renders it and then gets out of the way: acknowledging it
 * collapses it for the rest of the day (localStorage, keyed by date).
 *
 * Quiet by design: while loading, on fetch failure, or on a quiet night the
 * card renders NOTHING — a briefing that has nothing to say stays silent.
 */

const ACK_KEY = 'nexus.briefing.ack.v1'

const TONE_DOT: Record<BriefingTone, string> = {
  signal: 'bg-glow [box-shadow:0_0_8px_rgba(96,165,250,0.9)]',
  warn: 'bg-warn',
  danger: 'bg-danger',
}

function compiledLabel(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `· compiled ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

export function MorningBriefing() {
  const navigate = useNavigate()
  const { session } = useAuth()
  const [acked, setAcked] = useState<boolean>(() => {
    try {
      return localStorage.getItem(ACK_KEY) === new Date().toDateString()
    } catch {
      return false
    }
  })

  const token = session?.access_token
  // Deliberately two-state, not four: this is the one surface where silence IS
  // the design (a briefing that can't compile, or has nothing to say, renders
  // nothing). retry: false — never hammer a quiet card.
  const { data: briefing } = useQuery({
    queryKey: queryKeys.briefing,
    queryFn: ({ signal }) => fetchBriefing(token!, signal),
    enabled: !!token && !acked,
    retry: false,
    staleTime: 5 * 60_000,
  })

  if (acked || !briefing || briefing.items.length === 0) return null

  const dismiss = () => {
    try {
      localStorage.setItem(ACK_KEY, new Date().toDateString())
    } catch { /* private mode — the card simply returns tomorrow */ }
    setAcked(true)
  }

  const n = briefing.items.length
  return (
    <section
      aria-label="Morning briefing"
      className="cq-rise-slow mb-4 overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-2.5">
          <Icon name="sparkle" size={13} className="text-glow" />
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
            Morning briefing
          </span>
          <span className="font-mono text-[10px] tabular-nums text-faint">
            {compiledLabel(briefing.compiled_at)}
          </span>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="flex items-center gap-1.5 rounded-control px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-faint transition-colors hover:bg-raised hover:text-muted"
        >
          <Icon name="check" size={12} />
          Read
        </button>
      </div>

      <p className="px-5 pt-4 text-[15px] text-ink">
        {n} {n === 1 ? 'thing' : 'things'} changed overnight.
      </p>

      <ul className="list-none px-2 pb-2 pt-2">
        {briefing.items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => navigate(item.href)}
              className="group flex w-full items-start gap-3 rounded-control px-3 py-2.5 text-left transition-colors hover:bg-raised"
            >
              <span
                aria-hidden
                className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[item.tone] ?? TONE_DOT.signal}`}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-ink">{item.headline}</span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted">{item.detail}</span>
              </span>
              <span className="flex shrink-0 items-center gap-1 pt-0.5 text-xs text-faint transition-colors group-hover:text-glow">
                {item.cta}
                <Icon name="arrowRight" size={12} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
