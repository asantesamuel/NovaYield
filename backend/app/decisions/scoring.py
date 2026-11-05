"""NY-8 evidence-gated weighted ranking across four farmer criteria.

New results use equal default weights or the farmer's saved priority points.
Historical NY-8 result versions remain parseable for existing Mongo documents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from itertools import combinations
from typing import Annotated, Literal

from bson.decimal128 import Decimal128
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.decisions.climate_features import (
    CLIMATE_TIE_POLICY_VERSION,
    CropExposureComparison,
    MatchedCropExposure,
    StageCDDExposure,
    compare_matched_rotation_exposure,
)
from app.decisions.rotation import (
    CandidateRuleFinding,
    RotationCandidate,
)
from app.indicators.environmental import EnvironmentalIndicator

SCORING_VERSION = "ny40-scoring-v5"
WEIGHT_PERCENT_QUANTUM = Decimal("0.0001")


def _normalize_bson_decimal(value: object) -> object:
    """Convert MongoDB's BSON Decimal128 wrapper back to Python Decimal."""

    if isinstance(value, Decimal128):
        return value.to_decimal()
    return value


WeightPercent = Annotated[Decimal, BeforeValidator(_normalize_bson_decimal)]

Criterion = Literal[
    "water_resilience",
    "soil_health_potential",
    "yield_stability_proxy",
    "labor_feasibility",
]
ActiveCriterion = Criterion
CriterionRating = Literal["high", "moderate", "low"]
Confidence = Literal["high", "moderate", "low"]
EvidenceStatus = Literal["assessed", "not_assessed"]
ConstraintOutcome = Literal["passed", "failed", "needs_review"]
WeightSource = Literal["default_equal", "farmer_selected"]
RankingMode = Literal["four_criterion", "water_soil_fallback"]
RankingStatus = Literal["ranked", "withheld", "insufficient_options"]
SensitivityStatus = Literal["not_applicable", "stable", "weight_sensitive", "unavailable"]
TransitionStatus = Literal["assessed", "needs_review", "not_assessed"]
CalendarEvidenceStatus = Literal["unknown", "provisional", "locally_validated"]

CRITERIA: tuple[ActiveCriterion, ...] = (
    "water_resilience",
    "soil_health_potential",
    "yield_stability_proxy",
    "labor_feasibility",
)

TOP_RECOMMENDATION_LIMIT = 3
RATING_ORDER: dict[CriterionRating, int] = {"high": 3, "moderate": 2, "low": 1}
RANKING_METHOD = "weighted_ordinal_sum_v1"
LEGACY_RANKING_METHOD = "legacy_weighted_v1"


class PriorityPoints(BaseModel):
    """Farmer-entered relative importance points for the four active criteria."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    water_resilience: int = Field(ge=0, le=100)
    soil_health_potential: int = Field(ge=0, le=100)
    yield_stability_proxy: int = Field(ge=0, le=100)
    labor_feasibility: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def require_nonzero_total(self) -> PriorityPoints:
        """A zero total cannot define relative importance."""

        if sum(self.model_dump().values()) == 0:
            raise ValueError("At least one farmer priority must have a positive value")
        return self


class CriterionEvidence(BaseModel):
    """One sourced qualitative rating, or an explicit reason it is unavailable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion
    status: EvidenceStatus
    rating: CriterionRating | None = None
    confidence: Confidence | None = None
    rationale: str = Field(min_length=1)
    comparison_basis: str | None = None
    evidence_references: tuple[str, ...] = ()
    environmental_inputs: tuple[EnvironmentalIndicator, ...] = ()
    climate_features: tuple[StageCDDExposure, ...] = ()
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_state(self) -> CriterionEvidence:
        """Prevent an unknown result from carrying a score or a score lacking provenance."""

        if self.status == "assessed":
            if self.rating is None or self.confidence is None:
                raise ValueError("An assessed criterion requires a rating and confidence")
            if not self.comparison_basis:
                raise ValueError("An assessed criterion requires a comparison basis")
            has_usable_indicator = any(
                indicator.value is not None
                and indicator.status != "unavailable"
                and indicator.data_status != "unavailable"
                for indicator in self.environmental_inputs
            )
            if not self.evidence_references and not has_usable_indicator:
                raise ValueError("An assessed criterion requires sourced evidence")
        elif any(
            value is not None for value in (self.rating, self.confidence, self.comparison_basis)
        ):
            raise ValueError("A not-assessed criterion cannot carry a rating, confidence, or basis")
        return self


class HardConstraintFinding(BaseModel):
    """A reviewed hard rule evaluated before any priority-weighted comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1)
    outcome: ConstraintOutcome
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_evidence_for_decisions(self) -> HardConstraintFinding:
        """Do not pass or exclude an option using an undocumented hard rule."""

        if self.outcome in ("passed", "failed") and not self.evidence_references:
            raise ValueError("A passed or failed hard constraint requires an evidence reference")
        return self


class EventAssessment(BaseModel):
    """Context checks for one crop assigned to one planting event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_order: int = Field(ge=1, le=3)
    crop_id: str = Field(min_length=1)
    status: TransitionStatus
    calendar_status: CalendarEvidenceStatus
    rationale: str = Field(min_length=1)
    required_context_missing: tuple[str, ...] = ()
    evidence_references: tuple[str, ...] = ()


