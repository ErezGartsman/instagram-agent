import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import { fetchThread, sendThreadMessage, type ChannelEligibility, type ThreadData, type ThreadMessage } from '../lib/api'
import type { TimelineEvent } from '../lib/workqueue'
import { relativeTime } from '../lib/pipeline'

// ── Dev-bypass sample (dead-code-eliminated in prod builds) ───────────────────
// Spans two channels deliberately so the dev preview exercises the channel
// chip (only shown when a person's thread crosses >1 channel — see spansMultipleChannels).
const SAMPLE_THREAD: ThreadData = import.meta.env.DEV
  ? {
      messages: [
        {
          role: 'user',
          body: 'שלום, ראיתי אותך באינסטגרם ורציתי לשאול על ייעוץ זוגי',
          at: new Date(Date.now() - 11 * 86_400_000 - 2 * 3_600_000).toISOString(),
          channel: 'instagram',
        },
        {
          role: 'assistant',
          body: 'שלום! זו הודעה אוטומטית — אני עוזר הקבלה של ארז. הוא קורא את ההודעות שלך ועונה אישית. נחזור אליך בהקדם.',
          at: new Date(Date.now() - 11 * 86_400_000 - 2 * 3_600_000 + 9_000).toISOString(),
          channel: 'instagram',
        },
        {
          role: 'user',
          body: 'אוקיי תודה. אני וחברי בזוגיות של 4 שנים ויש לנו משבר. רציתי לדעת אם יש פגישה ראשונה חינם',
          at: new Date(Date.now() - 11 * 86_400_000).toISOString(),
          channel: 'instagram',
        },
        {
          role: 'user',
          body: 'האם אתם עובדים גם עם זוגות שגרים בחו"ל?',
          at: new Date(Date.now() - 4 * 86_400_000 - 3 * 3_600_000).toISOString(),
          channel: 'whatsapp',
        },
        {
          role: 'user',
          body: 'אגב, ראיתי שיש לך פוסט על אמון. בדיוק מה שאנחנו עוברים. רוצה לדעת יותר',
          at: new Date(Date.now() - 4 * 86_400_000 - 2 * 3_600_000).toISOString(),
          channel: 'whatsapp',
        },
        {
          role: 'operator',
          body: 'היי מאיה, ארז כאן. עובדים גם אונליין, ופגישה ראשונה בתשלום — אבל אם תרצי נדבר תחילה בחינם ל-15 דקות. מתי נוח לך?',
          at: new Date(Date.now() - 4 * 60_000).toISOString(),
          channel: 'whatsapp',
          status: 'sent',
        },
      ],
      channels: {
        whatsapp: { eligible: true, reason: null, window_expires_at: null },
        instagram: { eligible: false, reason: 'window_expired', window_expires_at: null },
      },
      default_channel: 'whatsapp',
    }
  : { messages: [], channels: {}, default_channel: 'whatsapp' }

const EMPTY_THREAD: ThreadData = { messages: [], channels: {}, default_channel: 'whatsapp' }

// ── Helpers ────────────────────────────────────────────────────────────────────

const GROUP_WINDOW_MS = 3 * 60_000

// Channels One Thread can send on. Matches the backend's _SUPPORTED_SEND_CHANNELS.
const SUPPORTED_SEND_CHANNELS = new Set(['whatsapp', 'instagram', 'telegram'])

// Short, tiny-chip labels — distinct from the full CHANNEL_LABELS used in page
// headers (lib/pipeline.ts). A per-message inline chip needs to stay unobtrusive.
const SHORT_CHANNEL: Record<string, string> = {
  whatsapp: 'WA',
  instagram: 'IG',
  telegram: 'TG',
}

function channelLabel(channel: string): string {
  return SHORT_CHANNEL[channel] ?? channel.slice(0, 2).toUpperCase()
}

