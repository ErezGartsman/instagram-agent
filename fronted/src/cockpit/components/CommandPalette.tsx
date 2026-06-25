import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { LoaderCircle, Search } from 'lucide-react'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import { useAuth } from '../auth/AuthProvider'
import { searchCockpit, type SearchResult, type SearchResultType } from '../lib/api'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from '../lib/workqueue'
import { NAV } from '../shell/nav'

const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]
const DEBOUNCE_MS = 200
const TOP_LEADS_COUNT = 3

// Static pages — filtered client-side in the typed state only.
const PAGE_RESULTS: SearchResult[] = NAV.map((item) => ({
  type: 'page',
  id: item.to,
  label: item.label,
  sublabel: 'Go to page',
  route: item.to,
}))

// Quick actions — verb-first, intent-driven. Appears in the empty state.
const QUICK_ACTIONS: SearchResult[] = [
  {
    type: 'action',
    id: 'draft-reply-ai',
    label: '✦ Draft reply with AI',
    sublabel: 'Open the top lead and stream a draft reply with the Copilot',
    route: '/app/queue?draft=1',
  },
  {
    type: 'action',
    id: 'new-content-piece',
    label: 'New content piece',
    sublabel: 'Create and open in Content Studio',
    route: '/app/content?new=1',
  },
]

