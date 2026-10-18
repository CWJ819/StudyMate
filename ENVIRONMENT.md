# Environment Record

This file records the local development environment used while building the project so later containerization can target the same baseline.

## Host

- OS: Ubuntu 22.04.5 LTS (WSL2)
- Kernel: Linux 5.15.167.4-microsoft-standard-WSL2
- Architecture: x86_64

## Runtime

- Python: 3.13.11
- FastAPI: 0.136.3
- httpx: runtime dependency
- SQLAlchemy: 2.0.48
- Alembic: 1.18.5
- Pydantic: 2.12.5
- pydantic-settings: 2.14.2
- PyMuPDF: 1.27.2
- python-pptx: available in local environment
- Uvicorn: 0.42.0

## Notes For Future Images

- Current application requirement is Python `3.12+`.
- Default database is local SQLite at `./data/studymate.db`.
- Default storage root is `./data/uploads`.
- Background work is handled in-process; the first image does not need Redis, Celery, or any external queue.
- Default server bind must remain `127.0.0.1` unless security posture changes.
- Prefer matching the current Linux userspace baseline when authoring the first `Dockerfile`.
