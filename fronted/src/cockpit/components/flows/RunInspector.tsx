import { Icon } from '../Icon'
import { Button } from '../ui'
import { VerifierPanel } from './VerifierPanel'
import { relativeTime } from '../../lib/pipeline'
import {
  nodeMeta, RUN_STATUS_TONE, STEP_STATUS_TONE, STEP_STATUS_LABEL,
  type FlowRun, type FlowRunStep, type FlowSummary,
} from '../../lib/flows'
import { asTone, TONE_TEXT, TONE_DOT, TONE_TINT } from './tone'

/**
 * RunInspector — the right rail. Two levels, Linear-style drill-in:
 *   list   — recent runs for the selected flow, each a selectable row.
 *   detail — one run's step timeline; send/notify steps expand the full
 *            Verifier Loop panel inline. A back affordance returns to the list.
 * Selecting a run drives the canvas replay (owned by the page); clicking a
 * step syncs the canvas node highlight.
 */
export function RunInspector({
  flow,
  runs,
  selectedRun,
  onSelectRun,
  selectedNode,
  onSelectNode,
  onSweep,
  sweeping,
  canSweep,
}: {
  flow: FlowSummary
  runs: FlowRun[]
  selectedRun: FlowRun | null
  onSelectRun: (id: string | null) => void
  selectedNode: string | null
  onSelectNode: (nodeId: string | null) => void
  onSweep: () => void
  sweeping: boolean
  canSweep: boolean
}) {
  return (
    <aside className="flex h-full w-[384px] shrink-0 flex-col border-l border-line">
      {selectedRun ? (
        <RunDetail
          run={selectedRun}
          onBack={() => { onSelectRun(null); onSelectNode(null) }}
          selectedNode={selectedNode}
          onSelectNode={onSelectNode}
        />
      ) : (
        <RunList
          flow={flow} runs={runs} onSelect={(id) => onSelectRun(id)}
          onSweep={onSweep} sweeping={sweeping} canSweep={canSweep}
        />
      )}
    </aside>
  )
}

// ── List level ────────────────────────────────────────────────────────────────

function RunList({
  flow, runs, onSelect, onSweep, sweeping, canSweep,
}: {
  flow: FlowSummary
  runs: FlowRun[]
  onSelect: (id: string) => void
  onSweep: () => void
  sweeping: boolean
  canSweep: boolean
}) {
  return (
    <>
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Runs</div>
          <div className="mt-0.5 text-sm text-muted">
            <span className="font-mono tabular-nums text-ink">{flow.run_count}</span> total
          </div>
        </div>
        {canSweep && (
          <Button variant="outline" size="sm" icon="play" onClick={onSweep} disabled={sweeping}>
            {sweeping ? 'Running…' : 'Run sweep'}
          </Button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {runs.length === 0 ? (
          <div className="flex flex-col items-center px-6 py-16 text-center">
            <span className="mb-3 grid h-10 w-10 place-items-center rounded-control border border-line bg-raised text-faint">
              <Icon name="clock" size={18} />
            </span>
            <p className="text-sm text-muted">No runs yet.</p>
            <p className="mt-1 text-xs text-faint">
              The engine records a run each time this flow&rsquo;s trigger fires.
            </p>
          </div>
        ) : (
          runs.map((run) => <RunRow key={run.id} run={run} onSelect={() => onSelect(run.id)} />)
        )}
      </div>
    </>
  )
}

function RunRow({ run, onSelect }: { run: FlowRun; onSelect: () => void }) {
  const tone = asTone(RUN_STATUS_TONE[run.status])
  // The outcome of the last step is the run's "verdict at a glance".
  const last = run.steps[run.steps.length - 1]
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group flex w-full items-center gap-3 rounded-control px-3 py-2.5 text-left transition-colors hover:bg-raised"
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[tone]}`} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-ink">{run.person_name}</span>
        <span className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] text-faint">
          <span className={TONE_TEXT[tone]}>{run.status}</span>
          {last && <><span>·</span><span>{stepVerdictSummary(last)}</span></>}
        </span>
      </span>
      <span className="shrink-0 font-mono text-[10px] text-faint">{relativeTime(run.started_at)}</span>
      <Icon name="arrowRight" size={13} className="shrink-0 text-faint transition-colors group-hover:text-glow" />
    </button>
  )
}

// ── Detail level ────────────────────────────────────────────────────────────────

function RunDetail({
  run, onBack, selectedNode, onSelectNode,
}: {
  run: FlowRun
  onBack: () => void
  selectedNode: string | null
  onSelectNode: (nodeId: string | null) => void
}) {
  const tone = asTone(RUN_STATUS_TONE[run.status])
  return (
    <>
      <div className="border-b border-line px-5 py-3.5">
        <button
          type="button"
          onClick={onBack}
          className="mb-2.5 inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-faint transition-colors hover:text-muted"
        >
          <Icon name="arrowRight" size={12} className="rotate-180" />
          All runs
        </button>
        <div className="flex items-center gap-2.5">
          <span className={`h-2 w-2 shrink-0 rounded-full ${TONE_DOT[tone]}`} aria-hidden />
          <span className="text-base font-medium text-ink">{run.person_name}</span>
          <span className={`ml-auto rounded-control px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
            {run.status}
          </span>
        </div>
        <p className="mt-1.5 font-mono text-[10px] text-faint">
          started {relativeTime(run.started_at)}
          {run.completed_at ? ` · finished ${relativeTime(run.completed_at)}` : ' · in flight'}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <ol className="relative space-y-1">
          {/* the timeline spine */}
          <span aria-hidden className="absolute bottom-3 left-[15px] top-3 w-px bg-line" />
          {run.steps.map((step, i) => (
            <StepRow
              key={`${step.node_id}:${i}`}
              step={step}
              selected={selectedNode === step.node_id}
              onToggle={() => onSelectNode(selectedNode === step.node_id ? null : step.node_id)}
            />
          ))}
        </ol>
      </div>
    </>
  )
}

