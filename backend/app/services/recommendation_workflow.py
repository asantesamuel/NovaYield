"""NY-40 orchestration from one owned Farm to one saved, explainable result.

Mongo and NASA access stays here and in existing repositories/services. Calendar,
CDD and scoring functions receive versioned values and perform no I/O.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from beanie import PydanticObjectId

from app.decisions.climate_features import (
    CDD_METHOD_VERSION,
    MatchedCropExposure,
    StageCDDExposure,
    StageCDDRequest,
    calculate_stage_cdd_exposure,
)
from app.decisions.crop_evidence import (
    ASSESSMENT_VERSION,
    FarmAssessmentContext,
    build_crop_evidence_option,
)
from app.decisions.crop_profiles import CropProfile
from app.decisions.future_calendar import (
    FUTURE_CALENDAR_METHOD_VERSION,
    CropCalendarSpec,
    CropEventScope,
    FutureRotationSchedule,
    derive_three_event_windows,
)
from app.decisions.rotation import (
    ROTATION_GENERATOR_VERSION,
    ROTATION_RULE_SET_VERSION,
    CandidatePlantingEvent,
    CandidateRuleFinding,
    CropCandidate,
    PlantingEventSlot,
    RotationCandidate,
    RotationGenerationRequest,
    RotationGenerationResult,
    generate_rotation_candidates,
)
from app.decisions.scoring import (
    SCORING_VERSION,
    PriorityPoints,
    ScoringRequest,
    score_rotation_options,
)
from app.farms.context_window import DerivedContextPeriod
from app.farms.environmental_context import FarmContextService
from app.indicators.environmental import EnvironmentalIndicator
from app.integrations.nasa.power import PowerParameterSeries, PowerRequest
from app.models.crop_catalog import (
    CROP_IDENTITY_SCHEMA_VERSION,
    CropCalendar,
    CropProfileRevision,
    EvidenceValue,
    GrowthStage,
)
from app.models.farms import Farm
from app.models.rotation_results import (
    FutureWindowSummary,
    ParameterProvenance,
    RotationDecisionInputs,
    RotationResult,
    SnapshotUseProvenance,
)
from app.models.supported_locations import SupportedLocation
from app.repositories.crop_catalog import CropCandidateBundle, CropCatalogRepository
from app.repositories.farms import FarmRepository
from app.repositories.rotation_results import RotationResultRepository
from app.services.environmental_indicators import EnvironmentalIndicatorService
from app.services.environmental_snapshots import EnvironmentalSnapshotService, SnapshotRetrieval

CLIMATE_REFERENCE_START = date(1991, 1, 1)
CLIMATE_REFERENCE_END = date(2020, 12, 31)


class FarmHistoryNeedsReview(ValueError):
    """A legacy, partial or unknown history cannot support sequential decisions."""


class CropCatalogNotReady(ValueError):
    """The canonical candidate catalog is empty or lacks persisted identities."""


class FarmChangedDuringGeneration(ValueError):
    """The plot changed after this run loaded its history/context."""


@dataclass(frozen=True, slots=True)
class CandidateCatalog:
    candidates: tuple[CropCandidate, ...]
    bundles_by_key: dict[str, CropCandidateBundle]
    profile_by_id: dict[str, CropProfileRevision]
    calendar_specs: tuple[CropCalendarSpec, ...]
    assessment_profiles: dict[str, CropProfile | None]


def _calendar_spec(
    calendar: CropCalendar,
    crop_key: str,
    profile_by_id: dict[str, CropProfileRevision],
) -> CropCalendarSpec:
    """Map a stored scoped revision without inheriting another variety's timing."""

    profile = (
        profile_by_id.get(str(calendar.profile_revision_id))
        if calendar.profile_revision_id is not None
        else None
    )
    maturity = profile.maturity_days if profile is not None else None
    maturity_range = maturity.value if maturity is not None else None
    # A source's maturity number is not a plot-release date unless its endpoint
    # is explicitly *planting to harvest*. Days to physiological maturity or
    # emergence must never be silently substituted for that span.
    maturity_verified = bool(
        maturity_range
        and maturity_range.endpoint_verified
        and maturity_range.meaning.strip().casefold().replace(" ", "_") == "planting_to_harvest"
    )
    planting_window = calendar.planting_window
    calendar_status = _weaker_evidence_status(
        calendar.status,
        calendar.evidence.validation_status if calendar.evidence is not None else "unknown",
    )
    maturity_status = (
        _weaker_evidence_status(profile.evidence_status, maturity.source.validation_status)
        if profile is not None and maturity is not None
        else "unknown"
    )
    return CropCalendarSpec(
        location_key=calendar.location_key,
        crop_id=crop_key,
        variety_key=profile.variety_key if profile is not None else None,
        production_system_key=(profile.production_system_key if profile is not None else None),
        season_key=calendar.season_key,
        start_month_day=(planting_window.start_month_day if planting_window else None),
        end_month_day=(planting_window.end_month_day if planting_window else None),
        crosses_year=(planting_window.crosses_year if planting_window else None),
        valid_from_year=(planting_window.valid_from_year if planting_window else None),
        valid_to_year=(planting_window.valid_to_year if planting_window else None),
        calendar_version_id=str(calendar.id) if calendar.id is not None else None,
        profile_revision_id=str(profile.id) if profile is not None and profile.id else None,
        calendar_source=(calendar.evidence.source_url if calendar.evidence else None),
        maturity_source=(maturity.source.source_url if maturity else None),
        calendar_status=calendar_status,
        maturity_status=maturity_status,
        maturity_basis="planting_to_harvest" if maturity_verified else "unknown",
        maturity_min_days=maturity_range.min_days if maturity_verified else None,
        maturity_max_days=maturity_range.max_days if maturity_verified else None,
    )


