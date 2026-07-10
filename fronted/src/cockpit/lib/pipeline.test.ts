import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { relativeTime } from './pipeline'

describe('relativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-10T12:00:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('returns "—" for null', () => {
    expect(relativeTime(null)).toBe('—')
  })

  it('returns "—" for an unparseable string', () => {
    expect(relativeTime('not-a-date')).toBe('—')
  })

  it('returns "now" for under a minute ago', () => {
    expect(relativeTime(new Date('2026-07-10T11:59:45Z').toISOString())).toBe('now')
  })

  it('formats minutes', () => {
    expect(relativeTime(new Date('2026-07-10T11:45:00Z').toISOString())).toBe('15m')
  })

  it('formats hours', () => {
    expect(relativeTime(new Date('2026-07-10T09:00:00Z').toISOString())).toBe('3h')
  })

  it('formats days', () => {
    expect(relativeTime(new Date('2026-07-08T12:00:00Z').toISOString())).toBe('2d')
  })

  it('formats weeks', () => {
    expect(relativeTime(new Date('2026-06-26T12:00:00Z').toISOString())).toBe('2w')
  })
})
