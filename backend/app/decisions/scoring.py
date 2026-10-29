"""NY-8 qualitative multi-criteria comparison and ranking.

The scorer aggregates supplied, evidence-backed criterion assessments. It does
not infer crop performance from a crop name or calculate agronomic ratings
from unvalidated inputs.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decisions.rotation import (
    CandidateRuleFinding,
    RotationCandidate,
)
from app.indicators.environmental import EnvironmentalIndicator

SCORING_VERSION = "ny8-scoring-v1"
WEIGHT_PERCENT_QUANTUM = Decimal("0.0001")

Criterion = Literal[
    "water_resilience",
    "soil_health_potential",
    "yield_stability_proxy",
    "labor_feasibility",
]
CriterionRating = Literal["high", "moderate", "low"]
Confidence = Literal["high", "moderate", "low"]
EvidenceStatus = Literal["assessed", "not_assessed"]
ConstraintOutcome = Literal["passed", "failed", "needs_review"]
WeightSource = Literal["default_equal", "farmer_selected"]
RankingStatus = Literal["ranked", "withheld", "insufficient_options"]
SensitivityStatus = Literal["not_applicable", "stable", "weight_sensitive", "unavailable"]

CRITERIA: tuple[Criterion, ...] = (
    "water_resilience",
    "soil_health_potential",
    "yield_stability_proxy",
    "labor_feasibility",
)

RATING_ORDER: dict[CriterionRating, int] = {"high": 3, "moderate": 2, "low": 1}
RANKING_BLOCKER_RULE_IDS = frozenset({"ROT-001", "ROT-002", "ROT-003", "NY14-SUITABILITY"})


class PriorityPoints(BaseModel):
    """Farmer-entered importance points; relative weights are normalized later."""

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


class RotationOptionEvidence(BaseModel):
    """Candidate plus the evidence and hard-rule outcomes used for comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RotationCandidate
    hard_constraints: tuple[HardConstraintFinding, ...] = ()
    criteria: tuple[CriterionEvidence, ...] = ()
    benefits: tuple[str, ...] = ()
    trade_offs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_one_assessment_per_criterion(self) -> RotationOptionEvidence:
        """Require explicit assessed or not-assessed state for all four criteria."""

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
        if len(criterion_ids) != len(CRITERIA) or set(criterion_ids) != set(CRITERIA):
            raise ValueError("Every option must provide exactly one assessment for each criterion")
        return self


class ScoringRequest(BaseModel):
    """Options to compare and optional farmer importance points."""

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
    """Normalized percentage shown alongside every criterion assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion
    percent: Decimal = Field(ge=0, le=100)


class WeightProfile(BaseModel):
    """Auditable origin and normalized form of a weight profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: WeightSource
    points: PriorityPoints
    normalized_weights: tuple[WeightShare, ...]


class CriterionResult(BaseModel):
    """Per-option display record; no numeric composite score is exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion
    status: EvidenceStatus
    rating: CriterionRating | None
    confidence: Confidence | None
    equal_weight_percent: Decimal
    selected_weight_percent: Decimal
    rationale: str
    comparison_basis: str | None
    evidence_references: tuple[str, ...]
    environmental_inputs: tuple[EnvironmentalIndicator, ...]
    assumptions: tuple[str, ...]


class ScoredOption(BaseModel):
    """Presentation-ready qualitative evidence for one non-excluded option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RotationCandidate
    criteria: tuple[CriterionResult, ...]
    hard_constraints: tuple[HardConstraintFinding, ...]
    candidate_rule_findings: tuple[CandidateRuleFinding, ...]
    benefits: tuple[str, ...]
    trade_offs: tuple[str, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]


class ExcludedOption(BaseModel):
    """A failed hard constraint excludes an option before it can be scored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RotationCandidate
    failed_constraints: tuple[HardConstraintFinding, ...]


class RankingOutcome(BaseModel):
    """Tie-aware ordering, or an explicit reason no overall rank is available."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RankingStatus
    rank_groups: tuple[tuple[str, ...], ...] = ()
    reasons: tuple[str, ...] = ()


