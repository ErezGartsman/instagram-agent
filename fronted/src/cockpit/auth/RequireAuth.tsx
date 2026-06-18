import type { ReactNode } from 'react'
import { useAuth } from './AuthProvider'
import { LoginScreen } from './LoginScreen'
import { Icon } from '../components/Icon'
import type { IconName } from '../components/Icon'

/**
 * The Cockpit auth gate, and the single place that applies `.cockpit-root`.
 * Two layers must both pass: a valid Supabase session AND a server-side `allowed`
 * verdict from /api/cockpit/me. Anything else fails closed (login / denied / error).
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { loading, session, access } = useAuth()

  let content: ReactNode
  if (loading) content = <AuthSplash label="Loading" />
  else if (!session) content = <LoginScreen />
  else if (access === 'checking') content = <AuthSplash label="Verifying access" />
  else if (access === 'allowed') content = children
  else if (access === 'denied') content = <AccessDenied />
  else content = <VerifyError />

  return <div className="cockpit-root min-h-screen bg-bg text-ink">{content}</div>
}

function AuthSplash({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <span className="text-lg font-semibold text-ink">Nexus</span>
      <span className="h-0.5 w-10 animate-pulse bg-accent" aria-hidden />
      <span className="text-sm text-muted">{label}…</span>
    </div>
  )
}

function AccessDenied() {
  const { user, signOut } = useAuth()
  return (
    <CenteredCard
      icon="alert"
      tone="text-danger"
      title="Access not approved"
      body={
        user?.email
          ? `${user.email} isn't on the Cockpit allow-list. Ask the owner to add it, or sign in with an approved address.`
          : "This account isn't on the Cockpit allow-list. Sign in with an approved address."
      }
    >
      <GhostButton onClick={() => signOut()} />
    </CenteredCard>
  )
}

function VerifyError() {
  const { recheck, signOut } = useAuth()
  return (
    <CenteredCard
      icon="alert"
      tone="text-warn"
      title="Couldn't verify access"
      body="We hit a snag confirming your access with the server. Check your connection and try again."
    >
      <button
        onClick={recheck}
        className="rounded-control bg-accent px-4 py-2 text-sm font-semibold text-bg transition-opacity hover:opacity-90"
      >
        Try again
      </button>
      <GhostButton onClick={() => signOut()} />
    </CenteredCard>
  )
}

function GhostButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 rounded-control border border-line px-3 py-2 text-sm text-muted transition-colors hover:bg-raised hover:text-ink"
    >
      <Icon name="logout" size={15} />
      Sign out
    </button>
  )
}

function CenteredCard({
  icon,
  tone,
  title,
  body,
  children,
}: {
  icon: IconName
  tone: string
  title: string
  body: string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-[360px] max-w-full rounded-card border border-line bg-surface p-8 text-center">
        <span
          className={`mx-auto mb-4 grid h-12 w-12 place-items-center rounded-card border border-line bg-raised ${tone}`}
        >
          <Icon name={icon} size={22} />
        </span>
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        <p className="mt-2 text-sm text-muted">{body}</p>
        <div className="mt-6 flex items-center justify-center gap-3">{children}</div>
      </div>
    </div>
  )
}