class TransitionAssessment(BaseModel):
    """Evidence state for one ordered relationship between planting events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relationship_id: str | None = None
    predecessor_crop_id: str | None = None
    successor_crop_id: str = Field(min_length=1)
    context: Literal["reported_history", "history_to_candidate", "candidate"] = "candidate"
    status: TransitionStatus
    rationale: str = Field(min_length=1)
    evidence_references: tuple[str, ...] = ()
    required_context_missing: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_sources_for_assessed_relationship(self) -> TransitionAssessment:
        """An assessed crop transition must identify the evidence it used."""

        if self.status == "assessed" and not self.evidence_references:
            raise ValueError("An assessed crop transition requires evidence references")
        return self


class RotationOptionEvidence(BaseModel):
    """Candidate plus the evidence and hard-rule outcomes used for comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RotationCandidate
    hard_constraints: tuple[HardConstraintFinding, ...] = ()
    event_assessments: tuple[EventAssessment, ...] = ()
    transition_assessments: tuple[TransitionAssessment, ...] = ()
    criteria: tuple[CriterionEvidence, ...] = ()
    climate_exposures: tuple[MatchedCropExposure, ...] = ()
    benefits: tuple[str, ...] = ()
    trade_offs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_one_assessment_per_criterion(self) -> RotationOptionEvidence:
        """Allow explicit active assessments and legacy four-criterion records."""

        rule_ids = tuple(item.rule_id for item in self.hard_constraints)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("Hard constraint rule IDs must be unique per option")

        if any(item.outcome == "failed" for item in self.hard_constraints):
            if self.criteria:
                raise ValueError(
                    "Options failing a hard constraint must be excluded before assessment"
                )
            return self

        criterion_ids = tuple(item.criterion for item in self.criteria)
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("An option can assess each criterion only once")
        return self


class ScoringRequest(BaseModel):
    """Options to compare using equal defaults or the saved farmer priorities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    options: tuple[RotationOptionEvidence, ...]
    farmer_priorities: PriorityPoints | None = None

    @model_validator(mode="after")
    def require_unique_option_ids(self) -> ScoringRequest:
        """An option ID must map to exactly one candidate in every ranking view."""

        ids = tuple(option.candidate.candidate_id for option in self.options)
        if len(set(ids)) != len(ids):
            raise ValueError("Candidate IDs must be unique within a scoring request")
        return self


class WeightShare(BaseModel):
    """One criterion's normalized percentage weight for an auditable comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion
    percent: WeightPercent = Field(ge=0, le=100)


class WeightProfile(BaseModel):
    """Priority points and normalized weights used in one ranking view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: WeightSource
    points: PriorityPoints
    normalized_weights: tuple[WeightShare, ...]


class WeightedCriterionDifference(BaseModel):
    """One criterion where two ranked options differ, with its selected weight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion
    higher_ranked_rating: CriterionRating
    lower_ranked_rating: CriterionRating
    selected_weight_percent: WeightPercent = Field(ge=0, le=100)


class RankingTradeoff(BaseModel):
    """Explain what the higher-ranked option gains and gives up against another."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    higher_ranked_candidate_id: str
    lower_ranked_candidate_id: str
    strengths: tuple[WeightedCriterionDifference, ...]
    concessions: tuple[WeightedCriterionDifference, ...]
    explanation: str = Field(min_length=1)


class CriterionResult(BaseModel):
    """Per-option display record; no numeric composite score is exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion = Field(
        description=(
            "NY-8 v4 exposes all four approved criteria. Ranking mode and criteria_used "
            "show which evidence affected this result."
        )
    )
    status: EvidenceStatus
    rating: CriterionRating | None
    confidence: Confidence | None
    equal_weight_percent: WeightPercent | None = None
    selected_weight_percent: WeightPercent | None = None
    rationale: str
    comparison_basis: str | None
    evidence_references: tuple[str, ...]
    environmental_inputs: tuple[EnvironmentalIndicator, ...]
    climate_features: tuple[StageCDDExposure, ...] = ()
    assumptions: tuple[str, ...]


class ScoredOption(BaseModel):
    """Presentation-ready qualitative evidence for one non-excluded option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RotationCandidate
    criteria: tuple[CriterionResult, ...]
    hard_constraints: tuple[HardConstraintFinding, ...]
    event_assessments: tuple[EventAssessment, ...] = ()
    transition_assessments: tuple[TransitionAssessment, ...] = ()
    candidate_rule_findings: tuple[CandidateRuleFinding, ...]
    benefits: tuple[str, ...]
    trade_offs: tuple[str, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]


class ClimateTiePreference(BaseModel):
    """A pairwise, provisional CDD preference after equal Decision-13 totals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preferred_candidate_id: str
    other_candidate_id: str
    policy_version: str = CLIMATE_TIE_POLICY_VERSION
    metric_key: Literal["stage_cdd_exposure"] = "stage_cdd_exposure"
    comparisons: tuple[CropExposureComparison, ...]
    explanation: str


