"""Immutable persistence envelope for farm-specific NY-8 decision results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import DESCENDING, IndexModel

from app.database.registry import register_document_model
from app.decisions.rotation import RotationGenerationRequest, RotationGenerationResult
from app.decisions.scoring import PriorityPoints, ScoringRequest, ScoringResult
from app.farms.contracts import CropName, FarmText, LocationKey
from app.models.farms import Farm

ROTATION_RESULTS_COLLECTION_NAME = "rotation_results"
ROTATION_RESULT_HISTORY_INDEX_NAME = "ix_rotation_results_owner_farm_created_at"
ROTATION_RESULT_SCHEMA_VERSION = "ny20-result-v1"


class FarmDecisionInputSnapshot(BaseModel):
    """Copy only the farm fields that can affect a decision, never its coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location_key: LocationKey
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: tuple[CropName, ...] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints
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

    @field_validator("environmental_snapshot_ids")
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

    schema_version: Literal["ny20-result-v1"] = ROTATION_RESULT_SCHEMA_VERSION
    owner_user_id: PydanticObjectId
    farm_id: PydanticObjectId
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    farm_inputs: FarmDecisionInputSnapshot
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
