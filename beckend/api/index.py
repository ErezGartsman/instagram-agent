# Vercel serverless entry-point.
#
# Vercel's Python runtime discovers this file because it lives in the `api/`
# directory.  It looks for a top-level variable named `app` (ASGI) or
# `handler` (WSGI).  Importing `app` from `main` is all that's needed —
# Vercel handles the rest.
#
# Why this works:
#   • Vercel root directory is set to `beckend/` in the project settings.
#   • That means `beckend/` is on sys.path, so `from main import app` resolves.
#   • All routes in main.py (/health, /db-test, /api/*) are served through
#     the single wildcard route in vercel.json → this file.

from main import app  # noqa: F401  (Vercel reads the `app` name directly)
