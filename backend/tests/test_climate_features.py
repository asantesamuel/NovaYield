"""Focused, synthetic contract tests for NY-40's pure CDD method.

The rainfall series below is fabricated to make the arithmetic reviewable. It
is never presented as an Ejura observation or a validated crop profile.
"""

from __future__ import annotations

from datetime import date

from app.decisions.climate_features import (
    MatchedCropExposure,
    StageCDDRequest,
    calculate_stage_cdd_exposure,
    compare_matched_rotation_exposure,
)
from app.decisions.rotation import (
    CandidatePlantingEvent,
    CropCandidate,
    PlantingEventSlot,
    RotationCandidate,
)
from app.decisions.scoring import (
    CRITERIA,
    CriterionEvidence,
    RotationOptionEvidence,
    ScoringRequest,
    score_rotation_options,
)
from app.integrations.nasa.power import (
    DailyValue,
    DateCoverage,
    PowerParameterMetadata,
    PowerParameterSeries,
    SeasonalSummary,
)


def _series(values_by_month_day: dict[tuple[int, int], float | None]) -> PowerParameterSeries:
    days = [
        DailyValue(date=date(year, month, day), value=value)
        for year in range(1991, 2021)
        for (month, day), value in values_by_month_day.items()
    ]
    return PowerParameterSeries(
        metadata=PowerParameterMetadata(
            code="PRECTOTCORR",
            long_name="Precipitation corrected",
            source_units="mm/day",
            normalized_units="mm/day",
            source="MERRA-2",
            spatial_resolution="0.5 x 0.625 degrees",
            fill_value=-999.0,
        ),
        daily_values=days,
        seasonal_summary=SeasonalSummary(
            method="sum",
            value=None,
            units="mm",
            status="partial",
            coverage=DateCoverage(
                requested_start_date=date(1991, 1, 1),
                requested_end_date=date(2020, 12, 31),
                returned_start_date=days[0].date if days else None,
                returned_end_date=days[-1].date if days else None,
                expected_days=10_958,
                valid_days=sum(item.value is not None for item in days),
                missing_days=10_958 - sum(item.value is not None for item in days),
                coverage_percent=100 * sum(item.value is not None for item in days) / 10_958,
            ),
        ),
    )


def _request(**changes: object) -> StageCDDRequest:
    base = StageCDDRequest(
        crop_id="maize",
        variety_key="synthetic-variety",
        production_system_key="synthetic-rainfed",
        stage_key="synthetic-sensitive-stage",
        planting_window_start=date(2027, 3, 1),
        planting_window_end=date(2027, 3, 1),
        stage_offset_min_days=0,
        stage_offset_max_days=0,
        stage_duration_min_days=7,
        stage_duration_max_days=7,
        maturity_min_days=70,
        maturity_max_days=80,
        profile_revision_id="synthetic-profile-v1",
        calendar_version_id="synthetic-calendar-v1",
        calendar_source="synthetic-calendar-fixture",
        stage_source="synthetic-stage-fixture",
        sensitivity_source="synthetic-sensitivity-fixture",
        maturity_source="synthetic-maturity-fixture",
        evidence_status="provisional",
        source_snapshot_id="synthetic-nasa-snapshot",
        source_products=("MERRA-2",),
    )
    return base.model_copy(update=changes)


def test_cdd_is_longest_consecutive_run_and_is_deterministic() -> None:
    # March 1–7: two dry days, one wet day, three dry days, one wet day.
    values = [0.0, 0.2, 3.0, 0.0, 0.0, 0.4, 2.0]
    series = _series({(3, day): value for day, value in enumerate(values, 1)})

    result = calculate_stage_cdd_exposure(_request(), series)

    assert result.status == "assessed"
    assert result.exposure_min_days == result.exposure_max_days == 3.0
    assert result.feasible_placement_count == 1
    assert result.complete_years_per_placement == 30
    assert result.placements[0].annual_cdd_days == (3,) * 30
    assert calculate_stage_cdd_exposure(_request(), series) == result
    assert "not a forecast" in result.interpretation


