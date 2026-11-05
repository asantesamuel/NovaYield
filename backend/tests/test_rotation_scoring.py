"""NY-8 tests use synthetic ratings unless a test explicitly names public evidence."""

from datetime import date
from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128
from pydantic import ValidationError

from app.decisions.crop_evidence import build_crop_evidence_option
from app.decisions.rotation import (
    CandidatePlantingEvent,
    CandidateRuleFinding,
    CropCandidate,
    PlantingEventSlot,
    RotationCandidate,
)
from app.decisions.scoring import (
    CRITERIA,
    SCORING_VERSION,
    CriterionEvidence,
    HardConstraintFinding,
    PriorityPoints,
    RotationOptionEvidence,
    ScoringRequest,
    ScoringResult,
    score_rotation_options,
)

TEST_SOURCE = "synthetic scoring test fixture; not agronomic evidence"
WATER_BASIS = "synthetic-water-rating-v1"
SOIL_BASIS = "synthetic-soil-rating-v1"


def make_candidate(
    candidate_id: str,
    crop_ids: tuple[str, str, str],
    *,
    kind: str = "alternative",
) -> RotationCandidate:
    """Make a stable three-event candidate for unit tests."""

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
        kind=kind,  # type: ignore[arg-type]
        events=crop_events,
        readiness="structurally_valid",
        rule_findings=(
            CandidateRuleFinding(
                rule_id="synthetic-rule",
                outcome="needs_review",
                explanation="Synthetic test only.",
                evidence_references=(TEST_SOURCE,),
            ),
        ),
    )


def make_assessment(
    criterion: str,
    rating: str,
    *,
    basis: str,
) -> CriterionEvidence:
    """Build a sourced-shaped synthetic assessment, not real crop evidence."""

    return CriterionEvidence(
        criterion=criterion,  # type: ignore[arg-type]
        status="assessed",
        rating=rating,  # type: ignore[arg-type]
        confidence="low",
        rationale="Synthetic unit-test rating.",
        comparison_basis=basis,
        evidence_references=(TEST_SOURCE,),
        assumptions=("Synthetic input; never use as an agronomic recommendation.",),
    )


def make_option(
    candidate_id: str,
    crop_ids: tuple[str, str, str],
    water_rating: str | None,
    *,
    soil_rating: str | None = "moderate",
    yield_rating: str | None = "moderate",
    labor_rating: str | None = "moderate",
    water_basis: str = WATER_BASIS,
    soil_basis: str = SOIL_BASIS,
    water_status: str = "assessed",
    hard_constraints: tuple[HardConstraintFinding, ...] = (),
    kind: str = "alternative",
) -> RotationOptionEvidence:
    """Create an option with optional active criterion evidence."""

    criteria: list[CriterionEvidence] = []
    if water_status == "assessed" and water_rating is not None:
        criteria.append(make_assessment("water_resilience", water_rating, basis=water_basis))
    else:
        criteria.append(
            CriterionEvidence(
                criterion="water_resilience",
                status="not_assessed",
                rationale="Water evidence is intentionally missing in this test.",
            )
        )
    for criterion, rating in (
        ("soil_health_potential", soil_rating),
        ("yield_stability_proxy", yield_rating),
        ("labor_feasibility", labor_rating),
    ):
        if rating is None:
            criteria.append(
                CriterionEvidence(
                    criterion=criterion,  # type: ignore[arg-type]
                    status="not_assessed",
                    rationale=f"{criterion} evidence is intentionally missing in this test.",
                )
            )
        else:
            criteria.append(
                make_assessment(
                    criterion,
                    rating,
                    basis=soil_basis if criterion == "soil_health_potential" else WATER_BASIS,
                )
            )
    if any(item.outcome == "failed" for item in hard_constraints):
        criteria = []
    return RotationOptionEvidence(
        candidate=make_candidate(candidate_id, crop_ids, kind=kind),
        hard_constraints=hard_constraints,
        criteria=tuple(criteria),
        assumptions=("Synthetic test option.",),
    )


