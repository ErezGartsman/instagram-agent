import { useLocation } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { useAuth } from '../auth/AuthProvider'
import { NAV } from './nav'

export function Topbar() {
  const { pathname } = useLocation()
  const { user, signOut, devBypass } = useAuth()
  const title = NAV.find((n) => n.to === pathname)?.label ?? 'Cockpit'

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-line bg-bg px-8">
      <h1 className="text-base font-semibold text-ink">{title}</h1>
      <div className="flex items-center gap-4">
        {devBypass && (
          <span className="rounded-control border border-line px-2 py-0.5 text-xs text-warn">
            dev session
          </span>
        )}
        {user?.email && <span className="hidden text-sm text-muted sm:inline">{user.email}</span>}
        <button
          onClick={() => signOut()}
          className="flex items-center gap-2 rounded-control border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:bg-raised hover:text-ink"
        >
          <Icon name="logout" size={15} />
          <span>Sign out</span>
        </button>
      </div>
    </header>
  )
}
