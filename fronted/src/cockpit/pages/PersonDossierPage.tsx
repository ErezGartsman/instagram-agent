import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'

/**
 * Person Dossier — the deep memory view (2026-07-07). "Held, not filed."
 *
 * The Work Queue answers "what's my next move"; this route answers "who is
 * this person, really". Three instruments:
 *   1. Relationship trajectory — one sentiment line across the whole arc,
 *      chapter markers included (inline SVG, no chart lib on this route).
 *   2. Timeline chapters — the AI-summarized story ("Week 1: reached out
 *      about trust…"), not a raw event log. Chapters are the memory spine's
 *      narrative summaries, one glance per era.
 *   3. Scoped chat — ask the memory questions about THIS person only.
 *
 * FRONTEND-ONLY for now. The dossier below is a DEV-gated mock (dead-code-
 * eliminated from prod, same discipline as SAMPLE_QUEUE); in production the
 * route shows the "no dossier formed yet" state until the backend ships
 *   GET /api/cockpit/person/:id/dossier
 * The scoped chat renders the full layout with a canned reply — the live
 * planner (ai_planner.py) will take the seam over unchanged.
 */

// ── Types (the intended API contract, verbatim) ────────────────────────────────

type Chapter = {
  id: string
  range: string
  title: string
  summary: string
  signals: string[]
  /** Index into `sentiment` where this chapter begins — anchors the marker. */
  at: number
}

type SentimentPoint = { label: string; value: number } // value ∈ [-1, 1]

type ChatMsg = { role: 'user' | 'ai'; text: string; cite?: string }

type Dossier = {
  personId: string
  name: string
  initials: string
  channel: string
  handle: string
  heldSince: string
  stage: string
  memoryCount: number
  essence: string
  goal: string
  tension: string
  sentiment: SentimentPoint[]
  chapters: Chapter[]
  seedChat: ChatMsg[]
}

// ── Mock: Maya's dossier (DEV-only, mirrors SAMPLE_QUEUE p1) ───────────────────

const DOSSIERS: Record<string, Dossier> = import.meta.env.DEV
  ? {
      p1: {
        personId: 'p1',
        name: 'Maya Goren',
        initials: 'MG',
        channel: 'whatsapp',
        handle: 'BR-1188',
        heldSince: 'Jun 8',
        stage: 'Ready to book',
        memoryCount: 42,
        essence: "She isn't afraid of leaving. She's afraid of being the one who broke it.",
        goal: 'Decide before the anniversary, Jul 2',
        tension: 'Guilt vs. relief',
        sentiment: [
          { label: 'Jun 8', value: 0.15 },
          { label: 'Jun 12', value: 0.3 },
          { label: 'Jun 16', value: 0.55 },
          { label: 'Jun 20', value: 0.6 },
          { label: 'Jun 24', value: 0.2 },
          { label: 'Jun 29', value: -0.15 },
          { label: 'Jul 3', value: -0.2 },
          { label: 'Jul 6', value: 0.62 },
        ],
        chapters: [
          {
            id: 'c1',
            range: 'Week 1 · Jun 8–14',
            title: 'Reached out about trust',
            summary:
              'First contact through the WhatsApp line. The fights had stopped and the silence had started — and she named the anniversary, Jul 2, as her deadline for deciding.',
            signals: ['Started a conversation', 'Shared her context'],
            at: 0,
          },
          {
            id: 'c2',
            range: 'Week 2 · Jun 15–21',
            title: 'Named the real fear',
            summary:
              "Moved past logistics to the actual question: not whether to leave, but whether she could live with being the one who broke it. Saying it out loud lifted her — sentiment climbed all week. Qualified.",
            signals: ['Qualified', 'Sentiment rising'],
            at: 2,
          },
          {
            id: 'c3',
            range: 'Weeks 3–5 · Jun 22 – Jul 5',
            title: 'Went quiet',
            summary:
              'Three weeks of silence — the anniversary itself passed inside it. Two gentle nudges went unanswered. The trajectory drifted, but never dropped to cold: she read everything.',
            signals: ['2 nudges · no reply', 'Anniversary passed Jul 2'],
            at: 4,
          },
          {
            id: 'c4',
            range: 'Last night · Jul 6, 23:40',
            title: 'Reopened',
            summary:
              'Returned unprompted four days after the deadline she set for herself. Clicked the outreach link and re-read the booking page twice. The deadline expired; the decision didn’t. The move is yours.',
            signals: ['Outreach click', 'Booking page × 2'],
            at: 7,
          },
        ],
        seedChat: [
          { role: 'user', text: 'What changed while she was quiet?' },
          {
            role: 'ai',
            text:
              'Nothing inbound for 21 days — but she never disengaged. The anniversary she set as her deadline (Jul 2) passed during the silence, and she came back four days after it. The deadline expired; the decision didn’t.',
            cite: 'Weeks 3–5 · 2 signals',
          },
        ],
      },
    }
  : {}

