import { PageHeader } from '../components/PageHeader'
import { Placeholder } from '../components/Placeholder'
import { StatCard } from '../components/StatCard'

const STATS = [
  { label: 'Open leads', value: '—', note: 'Connects in Ticket 5.1' },
  { label: 'Unread messages', value: '—', note: 'Connects in Ticket 5.2' },
  { label: 'Booked consultations', value: '—', note: 'North-star metric' },
  { label: 'Reply rate', value: '—', note: 'Awaiting data' },
]

export function OverviewPage() {
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Overview" subtitle="Your command center at a glance." />

      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STATS.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      <Placeholder
        icon="grid"
        title="The Overview dashboard lands in Ticket 5.4"
        body="Once the pipeline and inbox are live, this surface unifies the funnel — booked consultations, lead velocity, and channel health — in one calm view."
        ticket="Ticket 5.4 · Overview"
      />
    </div>
  )
}
