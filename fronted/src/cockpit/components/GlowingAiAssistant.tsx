/**
 * GlowingAiAssistant — floating AI chat panel.
 *
 * Exports:
 *   GlowingAiAssistant  — mount once in AppShell
 *   pushAiContext(label) — fires 'nexus:ai-context' window event → injects chip + opens panel
 *   ContextTarget        — tiny ✦ button for dashboard elements
 *
 * State model:
 *   messages  — full chat history (user + assistant bubbles)
 *   chips     — context tokens injected from dashboard (dismissed on send)
 *   isRecording — transforms input into waveform recording UI
 *
 * P2 Copilot: assistant replies are simulated until POST /api/cockpit/copilot/draft is wired.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { Paperclip, Link2, Code2, Mic, Send, Info, Bot, X } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

// ── Types ──────────────────────────────────────────────────────────────────────
type Message = {
  role: 'user' | 'assistant'
  content: string
  chips?: string[]   // context chips attached at send time
  file?: string      // filename if the message is a file attachment
}

// ── Context bridge (window-event based, zero prop drilling) ────────────────────
export const pushAiContext = (label: string) => {
  window.dispatchEvent(new CustomEvent('nexus:ai-context', { detail: { label } }))
}

// ── ContextTarget ──────────────────────────────────────────────────────────────
interface ContextTargetProps { label: string; className?: string }
export function ContextTarget({ label, className = '' }: ContextTargetProps) {
  const [flash, setFlash] = useState(false)
  const handle = () => { pushAiContext(label); setFlash(true); setTimeout(() => setFlash(false), 700) }
  return (
    <button type="button" title={`Ask Nexus AI: ${label}`} onClick={handle}
      className={`inline-flex items-center justify-center rounded transition-all duration-200 ${
        flash ? 'text-glow scale-125' : 'text-faint/40 hover:text-glow hover:scale-110'
      } ${className}`}>
      <span className="select-none text-[9px] leading-none">✦</span>
    </button>
  )
}

// ── Context chip pill ──────────────────────────────────────────────────────────
function ContextChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-glow/25 px-2.5 py-0.5 font-mono text-[9px] text-glow"
      style={{ background: 'color-mix(in srgb, var(--color-accent) 12%, transparent)' }}>
      ✦ {label}
      <button type="button" onClick={onRemove} className="ml-0.5 opacity-60 hover:opacity-100 transition-opacity">
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  )
}

// ── Message bubble ─────────────────────────────────────────────────────────────
function Bubble({ msg }: { msg: Message }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[82%] rounded-2xl rounded-br-sm px-3.5 py-2.5 text-sm text-white"
          style={{ background: 'var(--color-accent)', boxShadow: 'var(--shadow-glow)' }}>
          {msg.chips?.map(c => (
            <div key={c} className="mb-1.5 font-mono text-[8px] text-white/55">✦ {c}</div>
          ))}
          {msg.file ? (
            <div className="flex items-center gap-2">
              <Paperclip className="h-3.5 w-3.5 shrink-0 opacity-70" />
              <span className="font-mono text-[11px]">{msg.file}</span>
            </div>
          ) : msg.content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[88%] rounded-2xl rounded-bl-sm border border-glow/15 bg-raised px-3.5 py-2.5 text-sm text-ink">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="text-[9px] leading-none text-glow">✦</span>
          <span className="font-mono text-[8px] uppercase tracking-wider text-glow">Nexus</span>
        </div>
        {msg.content}
      </div>
    </div>
  )
}

// ── Waveform bars (recording mode) ─────────────────────────────────────────────
function Waveform() {
  return (
    <div className="flex flex-1 items-center justify-center gap-[3px]" style={{ height: 28 }}>
      {Array.from({ length: 22 }, (_, i) => (
        <div key={i}
          className="w-[3px] rounded-full bg-danger/75"
          style={{
            height: 14,
            transformOrigin: 'center',
            animation: `wave-bar ${0.55 + (i % 5) * 0.07}s ease-in-out infinite alternate`,
            animationDelay: `${(i * 0.032).toFixed(3)}s`,
          }}
        />
      ))}
    </div>
  )
}

// ── Simulated assistant reply ──────────────────────────────────────────────────
function buildReply(chips: string[], content: string): string {
  const ref = chips[0] ?? (content.slice(0, 55) || 'your query')
  return `Received your query about "${ref}". ` +
    `The Nexus reasoning engine (P2 Copilot) will process this in the next workstream — ` +
    `Erez will be notified and can respond directly from the Work Queue.`
}

const MAX_CHARS = 2000

// ── Main component ─────────────────────────────────────────────────────────────
export function GlowingAiAssistant() {
  const [open, setOpen]                 = useState(false)
  const [messages, setMessages]         = useState<Message[]>([])
  const [message, setMessage]           = useState('')
  const [chips, setChips]               = useState<string[]>([])
  const [linkMode, setLinkMode]         = useState(false)
  const [linkUrl, setLinkUrl]           = useState('')
  const [codeMode, setCodeMode]         = useState(false)
  const [isRecording, setIsRecording]   = useState(false)
  const [recordingTime, setRecordingTime] = useState(0)
  const { session }                     = useAuth()

  const chatRef       = useRef<HTMLDivElement>(null)
  const textareaRef   = useRef<HTMLTextAreaElement>(null)
  const fileRef       = useRef<HTMLInputElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef        = useRef<any>(null)

  // ── Scroll to newest message ────────────────────────────────────────────────
  const scrollToBottom = useCallback(() => {
    setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 60)
  }, [])

  // ── Context event listener ──────────────────────────────────────────────────
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

  // ── Recording timer ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!isRecording) { setRecordingTime(0); return }
    const id = setInterval(() => setRecordingTime(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [isRecording])

  // ── Close panel on outside click ────────────────────────────────────────────
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

  // ── Escape to close ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open])

  // ── Send message ────────────────────────────────────────────────────────────
  const handleSend = useCallback(() => {
    const hasContent = message.trim().length > 0 || chips.length > 0
    if (!hasContent) return

    const userMsg: Message = { role: 'user', content: message.trim(), chips: chips.length ? [...chips] : undefined }
    setMessages(prev => [...prev, userMsg])
    setMessage('')
    setChips([])
    setCodeMode(false)
    setLinkMode(false)
    scrollToBottom()

    // Simulated assistant reply (replace with real API call in P2)
    // session.access_token will be the bearer token for POST /api/cockpit/copilot/draft
    setTimeout(() => {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: buildReply(userMsg.chips ?? [], userMsg.content),
      }])
      scrollToBottom()
    }, 900)
  }, [message, chips, session, scrollToBottom])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  // ── File attach ─────────────────────────────────────────────────────────────
  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const msg: Message = { role: 'user', content: '', file: file.name }
    setMessages(prev => [...prev, msg])
    scrollToBottom()
    setTimeout(() => {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `File "${file.name}" received. I'll include it in context when the P2 engine goes live.`,
      }])
      scrollToBottom()
    }, 900)
    e.target.value = ''
  }

  // ── Link inject ─────────────────────────────────────────────────────────────
  const submitLink = () => {
    if (!linkUrl.trim()) { setLinkMode(false); return }
    const url = linkUrl.startsWith('http') ? linkUrl : `https://${linkUrl}`
    setMessage(prev => prev ? `${prev}\n[URL: ${url}]` : `[URL: ${url}]`)
    setLinkUrl(''); setLinkMode(false)
    textareaRef.current?.focus()
  }

  // ── Code toggle ─────────────────────────────────────────────────────────────
  const toggleCode = () => {
    setCodeMode(v => !v)
    if (!codeMode && message && !message.startsWith('```'))
      setMessage(prev => '```\n' + prev + '\n```')
  }

  // ── Voice recording ─────────────────────────────────────────────────────────
  const startRecording = () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const win = window as any
    const SR = win.SpeechRecognition || win.webkitSpeechRecognition
    if (!SR) {
      setMessage('[Voice input not supported in this browser]')
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

  const stopRecording = () => {
    recRef.current?.stop()
    setIsRecording(false)
  }

  const fmtTime = (s: number) =>
    `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  const canSend    = (message.trim().length > 0 || chips.length > 0) && message.length <= MAX_CHARS
  const hasHistory = messages.length > 0

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
            ? '0 0 10px color-mix(in srgb, var(--color-glow) 35%, transparent)'
            : '0 0 18px color-mix(in srgb, var(--color-glow) 50%, transparent), 0 0 36px color-mix(in srgb, var(--color-accent) 28%, transparent)',
          border: '1px solid color-mix(in srgb, var(--color-glow) 22%, transparent)',
        }}
      >
        <div className="pointer-events-none absolute inset-0 rounded-full"
          style={{ background: 'linear-gradient(to bottom, rgba(255,255,255,0.15), transparent)' }} />
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
              minHeight: hasHistory ? 440 : 'auto',
              maxHeight: 560,
            }}
          >
            {/* Header */}
            <div className="flex shrink-0 items-center justify-between border-b border-line px-5 pb-3 pt-4">
              <div className="flex items-center gap-2">
                <div className="h-1.5 w-1.5 rounded-full bg-glow" />
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-glow">Nexus AI</span>
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

            {/* ── Chat history ────────────────────────────────────────────── */}
            {hasHistory && (
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4" style={{ scrollbarWidth: 'none' }}>
                <div className="flex flex-col gap-3">
                  {messages.map((msg, i) => <Bubble key={i} msg={msg} />)}
                </div>
                <div ref={messagesEndRef} />
              </div>
            )}

            {/* ── Context chips ────────────────────────────────────────────── */}
            {chips.length > 0 && (
              <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-line px-5 py-2.5">
                {chips.map(chip => (
                  <ContextChip key={chip} label={chip}
                    onRemove={() => setChips(prev => prev.filter(c => c !== chip))} />
                ))}
              </div>
            )}

            {/* ── Link input strip ─────────────────────────────────────────── */}
            {linkMode && (
              <div className="flex shrink-0 items-center gap-2 border-b border-line bg-raised px-5 py-2.5">
                <Link2 className="h-3.5 w-3.5 shrink-0 text-glow" />
                <input autoFocus type="url" value={linkUrl}
                  onChange={e => setLinkUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') submitLink(); if (e.key === 'Escape') setLinkMode(false) }}
                  placeholder="https://…"
                  className="flex-1 bg-transparent font-mono text-xs text-ink outline-none placeholder:text-faint" />
                <button type="button" onClick={submitLink}
                  className="font-mono text-[9px] text-glow transition-colors hover:text-ink">Add</button>
                <button type="button" onClick={() => setLinkMode(false)}
                  className="text-faint transition-colors hover:text-ink"><X className="h-3.5 w-3.5" /></button>
              </div>
            )}

            {/* ── Input area: recording UI OR textarea ─────────────────────── */}
            {isRecording ? (
              /* Recording state */
              <div className="shrink-0 px-5 py-4">
                <div className="flex items-center gap-3 rounded-xl px-4 py-3"
                  style={{
                    border: '1px solid color-mix(in srgb, var(--color-danger) 35%, transparent)',
                    background: 'color-mix(in srgb, var(--color-danger) 6%, transparent)',
                  }}>
                  {/* Pulsing dot */}
                  <div className="relative flex h-3 w-3 shrink-0 items-center justify-center">
                    <div className="absolute h-full w-full animate-ping rounded-full opacity-40"
                      style={{ background: 'var(--color-danger)' }} />
                    <div className="h-2 w-2 rounded-full" style={{ background: 'var(--color-danger)' }} />
                  </div>
                  {/* Timer */}
                  <span className="shrink-0 font-mono text-sm tabular-nums" style={{ color: 'var(--color-danger)' }}>
                    {fmtTime(recordingTime)}
                  </span>
                  {/* Animated waveform */}
                  <Waveform />
                  {/* Stop button */}
                  <button type="button" onClick={stopRecording} title="Stop recording"
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-white transition-all hover:scale-105"
                    style={{ background: 'var(--color-danger)' }}>
                    <div className="h-3 w-3 rounded-sm bg-white" />
                  </button>
                </div>
                <p className="mt-2 text-center font-mono text-[9px] text-faint">
                  Speak clearly · stops automatically when silent
                </p>
              </div>
            ) : (
              /* Normal textarea */
              <textarea
                ref={textareaRef}
                value={message}
                onChange={e => setMessage(e.target.value.slice(0, MAX_CHARS))}
                onKeyDown={handleKeyDown}
                rows={hasHistory ? 2 : 4}
                className="w-full shrink-0 resize-none border-none bg-transparent px-5 py-4 text-sm leading-relaxed text-ink outline-none placeholder:text-faint"
                style={{
                  scrollbarWidth: 'none',
                  fontFamily: codeMode ? 'var(--font-mono)' : 'var(--font-sans)',
                  fontSize: codeMode ? '11px' : '14px',
                }}
                placeholder={chips.length > 0
                  ? 'What would you like to know about this?'
                  : 'Ask about leads, pipeline health, or community insights…'}
              />
            )}

            {/* ── Controls ─────────────────────────────────────────────────── */}
            <div className="shrink-0 px-4 pb-4">
              <div className="flex items-center justify-between">
                {/* Attachment actions */}
                <div className="flex items-center gap-1">
                  <input ref={fileRef} type="file" hidden accept="*/*" onChange={onFileChange} />
                  <div className="flex items-center gap-0.5 rounded-control border border-line p-0.5"
                    style={{ background: 'color-mix(in srgb, var(--color-raised) 60%, transparent)' }}>
                    <button type="button" title="Attach file"
                      onClick={() => fileRef.current?.click()}
                      className="rounded p-2 text-faint transition-all hover:bg-raised hover:text-glow active:scale-90">
                      <Paperclip className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" title="Add URL"
                      onClick={() => { setLinkMode(v => !v); setLinkUrl('') }}
                      className={`rounded p-2 transition-all hover:bg-raised active:scale-90 ${linkMode ? 'bg-raised text-glow' : 'text-faint hover:text-glow'}`}>
                      <Link2 className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" title="Code block"
                      onClick={toggleCode}
                      className={`rounded p-2 transition-all hover:bg-raised active:scale-90 ${codeMode ? 'bg-raised text-glow' : 'text-faint hover:text-glow'}`}>
                      <Code2 className="h-3.5 w-3.5" />
                    </button>
                    {/* Mic: click to START recording (correct state: Mic icon when idle) */}
                    <button type="button" title="Voice input"
                      onClick={startRecording}
                      disabled={isRecording}
                      className="rounded p-2 text-faint transition-all hover:bg-raised hover:text-glow active:scale-90 disabled:opacity-30">
                      <Mic className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {/* Char count + send */}
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[10px] text-faint">
                    {message.length}<span className="text-faint/40">/{MAX_CHARS}</span>
                  </span>
                  <button type="button" onClick={handleSend} disabled={!canSend || isRecording}
                    className="grid h-9 w-9 place-items-center rounded-control text-white transition-all hover:scale-105 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
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

            {/* Ambient tint */}
            <div className="pointer-events-none absolute inset-0 rounded-2xl"
              style={{ background: 'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 3%, transparent), transparent)' }} />
          </div>
        </div>
      )}
    </div>
  )
}
