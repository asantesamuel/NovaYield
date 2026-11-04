"""Versioned, evidence-backed crop profiles for the NY-8 candidate library.

Only evidence currently reviewed for NovaYield is populated. Optional fields
remain ``None`` or empty until a source supports them; the profile shape is not
permission to infer agronomic values.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CROP_LIBRARY_VERSION = "ny8-crop-library-v1"
EvidenceStatus = Literal["unknown", "provisional", "locally_validated"]
EvidenceConfidence = Literal["low", "moderate", "high"]


class CropTraitEvidence(BaseModel):
    """One independently sourced crop characteristic, with transfer limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trait_name: str = Field(min_length=1)
    value: str | float | None = None
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    evidence_status: EvidenceStatus = "unknown"
    source_reference: str | None = None
    source_title: str | None = None
    source_date: date | None = None
    study_location: str | None = None
    agroecological_zone: str | None = None
    variety: str | None = None
    production_system: str | None = None
    management_conditions: str | None = None
    confidence: EvidenceConfidence | None = None
    applicability_notes: str | None = None
    limitations: str | None = None

    @model_validator(mode="after")
    def validate_evidence_state(self) -> CropTraitEvidence:
        """Unknown traits have no invented values; known claims need provenance."""

        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Trait minimum cannot exceed its maximum")
        if (self.minimum is None) != (self.maximum is None):
            raise ValueError("A numeric trait range requires both minimum and maximum")
        if self.evidence_status == "unknown":
            if any(
                value is not None
                for value in (
                    self.value,
                    self.minimum,
                    self.maximum,
                    self.source_reference,
                    self.confidence,
                )
            ):
                raise ValueError("Unknown traits cannot carry a value, source, or confidence")
        elif not self.source_reference:
            raise ValueError("Provisional and validated traits require a source reference")
        return self


class CropProfile(BaseModel):
    """Crop identity and optional characteristics for an MVP crop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    crop_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    common_name: str = Field(min_length=1)
    scientific_name: str | None = None
    crop_family: str | None = None
    local_names: tuple[str, ...] = ()
    variety: str | None = None
    production_systems: tuple[str, ...] = ()
    maturity_days_min: int | None = Field(default=None, ge=1)
    maturity_days_max: int | None = Field(default=None, ge=1)
    planting_window: str | None = None
    harvest_window: str | None = None
    calendar_source: str | None = None
    calendar_version: str | None = None
    calendar_status: EvidenceStatus = "unknown"
    traits: tuple[CropTraitEvidence, ...] = ()
    identity_source_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile(self) -> CropProfile:
        """Reject duplicate traits and incomplete maturity/calendar claims."""

        trait_names = tuple(trait.trait_name for trait in self.traits)
        if len(set(trait_names)) != len(trait_names):
            raise ValueError("Trait names must be unique within a crop profile")
        if (
            self.maturity_days_min is not None
            and self.maturity_days_max is not None
            and self.maturity_days_min > self.maturity_days_max
        ):
            raise ValueError("Minimum crop maturity cannot exceed maximum maturity")
        if self.calendar_status != "unknown" and not (
            self.calendar_source and self.calendar_version and self.planting_window
        ):
            raise ValueError("A sourced calendar requires its window, source, and version")
        return self

    def trait(self, name: str) -> CropTraitEvidence | None:
        """Return the named trait without manufacturing a default value."""

        return next((trait for trait in self.traits if trait.trait_name == name), None)


class CropTransitionEvidence(BaseModel):
    """Evidence for one ordered crop relationship and its required context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relationship_id: str = Field(min_length=1)
    predecessor_crop_id: str = Field(min_length=1)
    successor_crop_id: str = Field(min_length=1)
    evidence_status: EvidenceStatus
    source_reference: str
    source_title: str
    study_location: str
    study_scope: str
    required_context: tuple[str, ...]
    limitations: str


def _water_profile(
    crop_id: str,
    common_name: str,
    *,
    resilience: str | None,
    confidence: EvidenceConfidence | None,
    rationale: str | None,
    references: tuple[str, ...] = (),
    requirement_min: float | None = None,
    requirement_max: float | None = None,
    requirement_system: str | None = None,
    requirement_reference: str | None = None,
) -> CropProfile:
    """Build a profile with only the reviewed identity and water evidence."""

    traits: list[CropTraitEvidence] = []
    if resilience is not None and rationale and references:
        traits.append(
            CropTraitEvidence(
                trait_name="water_resilience_class",
                value=resilience,
                evidence_status="provisional",
                source_reference="; ".join(references),
                source_title="NY-8 provisional crop-by-criterion evidence matrix",
                study_location="Multiple public sources; transfer to Ejura is provisional",
                confidence=confidence,
                applicability_notes=rationale,
                limitations="Crop-level desk synthesis; not a farm water-balance estimate.",
            )
        )
    if requirement_min is not None and requirement_max is not None and requirement_reference:
        traits.append(
            CropTraitEvidence(
                trait_name="seasonal_crop_water_need",
                minimum=requirement_min,
                maximum=requirement_max,
                unit="mm/total growing period",
                evidence_status="provisional",
                source_reference=requirement_reference,
                source_title="FAO, Crop Water Needs, indicative crop water requirements",
                production_system=requirement_system,
                confidence="low",
                applicability_notes=(
                    "Indicative source range only; the crop duration and local conditions "
                    "are not specified for this profile."
                ),
                limitations=(
                    "Do not compare as local irrigation needs or infer farm water sufficiency."
                ),
            )
        )
    if resilience is not None and rationale and references:
        traits.append(
            CropTraitEvidence(
                trait_name="drought_sensitivity_summary",
                value=rationale,
                evidence_status="provisional",
                source_reference="; ".join(references),
                source_title="NY-8 provisional crop-by-criterion evidence matrix",
                confidence=confidence,
                applicability_notes="Interpret only within the stated source and crop context.",
                limitations="Not a locally validated crop or variety threshold.",
            )
        )
    return CropProfile(
        crop_id=crop_id,
        common_name=common_name,
        identity_source_reference="NY-14 approved MVP crop candidate library",
        traits=tuple(traits),
    )


