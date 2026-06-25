import type { LucideIcon } from 'lucide-react'
import { LayoutGrid, ListChecks, Columns3, Inbox, Sparkles, ChartColumn } from 'lucide-react'
import { FEATURES } from '../lib/flags'

export type NavItem = { to: string; label: string; icon: LucideIcon }
/** A nav group — an optional micro-label over a set of items. Empty groups
 *  (everything in them flagged off) are skipped by the Sidebar. */
export type NavSection = { label?: string; items: NavItem[] }

/**
 * The Cockpit nav, grouped by mode of work so it never reads as a flat
 * corporate list: Overview pinned on top, then Work (act) · Studio (create) ·
 * Insight (measure). Feature-flagged surfaces stay dark until ready.
 *
 * Icons are lucide-react components (the shell icon system) — the Sidebar renders
 * `<item.icon />` directly, so swapping a glyph means swapping the import here.
 */
export const NAV_SECTIONS: NavSection[] = [
  { items: [{ to: '/app', label: 'Today', icon: LayoutGrid }] },
  {
    label: 'Work',
    items: [
      ...(FEATURES.workQueue
        ? [{ to: '/app/queue', label: 'Work queue', icon: ListChecks }]
        : []),
      { to: '/app/pipeline', label: 'Pipeline', icon: Columns3 },
      // Inbox hidden until P2 builds the full WhatsApp thread view (B2 decision).
      // Route /app/inbox stays registered; VITE_FEATURE_INBOX=1 to preview locally.
      ...(FEATURES.inbox
        ? [{ to: '/app/inbox', label: 'Inbox', icon: Inbox }]
        : []),
    ],
  },
  {
    label: 'Studio',
    items: [
      ...(FEATURES.content
        ? [{ to: '/app/content', label: 'Content', icon: Sparkles }]
        : []),
    ],
  },
  {
    label: 'Intelligence',
    items: [
      ...(FEATURES.analytics
        ? [{ to: '/app/analytics', label: 'Analytics', icon: ChartColumn }]
        : []),
    ],
  },
]

/** Flattened view — for title lookups (Topbar) and route checks. */
export const NAV: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items)
