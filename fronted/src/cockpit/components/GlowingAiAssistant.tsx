/**
 * GlowingAiAssistant — floating AI chat bubble.
 *
 * Exports:
 *   GlowingAiAssistant  — the floating button + panel (mount in AppShell)
 *   pushAiContext(label)  — fires a window event that injects a context chip
 *   ContextTarget         — small ✦ button placed next to any targetable element
 *
 * P2 Ambient Copilot: the textarea + context chips are ready; backend wiring
 * happens in the next workstream via POST /api/cockpit/copilot/draft.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { Paperclip, Link2, Code2, Mic, Send, Info, Bot, X, MicOff } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

// ── Context bridge ─────────────────────────────────────────────────────────────
/** Call from any component to inject a context chip into the AI panel. */
export const pushAiContext = (label: string) => {
  window.dispatchEvent(new CustomEvent('nexus:ai-context', { detail: { label } }))
}

// ── ContextTarget button ───────────────────────────────────────────────────────
interface ContextTargetProps {
  label: string
  className?: string
}
export function ContextTarget({ label, className = '' }: ContextTargetProps) {
  const [flash, setFlash] = useState(false)
  const handle = () => {
    pushAiContext(label)
    setFlash(true)
    setTimeout(() => setFlash(false), 700)
  }
  return (
    <button
      type="button"
      title={`Ask Nexus AI about: ${label}`}
      onClick={handle}
      className={`inline-flex items-center justify-center rounded transition-all duration-300 ${
        flash
          ? 'text-glow scale-125'
          : 'text-faint/40 hover:text-glow hover:scale-110'
      } ${className}`}
    >
      <span className="select-none text-[9px] leading-none">✦</span>
    </button>
  )
}

// ── Chip ──────────────────────────────────────────────────────────────────────
function ContextChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-glow/25 px-2.5 py-0.5 font-mono text-[9px] text-glow"
      style={{ background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)' }}>
      ✦ {label}
      <button type="button" onClick={onRemove}
        className="ml-0.5 opacity-60 hover:opacity-100 transition-opacity">
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  )
}

const MAX_CHARS = 2000

