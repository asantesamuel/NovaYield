"""Pure sequence assessment using the versioned NY-8 crop evidence library."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.decisions.crop_profiles import (
    CROP_PROFILES,
    CROP_TRANSITION_EVIDENCE,
    CropProfile,
    CropTransitionEvidence,
)
from app.decisions.rotation import RotationCandidate
from app.decisions.scoring import (
    Confidence,
    CriterionEvidence,
    EventAssessment,
    RotationOptionEvidence,
    TransitionAssessment,
)
from app.indicators.environmental import EnvironmentalIndicator

ASSESSMENT_VERSION = "ny8-sequence-assessment-v2"
WaterRating = Literal["high", "moderate", "low"]

YIELD_STABILITY_SOURCES = {
    "maize": (
        "https://onlinelibrary.wiley.com/doi/full/10.1155/2022/9077383",
        "https://www.mdpi.com/2071-1050/14/6/3514",
    ),
    "cowpea": ("https://pmc.ncbi.nlm.nih.gov/articles/PMC11759354/",),
    "groundnut": ("https://cspace.csirgh.com/items/show/139",),
    "cassava": ("https://onlinelibrary.wiley.com/doi/full/10.1155/2022/9077383",),
    "yam": (
        "https://onlinelibrary.wiley.com/doi/full/10.1155/2022/9077383",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC10008982/",
    ),
    "rice": ("https://eprints.whiterose.ac.uk/id/eprint/189376/",),
}
LABOUR_FEASIBILITY_SOURCES = (
    "https://hdl.handle.net/10568/154236",
    "https://biblio.iita.org/documents/U17ArtKermahMaizegrainInthomDev.pdf-445c35e8e1f6327f3454293ca87e73c6.pdf",
)


class FarmAssessmentContext(BaseModel):
    """Non-coordinate farm facts that may contextualize a pure assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location_key: str | None = None
    soil_texture: str | None = None
    irrigation_access: str | None = None
    soil_fertility_context: str | None = None
    residue_management: str | None = None
    crop_varieties: dict[str, str] = Field(default_factory=dict)


def build_crop_evidence_option(
    candidate: RotationCandidate,
    historical_indicators: tuple[EnvironmentalIndicator, ...],
    *,
    farm_context: FarmAssessmentContext | None = None,
    prior_crop_history: tuple[str, ...] | None = None,
    environmental_context_ready: bool = False,
) -> RotationOptionEvidence:
    """Assess one full sequence; never turn missing crop or farm data into a rating."""

    context = farm_context or FarmAssessmentContext()
    crop_profiles = tuple(CROP_PROFILES.get(event.crop.crop_id) for event in candidate.events)
    event_assessments = _assess_events(candidate, crop_profiles, context)
    water = _assess_sequence_water(
        candidate,
        crop_profiles,
        historical_indicators,
        context,
        environmental_context_ready=environmental_context_ready,
    )
    transitions = _assess_sequence_transitions(
        candidate,
        crop_profiles,
        context,
        prior_crop_history=prior_crop_history,
    )
    soil = _not_assessed_soil(context, transitions)
    yield_stability = _not_assessed_yield_stability(candidate, historical_indicators)
    labor_feasibility = _not_assessed_labor(candidate, historical_indicators, context)

    water_is_assessed = water.status == "assessed"
    bottleneck = water.rating
    benefits = (
        (
            f"No crop in this sequence falls below the provisional {bottleneck} "
            "water-resilience class.",
        )
        if water_is_assessed and bottleneck is not None
        else ()
    )
    assumptions = [
        "Crop-level water classes are desk-based and provisional; local agronomic "
        "review remains outstanding.",
        "Historical NASA indicators describe past analysis periods and are not future "
        "weather or a crop water-balance calculation.",
        "Future recommendation windows are not source-reviewed crop calendars.",
    ]
    if context.irrigation_access is None:
        assumptions.append("Farm irrigation access is unknown and was not inferred.")
    if context.soil_texture is None:
        assumptions.append(
            "Plot soil texture is unknown and was not inferred from the municipality."
        )
    if prior_crop_history is None:
        assumptions.append("Prior crop history is unavailable; no predecessor crop was invented.")

    return RotationOptionEvidence(
        candidate=candidate,
        event_assessments=event_assessments,
        transition_assessments=transitions,
        criteria=(water, soil, yield_stability, labor_feasibility),
        benefits=benefits,
        trade_offs=(
            "Relative water resilience does not establish crop water requirement, "
            "field water sufficiency, crop suitability, or yield.",
            "Context-specific rotation relationships remain review-needed until "
            "variety, residue, soil, and location conditions are known.",
        ),
        assumptions=tuple(assumptions),
    )