def test_farmer_priorities_reorder_four_criteria_and_disclose_tradeoffs() -> None:
    request = ScoringRequest(
        options=(
            make_option(
                "soil-winner",
                ("maize", "cowpea", "yam"),
                "moderate",
                soil_rating="high",
                yield_rating="high",
                labor_rating="high",
            ),
            make_option(
                "water-winner",
                ("cowpea", "yam", "groundnut"),
                "high",
                soil_rating="low",
                yield_rating="low",
                labor_rating="low",
            ),
        ),
        farmer_priorities=PriorityPoints(
            water_resilience=100,
            soil_health_potential=0,
            yield_stability_proxy=0,
            labor_feasibility=0,
        ),
    )

    result = score_rotation_options(request)

    assert [item.candidate.candidate_id for item in result.options] == [
        "water-winner",
        "soil-winner",
    ]
    assert result.equal_weight_ranking.rank_groups == (
        ("soil-winner",),
        ("water-winner",),
    )
    assert result.ranking_method == "weighted_ordinal_sum_v1"
    assert result.ranking_mode == "four_criterion"
    assert result.ranking.criteria_used == CRITERIA
    assert tuple(item.criterion for item in result.options[0].criteria) == CRITERIA
    assert [share.percent for share in result.selected_weights.normalized_weights] == [
        100,
        0,
        0,
        0,
    ]
    assert result.sensitivity == "weight_sensitive"
    assert result.ranking.tradeoffs[0].higher_ranked_candidate_id == "water-winner"
    assert result.ranking.tradeoffs[0].concessions
    assert "concessions" in result.ranking.tradeoffs[0].explanation
    assert any("Priority trade-off" in text for text in result.options[0].trade_offs)


def test_equal_weights_use_soil_rating_when_other_criteria_match() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option("soil-low", ("maize", "cowpea", "yam"), "moderate", soil_rating="low"),
                make_option(
                    "soil-high", ("cowpea", "yam", "groundnut"), "moderate", soil_rating="high"
                ),
            )
        )
    )

    assert [item.candidate.candidate_id for item in result.options] == [
        "soil-high",
        "soil-low",
    ]
    assert result.ranking.rank_groups == (("soil-high",), ("soil-low",))


def test_missing_one_criterion_uses_water_only_fallback_when_soil_is_not_comparable() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option("option-b", ("maize", "cowpea", "yam"), "high", soil_rating="high"),
                make_option(
                    "option-a",
                    ("cowpea", "yam", "groundnut"),
                    "high",
                    soil_rating=None,
                ),
            )
        )
    )

    assert result.ranking_mode == "water_soil_fallback"
    assert result.ranking.status == "ranked"
    assert result.ranking.criteria_used == ("water_resilience",)
    assert [item.candidate.candidate_id for item in result.options] == ["option-a", "option-b"]
    assert [share.percent for share in result.selected_weights.normalized_weights] == [
        100,
        0,
        0,
        0,
    ]
    assert any("Soil evidence is not comparable" in reason for reason in result.ranking.reasons)


def test_farmer_priorities_reorder_water_soil_fallback_and_explain_tradeoffs() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option(
                    "water-option",
                    ("cowpea", "yam", "groundnut"),
                    "high",
                    soil_rating="low",
                    yield_rating=None,
                ),
                make_option(
                    "soil-option",
                    ("groundnut", "cassava", "cowpea"),
                    "moderate",
                    soil_rating="high",
                    yield_rating=None,
                ),
            ),
            farmer_priorities=PriorityPoints(
                water_resilience=100,
                soil_health_potential=0,
                yield_stability_proxy=50,
                labor_feasibility=50,
            ),
        )
    )

    assert result.ranking_mode == "water_soil_fallback"
    assert result.ranking.criteria_used == ("water_resilience", "soil_health_potential")
    assert result.equal_weight_ranking.rank_groups == (("soil-option",), ("water-option",))
    assert result.ranking.rank_groups == (("water-option",), ("soil-option",))
    assert [share.percent for share in result.selected_weights.normalized_weights] == [
        100,
        0,
        0,
        0,
    ]
    assert result.sensitivity == "weight_sensitive"
    tradeoff = result.ranking.tradeoffs[0]
    assert tradeoff.higher_ranked_candidate_id == "water-option"
    assert {item.criterion for item in tradeoff.strengths} == {"water_resilience"}
    assert {item.criterion for item in tradeoff.concessions} == {"soil_health_potential"}
    assert "not applied" in " ".join(result.ranking.reasons)


