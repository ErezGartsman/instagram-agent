/**
 * realtime — Supabase Realtime → TanStack Query invalidation
 * (E0 server-state spine, SYSTEM_ELEVATION_PRD.md §A2: "push becomes the norm,
 * polling becomes the fallback").
 *
 * One channel per concern; a table change invalidates the matching query keys
 * and TanStack refetches whatever is mounted. Debounced so a burst of agent
 * writes causes one refetch, not ten.
 *
 * Today only agent_runs is in the supabase_realtime publication (migration
 * 002). opportunities/outbound_messages join it with 009_flows.sql (F1), at
 * which point adding them here is one line each.
 */
import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { supabase } from './supabase'
import { queryKeys } from './queryClient'

const DEBOUNCE_MS = 400

/**
 * While mounted, any agent_runs INSERT/UPDATE invalidates the Work Queue —
 * agent activity is what changes stages/recommendations, so this turns the
 * queue live without touching the 30s poll fallback.
 */
export function useQueueRealtimeInvalidation(enabled: boolean): void {
  const qc = useQueryClient()
  useEffect(() => {
    if (!enabled) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const channel = supabase
      .channel('rt:queue-invalidation')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'agent_runs' },
        () => {
          if (timer) clearTimeout(timer)
          timer = setTimeout(() => {
            void qc.invalidateQueries({ queryKey: queryKeys.queue })
          }, DEBOUNCE_MS)
        },
      )
      .subscribe()
    return () => {
      if (timer) clearTimeout(timer)
      void supabase.removeChannel(channel)
    }
  }, [enabled, qc])
}
