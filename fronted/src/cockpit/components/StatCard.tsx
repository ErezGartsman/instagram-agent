export function StatCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-6 [box-shadow:var(--shadow-card)]">
      <p className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{label}</p>
      <p className="mt-3 font-mono text-3xl font-semibold leading-none tabular-nums text-ink">{value}</p>
      {note && <p className="mt-2 text-xs text-muted">{note}</p>}
    </div>
  )
}
