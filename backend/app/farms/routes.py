"""Public-safe reference catalogs and owner-scoped Farm v2 HTTP routes."""

from collections.abc import Callable
from typing import Annotated, Any, Literal

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from pymongo.errors import PyMongoError

from app.farms.environmental_context import FarmContextService
from app.models.crop_catalog import CROP_IDENTITY_SCHEMA_VERSION
from app.models.farm_reference_options import REFERENCE_SCHEMA_VERSION
from app.models.farms import Farm, FarmEnvironmentalContextState
from app.models.users import User
from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.farm_reference_options import FarmReferenceRepository
from app.repositories.farms import (
    FarmRepository,
    FarmRevisionConflict,
    IncompleteFarmMigration,
    UnsupportedCropProfile,
    UnsupportedFarmLocation,
    UnsupportedFarmReference,
    UnsupportedHistoryCrop,
)
from app.repositories.supported_locations import SupportedLocationRepository
from app.schemas.farms import (
    CropOptionResponse,
    CropOptionsResponse,
    FarmCreate,
    FarmReferenceOptionsResponse,
    FarmResponse,
    FarmUpdate,
    ReferenceOptionResponse,
    SupportedLocationOption,
    SupportedLocationsResponse,
)
from app.services.environmental_snapshots import EnvironmentalSnapshotService

SUPPORTED_LOCATION_COVERAGE_NOTICE = (
    "NovaYield currently supports only the locations listed here. "
    "Coverage has not yet expanded to other parts of Ghana."
)
FARM_NOT_FOUND_DETAIL = "Farm not found."
SUPPORTED_LOCATION_ERROR_DETAIL = "Select a location from the supported locations list."
CATALOG_UNAVAILABLE_DETAIL = "Farm setup options are temporarily unavailable."
FARM_STORAGE_UNAVAILABLE_DETAIL = "Farm data is temporarily unavailable."


class FarmSafeValidationRoute(APIRoute):
    """Do not echo private farm request values in validation responses."""

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
    return FarmRepository()


def get_supported_location_repository() -> SupportedLocationRepository:
    return SupportedLocationRepository()


def get_crop_catalog_repository() -> CropCatalogRepository:
    return CropCatalogRepository()


def get_farm_reference_repository() -> FarmReferenceRepository:
    return FarmReferenceRepository()


def get_optional_snapshot_service(request: Request) -> EnvironmentalSnapshotService | None:
    """Farm creation still succeeds if NASA's app-state service is unavailable."""

    return getattr(request.app.state, "environmental_snapshot_service", None)


def get_farm_context_service() -> FarmContextService:
    return FarmContextService()


def create_crop_catalog_router() -> APIRouter:
    """The same persisted crop identities serve history and candidate consumers."""

    router = APIRouter(prefix="/crops", tags=["crop-catalog"])

    @router.get("", response_model=CropOptionsResponse, summary="List canonical crop options")
    async def list_crops(
        repository: Annotated[CropCatalogRepository, Depends(get_crop_catalog_repository)],
        usage: Literal["history", "recommendation"] | None = None,
    ) -> CropOptionsResponse:
        try:
            crops = await repository.list_crops(usage=usage)
            profiles = await repository.list_active_profiles(
                tuple(crop.id for crop in crops if crop.id is not None)
            )
        except PyMongoError:
            raise _catalog_unavailable_error() from None
        status_by_crop: dict[Any, set[str]] = {}
        for profile in profiles:
            status_by_crop.setdefault(profile.crop_id, set()).add(profile.evidence_status)
        return CropOptionsResponse(
            catalog_version=CROP_IDENTITY_SCHEMA_VERSION,
            crops=[
                CropOptionResponse.from_document(
                    crop,
                    evidence_status=_combined_evidence_status(status_by_crop.get(crop.id, set())),
                )
                for crop in crops
            ],
        )

    return router


