"""Unit tests for deterministic calculations over stored environmental values."""

from datetime import UTC, date, datetime, timedelta
from math import fsum

from app.indicators.environmental import (
    INDICATOR_CALCULATION_VERSION,
    EnvironmentalIndicator,
    IndicatorCode,
    IndicatorDataStatus,
    calculate_environmental_indicators,
)
from app.integrations.nasa.power import (
    DailyValue,
    DateCoverage,
    PowerParameterCode,
    PowerParameterMetadata,
    PowerParameterSeries,
    PowerRequest,
    SeasonalSummary,
)
from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    build_snapshot_identity,
)

LOCATION_SECRET = "environmental-indicator-tests-location-key-32-bytes"
START_DATE = date(2024, 1, 1)
END_DATE = date(2024, 1, 2)
RETRIEVED_AT = datetime(2026, 10, 1, tzinfo=UTC)
REQUEST = PowerRequest(
    latitude=0.0,
    longitude=0.0,
    start_date=START_DATE,
    end_date=END_DATE,
)
IDENTITY = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)


def make_series(
    code: PowerParameterCode,
    values: list[float | None],
    *,
    normalized_units: str | None = None,
) -> PowerParameterSeries:
    """Build a validated NY-5 daily series for one requested parameter."""

    dates = [START_DATE + timedelta(days=offset) for offset in range(len(values))]
    valid_values = [value for value in values if value is not None]
    method = "sum" if code == "PRECTOTCORR" else "mean"
    result_units = "mm/season" if code == "PRECTOTCORR" else "°C"
    input_units = normalized_units or ("mm/day" if code == "PRECTOTCORR" else "°C")
    if code == "PRECTOTCORR":
        summary_value = fsum(valid_values) if valid_values else None
    else:
        summary_value = fsum(valid_values) / len(valid_values) if valid_values else None
    expected_days = (END_DATE - START_DATE).days + 1
    valid_days = len(valid_values)
    missing_days = expected_days - valid_days
    coverage = DateCoverage(
        requested_start_date=START_DATE,
        requested_end_date=END_DATE,
        returned_start_date=dates[0] if dates else None,
        returned_end_date=dates[-1] if dates else None,
        expected_days=expected_days,
        valid_days=valid_days,
        missing_days=missing_days,
        coverage_percent=round(valid_days / expected_days * 100, 2),
    )
    status = "unavailable" if not valid_values else "partial" if missing_days else "complete"
    return PowerParameterSeries(
        metadata=PowerParameterMetadata(
            code=code,
            long_name=code,
            source_units=input_units,
            normalized_units=input_units,
            source="MERRA2",
            spatial_resolution="0.5 degree latitude x 0.625 degree longitude",
            fill_value=-999.0,
        ),
        daily_values=[
            DailyValue(date=day, value=value) for day, value in zip(dates, values, strict=True)
        ],
        seasonal_summary=SeasonalSummary(
            method=method,
            value=summary_value,
            units=result_units,
            status=status,
            coverage=coverage,
        ),
    )


def make_snapshot(
    *,
    precipitation: list[float | None] | None = None,
    air_temperature: list[float | None] | None = None,
    maximum_temperature: list[float | None] | None = None,
    precipitation_units: str | None = None,
) -> EnvironmentalSnapshot:
    """Create an in-memory snapshot without requiring Beanie or MongoDB."""

    values = {
        "PRECTOTCORR": precipitation if precipitation is not None else [1.0, 2.0],
        "T2M": air_temperature if air_temperature is not None else [20.0, 22.0],
        "T2M_MAX": maximum_temperature if maximum_temperature is not None else [30.0, 32.0],
    }
    parameters = {
        code: make_series(
            code,
            series_values,
            normalized_units=precipitation_units if code == "PRECTOTCORR" else None,
        )
        for code, series_values in values.items()
    }
    return EnvironmentalSnapshot.model_construct(
        identity=IDENTITY,
        retrieved_at=RETRIEVED_AT,
        parameters=parameters,
        request_contexts=[],
    )


def indicators_by_code(
    snapshot: EnvironmentalSnapshot,
    *,
    data_status: IndicatorDataStatus = "live",
) -> dict[IndicatorCode, EnvironmentalIndicator]:
    indicators = calculate_environmental_indicators(snapshot, data_status=data_status)
    return {indicator.code: indicator for indicator in indicators}


