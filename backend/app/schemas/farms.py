"""Validated HTTP request and response DTOs for farm profiles (NY-19)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.decisions.scoring import PriorityPoints
from app.farms.contracts import (
    CropName,
    FarmLocationData,
    FarmName,
    FarmText,
    default_farmer_priorities,
    validate_location_label,
)

if TYPE_CHECKING:
    from app.models.farms import Farm


class FarmCreate(BaseModel):
    """Fields accepted when creating a farm; ownership is never client input."""

    model_config = ConfigDict(extra="forbid")

    name: FarmName
    location: FarmLocationData
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[CropName] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints = Field(default_factory=default_farmer_priorities)


class FarmUpdate(BaseModel):
    """Partial update fields; a supplied location replaces the stored location."""

    model_config = ConfigDict(extra="forbid")

    name: FarmName | None = None
    location: FarmLocationData | None = None
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[CropName] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints | None = None

    @model_validator(mode="after")
    def require_mutable_fields(self) -> FarmUpdate:
        """Reject empty patches and nulls for fields needed by every farm."""

        if not self.model_fields_set:
            raise ValueError("At least one farm field must be supplied")
        for field_name in ("name", "location", "farmer_priorities"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be cleared")
        return self


class FarmLocationSummary(BaseModel):
    """Location label safe to return from the authenticated farm API."""

    model_config = ConfigDict(extra="forbid")

    label: FarmText

    @field_validator("label")
    @classmethod
    def reject_coordinate_text(cls, value: str) -> str:
        """Keep a malformed persisted label from leaking coordinates in responses."""

        return validate_location_label(value)


class FarmResponse(BaseModel):
    """Public farm DTO: API ID is a string; owner ID and exact coordinates are omitted."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: FarmName
    location: FarmLocationSummary
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[CropName] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints = Field(default_factory=default_farmer_priorities)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_document(cls, farm: Farm) -> FarmResponse:
        """Map persistence data to a response without copying private location fields."""

        return cls(
            id=str(farm.id),
            name=farm.name,
            location=FarmLocationSummary(label=farm.location.label),
            soil_texture=farm.soil_texture,
            irrigation_access=farm.irrigation_access,
            previous_crops=farm.previous_crops,
            current_practice=farm.current_practice,
            farmer_priorities=farm.farmer_priorities,
            created_at=farm.created_at,
            updated_at=farm.updated_at,
        )
