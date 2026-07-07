import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'
import { LogOut, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { NexusLogo } from '../../components/ui/nexus-logo'
import { useAuth } from '../auth/AuthProvider'
import { useNavSignals } from '../lib/navSignals'
import { FOOTER_NAV, NAV_SECTIONS } from './nav'

const W_EXPANDED = 240
const W_COLLAPSED = 76
const STORAGE_KEY = 'nexus.cockpit.sidebar.collapsed'
const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]

/**
 * The Cockpit's left rail — collapsible to icons-only to cut cognitive load.
 * Framer Motion drives the width; labels fade to maxWidth:0 so the icons stay
 * perfectly centered with no spill. When collapsed, each icon gets a crisp glass
 * tooltip on hover. Collapse state persists across sessions in localStorage.
 */
export function Sidebar() {
  const { signOut } = useAuth()
  const reduce = useReducedMotion()
  const { yourMove, breach } = useNavSignals()
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1'
    } catch {
      return false
    }
  })

  const toggle = () =>
    setCollapsed((c) => {
      const next = !c
      try {
        localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
      } catch {
        /* storage unavailable — collapse still works for the session */
      }
      return next
    })

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? W_COLLAPSED : W_EXPANDED }}
      transition={reduce ? { duration: 0 } : { duration: 0.32, ease: EASE }}
      className="relative z-20 flex shrink-0 flex-col overflow-visible border-r border-line bg-surface backdrop-blur-xl"
    >
      {/* Brand mark */}
      <div
        className={`flex h-14 items-center border-b border-line ${
          collapsed ? 'justify-center px-0' : 'px-5'
        }`}
      >
        <span className="grid h-8 w-7 shrink-0 place-items-center text-ink">
          <NexusLogo size={30} />
        </span>
        <motion.div
          initial={false}
          animate={{
            maxWidth: collapsed ? 0 : 160,
            opacity: collapsed ? 0 : 1,
            marginLeft: collapsed ? 0 : 12,
          }}
          transition={reduce ? { duration: 0 } : { duration: 0.2, ease: EASE }}
          className="flex flex-col overflow-hidden whitespace-nowrap leading-tight"
        >
          <span className="text-sm font-semibold text-ink">Nexus</span>
          <span className="text-[11px] text-faint">Cockpit</span>
        </motion.div>
      </div>

      {/* Grouped nav: Work · Studio · Insight */}
      <nav className="flex flex-1 flex-col gap-5 p-3">
        {NAV_SECTIONS.filter((s) => s.items.length > 0).map((section, i) => (
          <div key={section.label ?? `s${i}`} className="flex flex-col gap-0.5">
            {section.label &&
              (collapsed ? (
                // Collapsed: micro-labels would crowd — a hairline keeps the grouping.
                i > 0 ? <span className="mx-2 my-1 h-px bg-line" aria-hidden /> : null
              ) : (
                <span className="px-3 pb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                  {section.label}
                </span>
              ))}
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/app'}
                aria-label={item.label}
                className={({ isActive }) =>
                  `group relative flex items-center rounded-control py-2 text-sm transition-colors ${
                    collapsed ? 'justify-center px-0' : 'px-3'
                  } ${
                    isActive
                      ? 'bg-raised font-semibold text-ink [box-shadow:inset_0_0_16px_rgba(59,130,246,0.12)]'
                      : 'text-muted hover:bg-surface hover:text-ink'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {/* Neon filament pip — glows when active */}
                    <span
                      className={`absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-glow transition-all duration-200 ${
                        isActive ? 'opacity-100 [box-shadow:var(--shadow-glow)]' : 'opacity-0'
                      }`}
                      aria-hidden
                    />
                    <motion.span
                      whileHover={reduce ? undefined : { scale: 1.15 }}
                      transition={{ duration: 0.15, ease: 'easeOut' }}
                      className="grid shrink-0 place-items-center"
                    >
                      <item.icon
                        size={18}
                        strokeWidth={1.8}
                        aria-hidden
                        className={isActive ? 'text-glow' : ''}
                      />
                    </motion.span>
                    <motion.span
                      initial={false}
                      animate={{
                        maxWidth: collapsed ? 0 : 160,
                        opacity: collapsed ? 0 : 1,
                        marginLeft: collapsed ? 0 : 12,
                      }}
                      transition={reduce ? { duration: 0 } : { duration: 0.2, ease: EASE }}
                      className="overflow-hidden whitespace-nowrap"
                    >
                      {item.label}
                    </motion.span>

                    {/* Accountability badge — the sidebar answers "do I need to go there?" */}
                    {item.to === '/app/queue' && yourMove > 0 && !collapsed && (
                      <span className="ml-auto flex items-center gap-1.5">
                        {breach > 0 && (
                          <span
                            aria-label={`${breach} breached`}
                            className="cq-sla-pulse h-1.5 w-1.5 rounded-full bg-danger [box-shadow:0_0_6px_rgba(224,112,92,0.8)]"
                          />
                        )}
                        <span className="rounded-full bg-accent/15 px-1.5 py-px font-mono text-[10px] tabular-nums text-glow">
                          {yourMove}
                        </span>
                      </span>
                    )}

                    {/* Glass tooltip — only when collapsed */}
                    {collapsed && (
                      <span className="pointer-events-none absolute left-full z-50 ml-3 -translate-x-1 whitespace-nowrap rounded-control border border-line bg-raised px-2.5 py-1.5 text-xs font-medium text-ink opacity-0 backdrop-blur-xl transition-all duration-150 [box-shadow:var(--shadow-card)] group-hover:translate-x-0 group-hover:opacity-100">
                        {item.label}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer — quiet destinations + collapse toggle + sign out */}
      <div className="flex flex-col gap-1 border-t border-line p-3">
        {FOOTER_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            aria-label={item.label}
            className={({ isActive }) =>
              `group relative flex items-center rounded-control py-2 text-sm transition-colors ${
                collapsed ? 'justify-center px-0' : 'px-3'
              } ${isActive ? 'bg-raised text-ink' : 'text-faint hover:bg-surface hover:text-muted'}`
            }
          >
            <span className="grid shrink-0 place-items-center">
              <item.icon size={16} strokeWidth={1.8} aria-hidden />
            </span>
            <motion.span
              initial={false}
              animate={{
                maxWidth: collapsed ? 0 : 160,
                opacity: collapsed ? 0 : 1,
                marginLeft: collapsed ? 0 : 12,
              }}
              transition={reduce ? { duration: 0 } : { duration: 0.2, ease: EASE }}
              className="overflow-hidden whitespace-nowrap"
            >
              {item.label}
            </motion.span>
            {collapsed && (
              <span className="pointer-events-none absolute left-full z-50 ml-3 -translate-x-1 whitespace-nowrap rounded-control border border-line bg-raised px-2.5 py-1.5 text-xs font-medium text-ink opacity-0 backdrop-blur-xl transition-all duration-150 [box-shadow:var(--shadow-card)] group-hover:translate-x-0 group-hover:opacity-100">
                {item.label}
              </span>
            )}
          </NavLink>
        ))}
        <FooterAction
          collapsed={collapsed}
          reduce={reduce}
          onClick={toggle}
          icon={collapsed ? PanelLeftOpen : PanelLeftClose}
          label={collapsed ? 'Expand' : 'Collapse'}
        />
        <FooterAction
          collapsed={collapsed}
          reduce={reduce}
          onClick={() => void signOut()}
          icon={LogOut}
          label="Sign out"
          danger
        />
      </div>
    </motion.aside>
  )
}

function FooterAction({
  collapsed,
  reduce,
  onClick,
  icon: IconCmp,
  label,
  danger,
}: {
  collapsed: boolean
  reduce: boolean | null
  onClick: () => void
  icon: LucideIcon
  label: string
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={`group relative flex items-center rounded-control py-2 text-sm text-faint transition-colors ${
        collapsed ? 'justify-center px-0' : 'px-3'
      } ${danger ? 'hover:bg-surface hover:text-danger' : 'hover:bg-surface hover:text-muted'}`}
    >
      <span className="grid shrink-0 place-items-center">
        <IconCmp size={16} strokeWidth={1.8} aria-hidden />
      </span>
      <motion.span
        initial={false}
        animate={{
          maxWidth: collapsed ? 0 : 160,
          opacity: collapsed ? 0 : 1,
          marginLeft: collapsed ? 0 : 12,
        }}
        transition={reduce ? { duration: 0 } : { duration: 0.2, ease: EASE }}
        className="overflow-hidden whitespace-nowrap"
      >
        {label}
      </motion.span>

      {collapsed && (
        <span className="pointer-events-none absolute left-full z-50 ml-3 -translate-x-1 whitespace-nowrap rounded-control border border-line bg-raised px-2.5 py-1.5 text-xs font-medium text-ink opacity-0 backdrop-blur-xl transition-all duration-150 [box-shadow:var(--shadow-card)] group-hover:translate-x-0 group-hover:opacity-100">
          {label}
        </span>
      )}
    </button>
  )
}
