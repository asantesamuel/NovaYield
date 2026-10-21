"""Smoke tests for application startup and health/readiness contracts."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.readiness import register_readiness_check
from app.main import create_app


def make_app() -> TestClient:
    settings = Settings(
        _env_file=None,
        app_name="Nova Yield Test API",
        cors_allowed_origins="http://localhost:5173",
    )
    return TestClient(create_app(settings))


def test_application_starts_and_exposes_openapi() -> None:
    with make_app() as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Nova Yield Test API"


def test_liveness_does_not_depend_on_database_readiness() -> None:
    with make_app() as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_unconfigured_database() -> None:
    with make_app() as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "not_configured"},
    }


def test_readiness_reflects_registered_database_check() -> None:
    settings = Settings(_env_file=None)
    app = create_app(settings)
    register_readiness_check(app, "database", lambda: True)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_cors_allows_configured_frontend_origin_with_credentials() -> None:
    with make_app() as client:
        response = client.options(
            "/api/v1/example",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_wildcard_origin() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS origins are not allowed"):
        Settings(_env_file=None, cors_allowed_origins="*")
