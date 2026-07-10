/**
 * useSurfaceQuery — one hook, the whole four-state lifecycle
 * (E1, SYSTEM_ELEVATION_PRD.md §A2 + §A4).
 *
 * Every read surface in the cockpit renders exactly four honest states:
 * loading (page-shaped skeleton) · error (authored, with retry) · empty
 * (authored, with next action) · ready. Before E1 each page hand-rolled the
 * lifecycle with useEffect + AbortController + retry nonces; this hook puts
 * it on the TanStack spine and hands pages a closed union they must exhaust —
 * TypeScript itself enforces the four-state audit.
 *
 * Empty is the caller's judgment (isEmpty predicate) because only the page
 * knows what "nothing here" means for its shape ([] vs {stages:[…,count:0]}).
 */
import { useQuery, type QueryKey } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthProvider'

export type SurfaceState<T> =
  | { kind: 'loading' }
  | { kind: 'error'; retry: () => void }
  | { kind: 'empty' }
  | { kind: 'ready'; data: T; sample: boolean }

export function useSurfaceQuery<T>(opts: {
  queryKey: QueryKey
  fetcher: (token: string, signal: AbortSignal) => Promise<T>
  /** Dev-bypass stand-in (dead-code-eliminated sample constants). */
  sample: T
  /** When true for the fetched data, the surface renders its authored empty
   *  state. Defaults to "never empty" — pages opt in deliberately. */
  isEmpty?: (data: T) => boolean
  /** Optional refetch interval for live surfaces (ms). */
  refetchInterval?: number
}): SurfaceState<T> {
  const { session, devBypass } = useAuth()
  const token = session?.access_token ?? null

  const query = useQuery({
    queryKey: opts.queryKey,
    queryFn: ({ signal }) => opts.fetcher(token!, signal),
    enabled: !!token && !devBypass,
    refetchInterval: opts.refetchInterval,
  })

  if (devBypass) return { kind: 'ready', data: opts.sample, sample: true }
  if (query.data !== undefined) {
    if (opts.isEmpty?.(query.data)) return { kind: 'empty' }
    return { kind: 'ready', data: query.data, sample: false }
  }
  if (query.isError && !query.isFetching) {
    return { kind: 'error', retry: () => void query.refetch() }
  }
  return { kind: 'loading' }
}