def test_all_wet_is_a_measured_zero_and_threshold_one_is_wet() -> None:
    result = calculate_stage_cdd_exposure(
        _request(), _series({(3, day): 1.0 for day in range(1, 8)})
    )
    assert result.status == "assessed"
    assert result.exposure_min_days == result.exposure_max_days == 0.0


def test_all_feasible_planting_dates_define_an_interval() -> None:
    request = _request(
        planting_window_end=date(2027, 3, 2),
        stage_duration_min_days=3,
        stage_duration_max_days=3,
    )
    series = _series({(3, 1): 0.0, (3, 2): 0.0, (3, 3): 2.0, (3, 4): 0.0})

    result = calculate_stage_cdd_exposure(request, series)

    assert result.status == "assessed"
    assert result.feasible_placement_count == 2
    assert (result.exposure_min_days, result.exposure_max_days) == (1.0, 2.0)


def test_supported_stage_offset_and_duration_ranges_are_all_examined() -> None:
    request = _request(
        stage_offset_min_days=0,
        stage_offset_max_days=1,
        stage_duration_min_days=2,
        stage_duration_max_days=3,
    )
    series = _series({(3, 1): 0.0, (3, 2): 0.0, (3, 3): 2.0, (3, 4): 0.0})
    result = calculate_stage_cdd_exposure(request, series)
    assert result.status == "assessed"
    assert result.feasible_placement_count == 4
    assert (result.exposure_min_days, result.exposure_max_days) == (1.0, 2.0)


def test_large_exact_workload_is_withheld_without_sampling_or_approximation() -> None:
    request = _request(
        planting_window_start=date(2027, 1, 1),
        planting_window_end=date(2027, 4, 10),
        stage_offset_min_days=0,
        stage_offset_max_days=9,
        stage_duration_min_days=100,
        stage_duration_max_days=109,
        maturity_min_days=200,
        maturity_max_days=210,
    )
    result = calculate_stage_cdd_exposure(request, _series({}))
    assert result.status == "not_assessed"
    assert result.reason == "reference_work_exceeds_exact_assessment_budget"
    assert result.exposure_min_days is None


def test_missing_year_or_day_is_not_a_zero_or_partial_rankable_cdd() -> None:
    values = {(3, day): 0.0 for day in range(1, 8)}
    series = _series(values)
    series.daily_values = [item for item in series.daily_values if item.date != date(2008, 3, 4)]
    result = calculate_stage_cdd_exposure(_request(), series)
    assert result.status == "not_assessed"
    assert result.reason == "reference_window_incomplete"
    assert result.exposure_min_days is None
    assert result.placements == ()

    series = _series(values)
    series.daily_values[0].value = None
    assert calculate_stage_cdd_exposure(_request(), series).status == "not_assessed"

    series = _series(values)
    series.daily_values[0].value = -999.0
    assert calculate_stage_cdd_exposure(_request(), series).reason == (
        "reference_window_incomplete"
    )


def test_invalid_precipitation_units_and_stage_evidence_are_withheld() -> None:
    series = _series({(3, day): 0.0 for day in range(1, 8)})
    series.daily_values[0].value = -0.5
    assert calculate_stage_cdd_exposure(_request(), series).reason == (
        "reference_precipitation_invalid"
    )

    series = _series({(3, day): 0.0 for day in range(1, 8)})
    series.metadata.normalized_units = "inches/day"
    assert calculate_stage_cdd_exposure(_request(), series).reason == (
        "precipitation_units_incompatible"
    )

    series = _series({(3, day): 0.0 for day in range(1, 8)})
    assert calculate_stage_cdd_exposure(_request(stage_offset_min_days=None), series).reason == (
        "stage_timing_missing"
    )
    series.metadata.code = "T2M"
    assert calculate_stage_cdd_exposure(_request(), series).reason == (
        "precipitation_parameter_required"
    )


