/**
 * tone — semantic-tone → Midnight Instrument class strings for the Playbooks
 * surface + run inspector. Full literal classes (never interpolated) so
 * Tailwind's source scan keeps them. One source of truth: step chips, verdict
 * chips, and status dots all read from here, so a "blocked" step and a
 * "reject" verdict are visibly the same red without either component
 * hard-coding it.
 */
export type Tone = 'sage' | 'glow' | 'accent' | 'warn' | 'danger' | 'success' | 'muted' | 'faint'

export const TONE_TEXT: Record<Tone, string> = {
  sage: 'text-sage', glow: 'text-glow', accent: 'text-accent', warn: 'text-warn',
  danger: 'text-danger', success: 'text-success', muted: 'text-muted', faint: 'text-faint',
}

export const TONE_DOT: Record<Tone, string> = {
  sage: 'bg-sage', glow: 'bg-glow', accent: 'bg-accent', warn: 'bg-warn',
  danger: 'bg-danger', success: 'bg-success', muted: 'bg-muted', faint: 'bg-faint',
}

/** Border color for a node's active ring / a chip outline. */
export const TONE_BORDER: Record<Tone, string> = {
  sage: 'border-[rgba(45,212,191,0.55)]',
  glow: 'border-[rgba(96,165,250,0.55)]',
  accent: 'border-[rgba(59,130,246,0.55)]',
  warn: 'border-[rgba(217,169,78,0.55)]',
  danger: 'border-[rgba(224,112,92,0.55)]',
  success: 'border-[rgba(52,211,153,0.55)]',
  muted: 'border-line',
  faint: 'border-line',
}

/** A faint tinted fill for a chip / active node background. */
export const TONE_TINT: Record<Tone, string> = {
  sage: 'bg-[rgba(45,212,191,0.10)]',
  glow: 'bg-[rgba(96,165,250,0.10)]',
  accent: 'bg-[rgba(59,130,246,0.10)]',
  warn: 'bg-[rgba(217,169,78,0.10)]',
  danger: 'bg-[rgba(224,112,92,0.10)]',
  success: 'bg-[rgba(52,211,153,0.10)]',
  muted: 'bg-raised',
  faint: 'bg-raised',
}

export function asTone(t: string): Tone {
  return (t in TONE_TEXT ? t : 'muted') as Tone
}
