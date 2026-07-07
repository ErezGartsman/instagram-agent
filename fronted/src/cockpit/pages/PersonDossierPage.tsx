import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError } from '../components/SurfaceStates'
import { useAuth } from '../auth/AuthProvider'
import {
  askScopedMemory, DossierNotFound, fetchDossier, fmtDay,
  type DossierChapter, type DossierData, type DossierTimelineEvent,
  type ScopedChatTurn, type TrajectoryPoint,
} from '../lib/dossier'

/**
 * Person Dossier — the deep memory view (live since Phase 3). "Held, not filed."
 *
 * The Work Queue answers "what's my next move"; this route answers "who is
 * this person, really". One payload (GET /api/cockpit/person/:id/dossier):
 *   1. Relationship trajectory — session urgency mapped to [-1, +1], calm
 *      positive (inline SVG, no chart lib on this route).
 *   2. Timeline chapters — the story the formation cron has already written
 *      (session_summaries grouped into weekly chapters; silences become
 *      "Went quiet" chapters — assembled in nexus/dossier.py).
 *   3. Signal log — the raw interaction timeline.
 *   4. Scoped chat — the live planner seam (/api/cockpit/ai/chat) with a
 *      person chip, so answers are grounded in THIS person's held memory.
 */

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'empty' }
  | { kind: 'ready'; data: DossierData }

export function PersonDossierPage() {
  const { id } = useParams()
  const { session } = useAuth()
  const token = session?.access_token
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const retry = useCallback(() => {
    setState({ kind: 'loading' })
    setRetryNonce((x) => x + 1)
  }, [])

  useEffect(() => {
    if (!id || !token) {
      setState({ kind: 'empty' })
      return
    }
    const ctrl = new AbortController()
    setState({ kind: 'loading' })
    fetchDossier(token, id, ctrl.signal)
      .then((data) => setState({ kind: 'ready', data }))
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name === 'AbortError') return
        setState(err instanceof DossierNotFound ? { kind: 'empty' } : { kind: 'error' })
      })
    return () => ctrl.abort()
  }, [id, token, retryNonce])

  if (state.kind === 'loading') {
    return (
      <div className="mx-auto max-w-[1360px]">
        <SurfaceLoading variant="grid" />
      </div>
    )
  }
  if (state.kind === 'error') {
    return (
      <div className="mx-auto max-w-[1360px]">
        <SurfaceError
          title="Couldn't open the dossier"
          body="The memory spine couldn't be reached. Check your connection and try again."
          onRetry={retry}
        />
      </div>
    )
  }
  if (state.kind === 'empty') return <DossierEmpty />

  const { person, chapters, trajectory, timeline } = state.data
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
          {person.initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="text-2xl font-medium leading-tight text-ink">{person.name}</h2>
            {person.stage && (
              <span className="rounded-full bg-accent/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-glow">
                {person.stage}
              </span>
            )}
          </div>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-faint">
            {person.channel ?? '—'}{person.handle ? ` · ${person.handle}` : ''}
            <span className="mx-1">·</span> held since {fmtDay(person.held_since)}
          </p>
          {/* font-serif = the sanctioned lead-essence voice (same object as the
              queue essence line — the one human line in the machine). */}
          {person.essence && (
            <p
              dir="ltr"
              className="mt-3 max-w-xl border-l-2 border-accent/60 pl-3 text-left font-serif text-[17px] font-light italic leading-snug text-muted"
            >
              {person.essence}
            </p>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* ── Left: trajectory + chapters ─────────────────────────────────────── */}
        <div className="flex flex-col gap-4 xl:col-span-8">
          {trajectory.length >= 2 && (
            <TrajectoryPanel trajectory={trajectory} chapters={chapters} />
          )}
          <ChaptersPanel chapters={chapters} />
        </div>

        {/* ── Right: the held facts + signal log + scoped chat ────────────────── */}
        <div className="flex flex-col gap-4 xl:col-span-4">
          <FactsPanel data={state.data} />
          {timeline.length > 0 && <SignalLogPanel timeline={timeline} />}
          <ScopedChat token={token!} personName={person.name} />
        </div>
      </div>
    </div>
  )
}

// ── Empty state (unknown person / no dossier formed yet) ───────────────────────

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
// Backend semantics (nexus/dossier.py): session urgency → [-1, +1], calm
// positive. A rising line = the person is settling; falling = strain.

const W = 100
const H = 44
const MID = H / 2
const AMP = 17 // px of half-height a full |1.0| reading reaches