def _weaker_evidence_status(*statuses: str) -> str:
    """A derived claim cannot be more certain than any of its cited inputs."""

    for status in ("conflicted", "unknown", "provisional"):
        if status in statuses:
            return status
    return "locally_reviewed"


def _catalog_from_bundles(bundles: list[CropCandidateBundle]) -> CandidateCatalog:
    """Use canonical Mongo identities; static NY-8 candidate/profile defaults are bypassed."""

    if not bundles or any(bundle.crop.id is None for bundle in bundles):
        raise CropCatalogNotReady("The canonical crop catalog is not ready")
    candidates: list[CropCandidate] = []
    profile_by_id: dict[str, CropProfileRevision] = {}
    assessment_profiles: dict[str, CropProfile | None] = {}
    calendar_specs: list[CropCalendarSpec] = []
    for bundle in bundles:
        crop = bundle.crop
        candidates.append(
            CropCandidate(
                crop_id=crop.crop_key,
                display_name=crop.common_name,
                # Catalog membership is not farm suitability.
                suitability_status="unknown",
                evidence_references=(crop.identity_source_url,) if crop.identity_source_url else (),
            )
        )
        for profile in bundle.active_profiles:
            if profile.id is not None:
                profile_by_id[str(profile.id)] = profile
        generic_profile = next(
            (
                profile
                for profile in bundle.active_profiles
                if profile.variety_key is None and profile.production_system_key is None
            ),
            None,
        )
        assessment_profiles[crop.crop_key] = (
            CropProfile(
                crop_id=crop.crop_key,
                common_name=crop.common_name,
                scientific_name=crop.scientific_name,
                crop_family=crop.family,
                identity_source_reference=(crop.identity_source_url or "NY-38 crop catalog"),
                # The approved seed has no comparable qualitative class. Scoped
                # traits cannot be promoted from a crop name or family.
                traits=(),
            )
            if generic_profile is not None
            else None
        )
    for bundle in bundles:
        for calendar in bundle.calendars:
            calendar_specs.append(_calendar_spec(calendar, bundle.crop.crop_key, profile_by_id))
    return CandidateCatalog(
        candidates=tuple(candidates),
        bundles_by_key={bundle.crop.crop_key: bundle for bundle in bundles},
        profile_by_id=profile_by_id,
        calendar_specs=tuple(calendar_specs),
        assessment_profiles=assessment_profiles,
    )


