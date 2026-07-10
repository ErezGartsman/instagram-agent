/**
 * Button — the one way to press things in the cockpit (E1 primitive library,
 * SYSTEM_ELEVATION_PRD.md §A1: pages compose primitives, never restyle glass).
 *
 * Variants map to Midnight Instrument roles:
 *   primary — electric-blue fill, the single loudest element on a surface
 *   ghost   — raised glass, the workhorse secondary
 *   subtle  — borderless text action for dense rows
 *   danger  — terracotta outline; destructive intent without alarm
 * One neon box-shadow max, and only on primary (the active-element rule).
 */
import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/cn'
import { Icon, type IconName } from '../Icon'

const button = cva(
  [
    'inline-flex items-center justify-center gap-2 rounded-control font-medium',
    'transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-glow',
    'disabled:pointer-events-none disabled:opacity-45',
  ],
  {
    variants: {
      variant: {
        primary:
          'bg-accent text-ink shadow-[0_0_14px_rgba(59,130,246,0.35)] hover:bg-[#4f8ef7]',
        ghost:
          'border border-line bg-raised text-muted hover:bg-surface hover:text-ink',
        subtle: 'text-muted hover:text-ink',
        /** Electric outline — the quiet call-to-action (New, Save). */
        outline: 'border border-accent/40 text-accent hover:bg-accent/10',
        danger:
          'border border-[rgba(224,112,92,0.35)] bg-transparent text-danger hover:bg-[rgba(224,112,92,0.08)]',
      },
      size: {
        sm: 'px-3 py-1.5 text-xs',
        md: 'px-4 py-2 text-sm',
      },
    },
    defaultVariants: { variant: 'ghost', size: 'md' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  /** Optional leading icon (from the cockpit Icon registry). */
  icon?: IconName
  /** Render the child element (e.g. a router <Link>) with button styling —
   *  keeps the DOM valid: never a <button> wrapping an <a>. */
  asChild?: boolean
  children?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, icon, asChild, type = 'button', children, ...props }, ref) => {
    if (asChild) {
      return (
        <Slot ref={ref} className={cn(button({ variant, size }), className)} {...props}>
          {children}
        </Slot>
      )
    }
    return (
      <button ref={ref} type={type} className={cn(button({ variant, size }), className)} {...props}>
        {icon && <Icon name={icon} size={size === 'sm' ? 13 : 15} />}
        {children}
      </button>
    )
  },
)
Button.displayName = 'Button'
