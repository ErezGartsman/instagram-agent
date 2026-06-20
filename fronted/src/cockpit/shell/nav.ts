import type { IconName } from '../components/Icon'
import { FEATURES } from '../lib/flags'

export type NavItem = { to: string; label: string; icon: IconName }
/** A nav group — an optional micro-label over a set of items. Empty groups
 *  (everything in them flagged off) are skipped by the Sidebar. */
export type NavSection = { label?: string; items: NavItem[] }

/**
 * The Cockpit nav, grouped by mode of work so it never reads as a flat
 * corporate list: Overview pinned on top, then Work (act) · Studio (create) ·
 * Insight (measure). Feature-flagged surfaces stay dark until ready.
 */
export const NAV_SECTIONS: NavSection[] = [
  { items: [{ to: '/', label: 'Overview', icon: 'grid' }] },
  {
    label: 'Work',
    items: [
      ...(FEATURES.workQueue
        ? [{ to: '/queue', label: 'Work queue', icon: 'queue' as IconName }]
        : []),
      { to: '/pipeline', label: 'Pipeline', icon: 'columns' },
      { to: '/inbox', label: 'Inbox', icon: 'inbox' },
    ],
  },
  {
    label: 'Studio',
    items: [{ to: '/content', label: 'Content', icon: 'sparkle' }],
  },
  {
    label: 'Insight',
    items: [
      ...(FEATURES.analytics
        ? [{ to: '/analytics', label: 'Analytics', icon: 'chart' as IconName }]
        : []),
    ],
  },
]

/** Flattened view — for title lookups (Topbar) and route checks. */
export const NAV: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items)
