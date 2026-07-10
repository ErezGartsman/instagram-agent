"""
nexus.flows.memory — the persistent, file-based memory system for the Flows
runtime.

Three append-only JSONL ledgers in a dedicated directory (FLOWS_MEMORY_DIR
env var, default beckend/flows_memory/):

  failures.jsonl    — persistent failure patterns: verifier rejections,
                      policy blocks, transport failures, run crashes. This is
                      the ledger the circuit-breaker verifier CONSULTS — the
                      engine reads its own failure history and stops
                      repeating a mistake (see nexus/flows/verifier.py).
  lessons.jsonl     — durable operational lessons the runtime derives (e.g.
                      "circuit opened for flow X + person Y after N rejects").
  efficiency.jsonl  — runtime-cost records per sweep cycle (durations, rows
                      scanned, runs claimed/executed) — the optimization
                      ledger for tuning sweep cadence and batch limits.

Plus MEMORY_INDEX.md — a human-readable digest (counts, top failure
patterns, recent lessons) regenerated after writes, so `cat MEMORY_INDEX.md`
answers "what has the engine learned" without parsing JSONL.

CONCURRENCY (the "parallel subagents" contract): writers append one complete
JSON line per record — an in-process lock serializes threads (the actual
runtime shape: FastAPI background tasks, sweep workers), and O_APPEND keeps
separate POSIX processes atomic. See _write_lock's comment for the Windows
multi-process caveat this module's own tests surfaced. The index rebuild is
derived data; racing rebuilds are benign (last writer wins, next write
regenerates).

PII DISCIPLINE: entries are ref-only — person/flow ids, reason codes, counts,
hashes. NEVER message bodies (same rule as interactions.payload; verbatim
text lives only in outbound_messages).

DURABILITY HONESTY: on Vercel the filesystem is ephemeral and read-only
outside /tmp — set FLOWS_MEMORY_DIR=/tmp/flows_memory there and memory
persists per warm instance only; every write here also has a durable DB
counterpart (flow_run_steps / outbound_messages), so nothing load-bearing is
lost when an instance recycles — the circuit breaker simply starts
conservative (empty memory = fail-open = no false blocks). On a long-running
deployment (local, VPS, container) the directory is fully persistent. Every
public function is best-effort and NEVER raises: a memory failure must never
break a send, a sweep, or a webhook turn.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from collections import Counter
from pathlib import Path

logger = logging.getLogger("nexus.flows.memory")

# In-process append serialization. O_APPEND alone is atomic across POSIX
# processes but NOT across Windows threads/processes (the CRT implements
# append as seek-then-write, so concurrent appends can silently overwrite
# each other — a bug this module's own test suite caught on the dev machine).
# The realistic parallel topology here is threads within one process (FastAPI
# background tasks, sweep workers), which this lock fully covers; separate
# POSIX processes are covered by O_APPEND. Multi-process Windows writers are
# the one uncovered corner — dev-only, single-process in practice.
_write_lock = threading.Lock()

_ENV_DIR = "FLOWS_MEMORY_DIR"
_CATEGORIES = ("failures", "lessons", "efficiency")
# Reads cap: recall scans at most this many bytes from the tail of a ledger,
# so a years-old file can never make a verifier slow.
_MAX_READ_BYTES = 512 * 1024


def _dir() -> Path:
    """Resolve the memory directory fresh on every call — tests and Vercel
    point FLOWS_MEMORY_DIR elsewhere without a process restart."""
    env = os.environ.get(_ENV_DIR)
    if env:
        return Path(env)
    # nexus/flows/memory.py -> nexus/flows -> nexus -> beckend
    return Path(__file__).resolve().parents[2] / "flows_memory"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── Writing ───────────────────────────────────────────────────────────────────

def _append(category: str, entry: dict) -> bool:
    """Append one record as a single atomic line. Returns False (never
    raises) when the directory is unwritable — e.g. Vercel's read-only
    package FS when FLOWS_MEMORY_DIR isn't set."""
    if category not in _CATEGORIES:
        logger.warning("[flows.memory] unknown category %r dropped", category)
        return False
    try:
        base = _dir()
        base.mkdir(parents=True, exist_ok=True)
        record = {"at": _now_iso(), "pid": os.getpid(), **entry}
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _write_lock:
            fd = os.open(str(base / f"{category}.jsonl"),
                         os.O_APPEND | os.O_CREAT | os.O_WRONLY)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
        return True
    except Exception as e:
        logger.warning("[flows.memory] append to %s failed: %s", category, e)
        return False