class ExcludedOption(BaseModel):
    """A failed hard constraint excludes an option before it can be scored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RotationCandidate
    failed_constraints: tuple[HardConstraintFinding, ...]


class RankingOutcome(BaseModel):
    """Weighted, tie-aware ranking and explicit evidence/trade-off rationale."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RankingStatus
    criteria_used: tuple[ActiveCriterion, ...] = ()
    rank_groups: tuple[tuple[str, ...], ...] = ()
    reasons: tuple[str, ...] = ()
    method: str = LEGACY_RANKING_METHOD
    provisional: bool = True
    ranked_candidate_count: int = 0
    unranked_candidate_count: int = 0
    tie_at_limit: bool = False
    tradeoffs: tuple[RankingTradeoff, ...] = ()
    climate_tie_preferences: tuple[ClimateTiePreference, ...] = ()


class ScoringResult(BaseModel):
    """Three priority-ranked alternatives, separate baseline, and audit provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoring_version: str = SCORING_VERSION
    rating_scale: Literal["relative_qualitative"] = "relative_qualitative"
    ranking_method: str = RANKING_METHOD
    ranking_mode: RankingMode | None = None
    provisional: bool = True
    candidate_count: int = 0
    default_weights: WeightProfile | None = None
    selected_weights: WeightProfile | None = None
    options: tuple[ScoredOption, ...] = Field(
        description="At most three comparable alternatives; current practice is separate."
    )
    baseline_option: ScoredOption | None = None
    excluded_options: tuple[ExcludedOption, ...]
    ranking: RankingOutcome | None = None
    # Keep both comparison views so the farmer can see whether priorities change order.
    equal_weight_ranking: RankingOutcome | None = None
    selected_weight_ranking: RankingOutcome | None = None
    sensitivity: SensitivityStatus | None = None

    @model_validator(mode="before")
    @classmethod
    def add_legacy_result_metadata(cls, value: object) -> object:
        """Keep historical weighted and water-first results readable after revision."""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if payload.get("scoring_version") == "ny8-scoring-v1":
            payload.setdefault("ranking_method", LEGACY_RANKING_METHOD)
            payload.setdefault("candidate_count", len(payload.get("options", ())))
        elif payload.get("scoring_version") == "ny8-scoring-v2":
            payload.setdefault("ranking_method", "lexicographic_water_then_optional_soil")
        return payload

    @model_validator(mode="after")
    def validate_current_output_contract(self) -> ScoringResult:
        """Require explicit ranking mode and the four-criterion evidence envelope."""

        if self.scoring_version != SCORING_VERSION:
            return self
        if len(self.options) > TOP_RECOMMENDATION_LIMIT:
            raise ValueError("The scoring result can return at most three alternatives")
        if self.ranking is None:
            raise ValueError("The scoring result requires ranking status and rationale")
        if self.ranking_method != RANKING_METHOD:
            raise ValueError("The scoring result requires weighted ordinal ranking")
        if self.ranking_mode is None:
            raise ValueError("The scoring result requires an explicit ranking mode")
        if not self.ranking.criteria_used:
            raise ValueError("The scoring result requires the criteria used by its ranking")
        if self.ranking_mode == "four_criterion" and self.ranking.criteria_used != CRITERIA:
            raise ValueError("Four-criterion mode must use all four approved criteria")
        if self.ranking_mode == "water_soil_fallback" and self.ranking.criteria_used not in (
            ("water_resilience",),
            ("water_resilience", "soil_health_potential"),
        ):
            raise ValueError("Fallback mode must use water, optionally followed by soil health")
        if self.default_weights is None or self.selected_weights is None:
            raise ValueError("The scoring result requires default and selected weight profiles")
        for option in (*self.options, *((self.baseline_option,) if self.baseline_option else ())):
            if tuple(result.criterion for result in option.criteria) != CRITERIA:
                raise ValueError("Scored options must expose all four criteria in order")
        return self


def _equal_priority_points() -> PriorityPoints:
    """Create the fallback weight profile when a farmer has no saved priorities."""

    return PriorityPoints(
        water_resilience=25,
        soil_health_potential=25,
        yield_stability_proxy=25,
        labor_feasibility=25,
    )


def _weight_profile(
    points: PriorityPoints,
    source: WeightSource,
    *,
    criteria_used: tuple[ActiveCriterion, ...],
) -> WeightProfile:
    """Normalize priorities only across criteria that are comparable in this mode."""

    values = points.model_dump()
    active_points = {
        criterion: values[criterion] if criterion in criteria_used else 0 for criterion in CRITERIA
    }
    if sum(active_points.values()) == 0:
        active_points = {criterion: int(criterion in criteria_used) for criterion in CRITERIA}
    total = sum(active_points.values())
    normalized = {
        criterion: (Decimal(active_points[criterion]) * 100 / total).quantize(
            WEIGHT_PERCENT_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        for criterion in CRITERIA
    }
    correction = Decimal("100") - sum(normalized.values(), Decimal("0"))
    correction_target = next(
        criterion for criterion in reversed(CRITERIA) if active_points[criterion] > 0
    )
    normalized[correction_target] += correction
    return WeightProfile(
        source=source,
        points=points,
        normalized_weights=tuple(
            WeightShare(criterion=criterion, percent=normalized[criterion])
            for criterion in CRITERIA
        ),
    )


def _build_scored_option(
    option: RotationOptionEvidence,
    *,
    default_profile: WeightProfile,
    selected_profile: WeightProfile,
    criteria_used: tuple[ActiveCriterion, ...],
    needs_review_constraints: tuple[HardConstraintFinding, ...],
) -> ScoredOption:
    """Attach both disclosed weight profiles and preserve each criterion's missingness."""

    evidence_by_criterion = {item.criterion: item for item in option.criteria}
    default_by_criterion = {
        item.criterion: item.percent for item in default_profile.normalized_weights
    }
    selected_by_criterion = {
        item.criterion: item.percent for item in selected_profile.normalized_weights
    }
    criteria_list: list[CriterionResult] = []
    for criterion in CRITERIA:
        evidence = evidence_by_criterion.get(criterion)
        if evidence is None:
            evidence = CriterionEvidence(
                criterion=criterion,
                status="not_assessed",
                rationale="No comparable evidence was supplied for this criterion.",
            )
        criteria_list.append(
            CriterionResult(
                criterion=criterion,
                status=evidence.status,
                rating=evidence.rating,
                confidence=evidence.confidence,
                equal_weight_percent=default_by_criterion[criterion],
                selected_weight_percent=selected_by_criterion[criterion],
                rationale=evidence.rationale,
                comparison_basis=evidence.comparison_basis,
                evidence_references=evidence.evidence_references,
                environmental_inputs=evidence.environmental_inputs,
                climate_features=evidence.climate_features,
                assumptions=evidence.assumptions,
            )
        )
    criteria = tuple(criteria_list)
    weights = {item.criterion: item.percent for item in selected_profile.normalized_weights}
    rated_high = [
        item
        for item in criteria
        if item.criterion in criteria_used and item.status == "assessed" and item.rating == "high"
    ]
    rated_low = [
        item
        for item in criteria
        if item.criterion in criteria_used and item.status == "assessed" and item.rating == "low"
    ]
    trade_offs = list(option.trade_offs)
    if rated_high and rated_low:
        strength = max(rated_high, key=lambda item: weights[item.criterion])
        weakness = max(rated_low, key=lambda item: weights[item.criterion])
        trade_offs.append(
            f"Priority trade-off: this sequence is High on {strength.criterion} "
            f"({weights[strength.criterion]}% weight) and Low on {weakness.criterion} "
            f"({weights[weakness.criterion]}% weight). The selected weights determine "
            "how much that difference affects its position."
        )

    warnings = tuple(
        f"{finding.rule_id}: {finding.rationale}" for finding in needs_review_constraints
    )
    warnings += tuple(
        f"{finding.rule_id}: {finding.explanation}"
        for finding in option.candidate.rule_findings
        if finding.outcome == "needs_review"
    )
    return ScoredOption(
        candidate=option.candidate,
        criteria=criteria,
        hard_constraints=option.hard_constraints,
        event_assessments=option.event_assessments,
        transition_assessments=option.transition_assessments,
        candidate_rule_findings=option.candidate.rule_findings,
        benefits=option.benefits,
        trade_offs=tuple(trade_offs),
        assumptions=option.assumptions,
        warnings=warnings,
    )