class ScoringResult(BaseModel):
    """Criterion comparisons, exclusions, weight sensitivity, and rank status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoring_version: str = SCORING_VERSION
    rating_scale: Literal["relative_qualitative"] = "relative_qualitative"
    default_weights: WeightProfile
    selected_weights: WeightProfile
    options: tuple[ScoredOption, ...]
    excluded_options: tuple[ExcludedOption, ...]
    equal_weight_ranking: RankingOutcome
    selected_weight_ranking: RankingOutcome
    sensitivity: SensitivityStatus


def score_rotation_options(request: ScoringRequest) -> ScoringResult:
    """Compare options with sourced qualitative evidence under two weight views.

    Hard failures are removed before scoring. Missing/incomparable evidence or
    unresolved hard-rule review blocks the overall rank but preserves all
    available per-criterion comparisons. Farmer priorities never affect
    validity.
    """

    default_points = _equal_priority_points()
    selected_points = request.farmer_priorities or default_points
    default_profile = _weight_profile(default_points, "default_equal")
    selected_profile = _weight_profile(
        selected_points,
        "farmer_selected" if request.farmer_priorities is not None else "default_equal",
    )

    scored_options: list[ScoredOption] = []
    excluded_options: list[ExcludedOption] = []
    ranking_blockers: list[str] = []

    for option in sorted(request.options, key=lambda item: item.candidate.candidate_id):
        failed = tuple(
            finding for finding in option.hard_constraints if finding.outcome == "failed"
        )
        if failed:
            excluded_options.append(
                ExcludedOption(
                    candidate=option.candidate,
                    failed_constraints=failed,
                )
            )
            continue

        needs_review_constraints = tuple(
            finding for finding in option.hard_constraints if finding.outcome == "needs_review"
        )
        ranking_blockers.extend(
            f"{option.candidate.candidate_id}: {finding.rule_id} needs review: {finding.rationale}"
            for finding in needs_review_constraints
        )
        ranking_blockers.extend(
            f"{option.candidate.candidate_id}: {finding.rule_id} needs review: "
            f"{finding.explanation}"
            for finding in option.candidate.rule_findings
            if finding.rule_id in RANKING_BLOCKER_RULE_IDS and finding.outcome == "needs_review"
        )

        scored_options.append(
            _build_scored_option(
                option,
                default_profile=default_profile,
                selected_profile=selected_profile,
                needs_review_constraints=needs_review_constraints,
            )
        )

    equal_ranking = _rank_options(
        scored_options,
        points=default_points,
        blockers=ranking_blockers,
    )
    selected_ranking = _rank_options(
        scored_options,
        points=selected_points,
        blockers=ranking_blockers,
    )

    if request.farmer_priorities is None:
        sensitivity: SensitivityStatus = "not_applicable"
    elif equal_ranking.status != "ranked" or selected_ranking.status != "ranked":
        sensitivity = "unavailable"
    elif equal_ranking.rank_groups == selected_ranking.rank_groups:
        sensitivity = "stable"
    else:
        sensitivity = "weight_sensitive"

    return ScoringResult(
        default_weights=default_profile,
        selected_weights=selected_profile,
        options=tuple(scored_options),
        excluded_options=tuple(excluded_options),
        equal_weight_ranking=equal_ranking,
        selected_weight_ranking=selected_ranking,
        sensitivity=sensitivity,
    )


def _equal_priority_points() -> PriorityPoints:
    """Create the approved default without sharing a mutable model instance."""

    return PriorityPoints(
        water_resilience=25,
        soil_health_potential=25,
        yield_stability_proxy=25,
        labor_feasibility=25,
    )


def _weight_profile(points: PriorityPoints, source: WeightSource) -> WeightProfile:
    """Normalize points to visible percentages that sum exactly to 100.

    Percentages are rounded to four decimal places. The final non-zero criterion
    absorbs any rounding remainder so a zero-weight criterion stays at zero.
    """

    values = points.model_dump()
    total = sum(values.values())
    normalized: dict[Criterion, Decimal] = {}
    for criterion in CRITERIA:
        percentage = (Decimal(values[criterion]) * 100 / total).quantize(
            WEIGHT_PERCENT_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        normalized[criterion] = percentage

    correction = Decimal("100") - sum(normalized.values(), Decimal("0"))
    correction_target = next(criterion for criterion in reversed(CRITERIA) if values[criterion] > 0)
    normalized[correction_target] += correction
    shares = tuple(
        WeightShare(criterion=criterion, percent=normalized[criterion]) for criterion in CRITERIA
    )
    return WeightProfile(source=source, points=points, normalized_weights=shares)


def _build_scored_option(
    option: RotationOptionEvidence,
    *,
    default_profile: WeightProfile,
    selected_profile: WeightProfile,
    needs_review_constraints: tuple[HardConstraintFinding, ...],
) -> ScoredOption:
    """Join evidence with both disclosed weight profiles in fixed criterion order."""

    evidence_by_criterion = {item.criterion: item for item in option.criteria}
    default_by_criterion = {
        item.criterion: item.percent for item in default_profile.normalized_weights
    }
    selected_by_criterion = {
        item.criterion: item.percent for item in selected_profile.normalized_weights
    }
    criterion_results = tuple(
        CriterionResult(
            criterion=criterion,
            status=evidence_by_criterion[criterion].status,
            rating=evidence_by_criterion[criterion].rating,
            confidence=evidence_by_criterion[criterion].confidence,
            equal_weight_percent=default_by_criterion[criterion],
            selected_weight_percent=selected_by_criterion[criterion],
            rationale=evidence_by_criterion[criterion].rationale,
            comparison_basis=evidence_by_criterion[criterion].comparison_basis,
            evidence_references=evidence_by_criterion[criterion].evidence_references,
            environmental_inputs=evidence_by_criterion[criterion].environmental_inputs,
            assumptions=evidence_by_criterion[criterion].assumptions,
        )
        for criterion in CRITERIA
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
        criteria=criterion_results,
        hard_constraints=option.hard_constraints,
        candidate_rule_findings=option.candidate.rule_findings,
        benefits=option.benefits,
        trade_offs=option.trade_offs,
        assumptions=option.assumptions,
        warnings=warnings,
    )


def _rank_options(
    options: list[ScoredOption],
    *,
    points: PriorityPoints,
    blockers: list[str],
) -> RankingOutcome:
    """Return tie-aware rank groups only when all compared evidence is complete."""

    if len(options) < 2:
        return RankingOutcome(
            status="insufficient_options",
            reasons=("At least two non-excluded options are required for comparison.",),
        )

    reasons = list(dict.fromkeys(blockers))

    for criterion in CRITERIA:
        assessments = [
            next(result for result in option.criteria if result.criterion == criterion)
            for option in options
        ]
        missing_ids = tuple(
            option.candidate.candidate_id
            for option, assessment in zip(options, assessments, strict=True)
            if assessment.status != "assessed" or assessment.rating is None
        )
        if missing_ids:
            reasons.append(f"{criterion} is not assessed for: {', '.join(missing_ids)}.")
            continue

        incomplete_source_ids = tuple(
            option.candidate.candidate_id
            for option, assessment in zip(options, assessments, strict=True)
            if any(
                indicator.status != "complete" or indicator.data_status == "unavailable"
                for indicator in assessment.environmental_inputs
            )
        )
        if incomplete_source_ids:
            reasons.append(
                f"{criterion} uses partial or unavailable environmental data for: "
                f"{', '.join(incomplete_source_ids)}."
            )

        bases = {assessment.comparison_basis for assessment in assessments}
        if len(bases) != 1 or None in bases:
            reasons.append(f"{criterion} evidence uses incomparable assessment bases.")

    if reasons:
        return RankingOutcome(status="withheld", reasons=tuple(reasons))

    total_points = sum(points.model_dump().values())
    weighted_values: list[tuple[Fraction, str]] = []
    for option in options:
        result_by_criterion = {result.criterion: result for result in option.criteria}
        value = sum(
            (
                Fraction(getattr(points, criterion), total_points)
                * RATING_ORDER[result_by_criterion[criterion].rating]
                for criterion in CRITERIA
            ),
            Fraction(0),
        )
        weighted_values.append((value, option.candidate.candidate_id))

    weighted_values.sort(key=lambda item: (-item[0], item[1]))
    rank_groups: list[list[str]] = []
    previous_value: Fraction | None = None
    for value, candidate_id in weighted_values:
        if value != previous_value:
            rank_groups.append([])
            previous_value = value
        rank_groups[-1].append(candidate_id)

    return RankingOutcome(
        status="ranked",
        rank_groups=tuple(tuple(group) for group in rank_groups),
    )
