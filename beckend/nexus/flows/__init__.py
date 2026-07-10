"""
nexus.flows — the Flows automation engine (Phase F1, SYSTEM_ELEVATION_PRD.md §B).

Three thin layers on the existing spine, not a fourth automation system:
  predicates  — the safe condition DSL (never arbitrary code)
  signals     — the shared live-state snapshot condition nodes evaluate against
  policy      — the Policy Gate every automated outbound message passes through
  dispatcher  — event/state triggers -> flow_runs (the reconciliation "outbox" read)
  runner      — flow_runs -> executed nodes -> flow_run_steps (the executor)
"""
