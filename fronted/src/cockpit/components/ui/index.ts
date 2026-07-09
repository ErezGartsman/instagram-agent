/**
 * The cockpit primitive library (E1, SYSTEM_ELEVATION_PRD.md §A1).
 *
 * The rule: pages COMPOSE these; pages never restyle glass, buttons, badges,
 * or shortcut chips inline. A new visual need = a new variant here, reviewed
 * against Midnight Instrument (CLAUDE.md §4) — not a one-off className.
 */
export { Button, type ButtonProps } from './Button'
export { Badge, type BadgeProps } from './Badge'
export { GlassPanel, type GlassPanelProps } from './GlassPanel'
export { Kbd } from './Kbd'
export { Skeleton } from './Skeleton'
