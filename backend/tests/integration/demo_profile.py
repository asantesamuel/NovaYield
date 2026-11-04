"""Fixed, synthetic NY-10 API profile used only by integration tests.

This is intentionally not a real farm, a local agronomic finding, or a public demo
recommendation. Past crops and environmental responses are invented test inputs
used to verify contracts, persistence, cache reuse, and result serialization.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

PROFILE_ID = "ny10-synthetic-workflow-v1"
PROFILE_STATUS = "synthetic-test-data-only"

SYNTHETIC_PASSWORD = "ny10-test-only-not-a-real-account-password"

FARM_REQUEST: dict[str, Any] = {
    "name": "NY-10 synthetic test farm",
    "location_key": "ejura",
}

PAST_SEASONS: tuple[dict[str, Any], ...] = (
    {
        "season_label": "synthetic-past-season-1",
        "analysis_start_date": "2022-04-01",
        "analysis_end_date": "2022-04-03",
        "planted_crop": "maize",
    },
    {
        "season_label": "synthetic-past-season-2",
        "analysis_start_date": "2022-09-01",
        "analysis_end_date": "2022-09-03",
        "planted_crop": "cowpea",
    },
    {
        "season_label": "synthetic-past-season-3",
        "analysis_start_date": "2023-04-01",
        "analysis_end_date": "2023-04-03",
        "planted_crop": "maize",
    },
)


def recommendation_request(*, today: date | None = None) -> dict[str, Any]:
    """Build one stable request; only future slots move to remain valid over time.

    The three past analysis windows and reported crops are fixed. Future dates are
    generated relative to UTC today because the API correctly rejects past
    recommendation slots. These synthetic slots do not represent a Ghana crop
    calendar or planting advice.
    """

    current_day = today or datetime.now(UTC).date()
    first_start = current_day + timedelta(days=30)
    future_slots = []
    for order in range(3):
        window_start = first_start + timedelta(days=30 * order)
        window_end = window_start + timedelta(days=6)
        future_slots.append(
            {
                "season_label": f"synthetic-future-slot-{order + 1}",
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            }
        )

    return {
        "plot_reference": "synthetic-test-plot",
        "historical_seasons": [dict(season) for season in PAST_SEASONS],
        "recommendation_seasons": future_slots,
    }