def _assess_events(
    candidate: RotationCandidate,
    profiles: tuple[CropProfile | None, ...],
    farm_context: FarmAssessmentContext,
) -> tuple[EventAssessment, ...]:
    """Record why crop/calendar fit is or is not assessable for each event."""

    assessments: list[EventAssessment] = []
    for candidate_event, profile in zip(candidate.events, profiles, strict=True):
        missing: list[str] = []
        if profile is None:
            missing.append("versioned crop profile")
        else:
            if profile.maturity_days_min is None or profile.maturity_days_max is None:
                missing.append("sourced crop maturity duration")
            if profile.calendar_status != "locally_validated":
                missing.append("locally reviewed crop/community planting calendar")
            if not profile.production_systems:
                missing.append("crop production system where it affects suitability")
        if candidate_event.event.calendar_status != "locally_validated":
            missing.append("locally validated event calendar")
        if farm_context.soil_texture is None:
            missing.append("reported plot soil texture for crop suitability review")
        if farm_context.irrigation_access is None:
            missing.append("reported farm water access for crop suitability review")

        crop_id = candidate_event.crop.crop_id
        if profile is None:
            status: Literal["needs_review", "not_assessed"] = "not_assessed"
            rationale = "No versioned crop profile exists; this event cannot be assessed."
        else:
            status = "needs_review"
            rationale = (
                "The candidate window represents a future planting slot, not a verified "
                "growing-period span. Crop duration, local calendar fit, production-system "
                "compatibility, and farm suitability are not established."
            )
            if crop_id == "rice":
                rationale += (
                    " Rice ecology is unspecified; upland, rain-fed lowland, and irrigated "
                    "systems are not interchangeable."
                )
        assessments.append(
            EventAssessment(
                event_order=candidate_event.event.order,
                crop_id=crop_id,
                status=status,
                calendar_status=candidate_event.event.calendar_status,
                rationale=rationale,
                required_context_missing=tuple(dict.fromkeys(missing)),
            )
        )
    return tuple(assessments)


def _assess_sequence_water(
    candidate: RotationCandidate,
    profiles: tuple[CropProfile | None, ...],
    indicators: tuple[EnvironmentalIndicator, ...],
    farm_context: FarmAssessmentContext,
    *,
    environmental_context_ready: bool,
) -> CriterionEvidence:
    """Apply the approved weakest-crop water-resilience rule to all three events."""

    if not environmental_context_ready:
        return CriterionEvidence(
            criterion="water_resilience",
            status="not_assessed",
            rationale=(
                "The past-season NASA context is insufficient for assessment. NY-13 requires "
                "at least two of the three approved indicators to have usable values for "
                "each historical period; missing values remain unavailable."
            ),
            environmental_inputs=indicators,
            assumptions=(
                "Available partial values retain their coverage metadata; no values were imputed.",
                "No overall ranking is produced without comparable primary water evidence.",
            ),
        )

    evidence: list[tuple[str, CropProfile, WaterRating, Confidence, tuple[str, ...]]] = []
    unknown_crops: list[str] = []
    for event, profile in zip(candidate.events, profiles, strict=True):
        trait = profile.trait("water_resilience_class") if profile is not None else None
        if (
            profile is None
            or trait is None
            or trait.value not in ("high", "moderate", "low")
            or trait.confidence is None
            or trait.evidence_status == "unknown"
        ):
            unknown_crops.append(event.crop.display_name)
            continue
        evidence.append(
            (
                event.crop.display_name,
                profile,
                trait.value,  # type: ignore[arg-type]
                trait.confidence,
                tuple(reference for reference in trait.source_reference.split("; ") if reference),
            )
        )

    if unknown_crops or len(evidence) != len(candidate.events):
        return CriterionEvidence(
            criterion="water_resilience",
            status="not_assessed",
            rationale=(
                "Comparable sequence water-resilience evidence is unavailable for: "
                f"{', '.join(unknown_crops)}. No rating was inferred."
            ),
            environmental_inputs=indicators,
            assumptions=(
                "Rice remains unassessed until its production system is identified.",
                "Historical NASA values are contextual provenance, not a crop-water balance.",
            ),
        )

    order = {"low": 1, "moderate": 2, "high": 3}
    rating: WaterRating = min((item[2] for item in evidence), key=order.__getitem__)
    confidence_order = {"low": 1, "moderate": 2, "high": 3}
    confidence = min((item[3] for item in evidence), key=confidence_order.__getitem__)
    summaries = "; ".join(
        f"season {event.event.order} {item[0]}: {item[2]}"
        for event, item in zip(candidate.events, evidence, strict=True)
    )
    references = tuple(dict.fromkeys(reference for item in evidence for reference in item[4]))
    context_notes = []
    if farm_context.irrigation_access is not None:
        context_notes.append(
            f"Reported farm irrigation access is {farm_context.irrigation_access!r}; "
            "it does not alter the crop-level class without a reviewed rule."
        )
    if farm_context.location_key is not None:
        context_notes.append(
            f"The supported location key is {farm_context.location_key!r}; "
            "no field coordinates are used in this assessment."
        )
    return CriterionEvidence(
        criterion="water_resilience",
        status="assessed",
        rating=rating,
        confidence=confidence,
        rationale=(
            "Sequence class uses the least water-resilient crop as a conservative "
            f"bottleneck ({summaries}). Ratings are relative and provisional. "
            "Historical NASA indicators are preserved as context; they do not "
            "change this crop-level class. " + " ".join(context_notes)
        ),
        comparison_basis="ny8-water-resilience-desk-synthesis-v1",
        evidence_references=references,
        environmental_inputs=indicators,
        assumptions=(
            "The weakest-crop rule is a deterministic implementation choice, not a "
            "locally validated agronomic threshold.",
            "FAO crop-water need ranges are rough growing-period estimates; they are "
            "not used as farm irrigation requirements.",
            "Temperature and precipitation alone do not provide ET0, crop stage, "
            "effective rainfall, soil-water storage, or irrigation scheduling.",
        ),
    )


