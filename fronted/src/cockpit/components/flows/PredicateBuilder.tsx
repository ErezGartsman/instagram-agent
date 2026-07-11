import { parsePredicate, buildPredicate, STAGES } from '../../lib/playbook'

/**
 * PredicateBuilder — a bounded, safe editor for the common flow predicate:
 * "stage is one of [...] AND the lead has been quiet ≥ N hours". Shared by the
 * state-trigger editor and 'only if' steps in the composer. The pure
 * parse/build logic lives in lib/playbook (tested there); a predicate that
 * doesn't fit the editable shape shows a read-only note rather than risk
 * corrupting a hand-authored one.
 */

export function PredicateBuilder({
  predicate,
  onChange,
}: {
  predicate: unknown
  onChange: (next: Record<string, unknown>) => void
}) {
  const model = parsePredicate(predicate)
  if (model === null) {
    return (
      <p className="rounded-control border border-line bg-raised px-3 py-2 text-[11px] text-faint">
        Advanced predicate — edit in the flow JSON. The visual builder handles
        stage + quiet-duration conditions.
      </p>
    )
  }

  const toggleStage = (stage: string) => {
    const stages = model.stages.includes(stage)
      ? model.stages.filter((s) => s !== stage)
      : [...model.stages, stage]
    onChange(buildPredicate({ ...model, stages }))
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-faint">Stage is one of</div>
        <div className="flex flex-wrap gap-1.5">
          {STAGES.map((s) => {
            const on = model.stages.includes(s)
            return (
              <button
                key={s}
                type="button"
                onClick={() => toggleStage(s)}
                className={`rounded-control border px-2 py-1 text-[11px] transition-colors ${
                  on
                    ? 'border-[rgba(59,130,246,0.5)] bg-[rgba(59,130,246,0.12)] text-glow'
                    : 'border-line text-muted hover:text-ink'
                }`}
              >
                {s}
              </button>
            )
          })}
        </div>
      </div>
      <div>
        <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-faint">Quiet for at least</div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            value={model.hours ?? ''}
            onChange={(e) =>
              onChange(buildPredicate({ ...model, hours: e.target.value === '' ? null : Math.max(0, Number(e.target.value)) }))
            }
            placeholder="—"
            className="w-20 rounded-control border border-line bg-transparent px-2 py-1 font-mono text-xs tabular-nums text-ink outline-none focus:border-accent/40"
          />
          <span className="text-xs text-muted">hours</span>
        </div>
      </div>
    </div>
  )
}
