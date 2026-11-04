"""NY-8 provisional water-first ranking and optional soil tie-breaking.

New results use a lexicographic order: water resilience is primary and
soil-health potential can break a tie only when its evidence is comparable.
Historical NY-8 result fields remain parseable for existing Mongo documents.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decisions.rotation import (
    CandidateRuleFinding,
    RotationCandidate,
)
from app.indicators.environmental import EnvironmentalIndicator

SCORING_VERSION = "ny8-scoring-v2"

Criterion = Literal[
    "water_resilience",
    "soil_health_potential",
    # Legacy values are retained solely to deserialize previously stored NY-20 results.
    "yield_stability_proxy",
    "labor_feasibility",
]
ActiveCriterion = Literal["water_resilience", "soil_health_potential"]
CriterionRating = Literal["high", "moderate", "low"]
Confidence = Literal["high", "moderate", "low"]
EvidenceStatus = Literal["assessed", "not_assessed"]
ConstraintOutcome = Literal["passed", "failed", "needs_review"]
WeightSource = Literal["default_equal", "farmer_selected"]
RankingStatus = Literal["ranked", "withheld", "insufficient_options"]
SensitivityStatus = Literal["not_applicable", "stable", "weight_sensitive", "unavailable"]
TransitionStatus = Literal["assessed", "needs_review", "not_assessed"]
CalendarEvidenceStatus = Literal["unknown", "provisional", "locally_validated"]

CRITERIA: tuple[ActiveCriterion, ...] = (
    "water_resilience",
    "soil_health_potential",
)

TOP_RECOMMENDATION_LIMIT = 3
RANKING_METHOD = "lexicographic_water_then_optional_soil"
LEGACY_RANKING_METHOD = "legacy_weighted_v1"


class PriorityPoints(BaseModel):
    """Legacy farmer priority values retained for reading old persisted records."""

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
    """Options to compare; legacy farmer points are retained but ignored in v2."""

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
    """Legacy normalized percentage retained for old result documents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion
    percent: Decimal = Field(ge=0, le=100)


class WeightProfile(BaseModel):
    """Legacy audit record retained so historical scoring results deserialize."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: WeightSource
    points: PriorityPoints
    normalized_weights: tuple[WeightShare, ...]


class CriterionResult(BaseModel):
    """Per-option display record; no numeric composite score is exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: Criterion = Field(
        description=(
            "NY-8 v2 emits only water_resilience and soil_health_potential. "
            "Older persisted scoring-v1 results may also contain yield/labour criteria."
        )
    )
    status: EvidenceStatus
    rating: CriterionRating | None
    confidence: Confidence | None
    equal_weight_percent: Decimal | None = None
    selected_weight_percent: Decimal | None = None
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
    event_assessments: tuple[EventAssessment, ...] = ()
    transition_assessments: tuple[TransitionAssessment, ...] = ()
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
    """Provisional water-first top-three ordering with ties and unranked count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RankingStatus
    rank_groups: tuple[tuple[str, ...], ...] = ()
    reasons: tuple[str, ...] = ()
    method: str = LEGACY_RANKING_METHOD
    provisional: bool = True
    ranked_candidate_count: int = 0
    unranked_candidate_count: int = 0
    tie_at_limit: bool = False


class ScoringResult(BaseModel):
    """Three returned alternatives, a separate baseline, and ranking provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoring_version: str = SCORING_VERSION
    rating_scale: Literal["relative_qualitative"] = "relative_qualitative"
    ranking_method: str = RANKING_METHOD
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
    # Optional legacy fields preserve deserialization of NY-8 scoring-v1 records.
    equal_weight_ranking: RankingOutcome | None = None
    selected_weight_ranking: RankingOutcome | None = None
    sensitivity: SensitivityStatus | None = None

    @model_validator(mode="before")
    @classmethod
    def add_legacy_result_metadata(cls, value: object) -> object:
        """Keep v1 scores labeled as weighted results when old Mongo docs load."""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if payload.get("scoring_version") == "ny8-scoring-v1":
            payload.setdefault("ranking_method", LEGACY_RANKING_METHOD)
            payload.setdefault("candidate_count", len(payload.get("options", ())))
        return payload

    @model_validator(mode="after")
    def validate_v2_output_contract(self) -> ScoringResult:
        """Protect the new top-three/two-criterion contract, while reading v1 docs."""

        if self.scoring_version != SCORING_VERSION:
            return self
        if len(self.options) > TOP_RECOMMENDATION_LIMIT:
            raise ValueError("NY-8 v2 can return at most three alternatives")
        if self.ranking is None:
            raise ValueError("NY-8 v2 requires ranking status and rationale")
        if self.ranking_method != RANKING_METHOD:
            raise ValueError("NY-8 v2 requires the fixed water-first ranking method")
        if any(
            result.criterion not in CRITERIA
            for option in self.options
            for result in option.criteria
        ):
            raise ValueError("NY-8 v2 results can expose only water and soil criteria")
        if self.default_weights is not None or self.selected_weights is not None:
            raise ValueError("NY-8 v2 uses fixed criterion precedence, not weighted profiles")
        return self


