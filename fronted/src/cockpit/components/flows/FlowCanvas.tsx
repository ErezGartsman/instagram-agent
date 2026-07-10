import type { CSSProperties } from 'react'
import { Icon } from '../Icon'
import type { IconName } from '../Icon'
import {
  nodeMeta, nodeCaption, STEP_STATUS_LABEL, STEP_STATUS_TONE,
  type FlowGraph, type StepStatus,
} from '../../lib/flows'
import { layoutFlow, activeEdges, NODE_W, NODE_H } from '../../lib/flowLayout'
import { asTone, TONE_TEXT, TONE_BORDER, TONE_TINT, TONE_GLOW, TONE_STROKE } from './tone'

/**
 * FlowCanvas — the bespoke node graph (F2). SVG layer for the bezier edges,
 * absolutely-positioned glass cards for the nodes, on a dotted node-editor
 * grid. Two modes:
 *   definition — neutral glass, the flow's shape at rest.
 *   replay     — a `visited` map (node_id → step status) lights the path the
 *                selected run took; unvisited nodes dim, the traversed edges
 *                carry flowing current, the parked node breathes.
 *
 * Pure presentation: layout is computed by the tested lib/flowLayout.
 */
export function FlowCanvas({
  graph,
  visited,
  parkedNode,
  selectedNode,
  onNodeClick,
}: {
  graph: FlowGraph
  /** Present in replay mode: node_id → the step status it reached. */
  visited?: Map<string, string>
  /** The node a waiting run is parked at (breathes). */
  parkedNode?: string | null
  selectedNode?: string | null
  onNodeClick?: (nodeId: string) => void
}) {
  const layout = layoutFlow(graph)
  const replay = !!visited
  const active = replay ? activeEdges(layout.edges, visited!) : new Set<string>()

  return (
    <div
      className="relative h-full w-full overflow-auto"
      style={{
        backgroundImage: 'radial-gradient(rgba(148,186,255,0.07) 1px, transparent 1px)',
        backgroundSize: '22px 22px',
      }}
    >
      <div className="relative" style={{ width: layout.width, height: layout.height, minWidth: '100%' }}>
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
                  <path
                    d={e.path}
                    fill="none"
                    stroke={TONE_STROKE.glow}
                    strokeWidth={2}
                    className="cq-flow-edge"
                  />
                )}
                {e.when && (
                  <text
                    x={e.labelX}
                    y={e.labelY}
                    textAnchor="middle"
                    className="fill-faint font-mono text-[9px] uppercase"
                  >
                    {e.when}
                  </text>
                )}
              </g>
            )
          })}
        </svg>

        {/* Node layer */}
        {graph.nodes.map((node) => {
          const pos = layout.nodes[node.id]
          if (!pos) return null
          const meta = nodeMeta(node.type)
          const caption = nodeCaption(node)

          const stepStatus = visited?.get(node.id) as StepStatus | undefined
          const dimmed = replay && !stepStatus
          // In replay a visited node adopts its STEP status tone; otherwise the
          // node's own type tone. This is why a blocked send glows red.
          const tone = asTone(stepStatus ? STEP_STATUS_TONE[stepStatus] : meta.tone)
          const isParked = parkedNode === node.id
          const isSelected = selectedNode === node.id

          const style: CSSProperties = { left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }

          return (
            <button
              key={node.id}
              type="button"
              onClick={() => onNodeClick?.(node.id)}
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
              {/* Parked breathing halo */}
              {isParked && (
                <span
                  aria-hidden
                  className={`cq-node-wait pointer-events-none absolute -inset-px rounded-card ${TONE_GLOW.warn}`}
                />
              )}

              <div className="flex items-center gap-2">
                <span
                  className={`grid h-6 w-6 shrink-0 place-items-center rounded-control ${TONE_TINT[tone]} ${TONE_TEXT[tone]}`}
                >
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
                <p className="truncate pl-8 text-[11px] leading-tight text-muted" dir="auto">
                  {caption}
                </p>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