def _criterion(option: ScoredOption, criterion: Criterion) -> CriterionResult:
    """Find one of the four criterion records in its normalized output."""

    return next(item for item in option.criteria if item.criterion == criterion)


def _refine_equal_groups_with_climate(
    groups: tuple[tuple[str, ...], ...],
    climate_by_id: dict[str, tuple[MatchedCropExposure, ...]],
    event_count_by_id: dict[str, int],
) -> tuple[tuple[tuple[str, ...], ...], tuple[ClimateTiePreference, ...], bool]:
    """Split a weighted tie only when strict CDD evidence orders its whole group.

    CDD is a partial order. A preference between two options does not justify
    placing a third, incomparable option above or below either one. Pairwise
    findings stay visible even when the weighted rank group remains tied.
    """

    refined: list[tuple[str, ...]] = []
    preferences: list[ClimateTiePreference] = []
    split_any = False
    for group in groups:
        if len(group) < 2 or not all(climate_by_id.get(item) for item in group):
            refined.append(group)
            continue

        group_preferences: list[ClimateTiePreference] = []
        for left_id, right_id in combinations(sorted(group), 2):
            if event_count_by_id[left_id] != event_count_by_id[right_id]:
                continue
            comparison = compare_matched_rotation_exposure(
                climate_by_id[left_id],
                climate_by_id[right_id],
                decision13_weighted_total_tie=True,
                expected_event_count=event_count_by_id[left_id],
            )
            if comparison.status not in {"left_preferred", "right_preferred"}:
                continue
            preferred, other = (
                (left_id, right_id)
                if comparison.status == "left_preferred"
                else (right_id, left_id)
            )
            preferred_exposures = {
                (
                    item.exposure.crop_id,
                    item.exposure.variety_key,
                    item.exposure.production_system_key,
                    item.exposure.stage_key,
                    item.occurrence_index or 1,
                ): item.exposure
                for item in climate_by_id[preferred]
            }
            details: list[str] = []
            for matched in comparison.comparisons:
                key = (
                    matched.crop_id,
                    matched.variety_key,
                    matched.production_system_key,
                    matched.stage_key,
                    matched.occurrence_index,
                )
                feature = preferred_exposures.get(key)
                preferred_interval, other_interval = (
                    (matched.left_interval_days, matched.right_interval_days)
                    if preferred == left_id
                    else (matched.right_interval_days, matched.left_interval_days)
                )
                window = (
                    f"planting {feature.planting_window_start}–{feature.planting_window_end}, "
                    if feature is not None
                    else ""
                )
                source = (
                    f"NASA POWER {', '.join(feature.source_products) or 'source unspecified'}, "
                    f"snapshot {feature.source_snapshot_id}"
                    if feature is not None
                    else "NASA POWER source in the stored feature"
                )
                details.append(
                    f"{matched.crop_id} {matched.stage_key} ({window}{source}): "
                    f"{preferred_interval[0]}–{preferred_interval[1]} vs "
                    f"{other_interval[0]}–{other_interval[1]} days"
                )
            group_preferences.append(
                ClimateTiePreference(
                    preferred_candidate_id=preferred,
                    other_candidate_id=other,
                    comparisons=comparison.comparisons,
                    explanation=(
                        f"{preferred} is preferred over {other} only after equal weighted "
                        "criterion totals: 1991–2020 median annual longest dry spell "
                        "(PRECTOTCORR <1 mm/day) intervals are "
                        + "; ".join(details)
                        + ". Every matched crop stage has a strictly lower exposure "
                        "interval. This provisional planting-window comparison is "
                        "not a water-sufficiency or yield claim."
                    ),
                )
            )
        preferences.extend(group_preferences)

        expected_pairs = len(group) * (len(group) - 1) // 2
        if len(group_preferences) != expected_pairs:
            refined.append(group)
            continue
        wins = {item: 0 for item in group}
        for preference in group_preferences:
            wins[preference.preferred_candidate_id] += 1
        if len(set(wins.values())) != len(group):
            refined.append(group)
            continue
        refined.extend((item,) for item in sorted(group, key=lambda item: -wins[item]))
        split_any = True

    return tuple(refined), tuple(preferences), split_any


