/**
 * GlowingAiAssistant — floating AI chat panel.
 *
 * Exports:
 *   GlowingAiAssistant  — mount once in AppShell
 *   pushAiContext(label) — fires 'nexus:ai-context' window event → injects chip + opens panel
 *   ContextTarget        — tiny ✦ button for dashboard elements
 *
 * State model:
 *   messages    — full chat history (user + assistant bubbles)
 *   chips       — context tokens injected from dashboard (dismissed on send)
 *   isRecording — transforms input into waveform recording UI
 *
 * Backend: POST /api/cockpit/ai/chat — Gemini 2.5 Flash with live DB context.
 * Context chips are parsed server-side into real SQL queries so the LLM has
 * grounded data, not hallucinated numbers.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { Paperclip, Link2, Code2, Mic, Send, Info, Bot, X } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// ── Types ──────────────────────────────────────────────────────────────────────
type ContextData = Record<string, unknown> | null

type Message = {
  role:         'user' | 'assistant'
  content:      string
  chips?:       string[]     // context chips attached at send time
  file?:        string       // filename if the message is a file attachment
  intent?:      string       // backend-signalled widget type
  context_data?: ContextData  // structured DB data for the widget
  actions?:     string[]     // suggested follow-up chips
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

// ── ReplyText — strips raw Markdown into clean semantic spans ─────────────────
// Handles **bold**, *italic*, and bare line-breaks without any library.
function ReplyText({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <div className="space-y-1">
      {lines.map((line, li) => {
        if (!line.trim()) return <div key={li} className="h-2" />
        // Segment each line by **bold** spans
        const parts: { t: string; bold: boolean }[] = []
        let remaining = line
        while (remaining) {
          const idx = remaining.indexOf('**')
          if (idx === -1) { parts.push({ t: remaining, bold: false }); break }
          if (idx > 0)     parts.push({ t: remaining.slice(0, idx), bold: false })
          const end = remaining.indexOf('**', idx + 2)
          if (end === -1) { parts.push({ t: remaining.slice(idx), bold: false }); break }
          parts.push({ t: remaining.slice(idx + 2, end), bold: true })
          remaining = remaining.slice(end + 2)
        }
        return (
          <p key={li} className="leading-relaxed">
            {parts.map((p, pi) =>
              p.bold
                ? <strong key={pi} className="font-semibold text-ink">{p.t}</strong>
                : <span key={pi}>{p.t}</span>
            )}
          </p>
        )
      })}
    </div>
  )
}

// ── Generative UI widgets ─────────────────────────────────────────────────────

function SlaWidget({ data }: { data: ContextData }) {
  if (!data) return null
  const d = data as { name: string; stage: string; hours_in_stage: number; target_hours: number; warn_hours: number; sla_status: string }
  const pct   = Math.min((d.hours_in_stage / (d.target_hours || 1)) * 100, 100)
  const isBreached = d.sla_status === 'breach'
  const isWarn     = d.sla_status === 'warn'
  const statusColor = isBreached ? 'text-danger' : isWarn ? 'text-warn' : 'text-success'
  const barColor    = isBreached ? 'var(--color-danger)' : isWarn ? 'var(--color-warn)' : 'var(--color-success)'
  return (
    <div className="mt-2.5 rounded-control border border-line p-3"
      style={{ background: 'color-mix(in srgb, var(--color-bg) 80%, transparent)' }}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] font-semibold text-ink">{d.name}</span>
        <span className={`rounded-full px-2 py-0.5 font-mono text-[8px] uppercase tracking-wider ${statusColor}`}
          style={{ background: `color-mix(in srgb, ${barColor} 12%, transparent)`, border: `1px solid color-mix(in srgb, ${barColor} 25%, transparent)` }}>
          {d.sla_status}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <span className="font-mono text-[9px] text-muted w-14 shrink-0">{d.stage}</span>
        <div className="flex-1 h-1.5 rounded-full bg-raised overflow-hidden">
          <div className="h-full rounded-full transition-[width] duration-700"
            style={{ width: `${pct}%`, background: barColor }} />
        </div>
        <span className={`font-mono text-[9px] tabular-nums shrink-0 ${statusColor}`}>
          {d.hours_in_stage}h / {d.target_hours}h
        </span>
      </div>
    </div>
  )
}

function FunnelWidget({ data }: { data: ContextData }) {
  if (!data) return null
  const d = data as { total_leads: number; stages: { stage: string; count: number; conv_pct: number | null }[] }
  const maxCount = Math.max(...d.stages.map(s => s.count), 1)
  const LABELS: Record<string, string> = {
    engaged: 'Engaged', qualified: 'Qualified', captured: 'Captured',
    briefed: 'Briefed', booked: 'Booked',
  }
  return (
    <div className="mt-2.5 rounded-control border border-line p-3 space-y-1.5"
      style={{ background: 'color-mix(in srgb, var(--color-bg) 80%, transparent)' }}>
      <div className="mb-2 font-mono text-[9px] text-faint">{d.total_leads} total leads</div>
      {d.stages.map(s => (
        <div key={s.stage} className="flex items-center gap-2">
          <span className="w-14 shrink-0 font-mono text-[9px] text-muted">{LABELS[s.stage] ?? s.stage}</span>
          <div className="flex-1 h-1.5 rounded-full bg-raised overflow-hidden">
            <div className="h-full rounded-full"
              style={{ width: `${(s.count / maxCount) * 100}%`, background: 'var(--color-accent)', opacity: 0.85 }} />
          </div>
          <span className="w-5 shrink-0 font-mono text-[9px] tabular-nums text-ink text-right">{s.count}</span>
          <span className={`w-10 shrink-0 font-mono text-[9px] tabular-nums text-right ${
            s.conv_pct === null ? 'text-faint'
            : s.conv_pct >= 60 ? 'text-success'
            : s.conv_pct >= 30 ? 'text-warn'
            : 'text-danger'
          }`}>{s.conv_pct !== null ? `${s.conv_pct}%→` : ''}</span>
        </div>
      ))}
    </div>
  )
}

function VelocityWidget({ data }: { data: ContextData }) {
  if (!data) return null
  const d = data as { stage: string; avg_hours: number; median_hours: number | null; conv_pct: number | null }
  const fmt = (h: number | null) => {
    if (h === null) return '—'
    if (h < 1)  return '<1h'
    if (h < 24) return `${Math.round(h)}h`
    const days = Math.floor(h / 24), hrs = Math.round(h % 24)
    return hrs > 0 ? `${days}d ${hrs}h` : `${days}d`
  }
  return (
    <div className="mt-2.5 flex gap-2 rounded-control border border-line p-3"
      style={{ background: 'color-mix(in srgb, var(--color-bg) 80%, transparent)' }}>
      {[
        { label: 'Avg time', value: fmt(d.avg_hours) },
        { label: 'Median',   value: fmt(d.median_hours) },
        { label: 'Conv. rate', value: d.conv_pct !== null ? `${d.conv_pct}%` : '—' },
      ].map(m => (
        <div key={m.label} className="flex-1 rounded border border-line/50 p-2 text-center">
          <div className="font-mono text-base tabular-nums text-ink">{m.value}</div>
          <div className="mt-0.5 font-mono text-[8px] text-faint">{m.label}</div>
        </div>
      ))}
    </div>
  )
}

function PostWidget({ data }: { data: ContextData }) {
  if (!data) return null
  const d = data as { shortcode: string; likes: number; comments: number }
  const fmt = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
  return (
    <div className="mt-2.5 flex items-center gap-3 rounded-control border border-line px-3 py-2.5"
      style={{ background: 'color-mix(in srgb, var(--color-bg) 80%, transparent)' }}>
      <span className="font-mono text-[11px] text-muted flex-1 truncate">{d.shortcode}</span>
      <span className="font-mono text-[11px] tabular-nums text-accent">{fmt(d.likes)} ♥</span>
      <span className="font-mono text-[11px] tabular-nums text-faint">{fmt(d.comments)} ✦</span>
      <a href={`https://instagram.com/p/${d.shortcode}`} target="_blank" rel="noreferrer"
        className="font-mono text-[9px] text-glow/70 hover:text-glow transition-colors">
        View ↗
      </a>
    </div>
  )
}

function CommunityWidget({ data }: { data: ContextData }) {
  if (!data) return null
  const d = data as { community_size: number; total_likes: number; total_comments: number; total_posts: number }
  const fmt = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
  const stats = [
    { label: 'Community', value: fmt(d.community_size) },
    { label: 'Likes',     value: fmt(d.total_likes) },
    { label: 'Comments',  value: fmt(d.total_comments) },
    { label: 'Posts',     value: fmt(d.total_posts) },
  ]
  return (
    <div className="mt-2.5 grid grid-cols-4 gap-1.5 rounded-control border border-line p-2.5"
      style={{ background: 'color-mix(in srgb, var(--color-bg) 80%, transparent)' }}>
      {stats.map(s => (
        <div key={s.label} className="rounded border border-line/50 p-1.5 text-center">
          <div className="font-mono text-sm tabular-nums text-ink">{s.value}</div>
          <div className="mt-0.5 font-mono text-[8px] text-faint">{s.label}</div>
        </div>
      ))}
    </div>
  )
}

function WidgetRenderer({ intent, data }: { intent?: string; data: ContextData }) {
  if (!intent || !data) return null
  if (intent.startsWith('sla_lead'))    return <SlaWidget data={data} />
  if (intent === 'funnel')              return <FunnelWidget data={data} />
  if (intent === 'velocity')            return <VelocityWidget data={data} />
  if (intent === 'post')                return <PostWidget data={data} />
  if (intent === 'community')           return <CommunityWidget data={data} />
  return null
}

// ── Action chips — pre-filled follow-up queries ───────────────────────────────
function ActionChips({ actions, onAction }: { actions: string[]; onAction: (a: string) => void }) {
  if (!actions.length) return null
  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      {actions.map(a => (
        <button key={a} type="button" onClick={() => onAction(a)}
          className="rounded-full border border-glow/20 px-2.5 py-1 font-mono text-[9px] text-glow/70 transition-all hover:border-glow/40 hover:text-glow hover:scale-[1.02] active:scale-95"
          style={{ background: 'color-mix(in srgb, var(--color-accent) 6%, transparent)' }}>
          {a}
        </button>
      ))}
    </div>
  )
}

// ── Message bubble ─────────────────────────────────────────────────────────────
function Bubble({ msg, onAction }: { msg: Message; onAction: (a: string) => void }) {
  // Typing indicator
  if (msg.role === 'assistant' && msg.content === '__thinking__') {
    return (
      <div className="flex justify-start">
        <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm border border-glow/15 bg-raised px-3.5 py-3">
          <span className="font-mono text-[9px] leading-none text-glow">✦</span>
          {[0, 1, 2].map(i => (
            <div key={i}
              className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>
      </div>
    )
  }

  // User bubble
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
          ) : <ReplyText text={msg.content} />}
        </div>
      </div>
    )
  }

  // Assistant bubble — full Generative UI
  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] rounded-2xl rounded-bl-sm border border-glow/15 bg-raised px-3.5 py-2.5 text-sm text-ink">
        {/* Header */}
        <div className="mb-2 flex items-center gap-1.5">
          <span className="text-[9px] leading-none text-glow">✦</span>
          <span className="font-mono text-[8px] uppercase tracking-wider text-glow">Nexus</span>
        </div>
        {/* Formatted prose */}
        <ReplyText text={msg.content} />
        {/* Generative widget (intent-driven) */}
        <WidgetRenderer intent={msg.intent} data={msg.context_data ?? null} />
        {/* Suggested follow-up action chips */}
        {msg.actions && msg.actions.length > 0 && (
          <ActionChips actions={msg.actions} onAction={onAction} />
        )}
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

