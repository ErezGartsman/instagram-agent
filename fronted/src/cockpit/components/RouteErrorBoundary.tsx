import { useRouteError } from 'react-router-dom'

/**
 * Router-level error boundary (React Router `errorElement`): any render error
 * inside a route lands here instead of white-screening the app. Deliberately
 * dependency-free and self-styled — if the crash came from the shell or the
 * theme layer, this must still paint.
 */
export function RouteErrorBoundary() {
  const error = useRouteError()
  const message = error instanceof Error ? error.message : 'An unexpected error occurred.'
  return (
    <div
      role="alert"
      style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 12,
        background: '#04070f', color: '#f2f6ff', padding: 24, textAlign: 'center',
        fontFamily: 'Inter, system-ui, sans-serif',
      }}
    >
      <p style={{ fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#55617a' }}>
        Nexus
      </p>
      <h1 style={{ fontSize: 18, fontWeight: 500 }}>Something broke on this screen</h1>
      <p style={{ fontSize: 13, color: '#9aa7bd', maxWidth: 420, lineHeight: 1.5 }}>
        The rest of the cockpit is fine — reload to recover. ({message})
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{
          marginTop: 8, padding: '8px 18px', borderRadius: 9, border: '1px solid rgba(148,186,255,0.2)',
          background: 'rgba(59,130,246,0.15)', color: '#60a5fa', fontSize: 13, cursor: 'pointer',
        }}
      >
        Reload
      </button>
    </div>
  )
}
