"""
routers — the E0 strangler extraction of main.py's route surface.

Each module exposes a FastAPI APIRouter that main.py mounts at the bottom of
the module (after every shared helper is defined). Modules late-import main
and reference helpers as main.<name> — see SYSTEM_ELEVATION_PRD.md, Phase E0.
"""
