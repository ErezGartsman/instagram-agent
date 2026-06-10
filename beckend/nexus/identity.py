"""
nexus.identity — the Person spine: identity resolution, phone linking, wa_ref.

Design rules (docs/NEXUS_V1_BUILD_PLAN.md §4):
  • Deterministic resolution ONLY — exact (channel, external_id) match or a
    normalized phone number. No probabilistic matching in V1.
  • NO auto-merge, ever. A phone that already belongs to a different person
    writes a merge_candidates row for manual cockpit review — wrong merges
    cross-contaminate intimate context, so a human resolves every one.
  • Persons are created on funnel entry (instagram/telegram at first DM; web
    lazily at phone capture — enforced by the callers in main.py, not here).
    NEVER from the content tables: 20k followers must not become 20k persons.

All core functions are commit-free and take an open psycopg2 connection —
the calling route handler owns the transaction boundary (same contract as
the _db_* helpers in main.py).
"""

import logging
import re
import secrets

logger = logging.getLogger("nexus.identity")

FUNNEL_CHANNELS = {"instagram", "telegram", "web"}
IDENTITY_CHANNELS = FUNNEL_CHANNELS | {"phone", "email", "whatsapp"}

# wa_ref alphabet drops 0/O/1/I — these codes get read aloud / retyped by a
# human off a WhatsApp message, so visual ambiguity is a real failure mode.
_WA_REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_WA_REF_LENGTH = 6


def generate_wa_ref() -> str:
    """
    Short per-person ref code embedded in the wa.me prefill text, so a WhatsApp
    arrival can be linked back to its Instagram person in the cockpit.
    31^6 ≈ 887M codes — collisions are negligible at this scale, and the UNIQUE
    constraint on person.wa_ref_code is the final guard.
    """
    return "".join(secrets.choice(_WA_REF_ALPHABET) for _ in range(_WA_REF_LENGTH))


def normalize_phone(raw: object, default_cc: str = "972") -> str | None:
    """
    Best-effort E.164 normalization with an Israeli default country code.

    Handles the forms that actually reach us: Telegram contact shares
    ("972501234567", "+972501234567"), typed local numbers ("050-123 4567"),
    and full international numbers with "+" or "00" prefixes. Returns None
    when the input can't be normalized with confidence — callers MUST treat
    None as "do not link", never guess. A bare 10-digit number without a
    leading 0 is deliberately rejected (could be a foreign local number;
    guessing a country code here would corrupt the identity join key).
    """
    if raw is None:
        return None
    s = re.sub(r"[^\d+]", "", str(raw))
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("00"):
        s = s[2:]
    if not s.isdigit():
        return None
    if s.startswith(default_cc) and 11 <= len(s) <= 13:
        return "+" + s
    if s.startswith("0") and 9 <= len(s) <= 10:
        return "+" + default_cc + s[1:]
    if 11 <= len(s) <= 15:
        return "+" + s
    return None


def resolve_or_create_person(
    conn,
    channel: str,
    external_id: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
) -> tuple[str, bool]:
    """
    Return (person_id, created) for a channel handle, creating person +
    identity on first contact. Race-safe under the person_identity
    (channel, external_id) unique index: if two webhook deliveries race the
    creation, the loser adopts the winner's person and deletes its orphan.

    On every resolve we bump person.last_seen_at and opportunistically fill
    display_name / identity.username when they arrive later (IG usernames are
    fetched lazily). Commit-free.
    """
    channel = (channel or "").strip().lower()
    external_id = str(external_id or "").strip()
    if channel not in IDENTITY_CHANNELS or not external_id:
        raise ValueError(f"invalid identity ({channel!r}, {external_id!r})")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id FROM person_identity "
            "WHERE channel = %s AND external_id = %s",
            (channel, external_id),
        )
        row = cur.fetchone()
        if row:
            person_id = str(row[0])
            cur.execute(
                "UPDATE person SET last_seen_at = NOW(), updated_at = NOW(), "
                "display_name = COALESCE(display_name, %s) WHERE id = %s",
                (display_name, person_id),
            )
            if username:
                cur.execute(
                    "UPDATE person_identity SET username = COALESCE(username, %s) "
                    "WHERE channel = %s AND external_id = %s",
                    (username, channel, external_id),
                )
            return person_id, False

        cur.execute(
            "INSERT INTO person (display_name, wa_ref_code) "
            "VALUES (%s, %s) RETURNING id",
            (display_name, generate_wa_ref()),
        )
        person_id = str(cur.fetchone()[0])
        cur.execute(
            "INSERT INTO person_identity (person_id, channel, external_id, username) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (channel, external_id) DO NOTHING RETURNING id",
            (person_id, channel, external_id, username),
        )
        if cur.fetchone() is None:
            # Lost a creation race: another request inserted this identity
            # between our SELECT and INSERT. Drop our orphan person and adopt
            # the winner's.
            cur.execute("DELETE FROM person WHERE id = %s", (person_id,))
            cur.execute(
                "SELECT person_id FROM person_identity "
                "WHERE channel = %s AND external_id = %s",
                (channel, external_id),
            )
            return str(cur.fetchone()[0]), False
        return person_id, True


def attach_phone_identity(conn, person_id: str, raw_phone: object) -> str:
    """
    Link a captured phone number to a person as a 'phone' identity — the
    deterministic cross-channel join key (Telegram capture ↔ Calendly invitee).

    Returns one of:
      'linked'   — new phone identity created for this person.
      'already'  — this person already owns this phone.
      'conflict' — phone belongs to ANOTHER person → merge_candidates row
                   written for manual cockpit review (never auto-merged).
      'invalid'  — number could not be normalized; nothing written.

    Commit-free.
    """
    e164 = normalize_phone(raw_phone)
    if not e164:
        return "invalid"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id FROM person_identity "
            "WHERE channel = 'phone' AND external_id = %s",
            (e164,),
        )
        row = cur.fetchone()
        if row:
            owner = str(row[0])
            if owner == str(person_id):
                return "already"
            cur.execute(
                "INSERT INTO merge_candidates (person_a, person_b, reason) "
                "VALUES (%s, %s, 'shared_phone') ON CONFLICT DO NOTHING",
                (person_id, owner),
            )
            logger.info(
                "[identity] shared phone → merge candidate (%s, %s)",
                person_id, owner,
            )
            return "conflict"
        cur.execute(
            "INSERT INTO person_identity (person_id, channel, external_id) "
            "VALUES (%s, 'phone', %s) ON CONFLICT (channel, external_id) DO NOTHING",
            (person_id, e164),
        )
        return "linked"
