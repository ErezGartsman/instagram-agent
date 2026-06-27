/**
 * GlowingAiAssistant — floating AI chat bubble, global to the cockpit.
 *
 * Replaces the old NexusAIPanel slide-out drawer.
 * Adapts the upstream FloatingAiAssistant component to the Nexus theme:
 *   • Uses CSS-variable–based semantic tokens (bg-surface, text-glow, etc.)
 *     so it inherits whichever design system the cockpit is running.
 *   • Removes <style jsx> (Next.js only) — uses `ai-pop-in` keyframe from index.css.
 *   • Send button uses var(--color-accent) + var(--shadow-glow).
 *   • "GPT-4" badge replaced with "Claude" — the actual LLM in use.
 *   • The textarea is functional (sends message to onSend callback);
 *     real backend wiring happens in the P2 Ambient Copilot workstream.
 */

import { useState, useRef, useEffect } from 'react'
import { Paperclip, Link, Code, Mic, Send, Info, Bot, X } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

const MAX_CHARS = 2000

export function GlowingAiAssistant() {
  const [open, setOpen]         = useState(false)
  const [message, setMessage]   = useState('')
  const { session }             = useAuth()
  const chatRef                 = useRef<HTMLDivElement>(null)
  const charCount               = message.length

  // Close when clicking outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Element
      if (chatRef.current && !chatRef.current.contains(target) && !target.closest('[data-ai-trigger]')) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  const handleSend = () => {
    if (!message.trim()) return
    // P2 Ambient Copilot: wire to /api/cockpit/copilot/draft with session token
    console.log('[NexusAI] message:', message, '| token:', session?.access_token?.slice(0, 12))
    setMessage('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const ACTIONS = [
    { icon: Paperclip, label: 'Attach file' },
    { icon: Link,      label: 'Web link'   },
    { icon: Code,      label: 'Code'       },
    { icon: Mic,       label: 'Voice'      },
  ] as const

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {/* ── Floating glowing trigger button ─────────────────────────────────── */}
      <button
        data-ai-trigger
        aria-label={open ? 'Close Nexus AI' : 'Open Nexus AI'}
        onClick={() => setOpen(v => !v)}
        className="relative flex h-14 w-14 items-center justify-center rounded-full transition-all duration-300"
        style={{
          background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-glow) 100%)',
          boxShadow: open
            ? '0 0 12px var(--color-glow)'
            : '0 0 20px color-mix(in srgb, var(--color-glow) 70%, transparent), 0 0 40px color-mix(in srgb, var(--color-accent) 50%, transparent)',
          border: '1px solid color-mix(in srgb, var(--color-glow) 30%, transparent)',
          transform: open ? 'rotate(90deg) scale(0.92)' : 'rotate(0deg) scale(1)',
        }}
      >
        {/* Glass shine */}
        <div className="absolute inset-0 rounded-full"
          style={{ background: 'linear-gradient(to bottom, rgba(255,255,255,0.18), transparent)' }} />
        {/* Ping ring — only when closed */}
        {!open && (
          <div className="absolute inset-0 animate-ping rounded-full opacity-20"
            style={{ background: 'var(--color-glow)' }} />
        )}
        <span className="relative z-10 text-white">
          {open
            ? <X    className="h-5 w-5" />
            : <Bot  className="h-6 w-6" />}
        </span>
      </button>

      {/* ── Chat interface ───────────────────────────────────────────────────── */}
      {open && (
        <div
          ref={chatRef}
          className="absolute bottom-20 right-0 w-[420px] ai-pop-in"
        >
          <div
            className="relative flex flex-col overflow-hidden rounded-[20px] border border-line"
            style={{
              background: 'color-mix(in srgb, var(--color-bg) 92%, transparent)',
              backdropFilter: 'blur(24px)',
              boxShadow: 'var(--shadow-card)',
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-line px-5 pb-2.5 pt-4">
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-glow" />
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-glow">
                  Nexus AI
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className="rounded-full border border-glow/25 px-2 py-0.5 font-mono text-[9px] text-glow"
                  style={{ background: 'color-mix(in srgb, var(--color-accent) 15%, transparent)' }}
                >
                  Claude
                </span>
                <span
                  className="rounded-full border border-line px-2 py-0.5 font-mono text-[9px] text-faint"
                >
                  Preview
                </span>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="grid h-6 w-6 place-items-center rounded-control text-faint transition-colors hover:bg-raised hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Textarea */}
            <textarea
              value={message}
              onChange={e => setMessage(e.target.value.slice(0, MAX_CHARS))}
              onKeyDown={handleKeyDown}
              rows={4}
              autoFocus
              className="w-full resize-none border-none bg-transparent px-5 py-4 text-sm leading-relaxed text-ink outline-none placeholder:text-faint"
              style={{ scrollbarWidth: 'none' }}
              placeholder="Ask about leads, pipeline health, or community insights…"
            />

            {/* Controls */}
            <div className="px-4 pb-4">
              <div className="flex items-center justify-between">
                {/* Attachment actions */}
                <div className="flex items-center gap-1">
                  <div
                    className="flex items-center gap-0.5 rounded-control border border-line p-0.5"
                    style={{ background: 'color-mix(in srgb, var(--color-raised) 60%, transparent)' }}
                  >
                    {ACTIONS.map(({ icon: Ic, label }) => (
                      <button
                        key={label}
                        type="button"
                        title={label}
                        className="rounded p-2 text-faint transition-all duration-200 hover:bg-raised hover:text-glow"
                      >
                        <Ic className="h-3.5 w-3.5" />
                      </button>
                    ))}
                  </div>
                </div>

                {/* Char count + send */}
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[10px] text-faint">
                    {charCount}<span className="text-faint/50">/{MAX_CHARS}</span>
                  </span>
                  <button
                    type="button"
                    onClick={handleSend}
                    disabled={!message.trim()}
                    className="grid h-9 w-9 place-items-center rounded-control text-white transition-all duration-200 hover:scale-105 disabled:opacity-30 disabled:cursor-not-allowed"
                    style={{
                      background: 'var(--color-accent)',
                      boxShadow: message.trim() ? 'var(--shadow-glow)' : 'none',
                    }}
                  >
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* Footer */}
              <div className="mt-3 flex items-center justify-between border-t border-line pt-3 font-mono text-[9px] text-faint">
                <div className="flex items-center gap-1.5">
                  <Info className="h-3 w-3" />
                  <span>
                    <kbd className="rounded border border-line bg-raised px-1 py-0.5 text-[9px]">Shift+Enter</kbd>
                    {' '}for new line
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 w-1.5 rounded-full bg-glow" />
                  <span>NLP engine · P2 Copilot</span>
                </div>
              </div>
            </div>

            {/* Ambient glow overlay */}
            <div
              className="pointer-events-none absolute inset-0 rounded-[20px]"
              style={{
                background: 'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 4%, transparent), transparent, color-mix(in srgb, var(--color-glow) 3%, transparent))',
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
