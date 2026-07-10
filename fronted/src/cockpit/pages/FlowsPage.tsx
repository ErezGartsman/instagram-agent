import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '../components/PageHeader'
import { SurfaceLoading, SurfaceError, SurfaceEmpty, SampleNotice } from '../components/SurfaceStates'
import { Badge } from '../components/ui'
import { FlowCanvas } from '../components/flows/FlowCanvas'
import { RunInspector } from '../components/flows/RunInspector'
import { asTone, TONE_TEXT, TONE_DOT } from '../components/flows/tone'
import { useAuth } from '../auth/AuthProvider'
import { useSurfaceQuery } from '../lib/useSurfaceQuery'
import { useFlowsRealtimeInvalidation } from '../lib/realtime'
import { queryKeys } from '../lib/queryClient'
import { relativeTime } from '../lib/pipeline'
import { runPath } from '../lib/flowLayout'
import {
  fetchFlows, fetchFlowRuns, triggerFlowsSweep,
  type FlowsResponse, type FlowRun, type FlowSummary,
} from '../lib/flows'
import { SAMPLE_FLOWS, SAMPLE_RUNS } from '../lib/flowsSample'

/**
 * FlowsPage — the F2 canvas. Three panes: the flow list (left), the visual
 * node canvas (center), the run inspector (right). Selecting a run turns the
 * canvas into a replay of that run's path; selecting a send/notify step opens
 * its full Verifier Loop panel — the "why" for every shadow decision.
 */
export function FlowsPage() {
  const { session, devBypass } = useAuth()
  const token = session?.access_token ?? null
  const qc = useQueryClient()

  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)

  // ── Flows list (four-state on the spine) ─────────────────────────────────
  const flowsState = useSurfaceQuery<FlowsResponse>({
    queryKey: queryKeys.flows,
    fetcher: fetchFlows,
    sample: { enabled: false, flows: SAMPLE_FLOWS },
    isEmpty: (d) => d.flows.length === 0,
  })

  const flows: FlowSummary[] = flowsState.kind === 'ready' ? flowsState.data.flows : []
  const enginEnabled = flowsState.kind === 'ready' ? flowsState.data.enabled : false

  // Default-select the first flow once loaded.
  useEffect(() => {
    if (!selectedFlowId && flows.length) setSelectedFlowId(flows[0].id)
  }, [flows, selectedFlowId])

  const selectedFlow = flows.find((f) => f.id === selectedFlowId) ?? null

  // ── Runs for the selected flow ────────────────────────────────────────────
  const runsQuery = useQuery({
    queryKey: queryKeys.flowRuns(selectedFlowId ?? 'none'),
    queryFn: ({ signal }) => fetchFlowRuns(token!, selectedFlowId!, signal),
    enabled: !!token && !devBypass && !!selectedFlowId,
  })
  const runs: FlowRun[] = devBypass
    ? SAMPLE_RUNS[selectedFlowId ?? ''] ?? []
    : runsQuery.data ?? []

  useFlowsRealtimeInvalidation(!!token && !devBypass, selectedFlowId)

  // Reset run/node selection when the flow changes.
  useEffect(() => { setSelectedRunId(null); setSelectedNode(null) }, [selectedFlowId])

  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null
  const visited = useMemo(
    () => (selectedRun ? runPath(selectedRun.steps) : undefined),
    [selectedRun],
  )
  const parkedNode = selectedRun?.status === 'waiting' ? selectedRun.cursor_node : null

  // ── Sweep ─────────────────────────────────────────────────────────────────
  const sweep = useMutation({
    mutationFn: () => triggerFlowsSweep(token!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.flows })
      if (selectedFlowId) void qc.invalidateQueries({ queryKey: queryKeys.flowRuns(selectedFlowId) })
    },
  })

  // ── Four-state gate on the whole surface ─────────────────────────────────
  if (flowsState.kind === 'loading') {
    return <div className="mx-auto max-w-[1600px]"><SurfaceLoading variant="rail" /></div>
  }
  if (flowsState.kind === 'error') {
    return (
      <div className="mx-auto max-w-[1600px]">
        <SurfaceError
          title="Couldn't load Flows"
          body="The automation engine couldn't be reached. Check your connection and try again."
          onRetry={flowsState.retry}
        />
      </div>
    )
  }
  if (flowsState.kind === 'empty') {
    return (
      <div className="mx-auto max-w-[1600px]">
        <PageHeader title="Flows" subtitle="Autonomous flows that watch your leads and act." />
        <SurfaceEmpty
          flavor="start"
          icon="zap"
          title="No flows yet"
          body="Flows run in shadow mode first — the engine records exactly what each one would do against real leads, so you can trust it before it ever sends. Seeded system flows appear here once the engine is provisioned."
        />
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {flowsState.sample && <SampleNotice />}

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-card border border-line bg-bg">
        {/* ── Left: flow list ──────────────────────────────────────────────── */}
        <FlowListRail
          flows={flows}
          selectedId={selectedFlowId}
          onSelect={setSelectedFlowId}
          engineEnabled={enginEnabled}
        />

        {/* ── Center: header + canvas ──────────────────────────────────────── */}
        <section className="flex min-w-0 flex-1 flex-col">
          {selectedFlow ? (
            <>
              <CanvasHeader flow={selectedFlow} replaying={!!selectedRun} />
              <div className="min-h-0 flex-1">
                <FlowCanvas
                  graph={selectedFlow.graph}
                  visited={visited}
                  parkedNode={parkedNode}
                  selectedNode={selectedNode}
                  onNodeClick={(id) => setSelectedNode(selectedNode === id ? null : id)}
                />
              </div>
            </>
          ) : (
            <div className="grid flex-1 place-items-center text-sm text-faint">Select a flow</div>
          )}
        </section>

        {/* ── Right: run inspector ─────────────────────────────────────────── */}
        {selectedFlow && (
          <RunInspector
            flow={selectedFlow}
            runs={runs}
            selectedRun={selectedRun}
            onSelectRun={setSelectedRunId}
            selectedNode={selectedNode}
            onSelectNode={setSelectedNode}
            onSweep={() => sweep.mutate()}
            sweeping={sweep.isPending}
            canSweep={!devBypass}
          />
        )}
      </div>
    </div>
  )
}

