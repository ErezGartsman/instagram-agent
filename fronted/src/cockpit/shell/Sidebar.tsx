import { NavLink } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { NAV_SECTIONS } from './nav'

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface backdrop-blur-xl">
      {/* Brand mark */}
      <div className="flex h-16 items-center gap-3 border-b border-line px-5">
        <span className="grid h-7 w-7 place-items-center rounded-control bg-accent text-bg">
          <Icon name="grid" size={15} />
        </span>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold text-ink">Nexus</span>
          <span className="text-xs text-muted">Cockpit</span>
        </div>
      </div>

      {/* Grouped nav: Work · Studio · Insight */}
      <nav className="flex flex-1 flex-col gap-5 p-3">
        {NAV_SECTIONS.filter((s) => s.items.length > 0).map((section, i) => (
          <div key={section.label ?? `s${i}`} className="flex flex-col gap-1">
            {section.label && (
              <span className="px-3 pb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                {section.label}
              </span>
            )}
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/app'}
                className={({ isActive }) =>
                  `relative flex items-center gap-3 rounded-control px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? 'bg-raised font-semibold text-ink [box-shadow:inset_0_0_16px_rgba(124,58,237,0.12)]'
                      : 'text-muted hover:bg-surface hover:text-ink'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {/* Neon filament pip — glows when active */}
                    <span
                      className={`absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-glow transition-all duration-200 ${
                        isActive
                          ? 'opacity-100 [box-shadow:var(--shadow-glow)]'
                          : 'opacity-0'
                      }`}
                      aria-hidden
                    />
                    <Icon name={item.icon} size={18} />
                    <span>{item.label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  )
}
