/**
 * AgentPip — inline agent status indicator on Work Queue rows.
 *
 * Three visual states:
 *   running  → pulsing violet dot  (agent is actively working)
 *   waiting  → amber dot           (info request sent, waiting for reply)
 *   success  → sage checkmark pip  (agent advanced the stage)
 *
 * No state when there are no agent runs for this person (renders nothing).
 * Driven by the useAgentRuns hook — updates live via Supabase Realtime.
 */

import { isWaitingForInfo, type AgentRun } from '../lib/useAgentRuns'

interface AgentPipProps {
  runs: AgentRun[]
}

export function AgentPip({ runs }: AgentPipProps) {
  if (runs.length === 0) return null

  const latest = runs[0]
  const isRunning = latest.status === 'running' || latest.status === 'pending'
  const waiting = !isRunning && isWaitingForInfo(runs)
  const succeeded = !isRunning && !waiting && latest.status === 'success' &&
    latest.actions.some((a) => a.action_type === 'stage_advanced')

  if (isRunning) {
    return (
      <span
        aria-label="Agent running"
        title="Qualification agent running"
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent [box-shadow:0_0_4px_rgba(96,165,250,0.8)]"
      />
    )
  }

  if (waiting) {
    return (
      <span
        aria-label="Waiting for reply"
        title="Waiting for lead's reply"
        className="inline-block h-1.5 w-1.5 rounded-full bg-warn"
      />
    )
  }

  if (succeeded) {
    return (
      <span
        aria-label="Auto-qualified"
        title="Auto-qualified by agent"
        className="inline-block h-1.5 w-1.5 rounded-full bg-success"
      />
    )
  }

  return null
}
