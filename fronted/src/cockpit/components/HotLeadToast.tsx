import { useEffect } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Icon } from './Icon'
import type { QueueItem } from '../lib/workqueue'

const AUTO_DISMISS_MS = 6_000
const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]

/**
 * Warm Luxury in-app toast for new high-confidence leads.
 *
 * Positioned `fixed bottom-6 right-6` so it overlays the entire cockpit
 * regardless of where it's mounted in the tree. Uses `role="status"` +
 * `aria-live="polite"` — announced to screen readers without interrupting
 * active reading. Auto-dismisses after 6 s; resets the timer on each new item.
 */
export function HotLeadToast({
  item,
  onDismiss,
  onView,
}: {
  item: QueueItem | null
  onDismiss: () => void
  onView: () => void
}) {
  const reduce = useReducedMotion()

  // Auto-dismiss timer — restarts when a new item arrives.
  useEffect(() => {
    if (!item) return
    const t = setTimeout(onDismiss, AUTO_DISMISS_MS)
    return () => clearTimeout(t)
  }, [item, onDismiss])

  return (
    // The live region always exists in the DOM so screen reader state is stable.
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="pointer-events-none fixed bottom-6 right-6 z-[200]"
    >
      <AnimatePresence>
        {item && (
          <motion.div
            key={item.id}
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.97 }}
            transition={{ duration: 0.22, ease: EASE }}
            className="pointer-events-auto w-[296px] overflow-hidden rounded-card border border-line border-l-2 border-l-glow bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
          >
            {/* Header row */}
            <div className="flex items-center justify-between gap-2 px-4 pt-3.5 pb-2">
              <div className="flex items-center gap-2">
                <Icon name="sparkle" size={12} className="shrink-0 text-glow" />
                <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-glow">
                  Hot lead
                </span>
              </div>
              <button
                type="button"
                onClick={onDismiss}
                aria-label="Dismiss notification"
                className="text-faint transition-colors hover:text-muted"
              >
                <Icon name="x" size={14} />
              </button>
            </div>

            {/* Lead details */}
            <div className="px-4 pb-4">
              <p className="text-sm font-semibold leading-snug text-ink">{item.name}</p>
              {item.action && (
                <p className="mt-0.5 line-clamp-1 text-xs leading-relaxed text-muted">
                  {item.action}
                </p>
              )}

              {/* Confidence + CTA */}
              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  {/* Mini confidence bar */}
                  <span className="h-1 w-12 overflow-hidden rounded-full bg-raised">
                    <span
                      className="block h-full rounded-full bg-glow/60"
                      style={{ width: `${item.confidence}%` }}
                    />
                  </span>
                  <span className="font-mono text-xs tabular-nums text-glow">
                    {item.confidence}%
                  </span>
                </div>
                <button
                  type="button"
                  onClick={onView}
                  className="flex items-center gap-1 text-xs text-muted transition-colors hover:text-ink"
                >
                  View in queue
                  <Icon name="arrowRight" size={12} />
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
