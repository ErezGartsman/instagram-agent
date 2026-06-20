import HeroSection_05 from '@/components/ui/hero-section-with-gradient'

/**
 * Public Nexus marketing landing page, served at /landing.
 *
 * Fully isolated from the Graphite Atelier cockpit: it renders OUTSIDE
 * `.cockpit-root` (no dark reset, no auth gate) and inside `.landing-root`,
 * which carries its own light, shadcn-style theme. Lazy-loaded so its deps
 * (gsap, framer-motion, lucide) never weigh down the cockpit bundle.
 */
export function LandingPage() {
  return (
    <div className="landing-root min-h-screen w-full bg-white">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:py-16">
        <HeroSection_05 />
      </div>
    </div>
  )
}
