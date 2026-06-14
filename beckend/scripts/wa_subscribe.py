#!/usr/bin/env python3
"""
WhatsApp Business Cloud API — webhook subscription helper.

Subscribes THIS app to your WhatsApp Business Account (WABA) so Meta delivers
inbound `messages` webhooks to the app's callback URL. Ticking the `messages`
field in the Meta dashboard declares WHICH fields the app wants; this
`subscribed_apps` edge is what links a specific WABA's events to the app. Without
it the GET verification passes but NO message events are ever delivered — the
exact symptom we hit during Ticket 4.1 bring-up.

This is the WhatsApp analog of scripts/ig_subscribe.py (which does the same for
Instagram via graph.instagram.com). WhatsApp Cloud API lives on
graph.facebook.com.

What it does:
  1. GET  /<WABA_ID>/subscribed_apps  → BEFORE state
  2. POST /<WABA_ID>/subscribed_apps  → subscribe THIS app
  3. GET  /<WABA_ID>/subscribed_apps  → AFTER state (confirm success)

Inputs (token, then WABA id):
  token:    arg 1  | env WHATSAPP_ACCESS_TOKEN | beckend/.env
  waba id:  arg 2  | env WHATSAPP_WABA_ID       | default below
  (The token needs the whatsapp_business_management scope.)

Stdlib only — no pip install. Run from anywhere:
    python beckend/scripts/wa_subscribe.py "<TOKEN>"
    python beckend/scripts/wa_subscribe.py "<TOKEN>" "<WABA_ID>"
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.facebook.com/v21.0"
TIMEOUT = 15

# Single-tenant project (build-plan A1): the live WABA id, taken from the inbound
# webhook payload's entry.id. Override with arg 2 or WHATSAPP_WABA_ID.
DEFAULT_WABA_ID = "976227335188804"


def _load_token() -> str:
    # 1) CLI arg
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    # 2) environment
    tok = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    if tok:
        return tok
    # 3) beckend/.env (script lives in beckend/scripts/, so parent.parent is beckend/)
    for candidate in (
        Path(__file__).resolve().parent.parent / ".env",   # beckend/.env
        Path.cwd() / ".env",
        Path.cwd() / "beckend" / ".env",
    ):
        if candidate.is_file():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("WHATSAPP_ACCESS_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("ERROR: no token found. Pass it as the first argument, set "
          "WHATSAPP_ACCESS_TOKEN, or add WHATSAPP_ACCESS_TOKEN=... to beckend/.env")
    sys.exit(1)


def _load_waba_id() -> str:
    if len(sys.argv) > 2 and sys.argv[2].strip():
        return sys.argv[2].strip()
    return os.environ.get("WHATSAPP_WABA_ID", "").strip() or DEFAULT_WABA_ID


def _call(method: str, path: str, token: str) -> dict:
    """Make a Graph API call. Returns parsed JSON; prints + raises on HTTP error."""
    params = {"access_token": token}
    if method == "POST":
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(f"{GRAPH}{path}", data=data, method="POST")
    else:
        req = urllib.request.Request(
            f"{GRAPH}{path}?{urllib.parse.urlencode(params)}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"  HTTP {e.code} on {method} {path}:\n  {body}")
        raise
    except Exception as e:
        print(f"  Network error on {method} {path}: {e}")
        raise


def main() -> None:
    token = _load_token()
    waba_id = _load_waba_id()
    base = f"/{waba_id}/subscribed_apps"

    print("=" * 70)
    print("WhatsApp Cloud API webhook subscription helper (graph.facebook.com)")
    print(f"WABA: {waba_id}")
    print("=" * 70)

    # 1) BEFORE state
    print("\n[1/3] Current subscriptions (BEFORE) …")
    try:
        before = _call("GET", base, token)
    except Exception:
        print("      Could not read subscriptions. The token is likely invalid, "
              "expired, or missing the whatsapp_business_management scope.")
        sys.exit(1)
    print(f"      → {json.dumps(before.get('data', before), ensure_ascii=False)}")

    # 2) Subscribe THIS app to the WABA
    print("\n[2/3] Subscribing THIS app to the WABA …")
    result = _call("POST", base, token)
    ok = result.get("success") is True
    print(f"      → {json.dumps(result, ensure_ascii=False)}  {'✅' if ok else '⚠️'}")

    # 3) AFTER state
    print("\n[3/3] Current subscriptions (AFTER) …")
    after = _call("GET", base, token)
    print(f"      → {json.dumps(after.get('data', after), ensure_ascii=False)}")

    print("\n" + "=" * 70)
    if ok and after.get("data"):
        print("DONE ✅  The WABA is now subscribed to the app. Send 'היי בוט' from "
              "your allow-listed number, then ask Claude to re-read the probe row "
              "(app_config → whatsapp._debug_last_inbound).")
    else:
        print("Subscription did not confirm. Check the error above — the most "
              "common causes are a token without whatsapp_business_management, or "
              "the wrong WABA id (pass it as arg 2 or set WHATSAPP_WABA_ID).")
    print("=" * 70)


if __name__ == "__main__":
    main()
