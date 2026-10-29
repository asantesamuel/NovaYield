"""HTTP-level tests for NY-11 registration, sessions, identity, and CSRF."""

from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any

import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from app.models.access_tokens import AccessToken
from app.models.users import User
from app.services.authentication import (
    AUTH_COOKIE_NAME,
    AUTH_CSRF_COOKIE_NAME,
    get_access_token_database,
    get_user_database,
)

FRONTEND_ORIGIN = "http://localhost:5173"
TEST_CSRF_SECRET = token_urlsafe(32)


class FakeMongoConnection:
    async def connect(self) -> bool:
        return True

    async def is_ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class InMemoryUserDatabase:
    def __init__(self) -> None:
        self.users: dict[PydanticObjectId, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.email == email), None)

    async def create(self, data: dict[str, Any]) -> User:
        user = User(id=PydanticObjectId(), **data)
        self.users[user.id] = user
        return user

    async def get(self, user_id: PydanticObjectId) -> User | None:
        return self.users.get(user_id)

    async def update(self, user: User, data: dict[str, Any]) -> User:
        updated_user = user.model_copy(update=data)
        self.users[updated_user.id] = updated_user
        return updated_user

    async def delete(self, user: User) -> None:
        self.users.pop(user.id, None)


class InMemoryAccessTokenDatabase:
    def __init__(self) -> None:
        self.tokens: dict[str, AccessToken] = {}

    async def create(self, data: dict[str, Any]) -> AccessToken:
        access_token = AccessToken(**data)
        self.tokens[access_token.token] = access_token
        return access_token

    async def get_by_token(self, token: str, max_age: datetime | None = None) -> AccessToken | None:
        access_token = self.tokens.get(token)
        if access_token is None:
            return None
        if max_age is not None and access_token.created_at < max_age:
            return None
        return access_token

    async def delete(self, access_token: AccessToken) -> None:
        self.tokens.pop(access_token.token, None)


