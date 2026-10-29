# Backend

This directory contains Nova Yield's FastAPI application and Python dependencies. The backend owns API behavior, MongoDB-backed application persistence, and integrations with external data providers. Research notes and analysis artifacts belong in the repository's `analysis_docs/` directory.

## Layout

- `app/main.py` creates the FastAPI app and manages its startup/shutdown lifespan.
- `app/core/` contains shared settings and cross-cutting infrastructure.
- `app/database/` owns the shared Mongo client, Beanie initialization, document registry, and connection dependencies.
- `app/integrations/nasa/power.py` owns the isolated NASA POWER Daily Point client and normalization service.
- `app/models/` is where feature teams add their own Beanie document modules.
- `app/repositories/` contains feature-owned MongoDB read/write boundaries, including the NY-6 environmental snapshot repository.
- `app/api/` contains health endpoints and the versioned router registration point.
- `tests/` contains backend unit and optional database integration tests.
- `docs/backend-contracts.md` defines the API and module contracts from NY-1.
- `docs/persistence-conventions.md` explains MongoDB references, indexes, and lifecycle conventions from NY-4.
- `docs/nasa-power.md` records the NY-5 request, normalization, coverage, privacy, and error contracts.
- `docs/nasa-power-snapshots.md` records the NY-6 identity, persistence, and refresh-policy decisions.

## Local development (Windows PowerShell)

From the repository root:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

The default settings expect MongoDB at `mongodb://localhost:27017` and use the `nova_yield` database. Start a local MongoDB service or set `NOVAYIELD_MONGODB_URI` and `NOVAYIELD_MONGODB_DATABASE_NAME` in `backend/.env` to point to an existing development database. Never put a production URI or credentials in `.env.example` or commit a real `.env` file.

Authentication uses a one-hour database-backed session by default. The `.env.example` sets `NOVAYIELD_AUTH_COOKIE_SECURE=false` for local HTTP development. Set it to `true` when serving the API over HTTPS; the session cookie remains HttpOnly and SameSite=Lax.

The API requires a private signing key for its signed CSRF double-submit cookie. Generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the generated value into `backend/.env` as `NOVAYIELD_CSRF_SECRET=<generated-value>`. Keep `.env` private and out of Git; the example file contains only a commented placeholder.

The browser should first call `GET /api/v1/auth/csrf` with credentials enabled, read the `nova_yield_csrf` cookie, and send its value in the `X-CSRF-Token` header on registration, login, logout, and other authenticated state-changing requests. If the frontend and API are sibling subdomains, configure `NOVAYIELD_CSRF_COOKIE_DOMAIN` to their shared parent domain so frontend JavaScript can read the CSRF cookie. Keep it unset for localhost. Both registration and login accept JSON with `email` and `password`; email is normalized to lowercase. Postman should use **Body → raw → JSON** for both requests.

Authentication endpoints are `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, and authenticated `GET /api/v1/auth/me`. The `/me` response contains only the user's public ID and email.

If using Docker Desktop for a disposable local database, start its engine and run:

```powershell
docker run --name nova-yield-mongo --publish 27017:27017 --detach mongo:8
```

Stop it with `docker stop nova-yield-mongo`; remove the container with `docker rm nova-yield-mongo` only when you no longer need that local database.

Start the API from `backend/`:

```powershell
python -m uvicorn app.main:app --reload
```

The API is at `http://127.0.0.1:8000`, OpenAPI docs at `http://127.0.0.1:8000/docs`, and health probes at `/health/live` and `/health/ready`. The process can start while MongoDB is unavailable; `/health/ready` returns HTTP 503 until the database can be reached and Beanie initialization succeeds.

## Checks

Run from `backend/`:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The unit tests use fakes and do not require MongoDB. To run the optional real-database checks, set `NOVAYIELD_TEST_MONGODB_URI` in the current PowerShell session to a disposable test MongoDB URI, then run:

```powershell
python -m pytest tests/test_database.py -k integration
python -m pytest tests/test_environmental_snapshot_integration.py
```

Both integration tests create and drop uniquely named temporary databases. The snapshot test mocks NASA POWER and verifies that MongoDB stores one normalized snapshot which a later request reuses without another provider call. Do not point these tests at a database containing data you need to keep.

The committed `.env.example` contains non-secret development defaults. Read [the persistence conventions](docs/persistence-conventions.md) before adding a model or repository.
