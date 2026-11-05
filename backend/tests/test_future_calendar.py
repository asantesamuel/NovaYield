"""Synthetic, source-labeled tests for three crop-specific future windows."""

from __future__ import annotations

from datetime import date

from app.decisions.future_calendar import (
    CropCalendarSpec,
    CropEventScope,
    derive_three_event_windows,
)

CROPS = (
    CropEventScope(crop_id="maize", variety_key="synthetic-a", production_system_key="rainfed"),
    CropEventScope(crop_id="cowpea", variety_key="synthetic-b", production_system_key="rainfed"),
    CropEventScope(crop_id="groundnut", variety_key="synthetic-c", production_system_key="rainfed"),
)


def _calendar(
    crop: CropEventScope,
    start: str,
    end: str,
    maturity: tuple[int, int],
    **changes: object,
) -> CropCalendarSpec:
    base = CropCalendarSpec(
        location_key="synthetic-pilot",
        crop_id=crop.crop_id,
        variety_key=crop.variety_key,
        production_system_key=crop.production_system_key,
        season_key="synthetic-season",
        start_month_day=start,
        end_month_day=end,
        crosses_year=False,
        calendar_version_id=f"{crop.crop_id}-calendar-v1",
        profile_revision_id=f"{crop.crop_id}-profile-v1",
        calendar_source="synthetic-reviewed-calendar-fixture",
        maturity_source="synthetic-reviewed-maturity-fixture",
        calendar_status="provisional",
        maturity_status="provisional",
        maturity_basis="planting_to_harvest",
        maturity_min_days=maturity[0],
        maturity_max_days=maturity[1],
    )
    return base.model_copy(update=changes)


def _derive(calendars: list[CropCalendarSpec], **changes: object):
    arguments = dict(
        location_key="synthetic-pilot",
        plot_id="synthetic-plot",
        as_of_date=date(2027, 1, 1),
        earliest_available_date=date(2027, 1, 1),
        availability_source="synthetic-confirmed-farmer-history",
    )
    arguments.update(changes)
    return derive_three_event_windows(CROPS, calendars, **arguments)


def test_three_sourced_crop_windows_do_not_overlap_possible_harvest() -> None:
    calendars = [
        _calendar(CROPS[0], "03-01", "03-10", (100, 110)),
        _calendar(CROPS[1], "07-01", "07-10", (60, 70)),
        _calendar(CROPS[2], "10-01", "10-10", (85, 95)),
    ]

    schedule = _derive(calendars)

    assert schedule.status == "provisional"
    assert [event.crop.crop_id for event in schedule.events] == ["maize", "cowpea", "groundnut"]
    assert schedule.events[0].planting_window_start == date(2027, 3, 1)
    assert schedule.events[0].planting_window_end == date(2027, 3, 10)
    assert schedule.events[1].planting_window_start == date(2027, 7, 1)
    assert schedule.events[2].planting_window_start == date(2027, 10, 1)
    for preceding, following in zip(schedule.events, schedule.events[1:], strict=False):
        assert preceding.latest_harvest_date is not None
        assert following.planting_window_start is not None
        assert preceding.latest_harvest_date < following.planting_window_start
    assert _derive(calendars) == schedule
    assert all(event.calendar_source and event.maturity_source for event in schedule.events)


def test_availability_inside_window_shortens_possible_planting_range() -> None:
    calendars = [
        _calendar(CROPS[0], "03-01", "03-10", (100, 110)),
        _calendar(CROPS[1], "07-01", "07-10", (60, 70)),
        _calendar(CROPS[2], "10-01", "10-10", (85, 95)),
    ]
    schedule = _derive(calendars, earliest_available_date=date(2027, 3, 5))
    assert schedule.events[0].planting_window_start == date(2027, 3, 5)
    assert schedule.events[0].planting_window_end == date(2027, 3, 10)


def test_missing_maturity_or_unconfirmed_plot_avoids_invented_dates() -> None:
    calendars = [
        _calendar(CROPS[0], "03-01", "03-10", (100, 110), maturity_min_days=None),
        _calendar(CROPS[1], "07-01", "07-10", (60, 70)),
        _calendar(CROPS[2], "10-01", "10-10", (85, 95)),
    ]
    schedule = _derive(calendars)
    assert schedule.status == "needs_review"
    assert [event.reason for event in schedule.events] == [
        "calendar_or_maturity_evidence_unresolved",
        "prior_event_schedule_unresolved",
        "prior_event_schedule_unresolved",
    ]
    assert all(event.planting_window_start is None for event in schedule.events)

    unconfirmed = _derive(calendars, earliest_available_date=None)
    assert all(event.reason == "plot_availability_unconfirmed" for event in unconfirmed.events)

    maturity_endpoint_unknown = _calendar(
        CROPS[0], "03-01", "03-10", (100, 110), maturity_basis="unknown"
    )
    schedule = _derive([maturity_endpoint_unknown])
    assert schedule.events[0].status == "needs_review"
    assert schedule.events[0].planting_window_start is None


def test_competing_same_start_calendars_require_review() -> None:
    first = _calendar(CROPS[0], "03-01", "03-10", (100, 110))
    alternative = first.model_copy(
        update={"calendar_version_id": "other-source-v2", "end_month_day": "03-15"}
    )
    schedule = _derive([first, alternative])
    assert schedule.events[0].reason == "competing_calendar_windows_need_review"
    assert schedule.events[0].planting_window_start is None


def test_expired_calendar_or_leap_boundary_has_no_claimed_future_date() -> None:
    expired = _calendar(CROPS[0], "03-01", "03-10", (100, 110), valid_to_year=2026)
    schedule = _derive([expired])
    assert schedule.events[0].reason == "no_sourced_future_window"

    leap = _calendar(CROPS[0], "02-29", "03-10", (100, 110))
    schedule = _derive([leap])
    assert schedule.events[0].reason == "calendar_or_maturity_evidence_unresolved"

    leap_span = _calendar(CROPS[0], "02-15", "03-10", (100, 110))
    schedule = _derive([leap_span])
    assert schedule.events[0].planting_window_start is None

    conflicted = _calendar(CROPS[0], "03-01", "03-10", (100, 110), calendar_status="conflicted")
    schedule = _derive([conflicted, _calendar(CROPS[0], "04-01", "04-10", (100, 110))])
    assert schedule.events[0].reason == "conflicting_scoped_evidence"


def test_late_harvest_skips_earlier_next_crop_window() -> None:
    calendars = [
        _calendar(CROPS[0], "03-01", "03-10", (200, 220)),
        _calendar(CROPS[1], "07-01", "07-10", (60, 70)),
        _calendar(CROPS[2], "10-01", "10-10", (85, 95)),
    ]
    schedule = _derive(calendars)
    assert schedule.events[0].latest_harvest_date is not None
    assert schedule.events[1].planting_window_start == date(2028, 7, 1)
    assert schedule.events[0].latest_harvest_date < schedule.events[1].planting_window_start


def test_cross_year_calendar_can_be_dated_but_unscoped_generic_crop_cannot() -> None:
    cross_year = _calendar(CROPS[0], "12-01", "01-15", (50, 60), crosses_year=True)
    schedule = _derive([cross_year])
    # The December 2026–January 2027 occurrence is still open on Jan 1.
    assert schedule.events[0].planting_window_start == date(2027, 1, 1)
    assert schedule.events[0].planting_window_end == date(2027, 1, 15)
    assert schedule.events[0].status == "provisional"

    generic = cross_year.model_copy(update={"variety_key": None})
    schedule = _derive([generic])
    assert schedule.events[0].reason == "scoped_crop_calendar_missing"