def _scheduled_candidate(
    candidate: RotationCandidate,
    schedule: FutureRotationSchedule,
) -> RotationCandidate:
    """Attach crop-specific sourced windows to an enumerated crop sequence."""

    events: list[CandidatePlantingEvent] = []
    for old, future in zip(candidate.events, schedule.events, strict=True):
        calendar_status = (
            "locally_validated"
            if future.status == "locally_reviewed"
            else "provisional"
            if future.status == "provisional"
            else "unknown"
        )
        slot = PlantingEventSlot(
            event_id=future.event_id,
            order=future.order,
            plot_id=future.plot_id,
            season_label=future.season_key or f"Future event {future.order}",
            window_start=future.planting_window_start,
            window_end=future.planting_window_end,
            harvest_start=future.earliest_harvest_date,
            harvest_end=future.latest_harvest_date,
            maturity_days_min=future.maturity_min_days,
            maturity_days_max=future.maturity_max_days,
            variety_key=future.crop.variety_key,
            production_system_key=future.crop.production_system_key,
            profile_revision_id=future.profile_revision_id,
            calendar_version_id=future.calendar_version_id,
            calendar_status=calendar_status,
            calendar_source=future.calendar_source,
            calendar_source_version=future.calendar_version_id,
            review_reasons=(future.reason,) if future.reason else future.limitations,
        )
        events.append(CandidatePlantingEvent(event=slot, crop=old.crop))
    findings = tuple(item for item in candidate.rule_findings if item.rule_id != "ROT-003") + (
        CandidateRuleFinding(
            rule_id="NY40-CALENDAR",
            outcome="passed" if schedule.status == "locally_reviewed" else "needs_review",
            explanation=(
                "All three event windows have locally reviewed crop calendar and maturity evidence."
                if schedule.status == "locally_reviewed"
                else "One or more future windows are provisional or cannot be dated from scoped "
                "crop calendar, maturity, and plot-availability evidence."
            ),
            evidence_references=tuple(
                dict.fromkeys(
                    event.calendar_source
                    for event in schedule.events
                    if event.calendar_source is not None
                )
            )
            or ("NY-38 approved calendar policy",),
        ),
    )
    return candidate.model_copy(
        update={
            "events": (events[0], events[1], events[2]),
            "readiness": (
                "needs_review"
                if schedule.status != "locally_reviewed"
                or any(item.outcome == "needs_review" for item in findings)
                else "structurally_valid"
            ),
            "rule_findings": findings,
        }
    )


def _generate_scheduled_candidates(
    farm: Farm,
    catalog: CandidateCatalog,
    *,
    as_of_date: date,
) -> tuple[RotationGenerationRequest, RotationGenerationResult, FutureWindowSummary]:
    if farm.id is None:
        raise ValueError("The owned farm must be persisted")
    history = tuple(event.crop_key_snapshot for event in farm.crop_history)
    request = RotationGenerationRequest(
        planting_events=tuple(
            PlantingEventSlot(
                event_id=f"future-{order}",
                order=order,
                plot_id=str(farm.id),
                season_label=f"Future event {order}",
            )
            for order in (1, 2, 3)
        ),
        as_of_date=as_of_date,
        candidate_crops=catalog.candidates,
        sequence_evidence_status="provisional",
        sequence_evidence_source="Farmer-reported, ordered history on this one Farm plot.",
        prior_crop_history=history,
        prior_history_source="Saved Farm crop-history events and canonical crop references.",
        current_practice=None,
    )
    generated = generate_rotation_candidates(request)
    scheduled: list[RotationCandidate] = []
    reasons: Counter[str] = Counter()
    fully_scheduled_count = 0
    needs_review_count = 0
    for candidate in generated.candidates:
        schedule = derive_three_event_windows(
            tuple(CropEventScope(crop_id=event.crop.crop_id) for event in candidate.events),
            catalog.calendar_specs,
            location_key=farm.location_key,
            plot_id=str(farm.id),
            as_of_date=as_of_date,
            earliest_available_date=(
                farm.earliest_available_date if farm.current_plot_available is True else None
            ),
            availability_source=(
                "farmer_reported" if farm.current_plot_available is True else None
            ),
        )
        for event in schedule.events:
            if event.reason:
                reasons[event.reason] += 1
        if all(
            event.planting_window_start is not None and event.latest_harvest_date is not None
            for event in schedule.events
        ):
            fully_scheduled_count += 1
        if schedule.status != "locally_reviewed":
            needs_review_count += 1
            if schedule.status == "provisional":
                reasons["provisional_calendar_requires_local_review"] += 1
        scheduled.append(_scheduled_candidate(candidate, schedule))
    result = RotationGenerationResult(
        generator_version=ROTATION_GENERATOR_VERSION,
        readiness=(
            "needs_review"
            if any(item.readiness == "needs_review" for item in scheduled)
            else "structurally_valid"
        ),
        candidates=tuple(scheduled),
    )
    summary = FutureWindowSummary(
        candidate_count=len(scheduled),
        fully_scheduled_count=fully_scheduled_count,
        needs_review_count=needs_review_count,
        review_reasons=tuple(sorted(reasons)),
    )
    return request, result, summary


