"""NY-8 rotation contracts and deterministic candidate generation.

This module performs no database, HTTP, or filesystem I/O. It enumerates
candidate sequences and applies only the integrity/review rules supported by
the NY-14/NY-15 research. It does not score or rank recommendations.
"""

from __future__ import annotations

from datetime import date
from itertools import product
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROTATION_GENERATOR_VERSION = "ny8-candidates-v1"

CropSuitabilityStatus = Literal["unknown", "provisional", "locally_validated"]
CalendarStatus = Literal["unknown", "provisional", "locally_validated"]
SequenceEvidenceStatus = Literal["unknown", "provisional", "locally_validated"]
CandidateKind = Literal["baseline", "alternative"]
CandidateReadiness = Literal["structurally_valid", "needs_review"]
RuleOutcome = Literal["passed", "needs_review"]
CropId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]


class CropCandidate(BaseModel):
    """A crop offered to the generator, without guessed agronomic traits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    crop_id: CropId
    display_name: str = Field(min_length=1)
    suitability_status: CropSuitabilityStatus = "unknown"
    evidence_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validated_suitability_has_evidence(self) -> CropCandidate:
        """Require a citation for crop records labelled provisional or validated."""

        if self.suitability_status != "unknown" and not self.evidence_references:
            raise ValueError(
                "Provisional or validated crop suitability requires an evidence reference"
            )
        return self


# These are the six approved MVP candidate records. Inclusion means locally
# reported crop presence, not that a crop is suitable for every sequence.
MVP_CROP_CANDIDATES = (
    CropCandidate(crop_id="maize", display_name="Maize", evidence_references=("NY-14",)),
    CropCandidate(crop_id="cowpea", display_name="Cowpea", evidence_references=("NY-14",)),
    CropCandidate(crop_id="groundnut", display_name="Groundnut", evidence_references=("NY-14",)),
    CropCandidate(crop_id="cassava", display_name="Cassava", evidence_references=("NY-14",)),
    CropCandidate(crop_id="yam", display_name="Yam", evidence_references=("NY-14",)),
    CropCandidate(crop_id="rice", display_name="Rice", evidence_references=("NY-14",)),
)


class PlantingEventSlot(BaseModel):
    """One ordered planting event and its sourced calendar/data window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    order: int = Field(ge=1, le=3)
    plot_id: str = Field(min_length=1)
    season_label: str = Field(min_length=1)
    window_start: date
    window_end: date
    calendar_status: CalendarStatus = "unknown"
    calendar_source: str | None = None
    calendar_source_version: str | None = None

    @model_validator(mode="after")
    def validate_window(self) -> PlantingEventSlot:
        """Reject invalid date ranges and unverifiable validated calendars."""

        if self.window_end < self.window_start:
            raise ValueError("Planting event window end must be on or after its start")
        if self.calendar_status != "unknown" and not (
            self.calendar_source and self.calendar_source_version
        ):
            raise ValueError("A provisional or validated calendar requires a source and version")
        return self