// The canned reply keeps the layout honest about what's live in preview.
const CANNED_REPLY: ChatMsg = {
  role: 'ai',
  text:
    'Scoped memory is mocked in this preview — once the dossier endpoint ships, this chat answers from her held items only, with citations into the chapters above.',
  cite: 'Preview',
}

// ── Page ───────────────────────────────────────────────────────────────────────

export function PersonDossierPage() {
  const { id } = useParams()
  const dossier = id ? DOSSIERS[id] : undefined

  if (!dossier) return <DossierEmpty />

  return (
    <div className="mx-auto max-w-[1360px]">
      <Link
        to="/app"
        className="mb-5 inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-faint transition-colors hover:text-muted"
      >
        <Icon name="arrowRight" size={12} className="rotate-180" />
        Command
      </Link>

      {/* ── Identity header ─────────────────────────────────────────────────── */}
      <header className="cq-rise mb-6 flex flex-wrap items-start gap-4">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-accent/12 font-mono text-sm font-medium text-glow">
          {dossier.initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-2xl font-medium leading-tight text-ink">{dossier.name}</h2>
            <span className="rounded-full bg-accent/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-glow">
              {dossier.stage}
            </span>
          </div>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-faint">
            {dossier.channel} · {dossier.handle} <span className="mx-1">·</span> held since {dossier.heldSince}
          </p>
          {/* font-serif = the sanctioned lead-essence voice (same object as the
              queue essence line — the one human line in the machine). */}
          <p className="mt-3 max-w-xl border-l-2 border-accent/60 pl-3 font-serif text-[17px] font-light italic leading-snug text-muted">
            {dossier.essence}
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* ── Left: trajectory + chapters ─────────────────────────────────────── */}
        <div className="flex flex-col gap-4 xl:col-span-8">
          <TrajectoryPanel sentiment={dossier.sentiment} chapters={dossier.chapters} />
          <ChaptersPanel chapters={dossier.chapters} />
        </div>

        {/* ── Right: the held facts + scoped chat ─────────────────────────────── */}
        <div className="flex flex-col gap-4 xl:col-span-4">
          <FactsPanel dossier={dossier} />
          <ScopedChat dossier={dossier} />
        </div>
      </div>
    </div>
  )
}

// ── Empty state (prod until the backend ships; unknown ids in dev) ─────────────

function DossierEmpty() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center pt-24 text-center">
      <Icon name="inbox" size={22} className="text-faint" />
      <h2 className="mt-4 text-lg font-medium text-ink">No dossier has formed yet</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        The memory spine builds a dossier once a person has enough held signals. Until then,
        their story lives in the queue.
      </p>
      <Link
        to="/app/queue"
        className="mt-5 inline-flex items-center gap-1.5 text-sm text-glow transition-opacity hover:opacity-80"
      >
        Open the work queue <Icon name="arrowRight" size={13} />
      </Link>
    </div>
  )
}

// ── Shared bits ────────────────────────────────────────────────────────────────