function StepRow({
  step, selected, onToggle,
}: {
  step: FlowRunStep
  selected: boolean
  onToggle: () => void
}) {
  const meta = nodeMeta(step.node_type)
  const tone = asTone(STEP_STATUS_TONE[step.status])
  const verification = step.output.verification
  const preview = step.output.would_notify || step.output.would_send

  return (
    <li className="relative">
      <button
        type="button"
        onClick={onToggle}
        className={`flex w-full items-start gap-3 rounded-control py-2 pl-1.5 pr-2 text-left transition-colors ${
          selected ? 'bg-raised' : 'hover:bg-raised/60'
        }`}
      >
        <span className={`relative z-10 mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border ${
          tone === 'success' ? 'border-[rgba(52,211,153,0.4)]' :
          tone === 'accent' ? 'border-[rgba(59,130,246,0.4)]' :
          tone === 'danger' ? 'border-[rgba(224,112,92,0.4)]' :
          tone === 'warn' ? 'border-[rgba(217,169,78,0.4)]' : 'border-line'
        } ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
          <Icon name={step.status === 'blocked' || step.status === 'failed' ? 'x' : step.status === 'waiting' ? 'clock' : 'check'} size={12} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-ink">{meta.label}</span>
            <span className={`ml-auto shrink-0 font-mono text-[9px] uppercase tracking-wider ${TONE_TEXT[tone]}`}>
              {STEP_STATUS_LABEL[step.status]}
            </span>
          </span>
          {preview && (
            <span className="mt-0.5 block truncate text-[11px] leading-tight text-muted" dir="auto">
              {preview}
            </span>
          )}
          {step.error && (
            <span className="mt-0.5 block text-[11px] leading-tight text-danger">{step.error}</span>
          )}
        </span>
      </button>

      {/* The Verifier Loop panel, inline, when this step is expanded */}
      {selected && verification && (
        <div className="mb-1 ml-10 mr-1 mt-1">
          <VerifierPanel verification={verification} />
        </div>
      )}
    </li>
  )
}

// ── helpers ────────────────────────────────────────────────────────────────────

function stepVerdictSummary(step: FlowRunStep): string {
  if (step.output.verification?.blocking) {
    return step.output.verification.blocking.verifier.replace(/_/g, ' ')
  }
  return STEP_STATUS_LABEL[step.status].toLowerCase()
}
