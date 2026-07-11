import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError, SurfaceEmpty, SampleNotice } from '../components/SurfaceStates'
import { Badge, Button } from '../components/ui'
import { FlowCanvas } from '../components/flows/FlowCanvas'
import { RunInspector } from '../components/flows/RunInspector'
import { AuthoringPanel } from '../components/flows/AuthoringPanel'
import { SimulationDialog } from '../components/flows/SimulationDialog'
import { FlowSettingsModal } from '../components/flows/FlowSettingsModal'
import { asTone, TONE_TEXT, TONE_DOT } from '../components/flows/tone'
import { useAuth } from '../auth/AuthProvider'
import { useSurfaceQuery } from '../lib/useSurfaceQuery'
import { useFlowsRealtimeInvalidation } from '../lib/realtime'
import { queryKeys } from '../lib/queryClient'
import { relativeTime } from '../lib/pipeline'
import { runPath } from '../lib/flowLayout'
import {
  fetchFlows, fetchFlowRuns, triggerFlowsSweep,
  createFlow, updateFlow, forkFlow, simulateFlow, publishFlow, setFlowStatus, setFlowLive,
  blankGraph,
  type FlowsResponse, type FlowRun, type FlowSummary, type FlowTrigger, type FlowGraph,
  type SimulationReport,
} from '../lib/flows'
import { SAMPLE_FLOWS, SAMPLE_RUNS, SAMPLE_SIM_REPORT } from '../lib/flowsSample'

type Draft = {
  id: string | null   // null = a brand-new flow not yet persisted (dev bypass)
  name: string
  description: string | null
  trigger: FlowTrigger
  graph: FlowGraph
}

/**
 * FlowsPage — the F2 canvas + F3 authoring. Three panes: flow list · visual
 * node canvas · inspector. Read mode replays runs (F2). Edit mode (F3) turns
 * the canvas editable, swaps the inspector for the AuthoringPanel, and gates
 * publish behind the 90-day time-travel simulation.
 */