def test_missing_water_evidence_stays_unranked_and_does_not_fill_top_three() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option("ranked", ("cowpea", "yam", "groundnut"), "high"),
                make_option(
                    "unknown", ("maize", "cowpea", "yam"), None, water_status="not_assessed"
                ),
            )
        )
    )

    assert result.options == ()
    assert result.ranking.unranked_candidate_count == 1
    assert result.ranking.status == "insufficient_options"
    assert result.ranking.criteria_used == ("water_resilience", "soil_health_potential")
    assert any("water_resilience" in reason for reason in result.ranking.reasons)


def test_different_water_comparison_bases_withhold_ranking() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option("basis-a", ("cowpea", "yam", "groundnut"), "high"),
                make_option(
                    "basis-b",
                    ("maize", "cowpea", "yam"),
                    "moderate",
                    water_basis="another-water-method-v1",
                ),
                make_option("basis-c", ("yam", "maize", "groundnut"), "low"),
            )
        )
    )

    assert result.options == ()
    assert result.ranking.status == "withheld"
    assert result.ranking.unranked_candidate_count == 3
    assert any("different" in reason for reason in result.ranking.reasons)


def test_returns_only_three_and_reports_tie_at_display_limit() -> None:
    options = tuple(
        make_option(
            f"option-{letter}",
            ("cowpea", "yam", "groundnut"),
            "high",
        )
        for letter in "abcde"
    )

    result = score_rotation_options(ScoringRequest(options=options))

    assert len(result.options) == 3
    assert [item.candidate.candidate_id for item in result.options] == [
        "option-a",
        "option-b",
        "option-c",
    ]
    assert result.ranking.tie_at_limit is True
    assert result.ranking.rank_groups == (("option-a", "option-b", "option-c"),)


def test_v4_result_model_rejects_more_than_three_alternatives() -> None:
    options = tuple(
        make_option(
            f"option-{letter}",
            ("cowpea", "yam", "groundnut"),
            "high",
        )
        for letter in "abc"
    )
    result = score_rotation_options(ScoringRequest(options=options))

    with pytest.raises(ValidationError, match="at most three"):
        ScoringResult.model_validate(
            {**result.model_dump(), "options": result.options + result.options}
        )


def test_previous_weighted_result_documents_remain_labeled_as_legacy() -> None:
    legacy = ScoringResult.model_validate(
        {
            "scoring_version": "ny8-scoring-v1",
            "rating_scale": "relative_qualitative",
            "options": [],
            "excluded_options": [],
            "equal_weight_ranking": {"status": "withheld"},
            "selected_weight_ranking": {"status": "withheld"},
        }
    )

    assert legacy.ranking_method == "legacy_weighted_v1"
    assert legacy.equal_weight_ranking is not None
    assert legacy.equal_weight_ranking.method == "legacy_weighted_v1"


def test_tied_display_uses_stable_candidate_id_without_breaking_the_tie() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option("option-a", ("maize", "cowpea", "maize"), "high"),
                make_option("option-b", ("maize", "cowpea", "groundnut"), "high"),
                make_option("option-c", ("cowpea", "groundnut", "cassava"), "high"),
                make_option("option-d", ("cassava", "maize", "yam"), "high"),
            )
        )
    )

    assert [item.candidate.candidate_id for item in result.options] == [
        "option-a",
        "option-b",
        "option-c",
    ]
    assert result.ranking.tie_at_limit is True
    assert result.ranking.rank_groups == (("option-a", "option-b", "option-c"),)
    assert any("candidate ID" in reason for reason in result.ranking.reasons)


def test_repeated_crop_alternative_is_not_excluded_by_the_scorer() -> None:
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option("all-maize", ("maize", "maize", "maize"), "low"),
                make_option("mixed-a", ("maize", "cowpea", "yam"), "moderate"),
            )
        )
    )

    assert "all-maize" in {item.candidate.candidate_id for item in result.options}
    assert result.excluded_options == ()


def test_baseline_is_separate_and_failed_constraint_is_excluded_before_ranking() -> None:
    failed = HardConstraintFinding(
        rule_id="synthetic-hard-rule",
        outcome="failed",
        rationale="Synthetic invalidity fixture.",
        evidence_references=(TEST_SOURCE,),
    )
    result = score_rotation_options(
        ScoringRequest(
            options=(
                make_option(
                    "single-crop-baseline",
                    ("maize", "maize", "maize"),
                    "low",
                    kind="baseline",
                ),
                make_option(
                    "excluded", ("maize", "cowpea", "yam"), "high", hard_constraints=(failed,)
                ),
                make_option("one", ("cowpea", "groundnut", "cassava"), "moderate"),
                make_option("two", ("groundnut", "cassava", "cowpea"), "moderate"),
                make_option("three", ("cassava", "cowpea", "groundnut"), "moderate"),
            )
        )
    )

    assert result.baseline_option is not None
    assert result.baseline_option.candidate.candidate_id == "single-crop-baseline"
    assert "single-crop-baseline" not in {item.candidate.candidate_id for item in result.options}
    assert [item.candidate.candidate_id for item in result.options] == ["one", "three", "two"]
    assert [item.candidate.candidate_id for item in result.excluded_options] == ["excluded"]


