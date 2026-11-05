"""Pure NY-40 scheduling of three crop-specific future planting events.

The caller supplies the plot's confirmed availability and versioned crop
calendar/maturity evidence. An absent or conflicting value never becomes a
generic season slot or an invented planting day. Results describe windows and
uncertain harvest bounds, not a forecast of the farmer's actual dates.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FUTURE_CALENDAR_METHOD_VERSION = "ny40-three-event-calendar-v1"
MAX_CALENDAR_LOOKAHEAD_YEARS = 10  # Computational guard, not an agronomic claim.

EvidenceStatus = Literal["unknown", "provisional", "locally_reviewed", "conflicted"]
EventStatus = Literal["provisional", "locally_reviewed", "needs_review"]


class CropEventScope(BaseModel):
    """The exact crop/variety/system scope to place on one plot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    crop_id: str = Field(min_length=1)
    variety_key: str | None = None
    production_system_key: str | None = None


class CropCalendarSpec(BaseModel):
    """A caller-resolved active calendar and matching profile maturity range.

    ``start_month_day`` and ``end_month_day`` are inclusive recurring MM-DD
    bounds. Duration is sourced planting-to-harvest days. The source fields
    are required before this record can yield an asserted future window.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    location_key: str = Field(min_length=1)
    crop_id: str = Field(min_length=1)
    variety_key: str | None = None
    production_system_key: str | None = None
    season_key: str = Field(min_length=1)
    start_month_day: str | None = None
    end_month_day: str | None = None
    crosses_year: bool | None = None
    valid_from_year: int | None = None
    valid_to_year: int | None = None
    calendar_version_id: str | None = None
    profile_revision_id: str | None = None
    calendar_source: str | None = None
    maturity_source: str | None = None
    calendar_status: EvidenceStatus = "unknown"
    maturity_status: EvidenceStatus = "unknown"
    maturity_basis: Literal["planting_to_harvest", "other", "unknown"] = "unknown"
    maturity_min_days: int | None = None
    maturity_max_days: int | None = None


class FuturePlantingEvent(BaseModel):
    """One ordered event, with dates only when evidence supports them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    order: int = Field(ge=1, le=3)
    plot_id: str
    crop: CropEventScope
    status: EventStatus
    reason: str | None = None
    season_key: str | None = None
    planting_window_start: date | None = None
    planting_window_end: date | None = None
    earliest_harvest_date: date | None = None
    latest_harvest_date: date | None = None
    maturity_min_days: int | None = None
    maturity_max_days: int | None = None
    calendar_version_id: str | None = None
    profile_revision_id: str | None = None
    calendar_source: str | None = None
    maturity_source: str | None = None
    calendar_status: EvidenceStatus = "unknown"
    maturity_status: EvidenceStatus = "unknown"
    maturity_basis: Literal["planting_to_harvest", "other", "unknown"] = "unknown"
    limitations: tuple[str, ...] = ()


