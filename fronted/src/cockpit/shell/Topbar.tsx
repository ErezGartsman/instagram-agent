import { useLocation } from 'react-router-dom'
import { NAV } from './nav'
import { AnimatedSearchBar } from '../components/ui/animated-glowing-search-bar'
import { AvatarMenu } from './AvatarMenu'

/**
 * Top bar — page title (left), animated glow search (center), account avatar
 * (right). The search collapses below md so the bar stays uncluttered on narrow
 * viewports; the avatar then hugs the right edge.
 */
export function Topbar() {
  const { pathname } = useLocation()
  const title = NAV.find((n) => n.to === pathname)?.label ?? 'Cockpit'

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-surface px-6 backdrop-blur-xl">
      <h1 className="shrink-0 text-sm font-medium text-muted">{title}</h1>

      <div className="hidden flex-1 justify-center md:flex">
        <AnimatedSearchBar className="w-full max-w-md" />
      </div>

      <div className="ml-auto md:ml-0">
        <AvatarMenu />
      </div>
    </header>
  )
}
