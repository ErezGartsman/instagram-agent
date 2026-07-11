import type { KeyboardEvent } from 'react'
import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import { Button } from '../ui'
import { relativeTime } from '../../lib/pipeline'
import { nodeMeta, type FlowSummary } from '../../lib/flows'
import { graphToSteps, playbookSentence, KIND_TO_NODE, type PlaybookStep } from '../../lib/playbook'
import { asTone, TONE_TEXT, TONE_TINT, TONE_DOT } from './tone'

/**
 * PlaybookCard — one automation, readable as a sentence. The card IS the
 * flow's whole story: "When a booking is canceled → notify Erez", its
 * live/shadow state, and its run pulse. No graph, no nodes — selecting the
 * card opens its activity in the rail; the controls live on the card itself.
 */
export function PlaybookCard({
  flow, selected, busy, onSelect, onEdit, onLive, onStatus,
}: {
  flow: FlowSummary
  selected: boolean
  busy: boolean
  onSelect: () => void
  onEdit: () => void
  onLive: (live: boolean) => void
  onStatus: (action: 'pause' | 'resume') => void
}) {
  const steps = graphToSteps(flow.graph)
  const sentence = playbookSentence(flow.trigger, steps)

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect() }
  }

  return (
    <div
      role="button" tabIndex={0} aria-current={selected ? 'true' : undefined}
      onClick={onSelect} onKeyDown={onKeyDown}
      className={`group cursor-pointer rounded-card border bg-surface p-5 backdrop-blur-xl transition-colors [box-shadow:var(--shadow-card)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 ${
        selected
          ? 'border-[rgba(59,130,246,0.45)] shadow-[0_0_24px_rgba(59,130,246,0.18)]'
          : 'border-line hover:border-[rgba(148,186,255,0.22)]'
      }`}
    >
      {/* Header: name · state (the switch IS the state for published flows) */}
      <div className="flex items-center gap-3">
        {flow.status !== 'published' && <StatusChip flow={flow} />}
        <h3 className="min-w-0 truncate text-[15px] font-semibold text-ink">{flow.name}</h3>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {flow.status === 'published' && (
            <LiveSwitch live={flow.live} busy={busy} onToggle={() => onLive(!flow.live)} />
          )}
        </div>
      </div>

      {/* The sentence — the whole point */}
      <div className="mt-3.5">
        <p className="text-[15px] leading-relaxed">
          <span className="mr-2 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">When</span>
          <span className="text-ink">{sentence.when}</span>
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-y-2">
          <span className="mr-2 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Then</span>
          {steps === null ? (
            <StepChip icon="branch" tone="muted" label="custom branching logic" />
          ) : (
            steps.map((step, i) => (
              <span key={i} className="flex items-center">
                {i > 0 && <Icon name="arrowRight" size={12} className="mx-1.5 text-faint" />}
                <StepChip {...stepChipProps(step)} />
              </span>
            ))
          )}
        </div>
      </div>

      {/* Footer: run pulse + actions */}
      <div className="mt-4 flex items-center gap-3 border-t border-line pt-3">
        <span className="font-mono text-[10px] tabular-nums text-faint">
          v{flow.version} · {flow.run_count} {flow.run_count === 1 ? 'run' : 'runs'}
          {flow.last_run_at && ` · last ${relativeTime(flow.last_run_at)}`}
        </span>
        <div
          className="ml-auto flex items-center gap-1.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100"
          onClick={(e) => e.stopPropagation()}
        >
          {flow.status === 'published' && (
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => onStatus('pause')}>Pause</Button>
          )}
          {flow.status === 'paused' && (
            <Button variant="outline" size="sm" disabled={busy} onClick={() => onStatus('resume')}>Resume</Button>
          )}
          <Button variant="ghost" size="sm" icon="branch" disabled={busy} onClick={onEdit}>
            {flow.status === 'draft' ? 'Edit' : 'Tune'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function stepChipProps(step: PlaybookStep): { icon: IconName; tone: string; label: string } {
  const meta = nodeMeta(KIND_TO_NODE[step.kind])
  return {
    icon: meta.icon as IconName,
    tone: meta.tone,
    label: stepChipLabel(step),
  }
}

/** Chip captions stay terse — the config detail lives in the composer. */
function stepChipLabel(step: PlaybookStep): string {
  switch (step.kind) {
    case 'wait': return `wait ${step.hours}h`
    case 'if': return 'only if…'
    case 'send': return 'message the lead'
    case 'notify': return 'notify Erez'
    case 'advance': return `→ ${step.to_stage}`
    case 'note': return 'add a note'
    case 'flag': return step.flag ? `flag: ${step.flag}` : 'set a flag'
  }
}

function StepChip({ icon, tone, label }: { icon: IconName; tone: string; label: string }) {
  const t = asTone(tone)
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-control px-2 py-1 text-[11px] ${TONE_TINT[t]} ${TONE_TEXT[t]}`}>
      <Icon name={icon} size={11} />
      {label}
    </span>
  )
}

export function StatusChip({ flow }: { flow: FlowSummary }) {
  const { tone, label } =
    flow.status === 'draft' ? { tone: asTone('warn'), label: 'draft' } :
    flow.status === 'paused' ? { tone: asTone('faint'), label: 'paused' } :
    flow.status === 'archived' ? { tone: asTone('faint'), label: 'archived' } :
    flow.live ? { tone: asTone('success'), label: 'live' } :
    { tone: asTone('accent'), label: 'shadow' }
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-control px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]} ${flow.status === 'published' && flow.live ? '[box-shadow:0_0_8px_rgba(52,211,153,0.9)]' : ''}`} />
      {label}
    </span>
  )
}

/**
 * LiveSwitch — shadow ⇄ live. Shadow is the safe default (the engine records
 * what it WOULD do); flipping live is the one gesture on this surface with
 * outward consequences, so it reads loud: green thumb, mono label.
 */
function LiveSwitch({ live, busy, onToggle }: { live: boolean; busy: boolean; onToggle: () => void }) {
  return (
    <button
      type="button" role="switch" aria-checked={live} aria-label={live ? 'Live — sending real actions' : 'Shadow — recording only'}
      disabled={busy}
      onClick={(e) => { e.stopPropagation(); onToggle() }}
      className="flex cursor-pointer items-center gap-2 rounded-control px-1.5 py-1 transition-colors hover:bg-raised disabled:opacity-40"
    >
      <span className={`font-mono text-[10px] uppercase tracking-wider ${live ? 'text-success' : 'text-accent'}`}>
        {live ? 'live' : 'shadow'}
      </span>
      <span className={`relative h-[18px] w-8 rounded-full transition-colors ${live ? 'bg-[rgba(52,211,153,0.35)]' : 'bg-raised'}`}>
        <span className={`absolute top-[2px] h-[14px] w-[14px] rounded-full transition-transform ${
          live ? 'translate-x-[16px] bg-success [box-shadow:0_0_8px_rgba(52,211,153,0.9)]' : 'translate-x-[2px] bg-glow'
        }`} />
      </span>
    </button>
  )
}
