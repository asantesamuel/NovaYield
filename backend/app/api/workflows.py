"""Authenticated orchestration endpoints for persisted environmental context."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.errors import PyMongoError

from app.decisions.crop_evidence import (
    ASSESSMENT_VERSION,
    FarmAssessmentContext,
    build_crop_evidence_option,
)
from app.decisions.crop_profiles import CROP_LIBRARY_VERSION
from app.decisions.rotation import (
    MVP_CROP_CANDIDATES,
    ROTATION_RULE_SET_VERSION,
    CurrentPractice,
    PlantingEventSlot,
    RotationGenerationRequest,
    generate_rotation_candidates,
)
from app.decisions.scoring import (
    ScoringRequest,
    score_rotation_options,
)
from app.farms.routes import get_farm_repository, get_supported_location_repository
from app.indicators.environmental import EnvironmentalIndicator
from app.integrations.nasa.power import PowerRequest
from app.models.farms import Farm
from app.models.rotation_results import RotationDecisionInputs
from app.models.supported_locations import SupportedLocation
from app.models.users import User
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

FARM_NOT_FOUND_DETAIL = "Farm not found."
AUTHENTICATION_REQUIRED_DETAIL = "Authentication is required."
CSRF_VERIFICATION_FAILED_DETAIL = "CSRF token verification failed."
LOCATION_UNAVAILABLE_DETAIL = "Environmental location details are temporarily unavailable."
ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL = "Environmental data is temporarily unavailable."
ROTATION_RESULT_UNAVAILABLE_DETAIL = "The rotation result could not be saved. Please retry."

_PUBLIC_ERROR_CODES = {
    "PowerTimeoutError": "NASA_TIMEOUT",
    "PowerTransportError": "NASA_UNAVAILABLE",
    "PowerHTTPError": "NASA_UPSTREAM_ERROR",
    "PowerMalformedResponseError": "NASA_RESPONSE_INVALID",
    "PowerMissingParameterError": "NASA_RESPONSE_INVALID",
    "PowerUnsupportedUnitsError": "NASA_RESPONSE_INVALID",
    "SnapshotRefreshInProgress": "NASA_RETRIEVAL_IN_PROGRESS",
    "SnapshotRepositoryError": "ENVIRONMENTAL_STORAGE_UNAVAILABLE",
}


@dataclass(frozen=True, slots=True)
class RetrievedEnvironmentalPeriod:
    """One request's normalized snapshot outcome and derived indicators."""

    request: PowerRequest
    retrieval: SnapshotRetrieval
    indicators: tuple[EnvironmentalIndicator, ...]


def get_environmental_snapshot_service(request: Request) -> EnvironmentalSnapshotService:
    """Read the shared NY-6 service created by this app's lifespan."""

    service = getattr(request.app.state, "environmental_snapshot_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL,
        )
    return service


