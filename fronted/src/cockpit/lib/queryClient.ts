/**
 * queryClient — the single TanStack Query client behind the cockpit
 * (E0 server-state spine, SYSTEM_ELEVATION_PRD.md §A2).
 *
 * Query keys are the invalidation contract between fetching and Realtime:
 * lib/realtime.ts invalidates these keys when Postgres rows change, so push
 * is the norm and the per-query refetchInterval is only the safety net.
 */
import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './http'

/** Central query-key registry — every key the Realtime layer may invalidate. */
export const queryKeys = {
  queue: ['queue'] as const,
  overview: ['overview'] as const,
  pipeline: ['pipeline'] as const,
  briefing: ['briefing'] as const,
  analytics: ['analytics'] as const,
  funnel: (days: number) => ['analytics', 'funnel', days] as const,
  sla: ['analytics', 'sla'] as const,
  content: ['content'] as const,
  dossier: (personId: string) => ['dossier', personId] as const,
  thread: (personId: string) => ['thread', personId] as const,
  agentRuns: (personId: string) => ['agents', 'runs', personId] as const,
  flows: ['flows'] as const,
  flowRuns: (flowId: string) => ['flows', 'runs', flowId] as const,
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // Auth failures and 4xx are deterministic — retry only what can heal.
      retry: (failureCount, error) => {
        if (error instanceof ApiError && !error.retryable) return false
        return failureCount < 2
      },
      refetchOnWindowFocus: true,
    },
  },
})
