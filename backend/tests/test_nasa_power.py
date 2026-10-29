"""Mocked tests for the NASA POWER Daily Point client and normalizer."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.integrations.nasa.power import (
    NASA_POWER_DAILY_ENDPOINT,
    NASAPowerHttpClient,
    NASAPowerService,
    PowerHTTPError,
    PowerMalformedResponseError,
    PowerMissingParameterError,
    PowerRequest,
    PowerTimeoutError,
    PowerUnsupportedUnitsError,
)

TEST_REQUEST = PowerRequest(
    latitude=0.0,
    longitude=0.0,
    start_date=date(2020, 1, 1),
    end_date=date(2020, 1, 4),
    season_label="test-window",
    calendar_source_version="test-calendar-v1",
    crop="test-crop",
)


def nasa_payload() -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0, 100.0]},
        "properties": {
            "parameter": {
                "PRECTOTCORR": {
                    "20200101": 1.0,
                    "20200102": -999,
                    "20200104": 3.0,
                },
                "T2M": {
                    "20200101": 20.0,
                    "20200102": 21.0,
                    "20200103": 22.0,
                    "20200104": 23.0,
                },
                "T2M_MAX": {
                    "20200101": 29.0,
                    "20200102": 30.0,
                    "20200103": 31.0,
                    "20200104": 32.0,
                },
            }
        },
        "header": {
            "title": "NASA/POWER Source Native Resolution Daily Data",
            "api": {"name": "POWER Daily API", "version": "v2.10.1"},
            "fill_value": -999,
            "sources": ["MERRA2", "POWER"],
        },
        "messages": [],
        "parameters": {
            "PRECTOTCORR": {
                "units": "mm/day",
                "longname": "Precipitation Corrected",
                "source": "MERRA2",
            },
            "T2M": {"units": "C", "longname": "Temperature at 2 Meters"},
            "T2M_MAX": {"units": "C", "longname": "Temperature at 2 Meters Maximum"},
        },
        "times": {"data": 0.1, "process": 0.1},
    }


def make_mock_service(
    *,
    payload: dict[str, Any] | None = None,
    status_code: int = 200,
    body: str | None = None,
    exception: Exception | None = None,
) -> tuple[NASAPowerService, list[httpx.Request], Any]:
    requests: list[httpx.Request] = []

    class MockResponse:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self) -> Any:
            if body is not None:
                return json.loads(body)
            return payload or nasa_payload()

    class MockHttpClient:
        async def get(self, url: str, *, params: dict[str, Any]) -> MockResponse:
            requests.append(httpx.Request("GET", url, params=params))
            if exception is not None:
                raise exception
            return MockResponse()

        async def aclose(self) -> None:
            return None

    client = MockHttpClient()
    return NASAPowerService(NASAPowerHttpClient(client)), requests, client


def run_immediately(awaitable: Any) -> Any:
    """Run a coroutine made only of immediate mocks without opening an event loop."""
    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("The in-memory mock unexpectedly suspended.")


def test_retrieves_daily_point_with_required_parameters_and_normalizes_summaries() -> None:
    async def run() -> None:
        service, requests, http_client = make_mock_service()
        try:
            result = await service.retrieve(TEST_REQUEST)
        finally:
            await http_client.aclose()

        assert len(requests) == 1
        request = requests[0]
        assert str(request.url).startswith(NASA_POWER_DAILY_ENDPOINT)
        assert request.url.params["parameters"] == "PRECTOTCORR,T2M,T2M_MAX"
        assert request.url.params["community"] == "AG"
        assert request.url.params["latitude"] == "0.0"
        assert request.url.params["longitude"] == "0.0"
        assert request.url.params["start"] == "20200101"
        assert request.url.params["end"] == "20200104"
        assert request.url.params["format"] == "JSON"
        assert request.url.params["units"] == "metric"
        assert request.url.params["time-standard"] == "UTC"

        rain = result.parameters["PRECTOTCORR"]
        assert rain.metadata.source_units == "mm/day"
        assert rain.metadata.normalized_units == "mm/day"
        assert rain.metadata.source == "MERRA2"
        assert rain.seasonal_summary.method == "sum"
        assert rain.seasonal_summary.units == "mm/season"
        assert rain.seasonal_summary.value == 4.0
        assert rain.seasonal_summary.status == "partial"
        assert rain.seasonal_summary.coverage.expected_days == 4
        assert rain.seasonal_summary.coverage.valid_days == 2
        assert rain.seasonal_summary.coverage.missing_days == 2
        assert rain.seasonal_summary.coverage.coverage_percent == 50.0
        assert [item.value for item in rain.daily_values] == [1.0, None, None, 3.0]

        mean_temp = result.parameters["T2M"].seasonal_summary
        mean_daily_max = result.parameters["T2M_MAX"].seasonal_summary
        assert mean_temp.method == "mean"
        assert mean_temp.value == 21.5
        assert mean_temp.units == "°C"
        assert mean_daily_max.value == 30.5
        assert result.provider == "NASA POWER"
        assert result.retrieval_status == "live"
        assert result.time_standard == "UTC"
        assert result.provider_metadata.source_products == ["MERRA2", "POWER"]
        assert (
            result.provider_metadata.spatial_resolution_note
            == result.provider_metadata.header_title
        )
        assert result.date_window.season_label == "test-window"
        assert result.date_window.calendar_source_version == "test-calendar-v1"
        assert result.retrieved_at.tzinfo == UTC
        # The normalized service result deliberately omits requested/grid coordinates.
        result_json = result.model_dump_json()
        assert '"latitude"' not in result_json
        assert '"longitude"' not in result_json

    run_immediately(run())


def test_empty_valid_series_is_unavailable_not_zero() -> None:
    async def run() -> None:
        payload = nasa_payload()
        payload["properties"]["parameter"]["PRECTOTCORR"] = {
            "20200101": -999,
            "20200102": -999,
            "20200103": -999,
            "20200104": -999,
        }
        service, _requests, http_client = make_mock_service(payload=payload)
        try:
            result = await service.retrieve(TEST_REQUEST)
        finally:
            await http_client.aclose()

        summary = result.parameters["PRECTOTCORR"].seasonal_summary
        assert summary.value is None
        assert summary.status == "unavailable"
        assert summary.coverage.valid_days == 0
        assert summary.coverage.missing_days == 4

    run_immediately(run())


def test_missing_required_parameter_has_a_typed_error() -> None:
    async def run() -> None:
        payload = nasa_payload()
        del payload["properties"]["parameter"]["T2M_MAX"]
        service, _requests, http_client = make_mock_service(payload=payload)
        try:
            with pytest.raises(PowerMissingParameterError) as error:
                await service.retrieve(TEST_REQUEST)
        finally:
            await http_client.aclose()

        assert error.value.parameter == "T2M_MAX"

    run_immediately(run())


def test_invalid_request_coordinates_and_dates_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PowerRequest(
            latitude=90.1,
            longitude=0,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 2),
        )
    with pytest.raises(ValidationError):
        PowerRequest(
            latitude=0,
            longitude=180.1,
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 2),
        )
    with pytest.raises(ValidationError, match="1981-01-01"):
        PowerRequest(
            latitude=0,
            longitude=0,
            start_date=date(1980, 12, 31),
            end_date=date(1981, 1, 1),
        )
    with pytest.raises(ValidationError, match="on or after"):
        PowerRequest(
            latitude=0,
            longitude=0,
            start_date=date(2020, 1, 2),
            end_date=date(2020, 1, 1),
        )
    with pytest.raises(ValidationError, match="future"):
        tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        PowerRequest(
            latitude=0,
            longitude=0,
            start_date=tomorrow,
            end_date=tomorrow,
        )


def test_http_status_error_does_not_expose_upstream_body_or_url() -> None:
    async def run() -> None:
        service, requests, http_client = make_mock_service(
            status_code=503,
            body="backend unavailable; request included coordinates 12.345,67.890",
        )
        try:
            with pytest.raises(PowerHTTPError) as error:
                await service.retrieve(TEST_REQUEST)
        finally:
            await http_client.aclose()

        assert error.value.status_code == 503
        assert "coordinates" not in str(error.value)
        assert "12.345" not in str(error.value)
        assert len(requests) == 1

    run_immediately(run())


def test_timeout_maps_to_a_typed_outcome() -> None:
    async def run() -> None:
        service, _requests, http_client = make_mock_service(exception=httpx.ReadTimeout("timeout"))
        try:
            with pytest.raises(PowerTimeoutError):
                await service.retrieve(TEST_REQUEST)
        finally:
            await http_client.aclose()

    run_immediately(run())


def test_invalid_json_missing_metadata_and_unsupported_units_are_explicit() -> None:
    async def run() -> None:
        invalid_json_service, _requests, invalid_json_client = make_mock_service(body="not-json")
        try:
            with pytest.raises(PowerMalformedResponseError, match="invalid JSON"):
                await invalid_json_service.retrieve(TEST_REQUEST)
        finally:
            await invalid_json_client.aclose()

        missing_metadata = nasa_payload()
        del missing_metadata["parameters"]["T2M"]
        metadata_service, _requests, metadata_client = make_mock_service(payload=missing_metadata)
        try:
            with pytest.raises(PowerMissingParameterError):
                await metadata_service.retrieve(TEST_REQUEST)
        finally:
            await metadata_client.aclose()

        unsupported = nasa_payload()
        unsupported["parameters"]["T2M"]["units"] = "F"
        units_service, _requests, units_client = make_mock_service(payload=unsupported)
        try:
            with pytest.raises(PowerUnsupportedUnitsError):
                await units_service.retrieve(TEST_REQUEST)
        finally:
            await units_client.aclose()

    run_immediately(run())
