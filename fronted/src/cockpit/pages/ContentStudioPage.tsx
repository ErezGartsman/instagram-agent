import { useCallback, useEffect, useMemo, useState } from 'react'
import { Icon } from '../components/Icon'
import { useAuth } from '../auth/AuthProvider'
import { relativeTime } from '../lib/pipeline'
import {
  createContent,
  deleteContent,
  fetchContent,
  SAMPLE_CONTENT,
  STATUS_LABELS,
  STATUS_ORDER,
  updateContent,
  type ContentPiece,
  type ContentStatus,
} from '../lib/content'

type Phase = 'loading' | 'error' | 'ready'
type Draft = {
  title: string
  body: string
  status: ContentStatus
  theme_tags: string[]
  leads_attributed: number | null
}

const toDraft = (p: ContentPiece): Draft => ({
  title: p.title,
  body: p.body,
  status: p.status,
  theme_tags: p.theme_tags,
  leads_attributed: p.leads_attributed,
})

/**
 * Ticket 5.6 — the Content Studio (Studio pillar). The Work Queue's rail +
 * focused-canvas skeleton, but the canvas is an editorial writing surface in
 * Fraunces — the Human voice, for the emotional content work. The cockpit's
 * first write surface (create / edit / save / delete), with the manual
 * "logic behind the magic" lead bridge (true attribution is V2).
 */