def _build_provisional_option(
    option: RotationOptionEvidence,
    *,
    needs_review_constraints: tuple[HardConstraintFinding, ...],
) -> ScoredOption:
    """Return only the current water and optional soil assessments."""

    evidence_by_criterion = {item.criterion: item for item in option.criteria}
    results: list[CriterionResult] = []
    for criterion in CRITERIA:
        evidence = evidence_by_criterion.get(criterion)
        if evidence is None:
            evidence = CriterionEvidence(
                criterion=criterion,
                status="not_assessed",
                rationale="No comparable evidence was supplied for this criterion.",
            )
        results.append(
            CriterionResult(
                criterion=criterion,
                status=evidence.status,
                rating=evidence.rating,
                confidence=evidence.confidence,
                rationale=evidence.rationale,
                comparison_basis=evidence.comparison_basis,
                evidence_references=evidence.evidence_references,
                environmental_inputs=evidence.environmental_inputs,
                assumptions=evidence.assumptions,
            )
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
        criteria=tuple(results),
        hard_constraints=option.hard_constraints,
        event_assessments=option.event_assessments,
        transition_assessments=option.transition_assessments,
        candidate_rule_findings=option.candidate.rule_findings,
        benefits=option.benefits,
        trade_offs=option.trade_offs,
        assumptions=option.assumptions,
        warnings=warnings,
    )


def _criterion(option: ScoredOption, criterion: ActiveCriterion) -> CriterionResult:
    """Find one active criterion already normalized into the output option."""

    return next(item for item in option.criteria if item.criterion == criterion)


def _rank_provisionally(
    options: list[ScoredOption],
) -> tuple[tuple[tuple[str, ...], ...], dict[str, ScoredOption], int, str | None]:
    """Rank comparable water groups and use soil only for complete tied groups."""

    assessed = [
        option
        for option in options
        if _criterion(option, "water_resilience").status == "assessed"
        and _criterion(option, "water_resilience").rating is not None
    ]
    bases = {_criterion(option, "water_resilience").comparison_basis for option in assessed}
    if len(bases) > 1 or (assessed and None in bases):
        return (
            (),
            {},
            len(options),
            "Primary water evidence uses different or missing comparison bases; "
            "ranking is withheld.",
        )
    if not assessed:
        return (), {}, len(options), None

    groups: list[tuple[str, ...]] = []
    for water_rating in ("high", "moderate", "low"):
        water_group = [
            option
            for option in assessed
            if _criterion(option, "water_resilience").rating == water_rating
        ]
        if not water_group:
            continue

        soil_evidence = [_criterion(option, "soil_health_potential") for option in water_group]
        soil_is_comparable = (
            all(item.status == "assessed" and item.rating is not None for item in soil_evidence)
            and len({item.comparison_basis for item in soil_evidence}) == 1
            and soil_evidence[0].comparison_basis is not None
        )
        if soil_is_comparable:
            for soil_rating in ("high", "moderate", "low"):
                tied = [
                    option
                    for option in water_group
                    if _criterion(option, "soil_health_potential").rating == soil_rating
                ]
                if tied:
                    groups.append(tuple(sorted(item.candidate.candidate_id for item in tied)))
        else:
            groups.append(tuple(sorted(item.candidate.candidate_id for item in water_group)))

    by_id = {option.candidate.candidate_id: option for option in assessed}
    return tuple(groups), by_id, len(options) - len(assessed), None


