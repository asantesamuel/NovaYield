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

- **`frontend/`** contains the React application, browser-facing configuration, and Node dependencies. It includes account access, catalog-backed plot setup, and the saved-assessment view.
- **`backend/`** contains the FastAPI app, Python dependencies, API configuration, tests, MongoDB persistence, NASA POWER ingestion/reuse, and decision services.
- **`analysis_docs/`** contains human-authored research and analytical work. Runtime data such as user accounts, farm records, decision results, and NASA response caches belongs in backend persistence (MongoDB), never in this directory.

## Technologies

| Area | Foundation technology |
| --- | --- |
| Frontend | React, TypeScript, Vite, Oxlint |
| Backend | Python, FastAPI, Pydantic Settings, Uvicorn, Beanie |
| Database | MongoDB through one shared PyMongo async client and Beanie initialization boundary |
| External data | NASA POWER daily meteorological data through a reusable snapshot service |

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

Generate two different local secret values and place them in `backend/.env` as
`NOVAYIELD_CSRF_SECRET` and `NOVAYIELD_LOCATION_HASH_SECRET`. The latter must
remain stable to reuse existing NASA snapshot identities. Run this command
twice and keep the values private:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
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

- API base: <http://localhost:8000> (or `http://127.0.0.1:8000` when the frontend uses that host)
- OpenAPI / Swagger UI: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/health/live>
- Readiness: <http://localhost:8000/health/ready>

The backend expects a MongoDB service at `mongodb://localhost:27017` by default. Set `NOVAYIELD_MONGODB_URI` and `NOVAYIELD_MONGODB_DATABASE_NAME` in `backend/.env` to use another development database. The API can start while MongoDB is unavailable, but `/health/ready` reports HTTP 503 until the connection and Beanie initialization succeed. Liveness and OpenAPI remain available.

Seed the supported places and NY-39 crop/reference catalogs into that configured database from `backend/`:

```powershell
python -m app.farms.seed_locations
python -m app.farms.seed_catalogs
```

Both commands insert missing stable keys and can be rerun. The candidate crop library contains maize, cowpea, groundnut, cassava, yam, and rice; extra history-only crop identities do not become recommendation candidates. If an older NovaYield database already contains farms created with free-text fields, run the explicit migration before using those farms in the new workflow:

```powershell
python -m app.farms.migrate_legacy
```

The migration marks those records `legacy_unresolved`. It preserves old text and does not manufacture crop IDs, event order, or dates. The owner must review the profile and supply the new catalog choices and actual history through the farm update flow.

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

When `VITE_API_BASE_URL` is unset, the frontend calls port 8000 on the page's current hostname, so a Vite page opened on `localhost` uses `localhost` for the API and one opened on `127.0.0.1` uses `127.0.0.1`. Set the variable in `frontend/.env.local` for another API origin, and keep it on the same browser site for cookie access. Remove or update an older `.env.local` that explicitly pins the wrong hostname. The frontend makes authenticated API requests with browser cookies; no frontend unit-test framework is configured yet.

## Saved-farm API flow

After cookie/CSRF login, the frontend loads supported locations, crop identities, and soil/irrigation choices from the backend catalogs. A new `farm-v2` profile stores one to three ordered, actual past crop events when history is complete, plus explicit between-crop gap reports and plot availability. Unknown or incomplete history remains marked for review; old free-text farms require a farmer-led update rather than inferred crop identities or dates.

The server derives an inclusive NASA POWER period ending at the last reported crop end and starting at the earlier of the first crop start or twelve calendar months before that end. Saving a complete farm attempts to retrieve and persist that context. Subsequent environmental and recommendation POSTs use the saved farm ID; callers send no historical or future date range. The environmental POST can request `force_refresh`; the recommendation POST can supply only an optional four-criterion `priority_adjustment`. The saved result exposes source/freshness, evidence and timing status, assumptions and trade-offs. It can legitimately report `needs_review` with no ranked options while exact pilot crop/calendar evidence remains incomplete. See the [API workflow guide](backend/docs/api-workflows.md) for request shapes and result interpretation.

## Configuration and secrets

- Backend settings use the `NOVAYIELD_` environment-variable prefix and load `backend/.env` when present. See `backend/.env.example` for non-secret defaults.
- Frontend browser-exposed settings use `VITE_` variables. See `frontend/.env.example`; never put credentials or private API keys in a Vite variable because those values are bundled for the browser.
- Cookie-based login requires `GET /api/v1/auth/csrf` before a mutation and an `X-CSRF-Token` header copied from the readable CSRF cookie. The separate session cookie is HttpOnly. Local HTTP uses `NOVAYIELD_AUTH_COOKIE_SECURE=false`; use `true` behind HTTPS and allow only the configured frontend origin for credentialed CORS. The frontend client handles the CSRF bootstrap automatically.
- NASA snapshot checks use configurable recent-publication and GEOS-IT replacement timings in `backend/.env.example`; they do not apply a universal expiration time to old historical data. A valid prior snapshot remains available as labeled cached data when a refresh fails.
- Local `.env` and `.env.local` files, virtual environments, dependencies, and build output are ignored by Git. Do not commit secrets.

## Development boundaries and decisions

- The root keeps the monorepo simple: one repository and separate dependency/configuration boundaries, without adding a workspace manager before it is needed.
- The FastAPI application factory, settings, API router hook, health endpoints, and shared MongoDB/Beanie boundary live under `backend/app/`. Feature routers can be registered under `/api/v1`; request/response schemas, MongoDB documents, repositories, services, and external NASA clients remain in their respective feature modules.
- API settings are read from environment variables rather than hard-coded deployment values. CORS allows explicit configured origins with credentials and rejects wildcard origins.
- Liveness checks only the API process. Readiness checks required dependencies and safely reports unavailable/not-configured status without returning connection details.
- React and Vite are isolated under `frontend/`. The account, plot setup, and saved-assessment screens use the FastAPI API through `VITE_API_BASE_URL`.
- Backend tests live in `backend/tests/`; the frontend currently has type, lint, and production-build checks but no test runner.
- Backend contracts and module ownership are documented in [`backend/docs/backend-contracts.md`](backend/docs/backend-contracts.md). The current workflow and request examples are in [`backend/docs/api-workflows.md`](backend/docs/api-workflows.md). The [research and Product Owner decision record](novayield-research-and-product-decisions.md) defines the approved baseline and provisional evidence limits.
- MongoDB lifecycle, model registration, references, indexes, and local setup are documented in [`backend/docs/persistence-conventions.md`](backend/docs/persistence-conventions.md).

## Analysis workflow

Use `analysis_docs/` for source-based agronomic findings, pilot-region and crop-library decisions, data-source documentation, assumptions requiring expert validation, and reproducible analytical experiments. Record evidence and unresolved questions so the eventual decision logic can be implemented from reviewed conclusions. Do not store live application records or external-response caches here.

## Git workflow

The initial foundation was established on `master`. For later tickets, create one branch per ticket from the team's current integration branch after confirming that it contains the merged work:

```powershell
git status --short --branch
git switch <current-integration-branch>
git pull --ff-only
git switch -c feature/NY-<issue>-short-description
```

From the repository root, inspect the current branch and worktree with:

```powershell
git status --short --branch
git log --oneline -3
```

Use `frontend/` for browser code, `backend/` for service/API/runtime persistence code, and `analysis_docs/` for research and analytical artifacts.
