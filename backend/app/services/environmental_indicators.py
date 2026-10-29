"""Adapt NY-6 snapshot retrievals into NY-7 indicator results."""

from __future__ import annotations

from app.indicators.environmental import (
    EnvironmentalIndicator,
    calculate_environmental_indicators,
    unavailable_environmental_indicators,
)
from app.integrations.nasa.power import PowerRequest
from app.models.environmental_snapshots import SnapshotSeasonContext
from app.services.environmental_snapshots import SnapshotRetrieval


class EnvironmentalIndicatorService:
    """Coordinate persisted snapshot use and pure indicator calculation.

    The caller must provide the same validated request that produced the NY-6
    retrieval. This service performs no database or NASA I/O.
    """

    def calculate(
        self,
        retrieval: SnapshotRetrieval,
        request: PowerRequest,
    ) -> tuple[EnvironmentalIndicator, ...]:
        """Calculate indicators while preserving request and retrieval provenance."""

        season_context = SnapshotSeasonContext(
            season_label=request.season_label,
            calendar_source_version=request.calendar_source_version,
            crop=request.crop,
        )
        snapshot = retrieval.snapshot

        if snapshot is None:
            return unavailable_environmental_indicators(
                request.start_date,
                request.end_date,
                season_context=season_context,
                warnings=retrieval.warnings,
            )

        if (
            snapshot.identity.start_date != request.start_date
            or snapshot.identity.end_date != request.end_date
        ):
            raise ValueError("PowerRequest dates do not match the retrieved snapshot identity")

        indicators = calculate_environmental_indicators(
            snapshot,
            data_status=retrieval.data_status,
            season_context=season_context,
        )
        if not retrieval.warnings:
            return indicators

        return tuple(
            indicator.model_copy(update={"warnings": (*indicator.warnings, *retrieval.warnings)})
            for indicator in indicators
        )
