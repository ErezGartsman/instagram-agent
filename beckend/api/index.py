# Vercel serverless entry-point.
#
# Vercel's Python runtime discovers this file because it lives in the `api/`
# directory.  It looks for a top-level variable named `app` (ASGI) or
# `handler` (WSGI) — FastAPI is ASGI so `app` is the correct export.
#
# sys.path note:
#   Vercel adds the directory of THIS file (`beckend/api/`) to sys.path,
#   NOT the project root (`beckend/`).  Without the explicit insert below,
#   `from main import app` would raise ModuleNotFoundError because main.py
#   sits one directory above.  We resolve it by inserting the parent dir
#   (i.e. `beckend/`) at position 0 so it takes priority over everything else.

import os
import sys

# Insert beckend/ (parent of this file's directory) onto sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: F401  (Vercel reads the `app` name directly)
