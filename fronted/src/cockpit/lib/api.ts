// Backend base URL for the Cockpit. Defaults to the local FastAPI dev server;
// in production VITE_API_BASE points at instagram-agent-seven (set in .env.production
// / Vercel). The normalisation mirrors the legacy app: strip a trailing slash and
// repair a single-slash "https:/" that some env editors save by mistake.
export const API_BASE = (
  import.meta.env.VITE_API_BASE ??
  import.meta.env.VITE_API_URL ??
  'http://localhost:8000'
)
  .trim()
  .replace(/\/$/, '')
  .replace(/^(https?):\/(?!\/)/, '$1://')

// ── Command Palette search ────────────────────────────────────────────────────

export type SearchResultType = 'page' | 'person' | 'content' | 'action'

export interface SearchResult {
  type: SearchResultType
  id: string
  /** Primary display text */
  label: string
  /** Secondary context (channel · stage, status, page description) */
  sublabel: string
  /** React Router route to navigate to on selection */
  route: string
}

// ── WhatsApp thread ───────────────────────────────────────────────────────────

export interface ThreadMessage {
  /** 'user' = lead's inbound · 'assistant' = bot handoff ACK · 'operator' = Erez's reply */
  role: 'user' | 'assistant' | 'operator'
  body: string
  at: string  // ISO 8601
}

/** Fetch the merged WhatsApp thread for a person (inbound + outbound). Returns [] on error. */
export async function fetchThread(token: string, personId: string): Promise<ThreadMessage[]> {
  try {
    const res = await fetch(
      `${API_BASE}/api/cockpit/thread/${encodeURIComponent(personId)}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!res.ok) return []
    const data = await res.json() as { messages?: ThreadMessage[] }
    return data.messages ?? []
  } catch {
    return []
  }
}

// ── Copilot draft streaming ───────────────────────────────────────────────────

/**
 * Stream a Copilot reply draft via SSE. Calls `POST /api/cockpit/copilot/stream`
 * and parses the event-stream, firing callbacks per event type:
 *   onChunk(text)  — incremental word delta while the draft streams in
 *   onDone(full)   — the complete draft text when the stream closes cleanly
 *   onError(msg?)  — any fetch or stream error; the caller resets drafting state
 *
 * Pass an AbortSignal to cancel mid-stream (e.g. when the user closes the composer).
 */
export async function streamDraft(
  token: string,
  personId: string,
  intent: string | undefined,
  onChunk: (text: string) => void,
  onDone: (fullText: string) => void,
  onError: (detail?: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/cockpit/copilot/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ person_id: personId, intent: intent ?? null }),
      signal,
    })
  } catch (e) {
    if ((e as Error)?.name !== 'AbortError') onError()
    return
  }
  if (!res.ok || !res.body) {
    onError(`HTTP ${res.status}`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    let done: boolean
    let value: Uint8Array | undefined
    try {
      ;({ done, value } = await reader.read())
    } catch {
      onError()
      return
    }
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE lines end with \n\n; split on newlines and process complete events.
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const event = JSON.parse(line.slice(6)) as {
          type: 'delta' | 'done' | 'error'
          text?: string
          detail?: string
        }
        if (event.type === 'delta' && event.text) onChunk(event.text)
        if (event.type === 'done') { onDone(event.text ?? ''); return }
        if (event.type === 'error') { onError(event.detail); return }
      } catch {
        // ignore malformed SSE line
      }
    }
  }
}

// ── Command Palette search ────────────────────────────────────────────────────

/** Unified cockpit search — people (open opps) + content pieces.
 *  Returns [] on error or when q < 2 chars (handled server-side too). */
export async function searchCockpit(token: string, q: string): Promise<SearchResult[]> {
  try {
    const res = await fetch(
      `${API_BASE}/api/cockpit/search?q=${encodeURIComponent(q)}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!res.ok) return []
    const data = await res.json() as { results?: SearchResult[] }
    return data.results ?? []
  } catch {
    return []
  }
}
