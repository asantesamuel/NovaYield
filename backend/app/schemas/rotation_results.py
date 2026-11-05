"""Safe JSON response schema for persisted rotation results."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.decisions.climate_features import StageCDDExposure
from app.decisions.rotation import CandidatePlantingEvent
from app.decisions.scoring import CRITERIA, PriorityPoints, ScoringResult
from app.farms.context_window import DerivedContextPeriod
from app.indicators.environmental import EnvironmentalIndicator
from app.models.rotation_results import (
    FutureWindowSummary,
    RotationResult,
    SnapshotUseProvenance,
)


class FarmDecisionInputPublic(BaseModel):
    """Recorded farm inputs without legacy current-practice text or owner IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    location_key: str
    farm_revision: int | None = None
    soil_texture_key: str | None = None
    irrigation_access_key: str | None = None
    history_status: str | None = None
    current_plot_available: bool | None = None
    earliest_available_date: date | None = None
    farmer_priorities: PriorityPoints | None = None
    farm_updated_at: datetime


class HistoryEventResultPublic(BaseModel):
    """One saved reported event with its stable crop reference and actual dates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    crop_id: str
    crop_key: str
    sequence_order: int
    start_date: date | None
    end_date: date | None
    variety_key: str | None
    production_system_key: str | None


class CandidatePoolSummary(BaseModel):
    """Counts audit the generated pool without returning all generated candidates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_generated: int = Field(ge=0)
    total_excluded: int = Field(ge=0)
    total_needing_review: int = Field(ge=0)
    total_assessed: int = Field(ge=0)
    total_rankable: int = Field(ge=0)
    total_returned: int = Field(ge=0)


