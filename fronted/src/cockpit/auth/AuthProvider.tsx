import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'
import { API_BASE } from '../lib/api'

/** Server-side verification status from GET /api/cockpit/me. */
export type Access = 'checking' | 'allowed' | 'denied' | 'error'

export type CockpitProfile = { id?: string; email?: string; role?: string }

// ── Dev-only auth bypass ─────────────────────────────────────────────────────
// Active under `vite dev` so local work needs no login and no running backend.
// NEVER active in production: `import.meta.env.DEV` is statically `false` in a
// production build, so every branch guarded by DEV_BYPASS is dead-code-eliminated
// and the strict two-layer gate is the only thing that ships. Set
// VITE_COCKPIT_DEV_BYPASS=off in .env.local to exercise the real login locally.
const DEV_EMAIL = 'erezkim1234@gmail.com'
const DEV_BYPASS = import.meta.env.DEV && import.meta.env.VITE_COCKPIT_DEV_BYPASS !== 'off'

if (DEV_BYPASS) {
  console.warn(
    `[cockpit] DEV auth bypass active — mocking session as ${DEV_EMAIL}. ` +
      'This never ships to production. Set VITE_COCKPIT_DEV_BYPASS=off to disable.',
  )
}

function devSession(): Session {
  return {
    access_token: 'dev-bypass',
    token_type: 'bearer',
    user: { id: 'dev-user', email: DEV_EMAIL, role: 'authenticated' },
  } as unknown as Session
}

type AuthValue = {
  session: Session | null
  user: User | null
  loading: boolean
  access: Access
  profile: CockpitProfile | null
  /** True when the dev-only auth bypass is active (never in production). */
  devBypass: boolean
  recheck: () => void
  signInWithEmail: (email: string) => Promise<{ error: string | null }>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(DEV_BYPASS ? devSession() : null)
  const [loading, setLoading] = useState(!DEV_BYPASS)
  const [access, setAccess] = useState<Access>(DEV_BYPASS ? 'allowed' : 'checking')
  const [profile, setProfile] = useState<CockpitProfile | null>(
    DEV_BYPASS ? { id: 'dev-user', email: DEV_EMAIL, role: 'authenticated' } : null,
  )
  const [recheckNonce, setRecheckNonce] = useState(0)

  useEffect(() => {
    if (DEV_BYPASS) return
    let active = true

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return
      setSession(data.session)
      setLoading(false)
    })

    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next)
      setLoading(false)
    })

    return () => {
      active = false
      sub.subscription.unsubscribe()
    }
  }, [])

  // Server-side gate. Fails CLOSED: any non-200 leaves access at denied/error.
  const token = session?.access_token
  useEffect(() => {
    if (DEV_BYPASS) return
    if (!token) {
      setAccess('checking')
      setProfile(null)
      return
    }
    let cancelled = false
    const controller = new AbortController()
    setAccess((prev) => (prev === 'allowed' ? prev : 'checking'))

    fetch(`${API_BASE}/api/cockpit/me`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (res) => {
        if (cancelled) return
        if (res.ok) {
          const data = (await res.json().catch(() => null)) as CockpitProfile | null
          setProfile(data)
          setAccess('allowed')
        } else if (res.status === 403) {
          setAccess('denied')
        } else {
          setAccess('error')
        }
      })
      .catch((err) => {
        if (!cancelled && err?.name !== 'AbortError') setAccess('error')
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [token, recheckNonce])

  const recheck = useCallback(() => setRecheckNonce((n) => n + 1), [])

  const value = useMemo<AuthValue>(
    () => ({
      session,
      user: session?.user ?? null,
      loading,
      access,
      profile,
      devBypass: DEV_BYPASS,
      recheck,
      signInWithEmail: async (email) => {
        const { error } = await supabase.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: `${window.location.origin}/app` },
        })
        return { error: error?.message ?? null }
      },
      signOut: async () => {
        await supabase.auth.signOut()
      },
    }),
    [session, loading, access, profile, recheck],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}
