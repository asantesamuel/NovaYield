"""Safe JSON response schema for persisted rotation results."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.decisions.scoring import CRITERIA, ScoringResult
from app.models.rotation_results import FarmDecisionInputSnapshot, RotationResult


class CandidatePoolSummary(BaseModel):
    """Counts audit the generated pool without returning all generated candidates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_generated: int = Field(ge=0)
    total_excluded: int = Field(ge=0)
    total_needing_review: int = Field(ge=0)
    total_assessed: int = Field(ge=0)
    total_rankable: int = Field(ge=0)
    total_returned: int = Field(ge=0)


class RotationResultResponse(BaseModel):
    """Expose a user's saved decision without exposing owner or auth internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    farm_id: str
    schema_version: str
    created_at: datetime
    farm_inputs: FarmDecisionInputSnapshot
    generator_version: str
    crop_library_version: str
    assessment_version: str
    rule_set_version: str
    environmental_snapshot_ids: tuple[str, ...]
    candidate_pool_summary: CandidatePoolSummary
    scoring_result: ScoringResult

    @classmethod
    def from_document(cls, result: RotationResult) -> RotationResultResponse:
        """Convert Mongo ObjectIds to API strings and select only response-safe fields."""

        if result.id is None:
            raise ValueError("A stored rotation result must have a MongoDB ID")
        excluded_ids = {
            item.candidate.candidate_id for item in result.scoring_result.excluded_options
        }
        assessment_by_id = {
            item.candidate.candidate_id: item
            for item in result.decision_inputs.scoring_request.options
        }
        total_assessed = sum(
            all(
                any(
                    criterion.criterion == required and criterion.status == "assessed"
                    for criterion in assessment.criteria
                )
                for required in CRITERIA
            )
            for candidate_id, assessment in assessment_by_id.items()
            if candidate_id not in excluded_ids
        )
        ranking = result.scoring_result.ranking
        candidate_pool_summary = CandidatePoolSummary(
            total_generated=len(result.candidate_generation.candidates),
            total_excluded=len(excluded_ids),
            total_needing_review=sum(
                candidate.readiness == "needs_review"
                for candidate in result.candidate_generation.candidates
            ),
            total_assessed=total_assessed,
            total_rankable=ranking.ranked_candidate_count if ranking is not None else 0,
            total_returned=(
                len(result.scoring_result.options)
                + int(result.scoring_result.baseline_option is not None)
            ),
        )
        return cls(
            id=str(result.id),
            farm_id=str(result.farm_id),
            schema_version=result.schema_version,
            created_at=result.created_at,
            farm_inputs=result.farm_inputs,
            generator_version=result.candidate_generation.generator_version,
            crop_library_version=result.decision_inputs.crop_library_version,
            assessment_version=result.decision_inputs.assessment_version,
            rule_set_version=result.decision_inputs.rule_set_version,
            environmental_snapshot_ids=tuple(
                str(snapshot_id)
                for snapshot_id in result.decision_inputs.environmental_snapshot_ids
            ),
            candidate_pool_summary=candidate_pool_summary,
            scoring_result=result.scoring_result,
        )
