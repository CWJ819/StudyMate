"""Single-port ASGI entrypoint used by the container image.

The backend (``app/``) intentionally does not mount the built SPA yet; the
frontend plan tracks that as a backend follow-up. To keep the image
single-process and single-port without editing the backend application code,
this wrapper mounts ``frontend/dist`` *after* the API routes. FastAPI/Starlette
matches routes in registration order, so ``/api/*``, ``/docs`` and
``/openapi.json`` keep their existing handlers and everything else is served
from the static build.

HashRouter is used by the SPA, so no history fallback is required.
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.staticfiles import StaticFiles

from app.main import app

frontend_dist = Path(os.environ.get("FRONTEND_DIST", "/app/frontend/dist"))
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
