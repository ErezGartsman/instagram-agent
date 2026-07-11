/**
 * PredicateBuilder — a bounded, safe editor for the common flow predicate:
 * "stage is one of [...] AND the lead has been quiet ≥ N hours". Shared by the
 * state-trigger editor and condition nodes. A predicate that doesn't fit this
 * shape shows a read-only note rather than risk corrupting a hand-authored one
 * (F3 V1 — the builder covers what the seeded/typical flows need).
 */
const STAGES = ['engaged', 'qualified', 'captured', 'briefed', 'booked'] as const

type Model = { stages: string[]; hours: number | null }

export function parsePredicate(pred: unknown): Model | null {
  if (!pred || typeof pred !== 'object') return { stages: [], hours: null }
  const p = pred as Record<string, unknown>
  // A fresh state trigger has no predicate yet — start from a blank model.
  if (Object.keys(p).length === 0) return { stages: [], hours: null }
  const clauses = Array.isArray(p.all) ? (p.all as Record<string, unknown>[]) : [p]
  const model: Model = { stages: [], hours: null }
  let recognized = 0
  for (const c of clauses) {
    if (c.field === 'stage' && c.op === 'in' && Array.isArray(c.value)) {
      model.stages = (c.value as string[]).filter((s) => STAGES.includes(s as typeof STAGES[number]))
      recognized++
    } else if (c.field === 'stage' && c.op === 'eq' && typeof c.value === 'string') {
      model.stages = [c.value]
      recognized++
    } else if (c.field === 'hours_since_last' && c.op === 'gte' && typeof c.value === 'number') {
      model.hours = c.value
      recognized++
    } else {
      return null // an unrecognized clause — don't pretend we can edit it
    }
  }
  return recognized > 0 || Object.keys(p).length === 0 ? model : null
}

export function buildPredicate(model: Model): Record<string, unknown> {
  const clauses: Record<string, unknown>[] = []
  if (model.stages.length) clauses.push({ field: 'stage', op: 'in', value: model.stages })
  if (model.hours != null) clauses.push({ field: 'hours_since_last', op: 'gte', value: model.hours })
  if (clauses.length === 1) return clauses[0]
  return { all: clauses }
}

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
