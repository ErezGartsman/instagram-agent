import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import { verifierLabel, VERDICT_TONE, type Verification, type VerifierVerdict } from '../../lib/flows'
import { asTone, TONE_TEXT, TONE_TINT, TONE_BORDER } from './tone'

/**
 * VerifierPanel — the Verifier Loop's five-agent review, rendered so Erez can
 * see at a glance which reviewer decided a run's fate and why. The blocking
 * verdict is pulled to the top and expanded; the rest collapse to a quiet
 * row of pass/verdict dots. This is the "why" the whole F2 surface exists for.
 */

const DECISION_ICON: Record<VerifierVerdict['decision'], IconName> = {
  approve: 'check', reject: 'x', defer: 'clock', error: 'alert',
}

const AGGREGATE_COPY: Record<Verification['decision'], { label: string; sub: string }> = {
  approve: { label: 'Cleared by the panel', sub: 'all five reviewers approved' },
  reject: { label: 'Blocked by the panel', sub: 'one reviewer vetoed the send' },
  defer: { label: 'Deferred by the panel', sub: 'held back, will retry' },
}

export function VerifierPanel({ verification }: { verification: Verification }) {
  const agg = asTone(VERDICT_TONE[verification.decision])
  const copy = AGGREGATE_COPY[verification.decision]
  const blocking = verification.blocking
  const others = verification.verdicts.filter((v) => v.verifier !== blocking?.verifier)

  return (
    <div className="rounded-card border border-line bg-bg/40 p-3">
      {/* Aggregate verdict header */}
      <div className="mb-3 flex items-center gap-2.5">
        <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-control ${TONE_TINT[agg]} ${TONE_TEXT[agg]}`}>
          <Icon name="shield" size={14} />
        </span>
        <div className="min-w-0">
          <div className={`text-[13px] font-semibold ${TONE_TEXT[agg]}`}>{copy.label}</div>
          <div className="font-mono text-[10px] text-faint">Verifier Loop · {copy.sub}</div>
        </div>
      </div>

      {/* The decisive verdict, expanded */}
      {blocking && (
        <div className={`mb-2 rounded-control border ${TONE_BORDER[asTone(VERDICT_TONE[blocking.decision])]} ${TONE_TINT[asTone(VERDICT_TONE[blocking.decision])]} px-3 py-2`}>
          <div className="flex items-center gap-2">
            <VerdictDot verdict={blocking} />
            <span className="text-[12px] font-medium text-ink">{verifierLabel(blocking.verifier)}</span>
            {blocking.defer_hours != null && (
              <span className="ml-auto font-mono text-[10px] text-warn">retry in {blocking.defer_hours}h</span>
            )}
          </div>
          {blocking.detail && (
            <p className="mt-1 pl-6 text-[11px] leading-snug text-muted">{blocking.detail}</p>
          )}
        </div>
      )}

      {/* The rest — quiet pass rows */}
      <ul className="space-y-1">
        {others.map((v) => (
          <li key={v.verifier} className="flex items-center gap-2 px-1 py-0.5">
            <VerdictDot verdict={v} />
            <span className="text-[11px] text-muted">{verifierLabel(v.verifier)}</span>
            <span className={`ml-auto font-mono text-[9px] uppercase tracking-wider ${TONE_TEXT[asTone(VERDICT_TONE[v.decision])]}`}>
              {v.decision}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function VerdictDot({ verdict }: { verdict: VerifierVerdict }) {
  const tone = asTone(VERDICT_TONE[verdict.decision])
  return (
    <span className={`grid h-4 w-4 shrink-0 place-items-center rounded-full ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
      <Icon name={DECISION_ICON[verdict.decision]} size={9} />
    </span>
  )
}
