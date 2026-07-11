import { motion } from 'framer-motion'
import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import { Button } from '../ui'
import { PredicateBuilder } from './PredicateBuilder'
import { nodeMeta, type FlowTrigger } from '../../lib/flows'
import {
  buildPredicate, eventPhrase, newStep, playbookSentence, stepPhrase,
  EVENT_KINDS, KIND_TO_NODE, STAGES,
  type PlaybookStep, type StepKind,
} from '../../lib/playbook'
import { asTone, TONE_TEXT, TONE_TINT } from './tone'

/**
 * PlaybookComposer — the F3 editor, rebuilt without the canvas. A playbook is
 * authored the way Erez would say it: pick WHEN it fires, stack what happens
 * THEN as a vertical list of plain steps. The live sentence preview at the top
 * is the contract: if the sentence reads right, the playbook is right.
 * Publishing still goes through the 90-day time-travel simulation gate.
 */

export type PlaybookDraft = {
  id: string | null // null = a brand-new draft not yet persisted (dev bypass)
  name: string
  description: string | null
  trigger: FlowTrigger
  /** null = the saved graph has branching the linear editor can't express. */
  steps: PlaybookStep[] | null
}

const ADDABLE: StepKind[] = ['send', 'notify', 'wait', 'if', 'advance', 'note', 'flag']

