import { PageHeader } from '../components/PageHeader'
import { Placeholder } from '../components/Placeholder'

export function ContentPage() {
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Content" subtitle="Plan and ship anonymized content." />
      <Placeholder
        icon="sparkle"
        title="The content workflow lands in Ticket 5.3"
        body="Draft, review, and schedule the anonymized content engine — turning real conversations into publishable insight without exposing anyone."
        ticket="Ticket 5.3 · Content"
      />
    </div>
  )
}