class FutureRotationSchedule(BaseModel):
    """One-plot three-event schedule; ``needs_review`` blocks dated claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method_version: str = FUTURE_CALENDAR_METHOD_VERSION
    status: EventStatus
    location_key: str
    plot_id: str
    as_of_date: date
    confirmed_available_from: date | None
    availability_source: str | None
    events: tuple[FuturePlantingEvent, FuturePlantingEvent, FuturePlantingEvent]
    interpretation: str = (
        "Sourced crop-specific future planting windows and possible harvest dates; "
        "source status is disclosed and dates are not a weather or yield prediction."
    )


def _month_day(value: str | None) -> tuple[int, int] | None:
    if (
        value is None
        or len(value) != 5
        or value[2] != "-"
        or not value[:2].isdigit()
        or not value[3:].isdigit()
    ):
        return None
    try:
        month, day = int(value[:2]), int(value[3:])
        date(2000, month, day)  # Leap template validates Feb 29 without normalizing it.
    except ValueError:
        return None
    return month, day


def _calendar_issue(calendar: CropCalendarSpec) -> str | None:
    if calendar.calendar_status in {"unknown", "conflicted"}:
        return "calendar_evidence_unresolved"
    if calendar.maturity_status in {"unknown", "conflicted"}:
        return "maturity_evidence_unresolved"
    if calendar.maturity_basis != "planting_to_harvest":
        return "planting_to_harvest_basis_unverified"
    if not all(
        (
            calendar.calendar_version_id,
            calendar.profile_revision_id,
            calendar.calendar_source,
            calendar.maturity_source,
        )
    ):
        return "calendar_or_maturity_provenance_missing"
    start, end = _month_day(calendar.start_month_day), _month_day(calendar.end_month_day)
    if start is None or end is None or calendar.crosses_year is None:
        return "planting_window_missing_or_invalid"
    if calendar.crosses_year != (end < start):
        return "cross_year_calendar_flag_inconsistent"
    # A Feb-29 boundary or a window spanning that day lacks an approved
    # recurrence/alignment rule for non-leap years.
    contains_feb29 = (
        start <= (2, 29) <= end if not calendar.crosses_year else start <= (2, 29) or (2, 29) <= end
    )
    if contains_feb29:
        return "leap_day_calendar_alignment_unresolved"
    if (
        calendar.valid_from_year is not None
        and calendar.valid_to_year is not None
        and calendar.valid_to_year < calendar.valid_from_year
    ):
        return "calendar_valid_year_range_invalid"
    minimum, maximum = calendar.maturity_min_days, calendar.maturity_max_days
    if minimum is None or maximum is None:
        return "maturity_timing_missing"
    if minimum < 1 or maximum < minimum:
        return "maturity_timing_invalid"
    return None


def _next_occurrence(
    calendar: CropCalendarSpec,
    available_from: date,
) -> tuple[date, date] | None:
    start_md, end_md = _month_day(calendar.start_month_day), _month_day(calendar.end_month_day)
    assert start_md is not None and end_md is not None
    assert calendar.crosses_year is not None
    for year in range(
        available_from.year - int(calendar.crosses_year),
        available_from.year + MAX_CALENDAR_LOOKAHEAD_YEARS + 1,
    ):
        if calendar.valid_from_year is not None and year < calendar.valid_from_year:
            continue
        if calendar.valid_to_year is not None and year > calendar.valid_to_year:
            continue
        try:
            start = date(year, *start_md)
            end = date(year + int(calendar.crosses_year), *end_md)
        except ValueError:
            continue  # A source with a Feb-29 boundary was withheld above.
        if end < available_from:
            continue
        feasible_start = max(start, available_from)
        if feasible_start <= end:
            return feasible_start, end
    return None


def _review_event(
    order: int,
    plot_id: str,
    crop: CropEventScope,
    reason: str,
) -> FuturePlantingEvent:
    return FuturePlantingEvent(
        event_id=f"future-{order}",
        order=order,
        plot_id=plot_id,
        crop=crop,
        status="needs_review",
        reason=reason,
    )


def derive_three_event_windows(
    crops: Sequence[CropEventScope],
    calendars: Sequence[CropCalendarSpec],
    *,
    location_key: str,
    plot_id: str,
    as_of_date: date,
    earliest_available_date: date | None,
    availability_source: str | None,
) -> FutureRotationSchedule:
    """Place three crops sequentially, never overlapping a possible harvest.

    ``as_of_date`` is explicit to keep the calculation deterministic. The
    farmer-confirmed availability date and its source must also be explicit;
    callers must not derive either from a generic season label. A later crop
    starts no earlier than the preceding crop's *latest* possible harvest +1.
    """

    if len(crops) != 3:
        raise ValueError("Exactly three ordered crop scopes are required")
    if not location_key or not plot_id:
        raise ValueError("Location and plot identity are required")

    events: list[FuturePlantingEvent] = []
    if earliest_available_date is None or not availability_source:
        events = [
            _review_event(i, plot_id, crop, "plot_availability_unconfirmed")
            for i, crop in enumerate(crops, 1)
        ]
    else:
        next_available = max(as_of_date, earliest_available_date)
        prior_unresolved = False
        for order, crop in enumerate(crops, 1):
            if prior_unresolved:
                events.append(
                    _review_event(order, plot_id, crop, "prior_event_schedule_unresolved")
                )
                continue
            scoped = [
                calendar
                for calendar in calendars
                if calendar.location_key == location_key
                and calendar.crop_id == crop.crop_id
                and calendar.variety_key == crop.variety_key
                and calendar.production_system_key == crop.production_system_key
            ]
            if not scoped:
                events.append(_review_event(order, plot_id, crop, "scoped_crop_calendar_missing"))
                prior_unresolved = True
                continue

            if any(
                calendar.calendar_status == "conflicted" or calendar.maturity_status == "conflicted"
                for calendar in scoped
            ):
                events.append(_review_event(order, plot_id, crop, "conflicting_scoped_evidence"))
                prior_unresolved = True
                continue

            viable: list[tuple[date, date, CropCalendarSpec]] = []
            issues: list[str] = []
            for calendar in scoped:
                issue = _calendar_issue(calendar)
                if issue:
                    issues.append(issue)
                    continue
                occurrence = _next_occurrence(calendar, next_available)
                if occurrence is not None:
                    viable.append((*occurrence, calendar))
            if not viable:
                reason = (
                    "calendar_or_maturity_evidence_unresolved"
                    if issues
                    else "no_sourced_future_window"
                )
                events.append(_review_event(order, plot_id, crop, reason))
                prior_unresolved = True
                continue

            viable.sort(key=lambda entry: (entry[0], entry[1], entry[2].calendar_version_id or ""))
            earliest_start = viable[0][0]
            same_start = [entry for entry in viable if entry[0] == earliest_start]
            if len(same_start) > 1:
                events.append(
                    _review_event(order, plot_id, crop, "competing_calendar_windows_need_review")
                )
                prior_unresolved = True
                continue

            start, end, calendar = viable[0]
            assert calendar.maturity_min_days is not None
            assert calendar.maturity_max_days is not None
            try:
                earliest_harvest = start + timedelta(days=calendar.maturity_min_days - 1)
                latest_harvest = end + timedelta(days=calendar.maturity_max_days - 1)
            except OverflowError:
                events.append(_review_event(order, plot_id, crop, "harvest_date_out_of_range"))
                prior_unresolved = True
                continue
            limitations = (
                ("calendar_source_validity_end_unspecified",)
                if calendar.valid_to_year is None
                else ()
            )
            status: EventStatus = (
                "locally_reviewed"
                if calendar.calendar_status == calendar.maturity_status == "locally_reviewed"
                else "provisional"
            )
            events.append(
                FuturePlantingEvent(
                    event_id=f"future-{order}",
                    order=order,
                    plot_id=plot_id,
                    crop=crop,
                    status=status,
                    season_key=calendar.season_key,
                    planting_window_start=start,
                    planting_window_end=end,
                    earliest_harvest_date=earliest_harvest,
                    latest_harvest_date=latest_harvest,
                    maturity_min_days=calendar.maturity_min_days,
                    maturity_max_days=calendar.maturity_max_days,
                    calendar_version_id=calendar.calendar_version_id,
                    profile_revision_id=calendar.profile_revision_id,
                    calendar_source=calendar.calendar_source,
                    maturity_source=calendar.maturity_source,
                    calendar_status=calendar.calendar_status,
                    maturity_status=calendar.maturity_status,
                    maturity_basis=calendar.maturity_basis,
                    limitations=limitations,
                )
            )
            if order < 3:
                try:
                    next_available = latest_harvest + timedelta(days=1)
                except OverflowError:
                    prior_unresolved = True

    assert len(events) == 3
    overall: EventStatus = (
        "needs_review"
        if any(event.status == "needs_review" for event in events)
        else "provisional"
        if any(event.status == "provisional" for event in events)
        else "locally_reviewed"
    )
    return FutureRotationSchedule(
        status=overall,
        location_key=location_key,
        plot_id=plot_id,
        as_of_date=as_of_date,
        confirmed_available_from=earliest_available_date,
        availability_source=availability_source,
        events=(events[0], events[1], events[2]),
    )
