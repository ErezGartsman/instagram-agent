import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ResponsiveContainer, AreaChart, Area, Tooltip } from 'recharts'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { SurfaceLoading, SurfaceError } from '../components/SurfaceStates'
import { useAuth } from '../auth/AuthProvider'
import { STAGE_LABELS } from '../lib/pipeline'
import { compact, fetchAnalytics, SAMPLE_ANALYTICS, type AnalyticsData } from '../lib/analytics'

type State =
  | { kind: 'loading' }
  | { kind: 'error' }
  | { kind: 'ready'; data: AnalyticsData; sample: boolean }

const BRONZE = '#d4a843'   // Warm Luxury — amber-gold (--color-glow)
const SAGE   = '#8fbc8f'   // Warm Luxury — sage green (--color-sage)
const REDUCED =
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Ticket 5.7 — the Analytics pillar, rebuilt NATIVE. A handcrafted Bento of
 * Graphite Atelier cards over our own data (social + CRM) — recharts drawn in
 * our language, no Power BI embed. Density framed in obsidian; whispered motion.
 */
export function AnalyticsPage() {
  const { session, devBypass } = useAuth()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)
  const [analystOpen, setAnalystOpen] = useState(false)
  const retry = useCallback(() => {
    setState({ kind: 'loading' })
    setRetryNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    if (devBypass) {
      setState({ kind: 'ready', data: SAMPLE_ANALYTICS, sample: true })
      return
    }
    const token = session?.access_token
    if (!token) {
      setState({ kind: 'loading' })
      return
    }
    const controller = new AbortController()
    setState({ kind: 'loading' })
    fetchAnalytics(token, controller.signal)
      .then((data) => setState({ kind: 'ready', data, sample: false }))
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') setState({ kind: 'error' })
      })
    return () => controller.abort()
  }, [session?.access_token, devBypass, retryNonce])

  return (
    <div className="mx-auto max-w-[1280px]">
      <div className="flex items-start justify-between gap-4">
        <PageHeader title="Analytics" subtitle="Community reach and pipeline, from social glance to booked call." />
        <button
          type="button"
          onClick={() => setAnalystOpen(true)}
          className="mt-1 inline-flex shrink-0 items-center gap-1.5 rounded-control border border-glow/40 bg-glow/10 px-3.5 py-2 text-xs font-medium text-glow transition-colors hover:bg-glow/20"
          aria-label="Open Nexus Data Analyst AI"
        >
          <span aria-hidden className="text-[10px]">✦</span> Ask AI
        </button>
      </div>

      {state.kind === 'ready' && state.sample && (
        <div className="mb-4 inline-flex items-center gap-2 rounded-control border border-line px-3 py-1 text-xs text-warn">
          <Icon name="alert" size={13} />
          sample data (dev bypass) — live community + CRM load when you&rsquo;re signed in
        </div>
      )}

      {state.kind === 'loading' && <SurfaceLoading variant="bento" />}
      {state.kind === 'error' && (
        <SurfaceError
          title="Couldn't load analytics"
          body="The metrics couldn't be reached. Check your connection and try again."
          onRetry={retry}
        />
      )}
      {state.kind === 'ready' && <Bento data={state.data} />}

      <DataAnalystPanel open={analystOpen} onClose={() => setAnalystOpen(false)} />
    </div>
  )
}

