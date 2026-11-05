"""Immutable persistence envelope for farm-specific NY-8 decision results."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import DESCENDING, IndexModel

from app.database.registry import register_document_model
from app.decisions.climate_features import StageCDDExposure
from app.decisions.rotation import RotationGenerationRequest, RotationGenerationResult
from app.decisions.scoring import PriorityPoints, ScoringRequest, ScoringResult
from app.farms.context_window import DerivedContextPeriod
from app.farms.contracts import CropName, FarmText, LocationKey
from app.indicators.environmental import EnvironmentalIndicator
from app.models.farms import CropHistoryEvent, Farm, HistoryGap

ROTATION_RESULTS_COLLECTION_NAME = "rotation_results"
ROTATION_RESULT_HISTORY_INDEX_NAME = "ix_rotation_results_owner_farm_created_at"
ROTATION_RESULT_SCHEMA_VERSION = "ny20-result-v1"
NY38_RESULT_SCHEMA_VERSION = "ny38-result-v2"


class ParameterProvenance(BaseModel):
    """Coverage and units for one persisted NASA POWER parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    units: str
    source: str | None = None
    spatial_resolution: str | None = None
    expected_days: int = Field(ge=0)
    valid_days: int = Field(ge=0)
    missing_days: int = Field(ge=0)


class SnapshotUseProvenance(BaseModel):
    """A compact source record, never a copy of the daily NASA time series."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str | None = None
    start_date: date
    end_date: date
    data_status: Literal["live", "cached", "unavailable"]
    cache_action: str
    freshness_status: Literal["fresh", "stale", "unknown"]
    retrieved_at: datetime | None = None
    source_products: tuple[str, ...] = ()
    parameters: tuple[ParameterProvenance, ...] = ()
    warning_codes: tuple[str, ...] = ()


class FutureWindowSummary(BaseModel):
    """Explain scheduling readiness without presenting arbitrary options as ranked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_count: int = Field(ge=0)
    fully_scheduled_count: int = Field(ge=0)
    needs_review_count: int = Field(ge=0)
    review_reasons: tuple[str, ...] = ()


class FarmDecisionInputSnapshot(BaseModel):
    """Copy only the farm fields that can affect a decision, never its coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location_key: LocationKey
    schema_version: str = "ny20-farm-inputs-v1"
    farm_revision: int | None = None
    soil_texture_key: str | None = None
    irrigation_access_key: str | None = None
    history_status: str | None = None
    declared_gaps: tuple[HistoryGap, ...] = ()
    current_plot_available: bool | None = None
    earliest_available_date: date | None = None
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: tuple[CropName, ...] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints | None = None
    farm_updated_at: datetime

    @field_validator("farm_updated_at")
    @classmethod
    def require_timezone_aware_update_time(cls, value: datetime) -> datetime:
        """Keep the captured farm revision unambiguous across time zones."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Farm update time must include a timezone")
        return value.astimezone(UTC)

    @classmethod
    def from_farm(cls, farm: Farm) -> FarmDecisionInputSnapshot:
        """Snapshot the persisted profile at generation time without copying owner data."""

        return cls(
            location_key=farm.location_key,
            schema_version=(
                "ny38-farm-inputs-v2" if farm.schema_version == "farm-v2" else "ny20-farm-inputs-v1"
            ),
            farm_revision=farm.revision,
            soil_texture_key=farm.soil_texture_key,
            irrigation_access_key=farm.irrigation_access_key,
            history_status=farm.history_status,
            declared_gaps=tuple(farm.declared_gaps),
            current_plot_available=farm.current_plot_available,
            earliest_available_date=farm.earliest_available_date,
            soil_texture=farm.soil_texture,
            irrigation_access=farm.irrigation_access,
            previous_crops=(
                tuple(farm.previous_crops) if farm.previous_crops is not None else None
            ),
            current_practice=farm.current_practice,
            farmer_priorities=farm.farmer_priorities,
            farm_updated_at=farm.updated_at,
        )


class RotationDecisionInputs(BaseModel):
    """Inputs needed to trace the candidate generation and scoring run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_request: RotationGenerationRequest
    scoring_request: ScoringRequest
    environmental_snapshot_ids: tuple[PydanticObjectId, ...] = ()
    climate_reference_ids: tuple[PydanticObjectId, ...] = ()
    crop_profile_revision_ids: tuple[PydanticObjectId, ...] = ()
    calendar_version_ids: tuple[PydanticObjectId, ...] = ()
    crop_library_version: str = "not_recorded"
    assessment_version: str = "not_recorded"
    rule_set_version: str = "not_recorded"
    scoring_version: str = "not_recorded"
    climate_method_version: str = "not_recorded"
    calendar_method_version: str = "not_recorded"

    @field_validator(
        "environmental_snapshot_ids",
        "climate_reference_ids",
        "crop_profile_revision_ids",
        "calendar_version_ids",
    )
    @classmethod
    def require_unique_snapshot_references(
        cls, value: tuple[PydanticObjectId, ...]
    ) -> tuple[PydanticObjectId, ...]:
        """Avoid storing the same NASA snapshot reference more than once."""

        if len(set(value)) != len(value):
            raise ValueError("Environmental snapshot references must be unique")
        return value


@register_document_model
class RotationResult(Document):
    """Append-only decision record; owner and farm are application-checked references."""

    schema_version: Literal["ny20-result-v1", "ny38-result-v2"] = ROTATION_RESULT_SCHEMA_VERSION
    owner_user_id: PydanticObjectId
    farm_id: PydanticObjectId
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    farm_inputs: FarmDecisionInputSnapshot
    history_event_snapshots: tuple[CropHistoryEvent, ...] = ()
    derived_context_period: DerivedContextPeriod | None = None
    context_provenance: SnapshotUseProvenance | None = None
    climate_reference_provenance: SnapshotUseProvenance | None = None
    indicators: tuple[EnvironmentalIndicator, ...] = ()
    climate_features: tuple[StageCDDExposure, ...] = ()
    climate_feature_status_reason: str | None = None
    future_window_summary: FutureWindowSummary | None = None
    baseline_status: Literal["deferred", "historical"] | None = None
    decision_status: (
        Literal["ranked_provisional", "needs_review", "unranked", "unavailable"] | None
    ) = None
    decision_inputs: RotationDecisionInputs
    candidate_generation: RotationGenerationResult
    scoring_result: ScoringResult

    @field_validator("created_at")
    @classmethod
    def require_timezone_aware_creation_time(cls, value: datetime) -> datetime:
        """Ensure history ordering uses a clear UTC instant."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Result creation time must include a timezone")
        return value.astimezone(UTC)

    class Settings:
        name = ROTATION_RESULTS_COLLECTION_NAME
        indexes = [
            IndexModel(
                [
                    ("owner_user_id", 1),
                    ("farm_id", 1),
                    ("created_at", DESCENDING),
                ],
                name=ROTATION_RESULT_HISTORY_INDEX_NAME,
            )
        ]
