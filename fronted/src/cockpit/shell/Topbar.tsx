import { useLocation } from 'react-router-dom'
import { Search } from 'lucide-react'
import { NAV } from './nav'
import { AvatarMenu } from './AvatarMenu'

/**
 * Top bar — page title (left), ⌘K trigger (center), account avatar (right).
 * Receives `onOpenPalette` from AppShell which owns the palette state and the
 * global ⌘K listener.
 */
export function Topbar({ onOpenPalette }: { onOpenPalette?: () => void }) {
  const { pathname } = useLocation()
  const title = NAV.find((n) => n.to === pathname)?.label ?? 'Cockpit'

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-surface px-6 backdrop-blur-xl">
      <h1 className="shrink-0 text-sm font-medium text-muted">{title}</h1>

      <div className="hidden flex-1 justify-center md:flex">
        <SearchHint onOpen={onOpenPalette} />
      </div>

      <div className="ml-auto md:ml-0">
        <AvatarMenu />
      </div>
    </header>
  )
}

/**
 * Clickable ⌘K trigger chip in the Topbar centre slot.
 * Clicking opens the CommandPalette; ⌘K from anywhere does the same
 * via AppShell's global listener.
 */
function SearchHint({ onOpen }: { onOpen?: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="Open command palette (⌘K)"
      className="flex w-[480px] items-center gap-2.5 rounded-control border border-line bg-bg/60 px-4 py-2 text-sm text-faint backdrop-blur-xl transition-colors duration-200 hover:border-[rgba(59,130,246,0.28)] hover:text-muted"
    >
      <Search size={14} strokeWidth={1.8} aria-hidden className="shrink-0" />
      <span>Search</span>
    </button>
  )
}