def test_complete_series_produce_research_defined_indicators_deterministically() -> None:
    snapshot = make_snapshot(precipitation=[1.5, 2.5], air_temperature=[20.0, 22.0])

    first = calculate_environmental_indicators(snapshot, data_status="live")
    second = calculate_environmental_indicators(snapshot, data_status="live")
    results = {indicator.code: indicator for indicator in first}

    rainfall = results["seasonal_precipitation_total"]
    mean_temperature = results["mean_daily_air_temperature"]
    mean_maximum = results["mean_daily_maximum_air_temperature"]
    assert rainfall.value == 4.0
    assert rainfall.units == "mm/season"
    assert rainfall.calculation_method == "sum"
    assert mean_temperature.value == 21.0
    assert mean_temperature.units == "°C"
    assert mean_temperature.calculation_method == "mean"
    assert mean_maximum.value == 31.0
    assert rainfall.status == mean_temperature.status == mean_maximum.status == "complete"
    assert rainfall.data_status == "live"
    assert rainfall.source == "MERRA2"
    assert rainfall.period_start == START_DATE
    assert rainfall.period_end == END_DATE
    assert rainfall.retrieved_at == RETRIEVED_AT
    assert rainfall.spatial_resolution is not None
    assert rainfall.coverage.expected_days == 2
    assert rainfall.coverage.valid_days == 2
    assert rainfall.coverage.missing_days == 0
    assert rainfall.calculation_version == INDICATOR_CALCULATION_VERSION
    assert all(indicator.name and indicator.definition for indicator in first)
    assert all(indicator.source == "MERRA2" for indicator in first)
    assert all(indicator.period_start == START_DATE for indicator in first)
    assert all(indicator.period_end == END_DATE for indicator in first)
    assert all(indicator.data_status == "live" for indicator in first)
    assert all(
        indicator.calculation_version == INDICATOR_CALCULATION_VERSION for indicator in first
    )
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]


def test_partial_data_uses_valid_days_and_marks_each_indicator_explicitly() -> None:
    snapshot = make_snapshot(
        precipitation=[2.0, None],
        air_temperature=[None, 24.0],
        maximum_temperature=[None, None],
    )

    results = indicators_by_code(snapshot, data_status="cached")
    rainfall = results["seasonal_precipitation_total"]
    mean_temperature = results["mean_daily_air_temperature"]
    mean_maximum = results["mean_daily_maximum_air_temperature"]

    assert rainfall.value == 2.0
    assert rainfall.status == "partial"
    assert rainfall.data_status == "cached"
    assert rainfall.coverage.valid_days == 1
    assert rainfall.coverage.missing_days == 1
    assert rainfall.coverage.coverage_percent == 50.0
    assert "not imputed" in rainfall.warnings[0]
    assert mean_temperature.value == 24.0
    assert mean_temperature.status == "partial"
    assert mean_maximum.value is None
    assert mean_maximum.status == "unavailable"


def test_valid_zero_precipitation_is_distinct_from_missing_data() -> None:
    snapshot = make_snapshot(precipitation=[0.0, 0.0])

    rainfall = indicators_by_code(snapshot)["seasonal_precipitation_total"]

    assert rainfall.value == 0.0
    assert rainfall.status == "complete"
    assert rainfall.coverage.valid_days == 2
    assert rainfall.coverage.missing_days == 0


def test_missing_parameter_values_return_none_and_not_zero() -> None:
    snapshot = make_snapshot(
        precipitation=[None, None],
        air_temperature=[None, None],
        maximum_temperature=[None, None],
    )

    results = calculate_environmental_indicators(snapshot, data_status="unavailable")

    assert len(results) == 3
    assert all(indicator.value is None for indicator in results)
    assert all(indicator.status == "unavailable" for indicator in results)
    assert all(indicator.coverage.valid_days == 0 for indicator in results)
    assert all(indicator.coverage.missing_days == 2 for indicator in results)


def test_missing_parameter_or_unrecognized_units_is_unavailable() -> None:
    snapshot = make_snapshot(precipitation_units="inches/day")
    missing_parameter_snapshot = snapshot.model_copy(
        update={"parameters": {"PRECTOTCORR": snapshot.parameters["PRECTOTCORR"]}}
    )

    unsupported = indicators_by_code(snapshot)["seasonal_precipitation_total"]
    missing = indicators_by_code(missing_parameter_snapshot)["mean_daily_air_temperature"]

    assert unsupported.value is None
    assert unsupported.status == "unavailable"
    assert "Expected normalized units mm/day" in unsupported.warnings[0]
    assert missing.value is None
    assert missing.status == "unavailable"
    assert missing.coverage.missing_days == 2


def test_duplicate_and_non_finite_daily_records_are_reported_as_missing() -> None:
    snapshot = make_snapshot()
    precipitation = snapshot.parameters["PRECTOTCORR"].model_copy(
        update={
            "daily_values": [
                DailyValue(date=START_DATE, value=1.0),
                DailyValue(date=START_DATE, value=3.0),
                DailyValue.model_construct(date=END_DATE, value=float("nan")),
            ]
        }
    )
    snapshot = snapshot.model_copy(
        update={"parameters": {**snapshot.parameters, "PRECTOTCORR": precipitation}}
    )

    rainfall = indicators_by_code(snapshot)["seasonal_precipitation_total"]

    assert rainfall.value is None
    assert rainfall.status == "unavailable"
    assert rainfall.coverage.valid_days == 0
    assert rainfall.coverage.missing_days == 2
    assert len(rainfall.warnings) == 3
