import { useLocation } from 'react-router-dom'
import { Search } from 'lucide-react'
import { NAV } from './nav'
import { AvatarMenu } from './AvatarMenu'

/**
 * Top bar — page title (left), ⌘K search hint (center), account avatar (right).
 * The search hint is a static shortcut chip, not a live input — global search
 * is a P1 feature. The chip signals the affordance without faking functionality.
 */
export function Topbar() {
  const { pathname } = useLocation()
  const title = NAV.find((n) => n.to === pathname)?.label ?? 'Cockpit'

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-surface px-6 backdrop-blur-xl">
      <h1 className="shrink-0 text-sm font-medium text-muted">{title}</h1>

      <div className="hidden flex-1 justify-center md:flex">
        <SearchHint />
      </div>

      <div className="ml-auto md:ml-0">
        <AvatarMenu />
      </div>
    </header>
  )
}

/**
 * A keyboard-shortcut hint chip occupying the Topbar's centre slot.
 * It is deliberately NOT an input — global search (⌘K) lands in P1.
 * Hovering reveals a "coming in P1" tooltip so the inert state is
 * 100% intentional, never a broken promise.
 */
function SearchHint() {
  return (
    <div className="group relative">
      <button
        type="button"
        aria-label="Global search — arriving in P1"
        tabIndex={-1}
        className="flex cursor-default items-center gap-2.5 rounded-control border border-line bg-bg/60 px-4 py-2 text-sm text-faint backdrop-blur-xl transition-colors duration-200 hover:border-[rgba(184,134,11,0.22)] hover:text-muted"
      >
        <Search size={14} strokeWidth={1.8} aria-hidden className="shrink-0" />
        <span>Search</span>
        <kbd className="ml-1 rounded border border-line px-1.5 py-px font-mono text-[10px] leading-none text-faint">
          ⌘K
        </kbd>
      </button>

      {/* CSS-only tooltip — no JS state, no delay, pure transition */}
      <span
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-full mt-2 -translate-x-1/2 whitespace-nowrap rounded-control border border-line bg-surface px-3 py-1.5 text-[11px] text-muted opacity-0 backdrop-blur-xl transition-opacity duration-150 group-hover:opacity-100 [box-shadow:var(--shadow-card)]"
      >
        Global search · arriving in P1
      </span>
    </div>
  )
}
