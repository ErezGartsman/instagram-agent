import type { ReactNode } from 'react'
import { useAuth } from './AuthProvider'
import { LoginScreen } from './LoginScreen'

/**
 * The Cockpit auth gate. Also the single place that applies `.cockpit-root`, so
 * every authed/unauthed state below inherits the design-system reset and tokens.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { loading, session } = useAuth()

  return (
    <div className="cockpit-root min-h-screen bg-bg text-ink">
      {loading ? <AuthSplash /> : session ? children : <LoginScreen />}
    </div>
  )
}

function AuthSplash() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <span className="text-lg font-semibold text-ink">Nexus</span>
      <span className="h-0.5 w-10 animate-pulse bg-accent" aria-label="Loading" />
    </div>
  )
}