class CurrentPractice(BaseModel):
    """Known three-event practice, included as a comparison baseline when supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    crop_ids: tuple[CropId, CropId, CropId]
    source_reference: str = Field(min_length=1)


class RotationGenerationRequest(BaseModel):
    """Inputs needed to produce ordered candidates for one plot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    planting_events: tuple[PlantingEventSlot, ...]
    candidate_crops: tuple[CropCandidate, ...] = MVP_CROP_CANDIDATES
    sequence_evidence_status: SequenceEvidenceStatus = "unknown"
    sequence_evidence_source: str | None = None
    prior_crop_history: tuple[CropId, ...] | None = None
    prior_history_source: str | None = None
    current_practice: CurrentPractice | None = None

    @model_validator(mode="after")
    def validate_generation_inputs(self) -> RotationGenerationRequest:
        """Enforce the three-event, same-plot, chronological data-integrity contract."""

        if len(self.planting_events) != 3:
            raise ValueError("A rotation requires exactly three planting events")

        expected_order = (1, 2, 3)
        actual_order = tuple(event.order for event in self.planting_events)
        if actual_order != expected_order:
            raise ValueError("Planting events must be ordered consecutively as 1, 2, 3")

        event_ids = tuple(event.event_id for event in self.planting_events)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("Planting event IDs must be unique")

        plot_ids = {event.plot_id for event in self.planting_events}
        if len(plot_ids) != 1:
            raise ValueError("All planting events in a rotation must belong to the same plot")

        for index in range(1, len(self.planting_events)):
            previous = self.planting_events[index - 1]
            following = self.planting_events[index]
            if following.window_start <= previous.window_end:
                raise ValueError("Planting event windows must be chronological and non-overlapping")

        crop_ids = tuple(crop.crop_id for crop in self.candidate_crops)
        if not crop_ids:
            raise ValueError("At least one candidate crop is required")
        if len(set(crop_ids)) != len(crop_ids):
            raise ValueError("Candidate crop IDs must be unique")

        if self.sequence_evidence_status != "unknown" and not self.sequence_evidence_source:
            raise ValueError(
                "Provisional or validated event continuity requires a source reference"
            )

        if self.prior_crop_history is not None:
            if not self.prior_crop_history:
                raise ValueError("Prior crop history must be omitted or contain at least one crop")
            if not self.prior_history_source:
                raise ValueError("Known prior crop history requires a source reference")
        return self


class CandidateRuleFinding(BaseModel):
    """A transparent result from a reviewed integrity or review rule."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    outcome: RuleOutcome
    explanation: str
    evidence_references: tuple[str, ...] = ()


class CandidatePlantingEvent(BaseModel):
    """A planting event paired with the crop assigned to that event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: PlantingEventSlot
    crop: CropCandidate


class RotationCandidate(BaseModel):
    """An ordered candidate sequence; it is not yet a scored recommendation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    kind: CandidateKind
    source_reference: str | None = None
    events: tuple[CandidatePlantingEvent, CandidatePlantingEvent, CandidatePlantingEvent]
    readiness: CandidateReadiness
    rule_findings: tuple[CandidateRuleFinding, ...]


class RotationGenerationResult(BaseModel):
    """Deterministic candidate set and the generator version that produced it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    generator_version: str = ROTATION_GENERATOR_VERSION
    readiness: CandidateReadiness
    candidates: tuple[RotationCandidate, ...]


def generate_rotation_candidates(
    request: RotationGenerationRequest,
) -> RotationGenerationResult:
    """Enumerate candidates in stable order and include a known baseline once.

    Repeated crops are retained as candidates because NY-15 treats repetition
    as a review concern, not a blanket hard exclusion. Provisional evidence
    also remains visible as ``needs_review`` instead of being promoted to a
    validated recommendation.
    """

    crops_by_id = {crop.crop_id: crop for crop in request.candidate_crops}
    ordered_crops = tuple(sorted(request.candidate_crops, key=lambda crop: crop.crop_id))
    findings_by_sequence = _base_rule_findings(request)

    candidates: list[RotationCandidate] = []
    baseline_sequence = request.current_practice.crop_ids if request.current_practice else None
    if baseline_sequence is not None:
        candidates.append(
            _build_candidate(
                sequence=baseline_sequence,
                kind="baseline",
                request=request,
                crops_by_id=crops_by_id,
                findings_by_sequence=findings_by_sequence,
                baseline_source=request.current_practice.source_reference,
            )
        )

    for sequence in product((crop.crop_id for crop in ordered_crops), repeat=3):
        if sequence == baseline_sequence:
            continue
        candidates.append(
            _build_candidate(
                sequence=sequence,
                kind="alternative",
                request=request,
                crops_by_id=crops_by_id,
                findings_by_sequence=findings_by_sequence,
            )
        )

    readiness: CandidateReadiness = (
        "needs_review"
        if any(candidate.readiness == "needs_review" for candidate in candidates)
        else "structurally_valid"
    )
    return RotationGenerationResult(readiness=readiness, candidates=tuple(candidates))


