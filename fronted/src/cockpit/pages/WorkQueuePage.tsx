import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, MouseEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SurfaceLoading, SurfaceEmpty, SurfaceError } from '../components/SurfaceStates'
import { HotLeadToast } from '../components/HotLeadToast'
import { WhatsAppThread } from '../components/WhatsAppThread'
import { CopilotNudge } from '../components/CopilotNudge'
import { AgentPip } from '../components/AgentPip'
import { AgentActivityFeed } from '../components/AgentActivityFeed'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Icon } from '../components/Icon'
import type { IconName } from '../components/Icon'
import { useAuth } from '../auth/AuthProvider'
import { CHANNEL_LABELS, relativeTime } from '../lib/pipeline'
import { postQueueAction, type QueueActionType, type QueueItem } from '../lib/workqueue'
import { streamDraft } from '../lib/api'
import { useQueueData } from '../lib/useQueueData'
import { useAgentRuns } from '../lib/useAgentRuns'

// Dev-bypass demo draft — dead-code-eliminated in production builds.
// Streams locally when devBypass=true so the fake 'dev-bypass' token never
// reaches the backend (which correctly rejects it with 401).
const DEV_BYPASS_DRAFT: string = import.meta.env.DEV
  ? 'היי מאיה, ארז כאן. קראתי את מה שכתבת ואני מבין — זה לא מקום פשוט להיות בו. יש לי מקום השבוע לשיחה ראשונה, אם בא לך. הנה הלינק לתיאום: '
  : ''
import { useNotifications } from '../lib/useNotifications'

// ── The Action Loop ──────────────────────────────────────────────────────────
// Four moves on a lead, each with its own emotional read encoded in the exit
// direction: a win/send files RIGHT, a dismissal sweeps LEFT, a snooze settles DOWN.
type ActionType = QueueActionType
type ExitDir = 'right' | 'left' | 'down'

const EXIT_DIR: Record<ActionType, ExitDir> = {
  send: 'right',
  done: 'right',
  snooze: 'down',
  dismiss: 'left',
}
const ACTION_VERB: Record<ActionType, string> = {
  send: 'Message sent',
  done: 'Marked done',
  snooze: 'Snoozed',
  dismiss: 'Dismissed',
}

// The optimistic UI commits to the backend only when the undo window closes
// (Gmail-style) — so Undo truly cancels, with no compensating request.
const UNDO_MS = 4500
const DEV_SIMULATE_FAILURE = false // dev-bypass only: flip to exercise the rollback path locally

// Easing tuples (typed so Framer reads them as cubic-bezier, not number[]).
const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]
const EASE_OUT: [number, number, number, number] = [0.4, 0, 0.2, 1]

// Smart default for the Send composer — a personal starter Erez edits before
// sending (never blind auto-send). Contextual to the suggested action.
function draftFor(item: QueueItem): string {
  const first = item.name.split(' ')[0] || 'there'
  const a = (item.action || '').toLowerCase()
  if (a.includes('book')) {
    return `Hi ${first}, ready to find a time that works for you? Here's the link to book: `
  }
  if (a.includes('check') || a.includes('re-engage') || a.includes('nudge') || a.includes('reopen')) {
    return `Hi ${first}, just checking in — how are things going? `
  }
  return `Hi ${first}, `
}

/**
 * Ticket 5.2 — the 3-pane Work Queue, the core of the Decision Engine, with the
 * Action Loop (P0 ①) now wired to the real backend: act on a lead and the card
 * leaves while the next rises. Optimistic + Undo — zero spinners; the actual
 * `POST /api/cockpit/queue/{id}/action` fires when the undo window closes, and a
 * failure rolls the card back. Dev-bypass mocks the call so local UI needs no API.
 */
