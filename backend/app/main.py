"""FastAPI application factory and ASGI entry point."""

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette_csrf import CSRFMiddleware

from app.api.authentication import create_authentication_components
from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.readiness import register_readiness_check
from app.database.connection import MongoConnection
from app.services.authentication import AUTH_COOKIE_NAME, AUTH_CSRF_COOKIE_NAME


def create_app(
    settings: Settings | None = None,
    *,
    mongo_connection_factory: Callable[[Settings], MongoConnection] = MongoConnection,
) -> FastAPI:
    """Build a configured FastAPI application, allowing isolated test settings."""

    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Create the async client inside the lifespan so it belongs to this app's event loop.
        mongo = mongo_connection_factory(app_settings)
        app.state.mongo = mongo
        register_readiness_check(app, "database", mongo.is_ready)
        try:
            # A failed ping keeps the process alive; readiness reports that it cannot serve.
            await mongo.connect()
            yield
        finally:
            await mongo.close()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="Nova Yield API for farm decision support.",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.readiness_checks = {"database": None}
    authentication = create_authentication_components(app_settings)
    application.state.current_active_user = authentication.current_active_user

    api_prefix = app_settings.api_v1_prefix.rstrip("/")
    application.add_middleware(
        CSRFMiddleware,
        secret=app_settings.csrf_secret.get_secret_value(),
        required_urls=[re.compile(rf"^{re.escape(api_prefix)}/auth/(?:register|login|logout)$")],
        sensitive_cookies={AUTH_COOKIE_NAME},
        cookie_name=AUTH_CSRF_COOKIE_NAME,
        cookie_domain=app_settings.csrf_cookie_domain,
        cookie_secure=app_settings.auth_cookie_secure,
        cookie_httponly=False,
        cookie_samesite="lax",
        header_name="X-CSRF-Token",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )
    application.include_router(api_router, prefix=app_settings.api_v1_prefix)
    application.include_router(authentication.router, prefix=app_settings.api_v1_prefix)
    application.include_router(health_router)
    return application


app = create_app()
