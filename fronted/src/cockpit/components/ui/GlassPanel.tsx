/**
 * GlassPanel — the Midnight Instrument glass surface, in its three legal
 * depths (E1 primitive library, SYSTEM_ELEVATION_PRD.md §A1).
 *
 *   section — backdrop-blur glass + card glow shadow. Section-level containers
 *             ONLY (the CLAUDE.md §4 rule: blur never on list rows).
 *   card    — flat rgba surface + hairline; the list-row / tile material.
 *   inset   — raised rgba, no border; nested wells inside a section.
 *
 * If a component needs different glass than these three, that is a design
 * question for the system, not a className override.
 */
import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/cn'

const panel = cva('rounded-card', {
  variants: {
    depth: {
      section:
        'border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]',
      card: 'border border-line bg-surface',
      inset: 'bg-raised',
    },
  },
  defaultVariants: { depth: 'card' },
})

export interface GlassPanelProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof panel> {}

export function GlassPanel({ className, depth, ...props }: GlassPanelProps) {
  return <div className={cn(panel({ depth }), className)} {...props} />
}
