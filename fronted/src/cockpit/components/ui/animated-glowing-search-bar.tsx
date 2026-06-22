import { Search } from 'lucide-react'
import { useId } from 'react'

type Props = {
  placeholder?: string
  /** Extra classes for the outer wrapper — e.g. width caps from the Topbar. */
  className?: string
  value?: string
  onChange?: (value: string) => void
}

/**
 * Animated glow search — a conic violet→electric-blue ring orbits the field while
 * it is hovered or focused, then settles to a calm static glow at rest (idle never
 * loops, per the motion budget). Glass field over the void; the ring is the only
 * neon, lit on the active state.
 *
 * The icon is lucide-react for shell-wide icon consistency. The spin + dual-glow
 * colours live in index.css (.cq-search / .cq-search-glow) so the global
 * prefers-reduced-motion guard flattens the orbit to a static glow automatically.
 */
export function AnimatedSearchBar({
  placeholder = 'Search leads, conversations…',
  className = '',
  value,
  onChange,
}: Props) {
  const id = useId()
  return (
    <div className={`cq-search group relative rounded-control ${className}`}>
      {/* Orbiting conic ring — paused at rest, runs on hover/focus (see index.css). */}
      <span className="cq-search-glow" aria-hidden />

      {/* The field — glass-dark over the void, masking the ring to a glowing rim.
          A static hairline keeps it legible at rest; the ring is the active cue. */}
      <div className="relative flex items-center gap-2.5 rounded-control border border-line bg-bg/70 px-3.5 py-2 backdrop-blur-xl">
        <Search
          size={16}
          strokeWidth={1.8}
          aria-hidden
          className="shrink-0 text-faint transition-colors duration-200 group-focus-within:text-glow"
        />
        <label htmlFor={id} className="sr-only">
          Search
        </label>
        <input
          id={id}
          type="search"
          value={value}
          onChange={onChange ? (e) => onChange(e.target.value) : undefined}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          className="w-full min-w-0 bg-transparent text-sm text-ink outline-none placeholder:text-faint [&::-webkit-search-cancel-button]:appearance-none"
        />
      </div>
    </div>
  )
}