def _top_three(
    groups: tuple[tuple[str, ...], ...],
    options_by_id: dict[str, ScoredOption],
) -> tuple[list[ScoredOption], tuple[tuple[str, ...], ...], bool]:
    """Return at most three candidates, preserving ties and stable display order."""

    selected_ids: list[str] = []
    selected_groups: list[tuple[str, ...]] = []
    tie_at_limit = False
    for original_group in groups:
        group = tuple(sorted(original_group))
        remaining = TOP_RECOMMENDATION_LIMIT - len(selected_ids)
        if remaining <= 0:
            break
        shown = group[:remaining]
        selected_ids.extend(shown)
        selected_groups.append(shown)
        if len(group) > remaining:
            tie_at_limit = True
            break
    return [options_by_id[item] for item in selected_ids], tuple(selected_groups), tie_at_limit


def _build_tradeoff_explanations(
    selected: list[ScoredOption],
    values_by_id: dict[str, Fraction],
    weight_by_criterion: dict[Criterion, Decimal],
    criteria_used: tuple[ActiveCriterion, ...],
) -> tuple[RankingTradeoff, ...]:
    """Explain criterion gains and concessions between adjacent displayed ranks."""

    explanations: list[RankingTradeoff] = []
    for higher, lower in zip(selected, selected[1:], strict=False):
        higher_id = higher.candidate.candidate_id
        lower_id = lower.candidate.candidate_id
        if values_by_id[higher_id] == values_by_id[lower_id]:
            continue

        strengths: list[WeightedCriterionDifference] = []
        concessions: list[WeightedCriterionDifference] = []
        for criterion in criteria_used:
            higher_result = _criterion(higher, criterion)
            lower_result = _criterion(lower, criterion)
            higher_rating = higher_result.rating
            lower_rating = lower_result.rating
            if higher_rating is None or lower_rating is None or higher_rating == lower_rating:
                continue
            difference = WeightedCriterionDifference(
                criterion=criterion,
                higher_ranked_rating=higher_rating,
                lower_ranked_rating=lower_rating,
                selected_weight_percent=weight_by_criterion[criterion],
            )
            target = (
                strengths
                if RATING_ORDER[higher_rating] > RATING_ORDER[lower_rating]
                else concessions
            )
            target.append(difference)

        strength_text = (
            "; ".join(
                f"{item.criterion} is {item.higher_ranked_rating} vs "
                f"{item.lower_ranked_rating} ({item.selected_weight_percent}% weight)"
                for item in strengths
            )
            or "no criterion rating advantage"
        )
        concession_text = (
            "; ".join(
                f"{item.criterion} is {item.higher_ranked_rating} vs "
                f"{item.lower_ranked_rating} ({item.selected_weight_percent}% weight)"
                for item in concessions
            )
            or "no lower criterion rating"
        )
        explanations.append(
            RankingTradeoff(
                higher_ranked_candidate_id=higher_id,
                lower_ranked_candidate_id=lower_id,
                strengths=tuple(strengths),
                concessions=tuple(concessions),
                explanation=(
                    f"{higher_id} ranks ahead of {lower_id} under the selected priorities: "
                    f"strengths are {strength_text}; concessions are {concession_text}. "
                    "The weighted ordinal model lets gains on higher-priority criteria "
                    "offset weaker ratings on other criteria."
                ),
            )
        )
    return tuple(explanations)