def _top_three(
    groups: tuple[tuple[str, ...], ...],
    options_by_id: dict[str, ScoredOption],
) -> tuple[list[ScoredOption], tuple[tuple[str, ...], ...], bool]:
    """Return at most three options, marking when the cutoff splits a tie.

    Candidate ID supplies stable display order within a tie. It is not a score
    or agronomic preference; a tie cut by the limit remains explicitly marked.
    """

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


def score_rotation_options(request: ScoringRequest) -> ScoringResult:
    """Apply constraints, water-first ranking, optional soil ties, and a top-three cap.

    Farmer priority points are retained on the request for historical-record
    compatibility, but cannot override the Product Owner's fixed water-first
    policy. Missing water evidence stays unranked. Missing soil evidence never
    blocks a water comparison and is never imputed.
    """

    scored: list[ScoredOption] = []
    excluded: list[ExcludedOption] = []
    for option in sorted(request.options, key=lambda item: item.candidate.candidate_id):
        failed = tuple(
            finding for finding in option.hard_constraints if finding.outcome == "failed"
        )
        if failed:
            excluded.append(ExcludedOption(candidate=option.candidate, failed_constraints=failed))
            continue

        needs_review = tuple(
            finding for finding in option.hard_constraints if finding.outcome == "needs_review"
        )
        scored.append(_build_provisional_option(option, needs_review_constraints=needs_review))

    baseline = next((option for option in scored if option.candidate.kind == "baseline"), None)
    alternatives = [option for option in scored if option.candidate.kind != "baseline"]
    rank_groups, rankable_by_id, unranked_count, comparability_issue = _rank_provisionally(
        alternatives
    )
    selected, selected_groups, tie_at_limit = _top_three(rank_groups, rankable_by_id)

    reasons = [
        "This ranking is provisional and based on crop-level public evidence; "
        "it is not local agronomic validation.",
        "The water rating uses the least-resilient crop in the three-season "
        "sequence as a conservative bottleneck.",
        "Historical NASA indicators are context only; they are not a future-weather "
        "forecast or a crop water-balance calculation.",
    ]
    if comparability_issue:
        reasons.append(comparability_issue)
    if unranked_count and comparability_issue is None:
        reasons.append(
            f"{unranked_count} alternative(s) lack comparable primary water "
            "evidence and remain unranked."
        )
    if any(len(group) > 1 for group in rank_groups):
        reasons.append(
            "Options within a tied group use candidate ID for stable display order; "
            "this is not an agronomic preference."
        )
    if tie_at_limit:
        reasons.append(
            "The three-item display limit splits a tied rank group; other equally "
            "ranked options are omitted from the short list."
        )
    if len(alternatives) < TOP_RECOMMENDATION_LIMIT:
        reasons.append(
            f"Only {len(alternatives)} valid alternative(s) were available; "
            "fewer than three can be returned."
        )
    elif selected and len(selected) < TOP_RECOMMENDATION_LIMIT:
        reasons.append(
            "Fewer than three alternatives had comparable water evidence; the "
            "result does not fill the limit with unranked options."
        )

    status: RankingStatus
    if not selected:
        status = "withheld"
    elif len(alternatives) < TOP_RECOMMENDATION_LIMIT:
        status = "insufficient_options"
    else:
        status = "ranked"
    ranking = RankingOutcome(
        status=status,
        rank_groups=selected_groups,
        reasons=tuple(reasons),
        method=RANKING_METHOD,
        ranked_candidate_count=len(rankable_by_id),
        unranked_candidate_count=unranked_count,
        tie_at_limit=tie_at_limit,
    )
    return ScoringResult(
        candidate_count=len(request.options),
        ranking_method=RANKING_METHOD,
        options=tuple(selected),
        baseline_option=baseline,
        excluded_options=tuple(excluded),
        ranking=ranking,
    )
