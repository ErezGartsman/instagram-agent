import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from './Badge'

describe('Badge', () => {
  it('renders its children', () => {
    render(<Badge>5</Badge>)
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('mono applies tabular-nums for numeral alignment', () => {
    render(<Badge mono>42</Badge>)
    expect(screen.getByText('42')).toHaveClass('tabular-nums')
  })

  it('tone="danger" carries the danger text color, not the neutral default', () => {
    render(<Badge tone="danger">Breach</Badge>)
    const el = screen.getByText('Breach')
    expect(el).toHaveClass('text-danger')
    expect(el).not.toHaveClass('text-muted')
  })
})
