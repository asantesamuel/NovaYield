"""Tests for app-local API v1 routing and configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.main import create_app

TEST_CSRF_SECRET = "csrf-secret-for-tests-that-is-long-enough"
TEST_LOCATION_HASH_SECRET = "location-hash-test-secret-that-is-long-enough"


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        csrf_secret=SecretStr(TEST_CSRF_SECRET),
        location_hash_secret=SecretStr(TEST_LOCATION_HASH_SECRET),
    )


def test_create_app_composes_versioned_feature_routes_without_global_router_state() -> None:
    first_app = create_app(make_settings())
    second_app = create_app(make_settings())

    first_paths = first_app.openapi()["paths"]
    second_paths = second_app.openapi()["paths"]

    expected_paths = {
        "/api/v1/farms/locations",
        "/api/v1/farms",
        "/api/v1/farms/{farm_id}",
        "/api/v1/farms/{farm_id}/rotation-results",
        "/api/v1/farms/{farm_id}/rotation-results/{result_id}",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
    }
    assert expected_paths <= first_paths.keys()
    assert first_paths.keys() == second_paths.keys()
    assert set(first_paths["/api/v1/farms"]) == {"get", "post"}
    assert set(first_paths["/api/v1/farms/{farm_id}"]) == {"get", "patch"}
    assert set(first_paths["/api/v1/farms/{farm_id}/rotation-results"]) == {"get"}


def test_location_hash_secret_requires_at_least_32_bytes() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(
            _env_file=None,
            csrf_secret=SecretStr(TEST_CSRF_SECRET),
            location_hash_secret=SecretStr("too-short"),
        )

