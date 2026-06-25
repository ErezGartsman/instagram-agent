/**
 * P2 WS3 — Proactive Copilot nudge surface.
 *
 * Mounts into the `copilotSlot` prop of <SurfaceEmpty> so that the Work Queue's
 * "Queue clear" empty state becomes an active surface instead of a dead end.
 * The SurfaceEmpty wrapper already provides the outer glass card container and
 * the `mt-6 w-full max-w-sm` layout — this component owns only the inner content.
 *
 * When the queue is clear, this tells Erez there's still value to extract:
 * leads that have gone quiet, follow-ups worth drafting. The CTA navigates to
 * the queue — the actual AI draft fires from the "Draft with AI" button there.
 */
import { useNavigate } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'

export function CopilotNudge() {
  const navigate = useNavigate()
  const reduce = useReducedMotion()

  return (
    <div className="flex flex-col gap-3">
      {/* Label row */}
      <div className="flex items-center gap-2">
        <span className="text-[11px] leading-none text-glow" aria-hidden>✦</span>
        <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-glow">
          Copilot
        </span>
      </div>

      {/* Nudge message */}
      <p className="text-sm leading-relaxed text-ink">
        Queue is clear — well done. A few leads have gone quiet this week and may
        benefit from a personal check-in.
      </p>
      <p className="text-xs leading-relaxed text-muted">
        Select a quiet lead in the Work Queue, then use{' '}
        <span className="text-glow">✦ Draft with AI</span> to write a natural
        message in your voice.
      </p>

      {/* CTA */}
      <motion.button
        type="button"
        onClick={() => navigate('/app/queue')}
        whileHover={reduce ? undefined : { scale: 1.02 }}
        whileTap={reduce ? undefined : { scale: 0.97 }}
        className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-control border border-glow/30 bg-glow/10 py-2 text-xs font-medium text-glow transition-colors hover:bg-glow/20"
      >
        <span aria-hidden className="text-[10px]">✦</span>
        View the Work Queue
      </motion.button>
    </div>
  )
}
