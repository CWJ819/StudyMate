# StudyMate

StudyMate is a local-first, single-user study workspace: course material parsing, knowledge-framework management, quiz generation and grading, mastery tracking, review-target selection, and study planning. The FastAPI backend lives in `app/`; the React SPA lives in `frontend/`.

## Status (2026-10-20)

The backend implements `Stage 8`: project skeleton, configuration, logging, error handling, Alembic wiring, database-backed settings overrides, course CRUD, material upload/parsing for PDF and PPTX files, a persistent SQLite-backed job system, knowledge framework generation/query APIs, quiz generation/grading APIs with snapshotting and idempotent submission, mastery tracking, gap evidence, review target selection, study plan generation, end-to-end coverage, and Stage 8 documentation/hardening checks.

The SPA covers courses, materials, knowledge frameworks, quizzes, review/mastery, study plans, and settings. It uses React 19, Vite 8, TypeScript 5.9, Tailwind CSS 4, TanStack Query 5, and a HashRouter.

The repository root also contains a two-stage `Dockerfile` that builds the SPA with Node 24 and runs the API + SPA on one port with Python 3.13.

Verification baseline for this revision: 47 backend `pytest` tests and 58 frontend `vitest` tests pass; `npm run build` succeeds.

This is still a trusted-local-use service: there is no authentication and no workspace isolation. Do not expose it directly to the public internet.

## Requirements

- Python `3.12+` (tested with `3.13`)
- Node.js `24+` and npm (frontend)
- SQLite is embedded; no external database, queue, or cache is required

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

## Run

Default startup binds to `127.0.0.1` only. Apply migrations first:

```bash
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use a real OpenAI-compatible model:

```bash
export LLM_BASE_URL=https://your-endpoint.example/v1
export LLM_MODEL=your-model
export LLM_API_KEY=...
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run without an API key using the built-in mock adapter:

```bash
LLM_BASE_URL=mock://local uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The mock adapter returns English template questions. It is suitable for exercising the full flow, not for product demos that need realistic course content.

## Frontend

```bash
cd frontend
npm install
npm run dev         # http://localhost:5173; /api is proxied to 127.0.0.1:8000
npm run test        # vitest + msw
npm run typecheck
npm run build       # tsc --noEmit + vite build, output in frontend/dist
npm run gen:types   # regenerate src/api/schema.d.ts from openapi/openapi.json
```

See [frontend/README.md](frontend/README.md) for the SPA structure, visual baseline, and integration notes.

## Container image

The repository root contains the multi-stage `Dockerfile` and `.dockerignore`; `deploy/` holds the single-port ASGI entrypoint and the pinned runtime constraints.

```bash
docker build -t studymate:local .
docker run --rm -p 7860:7860 \
  -v studymate-data:/mnt/workspace/studymate \
  -e LLM_BASE_URL=mock://local \
  studymate:local
