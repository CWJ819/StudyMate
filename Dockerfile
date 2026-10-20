# ---------------------------------------------------------------------------
# 智学伴 StudyMate — single-container image (API + built SPA)
#
# Build from the repository root (ModelScope expects Dockerfile at repo root):
#   docker build -t studymate:local .
#   docker run --rm -p 7860:7860 \
#     -v studymate-data:/mnt/workspace/studymate \
#     -e LLM_BASE_URL=mock://local studymate:local
#
# Layout in the runtime image:
#   /app/app              FastAPI backend (from app/)
#   /app/alembic*         migrations + config (health check reads alembic.ini
#                         relative to the working directory)
#   /app/frontend/dist    Vite build output
#   /app/serve.py         mounts the SPA after the API routes (see deploy/)
#
# Platform constraints (ModelScope Studio, architecture v2.2 §12.3):
#   - listen on 0.0.0.0:7860 (8080 is reserved by the platform)
#   - no --reload, single uvicorn worker (in-process job worker + SQLite)
#   - /mnt/workspace is the only persistent path; secrets come from env
# ---------------------------------------------------------------------------

ARG NODE_IMAGE=node:24.13.0-bookworm-slim
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---- Stage 1: build the Vite SPA ------------------------------------------
FROM ${NODE_IMAGE} AS frontend-build

WORKDIR /build/frontend

# Install from the lockfile first so dependency layers cache across source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Pinned runtime dependency set (see deploy/constraints.txt). Versions were
# resolved in the verified 2026-10-20 local environment and are intentionally
# newer than docs/spec/environment.md; rebuild and smoke-test after any bump.
COPY deploy/constraints.txt /tmp/constraints.txt

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir -c /tmp/constraints.txt . \
    && rm -f /tmp/constraints.txt

# alembic.ini + migrations must live in WORKDIR: /api/health resolves the
# Alembic head from the relative path "alembic.ini".
COPY alembic.ini ./
COPY alembic ./alembic

# Built SPA and the thin ASGI wrapper that serves it on the same port.
COPY --from=frontend-build /build/frontend/dist ./frontend/dist
COPY deploy/serve.py ./serve.py

ENV APP_ENV=production \
    DATA_DIR=/mnt/workspace/studymate \
    DATABASE_URL=sqlite:////mnt/workspace/studymate/studymate.db \
    STORAGE_ROOT=/mnt/workspace/studymate/uploads \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=7860

RUN mkdir -p /mnt/workspace/studymate/uploads

EXPOSE 7860

# Apply migrations on every start (idempotent), then serve API + SPA. The
# platform does not inject PORT today; it is only a local debugging override.
CMD ["sh", "-c", "mkdir -p \"$DATA_DIR\" \"$STORAGE_ROOT\" && alembic upgrade head && exec uvicorn serve:app --host 0.0.0.0 --port \"${PORT:-7860}\""]