def create_workflow_router(current_active_user: Callable[..., User]) -> APIRouter:
    """Build farm-scoped use cases without moving feature persistence into NY-9."""

    router = APIRouter(prefix="/farms", tags=["decision-workflows"])

    @router.post(
        "/{farm_id}/environmental-context",
        response_model=EnvironmentalContextResponse,
        summary="Retrieve historical NASA POWER indicators for an owned farm",
        responses={
            status.HTTP_401_UNAUTHORIZED: {"description": AUTHENTICATION_REQUIRED_DETAIL},
            status.HTTP_403_FORBIDDEN: {"description": CSRF_VERIFICATION_FAILED_DETAIL},
            status.HTTP_404_NOT_FOUND: {"description": FARM_NOT_FOUND_DETAIL},
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL
            },
        },
    )
    async def environmental_context(
        farm_id: PydanticObjectId,
        request_body: EnvironmentalContextRequest,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
        snapshot_service: Annotated[
            EnvironmentalSnapshotService,
            Depends(get_environmental_snapshot_service),
        ],
    ) -> EnvironmentalContextResponse:
        """Authorize the farm before resolving private coordinates or reading snapshots."""

        farm, location = await _load_owned_farm_and_location(
            farm_id=farm_id,
            owner_user_id=user.id,
            farm_repository=farm_repository,
            location_repository=location_repository,
        )
        period = await _retrieve_environmental_period(
            location=location,
            start_date=request_body.start_date,
            end_date=request_body.end_date,
            snapshot_service=snapshot_service,
            force_refresh=request_body.force_refresh,
        )

        return _environmental_context_response(farm, location, period)

    @router.post(
        "/{farm_id}/rotation-recommendations",
        response_model=RotationResultResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Generate and save a farm-specific rotation comparison",
        responses={
            status.HTTP_401_UNAUTHORIZED: {"description": AUTHENTICATION_REQUIRED_DETAIL},
            status.HTTP_403_FORBIDDEN: {"description": CSRF_VERIFICATION_FAILED_DETAIL},
            status.HTTP_404_NOT_FOUND: {"description": FARM_NOT_FOUND_DETAIL},
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": ROTATION_RESULT_UNAVAILABLE_DETAIL
            },
        },
    )
    async def generate_rotation_recommendation(
        farm_id: PydanticObjectId,
        request_body: RotationRecommendationRequest,
        user: Annotated[User, Depends(current_active_user)],
        farm_repository: Annotated[FarmRepository, Depends(get_farm_repository)],
        location_repository: Annotated[
            SupportedLocationRepository,
            Depends(get_supported_location_repository),
        ],
        snapshot_service: Annotated[
            EnvironmentalSnapshotService,
            Depends(get_environmental_snapshot_service),
        ],
        result_repository: Annotated[
            RotationResultRepository,
            Depends(get_rotation_result_repository),
        ],
    ) -> RotationResultResponse:
        """Analyze farmer-reported past seasons, score transparently, and persist the result."""

        farm, location = await _load_owned_farm_and_location(
            farm_id=farm_id,
            owner_user_id=user.id,
            farm_repository=farm_repository,
            location_repository=location_repository,
        )

        event_slots = tuple(
            PlantingEventSlot(
                event_id=f"future-recommendation-season-{order}",
                order=order,
                plot_id=request_body.plot_reference,
                season_label=slot.season_label,
                window_start=slot.window_start,
                window_end=slot.window_end,
                # User-selected future dates are not a source-reviewed crop calendar.
                calendar_status="unknown",
            )
            for order, slot in enumerate(request_body.recommendation_seasons, start=1)
        )
        environmental_periods: list[RetrievedEnvironmentalPeriod] = []
        for season in request_body.historical_seasons:
            environmental_periods.append(
                await _retrieve_environmental_period(
                    location=location,
                    start_date=season.analysis_start_date,
                    end_date=season.analysis_end_date,
                    season_label=season.season_label,
                    crop=season.planted_crop,
                    snapshot_service=snapshot_service,
                    force_refresh=request_body.force_refresh,
                )
            )

        reported_crops = tuple(season.planted_crop for season in request_body.historical_seasons)
        prior_crop_history = (reported_crops[-1],) if reported_crops[-1] is not None else None
        current_practice = None
        if all(crop_id is not None for crop_id in reported_crops):
            current_practice = CurrentPractice(
                crop_ids=tuple(crop_id for crop_id in reported_crops if crop_id is not None),
                source_reference="Farmer-reported past seasons supplied to NY-9.",
            )

        generation_request = RotationGenerationRequest(
            planting_events=event_slots,
            candidate_crops=MVP_CROP_CANDIDATES,
            sequence_evidence_status="provisional",
            sequence_evidence_source=(
                "Farmer-selected future recommendation slots; calendar continuity is unvalidated."
            ),
            prior_crop_history=prior_crop_history,
            prior_history_source=(
                "Farmer-reported past season history supplied to NY-9."
                if prior_crop_history is not None
                else None
            ),
            current_practice=current_practice,
        )
        generated = generate_rotation_candidates(generation_request)
        all_indicators = tuple(
            indicator for period in environmental_periods for indicator in period.indicators
        )
        environmental_context_ready = all(
            sum(_is_usable_indicator(indicator) for indicator in period.indicators) >= 2
            for period in environmental_periods
        )
        farm_assessment_context = FarmAssessmentContext(
            location_key=farm.location_key,
            soil_texture=farm.soil_texture,
            irrigation_access=farm.irrigation_access,
        )
        scoring_request = ScoringRequest(
            options=tuple(
                build_crop_evidence_option(
                    candidate,
                    all_indicators,
                    farm_context=farm_assessment_context,
                    prior_crop_history=prior_crop_history,
                    environmental_context_ready=environmental_context_ready,
                )
                for candidate in generated.candidates
            ),
            farmer_priorities=farm.farmer_priorities,
        )
        scoring_result = score_rotation_options(scoring_request)
        snapshot_ids = tuple(
            dict.fromkeys(
                period.retrieval.snapshot.id
                for period in environmental_periods
                if period.retrieval.snapshot is not None
                and period.retrieval.snapshot.id is not None
            )
        )
        decision_inputs = RotationDecisionInputs(
            generation_request=generation_request,
            scoring_request=scoring_request,
            environmental_snapshot_ids=snapshot_ids,
            crop_library_version=CROP_LIBRARY_VERSION,
            assessment_version=ASSESSMENT_VERSION,
            rule_set_version=ROTATION_RULE_SET_VERSION,
        )
        try:
            saved = await result_repository.create_for_farm(
                owner_user_id=user.id,
                farm=farm,
                decision_inputs=decision_inputs,
                candidate_generation=generated,
                scoring_result=scoring_result,
            )
        except (PyMongoError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=ROTATION_RESULT_UNAVAILABLE_DETAIL,
            ) from None
        return RotationResultResponse.from_document(saved)

    return router


