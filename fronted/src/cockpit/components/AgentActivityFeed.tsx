/**
 * AgentActivityFeed — the Agent Log tab in the Work Queue center pane.
 *
 * Shows a chronological list of agent runs and their actions for the selected
 * person. Updates automatically via Supabase Realtime (parent passes the runs
 * from useAgentRuns — no extra fetch here).
 *
 * Visual language:
 *   - Run header: status chip + agent type + trigger label + timestamp
 *   - Action rows: action_type icon glyph + summary + timestamp
 *   - Violet left-border accent for agent rows (machine provenance)
 *   - Amber left-border for 'info_requested' actions (waiting state)
 */

import type { AgentRun } from '../lib/useAgentRuns'
import { relativeTime } from '../lib/pipeline'

const ACTION_LABELS: Record<string, string> = {
  stage_advanced:  'Stage advanced',
  whatsapp_sent:   'WhatsApp sent',
  info_requested:  'Info requested',
  flag_set:        'Flag set',
  note_added:      'Note added',
  skipped:         'Skipped',
}

const ACTION_GLYPH: Record<string, string> = {
  stage_advanced: '↗',
  whatsapp_sent:  '✉',
  info_requested: '?',
  flag_set:       '⚑',
  note_added:     '✎',
  skipped:        '—',
}

const STATUS_CHIP: Record<string, { label: string; className: string }> = {
  running:  { label: 'Running',  className: 'text-accent bg-accent/15' },
  pending:  { label: 'Pending',  className: 'text-muted bg-raised' },
  success:  { label: 'Done',     className: 'text-success bg-success/10' },
  skipped:  { label: 'Skipped',  className: 'text-faint bg-raised' },
  failed:   { label: 'Failed',   className: 'text-danger bg-danger/10' },
}

const TRIGGER_LABELS: Record<string, string> = {
  stage_change:  'stage change',
  action_loop:   'action loop',
  cron:          'scheduled sweep',
  manual:        'manual trigger',
}

interface AgentActivityFeedProps {
  runs: AgentRun[]
  loading: boolean
}

export function AgentActivityFeed({ runs, loading }: AgentActivityFeedProps) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 py-6 text-xs text-faint">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
        Loading agent activity…
      </div>
    )
  }

  if (runs.length === 0) {
    return (
      <div className="py-6 text-center">
        <p className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
          No agent activity yet
        </p>
        <p className="mt-1 text-xs text-muted">
          The qualification agent will run after the next action on this lead.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
        Agent log
      </div>

      {runs.map((run) => {
        const chip = STATUS_CHIP[run.status] ?? STATUS_CHIP.skipped
        const trigger = TRIGGER_LABELS[run.triggered_by] ?? run.triggered_by
        const agentLabel = run.agent_type.replace(/_/g, ' ')

        return (
          <div
            key={run.id}
            className="rounded-control border border-line bg-surface"
          >
            {/* Run header */}
            <div className="flex items-center gap-2 border-b border-line px-3 py-2">
              <span
                aria-hidden
                className="text-[9px] leading-none text-glow"
              >
                ✦
              </span>
              <span className="flex-1 font-mono text-[11px] capitalize text-ink">
                {agentLabel}
              </span>
              <span
                className={`rounded-control px-1.5 py-px font-mono text-[9px] uppercase tracking-wider ${chip.className}`}
              >
                {chip.label}
              </span>
            </div>

            {/* Run meta */}
            <div className="flex items-center justify-between px-3 py-1.5">
              <span className="font-mono text-[10px] text-faint">
                via {trigger}
              </span>
              <span className="font-mono text-[10px] text-faint">
                {relativeTime(run.started_at)}
              </span>
            </div>

            {/* Action rows */}
            {run.actions.length > 0 && (
              <div className="border-t border-line px-3 py-2">
                <div className="flex flex-col gap-1.5">
                  {run.actions.map((action, i) => {
                    const isWaiting = action.action_type === 'info_requested'
                    return (
                      <div
                        key={i}
                        className={`flex items-start gap-2 border-l-2 pl-2.5 ${
                          isWaiting ? 'border-warn' : 'border-accent/40'
                        }`}
                      >
                        <span
                          aria-hidden
                          className={`mt-0.5 shrink-0 font-mono text-[10px] ${
                            isWaiting ? 'text-warn' : 'text-accent'
                          }`}
                        >
                          {ACTION_GLYPH[action.action_type] ?? '·'}
                        </span>
                        <div className="min-w-0 flex-1">
                          <span className="text-xs text-ink">
                            {ACTION_LABELS[action.action_type] ?? action.action_type.replace(/_/g, ' ')}
                          </span>
                          {_renderActionDetail(action)}
                        </div>
                        <span className="shrink-0 font-mono text-[9px] text-faint">
                          {relativeTime(action.at)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Error detail (failed runs only) */}
            {run.status === 'failed' && run.error && (
              <div className="border-t border-line px-3 py-2">
                <span className="font-mono text-[10px] text-danger">{run.error}</span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function _renderActionDetail(
  action: AgentActivityFeedProps['runs'][number]['actions'][number],
) {
  if (action.action_type === 'stage_advanced') {
    const from = action.payload.from as string | undefined
    const to   = action.payload.to as string | undefined
    if (from && to) {
      return (
        <p className="mt-0.5 font-mono text-[10px] text-muted">
          {from} → {to}
        </p>
      )
    }
  }
  if (action.action_type === 'info_requested') {
    const missing = action.payload.fields_missing as string[] | undefined
    if (missing?.length) {
      return (
        <p className="mt-0.5 font-mono text-[10px] text-muted">
          missing: {missing.join(', ')}
        </p>
      )
    }
  }
  if (action.action_type === 'whatsapp_sent') {
    const mid = action.payload.message_id as string | undefined
    return (
      <p className="mt-0.5 font-mono text-[10px] text-muted">
        {mid ? `id: ${mid.slice(0, 16)}…` : 'sent via WhatsApp'}
      </p>
    )
  }
  return null
}
