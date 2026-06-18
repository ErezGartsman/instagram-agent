export function StatCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-5">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-ink">{value}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  )
}