export function FlowsPage() {
  const { session, devBypass } = useAuth()
  const token = session?.access_token ?? null
  const qc = useQueryClient()

  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [sim, setSim] = useState<{ open: boolean; report: SimulationReport | null; loading: boolean }>(
    { open: false, report: null, loading: false },
  )
  const [showSettings, setShowSettings] = useState(false)

  const flowsState = useSurfaceQuery<FlowsResponse>({
    queryKey: queryKeys.flows,
    fetcher: fetchFlows,
    sample: { enabled: false, flows: SAMPLE_FLOWS },
    isEmpty: (d) => d.flows.length === 0,
  })
  const flows: FlowSummary[] = flowsState.kind === 'ready' ? flowsState.data.flows : []
  const engineEnabled = flowsState.kind === 'ready' ? flowsState.data.enabled : false

  useEffect(() => {
    if (!selectedFlowId && !draft && flows.length) setSelectedFlowId(flows[0].id)
  }, [flows, selectedFlowId, draft])

  const selectedFlow = flows.find((f) => f.id === selectedFlowId) ?? null
  const editing = draft !== null

  const runsQuery = useQuery({
    queryKey: queryKeys.flowRuns(selectedFlowId ?? 'none'),
    queryFn: ({ signal }) => fetchFlowRuns(token!, selectedFlowId!, signal),
    enabled: !!token && !devBypass && !!selectedFlowId && !editing,
  })
  const runs: FlowRun[] = devBypass ? SAMPLE_RUNS[selectedFlowId ?? ''] ?? [] : runsQuery.data ?? []
  useFlowsRealtimeInvalidation(!!token && !devBypass, selectedFlowId)

  useEffect(() => { setSelectedRunId(null); setSelectedNode(null) }, [selectedFlowId])

  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null
  const visited = useMemo(() => (selectedRun ? runPath(selectedRun.steps) : undefined), [selectedRun])
  const parkedNode = selectedRun?.status === 'waiting' ? selectedRun.cursor_node : null

  const invalidateFlows = () => void qc.invalidateQueries({ queryKey: queryKeys.flows })

  // ── Mutations ─────────────────────────────────────────────────────────────
  const sweep = useMutation({
    mutationFn: () => triggerFlowsSweep(token!),
    onSuccess: () => {
      invalidateFlows()
      if (selectedFlowId) void qc.invalidateQueries({ queryKey: queryKeys.flowRuns(selectedFlowId) })
    },
  })

  const save = useMutation({
    mutationFn: async () => {
      if (!draft || devBypass) return
      if (draft.id) await updateFlow(token!, draft.id, draft)
    },
    onSuccess: invalidateFlows,
  })

  const publish = useMutation({
    mutationFn: async () => {
      if (devBypass || !draft?.id) return SAMPLE_SIM_REPORT
      // Save the latest edits first, then publish (server re-runs the sim as
      // the authoritative gate).
      await updateFlow(token!, draft.id, draft)
      return publishFlow(token!, draft.id)
    },
    onSuccess: () => {
      invalidateFlows()
      setSim({ open: false, report: null, loading: false })
      setDraft(null)
    },
  })

  const statusMut = useMutation({
    mutationFn: (action: 'pause' | 'resume' | 'archive') =>
      devBypass || !selectedFlowId ? Promise.resolve() : setFlowStatus(token!, selectedFlowId, action),
    onSuccess: invalidateFlows,
  })
  const liveMut = useMutation({
    mutationFn: (live: boolean) =>
      devBypass || !selectedFlowId ? Promise.resolve() : setFlowLive(token!, selectedFlowId, live),
    onSuccess: invalidateFlows,
  })

  // ── Edit lifecycle ────────────────────────────────────────────────────────
  const enterEdit = (flow: FlowSummary) =>
    setDraft({ id: flow.id, name: flow.name, description: flow.description,
               trigger: flow.trigger, graph: flow.graph })

  const enterFork = useMutation({
    mutationFn: async (flow: FlowSummary) => {
      if (devBypass) return flow.id
      const { id } = await forkFlow(token!, flow.id)
      return id
    },
    onSuccess: (id, flow) => {
      invalidateFlows()
      enterEdit({ ...flow, id })
      setSelectedFlowId(id)
    },
  })

  const startNew = useMutation({
    mutationFn: async () => {
      const trigger: FlowTrigger = { type: 'event', kind: 'booking_canceled' }
      const graph = blankGraph()
      if (devBypass) return { id: null as string | null, trigger, graph }
      const { id } = await createFlow(token!, { name: 'New flow', trigger, graph })
      return { id, trigger, graph }
    },
    onSuccess: ({ id, trigger, graph }) => {
      invalidateFlows()
      if (id) setSelectedFlowId(id)
      setDraft({ id, name: 'New flow', description: '', trigger, graph })
    },
  })

  const cancelEdit = () => { setDraft(null); setSelectedNode(null) }

  const runSimulation = async () => {
    if (!draft) return
    setSim({ open: true, report: null, loading: true })
    try {
      const report = devBypass || !draft.id
        ? SAMPLE_SIM_REPORT
        : await simulateFlow(token!, draft.id, { graph: draft.graph, trigger: draft.trigger })
      setSim({ open: true, report, loading: false })
    } catch {
      setSim({ open: true, report: { window_days: 90, trigger_type: draft.trigger.type, fires: 0,
        actions: {}, blocked: 0, blocked_by: {}, sample: [],
        notes: ['Simulation failed — check the flow and try again.'] }, loading: false })
    }
  }

  // ── Four-state gate ────────────────────────────────────────────────────────
  if (flowsState.kind === 'loading') {
    return <div className="mx-auto max-w-[1600px]"><SurfaceLoading variant="rail" /></div>
  }
  if (flowsState.kind === 'error') {
    return (
      <div className="mx-auto max-w-[1600px]">
        <SurfaceError title="Couldn't load Flows"
          body="The automation engine couldn't be reached. Check your connection and try again."
          onRetry={flowsState.retry} />
      </div>
    )
  }
  if (flowsState.kind === 'empty' && !editing) {
    return (
      <div className="mx-auto max-w-[1600px]">
        <PageHeader title="Flows" subtitle="Autonomous flows that watch your leads and act." />
        <SurfaceEmpty flavor="start" icon="zap" title="No flows yet"
          body="Build a flow and simulate it against 90 days of real history before it ever touches a lead."
          action={<Button icon="sparkle" onClick={() => startNew.mutate()}>New flow</Button>} />
      </div>
    )
  }

  const draftGraph = draft?.graph
  const canvasGraph = editing ? draftGraph! : selectedFlow?.graph

  return (
    <div className="flex h-full min-h-0 flex-col">
      {flowsState.kind === 'ready' && flowsState.sample && <SampleNotice />}

      <div className="flex min-h-0 flex-1 overflow-hidden rounded-card border border-line bg-bg">
        <FlowListRail
          flows={flows}
          selectedId={editing ? draft!.id : selectedFlowId}
          onSelect={(id) => { if (!editing) setSelectedFlowId(id) }}
          engineEnabled={engineEnabled}
          disabled={editing}
          onNew={() => startNew.mutate()}
          onSettings={() => setShowSettings(true)}
        />

        <section className="flex min-w-0 flex-1 flex-col">
          {editing ? (
            <EditToolbar
              draft={draft!}
              onSave={() => save.mutate()}
              saving={save.isPending}
              onSimulate={runSimulation}
              onCancel={cancelEdit}
            />
          ) : selectedFlow ? (
            <FlowToolbar
              flow={selectedFlow}
              replaying={!!selectedRun}
              busy={statusMut.isPending || liveMut.isPending || enterFork.isPending}
              onEdit={() => (selectedFlow.status === 'draft' ? enterEdit(selectedFlow) : enterFork.mutate(selectedFlow))}
              onStatus={(a) => statusMut.mutate(a)}
              onLive={(v) => liveMut.mutate(v)}
            />
          ) : (
            <div className="border-b border-line px-6 py-4 text-sm text-faint">Select a flow</div>
          )}

          <div className="min-h-0 flex-1">
            {canvasGraph ? (
              <FlowCanvas
                graph={canvasGraph}
                visited={editing ? undefined : visited}
                parkedNode={editing ? null : parkedNode}
                selectedNode={selectedNode}
                onNodeClick={(id) => setSelectedNode(selectedNode === id ? null : id)}
                editable={editing}
                onConnect={(from, to) => setDraft((d) => (d ? { ...d, graph: connectInDraft(d.graph, from, to) } : d))}
              />
            ) : (
              <div className="grid h-full place-items-center text-sm text-faint">Select a flow</div>
            )}
          </div>
        </section>

        {editing ? (
          <AuthoringPanel
            name={draft!.name}
            description={draft!.description}
            trigger={draft!.trigger}
            graph={draft!.graph}
            selectedNode={selectedNode}
            onMeta={(p) => setDraft((d) => (d ? { ...d, ...p } : d))}
            onTrigger={(t) => setDraft((d) => (d ? { ...d, trigger: t } : d))}
            onGraph={(g) => setDraft((d) => (d ? { ...d, graph: g } : d))}
            onSelectNode={setSelectedNode}
          />
        ) : selectedFlow ? (
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
        ) : null}
      </div>

      {sim.open && (
        <SimulationDialog
          report={sim.report}
          loading={sim.loading}
          onClose={() => setSim({ open: false, report: null, loading: false })}
          onPublish={() => publish.mutate()}
          publishing={publish.isPending}
          canPublish={editing}
        />
      )}
      {showSettings && (
        <FlowSettingsModal
          enabled={engineEnabled}
          devBypass={devBypass}
          token={token}
          onClose={() => setShowSettings(false)}
          onSaved={invalidateFlows}
        />
      )}
    </div>
  )
}

