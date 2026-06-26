import React, { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { gsap } from "gsap";
import { motion, type Variants } from "framer-motion";
import {
  MessageCircle,
  Camera,
  Send,
  CalendarClock,
  Phone,
  Globe,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function HeroSection_05() {
  const gradientRef = useRef<HTMLDivElement>(null);

  const transitionVariants = {
    item: {
      hidden: {
        opacity: 0,
        filter: "blur(12px)",
        y: 12,
      },
      visible: {
        opacity: 1,
        filter: "blur(0px)",
        y: 0,
        transition: {
          type: "spring" as const,
          bounce: 0.3,
          duration: 1.5,
        },
      },
    },
  };

  useEffect(() => {
    if (!gradientRef.current) return;
    gsap.fromTo(
      gradientRef.current,
      { opacity: 0, y: -30 },
      { opacity: 1, y: 0, duration: 1.6, ease: "power3.out" }
    );
  }, []);

  return (
    <div className="p-6 overflow-hidden rounded-xl">
      <div className="relative w-full">
        <div
          ref={gradientRef}
          className="absolute inset-0 -z-10 transition-colors duration-700 max-h-[90vh] rounded-2xl"
          style={{
            backgroundImage: `
              linear-gradient(180deg, #ffffff 0%, #FFEDD5 25%, #FFDAB9 50%, #FFB6C1 70%, #E0BBE4 85%, #F3E5F5 100%),
              radial-gradient(at 20% 30%, #ffffff33 0%, transparent 60%),
              radial-gradient(at 80% 70%, #f3e5f533 0%, transparent 70%)
            `,
            backgroundBlendMode: "overlay, screen",
          }}
        />

        <div className="pt-4 pb-10 sm:pt-6 sm:pb-12 text-center">
          <div className="relative max-w-2xl mx-auto">
            <h1 className="text-3xl sm:text-5xl md:text-6xl text-gray-800 font-bold tracking-tight">
              Nexus: the command center for relationship work
            </h1>
            <p className="mt-4 text-lg text-gray-600">
              Nexus turns every WhatsApp, Instagram, and Telegram conversation into a ranked
              queue of next moves — memory-first, calm by design — so you always know who
              needs you next, and exactly what to say.
            </p>
            <AnimatedGroup
              variants={{
                container: {
                  visible: {
                    transition: {
                      staggerChildren: 0.05,
                      delayChildren: 0.75,
                    },
                  },
                },
                ...transitionVariants,
              }}
              className="mt-12 flex flex-col items-center justify-center gap-2 md:flex-row"
            >
              <div key={1} className="bg-foreground/10 rounded-[14px] border p-0.5">
                <Button asChild size="lg" className="rounded-xl px-5 text-base">
                  <a href="/">
                    <span className="text-nowrap no-underline">Sign In</span>
                  </a>
                </Button>
              </div>
              <div
                key={2}
                className="bg-gradient-to-r from-cyan-400 via-blue-500 to-purple-500 rounded-[14px] border p-0.5"
              >
                <Button
                  asChild
                  size="lg"
                  className="rounded-xl px-5 text-base bg-white text-black hover:bg-black hover:text-white"
                >
                  <a href="mailto:erezkim1234@gmail.com?subject=Nexus%20demo">
                    <span className="text-nowrap">Request a demo</span>
                  </a>
                </Button>
              </div>
            </AnimatedGroup>
          </div>
        </div>

        <AnimatedGroup
          variants={{
            container: {
              visible: {
                transition: {
                  staggerChildren: 0.05,
                  delayChildren: 0.75,
                },
              },
            },
            ...transitionVariants,
          }}
        >
          <div className="relative overflow-hidden px-2">
            <div
              aria-hidden
              className="bg-gradient-to-b from-transparent to-background absolute inset-0 z-10 from-35%"
            />
            <div className="relative mx-auto max-w-5xl overflow-hidden rounded-t-2xl border border-black/5 border-b-0 p-4 shadow-2xl shadow-black/10 bg-white">
              <img
                className="aspect-[15/8] relative w-full rounded-2xl object-cover"
                src="https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=2700&q=80&auto=format&fit=crop"
                alt="Nexus work-queue preview"
                width={2700}
                height={1440}
                loading="eager"
              />
            </div>
          </div>
        </AnimatedGroup>
      </div>
      <ChannelsStrip />
    </div>
  );
}

const CHANNELS: { name: string; icon: LucideIcon }[] = [
  { name: "WhatsApp", icon: MessageCircle },
  { name: "Instagram", icon: Camera },
  { name: "Telegram", icon: Send },
  { name: "Calendly", icon: CalendarClock },
  { name: "Phone", icon: Phone },
  { name: "Web", icon: Globe },
];

export const ChannelsStrip = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  return (
    <div ref={ref} className={cn("py-8", className)} {...props}>
      <div className="max-w-5xl mx-auto px-4">
        <p className="mb-6 text-center text-xs font-medium uppercase tracking-[0.18em] text-gray-500">
          One queue, every channel
        </p>
        <div className="max-w-xs mx-auto grid grid-cols-2 items-center gap-y-6 md:grid-cols-3 md:max-w-lg lg:grid-cols-6 lg:max-w-3xl">
          {CHANNELS.map(({ name, icon: Icon }) => (
            <div key={name} className="flex items-center justify-center gap-2 p-2 text-gray-600">
              <Icon className="h-5 w-5" strokeWidth={1.8} aria-hidden />
              <span className="text-sm font-medium">{name}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});

ChannelsStrip.displayName = "ChannelsStrip";

type PresetType = "fade" | "slide" | "scale" | "blur" | "blur-slide" | "zoom" | "flip" | "bounce" | "rotate" | "swing";

type AnimatedGroupProps = {
  children: ReactNode;
  className?: string;
  variants?: { container?: Variants; item?: Variants };
  preset?: PresetType;
};

const defaultContainerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.1 } },
};

const defaultItemVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
};

