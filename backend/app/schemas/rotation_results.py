"""Safe JSON response schema for persisted rotation results."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.decisions.scoring import ScoringResult
from app.models.rotation_results import FarmDecisionInputSnapshot, RotationResult


class RotationResultResponse(BaseModel):
    """Expose a user's saved decision without exposing owner or auth internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    farm_id: str
    schema_version: str
    created_at: datetime
    farm_inputs: FarmDecisionInputSnapshot
    generator_version: str
    scoring_result: ScoringResult

    @classmethod
    def from_document(cls, result: RotationResult) -> RotationResultResponse:
        """Convert Mongo ObjectIds to API strings and select only response-safe fields."""

        if result.id is None:
            raise ValueError("A stored rotation result must have a MongoDB ID")
        return cls(
            id=str(result.id),
            farm_id=str(result.farm_id),
            schema_version=result.schema_version,
            created_at=result.created_at,
            farm_inputs=result.farm_inputs,
            generator_version=result.candidate_generation.generator_version,
            scoring_result=result.scoring_result,
        )