class UnrankedCalendarExample(BaseModel):
    """A dated candidate shown only as a review example, never as a recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    status: str = "unranked_needs_review"
    events: tuple[CandidatePlantingEvent, CandidatePlantingEvent, CandidatePlantingEvent]
    review_reasons: tuple[str, ...]
    selection_note: str = (
        "Deterministic calendar example selected by candidate ID for review only; "
        "it has no rank or agronomic endorsement."
    )


class RotationResultResponse(BaseModel):
    """Expose a user's saved decision without exposing owner or auth internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    farm_id: str
    schema_version: str
    created_at: datetime
    farm_inputs: FarmDecisionInputPublic
    history_event_snapshots: tuple[HistoryEventResultPublic, ...] = ()
    derived_context_period: DerivedContextPeriod | None = None
    context_provenance: SnapshotUseProvenance | None = None
    climate_reference_provenance: SnapshotUseProvenance | None = None
    indicators: tuple[EnvironmentalIndicator, ...] = ()
    climate_features: tuple[StageCDDExposure, ...] = ()
    climate_feature_status_reason: str | None = None
    future_window_summary: FutureWindowSummary | None = None
    unranked_calendar_examples: tuple[UnrankedCalendarExample, ...] = ()
    baseline_status: str | None = None
    decision_status: str | None = None
    generator_version: str
    crop_library_version: str
    assessment_version: str
    rule_set_version: str
    environmental_snapshot_ids: tuple[str, ...]
    climate_reference_ids: tuple[str, ...] = ()
    crop_profile_revision_ids: tuple[str, ...] = ()
    calendar_version_ids: tuple[str, ...] = ()
    scoring_version: str = "not_recorded"
    climate_method_version: str = "not_recorded"
    calendar_method_version: str = "not_recorded"
    candidate_pool_summary: CandidatePoolSummary
    scoring_result: ScoringResult

    @classmethod
    def from_document(cls, result: RotationResult) -> RotationResultResponse:
        """Convert Mongo ObjectIds to API strings and select only response-safe fields."""

        if result.id is None:
            raise ValueError("A stored rotation result must have a MongoDB ID")
        # Older NY-20 records keep their original baseline for audit, but the
        # approved NY-38 farmer-facing workflow defers baseline presentation.
        public_scoring_result = result.scoring_result.model_copy(update={"baseline_option": None})
        excluded_ids = {
            item.candidate.candidate_id for item in result.scoring_result.excluded_options
        }
        calendar_examples: tuple[UnrankedCalendarExample, ...] = ()
        if result.schema_version == "ny38-result-v2" and not public_scoring_result.options:
            dated_candidates = sorted(
                (
                    candidate
                    for candidate in result.candidate_generation.candidates
                    if candidate.candidate_id not in excluded_ids
                    and all(
                        event.event.window_start is not None
                        and event.event.window_end is not None
                        and event.event.harvest_start is not None
                        and event.event.harvest_end is not None
                        for event in candidate.events
                    )
                ),
                key=lambda candidate: candidate.candidate_id,
            )
            calendar_examples = tuple(
                UnrankedCalendarExample(
                    candidate_id=candidate.candidate_id,
                    events=candidate.events,
                    review_reasons=tuple(
                        finding.explanation
                        for finding in candidate.rule_findings
                        if finding.outcome == "needs_review"
                    ),
                )
                for candidate in dated_candidates[:3]
            )
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
            total_returned=len(public_scoring_result.options),
        )
        return cls(
            id=str(result.id),
            farm_id=str(result.farm_id),
            schema_version=result.schema_version,
            created_at=result.created_at,
            farm_inputs=FarmDecisionInputPublic(
                schema_version=result.farm_inputs.schema_version,
                location_key=result.farm_inputs.location_key,
                farm_revision=result.farm_inputs.farm_revision,
                soil_texture_key=result.farm_inputs.soil_texture_key,
                irrigation_access_key=result.farm_inputs.irrigation_access_key,
                history_status=result.farm_inputs.history_status,
                current_plot_available=result.farm_inputs.current_plot_available,
                earliest_available_date=result.farm_inputs.earliest_available_date,
                farmer_priorities=result.farm_inputs.farmer_priorities,
                farm_updated_at=result.farm_inputs.farm_updated_at,
            ),
            history_event_snapshots=tuple(
                HistoryEventResultPublic(
                    event_id=event.event_id,
                    crop_id=str(event.crop_id),
                    crop_key=event.crop_key_snapshot,
                    sequence_order=event.sequence_order,
                    start_date=event.start_date,
                    end_date=event.end_date,
                    variety_key=event.variety_key,
                    production_system_key=event.production_system_key,
                )
                for event in result.history_event_snapshots
            ),
            derived_context_period=result.derived_context_period,
            context_provenance=result.context_provenance,
            climate_reference_provenance=result.climate_reference_provenance,
            indicators=result.indicators,
            climate_features=result.climate_features,
            climate_feature_status_reason=result.climate_feature_status_reason,
            future_window_summary=result.future_window_summary,
            unranked_calendar_examples=calendar_examples,
            baseline_status=result.baseline_status,
            decision_status=result.decision_status,
            generator_version=result.candidate_generation.generator_version,
            crop_library_version=result.decision_inputs.crop_library_version,
            assessment_version=result.decision_inputs.assessment_version,
            rule_set_version=result.decision_inputs.rule_set_version,
            environmental_snapshot_ids=tuple(
                str(snapshot_id)
                for snapshot_id in result.decision_inputs.environmental_snapshot_ids
            ),
            climate_reference_ids=tuple(
                str(snapshot_id) for snapshot_id in result.decision_inputs.climate_reference_ids
            ),
            crop_profile_revision_ids=tuple(
                str(profile_id) for profile_id in result.decision_inputs.crop_profile_revision_ids
            ),
            calendar_version_ids=tuple(
                str(calendar_id) for calendar_id in result.decision_inputs.calendar_version_ids
            ),
            scoring_version=result.decision_inputs.scoring_version,
            climate_method_version=result.decision_inputs.climate_method_version,
            calendar_method_version=result.decision_inputs.calendar_method_version,
            candidate_pool_summary=candidate_pool_summary,
            scoring_result=public_scoring_result,
        )