def _criterion_evidence(
    option: RotationOptionEvidence,
    criterion: ActiveCriterion,
) -> CriterionEvidence | None:
    return next((item for item in option.criteria if item.criterion == criterion), None)


def _has_comparable_evidence(
    options: list[RotationOptionEvidence],
    criterion: ActiveCriterion,
) -> bool:
    """Check that every option is rated on one shared, explicit evidence basis."""

    if not options:
        return False
    evidence = [_criterion_evidence(option, criterion) for option in options]
    if any(
        item is None
        or item.status != "assessed"
        or item.rating is None
        or item.comparison_basis is None
        for item in evidence
    ):
        return False
    return len({item.comparison_basis for item in evidence if item is not None}) == 1


def _select_ranking_plan(
    alternatives: list[RotationOptionEvidence],
) -> tuple[
    RankingMode,
    tuple[ActiveCriterion, ...],
    list[RotationOptionEvidence],
    tuple[str, ...],
    tuple[str, ...],
]:
    """Select a single comparable evidence mode for the whole candidate comparison."""

    if alternatives and all(_has_comparable_evidence(alternatives, item) for item in CRITERIA):
        return (
            "four_criterion",
            CRITERIA,
            alternatives,
            (),
            ("All four criteria are assessed on comparable bases; full ranking is used.",),
        )

    reasons = [
        "Four-criterion ranking is unavailable because at least one criterion is "
        "missing or incomparable across the alternatives."
    ]
    for criterion in CRITERIA:
        if not _has_comparable_evidence(alternatives, criterion):
            affected = [
                option.candidate.candidate_id
                for option in alternatives
                if (
                    (item := _criterion_evidence(option, criterion)) is None
                    or item.status != "assessed"
                    or item.rating is None
                    or item.comparison_basis is None
                )
            ]
            if affected:
                sample = ", ".join(affected[:5])
                suffix = "…" if len(affected) > 5 else ""
                reasons.append(
                    f"{criterion} is missing or unassessed for "
                    f"{len(affected)} alternative(s) ({sample}{suffix})."
                )
            else:
                reasons.append(f"{criterion} ratings do not share a comparison basis.")

    water_options = [
        option
        for option in alternatives
        if (
            (water := _criterion_evidence(option, "water_resilience")) is not None
            and water.status == "assessed"
            and water.rating is not None
            and water.comparison_basis is not None
        )
    ]
    water_ids = {item.candidate.candidate_id for item in water_options}
    unranked_ids = tuple(
        option.candidate.candidate_id
        for option in alternatives
        if option.candidate.candidate_id not in water_ids
    )
    if not water_options:
        reasons.append("No alternative has comparable water evidence, so ranking is withheld.")
        return (
            "water_soil_fallback",
            ("water_resilience",),
            [],
            tuple(option.candidate.candidate_id for option in alternatives),
            tuple(reasons),
        )

    water_bases = {
        item.comparison_basis
        for option in water_options
        if (item := _criterion_evidence(option, "water_resilience")) is not None
    }
    if len(water_bases) != 1:
        reasons.append(
            "Water ratings use different comparison bases; no alternatives can be "
            "compared safely in the fallback mode."
        )
        return (
            "water_soil_fallback",
            ("water_resilience",),
            [],
            tuple(option.candidate.candidate_id for option in alternatives),
            tuple(reasons),
        )

    if unranked_ids:
        sample = ", ".join(unranked_ids[:5])
        suffix = "…" if len(unranked_ids) > 5 else ""
        reasons.append(
            f"{len(unranked_ids)} alternative(s) without assessed water evidence "
            f"remain unranked ({sample}{suffix})."
        )

    if _has_comparable_evidence(water_options, "soil_health_potential"):
        criteria_used: tuple[ActiveCriterion, ...] = (
            "water_resilience",
            "soil_health_potential",
        )
        reasons.append(
            "Fallback ranking uses comparable water and soil evidence; farmer priorities "
            "are normalized across those two criteria."
        )
    else:
        criteria_used = ("water_resilience",)
        reasons.append(
            "Soil evidence is not comparable across water-assessed alternatives; "
            "fallback ranking uses water alone."
        )
    reasons.append(
        "Yield stability and labour remain visible in each option but do not affect "
        "the fallback order."
    )
    return "water_soil_fallback", criteria_used, water_options, unranked_ids, tuple(reasons)


