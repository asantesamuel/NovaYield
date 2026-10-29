"""Tests for NY-6's snapshot identity and persistence contract."""

from datetime import date

import pytest
from pydantic import SecretStr

from app.database.registry import load_document_models
from app.integrations.nasa.power import PowerRequest, normalize_power_response
from app.models.environmental_snapshots import (
    REQUEST_KEY_INDEX_NAME,
    EnvironmentalSnapshot,
    build_snapshot_identity,
    snapshot_fields_from_power_result,
)

LOCATION_SECRET = "test-only-snapshot-identity-secret-value-32-bytes"
REQUEST = PowerRequest(
    # Synthetic test point only; this file never calls NASA POWER.
    latitude=0.0,
    longitude=0.0,
    start_date=date(2024, 3, 1),
    end_date=date(2024, 3, 1),
    season_label="major-season-v1",
    calendar_source_version="research-draft-v1",
    crop="maize",
)


def test_identity_is_stable_private_and_includes_source_query_dimensions() -> None:
    first = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    second = build_snapshot_identity(REQUEST, location_secret=SecretStr(LOCATION_SECRET))

    assert first == second
    assert first.parameters == ("PRECTOTCORR", "T2M", "T2M_MAX")
    assert len(first.request_key) == 64
    assert len(first.location_key) == 64
    serialized = first.model_dump_json()
    assert "latitude" not in serialized
    assert "longitude" not in serialized


def test_identity_changes_for_a_different_location_period_or_secret() -> None:
    original = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    different_location = build_snapshot_identity(
        REQUEST.model_copy(update={"latitude": 0.001}),
        location_secret=LOCATION_SECRET,
    )
    different_period = build_snapshot_identity(
        REQUEST.model_copy(update={"end_date": date(2024, 3, 2)}),
        location_secret=LOCATION_SECRET,
    )
    rotated_secret = build_snapshot_identity(
        REQUEST, location_secret="another-test-secret-value-32-bytes-long"
    )

    assert original.request_key != different_location.request_key
    assert original.request_key != different_period.request_key
    assert original.request_key != rotated_secret.request_key


def test_crop_and_season_context_do_not_duplicate_the_same_provider_query() -> None:
    different_context = REQUEST.model_copy(
        update={
            "season_label": "minor-season-v1",
            "calendar_source_version": "research-draft-v2",
            "crop": "cowpea",
        }
    )

    assert (
        build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET).request_key
        == build_snapshot_identity(different_context, location_secret=LOCATION_SECRET).request_key
    )


def test_short_identity_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        build_snapshot_identity(REQUEST, location_secret="too-short")


def test_snapshot_document_omits_raw_location_and_declares_unique_identity_index() -> None:
    identity = build_snapshot_identity(REQUEST, location_secret=LOCATION_SECRET)
    result = normalize_power_response(
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "properties": {
                "parameter": {
                    "PRECTOTCORR": {"20240301": 2.0},
                    "T2M": {"20240301": 29.0},
                    "T2M_MAX": {"20240301": 34.0},
                }
            },
            "header": {
                "title": "NASA POWER Daily Source Native Resolution",
                "api": {"name": "POWER Daily API", "version": "v2"},
                "fill_value": -999,
            },
            "messages": [],
            "parameters": {
                "PRECTOTCORR": {"units": "mm/day", "longname": "Precipitation"},
                "T2M": {"units": "C", "longname": "Temperature"},
                "T2M_MAX": {"units": "C", "longname": "Maximum temperature"},
            },
            "times": {},
        },
        REQUEST,
    )

    fields = snapshot_fields_from_power_result(identity, result)
    snapshot = EnvironmentalSnapshot.model_construct(**fields)
    serialized = snapshot.model_dump_json()

    assert fields["request_contexts"][0].crop == "maize"
    assert fields["identity"] == identity
    assert fields["parameters"] == result.parameters
    assert identity.request_key in serialized
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "geometry" not in serialized
    assert "latitude" not in EnvironmentalSnapshot.model_fields
    assert "longitude" not in EnvironmentalSnapshot.model_fields
    assert "raw_payload" not in EnvironmentalSnapshot.model_fields

    identity_index = next(
        index
        for index in EnvironmentalSnapshot.Settings.indexes
        if index.document["name"] == REQUEST_KEY_INDEX_NAME
    )
    assert identity_index.document["unique"] is True
    assert identity_index.document["key"] == {"identity.request_key": 1}
    assert EnvironmentalSnapshot in load_document_models()
