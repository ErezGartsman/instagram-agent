import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Link } from 'react-router-dom'
import { Button } from './Button'

describe('Button', () => {
  it('renders its label and fires onClick', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Save</Button>)
    const btn = screen.getByRole('button', { name: 'Save' })
    await userEvent.click(btn)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('defaults to type="button" so it never submits a wrapping form', () => {
    render(<Button>Cancel</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })

  it('disabled buttons do not fire onClick', async () => {
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Send</Button>)
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('asChild renders the child element (e.g. a router Link) instead of a <button>', () => {
    render(
      <MemoryRouter>
        <Button asChild>
          <Link to="/app/queue">Open the Work Queue</Link>
        </Button>
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: 'Open the Work Queue' })
    expect(link).toHaveAttribute('href', '/app/queue')
    // The DOM must stay valid: no nested <button><a> — asChild merges props
    // onto the single rendered element instead of wrapping it.
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
