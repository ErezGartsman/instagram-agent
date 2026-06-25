import { useCallback, useEffect, useRef, useState } from 'react'
import type { MutableRefObject } from 'react'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from './workqueue'

// ── Constants ──────────────────────────────────────────────────────────────
const POLL_MS = 30_000   // background poll interval
const FOCUS_DEBOUNCE_MS = 500  // guard against rapid focus/blur cycling

// ── Signature ──────────────────────────────────────────────────────────────
// Cheap string identity for a queue snapshot. If this is unchanged we skip
// setState entirely — zero re-renders on the common "nothing happened" poll.
function queueSig(items: QueueItem[]): string {
  return items.map((i) => `${i.id}:${i.stage ?? ''}:${i.confidence}`).join('|')
}

// ── Types ──────────────────────────────────────────────────────────────────
export type QueueDataState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; items: QueueItem[]; sample: boolean }

/**
 * Smart-polling queue data hook for P1 Liveness.
 *
 * Three guarantees:
 *   1. Signature-diff guard — setState is skipped when nothing changed.
 *   2. Pending-action suppression — if `suppressRef.current` is true
 *      (set by the Board while an optimistic action is in flight) the
 *      background poll yields silently. The next poll or focus-refetch
 *      picks up after the action commits / is undone.
 *   3. Aggressive focus-refetch — tab focus and visibility change both
 *      trigger an immediate check so Erez always lands on fresh data.
 *
 * @param token       Supabase access token (null while loading/signed out).
 * @param devBypass   True in local dev — uses SAMPLE_QUEUE, no API call.
 * @param suppressRef Mutable ref owned by WorkQueuePage, written by Board.
 *                    true  = action in flight, skip background setState.
 *                    false = safe to apply server updates.
 */
export function useQueueData(
  token: string | null,
  devBypass: boolean,
  suppressRef: MutableRefObject<boolean>,
): {
  state: QueueDataState
  refetch: () => void
} {
  const [state, setState] = useState<QueueDataState>({ kind: 'loading' })

  // Refs that change without triggering re-renders.
  const sigRef     = useRef('')                         // last known signature
  const abortRef   = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)

  // ── Core fetch ────────────────────────────────────────────────────────────
  // isInitial=true  → show loading state on error, always apply result.
  // isInitial=false → silent background; bail if suppressed or unchanged.
  const doFetch = useCallback(
    async (isInitial: boolean) => {
      if (!isInitial && suppressRef.current) return  // yield to action loop

      // ── Dev bypass ──────────────────────────────────────────────────────
      if (devBypass) {
        if (isInitial) {
          const items = rankQueue(SAMPLE_QUEUE)
          sigRef.current = queueSig(items)
          setState({ kind: 'ready', items, sample: true })
        }
        return
      }

      if (!token) return

      // Abort any in-flight request before starting a new one.
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      try {
        const raw   = await fetchQueue(token, controller.signal)
        if (!mountedRef.current) return
        const items  = rankQueue(raw)
        const newSig = queueSig(items)

        // Signature guard — nothing changed, skip setState entirely.
        if (!isInitial && newSig === sigRef.current) return

        sigRef.current = newSig
        setState({ kind: 'ready', items, sample: false })
      } catch (err: unknown) {
        if (!mountedRef.current) return
        if ((err as { name?: string })?.name === 'AbortError') return
        // Initial load failure → show error state so the user can retry.
        // Background poll failure → silent; next poll will try again.
        if (isInitial) setState({ kind: 'error' })
      }
    },
    // suppressRef is a stable ref object — changing its `.current` doesn't
    // cause doFetch to be recreated, which is intentional.
    [token, devBypass, suppressRef],
  )

  // ── Initial load ─────────────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true
    sigRef.current = ''
    setState({ kind: 'loading' })
    void doFetch(true)
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()
    }
  }, [doFetch])

  // ── Background polling ────────────────────────────────────────────────────
  useEffect(() => {
    const id = setInterval(() => void doFetch(false), POLL_MS)
    return () => clearInterval(id)
  }, [doFetch])

  // ── Focus + visibility refetch ────────────────────────────────────────────
  // Debounced so rapid focus/blur cycling doesn't hammer the API.
  useEffect(() => {
    let debounce: ReturnType<typeof setTimeout> | null = null
    const trigger = () => {
      if (debounce) clearTimeout(debounce)
      debounce = setTimeout(() => void doFetch(false), FOCUS_DEBOUNCE_MS)
    }
    const onVisibility = () => {
      if (document.visibilityState === 'visible') trigger()
    }
    window.addEventListener('focus', trigger)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('focus', trigger)
      document.removeEventListener('visibilitychange', onVisibility)
      if (debounce) clearTimeout(debounce)
    }
  }, [doFetch])

  // refetch is the "Try again" handler for the error state — it shows loading
  // and treats the result as an initial load (never silently discarded).
  const refetch = useCallback(() => {
    sigRef.current = ''
    setState({ kind: 'loading' })
    void doFetch(true)
  }, [doFetch])

  return { state, refetch }
}
