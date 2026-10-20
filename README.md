# StudyMate Backend

StudyMate is a local-only single-user backend for course material parsing, knowledge framework management, quiz generation, grading, mastery tracking, and study planning.

This repository currently implements `Stage 8`: project skeleton, configuration, logging, error handling, Alembic wiring, database-backed settings overrides, course CRUD, material upload/parsing for PDF and PPTX files, a persistent SQLite-backed job system, knowledge framework generation/query APIs, quiz generation/grading APIs with snapshotting and idempotent submission, mastery tracking, gap evidence, review target selection, study plan generation, end-to-end coverage, and Stage 8 documentation/hardening checks.

## Requirements

- Python `3.12+`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

## Run

Default startup binds to `127.0.0.1` only.

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Repository layout

- `app/`: FastAPI application（`api/routes` → `schemas` → `services` → `repositories` → `db/models`）
- `alembic/`: database migrations
- `tests/`: pytest suite（`unit/`、`integration/`、`e2e/`；fixtures 在 `tests/fixtures/`）
- `scripts/smoke/`: manual smoke scripts that require a running backend
- `scripts/fixtures/`: fixture generators（生成 `tests/fixtures/f1-sample.pdf`）
- `docs/spec/`: backend specification and environment baseline
- `docs/testing/`: acceptance and test reports
- `docs/demo/`: demo script
- `data/`: local runtime data（SQLite、uploads；gitignored）
- `frontend/`: React SPA

## Configuration

Use `.env.example` as the baseline local configuration:

```bash
cp .env.example .env
```

Key settings:

- `DATABASE_URL`: SQLite database path, default `sqlite:///./data/studymate.db`
- `STORAGE_ROOT`: local upload directory, default `./data/uploads`
- `LLM_BASE_URL` and `LLM_MODEL`: required for real LLM-backed knowledge/quiz features, or set `LLM_BASE_URL=mock://local` for offline testing
- `LLM_API_KEY`: environment-only secret; it is never returned by `GET /api/settings`
- `MAX_UPLOAD_BYTES`, `MAX_DOCUMENT_PAGES`, `JOB_MAX_ATTEMPTS`: local safety and capacity limits

## Migrations

Alembic includes the `Stage 1` schema for `courses` and `settings`, the `Stage 2` material parsing tables, the `Stage 3` jobs table, the `Stage 4` knowledge framework tables, the `Stage 5` quiz/question tables, the `Stage 6` mastery and gap tracking tables, and the `Stage 7` study plan tables.

```bash
alembic upgrade head
```

## Test

```bash
pytest
```

Manual smoke scripts live in `scripts/smoke/` and require a running backend. The smoke fixture is `tests/fixtures/f1-sample.pdf`; regenerate it with `python scripts/fixtures/make_sample_pdf.py`.

Stage 8 verification includes:

- `tests/e2e/test_stage8_flow.py`
- `tests/integration/test_stage8_security.py`
- security masking and health checks in `tests/integration/test_health.py` and `tests/integration/test_settings.py`

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

## Current Limitations

- Upload and parsing currently support `.pdf` and `.pptx`. Legacy `.ppt` is not implemented yet.
- Material uploads enqueue persistent `document.parse` jobs and return a `job_id` for polling.
- The job worker is single-process and SQLite-backed. It supports retry and stale-running recovery, but it is not a multi-instance queue.
- Knowledge framework generation currently uses either a configured OpenAI-compatible API or the built-in mock adapter for offline testing.
- Knowledge framework generation blocks material deletion when the material is referenced by framework sources.
- Quiz generation deduplicates by normalized stem hash within a course and snapshots full question content into each quiz.
- `GET /api/quizzes/{quiz_id}` hides answer keys, rubrics, explanations, and internal metadata until after submission.
- Objective grading is deterministic on the backend. Multiple-choice questions only receive full credit on exact set match.
- Short-answer grading is synchronous and requires an available LLM adapter at submission time. Pending/retry background grading is not implemented yet.
- Mastery tracking uses a transparent Beta-Binomial update over primary knowledge mappings only; wrong answers are not propagated to secondary or related nodes.
- Review target selection uses a simple weakness/exploration heuristic and records strategy logs; it is not MCTS.
- Study plan generation is deterministic and capacity-limited by `daily_minutes`; it preserves old plan versions and does not overwrite historical task state.
- No authentication. The service is intended only for trusted local use.

## Stage 8 Checklist

- End-to-end flow is covered from material upload through knowledge build, quiz generation/submission, mastery update, review-target selection, and plan generation.
- Error responses use a consistent envelope with `error.code`, `error.message`, `error.details`, and `request_id`.
- Settings and error responses do not expose `LLM_API_KEY`; `GET /api/settings` only reports `llm_auth_configured`.
- Upload filenames reject path traversal inputs and startup documentation binds to `127.0.0.1`.
- README, `.env.example`, migrations, and Stage 8 tests are present and runnable in a fresh local environment.

## Environment Tracking

See `docs/spec/environment.md` for the current development baseline that will be used when authoring container images later.