// ── Real API call ──────────────────────────────────────────────────────────────
type AiApiResponse = {
  status:       string
  reply:        string
  intent?:      string
  context_data?: ContextData
  actions?:     string[]
}

async function fetchAiReply(
  token: string,
  message: string,
  chips: string[],
  history: Message[],
): Promise<AiApiResponse> {
  const res = await fetch(`${API_BASE}/api/cockpit/ai/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      message,
      chips,
      history: history
        .filter(m => m.content !== '__thinking__')
        .slice(-6)
        .map(m => ({ role: m.role, content: m.file ? `[File: ${m.file}]` : m.content })),
    }),
    signal: AbortSignal.timeout(35_000),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json() as AiApiResponse
  if (data.status === 'error') throw new Error(data.reply)
  return data
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

  // ── Send message — real Gemini call via /api/cockpit/ai/chat ────────────────
  const handleSend = useCallback(async () => {
    const hasContent = message.trim().length > 0 || chips.length > 0
    if (!hasContent) return

    const token = session?.access_token
    const userMsg: Message = {
      role:    'user',
      content: message.trim(),
      chips:   chips.length ? [...chips] : undefined,
    }

    // Snapshot current history BEFORE state updates (for the API call below)
    const historySnapshot = messages.slice()

    setMessages(prev => [...prev, userMsg, { role: 'assistant', content: '__thinking__' }])
    setMessage('')
    setChips([])
    setCodeMode(false)
    setLinkMode(false)
    scrollToBottom()

    if (!token) {
      setMessages(prev =>
        prev.map(m => m.content === '__thinking__'
          ? { role: 'assistant', content: 'Sign in to use the AI assistant.' }
          : m)
      )
      return
    }

    try {
      const res = await fetchAiReply(token, userMsg.content, userMsg.chips ?? [], historySnapshot)
      setMessages(prev => prev.map(m =>
        m.content === '__thinking__'
          ? { role: 'assistant', content: res.reply, intent: res.intent, context_data: res.context_data, actions: res.actions }
          : m
      ))
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Connection error — please try again.'
      setMessages(prev =>
        prev.map(m => m.content === '__thinking__' ? { role: 'assistant', content: errMsg } : m)
      )
    }
    scrollToBottom()
  }, [message, chips, messages, session, scrollToBottom])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  // ── File attach ─────────────────────────────────────────────────────────────
  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const token = session?.access_token
    const fileMsg: Message = { role: 'user', content: '', file: file.name }

    setMessages(prev => [...prev, fileMsg, { role: 'assistant', content: '__thinking__' }])
    scrollToBottom()
    e.target.value = ''

    if (!token) {
      setMessages(prev =>
        prev.map(m => m.content === '__thinking__'
          ? { role: 'assistant', content: 'Sign in to use the AI assistant.' }
          : m)
      )
      return
    }

    try {
      const res = await fetchAiReply(token, `[File: ${file.name}]`, [], messages)
      setMessages(prev =>
        prev.map(m => m.content === '__thinking__'
          ? { role: 'assistant', content: res.reply, intent: res.intent, context_data: res.context_data, actions: res.actions }
          : m)
      )
    } catch {
      setMessages(prev =>
        prev.map(m => m.content === '__thinking__'
          ? { role: 'assistant', content: `File "${file.name}" noted. Unable to reach the AI — please try again.` }
          : m)
      )
    }
    scrollToBottom()
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

  // Action chip handler — pre-fills the textarea and auto-sends
  const handleAction = useCallback((action: string) => {
    setMessage(action)
    setOpen(true)
    setTimeout(() => textareaRef.current?.focus(), 100)
  }, [])

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
                  {messages.map((msg, i) => <Bubble key={i} msg={msg} onAction={handleAction} />)}
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
