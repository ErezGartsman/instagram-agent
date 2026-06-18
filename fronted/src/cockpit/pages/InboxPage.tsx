import { PageHeader } from '../components/PageHeader'
import { Placeholder } from '../components/Placeholder'

export function InboxPage() {
  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Inbox" subtitle="Read, reply, and take over conversations." />
      <Placeholder
        icon="inbox"
        title="The unified inbox lands in Ticket 5.2"
        body="One thread view across WhatsApp and Telegram. Read the history, reply, or take over from the bot — sent through KapsoChannel on the backend."
        ticket="Ticket 5.2 · Inbox"
      />
    </div>
  )
}