def _days_range(value: EvidenceValue | None) -> tuple[int | None, int | None]:
    if value is None or value.unit != "days":
        return None, None
    minimum, maximum = value.value.get("min_days"), value.value.get("max_days")
    if isinstance(minimum, int) and isinstance(maximum, int):
        return minimum, maximum
    return None, None


def _water_sensitive_stage(stage: GrowthStage) -> bool:
    """Only an explicitly sourced water-shortage-sensitive stage uses rainfall CDD."""

    sensitivity = stage.sensitivity
    return bool(
        sensitivity is not None
        and sensitivity.value.get("factor") == "water_shortage"
        and sensitivity.value.get("direction") == "sensitive"
    )


def _stage_sources_resolved(stage: GrowthStage) -> bool:
    values = (stage.start_offset_days, stage.duration_days, stage.sensitivity)
    return all(
        value is not None
        and value.source.source_url
        and value.source.validation_status in {"provisional", "locally_reviewed"}
        for value in values
    )


def _stages_with_timing(profile: CropProfileRevision | None, maturity_min_days: int | None) -> bool:
    if (
        profile is None
        or profile.evidence_status not in {"provisional", "locally_reviewed"}
        or maturity_min_days is None
    ):
        return False
    for stage in profile.growth_stages:
        if not _water_sensitive_stage(stage) or not _stage_sources_resolved(stage):
            continue
        offset_min, offset_max = _days_range(stage.start_offset_days)
        duration_min, duration_max = _days_range(stage.duration_days)
        if (
            offset_min is not None
            and offset_max is not None
            and duration_min is not None
            and duration_max is not None
            and 0 <= offset_min <= offset_max
            and 1 <= duration_min <= duration_max
            and offset_max + duration_max <= maturity_min_days
        ):
            return True
    return False


def _candidate_stage_exposures(
    candidate: RotationCandidate,
    catalog: CandidateCatalog,
    reference: SnapshotRetrieval | None,
    cache: dict[str, StageCDDExposure],
) -> tuple[MatchedCropExposure, ...]:
    """Calculate only sourced stages; compact audit records avoid duplicating 30-year runs."""

    snapshot = reference.snapshot if reference is not None else None
    precipitation: PowerParameterSeries | None = (
        snapshot.parameters.get("PRECTOTCORR") if snapshot is not None else None
    )
    occurrences: Counter[tuple[str, str | None, str | None, str]] = Counter()
    exposures: list[MatchedCropExposure] = []
    for item in candidate.events:
        event = item.event
        profile = (
            catalog.profile_by_id.get(event.profile_revision_id)
            if event.profile_revision_id is not None
            else None
        )
        if profile is None:
            continue
        for stage in profile.growth_stages:
            if not _water_sensitive_stage(stage):
                continue
            assert stage.sensitivity is not None
            offset_min, offset_max = _days_range(stage.start_offset_days)
            duration_min, duration_max = _days_range(stage.duration_days)
            maturity = profile.maturity_days
            request = StageCDDRequest(
                crop_id=item.crop.crop_id,
                variety_key=event.variety_key,
                production_system_key=event.production_system_key,
                stage_key=stage.stage_key,
                planting_window_start=event.window_start,
                planting_window_end=event.window_end,
                stage_offset_min_days=offset_min,
                stage_offset_max_days=offset_max,
                stage_duration_min_days=duration_min,
                stage_duration_max_days=duration_max,
                maturity_min_days=event.maturity_days_min,
                maturity_max_days=event.maturity_days_max,
                profile_revision_id=event.profile_revision_id,
                calendar_version_id=event.calendar_version_id,
                calendar_source=event.calendar_source,
                stage_source=(
                    stage.start_offset_days.source.source_url
                    if stage.start_offset_days is not None
                    else None
                ),
                sensitivity_source=stage.sensitivity.source.source_url,
                maturity_source=maturity.source.source_url if maturity is not None else None,
                evidence_status=_weaker_evidence_status(
                    profile.evidence_status,
                    stage.start_offset_days.source.validation_status
                    if stage.start_offset_days is not None
                    else "unknown",
                    stage.duration_days.source.validation_status
                    if stage.duration_days is not None
                    else "unknown",
                    stage.sensitivity.source.validation_status,
                    event.calendar_status,
                ),
                source_snapshot_id=(
                    str(snapshot.id) if snapshot is not None and snapshot.id else None
                ),
                source_products=(
                    tuple(snapshot.provider_metadata.source_products)
                    if snapshot is not None
                    else ()
                ),
                snapshot_retrieved_at=(snapshot.retrieved_at if snapshot is not None else None),
                snapshot_status=(reference.data_status if reference is not None else "unavailable"),
            )
            # Permutations reuse the same crop/stage/window many times. Keep
            # exact feature results for this one request, keyed by all sourced
            # inputs; never reuse them across different snapshots or requests.
            cache_key = request.model_dump_json()
            compact = cache.get(cache_key)
            if compact is None:
                calculated = calculate_stage_cdd_exposure(request, precipitation)
                # Per-placement annual values are reproducible from the pinned
                # snapshot and method version; do not multiply them into every result.
                compact = calculated.model_copy(update={"placements": ()})
                cache[cache_key] = compact
            scope = (
                compact.crop_id,
                compact.variety_key,
                compact.production_system_key,
                compact.stage_key,
            )
            occurrences[scope] += 1
            exposures.append(
                MatchedCropExposure(
                    exposure=compact,
                    occurrence_index=occurrences[scope],
                    event_order=event.order,
                )
            )
    return tuple(exposures)


