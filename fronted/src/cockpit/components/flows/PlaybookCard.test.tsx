import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PlaybookCard } from './PlaybookCard'
import type { FlowSummary } from '../../lib/flows'

const BASE: FlowSummary = {
  id: 'f1',
  slug: 'cooling-lead-nudge',
  version: 1,
  status: 'published',
  live: false,
  name: 'Cooling lead → notify operator',
  description: null,
  trigger: {
    type: 'state',
    predicate: {
      all: [
        { field: 'stage', op: 'in', value: ['qualified', 'captured'] },
        { field: 'hours_since_last', op: 'gte', value: 36 },
      ],
    },
  },
  graph: {
    nodes: [
      { id: 't1', type: 'trigger' },
      { id: 'n1', type: 'action:notify_operator', body: 'check the queue' },
    ],
    edges: [{ from: 't1', to: 'n1' }],
  },
  created_at: null,
  published_at: null,
  run_count: 34,
  last_run_at: null,
}

const noop = () => {}
const renderCard = (flow: FlowSummary, over: Partial<Parameters<typeof PlaybookCard>[0]> = {}) =>
  render(
    <PlaybookCard
      flow={flow} selected={false} busy={false}
      onSelect={noop} onEdit={noop} onLive={noop} onStatus={noop}
      {...over}
    />,
  )

describe('PlaybookCard', () => {
  it('reads as a sentence: when-phrase + step chips', () => {
    renderCard(BASE)
    expect(screen.getByText('a lead in qualified or captured has been quiet for 36+ hours')).toBeInTheDocument()
    expect(screen.getByText('notify Erez')).toBeInTheDocument()
  })

  it('a published flow shows the shadow/live switch, not a status chip', () => {
    renderCard(BASE)
    const sw = screen.getByRole('switch')
    expect(sw).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('shadow')).toBeInTheDocument()
  })

  it('flipping the switch requests the opposite live state without selecting the card', async () => {
    const onLive = vi.fn()
    const onSelect = vi.fn()
    renderCard(BASE, { onLive, onSelect })
    await userEvent.click(screen.getByRole('switch'))
    expect(onLive).toHaveBeenCalledWith(true)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('a draft shows the draft chip and an Edit action', () => {
    renderCard({ ...BASE, status: 'draft' })
    expect(screen.getByText('draft')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).toBeNull()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
  })

  it('a published flow offers Tune (fork), never direct Edit', () => {
    renderCard(BASE)
    expect(screen.getByRole('button', { name: 'Tune' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
  })

  it('degrades a branching graph to the custom-logic chip', () => {
    renderCard({
      ...BASE,
      graph: {
        nodes: [
          { id: 't1', type: 'trigger' },
          { id: 'c1', type: 'condition', predicate: {} },
          { id: 'a', type: 'action:add_note', note: 'x' },
          { id: 'b', type: 'action:add_note', note: 'y' },
        ],
        edges: [
          { from: 't1', to: 'c1' },
          { from: 'c1', to: 'a', when: 'true' },
          { from: 'c1', to: 'b', when: 'false' },
        ],
      },
    })
    expect(screen.getByText('custom branching logic')).toBeInTheDocument()
  })

  it('clicking the card selects it', async () => {
    const onSelect = vi.fn()
    renderCard(BASE, { onSelect })
    await userEvent.click(screen.getByRole('button', { name: /Cooling lead/ }))
    expect(onSelect).toHaveBeenCalledOnce()
  })
})
