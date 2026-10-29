# NY-11 Authentication Dependency Compatibility

**Status:** Compatibility checked for the current backend environment; MongoDB persistence check is opt-in.

## Decision

Use the following authentication packages for NY-11:

| Package | Version | Reason |
| --- | --- | --- |
| `fastapi-users` | `15.0.5` | Approved FastAPI authentication and user-management library. |
| `fastapi-users-db-beanie` | `5.0.0` | Beanie adapter release that supports Beanie 2.0 and later. |
| `pwdlib[argon2]` | `0.3.0` | Argon2 password hashing support; FastAPI Users 15.0.5 requires exactly `pwdlib==0.3.0`. |

These are exact pins because this is a newly introduced security boundary and the tested combination matters. The Argon2 extra is explicit; authentication code must configure Argon2 for new password hashes rather than relying on an unspecified default. FastAPI Users 15.0.5 also requests its bcrypt extra, so bcrypt is installed as a transitive dependency, but it is not the selected hash for NovaYield passwords.

The adapter package declares `fastapi-users >=15.0.1` and `beanie >=2.0.0`, so the chosen adapter and installed Beanie 2.2.0 satisfy its declared compatibility range. The adapter source uses Beanie document operations (`get`, `find_one`, `create`, `save`, and `delete`) and does not call Motor-specific collection methods. Beanie 2.2.0 in this application is initialized with PyMongo's `AsyncMongoClient`, so the adapter receives already-initialized document classes and does not create a client of its own.

## Verification

- Installed and imported the selected packages in the ignored `backend/.venv`.
- Verified that `BeanieUserDatabase` accepts a Beanie user document class and `BeanieAccessTokenDatabase` accepts a Beanie access-token document class.
- Verified that `pwdlib` can create and verify an Argon2id hash.
- The optional integration test initializes probe documents through the application's shared `MongoConnection`, then exercises user/token persistence, token-to-user lookup, expiry, and revocation. It runs when `NOVAYIELD_TEST_MONGODB_URI` is configured.
- Real MongoDB checks create a uniquely named disposable database and drop only that database. Use a test MongoDB instance or a local development instance and never point the checks at a database whose contents must be retained.

## Implementation notes

- The current FastAPI Users Beanie documentation still shows Motor. A FastAPI Users issue confirms that this example is outdated for current PyMongo Async installations. Do not copy its client setup: keep using NovaYield's shared `MongoConnection` and let Beanie own document operations.
- The Beanie adapter's base user document includes `is_active`, `is_superuser`, and `is_verified` fields. NY-11 must not expose superuser behavior or add verification flows; keep the agreed API surface limited to email/password account access and the current-user dependency.
- The adapter's base user model has a case-insensitive unique email index. NY-4 additionally requires email normalization before persistence. Normalize before passing the email to the adapter, and keep registration safe against unique-index conflicts.
- The database access-token document stores the session lookup token, an ObjectId user reference, and `created_at`; its adapter queries by token and age and deletes the record on revocation. Treat the token as sensitive session material: do not log it or expose these documents through user-facing schemas, and keep database access restricted.
- FastAPI Users is in maintenance mode. Its maintainers state that security and dependency updates continue, but new features do not. Recheck supported versions and security advisories when dependencies are upgraded.

## NY-11 wiring defaults

- `NOVAYIELD_AUTH_SESSION_LIFETIME_SECONDS` defaults to `3600` and is used by both the browser cookie and the database-backed token strategy. The server checks the token's creation time on use; expired records are not accepted.
- `NOVAYIELD_AUTH_COOKIE_SECURE` defaults to `true`. The local `.env.example` sets it to `false` for plain-HTTP development at localhost. Set it to `true` for HTTPS deployments.
- The cookie name is `nova_yield_session`; it is `HttpOnly` and `SameSite=Lax`.
- UserManager password creation is explicitly configured with `pwdlib`'s Argon2 hasher. No reset-password or email-verification routes are configured by this wiring.
- The database adapters wrap feature-owned Beanie document classes. They do not create Mongo clients; Beanie uses the app's initialized shared Mongo connection.

## NY-11 routes and browser CSRF

- Registration, login, logout, and current identity are exposed under `/api/v1/auth`. Registration accepts only email and password; the response contains only public ID and normalized email. The library's active-user dependency is returned by the app's auth component for reuse by protected feature routers.
- Registration and login both accept JSON with `email` and `password`. Registration uses FastAPI Users' user manager to create the account. A NovaYield-owned login route passes the email/password pair to FastAPI Users' existing credential verifier, then uses the selected cookie backend and database strategy to issue and persist the session token. Logout uses the same backend to revoke the token and clear the cookie. The library's generated login route requires an OAuth2-style form field named `username`; NovaYield deliberately does not expose that form contract because the Product Owner chose a consistent JSON `email` contract for both endpoints.
- Registration uses FastAPI Users' UserManager create operation but maps duplicate-email, invalid-password, and unique-index race failures to the same generic response so registration errors do not name an existing email. Login uses the library's generic bad-credentials response for both unknown email and wrong password.
- New passwords must contain 8–128 characters. This is an implementation validation choice for the MVP; it can be revised if product policy changes. The secret request type masks the password in representations, and public response schemas exclude password hashes and internal account flags.
- The pinned `starlette-csrf==3.0.0` middleware signs a double-submit CSRF cookie and compares it with the `X-CSRF-Token` header. Login, registration, and logout are always checked, including login before a session exists; other unsafe requests are checked when the NovaYield session cookie is present. A safe `GET /auth/csrf` initializes the readable CSRF cookie. The PyPI release is older than this codebase, so review its maintenance and compatibility before a production dependency upgrade.
- The CSRF signing key is required through `NOVAYIELD_CSRF_SECRET` in every environment. The test suite creates a process-local key without committing one. Developers should generate a stable private local value and put it in ignored `backend/.env`; deployments must provide a stable private value through their secret manager. Optional `NOVAYIELD_CSRF_COOKIE_DOMAIN` supports sibling frontend/API subdomains; leave it unset on localhost.
- CORS remains credentialed and restricted to configured frontend origins. The CSRF cookie uses HttpOnly=false so frontend code can read its token; the session cookie remains HttpOnly. Both use SameSite=Lax, and Secure follows the configured HTTPS cookie setting.

## Sources

- [FastAPI Users 15.0.5 on PyPI](https://pypi.org/project/fastapi-users/15.0.5/)
- [FastAPI Users Beanie adapter 5.0.0 on PyPI](https://pypi.org/project/fastapi-users-db-beanie/5.0.0/)
- [Adapter package metadata](https://github.com/fastapi-users/fastapi-users-db-beanie/blob/main/pyproject.toml)
- [Adapter user document and operations](https://github.com/fastapi-users/fastapi-users-db-beanie/blob/main/fastapi_users_db_beanie/__init__.py)
- [Adapter access-token document and operations](https://github.com/fastapi-users/fastapi-users-db-beanie/blob/main/fastapi_users_db_beanie/access_token.py)
- [FastAPI Users issue documenting the outdated Motor example](https://github.com/fastapi-users/fastapi-users/issues/1559)
- [Beanie initialization guide](https://beanie-odm.dev/tutorial/initialization/)
- [pwdlib project](https://github.com/frankie567/pwdlib)
- [Starlette CSRF middleware documentation](https://github.com/frankie567/starlette-csrf)
- [Starlette CSRF 3.0.0 release on PyPI](https://pypi.org/project/starlette-csrf/3.0.0/)
