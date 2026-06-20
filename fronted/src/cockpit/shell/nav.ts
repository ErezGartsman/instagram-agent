import type { IconName } from '../components/Icon'
import { FEATURES } from '../lib/flags'

export type NavItem = { to: string; label: string; icon: IconName }

/** The Cockpit pillars, in build order (Tickets 5.1 → 5.4). The Work Queue
 *  (5.2) is gated on its feature flag so it stays dark in prod until ready. */
export const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'grid' },
  ...(FEATURES.workQueue
    ? [{ to: '/queue', label: 'Work queue', icon: 'queue' as IconName }]
    : []),
  { to: '/pipeline', label: 'Pipeline', icon: 'columns' },
  { to: '/inbox', label: 'Inbox', icon: 'inbox' },
  { to: '/content', label: 'Content', icon: 'sparkle' },
]
