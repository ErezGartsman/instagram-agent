import { useSyncExternalStore } from 'react'

/**
 * aiDock — a tiny module-level store for the assistant's "pinned" dock state.
 *
 * The GlowingAiAssistant writes it; AppShell subscribes so the content column
 * reflows (never overlays) when the panel docks — data density is sacred, so
 * pinning squeezes the layout instead of covering it. No context, no prop
 * drilling: useSyncExternalStore keeps both sides in lockstep.
 */

export const AI_DOCK_WIDTH = 400

let pinned = false
const listeners = new Set<() => void>()

export function getAiDockPinned(): boolean {
  return pinned
}

export function setAiDockPinned(next: boolean): void {
  if (pinned === next) return
  pinned = next
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useAiDockPinned(): boolean {
  return useSyncExternalStore(subscribe, getAiDockPinned)
}
