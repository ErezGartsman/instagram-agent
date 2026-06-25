import { useEffect, useRef, useState } from 'react'
import { fetchThread, type ThreadMessage } from '../lib/api'
import type { TimelineEvent } from '../lib/workqueue'
import { relativeTime } from '../lib/pipeline'

// ── Dev-bypass sample (dead-code-eliminated in prod builds) ───────────────────
const SAMPLE_THREAD: ThreadMessage[] = import.meta.env.DEV
  ? [
      {
        role: 'user',
        body: 'שלום, ראיתי אותך באינסטגרם ורציתי לשאול על ייעוץ זוגי',
        at: new Date(Date.now() - 11 * 86_400_000 - 2 * 3_600_000).toISOString(),
      },
      {
        role: 'assistant',
        body: 'שלום! זו הודעה אוטומטית — אני עוזר הקבלה של ארז. הוא קורא את ההודעות שלך ועונה אישית. נחזור אליך בהקדם.',
        at: new Date(Date.now() - 11 * 86_400_000 - 2 * 3_600_000 + 9_000).toISOString(),
      },
      {
        role: 'user',
        body: 'אוקיי תודה. אני וחברי בזוגיות של 4 שנים ויש לנו משבר. רציתי לדעת אם יש פגישה ראשונה חינם',
        at: new Date(Date.now() - 11 * 86_400_000).toISOString(),
      },
      {
        role: 'user',
        body: 'האם אתם עובדים גם עם זוגות שגרים בחו"ל?',
        at: new Date(Date.now() - 4 * 86_400_000 - 3 * 3_600_000).toISOString(),
      },
      {
        role: 'user',
        body: 'אגב, ראיתי שיש לך פוסט על אמון. בדיוק מה שאנחנו עוברים. רוצה לדעת יותר',
        at: new Date(Date.now() - 4 * 86_400_000 - 2 * 3_600_000).toISOString(),
      },
      {
        role: 'operator',
        body: 'היי מאיה, ארז כאן. עובדים גם אונליין, ופגישה ראשונה בתשלום — אבל אם תרצי נדבר תחילה בחינם ל-15 דקות. מתי נוח לך?',
        at: new Date(Date.now() - 4 * 60_000).toISOString(),
      },
    ]
  : []

// ── Helpers ────────────────────────────────────────────────────────────────────

const GROUP_WINDOW_MS = 3 * 60_000

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

function Bubble({
  msg,
  isNewGroup,
  isLastInGroup,
}: {
  msg: ThreadMessage
  isNewGroup: boolean
  isLastInGroup: boolean
}) {
  const { role, body, at } = msg

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
    return (
      <div className={`flex flex-col items-end ${isNewGroup ? 'mt-4' : 'mt-0.5'}`}>
        <div
          className="max-w-[78%] rounded-card bg-accent px-3.5 py-2.5"
          style={{ boxShadow: 'var(--shadow-glow)' }}
        >
          <p className="text-sm leading-relaxed text-ink" dir="auto">
            {body}
          </p>
        </div>
        {isLastInGroup && (
          <p className="mr-1 mt-0.5 font-mono text-[9px] text-glow/70">
            {formatTime(at)} · you
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
        <p className="ml-1 mt-0.5 font-mono text-[9px] text-faint">
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

// ── WhatsAppThread ─────────────────────────────────────────────────────────────
// Fetches the conversation thread for a WhatsApp lead and renders it as
// premium glass bubbles. Falls back to the Activity timeline when no messages
// are persisted yet (e.g. sample data or a non-WA channel fallback path).

export function WhatsAppThread({
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
  const [msgs, setMsgs] = useState<ThreadMessage[] | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMsgs(null)
    if (devBypass) {
      const t = setTimeout(() => setMsgs(SAMPLE_THREAD), 180)
      return () => clearTimeout(t)
    }
    if (!token) { setMsgs([]); return }
    fetchThread(token, personId).then(setMsgs).catch(() => setMsgs([]))
  }, [personId, token, devBypass])

  // Auto-scroll to the most-recent message whenever the thread loads or person changes
  useEffect(() => {
    if (msgs && msgs.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'instant' })
    }
  }, [msgs])

  if (msgs === null) return <ThreadSkeleton />
  if (msgs.length === 0) return <ActivityTimeline timeline={fallbackTimeline} />

  return (
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
            <div key={i}>
              {showDate && <DateSeparator at={msg.at} />}
              <Bubble msg={msg} isNewGroup={isNewGroup} isLastInGroup={isLastInGroup} />
            </div>
          )
        })}
      </div>

      <div ref={bottomRef} className="h-2" />
    </>
  )
}
