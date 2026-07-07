# NEXUS — Project Instructions

Standing rules for Claude in this repository. These OVERRIDE default behavior and
must survive every context compaction. Read them at the start of every session.

## 1. The Golden Rule — always address Erez by name
Begin **every** response to the user with his name, "Erez"
(e.g., "Erez, I've built…", "Erez, here are the steps…"). No exceptions, every turn.

## 2. Roadmap alignment — the next milestone is "The Cockpit"
The shipped milestone is the WhatsApp qualification funnel (Sprint 4). The **next
major milestone is Sprint 5: "The Cockpit"** — a comprehensive command center /
dashboard to manage all leads and conversations in one place. It begins once the
real number (0546150955) is stable in production. Keep proposals and architecture
decisions pointed at that north star.

## 3. WhatsApp bot — intake assistant, NOT a counselor (LOCKED, Ticket 4.6)
Pivoted 2026-06-21 after the funnel sent generic "therapist" advice to emotionally
heavy messages and killed leads. The WhatsApp bot's OUTWARD persona is strictly an
intake assistant / clinic manager. **Absolute rule:** on first contact it sends
exactly ONE fully transparent automated handoff message (`whatsapp.handoff_ack` —
"this is automated… Erez reads and replies personally"), then goes COMPLETELY
SILENT. Zero conversational looping, zero AI advice/insights/qualification. The
old qualification funnel (`_wa_run_qualification`, opener/insight/price/booking) is
RETIRED — kept in code for rollback only; do not re-wire without an explicit
decision to reverse this pivot.

**Inward, the brain keeps running silently:** inbound messages are still persisted,
the opportunity is still opened (so the person lands in the Work Queue), and the
daily formation cron still builds the Person-360 (goal / tension / essence). The
Machine organizes the data; the Human (Erez) does the actual consulting.

**Safety exception:** the crisis gate (`is_crisis` → `crisis.message`) ALWAYS fires,
upstream of everything — never silence a self-harm signal.

## 4. Cockpit design discipline — Midnight Instrument (pivoted 2026-07-05)
The violet Neon Glassmorphism Engine (2026-06-22) and the interim warm-gold drift
are **retired**. The new system is **Midnight Instrument** — deep-navy void +
electric-blue neon — pivoted on Erez's directive 2026-07-05 (Vision UI reference
family: near-black navy depth, glass panels, electric-blue signatures).

**Three-layer depth architecture — never collapse any layer:**
1. **Void + ambient glow** — CSS radial gradients on `.cockpit-root`: electric-blue
   crown top (`rgba(59,130,246,0.28)`) + abyssal blue pool bottom-right
   (`rgba(37,99,235,0.18)`) + violet whisper bottom-left (`rgba(109,40,217,0.10)`)
   over `#04070f` void base. No images, no canvas — pure CSS.
2. **Glass panels** — `bg-surface` (`rgba(148,186,255,0.055)`) + `backdrop-blur-xl`
   on section-level containers: Sidebar, Topbar, StatCard, feature cards.
   **Never on list rows** (GPU cost). List rows get `bg-surface` rgba only.
3. **Neon signatures** — `--color-accent: #3b82f6` (electric blue) for fills/badges;
   `--color-glow: #60a5fa` for pip glow, confidence %, gradient tips. Violet is
   ambient depth only — never a voice. One neon `box-shadow` per active element.

Canonical tokens in `fronted/src/cockpit/index.css` (`@theme`). Semantic utilities
only — `bg-surface`, `bg-raised`, `text-ink`, `text-muted`, `text-faint`,
`border-line`, `text-accent`, `text-glow`, `text-sage`, `text-success` / `text-warn`
/ `text-danger` — never raw hex in components.

**Primitives (midnight, 2026-07-05):** bg `#04070f` · surface `rgba(148,186,255,0.055)`
glass · raised `rgba(148,186,255,0.09)` hover glass · ink `#f2f6ff` · muted `#9aa7bd` ·
faint `#55617a` · line `rgba(148,186,255,0.08)` · accent `#3b82f6` · glow `#60a5fa` ·
sage `#2dd4bf` (teal counter-accent) · success `#34d399` · warn `#d9a94e` · danger
`#e0705c`. Radius 9px (controls) / 14px (cards).

**Elevation:** `--shadow-card: 0 0 24px rgba(59,130,246,0.14), inset 0 1px 0 rgba(190,214,255,0.09)`
on glass cards. `--shadow-glow: 0 0 8px rgba(96,165,250,0.90), 0 0 16px rgba(59,130,246,0.50)`
for the active nav pip. No flat black shadows — glow-based only.

**Typography — two voices (the logic machine):**
**Inter** for all UI. **JetBrains Mono** `tabular-nums` for every numeral.
**Fraunces** is reserved for the Overview `greeting()` heading and the lead
**essence** line (Work Queue + Person Dossier header — the same semantic object)
ONLY — **nowhere else in the cockpit**. It is "the human
voice in the machine" per Erez's decision. Enforce strictly; reject any other
`font-serif` usage.

**Motion — signature boot, quiet after (locked 2026-07-05):** one GSAP boot
sequence per session (`components/BootSequence.tsx`, ~1.15s, skippable, sessionStorage-
guarded, reduced-motion-safe); afterwards sub-300ms meaning-first micro-motion only.
Queue rows FLIP on live re-rank with a glow flash on risers. The AI orb's breathing
halo (`cq-orb-halo`) is the single approved ambient exception.

**Motion whisper budget** (CSS): `cq-rise` 0.26s · `cq-rise-slow` 0.42s · `cq-grow`
0.7s · `cq-crystallize` 0.32s (AI widget assembly) · `cq-thought` (AI thinking
shimmer) · `cq-sla-pulse` (accountability filament). All killed by the global
`prefers-reduced-motion` guard in `index.css`.

**AI assistant (crown jewel):** morphing orb → glass panel; pinnable as a docked
right rail (content reflows via `lib/aiDock.ts` — never overlays data); spatial
memory per route (`nexus.ai.spatial.v1`); ⌘J toggles anywhere.

Discipline: glass over void always. Backdrop-blur on section containers only. Neon
glow on active states only. No warm tones anywhere. Sentence case; two weights max.
When extending, consult `ui-ux-pro-max`; never drift back toward warm/flat/violet.

---

Deep project history, locked decisions, and ops facts live in Claude's persistent
memory (the `MEMORY.md` index + its linked notes) — consult and update memory
rather than duplicating that context here.
