import { useSyncExternalStore } from 'react'

/**
 * navSignals — a tiny store carrying live accountability counts into the shell.
 *
 * The Command screen's single data cycle writes { yourMove, breach } here; the
 * Sidebar subscribes so the "Work queue" nav item can answer "do I need to go
 * there?" without its own fetcher. Same pattern as aiDock: module store +
 * useSyncExternalStore, no context, no prop drilling.
 */

export type NavSignals = { yourMove: number; breach: number }

let signals: NavSignals = { yourMove: 0, breach: 0 }
const listeners = new Set<() => void>()

export function setNavSignals(next: NavSignals): void {
  if (next.yourMove === signals.yourMove && next.breach === signals.breach) return
  signals = next
  listeners.forEach((l) => l())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useNavSignals(): NavSignals {
  return useSyncExternalStore(subscribe, () => signals)
}
