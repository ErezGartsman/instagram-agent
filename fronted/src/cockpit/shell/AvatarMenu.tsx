import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Bell, ChevronDown, LogOut } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'
import { useNotifications } from '../lib/useNotifications'

/**
 * The account control on the Topbar's far right. Avatar priority:
 *   1. Google profile picture (avatarUrl from user_metadata)
 *   2. Gold initials disc — premium fallback for email/password users
 *      and Google URLs that fail to load.
 * Closes on outside-click and Escape; respects the motion budget.
 */
export function AvatarMenu() {
  const { profile, user, avatarUrl, displayName, signOut } = useAuth()
  const { pref: notifPref, enable: enableNotif, disable: disableNotif } = useNotifications()
  const reduce = useReducedMotion()
  const [open, setOpen] = useState(false)
  const [imgOk, setImgOk] = useState(true)
  const ref = useRef<HTMLDivElement>(null)

  const email = profile?.email ?? user?.email ?? ''
  const initial = displayName.charAt(0).toUpperCase()

  // Reset image error state whenever the URL changes (e.g. after re-login).
  useEffect(() => { setImgOk(true) }, [avatarUrl])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  /** Renders the avatar image or the gold initials disc fallback. */
  const AvatarFace = () =>
    imgOk && avatarUrl ? (
      <img
        src={avatarUrl}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setImgOk(false)}
        className="h-full w-full object-cover"
      />
    ) : (
      <span
        aria-hidden
        className="grid h-full w-full place-items-center rounded-full bg-accent font-mono text-[11px] font-semibold text-bg"
      >
        {initial}
      </span>
    )

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className={`group flex items-center gap-2 rounded-full p-0.5 pr-2 transition-colors duration-200 ${
          open ? 'bg-surface' : 'hover:bg-surface'
        }`}
      >
        <span
          className={`grid h-8 w-8 place-items-center overflow-hidden rounded-full ring-1 transition-all duration-200 ${
            open
              ? 'ring-glow [box-shadow:var(--shadow-glow)]'
              : 'ring-line group-hover:ring-glow group-hover:[box-shadow:var(--shadow-glow)]'
          }`}
        >
          <AvatarFace />
        </span>
        <ChevronDown
          size={14}
          aria-hidden
          className={`text-faint transition-transform duration-200 ${open ? 'rotate-180 text-muted' : ''}`}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            aria-label="Account"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.16, ease: [0.25, 0.4, 0.25, 1] }}
            className="absolute right-0 top-full z-50 mt-2 w-60 origin-top-right overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
          >
            {/* Identity header */}
            <div className="flex items-center gap-3 border-b border-line px-4 py-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center overflow-hidden rounded-full ring-1 ring-line">
                <AvatarFace />
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink">{displayName}</p>
                <p className="truncate text-xs text-faint">{email}</p>
              </div>
            </div>

            {/* Items */}
            <div className="p-1.5">
              {/* Hot-lead alert toggle — temporary home until WS5 Settings route */}
              {notifPref !== 'unavailable' && (
                <button
                  role="menuitem"
                  type="button"
                  disabled={notifPref === 'denied'}
                  onClick={() => {
                    if (notifPref === 'on') disableNotif()
                    else void enableNotif()
                  }}
                  title={notifPref === 'denied' ? 'Notifications blocked in browser settings' : undefined}
                  className="flex w-full items-center justify-between gap-3 rounded-control px-3 py-2 text-sm text-muted transition-colors hover:bg-raised hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <span className="flex items-center gap-3">
                    <Bell size={16} strokeWidth={1.8} aria-hidden />
                    Hot lead alerts
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 font-mono text-[10px] leading-none ${
                      notifPref === 'on'
                        ? 'bg-[rgba(127,169,127,0.15)] text-success'
                        : 'text-faint'
                    }`}
                  >
                    {notifPref === 'on' ? 'on' : notifPref === 'denied' ? 'blocked' : 'off'}
                  </span>
                </button>
              )}
              <button
                role="menuitem"
                type="button"
                onClick={() => {
                  setOpen(false)
                  void signOut()
                }}
                className="flex w-full items-center gap-3 rounded-control px-3 py-2 text-sm text-muted transition-colors hover:bg-raised hover:text-danger"
              >
                <LogOut size={16} strokeWidth={1.8} aria-hidden />
                Sign out
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
