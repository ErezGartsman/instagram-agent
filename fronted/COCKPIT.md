# NEXUS — Cockpit (Sprint 5)

The Cockpit is the internal command center for leads & conversations. This is the
**Ticket 5.0 foundation**: tooling, design tokens, app shell, and the Supabase
auth gate. The pillars (Pipeline, Inbox, Content, Overview) ship in 5.1–5.4.

## Routes
- `/` — Cockpit (new). Supabase magic-link auth gate → app shell.
  - `/` Overview · `/pipeline` · `/inbox` · `/content`
- `/legacy` — the previous **Nexus** analytics app, preserved and code-split.
  It keeps its own API-key auth and `instagram-agent-seven` backend.

## Stack
- React 19 + Vite 8; TypeScript for all new `.tsx` (legacy stays `.jsx`, no migration).
- Tailwind v4 via PostCSS, **without preflight** (so `/legacy` is untouched); tokens
  live in `src/cockpit/index.css` `@theme`. The reset is scoped to `.cockpit-root`.
- `@supabase/supabase-js` (Auth now, Realtime later) + React Router.

## Design tokens (semantic — never raw hex in components)
`bg #100b06` · `surface #322c23` · `raised #3d362b` · `ink #f5e4c7` ·
`muted #998d7a` · `line` cream/12% · `accent #be8d3f` (gold — the one signature) ·
`success #8a9a5b` · `danger #bf5a40` · radius 8/10 · Inter Tight (400/600).
Flat: no shadows / gradients / blur. Utilities: `bg-surface`, `text-muted`,
`border-line`, `text-accent`, `rounded-card`, `rounded-control`, …

## Environment
| Var | Local | Production |
|---|---|---|
| `VITE_SUPABASE_URL` | `.env.local` | Vercel env |
| `VITE_SUPABASE_ANON_KEY` | `.env.local` | Vercel env |

`.env.local` is gitignored. The anon key is the public, RLS-protected publishable key.

## Supabase setup (one-time, Erez)
1. **Auth → URL Configuration → Redirect URLs**: add `http://localhost:5173/`
   and the prod origin (e.g. `https://instagram-agent-euxl.vercel.app/`).
2. **Allow-list**: restrict sign-ups to approved emails (Auth settings), and/or
   enforce server-side (below). Magic link is email-OTP, no password.
3. **Vercel**: add the two `VITE_SUPABASE_*` vars to the cockpit project.

## Next — Ticket 5.0 backend (separate change)
`/api/cockpit/me` in `beckend/main.py`: a FastAPI dependency verifying the
Supabase JWT (HS256 via `SUPABASE_JWT_SECRET`) and checking the email allow-list.

## Commands
```bash
npm install
npm run dev        # http://localhost:5173  — Cockpit at /, Nexus at /legacy
npm run build
npm run typecheck
```