// ── Main component ─────────────────────────────────────────────────────────────
export function GlowingAiAssistant() {
  const [open, setOpen]               = useState(false)
  const [message, setMessage]         = useState('')
  const [chips, setChips]             = useState<string[]>([])
  const [linkMode, setLinkMode]       = useState(false)
  const [linkUrl, setLinkUrl]         = useState('')
  const [codeMode, setCodeMode]       = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const { session }                   = useAuth()
  const chatRef                       = useRef<HTMLDivElement>(null)
  const textareaRef                   = useRef<HTMLTextAreaElement>(null)
  const fileRef                       = useRef<HTMLInputElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null)

  // ── Context event listener ─────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      const { label } = (e as CustomEvent<{ label: string }>).detail
      setChips(prev => prev.includes(label) ? prev : [...prev, label])
      setOpen(true)
      setTimeout(() => textareaRef.current?.focus(), 150)
    }
    window.addEventListener('nexus:ai-context', handler)
    return () => window.removeEventListener('nexus:ai-context', handler)
  }, [])

  // ── Close on click-outside ─────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => {
      const t = e.target as Element
      if (chatRef.current && !chatRef.current.contains(t) && !t.closest('[data-ai-btn]'))
        setOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  // ── Escape to close ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open])

  // ── Actions ────────────────────────────────────────────────────────────────
  const handleSend = useCallback(() => {
    if (!message.trim() && chips.length === 0) return
    const contextPrefix = chips.map(c => `[Context: ${c}]`).join(' ')
    const fullMsg = [contextPrefix, message.trim()].filter(Boolean).join('\n')
    // P2: replace with actual API call
    console.log('[NexusAI] →', fullMsg, '| token:', session?.access_token?.slice(0, 12))
    setMessage('')
    setChips([])
    setCodeMode(false)
  }, [message, chips, session])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  // File attach
  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setMessage(prev => prev ? `${prev}\n[File: ${file.name}]` : `[File: ${file.name}]`)
      textareaRef.current?.focus()
    }
    e.target.value = ''
  }

  // Link injection
  const submitLink = () => {
    if (!linkUrl.trim()) { setLinkMode(false); return }
    const url = linkUrl.startsWith('http') ? linkUrl : `https://${linkUrl}`
    setMessage(prev => prev ? `${prev}\n[URL: ${url}]` : `[URL: ${url}]`)
    setLinkUrl('')
    setLinkMode(false)
    textareaRef.current?.focus()
  }

  // Code mode toggle
  const toggleCode = () => {
    setCodeMode(v => !v)
    if (!codeMode && message && !message.startsWith('```')) {
      setMessage(prev => '```\n' + prev + '\n```')
    }
  }

  // Voice / speech recognition
  const toggleMic = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const win = window as any
    const SR = win.SpeechRecognition || win.webkitSpeechRecognition
    if (!SR) {
      setMessage(prev => prev ? prev : '[Voice input not supported in this browser]')
      return
    }
    if (isRecording) {
      recRef.current?.stop()
      setIsRecording(false)
      return
    }
    const rec = new SR()
    rec.lang = 'en-US'
    rec.interimResults = false
    rec.onresult = (e: { results: { [i: number]: { [j: number]: { transcript: string } } } }) => {
      const t = e.results[0][0].transcript
      setMessage(prev => prev ? `${prev} ${t}` : t)
    }
    rec.onend  = () => setIsRecording(false)
    rec.onerror = () => setIsRecording(false)
    rec.start()
    setIsRecording(true)
    recRef.current = rec
  }

  const charCount = message.length
  const canSend   = (message.trim().length > 0 || chips.length > 0) && charCount <= MAX_CHARS

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {/* ── Trigger button ──────────────────────────────────────────────────── */}
      <button
        data-ai-btn
        aria-label={open ? 'Close Nexus AI' : 'Open Nexus AI'}
        onClick={() => setOpen(v => !v)}
        className="relative flex h-14 w-14 items-center justify-center rounded-full transition-all duration-200 hover:scale-105 active:scale-95"
        style={{
          background: 'linear-gradient(135deg, var(--color-accent) 0%, var(--color-glow) 100%)',
          boxShadow: open
            ? '0 0 10px color-mix(in srgb, var(--color-glow) 40%, transparent)'
            : '0 0 16px color-mix(in srgb, var(--color-glow) 55%, transparent), 0 0 32px color-mix(in srgb, var(--color-accent) 30%, transparent)',
          border: '1px solid color-mix(in srgb, var(--color-glow) 25%, transparent)',
        }}
      >
        <div className="pointer-events-none absolute inset-0 rounded-full"
          style={{ background: 'linear-gradient(to bottom, rgba(255,255,255,0.16), transparent)' }} />
        <span className="relative z-10 text-white transition-transform duration-200"
          style={{ transform: open ? 'rotate(90deg)' : 'none' }}>
          {open ? <X className="h-5 w-5" /> : <Bot className="h-6 w-6" />}
        </span>
      </button>

      {/* ── Chat panel ──────────────────────────────────────────────────────── */}
      {open && (
        <div ref={chatRef} className="absolute bottom-20 right-0 w-[420px] ai-pop-in">
          <div
            className="relative flex flex-col overflow-hidden rounded-2xl border border-line"
            style={{
              background: 'color-mix(in srgb, var(--color-bg) 90%, transparent)',
              backdropFilter: 'blur(10px)',
              boxShadow: '0 8px 32px rgba(0,0,0,0.4), var(--shadow-card)',
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-line px-5 pb-3 pt-4">
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-glow" />
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-glow">
                  Nexus AI
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="rounded-full border border-glow/20 px-2 py-0.5 font-mono text-[9px] text-glow"
                  style={{ background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)' }}>
                  Claude
                </span>
                <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[9px] text-faint">
                  Preview
                </span>
                <button type="button" onClick={() => setOpen(false)}
                  className="ml-1 grid h-6 w-6 place-items-center rounded-control text-faint transition-colors hover:bg-raised hover:text-ink">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Context chips */}
            {chips.length > 0 && (
              <div className="flex flex-wrap gap-1.5 border-b border-line px-5 py-2.5">
                {chips.map(chip => (
                  <ContextChip key={chip} label={chip}
                    onRemove={() => setChips(prev => prev.filter(c => c !== chip))} />
                ))}
              </div>
            )}

            {/* Link input strip */}
            {linkMode && (
              <div className="flex items-center gap-2 border-b border-line bg-raised px-5 py-2.5">
                <Link2 className="h-3.5 w-3.5 shrink-0 text-glow" />
                <input
                  autoFocus
                  type="url"
                  value={linkUrl}
                  onChange={e => setLinkUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') submitLink(); if (e.key === 'Escape') setLinkMode(false) }}
                  placeholder="https://…"
                  className="flex-1 bg-transparent font-mono text-xs text-ink outline-none placeholder:text-faint"
                />
                <button type="button" onClick={submitLink}
                  className="font-mono text-[9px] text-glow hover:text-ink transition-colors">Add</button>
                <button type="button" onClick={() => setLinkMode(false)}
                  className="text-faint hover:text-ink transition-colors"><X className="h-3.5 w-3.5" /></button>
              </div>
            )}

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              value={message}
              onChange={e => setMessage(e.target.value.slice(0, MAX_CHARS))}
              onKeyDown={handleKeyDown}
              rows={4}
              autoFocus={chips.length === 0}
              className="w-full resize-none border-none bg-transparent px-5 py-4 text-sm leading-relaxed text-ink outline-none placeholder:text-faint"
              style={{
                scrollbarWidth: 'none',
                fontFamily: codeMode ? 'var(--font-mono)' : 'var(--font-sans)',
                fontSize: codeMode ? '11px' : '14px',
              }}
              placeholder={chips.length > 0
                ? 'What would you like to know about this?'
                : 'Ask about leads, pipeline health, or community insights…'}
            />

            {/* Controls */}
            <div className="px-4 pb-4">
              <div className="flex items-center justify-between">
                {/* Attachment actions */}
                <div className="flex items-center gap-1">
                  <input ref={fileRef} type="file" hidden accept="*/*" onChange={onFileChange} />
                  <div className="flex items-center gap-0.5 rounded-control border border-line p-0.5"
                    style={{ background: 'color-mix(in srgb, var(--color-raised) 60%, transparent)' }}>
                    {/* File */}
                    <button type="button" title="Attach file"
                      onClick={() => fileRef.current?.click()}
                      className="rounded p-2 text-faint transition-all duration-150 hover:bg-raised hover:text-glow active:scale-90">
                      <Paperclip className="h-3.5 w-3.5" />
                    </button>
                    {/* Link */}
                    <button type="button" title="Add URL"
                      onClick={() => { setLinkMode(v => !v); setLinkUrl('') }}
                      className={`rounded p-2 transition-all duration-150 hover:bg-raised active:scale-90 ${
                        linkMode ? 'text-glow bg-raised' : 'text-faint hover:text-glow'}`}>
                      <Link2 className="h-3.5 w-3.5" />
                    </button>
                    {/* Code */}
                    <button type="button" title="Code block"
                      onClick={toggleCode}
                      className={`rounded p-2 transition-all duration-150 hover:bg-raised active:scale-90 ${
                        codeMode ? 'text-glow bg-raised' : 'text-faint hover:text-glow'}`}>
                      <Code2 className="h-3.5 w-3.5" />
                    </button>
                    {/* Mic */}
                    <button type="button" title={isRecording ? 'Stop recording' : 'Voice input'}
                      onClick={toggleMic}
                      className={`rounded p-2 transition-all duration-150 hover:bg-raised active:scale-90 ${
                        isRecording ? 'text-danger animate-pulse' : 'text-faint hover:text-glow'}`}>
                      {isRecording ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>

                {/* Char count + send */}
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[10px] text-faint">
                    {charCount}
                    <span className="text-faint/40">/{MAX_CHARS}</span>
                  </span>
                  <button type="button" onClick={handleSend} disabled={!canSend}
                    className="grid h-9 w-9 place-items-center rounded-control text-white transition-all duration-150 hover:scale-105 active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed"
                    style={{
                      background: 'var(--color-accent)',
                      boxShadow: canSend ? 'var(--shadow-glow)' : 'none',
                    }}>
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* Footer */}
              <div className="mt-3 flex items-center justify-between border-t border-line pt-3 font-mono text-[9px] text-faint">
                <div className="flex items-center gap-1.5">
                  <Info className="h-3 w-3" />
                  <span>
                    <kbd className="rounded border border-line bg-raised px-1 py-0.5 font-mono text-[9px]">Shift+Enter</kbd>
                    {' '}new line
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="h-1.5 w-1.5 rounded-full bg-glow" />
                  <span>NLP engine · P2 Copilot</span>
                </div>
              </div>
            </div>

            {/* Subtle ambient tint */}
            <div className="pointer-events-none absolute inset-0 rounded-2xl"
              style={{ background: 'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 3%, transparent), transparent)' }} />
          </div>
        </div>
      )}
    </div>
  )
}
