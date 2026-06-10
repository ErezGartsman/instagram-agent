"""
nexus.hooks — the ONLY functions main.py calls (the strangler seam).

Contract (docs/NEXUS_V1_INTEGRATION_MAP.md):

  • A hook must NEVER raise into a webhook turn. Lead capture, the user's
    confirmation message, and the owner alert always win over the spine.

  • A hook that shares the caller's connection must never leave the caller's
    transaction ABORTED. A bare try/except is NOT enough for that: one failed
    SQL statement poisons the whole transaction ("current transaction is
    aborted, commands ignored…") and every later legacy statement on that
    connection would fail — the exact silent blast-radius failure this design
    forbids. Shared-connection hooks therefore run inside a SAVEPOINT and
    roll back to it on any failure — the same _ro_guard pattern main.py's
    execute_query() already uses.

  • Hooks that run post-ack (after the user's confirmation was sent) take
    their OWN pooled connection via nexus.db, commit themselves, and swallow
    everything.

  • Idempotence under webhook replays (Telegram edited_message, Meta
    redelivery, cold-start dedup loss) is guaranteed by the schema, not by
    hope: person_identity UNIQUE(channel, external_id), the one-open-
    opportunity partial unique index, the forward-only stage machine, and
    interaction dedup keys.
"""

import logging
import urllib.parse

from nexus import db, identity, interactions

logger = logging.getLogger("nexus.hooks")

# Hook D — WhatsApp prefill the lead sends TO Erez. Carries the per-person ref
# code so the WhatsApp arrival can be linked back to the Instagram person in
# the cockpit. Hebrew copy lives here like main.py's other copy constants;
# promote to app_config if it ever needs live editing.
_WA_PREFILL_TEMPLATE = "היי ארז, הגעתי מהאינסטגרם 🙂 (קוד: {ref})"
# Paranoid upper bound — far above any real encoded prefill (~400 chars), far
# below Meta's button-URL limits. Anything bigger means something went wrong.
_WA_URL_MAX = 1000