export function WorkQueuePage() {
  const { session, devBypass } = useAuth()
  const token = session?.access_token ?? null
  const [searchParams] = useSearchParams()
  const focusId = searchParams.get('focus') ?? undefined
  // ?draft=1 — auto-trigger AI drafting on the top lead (from ⌘K "Draft reply" action)
  const autoDraft = searchParams.get('draft') === '1'

  // ── Notifications ─────────────────────────────────────────────────────────
  const { notify } = useNotifications()
  const [hotLead, setHotLead] = useState<QueueItem | null>(null)
  const dismissToast = useCallback(() => setHotLead(null), [])

  const onHotLead = useCallback(
    (item: QueueItem) => {
      setHotLead(item)
      notify(`Hot lead: ${item.name}`, `${item.action} · ${item.confidence}% confidence`)
    },
    [notify],
  )

  // suppressRef: Board sets true while an optimistic action is in flight;
  // the hook reads it before every background setState. Stable ref — no renders.
  const suppressRef = useRef(false)
  const { state, refetch } = useQueueData(token, devBypass, suppressRef, onHotLead)

  // The single seam to the backend. Resolves on success; throws on failure so
  // the Board rolls the card back. Dev-bypass never calls the API.
  const commit = useCallback(
    async (id: string, type: ActionType, message?: string) => {
      if (devBypass || !token) {
        console.log(`[action] ${type} → ${id} (dev mock — backend not called)`)
        if (DEV_SIMULATE_FAILURE) throw new Error('simulated failure')
        return
      }
      await postQueueAction(token, id, type, { message })
    },
    [devBypass, token],
  )

  if (state.kind === 'loading') return <SurfaceLoading variant="queue" />
  if (state.kind === 'error') return (
    <SurfaceError
      title="Couldn't load the queue"
      body="The work queue couldn't be reached. Check your connection and try again."
      onRetry={refetch}
      className="h-full"
    />
  )
  if (state.items.length === 0) return (
    <SurfaceEmpty
      flavor="win"
      title="Queue clear"
      body="No one is waiting on a next move right now."
      copilotSlot={<CopilotNudge />}
      className="h-full"
    />
  )

  return (
    <>
      <HotLeadToast
        item={hotLead}
        onDismiss={dismissToast}
        onView={dismissToast}  // queue is already visible; dismiss is enough
      />
      <Board
        initialItems={state.items}
        liveItems={state.items}
        initialSelectedId={focusId}
        autoDraft={autoDraft}
        sample={state.sample}
        commit={commit}
        suppressRef={suppressRef}
        token={token}
        devBypass={devBypass}
      />
    </>
  )
}

type Toast = { item: QueueItem; index: number; type: ActionType; kind: 'undo' | 'error' }
type Pending = {
  item: QueueItem
  index: number
  type: ActionType
  message?: string
  timer: ReturnType<typeof setTimeout>
}