// A tiny wrapper so the canvas's onConnect can update the draft graph without
// importing graphEdit at the page top (keeps the page's imports focused).
function connectInDraft(graph: FlowGraph, from: string, to: string): FlowGraph {
  if (from === to) return graph
  const src = graph.nodes.find((n) => n.id === from)
  if (src?.type === 'condition') {
    // Fill the first empty branch; default to 'true'.
    const hasTrue = graph.edges.some((e) => e.from === from && e.when === 'true')
    const when = hasTrue ? 'false' : 'true'
    const edges = graph.edges.filter((e) => !(e.from === from && e.when === when))
    return { ...graph, edges: [...edges, { from, to, when }] }
  }
  const edges = graph.edges.filter((e) => e.from !== from)
  return { ...graph, edges: [...edges, { from, to }] }
}

// ── Flow list rail ───────────────────────────────────────────────────────────

function FlowListRail({
  flows, selectedId, onSelect, engineEnabled, disabled, onNew, onSettings,
}: {
  flows: FlowSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  engineEnabled: boolean
  disabled: boolean
  onNew: () => void
  onSettings: () => void
}) {
  return (
    <aside className="flex w-[300px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Flows</span>
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={onSettings} disabled={disabled} aria-label="Engine settings"
            className="grid h-6 w-6 place-items-center rounded-control text-faint transition-colors hover:text-ink disabled:opacity-40">
            <Icon name="shield" size={13} />
          </button>
          <Button variant="outline" size="sm" icon="sparkle" onClick={onNew} disabled={disabled}>New</Button>
        </div>
      </div>
      <div className="border-b border-line px-4 py-1.5">
        <span className={`inline-flex items-center gap-1.5 font-mono text-[10px] ${engineEnabled ? 'text-success' : 'text-faint'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${engineEnabled ? 'bg-success' : 'bg-faint'}`} />
          {engineEnabled ? 'engine on' : 'engine off'}
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {flows.map((flow) => (
          <FlowCard key={flow.id} flow={flow} selected={flow.id === selectedId}
            onSelect={() => onSelect(flow.id)} disabled={disabled} />
        ))}
      </div>
    </aside>
  )
}

