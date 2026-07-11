import { useRef, useState } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import {
  nodeMeta, nodeCaption, STEP_STATUS_LABEL, STEP_STATUS_TONE,
  type FlowGraph, type StepStatus,
} from '../../lib/flows'
import { layoutFlow, activeEdges, NODE_W, NODE_H } from '../../lib/flowLayout'
import { asTone, TONE_TEXT, TONE_BORDER, TONE_TINT, TONE_GLOW, TONE_STROKE } from './tone'

/**
 * FlowCanvas — the bespoke node graph (F2/F3). SVG layer for the bezier edges,
 * absolutely-positioned glass cards for the nodes, on a dotted node-editor
 * grid. Three modes:
 *   definition — neutral glass, the flow's shape at rest.
 *   replay     — a `visited` map (node_id → step status) lights the path the
 *                selected run took; unvisited nodes dim, traversed edges carry
 *                flowing current, the parked node breathes.
 *   editable   — (F3) each node gets an output PORT; drag from a port to
 *                another node to wire a connection. Positions stay
 *                auto-laid-out (the layout is the craft) — you shape the
 *                graph, not pixel positions.
 *
 * Pure presentation: layout is computed by the tested lib/flowLayout.
 */
export function FlowCanvas({
  graph,
  visited,
  parkedNode,
  selectedNode,
  onNodeClick,
  editable = false,
  onConnect,
}: {
  graph: FlowGraph
  /** Present in replay mode: node_id → the step status it reached. */
  visited?: Map<string, string>
  /** The node a waiting run is parked at (breathes). */
  parkedNode?: string | null
  selectedNode?: string | null
  onNodeClick?: (nodeId: string) => void
  editable?: boolean
  /** Edit mode: a drag from `from`'s port dropped on `to`. */
  onConnect?: (from: string, to: string) => void
}) {
  const layout = layoutFlow(graph)
  const replay = !!visited
  const active = replay ? activeEdges(layout.edges, visited!) : new Set<string>()

  // ── Drag-to-connect state (edit mode) ────────────────────────────────────
  const contentRef = useRef<HTMLDivElement>(null)
  const dragFrom = useRef<string | null>(null)
  const [dragTo, setDragTo] = useState<{ x: number; y: number } | null>(null)

  const toContentCoords = (e: ReactPointerEvent) => {
    const rect = contentRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }
  const startConnect = (nodeId: string) => (e: ReactPointerEvent) => {
    e.stopPropagation()
    dragFrom.current = nodeId
    setDragTo(toContentCoords(e))
  }
  const onPointerMove = (e: ReactPointerEvent) => {
    if (dragFrom.current) setDragTo(toContentCoords(e))
  }
  const dropOnNode = (targetId: string) => (e: ReactPointerEvent) => {
    if (dragFrom.current && dragFrom.current !== targetId) {
      e.stopPropagation()
      onConnect?.(dragFrom.current, targetId)
    }
    dragFrom.current = null
    setDragTo(null)
  }
  const endDrag = () => { dragFrom.current = null; setDragTo(null) }

  const dragSourcePos = dragFrom.current ? layout.nodes[dragFrom.current] : null

  return (
    <div
      className="relative h-full w-full overflow-auto"
      style={{
        backgroundImage: 'radial-gradient(rgba(148,186,255,0.07) 1px, transparent 1px)',
        backgroundSize: '22px 22px',
      }}
    >
      <div
        ref={contentRef}
        className="relative"
        style={{ width: layout.width, height: layout.height, minWidth: '100%' }}
        onPointerMove={editable ? onPointerMove : undefined}
        onPointerUp={editable ? endDrag : undefined}
      >
        {/* Edge layer */}
        <svg
          className="pointer-events-none absolute inset-0"
          width={layout.width}
          height={layout.height}
          aria-hidden
        >
          {layout.edges.map((e) => {
            const key = `${e.from}->${e.to}`
            const isActive = active.has(key)
            const dimmed = replay && !isActive
            return (
              <g key={key}>
                <path
                  d={e.path}
                  fill="none"
                  stroke={isActive ? TONE_STROKE.glow : 'rgba(148,186,255,0.20)'}
                  strokeWidth={isActive ? 2 : 1.5}
                  opacity={dimmed ? 0.25 : 1}
                />
                {isActive && (
                  <path d={e.path} fill="none" stroke={TONE_STROKE.glow} strokeWidth={2} className="cq-flow-edge" />
                )}
                {e.when && (
                  <text x={e.labelX} y={e.labelY} textAnchor="middle" className="fill-faint font-mono text-[9px] uppercase">
                    {e.when}
                  </text>
                )}
              </g>
            )
          })}
          {/* Temp connect edge while dragging */}
          {editable && dragSourcePos && dragTo && (
            <line
              x1={dragSourcePos.x + dragSourcePos.w}
              y1={dragSourcePos.y + dragSourcePos.h / 2}
              x2={dragTo.x}
              y2={dragTo.y}
              stroke={TONE_STROKE.glow}
              strokeWidth={2}
              strokeDasharray="4 4"
            />
          )}
        </svg>

        {/* Node layer */}
        {graph.nodes.map((node) => {
          const pos = layout.nodes[node.id]
          if (!pos) return null
          const meta = nodeMeta(node.type)
          const caption = nodeCaption(node)

          const stepStatus = visited?.get(node.id) as StepStatus | undefined
          const dimmed = replay && !stepStatus
          const tone = asTone(stepStatus ? STEP_STATUS_TONE[stepStatus] : meta.tone)
          const isParked = parkedNode === node.id
          const isSelected = selectedNode === node.id

          const style: CSSProperties = { left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }

          return (
            <button
              key={node.id}
              type="button"
              onClick={() => onNodeClick?.(node.id)}
              onPointerUp={editable ? dropOnNode(node.id) : undefined}
              aria-label={`${meta.label}${caption ? ` — ${caption}` : ''}`}
              className={`group absolute flex flex-col justify-center gap-1 rounded-card border bg-surface px-3.5 text-left backdrop-blur-xl transition-[opacity,transform] duration-200 ${
                dimmed ? 'opacity-35' : 'opacity-100'
              } ${
                stepStatus || isSelected
                  ? `${TONE_BORDER[tone]} ${TONE_GLOW[tone]}`
                  : 'border-line [box-shadow:var(--shadow-card)] hover:border-[rgba(148,186,255,0.2)]'
              }`}
              style={style}
            >
              {isParked && (
                <span aria-hidden className={`cq-node-wait pointer-events-none absolute -inset-px rounded-card ${TONE_GLOW.warn}`} />
              )}

              <div className="flex items-center gap-2">
                <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-control ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}>
                  <Icon name={meta.icon as IconName} size={13} />
                </span>
                <span className="truncate text-[13px] font-medium text-ink">{meta.label}</span>
                {stepStatus && (
                  <span className={`ml-auto shrink-0 font-mono text-[9px] uppercase tracking-wider ${TONE_TEXT[tone]}`}>
                    {STEP_STATUS_LABEL[stepStatus]}
                  </span>
                )}
              </div>
              {caption && (
                <p className="truncate pl-8 text-[11px] leading-tight text-muted" dir="auto">{caption}</p>
              )}

              {/* Output port — the drag-to-connect handle (edit mode only) */}
              {editable && (
                <span
                  role="button"
                  aria-label={`Connect from ${meta.label}`}
                  onPointerDown={startConnect(node.id)}
                  className="absolute -right-2 top-1/2 z-10 grid h-4 w-4 -translate-y-1/2 cursor-crosshair place-items-center rounded-full border border-[rgba(96,165,250,0.6)] bg-bg text-glow hover:bg-[rgba(59,130,246,0.2)]"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-glow" />
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