def _base_rule_findings(request: RotationGenerationRequest) -> tuple[CandidateRuleFinding, ...]:
    """Evaluate only high-confidence input-integrity and research-status rules."""

    if request.sequence_evidence_status == "locally_validated":
        findings = [
            CandidateRuleFinding(
                rule_id="ROT-001",
                outcome="passed",
                explanation=(
                    "The three ordered events are recorded as consecutive on one plot; "
                    f"continuity source: {request.sequence_evidence_source}."
                ),
                evidence_references=("NY-15", request.sequence_evidence_source or ""),
            )
        ]
    else:
        findings = [
            CandidateRuleFinding(
                rule_id="ROT-001",
                outcome="needs_review",
                explanation=(
                    "Three ordered event slots were supplied, but evidence that they are "
                    "consecutive planting events on the same plot is not locally validated."
                ),
                evidence_references=("NY-15",),
            )
        ]

    if request.prior_crop_history is None:
        findings.append(
            CandidateRuleFinding(
                rule_id="ROT-002",
                outcome="needs_review",
                explanation=(
                    "Prior crop history is unknown; do not infer fallow or an unreported crop."
                ),
                evidence_references=("NY-15",),
            )
        )
    else:
        findings.append(
            CandidateRuleFinding(
                rule_id="ROT-002",
                outcome="passed",
                explanation=(
                    f"Prior crop history was supplied with source {request.prior_history_source}."
                ),
                evidence_references=("NY-15", request.prior_history_source or ""),
            )
        )

    unvalidated_events = tuple(
        event for event in request.planting_events if event.calendar_status != "locally_validated"
    )
    if unvalidated_events:
        findings.append(
            CandidateRuleFinding(
                rule_id="ROT-003",
                outcome="needs_review",
                explanation=(
                    "At least one planting calendar is unknown or provisional; "
                    "calendar-dependent hard constraints are not applied."
                ),
                evidence_references=("NY-15",),
            )
        )
    else:
        findings.append(
            CandidateRuleFinding(
                rule_id="ROT-003",
                outcome="passed",
                explanation="All three planting calendars are locally validated.",
                evidence_references=(
                    "NY-15",
                    *(event.calendar_source or "" for event in request.planting_events),
                ),
            )
        )
    return tuple(findings)


def _build_candidate(
    *,
    sequence: tuple[str, str, str],
    kind: CandidateKind,
    request: RotationGenerationRequest,
    crops_by_id: dict[str, CropCandidate],
    findings_by_sequence: tuple[CandidateRuleFinding, ...],
    baseline_source: str | None = None,
) -> RotationCandidate:
    """Pair each crop with a slot and mark unsupported assumptions for review."""

    crop_records = tuple(
        crops_by_id.get(
            crop_id,
            CropCandidate(
                crop_id=crop_id,
                display_name=crop_id.replace("_", " ").replace("-", " ").title(),
                evidence_references=(baseline_source,) if baseline_source else (),
            ),
        )
        for crop_id in sequence
    )
    findings = list(findings_by_sequence)

    if any(crop.suitability_status != "locally_validated" for crop in crop_records):
        findings.append(
            CandidateRuleFinding(
                rule_id="NY14-SUITABILITY",
                outcome="needs_review",
                explanation=(
                    "Candidate-crop inclusion does not establish suitability for this plot, "
                    "calendar, variety, or management system."
                ),
                evidence_references=tuple(
                    sorted(
                        {
                            reference
                            for crop in crop_records
                            for reference in crop.evidence_references
                        }
                    )
                ),
            )
        )

    if len(set(sequence)) < len(sequence):
        findings.append(
            CandidateRuleFinding(
                rule_id="ROT-004",
                outcome="needs_review",
                explanation=(
                    "A crop repeats in this sequence. Repetition is flagged for review, "
                    "not excluded by a blanket rule."
                ),
                evidence_references=("NY-15",),
            )
        )

    paired_events = tuple(
        CandidatePlantingEvent(event=event, crop=crop)
        for event, crop in zip(request.planting_events, crop_records, strict=True)
    )
    readiness: CandidateReadiness = (
        "needs_review"
        if any(finding.outcome == "needs_review" for finding in findings)
        else "structurally_valid"
    )
    readable_sequence = "|".join(sequence)
    return RotationCandidate(
        candidate_id=f"{kind}:{readable_sequence}",
        kind=kind,
        source_reference=baseline_source,
        events=paired_events,
        readiness=readiness,
        rule_findings=tuple(findings),
    )
