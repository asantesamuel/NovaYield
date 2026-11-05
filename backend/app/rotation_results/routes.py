"""Authenticated, farm-scoped read routes for saved rotation results."""

from collections.abc import Callable
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.farms.routes import get_farm_repository
from app.models.users import User
from app.repositories.farms import FarmRepository
from app.repositories.rotation_results import RotationResultRepository
from app.schemas.rotation_results import RotationResultResponse

FARM_NOT_FOUND_DETAIL = "Farm not found."
ROTATION_RESULT_NOT_FOUND_DETAIL = "Rotation result not found."


def get_rotation_result_repository() -> RotationResultRepository:
    """Build a repository over the Beanie model initialized by the app lifespan."""

    return RotationResultRepository()


def create_rotation_result_router(current_active_user: Callable[..., User]) -> APIRouter:
    """Create result read routes using NY-11 identity and NY-19 farm ownership."""

    router = APIRouter(prefix="/farms", tags=["rotation-results"])

    @router.get(
        "/{farm_id}/rotation-results",
        response_model=list[RotationResultResponse],
        summary="List saved rotation results for an owned farm",
    )
    async def list_rotation_results(
        farm_id: PydanticObjectId,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        result_repository: Annotated[
            RotationResultRepository,
            Depends(get_rotation_result_repository),
        ],
    ) -> list[RotationResultResponse]:
        """Check farm ownership before listing with both owner and farm filters."""

        farm = await farm_repository.get_by_owner(
            farm_id=farm_id,
            owner_user_id=user.id,
        )
        if farm is None:
            raise _farm_not_found_error()

        results = await result_repository.list_by_owner_and_farm(
            owner_user_id=user.id,
            farm_id=farm_id,
        )
        return [RotationResultResponse.from_document(result) for result in results]

    @router.get(
        "/{farm_id}/rotation-results/{result_id}",
        response_model=RotationResultResponse,
        summary="Retrieve one saved rotation result for an owned farm",
    )
    async def get_rotation_result(
        farm_id: PydanticObjectId,
        result_id: PydanticObjectId,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        result_repository: Annotated[
            RotationResultRepository,
            Depends(get_rotation_result_repository),
        ],
    ) -> RotationResultResponse:
        """Require ownership of the farm and constrain the result query by all IDs."""

        farm = await farm_repository.get_by_owner(
            farm_id=farm_id,
            owner_user_id=user.id,
        )
        if farm is None:
            raise _farm_not_found_error()

        result = await result_repository.get_by_owner_farm_and_id(
            owner_user_id=user.id,
            farm_id=farm_id,
            result_id=result_id,
        )
        if result is None:
            raise _rotation_result_not_found_error()
        return RotationResultResponse.from_document(result)

    return router


def _farm_not_found_error() -> HTTPException:
    """Return one response for missing and non-owned farms."""

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=FARM_NOT_FOUND_DETAIL,
    )


def _rotation_result_not_found_error() -> HTTPException:
    """Avoid revealing whether an ID refers to another farm or owner."""

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ROTATION_RESULT_NOT_FOUND_DETAIL,
    )
