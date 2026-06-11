"""
nexus.bookings — Calendly booking webhook → the North Star (booked consultation).

Principle (docs/NEXUS_V1_BUILD_PLAN.md): observability ≠ attribution.
  • EVERY booking is recorded — the metric never depends on a successful match.
  • Matching a booking to a person is best-effort enrichment.
  • An opportunity advances to 'booked' ONLY on a confident match.

Match ladder (first hit wins): token (utm_content → wa_ref_code) → phone (the
V1 workhorse; the event requires it) → email → none (recorded, person_id NULL,
queued for the cockpit's unlinked-bookings inbox). Cancellations are handled at
the METRIC layer (count status='scheduled'); the forward-only opportunity stage
is never reverted.

Security: the endpoint verifies Calendly's signed webhook before any of this
runs. Idempotent under Calendly's redeliveries via bookings.external_id (the
invitee uri) + dedup-keyed interactions + the forward-only stage machine.
Never raises into the webhook turn.
"""

import hashlib
import hmac
import logging
import time

from nexus import db, identity, interactions

logger = logging.getLogger("nexus.bookings")

_SIGNATURE_TOLERANCE_SECONDS = 180   # ±3 min replay window


def verify_signature(raw_body: bytes, header: str | None, signing_key: str,
                     *, tolerance: int = _SIGNATURE_TOLERANCE_SECONDS) -> bool:
    """
    Verify Calendly's `Calendly-Webhook-Signature: t=<ts>,v1=<hmac>` header.
    v1 = HMAC-SHA256(signing_key, "<ts>.<raw_body>"). Hashes the RAW bytes (a
    re-serialised JSON copy would differ and fail). Constant-time compare +
    timestamp tolerance for replay protection. Fail-closed on anything missing.
    """
    if not (header and signing_key):
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, v1 = parts.get("t"), parts.get("v1")
    if not (ts and v1):
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
    except ValueError:
        return False
    signed = ts.encode("utf-8") + b"." + (raw_body or b"")
    expected = hmac.new(signing_key.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


# Question keywords that mark a phone-number answer (Calendly puts a required
# phone either in text_reminder_number or in questions_and_answers).
_PHONE_Q_HINTS = ("phone", "mobile", "whatsapp", "טלפון", "נייד", "וואטס", "ווצאפ")


def parse_invitee_payload(body: dict) -> dict:
    """Pull the fields we map onto the ontology from an invitee.* webhook body."""
    p = body.get("payload") or {}
    phone = (p.get("text_reminder_number") or "").strip() or None
    if not phone:
        for qa in (p.get("questions_and_answers") or []):
            question = (qa.get("question") or "").lower()
            answer = (qa.get("answer") or "").strip()
            if answer and any(h in question for h in _PHONE_Q_HINTS):
                phone = answer
                break
    tracking = p.get("tracking") or {}
    scheduled = p.get("scheduled_event") or {}
    return {
        "uri":       p.get("uri"),
        "email":     ((p.get("email") or "").strip().lower() or None),
        "name":      (p.get("name") or None),
        "phone":     phone,
        "token":     ((tracking.get("utm_content") or "").strip() or None),
        "starts_at": scheduled.get("start_time"),
    }


def match_person(conn, *, token, phone, email) -> tuple[str | None, str]:
    """
    Deterministic match ladder. Returns (person_id, matched_via) where
    matched_via ∈ token | phone | email | none. Commit-free.
    """
    with conn.cursor() as cur:
        if token:
            cur.execute("SELECT id FROM person WHERE wa_ref_code = %s", (token,))
            row = cur.fetchone()
            if row:
                return str(row[0]), "token"
        if phone:
            e164 = identity.normalize_phone(phone)
            if e164:
                cur.execute(
                    "SELECT person_id FROM person_identity "
                    "WHERE channel = 'phone' AND external_id = %s", (e164,))
                row = cur.fetchone()
                if row:
                    return str(row[0]), "phone"
        if email:
            cur.execute(
                "SELECT person_id FROM person_identity "
                "WHERE channel = 'email' AND external_id = %s", (email,))
            row = cur.fetchone()
            if row:
                return str(row[0]), "email"
    return None, "none"


def _handle_created(conn, parsed: dict) -> str:
    """Record the booking, match it, advance a matched opportunity. Commit-free."""
    external_id = parsed["uri"]
    if not external_id:
        return "ignored"

    person_id, matched_via = match_person(
        conn, token=parsed["token"], phone=parsed["phone"], email=parsed["email"])

    opp_id = None
    if person_id:
        # 'booked' is forward-reachable from any open stage; idempotent on retry.
        opp_id = interactions.get_or_open_opportunity(conn, person_id, "calendly")
        interactions.advance_stage(conn, opp_id, "booked", by="calendly")

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bookings "
            "(person_id, opportunity_id, source, external_id, starts_at, status, "
            " invitee_name, invitee_phone, invitee_email, matched_via) "
            "VALUES (%s, %s, 'calendly', %s, %s, 'scheduled', %s, %s, %s, %s) "
            "ON CONFLICT (external_id) WHERE external_id IS NOT NULL DO NOTHING",
            (person_id, opp_id, external_id, parsed["starts_at"], parsed["name"],
             parsed["phone"], parsed["email"], matched_via))

    interactions.log_interaction(
        conn, "booking_created", "calendly", person_id=person_id,
        payload={"external_id": external_id, "matched_via": matched_via},
        dedup_key=f"booking_created:{external_id}")
    logger.info("[calendly] booking %s matched_via=%s person=%s",
                external_id, matched_via, person_id)
    return matched_via


def _handle_canceled(conn, parsed: dict) -> str:
    """Mark the booking canceled. The opportunity stage is NEVER reverted."""
    external_id = parsed["uri"]
    if not external_id:
        return "ignored"
    person_id, matched_via = match_person(
        conn, token=parsed["token"], phone=parsed["phone"], email=parsed["email"])
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bookings SET status = 'canceled', updated_at = NOW() "
            "WHERE external_id = %s", (external_id,))
        if cur.rowcount == 0:
            # Cancel arrived before (or without) the create — record it anyway.
            cur.execute(
                "INSERT INTO bookings "
                "(person_id, source, external_id, starts_at, status, "
                " invitee_name, invitee_phone, invitee_email, matched_via) "
                "VALUES (%s, 'calendly', %s, %s, 'canceled', %s, %s, %s, %s) "
                "ON CONFLICT (external_id) WHERE external_id IS NOT NULL DO NOTHING",
                (person_id, external_id, parsed["starts_at"], parsed["name"],
                 parsed["phone"], parsed["email"], matched_via))
    interactions.log_interaction(
        conn, "booking_canceled", "calendly", person_id=person_id,
        payload={"external_id": external_id},
        dedup_key=f"booking_canceled:{external_id}")
    return "canceled"


def process_event(body: dict) -> None:
    """
    Entry point from the webhook endpoint (runs in a worker thread). Own
    pooled connection + commit; NEVER raises. Only invitee.created /
    invitee.canceled are acted on; everything else is ignored.
    """
    try:
        event_type = body.get("event")
        if event_type not in ("invitee.created", "invitee.canceled"):
            return
        parsed = parse_invitee_payload(body)
        with db.get_conn() as conn:
            if event_type == "invitee.created":
                _handle_created(conn, parsed)
            else:
                _handle_canceled(conn, parsed)
            conn.commit()
    except Exception as e:
        logger.error("[calendly] process_event failed: %s", e)