async def _load_owned_farm_and_location(
    *,
    farm_id: PydanticObjectId,
    owner_user_id: PydanticObjectId,
    farm_repository: FarmRepository,
    location_repository: SupportedLocationRepository,
) -> tuple[Farm, SupportedLocation]:
    """Apply ownership before any location point or environmental lookup."""

    try:
        farm = await farm_repository.get_by_owner(
            farm_id=farm_id,
            owner_user_id=owner_user_id,
        )
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL,
        ) from None
    if farm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=FARM_NOT_FOUND_DETAIL)

    try:
        location = await location_repository.get_by_key(farm.location_key)
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LOCATION_UNAVAILABLE_DETAIL,
        ) from None
    if location is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LOCATION_UNAVAILABLE_DETAIL,
        )
    return farm, location


async def _retrieve_environmental_period(
    *,
    location: SupportedLocation,
    start_date: date,
    end_date: date,
    snapshot_service: EnvironmentalSnapshotService,
    force_refresh: bool,
    season_label: str | None = None,
    crop: str | None = None,
) -> RetrievedEnvironmentalPeriod:
    """Use NY-6's snapshot boundary and NY-7's pure indicator service together."""

    power_request = PowerRequest(
        latitude=location.coordinates.latitude,
        longitude=location.coordinates.longitude,
        start_date=start_date,
        end_date=end_date,
        season_label=season_label,
        crop=crop,
    )
    try:
        retrieval = await snapshot_service.retrieve(
            power_request,
            force_refresh=force_refresh,
        )
    except (PyMongoError, SnapshotRepositoryError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ENVIRONMENTAL_SERVICE_UNAVAILABLE_DETAIL,
        ) from None
    indicators = EnvironmentalIndicatorService().calculate(retrieval, power_request)
    return RetrievedEnvironmentalPeriod(
        request=power_request,
        retrieval=retrieval,
        indicators=indicators,
    )


def _environmental_context_response(
    farm: Farm,
    location: SupportedLocation,
    period: RetrievedEnvironmentalPeriod,
) -> EnvironmentalContextResponse:
    """Serialize only public location data and stable service status values."""

    retrieval = period.retrieval
    error_code = _public_environmental_error_code(retrieval.error_code)
    if retrieval.data_status == "unavailable" and error_code is None:
        error_code = "NO_VALID_DATA"
    return EnvironmentalContextResponse(
        farm_id=str(farm.id),
        location=FarmLocationSummary(
            location_key=farm.location_key,
            label=location.label,
        ),
        period=EnvironmentalPeriodResponse(
            start_date=period.request.start_date,
            end_date=period.request.end_date,
        ),
        data_status=retrieval.data_status,
        cache_action=retrieval.cache_action,
        freshness_status=retrieval.freshness.status,
        freshness_age_seconds=retrieval.freshness.age_seconds,
        freshness_explanation=retrieval.freshness.reason,
        refresh_attempted=retrieval.refresh_attempted,
        error_code=error_code,
        indicators=period.indicators,
        warnings=retrieval.warnings,
    )


def _is_usable_indicator(indicator: EnvironmentalIndicator) -> bool:
    """Count a measured complete/partial value, never an unavailable value, per NY-13."""

    return (
        indicator.value is not None
        and indicator.status != "unavailable"
        and indicator.data_status != "unavailable"
    )


def _public_environmental_error_code(error_code: str | None) -> str | None:
    """Translate internal typed outcomes to stable, client-safe values."""

    if error_code is None:
        return None
    return _PUBLIC_ERROR_CODES.get(error_code, "NASA_UPSTREAM_ERROR")
