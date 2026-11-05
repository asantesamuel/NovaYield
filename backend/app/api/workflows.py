"""Authenticated HTTP composition for saved-farm context and recommendations."""

from collections.abc import Callable
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pymongo.errors import PyMongoError

from app.farms.environmental_context import FarmContextService
from app.farms.routes import (
    get_crop_catalog_repository,
    get_farm_repository,
    get_supported_location_repository,
)
from app.indicators.environmental import EnvironmentalIndicator
from app.integrations.nasa.power import PowerRequest
from app.models.farms import Farm
from app.models.supported_locations import SupportedLocation
from app.models.users import User
from app.repositories.crop_catalog import CropCatalogRepository
from app.repositories.environmental_snapshots import SnapshotRepositoryError
from app.repositories.farms import FarmRepository
from app.repositories.rotation_results import RotationResultRepository
from app.repositories.supported_locations import SupportedLocationRepository
from app.rotation_results.routes import get_rotation_result_repository
from app.schemas.decision_workflows import (
    EnvironmentalContextRequest,
    EnvironmentalContextResponse,
    EnvironmentalPeriodResponse,
    RotationRecommendationRequest,
)
from app.schemas.farms import FarmLocationSummary
from app.schemas.rotation_results import RotationResultResponse
from app.services.environmental_indicators import EnvironmentalIndicatorService
from app.services.environmental_snapshots import EnvironmentalSnapshotService, SnapshotRetrieval
from app.services.recommendation_workflow import (
    CropCatalogNotReady,
    FarmChangedDuringGeneration,
    FarmHistoryNeedsReview,
    create_rotation_result_for_owned_farm,
)

FARM_NOT_FOUND_DETAIL = "Farm not found."
AUTHENTICATION_REQUIRED_DETAIL = "Authentication is required."
CSRF_VERIFICATION_FAILED_DETAIL = "CSRF token verification failed."
FARM_HISTORY_NEEDS_REVIEW_DETAIL = (
    "Complete the dated crop history for this farm before requesting environmental "
    "context or a rotation comparison."
)
LOCATION_UNAVAILABLE_DETAIL = "Environmental location details are temporarily unavailable."
ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL = "Environmental data is temporarily unavailable."
ROTATION_RESULT_UNAVAILABLE_DETAIL = "The rotation result could not be saved. Please retry."
CATALOG_UNAVAILABLE_DETAIL = "The crop catalog is temporarily unavailable."

_PUBLIC_ERROR_CODES = {
    "PowerTimeoutError": "NASA_TIMEOUT",
    "PowerTransportError": "NASA_UNAVAILABLE",
    "PowerHTTPError": "NASA_UPSTREAM_ERROR",
    "PowerMalformedResponseError": "NASA_RESPONSE_INVALID",
    "PowerMissingParameterError": "NASA_RESPONSE_INVALID",
    "PowerUnsupportedUnitsError": "NASA_RESPONSE_INVALID",
    "SnapshotRefreshInProgress": "NASA_RETRIEVAL_IN_PROGRESS",
    "SnapshotRepositoryError": "ENVIRONMENTAL_STORAGE_UNAVAILABLE",
    "NASA_SERVICE_UNAVAILABLE": "NASA_UNAVAILABLE",
    "NASA_NO_VALID_DATA": "NO_VALID_DATA",
    "CONTEXT_PERIOD_UNSUPPORTED": "NO_VALID_DATA",
    "NASA_PARTIAL_COVERAGE": None,
}


def get_environmental_snapshot_service(request: Request) -> EnvironmentalSnapshotService:
    """Use the one NY-6 service attached to this app's lifespan."""

    service = getattr(request.app.state, "environmental_snapshot_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL,
        )
    return service


