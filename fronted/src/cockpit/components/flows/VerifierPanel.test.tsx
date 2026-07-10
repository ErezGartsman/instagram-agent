import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { VerifierPanel } from './VerifierPanel'
import type { Verification } from '../../lib/flows'

const REJECT: Verification = {
  decision: 'reject',
  verdicts: [
    { verifier: 'staleness', decision: 'reject', reason: 'stale_trigger', detail: 'trigger no longer holds' },
    { verifier: 'duplicate_content', decision: 'approve' },
    { verifier: 'upcoming_booking', decision: 'approve' },
    { verifier: 'recent_inbound', decision: 'approve' },
    { verifier: 'circuit_breaker', decision: 'approve' },
  ],
  blocking: { verifier: 'staleness', decision: 'reject', reason: 'stale_trigger', detail: 'trigger no longer holds' },
}

const APPROVE: Verification = {
  decision: 'approve',
  verdicts: [
    { verifier: 'staleness', decision: 'approve' },
    { verifier: 'duplicate_content', decision: 'approve' },
    { verifier: 'upcoming_booking', decision: 'approve' },
    { verifier: 'recent_inbound', decision: 'approve' },
    { verifier: 'circuit_breaker', decision: 'approve' },
  ],
}

const DEFER: Verification = {
  decision: 'defer',
  verdicts: [
    { verifier: 'recent_inbound', decision: 'defer', reason: 'recent_inbound_activity', detail: 'inbound within 2h', defer_hours: 2 },
  ],
  blocking: { verifier: 'recent_inbound', decision: 'defer', reason: 'recent_inbound_activity', detail: 'inbound within 2h', defer_hours: 2 },
}

describe('VerifierPanel', () => {
  it('leads with the aggregate blocked verdict', () => {
    render(<VerifierPanel verification={REJECT} />)
    expect(screen.getByText('Blocked by the panel')).toBeInTheDocument()
  })

  it('surfaces the blocking verifier by its plain-language name and detail', () => {
    render(<VerifierPanel verification={REJECT} />)
    expect(screen.getByText('Still relevant?')).toBeInTheDocument()
    expect(screen.getByText('trigger no longer holds')).toBeInTheDocument()
  })

  it('shows every one of the five verifiers (blocking + the rest)', () => {
    render(<VerifierPanel verification={REJECT} />)
    // blocking one is pulled out; the other four render as quiet rows.
    expect(screen.getByText('Not a repeat?')).toBeInTheDocument()
    expect(screen.getByText('No booking already?')).toBeInTheDocument()
    expect(screen.getByText('Not mid-conversation?')).toBeInTheDocument()
    expect(screen.getByText('Pattern not failing?')).toBeInTheDocument()
  })

  it('renders a clean approval with no blocking row', () => {
    render(<VerifierPanel verification={APPROVE} />)
    expect(screen.getByText('Cleared by the panel')).toBeInTheDocument()
    expect(screen.getByText(/all five reviewers approved/)).toBeInTheDocument()
  })

  it('shows the retry backoff for a defer', () => {
    render(<VerifierPanel verification={DEFER} />)
    expect(screen.getByText('Deferred by the panel')).toBeInTheDocument()
    expect(screen.getByText('retry in 2h')).toBeInTheDocument()
  })

  it('does not leak raw snake_case verifier identifiers to the operator', () => {
    const { container } = render(<VerifierPanel verification={REJECT} />)
    expect(within(container).queryByText(/circuit_breaker|recent_inbound/)).toBeNull()
  })
})
