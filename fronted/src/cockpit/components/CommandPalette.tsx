import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { LoaderCircle, Search } from 'lucide-react'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import { useAuth } from '../auth/AuthProvider'
import { searchCockpit, type SearchResult, type SearchResultType } from '../lib/api'
import { NAV } from '../shell/nav'

const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]
const DEBOUNCE_MS = 200

// Static pages — derived from the live nav so they're always in sync.
const PAGE_RESULTS: SearchResult[] = NAV.map((item) => ({
  type: 'page',
  id: item.to,
  label: item.label,
  sublabel: 'Go to page',
  route: item.to,
}))

const TYPE_ICON: Record<SearchResultType, IconName> = {
  page: 'grid',
  person: 'queue',
  content: 'sparkle',
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function ResultSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="px-4 pb-1 pt-3 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
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
        className={`grid h-7 w-7 shrink-0 place-items-center rounded-control border border-line ${
          isActive ? 'text-glow' : 'text-faint'
        } bg-surface`}
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

/**
 * ⌘K command palette. Controlled by `open` / `onClose` from AppShell,
 * which also owns the global ⌘K keyboard listener.
 *
 * - Pages: filtered client-side, instant.
 * - People + Content: debounced server search (200 ms, ≥ 2 chars).
 * - ↑↓ moves focus, ↵ selects, Esc closes.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { session, devBypass } = useAuth()
  const navigate = useNavigate()
  const reduce = useReducedMotion()

  const [query, setQuery] = useState('')
  const [serverResults, setServerResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)

  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Reset + focus on open
  useEffect(() => {
    if (open) {
      setQuery('')
      setServerResults([])
      setActiveIdx(0)
      setLoading(false)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  // Reset active index whenever results change
  useEffect(() => { setActiveIdx(0) }, [query])

  // Debounced server search (≥ 2 chars)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (query.length < 2) {
      setServerResults([])
      setLoading(false)
      return
    }
    setLoading(true)
    debounceRef.current = setTimeout(async () => {
      const token = session?.access_token
      if (!token && !devBypass) { setLoading(false); return }
      try {
        const results = token ? await searchCockpit(token, query) : []
        setServerResults(results)
      } finally {
        setLoading(false)
      }
    }, DEBOUNCE_MS)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [query, session?.access_token, devBypass])

  // Derive grouped + flat result lists
  const filteredPages = query.length === 0
    ? PAGE_RESULTS
    : PAGE_RESULTS.filter((p) => p.label.toLowerCase().includes(query.toLowerCase()))
  const people  = serverResults.filter((r) => r.type === 'person')
  const content = serverResults.filter((r) => r.type === 'content')

  // Flat list for keyboard nav: pages → people → content
  const allResults: SearchResult[] = [...filteredPages, ...people, ...content]
  const pageLen   = filteredPages.length
  const personLen = people.length

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
        setActiveIdx((i) => Math.min(i + 1, allResults.length - 1))
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx((i) => Math.max(i - 1, 0))
      }
      if (e.key === 'Enter' && allResults[activeIdx]) {
        e.preventDefault()
        select(allResults[activeIdx])
      }
    },
    [allResults, activeIdx, close, select],
  )

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
            {/* Search input row */}
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
              {loading ? (
                <LoaderCircle size={14} aria-hidden className="animate-spin text-faint" />
              ) : (
                <kbd className="rounded border border-line px-1.5 py-px font-mono text-[10px] text-faint">
                  esc
                </kbd>
              )}
            </div>

            {/* Results */}
            <div className="max-h-[380px] overflow-y-auto">
              {allResults.length === 0 && query.length >= 2 && !loading && (
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

              {/* Empty state when query is short: show all pages */}
              {allResults.length === 0 && query.length < 2 && (
                <ResultSection label="Pages">
                  {PAGE_RESULTS.map((r, i) => (
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
            </div>

            {/* Footer keyboard hint */}
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
