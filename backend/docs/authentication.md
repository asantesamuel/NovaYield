# Authentication API Guide

NovaYield uses email/password credentials and an HttpOnly browser session cookie backed by a MongoDB access-token document. The API does not return a bearer token in JSON.

## Routes

| Method and route | Request | Success | Purpose |
| --- | --- | --- | --- |
| `GET /api/v1/auth/csrf` | None | `204 No Content`; sets `nova_yield_csrf` | Initialize the CSRF cookie before state-changing requests. |
| `POST /api/v1/auth/register` | JSON `email`, `password` | `201 Created`; public `id` and normalized `email` | Create an account. |
| `POST /api/v1/auth/login` | JSON `email`, `password` | `204 No Content`; sets `nova_yield_session` | Start a database-backed session. |
| `GET /api/v1/auth/me` | Session cookie | `200 OK`; public `id` and `email` | Read the authenticated identity. |
| `POST /api/v1/auth/logout` | Session cookie and CSRF header | `204 No Content`; revokes and clears the session | End the current session. |

Registration and login use the same JSON shape:

```json
{
  "email": "farmer@example.com",
  "password": "replace-with-a-local-test-password"
}
```

Email is trimmed and lowercased before account creation and lookup. Passwords must contain 8–128 characters. Registration errors do not identify an existing email, and login uses the same generic `LOGIN_BAD_CREDENTIALS` response for an unknown email and an incorrect password.

## CSRF and session flow

The CSRF cookie is readable by browser code so it can be copied into the `X-CSRF-Token` request header. The session cookie is HttpOnly and must not be read by application JavaScript. Registration, login, and logout require a valid CSRF cookie/header pair, including login before a session exists. Other unsafe methods require CSRF protection when a NovaYield session cookie is present.

1. Call `GET /api/v1/auth/csrf` with cookie/credential handling enabled.
2. Send its `nova_yield_csrf` cookie value as `X-CSRF-Token` for registration or login.
3. After login, the cookie jar stores `nova_yield_session`; send it automatically on `GET /api/v1/auth/me` and other protected requests.
4. Send the CSRF header and session cookie on logout. The server deletes the database-backed token and expires the cookie.

Successful login intentionally has an empty response body. The session token is delivered in the `Set-Cookie` header. Keep session and CSRF cookie values out of logs, screenshots, and shared Postman collections.

## Postman

- Use one consistent host for every request, such as `http://localhost:8000`. `localhost` and `127.0.0.1` have separate cookie jars.
- Keep the cookie jar enabled. Send the CSRF bootstrap request first, then inspect **Cookies → Manage Cookies** for the `localhost` domain.
- For both register and login, choose **Body → raw → JSON** and use `email` and `password` keys.
- Add `X-CSRF-Token` with the current `nova_yield_csrf` cookie value on register, login, and logout. Postman sends stored cookies automatically for the same host.
- Check the response status and cookie manager. Do not expect a JSON token from login; `204 No Content` is the successful response.

## Local configuration

In `backend/.env`, keep `NOVAYIELD_CSRF_SECRET` private and stable. Generate a local signing key with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

For local plain-HTTP development, set `NOVAYIELD_AUTH_COOKIE_SECURE=false`; use `true` for HTTPS. `NOVAYIELD_AUTH_SESSION_LIFETIME_SECONDS` defaults to one hour. Set `NOVAYIELD_CORS_ALLOWED_ORIGINS` to the exact frontend origin, and leave `NOVAYIELD_CSRF_COOKIE_DOMAIN` unset for localhost.

The selected package versions and FastAPI Users maintenance-mode decision are recorded in [authentication-dependency-decision.md](authentication-dependency-decision.md). Mongo adapter checks use `NOVAYIELD_TEST_MONGODB_URI` and a unique disposable database; do not point them at a database whose contents must be preserved.
