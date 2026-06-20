import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { Icon } from '../components/Icon'
import { useAuth } from '../auth/AuthProvider'
import { CHANNEL_LABELS, relativeTime } from '../lib/pipeline'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from '../lib/workqueue'

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; items: QueueItem[]; sample: boolean }

/**
 * Ticket 5.2 — the 3-pane Work Queue, the core of the Decision Engine.
 *
 * Graphite Atelier in motion: a dense, ranked queue on the left (the precision
 * instrument), and — on selection — a spotlit conversation thread and a
 * memory-first Person-360 (the sanctuary). The "one-thing" mechanic dims every
 * unselected row to let the chosen person take the light.
 */
export function WorkQueuePage() {
  const { session, devBypass } = useAuth()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (devBypass) {
      setState({ kind: 'ready', items: SAMPLE_QUEUE, sample: true })
      setSelectedId((id) => id ?? SAMPLE_QUEUE[0]?.id ?? null)
      return
    }
    const token = session?.access_token
    if (!token) {
      setState({ kind: 'loading' })
      return
    }
    const controller = new AbortController()
    setState({ kind: 'loading' })
    fetchQueue(token, controller.signal)
      .then((items) => {
        const ranked = rankQueue(items)
        setState({ kind: 'ready', items: ranked, sample: false })
        setSelectedId((id) => id ?? ranked[0]?.id ?? null)
      })
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [session?.access_token, devBypass])

  if (state.kind === 'loading') return <QueueSkeleton />
  if (state.kind === 'error') return <QueueError />
  if (state.items.length === 0) return <QueueEmpty />

  return (
    <Board
      items={state.items}
      sample={state.sample}
      selectedId={selectedId ?? state.items[0].id}
      onSelect={setSelectedId}
    />
  )
}

function Board({
  items,
  sample,
  selectedId,
  onSelect,
}: {
  items: QueueItem[]
  sample: boolean
  selectedId: string
  onSelect: (id: string) => void
}) {
  const [acted, setActed] = useState(false)
  const actTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) ?? items[0],
    [items, selectedId],
  )
  const topId = items[0]?.id

  useEffect(() => setActed(false), [selectedId])
  useEffect(() => () => { if (actTimer.current) clearTimeout(actTimer.current) }, [])

  const move = useCallback(
    (delta: number) => {
      const idx = items.findIndex((i) => i.id === selected.id)
      const next = items[Math.min(items.length - 1, Math.max(0, idx + delta))]
      if (next) onSelect(next.id)
    },
    [items, selected.id, onSelect],
  )

  // Work the queue: acknowledge the suggested action, then advance to the next.
  const onSend = useCallback(() => {
    if (acted) return
    setActed(true)
    actTimer.current = setTimeout(() => move(1), 1100)
  }, [acted, move])

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
    else if (e.key === 'Enter') { e.preventDefault(); onSend() }
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden rounded-card border border-line bg-bg">
      {/* ── Left: the precision instrument — a dense, ranked queue ───────────── */}
      <section
        aria-label="Work queue"
        tabIndex={0}
        onKeyDown={onKeyDown}
        className="flex w-[300px] shrink-0 flex-col border-r border-line bg-surface outline-none"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Work queue</span>
          <div className="flex items-center gap-2">
            {sample && (
              <span className="rounded-control border border-line px-1.5 py-px text-[10px] text-warn">sample</span>
            )}
            <span className="font-mono text-xs tabular-nums text-muted">{items.length}</span>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {items.map((item) => (
            <QueueRow
              key={item.id}
              item={item}
              isSelected={item.id === selected.id}
              isTop={item.id === topId}
              onSelect={() => onSelect(item.id)}
            />
          ))}
        </div>

        <div className="border-t border-line px-4 py-2.5">
          <span className="font-mono text-[10px] text-faint">↑↓ navigate · ↵ send · ranked by priority</span>
        </div>
      </section>

      {/* ── Center: the spotlight — the conversation thread ─────────────────── */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div key={selected.id} className="cq-rise border-b border-line px-6 py-4">
          <div className="text-base font-medium text-ink">{selected.name}</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-sage" aria-hidden />
            <span className="font-mono text-xs text-muted">
              {selected.channel ? (CHANNEL_LABELS[selected.channel] ?? selected.channel) : '—'}
              {selected.handle ? ` · ${selected.handle}` : ''}
            </span>
          </div>
        </div>

        <div key={`${selected.id}:thread`} className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-6 py-5">
          {selected.thread.map((m, i) => (
            <div
              key={i}
              className={`cq-rise max-w-[78%] rounded-card px-3.5 py-2.5 text-sm leading-relaxed ${
                m.from === 'them'
                  ? 'self-start rounded-bl-sm bg-raised text-ink'
                  : 'self-end rounded-br-sm bg-accent/12 text-ink'
              }`}
              style={{ animationDelay: `${i * 45}ms` }}
            >
              {m.text}
            </div>
          ))}
        </div>

        {/* The trust trio: Action · Confidence · Reason. */}
        <div className="border-t border-line px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Suggested action</div>
              <div className="mt-1 text-sm text-ink">{selected.action}</div>
            </div>
            <button
              onClick={onSend}
              aria-label={`Send: ${selected.action}`}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-control border border-accent/40 px-3 py-1.5 text-xs text-accent transition-colors hover:bg-accent/10"
            >
              {acted ? (
                <><Icon name="check" size={13} /> Sent</>
              ) : (
                <>Send <Icon name="arrowRight" size={13} /></>
              )}
            </button>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-muted">Confidence</span>
            <span className="h-[3px] flex-1 overflow-hidden rounded-full bg-ink/10">
              <span
                key={selected.id}
                className="cq-grow block h-full rounded-full bg-accent"
                style={{ '--w': `${selected.confidence}%` } as CSSProperties}
              />
            </span>
            <span className="font-mono text-xs tabular-nums text-accent">{selected.confidence}%</span>
          </div>

          <div className="mt-2 text-xs leading-relaxed text-muted">
            <span className="text-faint">Reason · </span>
            {selected.reason}
          </div>
        </div>
      </section>

      {/* ── Right: the sanctuary — memory-first Person-360 ──────────────────── */}
      <aside
        aria-label="Memory"
        className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-l border-line px-5 py-5"
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Memory</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">360°</span>
        </div>

        <div key={selected.id} className="cq-rise-slow">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-accent/12 font-mono text-xs font-medium text-accent">
              {selected.initials}
            </span>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-ink">{selected.name}</div>
              <div className="font-mono text-[10px] text-faint">first contact · {selected.firstContactAgo}</div>
            </div>
          </div>

          {/* The human voice — the one place Fraunces speaks. */}
          <p className="border-l-2 border-accent pl-3.5 font-serif text-[17px] font-light leading-snug text-ink">
            {selected.essence}
          </p>

          <div className="my-4 h-px bg-line" />

          <Fact label="Goal" value={selected.goal} />
          <Fact label="Tension" value={selected.tension} />
          <Fact label="Last contact" value={relativeTime(selected.last_contacted)} mono />
        </div>
      </aside>
    </div>
  )
}

