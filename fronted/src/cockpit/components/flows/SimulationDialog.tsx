import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Icon } from '../Icon'
import { Button, AnimatedNumber } from '../ui'
import { relativeTime } from '../../lib/pipeline'
import { blockReasonLabel, type SimulationReport } from '../../lib/flows'
import { asTone, TONE_TEXT, TONE_TINT } from './tone'

/**
 * SimulationDialog — the publish gate, and the visible payoff of the 90-day
 * time-travel engine. Shows exactly what a flow WOULD have done against real
 * history ("fired 34 times · 6 blocked: 4 pressure budget, 2 quiet hours")
 * so Erez publishes on evidence, not faith. Publishing re-runs the sim
 * server-side as the authoritative gate.
 */

const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]
const ACTION_LABEL: Record<string, string> = {
  would_send: 'Messages sent',
  would_notify: 'Operator notifs',
  advanced: 'Stages advanced',
  noted: 'Notes added',
  flagged: 'Flags set',
}

export function SimulationDialog({
  report,
  loading,
  onClose,
  onPublish,
  publishing,
  canPublish,
}: {
  report: SimulationReport | null
  loading: boolean
  onClose: () => void
  onPublish: () => void
  publishing: boolean
  canPublish: boolean
}) {
  const reduce = useReducedMotion()
  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-[400] grid place-items-center bg-bg/70 p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={reduce ? { opacity: 0 } : { opacity: 0, y: -12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, y: -8, scale: 0.98 }}
          transition={{ duration: 0.2, ease: EASE }}
          role="dialog" aria-modal="true" aria-label="Simulation"
          onClick={(e) => e.stopPropagation()}
          className="w-[560px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
        >
          {/* Header */}
          <div className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
            <span className="grid h-7 w-7 place-items-center rounded-control bg-[rgba(59,130,246,0.12)] text-glow">
              <Icon name="clock" size={14} />
            </span>
            <div>
              <div className="text-sm font-semibold text-ink">Time-travel simulation</div>
              <div className="font-mono text-[10px] text-faint">
                replayed against the last {report?.window_days ?? 90} days of real events
              </div>
            </div>
            <button type="button" onClick={onClose} className="ml-auto text-faint transition-colors hover:text-ink" aria-label="Close">
              <Icon name="x" size={16} />
            </button>
          </div>

          {loading || !report ? (
            <div className="flex flex-col items-center gap-3 px-6 py-16">
              <span className="cq-node-wait grid h-10 w-10 place-items-center rounded-control bg-[rgba(59,130,246,0.12)] text-glow">
                <Icon name="clock" size={20} />
              </span>
              <p className="text-sm text-muted">Replaying 90 days of history…</p>
            </div>
          ) : (
            <div className="px-5 py-4">
              {/* Headline */}
              <div className="mb-4 flex items-baseline gap-2">
                <span className="font-mono text-4xl font-light tabular-nums text-ink">
                  <AnimatedNumber value={report.fires} />
                </span>
                <span className="text-sm text-muted">
                  {report.fires === 1 ? 'time this would have fired' : 'times this would have fired'}
                </span>
              </div>

              {/* Action + block tiles */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-card border border-line bg-bg/40 p-3">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-faint">Would have done</div>
                  <ul className="mt-2 space-y-1">
                    {Object.entries(report.actions).filter(([, v]) => v > 0).length === 0 && (
                      <li className="text-xs text-faint">nothing outward</li>
                    )}
                    {Object.entries(report.actions).filter(([, v]) => v > 0).map(([k, v]) => (
                      <li key={k} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{ACTION_LABEL[k] ?? k}</span>
                        <span className="font-mono tabular-nums text-ink">{v}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className={`rounded-card border border-line p-3 ${report.blocked > 0 ? 'bg-[rgba(224,112,92,0.06)]' : 'bg-bg/40'}`}>
                  <div className="font-mono text-[10px] uppercase tracking-wider text-faint">
                    Blocked by the gate
                  </div>
                  <div className="mt-1 font-mono text-2xl font-light tabular-nums text-ink">{report.blocked}</div>
                  <ul className="mt-1 space-y-0.5">
                    {Object.entries(report.blocked_by).map(([reason, n]) => {
                      const tone = asTone(reason === 'quiet_hours' ? 'warn' : reason === 'crisis' ? 'danger' : 'danger')
                      return (
                        <li key={reason} className="flex items-center justify-between text-[11px]">
                          <span className={TONE_TEXT[tone]}>{blockReasonLabel(reason)}</span>
                          <span className="font-mono tabular-nums text-muted">{n}</span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              </div>

              {/* Sample */}
              {report.sample.length > 0 && (
                <div className="mt-4">
                  <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-faint">Representative fires</div>
                  <ul className="max-h-[168px] space-y-0.5 overflow-y-auto">
                    {report.sample.map((s, i) => {
                      const blocked = s.outcome === 'blocked'
                      const tone = asTone(blocked ? 'danger' : 'success')
                      return (
                        <li key={i} className="flex items-center gap-2 rounded-control px-2 py-1 text-xs">
                          <span className={`grid h-4 w-4 shrink-0 place-items-center rounded-full ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
                            <Icon name={blocked ? 'x' : 'check'} size={9} />
                          </span>
                          <span className="truncate text-ink">{s.person_name}</span>
                          <span className="ml-auto shrink-0 font-mono text-[10px] text-faint">
                            {blocked ? blockReasonLabel(s.reason ?? 'blocked') : s.outcome.replace(/_/g, ' ')}
                            {' · '}{relativeTime(s.at)}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}

              {/* Honesty notes */}
              {report.notes.length > 0 && (
                <p className="mt-3 border-t border-line pt-2.5 text-[11px] leading-relaxed text-faint">
                  {report.notes.join(' ')}
                </p>
              )}
            </div>
          )}

          {/* Footer — the publish gate */}
          <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
            <span className="font-mono text-[10px] text-faint">
              {canPublish ? 'Publishing re-runs this simulation server-side.' : 'Preview only.'}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
              {canPublish && (
                <Button variant="primary" size="sm" icon="check" onClick={onPublish} disabled={loading || publishing || !report}>
                  {publishing ? 'Publishing…' : 'Publish flow'}
                </Button>
              )}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