def _rank_options(
    options: list[ScoredOption],
    *,
    criteria_used: tuple[ActiveCriterion, ...],
    profile: WeightProfile,
    view_name: str,
    plan_reasons: tuple[str, ...],
    unranked_candidate_count: int,
    climate_by_id: dict[str, tuple[MatchedCropExposure, ...]],
) -> tuple[RankingOutcome, list[ScoredOption], tuple[tuple[str, ...], ...]]:
    """Rank the selected evidence-comparable subset using visible effective weights."""

    if len(options) < 2:
        status: RankingStatus = "withheld" if not options else "insufficient_options"
        reason = (
            "No alternatives have comparable water evidence."
            if not options
            else "At least two evidence-comparable alternatives are required for ranking."
        )
        return (
            RankingOutcome(
                status=status,
                criteria_used=criteria_used,
                method=RANKING_METHOD,
                reasons=plan_reasons + (reason,),
                ranked_candidate_count=len(options),
                unranked_candidate_count=unranked_candidate_count,
            ),
            [],
            (),
        )

    blockers: list[str] = []
    for criterion in criteria_used:
        criterion_results = [_criterion(option, criterion) for option in options]
        if any(item.status != "assessed" or item.rating is None for item in criterion_results):
            blockers.append(f"{criterion} evidence is incomplete in the selected comparison set.")
            continue
        bases = {item.comparison_basis for item in criterion_results}
        if len(bases) != 1 or None in bases:
            blockers.append(f"{criterion} ratings use different comparison bases.")
    if blockers:
        return (
            RankingOutcome(
                status="withheld",
                criteria_used=criteria_used,
                method=RANKING_METHOD,
                reasons=plan_reasons + tuple(blockers),
                unranked_candidate_count=unranked_candidate_count + len(options),
            ),
            [],
            (),
        )

    weights = {item.criterion: item.percent for item in profile.normalized_weights}
    weight_fractions = {
        criterion: Fraction(weights[criterion]) / 100 for criterion in criteria_used
    }
    values_by_id: dict[str, Fraction] = {}
    options_by_id = {option.candidate.candidate_id: option for option in options}
    for option in options:
        value = sum(
            (
                weight_fractions[criterion] * RATING_ORDER[_criterion(option, criterion).rating]  # type: ignore[index]
                for criterion in criteria_used
            ),
            Fraction(0),
        )
        values_by_id[option.candidate.candidate_id] = value

    ordered = sorted(values_by_id.items(), key=lambda item: (-item[1], item[0]))
    full_groups: list[list[str]] = []
    previous_value: Fraction | None = None
    for candidate_id, value in ordered:
        if value != previous_value:
            full_groups.append([])
            previous_value = value
        full_groups[-1].append(candidate_id)

    weighted_groups = tuple(tuple(group) for group in full_groups)
    event_count_by_id = {
        candidate_id: len(option.candidate.events) for candidate_id, option in options_by_id.items()
    }
    all_groups, climate_preferences, climate_split = _refine_equal_groups_with_climate(
        weighted_groups, climate_by_id, event_count_by_id
    )
    selected, selected_groups, tie_at_limit = _top_three(all_groups, options_by_id)
    tradeoffs = _build_tradeoff_explanations(selected, values_by_id, weights, criteria_used)
    priorities_text = ", ".join(f"{criterion} {weights[criterion]}%" for criterion in criteria_used)
    reasons = list(plan_reasons)
    reasons.extend(
        (
            f"This is the {view_name} weighted comparison; effective priorities are "
            f"{priorities_text}.",
            "High/Moderate/Low are mapped to 3/2/1. This ordinal model assumes equal "
            "spacing between categories and is a comparison aid, not a probability or "
            "measured outcome.",
            "The comparison is compensatory: a gain on a higher-weight criterion can "
            "offset a weaker rating on another criterion. Hard constraints are applied "
            "before scoring and priorities cannot override them.",
            "Evidence and crop rules remain provisional until local validation; review "
            "warnings are retained with each option.",
        )
    )
    active_points = profile.points.model_dump()
    if profile.source == "farmer_selected":
        inactive_priorities = [
            criterion
            for criterion in CRITERIA
            if criterion not in criteria_used and active_points[criterion] > 0
        ]
        if inactive_priorities:
            reasons.append(
                "Farmer priorities for unavailable criteria are not applied in this mode: "
                + ", ".join(inactive_priorities)
                + "."
            )
        if sum(active_points[criterion] for criterion in criteria_used) == 0:
            reasons.append(
                "No positive farmer priority was set for the criteria used; equal weights "
                "were applied across those criteria."
            )
    if any(len(group) > 1 for group in all_groups):
        reasons.append(
            "Equal weighted totals remain tied unless complete, strict matched-crop "
            "CDD evidence establishes a provisional preference; otherwise candidate "
            "ID determines display order only."
        )
    if climate_split:
        reasons.append(
            "A complete strict matched-crop CDD comparison split an equal weighted "
            "total; criterion ratings and weighted totals were not changed."
        )
    elif climate_preferences:
        reasons.append(
            "Some pairwise CDD preferences exist, but incomparable alternatives "
            "keep the wider weighted rank group tied."
        )
    if tie_at_limit:
        reasons.append(
            "The three-option limit cuts through a tied rank group; other equally ranked "
            "options are omitted from the displayed shortlist."
        )
    outcome = RankingOutcome(
        status="ranked",
        criteria_used=criteria_used,
        rank_groups=selected_groups,
        reasons=tuple(reasons),
        method=RANKING_METHOD,
        ranked_candidate_count=len(options),
        unranked_candidate_count=unranked_candidate_count,
        tie_at_limit=tie_at_limit,
        tradeoffs=tradeoffs,
        climate_tie_preferences=climate_preferences,
    )
    return outcome, selected, all_groups


