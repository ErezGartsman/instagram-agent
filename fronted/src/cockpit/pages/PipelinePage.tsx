import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import {
  SurfaceLoading,
  SurfaceEmpty,
  SurfaceError,
  SampleNotice,
} from '../components/SurfaceStates'
import { Badge, Button, GlassPanel } from '../components/ui'
import { useSurfaceQuery } from '../lib/useSurfaceQuery'
import { queryKeys } from '../lib/queryClient'
import {
  fetchPipeline,
  relativeTime,
  CHANNEL_LABELS,
  STAGE_LABELS,
  SAMPLE_PIPELINE,
  type Lead,
  type Stage,
} from '../lib/pipeline'

export function PipelinePage() {
  const state = useSurfaceQuery<Stage[]>({
    queryKey: queryKeys.pipeline,
    fetcher: fetchPipeline,
    sample: SAMPLE_PIPELINE,
    isEmpty: (stages) => stages.every((s) => s.leads.length === 0),
  })

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader title="Pipeline" subtitle="Every open lead, across qualification stages." />

      {state.kind === 'ready' && state.sample && <SampleNotice />}

      {state.kind === 'loading' && <SurfaceLoading variant="board" />}

      {state.kind === 'error' && (
        <SurfaceError
          title="Couldn't load the pipeline"
          body="The lead board couldn't be reached. Check your connection and try again."
          onRetry={state.retry}
        />
      )}

      {state.kind === 'empty' && (
        <SurfaceEmpty
          flavor="start"
          icon="columns"
          title="The board is clear"
          body="No open opportunities right now. New leads land here the moment they message on WhatsApp, Instagram, or Telegram — the Work Queue will surface whoever needs you first."
          action={
            <Button asChild>
              <Link to="/app/queue">Open the Work Queue</Link>
            </Button>
          }
        />
      )}

      {state.kind === 'ready' && (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {state.data.map((s) => (
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
        <Badge tone="count" mono>
          {stage.count}
        </Badge>
      </div>
      <div className="flex flex-col gap-2">
        {stage.leads.length === 0 ? (
          <p className="rounded-card border border-dashed border-line px-3 py-6 text-center text-xs text-muted">
            No leads
          </p>
        ) : (
          // Staggered entrance (E2 §A3): 40ms/row, capped at 6 — a long column
          // shouldn't cascade for a full second before it's readable.
          stage.leads.map((lead, i) => (
            <LeadCard key={lead.id} lead={lead} delayMs={Math.min(i, 6) * 40} />
          ))
        )}
      </div>
    </div>
  )
}

function LeadCard({ lead, delayMs = 0 }: { lead: Lead; delayMs?: number }) {
  const channel = lead.channel ? (CHANNEL_LABELS[lead.channel] ?? lead.channel) : null
  return (
    <GlassPanel
      depth="card"
      className="cq-rise p-3 transition-colors hover:bg-raised"
      style={{ animationDelay: `${delayMs}ms` }}
    >
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
    </GlassPanel>
  )
}