def _has_possible_climate_stage(
    candidates: RotationGenerationResult,
    catalog: CandidateCatalog,
) -> bool:
    return any(
        item.event.window_start is not None
        and item.event.window_end is not None
        and item.event.maturity_days_min is not None
        and item.event.profile_revision_id is not None
        and item.event.calendar_version_id is not None
        and item.event.calendar_source is not None
        and item.event.calendar_status in {"provisional", "locally_validated"}
        and _stages_with_timing(
            catalog.profile_by_id.get(item.event.profile_revision_id),
            item.event.maturity_days_min,
        )
        for candidate in candidates.candidates
        for item in candidate.events
    )


def _indicator_usable(indicator: EnvironmentalIndicator) -> bool:
    return (
        indicator.value is not None
        # A partial series remains visible, but sparse data is not a verified
        # decision input without an approved coverage threshold.
        and indicator.status == "complete"
        and indicator.data_status != "unavailable"
    )


def _snapshot_provenance(
    retrieval: SnapshotRetrieval | None,
    *,
    start_date: date,
    end_date: date,
) -> SnapshotUseProvenance:
    snapshot = retrieval.snapshot if retrieval is not None else None
    parameters = (
        tuple(
            ParameterProvenance(
                code=code,
                units=series.metadata.normalized_units,
                source=series.metadata.source,
                spatial_resolution=series.metadata.spatial_resolution,
                expected_days=series.seasonal_summary.coverage.expected_days,
                valid_days=series.seasonal_summary.coverage.valid_days,
                missing_days=series.seasonal_summary.coverage.missing_days,
            )
            for code, series in sorted(snapshot.parameters.items())
        )
        if snapshot is not None
        else ()
    )
    return SnapshotUseProvenance(
        snapshot_id=str(snapshot.id) if snapshot is not None and snapshot.id else None,
        start_date=start_date,
        end_date=end_date,
        data_status=retrieval.data_status if retrieval is not None else "unavailable",
        cache_action=retrieval.cache_action if retrieval is not None else "unavailable",
        freshness_status=(retrieval.freshness.status if retrieval is not None else "unknown"),
        retrieved_at=snapshot.retrieved_at if snapshot is not None else None,
        source_products=(
            tuple(snapshot.provider_metadata.source_products) if snapshot is not None else ()
        ),
        parameters=parameters,
        warning_codes=(
            ("NASA_RETRIEVAL_UNAVAILABLE",)
            if retrieval is None
            else ("NASA_RETRIEVAL_UNAVAILABLE",)
            if retrieval.data_status == "unavailable"
            else ()
        ),
    )