def create_farm_router(current_active_user: Callable[..., User]) -> APIRouter:
    """Create routes that rely on NY-11's principal and NY-4's Beanie registry."""

    router = APIRouter(prefix="/farms", tags=["farms"], route_class=FarmSafeValidationRoute)

    # Fixed lookup paths precede /{farm_id} to avoid path matching ambiguity.
    @router.get(
        "/locations",
        response_model=SupportedLocationsResponse,
        summary="List supported farm locations",
    )
    async def list_supported_locations(
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
    ) -> SupportedLocationsResponse:
        try:
            locations = await location_repository.list_selectable()
        except PyMongoError:
            raise _catalog_unavailable_error() from None
        return SupportedLocationsResponse(
            coverage_notice=SUPPORTED_LOCATION_COVERAGE_NOTICE,
            locations=[SupportedLocationOption.from_document(location) for location in locations],
        )

    @router.get(
        "/reference-options",
        response_model=FarmReferenceOptionsResponse,
        summary="List soil and irrigation choices for farm setup",
    )
    async def list_reference_options(
        repository: Annotated[FarmReferenceRepository, Depends(get_farm_reference_repository)],
    ) -> FarmReferenceOptionsResponse:
        try:
            soils = await repository.list_selectable("soil_texture")
            irrigation = await repository.list_selectable("irrigation_access")
        except PyMongoError:
            raise _catalog_unavailable_error() from None
        return FarmReferenceOptionsResponse(
            catalog_version=REFERENCE_SCHEMA_VERSION,
            soil_textures=[ReferenceOptionResponse.from_document(item) for item in soils],
            irrigation_access=[ReferenceOptionResponse.from_document(item) for item in irrigation],
        )

    @router.post(
        "",
        response_model=FarmResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create an owned farm and retrieve its historical NASA context",
    )
    async def create_farm(
        profile: FarmCreate,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
        crop_repository: Annotated[CropCatalogRepository, Depends(get_crop_catalog_repository)],
        reference_repository: Annotated[
            FarmReferenceRepository, Depends(get_farm_reference_repository)
        ],
        context_service: Annotated[FarmContextService, Depends(get_farm_context_service)],
        snapshot_service: Annotated[
            EnvironmentalSnapshotService | None, Depends(get_optional_snapshot_service)
        ],
    ) -> FarmResponse:
        # Resolve every label needed by the 201 response before inserting the
        # Farm. A catalog outage after the insert must not hide a durable farm
        # ID and tempt the client to create a duplicate on retry.
        try:
            location = await location_repository.get_by_key(profile.location_key)
            crops = await crop_repository.list_by_keys(
                {event.crop_key for event in profile.crop_history}
            )
            soil_option = await reference_repository.get_by_key(
                "soil_texture", profile.soil_texture_key
            )
            irrigation_option = await reference_repository.get_by_key(
                "irrigation_access", profile.irrigation_access_key
            )
        except PyMongoError:
            raise _catalog_unavailable_error() from None
        if location is None or not location.is_selectable:
            raise _unsupported_location_error()
        if soil_option is None or not soil_option.selectable:
            raise HTTPException(
                status_code=422, detail=str(UnsupportedFarmReference("soil texture"))
            )
        if irrigation_option is None or not irrigation_option.selectable:
            raise HTTPException(
                status_code=422, detail=str(UnsupportedFarmReference("irrigation access"))
            )
        crops_by_key = {crop.crop_key: crop for crop in crops}
        if any(
            (crop := crops_by_key.get(event.crop_key)) is None
            or crop.catalog_status != "active"
            or not crop.history_selectable
            for event in profile.crop_history
        ):
            raise HTTPException(status_code=422, detail=str(UnsupportedHistoryCrop()))

        try:
            farm = await farm_repository.create(owner_user_id=user.id, profile=profile)
        except UnsupportedFarmLocation:
            raise _unsupported_location_error() from None
        except (UnsupportedFarmReference, UnsupportedHistoryCrop, UnsupportedCropProfile) as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except PyMongoError:
            raise _farm_storage_error() from None

        # Farm is durable before POWER lookup. On timeout/failure, return the
        # saved profile with an honest unavailable/pending context state.
        if farm.environmental_context and farm.environmental_context.status == "pending":
            farm = await context_service.refresh_after_save(
                farm=farm,
                location=location,
                snapshot_service=snapshot_service,
                farm_repository=farm_repository,
            )
        return FarmResponse.from_document(
            farm,
            location_label=location.label,
            crop_labels_by_key={crop.crop_key: crop.common_name for crop in crops},
            soil_option=soil_option,
            irrigation_option=irrigation_option,
        )

    @router.get("", response_model=list[FarmResponse], summary="List owned farm profiles")
    async def list_farms(
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
        crop_repository: Annotated[CropCatalogRepository, Depends(get_crop_catalog_repository)],
        reference_repository: Annotated[
            FarmReferenceRepository, Depends(get_farm_reference_repository)
        ],
    ) -> list[FarmResponse]:
        try:
            farms = await farm_repository.list_by_owner(owner_user_id=user.id)
        except PyMongoError:
            raise _farm_storage_error() from None
        return [
            await _farm_response(farm, location_repository, crop_repository, reference_repository)
            for farm in farms
        ]

    @router.get("/{farm_id}", response_model=FarmResponse, summary="Retrieve an owned farm")
    async def get_farm(
        farm_id: PydanticObjectId,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
        crop_repository: Annotated[CropCatalogRepository, Depends(get_crop_catalog_repository)],
        reference_repository: Annotated[
            FarmReferenceRepository, Depends(get_farm_reference_repository)
        ],
    ) -> FarmResponse:
        try:
            farm = await farm_repository.get_by_owner(farm_id=farm_id, owner_user_id=user.id)
        except PyMongoError:
            raise _farm_storage_error() from None
        if farm is None:
            raise _farm_not_found_error()
        return await _farm_response(
            farm, location_repository, crop_repository, reference_repository
        )

    @router.patch("/{farm_id}", response_model=FarmResponse, summary="Update an owned farm")
    async def update_farm(
        farm_id: PydanticObjectId,
        changes: FarmUpdate,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
        crop_repository: Annotated[CropCatalogRepository, Depends(get_crop_catalog_repository)],
        reference_repository: Annotated[
            FarmReferenceRepository, Depends(get_farm_reference_repository)
        ],
        context_service: Annotated[FarmContextService, Depends(get_farm_context_service)],
        snapshot_service: Annotated[
            EnvironmentalSnapshotService | None, Depends(get_optional_snapshot_service)
        ],
    ) -> FarmResponse:
        try:
            farm = await farm_repository.update_by_owner(
                farm_id=farm_id,
                owner_user_id=user.id,
                changes=changes,
            )
        except FarmRevisionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except UnsupportedFarmLocation:
            raise _unsupported_location_error() from None
        except (
            UnsupportedFarmReference,
            UnsupportedHistoryCrop,
            UnsupportedCropProfile,
            IncompleteFarmMigration,
            ValidationError,
            ValueError,
        ) as error:
            raise HTTPException(
                status_code=422,
                detail=(
                    str(error)
                    if not isinstance(error, ValidationError)
                    else "Farm history or reference choices are invalid."
                ),
            ) from None
        except PyMongoError:
            raise _farm_storage_error() from None
        if farm is None:
            raise _farm_not_found_error()

        if farm.environmental_context and farm.environmental_context.status == "pending":
            try:
                location = await location_repository.get_by_key(farm.location_key)
            except PyMongoError:
                location = None
            if location is None:
                farm = await _set_location_unavailable(farm, farm_repository)
            else:
                farm = await context_service.refresh_after_save(
                    farm=farm,
                    location=location,
                    snapshot_service=snapshot_service,
                    farm_repository=farm_repository,
                )
        return await _farm_response(
            farm, location_repository, crop_repository, reference_repository
        )

    return router


