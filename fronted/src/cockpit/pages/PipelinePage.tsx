import { useCallback, useEffect, useState } from 'react'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError } from '../components/SurfaceStates'
import { useAuth } from '../auth/AuthProvider'
import {
  fetchPipeline,
  relativeTime,
  CHANNEL_LABELS,
  STAGE_LABELS,
  SAMPLE_PIPELINE,
  type Lead,
  type Stage,
} from '../lib/pipeline'

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; stages: Stage[]; sample: boolean }

export function PipelinePage() {
  const { session, devBypass } = useAuth()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const retry = useCallback(() => {
    setState({ kind: 'loading' })
    setRetryNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    if (devBypass) {
      setState({ kind: 'ready', stages: SAMPLE_PIPELINE, sample: true })
      return
    }
    const token = session?.access_token
    if (!token) {
      setState({ kind: 'loading' })
      return
    }
    const controller = new AbortController()
    setState({ kind: 'loading' })
    fetchPipeline(token, controller.signal)
      .then((stages) => setState({ kind: 'ready', stages, sample: false }))
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') {
          setState({ kind: 'error' })
        }
      })
    return () => controller.abort()
  }, [session?.access_token, devBypass, retryNonce])

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Pipeline" subtitle="Every open lead, across qualification stages." />

      {state.kind === 'ready' && state.sample && (
        <div className="mb-4 inline-flex items-center gap-2 rounded-control border border-line px-3 py-1 text-xs text-warn">
          <Icon name="alert" size={13} />
          sample data (dev bypass) — live leads load when you&rsquo;re signed in
        </div>
      )}

      {state.kind === 'loading' && <SurfaceLoading variant="board" />}
      {state.kind === 'error' && (
        <SurfaceError
          title="Couldn't load the pipeline"
          body="The lead board couldn't be reached. Check your connection and try again."
          onRetry={retry}
        />
      )}
      {state.kind === 'ready' && (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {state.stages.map((s) => (
            <StageColumn key={s.stage} stage={s} />
          ))}
        </div>
      )}
    </div>
  )
}

function StageColumn({ stage }: { stage: Stage }) {
  const isBooked = stage.stage === 'booked'
  return (
    <div className="flex w-[264px] shrink-0 flex-col">
      <div className="mb-3 flex items-center justify-between px-1">
        <span className={`text-sm font-semibold ${isBooked ? 'text-success' : 'text-ink'}`}>
          {STAGE_LABELS[stage.stage] ?? stage.stage}
        </span>
        <span className="rounded-control bg-raised px-2 py-0.5 font-mono text-xs text-muted">
          {stage.count}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {stage.leads.length === 0 ? (
          <p className="rounded-card border border-dashed border-line px-3 py-6 text-center text-xs text-muted">
            No leads
          </p>
        ) : (
          stage.leads.map((lead) => <LeadCard key={lead.id} lead={lead} />)
        )}
      </div>
    </div>
  )
}

function LeadCard({ lead }: { lead: Lead }) {
  const channel = lead.channel ? (CHANNEL_LABELS[lead.channel] ?? lead.channel) : null
  return (
    <div className="rounded-card border border-line bg-surface p-3 transition-colors hover:bg-raised">
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <span className="text-sm font-semibold text-ink">{lead.name}</span>
        {channel && <span className="shrink-0 text-xs text-muted">{channel}</span>}
      </div>
      {lead.intent && (
        <p className="mb-2.5 line-clamp-2 text-xs leading-relaxed text-muted">{lead.intent}</p>
      )}
      <div className="flex items-center gap-1.5 text-xs text-muted">
        <Icon name="clock" size={12} />
        <span className="font-mono">{relativeTime(lead.last_contacted)}</span>
      </div>
    </div>
  )
}

