import { StrictMode, Suspense, lazy } from 'react'
import type { ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'

import './cockpit/index.css'
import { queryClient } from './cockpit/lib/queryClient'
import { AuthProvider } from './cockpit/auth/AuthProvider'
import { RequireAuth } from './cockpit/auth/RequireAuth'
import { AppShell } from './cockpit/shell/AppShell'
import { Navigate } from 'react-router-dom'
import { OverviewPage } from './cockpit/pages/OverviewPage'
import { PersonDossierPage } from './cockpit/pages/PersonDossierPage'
import { WorkQueuePage } from './cockpit/pages/WorkQueuePage'
import { PipelinePage } from './cockpit/pages/PipelinePage'
import { ContentStudioPage } from './cockpit/pages/ContentStudioPage'
import { NotFoundPage } from './cockpit/pages/NotFoundPage'
import { RouteErrorBoundary } from './cockpit/components/RouteErrorBoundary'
import { FEATURES } from './cockpit/lib/flags'

// Legacy Nexus app — preserved at /legacy, code-split so it never ships with the
// Cockpit bundle. It keeps its own styles, API-key auth, and backend.
const LegacyNexus = lazy(() =>
  import('./App.jsx').then((m) => ({ default: m.default as ComponentType })),
)

// Public Nexus marketing landing — code-split so its gsap/framer-motion/lucide
// deps stay out of the cockpit bundle. Renders outside RequireAuth + cockpit-root.
const LandingPage = lazy(() =>
  import('./landing/LandingPage').then((m) => ({ default: m.LandingPage })),
)

// Analytics — code-split so recharts stays out of the initial cockpit bundle.
const AnalyticsPage = lazy(() =>
  import('./cockpit/pages/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage })),
)

// Settings — lazy to break the AuthProvider circular evaluation order that
// a static import would create in Rollup's production chunk.
const SettingsPage = lazy(() =>
  import('./cockpit/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)

// Flows canvas (F2) — code-split so the canvas + inspector stay out of the
// initial cockpit chunk (respecting the E2 bundle budget).
const FlowsPage = lazy(() =>
  import('./cockpit/pages/FlowsPage').then((m) => ({ default: m.FlowsPage })),
)

const router = createBrowserRouter([
  // The public front door — the premium marketing landing at the root.
  {
    path: '/',
    element: (
      <Suspense fallback={<div className="min-h-screen w-full bg-[#04070f]" />}>
        <LandingPage />
      </Suspense>
    ),
    errorElement: <RouteErrorBoundary />,
  },
  // The cockpit (CRM) — behind Supabase auth at /app. index = the Overview pulse.
  {
    path: '/app',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    // Render errors anywhere in the cockpit land here instead of white-screening.
    errorElement: <RouteErrorBoundary />,
    children: [
      { index: true, element: <OverviewPage /> },
      ...(FEATURES.workQueue ? [{ path: 'queue', element: <WorkQueuePage /> }] : []),
      ...(FEATURES.analytics
        ? [{ path: 'analytics', element: <Suspense fallback={null}><AnalyticsPage /></Suspense> }]
        : []),
      { path: 'person/:id', element: <PersonDossierPage /> },
      { path: 'pipeline', element: <PipelinePage /> },
      // Inbox retired (E1 §A7) — One Thread in the dossier IS the inbox.
      // Deep links stay safe: old /app/inbox bookmarks land on the queue.
      { path: 'inbox', element: <Navigate to="/app/queue" replace /> },
      ...(FEATURES.content ? [{ path: 'content', element: <ContentStudioPage /> }] : []),
      ...(FEATURES.flows
        ? [{ path: 'flows', element: <Suspense fallback={null}><FlowsPage /></Suspense> }]
        : []),
      { path: 'settings', element: <Suspense fallback={null}><SettingsPage /></Suspense> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  {
    path: '/legacy/*',
    element: (
      <Suspense fallback={null}>
        <LegacyNexus />
      </Suspense>
    ),
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
