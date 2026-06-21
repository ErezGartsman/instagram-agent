import { motion, useReducedMotion } from "framer-motion";
import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

// Adapted from the provided shape-landing-hero, recolored from the original
// indigo/rose/violet/cyan palette into Graphite Atelier — warm obsidian with
// champagne-bronze + sage translucent shapes — and made reduced-motion aware.
function ElegantShape({
  className,
  delay = 0,
  width = 400,
  height = 100,
  rotate = 0,
  gradient = "from-[#f2ebe0]/[0.08]",
}: {
  className?: string;
  delay?: number;
  width?: number;
  height?: number;
  rotate?: number;
  gradient?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={{ opacity: 0, y: -150, rotate: rotate - 15 }}
      animate={{ opacity: 1, y: 0, rotate }}
      transition={{
        duration: 2.4,
        delay,
        ease: [0.23, 0.86, 0.39, 0.96],
        opacity: { duration: 1.2 },
      }}
      className={cn("absolute", className)}
    >
      <motion.div
        animate={reduce ? undefined : { y: [0, 15, 0] }}
        transition={{ duration: 12, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
        style={{ width, height }}
        className="relative"
      >
        <div
          className={cn(
            "absolute inset-0 rounded-full",
            "bg-gradient-to-r to-transparent",
            gradient,
            "backdrop-blur-[2px] border-2 border-[#f2ebe0]/[0.12]",
            "shadow-[0_8px_32px_0_rgba(201,170,113,0.10)]",
            "after:absolute after:inset-0 after:rounded-full",
            "after:bg-[radial-gradient(circle_at_50%_50%,rgba(242,235,224,0.15),transparent_70%)]",
          )}
        />
      </motion.div>
    </motion.div>
  );
}

export function HeroGeometric({
  badge = "Nexus OS",
  title1 = "Where the logic",
  title2 = "meets the magic",
}: {
  badge?: string;
  title1?: string;
  title2?: string;
}) {
  const fadeUpVariants = {
    hidden: { opacity: 0, y: 30 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: { duration: 1, delay: 0.5 + i * 0.2, ease: [0.25, 0.4, 0.25, 1] as const },
    }),
  };

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center overflow-hidden bg-[#100c0a]">
      <div className="absolute inset-0 bg-gradient-to-br from-[#c9aa71]/[0.06] via-transparent to-[#8a9a82]/[0.06] blur-3xl" />

      <div className="absolute inset-0 overflow-hidden">
        <ElegantShape delay={0.3} width={600} height={140} rotate={12} gradient="from-[#c9aa71]/[0.18]" className="left-[-10%] md:left-[-5%] top-[15%] md:top-[20%]" />
        <ElegantShape delay={0.5} width={500} height={120} rotate={-15} gradient="from-[#8a9a82]/[0.16]" className="right-[-5%] md:right-[0%] top-[70%] md:top-[75%]" />
        <ElegantShape delay={0.4} width={300} height={80} rotate={-8} gradient="from-[#bd9a5b]/[0.15]" className="left-[5%] md:left-[10%] bottom-[5%] md:bottom-[10%]" />
        <ElegantShape delay={0.6} width={200} height={60} rotate={20} gradient="from-[#d8a657]/[0.14]" className="right-[15%] md:right-[20%] top-[10%] md:top-[15%]" />
        <ElegantShape delay={0.7} width={150} height={40} rotate={-25} gradient="from-[#f2ebe0]/[0.10]" className="left-[20%] md:left-[25%] top-[5%] md:top-[10%]" />
      </div>

      <div className="relative z-10 container mx-auto px-4 md:px-6">
        <div className="max-w-3xl mx-auto text-center">
          <motion.div
            custom={0}
            variants={fadeUpVariants}
            initial="hidden"
            animate="visible"
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#f2ebe0]/[0.04] border border-[#f2ebe0]/[0.10] mb-8 md:mb-12"
          >
            <Circle className="h-2 w-2 fill-[#c9aa71] text-[#c9aa71]" />
            <span className="text-sm text-[#a99c8c] tracking-wide">{badge}</span>
          </motion.div>

          <motion.div custom={1} variants={fadeUpVariants} initial="hidden" animate="visible">
            <h1 className="text-4xl sm:text-6xl md:text-8xl font-semibold mb-6 md:mb-8 tracking-tight">
              <span className="bg-clip-text text-transparent bg-gradient-to-b from-[#f2ebe0] to-[#a99c8c]">
                {title1}
              </span>
              <br />
              <span className="font-serif font-light italic bg-clip-text text-transparent bg-gradient-to-r from-[#c9aa71] via-[#f2ebe0] to-[#8a9a82]">
                {title2}
              </span>
            </h1>
          </motion.div>

          <motion.div custom={2} variants={fadeUpVariants} initial="hidden" animate="visible">
            <p className="text-base sm:text-lg md:text-xl text-[#a99c8c] mb-9 leading-relaxed font-light tracking-wide max-w-xl mx-auto px-4">
              The private operating system for relationship work — leads, memory, and content,
              in one calm place.
            </p>
          </motion.div>

          <motion.div custom={3} variants={fadeUpVariants} initial="hidden" animate="visible">
            <a
              href="/app"
              className="inline-flex items-center gap-2 rounded-full border border-[#c9aa71]/40 bg-[#c9aa71]/10 px-5 py-2.5 text-sm text-[#e8cf9c] transition-colors hover:bg-[#c9aa71]/20"
            >
              Enter the cockpit
              <span aria-hidden>→</span>
            </a>
          </motion.div>
        </div>
      </div>

      <div className="absolute inset-0 bg-gradient-to-t from-[#100c0a] via-transparent to-[#100c0a]/80 pointer-events-none" />
    </div>
  );
}
