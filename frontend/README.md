# Frontend

React + TypeScript application built with Vite. The farm setup and recommendation screens use the authenticated FastAPI API; they do not contain demo crop or NASA values.

## Run locally

Start the backend with its MongoDB connection and allow the Vite origin in backend CORS settings. The frontend and API must use the same browser hostname (`localhost` or `127.0.0.1`) so the browser can read the API's CSRF cookie.

```powershell
cd frontend
npm ci
npm run dev
```

When `VITE_API_BASE_URL` is unset, the API URL follows the browser page hostname with port 8000: `http://localhost:8000/api/v1` for a `localhost` Vite page, or `http://127.0.0.1:8000/api/v1` for a `127.0.0.1` page. For another same-site API origin, copy `.env.example` to `.env.local` and set `VITE_API_BASE_URL` explicitly. If an older `.env.local` pins `localhost` while you open Vite on `127.0.0.1`, remove or correct that override. Do not put credentials in a Vite environment file: `VITE_` values are exposed to browser code.

## API flow

The shared client sends browser cookies with requests. It first calls `GET /auth/csrf` when a mutation needs a CSRF token, then reads the `nova_yield_csrf` cookie and sends it as `X-CSRF-Token`. Registration and login use JSON email/password bodies; login establishes a server-backed session cookie. `GET /auth/me` restores a session after refresh, and logout revokes it. An expired session returns the user to login.

Farm setup loads supported location, crop, soil and irrigation choices from the backend catalogs. The saved plot has one to three actual previous-crop events when history is complete. The backend derives the historical NASA period from those dates. An incomplete report remains labelled for review and can be edited later through the owner-scoped farm API. Older free-text profiles show their original entries for owner-led review and are never assigned invented dates or catalog identities. Plot availability and optional numeric priority points are saved with the farm. The screen shows the returned context state and can explicitly refresh unavailable or partial NASA context, including after a page reload, without supplying new dates.

The comparison screen loads an owned farm and its saved result history. Starting a new assessment calls `POST /farms/{farm_id}/rotation-recommendations` with `{}` to use saved priorities, or sends only `priority_adjustment` when the farmer chooses different points for one assessment. The saved farm supplies history and location. The screen compares the returned equal-weight and selected-priority rank groups where available and shows the criterion trade-offs. Returned options, climate evidence, timing and missing-evidence reasons are displayed as provided. If there are no ranked options but the result includes complete dated `unranked_calendar_examples`, the screen displays them separately as review-only calendar examples without rank, suitability, or benefit claims. The screen never constructs future planting dates or treats historical NASA observations as a forecast.

## Checks

```powershell
npm run typecheck
npm run lint
npm run build
```
