/** Skeleton — the shimmer bone every loading geometry is built from
 *  (E1 primitive library; extracted from SurfaceStates' private Bone so
 *  feature components can build faithful page-shaped skeletons too). */
import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn('cq-shimmer-block rounded-control', className)}
      {...props}
    />
  )
}