def test_cross_year_and_leap_day_plantings_wait_for_alignment_review() -> None:
    series = _series({(3, day): 0.0 for day in range(1, 8)})
    cross_year = _request(
        planting_window_start=date(2027, 12, 30),
        planting_window_end=date(2028, 1, 2),
    )
    assert calculate_stage_cdd_exposure(cross_year, series).reason == (
        "cross_year_window_alignment_unresolved"
    )
    leap = _request(
        planting_window_start=date(2028, 2, 29),
        planting_window_end=date(2028, 2, 29),
    )
    assert calculate_stage_cdd_exposure(leap, series).reason == (
        "leap_day_planting_alignment_unresolved"
    )


def test_climate_preference_uses_actual_calculated_exposure_only_after_score_tie() -> None:
    # Two permutations of the *same* three crops use the same three synthetic
    # months. Crop-specific sourced stage offsets see different weather days.
    # This is contract data, not a real Ghana crop calendar or stage profile.
    values = {(month, day): 2.0 for month in (3, 4, 5) for day in range(1, 9)}
    for month, days in ((3, (4, 5)), (4, (7, 8)), (5, (1, 2))):
        for day in days:
            values[(month, day)] = 0.0
    series = _series(values)

    def assessed(crop: str, month: int, offset: int) -> MatchedCropExposure:
        exposure = calculate_stage_cdd_exposure(
            _request(
                crop_id=crop,
                profile_revision_id=f"{crop}-synthetic-profile-v1",
                calendar_version_id=f"{crop}-synthetic-calendar-{month}",
                planting_window_start=date(2027, month, 1),
                planting_window_end=date(2027, month, 1),
                stage_offset_min_days=offset,
                stage_offset_max_days=offset,
                stage_duration_min_days=2,
                stage_duration_max_days=2,
            ),
            series,
        )
        assert exposure.status == "assessed"
        return MatchedCropExposure(exposure=exposure)

    left = [
        assessed("maize", 3, 0),
        assessed("cowpea", 4, 3),
        assessed("groundnut", 5, 6),
    ]
    right = [
        assessed("cowpea", 3, 3),
        assessed("groundnut", 4, 6),
        assessed("maize", 5, 0),
    ]
    assert {item.exposure.exposure_min_days for item in left} == {0.0}
    assert {item.exposure.exposure_min_days for item in right} == {2.0}
    assert (
        compare_matched_rotation_exposure(left, right, decision13_weighted_total_tie=False).status
        == "not_applicable"
    )
    preferred = compare_matched_rotation_exposure(left, right, decision13_weighted_total_tie=True)
    assert preferred.status == "left_preferred"
    assert preferred.reason == "every_matched_crop_stage_interval_strictly_lower_on_left"
    assert all(item.relationship == "left_strictly_lower" for item in preferred.comparisons)
    assert preferred.policy_status == "provisional"
    assert preferred.matched_crop_count == 3
    reversed_preference = compare_matched_rotation_exposure(
        right, left, decision13_weighted_total_tie=True
    )
    assert reversed_preference.status == "right_preferred"
    assert reversed_preference.reason == "every_matched_crop_stage_interval_strictly_lower_on_right"
    assert all(
        item.relationship == "right_strictly_lower" for item in reversed_preference.comparisons
    )


