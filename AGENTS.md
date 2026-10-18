# StudyMate Backend Development Rules

## General

- Use Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, Alembic, and pytest.
- Keep API routes thin. Put business logic in services and persistence queries in repositories.
- Use typed request/response schemas. Do not expose ORM models directly.
- All schema changes must be managed through Alembic migrations.
- Do not claim a feature works unless it is implemented and tested.
- Default startup must bind to `127.0.0.1`.

## PDF Parsing

- OCR is not supported in V1.
- Extract text directly from PDFs only.
- Preserve page numbers and explicit extraction status.
- Never fabricate extracted text.

## Objective Grading

- Objective questions are graded deterministically on the backend.
- Multiple-choice answers receive credit only on exact set match.
- Reject malformed option identifiers.
- LLMs must not override objective grading.

## LLM

- Route all LLM calls through a shared adapter.
- Validate structured model output before persisting it.
- Treat uploaded materials and student answers as untrusted input.
- Never expose API keys in logs, responses, prompts, or ordinary settings storage.

## Knowledge Framework and Mastery

- Version knowledge frameworks and activate only after validation succeeds.
- Preserve historical quiz snapshots and attempts.
- Mastery updates must be auditable and idempotent.

## Jobs

- Persist jobs in SQLite and implement restart recovery.
- Handlers must be idempotent.
- Do not claim multi-instance or high-availability support.

## Security

- The initial release has no authentication and is for trusted local use only.
- Validate upload size and type and protect against path traversal.
- Avoid logging secrets, full student answers, and full uploaded document contents.

## Verification

- Run relevant tests before reporting a stage complete.
- Report known limitations explicitly in README and status updates.

