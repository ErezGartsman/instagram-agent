// Cockpit feature flags. A surface is "on" when it's under active build (DEV) or
// explicitly forced on in a production build via its VITE_FEATURE_* env var. This
// lets us merge a half-built surface to main and keep it dark in prod until ready
// — the new nav item and route only appear when its flag is truthy.
//
// The `import.meta.env.DEV` literal is statically `true`/`false` per build, so the
// dev-only branch is dead-code-eliminated from production bundles.
export const FEATURES = {
  /** Sprint 5 · the 3-pane Work Queue. */
  workQueue: import.meta.env.DEV || import.meta.env.VITE_FEATURE_WORKQUEUE === '1',
  /** Sprint 5 · the Analytics pillar. */
  analytics: import.meta.env.DEV || import.meta.env.VITE_FEATURE_ANALYTICS === '1',
  /** Sprint 5 · the Content Studio. */
  content: import.meta.env.DEV || import.meta.env.VITE_FEATURE_CONTENT === '1',
  /** F2/F3 · Playbooks — sentence-form automations + run inspector + simulation. */
  flows: import.meta.env.DEV || import.meta.env.VITE_FEATURE_FLOWS === '1',
  // 'inbox' RETIRED (E1 §A7, SYSTEM_ELEVATION_PRD.md): One Thread inside the
  // dossier superseded the planned inbox surface; /app/inbox redirects to the queue.
} as const
