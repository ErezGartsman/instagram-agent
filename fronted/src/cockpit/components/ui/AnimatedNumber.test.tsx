import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { AnimatedNumber } from './AnimatedNumber'

describe('AnimatedNumber', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('shows the target value immediately on first render (no count-up from 0)', () => {
    render(<AnimatedNumber value={42} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('under prefers-reduced-motion, jumps straight to the new value on change', () => {
    // jsdom doesn't implement matchMedia at all — stub it rather than spy on
    // a method that doesn't exist here (real browsers always have it).
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true } as MediaQueryList))
    const { rerender } = render(<AnimatedNumber value={5} />)
    rerender(<AnimatedNumber value={9} />)
    expect(screen.getByText('9')).toBeInTheDocument()
  })

  it('applies the formatter to the displayed value', () => {
    render(<AnimatedNumber value={1200} formatter={(n) => `${(n / 1000).toFixed(1)}k`} />)
    expect(screen.getByText('1.2k')).toBeInTheDocument()
  })

  describe('with real timers', () => {
    beforeEach(() => vi.useRealTimers())

    it('eventually settles on the new value after a change (no reduced-motion)', async () => {
      const { rerender } = render(<AnimatedNumber value={0} />)
      rerender(<AnimatedNumber value={10} />)
      await waitFor(() => expect(screen.getByText('10')).toBeInTheDocument())
    })
  })
})
