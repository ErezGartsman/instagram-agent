import { HeroGeometric } from '@/components/ui/shape-landing-hero'

/**
 * Public Nexus marketing landing page, served at /landing.
 *
 * Now an immersive Graphite Atelier hero — warm obsidian with floating
 * champagne-bronze / sage shapes (framer-motion), the "logic meets magic"
 * statement in the Machine sans + the Human serif. Renders OUTSIDE
 * `.cockpit-root` (no auth gate); the `.landing-root` wrapper only supplies the
 * base reset + font family — the hero paints its own obsidian background.
 * Lazy-loaded so its motion deps never weigh down the cockpit bundle.
 */
export function LandingPage() {
  return (
    <div className="landing-root bg-[#100c0a]">
      <HeroGeometric badge="Nexus OS" title1="Where the logic" title2="meets the magic" />
    </div>
  )
}
