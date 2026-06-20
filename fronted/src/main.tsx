import { StrictMode, Suspense, lazy } from 'react'
import type { ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import './cockpit/index.css'
import { AuthProvider } from './cockpit/auth/AuthProvider'
import { RequireAuth } from './cockpit/auth/RequireAuth'
import { AppShell } from './cockpit/shell/AppShell'
import { OverviewPage } from './cockpit/pages/OverviewPage'
import { WorkQueuePage } from './cockpit/pages/WorkQueuePage'
import { PipelinePage } from './cockpit/pages/PipelinePage'
import { InboxPage } from './cockpit/pages/InboxPage'
import { ContentPage } from './cockpit/pages/ContentPage'
import { NotFoundPage } from './cockpit/pages/NotFoundPage'
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

const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <OverviewPage /> },
      ...(FEATURES.workQueue ? [{ path: 'queue', element: <WorkQueuePage /> }] : []),
      { path: 'pipeline', element: <PipelinePage /> },
      { path: 'inbox', element: <InboxPage /> },
      { path: 'content', element: <ContentPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
  {
    path: '/landing',
    element: (
      <Suspense fallback={null}>
        <LandingPage />
      </Suspense>
    ),
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
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </StrictMode>,
)