function Bento({ data }: { data: AnalyticsData }) {
  const { community, pipeline, booked } = data
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {/* Community — the bronze signature, spans 2 */}
      <Tile i={0} span={2} signature>
        <Label>Community · followers</Label>
        <div className="mt-1.5 font-mono text-4xl tabular-nums leading-none text-accent">
          {compact(community.size)}
        </div>
        <div className="mt-1.5 font-mono text-[10px] text-faint">
          {compact(community.followers_tracked)} tracked · IG + TikTok
        </div>
        <div className="mt-auto pt-3">
          <Spark data={community.growth} />
        </div>
      </Tile>

      <StatTile i={1} label="Reach · likes" value={compact(community.likes)} />
      <StatTile i={2} label="Conversation" value={compact(community.comments)} note="comments" />

      {/* Follower growth — the trend shape (axes hidden; absolute is the headline) */}
      <Tile i={3} span={2} className="min-h-[200px]">
        <Label>Follower growth · tracked</Label>
        <div className="mt-2 flex-1">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={community.growth} margin={{ top: 6, right: 2, bottom: 0, left: 2 }}>
              <Area
                type="monotone"
                dataKey="followers"
                stroke={BRONZE}
                strokeWidth={1.6}
                fill={BRONZE}
                fillOpacity={0.07}
                dot={false}
                isAnimationActive={!REDUCED}
                animationDuration={900}
              />
              <Tooltip
                cursor={{ stroke: 'rgba(242,235,224,0.15)' }}
                contentStyle={{
                  background: '#0e0b08',
                  border: '0.5px solid rgba(255,235,180,0.08)',
                  borderRadius: 8,
                  fontFamily: 'JetBrains Mono, monospace',
                  fontSize: 11,
                  color: '#ffffff',
                }}
                labelStyle={{ color: '#52525b' }}
                formatter={(v) => [compact(Number(v)), 'followers']}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Tile>

      {/* Top posts — spans 2 */}
      <Tile i={4} span={2} className="min-h-[200px]">
        <Label>Top posts · by likes</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {community.top_posts.slice(0, 5).map((p) => (
            <a
              key={p.shortcode}
              href={`https://instagram.com/p/${p.shortcode}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between gap-3 text-sm text-muted transition-colors hover:text-ink"
            >
              <span className="truncate font-mono text-xs text-muted">/{p.shortcode}</span>
              <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] tabular-nums">
                <span className="text-accent">{compact(p.likes)} likes</span>
                <span className="text-faint">{compact(p.comments)}</span>
              </span>
            </a>
          ))}
        </div>
      </Tile>

      {/* CRM pipeline funnel — spans 2 */}
      <Tile i={5} span={2}>
        <Label>CRM pipeline</Label>
        <div className="mt-3 flex flex-col gap-2.5">
          {pipeline.map((s) => {
            const max = Math.max(...pipeline.map((x) => x.count), 1)
            const isBooked = s.stage === 'booked'
            return (
              <div key={s.stage} className="flex items-center gap-2.5">
                <span className="w-16 shrink-0 font-mono text-[10px] text-muted">
                  {STAGE_LABELS[s.stage] ?? s.stage}
                </span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                  <span
                    className="block h-full rounded-full transition-[width] duration-700"
                    style={{ width: `${(s.count / max) * 100}%`, background: isBooked ? BRONZE : SAGE }}
                  />
                </span>
                <span className="w-5 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted">
                  {s.count}
                </span>
              </div>
            )
          })}
        </div>
      </Tile>

      <StatTile i={6} label="Content · posts" value={compact(community.posts)} />
      <StatTile i={7} label="Booked · north star" value={String(booked)} signature />
    </div>
  )
}

function Spark({ data }: { data: AnalyticsData['community']['growth'] }) {
  return (
    <div className="h-9 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <Area
            type="monotone"
            dataKey="followers"
            stroke={BRONZE}
            strokeWidth={1.4}
            fill={BRONZE}
            fillOpacity={0.08}
            dot={false}
            isAnimationActive={!REDUCED}
            animationDuration={900}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function Tile({
  children,
  i,
  span = 1,
  signature = false,
  className = '',
}: {
  children: ReactNode
  i: number
  span?: 1 | 2
  signature?: boolean
  className?: string
}) {
  return (
    <div
      className={`cq-rise flex flex-col rounded-card border bg-surface p-4 transition-colors hover:bg-raised ${
        signature ? 'border-accent/30' : 'border-line'
      } ${span === 2 ? 'sm:col-span-2' : ''} ${className}`}
      style={{ animationDelay: `${i * 55}ms` }}
    >
      {children}
    </div>
  )
}

function StatTile({
  label,
  value,
  note,
  i,
  signature = false,
}: {
  label: string
  value: string
  note?: string
  i: number
  signature?: boolean
}) {
  return (
    <Tile i={i} signature={signature}>
      <Label>{label}</Label>
      <div className={`mt-1.5 font-mono text-3xl tabular-nums leading-none ${signature ? 'text-accent' : 'text-ink'}`}>
        {value}
      </div>
      {note && <div className="mt-1.5 font-mono text-[10px] text-faint">{note}</div>}
    </Tile>
  )
}

function Label({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">{children}</span>
}

// ── Nexus Data Analyst AI — high-fidelity vision mock ────────────────────────
// Static mock panel showing the NLP-to-graph engine concept: the stakeholder
// sees the vision without requiring a backend. Marked "Preview" so the intent
// is clear. Real implementation arrives in a later workstream.

const MOCK_WEEK_DATA = [
  { day: 'Mon', leads: 2 }, { day: 'Tue', leads: 4 }, { day: 'Wed', leads: 3 },
  { day: 'Thu', leads: 1 }, { day: 'Fri', leads: 5 }, { day: 'Sat', leads: 2 },
  { day: 'Sun', leads: 3 },
]
const MOCK_MAX = Math.max(...MOCK_WEEK_DATA.map((d) => d.leads))

const MOCK_CONVERSATION: { role: 'user' | 'ai'; text: string }[] = [
  { role: 'user', text: 'How many unique leads contacted me this week?' },
  {
    role: 'ai',
    text: '7 unique leads reached out this week — up 40% from last week. 3 are in the "captured" stage and ready for a booking link. Your strongest day was Friday with 5 new contacts.',
  },
]

function DataAnalystPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Scrim */}
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="fixed inset-0 z-40 bg-bg/60 backdrop-blur-sm"
            aria-hidden
            onClick={onClose}
          />

          {/* Panel */}
          <motion.aside
            key="panel"
            initial={{ x: 420, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 420, opacity: 0 }}
            transition={{ type: 'spring', damping: 30, stiffness: 280, mass: 0.8 }}
            className="fixed right-0 top-0 z-50 flex h-screen w-[400px] flex-col border-l border-line bg-surface backdrop-blur-xl [box-shadow:var(--shadow-card)]"
            aria-label="Nexus Data Analyst AI"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div className="flex items-center gap-2.5">
                <span className="text-glow" aria-hidden>✦</span>
                <div>
                  <div className="text-sm font-semibold text-ink">Nexus Data Analyst</div>
                  <div className="font-mono text-[10px] text-faint">preview · NLP query engine</div>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close analyst panel"
                className="grid h-7 w-7 place-items-center rounded-control text-faint transition-colors hover:bg-raised hover:text-ink"
              >
                <Icon name="x" size={15} />
              </button>
            </div>

            {/* Mini chart — answers the mock query visually */}
            <div className="border-b border-line px-5 py-4">
              <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
                New leads · this week
              </div>
              <div className="flex items-end gap-1.5 h-16">
                {MOCK_WEEK_DATA.map(({ day, leads }) => (
                  <div key={day} className="flex flex-1 flex-col items-center gap-1">
                    <div
                      className="w-full rounded-sm bg-glow/30 transition-all duration-500"
                      style={{ height: `${(leads / MOCK_MAX) * 100}%`, minHeight: 2 }}
                    />
                    <span className="font-mono text-[8px] text-faint">{day}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 font-mono text-[10px] text-muted">
                <span className="text-glow tabular-nums">7</span> total ·{' '}
                <span className="text-success">↑ 40%</span> vs last week
              </div>
            </div>

            {/* Conversation */}
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              <div className="flex flex-col gap-3">
                {MOCK_CONVERSATION.map((msg, i) =>
                  msg.role === 'user' ? (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[80%] rounded-card bg-accent px-3.5 py-2.5 [box-shadow:var(--shadow-glow)]">
                        <p className="text-sm leading-relaxed text-ink">{msg.text}</p>
                      </div>
                    </div>
                  ) : (
                    <div key={i} className="flex justify-start">
                      <div className="max-w-[88%] rounded-card border border-glow/20 bg-raised px-3.5 py-2.5">
                        <div className="mb-1.5 flex items-center gap-1.5">
                          <span className="text-[9px] text-glow" aria-hidden>✦</span>
                          <span className="font-mono text-[9px] uppercase tracking-wide text-glow">Nexus</span>
                        </div>
                        <p className="text-sm leading-relaxed text-ink">{msg.text}</p>
                      </div>
                    </div>
                  ),
                )}
              </div>
            </div>

            {/* Input area */}
            <div className="border-t border-line px-5 py-4">
              <div className="flex items-center gap-2 rounded-control border border-line bg-bg/60 px-3.5 py-2.5 focus-within:border-glow/40">
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Ask about your community…"
                  className="flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint"
                  aria-label="Query the Nexus Data Analyst"
                />
                <button
                  type="button"
                  disabled
                  title="NLP query engine — coming soon"
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-control bg-glow/20 text-glow opacity-50"
                >
                  <Icon name="send" size={12} />
                </button>
              </div>
              <p className="mt-2 text-center font-mono text-[9px] text-faint">
                NLP-to-graph engine · coming in the next workstream
              </p>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