// ── Flow list rail ───────────────────────────────────────────────────────────

function FlowListRail({
  flows, selectedId, onSelect, engineEnabled,
}: {
  flows: FlowSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  engineEnabled: boolean
}) {
  return (
    <aside className="flex w-[300px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Flows</span>
        <span className={`inline-flex items-center gap-1.5 font-mono text-[10px] ${engineEnabled ? 'text-success' : 'text-faint'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${engineEnabled ? 'bg-success' : 'bg-faint'}`} />
          {engineEnabled ? 'engine on' : 'engine off'}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {flows.map((flow) => (
          <FlowCard
            key={flow.id}
            flow={flow}
            selected={flow.id === selectedId}
            onSelect={() => onSelect(flow.id)}
          />
        ))}
      </div>
    </aside>
  )
}

function FlowCard({ flow, selected, onSelect }: { flow: FlowSummary; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      className={`relative mb-1 flex w-full flex-col items-start gap-2 rounded-card px-3.5 py-3 text-left transition-colors ${
        selected ? 'bg-raised' : 'hover:bg-raised/60'
      }`}
    >
      <span
        aria-hidden
        className={`absolute left-0 top-1/2 h-8 w-0.5 -translate-y-1/2 rounded-full bg-accent transition-opacity ${
          selected ? 'opacity-100' : 'opacity-0'
        }`}
      />
      <div className="flex w-full items-start justify-between gap-2">
        <span className="text-[13px] font-medium leading-snug text-ink">{flow.name}</span>
        <ShadowBadge live={flow.live} />
      </div>
      <div className="flex items-center gap-2 font-mono text-[10px] text-faint">
        <span>{triggerLabel(flow)}</span>
        <span>·</span>
        <span className="tabular-nums">{flow.run_count} runs</span>
        {flow.last_run_at && <><span>·</span><span>{relativeTime(flow.last_run_at)}</span></>}
      </div>
    </button>
  )
}

// ── Canvas header ────────────────────────────────────────────────────────────

function CanvasHeader({ flow, replaying }: { flow: FlowSummary; replaying: boolean }) {
  return (
    <div className="border-b border-line px-6 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-ink">{flow.name}</h2>
        <ShadowBadge live={flow.live} />
        <Badge tone="neutral" mono>{triggerLabel(flow)}</Badge>
        {replaying && (
          <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-glow">
            <span className="h-1.5 w-1.5 rounded-full bg-glow [box-shadow:0_0_8px_rgba(96,165,250,0.9)]" />
            replaying a run
          </span>
        )}
      </div>
      {flow.description && (
        <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">{flow.description}</p>
      )}
    </div>
  )
}

function ShadowBadge({ live }: { live: boolean }) {
  const tone = asTone(live ? 'success' : 'accent')
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-control px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${TONE_TEXT[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} />
      {live ? 'live' : 'shadow'}
    </span>
  )
}

function triggerLabel(flow: FlowSummary): string {
  if (flow.trigger.type === 'event') return `on ${(flow.trigger.kind ?? 'event').replace(/_/g, ' ')}`
  return 'state trigger'
}
