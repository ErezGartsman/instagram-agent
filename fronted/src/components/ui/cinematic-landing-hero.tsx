// src/components/ui/cinematic-landing-hero.tsx
//
// The Nexus cinematic hero — a pinned GSAP scroll theatre, ~3 viewport-heights
// of choreography: the thesis ignites → the physical deep-navy card rises and
// swallows the viewport → the instrument (a 3D phone running the Work Queue)
// swings in with mouse parallax → confidence counts in, badges assemble →
// everything pulls back and hands the page to the manifesto scenes below.
//
// Adapted from a 21st.dev cinematic hero: re-souled to Midnight Instrument
// (#04070f void, electric blue #3b82f6/#60a5fa), copy from the Nexus landing
// brief, store buttons removed (this is a private instrument, not an app
// launch), and the phone screen rebuilt as the Nexus accountability queue.
//
// prefers-reduced-motion: the theatre never mounts — the hero renders as a
// single static viewport with the thesis, and the scenes below carry the story.

import React, { useEffect, useRef, useState } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { cn } from '@/lib/utils'

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger)
}

const INJECTED_STYLES = `
  .gsap-reveal { visibility: hidden; }

  /* Environment overlays */
  .nx-film-grain {
      position: absolute; inset: 0; width: 100%; height: 100%;
      pointer-events: none; z-index: 50; opacity: 0.05; mix-blend-mode: overlay;
      background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg"><filter id="noiseFilter"><feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="3" stitchTiles="stitch"/></filter><rect width="100%" height="100%" filter="url(%23noiseFilter)"/></svg>');
  }

  .nx-grid {
      background-size: 60px 60px;
      background-image:
          linear-gradient(to right, rgba(148,186,255,0.05) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(148,186,255,0.05) 1px, transparent 1px);
      mask-image: radial-gradient(ellipse at center, black 0%, transparent 70%);
      -webkit-mask-image: radial-gradient(ellipse at center, black 0%, transparent 70%);
  }

  /* Physical typography — cool ink with electric depth */
  .nx-text-3d {
      color: #f2f6ff;
      text-shadow:
          0 10px 30px rgba(59,130,246,0.25),
          0 2px 4px rgba(4,7,15,0.6);
  }

  .nx-text-silver {
      background: linear-gradient(180deg, #f2f6ff 0%, #7d8db0 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      transform: translateZ(0);
      filter:
          drop-shadow(0px 10px 20px rgba(59,130,246,0.20))
          drop-shadow(0px 2px 4px rgba(4,7,15,0.5));
  }

  .nx-card-silver {
      background: linear-gradient(180deg, #FFFFFF 0%, #9aa7bd 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      transform: translateZ(0);
      filter:
          drop-shadow(0px 12px 24px rgba(0,0,0,0.8))
          drop-shadow(0px 4px 8px rgba(0,0,0,0.6));
  }

  /* The physical deep-navy card with dynamic mouse lighting */
  .nx-depth-card {
      background: linear-gradient(145deg, #10275f 0%, #050a18 100%);
      box-shadow:
          0 40px 100px -20px rgba(0, 0, 0, 0.9),
          0 20px 40px -20px rgba(0, 0, 0, 0.8),
          0 0 80px -20px rgba(59, 130, 246, 0.25),
          inset 0 1px 2px rgba(190, 214, 255, 0.2),
          inset 0 -2px 4px rgba(0, 0, 0, 0.8);
      border: 1px solid rgba(148, 186, 255, 0.06);
      position: relative;
  }

  .nx-card-sheen {
      position: absolute; inset: 0; border-radius: inherit; pointer-events: none; z-index: 50;
      background: radial-gradient(800px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), rgba(148,186,255,0.07) 0%, transparent 40%);
      mix-blend-mode: screen; transition: opacity 0.3s ease;
  }

  /* Instrument hardware (the phone) */
  .nx-bezel {
      background-color: #0a0f1c;
      box-shadow:
          inset 0 0 0 2px #3a4763,
          inset 0 0 0 7px #000,
          0 40px 80px -15px rgba(0,0,0,0.9),
          0 15px 25px -5px rgba(0,0,0,0.7),
          0 0 60px -10px rgba(59,130,246,0.35);
      transform-style: preserve-3d;
  }

  .nx-hw-btn {
      background: linear-gradient(90deg, #2c3650 0%, #0c1220 100%);
      box-shadow:
          -2px 0 5px rgba(0,0,0,0.8),
          inset -1px 0 1px rgba(190,214,255,0.15),
          inset 1px 0 2px rgba(0,0,0,0.8);
      border-left: 1px solid rgba(190,214,255,0.05);
  }

  .nx-glare {
      background: linear-gradient(110deg, rgba(190,214,255,0.08) 0%, rgba(190,214,255,0) 45%);
  }

  .nx-widget {
      background: linear-gradient(180deg, rgba(148,186,255,0.05) 0%, rgba(148,186,255,0.01) 100%);
      box-shadow:
          0 10px 20px rgba(0,0,0,0.3),
          inset 0 1px 1px rgba(190,214,255,0.06),
          inset 0 -1px 1px rgba(0,0,0,0.5);
      border: 1px solid rgba(148,186,255,0.04);
  }

  .nx-badge {
      background: linear-gradient(135deg, rgba(148, 186, 255, 0.09) 0%, rgba(148, 186, 255, 0.01) 100%);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      box-shadow:
          0 0 0 1px rgba(148, 186, 255, 0.1),
          0 25px 50px -12px rgba(0, 0, 0, 0.8),
          inset 0 1px 1px rgba(190,214,255,0.2),
          inset 0 -1px 1px rgba(0,0,0,0.5);
  }

  /* bg-clip-text clips at the content box — reserve room for descenders */
  .nx-text-silver, .nx-card-silver { padding-bottom: 0.1em; }
  /* …and horizontally: negative tracking is applied after the LAST glyph too,
     so the measured text box ends ~0.05em inside the final letter's ink — the
     gradient stops there and the "S" of NEXUS lost its right edge. */
  .nx-card-silver { padding-right: 0.08em; }

  .nx-ring {
      transform: rotate(-90deg);
      transform-origin: center;
      stroke-dasharray: 402;
      stroke-dashoffset: 402;
      stroke-linecap: round;
      filter: drop-shadow(0 0 6px rgba(96,165,250,0.7));
  }

  @media (prefers-reduced-motion: reduce) {
    .gsap-reveal { visibility: visible; }
  }
`

