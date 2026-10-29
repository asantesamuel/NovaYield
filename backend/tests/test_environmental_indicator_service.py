"""Integration tests for NY-6 retrievals feeding the NY-7 calculator."""

import json
from datetime import UTC, date, datetime

import pytest

from app.integrations.nasa.power import (
    DailyValue,
    DateCoverage,
    PowerParameterMetadata,
    PowerParameterSeries,
    PowerRequest,
    SeasonalSummary,
)
from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotSeasonContext,
    build_snapshot_identity,
)
from app.services.environmental_indicators import EnvironmentalIndicatorService
from app.services.environmental_snapshots import (
    DataStatus,
    FreshnessAssessment,
    SnapshotRetrieval,
)

LOCATION_SECRET = "indicator-service-tests-location-key-at-least-32-bytes"
START_DATE = date(2024, 1, 1)
END_DATE = date(2024, 1, 2)
RETRIEVED_AT = datetime(2026, 10, 1, tzinfo=UTC)


def make_request(
    *,
    end_date: date = END_DATE,
    season_label: str | None = "2024 major season",
    crop: str | None = "maize",
) -> PowerRequest:
    """Create the same request contract NY-6 receives, with no live network call."""

    return PowerRequest(
        latitude=5.6037,
        longitude=-0.187,
        start_date=START_DATE,
        end_date=end_date,
        season_label=season_label,
        calendar_source_version="ny13-research-v1",
        crop=crop,
    )


def make_snapshot(request: PowerRequest) -> EnvironmentalSnapshot:
    """Build a small valid persisted-series shape without connecting to MongoDB."""

    coverage = DateCoverage(
        requested_start_date=START_DATE,
        requested_end_date=END_DATE,
        returned_start_date=START_DATE,
        returned_end_date=END_DATE,
        expected_days=2,
        valid_days=2,
        missing_days=0,
        coverage_percent=100.0,
    )
    temperature = PowerParameterSeries(
        metadata=PowerParameterMetadata(
            code="T2M",
            long_name="Temperature at 2 Meters",
            source_units="°C",
            normalized_units="°C",
            source="MERRA2",
            spatial_resolution="0.5 degree latitude x 0.625 degree longitude",
            fill_value=-999.0,
        ),
        daily_values=[
            DailyValue(date=START_DATE, value=20.0),
            DailyValue(date=END_DATE, value=22.0),
        ],
        seasonal_summary=SeasonalSummary(
            method="mean",
            value=21.0,
            units="°C",
            status="complete",
            coverage=coverage,
        ),
    )
    previous_context = SnapshotSeasonContext(
        season_label="old season",
        calendar_source_version="old-calendar",
        crop="sorghum",
    )
    return EnvironmentalSnapshot.model_construct(
        identity=build_snapshot_identity(request, location_secret=LOCATION_SECRET),
        retrieved_at=RETRIEVED_AT,
        parameters={"T2M": temperature},
        request_contexts=[previous_context],
    )


def make_retrieval(
    snapshot: EnvironmentalSnapshot | None,
    *,
    data_status: DataStatus,
    warnings: tuple[str, ...] = (),
) -> SnapshotRetrieval:
    """Represent the relevant NY-6 service outcome without repository I/O."""

    return SnapshotRetrieval(
        snapshot=snapshot,
        data_status=data_status,
        cache_action="hit" if snapshot is not None else "unavailable",
        freshness=FreshnessAssessment("unknown", None, "Test retrieval state."),
        refresh_attempted=False,
        warnings=warnings,
    )


@pytest.mark.parametrize("data_status", ["live", "cached"])
def test_calculation_uses_matching_snapshot_and_current_request_context(
    data_status: DataStatus,
) -> None:
    request = make_request()
    retrieval = make_retrieval(
        make_snapshot(request),
        data_status=data_status,
        warnings=("A NASA refresh failed; this result uses the stored snapshot.",),
    )

    indicators = EnvironmentalIndicatorService().calculate(retrieval, request)
    by_code = {indicator.code: indicator for indicator in indicators}

    assert by_code["mean_daily_air_temperature"].value == 21.0
    assert all(indicator.data_status == data_status for indicator in indicators)
    assert all(indicator.season_label == "2024 major season" for indicator in indicators)
    assert all(indicator.crop == "maize" for indicator in indicators)
    assert all(indicator.calendar_source_version == "ny13-research-v1" for indicator in indicators)
    assert all(indicator.retrieved_at == RETRIEVED_AT for indicator in indicators)
    assert all(indicator.season_label != "old season" for indicator in indicators)
    assert all(
        "A NASA refresh failed; this result uses the stored snapshot." in indicator.warnings
        for indicator in indicators
    )

    indicator_documents = [indicator.model_dump(mode="json") for indicator in indicators]
    serialized = json.dumps(indicator_documents)
    assert all(
        "latitude" not in document and "longitude" not in document
        for document in indicator_documents
    )
    assert "5.6037" not in serialized
    assert "-0.187" not in serialized


def test_missing_snapshot_returns_explicit_unavailable_indicators() -> None:
    request = make_request()
    retrieval = make_retrieval(
        None,
        data_status="unavailable",
        warnings=("Snapshot retrieval could not complete.",),
    )

    indicators = EnvironmentalIndicatorService().calculate(retrieval, request)

    assert len(indicators) == 3
    assert all(indicator.value is None for indicator in indicators)
    assert all(indicator.status == "unavailable" for indicator in indicators)
    assert all(indicator.data_status == "unavailable" for indicator in indicators)
    assert all(indicator.period_start == START_DATE for indicator in indicators)
    assert all(indicator.period_end == END_DATE for indicator in indicators)
    assert all(indicator.retrieved_at is None for indicator in indicators)
    assert all(indicator.source is None for indicator in indicators)
    assert all(indicator.coverage.expected_days == 2 for indicator in indicators)
    assert all(indicator.coverage.valid_days == 0 for indicator in indicators)
    assert all(indicator.coverage.missing_days == 2 for indicator in indicators)
    assert all(
        "Snapshot retrieval could not complete." in indicator.warnings for indicator in indicators
    )


def test_snapshot_period_must_match_the_request_that_was_retrieved() -> None:
    original_request = make_request()
    retrieval = make_retrieval(make_snapshot(original_request), data_status="cached")
    different_request = make_request(end_date=date(2024, 1, 3))

    with pytest.raises(ValueError, match="dates do not match"):
        EnvironmentalIndicatorService().calculate(retrieval, different_request)
