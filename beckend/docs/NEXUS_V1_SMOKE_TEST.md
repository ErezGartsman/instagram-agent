# NEXUS V1 — Post-deploy production smoke test (~5 minutes)

Run this once `feature/nexus-v1-integration` is merged to main and Vercel has
deployed. Migrations v1_000–002 are already live, so the only thing being
verified is the wiring. All SQL runs in the Supabase SQL Editor (postgres
role). Expected duration: 2 min Telegram + 1 min Instagram + 2 min SQL.

## 0. Pre-flight (30 seconds)

- Vercel deployment is green; `/health` returns `{"status": "ok"}`.
- You are messaging from a PERSONAL test account (Telegram and Instagram),
  not the owner account — the funnel treats the owner like any user, but a
  clean test identity makes the SQL checks unambiguous.

## 1. Telegram funnel (~2 minutes)

1. Send the bot: `אפשר לקבוע פגישה?`
   → expect the qualification question (C4 fired: opportunity opened).
2. Reply with a topic line, e.g. `רוצה לדבר על זוגיות`
   → expect the contact-share keyboard (C2 fired: stage → qualified).
3. Tap **📱 שתפו את המספר שלי**
   → expect the thank-you message AND the owner alert in Erez's Telegram
   (Hook B fired: capture spine).

## 2. Instagram funnel (~1 minute)

1. From the test IG account, send a DM containing a configured trigger word
   (e.g. `ייעוץ`), or tap the Icebreaker on a fresh thread
   → expect the warm reply asking for your WhatsApp number (C1 fired).
2. Type a phone number, e.g. `050-1234567`
   → expect the thanks + optional topic question (Hook B fired).
3. Reply with one topic sentence
   → expect the warm close; Erez's alert is edited in place with the 🧠 brief
   (C5 fired: stage → briefed).

**Note on Hook D (wa.me button):** the prefill-link code path is wired and
fully fallback-protected, but the CURRENT live IG funnel collects the lead's
typed number — `send_contact_prompt` (the only place the button renders) is
reachable only via the offer-accept path, which the cold-entry flow doesn't
arm. There is deliberately nothing to tap today; the real-device prefill test
becomes relevant when an IG flow starts arming `offered_meeting`.

## 3. Database verification (~2 minutes)

Run each block; expected results inline.

```sql
-- A. The person spine: expect your TG person (with phone identity, E.164
-- +972…) and your IG person (igsid identity). lifecycle_stage = 'lead'.
-- Every person has a wa_ref_code.
SELECT p.id, p.display_name, p.lifecycle_stage, p.wa_ref_code,
       pi.channel, pi.external_id
FROM person p JOIN person_identity pi ON pi.person_id = p.id
ORDER BY p.created_at DESC LIMIT 10;
```

```sql
-- B. Opportunities: expect one OPEN opportunity per test person.
-- Telegram: stage 'captured'. Instagram: stage 'briefed' (context landed).
SELECT person_id, stage, source_channel, opened_at, stage_entered_at, closed_at
FROM opportunities ORDER BY created_at DESC LIMIT 5;
```

```sql
-- C. The signal log: expect (newest first, roughly) — context_provided,
-- stage_change ×N, captured, qualified, trigger_hit/icebreaker_hit.
-- has_person should be TRUE on all of them (Hook A stamped the sessions).
SELECT kind, channel, person_id IS NOT NULL AS has_person, occurred_at, payload
FROM interactions ORDER BY id DESC LIMIT 15;
```

```sql
-- D. Legacy tables got stamped, not modified: the new leads/sessions rows
-- carry person_id; phone in leads is still the RAW user-typed form.
SELECT id, channel, phone, person_id IS NOT NULL AS stamped
FROM leads ORDER BY created_at DESC LIMIT 3;
SELECT id, channel, person_id IS NOT NULL AS stamped
FROM sessions ORDER BY created_at DESC LIMIT 5;
```

```sql
-- E. Negative checks: no merge candidates from the smoke (unless you used
-- the same phone on both channels — then exactly ONE row here is CORRECT
-- behavior: shared phone → manual review, never auto-merge).
SELECT * FROM merge_candidates WHERE status = 'open';
```

## 4. Regression spot-checks (~30 seconds)

- Send the bot a plain emotional message on Telegram → normal triage reply
  (legacy path untouched).
- In the DataLens frontend, open the schema sidebar (`/api/schema`) → the
  nexus tables (person, interactions, …) must NOT appear (guard pulled
  forward from ticket 3.7).
- Vercel logs: no `[hooks] … failed` warnings during the smoke. One warning
  is a soft signal, not an incident — hooks are best-effort by contract —
  but investigate before proceeding to ticket 3.4.

## If something is wrong

Every hook is best-effort: a spine failure cannot break the bot. Rollback is
`git revert` of the integration commit — the migrations can stay (additive,
unused columns/tables are harmless). Do NOT drop tables to roll back.
