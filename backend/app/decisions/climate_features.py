"""Pure, provisional NY-40 historical crop-stage climate assessment.

This module reads normalized NASA POWER daily precipitation supplied by its
caller. It neither fetches data nor assumes that dry days measure crop damage,
effective rainfall, soil water, or future weather. All stage and calendar
values must come from a scoped, versioned source supplied by the caller.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from math import isfinite
from statistics import median
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.nasa.power import PowerParameterSeries

CDD_METHOD_VERSION = "ny40-stage-cdd-v1"
CLIMATE_TIE_POLICY_VERSION = "ny40-matched-crop-tie-v1"
REFERENCE_START_YEAR = 1991
REFERENCE_END_YEAR = 2020
DRY_DAY_THRESHOLD_MM = 1.0  # ETCCDI/Climpact meteorological definition; not a crop threshold.
MAX_PLACEMENTS = 10_000  # Explicit computational guard; excess is not approximated.
MAX_REFERENCE_DAY_EVALUATIONS = 5_000_000  # Another exact-work guard for long stage ranges.

EvidenceStatus = Literal["unknown", "provisional", "locally_reviewed", "conflicted"]
ExposureStatus = Literal["assessed", "not_assessed"]
DominanceStatus = Literal[
    "left_preferred", "right_preferred", "incomparable", "not_assessed", "not_applicable"
]


class StageCDDRequest(BaseModel):
    """Sourced crop/event scope and ranges; unknown values stay null.

    Offsets count calendar days from planting (day zero). Stage durations are
    inclusive. ``maturity_min_days`` is the earliest supported harvest from
    planting; the full stage must fit before that earliest possible harvest.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    crop_id: str = Field(min_length=1)
    variety_key: str | None = None
    production_system_key: str | None = None
    stage_key: str = Field(min_length=1)
    planting_window_start: date | None = None
    planting_window_end: date | None = None
    stage_offset_min_days: int | None = None
    stage_offset_max_days: int | None = None
    stage_duration_min_days: int | None = None
    stage_duration_max_days: int | None = None
    maturity_min_days: int | None = None
    maturity_max_days: int | None = None
    profile_revision_id: str | None = None
    calendar_version_id: str | None = None
    calendar_source: str | None = None
    stage_source: str | None = None
    sensitivity_source: str | None = None
    maturity_source: str | None = None
    evidence_status: EvidenceStatus = "unknown"
    source_snapshot_id: str | None = None
    source_products: tuple[str, ...] = ()
    snapshot_retrieved_at: datetime | None = None
    snapshot_status: str | None = None


class PlacementCDD(BaseModel):
    """Auditable 30-year values for one feasible planting/stage placement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_planting_date: date
    stage_offset_days: int
    stage_duration_days: int
    annual_cdd_days: tuple[int, ...]
    median_cdd_days: float


class StageCDDExposure(BaseModel):
    """Historical exposure interval; null bounds mean no assessed value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_key: Literal["stage_cdd_exposure"] = "stage_cdd_exposure"
    method_version: str = CDD_METHOD_VERSION
    status: ExposureStatus
    reason: str | None = None
    crop_id: str
    variety_key: str | None
    production_system_key: str | None
    stage_key: str
    planting_window_start: date | None = None
    planting_window_end: date | None = None
    profile_revision_id: str | None
    calendar_version_id: str | None
    evidence_status: EvidenceStatus
    source_snapshot_id: str | None
    source_products: tuple[str, ...]
    snapshot_retrieved_at: datetime | None = None
    snapshot_status: str | None = None
    spatial_resolution: str | None = None
    reference_start_year: int = REFERENCE_START_YEAR
    reference_end_year: int = REFERENCE_END_YEAR
    statistic: Literal["median_of_annual_cdd"] = "median_of_annual_cdd"
    units: Literal["days"] = "days"
    dry_day_definition: Literal["PRECTOTCORR < 1 mm/day"] = "PRECTOTCORR < 1 mm/day"
    exposure_min_days: float | None = None
    exposure_max_days: float | None = None
    feasible_placement_count: int = 0
    complete_years_per_placement: int = 0
    placements: tuple[PlacementCDD, ...] = ()
    interpretation: str = (
        "Historical meteorological dry-spell exposure at a sourced crop stage; "
        "provisional, not a forecast, crop-water balance, or damage probability."
    )


