import { useState } from 'react'
import type { FormEvent } from 'react'
import { useAuth } from './AuthProvider'
import { isSupabaseConfigured } from '../lib/supabase'
import { Icon } from '../components/Icon'

type Status = 'idle' | 'sending' | 'sent' | 'error'

export function LoginScreen() {
  const { signInWithEmail } = useAuth()
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState('')

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const addr = email.trim()
    if (!addr || status === 'sending') return
    setStatus('sending')
    setError('')
    const result = await signInWithEmail(addr)
    if (result.error) {
      setStatus('error')
      setError(result.error)
    } else {
      setStatus('sent')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-[360px] max-w-full">
        <div className="mb-8 flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-card bg-accent text-bg">
            <Icon name="grid" size={18} />
          </span>
          <div className="flex flex-col leading-tight">
            <span className="text-base font-semibold text-ink">Nexus</span>
            <span className="text-xs text-muted">Cockpit</span>
          </div>
        </div>

        <div className="rounded-card border border-line bg-surface p-8">
          {!isSupabaseConfigured ? (
            <ConfigError />
          ) : status === 'sent' ? (
            <SentState
              email={email.trim()}
              onReset={() => {
                setStatus('idle')
                setEmail('')
              }}
            />
          ) : (
            <form onSubmit={onSubmit}>
              <h1 className="text-xl font-semibold text-ink">Sign in to the Cockpit</h1>
              <p className="mt-2 text-sm text-muted">
                We&rsquo;ll email you a magic link — no password needed.
              </p>

              <label htmlFor="cockpit-email" className="mt-6 mb-2 block text-xs text-muted">
                Email address
              </label>
              <input
                id="cockpit-email"
                type="email"
                autoFocus
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full rounded-control border border-line bg-bg px-3 py-2.5 text-sm text-ink placeholder:text-muted transition-colors focus:border-accent focus:outline-none"
              />

              {status === 'error' && (
                <p className="mt-3 flex items-center gap-2 text-sm text-danger">
                  <Icon name="alert" size={15} />
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={status === 'sending' || !email.trim()}
                className="mt-6 flex w-full items-center justify-center gap-2 rounded-control bg-accent py-2.5 text-sm font-semibold text-bg transition-opacity hover:opacity-90 disabled:bg-raised disabled:text-muted"
              >
                {status === 'sending' ? 'Sending…' : 'Send magic link'}
              </button>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted">
          Access is limited to approved addresses.
        </p>
      </div>
    </div>
  )
}

function SentState({ email, onReset }: { email: string; onReset: () => void }) {
  return (
    <div className="text-center">
      <span className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-card border border-line bg-raised text-accent">
        <Icon name="mail" size={22} />
      </span>
      <h1 className="text-xl font-semibold text-ink">Check your inbox</h1>
      <p className="mt-2 text-sm text-muted">
        We sent a magic link to <span className="text-ink">{email}</span>. Open it on this device to
        finish signing in.
      </p>
      <button onClick={onReset} className="mt-6 text-sm text-accent transition-opacity hover:opacity-80">
        Use a different email
      </button>
    </div>
  )
}

function ConfigError() {
  return (
    <div className="text-center">
      <span className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-card border border-line bg-raised text-danger">
        <Icon name="alert" size={22} />
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