def create_workflow_router(current_active_user: Callable[..., User]) -> APIRouter:
    """Mount thin routes; feature services retain their own persistence rules."""

    router = APIRouter(prefix="/farms", tags=["decision-workflows"])

    @router.post(
        "/{farm_id}/environmental-context",
        response_model=EnvironmentalContextResponse,
        summary="Retrieve or refresh the saved farm's derived NASA POWER context",
        responses={
            401: {"description": AUTHENTICATION_REQUIRED_DETAIL},
            403: {"description": CSRF_VERIFICATION_FAILED_DETAIL},
            404: {"description": FARM_NOT_FOUND_DETAIL},
            409: {"description": FARM_HISTORY_NEEDS_REVIEW_DETAIL},
            503: {"description": ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL},
        },
    )
    async def environmental_context(
        farm_id: PydanticObjectId,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
        snapshot_service: Annotated[
            EnvironmentalSnapshotService, Depends(get_environmental_snapshot_service)
        ],
        request_body: Annotated[EnvironmentalContextRequest | None, Body()] = None,
    ) -> EnvironmentalContextResponse:
        """Authorize before resolving the private place point or NY-6 identity."""

        farm, location = await _load_owned_farm_and_location(
            farm_id=farm_id,
            owner_user_id=user.id,
            farm_repository=farm_repository,
            location_repository=location_repository,
        )
        if (
            farm.schema_version != "farm-v2"
            or farm.history_status != "complete"
            or farm.environmental_context is None
            or farm.environmental_context.period is None
        ):
            raise HTTPException(status_code=409, detail=FARM_HISTORY_NEEDS_REVIEW_DETAIL)
        original_period = farm.environmental_context.period
        original_revision = farm.revision
        farm, retrieval = await FarmContextService().retrieve_for_owned_farm(
            farm=farm,
            location=location,
            snapshot_service=snapshot_service,
            farm_repository=farm_repository,
            force_refresh=(request_body.force_refresh if request_body else False),
        )
        # A concurrent Farm edit may have changed the period while NASA was in
        # flight. Never present old data as the new profile's context.
        if (
            farm.revision != original_revision
            or farm.location_key != location.location_key
            or farm.environmental_context is None
            or farm.environmental_context.period != original_period
        ):
            raise HTTPException(
                status_code=409,
                detail="The farm changed while environmental data was loading. Please retry.",
            )
        return _environmental_context_response(farm, location, retrieval)

    @router.post(
        "/{farm_id}/rotation-recommendations",
        response_model=RotationResultResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Generate and save a provisional rotation assessment for an owned farm",
        responses={
            401: {"description": AUTHENTICATION_REQUIRED_DETAIL},
            403: {"description": CSRF_VERIFICATION_FAILED_DETAIL},
            404: {"description": FARM_NOT_FOUND_DETAIL},
            409: {"description": FARM_HISTORY_NEEDS_REVIEW_DETAIL},
            503: {"description": ROTATION_RESULT_UNAVAILABLE_DETAIL},
        },
    )
    async def generate_rotation_recommendation(
        farm_id: PydanticObjectId,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository, Depends(get_supported_location_repository)
        ],
        catalog_repository: Annotated[CropCatalogRepository, Depends(get_crop_catalog_repository)],
        snapshot_service: Annotated[
            EnvironmentalSnapshotService, Depends(get_environmental_snapshot_service)
        ],
        result_repository: Annotated[
            RotationResultRepository, Depends(get_rotation_result_repository)
        ],
        request_body: Annotated[RotationRecommendationRequest | None, Body()] = None,
    ) -> RotationResultResponse:
        """Use saved history/context/catalog; only priority points may be overridden."""

        farm, location = await _load_owned_farm_and_location(
            farm_id=farm_id,
            owner_user_id=user.id,
            farm_repository=farm_repository,
            location_repository=location_repository,
        )
        try:
            result = await create_rotation_result_for_owned_farm(
                farm=farm,
                location=location,
                owner_user_id=user.id,
                farm_repository=farm_repository,
                catalog_repository=catalog_repository,
                snapshot_service=snapshot_service,
                result_repository=result_repository,
                priority_adjustment=(request_body.priority_adjustment if request_body else None),
            )
        except FarmHistoryNeedsReview:
            raise HTTPException(status_code=409, detail=FARM_HISTORY_NEEDS_REVIEW_DETAIL) from None
        except FarmChangedDuringGeneration:
            raise HTTPException(
                status_code=409,
                detail="The farm changed while this assessment was running. Please retry.",
            ) from None
        except CropCatalogNotReady:
            raise HTTPException(status_code=503, detail=CATALOG_UNAVAILABLE_DETAIL) from None
        except (PyMongoError, SnapshotRepositoryError):
            raise HTTPException(
                status_code=503, detail=ROTATION_RESULT_UNAVAILABLE_DETAIL
            ) from None
        return RotationResultResponse.from_document(result)

    return router


