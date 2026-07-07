import { useEffect, useRef } from 'react'
import { useReducedMotion } from 'framer-motion'

/**
 * Ambient cursor orb — a dual-color radial gradient that tracks the mouse via
 * requestAnimationFrame. Renders nothing when prefers-reduced-motion is active.
 * GPU-cheap: single fixed div, transform-only updates (no layout paint).
 */
export function CursorGlow() {
  const ref = useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion()

  useEffect(() => {
    if (reduce) return
    const el = ref.current
    if (!el) return
    let rafId = 0

    const onMove = (e: MouseEvent) => {
      cancelAnimationFrame(rafId)
      rafId = requestAnimationFrame(() => {
        el.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`
      })
    }

    window.addEventListener('mousemove', onMove, { passive: true })
    return () => {
      window.removeEventListener('mousemove', onMove)
      cancelAnimationFrame(rafId)
    }
  }, [reduce])

  if (reduce) return null

  return (
    <div
      ref={ref}
      className="pointer-events-none fixed left-0 top-0 z-[9999] h-0 w-0"
      aria-hidden
    >
      {/* Outer halo — wide, near-invisible cool-blue bleed */}
      <div
        style={{
          position: 'absolute',
          width: 700,
          height: 700,
          marginLeft: -350,
          marginTop: -350,
          borderRadius: '50%',
          background:
            'radial-gradient(circle, transparent 20%, rgba(59,130,246,0.03) 50%, transparent 70%)',
        }}
      />
      {/* Inner orb — electric-blue centered, the primary interactive glow */}
      <div
        style={{
          position: 'absolute',
          width: 420,
          height: 420,
          marginLeft: -210,
          marginTop: -210,
          borderRadius: '50%',
          background:
            'radial-gradient(circle, rgba(59,130,246,0.07) 0%, rgba(96,165,250,0.03) 45%, transparent 70%)',
        }}
      />
    </div>
  )
}
