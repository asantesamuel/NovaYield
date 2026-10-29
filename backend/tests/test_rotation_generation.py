"""Tests for NY-8 candidate generation; all farms/crops here are synthetic fixtures."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.decisions.rotation import (
    MVP_CROP_CANDIDATES,
    CropCandidate,
    CurrentPractice,
    PlantingEventSlot,
    RotationGenerationRequest,
    generate_rotation_candidates,
)


def make_event(
    *,
    event_id: str,
    order: int,
    plot_id: str = "synthetic-test-plot",
    start: date,
    end: date,
    calendar_status: str = "locally_validated",
) -> PlantingEventSlot:
    """Create an explicitly synthetic event slot for unit tests only."""

    return PlantingEventSlot(
        event_id=event_id,
        order=order,
        plot_id=plot_id,
        season_label=f"test-season-{order}",
        window_start=start,
        window_end=end,
        calendar_status=calendar_status,  # type: ignore[arg-type]
        calendar_source="synthetic test fixture",
        calendar_source_version="fixture-v1",
    )


def make_request(
    *,
    candidate_crops: tuple[CropCandidate, ...] = MVP_CROP_CANDIDATES,
    calendar_status: str = "locally_validated",
    prior_history: tuple[str, ...] | None = ("maize",),
    current_practice: CurrentPractice | None = None,
    sequence_evidence_status: str = "locally_validated",
) -> RotationGenerationRequest:
    """Build a synthetic request without asserting real farm or agronomic facts."""

    return RotationGenerationRequest(
        planting_events=(
            make_event(
                event_id="event-1",
                order=1,
                start=date(2024, 1, 1),
                end=date(2024, 1, 31),
                calendar_status=calendar_status,
            ),
            make_event(
                event_id="event-2",
                order=2,
                start=date(2024, 2, 1),
                end=date(2024, 2, 29),
                calendar_status=calendar_status,
            ),
            make_event(
                event_id="event-3",
                order=3,
                start=date(2024, 3, 1),
                end=date(2024, 3, 31),
                calendar_status=calendar_status,
            ),
        ),
        candidate_crops=candidate_crops,
        sequence_evidence_status=sequence_evidence_status,  # type: ignore[arg-type]
        sequence_evidence_source=(
            "synthetic test fixture" if sequence_evidence_status == "locally_validated" else None
        ),
        prior_crop_history=prior_history,
        prior_history_source="synthetic test fixture" if prior_history is not None else None,
        current_practice=current_practice,
    )


def make_validated_test_crop(crop_id: str) -> CropCandidate:
    """A synthetic, fully reviewed crop record used only to test readiness logic."""

    return CropCandidate(
        crop_id=crop_id,
        display_name=crop_id.title(),
        suitability_status="locally_validated",
        evidence_references=("synthetic test fixture",),
    )


def test_generation_is_deterministic_and_enumerates_all_candidate_combinations() -> None:
    request = make_request()

    first = generate_rotation_candidates(request)
    second = generate_rotation_candidates(request)

    assert len(first.candidates) == 6**3
    assert [item.candidate_id for item in first.candidates] == [
        item.candidate_id for item in second.candidates
    ]
    assert first.model_dump() == second.model_dump()
    assert first.readiness == "needs_review"
    assert all(len(candidate.events) == 3 for candidate in first.candidates)
    assert all(candidate.readiness == "needs_review" for candidate in first.candidates)


def test_repeated_crops_are_reviewed_but_not_removed_as_a_blanket_rule() -> None:
    request = make_request(
        candidate_crops=tuple(
            make_validated_test_crop(crop_id) for crop_id in ("maize", "cowpea", "yam")
        )
    )

    result = generate_rotation_candidates(request)
    repeated = next(
        candidate
        for candidate in result.candidates
        if tuple(event.crop.crop_id for event in candidate.events) == ("maize", "maize", "maize")
    )
    distinct = next(
        candidate
        for candidate in result.candidates
        if tuple(event.crop.crop_id for event in candidate.events) == ("maize", "cowpea", "yam")
    )

    assert len(result.candidates) == 3**3
    assert repeated.readiness == "needs_review"
    assert any(finding.rule_id == "ROT-004" for finding in repeated.rule_findings)
    assert all(finding.rule_id != "ROT-004" for finding in distinct.rule_findings)
    assert distinct.readiness == "structurally_valid"


def test_provisional_calendar_and_unknown_history_require_review() -> None:
    result = generate_rotation_candidates(
        make_request(
            calendar_status="provisional",
            prior_history=None,
            sequence_evidence_status="unknown",
        )
    )

    candidate = result.candidates[0]
    findings = {finding.rule_id: finding for finding in candidate.rule_findings}
    assert result.readiness == "needs_review"
    assert findings["ROT-002"].outcome == "needs_review"
    assert findings["ROT-003"].outcome == "needs_review"
    assert findings["ROT-001"].outcome == "needs_review"
    assert "calendar-dependent hard constraints are not applied" in findings["ROT-003"].explanation


def test_known_current_practice_is_included_once_as_baseline() -> None:
    baseline = CurrentPractice(
        crop_ids=("maize", "cowpea", "maize"),
        source_reference="synthetic farmer-history fixture",
    )
    result = generate_rotation_candidates(make_request(current_practice=baseline))

    baseline_candidates = [
        candidate for candidate in result.candidates if candidate.kind == "baseline"
    ]
    assert len(baseline_candidates) == 1
    assert baseline_candidates[0].candidate_id == "baseline:maize|cowpea|maize"
    assert baseline_candidates[0].source_reference == "synthetic farmer-history fixture"
    assert (
        sum(
            tuple(event.crop.crop_id for event in candidate.events) == baseline.crop_ids
            for candidate in result.candidates
        )
        == 1
    )


def test_unknown_current_practice_does_not_create_a_fabricated_baseline() -> None:
    result = generate_rotation_candidates(make_request(current_practice=None))

    assert all(candidate.kind == "alternative" for candidate in result.candidates)
    assert not any(candidate.kind == "baseline" for candidate in result.candidates)


@pytest.mark.parametrize(
    "event_changes, message",
    [
        ({"order": 3}, "ordered consecutively"),
        ({"event_id": "event-1"}, "IDs must be unique"),
        ({"plot_id": "another-plot"}, "same plot"),
        ({"window_start": "2024-01-15"}, "non-overlapping"),
    ],
)
def test_invalid_event_contract_is_rejected_before_candidate_generation(
    event_changes: dict[str, str | int], message: str
) -> None:
    valid_request = make_request()
    events = list(valid_request.model_dump(mode="json")["planting_events"])
    events[1].update(event_changes)

    with pytest.raises(ValidationError, match=message):
        RotationGenerationRequest.model_validate(
            {**valid_request.model_dump(mode="json"), "planting_events": events}
        )


def test_generation_request_requires_exactly_three_events() -> None:
    valid_request = make_request()

    with pytest.raises(ValidationError, match="exactly three"):
        RotationGenerationRequest.model_validate(
            {
                **valid_request.model_dump(mode="json"),
                "planting_events": valid_request.planting_events[:2],
            }
        )