function ineligibleReason(channel: string, reason: string | null): string | null {
  if (!reason) return null
  const label = channelLabel(channel)
  if (reason === 'no_inbound_yet') {
    return `This lead hasn't messaged on ${label} yet — nothing to reply to.`
  }
  if (reason === 'window_expired') {
    return `The 24-hour ${label} window has closed — they'll need to message again first.`
  }
  return `Sending on ${label} isn't available right now.`
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const diffMs = Date.now() - d.getTime()
  const diffDays = Math.floor(diffMs / 86_400_000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function needsDateSeparator(a: ThreadMessage, b: ThreadMessage): boolean {
  return new Date(a.at).toDateString() !== new Date(b.at).toDateString()
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function DateSeparator({ at }: { at: string }) {
  return (
    <div className="my-4 flex items-center gap-3" aria-hidden>
      <span className="h-px flex-1 bg-line" />
      <span className="font-mono text-[10px] text-faint">{formatDate(at)}</span>
      <span className="h-px flex-1 bg-line" />
    </div>
  )
}

function ChannelChip({ channel }: { channel: string | null | undefined }) {
  const label = channel ? channelLabel(channel) : null
  if (!label) return null
  return (
    <span className="rounded-full border border-line/70 bg-raised/60 px-1.5 py-px font-mono text-[8px] uppercase tracking-wider text-faint">
      {label}
    </span>
  )
}

function Bubble({
  msg,
  isNewGroup,
  isLastInGroup,
  showChannelChip,
  onRetry,
}: {
  msg: ThreadMessage
  isNewGroup: boolean
  isLastInGroup: boolean
  showChannelChip: boolean
  /** Present only on the composer's own optimistic bubbles (status 'sending'/'failed'). */
  onRetry?: () => void
}) {
  const { role, body, at, channel, status } = msg

  // ── Bot handoff notice — centered, muted ─────────────────────────────────────
  if (role === 'assistant') {
    return (
      <div className={`flex flex-col items-center ${isNewGroup ? 'mt-4' : 'mt-0.5'}`}>
        <div className="max-w-[88%] rounded-card border border-line/50 bg-raised/30 px-4 py-2.5 text-center">
          <p className="text-[11px] italic leading-relaxed text-faint" dir="auto">
            {body}
          </p>
          {isLastInGroup && (
            <p className="mt-1 font-mono text-[9px] text-faint/50">
              {formatTime(at)} · automated
            </p>
          )}
        </div>
      </div>
    )
  }

  // ── Operator reply — right-aligned, violet accent ─────────────────────────────
  if (role === 'operator') {
    const isFailed = status === 'failed'
    const isSending = status === 'sending'
    return (
      <div className={`flex flex-col items-end ${isNewGroup ? 'mt-4' : 'mt-0.5'}`}>
        <div
          className={`max-w-[78%] rounded-card px-3.5 py-2.5 ${isFailed ? 'bg-danger/20 border border-danger/40' : 'bg-accent'} ${isSending ? 'opacity-60' : ''}`}
          style={!isFailed ? { boxShadow: 'var(--shadow-glow)' } : undefined}
        >
          <p className="text-sm leading-relaxed text-ink" dir="auto">
            {body}
          </p>
        </div>
        {isLastInGroup && (
          <p className="mr-1 mt-0.5 flex items-center gap-1.5 font-mono text-[9px] text-glow/70">
            {isSending ? 'sending…' : isFailed ? (
              <span className="flex items-center gap-1 text-danger">
                failed
                {onRetry && (
                  <button type="button" onClick={onRetry} className="underline hover:text-warn">
                    retry
                  </button>
                )}
              </span>
            ) : (
              <>{formatTime(at)} · you</>
            )}
            {!isSending && !isFailed && showChannelChip && <ChannelChip channel={channel} />}
          </p>
        )}
      </div>
    )
  }

  // ── Lead's inbound message — left-aligned, glass ──────────────────────────────
  return (
    <div className={`flex flex-col items-start ${isNewGroup ? 'mt-4' : 'mt-0.5'}`}>
      <div className="max-w-[78%] rounded-card border border-line bg-surface px-3.5 py-2.5 backdrop-blur-sm">
        <p className="text-sm leading-relaxed text-ink" dir="auto">
          {body}
        </p>
      </div>
      {isLastInGroup && (
        <p className="ml-1 mt-0.5 flex items-center gap-1.5 font-mono text-[9px] text-faint">
          {showChannelChip && <ChannelChip channel={channel} />}
          {formatTime(at)}
        </p>
      )}
    </div>
  )
}

function ThreadSkeleton() {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex justify-start">
        <div className="h-10 w-[52%] animate-pulse rounded-card bg-raised" />
      </div>
      <div className="flex justify-center">
        <div className="h-8 w-[72%] animate-pulse rounded-card bg-raised/50" />
      </div>
      <div className="flex justify-start">
        <div className="h-14 w-[62%] animate-pulse rounded-card bg-raised" />
      </div>
      <div className="flex justify-start">
        <div className="h-9 w-[42%] animate-pulse rounded-card bg-raised" />
      </div>
      <div className="flex justify-end">
        <div className="h-12 w-[58%] animate-pulse rounded-card bg-accent/20" />
      </div>
    </div>
  )
}

function ActivityTimeline({ timeline }: { timeline: TimelineEvent[] }) {
  return (
    <>
      <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
        Activity
      </div>
      {timeline.length === 0 ? (
        <p className="text-sm text-muted">No recorded activity yet.</p>
      ) : (
        <ol className="relative ml-1 border-l border-line">
          {timeline.map((e, i) => (
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
  )
}

// ── Composer — One Thread, send-from-cockpit ──────────────────────────────────
// Docked at the bottom via `sticky` (the scroll container is the parent panel in
// WorkQueuePage, not this component — sticky works within any scrolling ancestor
// without needing to own the scroll itself). Disabled + explained, never a bare
// failure, when the channel isn't sendable yet or its window has closed.
//
// The channel picker only appears once a person's thread actually spans more
// than one channel (docs/ONE_THREAD_PRD.md §4.1: explicit pick > reply-to-
// last-inbound > origin) — the common single-channel lead stays clutter-free.

function ChannelPicker({
  channels,
  resolvedChannel,
  eligibilityByChannel,
  onSelect,
}: {
  channels: string[]
  resolvedChannel: string
  eligibilityByChannel: Record<string, ChannelEligibility | undefined>
  onSelect: (channel: string) => void
}) {
  return (
    <div className="mb-2 flex items-center gap-1.5">
      {channels.map((ch) => {
        const isSelected = ch === resolvedChannel
        const isEligible = eligibilityByChannel[ch]?.eligible ?? false
        return (
          <button
            key={ch}
            type="button"
            onClick={() => onSelect(ch)}
            title={!isEligible ? ineligibleReason(ch, eligibilityByChannel[ch]?.reason ?? null) ?? undefined : undefined}
            className={`rounded-full border px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider transition-colors ${
              isSelected
                ? 'border-accent/50 bg-accent/15 text-accent'
                : isEligible
                  ? 'border-line text-muted hover:border-line/70 hover:text-ink'
                  : 'border-line/50 text-faint'
            }`}
          >
            {channelLabel(ch)}
          </button>
        )
      })}
    </div>
  )
}

function Composer({
  draft,
  onDraftChange,
  onSend,
  sending,
  blockedReason,
  channelSupported,
  resolvedChannel,
  availableChannels,
  eligibilityByChannel,
  onSelectChannel,
}: {
  draft: string
  onDraftChange: (v: string) => void
  onSend: () => void
  sending: boolean
  blockedReason: string | null
  channelSupported: boolean
  resolvedChannel: string
  availableChannels: string[]
  eligibilityByChannel: Record<string, ChannelEligibility | undefined>
  onSelectChannel: (channel: string) => void
}) {
  const canSend = channelSupported && !blockedReason && draft.trim().length > 0 && !sending

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      if (canSend) onSend()
    }
  }

  return (
    <div className="sticky bottom-0 -mx-6 mt-4 border-t border-line bg-bg px-6 pt-3">
      {availableChannels.length > 1 && (
        <ChannelPicker
          channels={availableChannels}
          resolvedChannel={resolvedChannel}
          eligibilityByChannel={eligibilityByChannel}
          onSelect={onSelectChannel}
        />
      )}
      {blockedReason && (
        <p className="mb-2 font-mono text-[10px] text-faint">{blockedReason}</p>
      )}
      <div className="flex items-end gap-2 pb-3">
        <textarea
          dir="auto"
          rows={1}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!channelSupported}
          placeholder={channelSupported ? `Reply on ${channelLabel(resolvedChannel)}… (⌘/Ctrl+Enter to send)` : "Sending here isn't available yet"}
          className="max-h-32 min-h-[38px] flex-1 resize-none rounded-control border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-faint focus:border-accent/50 focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          className={`shrink-0 rounded-control px-3.5 py-2 font-mono text-[11px] uppercase tracking-wide transition-colors ${
            canSend ? 'bg-accent text-ink' : 'cursor-not-allowed bg-raised text-faint'
          }`}
          style={canSend ? { boxShadow: 'var(--shadow-glow)' } : undefined}
        >
          {sending ? '…' : 'Send'}
        </button>
      </div>
    </div>
  )
}

// ── ConversationThread ─────────────────────────────────────────────────────────
// One Thread — fetches a person's conversation ACROSS ALL CHANNELS (WhatsApp/
// Instagram/Telegram) and renders it as one chronological list of premium glass
// bubbles, tagging each with its origin channel only when the person's history
// actually spans more than one. Falls back to the Activity timeline when no
// messages are persisted yet.
//
// The bottom-docked composer sends from the cockpit on WhatsApp, Instagram, or
// Telegram (docs/ONE_THREAD_PRD.md). It stays visible even for an empty/
// loading thread so the operator always sees *why* they can or can't reply
// yet, rather than the affordance appearing and disappearing. The channel
// picker only shows once a person's history actually spans multiple channels —
// otherwise the resolved channel (reply-to-last-inbound) is implicit.

export function ConversationThread({
  personId,
  token,
  devBypass,
  fallbackTimeline,
}: {
  personId: string
  token: string | null
  devBypass: boolean
  fallbackTimeline: TimelineEvent[]
}) {
  const [thread, setThread] = useState<ThreadData | null>(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null)
  const clientTokenRef = useRef<string>(crypto.randomUUID())
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setThread(null)
    setDraft('')
    setSelectedChannel(null)   // a new person resets any explicit channel override
    if (devBypass) {
      const t = setTimeout(() => setThread(SAMPLE_THREAD), 180)
      return () => clearTimeout(t)
    }
    if (!token) { setThread(EMPTY_THREAD); return }
    fetchThread(token, personId).then(setThread).catch(() => setThread(EMPTY_THREAD))
  }, [personId, token, devBypass])

  const msgs = thread?.messages ?? null

  // Auto-scroll to the most-recent message whenever the thread loads or grows.
  useEffect(() => {
    if (msgs && msgs.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'instant' })
    }
  }, [msgs])

  // The distinct channels this person's history actually touches — drives both
  // the per-bubble channel chip and the composer's channel picker. A single-
  // channel lead (the common case) never sees either.
  const availableChannels = useMemo(() => {
    if (!msgs) return []
    return Array.from(new Set(msgs.map((m) => m.channel).filter((c): c is string => Boolean(c))))
  }, [msgs])
  const spansMultipleChannels = availableChannels.length > 1

  // Resolution order (§4.1): explicit operator pick > reply-to-last-inbound.
  const defaultChannel = thread?.default_channel ?? 'whatsapp'
  const resolvedChannel = selectedChannel ?? defaultChannel
  const eligibility: ChannelEligibility | undefined = thread?.channels?.[resolvedChannel]
  const channelSupported = SUPPORTED_SEND_CHANNELS.has(resolvedChannel)

  const blockedReason = !channelSupported
    ? `Sending on ${channelLabel(resolvedChannel)} isn't available yet.`
    : (eligibility && !eligibility.eligible)
      ? ineligibleReason(resolvedChannel, eligibility.reason)
      : null

  const attemptSend = async (text: string, tempId: string, channel: string) => {
    setSending(true)

    if (devBypass) {
      // Demo-only local echo — no real send, matching this page's existing
      // dev-bypass philosophy (see DEV_BYPASS_DRAFT in WorkQueuePage).
      await new Promise((r) => setTimeout(r, 250))
      setThread((prev) => prev && {
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === tempId ? { ...m, status: 'sent' } : m),
      })
      setSending(false)
      return
    }
    if (!token) { setSending(false); return }

    const result = await sendThreadMessage(token, personId, text, clientTokenRef.current, channel)
    setSending(false)
    if (result.status === 'success' && result.message) {
      clientTokenRef.current = crypto.randomUUID()
      setThread((prev) => prev && {
        ...prev,
        messages: prev.messages.map((m) => (m.id === tempId ? result.message! : m)),
      })
    } else {
      setThread((prev) => prev && {
        ...prev,
        messages: prev.messages.map((m) =>
          m.id === tempId ? { ...m, status: 'failed' } : m),
      })
    }
  }

  const handleSend = () => {
    const text = draft.trim()
    if (!text || sending) return
    const tempId = crypto.randomUUID()
    const channel = resolvedChannel
    const optimistic: ThreadMessage = {
      id: tempId, role: 'operator', body: text, at: new Date().toISOString(),
      channel, status: 'sending',
    }
    setThread((prev) => prev && { ...prev, messages: [...prev.messages, optimistic] })
    setDraft('')
    void attemptSend(text, tempId, channel)
  }

  const handleRetry = (msg: ThreadMessage) => {
    if (!msg.id || sending) return
    setThread((prev) => prev && {
      ...prev,
      messages: prev.messages.map((m) => (m.id === msg.id ? { ...m, status: 'sending' } : m)),
    })
    // Retry on the SAME channel it originally failed on — not whatever channel
    // is currently selected in the composer, which may have changed since.
    void attemptSend(msg.body, msg.id, msg.channel ?? resolvedChannel)
  }

  let body: ReactNode
  if (msgs === null) {
    body = <ThreadSkeleton />
  } else if (msgs.length === 0) {
    body = <ActivityTimeline timeline={fallbackTimeline} />
  } else {
    body = (
      <>
        <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
          Conversation
        </div>

        <div className="flex flex-col">
          {msgs.map((msg, i) => {
            const prev = msgs[i - 1]
            const next = msgs[i + 1]
            const showDate = !prev || needsDateSeparator(prev, msg)
            const gapBefore = prev
              ? new Date(msg.at).getTime() - new Date(prev.at).getTime()
              : Infinity
            const gapAfter = next
              ? new Date(next.at).getTime() - new Date(msg.at).getTime()
              : Infinity
            const isNewGroup = !prev || prev.role !== msg.role || gapBefore > GROUP_WINDOW_MS
            const isLastInGroup = !next || next.role !== msg.role || gapAfter > GROUP_WINDOW_MS

            return (
              <div key={msg.id ?? i}>
                {showDate && <DateSeparator at={msg.at} />}
                <Bubble
                  msg={msg}
                  isNewGroup={isNewGroup}
                  isLastInGroup={isLastInGroup}
                  showChannelChip={spansMultipleChannels}
                  onRetry={msg.status === 'failed' ? () => handleRetry(msg) : undefined}
                />
              </div>
            )
          })}
        </div>

        <div ref={bottomRef} className="h-2" />
      </>
    )
  }

  return (
    <>
      {body}
      {thread && (
        <Composer
          draft={draft}
          onDraftChange={setDraft}
          onSend={handleSend}
          sending={sending}
          blockedReason={blockedReason}
          channelSupported={channelSupported}
          resolvedChannel={resolvedChannel}
          availableChannels={availableChannels}
          eligibilityByChannel={thread.channels}
          onSelectChannel={setSelectedChannel}
        />
      )}
    </>
  )
}
