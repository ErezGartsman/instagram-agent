import { useEffect, useRef } from 'react'
import type { ReactNode, RefObject } from 'react'
import { Link } from 'react-router-dom'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { CinematicHero } from '@/components/ui/cinematic-landing-hero'
import { NexusLogo } from '@/components/ui/nexus-logo'
import { NexusParticles } from './NexusParticles'

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger)
}

/**
 * The public face of Nexus — a manifesto made physical, not a sales page.
 *
 * Scene map (from the landing narrative brief):
 *   1–2  CinematicHero  — pinned GSAP theatre: thesis → the instrument card → tension
 *   3    Dividing Line  — WebGL particle field: lattice (machine) flows into wave (human)
 *   4    Intelligence   — "Ask it anything. It only ever tells you what's true."
 *   5    Memory         — Person-360: Goal · Tension · Essence
 *   6    Work Queue     — the re-rank, performed live as you scroll
 *   7    Guarantee      — it drafts; you decide; it never speaks for you
 *   8    Who it's for   — one practitioner, total command
 *   9    Close          — the manifesto couplet + the quiet door
 *
 * All theatre respects prefers-reduced-motion (static scenes, no pin, no WebGL
 * loop). Lazy-loaded route: gsap + three never touch the cockpit bundle.
 */

const EASE = 'power3.out'

function prefersReduced(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// ── Reveal hook — blur-rise for a section's [data-reveal] children ─────────────
function useReveal(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (prefersReduced()) return
    const el = ref.current
    if (!el) return
    const ctx = gsap.context(() => {
      const targets = el.querySelectorAll('[data-reveal]')
      gsap.fromTo(
        targets,
        { autoAlpha: 0, y: 42, filter: 'blur(14px)' },
        {
          autoAlpha: 1,
          y: 0,
          filter: 'blur(0px)',
          duration: 1.1,
          stagger: 0.12,
          ease: EASE,
          scrollTrigger: { trigger: el, start: 'top 72%', toggleActions: 'play none none reverse' },
        },
      )
    }, el)
    return () => ctx.revert()
  }, [ref])
}

// ── Shared scene primitives ────────────────────────────────────────────────────
function Kicker({ children }: { children: ReactNode }) {
  return (
    <p data-reveal className="mb-6 font-mono text-[10px] uppercase tracking-[0.45em] text-[#60a5fa]">
      {children}
    </p>
  )
}

function Headline({ children, serif = false }: { children: ReactNode; serif?: boolean }) {
  return (
    <h2
      data-reveal
      className={`max-w-3xl text-balance text-[clamp(1.9rem,4.6vw,3.6rem)] font-bold leading-[1.06] tracking-tight text-[#f2f6ff] ${
        serif ? 'font-serif font-light italic' : ''
      }`}
      style={serif ? { fontFamily: 'Fraunces, Georgia, serif' } : undefined}
    >
      {children}
    </h2>
  )
}

function Body({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <p data-reveal className={`mt-7 max-w-xl text-[15px] font-light leading-relaxed text-[#9aa7bd] md:text-[17px] ${className}`}>
      {children}
    </p>
  )
}

function Micro({ children }: { children: ReactNode }) {
  return (
    <p data-reveal className="mt-6 font-mono text-[11px] uppercase tracking-[0.25em] text-[#55617a]">
      {children}
    </p>
  )
}

