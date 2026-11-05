"""Compose app-local API v1 routes from feature-owned router factories."""

from collections.abc import Callable

from fastapi import APIRouter

from app.api.workflows import create_workflow_router
from app.farms.routes import create_crop_catalog_router, create_farm_router
from app.models.users import User
from app.rotation_results.routes import create_rotation_result_router


def create_api_router(current_active_user: Callable[..., User]) -> APIRouter:
    """Build the versioned feature router using this app's NY-11 identity dependency.

    Returning a fresh router for every application avoids mutating one module-level
    router when tests or deployments create multiple FastAPI app instances.
    """

    router = APIRouter()
    router.include_router(create_crop_catalog_router())
    router.include_router(create_farm_router(current_active_user))
    router.include_router(create_rotation_result_router(current_active_user))
    router.include_router(create_workflow_router(current_active_user))
    return router
