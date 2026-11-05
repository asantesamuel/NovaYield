"""NY-39 source-aware catalog and farmer-history contract checks."""

from datetime import UTC, date, datetime

import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from app.farms.catalog_seed_data import (
    CROP_IDENTITY_SEEDS,
    GENERIC_STAGE_SEEDS,
    NAMED_PROFILE_SEEDS,
    REFERENCE_OPTION_SEEDS,
    REGIONAL_CALENDAR_SEEDS,
)
from app.farms.context_window import derive_context_period, subtract_twelve_calendar_months
from app.models.crop_catalog import CropCalendar, CropProfileRevision
from app.schemas.farms import FarmCreate


def _profile(events: list[dict[str, object]], **overrides: object) -> FarmCreate:
    fields: dict[str, object] = {
        "name": "Synthetic plot",
        "location_key": "ejura",
        "soil_texture_key": "unknown",
        "irrigation_access_key": "unknown",
        "history_status": "complete",
        "crop_history": events,
    }
    fields.update(overrides)
    return FarmCreate.model_validate(fields)


def _event(crop: str, order: int, start: str | None, end: str | None) -> dict[str, object]:
    return {"crop_key": crop, "sequence_order": order, "start_date": start, "end_date": end}


def test_one_event_uses_twelve_calendar_months_and_keeps_actual_dates() -> None:
    farm = _profile([_event("maize", 1, "2024-03-15", "2024-07-15")])
    period = derive_context_period(farm.crop_history)

    assert period.start_date == date(2023, 7, 15)
    assert period.end_date == date(2024, 7, 15)
    assert period.history_start == date(2024, 3, 15)
    assert farm.crop_history[0].start_date == date(2024, 3, 15)
    assert period.policy_version == "ny38-calendar-month-v1"


def test_three_events_preserve_longer_history_and_declared_gaps() -> None:
    events = [
        _event("maize", 1, "2023-03-01", "2023-07-31"),
        _event("cowpea", 2, "2023-08-02", "2023-11-30"),
        _event("maize", 3, "2023-12-02", "2024-05-15"),
    ]
    farm = _profile(
        events,
        declared_gaps=[
            {"start_date": "2023-08-01", "end_date": "2023-08-01", "status": "fallow"},
            {
                "start_date": "2023-12-01",
                "end_date": "2023-12-01",
                "status": "idle_unknown_management",
            },
        ],
    )
    period = derive_context_period(farm.crop_history)

    assert period.start_date == date(2023, 3, 1)
    assert period.end_date == date(2024, 5, 15)
    assert len(farm.crop_history) == 3
    assert farm.crop_history[2].crop_key == "maize"  # a repeated crop is still truthful


def test_leap_day_anniversary_clamps_and_never_uses_fixed_365_days() -> None:
    assert subtract_twelve_calendar_months(date(2024, 2, 29)) == date(2023, 2, 28)
    farm = _profile([_event("maize", 1, "2024-01-01", "2024-02-29")])
    assert derive_context_period(farm.crop_history).start_date == date(2023, 2, 28)


def test_unknown_dates_overlap_and_unexplained_gaps_stay_out_of_complete_path() -> None:
    with pytest.raises(ValidationError, match="needs start_date and end_date"):
        _profile([_event("maize", 1, None, "2024-07-15")])
    with pytest.raises(ValidationError, match="Overlapping crops"):
        _profile(
            [
                _event("maize", 1, "2024-03-01", "2024-06-01"),
                _event("cowpea", 2, "2024-05-01", "2024-08-01"),
            ]
        )
    with pytest.raises(ValidationError, match="Unexplained intervals"):
        _profile(
            [
                _event("maize", 1, "2024-03-01", "2024-06-01"),
                _event("cowpea", 2, "2024-07-01", "2024-08-01"),
            ]
        )
    draft = _profile(
        [
            _event("maize", 1, "2024-03-01", "2024-06-01"),
            _event("cowpea", 2, "2024-05-01", None),
        ],
        history_status="needs_review",
    )
    assert derive_context_period(draft.crop_history) is None


def test_invalid_order_future_date_and_legacy_free_text_are_rejected() -> None:
    with pytest.raises(ValidationError, match="sequence_order"):
        _profile([_event("maize", 2, "2024-03-01", "2024-06-01")])
    with pytest.raises(ValidationError, match="future"):
        _profile([_event("maize", 1, "2099-01-01", "2099-03-01")])
    with pytest.raises(ValidationError, match="Extra inputs"):
        _profile([_event("maize", 1, "2024-03-01", "2024-06-01")], current_practice="maize")


def test_one_catalog_has_six_candidates_and_sourced_history_only_choices() -> None:
    candidate_keys = {
        seed["crop_key"] for seed in CROP_IDENTITY_SEEDS if seed["recommendation_candidate"]
    }
    history_only = {
        seed["crop_key"]
        for seed in CROP_IDENTITY_SEEDS
        if seed["history_selectable"] and not seed["recommendation_candidate"]
    }
    assert candidate_keys == {"maize", "cowpea", "groundnut", "cassava", "yam", "rice"}
    assert history_only == {"plantain", "sorghum"}
    assert "beans" not in candidate_keys | history_only
    assert all(seed["identity_source_url"].startswith("https://") for seed in CROP_IDENTITY_SEEDS)


def test_seed_has_only_scoped_maturity_and_no_invented_numeric_traits_or_dates() -> None:
    assert all(seed["variety_key"] is not None for seed in NAMED_PROFILE_SEEDS)
    assert all(seed["min_days"] is None or seed["min_days"] > 0 for seed in NAMED_PROFILE_SEEDS)
    assert all(
        stage.start_offset_days is None and stage.duration_days is None
        for stages in GENERIC_STAGE_SEEDS.values()
        for stage in stages
    )
    assert all("source_note" in seed for seed in REGIONAL_CALENDAR_SEEDS)
    assert {seed["kind"] for seed in REFERENCE_OPTION_SEEDS} == {
        "soil_texture",
        "irrigation_access",
    }


def test_new_crop_and_calendar_revisions_require_explicit_publication() -> None:
    crop_id = PydanticObjectId()
    draft_profile = CropProfileRevision(crop_id=crop_id, revision=2)
    assert draft_profile.is_active is False
    with pytest.raises(ValidationError, match="publication time"):
        CropProfileRevision(crop_id=crop_id, revision=2, is_active=True)
    active_profile = CropProfileRevision(
        crop_id=crop_id,
        revision=2,
        is_active=True,
        published_at=datetime(2026, 11, 5, tzinfo=UTC),
        evidence_status="provisional",
    )
    assert active_profile.reviewer_ref is None  # desk publication is not local review

    fields = dict(
        crop_id=crop_id,
        location_key="ejura",
        season_key="major-rainy-season",
        calendar_version="research-v2",
    )
    assert CropCalendar(**fields).is_active is False
    with pytest.raises(ValidationError, match="publication time"):
        CropCalendar(**fields, is_active=True)
    assert (
        CropCalendar(
            **fields,
            is_active=True,
            published_at=datetime(2026, 11, 5, tzinfo=UTC),
            status="provisional",
        ).status
        == "provisional"
    )
