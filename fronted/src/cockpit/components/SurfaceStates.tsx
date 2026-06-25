import type { ReactNode } from 'react'
import { Icon } from './Icon'
import type { IconName } from './Icon'

// ── Bone ──────────────────────────────────────────────────────────────────────
// The atom of every skeleton: a warm-gold shimmer block. Geometry comes
// from the parent variant; this just applies the shimmer class + radius.
function Bone({ className = '' }: { className?: string }) {
  return <div className={`cq-shimmer-block rounded-control ${className}`} aria-hidden />
}

// ── SurfaceLoading ────────────────────────────────────────────────────────────
// Five geometry variants — each mirrors the real surface's layout so the
// skeleton is a faithful stand-in, not a generic spinner or blank box.
// Killed by prefers-reduced-motion via the global CSS guard.
// ─────────────────────────────────────────────────────────────────────────────

function GridLoading() {
  return (
    <div aria-hidden aria-label="Loading">
      <div className="mb-9 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Bone key={i} className="h-24 rounded-card" />
        ))}
      </div>
      <Bone className="h-28 rounded-card" />
    </div>
  )
}

function BoardLoading() {
  return (
    <div className="flex gap-4 overflow-x-auto pb-4" aria-hidden aria-label="Loading">
      {Array.from({ length: 5 }).map((_, c) => (
        <div key={c} className="flex w-[264px] shrink-0 flex-col gap-2">
          <Bone className="h-4 w-24" />
          <Bone className="h-20 rounded-card" />
          <Bone className="h-20 rounded-card" />
        </div>
      ))}
    </div>
  )
}

function QueueLoading() {
  return (
    <div
      className="flex h-full min-h-0 overflow-hidden rounded-card border border-line bg-bg"
      aria-hidden
      aria-label="Loading"
    >
      <div className="flex w-[300px] shrink-0 flex-col gap-1.5 border-r border-line bg-surface p-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Bone key={i} className="h-14" />
        ))}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-6">
        <Bone className="h-5 w-40" />
        <Bone className="h-4 w-56" />
        <Bone className="mt-2 h-24 rounded-card" />
      </div>
      <div className="flex w-[300px] shrink-0 flex-col gap-3 border-l border-line p-5">
        <Bone className="h-20 rounded-card" />
        <Bone className="h-4 w-32" />
      </div>
    </div>
  )
}

function BentoLoading() {
  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      aria-hidden
      aria-label="Loading"
    >
      {([2, 1, 1, 2, 2, 2, 1, 1] as const).map((span, i) => (
        <Bone key={i} className={`h-32 rounded-card ${span === 2 ? 'sm:col-span-2' : ''}`} />
      ))}
    </div>
  )
}

function RailLoading() {
  return (
    <div
      className="flex h-full min-h-0 overflow-hidden rounded-card border border-line bg-bg"
      aria-hidden
      aria-label="Loading"
    >
      <div className="flex w-[280px] shrink-0 flex-col gap-1.5 border-r border-line bg-surface p-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Bone key={i} className="h-12" />
        ))}
      </div>
      <div className="flex flex-1 flex-col gap-4 p-6">
        <Bone className="h-7 w-2/3" />
        <Bone className="h-4 w-1/3" />
        <Bone className="mt-2 h-40 rounded-card" />
      </div>
    </div>
  )
}

export type LoadingVariant = 'grid' | 'board' | 'queue' | 'bento' | 'rail'

export function SurfaceLoading({
  variant,
  className = '',
}: {
  variant: LoadingVariant
  className?: string
}) {
  const inner = (() => {
    switch (variant) {
      case 'grid':  return <GridLoading />
      case 'board': return <BoardLoading />
      case 'queue': return <QueueLoading />
      case 'bento': return <BentoLoading />
      case 'rail':  return <RailLoading />
    }
  })()
  return className ? <div className={className}>{inner}</div> : inner
}

// ── SurfaceEmpty ──────────────────────────────────────────────────────────────
// Two flavors:
//   'win'   — achievement tone (sage check). Queue clear, all caught up.
//   'start' — invitation tone (gold sparkle). Nothing here yet — start one.
//
// copilotSlot — the P2 architectural hook. When the Ambient Copilot is built,
// it mounts a <CopilotNudge /> here so empty states become proactive surfaces:
// "Queue's clear — but 3 leads need follow-ups. Draft them?" Pass null until
// then; the slot renders nothing but is structurally present in the layout.
// ─────────────────────────────────────────────────────────────────────────────

export function SurfaceEmpty({
  flavor = 'start',
  icon,
  title,
  body,
  action,
  copilotSlot,
  className = '',
}: {
  flavor?: 'win' | 'start'
  icon?: IconName
  title: string
  body: string
  action?: ReactNode
  /** P2 hook — Ambient Copilot mounts proactive nudges here. */
  copilotSlot?: ReactNode
  className?: string
}) {
  const defaultIcon: IconName = flavor === 'win' ? 'check' : 'sparkle'
  return (
    <div
      className={`flex flex-col items-center rounded-card border border-line bg-surface px-8 py-16 text-center [box-shadow:var(--shadow-card)] ${className}`}
    >
      <span
        className={`mb-5 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised ${
          flavor === 'win' ? 'text-success' : 'text-accent'
        }`}
      >
        <Icon name={icon ?? defaultIcon} size={22} />
      </span>

      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted">{body}</p>

      {action != null && <div className="mt-6">{action}</div>}

      {/* ── Copilot slot ──────────────────────────────────────────────────────
          P2: <CopilotNudge /> mounts here. null until the Copilot is built.
          The container is declared now so the layout never needs to change. */}
      {copilotSlot != null && (
        <div className="mt-6 w-full max-w-sm rounded-card border border-line p-4 text-left">
          {copilotSlot}
        </div>
      )}
    </div>
  )
}

// ── SurfaceError ──────────────────────────────────────────────────────────────
// Soft terracotta (--color-danger = #d08770) for the icon — attention, not
// alarm. onRetry re-runs the caller's fetch in place; no full page reload.
// ─────────────────────────────────────────────────────────────────────────────

export function SurfaceError({
  title = "Couldn't load this surface",
  body = 'Check your connection and try again.',
  onRetry,
  className = '',
}: {
  title?: string
  body?: string
  onRetry?: () => void
  className?: string
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-card border border-line bg-surface px-8 py-16 text-center [box-shadow:var(--shadow-card)] ${className}`}
    >
      <span className="mb-5 grid h-12 w-12 place-items-center rounded-control border border-[rgba(208,135,112,0.25)] bg-raised text-danger">
        <Icon name="alert" size={22} />
      </span>

      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <p className="mt-2 max-w-sm text-sm leading-relaxed text-muted">{body}</p>

      {onRetry != null && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-6 inline-flex items-center gap-2 rounded-control border border-line bg-raised px-4 py-2 text-sm text-muted transition-colors hover:bg-surface hover:text-ink"
        >
          <Icon name="refresh" size={14} />
          Try again
        </button>
      )}
    </div>
  )
}
