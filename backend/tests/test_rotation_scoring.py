"""NY-8 scoring tests use synthetic ratings, not public recommendation data."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.decisions.rotation import (
    CandidatePlantingEvent,
    CandidateRuleFinding,
    CropCandidate,
    PlantingEventSlot,
    RotationCandidate,
)
from app.decisions.scoring import (
    CRITERIA,
    CriterionEvidence,
    HardConstraintFinding,
    PriorityPoints,
    RotationOptionEvidence,
    ScoringRequest,
    score_rotation_options,
)
from app.indicators.environmental import EnvironmentalIndicator, IndicatorCoverage

TEST_SOURCE = "synthetic scoring test fixture"
COMPARISON_BASIS = "synthetic-rating-method-v1"


def make_candidate(
    candidate_id: str,
    crop_ids: tuple[str, str, str],
    *,
    findings: tuple[CandidateRuleFinding, ...] = (),
) -> RotationCandidate:
    """Construct a synthetic three-event candidate for scoring unit tests."""

    events = tuple(
        PlantingEventSlot(
            event_id=f"{candidate_id}-event-{order}",
            order=order,
            plot_id="synthetic-test-plot",
            season_label=f"synthetic-season-{order}",
            window_start=date(2024, order, 1),
            window_end=date(2024, order, 28),
            calendar_status="locally_validated",
            calendar_source=TEST_SOURCE,
            calendar_source_version="fixture-v1",
        )
        for order in (1, 2, 3)
    )
    crop_events = tuple(
        CandidatePlantingEvent(
            event=event,
            crop=CropCandidate(
                crop_id=crop_id,
                display_name=crop_id.title(),
                suitability_status="locally_validated",
                evidence_references=(TEST_SOURCE,),
            ),
        )
        for event, crop_id in zip(events, crop_ids, strict=True)
    )
    return RotationCandidate(
        candidate_id=candidate_id,
        kind="alternative",
        events=crop_events,
        readiness="structurally_valid",
        rule_findings=(
            CandidateRuleFinding(
                rule_id="ROT-001",
                outcome="passed",
                explanation="Synthetic sequence-continuity fixture.",
                evidence_references=(TEST_SOURCE,),
            ),
            CandidateRuleFinding(
                rule_id="ROT-002",
                outcome="passed",
                explanation="Synthetic prior-history fixture.",
                evidence_references=(TEST_SOURCE,),
            ),
            CandidateRuleFinding(
                rule_id="ROT-003",
                outcome="passed",
                explanation="Synthetic calendar fixture.",
                evidence_references=(TEST_SOURCE,),
            ),
            *findings,
        ),
    )


def make_criterion(
    criterion: str,
    rating: str | None,
    *,
    status: str = "assessed",
    comparison_basis: str | None = COMPARISON_BASIS,
    environmental_inputs: tuple[EnvironmentalIndicator, ...] = (),
) -> CriterionEvidence:
    """Build one synthetic evidence record, including explicit unknowns."""

    if status == "not_assessed":
        return CriterionEvidence(
            criterion=criterion,  # type: ignore[arg-type]
            status="not_assessed",
            rationale="Synthetic fixture marks this criterion as unknown.",
        )
    return CriterionEvidence(
        criterion=criterion,  # type: ignore[arg-type]
        status="assessed",
        rating=rating,  # type: ignore[arg-type]
        confidence="moderate",
        rationale="Synthetic fixture rating for deterministic algorithm tests.",
        comparison_basis=comparison_basis,
        evidence_references=() if environmental_inputs else (TEST_SOURCE,),
        environmental_inputs=environmental_inputs,
        assumptions=("Synthetic values are not agronomic claims.",),
    )


def make_option(
    candidate_id: str,
    crop_ids: tuple[str, str, str],
    ratings: tuple[str, str, str, str] | None,
    *,
    hard_constraints: tuple[HardConstraintFinding, ...] = (),
    missing_criterion: str | None = None,
    different_basis_for: str | None = None,
    candidate_findings: tuple[CandidateRuleFinding, ...] = (),
    water_inputs: tuple[EnvironmentalIndicator, ...] = (),
) -> RotationOptionEvidence:
    """Build one synthetic option with the four research-defined criteria."""

    criteria = (
        tuple(
            make_criterion(
                criterion,
                rating,
                status="not_assessed" if criterion == missing_criterion else "assessed",
                comparison_basis=(
                    "other-synthetic-method-v1"
                    if criterion == different_basis_for
                    else COMPARISON_BASIS
                ),
                environmental_inputs=water_inputs if criterion == "water_resilience" else (),
            )
            for criterion, rating in zip(CRITERIA, ratings, strict=True)
        )
        if ratings is not None
        else ()
    )
    return RotationOptionEvidence(
        candidate=make_candidate(candidate_id, crop_ids, findings=candidate_findings),
        hard_constraints=hard_constraints,
        criteria=criteria,
        benefits=("Synthetic evidence-backed benefit placeholder.",),
        trade_offs=("Synthetic evidence-backed trade-off placeholder.",),
        assumptions=("Synthetic fixture only; do not use as a demo recommendation.",),
    )


def make_request(
    *,
    farmer_priorities: PriorityPoints | None = None,
    options: tuple[RotationOptionEvidence, ...] | None = None,
) -> ScoringRequest:
    """Build a repeatable, synthetic three-option comparison."""

    if options is None:
        options = (
            make_option(
                "option-a", ("maize", "cowpea", "yam"), ("high", "moderate", "low", "moderate")
            ),
            make_option("option-b", ("cowpea", "yam", "rice"), ("low", "high", "moderate", "high")),
            make_option(
                "option-c", ("yam", "rice", "maize"), ("moderate", "moderate", "high", "low")
            ),
        )
    return ScoringRequest(options=options, farmer_priorities=farmer_priorities)


def make_cached_rainfall_indicator() -> EnvironmentalIndicator:
    """Create a source-provenance DTO as if NY-7 had calculated a cached input."""

    return EnvironmentalIndicator(
        code="seasonal_precipitation_total",
        name="Seasonal precipitation total",
        definition="Sum of valid daily precipitation values over the requested period.",
        calculation_method="sum",
        value=300.0,
        units="mm/season",
        status="complete",
        data_status="cached",
        source="NASA POWER",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        coverage=IndicatorCoverage(
            expected_days=91,
            valid_days=91,
            missing_days=0,
            coverage_percent=100,
        ),
        spatial_resolution="synthetic test grid",
    )


def test_default_equal_weights_are_visible_and_ties_are_not_broken_into_winners() -> None:
    request = make_request()
    result = score_rotation_options(request)
    repeated = score_rotation_options(request)

    assert [share.percent for share in result.default_weights.normalized_weights] == [
        25,
        25,
        25,
        25,
    ]
    assert result.default_weights.source == "default_equal"
    assert result.equal_weight_ranking.rank_groups == (("option-b",), ("option-a", "option-c"))
    assert result.equal_weight_ranking.status == "ranked"
    assert result.sensitivity == "not_applicable"
    assert result.rating_scale == "relative_qualitative"
    assert result.model_dump() == repeated.model_dump()
    assert not hasattr(result.options[0], "composite_score")


def test_farmer_priorities_normalize_and_weight_change_is_reported() -> None:
    priorities = PriorityPoints(
        water_resilience=100,
        soil_health_potential=0,
        yield_stability_proxy=0,
        labor_feasibility=0,
    )

    result = score_rotation_options(make_request(farmer_priorities=priorities))

    selected_weights = {
        weight.criterion: weight.percent for weight in result.selected_weights.normalized_weights
    }
    assert selected_weights == {
        "water_resilience": 100,
        "soil_health_potential": 0,
        "yield_stability_proxy": 0,
        "labor_feasibility": 0,
    }
    assert sum(selected_weights.values()) == 100
    assert result.selected_weights.source == "farmer_selected"
    assert result.selected_weight_ranking.rank_groups == (
        ("option-a",),
        ("option-c",),
        ("option-b",),
    )
    assert result.sensitivity == "weight_sensitive"


def test_missing_criterion_is_preserved_and_withholds_the_overall_rank() -> None:
    options = (
        make_option(
            "option-a", ("maize", "cowpea", "yam"), ("high", "moderate", "low", "moderate")
        ),
        make_option(
            "option-b",
            ("cowpea", "yam", "rice"),
            ("low", "high", "moderate", "high"),
            missing_criterion="soil_health_potential",
        ),
        make_option("option-c", ("yam", "rice", "maize"), ("moderate", "moderate", "high", "low")),
    )

    result = score_rotation_options(make_request(options=options))

    assert result.equal_weight_ranking.status == "withheld"
    assert result.equal_weight_ranking.rank_groups == ()
    assert any(
        "soil_health_potential is not assessed" in reason
        for reason in result.equal_weight_ranking.reasons
    )
    missing = next(
        option for option in result.options if option.candidate.candidate_id == "option-b"
    )
    soil = next(item for item in missing.criteria if item.criterion == "soil_health_potential")
    assert soil.rating is None
    assert soil.equal_weight_percent == 25
    assert soil.selected_weight_percent == 25


def test_incomparable_evidence_withholds_rank_even_when_all_ratings_exist() -> None:
    options = (
        make_option(
            "option-a",
            ("maize", "cowpea", "yam"),
            ("high", "moderate", "low", "moderate"),
            different_basis_for="water_resilience",
        ),
        make_option("option-b", ("cowpea", "yam", "rice"), ("low", "high", "moderate", "high")),
    )

    result = score_rotation_options(make_request(options=options))

    assert result.equal_weight_ranking.status == "withheld"
    assert any(
        "water_resilience evidence uses incomparable" in reason
        for reason in result.equal_weight_ranking.reasons
    )
    assert all(item.rating is not None for option in result.options for item in option.criteria)


def test_failed_hard_constraint_excludes_option_before_weighted_comparison() -> None:
    failed = HardConstraintFinding(
        rule_id="TEST-HARD-GATE",
        outcome="failed",
        rationale="Synthetic hard-constraint failure.",
        evidence_references=(TEST_SOURCE,),
    )
    options = (
        make_option(
            "option-a",
            ("maize", "cowpea", "yam"),
            None,
            hard_constraints=(failed,),
        ),
        make_option("option-b", ("cowpea", "yam", "rice"), ("low", "high", "moderate", "high")),
        make_option("option-c", ("yam", "rice", "maize"), ("moderate", "moderate", "high", "low")),
    )

    result = score_rotation_options(
        make_request(
            farmer_priorities=PriorityPoints(
                water_resilience=100,
                soil_health_potential=0,
                yield_stability_proxy=0,
                labor_feasibility=0,
            ),
            options=options,
        )
    )

    assert [option.candidate.candidate_id for option in result.excluded_options] == ["option-a"]
    assert [option.candidate.candidate_id for option in result.options] == ["option-b", "option-c"]
    assert result.selected_weight_ranking.rank_groups == (("option-c",), ("option-b",))


def test_hard_constraint_needs_review_keeps_partial_ratings_but_withholds_rank() -> None:
    needs_review = HardConstraintFinding(
        rule_id="TEST-HARD-GATE",
        outcome="needs_review",
        rationale="Synthetic required input needs review.",
    )
    options = (
        make_option(
            "option-a",
            ("maize", "cowpea", "yam"),
            ("high", "moderate", "low", "moderate"),
            hard_constraints=(needs_review,),
        ),
        make_option("option-b", ("cowpea", "yam", "rice"), ("low", "high", "moderate", "high")),
    )

    result = score_rotation_options(make_request(options=options))

    assert result.equal_weight_ranking.status == "withheld"
    assert len(result.options) == 2
    assert len(result.options[0].criteria) == 4
    assert any("needs review" in reason for reason in result.equal_weight_ranking.reasons)


def test_rotation_generation_review_findings_block_rank_except_soft_repeat_warning() -> None:
    blocking = CandidateRuleFinding(
        rule_id="ROT-003",
        outcome="needs_review",
        explanation="Synthetic provisional calendar.",
        evidence_references=(TEST_SOURCE,),
    )
    soft = CandidateRuleFinding(
        rule_id="ROT-004",
        outcome="needs_review",
        explanation="Synthetic repeated-crop warning.",
        evidence_references=(TEST_SOURCE,),
    )
    options = (
        make_option(
            "option-a",
            ("maize", "cowpea", "yam"),
            ("high", "moderate", "low", "moderate"),
            candidate_findings=(blocking,),
        ),
        make_option(
            "option-b",
            ("cowpea", "cowpea", "rice"),
            ("low", "high", "moderate", "high"),
            candidate_findings=(soft,),
        ),
    )

    result = score_rotation_options(make_request(options=options))

    assert result.equal_weight_ranking.status == "withheld"
    assert any("ROT-003 needs review" in reason for reason in result.equal_weight_ranking.reasons)
    repeated = next(
        option for option in result.options if option.candidate.candidate_id == "option-b"
    )
    assert any("ROT-004" in warning for warning in repeated.warnings)

    soft_review_only = score_rotation_options(
        make_request(
            options=(
                options[1],
                make_option(
                    "option-c",
                    ("yam", "rice", "maize"),
                    ("moderate", "moderate", "high", "low"),
                ),
            )
        )
    )
    assert soft_review_only.equal_weight_ranking.status == "ranked"


def test_environmental_indicator_provenance_is_returned_with_criterion_rating() -> None:
    indicator = make_cached_rainfall_indicator()
    options = (
        make_option(
            "option-a",
            ("maize", "cowpea", "yam"),
            ("high", "moderate", "low", "moderate"),
            water_inputs=(indicator,),
        ),
        make_option(
            "option-b",
            ("cowpea", "yam", "rice"),
            ("moderate", "high", "moderate", "high"),
        ),
    )

    result = score_rotation_options(make_request(options=options))
    option_a = next(
        option for option in result.options if option.candidate.candidate_id == "option-a"
    )
    water_result = next(item for item in option_a.criteria if item.criterion == "water_resilience")

    assert water_result.environmental_inputs == (indicator,)
    assert water_result.environmental_inputs[0].data_status == "cached"
    assert water_result.environmental_inputs[0].coverage.coverage_percent == 100


def test_ties_are_ordered_stably_for_display_but_remain_one_rank_group() -> None:
    options = (
        make_option(
            "option-z", ("maize", "cowpea", "yam"), ("high", "moderate", "low", "moderate")
        ),
        make_option("option-a", ("cowpea", "yam", "rice"), ("high", "moderate", "low", "moderate")),
    )

    result = score_rotation_options(make_request(options=options))

    assert result.equal_weight_ranking.rank_groups == (("option-a", "option-z"),)


def test_priority_points_must_have_a_positive_total() -> None:
    with pytest.raises(ValidationError, match="positive value"):
        PriorityPoints(
            water_resilience=0,
            soil_health_potential=0,
            yield_stability_proxy=0,
            labor_feasibility=0,
        )


def test_assessed_criterion_requires_rationale_and_source_evidence() -> None:
    with pytest.raises(ValidationError, match="sourced evidence"):
        CriterionEvidence(
            criterion="water_resilience",
            status="assessed",
            rating="high",
            confidence="moderate",
            rationale="No source was supplied.",
            comparison_basis=COMPARISON_BASIS,
        )


def test_unavailable_indicator_cannot_be_the_only_evidence_for_a_rating() -> None:
    unavailable = make_cached_rainfall_indicator().model_copy(
        update={"status": "unavailable", "data_status": "unavailable", "value": None}
    )

    with pytest.raises(ValidationError, match="sourced evidence"):
        CriterionEvidence(
            criterion="water_resilience",
            status="assessed",
            rating="high",
            confidence="moderate",
            rationale="Unavailable values cannot support this synthetic rating.",
            comparison_basis=COMPARISON_BASIS,
            environmental_inputs=(unavailable,),
        )


def test_failed_hard_constraint_cannot_be_given_criterion_assessments() -> None:
    failed = HardConstraintFinding(
        rule_id="TEST-HARD-GATE",
        outcome="failed",
        rationale="Synthetic hard-constraint failure.",
        evidence_references=(TEST_SOURCE,),
    )

    with pytest.raises(ValidationError, match="excluded before assessment"):
        make_option(
            "invalid-option",
            ("maize", "cowpea", "yam"),
            ("high", "moderate", "low", "moderate"),
            hard_constraints=(failed,),
        )


def test_partial_environmental_indicator_data_withholds_overall_rank() -> None:
    complete = make_cached_rainfall_indicator()
    partial = complete.model_copy(
        update={
            "status": "partial",
            "coverage": IndicatorCoverage(
                expected_days=91,
                valid_days=80,
                missing_days=11,
                coverage_percent=87.91,
            ),
        }
    )
    options = (
        make_option(
            "option-a",
            ("maize", "cowpea", "yam"),
            ("high", "moderate", "low", "moderate"),
            water_inputs=(partial,),
        ),
        make_option(
            "option-b",
            ("cowpea", "yam", "rice"),
            ("moderate", "high", "moderate", "high"),
        ),
    )

    result = score_rotation_options(make_request(options=options))

    assert result.equal_weight_ranking.status == "withheld"
    assert any(
        "partial or unavailable environmental data" in reason
        for reason in result.equal_weight_ranking.reasons
    )


def test_normalized_weight_rounding_keeps_zero_priorities_at_zero() -> None:
    priorities = PriorityPoints(
        water_resilience=13,
        soil_health_potential=17,
        yield_stability_proxy=19,
        labor_feasibility=0,
    )

    result = score_rotation_options(make_request(farmer_priorities=priorities))
    normalized = result.selected_weights.normalized_weights

    assert sum(item.percent for item in normalized) == 100
    assert next(item.percent for item in normalized if item.criterion == "labor_feasibility") == 0
