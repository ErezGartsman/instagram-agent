"""
tests.test_cors_preflight — the CORS preflight contract.

The cockpit talks to the API cross-origin (separate Vercel subdomains in prod,
separate ports in local dev), so every non-simple request (PATCH, and any POST
with a JSON body) triggers a browser preflight. A method missing from
`allow_methods` makes Starlette answer the OPTIONS preflight with 400
"Disallowed CORS method" — the browser then never sends the real request, which
reads as a dead button, not a validation error.

Regression: PATCH (flow draft update → the Publish flow path, flow-settings,
content update) must be allowed. No DB, no network — CORSMiddleware only.
"""
from fastapi.testclient import TestClient

import main
from main import app


def _origin() -> str:
    # Use a configured origin so the preflight passes the origin check
    # regardless of the deployment's allow-list.
    return main.settings.allowed_origins.split(",")[0].strip()


def _preflight(method: str):
    return TestClient(app).options(
        "/api/cockpit/flows/01f7fc06-3a1d-4e7d-bee9-1ff64f8326d7",
        headers={
            "Origin": _origin(),
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )


def test_patch_preflight_is_allowed():
    r = _preflight("PATCH")
    assert r.status_code == 200, r.text  # 400 = "Disallowed CORS method" (the bug)
    assert "PATCH" in r.headers.get("access-control-allow-methods", "")


def test_post_preflight_still_allowed():
    # Control: proves the middleware isn't just answering 200 for everything.
    r = _preflight("POST")
    assert r.status_code == 200
    assert "POST" in r.headers.get("access-control-allow-methods", "")
