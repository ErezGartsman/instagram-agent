import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Icon } from '../components/Icon'
import { useAuth } from '../auth/AuthProvider'
import { NAV_SECTIONS } from './nav'

export function Sidebar() {
  const { signOut } = useAuth()
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-surface backdrop-blur-xl">
      {/* Brand mark */}
      <div className="flex h-14 items-center gap-3 border-b border-line px-5">
        <span className="grid h-7 w-7 place-items-center rounded-control bg-accent text-bg">
          <Icon name="grid" size={15} />
        </span>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold text-ink">Nexus</span>
          <span className="text-[11px] text-faint">Cockpit</span>
        </div>
      </div>

      {/* Grouped nav: Work · Studio · Insight */}
      <nav className="flex flex-1 flex-col gap-5 p-3">
        {NAV_SECTIONS.filter((s) => s.items.length > 0).map((section, i) => (
          <div key={section.label ?? `s${i}`} className="flex flex-col gap-0.5">
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
                    <motion.span
                      whileHover={{ scale: 1.15 }}
                      transition={{ duration: 0.15, ease: 'easeOut' }}
                    >
                      <Icon name={item.icon} size={18} />
                    </motion.span>
                    <span>{item.label}</span>
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Sign out — sidebar footer */}
      <div className="border-t border-line p-3">
        <button
          onClick={() => signOut()}
          title="Sign out"
          className="flex w-full items-center gap-3 rounded-control px-3 py-2 text-sm text-faint transition-colors hover:bg-surface hover:text-muted"
        >
          <Icon name="logout" size={16} />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  )
}
