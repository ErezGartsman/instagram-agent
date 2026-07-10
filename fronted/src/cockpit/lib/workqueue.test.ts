import { describe, expect, it } from 'vitest'
import { rankQueue, type QueueItem } from './workqueue'

function item(id: string, confidence: number): QueueItem {
  return {
    id, person_id: id, name: id, initials: '—', channel: null, handle: null,
    teaser: '', action: '', confidence, reason: '',
    last_contacted: null, first_seen_at: null, timeline: [],
    essence: null, goal: null, tension: null,
  }
}

describe('rankQueue', () => {
  it('sorts by confidence descending', () => {
    const ranked = rankQueue([item('low', 20), item('high', 90), item('mid', 55)])
    expect(ranked.map((i) => i.id)).toEqual(['high', 'mid', 'low'])
  })

  it('does not mutate the input array', () => {
    const input = [item('a', 10), item('b', 90)]
    const original = [...input]
    rankQueue(input)
    expect(input).toEqual(original)
  })

  it('is a no-op on an empty queue', () => {
    expect(rankQueue([])).toEqual([])
  })
})
