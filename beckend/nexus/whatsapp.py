"""
nexus.whatsapp — send bridge for the WhatsApp channel.

Follows the same configure-then-call pattern as nexus.db: main.py installs
the real send function once at module level (after _KAPSO_CHANNEL is ready);
nexus agents call send_text without knowing about the Kapso/Meta wiring.

This keeps nexus.agents.qualification free of any import from main.py
(which would be circular) while still letting agents dispatch real WA sends.
"""

import logging

logger = logging.getLogger("nexus.whatsapp")

_send_fn = None   # installed by main.py via configure()


def configure(send_fn) -> None:
    """
    Install the transport function.  Called once at module level in main.py
    immediately after _KAPSO_CHANNEL is created:

        nexus_whatsapp.configure(
            lambda recipient, text: _KAPSO_CHANNEL.send_text(recipient, text)
        )
    """
    global _send_fn
    _send_fn = send_fn


def send_text(recipient: str, text: str) -> str | None:
    """
    Send a WhatsApp message via the installed transport.

    Returns the raw response string from the underlying channel (used to
    extract the provider message_id), or None when the send fails.

    Raises RuntimeError when configure() has not been called yet.
    Callers (agents) must treat a None return as a non-fatal skip, not a crash.
    """
    if _send_fn is None:
        raise RuntimeError(
            "nexus.whatsapp is not configured — main.py must call "
            "nexus_whatsapp.configure() after _KAPSO_CHANNEL is ready."
        )
    try:
        return _send_fn(recipient, text)
    except Exception as exc:
        logger.warning("[whatsapp] send_text to %s failed: %s", recipient, exc)
        return None
