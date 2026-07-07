# FABLE NOTES — Cockpit reimagining ("Midnight Instrument")

Working log for the frontend reimagining. Presentation-only; backend frozen.

## Locked decisions (Erez, 2026-07-05)
1. **Color soul: deep navy + electric blue** (attached Vision UI refs govern).
   Violet demoted to ambient depth tint. Warm-gold drift in index.css reverted.
2. **AI assistant: morphing orb → panel**, pinnable as docked right rail,
   spatial memory per route (open/pinned in localStorage).
3. **Motion: signature boot, quiet after.** One GSAP entrance (~1.1s, skippable,
   once per session, reduced-motion-safe). Afterwards sub-300ms micro-motion only.

## Frozen contracts (do not touch)
- `QueueItem`, `TimelineEvent`, `postQueueAction`, `fetchQueue`, `rankQueue`
- AI chat: `POST /api/cockpit/ai/chat` body/response, intent enum
  (`sla_lead*`, `sla_overview`, `funnel`, `velocity`, `post`, `top_posts`,
  `community`), `context_data` shapes, WA draft/phone/outreach endpoints
- `nexus:ai-context` + `nexus:sla-changed` window events
- Auth flow (AuthProvider / session.access_token / devBypass)
- `streamDraft` signature; analytics fetchers

## Token map (index.css @theme)
- bg `#04070f` · surface `rgba(148,186,255,0.055)` · raised `rgba(148,186,255,0.09)`
- ink `#f2f6ff` · muted `#9aa7bd` · faint `#55617a` · line `rgba(148,186,255,0.08)`
- accent `#3b82f6` (electric blue) · glow `#60a5fa` · sage → `#2dd4bf` (teal counter)
- success `#34d399` · warn `#d9a94e` · danger `#e0705c`
- Void gradients: blue crown top / abyss pool bottom-right / violet whisper bottom-left
- Fraunces rule preserved: greeting + lead essence only.

## Work plan (vertical slices)
- [x] Blind-spot pass + interview (3 questions)
- [x] 1. Tokens: index.css rewrite + warm-hex sweep (Sidebar, Topbar, StatCard,
      CursorGlow, AgentPip, AnalyticsPage, OverviewPage, LoginScreen, SurfaceStates).
      Grep confirms zero warm hexes remain in src/.
- [x] 2. Boot sequence (components/BootSequence.tsx, GSAP) + AppShell shell-rise
      entrance + dock spacer (lib/aiDock.ts store)
- [x] 3. GlowingAiAssistant: breathing ✦ orb, pin dock (content reflows),
      thought-shimmer thinking, cq-crystallize widget assembly, spatial memory
      per route, ⌘J toggle. All fetch/intent/event contracts untouched.
- [x] 4. Work Queue: FLIP re-rank (layout prop + glow flash on risers);
      Analytics Leads tab: breach filament pulse + "Your move" live pip
- [x] 5. Analytics recolored (ELECTRIC/TEAL); Overview NextMove electrified
- [x] 6. tsc --noEmit GREEN. Preview-verified (dev bypass, then restored to off):
      login + boot + overview + queue + analytics screenshots clean, zero console
      errors; chat send→thinking→reply works; pin dock reflows; spatial memory
      restores per route; done→undo round-trip intact (5→4→5 rows).

## Verified 2026-07-05/06 (preview session)
- Boot: plays once (sessionStorage `nexus.boot.v1`), skippable, no errors.
- Assistant: orb toggles; spatial map persists `{"/app/queue":{open,pinned}}`;
  dock mounts full-height and Overview keeps the free orb.
- Action loop: Mark done removes card, undo toast restores — backend untouched.
- CLAUDE.md §4 rewritten to Midnight Instrument; memory note saved.