// ── The glowing thread — draws itself down the manifesto as you scroll ────────
function SceneThread({ containerRef }: { containerRef: RefObject<HTMLDivElement | null> }) {
  const pathRef = useRef<SVGPathElement>(null)

  useEffect(() => {
    if (prefersReduced()) return
    const path = pathRef.current
    const container = containerRef.current
    if (!path || !container) return
    const len = path.getTotalLength()
    gsap.set(path, { strokeDasharray: len, strokeDashoffset: len })
    const tween = gsap.to(path, {
      strokeDashoffset: 0,
      ease: 'none',
      scrollTrigger: { trigger: container, start: 'top 65%', end: 'bottom bottom', scrub: 0.6 },
    })
    return () => {
      tween.scrollTrigger?.kill()
      tween.kill()
    }
  }, [containerRef])

  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 1000 5000"
      preserveAspectRatio="none"
      aria-hidden
    >
      <defs>
        <linearGradient id="nx-thread" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#60a5fa" stopOpacity="0.9" />
          <stop offset="0.45" stopColor="#3b82f6" stopOpacity="0.65" />
          <stop offset="0.8" stopColor="#2dd4bf" stopOpacity="0.75" />
          <stop offset="1" stopColor="#c9a24a" stopOpacity="0.9" />
        </linearGradient>
        <filter id="nx-thread-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {/* One continuous line: philosophy → intelligence → memory → queue →
          guarantee → who → straight plumb drop into the close/door. */}
      <path
        ref={pathRef}
        d="M 500 0
           C 500 240, 262 340, 252 580
           C 242 820, 732 900, 742 1140
           C 752 1380, 268 1470, 258 1710
           C 248 1950, 736 2040, 746 2280
           C 756 2520, 290 2610, 282 2850
           C 274 3090, 718 3180, 724 3420
           C 730 3660, 505 3760, 501 4000
           C 498 4200, 500 4600, 500 5000"
        fill="none"
        stroke="url(#nx-thread)"
        strokeWidth="1.6"
        filter="url(#nx-thread-glow)"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

