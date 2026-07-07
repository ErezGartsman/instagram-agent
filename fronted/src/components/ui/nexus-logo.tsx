import { useId } from 'react'

/**
 * NexusLogo — "The Plumb."
 *
 * The true line, held: a razor-thin vertical plumb line descending through a
 * sharp minimalist N, ending in a balanced brass weight. The line and letter
 * are the machine (cold, exact — they render in currentColor); the weight is
 * the human hand (the single warm note in the entire system, by design).
 *
 * `size` is the rendered height in px; width scales at 0.6×. Gradient ids are
 * instance-unique (useId) so multiple logos can mount at once.
 */
export function NexusLogo({
  size = 32,
  className = '',
  title = 'Nexus',
}: {
  size?: number
  className?: string
  title?: string
}) {
  const uid = useId()
  const ball = `nx-ball-${uid}`
  const collar = `nx-collar-${uid}`
  return (
    <svg
      width={size * 0.6}
      height={size}
      viewBox="0 0 96 160"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label={title}
      className={className}
    >
      <defs>
        <radialGradient id={ball} cx="0.35" cy="0.28" r="0.85">
          <stop offset="0" stopColor="#ecd08a" />
          <stop offset="0.45" stopColor="#c9a24a" />
          <stop offset="1" stopColor="#7a5c1c" />
        </radialGradient>
        <linearGradient id={collar} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d8b45e" />
          <stop offset="1" stopColor="#8a6a24" />
        </linearGradient>
      </defs>

      {/* The plumb line — top of frame down to the weight */}
      <path d="M48 4 V121" stroke="currentColor" strokeWidth="2.4" />

      {/* The N — sharp, staggered, crossed by the line */}
      <path d="M30 56 V98" stroke="currentColor" strokeWidth="2.4" />
      <path d="M66 62 V104" stroke="currentColor" strokeWidth="2.4" />
      <path d="M30 56 L66 104" stroke="currentColor" strokeWidth="2.4" />

      {/* The weight — collar + brass sphere (the human hand) */}
      <rect x="44" y="121" width="8" height="6" rx="1.5" fill={`url(#${collar})`} />
      <circle cx="48" cy="140" r="11.5" fill={`url(#${ball})`} />
    </svg>
  )
}