function QueueRow({
  item,
  isSelected,
  isTop,
  onSelect,
}: {
  item: QueueItem
  isSelected: boolean
  isTop: boolean
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      aria-current={isSelected ? 'true' : undefined}
      className={`relative mb-0.5 flex w-full items-start gap-2.5 rounded-control py-2.5 pl-3.5 pr-2.5 text-left transition-[opacity,background-color] duration-[260ms] ${
        isSelected ? 'bg-raised opacity-100' : 'opacity-40 hover:opacity-100'
      }`}
    >
      <span
        aria-hidden
        className={`absolute left-0 top-1/2 h-7 w-0.5 -translate-y-1/2 rounded-full bg-accent transition-opacity duration-200 ${
          isSelected ? 'opacity-100' : 'opacity-0'
        }`}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ink">{item.name}</span>
          {isTop && (
            <span className="shrink-0 rounded bg-accent/15 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-accent">
              Next
            </span>
          )}
        </span>
        <span className="mt-0.5 line-clamp-1 text-xs text-muted">{item.teaser}</span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-0.5">
        <span className="font-mono text-xs tabular-nums text-muted">{item.confidence}%</span>
        <span className="font-mono text-[10px] text-faint">{relativeTime(item.last_contacted)}</span>
      </span>
    </button>
  )
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="mt-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{label}</div>
      <div className={`mt-1 text-sm leading-relaxed text-ink ${mono ? 'font-mono text-[13px]' : ''}`}>{value}</div>
    </div>
  )
}

function QueueSkeleton() {
  return (
    <div className="flex h-full min-h-0 overflow-hidden rounded-card border border-line bg-bg" aria-hidden>
      <div className="w-[300px] shrink-0 border-r border-line bg-surface p-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="mb-1 h-14 animate-pulse rounded-control bg-raised/60" />
        ))}
      </div>
      <div className="flex-1 p-6">
        <div className="h-5 w-40 animate-pulse rounded-control bg-surface" />
      </div>
      <div className="w-[300px] shrink-0 border-l border-line p-5">
        <div className="h-20 animate-pulse rounded-card bg-surface" />
      </div>
    </div>
  )
}

function QueueError() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-card border border-line bg-surface px-8 text-center">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-danger">
        <Icon name="alert" size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">Couldn&rsquo;t load the queue</h3>
      <p className="mt-2 max-w-md text-sm text-muted">
        The work queue couldn&rsquo;t be reached. Check your connection and reload.
      </p>
    </div>
  )
}

function QueueEmpty() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-card border border-line bg-surface px-8 text-center">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-success">
        <Icon name="check" size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">Queue clear</h3>
      <p className="mt-2 max-w-md text-sm text-muted">No one is waiting on a next move right now.</p>
    </div>
  )
}
