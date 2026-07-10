import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FlowCanvas } from './FlowCanvas'
import { runPath } from '../../lib/flowLayout'
import type { FlowGraph } from '../../lib/flows'

const GRAPH: FlowGraph = {
  nodes: [
    { id: 't1', type: 'trigger' },
    { id: 'n1', type: 'action:notify_operator', body: 'check on this lead' },
  ],
  edges: [{ from: 't1', to: 'n1' }],
}

describe('FlowCanvas', () => {
  it('renders every node with its type label in definition mode', () => {
    render(<FlowCanvas graph={GRAPH} />)
    expect(screen.getByText('Trigger')).toBeInTheDocument()
    expect(screen.getByText('Notify Erez')).toBeInTheDocument()
  })

  it('shows a node caption from its config', () => {
    render(<FlowCanvas graph={GRAPH} />)
    expect(screen.getByText('check on this lead')).toBeInTheDocument()
  })

  it('in replay mode labels each visited node with its step status', () => {
    // A run where the notify step was blocked → the node reads "Blocked".
    const visited = runPath([
      { node_id: 't1', status: 'success' },
      { node_id: 'n1', status: 'blocked' },
    ])
    render(<FlowCanvas graph={GRAPH} visited={visited} />)
    expect(screen.getByText('Ran')).toBeInTheDocument()      // trigger: success → "Ran"
    expect(screen.getByText('Blocked')).toBeInTheDocument()  // notify: blocked
  })

  it('a shadow step reads "Would run" (the shadow-mode signature)', () => {
    const visited = runPath([
      { node_id: 't1', status: 'success' },
      { node_id: 'n1', status: 'shadow' },
    ])
    render(<FlowCanvas graph={GRAPH} visited={visited} />)
    expect(screen.getByText('Would run')).toBeInTheDocument()
  })

  it('clicking a node fires onNodeClick with its id', async () => {
    const onNodeClick = vi.fn()
    render(<FlowCanvas graph={GRAPH} onNodeClick={onNodeClick} />)
    await userEvent.click(screen.getByRole('button', { name: /Notify Erez/ }))
    expect(onNodeClick).toHaveBeenCalledWith('n1')
  })
})
