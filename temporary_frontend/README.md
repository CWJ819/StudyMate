# StudyMate Temporary Frontend

This is a disposable test UI for the local StudyMate backend. It has no build step and no npm dependencies.

## Run

Start the backend first:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For offline LLM-backed testing, configure the backend with:

```bash
LLM_BASE_URL=mock://local LLM_MODEL=mock-stage8 uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then start this frontend from the repository root:

```bash
python temporary_frontend/server.py
```

Open `http://127.0.0.1:5173`.

## Notes

- The frontend server binds to `127.0.0.1` by default.
- `/api/*` requests are proxied to `http://127.0.0.1:8000` by default to avoid browser CORS issues.
- Use `STUDYMATE_API_BASE=http://127.0.0.1:8001 python temporary_frontend/server.py` or `--backend` if the backend runs elsewhere.
- This directory is intentionally temporary and can be deleted when the real frontend replaces it.