## Landing page — "the manifesto made physical" (2026-07-06)
Handcuffs off per Erez: full amphora-style spectacle on the PUBLIC surface only.
- Old brown obsidian landing (HeroGeometric, #100c0a) retired; Suspense fallback
  recolored to #04070f. Same soul as the cockpit → seamless Enter → login seam.
- `components/ui/cinematic-landing-hero.tsx` — pinned GSAP theatre (~6500px
  scrub): thesis ignites → deep-navy physical card swallows viewport → 3D phone
  ("the instrument": confidence ring counts to 88, Your move/Theirs rows,
  glass badges) with rAF mouse parallax → pullback reveals Scene 2. Adapted
  from a 21st.dev component; store CTAs removed (private instrument), re-souled
  to Midnight tokens. Reduced motion → single static viewport, no pin.
- `landing/NexusParticles.tsx` — Three.js (new dep, landing-only, lazy route):
  ~6k-point field, rigid electric lattice (machine) flowing into teal organic
  wave (human), uMix scrubbed by ScrollTrigger. DPR ≤1.75, IO-paused rAF,
  full dispose, reduced-motion = one static frame.
- `landing/LandingPage.tsx` — Scenes 3–9 from the narrative brief: dividing
  line (WebGL + legibility vignette), intelligence chat vignette, Person-360
  facets, live queue re-rank vignette, draft-guarantee card, who-it's-for,
  Fraunces manifesto close + quiet "Enter the command center →". Glowing SVG
  thread draws down the manifesto on scroll. Ban-list honored (no hype verbs,
  no growth theater, single quiet CTA).
- index.html: Inter 700/800/900 + Fraunces italics added (were missing —
  headline weights would have faux-bolded).
- Verified in preview (desktop 1512 + mobile 375): all scenes screenshot-clean,
  zero console errors incl. WebGL, re-rank plays, Enter → /app login seam.
  tsc --noEmit GREEN.

## UX maturation pass (2026-07-06, Erez feedback round)
1. **Identity = "The Plumb"** (`components/ui/nexus-logo.tsx`): thin plumb line
   through a staggered N, ending in a brass weight — line/N in currentColor,
   the gold ball is the ONE sanctioned warm note ("the human hand"). Rolled out:
   landing nav, Sidebar, BootSequence (glow tween moved to drop-shadow filter),
   LoginScreen, favicon (`public/nexus-icon.svg`, dark chip). Hexagon burned.
2. **Sticky glass nav** on landing: h-16, blur, anchors (Philosophy /
   Intelligence / Memory / Queue via scrollIntoView + scroll-mt-16), CTAs
   "Sign in" + "Sign up for free" → /app.
3. **Auth de-glowed**: solid #070b16 card, hairline borders, 1px focus ring,
   flat solid Sign-in button, plumb mark above — Linear/Vercel register.
   cq-field no longer used by login (CSS kept for Topbar-family reuse).
4. **Scroll physics**: hero pin 6500→3600 (+holds 2.5/1.5→1.1/0.6, scrub 0.8);
   scenes py-36→py-24, min-h tightened. Total page 13.5k→10k px.
   **Truncation audit**: automated scan (scrollWidth/Height overflow) = 0 clipped
   elements at 1512 AND 375; bg-clip-text descender guard (pb 0.08–0.1em) added
   to all gradient texts; card texts moved to clamp() sizing.
5. **Thread continuous**: path extended (viewBox 5000), scrub end = bottom
   bottom, gradient ends in brass #c9a24a; CloseScene opens with a plumb
   terminal (line → gold weight) so the thread literally lands at the door.
All verified in preview: anchor jump lands +64px under nav, dashOffset 0 at
page bottom, zero console errors, tsc GREEN.

### Round-2 fixes (same day, Erez screenshots)
- Nav white boxes ROOT CAUSE: `.landing-midnight` reset lacked a `button`
  reset → native UA chrome leaked. Reset added (background:none, border:0,
  padding:0). Anchors verified computed: transparent bg, 0 border/padding.
- Nav glass: solid rgba(4,7,15,0.6)+blur-xl → bg-[#04070f]/45 + backdrop-blur-md
  (verified computed: blur(12px), 45% alpha).
- NEXUS "S" clipped on ~1900px screens: clamp cap 6.4rem overflowed its grid
  column (h2 overflowed PARENT — the earlier self-overflow audit couldn't see
  it; lesson: audit child-vs-parent rects too). Fix: clamp(2.8rem,5vw,5rem) +
  min-w-0 on the column. Measured at 1920: 211px clearance inside the card.
- Note: preview screenshot tool wedged mid-session (page stayed healthy —
  eval fine); a preview restart reset the capture pipeline.

## Cockpit "Command" overhaul (2026-07-06, Erez's IA directive)
Blind-spot pass first (3 findings): (1) three uncoordinated pollers → a unified
dashboard would contradict itself; (2) accountability buried 2 clicks deep in
Analytics while the landing sells "whose move it is"; (3) no time axis
(booked-session times not in any current API — needs backend, logged below).
Ratified by Erez: accountability list = prime object, ultra-dense KPI bento
around it.
- **Command screen** (`pages/OverviewPage.tsx` rewrite): ONE data cycle
  (Promise.allSettled: pipeline+queue mandatory, SLA/analytics degrade
  gracefully) feeding every widget; 30s poll + focus + `nexus:sla-changed`.
  Layout: greeting + SLA summary chips → left: "Your move" panel (breach
  filaments, clocks, target micro-bars, click → queue?focus) + Next-move card
  (Fraunces essence line); right bento: 4 KPI tiles (Booked = electric
  signature), Community tile w/ inline-SVG sparkline (NO recharts on the index
  route) + weekly delta, Pipeline funnel bars.
- **Nav restructure** (`shell/nav.ts`): Command / Work: Work queue + People
  (ex-Pipeline) / Intelligence: Analytics. Content demoted to FOOTER_NAV
  (kept — anonymized content engine is a locked pillar). Inbox stays flagged off.
- **Sidebar badge** (`lib/navSignals.ts` store): Command's cycle publishes
  { yourMove, breach }; queue nav item shows count + red breach pip.
- **Orb fixed**: button IS the orb now (was a nested span that could squash);
  cq-breathe reduced to opacity-only (transform warped the halo shadow into an
  ellipse at some zooms). Verified: 56×56, perfect circle.
- Verified (dev bypass toggled + restored): nav = Command/Work queue·3/People/
  Analytics + Content footer; breach clock "1d 2h" in danger red; 4
  accountability rows; zero console errors; tsc GREEN.

## Hotfix round (2026-07-06 late)
1. **Command crash** (`.breach` of undefined): fetchSla casts without validating;
   prod returned SLA without `summary`. Fixed: payload sanitized at runCycle
   (leads array required, summary defaulted) + `?.`/`?? 0` at every read.
2. **AI panel de-noised**: footer (⌘J/Shift+Enter/NLP-engine strip) and char
   counter removed. Added inert NLP-bridge widgets — `content_stats`,
   `growth_trend`, `themes` — renderers activate when the Python planner ships
   those intents (contracts documented on each component).
3. **Queue memory LTR**: essence + Goal/Tension facts pinned dir=ltr text-left
   (Hebrew legacy formations can't flip the panel). English-only formations =
   backend prompt change (logged in report). Nav "People" → "Pipeline".
4. **Content empty states** recast as "Automated insights & themes" (extraction
   engine framing; manual editor untouched underneath).
tsc GREEN. Preview not re-run this round (guards deterministic; sample data
cannot reproduce the missing-summary payload).

## Proactive layer — Morning Briefing + Person Dossier (2026-07-07)
Frontend-only pair (backend not ready); both mocks are DEV-gated (`import.meta.env.DEV`)
so, like SAMPLE_QUEUE, no mock intelligence ever ships — in prod the briefing simply
doesn't render and the dossier route shows its "no dossier formed yet" state.
- **Morning briefing** (`components/MorningBriefing.tsx`): the one Command surface
  that speaks FIRST. "3 things changed overnight" — Maya reopened after 3 weeks of
  silence (→ /app/person/p1), Daniel's sentiment dropped (→ queue?focus=q2), 2 SLA
  breaches before noon (→ queue). Tone dots (glow/warn/danger, one neon shadow on
  the signal dot only), compiled-at stamp, "Read" ack collapses it for the day
  (localStorage `nexus.briefing.ack.v1` keyed by date). Sits above the Command grid.
  Intended contract documented in-file: `GET /api/cockpit/briefing`.
- **Person dossier** (`pages/PersonDossierPage.tsx`, route `/app/person/:id`):
  the "held, not filed" deep-memory view. Identity header (stage chip, held-since,
  Fraunces essence line — CLAUDE.md §4 updated: dossier essence = same sanctioned
  object as the queue essence). Left: relationship-trajectory sentiment line
  (inline SVG, neutral baseline, chapter markers, glowing "now" dot) + "The story
  so far" chapter thread (AI-summarized eras: reached out about trust → named the
  real fear → went quiet → reopened; signal chips per chapter). Right: Person-360
  facts + "Held, not filed — 42 items" footnote + scoped AI chat (seed exchange
  with citation chip, cq-thought-line thinking shimmer, cq-crystallize on replies,
  canned preview reply; the live planner takes the seam unchanged via
  `GET /api/cockpit/person/:id/dossier` + scoped chat intent).
- Mock story kept coherent with SAMPLE_QUEUE's Maya (p1: essence/goal/tension
  verbatim; silence arc explains the briefing headline).

## Phase 3 — The Brain & Integration (2026-07-08)
Backend + wiring for the proactive layer; the Phase 2 mocks are GONE.
1. **Planner expansion** (`nexus/ai_planner.py`): 3 new registry tools powering
   the Phase 2 NLP-bridge widgets — `content_stats` (post/like/comment totals +
   per-post averages; averages OMITTED not null at 0 posts), `growth_trend`
   (weekly CUMULATIVE tracked-follows series + last-week delta %, weeks arg
   2-24), `themes` (person_profile goals/tensions/core_concerns ∪ session
   topics, `sensitive = FALSE` guard, count-ranked). Intents added to
   FROZEN_INTENTS (renderers shipped 2026-07-06); `_AI_ACTIONS` entries added.
2. **English system memory** (`nexus/memory.py` FORMATION_PROMPT): profile_summary
   (essence), attributes.goal and the NEW attributes.tension are English-only
   regardless of input language; session_summary/topic/emotional_state/facts
   stay Hebrew (they feed the Hebrew recall block + copilot drafts). Existing
   Hebrew formations remain until the cron re-forms a profile — the queue's
   LTR pins (2026-07-06 hotfix) still cover legacy rows.
3. **Proactive endpoints** (`main.py` + new pure module `nexus/dossier.py`):
   - `GET /api/cockpit/briefing` — deterministic 24h diff, zero LLM tokens:
     reopens after ≥7d silence (person-activity kinds only, not formation_run/
     alert_sent bookkeeping), new leads, SLA warn/breach roster. Item shape =
     the MorningBriefing contract; empty items = quiet night.
   - `GET /api/cockpit/person/{id}/dossier` — one payload: Person-360 header
     (essence/goal/tension, stage, held-since, memory_count), weekly chapters
     from session_summaries with synthetic "Went quiet" chapters (≥14d gaps),
     urgency→[-1,+1] trajectory (calm positive — the only longitudinal affect
     signal the spine records), raw signal timeline (30).
4. **Frontend live** (`lib/dossier.ts` new): MorningBriefing fetches the
   briefing (silent on load/failure/quiet night); PersonDossierPage fetches
   the dossier (loading/error/empty states, dir=auto for Hebrew memory);
   scoped chat = the LIVE planner seam (`/api/cockpit/ai/chat` + `Person: X`
   chip). All DEV mocks deleted.
Verified: ruff + pytest green (25 test_main fails pre-exist on clean HEAD —
env/legacy; copilot stream fail = local COPILOT_DEMO_MOCK=1); tsc GREEN;
END-TO-END against the real DB via minted HS256 token on a spare port
(briefing = 1 new lead + 20 breaches live; dossier = full payload incl.
Hebrew legacy memory; unknown person → clean empty state); preview verified
graceful degradation (401 → briefing silent, dossier error+retry, zero
console errors). NOTE: the local dev backend on 8012 runs pre-Phase-3 code —
restart it to pick up the new endpoints.

## Known follow-ups (not blocking)
- framer-motion dev warning: `motion() is deprecated → motion.create()` (pre-existing,
  from `motion(Link)` in StatCard/OverviewPage; harmless, fix opportunistically).
- Real-backend pass: widget crystallization + streaming draft with live data.
- Virtualize queue list only if it ever exceeds ~60 rows (currently 5–30).

## Perf/a11y guardrails
- backdrop-blur on section containers only, never list rows
- one neon box-shadow per active element
- tabular-nums on all numerals; keyboard shortcuts preserved (queue keys, ⌘K)
- prefers-reduced-motion kills boot, orb breathing, shimmer
