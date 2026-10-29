"""Calculate traceable MVP environmental indicators from persisted daily values."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.nasa.power import PowerParameterCode, PowerParameterSeries
from app.models.environmental_snapshots import EnvironmentalSnapshot, SnapshotSeasonContext

IndicatorCode = Literal[
    "seasonal_precipitation_total",
    "mean_daily_air_temperature",
    "mean_daily_maximum_air_temperature",
]
IndicatorStatus = Literal["complete", "partial", "unavailable"]
IndicatorDataStatus = Literal["live", "cached", "unavailable"]
CalculationMethod = Literal["sum", "mean"]

INDICATOR_CALCULATION_VERSION = "ny7-v1"


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    """Static research-backed meaning and input contract for one indicator."""

    code: IndicatorCode
    name: str
    definition: str
    parameter: PowerParameterCode
    method: CalculationMethod
    expected_input_units: str
    output_units: str


INDICATOR_DEFINITIONS = (
    IndicatorDefinition(
        code="seasonal_precipitation_total",
        name="Seasonal precipitation total",
        definition="Sum of valid daily precipitation values over the requested period.",
        parameter="PRECTOTCORR",
        method="sum",
        expected_input_units="mm/day",
        output_units="mm/season",
    ),
    IndicatorDefinition(
        code="mean_daily_air_temperature",
        name="Mean daily air temperature",
        definition="Arithmetic mean of valid daily T2M values over the requested period.",
        parameter="T2M",
        method="mean",
        expected_input_units="°C",
        output_units="°C",
    ),
    IndicatorDefinition(
        code="mean_daily_maximum_air_temperature",
        name="Mean daily maximum air temperature",
        definition=(
            "Arithmetic mean of valid daily T2M_MAX values; this is not the single hottest day."
        ),
        parameter="T2M_MAX",
        method="mean",
        expected_input_units="°C",
        output_units="°C",
    ),
)


class IndicatorCoverage(BaseModel):
    """Counts describe how much of the requested inclusive period has valid data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_days: int = Field(gt=0)
    valid_days: int = Field(ge=0)
    missing_days: int = Field(ge=0)
    coverage_percent: float = Field(ge=0, le=100)


