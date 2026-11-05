"""HTTP routes for the supported-location catalog and authenticated farm profiles."""

from collections.abc import Callable
from typing import Annotated, Any

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.models.farms import Farm
from app.models.users import User
from app.repositories.farms import FarmRepository, UnsupportedFarmLocation
from app.repositories.supported_locations import SupportedLocationRepository
from app.schemas.farms import (
    FarmCreate,
    FarmResponse,
    FarmUpdate,
    SupportedLocationOption,
    SupportedLocationsResponse,
)

SUPPORTED_LOCATION_COVERAGE_NOTICE = (
    "NovaYield currently supports only the locations listed here. "
    "Coverage has not yet expanded to other parts of Ghana."
)
FARM_NOT_FOUND_DETAIL = "Farm not found."
SUPPORTED_LOCATION_ERROR_DETAIL = "Select a location from the supported locations list."


class FarmSafeValidationRoute(APIRoute):
    """Avoid echoing request bodies in farm validation errors."""

    def get_route_handler(self) -> Callable[..., Any]:
        original_handler = super().get_route_handler()

        async def handle_without_input_echo(request: Request) -> Any:
            try:
                return await original_handler(request)
            except RequestValidationError as error:
                safe_errors = [
                    {key: value for key, value in item.items() if key != "input"}
                    for item in error.errors()
                ]
                raise RequestValidationError(safe_errors, body=None) from error

        return handle_without_input_echo


def get_farm_repository() -> FarmRepository:
    """Build the repository over the Beanie models initialized by the app lifespan."""

    return FarmRepository()


def get_supported_location_repository() -> SupportedLocationRepository:
    """Build the repository for location lookup and farm-response label resolution."""

    return SupportedLocationRepository()


def create_farm_router(current_active_user: Callable[..., User]) -> APIRouter:
    """Create farm routes using the current-user dependency owned by NY-11.

    NY-9 composes this feature router into the versioned API. Keeping this
    factory in the farm package avoids editing the shared app/router files here.
    """

    router = APIRouter(
        prefix="/farms",
        tags=["farms"],
        route_class=FarmSafeValidationRoute,
    )

    # Register the fixed path before /{farm_id}; otherwise "locations" could
    # be consumed as a farm ID by a path matcher that checks routes in order.
    @router.get(
        "/locations",
        response_model=SupportedLocationsResponse,
        summary="List supported farm locations",
    )
    async def list_supported_locations(
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
    ) -> SupportedLocationsResponse:
        """Return selectable labels/keys and the product's limited-coverage notice."""

        locations = await location_repository.list_selectable()
        return SupportedLocationsResponse(
            coverage_notice=SUPPORTED_LOCATION_COVERAGE_NOTICE,
            locations=[SupportedLocationOption.from_document(location) for location in locations],
        )

    @router.post(
        "",
        response_model=FarmResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create an authenticated user's farm profile",
    )
    async def create_farm(
        profile: FarmCreate,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
    ) -> FarmResponse:
        """Set ownership from the auth principal and resolve only a public label."""

        try:
            farm = await farm_repository.create(owner_user_id=user.id, profile=profile)
        except UnsupportedFarmLocation:
            raise _unsupported_location_error() from None
        return await _farm_response(farm, location_repository)

    @router.get(
        "",
        response_model=list[FarmResponse],
        summary="List the authenticated user's farm profiles",
    )
    async def list_farms(
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
    ) -> list[FarmResponse]:
        """Read only the caller's farms and resolve their labels in one catalog query."""

        farms = await farm_repository.list_by_owner(owner_user_id=user.id)
        locations = await location_repository.list_by_keys({farm.location_key for farm in farms})
        labels_by_key = {location.location_key: location.label for location in locations}
        if any(farm.location_key not in labels_by_key for farm in farms):
            raise _missing_catalog_record_error()
        return [
            FarmResponse.from_document(farm, location_label=labels_by_key[farm.location_key])
            for farm in farms
        ]

    @router.get(
        "/{farm_id}",
        response_model=FarmResponse,
        summary="Retrieve one of the authenticated user's farms",
    )
    async def get_farm(
        farm_id: PydanticObjectId,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
    ) -> FarmResponse:
        """Return the same 404 for an unknown farm ID and another user's farm ID."""

        farm = await farm_repository.get_by_owner(farm_id=farm_id, owner_user_id=user.id)
        if farm is None:
            raise _farm_not_found_error()
        return await _farm_response(farm, location_repository)

    @router.patch(
        "/{farm_id}",
        response_model=FarmResponse,
        summary="Update one of the authenticated user's farms",
    )
    async def update_farm(
        farm_id: PydanticObjectId,
        changes: FarmUpdate,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
    ) -> FarmResponse:
        """Apply validated fields through an ID-and-owner constrained repository call."""

        try:
            farm = await farm_repository.update_by_owner(
                farm_id=farm_id,
                owner_user_id=user.id,
                changes=changes,
            )
        except UnsupportedFarmLocation:
            raise _unsupported_location_error() from None
        if farm is None:
            raise _farm_not_found_error()
        return await _farm_response(farm, location_repository)

    return router


async def _farm_response(
    farm: Farm,
    location_repository: SupportedLocationRepository,
) -> FarmResponse:
    """Resolve one label for an API response without serializing the location document."""

    location = await location_repository.get_by_key(farm.location_key)
    if location is None:
        raise _missing_catalog_record_error()
    return FarmResponse.from_document(farm, location_label=location.label)


def _unsupported_location_error() -> HTTPException:
    """Return a stable client-safe error for keys outside the selectable catalog."""

    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=SUPPORTED_LOCATION_ERROR_DETAIL,
    )


def _farm_not_found_error() -> HTTPException:
    """Hide whether a farm exists when it is not owned by the authenticated user."""

    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=FARM_NOT_FOUND_DETAIL)


def _missing_catalog_record_error() -> HTTPException:
    """Report broken internal references without returning stored coordinates."""

    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Farm location details are temporarily unavailable.",
    )
