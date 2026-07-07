import { Link } from 'react-router-dom'
import { motion, useReducedMotion } from 'framer-motion'

const MotionLink = motion(Link)

export function StatCard({
  label,
  value,
  note,
  index = 0,
  href,
}: {
  label: string
  value: string
  note?: string
  index?: number
  href?: string
}) {
  const reduce = useReducedMotion()
  const motionProps = {
    initial: reduce ? false : { opacity: 0, y: 16 },
    animate: { opacity: 1, y: 0 },
    whileHover: reduce
      ? undefined
      : { y: -4, boxShadow: '0 0 36px rgba(59,130,246,0.26), inset 0 1px 0 rgba(190,214,255,0.10)' },
    transition: { duration: 0.4, delay: index * 0.08, ease: [0.25, 0.4, 0.25, 1] },
    className: 'block rounded-card border border-line bg-surface p-6 backdrop-blur-xl [box-shadow:var(--shadow-card)]' +
      (href ? ' cursor-pointer' : ''),
  } as const

  const inner = (
    <>
      <p className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{label}</p>
      <p className="mt-3 font-mono text-3xl font-light leading-none tabular-nums text-ink">{value}</p>
      {note && <p className="mt-2 text-xs text-muted">{note}</p>}
      <div className="mt-4 h-px rounded-full bg-gradient-to-r from-[#3b82f6] via-[rgba(96,165,250,0.4)] to-transparent" />
    </>
  )

  if (href) {
    return (
      <MotionLink to={href} {...motionProps}>
        {inner}
      </MotionLink>
    )
  }

  return (
    <motion.div {...motionProps}>
      {inner}
    </motion.div>
  )
}
