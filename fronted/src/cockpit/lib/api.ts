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
