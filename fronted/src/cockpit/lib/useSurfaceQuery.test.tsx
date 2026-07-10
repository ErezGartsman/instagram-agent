import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useSurfaceQuery } from './useSurfaceQuery'

// useSurfaceQuery is the enforcement mechanism behind the E1 four-state audit
// (SYSTEM_ELEVATION_PRD.md §A2/§A4) — every page's loading/error/empty/ready
// derivation funnels through here, so this hook earns direct coverage.

const mockAuth = vi.hoisted(() => ({ value: { session: null as { access_token: string } | null, devBypass: false } }))
vi.mock('../auth/AuthProvider', () => ({ useAuth: () => mockAuth.value }))

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useSurfaceQuery', () => {
  it('returns ready+sample immediately under dev bypass, without calling the fetcher', () => {
    mockAuth.value = { session: null, devBypass: true }
    const fetcher = vi.fn()
    const { result } = renderHook(
      () => useSurfaceQuery({ queryKey: ['t1'], fetcher, sample: ['a', 'b'] }),
      { wrapper },
    )
    expect(result.current).toEqual({ kind: 'ready', data: ['a', 'b'], sample: true })
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('stays loading while there is no token yet (query disabled)', () => {
    mockAuth.value = { session: null, devBypass: false }
    const { result } = renderHook(
      () => useSurfaceQuery({ queryKey: ['t2'], fetcher: vi.fn(), sample: [] }),
      { wrapper },
    )
    expect(result.current).toEqual({ kind: 'loading' })
  })

  it('transitions loading -> ready with the fetched data', async () => {
    mockAuth.value = { session: { access_token: 'tok' }, devBypass: false }
    const fetcher = vi.fn().mockResolvedValue(['x', 'y'])
    const { result } = renderHook(
      () => useSurfaceQuery({ queryKey: ['t3'], fetcher, sample: [] }),
      { wrapper },
    )
    expect(result.current.kind).toBe('loading')
    await waitFor(() => expect(result.current.kind).toBe('ready'))
    expect(result.current).toMatchObject({ kind: 'ready', data: ['x', 'y'], sample: false })
    expect(fetcher).toHaveBeenCalledWith('tok', expect.anything())
  })

  it('transitions loading -> error with a working retry() on fetcher failure', async () => {
    mockAuth.value = { session: { access_token: 'tok' }, devBypass: false }
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(['recovered'])
    const { result } = renderHook(
      () => useSurfaceQuery({ queryKey: ['t4'], fetcher, sample: [] }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.kind).toBe('error'))
    expect(result.current.kind === 'error' && typeof result.current.retry).toBe('function')

    if (result.current.kind === 'error') result.current.retry()
    await waitFor(() => expect(result.current.kind).toBe('ready'))
    expect(result.current).toMatchObject({ kind: 'ready', data: ['recovered'] })
  })

  it('renders empty when isEmpty(data) is true — a domain state, not an error', async () => {
    mockAuth.value = { session: { access_token: 'tok' }, devBypass: false }
    const fetcher = vi.fn().mockResolvedValue([])
    const { result } = renderHook(
      () =>
        useSurfaceQuery({
          queryKey: ['t5'],
          fetcher,
          sample: [],
          isEmpty: (data: unknown[]) => data.length === 0,
        }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.kind).toBe('empty'))
  })
})
