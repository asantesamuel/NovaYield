"""Canonical crop identities and evidence-scoped, versioned research records.

Identity is shared by farmer history and recommendation candidate lookup. A
profile or calendar is a separate revision because neither a crop name nor its
botanical family establishes a local planting date, water need, or soil effect.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo import ASCENDING, IndexModel

from app.database.registry import register_document_model
from app.farms.contracts import CropKey, FarmText, LocationKey

EvidenceStatus = Literal["unknown", "provisional", "locally_reviewed", "conflicted"]
Confidence = Literal["low", "moderate", "high"]

CROP_IDENTITY_SCHEMA_VERSION = "crop-identity-v1"
CROP_PROFILE_SCHEMA_VERSION = "crop-profile-v2"
CROP_CALENDAR_SCHEMA_VERSION = "crop-calendar-v1"


class SourceEvidence(BaseModel):
    """A claim's source and transfer limits; desk research is not local review."""

    model_config = ConfigDict(extra="forbid")

    source_url: str
    additional_source_urls: tuple[str, ...] = ()
    source_title: str
    source_publication_date: date | None = None
    study_location: str | None = None
    agroecological_zone: str | None = None
    variety: str | None = None
    production_system: str | None = None
    management: str | None = None
    source_confidence: Confidence
    pilot_transferability: Confidence
    applicability: str
    limitations: str
    validation_status: EvidenceStatus = "provisional"
    reviewer_ref: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def reviewed_claim_has_reviewer(self) -> SourceEvidence:
        if self.validation_status == "locally_reviewed" and (
            self.reviewer_ref is None or self.reviewed_at is None
        ):
            raise ValueError("Locally reviewed evidence requires a reviewer and review date")
        return self


class EvidenceValue(BaseModel):
    """A typed-enough storage envelope for a source-scoped, non-default trait."""

    model_config = ConfigDict(extra="forbid")

    value: dict[str, str | int | float | bool | None]
    unit: str | None = None
    source: SourceEvidence


class DecisionTraits(BaseModel):
    """Known slots remain null until a scoped source supports each trait."""

    model_config = ConfigDict(extra="forbid")

    crop_water_need_mm: EvidenceValue | None = None
    water_resilience_class: EvidenceValue | None = None
    crop_coefficient_by_stage: list[EvidenceValue] | None = None
    temperature_response: EvidenceValue | None = None
    soil_nutrient_residue_effect: EvidenceValue | None = None
    nitrogen_fixation_kg_ha: EvidenceValue | None = None
    erosion_context: EvidenceValue | None = None
    rotation_relationships: list[EvidenceValue] | None = None
    yield_stability_proxy: EvidenceValue | None = None
    labour_operations: list[EvidenceValue] | None = None


class MaturityRange(BaseModel):
    """Source-reported day range, which is unusable for exact scheduling if endpoints differ."""

    model_config = ConfigDict(extra="forbid")

    min_days: int = Field(gt=0)
    max_days: int = Field(gt=0)
    meaning: str
    endpoint_verified: bool = False

    @model_validator(mode="after")
    def ordered_range(self) -> MaturityRange:
        if self.max_days < self.min_days:
            raise ValueError("Maturity maximum must be at least the minimum")
        return self


class MaturityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: MaturityRange
    unit: Literal["days"] = "days"
    source: SourceEvidence


class GrowthStage(BaseModel):
    """Stage names may be known while exact timing remains explicitly unknown."""

    model_config = ConfigDict(extra="forbid")

    stage_key: CropKey
    start_offset_days: EvidenceValue | None = None
    duration_days: EvidenceValue | None = None
    sensitivity: EvidenceValue | None = None


class LocalName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_tag: str
    name: str
    source_url: str | None = None
    reviewer_ref: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    review_status: Literal["unverified", "locally_reviewed"] = "unverified"

    @model_validator(mode="after")
    def source_required(self) -> LocalName:
        if not self.source_url and not self.reviewer_ref:
            raise ValueError("A local name needs a source or reviewer")
        if self.review_status == "locally_reviewed" and not self.reviewer_ref:
            raise ValueError("Locally reviewed local name needs a reviewer")
        return self


@register_document_model
class Crop(Document):
    """Stable crop identity; deactivate a referenced crop rather than deleting it."""

    schema_version: str = CROP_IDENTITY_SCHEMA_VERSION
    crop_key: CropKey
    common_name: FarmText
    scientific_name: str | None = None
    family: str | None = None
    identity_source_url: str | None = None
    local_names: list[LocalName] = Field(default_factory=list)
    history_selectable: bool
    recommendation_candidate: bool
    catalog_status: Literal["active", "inactive", "needs_review"] = "active"
    requires_variety_for_timing: bool = True
    requires_production_system_for_assessment: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "crops"
        indexes = [
            IndexModel([("crop_key", ASCENDING)], unique=True, name="uq_crops_crop_key"),
            IndexModel(
                [
                    ("catalog_status", ASCENDING),
                    ("history_selectable", ASCENDING),
                    ("recommendation_candidate", ASCENDING),
                ],
                name="ix_crops_active_usage",
            ),
        ]


