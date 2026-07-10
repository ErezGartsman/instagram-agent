import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { GlassPanel } from './GlassPanel'

describe('GlassPanel', () => {
  it('depth="section" carries backdrop-blur — the ONLY depth allowed to blur (CLAUDE.md §4: never on list rows)', () => {
    const { container } = render(<GlassPanel depth="section">content</GlassPanel>)
    expect(container.firstChild).toHaveClass('backdrop-blur-xl')
  })

  it('depth="card" (the list-row material) never carries backdrop-blur', () => {
    const { container } = render(<GlassPanel depth="card">content</GlassPanel>)
    expect(container.firstChild).not.toHaveClass('backdrop-blur-xl')
  })

  it('depth="inset" has no border — a borderless nested well', () => {
    const { container } = render(<GlassPanel depth="inset">content</GlassPanel>)
    expect(container.firstChild).not.toHaveClass('border')
  })
})
