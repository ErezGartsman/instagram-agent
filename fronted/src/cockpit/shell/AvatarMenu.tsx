import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { ChevronDown, CircleUser, LogOut, Settings } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

// High-quality Unsplash portrait — placeholder identity until real avatars land.
const AVATAR_SRC =
  'https://images.unsplash.com/photo-1633332755192-727a05c4013d?w=160&h=160&fit=crop&crop=faces&auto=format&q=80'

/**
 * The account control on the Topbar's far right: a premium avatar with a neon
 * hover-glow that opens a glassmorphic dropdown (identity · Settings · Sign out).
 * Closes on outside-click and Escape; the panel respects the motion budget.
 */
export function AvatarMenu() {
  const { profile, user, signOut } = useAuth()
  const reduce = useReducedMotion()
  const [open, setOpen] = useState(false)
  const [imgOk, setImgOk] = useState(true)
  const ref = useRef<HTMLDivElement>(null)

  const email = profile?.email ?? user?.email ?? 'Signed in'
  const name = email.includes('@') ? email.split('@')[0] : email

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

  const avatarImg = (size: number) =>
    imgOk ? (
      <img
        src={AVATAR_SRC}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setImgOk(false)}
        className="h-full w-full object-cover"
      />
    ) : (
      <CircleUser size={size} className="text-muted" aria-hidden />
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
          {avatarImg(18)}
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
                {avatarImg(20)}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium capitalize text-ink">{name}</p>
                <p className="truncate text-xs text-faint">{email}</p>
              </div>
            </div>

            {/* Items */}
            <div className="p-1.5">
              <button
                role="menuitem"
                type="button"
                onClick={() => setOpen(false)}
                className="flex w-full items-center gap-3 rounded-control px-3 py-2 text-sm text-muted transition-colors hover:bg-raised hover:text-ink"
              >
                <Settings size={16} strokeWidth={1.8} aria-hidden />
                Settings
              </button>
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
