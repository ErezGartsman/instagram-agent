import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError, SurfaceEmpty, SampleNotice } from '../components/SurfaceStates'
import { Button } from '../components/ui'
import { PlaybookCard } from '../components/flows/PlaybookCard'
import { PlaybookComposer, type PlaybookDraft } from '../components/flows/PlaybookComposer'
import { RunInspector } from '../components/flows/RunInspector'
import { SimulationDialog } from '../components/flows/SimulationDialog'
import { FlowSettingsModal } from '../components/flows/FlowSettingsModal'
import { useAuth } from '../auth/AuthProvider'
import { useSurfaceQuery } from '../lib/useSurfaceQuery'
import { useFlowsRealtimeInvalidation } from '../lib/realtime'
import { queryKeys } from '../lib/queryClient'
import {
  fetchFlows, fetchFlowRuns, triggerFlowsSweep,
  createFlow, updateFlow, forkFlow, simulateFlow, publishFlow, setFlowStatus, setFlowLive,
  type FlowsResponse, type FlowRun, type FlowSummary,
  type SimulationReport,
} from '../lib/flows'
import { blankSteps, graphToSteps, stepsToGraph } from '../lib/playbook'
import { SAMPLE_FLOWS, SAMPLE_RUNS, SAMPLE_SIM_REPORT } from '../lib/flowsSample'

/**
 * FlowsPage — Playbooks. Automations as sentences, not flowcharts: a column
 * of playbook cards ("When a booking is canceled → notify Erez"), the run
 * inspector (with the Verifier Loop panel) on the rail, and the composer +
 * 90-day time-travel simulation gating every publish. The F2/F3 node canvas
 * is gone; the engine's graph format is compiled to/from a flat step list
 * (lib/playbook) so the backend never noticed the redesign.
 */
