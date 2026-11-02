"""Write-only persistence boundary for generated rotation results (NY-20)."""

from typing import Any

from beanie import PydanticObjectId

from app.decisions.rotation import RotationGenerationResult
from app.decisions.scoring import ScoringResult
from app.models.farms import Farm
from app.models.rotation_results import (
    FarmDecisionInputSnapshot,
    RotationDecisionInputs,
    RotationResult,
)


class FarmNotOwnedForResult(ValueError):
    """Raised when the authorized caller and supplied farm context do not match."""


class FarmNotPersistedForResult(ValueError):
    """Raised when a decision result is tied to a farm without a MongoDB ID."""


class RotationResultRepository:
    """Persist NY-8 outputs without recalculating them or accepting client owner IDs."""

    def __init__(self, result_model: Any = RotationResult) -> None:
        """Allow an in-memory document double in unit tests; production uses Beanie."""

        self._result_model = result_model

    async def create_for_farm(
        self,
        *,
        owner_user_id: PydanticObjectId,
        farm: Farm,
        decision_inputs: RotationDecisionInputs,
        candidate_generation: RotationGenerationResult,
        scoring_result: ScoringResult,
    ) -> RotationResult:
        """Insert a result using the caller identity and an already-authorized farm."""

        if farm.id is None:
            raise FarmNotPersistedForResult()
        if farm.owner_user_id != owner_user_id:
            raise FarmNotOwnedForResult()

        result = self._result_model(
            owner_user_id=owner_user_id,
            farm_id=farm.id,
            farm_inputs=FarmDecisionInputSnapshot.from_farm(farm),
            decision_inputs=decision_inputs,
            candidate_generation=candidate_generation,
            scoring_result=scoring_result,
        )
        await result.insert()
        return result