def score_rotation_options(request: ScoringRequest) -> ScoringResult:
    """Choose four-criterion or fallback ranking and return at most three options."""

    eligible: list[RotationOptionEvidence] = []
    excluded: list[ExcludedOption] = []
    for option in sorted(request.options, key=lambda item: item.candidate.candidate_id):
        failed = tuple(
            finding for finding in option.hard_constraints if finding.outcome == "failed"
        )
        if failed:
            excluded.append(ExcludedOption(candidate=option.candidate, failed_constraints=failed))
        else:
            eligible.append(option)

    baselines = [item for item in eligible if item.candidate.kind == "baseline"]
    alternatives_evidence = [item for item in eligible if item.candidate.kind != "baseline"]
    ranking_mode, criteria_used, rankable_evidence, unranked_ids, plan_reasons = (
        _select_ranking_plan(alternatives_evidence)
    )

    default_points = _equal_priority_points()
    selected_points = request.farmer_priorities or default_points
    default_profile = _weight_profile(
        default_points,
        "default_equal",
        criteria_used=criteria_used,
    )
    selected_profile = _weight_profile(
        selected_points,
        "farmer_selected" if request.farmer_priorities is not None else "default_equal",
        criteria_used=criteria_used,
    )

    scored_by_id: dict[str, ScoredOption] = {}
    for option in eligible:
        needs_review = tuple(
            finding for finding in option.hard_constraints if finding.outcome == "needs_review"
        )
        scored_by_id[option.candidate.candidate_id] = _build_scored_option(
            option,
            default_profile=default_profile,
            selected_profile=selected_profile,
            criteria_used=criteria_used,
            needs_review_constraints=needs_review,
        )

    baseline = scored_by_id[baselines[0].candidate.candidate_id] if baselines else None
    rankable_options = [scored_by_id[item.candidate.candidate_id] for item in rankable_evidence]
    climate_by_id = {
        item.candidate.candidate_id: item.climate_exposures for item in rankable_evidence
    }
    equal_ranking, _equal_top, equal_full_groups = _rank_options(
        rankable_options,
        criteria_used=criteria_used,
        profile=default_profile,
        view_name="equal-weight default",
        plan_reasons=plan_reasons,
        unranked_candidate_count=len(unranked_ids),
        climate_by_id=climate_by_id,
    )
    selected_ranking, selected, selected_full_groups = _rank_options(
        rankable_options,
        criteria_used=criteria_used,
        profile=selected_profile,
        view_name=("farmer-selected" if request.farmer_priorities is not None else "default"),
        plan_reasons=plan_reasons,
        unranked_candidate_count=len(unranked_ids),
        climate_by_id=climate_by_id,
    )

    if request.farmer_priorities is None:
        sensitivity: SensitivityStatus = "not_applicable"
    elif equal_ranking.status != "ranked" or selected_ranking.status != "ranked":
        sensitivity = "unavailable"
    elif equal_full_groups == selected_full_groups:
        sensitivity = "stable"
    else:
        sensitivity = "weight_sensitive"

    if sensitivity == "weight_sensitive":
        selected_ranking = selected_ranking.model_copy(
            update={
                "reasons": selected_ranking.reasons
                + (
                    "Farmer-selected priorities change the ranking relative to equal weights; "
                    "both rank groupings are included for comparison.",
                )
            }
        )

    return ScoringResult(
        scoring_version=SCORING_VERSION,
        candidate_count=len(request.options),
        ranking_method=RANKING_METHOD,
        ranking_mode=ranking_mode,
        default_weights=default_profile,
        selected_weights=selected_profile,
        options=tuple(selected),
        baseline_option=baseline,
        excluded_options=tuple(excluded),
        ranking=selected_ranking,
        equal_weight_ranking=equal_ranking,
        selected_weight_ranking=selected_ranking,
        sensitivity=sensitivity,
    )