const presetVariants: Record<PresetType, { container: Variants; item: Variants }> = {
  fade: { container: defaultContainerVariants, item: { hidden: { opacity: 0 }, visible: { opacity: 1 } } },
  slide: { container: defaultContainerVariants, item: { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0 } } },
  scale: { container: defaultContainerVariants, item: { hidden: { opacity: 0, scale: 0.8 }, visible: { opacity: 1, scale: 1 } } },
  blur: { container: defaultContainerVariants, item: { hidden: { opacity: 0, filter: "blur(4px)" }, visible: { opacity: 1, filter: "blur(0px)" } } },
  "blur-slide": { container: defaultContainerVariants, item: { hidden: { opacity: 0, filter: "blur(4px)", y: 20 }, visible: { opacity: 1, filter: "blur(0px)", y: 0 } } },
  zoom: { container: defaultContainerVariants, item: { hidden: { opacity: 0, scale: 0.5 }, visible: { opacity: 1, scale: 1, transition: { type: "spring" as const, stiffness: 300, damping: 20 } } } },
  flip: { container: defaultContainerVariants, item: { hidden: { opacity: 0, rotateX: -90 }, visible: { opacity: 1, rotateX: 0, transition: { type: "spring" as const, stiffness: 300, damping: 20 } } } },
  bounce: { container: defaultContainerVariants, item: { hidden: { opacity: 0, y: -50 }, visible: { opacity: 1, y: 0, transition: { type: "spring" as const, stiffness: 400, damping: 10 } } } },
  rotate: { container: defaultContainerVariants, item: { hidden: { opacity: 0, rotate: -180 }, visible: { opacity: 1, rotate: 0, transition: { type: "spring" as const, stiffness: 200, damping: 15 } } } },
  swing: { container: defaultContainerVariants, item: { hidden: { opacity: 0, rotate: -10 }, visible: { opacity: 1, rotate: 0, transition: { type: "spring" as const, stiffness: 300, damping: 8 } } } },
};

function AnimatedGroup({ children, className, variants, preset }: AnimatedGroupProps) {
  const selectedVariants = preset ? presetVariants[preset] : { container: defaultContainerVariants, item: defaultItemVariants };
  const containerVariants = variants?.container || selectedVariants.container;
  const itemVariants = variants?.item || selectedVariants.item;

  return (
    <motion.div initial="hidden" animate="visible" variants={containerVariants} className={cn(className)}>
      {React.Children.map(children, (child, index) => (
        <motion.div key={index} variants={itemVariants}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
}

export { AnimatedGroup };
