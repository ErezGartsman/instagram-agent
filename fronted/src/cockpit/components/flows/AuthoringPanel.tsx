import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import { PredicateBuilder, buildPredicate } from './PredicateBuilder'
import { nodeMeta, ADDABLE_NODE_TYPES, type FlowGraph, type FlowNodeDef, type FlowTrigger } from '../../lib/flows'
import { addNode, removeNode, updateNode, connect } from '../../lib/graphEdit'
import { asTone, TONE_TEXT, TONE_TINT } from './tone'

/**
 * AuthoringPanel — the right rail in edit mode (F3). Trigger editor · node
 * palette · the selected node's config + connections + delete. Every gesture
 * routes through the pure lib/graphEdit + PredicateBuilder, so this component
 * is thin glue over tested logic.
 */
const EVENT_KINDS = [
  'booking_canceled', 'booking_created', 'captured', 'qualified',
  'outreach_click', 'contacted', 'stage_change',
]
const STAGES = ['engaged', 'qualified', 'captured', 'briefed', 'booked']

export function AuthoringPanel({
  name,
  description,
  trigger,
  graph,
  selectedNode,
  onMeta,
  onTrigger,
  onGraph,
  onSelectNode,
}: {
  name: string
  description: string | null
  trigger: FlowTrigger
  graph: FlowGraph
  selectedNode: string | null
  onMeta: (patch: { name?: string; description?: string }) => void
  onTrigger: (t: FlowTrigger) => void
  onGraph: (g: FlowGraph) => void
  onSelectNode: (id: string | null) => void
}) {
  const node = graph.nodes.find((n) => n.id === selectedNode) ?? null
  const anchorId = selectedNode && node?.type !== 'trigger'
    ? selectedNode
    : lastNodeId(graph)

  return (
    <aside className="flex h-full w-[384px] shrink-0 flex-col overflow-y-auto border-l border-line">
      {/* Flow meta */}
      <div className="border-b border-line px-5 py-4">
        <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Flow</div>
        <input
          value={name}
          onChange={(e) => onMeta({ name: e.target.value })}
          placeholder="Flow name"
          className="w-full bg-transparent text-base font-medium text-ink outline-none placeholder:text-faint"
        />
        <textarea
          value={description ?? ''}
          onChange={(e) => onMeta({ description: e.target.value })}
          placeholder="What does this flow do?"
          rows={2}
          className="mt-1 w-full resize-none bg-transparent text-xs leading-relaxed text-muted outline-none placeholder:text-faint"
        />
      </div>

      {/* Trigger editor */}
      <div className="border-b border-line px-5 py-4">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">When it runs</div>
        <div className="mb-3 inline-flex overflow-hidden rounded-control border border-line">
          {(['event', 'state'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => onTrigger(t === 'event'
                ? { type: 'event', kind: trigger.kind ?? 'booking_canceled' }
                : { type: 'state', predicate: trigger.predicate ?? buildPredicate({ stages: ['qualified'], hours: 36 }) })}
              className={`px-3 py-1.5 text-[11px] transition-colors ${
                trigger.type === t ? 'bg-accent/15 text-accent' : 'text-muted hover:text-ink'
              }`}
            >
              {t === 'event' ? 'On an event' : 'On a state'}
            </button>
          ))}
        </div>

        {trigger.type === 'event' ? (
          <label className="block">
            <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-faint">Event</span>
            <select
              value={trigger.kind ?? ''}
              onChange={(e) => onTrigger({ type: 'event', kind: e.target.value })}
              className="w-full rounded-control border border-line bg-bg/60 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent/40"
            >
              {EVENT_KINDS.map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
            </select>
          </label>
        ) : (
          <PredicateBuilder predicate={trigger.predicate} onChange={(p) => onTrigger({ type: 'state', predicate: p })} />
        )}
      </div>

      {/* Node palette */}
      <div className="border-b border-line px-5 py-4">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
          Add step {anchorId && <span className="text-faint/60">after {shortLabel(graph, anchorId)}</span>}
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          {ADDABLE_NODE_TYPES.map((type) => {
            const meta = nodeMeta(type)
            return (
              <button
                key={type}
                type="button"
                onClick={() => {
                  if (!anchorId) return
                  const { graph: g, id } = addNode(graph, type, anchorId)
                  onGraph(g)
                  onSelectNode(id)
                }}
                className="flex items-center gap-2 rounded-control border border-line px-2.5 py-2 text-left text-[11px] text-muted transition-colors hover:border-[rgba(148,186,255,0.25)] hover:text-ink"
              >
                <span className={`grid h-5 w-5 shrink-0 place-items-center rounded ${TONE_TINT[asTone(meta.tone)]} ${TONE_TEXT[asTone(meta.tone)]}`}>
                  <Icon name={meta.icon as IconName} size={11} />
                </span>
                <span className="truncate">{meta.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Selected node config */}
      <div className="min-h-0 flex-1 px-5 py-4">
        {node ? (
          <NodeConfig
            node={node}
            graph={graph}
            onGraph={onGraph}
            onSelectNode={onSelectNode}
          />
        ) : (
          <p className="text-center text-xs text-faint">Select a node to configure it, or drag from a node&rsquo;s port to connect.</p>
        )}
      </div>
    </aside>
  )
}

function NodeConfig({
  node, graph, onGraph, onSelectNode,
}: {
  node: FlowNodeDef
  graph: FlowGraph
  onGraph: (g: FlowGraph) => void
  onSelectNode: (id: string | null) => void
}) {
  const meta = nodeMeta(node.type)
  const patch = (p: Partial<FlowNodeDef>) => onGraph(updateNode(graph, node.id, p))
  const others = graph.nodes.filter((n) => n.id !== node.id)
  const isCondition = node.type === 'condition'

  const currentTarget = (when?: 'true' | 'false') =>
    graph.edges.find((e) => e.from === node.id && (e.when ?? undefined) === when)?.to ?? ''

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <span className={`grid h-6 w-6 place-items-center rounded-control ${TONE_TINT[asTone(meta.tone)]} ${TONE_TEXT[asTone(meta.tone)]}`}>
          <Icon name={meta.icon as IconName} size={13} />
        </span>
        <span className="text-sm font-medium text-ink">{meta.label}</span>
        {node.type !== 'trigger' && (
          <button
            type="button"
            onClick={() => { onGraph(removeNode(graph, node.id)); onSelectNode(null) }}
            className="ml-auto inline-flex items-center gap-1 rounded-control border border-line px-2 py-1 text-[11px] text-muted transition-colors hover:border-danger/40 hover:text-danger"
          >
            <Icon name="x" size={11} /> Delete
          </button>
        )}
      </div>

      {/* Type-specific config */}
      {(node.type === 'action:send_message' || node.type === 'action:notify_operator') && (
        <Field label="Message">
          <textarea
            value={node.body ?? ''}
            onChange={(e) => patch({ body: e.target.value })}
            rows={4}
            dir="auto"
            placeholder="What it sends…"
            className="w-full resize-none rounded-control border border-line bg-bg/60 px-2.5 py-2 text-xs leading-relaxed text-ink outline-none focus:border-accent/40"
          />
        </Field>
      )}
      {node.type === 'wait' && (
        <Field label="Wait for (hours)">
          <input
            type="number" min={1}
            value={node.hours ?? ''}
            onChange={(e) => patch({ hours: Math.max(1, Number(e.target.value) || 1) })}
            className="w-24 rounded-control border border-line bg-bg/60 px-2 py-1.5 font-mono text-xs tabular-nums text-ink outline-none focus:border-accent/40"
          />
        </Field>
      )}
      {node.type === 'action:advance_stage' && (
        <Field label="Advance to">
          <select
            value={node.to_stage ?? ''}
            onChange={(e) => patch({ to_stage: e.target.value })}
            className="w-full rounded-control border border-line bg-bg/60 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent/40"
          >
            {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
      )}
      {node.type === 'action:add_note' && (
        <Field label="Note">
          <input value={node.note ?? ''} onChange={(e) => patch({ note: e.target.value })}
            className="w-full rounded-control border border-line bg-bg/60 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent/40" />
        </Field>
      )}
      {node.type === 'action:set_flag' && (
        <Field label="Flag">
          <input value={node.flag ?? ''} onChange={(e) => patch({ flag: e.target.value })}
            className="w-full rounded-control border border-line bg-bg/60 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent/40" />
        </Field>
      )}
      {isCondition && (
        <Field label="Condition">
          <PredicateBuilder predicate={node.predicate} onChange={(p) => patch({ predicate: p })} />
        </Field>
      )}

      {/* Connections */}
      {node.type !== 'trigger' || others.length > 0 ? null : null}
      <div className="mt-4 border-t border-line pt-3">
        <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-faint">Connects to</div>
        {isCondition ? (
          <div className="space-y-2">
            <ConnectSelect label="if true" nodes={others} value={currentTarget('true')}
              onChange={(to) => onGraph(connect(graph, node.id, to, 'true'))} />
            <ConnectSelect label="if false" nodes={others} value={currentTarget('false')}
              onChange={(to) => onGraph(connect(graph, node.id, to, 'false'))} />
          </div>
        ) : (
          <ConnectSelect label="next" nodes={others} value={currentTarget()}
            onChange={(to) => onGraph(connect(graph, node.id, to))} />
        )}
        <p className="mt-2 text-[10px] text-faint">…or drag from this node&rsquo;s port on the canvas.</p>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-faint">{label}</div>
      {children}
    </div>
  )
}

function ConnectSelect({
  label, nodes, value, onChange,
}: {
  label: string
  nodes: FlowNodeDef[]
  value: string
  onChange: (to: string) => void
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="w-14 shrink-0 font-mono text-[10px] text-faint">{label}</span>
      <select
        value={value}
        onChange={(e) => e.target.value && onChange(e.target.value)}
        className="min-w-0 flex-1 rounded-control border border-line bg-bg/60 px-2 py-1 text-xs text-ink outline-none focus:border-accent/40"
      >
        <option value="">— end here —</option>
        {nodes.map((n) => <option key={n.id} value={n.id}>{nodeMeta(n.type).label}</option>)}
      </select>
    </label>
  )
}

function lastNodeId(graph: FlowGraph): string | null {
  // The node with no outgoing edge (a leaf) is the natural append anchor.
  const withOut = new Set(graph.edges.map((e) => e.from))
  const leaf = graph.nodes.find((n) => !withOut.has(n.id) && n.type !== 'trigger')
  return leaf?.id ?? graph.nodes[graph.nodes.length - 1]?.id ?? null
}

function shortLabel(graph: FlowGraph, id: string): string {
  const n = graph.nodes.find((x) => x.id === id)
  return n ? nodeMeta(n.type).label.toLowerCase() : ''
}