@register_document_model
class CropProfileRevision(Document):
    """Immutable source-scoped profile revision for one variety and production system."""

    schema_version: str = CROP_PROFILE_SCHEMA_VERSION
    crop_id: PydanticObjectId
    revision: int = Field(ge=1)
    # New drafts are inactive. Publishing an approved desk revision is a
    # separate, explicit action and never implies local agronomic validation.
    is_active: bool = False
    variety_key: CropKey | None = None
    production_system_key: CropKey | None = None
    maturity_days: MaturityEvidence | None = None
    growth_stages: list[GrowthStage] = Field(default_factory=list)
    decision_traits: DecisionTraits = Field(default_factory=DecisionTraits)
    evidence_status: EvidenceStatus = "unknown"
    published_at: datetime | None = None
    reviewer_ref: str | None = None
    source_note: str | None = None

    @model_validator(mode="after")
    def active_revision_is_published(self) -> CropProfileRevision:
        if self.is_active and self.published_at is None:
            raise ValueError("An active crop profile revision must have a publication time")
        if self.published_at is not None and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("Crop profile publication time must include a timezone")
        return self

    class Settings:
        name = "crop_profile_revisions"
        indexes = [
            IndexModel(
                [
                    ("crop_id", ASCENDING),
                    ("variety_key", ASCENDING),
                    ("production_system_key", ASCENDING),
                    ("revision", ASCENDING),
                ],
                unique=True,
                name="uq_crop_profile_scope_revision",
            ),
            IndexModel(
                [
                    ("crop_id", ASCENDING),
                    ("variety_key", ASCENDING),
                    ("production_system_key", ASCENDING),
                ],
                unique=True,
                partialFilterExpression={"is_active": True},
                name="uq_crop_profile_active_scope",
            ),
        ]


class PlantingWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_month_day: str = Field(pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
    end_month_day: str = Field(pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
    crosses_year: bool
    valid_from_year: int | None = None
    valid_to_year: int | None = None


@register_document_model
class CropCalendar(Document):
    """Versioned local calendar; a null window cannot schedule a planting day."""

    schema_version: str = CROP_CALENDAR_SCHEMA_VERSION
    calendar_version: str
    is_active: bool = False
    published_at: datetime | None = None
    location_key: LocationKey
    crop_id: PydanticObjectId
    profile_revision_id: PydanticObjectId | None = None
    season_key: CropKey
    planting_window: PlantingWindow | None = None
    harvest_or_maturity_basis: EvidenceValue | None = None
    evidence: SourceEvidence | None = None
    status: EvidenceStatus = "unknown"
    source_note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def active_calendar_is_published(self) -> CropCalendar:
        if self.is_active and self.published_at is None:
            raise ValueError("An active crop calendar must have a publication time")
        if self.published_at is not None and (
            self.published_at.tzinfo is None or self.published_at.utcoffset() is None
        ):
            raise ValueError("Crop calendar publication time must include a timezone")
        return self

    class Settings:
        name = "crop_calendars"
        indexes = [
            IndexModel(
                [
                    ("location_key", ASCENDING),
                    ("crop_id", ASCENDING),
                    ("profile_revision_id", ASCENDING),
                    ("season_key", ASCENDING),
                    ("calendar_version", ASCENDING),
                ],
                unique=True,
                name="uq_crop_calendar_scope_version",
            ),
            IndexModel(
                [("location_key", ASCENDING), ("crop_id", ASCENDING)],
                name="ix_crop_calendar_location_crop",
            ),
            IndexModel(
                [
                    ("location_key", ASCENDING),
                    ("crop_id", ASCENDING),
                    ("profile_revision_id", ASCENDING),
                    ("season_key", ASCENDING),
                ],
                unique=True,
                partialFilterExpression={"is_active": True},
                name="uq_crop_calendar_active_scope",
            ),
        ]


def profile_scope_query(
    crop_id: PydanticObjectId,
    variety_key: str | None = None,
    production_system_key: str | None = None,
) -> dict[str, Any]:
    """Exact scope only: a generic profile never inherits a named variety's traits."""

    return {
        "crop_id": crop_id,
        "variety_key": variety_key,
        "production_system_key": production_system_key,
        "is_active": True,
    }
