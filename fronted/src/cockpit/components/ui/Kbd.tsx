/** Kbd — keyboard-shortcut chip, JetBrains Mono per the numeral voice rule
 *  (E1 primitive library, SYSTEM_ELEVATION_PRD.md §A1 / §A6 command-first). */
import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export function Kbd({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        'inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] border border-line',
        'bg-raised px-1 font-mono text-[10px] text-muted',
        className,
      )}
      {...props}
    />
  )
}
