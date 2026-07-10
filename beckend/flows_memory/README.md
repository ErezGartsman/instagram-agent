# flows_memory — the Flows runtime's persistent file-based memory

Written and read by `nexus/flows/memory.py`. Three append-only JSONL ledgers
plus a regenerated human-readable digest:

| File | What accumulates here | Who consumes it |
|---|---|---|
| `failures.jsonl` | Persistent failure patterns: verifier rejections, Policy Gate blocks, transport failures, crashed runs | The **circuit-breaker verifier** (`nexus/flows/verifier.py`) — the engine reads its own failure history and stops repeating a losing pattern |
| `lessons.jsonl` | Durable operational lessons the runtime derives (e.g. a circuit opening) | Humans + future tooling |
| `efficiency.jsonl` | Per-sweep-cycle cost records (duration, dispatch/run counts) | Cadence + batch-limit tuning |
| `MEMORY_INDEX.md` | Regenerated digest — counts, top failure patterns, recent lessons | `cat` it to see what the engine has learned |

Rules (enforced in code):

- **Ref-only.** Person/flow ids and reason codes — never message bodies
  (verbatim text lives only in `outbound_messages`, same PII discipline as
  `interactions.payload`).
- **Concurrency-safe appends.** One complete JSON line per record via a
  single `os.write` on an `O_APPEND` descriptor — parallel writers interleave
  whole lines, never partial ones.
- **Best-effort, never load-bearing for correctness.** Every write is
  swallowed on failure; every read tolerates a missing directory. Empty
  memory only ever means *less* extra protection (the circuit breaker
  approves), never a wrong block.
- **Location.** `FLOWS_MEMORY_DIR` env var overrides this directory. On
  Vercel (read-only package FS) set it to `/tmp/flows_memory` — memory then
  persists per warm instance; the durable record of every outcome remains
  `flow_run_steps` in Postgres regardless.

Only this README is checked in; the ledgers are runtime state (gitignored).
