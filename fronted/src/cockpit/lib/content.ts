import { apiFetch } from './http'

// The Content Studio — the Studio pillar. Video scripts + content themes managed
// in the same OS as the CRM, so the "magic" (content) sits beside the "logic"
// (leads). The cockpit's first write surface.

export type ContentStatus = 'idea' | 'drafting' | 'published'

export const STATUS_ORDER: ContentStatus[] = ['idea', 'drafting', 'published']
export const STATUS_LABELS: Record<ContentStatus, string> = {
  idea: 'Ideas',
  drafting: 'Drafting',
  published: 'Published',
}

export type ContentPiece = {
  id: string
  title: string
  body: string
  status: ContentStatus
  theme_tags: string[]
  /** Manual "logic behind the magic" bridge for V1 — null hides it.
   *  True content→lead attribution is a V2 problem; we never fake the number. */
  leads_attributed: number | null
  created_at: string | null
  updated_at: string | null
  published_at: string | null
}

export async function fetchContent(token: string, signal?: AbortSignal): Promise<ContentPiece[]> {
  const data = await apiFetch<{ items?: ContentPiece[] }>('/api/cockpit/content', token, { signal })
  return data.items ?? []
}

export async function createContent(
  token: string,
  draft: Partial<Pick<ContentPiece, 'title' | 'body' | 'status' | 'theme_tags'>>,
): Promise<ContentPiece> {
  const data = await apiFetch<{ item: ContentPiece }>('/api/cockpit/content', token, {
    method: 'POST',
    body: JSON.stringify(draft),
  })
  return data.item
}

export async function updateContent(
  token: string,
  id: string,
  patch: Partial<Pick<ContentPiece, 'title' | 'body' | 'status' | 'theme_tags' | 'leads_attributed'>>,
): Promise<ContentPiece> {
  const data = await apiFetch<{ item: ContentPiece }>(`/api/cockpit/content/${id}`, token, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
  return data.item
}

export async function deleteContent(token: string, id: string): Promise<void> {
  await apiFetch(`/api/cockpit/content/${id}`, token, { method: 'DELETE' })
}

function ago(secs: number): string {
  return new Date(Date.now() - secs * 1000).toISOString()
}

// Dev-bypass sample so the Studio is populated during local UI work. Guarded by
// import.meta.env.DEV → dead-code-eliminated from production builds.
export const SAMPLE_CONTENT: ContentPiece[] = import.meta.env.DEV
  ? [
      {
        id: 'c1', title: 'Why "just leave" is the worst advice you\'ll ever get',
        body: "Everyone says walk away like it's a door. But you're not leaving a room — you're leaving the version of yourself that believed it could work.\n\nThe real question isn't whether to stay. It's who you become on the way out.",
        status: 'drafting', theme_tags: ['self-worth', 'no clichés'],
        leads_attributed: null, created_at: ago(3 * 86400), updated_at: ago(2 * 3600),
        published_at: null,
      },
      {
        id: 'c2', title: 'The cost of over-functioning in a relationship',
        body: 'You became the strong one. The fixer. And somewhere in there you stopped being a person who gets to need things too.',
        status: 'idea', theme_tags: ['emotional dynamics', 'self-worth'],
        leads_attributed: null, created_at: ago(5 * 86400), updated_at: ago(1 * 86400),
        published_at: null,
      },
      {
        id: 'c3', title: 'Self-worth isn\'t a vibe — it\'s a boundary you keep',
        body: 'Self-worth isn\'t how you feel about yourself on a good day. It\'s what you tolerate on a bad one.',
        status: 'idea', theme_tags: ['self-worth'],
        leads_attributed: null, created_at: ago(6 * 86400), updated_at: ago(4 * 86400),
        published_at: null,
      },
      {
        id: 'c4', title: 'The anxious–avoidant trap, explained without jargon',
        body: 'One reaches, one retreats. Both are terrified of the same thing — and both are sure it\'s the other person\'s fault.',
        status: 'published', theme_tags: ['attachment', 'emotional dynamics'],
        leads_attributed: 12, created_at: ago(20 * 86400), updated_at: ago(9 * 86400),
        published_at: ago(9 * 86400),
      },
    ]
  : []
