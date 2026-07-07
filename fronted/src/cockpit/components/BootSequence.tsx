import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { NexusLogo } from '../../components/ui/nexus-logo'

/**
 * BootSequence — the one moment of theatre ("signature boot, quiet after").
 *
 * A GSAP-orchestrated ignition: the mark strikes, NEXUS letters assemble, a
 * filament draws, then the void lifts and the shell rises underneath (AppShell
 * drives the shell entrance off the same boot state). ~1.15s total.
 *
 * Guardrails:
 *  - once per browser session (sessionStorage) — never on route changes
 *  - any key / click skips straight to the cockpit
 *  - prefers-reduced-motion skips it entirely (shouldBoot returns false)
 */

const BOOT_KEY = 'nexus.boot.v1'

export function shouldBoot(): boolean {
  try {
    if (typeof window === 'undefined') return false
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
    return sessionStorage.getItem(BOOT_KEY) !== '1'
  } catch {
    return false
  }
}

export function BootSequence({ onDone }: { onDone: () => void }) {
  const rootRef = useRef<HTMLDivElement>(null)
  const doneRef = useRef(false)

  useEffect(() => {
    try {
      sessionStorage.setItem(BOOT_KEY, '1')
    } catch {
      /* storage unavailable — boot still plays once for this mount */
    }
    const root = rootRef.current
    if (!root) return
    const q = gsap.utils.selector(root)
    const finish = () => {
      if (doneRef.current) return
      doneRef.current = true
      onDone()
    }

    const tl = gsap.timeline({ onComplete: finish })
    tl.fromTo(
      q('[data-boot-mark]'),
      { scale: 0.4, opacity: 0 },
      { scale: 1, opacity: 1, duration: 0.36, ease: 'back.out(2.2)' },
    )
      .to(
        q('[data-boot-mark]'),
        {
          filter: 'drop-shadow(0 0 14px rgba(59,130,246,0.75))',
          duration: 0.28,
          ease: 'power2.out',
        },
        '<0.1',
      )
      .fromTo(
        q('[data-boot-letter]'),
        { y: 14, opacity: 0 },
        { y: 0, opacity: 1, duration: 0.3, stagger: 0.045, ease: 'power3.out' },
        '<0.05',
      )
      .fromTo(
        q('[data-boot-line]'),
        { scaleX: 0 },
        { scaleX: 1, duration: 0.38, ease: 'power2.inOut' },
        '<0.1',
      )
      .fromTo(q('[data-boot-sub]'), { opacity: 0 }, { opacity: 1, duration: 0.22 }, '<0.14')
      .to(root, { opacity: 0, scale: 1.02, duration: 0.38, ease: 'power2.inOut', delay: 0.16 })

    const skip = () => tl.progress(1)
    window.addEventListener('pointerdown', skip)
    window.addEventListener('keydown', skip)
    return () => {
      window.removeEventListener('pointerdown', skip)
      window.removeEventListener('keydown', skip)
      tl.kill()
    }
  }, [onDone])

  return (
    <div
      ref={rootRef}
      aria-hidden
      className="fixed inset-0 z-[80] flex flex-col items-center justify-center"
      style={{
        background:
          'radial-gradient(ellipse 80% 60% at 50% -10%, rgba(59,130,246,0.20) 0%, transparent 70%), #04070f',
      }}
    >
      <span
        data-boot-mark
        className="grid place-items-center text-ink"
        style={{ filter: 'drop-shadow(0 0 0 rgba(59,130,246,0))' }}
      >
        <NexusLogo size={84} />
      </span>

      <div className="mt-6 flex items-center gap-[0.35em] text-xl font-semibold tracking-[0.3em] text-ink">
        {'NEXUS'.split('').map((ch, i) => (
          <span key={i} data-boot-letter className="inline-block">
            {ch}
          </span>
        ))}
      </div>

      <span
        data-boot-line
        className="mt-5 block h-px w-44 origin-center rounded-full"
        style={{
          background:
            'linear-gradient(90deg, transparent 0%, rgba(96,165,250,0.9) 50%, transparent 100%)',
          boxShadow: '0 0 12px rgba(59,130,246,0.6)',
        }}
      />

      <span data-boot-sub className="mt-4 font-mono text-[10px] uppercase tracking-[0.3em] text-faint">
        Command center online
      </span>
    </div>
  )
}
