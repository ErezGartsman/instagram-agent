/**
 * Badge — small labeled chips: stages, channels, statuses, counts
 * (E1 primitive library, SYSTEM_ELEVATION_PRD.md §A1).
 *
 * `tone` carries meaning, `mono` switches numerals/codes to JetBrains Mono
 * per the two-voice typography rule. Counts use <Badge tone="count">.
 */
import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/cn'

const badge = cva(
  'inline-flex items-center gap-1.5 rounded-control px-2 py-0.5 text-xs',
  {
    variants: {
      tone: {
        neutral: 'border border-line bg-raised text-muted',
        accent: 'border border-[rgba(59,130,246,0.35)] bg-[rgba(59,130,246,0.12)] text-glow',
        success: 'border border-[rgba(52,211,153,0.3)] bg-[rgba(52,211,153,0.08)] text-success',
        warn: 'border border-[rgba(217,169,78,0.3)] bg-[rgba(217,169,78,0.08)] text-warn',
        danger: 'border border-[rgba(224,112,92,0.3)] bg-[rgba(224,112,92,0.08)] text-danger',
        sage: 'border border-[rgba(45,212,191,0.3)] bg-[rgba(45,212,191,0.08)] text-sage',
        /** Bare count chip (board columns, list headers). */
        count: 'bg-raised text-muted',
      },
      mono: {
        true: 'font-mono tabular-nums',
        false: '',
      },
    },
    defaultVariants: { tone: 'neutral', mono: false },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {}

export function Badge({ className, tone, mono, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone, mono }), className)} {...props} />
}
