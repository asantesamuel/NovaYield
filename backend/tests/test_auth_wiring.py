"""Tests for the NY-11 authentication adapters and session configuration."""

import pytest
from beanie import PydanticObjectId
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.exceptions import InvalidID
from pydantic import ValidationError

from app.core.config import Settings
from app.models.access_tokens import AccessToken
from app.models.users import User
from app.services.authentication import (
    AUTH_BACKEND_NAME,
    AUTH_COOKIE_NAME,
    UserManager,
    create_cookie_auth_backend,
    get_access_token_database,
    get_user_database,
)


def test_auth_settings_have_one_hour_default_and_secure_cookie_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.auth_session_lifetime_seconds == 3_600
    assert settings.auth_cookie_secure is True


def test_auth_settings_can_be_overridden_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVAYIELD_AUTH_SESSION_LIFETIME_SECONDS", "7200")
    monkeypatch.setenv("NOVAYIELD_AUTH_COOKIE_SECURE", "false")

    settings = Settings(_env_file=None)

    assert settings.auth_session_lifetime_seconds == 7_200
    assert settings.auth_cookie_secure is False


def test_auth_session_lifetime_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_session_lifetime_seconds=0)


def test_non_local_csrf_secret_must_have_sufficient_length() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(
            _env_file=None,
            environment="production",
            csrf_secret="short-key",
        )


def test_csrf_secret_is_required_in_every_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NOVAYIELD_CSRF_SECRET", raising=False)
    with pytest.raises(ValidationError, match="csrf_secret"):
        Settings(_env_file=None, environment="production")


def test_csrf_cookie_domain_is_normalized_and_rejects_a_url() -> None:
    settings = Settings(_env_file=None, csrf_cookie_domain=" example.com ")
    assert settings.csrf_cookie_domain == "example.com"

    with pytest.raises(ValidationError, match="hostname only"):
        Settings(_env_file=None, csrf_cookie_domain="https://example.com")


def test_user_manager_creates_argon2id_hashes_and_verifies_passwords() -> None:
    manager = UserManager(get_user_database())

    hashed_password = manager.password_helper.hash("safe-test-password")

    assert hashed_password.startswith("$argon2id$")
    assert manager.password_helper.verify_and_update("safe-test-password", hashed_password) == (
        True,
        None,
    )
    assert manager.password_helper.verify_and_update("incorrect", hashed_password) == (
        False,
        None,
    )


def test_cookie_backend_uses_configured_cookie_and_database_token_lifetime() -> None:
    settings = Settings(
        _env_file=None,
        auth_session_lifetime_seconds=120,
        auth_cookie_secure=False,
    )

    backend = create_cookie_auth_backend(settings)
    transport = backend.transport
    strategy = backend.get_strategy(get_access_token_database())

    assert backend.name == AUTH_BACKEND_NAME
    assert transport.cookie_name == AUTH_COOKIE_NAME
    assert transport.cookie_max_age == 120
    assert transport.cookie_httponly is True
    assert transport.cookie_samesite == "lax"
    assert transport.cookie_secure is False
    assert isinstance(strategy, DatabaseStrategy)
    assert strategy.lifetime_seconds == 120
    assert strategy.database.access_token_model is AccessToken

    https_backend = create_cookie_auth_backend(Settings(_env_file=None))
    assert https_backend.transport.cookie_secure is True


def test_auth_adapters_wrap_the_registered_feature_documents() -> None:
    assert get_user_database().user_model is User
    assert get_access_token_database().access_token_model is AccessToken


def test_user_manager_parses_beanie_ids_and_rejects_invalid_ids() -> None:
    manager = UserManager(get_user_database())
    user_id = PydanticObjectId()

    assert manager.parse_id(str(user_id)) == user_id
    with pytest.raises(InvalidID):
        manager.parse_id("not-an-object-id")
