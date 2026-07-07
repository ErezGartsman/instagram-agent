import { useCallback, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { CommandPalette } from '../components/CommandPalette'
import { GlowingAiAssistant } from '../components/GlowingAiAssistant'
import { BootSequence, shouldBoot } from '../components/BootSequence'
import { AI_DOCK_WIDTH, useAiDockPinned } from '../lib/aiDock'

const EASE: [number, number, number, number] = [0.25, 0.4, 0.25, 1]

/**
 * The authenticated frame: fixed left nav + top bar + animated page well +
 * the floating/dockable AI assistant.
 *
 * Boot: once per session the BootSequence overlay plays (~1.15s, skippable);
 * the shell columns rise underneath as it lifts. Route changes never re-boot.
 *
 * Dock: when the assistant pins itself, a spacer column animates open so the
 * content reflows — the panel never covers data.
 */
export function AppShell() {
  const location = useLocation()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const openPalette  = useCallback(() => setPaletteOpen(true), [])
  const closePalette = useCallback(() => setPaletteOpen(false), [])
  const dockPinned = useAiDockPinned()

  // Boot exactly once per session — the initializer freezes the decision so
  // re-renders (or route changes) can never replay the theatre.
  const [needsBoot] = useState(shouldBoot)
  const [booting, setBooting] = useState(needsBoot)
  const finishBoot = useCallback(() => setBooting(false), [])

  // Global ⌘K / Ctrl+K listener — owned here so it works on any page.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {booting && <BootSequence onDone={finishBoot} />}

      {/* Left rail — slides in from the void on boot. */}
      <motion.div
        initial={needsBoot ? { x: -28, opacity: 0 } : false}
        animate={booting ? { x: -28, opacity: 0 } : { x: 0, opacity: 1 }}
        transition={{ duration: 0.45, ease: EASE }}
        className="flex shrink-0"
      >
        <Sidebar />
      </motion.div>

      <div className="flex min-w-0 flex-1 flex-col">
        <motion.div
          initial={needsBoot ? { y: -16, opacity: 0 } : false}
          animate={booting ? { y: -16, opacity: 0 } : { y: 0, opacity: 1 }}
          transition={{ duration: 0.45, ease: EASE, delay: 0.06 }}
        >
          <Topbar onOpenPalette={openPalette} />
        </motion.div>
        <motion.main
          initial={needsBoot ? { y: 22, opacity: 0 } : false}
          animate={booting ? { y: 22, opacity: 0 } : { y: 0, opacity: 1 }}
          transition={{ duration: 0.5, ease: EASE, delay: 0.12 }}
          className="flex-1 overflow-y-auto px-10 py-10"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: EASE }}
              className="h-full min-h-0"
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </motion.main>
      </div>

      {/* Dock spacer — the assistant's pinned rail reflows content, never covers it. */}
      <motion.div
        aria-hidden
        initial={false}
        animate={{ width: dockPinned ? AI_DOCK_WIDTH : 0 }}
        transition={{ duration: 0.32, ease: EASE }}
        className="shrink-0"
      />

      <CommandPalette open={paletteOpen} onClose={closePalette} />
      {/* Global floating AI assistant — morphs orb ⇄ panel, pins as a dock */}
      <GlowingAiAssistant />
    </div>
  )
}