function TrajectoryPanel({ trajectory, chapters }: {
  trajectory: TrajectoryPoint[]
  chapters: DossierChapter[]
}) {
  const x = (i: number) => (i / (trajectory.length - 1)) * W
  const y = (v: number) => MID - Math.max(-1, Math.min(1, v)) * AMP
  const coords = trajectory.map((p, i) => [x(i), y(p.value)] as const)
  const line = coords.map(([cx, cy], i) => `${i ? 'L' : 'M'}${cx.toFixed(1)},${cy.toFixed(1)}`).join(' ')
  const last = coords[coords.length - 1]
  const current = trajectory[trajectory.length - 1]

  // Anchor each dated chapter to the first trajectory point at/after it.
  const markers = chapters
    .map((c) => {
      if (!c.at) return null
      const idx = trajectory.findIndex((p) => p.at !== null && p.at >= c.at!)
      return idx === -1 ? null : coords[idx]
    })
    .filter((m): m is readonly [number, number] => m !== null)

  return (
    <Panel
      label="Relationship trajectory"
      right={
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[9px] tabular-nums ${
            current.value >= 0 ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'
          }`}
        >
          {current.value >= 0 ? 'settling' : 'strained'} · {current.value >= 0 ? '+' : ''}
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
          {markers.map(([cx, cy], i) => (
            <circle key={i} cx={cx} cy={cy} r="1.6" fill="#04070f" stroke="#60a5fa" strokeWidth="1.1" vectorEffect="non-scaling-stroke" />
          ))}
          {/* now: the single sanctioned glow */}
          <circle cx={last[0]} cy={last[1]} r="2.2" fill="#60a5fa" style={{ filter: 'drop-shadow(0 0 3px rgba(96,165,250,0.9))' }} />
        </svg>
        <div className="mt-1.5 flex justify-between font-mono text-[9px] tabular-nums text-faint">
          {trajectory.map((p, i) =>
            // first, last, and every other label — keeps the axis quiet
            i === 0 || i === trajectory.length - 1 || i % 2 === 0 ? (
              <span key={`${p.label}-${i}`}>{p.label}</span>
            ) : (
              <span key={`${p.label}-${i}`} aria-hidden className="opacity-0">·</span>
            ),
          )}
        </div>
      </div>
    </Panel>
  )
}

// ── 2. Timeline chapters ───────────────────────────────────────────────────────

function ChaptersPanel({ chapters }: { chapters: DossierChapter[] }) {
  if (chapters.length === 0) {
    return (
      <Panel label="The story so far">
        <p className="mt-3 text-sm leading-relaxed text-muted">
          No chapters yet — the memory cron writes the first one after their
          first real conversation settles.
        </p>
      </Panel>
    )
  }
  return (
    <Panel
      label="The story so far"
      right={<span className="font-mono text-[10px] tabular-nums text-faint">{chapters.length} chapters</span>}
    >
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
              <h3 dir="auto" className={`mt-1 text-[15px] font-medium ${isNow ? 'text-glow' : 'text-ink'}`}>
                {c.title}
              </h3>
              {c.summary && (
                <p dir="auto" className="mt-1.5 max-w-prose text-sm leading-relaxed text-muted">
                  {c.summary}
                </p>
              )}
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

function FactsPanel({ data }: { data: DossierData }) {
  const { person } = data
  return (
    <Panel label="Person 360">
      <dl className="mt-3 flex flex-col gap-3" dir="ltr">
        <Fact term="Goal" detail={person.goal ?? '—'} />
        <Fact term="Tension" detail={person.tension ?? '—'} />
        <Fact
          term="Channel"
          detail={person.channel ? `${person.channel}${person.handle ? ` · ${person.handle}` : ''}` : '—'}
          mono
        />
        <Fact term="Held since" detail={fmtDay(person.held_since)} mono />
      </dl>
      <p className="mt-4 border-t border-line pt-3 font-mono text-[10px] text-faint">
        Held, not filed — {person.memory_count} {person.memory_count === 1 ? 'item' : 'items'} in living memory.
      </p>
    </Panel>
  )
}

function Fact({ term, detail, mono = false }: { term: string; detail: string; mono?: boolean }) {
  return (
    <div className="text-left">
      <dt className="font-mono text-[9px] uppercase tracking-wider text-faint">{term}</dt>
      <dd dir="auto" className={`mt-0.5 text-sm text-ink ${mono ? 'font-mono text-[12px] tabular-nums' : ''}`}>
        {detail}
      </dd>
    </div>
  )
}

// ── 3b. Signal log — the raw interaction timeline ──────────────────────────────

function SignalLogPanel({ timeline }: { timeline: DossierTimelineEvent[] }) {
  return (
    <Panel
      label="Signal log"
      right={<span className="font-mono text-[10px] tabular-nums text-faint">{timeline.length} signals</span>}
    >
      <ul className="mt-3 flex list-none flex-col gap-2">
        {timeline.slice(0, 8).map((e, i) => (
          <li key={`${e.kind}-${e.at ?? i}`} className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate text-xs text-muted">{e.label}</span>
            <span className="shrink-0 font-mono text-[9px] tabular-nums text-faint">{fmtDay(e.at)}</span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

// ── 4. Scoped AI chat — live planner seam, person-scoped ───────────────────────

function ScopedChat({ token, personName }: { token: string; personName: string }) {
  const [messages, setMessages] = useState<ScopedChatTurn[]>([])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const firstName = personName.split(' ')[0]

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, thinking])

  const send = (e: FormEvent) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || thinking) return
    const history = messages
    setMessages((m) => [...m, { role: 'user', text }])
    setInput('')
    setThinking(true)
    askScopedMemory(token, personName, text, history)
      .then((reply) => setMessages((m) => [...m, { role: 'ai', text: reply }]))
      .catch(() => setMessages((m) => [
        ...m,
        { role: 'ai', text: "The memory couldn't be reached just now — try again in a moment." },
      ]))
      .finally(() => setThinking(false))
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
          scoped to {firstName}
        </span>
      </div>

      <div ref={scrollRef} className="flex max-h-72 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !thinking && (
          <p className="self-start text-xs leading-relaxed text-faint">
            Ask anything about {firstName} — answers come from their held memory only.
          </p>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <p key={i} className="ml-8 self-end rounded-card rounded-br-sm bg-accent/15 px-3 py-2 text-sm text-ink">
              {m.text}
            </p>
          ) : (
            <div key={i} className="cq-crystallize mr-4 self-start">
              <p dir="auto" className="whitespace-pre-wrap rounded-card rounded-bl-sm bg-raised px-3 py-2 text-sm leading-relaxed text-ink">
                {m.text}
              </p>
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
          placeholder={`Ask about ${firstName}…`}
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
