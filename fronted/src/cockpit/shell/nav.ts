import type { IconName } from '../components/Icon'

export type NavItem = { to: string; label: string; icon: IconName }

/** The four Cockpit pillars, in build order (Tickets 5.1 → 5.4). */
export const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'grid' },
  { to: '/pipeline', label: 'Pipeline', icon: 'columns' },
  { to: '/inbox', label: 'Inbox', icon: 'inbox' },
  { to: '/content', label: 'Content', icon: 'sparkle' },
]