FAO_WATER_NEEDS = "https://www.fao.org/4/S2022E/s2022e07.htm"
FAO_CASSAVA = "https://www.fao.org/4/i3278e/i3278e.pdf"
TONO_COWPEA = "https://cspace.csirgh.com/items/show/1466"
GHANA_COWPEA_DROUGHT = "https://ugspace.ug.edu.gh/items/6ca7b2cc-9533-4d3b-9922-cf4589f3a914"
WEST_AFRICA_YAM = "https://doi.org/10.5772/intechopen.106504"

CROP_PROFILES: dict[str, CropProfile] = {
    "maize": _water_profile(
        "maize",
        "Maize",
        resilience="low",
        confidence="moderate",
        rationale="FAO reports 500–800 mm and medium-to-high drought sensitivity.",
        references=(FAO_WATER_NEEDS,),
        requirement_min=500,
        requirement_max=800,
        requirement_reference=FAO_WATER_NEEDS,
    ),
    "cowpea": _water_profile(
        "cowpea",
        "Cowpea",
        resilience="moderate",
        confidence="low",
        rationale=(
            "Ghana studies give crop-water context and show drought response varies by "
            "genotype and environment; a universal local class is not established."
        ),
        references=(TONO_COWPEA, GHANA_COWPEA_DROUGHT),
    ),
    "groundnut": _water_profile(
        "groundnut",
        "Groundnut",
        resilience="high",
        confidence="low",
        rationale="FAO reports 500–700 mm and low-to-medium drought sensitivity.",
        references=(FAO_WATER_NEEDS,),
        requirement_min=500,
        requirement_max=700,
        requirement_reference=FAO_WATER_NEEDS,
    ),
    "cassava": _water_profile(
        "cassava",
        "Cassava",
        resilience="moderate",
        confidence="moderate",
        rationale=(
            "FAO describes drought tolerance after establishment and sensitivity to water "
            "deficit in the first three months; the establishment window is unknown here."
        ),
        references=(FAO_CASSAVA,),
    ),
    "yam": _water_profile(
        "yam",
        "Yam",
        resilience="low",
        confidence="low",
        rationale=(
            "A West African review describes a long crop duration and need for sufficient, "
            "well-distributed moisture."
        ),
        references=(WEST_AFRICA_YAM,),
    ),
    "rice": _water_profile(
        "rice",
        "Rice",
        resilience=None,
        confidence=None,
        rationale=None,
    ),
}


CROP_TRANSITION_EVIDENCE: tuple[CropTransitionEvidence, ...] = (
    CropTransitionEvidence(
        relationship_id="GHANA-LEGUME-MAIZE-ROTATION-2019",
        predecessor_crop_id="cowpea",
        successor_crop_id="maize",
        evidence_status="provisional",
        source_reference="https://doi.org/10.1017/S0014479718000273",
        source_title=(
            "Legume-maize rotation or relay? Options for ecological intensification "
            "of smallholder farms in the Guinea savanna of northern Ghana"
        ),
        study_location="Southern and northern Guinea savanna sites, northern Ghana",
        study_scope=(
            "Specific legume-maize rotations and relay patterns compared across "
            "measured soil-fertility conditions."
        ),
        required_context=(
            "crop variety and sequence match",
            "residue retention/removal/return practice",
            "soil fertility and management context",
            "transferability to Ejura and the farm's agroecological setting",
        ),
        limitations=(
            "Study outcomes do not establish a universal nitrogen credit or a validated "
            "soil-health score for an unspecified Ejura farm."
        ),
    ),
    CropTransitionEvidence(
        relationship_id="GHANA-GROUNDNUT-MAIZE-ROTATION-2019",
        predecessor_crop_id="groundnut",
        successor_crop_id="maize",
        evidence_status="provisional",
        source_reference="https://doi.org/10.1017/S0014479718000273",
        source_title=(
            "Legume-maize rotation or relay? Options for ecological intensification "
            "of smallholder farms in the Guinea savanna of northern Ghana"
        ),
        study_location="Southern and northern Guinea savanna sites, northern Ghana",
        study_scope=(
            "Groundnut-maize rotation was one named comparison under measured "
            "fertility and management treatments."
        ),
        required_context=(
            "groundnut variety and sequence match",
            "residue retention/removal/return practice",
            "soil fertility and management context",
            "transferability to Ejura and the farm's agroecological setting",
        ),
        limitations=(
            "The trial does not support an automatic legume benefit or a universal "
            "soil-health rating."
        ),
    ),
)


def get_crop_profile(crop_id: str) -> CropProfile | None:
    """Look up an approved profile; an absent profile stays unknown."""

    return CROP_PROFILES.get(crop_id)
