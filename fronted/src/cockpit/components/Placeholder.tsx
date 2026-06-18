import { Icon } from './Icon'
import type { IconName } from './Icon'

/** A calm "coming soon" empty state — the recurring card pattern for unbuilt pillars. */
export function Placeholder({
  icon,
  title,
  body,
  ticket,
}: {
  icon: IconName
  title: string
  body: string
  ticket: string
}) {
  return (
    <div className="flex flex-col items-center rounded-card border border-line bg-surface px-8 py-16 text-center">
      <span className="mb-5 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-accent">
        <Icon name={icon} size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-muted">{body}</p>
      <span className="mt-5 rounded-control border border-line px-3 py-1 text-xs text-muted">
        {ticket}
      </span>
    </div>
  )
}
