/**
 * NexusAIPanel — global omnipresent AI assistant.
 *
 * Mounted once in AppShell so the tab is visible on every page. Manages its
 * own open state — no prop drilling into individual pages required.
 *
 * Anatomy:
 *   1. Floating right-edge vertical tab ("✦ Nexus AI") — slides in/out with
 *      the panel so there is never a double chrome.
 *   2. Glass slide-out drawer (400px, spring animation, fixed right-0) with:
 *      — Weekly-leads bar chart (pure CSS, no recharts)
 *      — Pre-baked mock NLP conversation showing the vision
 *      — Static query input labelled "coming in the next workstream"
 *
 * The mock content is intentionally high-fidelity so the stakeholder can feel
 * the NLP-to-graph experience without a live backend. Clearly marked "preview".
 */

import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Icon } from './Icon'

// ── Mock data (vision demo) ────────────────────────────────────────────────────

const WEEK_DATA = [
  { day: 'Mon', leads: 2 },
  { day: 'Tue', leads: 4 },
  { day: 'Wed', leads: 3 },
  { day: 'Thu', leads: 1 },
  { day: 'Fri', leads: 5 },
  { day: 'Sat', leads: 2 },
  { day: 'Sun', leads: 3 },
]
const WEEK_MAX = Math.max(...WEEK_DATA.map((d) => d.leads))

const CONVERSATION: { role: 'user' | 'ai'; text: string }[] = [
  {
    role: 'user',
    text: 'How many unique leads contacted me this week?',
  },
  {
    role: 'ai',
    text: '7 unique leads reached out this week — up 40% from last week. 3 are in the "captured" stage and ready for a booking link. Your strongest day was Friday with 5 new contacts.',
  },
]

// ── Component ──────────────────────────────────────────────────────────────────

export function NexusAIPanel() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const reduce = useReducedMotion()

  // Focus the input when the panel opens
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => inputRef.current?.focus(), 200)
      return () => clearTimeout(t)
    }
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  const springConfig = { type: 'spring', damping: 30, stiffness: 280, mass: 0.8 } as const

  return (
    <>
      {/* ── Persistent floating tab — hides when the panel is open ────────────── */}
      <AnimatePresence>
        {!open && (
          <motion.button
            key="nexus-ai-tab"
            initial={reduce ? { opacity: 0 } : { x: 72, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { x: 72, opacity: 0 }}
            transition={springConfig}
            type="button"
            onClick={() => setOpen(true)}
            aria-label="Open Nexus AI assistant"
            className="fixed right-0 top-1/2 z-30 flex -translate-y-1/2 flex-col items-center gap-2 rounded-l-card border border-r-0 border-glow/40 bg-surface py-5 pl-2.5 pr-2 text-glow backdrop-blur-xl [box-shadow:var(--shadow-card)] hover:bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-glow"
          >
            <span className="text-[11px] leading-none" aria-hidden>✦</span>
            <span
              className="font-mono text-[9px] uppercase tracking-[0.15em] text-glow"
              style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}
            >
              Nexus AI
            </span>
          </motion.button>
        )}
      </AnimatePresence>

      {/* ── Slide-out panel + scrim ────────────────────────────────────────────── */}
      <AnimatePresence>
        {open && (
          <>
            {/* Scrim */}
            <motion.div
              key="nexus-ai-scrim"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="fixed inset-0 z-40 bg-bg/60 backdrop-blur-sm"
              aria-hidden
              onClick={() => setOpen(false)}
            />

            {/* Panel */}
            <motion.aside
              key="nexus-ai-panel"
              initial={reduce ? { opacity: 0 } : { x: 420, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={reduce ? { opacity: 0 } : { x: 420, opacity: 0 }}
              transition={springConfig}
              className="fixed right-0 top-0 z-50 flex h-screen w-[400px] flex-col border-l border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
              aria-label="Nexus AI assistant"
              role="dialog"
              aria-modal="true"
            >
              {/* Header */}
              <div className="flex items-center justify-between border-b border-line px-5 py-4">
                <div className="flex items-center gap-2.5">
                  <span className="text-base leading-none text-glow" aria-hidden>✦</span>
                  <div>
                    <div className="text-sm font-semibold text-ink">Nexus Data Analyst</div>
                    <div className="font-mono text-[10px] text-faint">preview · NLP query engine</div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Close AI assistant"
                  className="grid h-7 w-7 place-items-center rounded-control text-faint transition-colors hover:bg-raised hover:text-ink"
                >
                  <Icon name="x" size={15} />
                </button>
              </div>

              {/* Mini bar chart — visualises the mock answer */}
              <div className="border-b border-line px-5 py-4">
                <div className="mb-2.5 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
                  New leads · this week
                </div>
                <div className="flex h-14 items-end gap-1.5">
                  {WEEK_DATA.map(({ day, leads }) => (
                    <div key={day} className="flex flex-1 flex-col items-center gap-1">
                      <div
                        className="w-full rounded-sm bg-glow/30 transition-all duration-500"
                        style={{ height: `${Math.max((leads / WEEK_MAX) * 100, 4)}%` }}
                        aria-label={`${day}: ${leads} leads`}
                      />
                      <span className="font-mono text-[8px] text-faint">{day}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2.5 font-mono text-[10px] text-muted">
                  <span className="tabular-nums text-glow">7</span> total ·{' '}
                  <span className="text-success">↑ 40%</span> vs last week
                </div>
              </div>

              {/* Conversation */}
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                <div className="flex flex-col gap-3">
                  {CONVERSATION.map((msg, i) =>
                    msg.role === 'user' ? (
                      <div key={i} className="flex justify-end">
                        <div
                          className="max-w-[82%] rounded-card bg-accent px-3.5 py-2.5"
                          style={{ boxShadow: 'var(--shadow-glow)' }}
                        >
                          <p className="text-sm leading-relaxed text-ink">{msg.text}</p>
                        </div>
                      </div>
                    ) : (
                      <div key={i} className="flex justify-start">
                        <div className="max-w-[90%] rounded-card border border-glow/20 bg-raised px-3.5 py-2.5">
                          <div className="mb-1.5 flex items-center gap-1.5">
                            <span className="text-[9px] leading-none text-glow" aria-hidden>✦</span>
                            <span className="font-mono text-[9px] uppercase tracking-wider text-glow">
                              Nexus
                            </span>
                          </div>
                          <p className="text-sm leading-relaxed text-ink">{msg.text}</p>
                        </div>
                      </div>
                    ),
                  )}
                </div>
              </div>

              {/* Input */}
              <div className="border-t border-line px-5 py-4">
                <div className="flex items-center gap-2 rounded-control border border-line bg-bg/60 px-3.5 py-2.5 focus-within:border-glow/40 transition-colors">
                  <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Ask about your community…"
                    className="flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint"
                    aria-label="Ask the Nexus AI analyst"
                  />
                  <button
                    type="button"
                    disabled
                    title="NLP query engine — coming soon"
                    className="grid h-6 w-6 shrink-0 place-items-center rounded-control bg-glow/20 text-glow opacity-50 cursor-not-allowed"
                    aria-label="Send query (coming soon)"
                  >
                    <Icon name="send" size={12} />
                  </button>
                </div>
                <p className="mt-2 text-center font-mono text-[9px] text-faint">
                  NLP-to-graph engine · coming in the next workstream
                </p>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  )
}