def _assess_sequence_transitions(
    candidate: RotationCandidate,
    profiles: tuple[CropProfile | None, ...],
    farm_context: FarmAssessmentContext,
    *,
    prior_crop_history: tuple[str, ...] | None,
) -> tuple[TransitionAssessment, ...]:
    """Evaluate ordered historical/current and within-sequence crop pairs."""

    pairs: list[tuple[str | None, str]] = []
    if prior_crop_history:
        pairs.append((prior_crop_history[-1], candidate.events[0].crop.crop_id))
    else:
        pairs.append((None, candidate.events[0].crop.crop_id))
    pairs.extend(
        (candidate.events[index].crop.crop_id, candidate.events[index + 1].crop.crop_id)
        for index in range(len(candidate.events) - 1)
    )

    output: list[TransitionAssessment] = []
    for predecessor, successor in pairs:
        if predecessor is None:
            output.append(
                TransitionAssessment(
                    predecessor_crop_id=None,
                    successor_crop_id=successor,
                    status="needs_review",
                    rationale=(
                        "The crop before the first recommendation event is unknown; "
                        "no transition effect was assumed."
                    ),
                    required_context_missing=("reported predecessor crop history",),
                )
            )
            continue

        relationship = _find_transition(predecessor, successor)
        if relationship is None:
            output.append(
                TransitionAssessment(
                    predecessor_crop_id=predecessor,
                    successor_crop_id=successor,
                    status="not_assessed",
                    rationale=(
                        "No reviewed, crop-specific transition evidence is registered for "
                        "this ordered pair. Crop family alone does not imply a benefit."
                    ),
                )
            )
            continue

        missing = _missing_transition_context(
            relationship,
            predecessor,
            successor,
            farm_context,
        )
        output.append(
            TransitionAssessment(
                relationship_id=relationship.relationship_id,
                predecessor_crop_id=predecessor,
                successor_crop_id=successor,
                status="needs_review" if missing else "assessed",
                rationale=(
                    f"{relationship.study_scope} This source is context-specific and does "
                    "not supply an automatic nitrogen credit or soil-health score."
                ),
                evidence_references=(relationship.source_reference,),
                required_context_missing=missing,
            )
        )
    return tuple(output)


def _find_transition(
    predecessor: str,
    successor: str,
) -> CropTransitionEvidence | None:
    return next(
        (
            item
            for item in CROP_TRANSITION_EVIDENCE
            if item.predecessor_crop_id == predecessor and item.successor_crop_id == successor
        ),
        None,
    )