def test_every_matched_crop_stage_requires_strict_separation() -> None:
    base = calculate_stage_cdd_exposure(_request(), _series({(3, day): 2.0 for day in range(1, 8)}))
    assert base.status == "assessed"

    def matched(crop: str, order: int, lower: float, upper: float) -> MatchedCropExposure:
        return MatchedCropExposure(
            exposure=base.model_copy(
                update={
                    "crop_id": crop,
                    "profile_revision_id": f"{crop}-synthetic-profile-v1",
                    "exposure_min_days": lower,
                    "exposure_max_days": upper,
                }
            ),
            event_order=order,
        )

    crops = ("maize", "cowpea", "groundnut")
    left = tuple(matched(crop, order, 0.0, 1.0) for order, crop in enumerate(crops, 1))
    right_strict = tuple(matched(crop, order, 3.0, 4.0) for order, crop in enumerate(crops, 1))
    strict = compare_matched_rotation_exposure(
        left, right_strict, decision13_weighted_total_tie=True, expected_event_count=3
    )
    assert strict.status == "left_preferred"

    # A single equal crop/stage cannot be carried by two strictly better pairs.
    right_one_equal = (right_strict[0], left[1], right_strict[2])
    one_equal = compare_matched_rotation_exposure(
        left, right_one_equal, decision13_weighted_total_tie=True, expected_event_count=3
    )
    assert one_equal.status == "incomparable"
    assert one_equal.reason == "equal_overlapping_or_mixed_crop_stage_exposure"
    assert {item.relationship for item in one_equal.comparisons} == {
        "left_strictly_lower",
        "equal",
    }

    # Intervals that merely touch at one boundary are not strictly separated.
    right_one_touching = (right_strict[0], matched("cowpea", 2, 1.0, 3.0), right_strict[2])
    one_touching = compare_matched_rotation_exposure(
        left, right_one_touching, decision13_weighted_total_tie=True, expected_event_count=3
    )
    assert one_touching.status == "incomparable"
    assert {item.relationship for item in one_touching.comparisons} == {
        "left_strictly_lower",
        "overlap",
    }

    # Opposite strict directions across crops likewise preserve the weighted tie.
    mixed_left = (left[0], left[1], matched("groundnut", 3, 3.0, 4.0))
    mixed_right = (right_strict[0], right_strict[1], matched("groundnut", 3, 0.0, 1.0))
    mixed = compare_matched_rotation_exposure(
        mixed_left, mixed_right, decision13_weighted_total_tie=True, expected_event_count=3
    )
    assert mixed.status == "incomparable"
    assert {item.relationship for item in mixed.comparisons} == {
        "left_strictly_lower",
        "right_strictly_lower",
    }


def test_overlapping_or_different_crop_scopes_cannot_create_preference() -> None:
    series = _series({(3, day): 0.0 for day in range(1, 8)})
    base = calculate_stage_cdd_exposure(_request(), series)
    assert base.status == "assessed"
    left = [
        MatchedCropExposure(
            exposure=base.model_copy(update={"exposure_min_days": 1.0, "exposure_max_days": 3.0})
        )
    ]
    right = [
        MatchedCropExposure(
            exposure=base.model_copy(update={"exposure_min_days": 2.0, "exposure_max_days": 4.0})
        )
    ]
    assert (
        compare_matched_rotation_exposure(left, right, decision13_weighted_total_tie=True).status
        == "incomparable"
    )
    different = [MatchedCropExposure(exposure=base.model_copy(update={"crop_id": "rice"}))]
    assert (
        compare_matched_rotation_exposure(
            left, different, decision13_weighted_total_tie=True
        ).reason
        == "different_crop_scope_multiset"
    )


def test_duplicate_crop_occurrences_need_explicit_pairing() -> None:
    series = _series({(3, day): 0.0 for day in range(1, 8)})
    base = calculate_stage_cdd_exposure(_request(), series)
    repeated = [MatchedCropExposure(exposure=base), MatchedCropExposure(exposure=base)]
    assert (
        compare_matched_rotation_exposure(
            repeated, repeated, decision13_weighted_total_tie=True
        ).reason
        == "repeated_crop_occurrence_pairing_unresolved"
    )