function FlowCard({ flow, selected, onSelect, disabled }: {
  flow: FlowSummary; selected: boolean; onSelect: () => void; disabled: boolean
}) {
  return (
    <button
      type="button" onClick={onSelect} disabled={disabled}
      aria-current={selected ? 'true' : undefined}
      className={`relative mb-1 flex w-full flex-col items-start gap-2 rounded-card px-3.5 py-3 text-left transition-colors disabled:opacity-50 ${
        selected ? 'bg-raised' : 'hover:bg-raised/60'
      }`}
    >
      <span aria-hidden className={`absolute left-0 top-1/2 h-8 w-0.5 -translate-y-1/2 rounded-full bg-accent transition-opacity ${selected ? 'opacity-100' : 'opacity-0'}`} />
      <div className="flex w-full items-start justify-between gap-2">
        <span className="text-[13px] font-medium leading-snug text-ink">{flow.name}</span>
        <StatusBadge flow={flow} />
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

// ── Toolbars ─────────────────────────────────────────────────────────────────

function FlowToolbar({ flow, replaying, busy, onEdit, onStatus, onLive }: {
  flow: FlowSummary
  replaying: boolean
  busy: boolean
  onEdit: () => void
  onStatus: (a: 'pause' | 'resume' | 'archive') => void
  onLive: (v: boolean) => void
}) {
  return (
    <div className="border-b border-line px-6 py-3.5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-ink">{flow.name}</h2>
        <StatusBadge flow={flow} />
        <Badge tone="neutral" mono>{triggerLabel(flow)}</Badge>
        {replaying && (
          <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-glow">
            <span className="h-1.5 w-1.5 rounded-full bg-glow [box-shadow:0_0_8px_rgba(96,165,250,0.9)]" />
            replaying a run
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {flow.status === 'published' && (
            <Button variant={flow.live ? 'ghost' : 'outline'} size="sm" disabled={busy}
              onClick={() => onLive(!flow.live)}>
              {flow.live ? 'Return to shadow' : 'Go live'}
            </Button>
          )}
          {flow.status === 'published' && <Button variant="ghost" size="sm" disabled={busy} onClick={() => onStatus('pause')}>Pause</Button>}
          {flow.status === 'paused' && <Button variant="outline" size="sm" disabled={busy} onClick={() => onStatus('resume')}>Resume</Button>}
          <Button variant="ghost" size="sm" icon="branch" disabled={busy} onClick={onEdit}>
            {flow.status === 'draft' ? 'Edit draft' : 'Edit'}
          </Button>
        </div>
      </div>
      {flow.description && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">{flow.description}</p>}
    </div>
  )
}

function EditToolbar({ draft, onSave, saving, onSimulate, onCancel }: {
  draft: Draft; onSave: () => void; saving: boolean; onSimulate: () => void; onCancel: () => void
}) {
  return (
    <div className="flex items-center gap-3 border-b border-line bg-[rgba(59,130,246,0.04)] px-6 py-3.5">
      <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-accent">
        <Icon name="branch" size={12} /> editing
      </span>
      <span className="truncate text-sm font-medium text-ink">{draft.name || 'Untitled flow'}</span>
      <div className="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        <Button variant="ghost" size="sm" icon="check" onClick={onSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save draft'}
        </Button>
        <Button variant="primary" size="sm" icon="clock" onClick={onSimulate}>Simulate &amp; publish</Button>
      </div>
    </div>
  )
}

// ── Badges / labels ──────────────────────────────────────────────────────────

function StatusBadge({ flow }: { flow: FlowSummary }) {
  if (flow.status === 'draft') {
    return <span className="inline-flex items-center gap-1.5 rounded-control px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-warn"><span className="h-1.5 w-1.5 rounded-full bg-warn" />draft</span>
  }
  if (flow.status === 'paused') {
    return <span className="inline-flex items-center gap-1.5 rounded-control px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-faint"><span className="h-1.5 w-1.5 rounded-full bg-faint" />paused</span>
  }
  if (flow.status === 'archived') {
    return <span className="font-mono text-[10px] uppercase tracking-wider text-faint">archived</span>
  }
  const tone = asTone(flow.live ? 'success' : 'accent')
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-control px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${TONE_TEXT[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} />
      {flow.live ? 'live' : 'shadow'}
    </span>
  )
}

function triggerLabel(flow: FlowSummary): string {
  if (flow.trigger.type === 'event') return `on ${(flow.trigger.kind ?? 'event').replace(/_/g, ' ')}`
  return 'state trigger'
}
