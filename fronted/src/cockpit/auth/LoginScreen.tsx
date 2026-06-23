import { useState } from 'react'
import type { FormEvent } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import {
  ArrowRight,
  CircleAlert,
  Eye,
  EyeOff,
  Hexagon,
  LoaderCircle,
  Lock,
  Mail,
} from 'lucide-react'
import { useAuth } from './AuthProvider'
import { isSupabaseConfigured } from '../lib/supabase'

const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]

/** The official multicolour Google "G" — lucide v1 dropped brand glyphs, and the
 *  real mark is the premium, recognizable choice for the OAuth button. */
function GoogleMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden className="shrink-0">
      <path fill="#4285F4" d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z" />
      <path fill="#34A853" d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z" />
      <path fill="#FBBC05" d="M11.69 28.18c-.44-1.32-.69-2.73-.69-4.18s.25-2.86.69-4.18v-5.7H4.34A21.99 21.99 0 0 0 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z" />
      <path fill="#EA4335" d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z" />
    </svg>
  )
}

export function LoginScreen() {
  const { signInWithPassword, signInWithGoogle } = useAuth()
  const reduce = useReducedMotion()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [busy, setBusy] = useState<false | 'password' | 'google'>(false)
  const [error, setError] = useState('')

  const clean = (msg: string) =>
    /invalid login credentials/i.test(msg)
      ? 'Invalid credentials — check your email and password.'
      : msg

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (!email.trim() || !password) {
      setError('Enter your email and password.')
      return
    }
    setBusy('password')
    setError('')
    const { error: err } = await signInWithPassword(email.trim(), password)
    if (err) {
      setBusy(false)
      setError(clean(err))
    }
    // On success, onAuthStateChange updates the session → RequireAuth swaps in the app.
  }

  const onGoogle = async () => {
    if (busy) return
    setBusy('google')
    setError('')
    const { error: err } = await signInWithGoogle()
    if (err) {
      setBusy(false)
      setError(clean(err))
    }
    // On success the browser redirects to Google's consent screen.
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-6">
      {/* Ambient gold glow — a soft champagne pool behind the card for warmth. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 h-[460px] w-[460px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ background: 'radial-gradient(circle, rgba(184,134,11,0.12) 0%, transparent 70%)' }}
      />

      <motion.div
        initial={reduce ? false : { opacity: 0, y: 14, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.42, ease: EASE }}
        className="relative w-[380px] max-w-full"
      >
        {/* Brand — Warm Gold Hexagon */}
        <div className="mb-7 flex items-center justify-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-control bg-accent text-bg [box-shadow:0_0_18px_rgba(184,134,11,0.45)]">
            <Hexagon size={18} strokeWidth={2} aria-hidden />
          </span>
          <div className="flex flex-col leading-tight">
            <span className="text-base font-semibold text-ink">Nexus</span>
            <span className="text-xs text-faint">Cockpit</span>
          </div>
        </div>

        <div className="rounded-card border border-line bg-surface p-8 backdrop-blur-xl [box-shadow:var(--shadow-card)]">
          {!isSupabaseConfigured ? (
            <ConfigError />
          ) : (
            <>
              <h1 className="text-xl font-semibold text-ink">Enter the Cockpit</h1>
              <p className="mt-1.5 text-sm text-muted">Sign in to your command center.</p>

              <form onSubmit={onSubmit} className="mt-6">
                <label htmlFor="cockpit-email" className="mb-1.5 block text-xs text-muted">
                  Email
                </label>
                <div className="cq-field flex items-center gap-2.5 rounded-control border border-line bg-bg/70 px-3.5">
                  <Mail size={16} strokeWidth={1.8} aria-hidden className="shrink-0 text-faint" />
                  <input
                    id="cockpit-email"
                    type="email"
                    autoFocus
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full bg-transparent py-2.5 text-sm text-ink outline-none placeholder:text-faint"
                  />
                </div>

                <label htmlFor="cockpit-password" className="mb-1.5 mt-4 block text-xs text-muted">
                  Password
                </label>
                <div className="cq-field flex items-center gap-2.5 rounded-control border border-line bg-bg/70 px-3.5">
                  <Lock size={16} strokeWidth={1.8} aria-hidden className="shrink-0 text-faint" />
                  <input
                    id="cockpit-password"
                    type={showPw ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full bg-transparent py-2.5 text-sm text-ink outline-none placeholder:text-faint"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((s) => !s)}
                    aria-label={showPw ? 'Hide password' : 'Show password'}
                    className="shrink-0 text-faint transition-colors hover:text-muted"
                  >
                    {showPw ? <EyeOff size={16} strokeWidth={1.8} /> : <Eye size={16} strokeWidth={1.8} />}
                  </button>
                </div>

                {error && (
                  <motion.p
                    initial={reduce ? false : { opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-3 flex items-center gap-2 text-sm text-danger"
                  >
                    <CircleAlert size={15} strokeWidth={1.8} aria-hidden /> {error}
                  </motion.p>
                )}

                <motion.button
                  type="submit"
                  disabled={busy !== false}
                  whileHover={reduce || busy ? undefined : { scale: 1.02 }}
                  whileTap={reduce || busy ? undefined : { scale: 0.98 }}
                  className="mt-6 flex w-full items-center justify-center gap-2 rounded-control bg-accent py-2.5 text-sm font-semibold text-bg transition-all hover:opacity-90 disabled:opacity-60 [box-shadow:var(--shadow-glow)]"
                >
                  {busy === 'password' ? (
                    <>
                      <LoaderCircle size={16} className="animate-spin" aria-hidden /> Entering…
                    </>
                  ) : (
                    <>
                      Enter Cockpit <ArrowRight size={15} strokeWidth={2} aria-hidden />
                    </>
                  )}
                </motion.button>
              </form>

              {/* Glass divider */}
              <div className="my-5 flex items-center gap-3">
                <span className="h-px flex-1 bg-line" />
                <span className="text-[11px] uppercase tracking-[0.14em] text-faint">or</span>
                <span className="h-px flex-1 bg-line" />
              </div>

              <button
                type="button"
                onClick={onGoogle}
                disabled={busy !== false}
                className="flex w-full items-center justify-center gap-2.5 rounded-control border border-line bg-raised py-2.5 text-sm font-medium text-ink backdrop-blur-xl transition-colors hover:bg-surface disabled:opacity-60"
              >
                {busy === 'google' ? (
                  <LoaderCircle size={16} className="animate-spin" aria-hidden />
                ) : (
                  <GoogleMark size={16} />
                )}
                Continue with Google
              </button>
            </>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-faint">Access is limited to approved addresses.</p>
      </motion.div>
    </div>
  )
}

function ConfigError() {
  return (
    <div className="text-center">
      <span className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-card border border-line bg-raised text-danger">
        <CircleAlert size={22} strokeWidth={1.8} aria-hidden />
      </span>
      <h1 className="text-xl font-semibold text-ink">Not configured</h1>
      <p className="mt-2 text-sm text-muted">
        Supabase keys are missing. Add <code className="text-ink">VITE_SUPABASE_URL</code> and{' '}
        <code className="text-ink">VITE_SUPABASE_ANON_KEY</code> to{' '}
        <code className="text-ink">.env.local</code>, then restart the dev server.
      </p>
    </div>
  )
}