```

Open <http://127.0.0.1:7860>; the health endpoint is `GET /api/health`. The entrypoint creates `/mnt/workspace/studymate`, runs `alembic upgrade head`, and starts one uvicorn worker on `0.0.0.0:7860`. The image keeps SQLite and uploads under `/mnt/workspace/studymate`, so mount a volume to keep data across containers.

The backend does not mount static files itself. `deploy/serve.py` mounts `frontend/dist` after the API routes, so `/api/*`, `/docs`, and `/openapi.json` keep their handlers and the SPA is served from the same origin.

For ModelScope Studio, use this repository root as the repository/Docker build root; the image already targets `0.0.0.0:7860` and reads secrets from the environment.

Validated on 2026-10-20: the image is about 283 MB; `/api/health`, the SPA, and static assets work on 7860; the full mock flow (upload with an empty page → knowledge framework → quiz → idempotent submit → mastery/wrongbook → review targets → plan → task completion) passes, and data survives a container restart via the mounted volume.

## Repository layout

- `app/`: FastAPI application (`api/routes` → `schemas` → `services` → `repositories` → `db/models`)
- `alembic/`: database migrations
- `tests/`: pytest suite (`unit/`, `integration/`, `e2e/`; fixtures in `tests/fixtures/`)
- `frontend/`: React SPA (Vite + TypeScript + Tailwind CSS 4)
- `deploy/`: container entrypoint (`serve.py`) and pinned runtime constraints
- `Dockerfile`, `.dockerignore`: single-container API + SPA build
- `scripts/smoke/`: manual smoke scripts that require a running backend
- `scripts/fixtures/`: fixture generators (generate `tests/fixtures/f1-sample.pdf`)
- `docs/spec/`: backend specification and environment baseline
- `docs/testing/`: acceptance and test reports
- `docs/demo/`: demo script
- `docs/reviews/`: backend design reviews and improvement proposals
- `data/`: local runtime data (SQLite, uploads; gitignored)

## Configuration

Use `.env.example` as the baseline local configuration:

```bash
cp .env.example .env
```

Key settings:

- `DATABASE_URL`: SQLite database path, default `sqlite:///./data/studymate.db`
- `STORAGE_ROOT`: local upload directory, default `./data/uploads`
- `LLM_BASE_URL` and `LLM_MODEL`: required for real LLM-backed knowledge/quiz features, or set `LLM_BASE_URL=mock://local` for offline testing
- `LLM_API_KEY`: optional fallback secret. The settings page can also save a key locally in `local_secrets.json` next to the SQLite database; neither value is returned by `GET /api/settings` or written to logs
- `MAX_UPLOAD_BYTES`, `MAX_DOCUMENT_PAGES`, `JOB_MAX_ATTEMPTS`: local safety and capacity limits

`PUT /api/settings` stores LLM runtime overrides (`llm_base_url`, `llm_model`, timeout, retries) that apply to the next LLM call without a restart. Upload limits, page limits, and job retry counts still come from the process environment. An API key saved from the settings page takes precedence over `LLM_API_KEY`; it lives in `local_secrets.json` next to the database (mode 0600 on POSIX), never in the settings table, and `PUT /api/settings` with `{"llm_api_key": ""}` clears it.

## Migrations

Alembic includes the `Stage 1` schema for `courses` and `settings`, the `Stage 2` material parsing tables, the `Stage 3` jobs table, the `Stage 4` knowledge framework tables, the `Stage 5` quiz/question tables, the `Stage 6` mastery and gap tracking tables, and the `Stage 7` study plan tables. Later revisions add section labels and knowledge content.

```bash
alembic upgrade head
```

If the database is not at the latest revision, `GET /api/health` returns `503 DATABASE_SCHEMA_OUTDATED`.

## Test

```bash
pytest -q
```

Manual smoke scripts live in `scripts/smoke/` and require a running backend. The smoke fixture is `tests/fixtures/f1-sample.pdf`; regenerate it with `python scripts/fixtures/make_sample_pdf.py`.

Frontend:

```bash
cd frontend
npm run test
npm run build
```

Stage 8 verification includes:

- `tests/e2e/test_stage8_flow.py`
- `tests/integration/test_stage8_security.py`
- security masking and health checks in `tests/integration/test_health.py` and `tests/integration/test_settings.py`
- the frontend Vitest suite (58 tests) and production build

## Implemented APIs

- `GET /api/health`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/courses`
- `GET /api/courses`
- `GET /api/courses/{course_id}`
- `PATCH /api/courses/{course_id}`
- `DELETE /api/courses/{course_id}`
- `GET /api/jobs/{job_id}`
- `POST /api/courses/{course_id}/materials`
- `GET /api/courses/{course_id}/materials`
- `GET /api/materials/{material_id}`
- `DELETE /api/materials/{material_id}`
- `GET /api/courses/{course_id}/search`
- `GET /api/chunks/{chunk_id}`
- `POST /api/courses/{course_id}/knowledge/build`
- `GET /api/courses/{course_id}/knowledge`
- `GET /api/knowledge/{knowledge_point_id}`
- `GET /api/courses/{course_id}/knowledge/versions`
- `POST /api/courses/{course_id}/quiz/generate`
- `GET /api/quizzes/{quiz_id}`
- `POST /api/quizzes/{quiz_id}/submit`
- `GET /api/courses/{course_id}/mastery`
- `GET /api/courses/{course_id}/wrongbook`
- `POST /api/courses/{course_id}/review-targets`
- `POST /api/courses/{course_id}/plan`
- `GET /api/courses/{course_id}/plans`
- `GET /api/plans/{plan_id}`
- `PATCH /api/tasks/{task_id}`

The OpenAPI document is served at `/openapi.json` (root path, not under `/api`); `/docs` provides the interactive UI.

## Notes for API clients

- Application errors use `{"error": {"code", "message", "details", "request_id"}}` and carry an `x-request-id` header. Route-level 404/405 responses may instead use FastAPI's `{"detail": "..."}` shape.
- Upload, knowledge-build, and quiz-generation requests return a `job_id`; poll `GET /api/jobs/{job_id}` until `succeeded`, `failed`, or `cancelled`. `progress` is only 0 or 100.
- `GET /api/courses/{course_id}/knowledge` returns `404 RESOURCE_NOT_FOUND` when no active framework exists. That is an empty state, not a server failure.
- A quiz can be submitted only once, with an answer for every question. Reuse the same idempotency key and payload to retry transport failures; a fresh key returns `409 QUIZ_NOT_OPEN`.
- Short-answer grading calls the LLM synchronously during submission. A temporary LLM failure returns `503` without saving the attempt, so the same idempotency key can be retried.
- `GET /api/settings` returns the real local `database_url` and `storage_root`; clients should not display them.

## Current Limitations

- Upload and parsing currently support `.pdf` and `.pptx`. Legacy `.ppt` is not implemented yet; OCR is not supported.
- Material uploads enqueue persistent `document.parse` jobs and return a `job_id` for polling.
- The job worker is single-process and SQLite-backed. It supports retry and stale-running recovery, but it is not a multi-instance queue.
- Knowledge framework generation currently uses either a configured OpenAI-compatible API or the built-in mock adapter for offline testing.
- Knowledge framework generation blocks material deletion when the material is referenced by framework sources.
- Quiz generation deduplicates by normalized stem hash within a course and snapshots full question content into each quiz.
- `GET /api/quizzes/{quiz_id}` hides answer keys, rubrics, explanations, and internal metadata until after submission.
- Objective grading is deterministic on the backend. Multiple-choice questions only receive full credit on exact set match.
- Short-answer grading is synchronous and requires an available LLM adapter at submission time. Pending/retry background grading is not implemented yet.
- Mastery tracking uses a transparent Beta-Binomial update over primary knowledge mappings only; wrong answers are not propagated to secondary or related nodes. The estimate is a provisional engineering value, not a precise measurement.
- Review target selection uses a simple weakness/exploration heuristic and records strategy logs; it is not MCTS.
- Study plan generation is deterministic and capacity-limited by `daily_minutes`; it preserves old plan versions and does not overwrite historical task state.
- The API has no variant-question endpoint, dashboard aggregate, LLM connectivity test, quiz list, job list, or demo/seed endpoint. The frontend substitutes a review-target → new-quiz loop for variants.
- There is no authentication and no workspace/session isolation. All courses and materials are visible to every caller; the service is intended only for trusted local use.
- The backend does not mount `frontend/dist`. The repository's container entrypoint (`deploy/serve.py`) serves the SPA after the API routes; adding static hosting to `app/main.py` remains a deployment follow-up.

## Stage 8 Checklist

- End-to-end flow is covered from material upload through knowledge build, quiz generation/submission, mastery update, review-target selection, and plan generation.
- Application errors use a consistent envelope with `error.code`, `error.message`, `error.details`, and `request_id`; route-level 404/405 responses may use FastAPI's default `detail` shape.
- Settings and error responses do not expose `LLM_API_KEY`; `GET /api/settings` only reports `llm_auth_configured` and `llm_api_key_source`.
- Upload filenames reject path traversal inputs and startup documentation binds to `127.0.0.1`.
- README, `.env.example`, and migrations are present; the Stage 8 tests run successfully in the current environment.
- The frontend test suite and production build are part of the current verification baseline.

## Environment Tracking

See [docs/spec/environment.md](docs/spec/environment.md) for the development baseline. The repository's container image uses Python 3.13 and Node 24, with runtime dependencies pinned in `deploy/constraints.txt`.