const TYPE_ICON: Record<SearchResultType, IconName> = {
  page:    'grid',
  person:  'queue',
  content: 'sparkle',
  action:  'sparkle',
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ResultSection({
  label,
  accent = false,
  children,
}: {
  label: string
  accent?: boolean
  children: ReactNode
}) {
  return (
    <div>
      <p
        className={`px-4 pb-1 pt-3 font-mono text-[10px] uppercase tracking-[0.13em] ${
          accent ? 'text-glow' : 'text-faint'
        }`}
      >
        {label}
      </p>
      {children}
    </div>
  )
}

function ResultRow({
  result,
  isActive,
  onSelect,
  onHover,
}: {
  result: SearchResult
  isActive: boolean
  onSelect: () => void
  onHover: () => void
}) {
  const rowRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (isActive) rowRef.current?.scrollIntoView({ block: 'nearest' })
  }, [isActive])

  return (
    <button
      ref={rowRef}
      type="button"
      onClick={onSelect}
      onMouseEnter={onHover}
      className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
        isActive ? 'bg-raised' : 'hover:bg-raised'
      }`}
    >
      <span
        className={`grid h-7 w-7 shrink-0 place-items-center rounded-control border border-line bg-surface ${
          isActive ? 'text-glow' : 'text-faint'
        }`}
      >
        <Icon name={TYPE_ICON[result.type]} size={13} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{result.label}</p>
        <p className="truncate text-xs text-faint">{result.sublabel}</p>
      </div>
      {isActive && (
        <kbd className="shrink-0 rounded border border-line px-1.5 py-px font-mono text-[10px] text-faint">
          ↵
        </kbd>
      )}
    </button>
  )
}

function Hint({ keys, label }: { keys: string[]; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {keys.map((k) => (
        <kbd key={k} className="rounded border border-line px-1.5 py-px font-mono text-[10px] text-faint">
          {k}
        </kbd>
      ))}
      <span className="text-[10px] text-faint">{label}</span>
    </div>
  )
}

// ── CommandPalette ──────────────────────────────────────────────────────────────
//
// Two distinct modes:
//
//   EMPTY STATE (query === ''):
//     "Needs you now" — top-3 ranked leads fetched on open (propose→dispose).
//     "Quick actions"  — global verbs (new content piece, …).
//     Pages are NOT shown here — they're already in the sidebar.
//
//   TYPED STATE (query !== ''):
//     Pages filtered instantly client-side (nav-level jump, useful when typed).
//     People + Content via debounced server search (≥ 2 chars, 200 ms).
//
// Both modes share the same ↑↓ ↵ esc keyboard contract.

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { session, devBypass } = useAuth()
  const navigate = useNavigate()
  const reduce = useReducedMotion()

  const [query, setQuery]               = useState('')
  const [serverResults, setServerResults] = useState<SearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [topLeads, setTopLeads]           = useState<QueueItem[]>([])
  const [leadsLoading, setLeadsLoading]   = useState(false)
  const [activeIdx, setActiveIdx]         = useState(0)

  const inputRef    = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Open: reset state + fetch top leads ───────────────────────────────────
  useEffect(() => {
    if (!open) return
    setQuery('')
    setServerResults([])
    setActiveIdx(0)
    setSearchLoading(false)
    requestAnimationFrame(() => inputRef.current?.focus())

    // Fetch the top-3 ranked leads for "Needs you now"
    if (devBypass) {
      setTopLeads(rankQueue(SAMPLE_QUEUE).slice(0, TOP_LEADS_COUNT))
      return
    }
    const token = session?.access_token
    if (!token) return
    setLeadsLoading(true)
    fetchQueue(token)
      .then((items) => setTopLeads(rankQueue(items).slice(0, TOP_LEADS_COUNT)))
      .catch(() => setTopLeads([]))
      .finally(() => setLeadsLoading(false))
  }, [open, session?.access_token, devBypass])

  // ── Reset active index on query change ────────────────────────────────────
  useEffect(() => { setActiveIdx(0) }, [query])

  // ── Debounced server search (typed state, ≥ 2 chars) ─────────────────────
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 2) { setServerResults([]); setSearchLoading(false); return }
    setSearchLoading(true)
    debounceRef.current = setTimeout(async () => {
      const token = session?.access_token
      if (!token && !devBypass) { setSearchLoading(false); return }
      try {
        setServerResults(token ? await searchCockpit(token, query) : [])
      } finally {
        setSearchLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, session?.access_token, devBypass])

  // ── Derive navigation items (single source of truth for ↑↓ ↵) ───────────
  const isTyping = query.length > 0

  // Typed state: pages (instant) + server results
  const filteredPages = PAGE_RESULTS.filter((p) =>
    p.label.toLowerCase().includes(query.toLowerCase()),
  )
  const people  = serverResults.filter((r) => r.type === 'person')
  const content = serverResults.filter((r) => r.type === 'content')

  // Empty state: top leads + quick actions (converted to SearchResult shape)
  const leadItems: SearchResult[] = topLeads.map((lead) => ({
    type: 'person',
    id: lead.id,
    label: lead.name,
    sublabel: `${lead.action} · ${lead.confidence}%`,
    route: `/app/queue?focus=${lead.id}`,
  }))

  // Unified flat list for keyboard navigation — whichever mode is active
  const navItems: SearchResult[] = isTyping
    ? [...filteredPages, ...people, ...content]
    : [...leadItems, ...QUICK_ACTIONS]

  const pageLen   = filteredPages.length
  const personLen = people.length
  const leadLen   = leadItems.length

  // ── Actions ────────────────────────────────────────────────────────────────
  const close = useCallback(() => { onClose(); setQuery('') }, [onClose])

  const select = useCallback(
    (result: SearchResult) => { close(); navigate(result.route) },
    [close, navigate],
  )

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') { close(); return }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx((i) => Math.min(i + 1, navItems.length - 1))
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx((i) => Math.max(i - 1, 0))
      }
      if (e.key === 'Enter' && navItems[activeIdx]) {
        e.preventDefault()
        select(navItems[activeIdx])
      }
    },
    [navItems, activeIdx, close, select],
  )

  const isLoading = isTyping ? searchLoading : leadsLoading

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[400] bg-bg/70 backdrop-blur-sm"
            onClick={close}
            aria-hidden
          />

          {/* Panel */}
          <motion.div
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.2, ease: EASE }}
            role="dialog"
            aria-label="Command palette"
            aria-modal="true"
            onKeyDown={onKeyDown}
            className="fixed left-1/2 top-[18%] z-[401] w-[560px] max-w-[calc(100vw-2rem)] -translate-x-1/2 overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
          >
            {/* Input row */}
            <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
              <Search size={15} strokeWidth={1.8} aria-hidden className="shrink-0 text-faint" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Search leads, content, pages…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint"
                aria-label="Search the cockpit"
                autoComplete="off"
                spellCheck={false}
              />
              {isLoading ? (
                <LoaderCircle size={14} aria-hidden className="animate-spin text-faint" />
              ) : (
                <kbd className="rounded border border-line px-1.5 py-px font-mono text-[10px] text-faint">
                  esc
                </kbd>
              )}
            </div>

            {/* Results area */}
            <div className="max-h-[380px] overflow-y-auto">

              {/* ── EMPTY STATE ─────────────────────────────────────────── */}
              {!isTyping && (
                <>
                  {/* "Needs you now" — the decision engine's verdict */}
                  <ResultSection label="Needs you now" accent>
                    {leadsLoading && (
                      <div className="flex items-center gap-2 px-4 py-3 text-faint">
                        <LoaderCircle size={13} className="animate-spin" aria-hidden />
                        <span className="text-sm">Checking your queue…</span>
                      </div>
                    )}
                    {!leadsLoading && leadItems.length === 0 && (
                      <div className="flex items-center gap-2.5 px-4 py-3">
                        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-line bg-raised text-success">
                          <Icon name="check" size={11} />
                        </span>
                        <p className="text-sm text-muted">Queue clear — no one needs a move right now.</p>
                      </div>
                    )}
                    {!leadsLoading && leadItems.map((r, i) => (
                      <ResultRow
                        key={r.id}
                        result={r}
                        isActive={activeIdx === i}
                        onSelect={() => select(r)}
                        onHover={() => setActiveIdx(i)}
                      />
                    ))}
                  </ResultSection>

                  {/* Quick actions */}
                  <ResultSection label="Quick actions">
                    {QUICK_ACTIONS.map((r, i) => (
                      <ResultRow
                        key={r.id}
                        result={r}
                        isActive={activeIdx === leadLen + i}
                        onSelect={() => select(r)}
                        onHover={() => setActiveIdx(leadLen + i)}
                      />
                    ))}
                  </ResultSection>
                </>
              )}

              {/* ── TYPED STATE ─────────────────────────────────────────── */}
              {isTyping && (
                <>
                  {navItems.length === 0 && !searchLoading && (
                    <p className="px-4 py-10 text-center text-sm text-faint">
                      No results for &ldquo;{query}&rdquo;
                    </p>
                  )}

                  {filteredPages.length > 0 && (
                    <ResultSection label="Pages">
                      {filteredPages.map((r, i) => (
                        <ResultRow
                          key={r.id}
                          result={r}
                          isActive={activeIdx === i}
                          onSelect={() => select(r)}
                          onHover={() => setActiveIdx(i)}
                        />
                      ))}
                    </ResultSection>
                  )}

                  {people.length > 0 && (
                    <ResultSection label="People">
                      {people.map((r, i) => (
                        <ResultRow
                          key={r.id}
                          result={r}
                          isActive={activeIdx === pageLen + i}
                          onSelect={() => select(r)}
                          onHover={() => setActiveIdx(pageLen + i)}
                        />
                      ))}
                    </ResultSection>
                  )}

                  {content.length > 0 && (
                    <ResultSection label="Content">
                      {content.map((r, i) => (
                        <ResultRow
                          key={r.id}
                          result={r}
                          isActive={activeIdx === pageLen + personLen + i}
                          onSelect={() => select(r)}
                          onHover={() => setActiveIdx(pageLen + personLen + i)}
                        />
                      ))}
                    </ResultSection>
                  )}
                </>
              )}
            </div>

            {/* Footer hint */}
            <div className="flex items-center justify-end gap-5 border-t border-line px-4 py-2">
              <Hint keys={['↑', '↓']} label="navigate" />
              <Hint keys={['↵']} label="select" />
              <Hint keys={['esc']} label="close" />
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
