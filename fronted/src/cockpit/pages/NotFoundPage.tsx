import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { Placeholder } from '../components/Placeholder'

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Not found" subtitle="That page isn't part of the Cockpit." />
      <Placeholder
        icon="alert"
        title="Nothing here"
        body="The page you're looking for doesn't exist. It may have moved, or it hasn't been built yet."
        ticket="404"
      />
      <div className="mt-6 text-center">
        <Link to="/app" className="text-sm text-accent transition-opacity hover:opacity-80">
          Return to Overview
        </Link>
      </div>
    </div>
  )
}