def test_changing_only_synthetic_nasa_rainfall_changes_a_weighted_tie_order() -> None:
    """Join daily NASA-shaped values to NY-40 CDD and Decision-13 scoring."""

    left_crops = ("maize", "cowpea", "groundnut")
    right_crops = ("cowpea", "groundnut", "maize")
    placements = {
        "A": tuple(zip(left_crops, (3, 4, 5), (0, 3, 6), strict=True)),
        "B": tuple(zip(right_crops, (3, 4, 5), (3, 6, 0), strict=True)),
    }

    def option(name: str, rainfall: PowerParameterSeries) -> RotationOptionEvidence:
        events = tuple(
            CandidatePlantingEvent(
                event=PlantingEventSlot(
                    event_id=f"{name}-{index}",
                    order=index,
                    plot_id="synthetic-one-plot",
                    season_label=f"synthetic-{index}",
                    window_start=date(2027, month, 1),
                    window_end=date(2027, month, 1),
                ),
                crop=CropCandidate(crop_id=crop, display_name=crop.title()),
            )
            for index, (crop, month, _offset) in enumerate(placements[name], 1)
        )
        exposures = []
        for event_order, (crop, month, offset) in enumerate(placements[name], 1):
            calculated = calculate_stage_cdd_exposure(
                _request(
                    crop_id=crop,
                    profile_revision_id=f"{crop}-synthetic-profile-v1",
                    calendar_version_id=f"{crop}-synthetic-calendar-{month}",
                    planting_window_start=date(2027, month, 1),
                    planting_window_end=date(2027, month, 1),
                    stage_offset_min_days=offset,
                    stage_offset_max_days=offset,
                    stage_duration_min_days=2,
                    stage_duration_max_days=2,
                ),
                rainfall,
            )
            assert calculated.status == "assessed"
            exposures.append(MatchedCropExposure(exposure=calculated, event_order=event_order))
        criteria = tuple(
            CriterionEvidence(
                criterion=criterion,
                status="assessed",
                rating="moderate",
                confidence="low",
                rationale="Synthetic comparable criterion rating, not a Ghana claim.",
                comparison_basis=f"synthetic-{criterion}-basis-v1",
                evidence_references=("synthetic-controlled-test",),
                climate_features=(
                    tuple(item.exposure for item in exposures)
                    if criterion == "water_resilience"
                    else ()
                ),
            )
            for criterion in CRITERIA
        )
        return RotationOptionEvidence(
            candidate=RotationCandidate(
                candidate_id=name,
                kind="alternative",
                events=events,
                readiness="needs_review",
                rule_findings=(),
            ),
            criteria=criteria,
            climate_exposures=tuple(exposures),
        )

    def score(rainfall: PowerParameterSeries):
        return score_rotation_options(
            ScoringRequest(options=(option("A", rainfall), option("B", rainfall)))
        )

    first_values = {(month, day): 2.0 for month in (3, 4, 5) for day in range(1, 9)}
    second_values = dict(first_values)
    # A sees wet stages and B dry stages in the first 30-year synthetic series.
    for month, days in ((3, (4, 5)), (4, (7, 8)), (5, (1, 2))):
        for day in days:
            first_values[(month, day)] = 0.0
    # The same candidates and ratings are retained; only rainfall reverses.
    for month, days in ((3, (1, 2)), (4, (4, 5)), (5, (7, 8))):
        for day in days:
            second_values[(month, day)] = 0.0

    first, second = score(_series(first_values)), score(_series(second_values))
    assert [item.candidate.candidate_id for item in first.options] == ["A", "B"]
    assert [item.candidate.candidate_id for item in second.options] == ["B", "A"]
    assert first.ranking.climate_tie_preferences[0].preferred_candidate_id == "A"
    assert second.ranking.climate_tie_preferences[0].preferred_candidate_id == "B"
    assert first.ranking.provisional and second.ranking.provisional

    # A missing crop-stage calculation must not let two other events decide
    # the ordering of the full three-event rotation.
    rainfall = _series(first_values)
    full_a = option("A", rainfall)
    full_b = option("B", rainfall)
    incomplete_b = full_b.model_copy(update={"climate_exposures": full_b.climate_exposures[:2]})
    incomplete = score_rotation_options(ScoringRequest(options=(full_a, incomplete_b)))
    assert incomplete.ranking.climate_tie_preferences == ()
    assert incomplete.ranking.rank_groups == (("A", "B"),)
