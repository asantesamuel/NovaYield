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
- Added an optional integration test that initializes the probe documents through the application's shared `MongoConnection`, then creates and reads a user and access token. It runs when `NOVAYIELD_TEST_MONGODB_URI` is configured.
- No local MongoDB service is listening at `localhost:27017` in this environment, so the real MongoDB integration test is not currently runnable here.

## Important implementation notes for the next NY-11 subtasks

- The current FastAPI Users Beanie documentation still shows Motor. A FastAPI Users issue confirms that this example is outdated for current PyMongo Async installations. Do not copy its client setup: keep using NovaYield's shared `MongoConnection` and let Beanie own document operations.
- The Beanie adapter's base user document includes `is_active`, `is_superuser`, and `is_verified` fields. NY-11 must not expose superuser behavior or add verification flows; keep the agreed API surface limited to email/password account access and the current-user dependency.
- The adapter's base user model has a case-insensitive unique email index. NY-4 additionally requires email normalization before persistence. Normalize before passing the email to the adapter, and keep registration safe against unique-index conflicts.
- The database access-token document stores the session lookup token, an ObjectId user reference, and `created_at`; its adapter queries by token and age and deletes the record on revocation. Treat the token as sensitive session material: do not log it or expose these documents through user-facing schemas, and keep database access restricted.
- FastAPI Users is in maintenance mode. Its maintainers state that security and dependency updates continue, but new features do not. Recheck supported versions and security advisories when dependencies are upgraded.

## Sources

- [FastAPI Users 15.0.5 on PyPI](https://pypi.org/project/fastapi-users/15.0.5/)
- [FastAPI Users Beanie adapter 5.0.0 on PyPI](https://pypi.org/project/fastapi-users-db-beanie/5.0.0/)
- [Adapter package metadata](https://github.com/fastapi-users/fastapi-users-db-beanie/blob/main/pyproject.toml)
- [Adapter user document and operations](https://github.com/fastapi-users/fastapi-users-db-beanie/blob/main/fastapi_users_db_beanie/__init__.py)
- [Adapter access-token document and operations](https://github.com/fastapi-users/fastapi-users-db-beanie/blob/main/fastapi_users_db_beanie/access_token.py)
- [FastAPI Users issue documenting the outdated Motor example](https://github.com/fastapi-users/fastapi-users/issues/1559)
- [Beanie initialization guide](https://beanie-odm.dev/tutorial/initialization/)
- [pwdlib project](https://github.com/frankie567/pwdlib)