function PanelLabel({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{children}</span>
}

function Panel({ label, right, children }: { label: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section
      aria-label={label}
      className="rounded-card border border-line bg-surface p-5 backdrop-blur-xl [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-center justify-between">
        <PanelLabel>{label}</PanelLabel>
        {right}
      </div>
      {children}
    </section>
  )
}

// ── 1. Relationship trajectory ─────────────────────────────────────────────────

const W = 100
const H = 44
const MID = H / 2
const AMP = 17 // px of half-height a full |1.0| sentiment reaches

function TrajectoryPanel({ sentiment, chapters }: { sentiment: SentimentPoint[]; chapters: Chapter[] }) {
  const x = (i: number) => (i / (sentiment.length - 1)) * W
  const y = (v: number) => MID - v * AMP
  const coords = sentiment.map((p, i) => [x(i), y(p.value)] as const)
  const line = coords.map(([cx, cy], i) => `${i ? 'L' : 'M'}${cx.toFixed(1)},${cy.toFixed(1)}`).join(' ')
  const last = coords[coords.length - 1]
  const current = sentiment[sentiment.length - 1]

  return (
    <Panel
      label="Relationship trajectory"
      right={
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[9px] tabular-nums ${
            current.value >= 0 ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'
          }`}
        >
          {current.value >= 0 ? 'warming' : 'cooling'} · {current.value >= 0 ? '+' : ''}
          {current.value.toFixed(2)}
        </span>
      }
    >
      <div className="mt-3">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-32 w-full" aria-hidden>
          {/* neutral baseline */}
          <line x1="0" y1={MID} x2={W} y2={MID} stroke="rgba(148,186,255,0.14)" strokeWidth="1" strokeDasharray="1.5 2.5" vectorEffect="non-scaling-stroke" />
          {/* area under the arc */}
          <path d={`${line} L${W},${H} L0,${H} Z`} fill="rgba(59,130,246,0.09)" />
          {/* the arc itself */}
          <path d={line} fill="none" stroke="#60a5fa" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          {/* chapter markers */}
          {chapters.map((c) => {
            const [cx, cy] = coords[Math.min(c.at, coords.length - 1)]
            return <circle key={c.id} cx={cx} cy={cy} r="1.6" fill="#04070f" stroke="#60a5fa" strokeWidth="1.1" vectorEffect="non-scaling-stroke" />
          })}
          {/* now: the single sanctioned glow */}
          <circle cx={last[0]} cy={last[1]} r="2.2" fill="#60a5fa" style={{ filter: 'drop-shadow(0 0 3px rgba(96,165,250,0.9))' }} />
        </svg>
        <div className="mt-1.5 flex justify-between font-mono text-[9px] tabular-nums text-faint">
          {sentiment.map((p, i) =>
            // first, last, and every other label — keeps the axis quiet
            i === 0 || i === sentiment.length - 1 || i % 2 === 0 ? (
              <span key={p.label}>{p.label}</span>
            ) : (
              <span key={p.label} aria-hidden className="opacity-0">·</span>
            ),
          )}
        </div>
      </div>
    </Panel>
  )
}

// ── 2. Timeline chapters ───────────────────────────────────────────────────────

function ChaptersPanel({ chapters }: { chapters: Chapter[] }) {
  return (
    <Panel label="The story so far" right={<span className="font-mono text-[10px] tabular-nums text-faint">{chapters.length} chapters</span>}>
      <ol className="relative mt-4 flex list-none flex-col">
        {/* the thread */}
        <span aria-hidden className="absolute bottom-3 left-[5px] top-2 w-px bg-line" />
        {chapters.map((c, i) => {
          const isNow = i === chapters.length - 1
          return (
            <li key={c.id} className="relative pb-6 pl-6 last:pb-0">
              <span
                aria-hidden
                className={`absolute left-0 top-[5px] h-[11px] w-[11px] rounded-full border ${
                  isNow
                    ? 'border-glow bg-accent/30 [box-shadow:0_0_8px_rgba(96,165,250,0.8)]'
                    : 'border-line bg-raised'
                }`}
              />
              <p className="font-mono text-[10px] uppercase tracking-wider text-faint">{c.range}</p>
              <h3 className={`mt-1 text-[15px] font-medium ${isNow ? 'text-glow' : 'text-ink'}`}>{c.title}</h3>
              <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-muted">{c.summary}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {c.signals.map((s) => (
                  <span key={s} className="rounded-full border border-line bg-raised px-2 py-0.5 font-mono text-[9px] text-faint">
                    {s}
                  </span>
                ))}
              </div>
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

// ── 3. The held facts ──────────────────────────────────────────────────────────

function FactsPanel({ dossier }: { dossier: Dossier }) {
  return (
    <Panel label="Person 360">
      <dl className="mt-3 flex flex-col gap-3" dir="ltr">
        <Fact term="Goal" detail={dossier.goal} />
        <Fact term="Tension" detail={dossier.tension} />
        <Fact term="Channel" detail={`${dossier.channel} · ${dossier.handle}`} mono />
        <Fact term="Held since" detail={dossier.heldSince} mono />
      </dl>
      <p className="mt-4 border-t border-line pt-3 font-mono text-[10px] text-faint">
        Held, not filed — {dossier.memoryCount} items in living memory.
      </p>
    </Panel>
  )
}

function Fact({ term, detail, mono = false }: { term: string; detail: string; mono?: boolean }) {
  return (
    <div className="text-left">
      <dt className="font-mono text-[9px] uppercase tracking-wider text-faint">{term}</dt>
      <dd className={`mt-0.5 text-sm text-ink ${mono ? 'font-mono text-[12px] tabular-nums' : ''}`}>{detail}</dd>
    </div>
  )
}

// ── 4. Scoped AI chat ──────────────────────────────────────────────────────────

function ScopedChat({ dossier }: { dossier: Dossier }) {
  const [messages, setMessages] = useState<ChatMsg[]>(dossier.seedChat)
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, thinking])

  const send = (e: FormEvent) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || thinking) return
    setMessages((m) => [...m, { role: 'user', text }])
    setInput('')
    setThinking(true)
    timerRef.current = setTimeout(() => {
      setMessages((m) => [...m, CANNED_REPLY])
      setThinking(false)
    }, 650)
  }

  return (
    <section
      aria-label="Scoped chat"
      className="flex min-h-[320px] flex-col rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-2">
          <Icon name="sparkle" size={12} className="text-glow" />
          <PanelLabel>Ask the memory</PanelLabel>
        </div>
        <span className="rounded-full bg-accent/12 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-glow">
          scoped to {dossier.name.split(' ')[0]}
        </span>
      </div>

      <div ref={scrollRef} className="flex max-h-72 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <p key={i} className="ml-8 self-end rounded-card rounded-br-sm bg-accent/15 px-3 py-2 text-sm text-ink">
              {m.text}
            </p>
          ) : (
            <div key={i} className="cq-crystallize mr-4 self-start">
              <p className="rounded-card rounded-bl-sm bg-raised px-3 py-2 text-sm leading-relaxed text-ink">{m.text}</p>
              {m.cite && (
                <span className="mt-1.5 inline-block rounded-full border border-line px-2 py-0.5 font-mono text-[9px] text-faint">
                  {m.cite}
                </span>
              )}
            </div>
          ),
        )}
        {thinking && (
          <div className="mr-4 flex w-44 flex-col gap-1.5 self-start rounded-card rounded-bl-sm bg-raised px-3 py-3" aria-label="Thinking">
            <div className="cq-thought-line w-full" />
            <div className="cq-thought-line w-2/3" />
          </div>
        )}
      </div>

      <form onSubmit={send} className="flex items-center gap-2 border-t border-line px-3 py-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={`Ask about ${dossier.name.split(' ')[0]}…`}
          className="min-w-0 flex-1 rounded-control border border-line bg-raised px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-accent/50 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!input.trim() || thinking}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-accent/20 text-glow transition-colors hover:bg-accent/30 disabled:opacity-40"
          aria-label="Send"
        >
          <Icon name="send" size={14} />
        </button>
      </form>
    </section>
  )
}
