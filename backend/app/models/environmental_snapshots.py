"""Snapshot persistence contract and opaque NASA POWER request identity (NY-6)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime
from typing import Any, Literal

from beanie import Document
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator
from pymongo import ASCENDING, IndexModel

from app.database.registry import register_document_model
from app.integrations.nasa.power import (
    NASA_POWER_COMMUNITY,
    NASA_POWER_DAILY_ENDPOINT,
    NASA_POWER_PARAMETERS,
    PowerParameterCode,
    PowerParameterSeries,
    PowerProviderMetadata,
    PowerRequest,
    PowerResult,
)

SNAPSHOT_IDENTITY_VERSION = "v1"
NASA_POWER_ADAPTER_VERSION = "ny5-v1"
SNAPSHOT_SCHEMA_VERSION = "v1"
SNAPSHOT_COLLECTION_NAME = "environmental_snapshots"
REQUEST_KEY_INDEX_NAME = "uq_environmental_snapshot_request_key"


class SnapshotIdentity(BaseModel):
    """Non-coordinate request dimensions and deterministic lookup keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_version: str = SNAPSHOT_IDENTITY_VERSION
    provider: Literal["NASA POWER"] = "NASA POWER"
    service: Literal["Daily Point"] = "Daily Point"
    endpoint: str = NASA_POWER_DAILY_ENDPOINT
    community: Literal["AG"] = NASA_POWER_COMMUNITY
    location_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: tuple[PowerParameterCode, ...]
    time_standard: Literal["UTC"] = "UTC"
    unit_system: Literal["metric"] = "metric"
    start_date: date
    end_date: date
    adapter_version: str = NASA_POWER_ADAPTER_VERSION
    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    request_key: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("parameters")
    @classmethod
    def require_sorted_unique_parameters(
        cls, value: tuple[PowerParameterCode, ...]
    ) -> tuple[PowerParameterCode, ...]:
        if not value or value != tuple(sorted(set(value))):
            raise ValueError("Snapshot parameters must be non-empty, sorted, and unique")
        return value

    @field_validator("end_date")
    @classmethod
    def require_ordered_date_range(cls, value: date, info: ValidationInfo) -> date:
        start_date = info.data.get("start_date")
        if start_date is not None and value < start_date:
            raise ValueError("Snapshot end date must be on or after start date")
        return value


class SnapshotSeasonContext(BaseModel):
    """Caller-provided seasonal context retained as provenance, not cache identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    season_label: str | None = None
    calendar_source_version: str | None = None
    crop: str | None = None


def build_snapshot_identity(
    request: PowerRequest,
    *,
    location_secret: str | bytes | SecretStr,
    adapter_version: str = NASA_POWER_ADAPTER_VERSION,
    schema_version: str = SNAPSHOT_SCHEMA_VERSION,
) -> SnapshotIdentity:
    """Build a stable key without putting raw coordinates in persisted identity.

    The location fingerprint is keyed HMAC-SHA-256. Coordinates are represented
    exactly as supplied after Pydantic's float parsing; they are not rounded to
    an assumed grid because the requested POWER parameters can have different
    native resolutions.
    """

    secret_bytes = _secret_bytes(location_secret)
    coordinate_payload = json.dumps(
        {
            "latitude": _canonical_coordinate(request.latitude),
            "longitude": _canonical_coordinate(request.longitude),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    location_key = hmac.new(
        secret_bytes, b"nova-yield:nasa-power:location:v1:" + coordinate_payload, hashlib.sha256
    ).hexdigest()

    identity_fields = {
        "identity_version": SNAPSHOT_IDENTITY_VERSION,
        "provider": "NASA POWER",
        "service": "Daily Point",
        "endpoint": NASA_POWER_DAILY_ENDPOINT,
        "community": NASA_POWER_COMMUNITY,
        "location_key": location_key,
        "parameters": tuple(sorted(NASA_POWER_PARAMETERS)),
        "time_standard": "UTC",
        "unit_system": "metric",
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "adapter_version": adapter_version,
        "schema_version": schema_version,
    }
    canonical_identity = json.dumps(identity_fields, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    request_key = hmac.new(
        secret_bytes,
        b"nova-yield:nasa-power:request:v1:" + canonical_identity,
        hashlib.sha256,
    ).hexdigest()

    return SnapshotIdentity(
        **identity_fields,
        request_key=request_key,
    )


@register_document_model
class EnvironmentalSnapshot(Document):
    """Normalized NASA values and provenance; raw payload and coordinates excluded."""

    identity: SnapshotIdentity
    source_url: str = NASA_POWER_DAILY_ENDPOINT
    retrieval_status: Literal["live"] = "live"
    retrieved_at: datetime
    provider_metadata: PowerProviderMetadata
    parameters: dict[PowerParameterCode, PowerParameterSeries]
    request_contexts: list[SnapshotSeasonContext] = Field(default_factory=list)

    @classmethod
    def from_power_result(
        cls, identity: SnapshotIdentity, result: PowerResult
    ) -> EnvironmentalSnapshot:
        """Create a persistence document after confirming result and key agree."""

        return cls(**snapshot_fields_from_power_result(identity, result))

    class Settings:
        name = SNAPSHOT_COLLECTION_NAME
        indexes = [
            IndexModel(
                [("identity.request_key", ASCENDING)],
                unique=True,
                name=REQUEST_KEY_INDEX_NAME,
            )
        ]


def snapshot_fields_from_power_result(
    identity: SnapshotIdentity, result: PowerResult
) -> dict[str, Any]:
    """Map a normalized provider response to safe persistence fields."""

    if result.date_window.start_date != identity.start_date:
        raise ValueError("NASA response start date does not match snapshot identity")
    if result.date_window.end_date != identity.end_date:
        raise ValueError("NASA response end date does not match snapshot identity")
    if result.provider != identity.provider or result.service != identity.service:
        raise ValueError("NASA response source does not match snapshot identity")
    if result.community != identity.community or result.time_standard != identity.time_standard:
        raise ValueError("NASA response community or time standard does not match identity")
    if tuple(sorted(result.parameters)) != identity.parameters:
        raise ValueError("NASA response parameter set does not match snapshot identity")

    return {
        "identity": identity,
        "source_url": result.source_url,
        "retrieval_status": result.retrieval_status,
        "retrieved_at": result.retrieved_at,
        "provider_metadata": result.provider_metadata,
        "parameters": result.parameters,
        "request_contexts": [
            SnapshotSeasonContext(
                season_label=result.date_window.season_label,
                calendar_source_version=result.date_window.calendar_source_version,
                crop=result.date_window.crop,
            )
        ],
    }


def _secret_bytes(secret: str | bytes | SecretStr) -> bytes:
    if isinstance(secret, SecretStr):
        value = secret.get_secret_value()
    else:
        value = secret
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    if len(encoded) < 32:
        raise ValueError("Snapshot identity secret must contain at least 32 bytes")
    return encoded


def _canonical_coordinate(value: float) -> str:
    """Return a stable, round-trippable decimal representation of a float."""

    if value == 0:
        return "0"
    return format(value, ".17g")
