/**
 * http — the typed fetch seam for the cockpit (E0, SYSTEM_ELEVATION_PRD.md §A2).
 *
 * The old api.ts pattern swallowed every failure into an empty shape ([]/{}),
 * so the UI could not distinguish "no data" from "API down" — the silent-failure
 * defect named in the PRD audit. Everything that migrates onto TanStack Query
 * goes through apiFetch instead: failures THROW a typed ApiError, queries carry
 * them to the surface, and pages render an honest error state.
 *
 * E1 migrates the remaining api.ts wrappers onto this seam page by page.
 */
import { API_BASE } from './api'

export class ApiError extends Error {
  constructor(
    /** HTTP status, or 0 for a network-level failure. */
    readonly status: number,
    /** The path that failed, for logging/telemetry. */
    readonly endpoint: string,
    message?: string,
  ) {
    super(message ?? (status === 0 ? `network error on ${endpoint}` : `HTTP ${status} on ${endpoint}`))
    this.name = 'ApiError'
  }

  /** True for failures worth retrying (network blips, 5xx, 429). */
  get retryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500
  }
}

/** Authorized JSON fetch that throws ApiError on any failure. */
export async function apiFetch<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (e) {
    // AbortError must propagate untouched — TanStack Query cancels stale
    // queries via the signal and treats aborts specially, not as errors.
    if ((e as Error)?.name === 'AbortError') throw e
    throw new ApiError(0, path)
  }
  if (!res.ok) throw new ApiError(res.status, path)
  return (await res.json()) as T
}
