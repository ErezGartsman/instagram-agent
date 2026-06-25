import { motion, useReducedMotion } from 'framer-motion'

export function StatCard({
  label,
  value,
  note,
  index = 0,
}: {
  label: string
  value: string
  note?: string
  index?: number
}) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={
        reduce
          ? undefined
          : { y: -4, boxShadow: '0 0 36px rgba(184,134,11,0.28), inset 0 1px 0 rgba(255,235,180,0.10)' }
      }
      transition={{ duration: 0.4, delay: index * 0.08, ease: [0.25, 0.4, 0.25, 1] }}
      className="rounded-card border border-line bg-surface p-6 backdrop-blur-xl [box-shadow:var(--shadow-card)]"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{label}</p>
      <p className="mt-3 font-mono text-3xl font-light leading-none tabular-nums text-ink">{value}</p>
      {note && <p className="mt-2 text-xs text-muted">{note}</p>}
      <div className="mt-4 h-px rounded-full bg-gradient-to-r from-[#b8860b] via-[rgba(212,168,67,0.4)] to-transparent" />
    </motion.div>
  )
}
