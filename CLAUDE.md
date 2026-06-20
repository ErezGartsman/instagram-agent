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

## 3. Bot voice — context-aware, never robotic (Sprint 5 guardrail)
The WhatsApp funnel must NOT fire the psychological opener on a bare greeting
("hi", "היי"). Initiate the funnel only on clear intent (or after a delay); on a
bare greeting, stay silent or send an ultra-brief, human acknowledgment. The bot
is a person, not a tripwire.

## 4. Cockpit design discipline — "Graphite Atelier" is the absolute source of truth (Sprint 5 guardrail)
The Cockpit's visual system is **"Graphite Atelier"** — a "quiet sanctuary that hides a
precision instrument": the calm, low-lit warmth of a private study fused with the razor-sharp
organization of a command center. Derived via the `ui-ux-pro-max` skill and locked by Erez
on 2026-06-20, it **permanently supersedes "Graphite Command"** (the cool-slate / electric-blue
skin) and the earlier buckssauce browns. References: Linear (typography, keyboard-first),
Notion dark (editorial negative space), an Aman-resort lounge at night (warm ambient light,
nothing screaming). Canonical tokens live in `fronted/src/cockpit/index.css` (`@theme`); every
component references the semantic Tailwind utilities only — `bg-bg`, `bg-surface`, `bg-raised`,
`text-ink`, `text-muted`, `text-faint`, `border-line`, `text-accent`, `text-sage`,
`text-success` / `text-warn` / `text-danger`, `font-serif` — never raw hex.

Primitives (warm obsidian): bg `#100c0a` · surface `#1a1512` · raised `#241d17` · ink `#f2ebe0`
(parchment) · muted `#a99c8c` · faint `#6f6357` · line parchment/9% · accent `#c9aa71`
(**champagne bronze — the one signature**, appears once with weight per view) · sage `#8a9a82`
(quiet supporting tone, live/calm cues, never competes with bronze) · success `#7fa97f` ·
warn `#d8a657` · danger `#d08770` (warm — attention, never alarm). Radius 6 (controls) / 8 (cards).

**Three typographic voices** — the signature risk, made structural (Machine vs. Human):
**Inter** for all UI / queue / system data (the Machine); **JetBrains Mono** `tabular-nums` for
every numeral — KPIs, counts, %, timestamps (the Instrument); **Fraunces** (light, soft optical)
for the Memory layer only — the emotional summary / core human problem (the Human). The sans stays
quiet; the serif speaks.

**Motion** — the whisper budget (CSS only, never a heavy anim lib; honors `prefers-reduced-motion`
via the global guard): the "one-thing" focus mechanic — on select, unselected queue rows recede
to 40% opacity (~260ms) while the thread + memory rise (`cq-rise`); the Human/Fraunces layer
recalls a touch slower (`cq-rise-slow`, ~420ms); the confidence bar draws once (`cq-grow`), never
loops; hover is color/opacity only, never scale.

Discipline: flat — no shadows / gradients / blur; elevation via surface + border shifts only; one
signature element, everything else quiet; sentence case; two weights. Apply real craft — never
templated or default-looking UI. When extending the system consult `ui-ux-pro-max`; adhere to this
aesthetic, don't drift.

---

Deep project history, locked decisions, and ops facts live in Claude's persistent
memory (the `MEMORY.md` index + its linked notes) — consult and update memory
rather than duplicating that context here.
