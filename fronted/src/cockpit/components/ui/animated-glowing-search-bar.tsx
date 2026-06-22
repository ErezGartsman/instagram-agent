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
 * Glass search field for the Topbar — quiet at rest, a static violet ambient glow
 * on focus (no motion, no spin). lucide Search icon for shell icon consistency.
 * Focus styling (border + dual-glow box-shadow + icon tint) lives in index.css
 * under `.cq-search:focus-within` — scoped CSS rather than JIT focus utilities, so
 * it's reliable; the global reduced-motion guard flattens the transition.
 */
export function AnimatedSearchBar({
  placeholder = 'Search leads, conversations…',
  className = '',
  value,
  onChange,
}: Props) {
  const id = useId()
  return (
    <div className={`relative ${className}`}>
      {/* Glass field — hairline at rest, a calm violet bloom on focus (see index.css). */}
      <div className="cq-search flex items-center gap-2.5 rounded-control border border-line bg-bg/70 px-3.5 py-2 backdrop-blur-xl">
        <Search size={16} strokeWidth={1.8} aria-hidden className="shrink-0 text-faint" />
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
