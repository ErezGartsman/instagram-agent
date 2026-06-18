import { PageHeader } from '../components/PageHeader'
import { Placeholder } from '../components/Placeholder'

export function PipelinePage() {
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Pipeline" subtitle="Every lead, across qualification stages." />
      <Placeholder
        icon="columns"
        title="The lead board lands in Ticket 5.1"
        body="Leads from the WhatsApp qualification funnel will appear here as cards you can move across stages, updating live over Supabase Realtime."
        ticket="Ticket 5.1 · Pipeline"
      />
    </div>
  )
}