// ── Scene 3 — the Dividing Line (WebGL centerpiece) ────────────────────────────
function DividingLineScene() {
  const ref = useRef<HTMLElement>(null)
  useReveal(ref)
  return (
    <section id="philosophy" ref={ref} className="relative flex min-h-screen scroll-mt-16 flex-col items-center justify-center overflow-hidden px-6 py-24 text-center">
      <NexusParticles />
      {/* Legibility vignette — dims the additive particles behind the statement */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 h-[70vh] w-[92vw] max-w-[1100px] -translate-x-1/2 -translate-y-1/2"
        style={{ background: 'radial-gradient(ellipse at center, rgba(4,7,15,0.82) 0%, rgba(4,7,15,0.45) 48%, transparent 72%)' }}
      />
      <div className="relative z-10 flex flex-col items-center">
        <Kicker>The philosophy</Kicker>
        <h2 data-reveal className="text-balance text-[clamp(2.2rem,6vw,5rem)] font-bold leading-[1.05] tracking-tight">
          <span className="text-[#f2f6ff]">The Machine </span>
          <span className="inline-block bg-gradient-to-r from-[#60a5fa] to-[#3b82f6] bg-clip-text pb-[0.08em] font-extrabold text-transparent">organizes.</span>
          <br />
          <span
            className="font-light italic text-[#f2f6ff]"
            style={{ fontFamily: 'Fraunces, Georgia, serif' }}
          >
            The Human{' '}
            <span className="inline-block bg-gradient-to-r from-[#5eead4] to-[#2dd4bf] bg-clip-text pb-[0.08em] text-transparent">consults.</span>
          </span>
        </h2>
        <Body className="mx-auto text-center">
          Everything cold — memory, ranking, timing, data — belongs to the machine.
          Everything warm — judgment, care, the actual conversation — stays with the
          person. Nexus is that line, drawn cleanly.
        </Body>
      </div>
    </section>
  )
}

// ── Scene 4 — the Intelligence ─────────────────────────────────────────────────
function IntelligenceScene() {
  const ref = useRef<HTMLElement>(null)
  useReveal(ref)
  return (
    <section id="intelligence" ref={ref} className="relative mx-auto flex min-h-[90vh] max-w-6xl scroll-mt-16 flex-col items-center gap-14 px-6 py-24 lg:flex-row lg:gap-24">
      <div className="flex-1">
        <Kicker>The intelligence</Kicker>
        <Headline>Ask it anything. It only ever tells you what&rsquo;s true.</Headline>
        <Body>
          Nexus has a mind of its own — a planner that reasons over your live data and
          answers in plain language. It never guesses, never invents a number, never
          fills a silence with a story. If it doesn&rsquo;t know, it says so.
        </Body>
        <Micro>It can see everything. It can change nothing.</Micro>
      </div>

      {/* Chat vignette — a grounded answer crystallizing */}
      <div data-reveal className="w-full max-w-md flex-1">
        <div className="rounded-2xl border border-[rgba(148,186,255,0.08)] bg-[rgba(148,186,255,0.045)] p-5 shadow-[0_0_40px_rgba(59,130,246,0.12)] backdrop-blur-xl">
          <div className="mb-4 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[#60a5fa] shadow-[0_0_6px_rgba(96,165,250,0.9)]" />
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[#60a5fa]">Nexus AI</span>
          </div>
          <div className="mb-3 flex justify-end">
            <div className="rounded-2xl rounded-br-sm bg-[#3b82f6] px-3.5 py-2.5 text-sm text-white shadow-[0_0_16px_rgba(59,130,246,0.4)]">
              Who&rsquo;s been waiting on me the longest?
            </div>
          </div>
          <div className="flex justify-start">
            <div className="w-full rounded-2xl rounded-bl-sm border border-[rgba(96,165,250,0.15)] bg-[rgba(148,186,255,0.06)] px-3.5 py-3 text-sm text-[#f2f6ff]">
              <p className="leading-relaxed">
                Three people are waiting on you. The longest is
                <span className="font-semibold"> 26 hours</span> — qualified, then quiet.
              </p>
              <div className="mt-3 space-y-1.5 rounded-lg border border-[rgba(148,186,255,0.08)] bg-[#04070f]/80 p-3">
                {[
                  { init: 'M', hours: '26h', pct: 92 },
                  { init: 'D', hours: '14h', pct: 58 },
                  { init: 'N', hours: '6h', pct: 31 },
                ].map((row) => (
                  <div key={row.init} className="flex items-center gap-2">
                    <span className="w-4 shrink-0 font-mono text-[10px] text-[#55617a]">{row.init}</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[rgba(148,186,255,0.08)]">
                      <div className="h-full rounded-full bg-[#3b82f6]" style={{ width: `${row.pct}%`, opacity: 0.85 }} />
                    </div>
                    <span className="w-8 shrink-0 text-right font-mono text-[10px] tabular-nums text-[#9aa7bd]">{row.hours}</span>
                  </div>
                ))}
              </div>
              <p className="mt-3 font-mono text-[9px] uppercase tracking-wider text-[#55617a]">
                Grounded in live data · nothing invented
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

// ── Scene 5 — the Memory ───────────────────────────────────────────────────────
function MemoryScene() {
  const ref = useRef<HTMLElement>(null)
  useReveal(ref)
  const facets = [
    { label: 'Goal', body: 'Decide before the anniversary.', tone: '#60a5fa' },
    { label: 'Tension', body: 'Guilt vs. relief.', tone: '#2dd4bf' },
    { label: 'Essence', body: 'She isn’t afraid of leaving. She’s afraid of being the one who broke it.', tone: '#f2f6ff', serif: true },
  ]
  return (
    <section id="memory" ref={ref} className="relative mx-auto flex min-h-[90vh] max-w-6xl scroll-mt-16 flex-col items-center gap-14 px-6 py-24 lg:flex-row-reverse lg:gap-24">
      <div className="flex-1">
        <Kicker>The memory</Kicker>
        <Headline>Every person, held — not filed.</Headline>
        <Body>
          No one here is a row in a spreadsheet. Nexus keeps a living picture of each
          person: what they&rsquo;re reaching for, what&rsquo;s holding them back, who
          they are beneath the message.
        </Body>
        <Micro>Goal · Tension · Essence</Micro>
      </div>

      <div className="w-full max-w-md flex-1 space-y-4">
        {facets.map((f) => (
          <div
            key={f.label}
            data-reveal
            className="rounded-2xl border border-[rgba(148,186,255,0.08)] bg-[rgba(148,186,255,0.045)] p-5 backdrop-blur-xl"
            style={{ boxShadow: `0 0 32px ${f.tone}14, inset 0 1px 0 rgba(190,214,255,0.08)` }}
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="h-1 w-1 rounded-full" style={{ background: f.tone, boxShadow: `0 0 6px ${f.tone}` }} />
              <span className="font-mono text-[10px] uppercase tracking-[0.2em]" style={{ color: f.tone }}>{f.label}</span>
            </div>
            <p
              className={f.serif ? 'text-lg font-light italic leading-snug text-[#f2f6ff]' : 'text-[15px] text-[#d7e0f2]'}
              style={f.serif ? { fontFamily: 'Fraunces, Georgia, serif' } : undefined}
            >
              {f.body}
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}

// ── Scene 6 — the Work Queue re-rank, performed live ───────────────────────────
function QueueScene() {
  const ref = useRef<HTMLElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  useReveal(ref)

  useEffect(() => {
    if (prefersReduced()) return
    const list = listRef.current
    if (!list) return
    const rows = list.querySelectorAll<HTMLElement>('[data-qrow]')
    if (rows.length < 3) return
    const STEP = rows[1].offsetTop - rows[0].offsetTop || 76

    const ctx = gsap.context(() => {
      // The third person (waiting on YOU) rises to the top; the others yield.
      const tl = gsap.timeline({
        scrollTrigger: { trigger: list, start: 'top 65%', toggleActions: 'play none none reverse' },
        delay: 0.5,
      })
      tl.to(rows[2], { y: -STEP * 2, duration: 0.7, ease: 'power3.inOut' })
        .to(rows[0], { y: STEP, duration: 0.7, ease: 'power3.inOut' }, '<')
        .to(rows[1], { y: STEP, duration: 0.7, ease: 'power3.inOut' }, '<')
        .fromTo(
          rows[2],
          { boxShadow: '0 0 0px rgba(96,165,250,0)' },
          { boxShadow: '0 0 28px rgba(96,165,250,0.35)', duration: 0.4, yoyo: true, repeat: 1 },
          '-=0.2',
        )
    }, list)
    return () => ctx.revert()
  }, [])

  const rows = [
    { name: 'D.R.', note: 'replied an hour ago', chip: 'Their move', tone: '#2dd4bf' },
    { name: 'N.L.', note: 'newly engaged', chip: 'Their move', tone: '#2dd4bf' },
    { name: 'M.G.', note: 'qualified, then quiet — 26h', chip: 'Your move', tone: '#60a5fa' },
  ]

  return (
    <section id="queue" ref={ref} className="relative mx-auto flex min-h-[90vh] max-w-6xl scroll-mt-16 flex-col items-center gap-14 px-6 py-24 lg:flex-row lg:gap-24">
      <div className="flex-1">
        <Kicker>The queue</Kicker>
        <Headline>It knows whose move it is.</Headline>
        <Body>
          Nexus doesn&rsquo;t measure how long a card has sat in a column. It measures
          the only thing that matters — how long someone has been waiting on you. It
          remembers every time you reached out, notices every time they replied, and
          quietly lifts the person who needs you next to the top.
        </Body>
        <Micro>Your move, or theirs. Always honest about which.</Micro>
      </div>

      <div data-reveal className="w-full max-w-md flex-1">
        <div ref={listRef} className="space-y-3">
          {rows.map((r) => (
            <div
              key={r.name}
              data-qrow
              className="flex items-center gap-3 rounded-2xl border border-[rgba(148,186,255,0.08)] bg-[rgba(148,186,255,0.045)] px-4 py-3.5 backdrop-blur-xl"
            >
              <span
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full font-mono text-xs font-semibold"
                style={{ color: r.tone, background: `${r.tone}1f`, border: `1px solid ${r.tone}40` }}
              >
                {r.name}
              </span>
              <div className="min-w-0 flex-1">
                <div className="h-2 w-24 rounded-full bg-[#9aa7bd]/70" />
                <div className="mt-1.5 font-mono text-[10px] text-[#55617a]">{r.note}</div>
              </div>
              <span
                className="shrink-0 rounded-full px-2.5 py-1 font-mono text-[9px] font-bold uppercase tracking-wider"
                style={{ color: r.tone, background: `${r.tone}14`, border: `1px solid ${r.tone}33` }}
              >
                {r.chip}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-4 text-center font-mono text-[10px] uppercase tracking-[0.2em] text-[#55617a]">
          watch the re-rank — that&rsquo;s the whole product
        </p>
      </div>
    </section>
  )
}

// ── Scene 7 — the Guarantee ────────────────────────────────────────────────────
function GuaranteeScene() {
  const ref = useRef<HTMLElement>(null)
  useReveal(ref)
  return (
    <section id="guarantee" ref={ref} className="relative mx-auto flex min-h-[90vh] max-w-6xl scroll-mt-16 flex-col items-center gap-14 px-6 py-24 lg:flex-row-reverse lg:gap-24">
      <div className="flex-1">
        <Kicker>The guarantee</Kicker>
        <Headline>It drafts. You decide. It never speaks for you.</Headline>
        <Body>
          Nexus will write the message — in your voice, grounded in the real
          conversation — and then it stops, and hands you the pen. Nothing is ever
          sent on your behalf. The warmth has to be yours. The machine only makes
          sure it&rsquo;s never late.
        </Body>
      </div>

      <div data-reveal className="w-full max-w-md flex-1">
        <div className="rounded-2xl border border-[rgba(148,186,255,0.08)] bg-[rgba(148,186,255,0.045)] p-5 backdrop-blur-xl shadow-[0_0_40px_rgba(45,212,191,0.10)]">
          <div className="mb-3 flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[#2dd4bf]">✎ Draft · your voice</span>
            <span className="font-mono text-[9px] text-[#55617a]">never auto-sent</span>
          </div>
          <div className="rounded-xl border border-[rgba(148,186,255,0.08)] bg-[#04070f]/80 p-4 text-[15px] font-light leading-relaxed text-[#d7e0f2]">
            Hi Maya — I read what you wrote, and I understand. That&rsquo;s not an easy
            place to be. I have room this week for a first conversation, if you&rsquo;d
            like.
            <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-[3px] animate-pulse bg-[#2dd4bf]" aria-hidden />
          </div>
          <div className="mt-4 flex items-center justify-between">
            <span className="font-mono text-[10px] text-[#55617a]">the machine stops here</span>
            <span className="rounded-lg border border-[#2dd4bf]/30 bg-[#2dd4bf]/10 px-4 py-2 font-mono text-[11px] font-semibold text-[#2dd4bf]">
              You send it →
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}

// ── Scene 8 — who it's for ─────────────────────────────────────────────────────
function WhoScene() {
  const ref = useRef<HTMLElement>(null)
  useReveal(ref)
  return (
    <section ref={ref} className="relative mx-auto flex min-h-[70vh] max-w-3xl flex-col items-center justify-center px-6 py-24 text-center">
      <Kicker>Who it&rsquo;s for</Kicker>
      <Headline>Built for one person doing work that deserves full attention.</Headline>
      <Body className="mx-auto text-center">
        Nexus isn&rsquo;t here to scale you into a call center. It&rsquo;s built for a
        single practitioner who refuses to let the human part slip — and needs an
        instrument dense enough, fast enough, and honest enough to make that possible.
      </Body>
      <Micro>One operator. Total command. Nothing lost.</Micro>
    </section>
  )
}

// ── Scene 9 — the close ────────────────────────────────────────────────────────
function CloseScene() {
  const ref = useRef<HTMLElement>(null)
  useReveal(ref)
  return (
    <section ref={ref} className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 py-32 text-center">
      {/* Final ambient pool */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 h-[640px] w-[640px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ background: 'radial-gradient(circle, rgba(59,130,246,0.14) 0%, transparent 70%)' }}
      />
      <div className="relative z-10 flex flex-col items-center">
        {/* The thread arrives — the plumb finds its weight at the door. */}
        <div data-reveal aria-hidden className="mb-12 flex flex-col items-center">
          <span className="block h-14 w-px bg-gradient-to-b from-transparent via-[#2dd4bf] to-[#c9a24a]" />
          <span
            className="mt-1 h-3.5 w-3.5 rounded-full"
            style={{
              background: 'radial-gradient(circle at 35% 28%, #ecd08a 0%, #c9a24a 45%, #7a5c1c 100%)',
              boxShadow: '0 0 16px rgba(201,162,74,0.45)',
            }}
          />
        </div>
        <p
          data-reveal
          className="max-w-3xl text-balance text-[clamp(1.7rem,4vw,3rem)] font-light italic leading-snug text-[#f2f6ff]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          The machine remembers, so you don&rsquo;t have to.
        </p>
        <p
          data-reveal
          className="mt-4 max-w-3xl text-balance text-[clamp(1.7rem,4vw,3rem)] font-light italic leading-snug text-[#9aa7bd]"
          style={{ fontFamily: 'Fraunces, Georgia, serif' }}
        >
          You show up, so the machine never has to pretend to be you.
        </p>

        <p data-reveal className="mt-16 font-mono text-[11px] uppercase tracking-[0.5em] text-[#60a5fa]">
          NEXUS
        </p>

        <div data-reveal className="mt-10">
          <Link
            to="/app"
            className="group inline-flex items-center gap-2.5 rounded-xl border border-[#3b82f6]/40 bg-[#3b82f6]/10 px-7 py-3.5 text-sm font-medium text-[#dbe7ff] backdrop-blur-xl transition-all duration-300 hover:border-[#60a5fa]/60 hover:bg-[#3b82f6]/20 hover:shadow-[0_0_32px_rgba(59,130,246,0.35)]"
          >
            Enter the command center
            <span className="transition-transform duration-300 group-hover:translate-x-1">→</span>
          </Link>
        </div>
      </div>
    </section>
  )
}

// ── Persistent glass nav — the SaaS anchor ─────────────────────────────────────
const NAV_LINKS = [
  { label: 'The Philosophy', target: 'philosophy' },
  { label: 'The Intelligence', target: 'intelligence' },
  { label: 'The Memory', target: 'memory' },
  { label: 'The Queue', target: 'queue' },
]

function LandingNav() {
  const jump = (target: string) => {
    document.getElementById(target)?.scrollIntoView({ behavior: prefersReduced() ? 'auto' : 'smooth', block: 'start' })
  }
  return (
    <nav className="fixed inset-x-0 top-0 z-[60] flex h-16 items-center justify-between border-b border-[rgba(148,186,255,0.07)] bg-[#04070f]/45 px-5 backdrop-blur-md md:px-8">
      <div className="flex items-center gap-3">
        <NexusLogo size={34} className="text-[#f2f6ff]" />
        <span className="font-mono text-[12px] font-semibold uppercase tracking-[0.35em] text-[#f2f6ff]">
          NEXUS
        </span>
      </div>

      <div className="hidden items-center gap-7 md:flex">
        {NAV_LINKS.map((l) => (
          <button
            key={l.target}
            type="button"
            onClick={() => jump(l.target)}
            className="bg-transparent text-[13px] font-medium text-[#9aa7bd] transition-colors duration-200 hover:text-white"
          >
            {l.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2.5">
        <Link
          to="/app"
          className="rounded-lg px-3.5 py-2 text-[13px] font-medium text-[#9aa7bd] transition-colors duration-200 hover:text-[#f2f6ff]"
        >
          Sign in
        </Link>
        <Link
          to="/app"
          className="rounded-lg bg-[#3b82f6] px-4 py-2 text-[13px] font-medium text-white transition-colors duration-200 hover:bg-[#2f74e8]"
        >
          Sign up for free
        </Link>
      </div>
    </nav>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export function LandingPage() {
  const threadRef = useRef<HTMLDivElement>(null)

  // Landing owns the whole viewport — kill any inherited margin/scroll quirks.
  useEffect(() => {
    document.title = 'Nexus — the logic machine meets the human hand'
    // Recalculate trigger positions once fonts/layout settle under the pinned hero.
    const t = setTimeout(() => ScrollTrigger.refresh(), 400)
    return () => clearTimeout(t)
  }, [])

  return (
    <div className="landing-midnight relative min-h-screen w-full overflow-x-clip bg-[#04070f] text-[#f2f6ff] antialiased">
      <LandingNav />

      {/* Scenes 1–2 — the pinned cinematic theatre */}
      <CinematicHero />

      {/* Scenes 3–9 — the manifesto, stitched by the glowing thread */}
      <div ref={threadRef} className="relative">
        <SceneThread containerRef={threadRef} />
        <DividingLineScene />
        <IntelligenceScene />
        <MemoryScene />
        <QueueScene />
        <GuaranteeScene />
        <WhoScene />
        <CloseScene />
      </div>

      <footer className="border-t border-[rgba(148,186,255,0.07)] px-6 py-10 text-center">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-[#55617a]">
          Nexus — a private instrument. The machine remembers; the human shows up.
        </p>
      </footer>
    </div>
  )
}
