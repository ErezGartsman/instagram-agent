"""
nexus.db — connection bridge between the nexus package and main.py's pool.

nexus modules never import main (that would be circular: main.py imports
nexus to mount routers and call hinge hooks). Core functions take an open
psycopg2 connection and stay commit-free — the caller owns the transaction
boundary, exactly like the _db_* helpers in main.py. Best-effort wrappers
that need their own connection (e.g. interactions.track on hot webhook
paths) obtain one through this bridge after main.py calls
nexus.db.configure(get_db_conn) once at import time.
"""

_conn_provider = None


def configure(conn_provider) -> None:
    """Install the app's pooled-connection factory (main.py's get_db_conn)."""
    global _conn_provider
    _conn_provider = conn_provider


def get_conn():
    """Return the app's pooled-connection context manager."""
    if _conn_provider is None:
        raise RuntimeError(
            "nexus.db is not configured — main.py must call "
            "nexus.db.configure(get_db_conn) before nexus code runs."
        )
    return _conn_provider()