def _exposure(
    request: StageCDDRequest,
    precipitation: PowerParameterSeries | None,
    *,
    status: ExposureStatus,
    reason: str | None = None,
    placements: tuple[PlacementCDD, ...] = (),
) -> StageCDDExposure:
    medians = [placement.median_cdd_days for placement in placements]
    return StageCDDExposure(
        status=status,
        reason=reason,
        crop_id=request.crop_id,
        variety_key=request.variety_key,
        production_system_key=request.production_system_key,
        stage_key=request.stage_key,
        planting_window_start=request.planting_window_start,
        planting_window_end=request.planting_window_end,
        profile_revision_id=request.profile_revision_id,
        calendar_version_id=request.calendar_version_id,
        evidence_status=request.evidence_status,
        source_snapshot_id=request.source_snapshot_id,
        source_products=(
            request.source_products
            or (
                (precipitation.metadata.source,)
                if precipitation is not None and precipitation.metadata.source
                else ()
            )
        ),
        snapshot_retrieved_at=request.snapshot_retrieved_at,
        snapshot_status=request.snapshot_status,
        spatial_resolution=(
            precipitation.metadata.spatial_resolution if precipitation is not None else None
        ),
        exposure_min_days=min(medians) if medians else None,
        exposure_max_days=max(medians) if medians else None,
        feasible_placement_count=len(placements),
        complete_years_per_placement=(
            REFERENCE_END_YEAR - REFERENCE_START_YEAR + 1 if placements else 0
        ),
        placements=placements,
    )