def on_channel_session(conn, session_id: str, channel: str,
                       contact_id: str) -> str | None:
    """
    Hook A — person spine at session resolution (Telegram + Instagram).

    Runs INSIDE the caller's transaction and is commit-free, like every _db_*
    helper in main.py — the writes ride the caller's commit. SAVEPOINT-guarded:
    any failure rolls back only the hook's own statements and leaves the
    caller's transaction fully usable. Never raises.

    Returns the person_id, or None when resolution failed — sessions.person_id
    then stays NULL and the next turn simply retries (self-healing).
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT nexus_hook")
    except Exception as e:
        # Could not even open a savepoint — the connection is already dead or
        # aborted for reasons unrelated to nexus. Stay out of the way.
        logger.warning("[hooks] session hook: savepoint open failed: %s", e)
        return None

    try:
        person_id, _created = identity.resolve_or_create_person(
            conn, channel, contact_id
        )
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET person_id = %s "
                "WHERE id = %s AND person_id IS NULL",
                (person_id, session_id),
            )
            cur.execute("RELEASE SAVEPOINT nexus_hook")
        return person_id
    except Exception as e:
        logger.warning("[hooks] session hook failed (channel=%s session=%s): %s",
                       channel, session_id, e)
        try:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT nexus_hook")
                cur.execute("RELEASE SAVEPOINT nexus_hook")
        except Exception as e2:
            logger.warning("[hooks] session hook rollback failed: %s", e2)
        return None


def on_lead_captured(lead_id: str, *, channel: str, chat_id: str,
                     phone: str) -> None:
    """
    Hook B — capture spine, called from the tail of _finalize_lead for every
    NEW lead (all four capture paths funnel through there).

    Own pooled connection + own commit; runs post-ack so the user's
    confirmation and the owner alert are already sent. NEVER raises.

    Writes: person resolve → phone identity (E.164, merge-candidate on
    conflict, never auto-merge) → stamp leads.person_id + sessions.person_id →
    open/advance opportunity to 'captured' → log the captured interaction.
    The interaction payload carries NO PII — the phone number itself lives
    only in leads.phone (raw, legacy-owned) and person_identity (E.164).
    """
    try:
        with db.get_conn() as conn:
            person_id, _created = identity.resolve_or_create_person(
                conn, channel, chat_id
            )
            phone_link = identity.attach_phone_identity(conn, person_id, phone)

            session_id = None
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE leads SET person_id = %s "
                    "WHERE id = %s AND person_id IS NULL",
                    (person_id, lead_id),
                )
                cur.execute(
                    "SELECT session_id FROM leads WHERE id = %s", (lead_id,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    session_id = str(row[0])
                    cur.execute(
                        "UPDATE sessions SET person_id = %s "
                        "WHERE id = %s AND person_id IS NULL",
                        (person_id, session_id),
                    )

            opp_id = interactions.get_or_open_opportunity(conn, person_id, channel)
            interactions.advance_stage(conn, opp_id, "captured", by="bot")
            interactions.log_interaction(
                conn, "captured", channel,
                person_id=person_id, session_id=session_id,
                payload={"lead_id": str(lead_id), "phone_link": phone_link},
                dedup_key=f"captured:{lead_id}",
            )
            conn.commit()

        if phone_link == "conflict":
            logger.info("[hooks] capture %s: shared phone → merge candidate "
                        "queued for cockpit review", lead_id)
        elif phone_link == "invalid":
            logger.info("[hooks] capture %s: phone not normalizable — lead "
                        "kept, no phone identity linked", lead_id)
    except Exception as e:
        logger.warning("[hooks] capture hook failed for lead %s: %s", lead_id, e)


def on_funnel_event(kind: str, channel: str, *, session_id: str,
                    stage: str | None = None,
                    payload: dict | None = None,
                    dedup_key: str | None = None) -> None:
    """
    Hooks C1–C5 — one-liner funnel signal + stage move at the hinge points.

    Own pooled connection + own commit; NEVER raises. The person comes from
    the session's Hook-A stamp: when the session is unstamped (Hook A failed
    earlier), the interaction is still counted (person_id NULL — parity with
    bot_events) but no opportunity is touched.

    stage semantics: 'engaged' just ensures an open opportunity exists (the
    opening stage); later stages also advance the forward-only machine, so
    replays and out-of-order webhook deliveries are harmless no-ops.
    """
    try:
        with db.get_conn() as conn:
            person_id = None
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT person_id FROM sessions WHERE id = %s", (session_id,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    person_id = str(row[0])
            if person_id:
                opp_id = interactions.get_or_open_opportunity(
                    conn, person_id, channel
                )
                if stage and stage != "engaged":
                    interactions.advance_stage(conn, opp_id, stage, by="bot")
            interactions.log_interaction(
                conn, kind, channel, person_id=person_id,
                session_id=session_id, payload=payload, dedup_key=dedup_key,
            )
            conn.commit()
    except Exception as e:
        logger.warning("[hooks] funnel event %r failed (session=%s): %s",
                       kind, session_id, e)


def whatsapp_cta_url(base_number: str, channel: str, external_id: str) -> str:
    """
    Hook D — build the WhatsApp CTA URL with the person's wa_ref prefill.

    HARD GUARANTEE: never raises and ALWAYS returns a usable wa.me URL.
    Any failure — bridge unconfigured, DB down, person/ref missing, encoding
    error, malformed or oversized result — falls back to the plain link the
    bot has shipped since Sprint 2. The conversion CTA can only ever be
    upgraded by this function, never broken.

    Deliberately READ-ONLY: a person without a wa_ref_code (e.g. pre-backfill)
    gets the plain link rather than a write on the conversion-critical path;
    the booking still links later via the Calendly phone match.
    """
    plain = f"https://wa.me/{base_number}"
    try:
        ref = None
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT p.wa_ref_code FROM person p "
                    "JOIN person_identity pi ON pi.person_id = p.id "
                    "WHERE pi.channel = %s AND pi.external_id = %s LIMIT 1",
                    (channel, str(external_id)),
                )
                row = cur.fetchone()
        if row and row[0]:
            ref = str(row[0]).strip()
        if not ref:
            return plain

        prefill = _WA_PREFILL_TEMPLATE.format(ref=ref)
        encoded = urllib.parse.quote(prefill, safe="")
        url = f"{plain}?text={encoded}"

        # Belt-and-braces validation — if ANY check fails, ship the plain link.
        if (not url.startswith(plain + "?text=")
                or len(url) > _WA_URL_MAX
                or not url.isascii()):
            logger.warning("[hooks] wa CTA failed validation — plain link used")
            return plain
        return url
    except Exception as e:
        logger.warning("[hooks] wa CTA prefill failed (%s) — plain link used", e)
        return plain
