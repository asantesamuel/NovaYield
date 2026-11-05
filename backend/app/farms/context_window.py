"""Pure NY-38 historical-context derivation from actual farmer event dates."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Sequence
from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict

CONTEXT_PERIOD_POLICY_VERSION = "ny38-calendar-month-v1"


class DatedEvent(Protocol):
    start_date: date | None
    end_date: date | None


class DerivedContextPeriod(BaseModel):
    """Inclusive POWER query bounds; the farmer's original dates stay unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date
    end_date: date
    history_start: date
    history_end: date
    policy_version: str = CONTEXT_PERIOD_POLICY_VERSION


def subtract_twelve_calendar_months(value: date) -> date:
    """Keep month/day, clamping 29 February to 28 February in non-leap years."""

    previous_year = value.year - 1
    if previous_year < 1:
        raise ValueError("Context date is outside supported calendar bounds")
    last_day = monthrange(previous_year, value.month)[1]
    return date(previous_year, value.month, min(value.day, last_day))


def derive_context_period(events: Sequence[DatedEvent]) -> DerivedContextPeriod | None:
    """Span every complete event and at least twelve calendar months before the last end.

    A missing date produces no context. Validation of chronology, event count and
    overlap is a separate farm-history responsibility; this function never fills
    a missing farmer date or shifts the reported harvest/end date.
    """

    if not events or any(event.start_date is None or event.end_date is None for event in events):
        return None
    starts = [event.start_date for event in events if event.start_date is not None]
    ends = [event.end_date for event in events if event.end_date is not None]
    history_start = min(starts)
    history_end = max(ends)
    if history_start > history_end:
        raise ValueError("Historical events have invalid date coverage")
    return DerivedContextPeriod(
        start_date=min(history_start, subtract_twelve_calendar_months(history_end)),
        end_date=history_end,
        history_start=history_start,
        history_end=history_end,
    )
