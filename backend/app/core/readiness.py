"""Readiness check contracts that feature modules can register with the app."""

from collections.abc import Awaitable, Callable
from typing import TypeAlias

from fastapi import FastAPI

ReadinessCheck: TypeAlias = Callable[[], bool | Awaitable[bool]]


def register_readiness_check(app: FastAPI, name: str, check: ReadinessCheck) -> None:
    """Register a dependency probe on the FastAPI app for the readiness endpoint."""

    checks: dict[str, ReadinessCheck | None] = getattr(app.state, "readiness_checks", {})
    checks[name] = check
    app.state.readiness_checks = checks
