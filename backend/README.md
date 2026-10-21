# Backend

This directory contains the FastAPI application and its independent Python dependencies. The initial scaffold provides an application factory, environment-backed settings, explicit-origin CORS, OpenAPI docs, and liveness/readiness probes. Feature routes and MongoDB integration belong in later backend tickets.

## Layout

- `app/main.py` creates the FastAPI app and is the Uvicorn entry point.
- `app/core/` contains shared settings and infrastructure hooks.
- `app/api/` contains health endpoints and the versioned router registration point.
- `tests/` contains backend tests.
- `docs/backend-contracts.md` defines the current module and API integration contracts from NY-1.

## Local development (Windows PowerShell)

From the repository root:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

The API is at `http://127.0.0.1:8000`, OpenAPI docs at `http://127.0.0.1:8000/docs`, and health probes at `/health/live` and `/health/ready`. Readiness currently reports `database: not_configured` until NY-4 supplies a MongoDB connection and probe.

Run checks from `backend/`:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The committed `.env.example` contains only non-secret defaults. Put local overrides in `.env`; never commit real credentials or connection strings.
