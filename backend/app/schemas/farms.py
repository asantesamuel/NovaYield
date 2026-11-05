"""Farm v2 request/response contract with explicit legacy and evidence status."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decisions.scoring import PriorityPoints
from app.farms.context_window import DerivedContextPeriod
from app.farms.contracts import CropKey, FarmName, FarmText, LocationKey

if TYPE_CHECKING:
    from app.models.crop_catalog import Crop
    from app.models.farm_reference_options import FarmReferenceOption
    from app.models.farms import Farm
    from app.models.supported_locations import SupportedLocation


class CropHistoryEventInput(BaseModel):
    """Farmer reports a selected identity and actual inclusive plot-occupancy dates."""

    model_config = ConfigDict(extra="forbid")

    crop_key: CropKey
    sequence_order: int = Field(ge=1, le=3)
    start_date: date | None = None
    end_date: date | None = None
    variety_key: CropKey | None = None
    production_system_key: CropKey | None = None


class HistoryGapInput(BaseModel):
    """A farmer can report an interval but cannot self-certify extension review."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    status: Literal["fallow", "idle_unknown_management", "unknown"]
    source: Literal["farmer_reported"] = "farmer_reported"


class HistoryGapResponse(BaseModel):
    """Preserve any later extension verification source without exposing reviewer PII."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    status: Literal["fallow", "idle_unknown_management", "unknown"]
    source: Literal["farmer_reported", "extension_verified"]


class FarmCreate(BaseModel):
    """New farm input; owner, coordinates, NASA dates and baseline are server-owned."""

    model_config = ConfigDict(extra="forbid")

    name: FarmName
    location_key: LocationKey
    soil_texture_key: CropKey
    irrigation_access_key: CropKey
    history_status: Literal["complete", "needs_review", "unknown"]
    crop_history: list[CropHistoryEventInput] = Field(default_factory=list, max_length=3)
    declared_gaps: list[HistoryGapInput] = Field(default_factory=list)
    current_plot_available: bool | None = None
    earliest_available_date: date | None = None
    farmer_priorities: PriorityPoints | None = None

    @model_validator(mode="after")
    def valid_history(self) -> FarmCreate:
        validate_farm_history(
            status=self.history_status,
            events=self.crop_history,
            gaps=self.declared_gaps,
            current_plot_available=self.current_plot_available,
            earliest_available_date=self.earliest_available_date,
        )
        return self


class FarmUpdate(BaseModel):
    """Partial owner-scoped update; history replacement is validated as a whole."""

    model_config = ConfigDict(extra="forbid")

    name: FarmName | None = None
    location_key: LocationKey | None = None
    soil_texture_key: CropKey | None = None
    irrigation_access_key: CropKey | None = None
    history_status: Literal["complete", "needs_review", "unknown"] | None = None
    crop_history: list[CropHistoryEventInput] | None = Field(default=None, max_length=3)
    declared_gaps: list[HistoryGapInput] | None = None
    current_plot_available: bool | None = None
    earliest_available_date: date | None = None
    farmer_priorities: PriorityPoints | None = None

    @model_validator(mode="after")
    def require_mutable_fields(self) -> FarmUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one farm field must be supplied")
        for field_name in (
            "name",
            "location_key",
            "soil_texture_key",
            "irrigation_access_key",
            "history_status",
        ):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be cleared")
        return self


def validate_farm_history(
    *,
    status: str,
    events: list[CropHistoryEventInput],
    gaps: list[HistoryGapInput],
    current_plot_available: bool | None,
    earliest_available_date: date | None,
    as_of_date: date | None = None,
) -> None:
    """Validate the one-plot sequence without filling unknown dates or fallow."""

    today = as_of_date or date.today()
    if len(events) > 3:
        raise ValueError("At most three past crop events can be supplied")
    if status == "complete" and not 1 <= len(events) <= 3:
        raise ValueError("A complete history needs one to three dated crop events")
    if status == "unknown" and (events or gaps):
        raise ValueError("An unknown history cannot assert crop events or gaps")
    if [event.sequence_order for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("Crop sequence_order must be 1 through the event count, oldest first")
    for event in events:
        if status == "complete" and (event.start_date is None or event.end_date is None):
            raise ValueError("Each complete crop event needs start_date and end_date")
        if event.start_date is not None and event.start_date > today:
            raise ValueError("Past crop start_date cannot be in the future")
        if event.end_date is not None and event.end_date > today:
            raise ValueError("Past crop end_date cannot be in the future")
        if (
            event.start_date is not None
            and event.end_date is not None
            and event.end_date < event.start_date
        ):
            raise ValueError("Crop end_date cannot precede start_date")

    for previous, current in zip(events, events[1:], strict=False):
        if (
            previous.start_date is not None
            and current.start_date is not None
            and (
                current.start_date < previous.start_date
                or (status == "complete" and current.start_date == previous.start_date)
            )
        ):
            raise ValueError("Crop event dates must agree with oldest-first sequence_order")
        if (
            status == "complete"
            and previous.end_date is not None
            and current.start_date is not None
            and current.start_date <= previous.end_date
        ):
            raise ValueError(
                "Overlapping crops require needs_review; sole-crop order is unsupported"
            )

    for gap in gaps:
        if gap.start_date > gap.end_date:
            raise ValueError("Declared gap end_date cannot precede start_date")
        if gap.end_date > today:
            raise ValueError("Declared gap cannot end in the future")
    if gaps and len(events) < 2:
        raise ValueError("A declared gap must lie between two reported crop events")
    if gaps and any(event.start_date is None or event.end_date is None for event in events):
        raise ValueError("Resolve event dates before recording exact gap dates")

    ordered_gaps = sorted(gaps, key=lambda item: item.start_date)
    for previous, current in zip(ordered_gaps, ordered_gaps[1:], strict=False):
        if current.start_date <= previous.end_date:
            raise ValueError("Declared gaps must not overlap")

    intervals: list[tuple[date, date]] = []
    for previous, current in zip(events, events[1:], strict=False):
        if previous.end_date is None or current.start_date is None:
            continue
        if current.start_date > previous.end_date + timedelta(days=1):
            intervals.append(
                (previous.end_date + timedelta(days=1), current.start_date - timedelta(days=1))
            )
    for gap in ordered_gaps:
        if not any(start <= gap.start_date <= gap.end_date <= end for start, end in intervals):
            raise ValueError("Declared gaps must lie within actual intervals between crops")

    if status == "complete":
        for start, end in intervals:
            matching = [
                gap for gap in ordered_gaps if start <= gap.start_date <= gap.end_date <= end
            ]
            if not matching or matching[0].start_date != start or matching[-1].end_date != end:
                raise ValueError("Unexplained intervals require needs_review or declared gaps")
            if any(gap.status == "unknown" for gap in matching):
                raise ValueError("Unknown interval status requires needs_review")
            for left, right in zip(matching, matching[1:], strict=False):
                if right.start_date != left.end_date + timedelta(days=1):
                    raise ValueError("Unexplained intervals require needs_review or declared gaps")

    if current_plot_available is None and earliest_available_date is not None:
        raise ValueError("Plot availability must be reported before an available date")
    if current_plot_available is True and earliest_available_date is None:
        raise ValueError("An available plot needs an explicit earliest_available_date")
    dated_ends = [event.end_date for event in events if event.end_date is not None]
    if (
        earliest_available_date is not None
        and dated_ends
        and earliest_available_date < max(dated_ends)
    ):
        raise ValueError("Plot cannot become available before the reported last crop end")


class SupportedLocationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_key: LocationKey
    label: FarmText

    @classmethod
    def from_document(cls, location: SupportedLocation) -> SupportedLocationOption:
        return cls(location_key=location.location_key, label=location.label)


class SupportedLocationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage_notice: str
    locations: list[SupportedLocationOption]


class FarmLocationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_key: LocationKey
    label: FarmText


class ReferenceOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: CropKey
    label: FarmText
    definition: FarmText

    @classmethod
    def from_document(cls, option: FarmReferenceOption) -> ReferenceOptionResponse:
        return cls(key=option.key, label=option.label, definition=option.definition)


class FarmReferenceOptionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    soil_textures: list[ReferenceOptionResponse]
    irrigation_access: list[ReferenceOptionResponse]


class CropOptionResponse(BaseModel):
    """Public crop identity; no claim that the crop is suitable for this farm."""

    model_config = ConfigDict(extra="forbid")

    id: str
    crop_key: CropKey
    common_name: FarmText
    scientific_name: str | None
    history_selectable: bool
    recommendation_candidate: bool
    evidence_status: Literal["unknown", "provisional", "locally_reviewed", "conflicted"]
    requires_variety_for_timing: bool
    requires_production_system_for_assessment: bool

    @classmethod
    def from_document(cls, crop: Crop, *, evidence_status: str) -> CropOptionResponse:
        return cls(
            id=str(crop.id),
            crop_key=crop.crop_key,
            common_name=crop.common_name,
            scientific_name=crop.scientific_name,
            history_selectable=crop.history_selectable,
            recommendation_candidate=crop.recommendation_candidate,
            evidence_status=evidence_status,
            requires_variety_for_timing=crop.requires_variety_for_timing,
            requires_production_system_for_assessment=(
                crop.requires_production_system_for_assessment
            ),
        )


class CropOptionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    crops: list[CropOptionResponse]


class CropIdentitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    key: CropKey
    label: FarmText


class FarmHistoryEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    crop: CropIdentitySummary
    sequence_order: int
    start_date: date | None
    end_date: date | None
    variety_key: CropKey | None
    production_system_key: CropKey | None
    date_precision: Literal["day", "unknown"]
    date_source: Literal["farmer_reported"]


class FarmEnvironmentalContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "ready", "partial", "unavailable", "needs_review"]
    period: DerivedContextPeriod | None
    snapshot_id: str | None
    data_status: Literal["live", "cached", "unavailable"] | None
    cache_action: str | None
    warning_code: str | None
    updated_at: datetime


class LegacyUnresolvedInputs(BaseModel):
    """Owner-visible old strings, clearly excluded from canonical decision inputs."""

    model_config = ConfigDict(extra="forbid")

    previous_crops: list[FarmText] | None = None
    soil_texture: FarmText | None = None
    irrigation_access: FarmText | None = None


class FarmResponse(BaseModel):
    """Owner-only response; no owner ID, precise coordinates, or current_practice."""

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: str
    revision: int
    name: FarmName
    location: FarmLocationSummary
    soil_texture: ReferenceOptionResponse | None = None
    irrigation_access: ReferenceOptionResponse | None = None
    history_status: Literal["complete", "needs_review", "unknown", "legacy_unresolved"]
    crop_history: list[FarmHistoryEventResponse]
    declared_gaps: list[HistoryGapResponse]
    current_plot_available: bool | None
    earliest_available_date: date | None
    environmental_context: FarmEnvironmentalContextResponse | None
    legacy_unresolved_inputs: LegacyUnresolvedInputs | None = None
    farmer_priorities: PriorityPoints | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_document(
        cls,
        farm: Farm,
        *,
        location_label: str,
        crop_labels_by_key: dict[str, str] | None = None,
        soil_option: FarmReferenceOption | None = None,
        irrigation_option: FarmReferenceOption | None = None,
    ) -> FarmResponse:
        labels = crop_labels_by_key or {}
        context = farm.environmental_context
        legacy = None
        if farm.history_status == "legacy_unresolved" and (
            farm.previous_crops or farm.soil_texture or farm.irrigation_access
        ):
            legacy = LegacyUnresolvedInputs(
                previous_crops=farm.previous_crops,
                soil_texture=farm.soil_texture,
                irrigation_access=farm.irrigation_access,
            )
        return cls(
            id=str(farm.id),
            schema_version=farm.schema_version,
            revision=farm.revision,
            name=farm.name,
            location=FarmLocationSummary(location_key=farm.location_key, label=location_label),
            soil_texture=(
                ReferenceOptionResponse.from_document(soil_option) if soil_option else None
            ),
            irrigation_access=(
                ReferenceOptionResponse.from_document(irrigation_option)
                if irrigation_option
                else None
            ),
            history_status=farm.history_status,
            crop_history=[
                FarmHistoryEventResponse(
                    event_id=event.event_id,
                    crop=CropIdentitySummary(
                        id=str(event.crop_id),
                        key=event.crop_key_snapshot,
                        label=labels.get(event.crop_key_snapshot, event.crop_key_snapshot),
                    ),
                    sequence_order=event.sequence_order,
                    start_date=event.start_date,
                    end_date=event.end_date,
                    variety_key=event.variety_key,
                    production_system_key=event.production_system_key,
                    date_precision=event.date_precision,
                    date_source=event.date_source,
                )
                for event in farm.crop_history
            ],
            declared_gaps=[
                HistoryGapResponse(
                    start_date=gap.start_date,
                    end_date=gap.end_date,
                    status=gap.status,
                    source=gap.source,
                )
                for gap in farm.declared_gaps
            ],
            current_plot_available=farm.current_plot_available,
            earliest_available_date=farm.earliest_available_date,
            environmental_context=(
                FarmEnvironmentalContextResponse(
                    status=context.status,
                    period=context.period,
                    snapshot_id=str(context.snapshot_id) if context.snapshot_id else None,
                    data_status=context.data_status,
                    cache_action=context.cache_action,
                    warning_code=context.warning_code,
                    updated_at=context.updated_at,
                )
                if context
                else None
            ),
            legacy_unresolved_inputs=legacy,
            farmer_priorities=farm.farmer_priorities,
            created_at=farm.created_at,
            updated_at=farm.updated_at,
        )
