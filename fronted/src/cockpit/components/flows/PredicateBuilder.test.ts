import { describe, expect, it } from 'vitest'
import { parsePredicate, buildPredicate } from './PredicateBuilder'

describe('parsePredicate', () => {
  it('parses the canonical cooling predicate', () => {
    const model = parsePredicate({
      all: [
        { field: 'stage', op: 'in', value: ['qualified', 'captured'] },
        { field: 'hours_since_last', op: 'gte', value: 36 },
      ],
    })
    expect(model).toEqual({ stages: ['qualified', 'captured'], hours: 36 })
  })

  it('parses a single stage eq clause', () => {
    expect(parsePredicate({ field: 'stage', op: 'eq', value: 'briefed' }))
      .toEqual({ stages: ['briefed'], hours: null })
  })

  it('returns null for a predicate it cannot safely edit', () => {
    expect(parsePredicate({ field: 'channel', op: 'eq', value: 'whatsapp' })).toBeNull()
    expect(parsePredicate({ all: [{ field: 'urgency', op: 'gte', value: 8 }] })).toBeNull()
  })

  it('empty predicate → empty model (a fresh state trigger)', () => {
    expect(parsePredicate({})).toEqual({ stages: [], hours: null })
  })
})

describe('buildPredicate', () => {
  it('round-trips with parsePredicate', () => {
    const model = { stages: ['qualified', 'briefed'], hours: 48 }
    expect(parsePredicate(buildPredicate(model))).toEqual(model)
  })

  it('a single clause is emitted bare (no redundant all wrapper)', () => {
    expect(buildPredicate({ stages: ['qualified'], hours: null }))
      .toEqual({ field: 'stage', op: 'in', value: ['qualified'] })
  })

  it('two clauses are wrapped in all', () => {
    const p = buildPredicate({ stages: ['qualified'], hours: 24 })
    expect(p.all).toHaveLength(2)
  })
})