async def _farm_response(
    farm: Farm,
    location_repository: SupportedLocationRepository,
    crop_repository: CropCatalogRepository,
    reference_repository: FarmReferenceRepository,
) -> FarmResponse:
    """Resolve labels without serializing coordinates or private catalog internals."""

    try:
        location = await location_repository.get_by_key(farm.location_key)
        crops = await crop_repository.list_by_keys(
            {event.crop_key_snapshot for event in farm.crop_history}
        )
        soil = (
            await reference_repository.get_by_key("soil_texture", farm.soil_texture_key)
            if farm.soil_texture_key
            else None
        )
        irrigation = (
            await reference_repository.get_by_key("irrigation_access", farm.irrigation_access_key)
            if farm.irrigation_access_key
            else None
        )
    except PyMongoError:
        raise _catalog_unavailable_error() from None
    if location is None:
        raise HTTPException(
            status_code=503, detail="Farm location details are temporarily unavailable."
        )
    if farm.schema_version != "farm-v1" and (
        (farm.soil_texture_key and soil is None)
        or (farm.irrigation_access_key and irrigation is None)
    ):
        raise _catalog_unavailable_error()
    return FarmResponse.from_document(
        farm,
        location_label=location.label,
        crop_labels_by_key={crop.crop_key: crop.common_name for crop in crops},
        soil_option=soil,
        irrigation_option=irrigation,
    )


async def _set_location_unavailable(farm: Farm, repository: FarmRepository) -> Farm:
    context = farm.environmental_context
    if farm.id is None or context is None:
        return farm
    try:
        saved = await repository.set_environmental_context_by_owner(
            farm_id=farm.id,
            owner_user_id=farm.owner_user_id,
            expected_revision=farm.revision,
            context=FarmEnvironmentalContextState(
                status="unavailable",
                period=context.period,
                data_status="unavailable",
                warning_code="LOCATION_UNAVAILABLE",
            ),
        )
    except PyMongoError:
        return farm
    return saved or farm


def _combined_evidence_status(statuses: set[str]) -> str:
    if "conflicted" in statuses:
        return "conflicted"
    if "provisional" in statuses:
        return "provisional"
    if "locally_reviewed" in statuses:
        return "locally_reviewed"
    return "unknown"


def _unsupported_location_error() -> HTTPException:
    return HTTPException(status_code=422, detail=SUPPORTED_LOCATION_ERROR_DETAIL)


def _farm_not_found_error() -> HTTPException:
    return HTTPException(status_code=404, detail=FARM_NOT_FOUND_DETAIL)


def _catalog_unavailable_error() -> HTTPException:
    return HTTPException(status_code=503, detail=CATALOG_UNAVAILABLE_DETAIL)


def _farm_storage_error() -> HTTPException:
    return HTTPException(status_code=503, detail=FARM_STORAGE_UNAVAILABLE_DETAIL)