export function ContentStudioPage() {
  const { session, devBypass } = useAuth()
  const token = session?.access_token
  const [phase, setPhase] = useState<Phase>('loading')
  const [sample, setSample] = useState(false)
  const [items, setItems] = useState<ContentPiece[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [justSaved, setJustSaved] = useState(false)

  useEffect(() => {
    if (devBypass) {
      setItems(SAMPLE_CONTENT)
      setSample(true)
      setSelectedId((id) => id ?? SAMPLE_CONTENT[0]?.id ?? null)
      setPhase('ready')
      return
    }
    if (!token) {
      setPhase('loading')
      return
    }
    const controller = new AbortController()
    setPhase('loading')
    fetchContent(token, controller.signal)
      .then((list) => {
        setItems(list)
        setSelectedId((id) => id ?? list[0]?.id ?? null)
        setPhase('ready')
      })
      .catch((err: unknown) => {
        if ((err as { name?: string } | null)?.name !== 'AbortError') setPhase('error')
      })
    return () => controller.abort()
  }, [token, devBypass])

  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) ?? null,
    [items, selectedId],
  )

  // Reset the working draft whenever the selected piece changes.
  useEffect(() => {
    setDraft(selected ? toDraft(selected) : null)
    setJustSaved(false)
  }, [selected])

  const dirty = useMemo(() => {
    if (!selected || !draft) return false
    return (
      draft.title !== selected.title ||
      draft.body !== selected.body ||
      draft.status !== selected.status ||
      draft.leads_attributed !== selected.leads_attributed ||
      draft.theme_tags.join('|') !== selected.theme_tags.join('|')
    )
  }, [selected, draft])

  const patch = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d))

  const onSave = useCallback(async () => {
    if (!selected || !draft || busy) return
    setBusy(true)
    try {
      if (devBypass) {
        const updated: ContentPiece = { ...selected, ...draft, updated_at: new Date().toISOString() }
        setItems((xs) => xs.map((x) => (x.id === selected.id ? updated : x)))
      } else if (token) {
        const saved = await updateContent(token, selected.id, draft)
        setItems((xs) => xs.map((x) => (x.id === saved.id ? saved : x)))
      }
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 1600)
    } finally {
      setBusy(false)
    }
  }, [selected, draft, busy, devBypass, token])

  const onNew = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      const blank = { title: '', body: '', status: 'idea' as ContentStatus, theme_tags: [] }
      let created: ContentPiece
      if (devBypass) {
        const now = new Date().toISOString()
        created = { id: crypto.randomUUID(), ...blank, leads_attributed: null,
          created_at: now, updated_at: now, published_at: null }
      } else if (token) {
        created = await createContent(token, blank)
      } else {
        return
      }
      setItems((xs) => [created, ...xs])
      setSelectedId(created.id)
    } finally {
      setBusy(false)
    }
  }, [busy, devBypass, token])

  const onDelete = useCallback(async () => {
    if (!selected || busy) return
    setBusy(true)
    try {
      if (!devBypass && token) await deleteContent(token, selected.id)
      const rest = items.filter((x) => x.id !== selected.id)
      setItems(rest)
      setSelectedId(rest[0]?.id ?? null)
    } finally {
      setBusy(false)
    }
  }, [selected, busy, devBypass, token, items])

  if (phase === 'loading') return <StudioSkeleton />
  if (phase === 'error') return <StudioError />

  return (
    <div className="flex h-full min-h-0 overflow-hidden rounded-card border border-line bg-bg">
      {/* ── Left: the rail — ideas in progress, the precision instrument ─────── */}
      <section aria-label="Content" className="flex w-[280px] shrink-0 flex-col border-r border-line bg-surface">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Content</span>
            {sample && (
              <span className="rounded-control border border-line px-1.5 py-px text-[10px] text-warn">sample</span>
            )}
          </div>
          <button
            onClick={onNew}
            aria-label="New piece"
            className="inline-flex items-center gap-1 rounded-control border border-accent/40 px-2 py-1 text-[11px] text-accent transition-colors hover:bg-accent/10"
          >
            <Icon name="sparkle" size={12} /> New
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {items.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted">No pieces yet — start one.</p>
          ) : (
            STATUS_ORDER.map((status) => {
              const group = items.filter((i) => i.status === status)
              if (group.length === 0) return null
              return (
                <div key={status} className="mb-3">
                  <div className="px-2 pb-1 font-mono text-[10px] uppercase tracking-[0.13em] text-faint">
                    {STATUS_LABELS[status]}
                  </div>
                  {group.map((piece) => (
                    <RailItem
                      key={piece.id}
                      piece={piece}
                      isSelected={piece.id === selectedId}
                      onSelect={() => setSelectedId(piece.id)}
                    />
                  ))}
                </div>
              )
            })
          )}
        </div>
      </section>

      {/* ── Right: the canvas — the Human voice, in Fraunces ─────────────────── */}
      <section className="flex min-w-0 flex-1 flex-col">
        {!selected || !draft ? (
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-accent">
              <Icon name="sparkle" size={22} />
            </span>
            <h3 className="text-base font-semibold text-ink">The Studio</h3>
            <p className="mt-2 max-w-sm text-sm text-muted">
              Select a piece, or start a new one. This is where the magic gets written.
            </p>
          </div>
        ) : (
          <div key={selected.id} className="cq-rise flex min-h-0 flex-1 flex-col">
            {/* Canvas header: status + delete */}
            <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-3">
              <div className="inline-flex overflow-hidden rounded-control border border-line">
                {STATUS_ORDER.map((s) => {
                  const active = draft.status === s
                  return (
                    <button
                      key={s}
                      onClick={() => patch('status', s)}
                      aria-pressed={active}
                      className={`px-3 py-1.5 text-[11px] transition-colors ${
                        active ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-raised hover:text-ink'
                      }`}
                    >
                      {STATUS_LABELS[s]}
                    </button>
                  )
                })}
              </div>
              <button
                onClick={onDelete}
                aria-label="Delete piece"
                className="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-danger/40 hover:text-danger"
              >
                <Icon name="alert" size={13} /> Delete
              </button>
            </div>

            {/* The writing surface — Fraunces */}
            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
              <input
                value={draft.title}
                onChange={(e) => patch('title', e.target.value)}
                placeholder="Untitled piece"
                className="w-full bg-transparent font-serif text-2xl font-light leading-tight text-ink outline-none placeholder:text-faint"
              />
              <input
                value={draft.theme_tags.join(', ')}
                onChange={(e) =>
                  patch('theme_tags', e.target.value.split(',').map((t) => t.trim()).filter(Boolean))
                }
                placeholder="themes (comma separated)"
                className="mt-3 w-full bg-transparent font-mono text-[11px] text-muted outline-none placeholder:text-faint"
              />
              <textarea
                value={draft.body}
                onChange={(e) => patch('body', e.target.value)}
                placeholder="Write the script…"
                className="mt-5 min-h-[280px] w-full resize-none bg-transparent font-serif text-[15px] font-light leading-relaxed text-ink outline-none placeholder:text-faint"
              />
            </div>

            {/* Footer: the "logic behind the magic" bridge + save */}
            <div className="flex items-center justify-between gap-4 border-t border-line px-6 py-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.13em] text-faint">Leads driven</span>
                <input
                  type="number"
                  min={0}
                  value={draft.leads_attributed ?? ''}
                  onChange={(e) =>
                    patch('leads_attributed', e.target.value === '' ? null : Math.max(0, Number(e.target.value)))
                  }
                  placeholder="—"
                  className="w-16 rounded-control border border-line bg-transparent px-2 py-1 font-mono text-xs tabular-nums text-ink outline-none focus:border-accent/40"
                />
                <span className="font-mono text-[10px] text-faint">manual · auto in V2</span>
              </div>
              <div className="flex items-center gap-3">
                {justSaved && <span className="font-mono text-[11px] text-sage">Saved</span>}
                <button
                  onClick={onSave}
                  disabled={!dirty || busy}
                  className="inline-flex items-center gap-1.5 rounded-control border border-accent/40 px-3.5 py-1.5 text-xs text-accent transition-colors hover:bg-accent/10 disabled:cursor-default disabled:opacity-40"
                >
                  <Icon name="check" size={13} /> Save
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function RailItem({
  piece,
  isSelected,
  onSelect,
}: {
  piece: ContentPiece
  isSelected: boolean
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      aria-current={isSelected ? 'true' : undefined}
      className={`relative mb-0.5 flex w-full flex-col items-start rounded-control py-2.5 pl-3.5 pr-2.5 text-left transition-[opacity,background-color] duration-[260ms] ${
        isSelected ? 'bg-raised opacity-100' : 'opacity-40 hover:opacity-100'
      }`}
    >
      <span
        aria-hidden
        className={`absolute left-0 top-1/2 h-7 w-0.5 -translate-y-1/2 rounded-full bg-accent transition-opacity duration-200 ${
          isSelected ? 'opacity-100' : 'opacity-0'
        }`}
      />
      <span className="line-clamp-2 text-sm font-medium leading-snug text-ink">
        {piece.title || 'Untitled piece'}
      </span>
      <span className="mt-1 flex items-center gap-2 font-mono text-[10px] text-faint">
        <span>{relativeTime(piece.updated_at)}</span>
        {piece.leads_attributed != null && (
          <span className="text-accent">· {piece.leads_attributed} leads</span>
        )}
      </span>
    </button>
  )
}

function StudioSkeleton() {
  return (
    <div className="flex h-full min-h-0 overflow-hidden rounded-card border border-line bg-bg" aria-hidden>
      <div className="w-[280px] shrink-0 border-r border-line bg-surface p-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="mb-1 h-12 animate-pulse rounded-control bg-raised/60" />
        ))}
      </div>
      <div className="flex-1 p-6">
        <div className="h-7 w-2/3 animate-pulse rounded-control bg-surface" />
        <div className="mt-5 h-40 animate-pulse rounded-card bg-surface" />
      </div>
    </div>
  )
}

function StudioError() {
  return (
    <div className="flex h-full flex-col items-center justify-center rounded-card border border-line bg-surface px-8 text-center">
      <span className="mb-4 grid h-12 w-12 place-items-center rounded-control border border-line bg-raised text-danger">
        <Icon name="alert" size={22} />
      </span>
      <h3 className="text-base font-semibold text-ink">Couldn&rsquo;t load the Studio</h3>
      <p className="mt-2 max-w-md text-sm text-muted">
        Your content couldn&rsquo;t be reached. Check your connection and reload.
      </p>
    </div>
  )
}