def _missing_transition_context(
    relationship: CropTransitionEvidence,
    predecessor: str,
    successor: str,
    farm_context: FarmAssessmentContext,
) -> tuple[str, ...]:
    """Report missing match conditions without treating profile blanks as negatives."""

    missing: list[str] = []
    if not farm_context.crop_varieties.get(predecessor) or not farm_context.crop_varieties.get(
        successor
    ):
        missing.append("crop varieties and study-sequence match")
    if farm_context.residue_management is None:
        missing.append("residue retention/removal/return practice")
    if farm_context.soil_fertility_context is None:
        missing.append("field soil-fertility and management context")
    if relationship.evidence_status != "locally_validated":
        missing.append("local validation for the Ejura farm and its production system")
    return tuple(dict.fromkeys(missing))


def _not_assessed_soil(
    context: FarmAssessmentContext,
    transitions: tuple[TransitionAssessment, ...],
) -> CriterionEvidence:
    """Keep soil unknown unless comparable, sequence-specific evidence exists."""

    review_count = sum(item.status == "needs_review" for item in transitions)
    reason = (
        "Soil-health potential is not assessed for this sequence."
        if review_count == 0
        else (
            f"Soil-health potential is not assessed; {review_count} transition(s) "
            "have source evidence that still needs context or local review."
        )
    )
    assumptions = [
        "No nitrogen credit is assigned from crop family or legume status.",
        "Soil-health potential is not a measured soil condition or guaranteed improvement.",
    ]
    if context.soil_texture is None:
        assumptions.append("Plot soil texture is unknown.")
    if context.residue_management is None:
        assumptions.append("Crop residue fate is unknown.")
    if context.soil_fertility_context is None:
        assumptions.append("Field soil-fertility measurements are unavailable.")
    return CriterionEvidence(
        criterion="soil_health_potential",
        status="not_assessed",
        rationale=reason,
        evidence_references=tuple(
            dict.fromkeys(
                reference
                for transition in transitions
                for reference in transition.evidence_references
            )
        ),
        assumptions=tuple(assumptions),
    )


def _not_assessed_yield_stability(
    candidate: RotationCandidate,
    indicators: tuple[EnvironmentalIndicator, ...],
) -> CriterionEvidence:
    """Retain crop-specific study references without inventing a stability rating."""

    references = tuple(
        dict.fromkeys(
            reference
            for event in candidate.events
            for reference in YIELD_STABILITY_SOURCES.get(event.crop.crop_id, ())
        )
    )
    return CriterionEvidence(
        criterion="yield_stability_proxy",
        status="not_assessed",
        rationale=(
            "The available studies are crop-, variety-, site-, or year-specific and do not "
            "establish a comparable yield-stability rating for this three-event sequence. "
            "No yield estimate or crop-failure probability is inferred."
        ),
        evidence_references=references,
        environmental_inputs=indicators,
        assumptions=(
            "Historical NASA indicators describe past periods and are not a future yield forecast.",
            "Variety-specific and sequence-level stability evidence is still required.",
        ),
    )


def _not_assessed_labor(
    candidate: RotationCandidate,
    indicators: tuple[EnvironmentalIndicator, ...],
    farm_context: FarmAssessmentContext,
) -> CriterionEvidence:
    """Record labor research while requiring actual farm capacity inputs for feasibility."""

    crop_references = {
        reference
        for event in candidate.events
        for reference in LABOUR_FEASIBILITY_SOURCES
        if event.crop.crop_id != "rice"
    }
    if any(event.crop.crop_id == "rice" for event in candidate.events):
        crop_references.add(
            "https://www.jica.go.jp/english/our_work/thematic_issues/agricultural/pdf/ghana_en.pdf"
        )
    assumptions = [
        "Published operation-day estimates vary by crop system and management; "
        "they are not this farm's labor capacity.",
        "Labor feasibility requires operation timing, available household/hired "
        "labor, plot area, and machinery or service access.",
    ]
    if farm_context.residue_management is None:
        assumptions.append(
            "Crop residue and land-preparation practices are not available as labor inputs."
        )
    return CriterionEvidence(
        criterion="labor_feasibility",
        status="not_assessed",
        rationale=(
            "Published Ghana labor estimates are operation- and system-specific; the farm profile "
            "does not capture labor availability, plot area, machinery access, "
            "or operation timing. "
            "A farm-specific feasibility rating would be unsupported."
        ),
        evidence_references=tuple(sorted(crop_references)),
        environmental_inputs=indicators,
        assumptions=tuple(assumptions),
    )