async def _load_owned_farm_and_location(
    *,
    farm_id: PydanticObjectId,
    owner_user_id: PydanticObjectId,
    farm_repository: FarmRepository,
    location_repository: SupportedLocationRepository,
) -> tuple[Farm, SupportedLocation]:
    """The owner filter runs before any private location or environmental lookup."""

    try:
        farm = await farm_repository.get_by_owner(farm_id=farm_id, owner_user_id=owner_user_id)
    except PyMongoError:
        raise HTTPException(
            status_code=503, detail=ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL
        ) from None
    if farm is None:
        raise HTTPException(status_code=404, detail=FARM_NOT_FOUND_DETAIL)
    try:
        location = await location_repository.get_by_key(farm.location_key)
    except PyMongoError:
        raise HTTPException(status_code=503, detail=LOCATION_UNAVAILABLE_DETAIL) from None
    if location is None:
        raise HTTPException(status_code=503, detail=LOCATION_UNAVAILABLE_DETAIL)
    return farm, location


def _environmental_context_response(
    farm: Farm,
    location: SupportedLocation,
    retrieval: SnapshotRetrieval | None,
) -> EnvironmentalContextResponse:
    """Serialize only public location labels and stable NASA result metadata."""

    context = farm.environmental_context
    if context is None or context.period is None or farm.id is None:
        raise ValueError("A complete Farm context is required for serialization")
    period = context.period
    indicators: tuple[EnvironmentalIndicator, ...] = ()
    if retrieval is not None:
        power_request = PowerRequest(
            latitude=location.coordinates.latitude,
            longitude=location.coordinates.longitude,
            start_date=period.start_date,
            end_date=period.end_date,
        )
        indicators = EnvironmentalIndicatorService().calculate(retrieval, power_request)
    snapshot_id = (
        str(retrieval.snapshot.id)
        if retrieval is not None and retrieval.snapshot is not None and retrieval.snapshot.id
        else str(context.snapshot_id)
        if context.snapshot_id is not None
        else None
    )
    error_code = _public_environmental_error_code(
        retrieval.error_code if retrieval is not None else context.warning_code
    )
    if retrieval is not None and retrieval.data_status == "unavailable" and error_code is None:
        error_code = "NO_VALID_DATA"
    return EnvironmentalContextResponse(
        farm_id=str(farm.id),
        location=FarmLocationSummary(location_key=farm.location_key, label=location.label),
        period=EnvironmentalPeriodResponse(
            start_date=period.start_date,
            end_date=period.end_date,
            policy_version=period.policy_version,
        ),
        context_status=(
            context.status if context.status in {"pending", "ready", "partial"} else "unavailable"
        ),
        snapshot_id=snapshot_id,
        data_status=retrieval.data_status if retrieval is not None else "unavailable",
        cache_action=retrieval.cache_action if retrieval is not None else "unavailable",
        freshness_status=(retrieval.freshness.status if retrieval is not None else "unknown"),
        freshness_age_seconds=(retrieval.freshness.age_seconds if retrieval is not None else None),
        freshness_explanation=(
            retrieval.freshness.reason
            if retrieval is not None
            else "No usable NASA POWER snapshot is linked to this farm yet."
        ),
        refresh_attempted=retrieval.refresh_attempted if retrieval is not None else False,
        error_code=error_code,
        indicators=indicators,
        warnings=retrieval.warnings if retrieval is not None else (),
    )


def _public_environmental_error_code(error_code: str | None) -> str | None:
    if error_code is None:
        return None
    if error_code in _PUBLIC_ERROR_CODES:
        return _PUBLIC_ERROR_CODES[error_code]
    if error_code in _PUBLIC_ERROR_CODES.values():
        return error_code
    return "NASA_UPSTREAM_ERROR"