@pytest.fixture
def auth_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Run the real auth routes against in-memory adapters, without MongoDB."""

    monkeypatch.setattr(User, "get_pymongo_collection", lambda _self: None)
    monkeypatch.setattr(AccessToken, "get_pymongo_collection", lambda _self: None)

    user_database = InMemoryUserDatabase()
    token_database = InMemoryAccessTokenDatabase()
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_cookie_secure=False,
        auth_session_lifetime_seconds=3_600,
        cors_allowed_origins=FRONTEND_ORIGIN,
        csrf_secret=SecretStr(TEST_CSRF_SECRET),
    )
    app = create_app(
        settings,
        mongo_connection_factory=lambda _settings: FakeMongoConnection(),
    )
    app.dependency_overrides[get_user_database] = lambda: user_database
    app.dependency_overrides[get_access_token_database] = lambda: token_database

    with TestClient(app) as client:
        yield client, user_database, token_database, app


def csrf_headers(client: TestClient) -> dict[str, str]:
    """Fetch the safe bootstrap route, then echo its readable cookie in the header."""

    response = client.get(
        "/api/v1/auth/csrf",
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert response.status_code == 204
    token = client.cookies.get(AUTH_CSRF_COOKIE_NAME)
    assert token is not None
    return {"Origin": FRONTEND_ORIGIN, "X-CSRF-Token": token}


def register_user(client: TestClient, *, email: str = "farmer@example.com") -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "safe-passphrase-123"},
        headers=csrf_headers(client),
    )

    assert response.status_code == 201
    return response.json()


def login_user(client: TestClient, *, email: str = "farmer@example.com") -> Any:
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "safe-passphrase-123"},
        headers=csrf_headers(client),
    )


def test_registration_normalizes_email_and_returns_only_public_fields(
    auth_client: Any,
) -> None:
    client, users, _tokens, _app = auth_client

    response = client.post(
        "/api/v1/auth/register",
        json={"email": " Farmer.Example@Mail.COM ", "password": "safe-passphrase-123"},
        headers=csrf_headers(client),
    )

    assert response.status_code == 201
    assert response.json()["email"] == "farmer.example@mail.com"
    assert set(response.json()) == {"id", "email"}
    stored_user = next(iter(users.users.values()))
    assert stored_user.email == "farmer.example@mail.com"
    assert stored_user.hashed_password.startswith("$argon2id$")
    assert "safe-passphrase-123" not in response.text
    assert "hashed_password" not in response.text


def test_registration_duplicate_email_is_rejected_without_email_enumeration(
    auth_client: Any,
) -> None:
    client, _users, _tokens, _app = auth_client
    register_user(client)

    duplicate_response = client.post(
        "/api/v1/auth/register",
        json={"email": "FARMER@example.com", "password": "safe-passphrase-123"},
        headers=csrf_headers(client),
    )

    assert duplicate_response.status_code == 400
    assert duplicate_response.json() == {
        "detail": "Unable to create an account with those details."
    }
    assert "farmer@example.com" not in duplicate_response.text


def test_registration_rejects_unapproved_fields_and_short_passwords(
    auth_client: Any,
) -> None:
    client, users, _tokens, _app = auth_client
    csrf = csrf_headers(client)

    privilege_attempt = client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@example.com",
            "password": "safe-passphrase-123",
            "is_superuser": True,
        },
        headers=csrf,
    )
    short_password = "short"
    short_password_response = client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": short_password},
        headers=csrf,
    )

    assert privilege_attempt.status_code == 422
    assert short_password_response.status_code == 400
    assert short_password_response.json()["detail"] == (
        "Unable to create an account with those details."
    )
    assert short_password not in short_password_response.text
    assert not users.users


def test_missing_registration_and_login_credentials_are_rejected(
    auth_client: Any,
) -> None:
    client, _users, _tokens, _app = auth_client
    csrf = csrf_headers(client)

    missing_registration = client.post(
        "/api/v1/auth/register",
        json={"email": "farmer@example.com"},
        headers=csrf,
    )
    missing_login = client.post("/api/v1/auth/login", json={}, headers=csrf)

    assert missing_registration.status_code == 422
    assert missing_login.status_code == 422


def test_login_sets_one_hour_httponly_cookie_and_authenticates_current_user(
    auth_client: Any,
) -> None:
    client, _users, tokens, _app = auth_client
    public_user = register_user(client, email=" Farmer.Example@Mail.COM ")

    login_response = login_user(client, email="FARMER.EXAMPLE@MAIL.COM")
    cookie_headers = login_response.headers.get_list("set-cookie")
    auth_cookie = next(header for header in cookie_headers if AUTH_COOKIE_NAME in header)

    identity_response = client.get("/api/v1/auth/me")

    assert login_response.status_code == 204
    assert "httponly" in auth_cookie.lower()
    assert "samesite=lax" in auth_cookie.lower()
    assert "max-age=3600" in auth_cookie.lower()
    assert "secure" not in auth_cookie.lower()
    assert len(tokens.tokens) == 1
    assert identity_response.status_code == 200
    assert identity_response.json() == public_user
    assert "hashed_password" not in identity_response.text
    assert "safe-passphrase-123" not in identity_response.text


def test_bad_login_is_indistinguishable_for_unknown_email_and_wrong_password(
    auth_client: Any,
) -> None:
    client, _users, _tokens, _app = auth_client
    register_user(client)

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": "farmer@example.com", "password": "incorrect-password"},
        headers=csrf_headers(client),
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": "incorrect-password"},
        headers=csrf_headers(client),
    )

    assert wrong_password.status_code == 400
    assert unknown_email.status_code == 400
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json() == {"detail": "LOGIN_BAD_CREDENTIALS"}


def test_current_user_requires_a_valid_session_and_rejects_expired_sessions(
    auth_client: Any,
) -> None:
    client, _users, tokens, _app = auth_client
    assert client.get("/api/v1/auth/me").status_code == 401

    register_user(client)
    assert login_user(client).status_code == 204
    access_token = next(iter(tokens.tokens.values()))
    access_token.created_at = datetime.now(UTC) - timedelta(hours=2)

    expired_identity = client.get("/api/v1/auth/me")

    assert expired_identity.status_code == 401


def test_logout_revokes_database_token_and_clears_cookie(auth_client: Any) -> None:
    client, _users, tokens, _app = auth_client
    register_user(client)
    assert login_user(client).status_code == 204
    assert len(tokens.tokens) == 1

    logout_response = client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    assert logout_response.status_code == 204
    assert not tokens.tokens
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auth_responses_and_logs_do_not_expose_password_or_session_token(
    auth_client: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _users, _tokens, _app = auth_client
    password = f"private-test-password-{token_urlsafe(12)}"
    email = "log-check@example.com"
    caplog.set_level("DEBUG")

    registration = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
        headers=csrf_headers(client),
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=csrf_headers(client),
    )
    session_token = client.cookies.get(AUTH_COOKIE_NAME)
    identity = client.get("/api/v1/auth/me")
    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    assert registration.status_code == 201
    assert login.status_code == 204
    assert session_token is not None
    assert identity.status_code == 200
    assert logout.status_code == 204
    for response in (registration, login, identity, logout):
        assert password not in response.text
        assert session_token not in response.text
    assert password not in caplog.text
    assert session_token not in caplog.text


def test_csrf_is_required_for_login_even_before_a_session_exists(auth_client: Any) -> None:
    client, _users, _tokens, _app = auth_client

    rejected = client.post(
        "/api/v1/auth/login",
        json={"email": "farmer@example.com", "password": "anything"},
    )

    assert rejected.status_code == 403
    assert rejected.text == "CSRF token verification failed"


def test_csrf_rejects_a_header_that_does_not_match_the_signed_cookie(
    auth_client: Any,
) -> None:
    client, _users, _tokens, _app = auth_client
    csrf_headers(client)

    rejected = client.post(
        "/api/v1/auth/login",
        json={"email": "farmer@example.com", "password": "anything"},
        headers={"X-CSRF-Token": "forged-token"},
    )

    assert rejected.status_code == 403


def test_csrf_cookie_is_readable_and_uses_configured_cookie_policy(
    auth_client: Any,
) -> None:
    client, _users, _tokens, _app = auth_client

    response = client.get("/api/v1/auth/csrf")
    cookie = next(
        header
        for header in response.headers.get_list("set-cookie")
        if AUTH_CSRF_COOKIE_NAME in header
    )

    assert response.status_code == 204
    assert "httponly" not in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert AUTH_CSRF_COOKIE_NAME in client.cookies


def test_csrf_protects_other_unsafe_requests_when_session_cookie_is_present(
    auth_client: Any,
) -> None:
    client, _users, _tokens, app = auth_client

    async def test_mutation() -> dict[str, bool]:
        return {"ok": True}

    app.add_api_route("/api/v1/test-mutation", test_mutation, methods=["POST"])
    client.cookies.set(AUTH_COOKIE_NAME, "session-cookie-present")

    response = client.post("/api/v1/test-mutation")

    assert response.status_code == 403


def test_cors_preflight_allows_the_configured_csrf_request_header(
    auth_client: Any,
) -> None:
    client, _users, _tokens, _app = auth_client

    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "x-csrf-token" in response.headers["access-control-allow-headers"].lower()
