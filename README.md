# Nova Yield

Nova Yield is a NASA Space Apps Challenge decision-support prototype for farmers and agricultural extension officers. It brings NASA-derived environmental context together with farm information, crop characteristics, and farmer priorities so users can explore crop-rotation options and understand their trade-offs.

The MVP is intended to support discussion and planning. Its relative, rule-based comparisons are not yield forecasts, soil tests, profitability estimates, or guaranteed planting advice. The pilot area, crop library, crop calendar, and agronomic rules remain subject to research and local validation.

## Repository layout

This monorepo keeps each application and workstream in its own directory while sharing one Git history:

```text
NovaYield/
├── frontend/       # React + TypeScript + Vite application
├── backend/        # FastAPI application, tests, and backend documentation
├── analysis_docs/  # Agronomic research, data evidence, decisions, and experiments
├── README.md       # Main developer guide
└── .gitignore
```

- **`frontend/`** contains the React application, browser-facing configuration, and Node dependencies. It currently provides only the initial application shell.
- **`backend/`** contains the FastAPI app, Python dependencies, API configuration, backend tests, and persistence conventions. NY-4 establishes the shared MongoDB connection and Beanie initialization; authentication, domain collections, NASA ingestion, and decision logic remain in their feature tickets.
- **`analysis_docs/`** contains human-authored research and analytical work. Runtime data such as user accounts, farm records, decision results, and NASA response caches belongs in backend persistence (MongoDB), never in this directory.

## Technologies

| Area | Foundation technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, Oxlint |
| Backend | Python, FastAPI, Pydantic Settings, Uvicorn, Beanie |
| Database | MongoDB through one shared PyMongo async client and Beanie initialization boundary |
| External data | NASA Earth observation APIs, to be integrated by later backend tickets |

The frontend and backend install their dependencies separately. `frontend/package-lock.json` locks the Node dependency tree; Python dependencies currently use bounded compatible ranges in requirement files and are not yet lockfile-pinned.

## Prerequisites

- Git
- Python 3.11 or later (the backend setup below uses the Python launcher on Windows)
- Node.js 22.12+ or 20.19+ and npm for the current Vite toolchain ([Vite's compatibility requirements](https://vite.dev/guide/))

## Backend setup and commands (Windows PowerShell)

From the repository root:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation, use this for the current terminal and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Alternatively, run commands with `.\.venv\Scripts\python.exe -m ...` without activating the environment.

Start the API from `backend/`:

```powershell
python -m uvicorn app.main:app --reload
```

- API base: <http://127.0.0.1:8000>
- OpenAPI / Swagger UI: <http://127.0.0.1:8000/docs>
- Liveness: <http://127.0.0.1:8000/health/live>
- Readiness: <http://127.0.0.1:8000/health/ready>

The backend expects a MongoDB service at `mongodb://localhost:27017` by default. Set `NOVAYIELD_MONGODB_URI` and `NOVAYIELD_MONGODB_DATABASE_NAME` in `backend/.env` to use another development database. The API can start while MongoDB is unavailable, but `/health/ready` reports HTTP 503 until the connection and Beanie initialization succeed. Liveness and OpenAPI remain available.

Run backend tests and code checks from `backend/`:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## Frontend setup and commands

From the repository root:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Vite prints the local address (normally <http://localhost:5173>). Frontend checks and production build:

```powershell
npm run lint
npm run typecheck
npm run build
npm run preview
```

The Vite dev server reads `VITE_API_BASE_URL` from `frontend/.env.local`; the safe local default is `http://localhost:8000/api/v1`. The scaffold does not yet make API requests. No frontend unit-test framework is configured yet.

## Configuration and secrets

- Backend settings use the `NOVAYIELD_` environment-variable prefix and load `backend/.env` when present. See `backend/.env.example` for non-secret defaults.
- Frontend browser-exposed settings use `VITE_` variables. See `frontend/.env.example`; never put credentials or private API keys in a Vite variable because those values are bundled for the browser.
- Local `.env` and `.env.local` files, virtual environments, dependencies, and build output are ignored by Git. Do not commit secrets.

## Development boundaries and decisions

- The root keeps the monorepo simple: one repository and separate dependency/configuration boundaries, without adding a workspace manager before it is needed.
- The FastAPI application factory, settings, API router hook, health endpoints, and shared MongoDB/Beanie boundary live under `backend/app/`. Feature routers can be registered under `/api/v1`; request/response schemas, MongoDB documents, repositories, services, and external NASA clients remain in their respective feature modules.
- API settings are read from environment variables rather than hard-coded deployment values. CORS allows explicit configured origins with credentials and rejects wildcard origins.
- Liveness checks only the API process. Readiness checks required dependencies and safely reports unavailable/not-configured status without returning connection details.
- React and Vite are isolated under `frontend/`. The current screen is a minimal project shell, not a feature page. API configuration is ready for later integration through `VITE_API_BASE_URL`.
- Backend tests live in `backend/tests/`; the frontend currently has type, lint, and production-build checks but no test runner.
- Backend contracts and proposed module ownership are documented in [`backend/docs/backend-contracts.md`](backend/docs/backend-contracts.md). The implementation avoids choosing unresolved agronomic rules, crop scoring, or NASA data freshness thresholds before the research tickets provide evidence.
- MongoDB lifecycle, model registration, references, indexes, and local setup are documented in [`backend/docs/persistence-conventions.md`](backend/docs/persistence-conventions.md).

## Analysis workflow

Use `analysis_docs/` for source-based agronomic findings, pilot-region and crop-library decisions, data-source documentation, assumptions requiring expert validation, and reproducible analytical experiments. Record evidence and unresolved questions so the eventual decision logic can be implemented from reviewed conclusions. Do not store live application records or external-response caches here.

## Git workflow

This initial foundation was established directly on `master` as requested. For later implementation work, create one branch per ticket from an up-to-date `master`:

```powershell
git switch master
git pull --ff-only
git switch -c feature/NY-<issue>-short-description
```

From the repository root, inspect the current branch and worktree with:

```powershell
git status --short --branch
git log --oneline -3
```

Use `frontend/` for browser code, `backend/` for service/API/runtime persistence code, and `analysis_docs/` for research and analytical artifacts.