function Board({
  initialItems,
  liveItems,
  initialSelectedId,
  autoDraft = false,
  sample,
  commit,
  suppressRef,
  token,
  devBypass,
}: {
  initialItems: QueueItem[]
  liveItems: QueueItem[]
  /** From ?focus= URL param — pre-selects a lead navigated to from ⌘K search. */
  initialSelectedId?: string
  /** Auto-trigger AI drafting on mount (from ⌘K "Draft reply" action via ?draft=1). */
  autoDraft?: boolean
  sample: boolean
  commit: (id: string, type: ActionType, message?: string) => Promise<void>
  suppressRef: { current: boolean }
  token: string | null
  devBypass: boolean
}) {
  const reduce = useReducedMotion()
  const [items, setItems] = useState<QueueItem[]>(initialItems)
  const [selectedId, setSelectedId] = useState<string | null>(
    initialSelectedId ?? initialItems[0]?.id ?? null,
  )
  const [exitDir, setExitDir] = useState<ExitDir>('right')
  const [toast, setToast] = useState<Toast | null>(null)
  const [composing, setComposing] = useState(false)
  const [draft, setDraft] = useState('')
  const [drafting, setDrafting] = useState(false)   // true while AI is streaming a draft
  const [centerTab, setCenterTab] = useState<'conversation' | 'agent'>('conversation')

  const pendingRef = useRef<Pending | null>(null)
  const toastHideRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const draftAbortRef = useRef<AbortController | null>(null)
  // Track the last live signature we applied so we don't re-apply the same data.
  const liveSigRef = useRef(liveItems.map((i) => i.id).join(','))

  // Agent runs for the selected person — Realtime-subscribed via Supabase.
  const selectedPersonId = useMemo(
    () => items.find((i) => i.id === selectedId)?.person_id ?? null,
    [items, selectedId],
  )
  const { runs: agentRuns, loading: agentRunsLoading } = useAgentRuns(
    devBypass ? null : selectedPersonId,
    token,
  )

  // Live-sync: apply server updates from background polls when safe.
  // Skips if an action is in flight (suppressRef.current) or data is unchanged.
  useEffect(() => {
    if (suppressRef.current) return
    const sig = liveItems.map((i) => i.id).join(',')
    if (sig === liveSigRef.current) return
    liveSigRef.current = sig
    setItems(liveItems)
    setSelectedId((prev) => liveItems.find((i) => i.id === prev)?.id ?? liveItems[0]?.id ?? null)
  }, [liveItems, suppressRef])

  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) ?? items[0],
    [items, selectedId],
  )
  const topId = items[0]?.id

  const insertAt = (arr: QueueItem[], idx: number, it: QueueItem) => {
    const next = [...arr]
    next.splice(Math.min(idx, next.length), 0, it)
    return next
  }

  // Send the optimistic action to the backend; roll the card back in on failure.
  const runCommit = useCallback(
    (p: Pending) => {
      void commit(p.item.id, p.type, p.message).catch(() => {
        setItems((prev) => (prev.some((i) => i.id === p.item.id) ? prev : insertAt(prev, p.index, p.item)))
        setSelectedId(p.item.id)
        if (toastHideRef.current) clearTimeout(toastHideRef.current)
        setToast({ item: p.item, index: p.index, type: p.type, kind: 'error' })
        toastHideRef.current = setTimeout(() => setToast(null), 4000)
        console.warn(`[action] ✗ ${p.type} → ${p.item.id} failed — restored`)
      })
    },
    [commit],
  )

  // Commit a still-pending move now (a newer action arrived, or we're unmounting),
  // so rapid draining persists every card and nothing is lost on navigate.
  const flushPending = useCallback(() => {
    const p = pendingRef.current
    if (!p) return
    clearTimeout(p.timer)
    pendingRef.current = null
    suppressRef.current = false   // action flushed — polling safe to resume
    runCommit(p)
  }, [runCommit, suppressRef])

  useEffect(
    () => () => {
      flushPending()
      if (toastHideRef.current) clearTimeout(toastHideRef.current)
    },
    [flushPending],
  )

  const move = useCallback(
    (delta: number) => {
      if (!selected) return
      const idx = items.findIndex((i) => i.id === selected.id)
      const next = items[Math.min(items.length - 1, Math.max(0, idx + delta))]
      if (next) setSelectedId(next.id)
    },
    [items, selected],
  )

  // Optimistic: the card leaves instantly; the real write fires when the undo
  // window closes. Side effects stay top-level (not in a state updater) so
  // StrictMode's double-invoke can't double-fire them.
  const act = useCallback(
    (id: string, type: ActionType, message?: string) => {
      const idx = items.findIndex((i) => i.id === id)
      if (idx === -1) return
      const item = items[idx]
      flushPending() // persist any prior pending move first

      setExitDir(EXIT_DIR[type])
      setItems((prev) => prev.filter((i) => i.id !== id))
      setSelectedId((curr) =>
        curr === id ? (items[idx + 1]?.id ?? items[idx - 1]?.id ?? null) : curr,
      )

      if (toastHideRef.current) {
        clearTimeout(toastHideRef.current)
        toastHideRef.current = null
      }
      setToast({ item, index: idx, type, kind: 'undo' })

      const timer = setTimeout(() => {
        const p = pendingRef.current
        pendingRef.current = null
        suppressRef.current = false  // undo window closed — polling safe to resume
        setToast((t) => (t && t.kind === 'undo' && t.item.id === id ? null : t))
        if (p) runCommit(p)
      }, UNDO_MS)
      pendingRef.current = { item, index: idx, type, message, timer }
      suppressRef.current = true   // action in flight — suppress background polls
    },
    [items, flushPending, runCommit],
  )

  // Reset composer, tab, and any in-flight AI draft when the selected lead changes.
  useEffect(() => {
    draftAbortRef.current?.abort()
    draftAbortRef.current = null
    setComposing(false)
    setDrafting(false)
    setCenterTab('conversation')
  }, [selectedId])

  const openComposer = useCallback(() => {
    if (!selected) return
    setDraft(draftFor(selected))
    setComposing(true)
  }, [selected])

  const openDraftWithAI = useCallback(() => {
    if (!selected) return
    draftAbortRef.current?.abort()
    const abort = new AbortController()
    draftAbortRef.current = abort
    setDraft('')
    setComposing(true)
    setDrafting(true)

    if (devBypass) {
      // Dev bypass: the mock token ('dev-bypass') is not a real JWT and would
      // correctly 401 on the backend. Simulate word-by-word streaming locally
      // with the pre-baked Hebrew demo draft (same cadence as the real endpoint).
      let cancelled = false
      abort.signal.addEventListener('abort', () => { cancelled = true })
      const words = DEV_BYPASS_DRAFT.split(' ')
      let i = 0
      const tick = () => {
        if (cancelled) return
        if (i < words.length) {
          const chunk = (i > 0 ? ' ' : '') + words[i++]
          setDraft((prev) => prev + chunk)
          setTimeout(tick, 38)
        } else {
          setDrafting(false)
        }
      }
      setTimeout(tick, 180)
      return
    }

    if (!token) { setDrafting(false); setComposing(false); return }
    void streamDraft(
      token,
      selected.person_id,
      undefined,
      (chunk) => setDraft((prev) => prev + chunk),
      (full) => { setDraft(full); setDrafting(false) },
      () => { setDrafting(false) },
      abort.signal,
    )
  }, [selected, devBypass, token])

  // Auto-draft: when ?draft=1 is in the URL (from ⌘K), fire once on mount for
  // the top lead — the demo narrative starts with the Copilot already drafting.
  const autoDraftFiredRef = useRef(false)
  useEffect(() => {
    if (!autoDraft || autoDraftFiredRef.current) return
    if (!selected || selected.channel !== 'whatsapp') return
    if (!token && !devBypass) return
    autoDraftFiredRef.current = true
    // Small delay so the UI settles before the stream starts
    const t = setTimeout(openDraftWithAI, 400)
    return () => clearTimeout(t)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoDraft, selected?.id, token])

  const sendComposed = useCallback(() => {
    const text = draft.trim()
    if (!text || !selected) return
    setComposing(false)
    act(selected.id, 'send', text)
  }, [draft, selected, act])

  const undo = useCallback(() => {
    const p = pendingRef.current
    if (!p) return
    clearTimeout(p.timer)
    pendingRef.current = null
    suppressRef.current = false  // undone — polling safe to resume
    setItems((prev) => insertAt(prev, p.index, p.item))
    setSelectedId(p.item.id)
    console.log(`[action] ⤺ undo ${p.type} → ${p.item.id} (canceled before commit)`)
    setToast(null)
  }, [suppressRef])

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'z' || e.key === 'Z')) {
      e.preventDefault()
      undo()
      return
    }
    if (!selected) return
    switch (e.key) {
      case 'ArrowDown': e.preventDefault(); move(1); break
      case 'ArrowUp': e.preventDefault(); move(-1); break
      case 'Enter':
      case 's':
      case 'S': e.preventDefault(); openComposer(); break
      case 'e':
      case 'E': e.preventDefault(); act(selected.id, 'done'); break
      case 'z':
      case 'Z': e.preventDefault(); act(selected.id, 'snooze'); break
      case 'Backspace': e.preventDefault(); act(selected.id, 'dismiss'); break
    }
  }

  const drained = items.length === 0 || !selected

  return (
    <>
      {drained ? (
        <QueueEmpty />
      ) : (
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
              <AnimatePresence initial={false} custom={exitDir}>
                {items.map((item) => (
                  <QueueRow
                    key={item.id}
                    item={item}
                    isSelected={item.id === selected.id}
                    isTop={item.id === topId}
                    reduce={!!reduce}
                    onSelect={() => setSelectedId(item.id)}
                    onAct={act}
                    agentRuns={item.id === selected.id ? agentRuns : []}
                  />
                ))}
              </AnimatePresence>
            </div>

            <div className="border-t border-line px-4 py-2.5">
              <span className="font-mono text-[10px] leading-relaxed text-faint">
                ↑↓ move · ↵ send · E done · Z snooze · ⌫ dismiss
              </span>
            </div>
          </section>

          {/* ── Center: the spotlight — activity + the Action Bar ────────────────── */}
          <section className="flex min-w-0 flex-1 flex-col">
            <div key={selected.id} className="cq-rise border-b border-line px-6 py-3">
              <div className="text-base font-medium text-ink">{selected.name}</div>
              <div className="mt-1 flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-sage" aria-hidden />
                <span className="font-mono text-xs text-muted">
                  {selected.channel ? (CHANNEL_LABELS[selected.channel] ?? selected.channel) : '—'}
                  {selected.handle ? ` · ${selected.handle}` : ''}
                </span>
              </div>
              {/* Tab bar — Conversation / Agent Log */}
              <div className="mt-3 flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setCenterTab('conversation')}
                  className={`rounded-control px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors ${
                    centerTab === 'conversation'
                      ? 'bg-accent/15 text-accent'
                      : 'text-faint hover:text-muted'
                  }`}
                >
                  Conversation
                </button>
                <button
                  type="button"
                  onClick={() => setCenterTab('agent')}
                  className={`flex items-center gap-1.5 rounded-control px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors ${
                    centerTab === 'agent'
                      ? 'bg-accent/15 text-accent'
                      : 'text-faint hover:text-muted'
                  }`}
                >
                  <span aria-hidden className="text-[8px]">✦</span>
                  Agent log
                  {agentRuns.length > 0 && (
                    <span className="rounded-full bg-accent/20 px-1 font-mono text-[9px] tabular-nums text-accent">
                      {agentRuns.length}
                    </span>
                  )}
                </button>
              </div>
            </div>

            <div key={`${selected.id}:${centerTab}`} className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              {centerTab === 'agent' ? (
                <AgentActivityFeed
                  runs={agentRuns}
                  loading={agentRunsLoading}
                  personId={selected.person_id}
                  token={token}
                />
              ) : selected.channel === 'whatsapp' ? (
                <WhatsAppThread
                  personId={selected.person_id}
                  token={token}
                  devBypass={devBypass}
                  fallbackTimeline={selected.timeline}
                />
              ) : (
                <>
                  <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Activity</div>
                  {selected.timeline.length === 0 ? (
                    <p className="text-sm text-muted">No recorded activity yet.</p>
                  ) : (
                    <ol className="relative ml-1 border-l border-line">
                      {selected.timeline.map((e, i) => (
                        <li
                          key={i}
                          className="cq-rise relative pb-4 pl-5 last:pb-0"
                          style={{ animationDelay: `${i * 45}ms` }}
                        >
                          <span
                            aria-hidden
                            className={`absolute -left-[4.5px] top-1.5 h-2 w-2 rounded-full ${
                              i === 0 ? 'bg-accent' : 'bg-faint'
                            }`}
                          />
                          <div className="text-sm text-ink">{e.label}</div>
                          <div className="font-mono text-[10px] text-faint">{relativeTime(e.at)}</div>
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              )}
            </div>

            {/* The trust trio + the Action Bar. */}
            <div className="border-t border-line px-6 py-4">
              <div className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Suggested action</div>
              <div className="mt-1 text-sm text-ink">{selected.action}</div>

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

              {/* Action Bar — or the inline Send composer when composing. */}
              {composing ? (
                <div className="mt-4 rounded-control border border-line bg-bg/70 p-2.5 backdrop-blur-xl [box-shadow:var(--shadow-card)]">
                  {/* Header row: status indicator while AI is streaming */}
                  {drafting && (
                    <div className="mb-2 flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-glow" aria-hidden />
                      <span className="font-mono text-[10px] text-glow">Copilot drafting…</span>
                    </div>
                  )}
                  <textarea
                    value={draft}
                    readOnly={drafting}
                    onChange={drafting ? undefined : (e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      e.stopPropagation()
                      if (e.key === 'Escape') {
                        e.preventDefault()
                        draftAbortRef.current?.abort()
                        setDrafting(false)
                        setComposing(false)
                      } else if (!drafting && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault()
                        sendComposed()
                      }
                    }}
                    rows={3}
                    autoFocus={!drafting}
                    placeholder={drafting ? '' : `Message ${selected.name} on WhatsApp…`}
                    dir="auto"
                    className={`w-full resize-none bg-transparent text-sm leading-relaxed text-ink outline-none placeholder:text-faint ${
                      drafting ? 'cursor-default opacity-90' : ''
                    }`}
                  />
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="font-mono text-[10px] text-faint">
                      {drafting ? 'Reviewing…' : '⌘↵ send · esc cancel · via WhatsApp'}
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          draftAbortRef.current?.abort()
                          setDrafting(false)
                          setComposing(false)
                        }}
                        className="rounded-control px-3 py-1.5 text-xs text-muted transition-colors hover:bg-raised hover:text-ink"
                      >
                        Cancel
                      </button>
                      <motion.button
                        type="button"
                        onClick={sendComposed}
                        disabled={!draft.trim() || drafting}
                        whileHover={reduce || !draft.trim() || drafting ? undefined : { scale: 1.03 }}
                        whileTap={reduce || !draft.trim() || drafting ? undefined : { scale: 0.97 }}
                        className="inline-flex items-center gap-1.5 rounded-control bg-accent px-3.5 py-1.5 text-xs font-medium text-ink transition-opacity [box-shadow:var(--shadow-glow)] disabled:opacity-40 disabled:[box-shadow:none]"
                      >
                        <Icon name="send" size={13} /> Send
                      </motion.button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <motion.button
                    type="button"
                    onClick={openComposer}
                    whileHover={reduce ? undefined : { scale: 1.03 }}
                    whileTap={reduce ? undefined : { scale: 0.97 }}
                    aria-label="Send message"
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-control bg-accent px-3.5 py-2 text-xs font-medium text-ink [box-shadow:var(--shadow-glow)]"
                  >
                    <Icon name="send" size={14} /> Send message
                  </motion.button>
                  {/* P2 WS4 — "Draft with AI" — only for WhatsApp leads */}
                  {selected.channel === 'whatsapp' && token && (
                    <motion.button
                      type="button"
                      onClick={openDraftWithAI}
                      whileHover={reduce ? undefined : { scale: 1.03 }}
                      whileTap={reduce ? undefined : { scale: 0.97 }}
                      aria-label="Draft reply with AI Copilot"
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-control border border-glow/40 bg-glow/10 px-3.5 py-2 text-xs font-medium text-glow transition-colors hover:bg-glow/20"
                    >
                      <span aria-hidden className="text-[10px]">✦</span> Draft with AI
                    </motion.button>
                  )}
                  <div className="ml-auto flex items-center gap-2">
                    <ActionButton icon="check" label="Done" tone="success" onClick={() => act(selected.id, 'done')} />
                    <ActionButton icon="clock" label="Snooze" tone="warn" onClick={() => act(selected.id, 'snooze')} />
                    <ActionButton icon="x" label="Dismiss" tone="danger" onClick={() => act(selected.id, 'dismiss')} />
                  </div>
                </div>
              )}
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
                  <div className="font-mono text-[10px] text-faint">
                    first contact · {relativeTime(selected.first_seen_at)}
                  </div>
                </div>
              </div>

              {selected.essence ? (
                <p className="border-l-2 border-accent pl-3.5 font-serif text-[17px] font-light leading-snug text-ink">
                  {selected.essence}
                </p>
              ) : (
                <p className="border-l-2 border-line pl-3.5 font-serif text-[15px] font-light italic leading-snug text-faint">
                  No memory summary yet.
                </p>
              )}

              <div className="my-4 h-px bg-line" />

              {selected.goal && <Fact label="Goal" value={selected.goal} />}
              {selected.tension && <Fact label="Tension" value={selected.tension} />}
              <Fact label="Last contact" value={relativeTime(selected.last_contacted)} mono />
            </div>
          </aside>
        </div>
      )}

      {/* Undo toast (the safety net) — or an error toast when a commit fails. */}
      <AnimatePresence>
        {toast && (
          <motion.div
            key={`${toast.item.id}:${toast.type}:${toast.kind}`}
            role="status"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 16 }}
            transition={{ duration: 0.2, ease: EASE }}
            className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2.5 overflow-hidden rounded-card border border-line bg-surface px-4 py-2.5 backdrop-blur-xl [box-shadow:var(--shadow-card)]"
          >
            {toast.kind === 'error' ? (
              <>
                <Icon name="alert" size={14} className="text-danger" />
                <span className="text-sm text-ink">Couldn&rsquo;t save</span>
                <span className="text-xs text-faint">·</span>
                <span className="max-w-[180px] truncate text-sm text-muted">{toast.item.name} restored</span>
              </>
            ) : (
              <>
                <span className="text-sm text-ink">{ACTION_VERB[toast.type]}</span>
                <span className="text-xs text-faint">·</span>
                <span className="max-w-[160px] truncate text-sm text-muted">{toast.item.name}</span>
                <button
                  type="button"
                  onClick={undo}
                  className="ml-1 inline-flex items-center gap-1 rounded-control px-2 py-1 text-xs font-medium text-glow transition-colors hover:bg-raised"
                >
                  <Icon name="arrowRight" size={12} className="rotate-180" /> Undo
                </button>
                {!reduce && (
                  <motion.span
                    aria-hidden
                    initial={{ scaleX: 1 }}
                    animate={{ scaleX: 0 }}
                    transition={{ duration: UNDO_MS / 1000, ease: 'linear' }}
                    className="absolute bottom-0 left-0 h-0.5 w-full origin-left bg-glow/60"
                  />
                )}
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

function QueueRow({
  item,
  isSelected,
  isTop,
  reduce,
  onSelect,
  onAct,
  agentRuns,
}: {
  item: QueueItem
  isSelected: boolean
  isTop: boolean
  reduce: boolean
  onSelect: () => void
  onAct: (id: string, type: ActionType) => void
  agentRuns: import('../lib/useAgentRuns').AgentRun[]
}) {
  const variants = {
    initial: reduce ? { opacity: 0 } : { opacity: 0, height: 0 },
    animate: reduce ? { opacity: 1 } : { opacity: 1, height: 'auto' as const },
    exit: (dir: ExitDir) =>
      reduce
        ? { opacity: 0 }
        : {
            opacity: 0,
            height: 0,
            marginTop: 0,
            marginBottom: 0,
            paddingTop: 0,
            paddingBottom: 0,
            x: dir === 'right' ? 64 : dir === 'left' ? -64 : 0,
            y: dir === 'down' ? 28 : 0,
            transition: { duration: 0.34, ease: EASE_OUT },
          },
  }

  const quick = (type: ActionType) => (e: MouseEvent) => {
    e.stopPropagation()
    onAct(item.id, type)
  }

  return (
    <motion.div
      variants={variants}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={{ duration: 0.26, ease: EASE }}
      role="button"
      tabIndex={-1}
      onClick={onSelect}
      aria-current={isSelected ? 'true' : undefined}
      className={`group relative mb-0.5 flex w-full cursor-pointer items-start gap-2.5 overflow-hidden rounded-control py-2.5 pl-3.5 pr-2.5 text-left transition-[opacity,background-color] duration-[260ms] ${
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
          <AgentPip runs={agentRuns} />
        </span>
        <span className="mt-0.5 line-clamp-1 text-xs text-muted">{item.teaser}</span>
      </span>

      {/* Default meta — fades out on hover to make room for triage. */}
      <span className="flex shrink-0 flex-col items-end gap-0.5 transition-opacity duration-150 group-hover:opacity-0">
        <span className="font-mono text-xs tabular-nums text-muted">{item.confidence}%</span>
        <span className="font-mono text-[10px] text-faint">{relativeTime(item.last_contacted)}</span>
      </span>

      {/* Hover triage — drain the queue without selecting. */}
      <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1 opacity-0 transition-opacity duration-150 group-hover:opacity-100">
        <QuickAction icon="check" tone="success" title="Mark done (E)" onClick={quick('done')} />
        <QuickAction icon="clock" tone="warn" title="Snooze (Z)" onClick={quick('snooze')} />
        <QuickAction icon="x" tone="danger" title="Dismiss (⌫)" onClick={quick('dismiss')} />
      </span>
    </motion.div>
  )
}

const TONE_HOVER = {
  success: 'hover:border-success/40 hover:text-success',
  warn: 'hover:border-warn/40 hover:text-warn',
  danger: 'hover:border-danger/40 hover:text-danger',
} as const

function QuickAction({
  icon,
  tone,
  title,
  onClick,
}: {
  icon: IconName
  tone: keyof typeof TONE_HOVER
  title: string
  onClick: (e: MouseEvent) => void
}) {
  return (
    <button
      type="button"
      tabIndex={-1}
      title={title}
      aria-label={title}
      onClick={onClick}
      className={`grid h-7 w-7 place-items-center rounded-control border border-line bg-surface text-muted backdrop-blur-xl transition-colors hover:bg-raised ${TONE_HOVER[tone]}`}
    >
      <Icon name={icon} size={14} />
    </button>
  )
}

function ActionButton({
  icon,
  label,
  tone,
  onClick,
}: {
  icon: IconName
  label: string
  tone: keyof typeof TONE_HOVER
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-control border border-line bg-surface px-3 py-2 text-xs text-muted backdrop-blur-xl transition-colors hover:bg-raised ${TONE_HOVER[tone]}`}
    >
      <Icon name={icon} size={14} /> {label}
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

// ── QueueEmpty ─────────────────────────────────────────────────────────────────
// Shown when the Board drains to zero via optimistic actions (all cards removed
// before the next background poll reloads). Same "Queue clear" surface as the
// outer WorkQueuePage empty state — full-height so it fills the Board's slot.
function QueueEmpty() {
  return (
    <SurfaceEmpty
      flavor="win"
      title="Queue clear"
      body="No one is waiting on a next move right now."
      copilotSlot={<CopilotNudge />}
      className="h-full"
    />
  )
}

