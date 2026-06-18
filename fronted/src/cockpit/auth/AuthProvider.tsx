import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'
import { API_BASE } from '../lib/api'

/** Server-side verification status from GET /api/cockpit/me. */
export type Access = 'checking' | 'allowed' | 'denied' | 'error'

export type CockpitProfile = { id?: string; email?: string; role?: string }

type AuthValue = {
  session: Session | null
  user: User | null
  loading: boolean
  /**
   * Result of verifying the session against the backend allow-list. A valid local
   * session is necessary but NOT sufficient — the shell renders only when `allowed`.
   */
  access: Access
  profile: CockpitProfile | null
  recheck: () => void
  signInWithEmail: (email: string) => Promise<{ error: string | null }>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [access, setAccess] = useState<Access>('checking')
  const [profile, setProfile] = useState<CockpitProfile | null>(null)
  // Bumped by recheck() to re-run the verification effect (the "Try again" button).
  const [recheckNonce, setRecheckNonce] = useState(0)

  useEffect(() => {
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

  // Server-side gate. Runs whenever the access token changes (sign-in, refresh) or
  // recheck() is called. Fails CLOSED: any non-200 leaves access at denied/error,
  // never `allowed`, so a blocked or spoofed request can't reveal the shell.
  const token = session?.access_token
  useEffect(() => {
    if (!token) {
      setAccess('checking')
      setProfile(null)
      return
    }
    let cancelled = false
    const controller = new AbortController()
    // On a silent token refresh while already allowed, don't flash the splash.
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
      recheck,
      signInWithEmail: async (email) => {
        const { error } = await supabase.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: `${window.location.origin}/` },
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
