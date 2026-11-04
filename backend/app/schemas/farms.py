"""Validated HTTP request and response DTOs for farm profiles (NY-19)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, model_validator

from app.decisions.scoring import PriorityPoints
from app.farms.contracts import CropName, FarmName, FarmText, LocationKey

if TYPE_CHECKING:
    from app.models.farms import Farm
    from app.models.supported_locations import SupportedLocation


class FarmCreate(BaseModel):
    """Fields accepted when creating a farm; ownership is never client input."""

    model_config = ConfigDict(extra="forbid")

    name: FarmName
    location_key: LocationKey
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[CropName] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints | None = None


class FarmUpdate(BaseModel):
    """Partial update fields; a supplied key selects another supported location."""

    model_config = ConfigDict(extra="forbid")

    name: FarmName | None = None
    location_key: LocationKey | None = None
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
        for field_name in ("name", "location_key"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be cleared")
        return self


class SupportedLocationOption(BaseModel):
    """Selectable location fields safe for the frontend; coordinates are omitted."""

    model_config = ConfigDict(extra="forbid")

    location_key: LocationKey
    label: FarmText

    @classmethod
    def from_document(cls, location: SupportedLocation) -> SupportedLocationOption:
        return cls(location_key=location.location_key, label=location.label)


class SupportedLocationsResponse(BaseModel):
    """Public catalog response with an explicit limited-coverage notice."""

    model_config = ConfigDict(extra="forbid")

    coverage_notice: str
    locations: list[SupportedLocationOption]


class FarmLocationSummary(BaseModel):
    """Stable lookup key plus display label; private point coordinates are omitted."""

    model_config = ConfigDict(extra="forbid")

    location_key: LocationKey
    label: FarmText


class FarmResponse(BaseModel):
    """Public farm DTO: owner ID and exact location coordinates are omitted."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: FarmName
    location: FarmLocationSummary
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None
    previous_crops: list[CropName] | None = None
    current_practice: FarmText | None = None
    farmer_priorities: PriorityPoints | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_document(cls, farm: Farm, *, location_label: str) -> FarmResponse:
        """Map persistence data to a safe response after resolving its catalog label."""

        return cls(
            id=str(farm.id),
            name=farm.name,
            location=FarmLocationSummary(
                location_key=farm.location_key,
                label=location_label,
            ),
            soil_texture=farm.soil_texture,
            irrigation_access=farm.irrigation_access,
            previous_crops=farm.previous_crops,
            current_practice=farm.current_practice,
            farmer_priorities=farm.farmer_priorities,
            created_at=farm.created_at,
            updated_at=farm.updated_at,
        )
