import { useState } from 'react'
import type { FormEvent } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import {
  ArrowRight,
  CircleAlert,
  Eye,
  EyeOff,
  LoaderCircle,
  Lock,
  Mail,
} from 'lucide-react'
import { NexusLogo } from '../../components/ui/nexus-logo'
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

  const fieldCls =
    'flex items-center gap-2.5 rounded-lg border border-[rgba(148,186,255,0.12)] bg-[#04070f] px-3 transition-[border-color,box-shadow] duration-200 ' +
    'focus-within:border-[rgba(59,130,246,0.65)] focus-within:[box-shadow:0_0_0_1px_rgba(59,130,246,0.35)]'

  return (
    <div className="relative flex min-h-screen items-center justify-center px-6">
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.36, ease: EASE }}
        className="relative w-[380px] max-w-full"
      >
        {/* Brand — the Plumb */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <NexusLogo size={52} className="text-ink" />
          <span className="font-mono text-[10px] uppercase tracking-[0.45em] text-faint">Nexus</span>
        </div>

        <div
          className="rounded-xl border border-[rgba(148,186,255,0.10)] bg-[#070b16] p-7"
          style={{ boxShadow: 'inset 0 1px 0 rgba(190,214,255,0.05), 0 24px 48px -24px rgba(0,0,0,0.7)' }}
        >
          {!isSupabaseConfigured ? (
            <ConfigError />
          ) : (
            <>
              <h1 className="text-[17px] font-semibold tracking-tight text-ink">Sign in to Nexus</h1>
              <p className="mt-1 text-[13px] text-muted">Your command center is waiting.</p>

              <form onSubmit={onSubmit} className="mt-6">
                <label htmlFor="cockpit-email" className="mb-1.5 block text-[11px] font-medium text-muted">
                  Email
                </label>
                <div className={fieldCls}>
                  <Mail size={14} strokeWidth={1.8} aria-hidden className="shrink-0 text-faint" />
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

                <label htmlFor="cockpit-password" className="mb-1.5 mt-4 block text-[11px] font-medium text-muted">
                  Password
                </label>
                <div className={fieldCls}>
                  <Lock size={14} strokeWidth={1.8} aria-hidden className="shrink-0 text-faint" />
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
                    {showPw ? <EyeOff size={15} strokeWidth={1.8} /> : <Eye size={15} strokeWidth={1.8} />}
                  </button>
                </div>

                {error && (
                  <motion.p
                    initial={reduce ? false : { opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-3 flex items-center gap-2 text-[13px] text-danger"
                  >
                    <CircleAlert size={14} strokeWidth={1.8} aria-hidden /> {error}
                  </motion.p>
                )}

                <button
                  type="submit"
                  disabled={busy !== false}
                  className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg bg-accent py-2.5 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#2f74e8] active:bg-[#2861c9] disabled:opacity-60"
                >
                  {busy === 'password' ? (
                    <>
                      <LoaderCircle size={15} className="animate-spin" aria-hidden /> Signing in…
                    </>
                  ) : (
                    <>
                      Sign in <ArrowRight size={14} strokeWidth={2} aria-hidden />
                    </>
                  )}
                </button>
              </form>

              <div className="my-5 flex items-center gap-3">
                <span className="h-px flex-1 bg-[rgba(148,186,255,0.08)]" />
                <span className="text-[10px] uppercase tracking-[0.14em] text-faint">or</span>
                <span className="h-px flex-1 bg-[rgba(148,186,255,0.08)]" />
              </div>

              <button
                type="button"
                onClick={onGoogle}
                disabled={busy !== false}
                className="flex w-full items-center justify-center gap-2.5 rounded-lg border border-[rgba(148,186,255,0.12)] bg-transparent py-2.5 text-sm font-medium text-ink transition-colors duration-200 hover:bg-[rgba(148,186,255,0.05)] disabled:opacity-60"
              >
                {busy === 'google' ? (
                  <LoaderCircle size={15} className="animate-spin" aria-hidden />
                ) : (
                  <GoogleMark size={15} />
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
