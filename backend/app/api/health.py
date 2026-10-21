"""Liveness and dependency-readiness endpoints."""

import inspect

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.readiness import ReadinessCheck

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Check that the API process is alive")
async def live() -> dict[str, str]:
    """Report process liveness without checking downstream dependencies."""

    return {"status": "alive"}


@router.get("/health/ready", summary="Check whether required dependencies are ready")
async def ready(request: Request) -> JSONResponse:
    """Report readiness; an unconfigured or unhealthy database check is not ready."""

    checks: dict[str, ReadinessCheck | None] = getattr(
        request.app.state, "readiness_checks", {"database": None}
    )
    check_results: dict[str, str] = {}

    for name, check in checks.items():
        if check is None:
            check_results[name] = "not_configured"
            continue
        try:
            result = check()
            if inspect.isawaitable(result):
                result = await result
            check_results[name] = "ok" if result else "unavailable"
        except Exception:
            # Do not expose dependency errors or connection strings to callers.
            check_results[name] = "unavailable"

    is_ready = bool(check_results) and all(value == "ok" for value in check_results.values())
    status_code = 200 if is_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if is_ready else "not_ready", "checks": check_results},
    )
