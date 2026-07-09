import { useCallback, useEffect, useRef, useState } from 'react'
import type { MutableRefObject } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchQueue, rankQueue, SAMPLE_QUEUE, type QueueItem } from './workqueue'
import { queryKeys } from './queryClient'
import { useQueueRealtimeInvalidation } from './realtime'

// ── Constants ──────────────────────────────────────────────────────────────
const POLL_MS = 30_000   // fallback poll — Realtime invalidation is the norm
/** Minimum confidence score (0-100) for a lead to trigger a hot-lead alert. */
export const HOT_LEAD_THRESHOLD = 70

// ── Signature ──────────────────────────────────────────────────────────────
// Cheap string identity for a queue snapshot. If this is unchanged we skip
// setState entirely — zero re-renders on the common "nothing happened" poll.
function queueSig(items: QueueItem[]): string {
  return items.map((i) => `${i.id}:${i.confidence}`).join('|')
}

// ── Types ──────────────────────────────────────────────────────────────────
export type QueueDataState =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; items: QueueItem[]; sample: boolean }

/**
 * Work Queue data on the TanStack Query spine (E0 rewrite — the hand-rolled
 * polling/abort/focus machinery this hook used to carry is now the query
 * layer's job; SYSTEM_ELEVATION_PRD.md §A2). The public contract is unchanged:
 *
 *   1. Signature-diff guard — consumers re-render only when the queue
 *      genuinely changed.
 *   2. Pending-action suppression — while `suppressRef.current` is true
 *      (set by the Board during an optimistic action) fresh server data is
 *      held back; the next update after release applies it.
 *   3. Liveness — Realtime invalidation on agent_runs (push), plus the 30s
 *      poll and focus refetch as fallbacks.
 *
 * Errors: an initial-load failure surfaces `{kind:'error'}` (after the query
 * layer's retries); background failures keep the last good snapshot, exactly
 * like the old behavior — except they now also mark the query stale so the
 * next focus heals it.
 *
 * @param token       Supabase access token (null while loading/signed out).
 * @param devBypass   True in local dev — uses SAMPLE_QUEUE, no API call.
 * @param suppressRef Mutable ref owned by WorkQueuePage, written by Board.
 */
export function useQueueData(
  token: string | null,
  devBypass: boolean,
  suppressRef: MutableRefObject<boolean>,
  /** Called with the highest-confidence new lead whenever an update surfaces
   *  an item above HOT_LEAD_THRESHOLD that wasn't previously seen. Never fires
   *  on the initial load. */
  onHotLead?: (item: QueueItem) => void,
): {
  state: QueueDataState
  refetch: () => void
} {
  // Accepted snapshot — what consumers actually see. Server data only lands
  // here through the accept-effect below (suppression + signature gates).
  const [accepted, setAccepted] = useState<QueueItem[] | null>(null)

  const sigRef      = useRef('')
  const initialRef  = useRef(true)
  const seenIdsRef  = useRef<Set<string>>(new Set())
  const onHotLeadRef = useRef(onHotLead)
  onHotLeadRef.current = onHotLead

  const enabled = !!token && !devBypass
  useQueueRealtimeInvalidation(enabled)

  const query = useQuery({
    queryKey: queryKeys.queue,
    queryFn: async ({ signal }) => rankQueue(await fetchQueue(token!, signal)),
    enabled,
    refetchInterval: POLL_MS,
    staleTime: 10_000,
  })

  // ── Accept-effect: server data → accepted snapshot ───────────────────────
  useEffect(() => {
    const items = query.data
    if (!enabled || !items) return
    if (!initialRef.current && suppressRef.current) return  // yield to action loop

    const newSig = queueSig(items)
    if (newSig === sigRef.current) return

    if (initialRef.current) {
      // Populate the seen-ID set without notification — these items were
      // already in the queue when the cockpit opened.
      seenIdsRef.current = new Set(items.map((i) => i.id))
      initialRef.current = false
    } else {
      // Hot-lead detection: new items above threshold that weren't seen before.
      if (seenIdsRef.current.size > 0 && onHotLeadRef.current) {
        const newHot = items
          .filter((i) => !seenIdsRef.current.has(i.id) && i.confidence >= HOT_LEAD_THRESHOLD)
          .sort((a, b) => b.confidence - a.confidence)
        if (newHot.length > 0) onHotLeadRef.current(newHot[0])
      }
      items.forEach((i) => seenIdsRef.current.add(i.id))
    }

    sigRef.current = newSig
    setAccepted(items)
    // query.data is structurally shared — identical fetches keep the same
    // reference, so this effect is already skipped on "nothing happened" polls.
  }, [query.data, enabled, suppressRef])

  // refetch is the "Try again" handler for the error state.
  const queryRefetch = query.refetch
  const refetch = useCallback(() => {
    void queryRefetch()
  }, [queryRefetch])

  // ── State derivation (contract-identical to the pre-E0 hook) ─────────────
  let state: QueueDataState
  if (devBypass) {
    state = { kind: 'ready', items: rankQueue(SAMPLE_QUEUE), sample: true }
  } else if (accepted) {
    state = { kind: 'ready', items: accepted, sample: false }
  } else if (query.isError && !query.isFetching) {
    state = { kind: 'error' }
  } else {
    state = { kind: 'loading' }
  }

  return { state, refetch }
}
