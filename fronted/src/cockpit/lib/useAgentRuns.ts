/**
 * useAgentRuns — agent run state with Supabase Realtime.
 *
 * Fetches the run history for a person on mount and subscribes to the
 * agent_runs table via Supabase Realtime so the AgentPip and AgentActivityFeed
 * update instantly whenever the backend changes a run's status — no polling,
 * no page reload.
 *
 * The subscription filter `person_id=eq.<id>` means each hook instance only
 * receives events for its person, keeping the payload minimal.
 */

import { useEffect, useState } from 'react'
import { supabase } from './supabase'
import { fetchAgentRuns, type AgentRun, type AgentRunStatus } from './api'

export type { AgentRun, AgentRunStatus }

/** The most actionable status across all runs for a person — used by AgentPip. */
export function deriveAgentStatus(
  runs: AgentRun[],
): AgentRunStatus | null {
  if (runs.some((r) => r.status === 'running'))  return 'running'
  if (runs.some((r) => r.status === 'pending'))  return 'pending'
  const latest = runs[0]
  if (!latest) return null
  // 'waiting' is modelled as a successful run whose last action was info_requested.
  if (
    latest.status === 'success' &&
    latest.actions.at(-1)?.action_type === 'info_requested'
  ) {
    return 'success'  // caller maps this to amber 'waiting' via action type
  }
  return latest.status
}

/** True when the latest successful run sent an info request (amber waiting state). */
export function isWaitingForInfo(runs: AgentRun[]): boolean {
  const latest = runs.find((r) => r.status === 'success')
  if (!latest) return false
  return latest.actions.some((a) => a.action_type === 'info_requested')
}

export function useAgentRuns(
  personId: string | null,
  token: string | null,
): { runs: AgentRun[]; loading: boolean } {
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [loading, setLoading] = useState(false)

  // Fetch on personId change.
  useEffect(() => {
    if (!personId || !token) {
      setRuns([])
      return
    }
    setLoading(true)
    fetchAgentRuns(token, personId).then((r) => {
      setRuns(r)
      setLoading(false)
    })
  }, [personId, token])

  // Supabase Realtime subscription — fires on any agent_runs INSERT or UPDATE
  // for this person. On INSERT: prepend the new run. On UPDATE: patch in place.
  // Action rows (agent_actions) are NOT subscribed here — we refetch the full
  // run (including its actions) from the API when the run status closes, keeping
  // the Realtime payload minimal.
  useEffect(() => {
    if (!personId || !token) return

    const channel = supabase
      .channel(`agent_runs:person:${personId}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'agent_runs',
          filter: `person_id=eq.${personId}`,
        },
        (payload) => {
          const run = payload.new as Omit<AgentRun, 'actions'> & { actions?: AgentRun['actions'] }
          setRuns((prev) => [{ ...run, actions: run.actions ?? [] }, ...prev])
        },
      )
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'agent_runs',
          filter: `person_id=eq.${personId}`,
        },
        (payload) => {
          const updated = payload.new as Omit<AgentRun, 'actions'>
          // When a run closes (success/failed/skipped), refetch that run to get
          // its actions — the Realtime payload doesn't carry the actions array.
          if (['success', 'failed', 'skipped'].includes(updated.status) && token) {
            fetchAgentRuns(token, personId).then(setRuns)
          } else {
            setRuns((prev) =>
              prev.map((r) =>
                r.id === updated.id ? { ...r, ...updated } : r,
              ),
            )
          }
        },
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [personId, token])

  return { runs, loading }
}
