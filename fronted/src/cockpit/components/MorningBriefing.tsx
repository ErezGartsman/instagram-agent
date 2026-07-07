import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from './Icon'

/**
 * Morning briefing — the cockpit's proactive "push" surface (2026-07-07).
 *
 * The Command screen's widgets all ANSWER questions; this card is the one
 * surface that SPEAKS FIRST. It compiles what changed overnight into three
 * quiet lines — each one click away from the work it describes — and then
 * gets out of the way: acknowledging it collapses it for the rest of the day
 * (localStorage, keyed by date).
 *
 * FRONTEND-ONLY for now. The briefing content is a DEV-gated mock (dead-code-
 * eliminated from production builds, same discipline as SAMPLE_QUEUE — until
 * the backend ships the card simply never renders in prod). Intended contract:
 *   GET /api/cockpit/briefing → { compiled_at, items: [{ tone, headline, detail, href }] }
 */

type Tone = 'signal' | 'warn' | 'danger'

type BriefingItem = {
  id: string
  tone: Tone
  headline: string
  detail: string
  href: string
  cta: string
}

const ACK_KEY = 'nexus.briefing.ack.v1'

const MOCK_BRIEFING: BriefingItem[] = import.meta.env.DEV
  ? [
      {
        id: 'b1',
        tone: 'signal',
        headline: 'Maya reopened after 3 weeks of silence',
        detail: 'Returned unprompted at 23:40 and re-read the booking page. Every signal reads as ready.',
        href: '/app/person/p1',
        cta: 'Open dossier',
      },
      {
        id: 'b2',
        tone: 'warn',
        headline: "Daniel's reply sentiment dropped",
        detail: 'His last two replies shortened and cooled. Re-engage before the door closes.',
        href: '/app/queue?focus=q2',
        cta: 'Open in queue',
      },
      {
        id: 'b3',
        tone: 'danger',
        headline: '2 SLA breaches approaching before noon',
        detail: 'Maya and Daniel both cross their response targets this morning.',
        href: '/app/queue',
        cta: 'Open the queue',
      },
    ]
  : []

const TONE_DOT: Record<Tone, string> = {
  signal: 'bg-glow [box-shadow:0_0_8px_rgba(96,165,250,0.9)]',
  warn: 'bg-warn',
  danger: 'bg-danger',
}

export function MorningBriefing() {
  const navigate = useNavigate()
  const [acked, setAcked] = useState<boolean>(() => {
    try {
      return localStorage.getItem(ACK_KEY) === new Date().toDateString()
    } catch {
      return false
    }
  })

  if (acked || MOCK_BRIEFING.length === 0) return null

  const dismiss = () => {
    try {
      localStorage.setItem(ACK_KEY, new Date().toDateString())
    } catch { /* private mode — the card simply returns tomorrow */ }
    setAcked(true)
  }

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
          <span className="font-mono text-[10px] tabular-nums text-faint">· compiled 07:00</span>
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
        {MOCK_BRIEFING.length} things changed overnight.
      </p>

      <ul className="list-none px-2 pb-2 pt-2">
        {MOCK_BRIEFING.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => navigate(item.href)}
              className="group flex w-full items-start gap-3 rounded-control px-3 py-2.5 text-left transition-colors hover:bg-raised"
            >
              <span
                aria-hidden
                className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[item.tone]}`}
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
