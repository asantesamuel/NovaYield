"""Crop library and sequence assessments keep evidence scoped and missingness explicit."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.decisions.crop_evidence import (
    FarmAssessmentContext,
    build_crop_evidence_option,
)
from app.decisions.crop_profiles import (
    CROP_LIBRARY_VERSION,
    CROP_PROFILES,
    CropProfile,
    CropTraitEvidence,
)
from app.decisions.rotation import (
    CandidatePlantingEvent,
    CropCandidate,
    PlantingEventSlot,
    RotationCandidate,
)
from app.decisions.scoring import ScoringRequest, score_rotation_options

SYNTHETIC_SOURCE = "synthetic profile unit-test fixture"


def make_candidate(crop_ids: tuple[str, str, str]) -> RotationCandidate:
    """Build a deterministic event sequence without claiming farm evidence."""

    events = tuple(
        PlantingEventSlot(
            event_id=f"event-{order}",
            order=order,
            plot_id="synthetic-plot",
            season_label=f"season-{order}",
            window_start=date(2024, order, 1),
            window_end=date(2024, order, 28),
        )
        for order in (1, 2, 3)
    )
    paired = tuple(
        CandidatePlantingEvent(
            event=event,
            crop=CropCandidate(crop_id=crop_id, display_name=crop_id.title()),
        )
        for event, crop_id in zip(events, crop_ids, strict=True)
    )
    return RotationCandidate(
        candidate_id="alternative:" + "|".join(crop_ids),
        kind="alternative",
        events=paired,
        readiness="needs_review",
        rule_findings=(),
    )


def test_crop_library_has_one_versioned_profile_for_each_mvp_crop() -> None:
    assert CROP_LIBRARY_VERSION == "ny8-crop-library-v1"
    assert set(CROP_PROFILES) == {
        "maize",
        "cowpea",
        "groundnut",
        "cassava",
        "yam",
        "rice",
    }
    assert CROP_PROFILES["maize"].trait("seasonal_crop_water_need").minimum == 500
    assert CROP_PROFILES["maize"].trait("seasonal_crop_water_need").maximum == 800
    assert CROP_PROFILES["rice"].production_systems == ()
    assert CROP_PROFILES["rice"].trait("water_resilience_class") is None


def test_crop_trait_validation_requires_sources_and_preserves_unknown_values() -> None:
    with pytest.raises(ValidationError, match="Unknown traits"):
        CropTraitEvidence(
            trait_name="nitrogen_credit",
            value=25.0,
            evidence_status="unknown",
        )

    with pytest.raises(ValidationError, match="require a source reference"):
        CropTraitEvidence(
            trait_name="drought_sensitivity",
            value="high",
            evidence_status="provisional",
        )

    unknown = CropTraitEvidence(trait_name="soil_requirement")
    assert unknown.value is None
    assert unknown.minimum is None
    assert unknown.evidence_status == "unknown"


def test_profile_calendar_requires_applicability_and_version_when_populated() -> None:
    with pytest.raises(ValidationError, match="sourced calendar"):
        CropProfile(
            crop_id="crop-a",
            common_name="Crop A",
            identity_source_reference=SYNTHETIC_SOURCE,
            calendar_status="provisional",
            planting_window="April",
        )


def test_supported_transition_stays_review_needed_without_required_context() -> None:
    evidence = build_crop_evidence_option(
        make_candidate(("cowpea", "maize", "yam")),
        historical_indicators=(),
        farm_context=FarmAssessmentContext(
            location_key="ejura",
            soil_texture="sandy loam",
            irrigation_access="unknown",
        ),
        prior_crop_history=("groundnut",),
    )

    cowpea_to_maize = next(
        item
        for item in evidence.transition_assessments
        if item.predecessor_crop_id == "cowpea" and item.successor_crop_id == "maize"
    )
    soil = next(item for item in evidence.criteria if item.criterion == "soil_health_potential")

    assert cowpea_to_maize.status == "needs_review"
    assert cowpea_to_maize.evidence_references
    assert "residue retention/removal/return practice" in cowpea_to_maize.required_context_missing
    assert soil.status == "not_assessed"
    assert "nitrogen credit" in " ".join(soil.assumptions)


def test_unreviewed_transition_does_not_get_a_family_based_benefit() -> None:
    evidence = build_crop_evidence_option(
        make_candidate(("groundnut", "cowpea", "cassava")),
        historical_indicators=(),
        prior_crop_history=("maize",),
    )

    pair = next(
        item
        for item in evidence.transition_assessments
        if item.predecessor_crop_id == "groundnut" and item.successor_crop_id == "cowpea"
    )
    assert pair.status == "not_assessed"
    assert "family alone" in pair.rationale


def test_missing_prior_history_is_a_review_item_not_an_invented_crop() -> None:
    evidence = build_crop_evidence_option(
        make_candidate(("maize", "cowpea", "groundnut")),
        historical_indicators=(),
    )

    first_transition = evidence.transition_assessments[0]
    assert first_transition.predecessor_crop_id is None
    assert first_transition.status == "needs_review"
    assert "reported predecessor crop history" in first_transition.required_context_missing


def test_missing_past_environmental_context_withholds_the_primary_rating_and_rank() -> None:
    option = build_crop_evidence_option(
        make_candidate(("groundnut", "cowpea", "cassava")),
        historical_indicators=(),
    )
    second_option = build_crop_evidence_option(
        make_candidate(("maize", "cowpea", "yam")),
        historical_indicators=(),
    )
    result = score_rotation_options(ScoringRequest(options=(option, second_option)))
    water = next(item for item in option.criteria if item.criterion == "water_resilience")

    assert water.status == "not_assessed"
    assert result.ranking.status == "withheld"
    assert result.options == ()
    assert any("two of the three" in assumption for assumption in water.rationale.split("."))
