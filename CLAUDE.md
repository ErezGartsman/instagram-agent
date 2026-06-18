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

## 4. Cockpit design discipline — "Graphite Command" is the source of truth (Sprint 5 guardrail)
The Cockpit's visual system is **"Graphite Command"** — a high-contrast, dark "Mission
Control" aesthetic for analytics-heavy intelligence software, derived via the
`ui-ux-pro-max` skill (Dark-Mode OLED × Executive Dashboard). It permanently supersedes
the earlier buckssauce browns. Canonical tokens live in `fronted/src/cockpit/index.css`
(`@theme`); every component references the semantic Tailwind utilities only — `bg-bg`,
`bg-surface`, `bg-raised`, `text-ink`, `text-muted`, `border-line`, `text-accent`,
`text-success` / `text-warn` / `text-danger` — never raw hex.

Primitives: bg `#0b0f17` · surface `#131a24` · raised `#1f2a38` · ink `#e8edf4` ·
muted `#8b98a9` · line cream/10% · accent `#3d8bff` (electric blue — the one signature) ·
success `#34d399` · warn `#fbbf24` · danger `#f87171`. Radius 6 (controls) / 8 (cards).
Type: IBM Plex Sans for UI, **JetBrains Mono for all data/numerals** (KPIs, counts,
timestamps — `tabular-nums`). Discipline: flat — no shadows / gradients / blur; elevation
via surface + border shifts only; one signature element, everything else quiet; sentence
case; two weights. Apply real craft — never templated or default-looking UI. When
extending the system consult `ui-ux-pro-max`; adhere to this aesthetic, don't drift.

---

Deep project history, locked decisions, and ops facts live in Claude's persistent
memory (the `MEMORY.md` index + its linked notes) — consult and update memory
rather than duplicating that context here.