def record_failure(
    kind: str,
    *,
    flow_slug: str | None = None,
    person_id: str | None = None,
    verifier: str | None = None,
    reason: str | None = None,
    detail: str = "",
) -> None:
    """One failure-pattern record. kind ∈ send_rejected | send_deferred |
    policy_blocked | send_failed | run_crashed | verifier_error (validated
    loosely — new kinds are data, not schema)."""
    if _append("failures", {
        "kind": kind, "flow_slug": flow_slug, "person_id": person_id,
        "verifier": verifier, "reason": reason, "detail": detail[:300],
    }):
        _rebuild_index_quietly()


def record_lesson(text: str, *, tags: list[str] | None = None) -> None:
    """A durable operational lesson, stated in plain language (ref-only —
    ids and reason codes, never message content)."""
    if _append("lessons", {"lesson": text[:500], "tags": tags or []}):
        _rebuild_index_quietly()


def record_efficiency(operation: str, *, duration_ms: float, counts: dict | None = None) -> None:
    """A runtime-cost record for one operation (sweep cycle, dispatch phase)."""
    _append("efficiency", {
        "operation": operation,
        "duration_ms": round(float(duration_ms), 1),
        "counts": counts or {},
    })


# ── Reading ───────────────────────────────────────────────────────────────────

def _read_recent(category: str) -> list[dict]:
    """Parse the tail of a ledger (bounded by _MAX_READ_BYTES). Missing
    file/dir → []. A torn or corrupt line is skipped, never fatal."""
    try:
        path = _dir() / f"{category}.jsonl"
        if not path.exists():
            return []
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > _MAX_READ_BYTES:
                f.seek(size - _MAX_READ_BYTES)
                f.readline()   # discard the (possibly torn) partial first line
            raw = f.read().decode("utf-8", errors="replace")
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except Exception as e:
        logger.warning("[flows.memory] read of %s failed: %s", category, e)
        return []


def recent_failures(
    *,
    flow_slug: str | None = None,
    person_id: str | None = None,
    within_days: float = 7,
    exclude_reasons: tuple[str, ...] = (),
) -> list[dict]:
    """Failure records matching the filters, newest last."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=within_days)
    out = []
    for e in _read_recent("failures"):
        try:
            at = datetime.datetime.fromisoformat(e.get("at", ""))
        except ValueError:
            continue
        if at < cutoff:
            continue
        if flow_slug is not None and e.get("flow_slug") != flow_slug:
            continue
        if person_id is not None and e.get("person_id") != person_id:
            continue
        if e.get("reason") in exclude_reasons:
            continue
        out.append(e)
    return out


def failure_count(
    *,
    flow_slug: str | None = None,
    person_id: str | None = None,
    within_days: float = 7,
    exclude_reasons: tuple[str, ...] = (),
) -> int:
    return len(recent_failures(flow_slug=flow_slug, person_id=person_id,
                              within_days=within_days, exclude_reasons=exclude_reasons))


# ── The index — a human-readable digest of what the engine has learned ─────────

def rebuild_index() -> None:
    """Regenerate MEMORY_INDEX.md from the ledgers. Derived data; safe to
    lose, safe to race. Never raises."""
    try:
        failures = _read_recent("failures")
        lessons = _read_recent("lessons")
        efficiency = _read_recent("efficiency")

        patterns = Counter(
            f"{e.get('kind', '?')} · {e.get('verifier') or e.get('reason') or '?'}"
            for e in failures
        )
        lines = [
            "# Flows runtime memory — index",
            "",
            f"_Regenerated {_now_iso()} · derived from the JSONL ledgers; do not edit._",
            "",
            f"**{len(failures)}** failure records · **{len(lessons)}** lessons · "
            f"**{len(efficiency)}** efficiency records (within the read window)",
            "",
            "## Top failure patterns",
        ]
        if patterns:
            lines += [f"- `{p}` × {n}" for p, n in patterns.most_common(10)]
        else:
            lines.append("- none recorded yet")
        lines += ["", "## Recent lessons"]
        if lessons:
            lines += [f"- {e.get('lesson', '')}" for e in lessons[-10:]]
        else:
            lines.append("- none recorded yet")
        if efficiency:
            recent = efficiency[-20:]
            avg = sum(e.get("duration_ms", 0) for e in recent) / len(recent)
            lines += ["", "## Efficiency",
                      f"- last {len(recent)} operations: avg {avg:.0f} ms"]
        base = _dir()
        base.mkdir(parents=True, exist_ok=True)
        (base / "MEMORY_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.warning("[flows.memory] index rebuild failed: %s", e)


def _rebuild_index_quietly() -> None:
    rebuild_index()