export interface CinematicHeroProps extends React.HTMLAttributes<HTMLDivElement> {
  brandName?: string
  tagline1?: string
  tagline2?: string
  subhead?: string
  cardHeading?: string
  cardDescription?: React.ReactNode
  metricValue?: number
  metricLabel?: string
  outroHeading?: string
  outroDescription?: string
}

export function CinematicHero({
  brandName = 'NEXUS',
  tagline1 = 'The logic machine',
  tagline2 = 'meets the human hand.',
  subhead = 'A private command center for relationship work. The machine remembers, ranks, and clears the noise — so the person doing the work can stay entirely human.',
  cardHeading = 'It knows whose move it is.',
  cardDescription = (
    <>
      Nexus measures the only thing that matters — how long someone has been
      waiting on <span className="text-white font-semibold">you</span>. It
      remembers every time you reached out, notices every reply, and quietly
      lifts the person who needs you next to the top.
    </>
  ),
  metricValue = 88,
  metricLabel = 'Confidence',
  outroHeading = "The work that matters can't be automated.",
  outroDescription = 'Real relationships don’t fit inside a funnel. But the logistics around them — who reached out, when, what was said, whose turn it is — will bury you if you let them. Most tools automate the human away. This one does the opposite.',
  className,
  ...props
}: CinematicHeroProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mainCardRef = useRef<HTMLDivElement>(null)
  const mockupRef = useRef<HTMLDivElement>(null)
  const requestRef = useRef<number>(0)
  const [reduced] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  // High-performance mouse parallax on the instrument (rAF-throttled).
  useEffect(() => {
    if (reduced) return
    const handleMouseMove = (e: MouseEvent) => {
      if (window.scrollY > window.innerHeight * 2) return
      cancelAnimationFrame(requestRef.current)
      requestRef.current = requestAnimationFrame(() => {
        if (mainCardRef.current && mockupRef.current) {
          const rect = mainCardRef.current.getBoundingClientRect()
          mainCardRef.current.style.setProperty('--mouse-x', `${e.clientX - rect.left}px`)
          mainCardRef.current.style.setProperty('--mouse-y', `${e.clientY - rect.top}px`)

          const xVal = (e.clientX / window.innerWidth - 0.5) * 2
          const yVal = (e.clientY / window.innerHeight - 0.5) * 2
          gsap.to(mockupRef.current, {
            rotationY: xVal * 12,
            rotationX: -yVal * 12,
            ease: 'power3.out',
            duration: 1.2,
          })
        }
      })
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      cancelAnimationFrame(requestRef.current)
    }
  }, [reduced])

  // The cinematic scroll timeline.
  useEffect(() => {
    if (reduced) return
    const isMobile = window.innerWidth < 768

    const ctx = gsap.context(() => {
      gsap.set('.text-track', { autoAlpha: 0, y: 60, scale: 0.85, filter: 'blur(20px)', rotationX: -20 })
      gsap.set('.text-days', { autoAlpha: 1, clipPath: 'inset(0 100% 0 0)' })
      gsap.set('.hero-subhead', { autoAlpha: 0, y: 24 })
      gsap.set('.main-card', { y: window.innerHeight + 200, autoAlpha: 1 })
      gsap.set(['.card-left-text', '.card-right-text', '.mockup-scroll-wrapper', '.floating-badge', '.phone-widget'], { autoAlpha: 0 })
      gsap.set('.cta-wrapper', { autoAlpha: 0, scale: 0.8, filter: 'blur(30px)' })

      const introTl = gsap.timeline({ delay: 0.25 })
      introTl
        .to('.text-track', { duration: 1.8, autoAlpha: 1, y: 0, scale: 1, filter: 'blur(0px)', rotationX: 0, ease: 'expo.out' })
        .to('.text-days', { duration: 1.4, clipPath: 'inset(0 0% 0 0)', ease: 'power4.inOut' }, '-=1.0')
        .to('.hero-subhead', { duration: 1.0, autoAlpha: 1, y: 0, ease: 'power3.out' }, '-=0.8')

      const scrollTl = gsap.timeline({
        scrollTrigger: {
          trigger: containerRef.current,
          start: 'top top',
          // Tightened 2026-07-06 (Erez: scroll friction too high) — the whole
          // theatre now clears in ~2.5 viewport-heights of scrolling.
          end: '+=3600',
          pin: true,
          scrub: 0.8,
          anticipatePin: 1,
        },
      })

      scrollTl
        .to(['.hero-text-wrapper', '.nx-grid'], { scale: 1.15, filter: 'blur(20px)', opacity: 0.2, ease: 'power2.inOut', duration: 2 }, 0)
        .to('.main-card', { y: 0, ease: 'power3.inOut', duration: 2 }, 0)
        .to('.main-card', { width: '100%', height: '100%', borderRadius: '0px', ease: 'power3.inOut', duration: 1.5 })
        .fromTo('.mockup-scroll-wrapper',
          { y: 300, z: -500, rotationX: 50, rotationY: -30, autoAlpha: 0, scale: 0.6 },
          { y: 0, z: 0, rotationX: 0, rotationY: 0, autoAlpha: 1, scale: 1, ease: 'expo.out', duration: 2.5 }, '-=0.8',
        )
        .fromTo('.phone-widget', { y: 40, autoAlpha: 0, scale: 0.95 }, { y: 0, autoAlpha: 1, scale: 1, stagger: 0.15, ease: 'back.out(1.2)', duration: 1.5 }, '-=1.5')
        .to('.nx-ring', { strokeDashoffset: 402 * (1 - metricValue / 100), duration: 2, ease: 'power3.inOut' }, '-=1.2')
        .to('.counter-val', { innerHTML: metricValue, snap: { innerHTML: 1 }, duration: 2, ease: 'expo.out' }, '-=2.0')
        .fromTo('.floating-badge', { y: 100, autoAlpha: 0, scale: 0.7, rotationZ: -10 }, { y: 0, autoAlpha: 1, scale: 1, rotationZ: 0, ease: 'back.out(1.5)', duration: 1.5, stagger: 0.2 }, '-=2.0')
        .fromTo('.card-left-text', { x: -50, autoAlpha: 0 }, { x: 0, autoAlpha: 1, ease: 'power4.out', duration: 1.5 }, '-=1.5')
        .fromTo('.card-right-text', { x: 50, autoAlpha: 0, scale: 0.8 }, { x: 0, autoAlpha: 1, scale: 1, ease: 'expo.out', duration: 1.5 }, '<')
        .to({}, { duration: 1.1 })
        .set('.hero-text-wrapper', { autoAlpha: 0 })
        .set('.cta-wrapper', { autoAlpha: 1 })
        .to({}, { duration: 0.6 })
        .to(['.mockup-scroll-wrapper', '.floating-badge', '.card-left-text', '.card-right-text'], {
          scale: 0.9, y: -40, z: -200, autoAlpha: 0, ease: 'power3.in', duration: 1.2, stagger: 0.05,
        })
        .to('.main-card', {
          width: isMobile ? '92vw' : '85vw',
          height: isMobile ? '92vh' : '85vh',
          borderRadius: isMobile ? '32px' : '40px',
          ease: 'expo.inOut',
          duration: 1.8,
        }, 'pullback')
        .to('.cta-wrapper', { scale: 1, filter: 'blur(0px)', ease: 'expo.inOut', duration: 1.8 }, 'pullback')
        .to('.main-card', { y: -window.innerHeight - 300, ease: 'power3.in', duration: 1.5 })
    }, containerRef)

    return () => ctx.revert()
  }, [metricValue, reduced])

  // Reduced motion: a single calm viewport — the thesis, no theatre.
  if (reduced) {
    return (
      <div className={cn('relative flex min-h-screen w-full flex-col items-center justify-center bg-[#04070f] px-6 text-center', className)} {...props}>
        <style dangerouslySetInnerHTML={{ __html: INJECTED_STYLES }} />
        <p className="mb-6 font-mono text-[11px] uppercase tracking-[0.4em] text-[#60a5fa]">{brandName}</p>
        <h1 className="nx-text-3d max-w-4xl text-4xl font-bold tracking-tight md:text-6xl">{tagline1}</h1>
        <h1 className="nx-text-silver max-w-4xl text-4xl font-extrabold tracking-tighter md:text-6xl">{tagline2}</h1>
        <p className="mt-8 max-w-xl text-base leading-relaxed text-[#9aa7bd]">{subhead}</p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        'relative flex h-screen w-screen items-center justify-center overflow-hidden bg-[#04070f] font-sans text-[#f2f6ff] antialiased',
        className,
      )}
      style={{ perspective: '1500px' }}
      {...props}
    >
      <style dangerouslySetInnerHTML={{ __html: INJECTED_STYLES }} />
      <div className="nx-film-grain" aria-hidden="true" />
      <div className="nx-grid pointer-events-none absolute inset-0 z-0 opacity-50" aria-hidden="true" />

      {/* BACKGROUND LAYER: the thesis */}
      <div className="hero-text-wrapper transform-style-3d absolute z-10 flex w-screen flex-col items-center justify-center px-4 text-center will-change-transform">
        <p className="mb-8 font-mono text-[11px] uppercase tracking-[0.5em] text-[#60a5fa]">{brandName}</p>
        <h1 className="text-track gsap-reveal nx-text-3d mb-2 text-[clamp(2.3rem,6.2vw,5rem)] font-bold leading-[1.08] tracking-tight">
          {tagline1}
        </h1>
        <h1 className="text-days gsap-reveal nx-text-silver text-[clamp(2.3rem,6.2vw,5rem)] font-extrabold leading-[1.08] tracking-tighter">
          {tagline2}
        </h1>
        <p className="hero-subhead gsap-reveal mx-auto mt-10 max-w-xl text-base font-light leading-relaxed text-[#9aa7bd] md:text-lg">
          {subhead}
        </p>
        <div className="hero-subhead gsap-reveal mt-14 flex flex-col items-center gap-2" aria-hidden="true">
          <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-[#55617a]">Scroll</span>
          <span className="block h-8 w-px bg-gradient-to-b from-[#60a5fa] to-transparent" />
        </div>
      </div>

      {/* BACKGROUND LAYER 2: the pullback statement (Scene 2 of the manifesto) */}
      <div className="cta-wrapper gsap-reveal pointer-events-auto absolute z-10 flex w-screen flex-col items-center justify-center px-4 text-center will-change-transform">
        <h2 className="nx-text-silver mb-8 max-w-4xl text-balance text-[clamp(1.8rem,4.4vw,3.4rem)] font-bold leading-[1.12] tracking-tight">
          {outroHeading}
        </h2>
        <p className="mx-auto max-w-2xl text-base font-light leading-relaxed text-[#9aa7bd] md:text-lg">
          {outroDescription}
        </p>
        <div className="mt-16 flex flex-col items-center gap-2" aria-hidden="true">
          <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-[#55617a]">Keep going</span>
          <span className="block h-8 w-px bg-gradient-to-b from-[#60a5fa] to-transparent" />
        </div>
      </div>

      {/* FOREGROUND LAYER: the physical deep-navy card */}
      <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center" style={{ perspective: '1500px' }}>
        <div
          ref={mainCardRef}
          className="main-card nx-depth-card gsap-reveal pointer-events-auto relative flex h-[92vh] w-[92vw] items-center justify-center overflow-hidden rounded-[32px] md:h-[85vh] md:w-[85vw] md:rounded-[40px]"
        >
          <div className="nx-card-sheen" aria-hidden="true" />

          <div className="relative z-10 mx-auto flex h-full w-full max-w-7xl flex-col items-center justify-evenly px-4 py-6 lg:grid lg:grid-cols-3 lg:gap-8 lg:px-12 lg:py-0">

            {/* 1. Brand name — clamp sized to its grid column so the final
                letter can never fall off the card edge on wide screens */}
            <div className="card-right-text gsap-reveal z-20 order-1 flex w-full min-w-0 justify-center lg:order-3 lg:justify-end">
              <h2 className="nx-card-silver max-w-full text-[clamp(2.8rem,5vw,5rem)] font-black uppercase leading-none tracking-tighter lg:mt-0">
                {brandName}
              </h2>
            </div>

            {/* 2. The instrument */}
            <div className="mockup-scroll-wrapper relative z-10 order-2 flex h-[380px] w-full items-center justify-center lg:h-[600px]" style={{ perspective: '1000px' }}>
              <div className="md:scale-85 relative flex h-full w-full scale-[0.65] transform items-center justify-center lg:scale-100">

                <div
                  ref={mockupRef}
                  className="nx-bezel transform-style-3d relative flex h-[580px] w-[280px] flex-col rounded-[3rem] will-change-transform"
                >
                  {/* Hardware buttons */}
                  <div className="nx-hw-btn absolute -left-[3px] top-[120px] z-0 h-[25px] w-[3px] rounded-l-md" aria-hidden="true" />
                  <div className="nx-hw-btn absolute -left-[3px] top-[160px] z-0 h-[45px] w-[3px] rounded-l-md" aria-hidden="true" />
                  <div className="nx-hw-btn absolute -left-[3px] top-[220px] z-0 h-[45px] w-[3px] rounded-l-md" aria-hidden="true" />
                  <div className="nx-hw-btn absolute -right-[3px] top-[170px] z-0 h-[70px] w-[3px] scale-x-[-1] rounded-r-md" aria-hidden="true" />

                  {/* Screen — the Nexus Work Queue, miniature */}
                  <div className="absolute inset-[7px] z-10 overflow-hidden rounded-[2.5rem] bg-[#04070f] text-white shadow-[inset_0_0_15px_rgba(0,0,0,1)]">
                    <div className="nx-glare pointer-events-none absolute inset-0 z-40" aria-hidden="true" />

                    {/* Dynamic island */}
                    <div className="absolute left-1/2 top-[5px] z-50 flex h-[28px] w-[100px] -translate-x-1/2 items-center justify-end rounded-full bg-black px-3 shadow-[inset_0_-1px_2px_rgba(190,214,255,0.1)]">
                      <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#60a5fa] shadow-[0_0_8px_rgba(96,165,250,0.8)]" />
                    </div>

                    {/* Instrument interface */}
                    <div className="relative flex h-full w-full flex-col px-5 pb-8 pt-12">
                      <div className="phone-widget mb-6 flex items-center justify-between">
                        <div className="flex flex-col">
                          <span className="mb-1 font-mono text-[9px] font-bold uppercase tracking-widest text-[#55617a]">Work queue</span>
                          <span className="text-xl font-bold tracking-tight text-white drop-shadow-md">Your move</span>
                        </div>
                        <div className="flex h-9 w-9 items-center justify-center rounded-full border border-[#3b82f6]/30 bg-[#3b82f6]/10 font-mono text-sm font-bold text-[#60a5fa] shadow-lg shadow-black/50">✦</div>
                      </div>

                      {/* Confidence ring */}
                      <div className="phone-widget relative mx-auto mb-6 flex h-44 w-44 items-center justify-center drop-shadow-[0_15px_25px_rgba(0,0,0,0.8)]">
                        <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
                          <circle cx="88" cy="88" r="64" fill="none" stroke="rgba(148,186,255,0.05)" strokeWidth="12" />
                          <circle className="nx-ring" cx="88" cy="88" r="64" fill="none" stroke="#3B82F6" strokeWidth="12" />
                        </svg>
                        <div className="z-10 flex flex-col items-center text-center">
                          <span className="flex items-baseline font-mono">
                            <span className="counter-val text-4xl font-extrabold tracking-tighter text-white">0</span>
                            <span className="text-xl font-bold text-[#60a5fa]">%</span>
                          </span>
                          <span className="mt-0.5 font-mono text-[8px] font-bold uppercase tracking-[0.1em] text-[#60a5fa]/60">{metricLabel}</span>
                        </div>
                      </div>

                      {/* Queue rows — anonymous, honest about whose move it is */}
                      <div className="space-y-3">
                        <div className="phone-widget nx-widget flex items-center rounded-2xl p-3">
                          <div className="mr-3 flex h-10 w-10 items-center justify-center rounded-xl border border-[#3b82f6]/25 bg-gradient-to-br from-[#3b82f6]/20 to-[#3b82f6]/5 shadow-inner">
                            <span className="font-mono text-[10px] font-bold text-[#60a5fa]">MG</span>
                          </div>
                          <div className="flex-1">
                            <div className="mb-2 h-2 w-20 rounded-full bg-[#9aa7bd] shadow-inner" />
                            <div className="h-1.5 w-12 rounded-full bg-[#3d4a66] shadow-inner" />
                          </div>
                          <span className="rounded-full border border-[#60a5fa]/25 bg-[#3b82f6]/10 px-2 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider text-[#60a5fa]">Your move</span>
                        </div>
                        <div className="phone-widget nx-widget flex items-center rounded-2xl p-3">
                          <div className="mr-3 flex h-10 w-10 items-center justify-center rounded-xl border border-[#2dd4bf]/25 bg-gradient-to-br from-[#2dd4bf]/20 to-[#2dd4bf]/5 shadow-inner">
                            <span className="font-mono text-[10px] font-bold text-[#2dd4bf]">DR</span>
                          </div>
                          <div className="flex-1">
                            <div className="mb-2 h-2 w-16 rounded-full bg-[#9aa7bd] shadow-inner" />
                            <div className="h-1.5 w-24 rounded-full bg-[#3d4a66] shadow-inner" />
                          </div>
                          <span className="rounded-full border border-[#2dd4bf]/25 bg-[#2dd4bf]/10 px-2 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider text-[#2dd4bf]">Theirs</span>
                        </div>
                      </div>

                      <div className="absolute bottom-2 left-1/2 h-[4px] w-[120px] -translate-x-1/2 rounded-full bg-white/20 shadow-[0_1px_2px_rgba(0,0,0,0.5)]" />
                    </div>
                  </div>
                </div>

                {/* Floating glass badges */}
                <div className="floating-badge nx-badge absolute left-[-15px] top-6 z-30 flex items-center gap-3 rounded-xl p-3 lg:left-[-80px] lg:top-12 lg:gap-4 lg:rounded-2xl lg:p-4">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[#60a5fa]/30 bg-gradient-to-b from-[#3b82f6]/20 to-[#0b2a6b]/10 shadow-inner lg:h-10 lg:w-10">
                    <span className="text-base text-[#60a5fa] drop-shadow-lg lg:text-xl" aria-hidden="true">✦</span>
                  </div>
                  <div>
                    <p className="text-xs font-bold tracking-tight text-white lg:text-sm">Waiting on you · 26h</p>
                    <p className="text-[10px] font-medium text-[#8fa4cc] lg:text-xs">Lifted to the top, quietly</p>
                  </div>
                </div>

                <div className="floating-badge nx-badge absolute bottom-12 right-[-15px] z-30 flex items-center gap-3 rounded-xl p-3 lg:bottom-20 lg:right-[-80px] lg:gap-4 lg:rounded-2xl lg:p-4">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[#2dd4bf]/30 bg-gradient-to-b from-[#2dd4bf]/20 to-[#134e48]/10 shadow-inner lg:h-10 lg:w-10">
                    <span className="text-base text-[#2dd4bf] drop-shadow-lg lg:text-lg" aria-hidden="true">✎</span>
                  </div>
                  <div>
                    <p className="text-xs font-bold tracking-tight text-white lg:text-sm">Draft ready</p>
                    <p className="text-[10px] font-medium text-[#8fa4cc] lg:text-xs">Sent by you. Always.</p>
                  </div>
                </div>

              </div>
            </div>

            {/* 3. The accountability statement */}
            <div className="card-left-text gsap-reveal z-20 order-3 flex w-full flex-col justify-center px-4 text-center lg:order-1 lg:px-0 lg:text-left">
              <h3 className="mb-0 text-balance text-[clamp(1.35rem,2.3vw,2.1rem)] font-bold leading-[1.15] tracking-tight text-white lg:mb-5">
                {cardHeading}
              </h3>
              <p className="mx-auto hidden max-w-sm text-[clamp(0.85rem,1.15vw,1.05rem)] font-normal leading-relaxed text-[#b6c5e4]/80 md:block lg:mx-0 lg:max-w-md">
                {cardDescription}
              </p>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