export function FlowsPage() {
  const { session, devBypass } = useAuth()
  const token = session?.access_token ?? null
  const qc = useQueryClient()

  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [draft, setDraft] = useState<PlaybookDraft | null>(null)
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

  const runsQuery = useQuery({
    queryKey: queryKeys.flowRuns(selectedFlowId ?? 'none'),
    queryFn: ({ signal }) => fetchFlowRuns(token!, selectedFlowId!, signal),
    enabled: !!token && !devBypass && !!selectedFlowId,
  })
  const runs: FlowRun[] = devBypass ? SAMPLE_RUNS[selectedFlowId ?? ''] ?? [] : runsQuery.data ?? []
  useFlowsRealtimeInvalidation(!!token && !devBypass, selectedFlowId)

  useEffect(() => { setSelectedRunId(null); setSelectedNode(null) }, [selectedFlowId])

  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null
  const invalidateFlows = () => void qc.invalidateQueries({ queryKey: queryKeys.flows })

  // ── Mutations ─────────────────────────────────────────────────────────────
  const sweep = useMutation({
    mutationFn: () => triggerFlowsSweep(token!),
    onSuccess: () => {
      invalidateFlows()
      if (selectedFlowId) void qc.invalidateQueries({ queryKey: queryKeys.flowRuns(selectedFlowId) })
    },
  })

  // A draft whose steps are null keeps its saved graph: PATCH simply omits
  // `graph` and the backend leaves the stored one untouched.
  const draftBody = (d: PlaybookDraft) => ({
    name: d.name,
    description: d.description,
    trigger: d.trigger,
    ...(d.steps !== null ? { graph: stepsToGraph(d.steps) } : {}),
  })

  const save = useMutation({
    mutationFn: async () => {
      if (!draft || devBypass) return
      if (draft.id) await updateFlow(token!, draft.id, draftBody(draft))
    },
    onSuccess: invalidateFlows,
  })

  const publish = useMutation({
    mutationFn: async () => {
      if (devBypass || !draft?.id) return SAMPLE_SIM_REPORT
      // Save the latest edits first, then publish (server re-runs the sim as
      // the authoritative gate).
      await updateFlow(token!, draft.id, draftBody(draft))
      return publishFlow(token!, draft.id)
    },
    onSuccess: () => {
      invalidateFlows()
      setSim({ open: false, report: null, loading: false })
      setDraft(null)
    },
  })

  const statusMut = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'pause' | 'resume' }) =>
      devBypass ? Promise.resolve() : setFlowStatus(token!, id, action),
    onSuccess: invalidateFlows,
  })
  const liveMut = useMutation({
    mutationFn: ({ id, live }: { id: string; live: boolean }) =>
      devBypass ? Promise.resolve() : setFlowLive(token!, id, live),
    onSuccess: invalidateFlows,
  })

  // ── Edit lifecycle ────────────────────────────────────────────────────────
  const enterEdit = (flow: FlowSummary, id: string | null = flow.id) =>
    setDraft({
      id, name: flow.name, description: flow.description,
      trigger: flow.trigger, steps: graphToSteps(flow.graph),
    })

  const enterFork = useMutation({
    mutationFn: async (flow: FlowSummary) => {
      if (devBypass) return flow.id
      const { id } = await forkFlow(token!, flow.id)
      return id
    },
    onSuccess: (id, flow) => {
      invalidateFlows()
      enterEdit(flow, id)
      setSelectedFlowId(id)
    },
  })

  const startNew = useMutation({
    mutationFn: async () => {
      const trigger = { type: 'event' as const, kind: 'booking_canceled' }
      const steps = blankSteps()
      if (devBypass) return { id: null as string | null, trigger, steps }
      const { id } = await createFlow(token!, { name: 'New playbook', trigger, graph: stepsToGraph(steps) })
      return { id, trigger, steps }
    },
    onSuccess: ({ id, trigger, steps }) => {
      invalidateFlows()
      if (id) setSelectedFlowId(id)
      setDraft({ id, name: 'New playbook', description: '', trigger, steps })
    },
  })

  const runSimulation = async () => {
    if (!draft) return
    setSim({ open: true, report: null, loading: true })
    try {
      const report = devBypass || !draft.id
        ? SAMPLE_SIM_REPORT
        : await simulateFlow(token!, draft.id, {
            trigger: draft.trigger,
            ...(draft.steps !== null ? { graph: stepsToGraph(draft.steps) } : {}),
          })
      setSim({ open: true, report, loading: false })
    } catch {
      setSim({ open: true, report: { window_days: 90, trigger_type: draft.trigger.type, fires: 0,
        actions: {}, blocked: 0, blocked_by: {}, sample: [],
        notes: ['Simulation failed — check the playbook and try again.'] }, loading: false })
    }
  }

  const onEditFlow = (flow: FlowSummary) =>
    flow.status === 'draft' ? enterEdit(flow) : enterFork.mutate(flow)

  // ── Four-state gate ────────────────────────────────────────────────────────
  if (flowsState.kind === 'loading') {
    return <div className="mx-auto max-w-[1600px]"><SurfaceLoading variant="rail" /></div>
  }
  if (flowsState.kind === 'error') {
    return (
      <div className="mx-auto max-w-[1600px]">
        <SurfaceError title="Couldn't load Playbooks"
          body="The automation engine couldn't be reached. Check your connection and try again."
          onRetry={flowsState.retry} />
      </div>
    )
  }
  if (flowsState.kind === 'empty' && !draft) {
    return (
      <div className="mx-auto max-w-[1600px]">
        <header className="mb-8">
          <h2 className="text-3xl font-semibold text-ink">Playbooks</h2>
          <p className="mt-1 text-sm text-muted">Automations in plain language, rehearsed against real history.</p>
        </header>
        <SurfaceEmpty flavor="start" icon="zap" title="No playbooks yet"
          body="Write your first playbook and rehearse it against 90 days of real history before it ever touches a lead."
          action={<Button icon="sparkle" onClick={() => startNew.mutate()}>New playbook</Button>} />
      </div>
    )
  }

  const busy = statusMut.isPending || liveMut.isPending || enterFork.isPending

  return (
    <div className="flex h-full min-h-0 flex-col">
      {flowsState.kind === 'ready' && flowsState.sample && <SampleNotice />}

      {/* Header strip: title · engine state · guardrails · sweep · new */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h2 className="text-2xl font-semibold text-ink">Playbooks</h2>
          <p className="mt-0.5 text-sm text-muted">
            Automations in plain language — every one rehearsed against 90 days of history before it touches a lead.
          </p>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <button
            type="button" onClick={() => setShowSettings(true)}
            aria-label="Engine guardrails"
            className={`flex cursor-pointer items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors hover:bg-raised ${
              engineEnabled ? 'text-success' : 'text-faint'
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${engineEnabled ? 'bg-success' : 'bg-faint'}`} />
            {engineEnabled ? 'engine on' : 'engine off'}
            <Icon name="shield" size={11} className="text-faint" />
          </button>
          {!devBypass && (
            <Button variant="outline" size="sm" icon="play" onClick={() => sweep.mutate()} disabled={sweep.isPending}>
              {sweep.isPending ? 'Sweeping…' : 'Run sweep'}
            </Button>
          )}
          <Button variant="primary" size="sm" icon="sparkle" onClick={() => startNew.mutate()} disabled={startNew.isPending}>
            New playbook
          </Button>
        </div>
      </div>

      {/* Cards + activity rail */}
      <div className="flex min-h-0 flex-1 gap-4">
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pb-6 pr-1">
          {flows.map((flow) => (
            <PlaybookCard
              key={flow.id}
              flow={flow}
              selected={flow.id === selectedFlowId}
              busy={busy}
              onSelect={() => setSelectedFlowId(flow.id)}
              onEdit={() => onEditFlow(flow)}
              onLive={(live) => liveMut.mutate({ id: flow.id, live })}
              onStatus={(action) => statusMut.mutate({ id: flow.id, action })}
            />
          ))}
        </div>

        {selectedFlow && (
          <div className="min-h-0 overflow-hidden rounded-card border border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]">
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
          </div>
        )}
      </div>

      {draft && (
        <PlaybookComposer
          draft={draft}
          onChange={(patch) => setDraft((d) => (d ? { ...d, ...patch } : d))}
          onCancel={() => setDraft(null)}
          onSave={() => save.mutate()}
          saving={save.isPending}
          onSimulate={runSimulation}
        />
      )}

      {sim.open && (
        <SimulationDialog
          report={sim.report}
          loading={sim.loading}
          onClose={() => setSim({ open: false, report: null, loading: false })}
          onPublish={() => publish.mutate()}
          publishing={publish.isPending}
          canPublish={!!draft}
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
