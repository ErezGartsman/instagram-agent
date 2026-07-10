/**
 * AnimatedNumber — count-up on stat deltas (E2, SYSTEM_ELEVATION_PRD.md §A3:
 * "data updates transition ... a live instrument, never a blinking refresh").
 *
 * Tweens the raw number on CHANGE only — the first render jumps straight to
 * its value (a KPI tile counting up from 0 on every page load reads as a
 * gimmick, not an instrument). `formatter` runs every frame, so compact()-
 * style suffixes ("75.2k") animate correctly, not just bare integers.
 * `prefers-reduced-motion` skips the tween entirely.
 */
import { useEffect, useRef, useState } from 'react'

const DURATION_MS = 400
const EASE_OUT = (t: number) => 1 - Math.pow(1 - t, 3)

function prefersReducedMotion(): boolean {
  return !!(typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
}

export function AnimatedNumber({
  value,
  formatter = (n) => String(Math.round(n)),
  className,
}: {
  value: number
  formatter?: (n: number) => string
  className?: string
}) {
  const [display, setDisplay] = useState(value)
  const prevRef = useRef(value)
  const rafRef = useRef<number | null>(null)
  const mountedRef = useRef(false)

  useEffect(() => {
    const from = prevRef.current
    prevRef.current = value
    if (!mountedRef.current) {
      mountedRef.current = true
      setDisplay(value)
      return
    }
    if (from === value || prefersReducedMotion()) {
      setDisplay(value)
      return
    }
    // Start the clock from the FIRST rAF callback's own timestamp, not a
    // separate performance.now() call — some environments (older jsdom)
    // don't share a clock origin between the two, which produces a huge
    // (even negative) elapsed time on the first tick.
    let start: number | null = null
    const tick = (now: number) => {
      if (start === null) start = now
      const t = Math.min(1, (now - start) / DURATION_MS)
      setDisplay(from + (value - from) * EASE_OUT(t))
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }
  }, [value])

  return <span className={className}>{formatter(display)}</span>
}