export function PlaybookComposer({
  draft, onChange, onCancel, onSave, saving, onSimulate,
}: {
  draft: PlaybookDraft
  onChange: (patch: Partial<PlaybookDraft>) => void
  onCancel: () => void
  onSave: () => void
  saving: boolean
  onSimulate: () => void
}) {
  const steps = draft.steps
  const sentence = playbookSentence(draft.trigger, steps)

  const patchStep = (i: number, next: PlaybookStep) =>
    onChange({ steps: steps!.map((s, j) => (j === i ? next : s)) })
  const removeStep = (i: number) =>
    onChange({ steps: steps!.filter((_, j) => j !== i) })
  const moveStep = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= steps!.length) return
    const next = [...steps!]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange({ steps: next })
  }

  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="fixed inset-0 z-[400] grid place-items-center bg-bg/70 p-4 backdrop-blur-sm"
      onClick={onCancel}
    >
      <motion.div
        initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.2, ease: [0.25, 0.4, 0.25, 1] }}
        role="dialog" aria-modal="true" aria-label="Edit playbook"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[calc(100vh-3rem)] w-[640px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
      >
        {/* Header: name + the living sentence */}
        <div className="border-b border-line px-6 pb-4 pt-5">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-control bg-[rgba(59,130,246,0.12)] text-glow">
              <Icon name="zap" size={16} />
            </span>
            <div className="min-w-0 flex-1">
              <input
                value={draft.name}
                onChange={(e) => onChange({ name: e.target.value })}
                placeholder="Name this playbook"
                className="w-full bg-transparent text-lg font-semibold text-ink outline-none placeholder:text-faint"
              />
              <input
                value={draft.description ?? ''}
                onChange={(e) => onChange({ description: e.target.value })}
                placeholder="Why this playbook exists (optional)"
                className="mt-0.5 w-full bg-transparent text-xs text-muted outline-none placeholder:text-faint"
              />
            </div>
            <button type="button" onClick={onCancel} aria-label="Close"
              className="cursor-pointer text-faint transition-colors hover:text-ink">
              <Icon name="x" size={16} />
            </button>
          </div>
          <p className="mt-3 rounded-control bg-bg/50 px-3 py-2 text-[13px] leading-relaxed text-muted">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Reads as&ensp;</span>
            When <span className="text-ink">{sentence.when}</span>
            {sentence.then.map((t, i) => (
              <span key={i}>
                <span className="mx-1 text-faint">→</span>
                <span className="text-glow">{t}</span>
              </span>
            ))}.
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {/* WHEN */}
          <SectionLabel>When</SectionLabel>
          <div className="mb-3 inline-flex overflow-hidden rounded-control border border-line">
            {(['event', 'state'] as const).map((t) => (
              <button
                key={t} type="button"
                onClick={() => onChange({
                  trigger: t === 'event'
                    ? { type: 'event', kind: draft.trigger.kind ?? 'booking_canceled' }
                    : { type: 'state', predicate: draft.trigger.predicate ?? buildPredicate({ stages: ['qualified'], hours: 36 }) },
                })}
                className={`cursor-pointer px-3 py-1.5 text-[11px] transition-colors ${
                  draft.trigger.type === t ? 'bg-accent/15 text-accent' : 'text-muted hover:text-ink'
                }`}
              >
                {t === 'event' ? 'Something happens' : 'A lead sits in a state'}
              </button>
            ))}
          </div>

          {draft.trigger.type === 'event' ? (
            <div className="flex flex-wrap gap-1.5">
              {EVENT_KINDS.map((k) => {
                const on = draft.trigger.kind === k
                return (
                  <button
                    key={k} type="button"
                    onClick={() => onChange({ trigger: { type: 'event', kind: k } })}
                    className={`cursor-pointer rounded-control border px-2.5 py-1.5 text-[11px] transition-colors ${
                      on
                        ? 'border-[rgba(59,130,246,0.5)] bg-[rgba(59,130,246,0.12)] text-glow'
                        : 'border-line text-muted hover:text-ink'
                    }`}
                  >
                    {eventPhrase(k)}
                  </button>
                )
              })}
            </div>
          ) : (
            <PredicateBuilder
              predicate={draft.trigger.predicate}
              onChange={(p) => onChange({ trigger: { type: 'state', predicate: p } })}
            />
          )}

          {/* THEN */}
          <div className="mt-6">
            <SectionLabel>Then</SectionLabel>
            {steps === null ? (
              <p className="rounded-control border border-line bg-raised px-3 py-2.5 text-xs leading-relaxed text-muted">
                This playbook was authored with custom branching the step editor
                can&rsquo;t safely rewrite. You can still rename it, retrigger it,
                simulate and publish — the steps themselves stay as built.
              </p>
            ) : (
              <>
                <ol className="relative space-y-2">
                  {steps.length > 1 && (
                    <span aria-hidden className="absolute bottom-5 left-[13px] top-5 w-px bg-line" />
                  )}
                  {steps.map((step, i) => (
                    <StepEditor
                      key={i} step={step} index={i} count={steps.length}
                      onPatch={(s) => patchStep(i, s)}
                      onRemove={() => removeStep(i)}
                      onMove={(d) => moveStep(i, d)}
                    />
                  ))}
                  {steps.length === 0 && (
                    <p className="py-1 text-xs text-faint">No steps yet — add what should happen below.</p>
                  )}
                </ol>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {ADDABLE.map((kind) => {
                    const meta = nodeMeta(KIND_TO_NODE[kind])
                    const tone = asTone(meta.tone)
                    return (
                      <button
                        key={kind} type="button"
                        onClick={() => onChange({ steps: [...steps, newStep(kind)] })}
                        className="flex cursor-pointer items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-[11px] text-muted transition-colors hover:border-[rgba(148,186,255,0.25)] hover:text-ink"
                      >
                        <span className={`grid h-4 w-4 place-items-center rounded ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
                          <Icon name={meta.icon as IconName} size={10} />
                        </span>
                        {meta.label}
                      </button>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Footer — the gate */}
        <div className="flex items-center justify-between gap-3 border-t border-line px-6 py-3.5">
          <span className="font-mono text-[10px] text-faint">
            Publishing replays this against 90 days of real history first.
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
            <Button variant="ghost" size="sm" icon="check" onClick={onSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save draft'}
            </Button>
            <Button variant="primary" size="sm" icon="clock" onClick={onSimulate}>
              Simulate &amp; publish
            </Button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{children}</div>
}

// ── One step row ─────────────────────────────────────────────────────────────

function StepEditor({
  step, index, count, onPatch, onRemove, onMove,
}: {
  step: PlaybookStep
  index: number
  count: number
  onPatch: (s: PlaybookStep) => void
  onRemove: () => void
  onMove: (dir: -1 | 1) => void
}) {
  const meta = nodeMeta(KIND_TO_NODE[step.kind])
  const tone = asTone(meta.tone)

  return (
    <li className="relative flex gap-3">
      <span className={`relative z-10 mt-2 grid h-7 w-7 shrink-0 place-items-center rounded-full border border-line ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
        <Icon name={meta.icon as IconName} size={13} />
      </span>
      <div className="min-w-0 flex-1 rounded-card border border-line bg-bg/40 px-3.5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-medium text-ink">{meta.label}</span>
          <span className="truncate font-mono text-[10px] text-faint">{stepPhrase(step)}</span>
          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            <RowButton label="Move step up" disabled={index === 0} onClick={() => onMove(-1)}>
              <Icon name="arrowRight" size={11} className="-rotate-90" />
            </RowButton>
            <RowButton label="Move step down" disabled={index === count - 1} onClick={() => onMove(1)}>
              <Icon name="arrowRight" size={11} className="rotate-90" />
            </RowButton>
            <RowButton label="Remove step" danger onClick={onRemove}>
              <Icon name="x" size={11} />
            </RowButton>
          </div>
        </div>
        <div className="mt-2">
          <StepConfig step={step} onPatch={onPatch} />
        </div>
      </div>
    </li>
  )
}

function RowButton({ label, danger, disabled, onClick, children }: {
  label: string
  danger?: boolean
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button" aria-label={label} disabled={disabled} onClick={onClick}
      className={`grid h-6 w-6 cursor-pointer place-items-center rounded-control text-faint transition-colors disabled:cursor-default disabled:opacity-30 ${
        danger ? 'hover:text-danger' : 'hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

const INPUT = 'w-full rounded-control border border-line bg-bg/60 px-2.5 py-1.5 text-xs text-ink outline-none focus:border-accent/40'

function StepConfig({ step, onPatch }: { step: PlaybookStep; onPatch: (s: PlaybookStep) => void }) {
  switch (step.kind) {
    case 'send':
    case 'notify':
      return (
        <textarea
          value={step.body}
          onChange={(e) => onPatch({ ...step, body: e.target.value })}
          rows={step.kind === 'send' ? 3 : 2} dir="auto"
          placeholder={step.kind === 'send' ? 'The message the lead receives…' : 'What the notification says…'}
          aria-label={step.kind === 'send' ? 'Message to the lead' : 'Notification text'}
          className={`${INPUT} resize-none leading-relaxed`}
        />
      )
    case 'wait':
      return (
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="number" min={1} value={step.hours}
            onChange={(e) => onPatch({ ...step, hours: Math.max(1, Number(e.target.value) || 1) })}
            aria-label="Hours to wait"
            className="w-20 rounded-control border border-line bg-bg/60 px-2 py-1.5 font-mono text-xs tabular-nums text-ink outline-none focus:border-accent/40"
          />
          hours before the next step
        </label>
      )
    case 'if':
      return <PredicateBuilder predicate={step.predicate} onChange={(p) => onPatch({ ...step, predicate: p })} />
    case 'advance':
      return (
        <label className="flex items-center gap-2 text-xs text-muted">
          move the lead to
          <select
            value={step.to_stage}
            onChange={(e) => onPatch({ ...step, to_stage: e.target.value })}
            aria-label="Stage to advance to"
            className="rounded-control border border-line bg-bg/60 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent/40"
          >
            {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      )
    case 'note':
      return (
        <input
          value={step.note}
          onChange={(e) => onPatch({ ...step, note: e.target.value })}
          placeholder="The note added to the person's timeline…"
          aria-label="Note text" dir="auto" className={INPUT}
        />
      )
    case 'flag':
      return (
        <input
          value={step.flag}
          onChange={(e) => onPatch({ ...step, flag: e.target.value })}
          placeholder="flag_name" aria-label="Flag name"
          className={`${INPUT} font-mono`}
        />
      )
  }
}
