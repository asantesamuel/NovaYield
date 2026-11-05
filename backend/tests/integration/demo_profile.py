"""Fixed synthetic Farm v2 inputs for the isolated NY-10 integration suite.

The crop dates, declared gaps, and mocked weather are test data only. They are
not an Ejura farm observation, validated calendar, or recommendation.
"""

from __future__ import annotations

import secrets
from typing import Any

PROFILE_ID = "ny10-synthetic-farm-v2"
PROFILE_STATUS = "synthetic-test-data-only"

# Generated at test-process startup; no reusable password is committed.
SYNTHETIC_PASSWORD = f"Ny10-{secrets.token_hex(16)}!"

HISTORY_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "crop_key": "maize",
        "sequence_order": 1,
        "start_date": "2022-04-01",
        "end_date": "2022-07-15",
    },
    {
        "crop_key": "cowpea",
        "sequence_order": 2,
        "start_date": "2022-09-01",
        "end_date": "2022-11-15",
    },
    {
        "crop_key": "maize",
        "sequence_order": 3,
        "start_date": "2023-04-01",
        "end_date": "2023-07-15",
    },
)

DECLARED_GAPS: tuple[dict[str, str], ...] = (
    {"start_date": "2022-07-16", "end_date": "2022-08-31", "status": "fallow"},
    {"start_date": "2022-11-16", "end_date": "2023-03-31", "status": "fallow"},
)

# The historical POWER period is derived server-side as 2022-04-01–2023-07-15:
# it spans every event and more than twelve calendar months before the last end.
CONTEXT_START = "2022-04-01"
CONTEXT_END = "2023-07-15"
CONTEXT_POWER_WINDOW = ("20220401", "20230715")

FARM_REQUEST: dict[str, Any] = {
    "name": "Ejura synthetic demonstration plot",
    "location_key": "ejura",
    "soil_texture_key": "loamy",
    "irrigation_access_key": "none",
    "history_status": "complete",
    "crop_history": [dict(item) for item in HISTORY_EVENTS],
    "declared_gaps": [dict(item) for item in DECLARED_GAPS],
    "current_plot_available": True,
    "earliest_available_date": "2023-07-16",
}


def recommendation_request(*, prioritize_water: bool = False) -> dict[str, Any]:
    """Only an optional priority override is accepted; dates come from the Farm."""

    if not prioritize_water:
        return {}
    return {
        "priority_adjustment": {
            "water_resilience": 70,
            "soil_health_potential": 10,
            "yield_stability_proxy": 10,
            "labor_feasibility": 10,
        }
    }
