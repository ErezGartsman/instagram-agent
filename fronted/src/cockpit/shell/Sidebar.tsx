import { NavLink } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { NAV } from './nav'

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface">
      {/* Brand — the gold mark is the one signature element up here. */}
      <div className="flex h-16 items-center gap-3 border-b border-line px-5">
        <span className="grid h-7 w-7 place-items-center rounded-control bg-accent text-bg">
          <Icon name="grid" size={15} />
        </span>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold text-ink">Nexus</span>
          <span className="text-xs text-muted">Cockpit</span>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `relative flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors ${
                isActive
                  ? 'bg-raised font-semibold text-ink'
                  : 'text-muted hover:bg-raised hover:text-ink'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={`absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 bg-accent transition-opacity ${
                    isActive ? 'opacity-100' : 'opacity-0'
                  }`}
                  aria-hidden
                />
                <Icon name={item.icon} size={18} />
                <span>{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-line px-5 py-4">
        <p className="text-xs text-muted">Foundation · Ticket 5.0</p>
      </div>
    </aside>
  )
}
