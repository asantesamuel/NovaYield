"""NY-39/NY-40 orchestration contracts using saved synthetic facts and cached POWER.

These are service-boundary tests. They exercise the real pure generation,
indicator, calendar and scoring code while replacing Mongo and NASA transport
with recorded calls. The synthetic farm and weather are not pilot evidence.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from beanie import PydanticObjectId

from app.decisions.climate_features import compare_matched_rotation_exposure
from app.decisions.scoring import (
    CRITERIA,
    CriterionEvidence,
    ScoringRequest,
    score_rotation_options,
)
from app.farms.context_window import derive_context_period
from app.farms.contracts import LocationCoordinates
from app.integrations.nasa.power import (
    DailyValue,
    DateCoverage,
    PowerParameterMetadata,
    PowerParameterSeries,
    PowerProviderMetadata,
    SeasonalSummary,
)
from app.models.crop_catalog import (
    Crop,
    CropCalendar,
    CropProfileRevision,
    EvidenceValue,
    GrowthStage,
    MaturityEvidence,
    MaturityRange,
    PlantingWindow,
    SourceEvidence,
)
from app.models.farms import CropHistoryEvent, Farm, FarmEnvironmentalContextState
from app.models.supported_locations import SupportedLocation
from app.repositories.crop_catalog import CropCandidateBundle
from app.services.environmental_snapshots import FreshnessAssessment, SnapshotRetrieval
from app.services.recommendation_workflow import (
    FarmChangedDuringGeneration,
    FarmHistoryNeedsReview,
    create_rotation_result_for_owned_farm,
)


def _period_days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _series(code: str, start: date, end: date, value: float) -> PowerParameterSeries:
    days = [DailyValue(date=day, value=value) for day in _period_days(start, end)]
    units = "mm/day" if code == "PRECTOTCORR" else "°C"
    return PowerParameterSeries(
        metadata=PowerParameterMetadata(
            code=code,
            long_name=f"Synthetic {code}",
            source_units=units,
            normalized_units=units,
            source="synthetic POWER fixture",
            spatial_resolution="synthetic resolution",
            fill_value=-999.0,
        ),
        daily_values=days,
        seasonal_summary=SeasonalSummary(
            method="sum" if code == "PRECTOTCORR" else "mean",
            value=value * len(days) if code == "PRECTOTCORR" else value,
            units="mm" if code == "PRECTOTCORR" else "°C",
            status="complete",
            coverage=DateCoverage(
                requested_start_date=start,
                requested_end_date=end,
                returned_start_date=start,
                returned_end_date=end,
                expected_days=len(days),
                valid_days=len(days),
                missing_days=0,
                coverage_percent=100,
            ),
        ),
    )


def _retrieval(start: date, end: date) -> SnapshotRetrieval:
    snapshot = SimpleNamespace(
        id=PydanticObjectId(),
        identity=SimpleNamespace(start_date=start, end_date=end),
        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
        provider_metadata=PowerProviderMetadata(
            header_title="Synthetic NASA POWER contract fixture",
            source_products=["synthetic POWER fixture"],
        ),
        parameters={
            "PRECTOTCORR": _series("PRECTOTCORR", start, end, 5.0),
            "T2M": _series("T2M", start, end, 27.0),
            "T2M_MAX": _series("T2M_MAX", start, end, 33.0),
        },
    )
    return SnapshotRetrieval(
        snapshot=snapshot,
        data_status="cached",
        cache_action="hit",
        freshness=FreshnessAssessment("unknown", 0, "No source refresh rule configured."),
        refresh_attempted=False,
    )


def _farm() -> Farm:
    history = [
        CropHistoryEvent(
            event_id=f"past-{index}",
            crop_id=PydanticObjectId(),
            crop_key_snapshot=crop,
            sequence_order=index,
            start_date=start,
            end_date=end,
        )
        for index, (crop, start, end) in enumerate(
            (
                ("maize", date(2023, 3, 15), date(2023, 7, 1)),
                ("cowpea", date(2023, 8, 1), date(2023, 10, 1)),
                ("groundnut", date(2024, 3, 1), date(2024, 6, 15)),
            ),
            1,
        )
    ]
    period = derive_context_period(history)
    assert period is not None
    return Farm.model_construct(
        id=PydanticObjectId(),
        owner_user_id=PydanticObjectId(),
        schema_version="farm-v2",
        revision=2,
        name="Synthetic owned plot",
        location_key="ejura",
        soil_texture_key="loamy",
        irrigation_access_key="none",
        history_status="complete",
        crop_history=history,
        current_plot_available=True,
        earliest_available_date=date(2027, 1, 1),
        environmental_context=FarmEnvironmentalContextState(status="pending", period=period),
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        updated_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def _location() -> SupportedLocation:
    return SupportedLocation.model_construct(
        location_key="ejura",
        label="Ejura",
        coordinates=LocationCoordinates(latitude=7.3856, longitude=-1.3562),
    )


class FakeFarmRepository:
    def __init__(self, farm: Farm) -> None:
        self.farm = farm
        self.context_updates: list[FarmEnvironmentalContextState] = []

    async def set_environmental_context_by_owner(
        self,
        *,
        farm_id: PydanticObjectId,
        owner_user_id: PydanticObjectId,
        expected_revision: int,
        context: FarmEnvironmentalContextState,
    ) -> Farm | None:
        if (
            farm_id != self.farm.id
            or owner_user_id != self.farm.owner_user_id
            or expected_revision != self.farm.revision
        ):
            return None
        self.context_updates.append(context)
        self.farm = self.farm.model_copy(update={"environmental_context": context})
        return self.farm

    async def get_by_owner(
        self, *, farm_id: PydanticObjectId, owner_user_id: PydanticObjectId
    ) -> Farm | None:
        if farm_id == self.farm.id and owner_user_id == self.farm.owner_user_id:
            return self.farm
        return None


class FakeSnapshotService:
    def __init__(self, retrieval: SnapshotRetrieval) -> None:
        self.retrieval = retrieval
        self.requests: list[Any] = []

    async def retrieve(self, request: Any, *, force_refresh: bool = False) -> SnapshotRetrieval:
        self.requests.append((request, force_refresh))
        if (
            request.start_date != self.retrieval.snapshot.identity.start_date
            or request.end_date != self.retrieval.snapshot.identity.end_date
        ):
            raise AssertionError("Unexpected non-context NASA request")
        return self.retrieval


class FakeCatalogRepository:
    def __init__(self, crop_keys: tuple[str, ...]) -> None:
        self.location_keys: list[str] = []
        self.bundles = [
            CropCandidateBundle(
                crop=Crop.model_construct(
                    id=PydanticObjectId(),
                    crop_key=key,
                    common_name=key.title(),
                    scientific_name=None,
                    family=None,
                    identity_source_url=f"https://example.org/synthetic-{key}",
                    history_selectable=True,
                    recommendation_candidate=True,
                    catalog_status="active",
                ),
                active_profiles=(),
                calendars=(),
            )
            for key in crop_keys
        ]

    async def list_recommendation_candidates(
        self, *, location_key: str
    ) -> list[CropCandidateBundle]:
        self.location_keys.append(location_key)
        return self.bundles


class FakeResultRepository:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def create_for_farm(self, **kwargs: Any) -> SimpleNamespace:
        self.saved.append(kwargs)
        return SimpleNamespace(**kwargs)


def _run(
    farm: Farm,
    farm_repository: FakeFarmRepository,
    snapshot_service: FakeSnapshotService,
    catalog_repository: FakeCatalogRepository,
    result_repository: FakeResultRepository,
) -> SimpleNamespace:
    return asyncio.run(
        create_rotation_result_for_owned_farm(
            farm=farm,
            location=_location(),
            owner_user_id=farm.owner_user_id,
            farm_repository=farm_repository,
            catalog_repository=catalog_repository,
            snapshot_service=snapshot_service,
            result_repository=result_repository,
            priority_adjustment=None,
            as_of_date=date(2027, 1, 1),
        )
    )


def test_owned_farm_uses_its_saved_period_and_only_canonical_catalog_candidates() -> None:
    farm = _farm()
    assert farm.environmental_context is not None
    assert farm.environmental_context.period is not None
    period = farm.environmental_context.period
    retrieval = _retrieval(period.start_date, period.end_date)
    farms = FakeFarmRepository(farm)
    snapshots = FakeSnapshotService(retrieval)
    catalog = FakeCatalogRepository(("maize", "cowpea", "groundnut"))
    results = FakeResultRepository()

    first = _run(farm, farms, snapshots, catalog, results)
    second = _run(farms.farm, farms, snapshots, catalog, results)

    assert len(results.saved) == 2
    assert len(snapshots.requests) == 2
    assert all(request.start_date == period.start_date for request, _ in snapshots.requests)
    assert all(request.end_date == period.end_date for request, _ in snapshots.requests)
    assert all(not force for _, force in snapshots.requests)
    assert first.derived_context_period == second.derived_context_period == period
    assert first.context_provenance.snapshot_id == second.context_provenance.snapshot_id
    assert first.context_provenance.data_status == second.context_provenance.data_status == "cached"
    assert first.context_provenance.cache_action == "hit"
    assert {item.code for item in first.indicators} == {
        "seasonal_precipitation_total",
        "mean_daily_air_temperature",
        "mean_daily_maximum_air_temperature",
    }
    assert all(item.status == "complete" for item in first.indicators)
    assert catalog.location_keys == ["ejura", "ejura"]
    assert {crop.crop_id for crop in first.decision_inputs.generation_request.candidate_crops} == {
        "maize",
        "cowpea",
        "groundnut",
    }
    assert len(first.candidate_generation.candidates) == 27
    assert first.decision_inputs.generation_request.prior_crop_history == (
        "maize",
        "cowpea",
        "groundnut",
    )


def test_missing_calendar_and_stage_evidence_stay_review_needed_without_reference_call() -> None:
    farm = _farm()
    period = farm.environmental_context.period
    assert period is not None
    farms = FakeFarmRepository(farm)
    snapshots = FakeSnapshotService(_retrieval(period.start_date, period.end_date))
    result = _run(
        farm,
        farms,
        snapshots,
        FakeCatalogRepository(("maize", "cowpea", "groundnut")),
        FakeResultRepository(),
    )

    assert result.decision_status == "needs_review"
    assert result.future_window_summary.fully_scheduled_count == 0
    assert result.future_window_summary.needs_review_count == 27
    assert "scoped_crop_calendar_missing" in result.future_window_summary.review_reasons
    assert result.climate_features == ()
    assert result.climate_reference_provenance is None
    assert result.climate_feature_status_reason is not None
    assert len(snapshots.requests) == 1
    assert all(
        event.event.window_start is None and event.event.harvest_end is None
        for candidate in result.candidate_generation.candidates
        for event in candidate.events
    )
    assert result.scoring_result.ranking is None or result.scoring_result.ranking.status != "ranked"


def test_non_v2_or_nonowned_farm_cannot_start_recommendation_work() -> None:
    farm = _farm()
    period = farm.environmental_context.period
    assert period is not None
    farms = FakeFarmRepository(farm)
    snapshots = FakeSnapshotService(_retrieval(period.start_date, period.end_date))
    catalog = FakeCatalogRepository(("maize", "cowpea", "groundnut"))
    results = FakeResultRepository()

    legacy = farm.model_copy(update={"schema_version": "farm-v1"})
    with pytest.raises(FarmHistoryNeedsReview):
        _run(legacy, farms, snapshots, catalog, results)
    assert snapshots.requests == []
    assert catalog.location_keys == []
    assert results.saved == []

    with pytest.raises(ValueError, match="owned, saved farm"):
        asyncio.run(
            create_rotation_result_for_owned_farm(
                farm=farm,
                location=_location(),
                owner_user_id=PydanticObjectId(),
                farm_repository=farms,
                catalog_repository=catalog,
                snapshot_service=snapshots,
                result_repository=results,
                priority_adjustment=None,
                as_of_date=date(2027, 1, 1),
            )
        )
    assert snapshots.requests == []


def test_patch_during_scoring_aborts_before_result_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    farm = _farm()
    period = farm.environmental_context.period
    assert period is not None
    farms = FakeFarmRepository(farm)
    snapshots = FakeSnapshotService(_retrieval(period.start_date, period.end_date))
    catalog = FakeCatalogRepository(("maize", "cowpea", "groundnut"))
    results = FakeResultRepository()

    def score_after_concurrent_patch(request: ScoringRequest):
        # A real PATCH increments the persisted Farm revision. Simulate that
        # deterministic interleaving after the initial read and before insert.
        farms.farm = farms.farm.model_copy(update={"revision": farms.farm.revision + 1})
        return score_rotation_options(request)

    monkeypatch.setattr(
        "app.services.recommendation_workflow.score_rotation_options",
        score_after_concurrent_patch,
    )

    with pytest.raises(FarmChangedDuringGeneration):
        _run(farm, farms, snapshots, catalog, results)

    assert farms.farm.revision == farm.revision + 1
    assert results.saved == []


def _synthetic_source(claim: str) -> SourceEvidence:
    """An explicit test-only provenance envelope, never a pilot research claim."""

    return SourceEvidence(
        source_url=f"https://example.org/synthetic-{claim}",
        source_title=f"Synthetic {claim} contract fixture",
        source_confidence="low",
        pilot_transferability="low",
        applicability="Controlled NY-40 test only; no real farm or crop claim.",
        limitations="Fabricated dates and values used solely to verify orchestration.",
        validation_status="provisional",
    )


def _sourced_generic_catalog() -> FakeCatalogRepository:
    catalog = FakeCatalogRepository(("maize", "cowpea", "groundnut"))
    offsets = {"maize": 0, "cowpea": 3, "groundnut": 6}
    bundles: list[CropCandidateBundle] = []
    for original in catalog.bundles:
        crop = original.crop
        offset = offsets[crop.crop_key]
        stage_source = _synthetic_source(f"{crop.crop_key}-stage")
        maturity_source = _synthetic_source(f"{crop.crop_key}-maturity")
        profile = CropProfileRevision.model_construct(
            id=PydanticObjectId(),
            crop_id=crop.id,
            revision=1,
            is_active=True,
            variety_key=None,
            production_system_key=None,
            maturity_days=MaturityEvidence(
                value=MaturityRange(
                    min_days=20,
                    max_days=20,
                    meaning="planting_to_harvest",
                    endpoint_verified=True,
                ),
                source=maturity_source,
            ),
            growth_stages=[
                GrowthStage(
                    stage_key="synthetic-water-sensitive-stage",
                    start_offset_days=EvidenceValue(
                        value={"min_days": offset, "max_days": offset},
                        unit="days",
                        source=stage_source,
                    ),
                    duration_days=EvidenceValue(
                        value={"min_days": 2, "max_days": 2},
                        unit="days",
                        source=stage_source,
                    ),
                    sensitivity=EvidenceValue(
                        value={"factor": "water_shortage", "direction": "sensitive"},
                        source=stage_source,
                    ),
                )
            ],
            evidence_status="provisional",
            published_at=datetime(2026, 11, 1, tzinfo=UTC),
        )
        calendars = tuple(
            CropCalendar.model_construct(
                id=PydanticObjectId(),
                calendar_version=f"synthetic-{crop.crop_key}-{month}-v1",
                is_active=True,
                published_at=datetime(2026, 11, 1, tzinfo=UTC),
                location_key="ejura",
                crop_id=crop.id,
                profile_revision_id=profile.id,
                season_key=f"synthetic-month-{month}",
                planting_window=PlantingWindow(
                    start_month_day=f"{month:02d}-01",
                    end_month_day=f"{month:02d}-01",
                    crosses_year=False,
                    valid_from_year=2027,
                    valid_to_year=2029,
                ),
                evidence=_synthetic_source(f"{crop.crop_key}-calendar-{month}"),
                status="provisional",
            )
            for month in (3, 4, 5)
        )
        bundles.append(
            CropCandidateBundle(
                crop=crop,
                active_profiles=(profile,),
                calendars=calendars,
            )
        )
    catalog.bundles = bundles
    return catalog


def _reference_retrieval(*, reverse: bool) -> SnapshotRetrieval:
    start, end = date(1991, 1, 1), date(2020, 12, 31)
    values = {(month, day): 2.0 for month in (3, 4, 5) for day in range(1, 9)}
    # In the first scenario, maize→cowpea→groundnut sees the wet stage days.
    # Reversing dry intervals favors cowpea→groundnut→maize instead.
    dry_intervals = (
        ((3, (1, 2)), (4, (4, 5)), (5, (7, 8)))
        if reverse
        else ((3, (4, 5)), (4, (7, 8)), (5, (1, 2)))
    )
    for month, days in dry_intervals:
        for day in days:
            values[(month, day)] = 0.0
    daily_values = [
        DailyValue(date=date(year, month, day), value=value)
        for year in range(1991, 2021)
        for (month, day), value in values.items()
    ]
    series = PowerParameterSeries(
        metadata=PowerParameterMetadata(
            code="PRECTOTCORR",
            long_name="Synthetic precipitation",
            source_units="mm/day",
            normalized_units="mm/day",
            source="synthetic reference source",
            spatial_resolution="synthetic resolution",
            fill_value=-999.0,
        ),
        daily_values=daily_values,
        seasonal_summary=SeasonalSummary(
            method="sum",
            value=None,
            units="mm",
            status="partial",
            coverage=DateCoverage(
                requested_start_date=start,
                requested_end_date=end,
                returned_start_date=daily_values[0].date,
                returned_end_date=daily_values[-1].date,
                expected_days=(end - start).days + 1,
                valid_days=len(daily_values),
                missing_days=(end - start).days + 1 - len(daily_values),
                coverage_percent=100 * len(daily_values) / ((end - start).days + 1),
            ),
        ),
    )
    snapshot = SimpleNamespace(
        id=PydanticObjectId(),
        identity=SimpleNamespace(start_date=start, end_date=end),
        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
        provider_metadata=PowerProviderMetadata(
            header_title="Synthetic NASA POWER historical reference",
            source_products=["synthetic reference source"],
        ),
        parameters={"PRECTOTCORR": series},
    )
    return SnapshotRetrieval(
        snapshot=snapshot,
        data_status="cached",
        cache_action="hit",
        freshness=FreshnessAssessment("unknown", 0, "Synthetic fixture"),
        refresh_attempted=False,
    )


class FakeTwoPeriodSnapshotService(FakeSnapshotService):
    def __init__(self, context: SnapshotRetrieval, reference: SnapshotRetrieval) -> None:
        super().__init__(context)
        self.reference = reference

    async def retrieve(self, request: Any, *, force_refresh: bool = False) -> SnapshotRetrieval:
        self.requests.append((request, force_refresh))
        if request.start_date == self.retrieval.snapshot.identity.start_date and (
            request.end_date == self.retrieval.snapshot.identity.end_date
        ):
            return self.retrieval
        if request.start_date == date(1991, 1, 1) and request.end_date == date(2020, 12, 31):
            return self.reference
        raise AssertionError("Unexpected NASA request outside saved context/reference")


def test_sourced_generic_stage_changes_climate_comparison_but_unrated_water_withholds_rank() -> (
    None
):
    catalog = _sourced_generic_catalog()

    def scenario(*, reverse: bool):
        farm = _farm()
        period = farm.environmental_context.period
        assert period is not None
        snapshots = FakeTwoPeriodSnapshotService(
            _retrieval(period.start_date, period.end_date),
            _reference_retrieval(reverse=reverse),
        )
        result = _run(
            farm,
            FakeFarmRepository(farm),
            snapshots,
            catalog,
            FakeResultRepository(),
        )
        assert [(item.start_date, item.end_date) for item, _ in snapshots.requests] == [
            (period.start_date, period.end_date),
            (date(1991, 1, 1), date(2020, 12, 31)),
        ]
        assert result.future_window_summary.fully_scheduled_count == 27
        assert result.climate_reference_provenance.snapshot_id is not None
        assert any(feature.status == "assessed" for feature in result.climate_features)
        by_id = {
            option.candidate.candidate_id: option
            for option in result.decision_inputs.scoring_request.options
        }
        left = by_id["alternative:maize|cowpea|groundnut"].climate_exposures
        right = by_id["alternative:cowpea|groundnut|maize"].climate_exposures
        assert len(left) == len(right) == 3
        assert all(item.exposure.status == "assessed" for item in (*left, *right))
        return (
            result,
            compare_matched_rotation_exposure(left, right, decision13_weighted_total_tie=True),
            (
                by_id["alternative:maize|cowpea|groundnut"],
                by_id["alternative:cowpea|groundnut|maize"],
            ),
        )

    wet_first, comparison_a, options_a = scenario(reverse=False)
    dry_first, comparison_b, options_b = scenario(reverse=True)
    assert comparison_a.status == "left_preferred"
    assert comparison_b.status == "right_preferred"
    # Decision 13 still gates ranking on a sourced comparable water rating.
    # The catalog has sourced timing/stages, but no approved rating translation
    # from meteorological CDD to crop water sufficiency or resilience class.
    for result in (wet_first, dry_first):
        assert result.decision_status == "needs_review"
        assert result.scoring_result.ranking is None or (
            result.scoring_result.ranking.status != "ranked"
        )

    # This separate test-only scoring input supplies explicit equal, comparable
    # four-criterion ratings. It is not promoted into the live catalog. The
    # actual service-calculated climate exposures are preserved unchanged.
    synthetic_criteria = tuple(
        CriterionEvidence(
            criterion=criterion,
            status="assessed",
            rating="moderate",
            confidence="low",
            rationale="Controlled synthetic equality for a Decision-13 tie test only.",
            comparison_basis=f"synthetic-{criterion}-v1",
            evidence_references=("synthetic scoring contract fixture",),
            assumptions=("No crop or pilot agronomic claim is made.",),
        )
        for criterion in CRITERIA
    )

    def synthetic_order(options):
        request = ScoringRequest(
            options=tuple(
                option.model_copy(update={"criteria": synthetic_criteria}) for option in options
            )
        )
        scored = score_rotation_options(request)
        assert scored.ranking is not None
        assert scored.ranking.status == "ranked"
        assert scored.ranking_mode == "four_criterion"
        assert scored.ranking.climate_tie_preferences
        return tuple(option.candidate.candidate_id for option in scored.options)

    assert synthetic_order(options_a) == (
        "alternative:maize|cowpea|groundnut",
        "alternative:cowpea|groundnut|maize",
    )
    assert synthetic_order(options_b) == (
        "alternative:cowpea|groundnut|maize",
        "alternative:maize|cowpea|groundnut",
    )
