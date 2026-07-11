import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SimulationDialog } from './SimulationDialog'
import type { SimulationReport } from '../../lib/flows'

const REPORT: SimulationReport = {
  window_days: 90,
  trigger_type: 'state',
  fires: 34,
  actions: { would_send: 28, would_notify: 0, advanced: 0, noted: 0, flagged: 0 },
  blocked: 6,
  blocked_by: { pressure_budget: 4, quiet_hours: 2 },
  sample: [
    { person_name: 'Maya Goren', at: new Date().toISOString(), outcome: 'blocked', reason: 'pressure_budget' },
    { person_name: 'Noa Levi', at: new Date().toISOString(), outcome: 'would_send', reason: null },
  ],
  notes: ['State trigger — cooling episodes reconstructed from the interaction log.'],
}

const noop = () => {}

describe('SimulationDialog', () => {
  it('shows the loading state while the sim runs', () => {
    render(<SimulationDialog report={null} loading onClose={noop} onPublish={noop} publishing={false} canPublish />)
    expect(screen.getByText(/Replaying 90 days/)).toBeInTheDocument()
  })

  it('renders the headline fire count', () => {
    render(<SimulationDialog report={REPORT} loading={false} onClose={noop} onPublish={noop} publishing={false} canPublish />)
    expect(screen.getByText('34')).toBeInTheDocument()
    expect(screen.getByText(/times this would have fired/)).toBeInTheDocument()
  })

  it('breaks down the blocked count by plain-language reason', () => {
    render(<SimulationDialog report={REPORT} loading={false} onClose={noop} onPublish={noop} publishing={false} canPublish />)
    expect(screen.getByText('Pressure budget')).toBeInTheDocument()
    expect(screen.getByText('Quiet hours')).toBeInTheDocument()
  })

  it('lists representative fires with the person name', () => {
    render(<SimulationDialog report={REPORT} loading={false} onClose={noop} onPublish={noop} publishing={false} canPublish />)
    expect(screen.getByText('Maya Goren')).toBeInTheDocument()
    expect(screen.getByText('Noa Levi')).toBeInTheDocument()
  })

  it('the Publish button appears only when canPublish, and fires onPublish', async () => {
    const onPublish = vi.fn()
    const { rerender } = render(
      <SimulationDialog report={REPORT} loading={false} onClose={noop} onPublish={onPublish} publishing={false} canPublish={false} />,
    )
    expect(screen.queryByRole('button', { name: /Publish flow/ })).toBeNull()

    rerender(<SimulationDialog report={REPORT} loading={false} onClose={noop} onPublish={onPublish} publishing={false} canPublish />)
    await userEvent.click(screen.getByRole('button', { name: /Publish flow/ }))
    expect(onPublish).toHaveBeenCalledOnce()
  })

  it('surfaces the honesty note about reconstruction', () => {
    render(<SimulationDialog report={REPORT} loading={false} onClose={noop} onPublish={noop} publishing={false} canPublish />)
    expect(screen.getByText(/cooling episodes reconstructed/)).toBeInTheDocument()
  })
})
