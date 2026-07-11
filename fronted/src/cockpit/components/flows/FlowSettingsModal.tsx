import { useState } from 'react'
import { motion } from 'framer-motion'
import { Icon } from '../Icon'
import { Button } from '../ui'
import { updateFlowSettings } from '../../lib/flows'

/**
 * FlowSettingsModal — the engine kill switch + pressure-budget surface (F3).
 * Writes app_config via PATCH /flow-settings. In dev bypass the controls are
 * shown but disabled (no backend to persist to).
 */
export function FlowSettingsModal({
  enabled, devBypass, token, onClose, onSaved,
}: {
  enabled: boolean
  devBypass: boolean
  token: string | null
  onClose: () => void
  onSaved: () => void
}) {
  const [on, setOn] = useState(enabled)
  const [budget, setBudget] = useState(2)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (devBypass || !token) { onClose(); return }
    setSaving(true)
    try {
      await updateFlowSettings(token, { enabled: on, pressure_budget: budget })
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="fixed inset-0 z-[400] grid place-items-center bg-bg/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.2, ease: [0.25, 0.4, 0.25, 1] }}
        role="dialog" aria-modal="true" aria-label="Engine settings"
        onClick={(e) => e.stopPropagation()}
        className="w-[440px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
      >
        <div className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
          <span className="grid h-7 w-7 place-items-center rounded-control bg-[rgba(59,130,246,0.12)] text-glow"><Icon name="shield" size={14} /></span>
          <div className="text-sm font-semibold text-ink">Flows engine settings</div>
          <button type="button" onClick={onClose} className="ml-auto text-faint hover:text-ink" aria-label="Close"><Icon name="x" size={16} /></button>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-sm font-medium text-ink">Engine</div>
              <p className="mt-0.5 text-xs text-muted">Master switch. Off = no flow dispatches or runs at all.</p>
            </div>
            <button
              type="button" role="switch" aria-checked={on} onClick={() => setOn((v) => !v)}
              className={`relative mt-1 h-5 w-9 shrink-0 rounded-full transition-colors ${on ? 'bg-accent' : 'bg-raised'}`}
            >
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-ink transition-transform ${on ? 'translate-x-4' : 'translate-x-0.5'}`} />
            </button>
          </div>

          <div className="border-t border-line pt-4">
            <div className="text-sm font-medium text-ink">Pressure budget</div>
            <p className="mt-0.5 text-xs text-muted">
              Max automated messages one lead can receive in any rolling 7 days, across every flow and agent.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <input
                type="number" min={0} value={budget}
                onChange={(e) => setBudget(Math.max(0, Number(e.target.value) || 0))}
                className="w-20 rounded-control border border-line bg-bg/60 px-2 py-1.5 font-mono text-sm tabular-nums text-ink outline-none focus:border-accent/40"
              />
              <span className="text-xs text-muted">messages / 7 days</span>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
          <span className="font-mono text-[10px] text-faint">{devBypass ? 'Read-only in dev bypass.' : 'Applies to every flow immediately.'}</span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
            <Button variant="primary" size="sm" icon="check" onClick={save} disabled={saving || devBypass}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}