async def create_rotation_result_for_owned_farm(
    *,
    farm: Farm,
    location: SupportedLocation,
    owner_user_id: PydanticObjectId,
    farm_repository: FarmRepository,
    catalog_repository: CropCatalogRepository,
    snapshot_service: EnvironmentalSnapshotService,
    result_repository: RotationResultRepository,
    priority_adjustment: PriorityPoints | None,
    as_of_date: date | None = None,
) -> RotationResult:
    """Assemble NY-39 saved facts, NY-6 data and NY-40 pure decisions once."""

    if farm.id is None or farm.owner_user_id != owner_user_id:
        raise ValueError("An owned, saved farm is required")
    if (
        farm.schema_version != "farm-v2"
        or farm.history_status != "complete"
        or not farm.crop_history
        or farm.environmental_context is None
        or farm.environmental_context.period is None
    ):
        raise FarmHistoryNeedsReview("Complete dated crop history is required")

    period: DerivedContextPeriod = farm.environmental_context.period
    refreshed_farm, context_retrieval = await FarmContextService().retrieve_for_owned_farm(
        farm=farm,
        location=location,
        snapshot_service=snapshot_service,
        farm_repository=farm_repository,
    )
    latest_farm = await farm_repository.get_by_owner(farm_id=farm.id, owner_user_id=owner_user_id)
    if (
        latest_farm is None
        or latest_farm.revision != farm.revision
        or latest_farm.environmental_context is None
        or latest_farm.environmental_context.period != period
    ):
        raise FarmChangedDuringGeneration("The farm changed during recommendation generation")
    farm = refreshed_farm

    indicators = (
        EnvironmentalIndicatorService().calculate(
            context_retrieval,
            PowerRequest(
                latitude=location.coordinates.latitude,
                longitude=location.coordinates.longitude,
                start_date=period.start_date,
                end_date=period.end_date,
            ),
        )
        if context_retrieval is not None
        else ()
    )
    context_ready = sum(_indicator_usable(item) for item in indicators) >= 2

    bundles = await catalog_repository.list_recommendation_candidates(
        location_key=farm.location_key
    )
    catalog = _catalog_from_bundles(bundles)
    current_date = as_of_date or datetime.now(UTC).date()
    generation_request, generated, future_summary = _generate_scheduled_candidates(
        farm, catalog, as_of_date=current_date
    )

    reference_request: PowerRequest | None = None
    reference_retrieval: SnapshotRetrieval | None = None
    if _has_possible_climate_stage(generated, catalog):
        reference_request = PowerRequest(
            latitude=location.coordinates.latitude,
            longitude=location.coordinates.longitude,
            start_date=CLIMATE_REFERENCE_START,
            end_date=CLIMATE_REFERENCE_END,
        )
        reference_retrieval = await snapshot_service.retrieve(reference_request)

    exposure_cache: dict[str, StageCDDExposure] = {}
    exposure_by_id = {
        candidate.candidate_id: _candidate_stage_exposures(
            candidate, catalog, reference_retrieval, exposure_cache
        )
        for candidate in generated.candidates
    }
    assessment_context = FarmAssessmentContext(
        location_key=farm.location_key,
        soil_texture=farm.soil_texture_key,
        irrigation_access=farm.irrigation_access_key,
    )
    history = tuple(event.crop_key_snapshot for event in farm.crop_history)
    scoring_request = ScoringRequest(
        options=tuple(
            build_crop_evidence_option(
                candidate,
                indicators,
                farm_context=assessment_context,
                prior_crop_history=history,
                environmental_context_ready=context_ready,
                crop_profiles_by_id=catalog.assessment_profiles,
                climate_exposures=exposure_by_id[candidate.candidate_id],
                require_sourced_timing=True,
            )
            for candidate in generated.candidates
        ),
        farmer_priorities=priority_adjustment or farm.farmer_priorities,
    )
    scoring_result = score_rotation_options(scoring_request)
    # This user-facing workflow no longer infers a future current-practice baseline.
    if scoring_result.baseline_option is not None:
        scoring_result = scoring_result.model_copy(update={"baseline_option": None})

    unique_features: dict[tuple[Any, ...], StageCDDExposure] = {}
    for exposures in exposure_by_id.values():
        for item in exposures:
            feature = item.exposure
            key = (
                feature.crop_id,
                feature.variety_key,
                feature.production_system_key,
                feature.stage_key,
                feature.profile_revision_id,
                feature.calendar_version_id,
                feature.planting_window_start,
                feature.planting_window_end,
                feature.source_snapshot_id,
                feature.exposure_min_days,
                feature.exposure_max_days,
                feature.reason,
            )
            unique_features.setdefault(key, feature)
    features = tuple(unique_features.values())
    climate_status_reason = (
        None
        if any(item.status == "assessed" for item in features)
        else "No complete, sourced crop-stage/calendar and 1991–2020 reference combination "
        "can support a comparable dry-spell assessment."
    )

    if context_retrieval is None or context_retrieval.data_status == "unavailable":
        decision_status = "unavailable"
    elif scoring_result.ranking is not None and scoring_result.ranking.status == "ranked":
        decision_status = "ranked_provisional"
    elif future_summary.needs_review_count:
        decision_status = "needs_review"
    else:
        decision_status = "unranked"

    context_provenance = _snapshot_provenance(
        context_retrieval, start_date=period.start_date, end_date=period.end_date
    )
    reference_provenance = (
        _snapshot_provenance(
            reference_retrieval,
            start_date=CLIMATE_REFERENCE_START,
            end_date=CLIMATE_REFERENCE_END,
        )
        if reference_request is not None
        else None
    )
    profile_ids = tuple(
        dict.fromkeys(
            PydanticObjectId(item.event.profile_revision_id)
            for candidate in generated.candidates
            for item in candidate.events
            if item.event.profile_revision_id is not None
        )
    )
    calendar_ids = tuple(
        dict.fromkeys(
            PydanticObjectId(item.event.calendar_version_id)
            for candidate in generated.candidates
            for item in candidate.events
            if item.event.calendar_version_id is not None
        )
    )
    decision_inputs = RotationDecisionInputs(
        generation_request=generation_request,
        scoring_request=scoring_request,
        environmental_snapshot_ids=(
            (context_retrieval.snapshot.id,)
            if context_retrieval is not None
            and context_retrieval.snapshot is not None
            and context_retrieval.snapshot.id is not None
            else ()
        ),
        climate_reference_ids=(
            (reference_retrieval.snapshot.id,)
            if reference_retrieval is not None
            and reference_retrieval.snapshot is not None
            and reference_retrieval.snapshot.id is not None
            else ()
        ),
        crop_profile_revision_ids=profile_ids,
        calendar_version_ids=calendar_ids,
        crop_library_version=CROP_IDENTITY_SCHEMA_VERSION,
        assessment_version=ASSESSMENT_VERSION,
        rule_set_version=ROTATION_RULE_SET_VERSION,
        scoring_version=SCORING_VERSION,
        climate_method_version=CDD_METHOD_VERSION,
        calendar_method_version=FUTURE_CALENDAR_METHOD_VERSION,
    )
    # Pure generation and scoring can take time after the initial Farm check.
    # Re-read through the owner-scoped repository immediately before inserting
    # so a PATCH that won during that work does not produce a current-looking
    # result for an obsolete plot revision or historical context period.
    latest_farm = await farm_repository.get_by_owner(farm_id=farm.id, owner_user_id=owner_user_id)
    if (
        latest_farm is None
        or latest_farm.revision != farm.revision
        or latest_farm.location_key != farm.location_key
        or latest_farm.environmental_context is None
        or latest_farm.environmental_context.period != period
    ):
        raise FarmChangedDuringGeneration("The farm changed during recommendation generation")
    return await result_repository.create_for_farm(
        owner_user_id=owner_user_id,
        farm=farm,
        decision_inputs=decision_inputs,
        candidate_generation=generated,
        scoring_result=scoring_result,
        derived_context_period=period,
        context_provenance=context_provenance,
        climate_reference_provenance=reference_provenance,
        indicators=indicators,
        climate_features=features,
        climate_feature_status_reason=climate_status_reason,
        future_window_summary=future_summary,
        decision_status=decision_status,
    )
