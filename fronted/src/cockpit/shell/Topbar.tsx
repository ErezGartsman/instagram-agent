import { useLocation } from 'react-router-dom'
import { NAV } from './nav'

/** Minimal top bar — page title only. User actions live in the Sidebar footer. */
export function Topbar() {
  const { pathname } = useLocation()
  const title = NAV.find((n) => n.to === pathname)?.label ?? 'Cockpit'

  return (
    <header className="flex h-14 shrink-0 items-center border-b border-line bg-surface backdrop-blur-xl px-8">
      <h1 className="text-sm font-medium text-muted">{title}</h1>
    </header>
  )
}