def test_crop_evidence_is_provisional_and_rice_ecology_remains_unknown() -> None:
    candidate = make_candidate("public-profile", ("groundnut", "cassava", "cowpea"))
    evidence = build_crop_evidence_option(
        candidate,
        historical_indicators=(),
        environmental_context_ready=True,
    )
    water, soil, yield_stability, labor = evidence.criteria

    assert water.status == "assessed"
    assert water.rating == "moderate"  # the sequence rating is the weakest crop's class
    assert water.confidence == "low"
    assert len(water.evidence_references) >= 2
    assert "bottleneck" in water.rationale
    assert soil.status == "not_assessed"
    assert "not assessed" in soil.rationale
    assert yield_stability.status == "not_assessed"
    assert yield_stability.evidence_references
    assert labor.status == "not_assessed"
    assert labor.evidence_references
    assert len(evidence.transition_assessments) == 3
    assert any(item.status == "needs_review" for item in evidence.transition_assessments)

    rice_candidate = make_candidate("rice-profile", ("groundnut", "rice", "cassava"))
    rice_evidence = build_crop_evidence_option(
        rice_candidate,
        historical_indicators=(),
        environmental_context_ready=True,
    )
    assert rice_evidence.criteria[0].status == "not_assessed"


def test_synthetic_four_criterion_scoring_is_deterministic_and_labeled_provisional() -> None:
    options = tuple(
        make_option(
            f"synthetic-{index}",
            crops,
            water,
            soil_rating=soil,
            yield_rating=yield_rating,
            labor_rating=labor,
        )
        for index, (crops, water, soil, yield_rating, labor) in enumerate(
            (
                (("groundnut", "cassava", "cowpea"), "high", "moderate", "low", "moderate"),
                (("cowpea", "groundnut", "cassava"), "moderate", "high", "high", "low"),
                (("cassava", "cowpea", "groundnut"), "moderate", "low", "moderate", "high"),
                (("groundnut", "cowpea", "cassava"), "high", "low", "low", "low"),
                (("cassava", "groundnut", "cowpea"), "low", "high", "high", "high"),
            ),
            start=1,
        )
    )
    request = ScoringRequest(options=options)
    first = score_rotation_options(request)
    second = score_rotation_options(request)

    assert first.model_dump() == second.model_dump()
    assert len(first.options) == 3
    assert first.provisional is True
    assert first.scoring_version == SCORING_VERSION
    assert first.ranking_mode == "four_criterion"
    assert first.default_weights.normalized_weights == first.selected_weights.normalized_weights


def test_scoring_result_rehydrates_mongodb_decimal128_percentages() -> None:
    """Mongo returns Decimal128 for stored weights; the domain model restores Decimal."""

    scored = score_rotation_options(
        ScoringRequest(
            options=(
                make_option(
                    "mongo-round-trip-a",
                    ("maize", "cowpea", "groundnut"),
                    "high",
                    soil_rating="moderate",
                    yield_rating="low",
                    labor_rating="moderate",
                ),
                make_option(
                    "mongo-round-trip-b",
                    ("cowpea", "groundnut", "maize"),
                    "moderate",
                    soil_rating="high",
                    yield_rating="moderate",
                    labor_rating="low",
                ),
            )
        )
    )

    def encode_mongo_decimals(value: object) -> object:
        if isinstance(value, Decimal):
            return Decimal128(value)
        if isinstance(value, dict):
            return {key: encode_mongo_decimals(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(encode_mongo_decimals(item) for item in value)
        if isinstance(value, list):
            return [encode_mongo_decimals(item) for item in value]
        return value

    mongo_decoded_document = encode_mongo_decimals(scored.model_dump(mode="python"))
    restored = ScoringResult.model_validate(mongo_decoded_document)

    assert restored == scored
    assert isinstance(restored.selected_weights.normalized_weights[0].percent, Decimal)