class EnvironmentalIndicator(BaseModel):
    """One calculated value with the metadata needed to explain and trace it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: IndicatorCode
    name: str
    definition: str
    calculation_method: CalculationMethod
    value: float | None
    units: str
    status: IndicatorStatus
    data_status: IndicatorDataStatus
    source: str | None
    period_start: date
    period_end: date
    retrieved_at: datetime | None
    coverage: IndicatorCoverage
    spatial_resolution: str | None
    season_label: str | None = None
    calendar_source_version: str | None = None
    crop: str | None = None
    calculation_version: str = INDICATOR_CALCULATION_VERSION
    warnings: tuple[str, ...] = ()


def calculate_environmental_indicators(
    snapshot: EnvironmentalSnapshot,
    *,
    data_status: IndicatorDataStatus,
    season_context: SnapshotSeasonContext | None = None,
) -> tuple[EnvironmentalIndicator, ...]:
    """Calculate all NY-13 environmental indicators without I/O or mutation."""

    period_start = snapshot.identity.start_date
    period_end = snapshot.identity.end_date
    expected_days = (period_end - period_start).days + 1
    parameters = snapshot.parameters

    return tuple(
        _calculate_indicator(
            definition,
            parameters.get(definition.parameter),
            period_start=period_start,
            period_end=period_end,
            expected_days=expected_days,
            retrieved_at=snapshot.retrieved_at,
            data_status=data_status,
            season_context=season_context,
        )
        for definition in INDICATOR_DEFINITIONS
    )


def unavailable_environmental_indicators(
    period_start: date,
    period_end: date,
    *,
    season_context: SnapshotSeasonContext | None = None,
    warnings: tuple[str, ...] = (),
) -> tuple[EnvironmentalIndicator, ...]:
    """Describe an unavailable snapshot without inventing values or retrieval time."""

    if period_end < period_start:
        raise ValueError("Indicator period end must be on or after its start")
    expected_days = (period_end - period_start).days + 1
    no_snapshot_warning = "No persisted environmental snapshot is available for this request."
    return tuple(
        _unavailable_indicator(
            definition,
            period_start=period_start,
            period_end=period_end,
            expected_days=expected_days,
            retrieved_at=None,
            data_status="unavailable",
            warning=no_snapshot_warning,
            season_context=season_context,
            additional_warnings=warnings,
        )
        for definition in INDICATOR_DEFINITIONS
    )


def _calculate_indicator(
    definition: IndicatorDefinition,
    series: PowerParameterSeries | None,
    *,
    period_start: date,
    period_end: date,
    expected_days: int,
    retrieved_at: datetime | None,
    data_status: IndicatorDataStatus,
    season_context: SnapshotSeasonContext | None,
) -> EnvironmentalIndicator:
    if series is None:
        return _unavailable_indicator(
            definition,
            period_start=period_start,
            period_end=period_end,
            expected_days=expected_days,
            retrieved_at=retrieved_at,
            data_status=data_status,
            warning=f"Required NASA POWER parameter {definition.parameter} is missing.",
            season_context=season_context,
        )

    values_by_date, input_warnings = _values_by_date(series, period_start, period_end)
    valid_values = [
        value
        for day in _period_days(period_start, period_end)
        if (value := values_by_date.get(day)) is not None and math.isfinite(value)
    ]
    missing_days = expected_days - len(valid_values)
    coverage = _coverage(expected_days, len(valid_values), missing_days)
    source = series.metadata.source
    resolution = series.metadata.spatial_resolution

    if series.metadata.normalized_units != definition.expected_input_units:
        warning = (
            f"Expected normalized units {definition.expected_input_units}; received "
            f"{series.metadata.normalized_units}. The indicator was not calculated."
        )
        return _make_indicator(
            definition,
            None,
            "unavailable",
            data_status,
            source,
            resolution,
            period_start,
            period_end,
            retrieved_at,
            coverage,
            (*input_warnings, warning),
            season_context,
        )

    if not valid_values:
        warning = f"{definition.parameter} has no valid daily values in the requested period."
        return _make_indicator(
            definition,
            None,
            "unavailable",
            data_status,
            source,
            resolution,
            period_start,
            period_end,
            retrieved_at,
            coverage,
            (*input_warnings, warning),
            season_context,
        )

    value = math.fsum(valid_values)
    if definition.method == "mean":
        value /= len(valid_values)

    status: IndicatorStatus = "partial" if missing_days else "complete"
    warnings = input_warnings
    if missing_days:
        warnings += (
            f"Partial coverage: {len(valid_values)} of {expected_days} days are valid; "
            "missing values were not imputed.",
        )
    return _make_indicator(
        definition,
        value,
        status,
        data_status,
        source,
        resolution,
        period_start,
        period_end,
        retrieved_at,
        coverage,
        warnings,
        season_context,
    )


def _values_by_date(
    series: PowerParameterSeries,
    period_start: date,
    period_end: date,
) -> tuple[dict[date, float | None], tuple[str, ...]]:
    values: dict[date, float | None] = {}
    warnings: list[str] = []
    for daily_value in series.daily_values:
        if not period_start <= daily_value.date <= period_end:
            continue
        if daily_value.date in values:
            values[daily_value.date] = None
            warnings.append(
                f"Duplicate daily record for {daily_value.date.isoformat()} was treated as missing."
            )
            continue
        values[daily_value.date] = daily_value.value

    for day, value in tuple(values.items()):
        if value is not None and not math.isfinite(value):
            values[day] = None
            warnings.append(
                f"Non-finite value for {day.isoformat()} was treated as missing, not as zero."
            )
    return values, tuple(warnings)


def _period_days(period_start: date, period_end: date) -> Iterable[date]:
    day_count = (period_end - period_start).days + 1
    return (period_start + timedelta(days=offset) for offset in range(day_count))


def _coverage(expected_days: int, valid_days: int, missing_days: int) -> IndicatorCoverage:
    return IndicatorCoverage(
        expected_days=expected_days,
        valid_days=valid_days,
        missing_days=missing_days,
        coverage_percent=round(valid_days / expected_days * 100, 2),
    )


def _unavailable_indicator(
    definition: IndicatorDefinition,
    *,
    period_start: date,
    period_end: date,
    expected_days: int,
    retrieved_at: datetime | None,
    data_status: IndicatorDataStatus,
    warning: str,
    season_context: SnapshotSeasonContext | None,
    additional_warnings: tuple[str, ...] = (),
) -> EnvironmentalIndicator:
    return _make_indicator(
        definition,
        None,
        "unavailable",
        data_status,
        None,
        None,
        period_start,
        period_end,
        retrieved_at,
        _coverage(expected_days, 0, expected_days),
        (warning, *additional_warnings),
        season_context,
    )


def _make_indicator(
    definition: IndicatorDefinition,
    value: float | None,
    status: IndicatorStatus,
    data_status: IndicatorDataStatus,
    source: str | None,
    spatial_resolution: str | None,
    period_start: date,
    period_end: date,
    retrieved_at: datetime | None,
    coverage: IndicatorCoverage,
    warnings: tuple[str, ...],
    season_context: SnapshotSeasonContext | None,
) -> EnvironmentalIndicator:
    return EnvironmentalIndicator(
        code=definition.code,
        name=definition.name,
        definition=definition.definition,
        calculation_method=definition.method,
        value=value,
        units=definition.output_units,
        status=status,
        data_status=data_status,
        source=source,
        period_start=period_start,
        period_end=period_end,
        retrieved_at=retrieved_at,
        season_label=season_context.season_label if season_context else None,
        calendar_source_version=(
            season_context.calendar_source_version if season_context else None
        ),
        crop=season_context.crop if season_context else None,
        coverage=coverage,
        spatial_resolution=spatial_resolution,
        warnings=warnings,
    )
