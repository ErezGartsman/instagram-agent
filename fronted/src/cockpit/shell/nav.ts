import type { LucideIcon } from 'lucide-react'
import { LayoutGrid, ListChecks, Columns3, Inbox, Sparkles, ChartColumn } from 'lucide-react'
import { FEATURES } from '../lib/flags'

export type NavItem = { to: string; label: string; icon: LucideIcon }
/** A nav group — an optional micro-label over a set of items. Empty groups
 *  (everything in them flagged off) are skipped by the Sidebar. */
export type NavSection = { label?: string; items: NavItem[] }

/**
 * The Cockpit nav — restructured 2026-07-06 (Erez's IA directive):
 *   Command (the unified dense dashboard, index) →
 *   Work: Work queue (carries the live "your move" badge) · People (the board;
 *   "Pipeline" was CRM-speak — the product's soul is people) →
 *   Intelligence: Analytics.
 * Content is demoted out of the primary groups into the Sidebar footer
 * (FOOTER_NAV): the anonymized content engine stays a strategic pillar, but a
 * solo practitioner's daily nav doesn't spend a top-level slot on it.
 *
 * Icons are lucide-react components — the Sidebar renders `<item.icon />`.
 */
export const NAV_SECTIONS: NavSection[] = [
  { items: [{ to: '/app', label: 'Command', icon: LayoutGrid }] },
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
    label: 'Intelligence',
    items: [
      ...(FEATURES.analytics
        ? [{ to: '/app/analytics', label: 'Analytics', icon: ChartColumn }]
        : []),
    ],
  },
]

/** Quiet footer destinations — present, never loud. */
export const FOOTER_NAV: NavItem[] = FEATURES.content
  ? [{ to: '/app/content', label: 'Content', icon: Sparkles }]
  : []

/** Flattened view — for title lookups (Topbar) and route checks. */
export const NAV: NavItem[] = [...NAV_SECTIONS.flatMap((s) => s.items), ...FOOTER_NAV]