def _dates_inclusive(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _longest_dry_run(values: Sequence[float]) -> int:
    longest = current = 0
    for value in values:
        if value < DRY_DAY_THRESHOLD_MM:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def calculate_stage_cdd_exposure(
    request: StageCDDRequest,
    precipitation: PowerParameterSeries | None,
) -> StageCDDExposure:
    """Return min/max 1991–2020 annual-median CDD over *all* feasible placements.

    Each planting day, sourced stage offset, and sourced duration is examined.
    A placement must have all 30 complete matching annual windows. No missing
    value is treated as zero. A Feb-29 planting or a cross-year crop/stage
    placement is withheld until a reviewed alignment rule exists. Other leap
    days count normally because offset/duration are calendar-day counts.
    """

    def missing(reason: str) -> StageCDDExposure:
        return _exposure(request, precipitation, status="not_assessed", reason=reason)

    if precipitation is None:
        return missing("reference_snapshot_missing")
    if precipitation.metadata.code != "PRECTOTCORR":
        return missing("precipitation_parameter_required")
    if precipitation.metadata.normalized_units != "mm/day":
        return missing("precipitation_units_incompatible")
    if request.evidence_status in {"unknown", "conflicted"}:
        return missing("crop_stage_or_calendar_evidence_unresolved")
    if not all(
        (
            request.profile_revision_id,
            request.calendar_version_id,
            request.calendar_source,
            request.stage_source,
            request.sensitivity_source,
            request.maturity_source,
            request.source_snapshot_id,
        )
    ):
        return missing("scoped_evidence_or_provenance_missing")
    if not (request.source_products or precipitation.metadata.source):
        return missing("source_product_missing")

    start, end = request.planting_window_start, request.planting_window_end
    if start is None or end is None or start > end:
        return missing("planting_window_missing_or_invalid")
    if start.year != end.year:
        return missing("cross_year_window_alignment_unresolved")
    if any(day.month == 2 and day.day == 29 for day in _dates_inclusive(start, end)):
        return missing("leap_day_planting_alignment_unresolved")

    offset_min, offset_max = request.stage_offset_min_days, request.stage_offset_max_days
    duration_min, duration_max = request.stage_duration_min_days, request.stage_duration_max_days
    maturity_min, maturity_max = request.maturity_min_days, request.maturity_max_days
    if any(value is None for value in (offset_min, offset_max, duration_min, duration_max)):
        return missing("stage_timing_missing")
    if maturity_min is None or maturity_max is None:
        return missing("maturity_timing_missing")
    # The preceding checks establish these as integers for Python and type checkers.
    assert offset_min is not None and offset_max is not None
    assert duration_min is not None and duration_max is not None
    if (
        offset_min < 0
        or offset_max < offset_min
        or duration_min < 1
        or duration_max < duration_min
        or maturity_min < 1
        or maturity_max < maturity_min
    ):
        return missing("stage_or_maturity_range_invalid")
    if offset_max + duration_max > maturity_min:
        return missing("stage_may_extend_beyond_earliest_harvest")

    placement_count = (
        ((end - start).days + 1) * (offset_max - offset_min + 1) * (duration_max - duration_min + 1)
    )
    if placement_count > MAX_PLACEMENTS:
        return missing("too_many_feasible_placements_for_exact_assessment")
    maximum_day_evaluations = (
        placement_count * (REFERENCE_END_YEAR - REFERENCE_START_YEAR + 1) * duration_max
    )
    if maximum_day_evaluations > MAX_REFERENCE_DAY_EVALUATIONS:
        return missing("reference_work_exceeds_exact_assessment_budget")

    daily_by_date: dict[date, float | None] = {}
    for item in precipitation.daily_values:
        if item.date in daily_by_date:
            return missing("duplicate_reference_date")
        daily_by_date[item.date] = item.value

    placements: list[PlacementCDD] = []
    for planting in _dates_inclusive(start, end):
        for offset in range(offset_min, offset_max + 1):
            for duration in range(duration_min, duration_max + 1):
                try:
                    candidate_stage_end = planting + timedelta(days=offset + duration - 1)
                except OverflowError:
                    return missing("stage_date_outside_supported_calendar")
                if candidate_stage_end.year != planting.year:
                    return missing("cross_year_stage_alignment_unresolved")
                annual_cdd: list[int] = []
                for year in range(REFERENCE_START_YEAR, REFERENCE_END_YEAR + 1):
                    # Feb-29 plantings were rejected above. Day offsets preserve
                    # the sourced number of days after planting in leap years.
                    reference_planting = date(year, planting.month, planting.day)
                    try:
                        stage_start = reference_planting + timedelta(days=offset)
                        stage_end = stage_start + timedelta(days=duration - 1)
                    except OverflowError:
                        return missing("stage_date_outside_supported_calendar")
                    if stage_end.year != year:
                        return missing("cross_year_stage_alignment_unresolved")
                    values: list[float] = []
                    for day in _dates_inclusive(stage_start, stage_end):
                        value = daily_by_date.get(day)
                        if value is None or value == precipitation.metadata.fill_value:
                            return missing("reference_window_incomplete")
                        if not isfinite(value) or value < 0:
                            return missing("reference_precipitation_invalid")
                        values.append(value)
                    annual_cdd.append(_longest_dry_run(values))
                placements.append(
                    PlacementCDD(
                        candidate_planting_date=planting,
                        stage_offset_days=offset,
                        stage_duration_days=duration,
                        annual_cdd_days=tuple(annual_cdd),
                        median_cdd_days=float(median(annual_cdd)),
                    )
                )
    return _exposure(request, precipitation, status="assessed", placements=tuple(placements))


class MatchedCropExposure(BaseModel):
    """One occurrence in a rotation; explicit index disambiguates repeats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exposure: StageCDDExposure
    occurrence_index: int | None = Field(default=None, ge=1)
    event_order: int | None = Field(default=None, ge=1, le=3)


class CropExposureComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    crop_id: str
    variety_key: str | None
    production_system_key: str | None
    stage_key: str
    occurrence_index: int
    left_interval_days: tuple[float, float]
    right_interval_days: tuple[float, float]
    relationship: Literal["left_strictly_lower", "right_strictly_lower", "equal", "overlap"]


class ClimateDominance(BaseModel):
    """Provisional partial-order result used only after a Decision-13 score tie."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: DominanceStatus
    reason: str
    policy_version: str = CLIMATE_TIE_POLICY_VERSION
    policy_status: Literal["provisional"] = "provisional"
    matched_crop_count: int = 0
    comparisons: tuple[CropExposureComparison, ...] = ()


def _scope(exposure: StageCDDExposure) -> tuple[str, str | None, str | None, str]:
    return (
        exposure.crop_id,
        exposure.variety_key,
        exposure.production_system_key,
        exposure.stage_key,
    )


def _indexed(
    entries: Sequence[MatchedCropExposure],
) -> dict[tuple[str, str | None, str | None, str, int], StageCDDExposure] | None:
    counts = Counter(_scope(entry.exposure) for entry in entries)
    seen: defaultdict[tuple[str, str | None, str | None, str], set[int]] = defaultdict(set)
    indexed: dict[tuple[str, str | None, str | None, str, int], StageCDDExposure] = {}
    for entry in entries:
        scope = _scope(entry.exposure)
        if counts[scope] > 1 and entry.occurrence_index is None:
            return None
        index = entry.occurrence_index or 1
        if index in seen[scope]:
            return None
        seen[scope].add(index)
        indexed[(*scope, index)] = entry.exposure
    return indexed


def compare_matched_rotation_exposure(
    left: Sequence[MatchedCropExposure],
    right: Sequence[MatchedCropExposure],
    *,
    decision13_weighted_total_tie: bool,
    expected_event_count: int | None = None,
) -> ClimateDominance:
    """Prefer only when every matched crop/stage is strictly lower at a score tie.

    This never changes criterion ratings or adds CDD points. It cannot compare
    different crop mixes, missing assessments, uncertain duplicate pairings,
    different reference products, or overlapping exposure intervals.
    """

    def result(
        status: DominanceStatus,
        reason: str,
        comparisons: Sequence[CropExposureComparison] = (),
    ) -> ClimateDominance:
        return ClimateDominance(
            status=status,
            reason=reason,
            matched_crop_count=len(comparisons),
            comparisons=tuple(comparisons),
        )

    if not decision13_weighted_total_tie:
        return result("not_applicable", "decision13_weighted_totals_not_tied")
    if not left or len(left) != len(right):
        return result("incomparable", "rotation_crop_count_differs_or_empty")
    if expected_event_count is not None:
        expected_orders = set(range(1, expected_event_count + 1))
        for entries in (left, right):
            assessed_orders = {
                entry.event_order for entry in entries if entry.exposure.status == "assessed"
            }
            if assessed_orders != expected_orders or any(
                entry.event_order is None for entry in entries
            ):
                return result("not_assessed", "candidate_event_stage_coverage_incomplete")
    if Counter(_scope(item.exposure) for item in left) != Counter(
        _scope(item.exposure) for item in right
    ):
        return result("incomparable", "different_crop_scope_multiset")
    left_map, right_map = _indexed(left), _indexed(right)
    if left_map is None or right_map is None or left_map.keys() != right_map.keys():
        return result("incomparable", "repeated_crop_occurrence_pairing_unresolved")

    comparisons: list[CropExposureComparison] = []
    left_strict_for_every_pair = right_strict_for_every_pair = True
    for key in sorted(
        left_map, key=lambda item: tuple("" if value is None else str(value) for value in item)
    ):
        a, b = left_map[key], right_map[key]
        if a.status != "assessed" or b.status != "assessed":
            return result("not_assessed", "one_or_more_crop_stage_exposures_missing")
        if (
            not a.source_snapshot_id
            or not b.source_snapshot_id
            or not a.profile_revision_id
            or not b.profile_revision_id
            or a.evidence_status in {"unknown", "conflicted"}
            or b.evidence_status in {"unknown", "conflicted"}
        ):
            return result("not_assessed", "crop_stage_provenance_missing_or_unresolved")
        if (
            a.method_version != b.method_version
            or a.method_version != CDD_METHOD_VERSION
            or a.reference_start_year != b.reference_start_year
            or a.reference_end_year != b.reference_end_year
            or a.reference_start_year != REFERENCE_START_YEAR
            or a.reference_end_year != REFERENCE_END_YEAR
            or a.source_snapshot_id != b.source_snapshot_id
            or a.profile_revision_id != b.profile_revision_id
            or a.spatial_resolution != b.spatial_resolution
        ):
            return result("incomparable", "climate_reference_or_profile_differs")
        bounds = (
            a.exposure_min_days,
            a.exposure_max_days,
            b.exposure_min_days,
            b.exposure_max_days,
        )
        if any(value is None or not isfinite(value) or value < 0 for value in bounds):
            return result("not_assessed", "crop_stage_exposure_interval_missing_or_invalid")
        assert a.exposure_min_days is not None and a.exposure_max_days is not None
        assert b.exposure_min_days is not None and b.exposure_max_days is not None
        if a.exposure_max_days < a.exposure_min_days or b.exposure_max_days < b.exposure_min_days:
            return result("not_assessed", "crop_stage_exposure_interval_missing_or_invalid")
        a_strictly_lower = a.exposure_max_days < b.exposure_min_days
        b_strictly_lower = b.exposure_max_days < a.exposure_min_days
        left_strict_for_every_pair &= a_strictly_lower
        right_strict_for_every_pair &= b_strictly_lower
        if a_strictly_lower:
            relationship = "left_strictly_lower"
        elif b_strictly_lower:
            relationship = "right_strictly_lower"
        elif (a.exposure_min_days, a.exposure_max_days) == (
            b.exposure_min_days,
            b.exposure_max_days,
        ):
            relationship = "equal"
        else:
            relationship = "overlap"
        comparisons.append(
            CropExposureComparison(
                crop_id=key[0],
                variety_key=key[1],
                production_system_key=key[2],
                stage_key=key[3],
                occurrence_index=key[4],
                left_interval_days=(a.exposure_min_days, a.exposure_max_days),
                right_interval_days=(b.exposure_min_days, b.exposure_max_days),
                relationship=relationship,
            )
        )
    if left_strict_for_every_pair:
        return result(
            "left_preferred",
            "every_matched_crop_stage_interval_strictly_lower_on_left",
            comparisons,
        )
    if right_strict_for_every_pair:
        return result(
            "right_preferred",
            "every_matched_crop_stage_interval_strictly_lower_on_right",
            comparisons,
        )
    return result("incomparable", "equal_overlapping_or_mixed_crop_stage_exposure", comparisons)
