"""
routers.flows — the Flows engine API surface (E0 skeleton).

Phase F1 (SYSTEM_ELEVATION_PRD.md §B) fills this in: flow definitions CRUD,
run history, simulation reports. Until then the cockpit can probe the feature
flag and always receives an honest, stable shape — never a 404 the frontend
has to special-case.

The engine itself will live in nexus/flows/ (dispatcher, runner, predicates,
policy gate); this module stays a thin HTTP layer over it, per the E0 rule
that new features never land inside main.py.
"""
from fastapi import APIRouter, Depends

import main

router = APIRouter()


@router.get("/api/cockpit/flows")
def list_flows(user: dict = Depends(main.require_cockpit_user)):
    """Flow definitions list. F1 replaces the static shape with real rows —
    the response contract (enabled + flows[]) is already final."""
    return {
        "status": "success",
        "enabled": False,   # global kill switch — app_config 'flows.enabled' in F1
        "flows": [],
    }
