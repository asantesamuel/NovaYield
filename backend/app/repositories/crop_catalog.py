"""Read canonical crop identities and seed only sourced, versioned research records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.farms.catalog_seed_data import (
    CROP_IDENTITY_SEEDS,
    GENERIC_PROFILE_SOURCE_NOTE,
    GENERIC_STAGE_SEEDS,
    LEGACY_GENERIC_PROFILE_NOTE,
    MOFA_MAIZE,
    NAMED_PROFILE_SEEDS,
    REGIONAL_CALENDAR_SEEDS,
    WATER_RESILIENCE_EVIDENCE,
    _source,
)
from app.models.crop_catalog import (
    CROP_PROFILE_SCHEMA_VERSION,
    Crop,
    CropCalendar,
    CropProfileRevision,
    DecisionTraits,
    EvidenceValue,
    MaturityEvidence,
    MaturityRange,
)


@dataclass(frozen=True, slots=True)
class CropCandidateBundle:
    """One candidate plus exact, versioned evidence records for NY-40."""

    crop: Crop
    active_profiles: tuple[CropProfileRevision, ...]
    calendars: tuple[CropCalendar, ...]


class CropCatalogRepository:
    def __init__(
        self,
        crop_model: Any = Crop,
        profile_model: Any = CropProfileRevision,
        calendar_model: Any = CropCalendar,
    ) -> None:
        self._crop_model = crop_model
        self._profile_model = profile_model
        self._calendar_model = calendar_model

    async def list_crops(self, *, usage: str | None = None) -> list[Crop]:
        """Use this same collection for history choices and candidate identities."""

        query: dict[str, Any] = {"catalog_status": "active"}
        if usage == "history":
            query["history_selectable"] = True
        elif usage == "recommendation":
            query["recommendation_candidate"] = True
        elif usage is not None:
            raise ValueError("Unsupported crop catalog usage")
        return await self._crop_model.find(query).sort([("crop_key", ASCENDING)]).to_list()

    async def get_history_crop(self, crop_key: str) -> Crop | None:
        """Reject absent, inactive, and recommendation-only identities for history."""

        return await self._crop_model.find_one(
            {"crop_key": crop_key, "catalog_status": "active", "history_selectable": True}
        )

    async def get_crop_by_key(self, crop_key: str) -> Crop | None:
        """Read retained identities even after deactivation for old farm display."""

        return await self._crop_model.find_one({"crop_key": crop_key})

    async def list_by_keys(self, keys: set[str]) -> list[Crop]:
        """Resolve old and active identities in one query for owner-safe farm DTOs."""

        if not keys:
            return []
        return await self._crop_model.find({"crop_key": {"$in": sorted(keys)}}).to_list()

    async def list_active_profiles(self, crop_ids: tuple[Any, ...]) -> list[CropProfileRevision]:
        if not crop_ids:
            return []
        return await self._profile_model.find(
            {"crop_id": {"$in": list(crop_ids)}, "is_active": True}
        ).to_list()

    async def get_active_profile(
        self,
        crop_id: Any,
        *,
        variety_key: str | None = None,
        production_system_key: str | None = None,
    ) -> CropProfileRevision | None:
        """Resolve an exact scope; never inherit another variety or rice ecology."""

        return await self._profile_model.find_one(
            {
                "crop_id": crop_id,
                "variety_key": variety_key,
                "production_system_key": production_system_key,
                "is_active": True,
            }
        )

    async def list_calendars(
        self,
        *,
        location_key: str,
        crop_ids: tuple[Any, ...],
    ) -> list[CropCalendar]:
        if not crop_ids:
            return []
        return await self._calendar_model.find(
            {
                "location_key": location_key,
                "crop_id": {"$in": list(crop_ids)},
                "is_active": True,
            }
        ).to_list()

    async def list_recommendation_candidates(
        self, *, location_key: str
    ) -> list[CropCandidateBundle]:
        """Return identities and their exact active profile/calendar revision IDs."""

        crops = await self.list_crops(usage="recommendation")
        crop_ids = tuple(crop.id for crop in crops if crop.id is not None)
        if not crop_ids:
            return []
        profiles = await self.list_active_profiles(crop_ids)
        calendars = await self.list_calendars(location_key=location_key, crop_ids=crop_ids)
        profiles_by_crop: dict[Any, list[CropProfileRevision]] = {}
        calendars_by_crop: dict[Any, list[CropCalendar]] = {}
        for profile in profiles:
            profiles_by_crop.setdefault(profile.crop_id, []).append(profile)
        for calendar in calendars:
            calendars_by_crop.setdefault(calendar.crop_id, []).append(calendar)
        return [
            CropCandidateBundle(
                crop=crop,
                active_profiles=tuple(profiles_by_crop.get(crop.id, [])),
                calendars=tuple(calendars_by_crop.get(crop.id, [])),
            )
            for crop in crops
        ]

    async def seed_missing(self) -> dict[str, int]:
        """Insert absent identities/revisions only; never overwrite a reviewed record."""

        counts = {"crops": 0, "profiles": 0, "calendars": 0}
        crops_by_key: dict[str, Crop] = {}
        for seed in CROP_IDENTITY_SEEDS:
            crop = await self._crop_model.find_one({"crop_key": seed["crop_key"]})
            if crop is None:
                crop = self._crop_model(**seed)
                try:
                    await crop.insert()
                    counts["crops"] += 1
                except DuplicateKeyError:
                    crop = await self._crop_model.find_one({"crop_key": seed["crop_key"]})
                    if crop is None:
                        raise
            crops_by_key[seed["crop_key"]] = crop

        for crop_key in ("maize", "cowpea", "groundnut", "cassava", "yam", "rice"):
            crop = crops_by_key[crop_key]
            if crop.id is None:
                raise RuntimeError("Seeded crop is missing its Mongo identity")
            counts["profiles"] += await self._seed_generic_profile(crop, crop_key)

        for seed in NAMED_PROFILE_SEEDS:
            crop = crops_by_key[seed["crop_key"]]
            if crop.id is None:
                raise RuntimeError("Seeded crop is missing its Mongo identity")
            maturity = None
            if seed["min_days"] is not None:
                maturity = MaturityEvidence(
                    value=MaturityRange(
                        min_days=seed["min_days"],
                        max_days=seed["max_days"],
                        meaning=(
                            "Source-reported maturity days; planting start and harvest endpoint "
                            "have not been verified for this pilot."
                        ),
                        endpoint_verified=False,
                    ),
                    source=_source(
                        seed["source_url"],
                        "CSIR Ghana crop variety catalog"
                        if seed["source_url"] != MOFA_MAIZE
                        else "Ghana MoFA crop guide",
                        variety=seed["variety"],
                        applicability="Only the named variety and source-listed system.",
                        limitations=(
                            "Not a generic crop duration or locally reviewed plot schedule; "
                            "the source's exact start and endpoint meaning needs validation."
                        ),
                    ),
                )
            counts["profiles"] += await self._insert_profile_if_absent(
                dict(
                    crop_id=crop.id,
                    revision=1,
                    is_active=True,
                    published_at=datetime.now(UTC),
                    variety_key=seed["variety_key"],
                    production_system_key=seed["production_system_key"],
                    evidence_status=seed.get("evidence_status", "provisional"),
                    maturity_days=maturity,
                    source_note=(
                        "MoFA and CSIR Nabogo maturity ranges conflict; no operational duration."
                        if seed.get("evidence_status") == "conflicted"
                        else "Named-variety maturity is desk evidence, not a local schedule."
                    ),
                )
            )

        for seed in REGIONAL_CALENDAR_SEEDS:
            crop = crops_by_key[seed["crop_key"]]
            if crop.id is None:
                raise RuntimeError("Seeded crop is missing its Mongo identity")
            query = {
                "location_key": seed["location_key"],
                "crop_id": crop.id,
                "profile_revision_id": None,
                "season_key": seed["season_key"],
                "calendar_version": "ny38-regional-maize-v1",
            }
            if await self._calendar_model.find_one(query) is not None:
                continue
            active_scope = {
                "location_key": seed["location_key"],
                "crop_id": crop.id,
                "profile_revision_id": None,
                "season_key": seed["season_key"],
                "is_active": True,
            }
            # A curated later calendar may already be the active revision for
            # this exact scope. Never revive the initial desk seed over it.
            if await self._calendar_model.find_one(active_scope) is not None:
                continue
            calendar = self._calendar_model(
                **query,
                is_active=True,
                published_at=datetime.now(UTC),
                planting_window=None,
                status="provisional",
                evidence=_source(
                    MOFA_MAIZE,
                    "Ghana MoFA maize production guide",
                    applicability="Regional seasonal association only; not an exact planting day.",
                    limitations="Ejura/Anyinasu local onset and variety timing remain unvalidated.",
                ),
                source_note=seed["source_note"],
            )
            try:
                await calendar.insert()
                counts["calendars"] += 1
            except DuplicateKeyError:
                if (
                    await self._calendar_model.find_one(query) is None
                    and await self._calendar_model.find_one(active_scope) is None
                ):
                    raise
        return counts

    async def _seed_generic_profile(self, crop: Crop, crop_key: str) -> int:
        """Seed a water class or safely promote only our original generic seed."""

        if crop.id is None:
            raise RuntimeError("Seeded crop is missing its Mongo identity")
        scope = {
            "crop_id": crop.id,
            "variety_key": None,
            "production_system_key": None,
        }
        water_evidence = WATER_RESILIENCE_EVIDENCE.get(crop_key)
        active = await self._profile_model.find_one({**scope, "is_active": True})

        if active is not None:
            current_traits = getattr(active, "decision_traits", None) or DecisionTraits()
            if current_traits.water_resilience_class is not None or water_evidence is None:
                return 0
            if (
                getattr(active, "revision", None) != 1
                or getattr(active, "source_note", None) != LEGACY_GENERIC_PROFILE_NOTE
            ):
                # A team-authored profile is authoritative, even if it has not
                # populated this optional trait. Never overwrite it with seeds.
                return 0
            replacement = await self._generic_profile_revision_two(active, water_evidence)
            if replacement is None:
                return 0
            active.is_active = False
            await active.save()
            replacement.is_active = True
            replacement.published_at = datetime.now(UTC)
            await replacement.save()
            return 1

        # Recover an interrupted seed migration: the previous run may have
        # inserted revision 2 and deactivated revision 1 before activation.
        pending = await self._profile_model.find_one({**scope, "revision": 2})
        if (
            pending is not None
            and water_evidence is not None
            and getattr(pending, "source_note", None) == GENERIC_PROFILE_SOURCE_NOTE
            and getattr(getattr(pending, "decision_traits", None), "water_resilience_class", None)
            is not None
        ):
            pending.is_active = True
            pending.published_at = datetime.now(UTC)
            await pending.save()
            return 0

        stages = list(GENERIC_STAGE_SEEDS.get(crop_key, ()))
        return await self._insert_profile_if_absent(
            dict(
                crop_id=crop.id,
                revision=1,
                is_active=True,
                published_at=datetime.now(UTC),
                variety_key=None,
                production_system_key=None,
                evidence_status=("provisional" if stages or water_evidence else "unknown"),
                growth_stages=stages,
                decision_traits=DecisionTraits(water_resilience_class=water_evidence),
                source_note=GENERIC_PROFILE_SOURCE_NOTE,
            )
        )

    async def _generic_profile_revision_two(
        self,
        profile: CropProfileRevision,
        water_evidence: EvidenceValue,
    ) -> CropProfileRevision | None:
        """Create an immutable replacement for only the exact legacy seed profile."""

        fields = {
            **profile.model_dump(exclude={"id", "revision", "is_active", "published_at"}),
            "schema_version": CROP_PROFILE_SCHEMA_VERSION,
            "revision": 2,
            "is_active": False,
            "published_at": None,
            "evidence_status": "provisional",
            "decision_traits": (
                getattr(profile, "decision_traits", None) or DecisionTraits()
            ).model_copy(update={"water_resilience_class": water_evidence}),
            "source_note": GENERIC_PROFILE_SOURCE_NOTE,
        }
        existing = await self._profile_model.find_one(
            {
                "crop_id": profile.crop_id,
                "variety_key": None,
                "production_system_key": None,
                "revision": 2,
            }
        )
        if existing is not None:
            if (
                getattr(existing, "source_note", None) == GENERIC_PROFILE_SOURCE_NOTE
                and getattr(
                    getattr(existing, "decision_traits", None), "water_resilience_class", None
                )
                is not None
            ):
                return existing
            return None
        replacement = self._profile_model(**fields)
        try:
            await replacement.insert()
        except DuplicateKeyError:
            replacement = await self._profile_model.find_one(
                {
                    "crop_id": profile.crop_id,
                    "variety_key": None,
                    "production_system_key": None,
                    "revision": 2,
                }
            )
            if replacement is None:
                raise
        return replacement

    async def _insert_profile_if_absent(self, fields: dict[str, Any]) -> int:
        query = {
            "crop_id": fields["crop_id"],
            "variety_key": fields["variety_key"],
            "production_system_key": fields["production_system_key"],
            "revision": fields["revision"],
        }
        if await self._profile_model.find_one(query) is not None:
            return 0
        active_scope = {
            "crop_id": fields["crop_id"],
            "variety_key": fields["variety_key"],
            "production_system_key": fields["production_system_key"],
            "is_active": True,
        }
        # Seed only an empty active scope. A curated higher revision is the
        # authority even if the initial revision was never stored here.
        if fields.get("is_active") and await self._profile_model.find_one(active_scope) is not None:
            return 0
        profile = self._profile_model(**fields)
        try:
            await profile.insert()
        except DuplicateKeyError:
            if await self._profile_model.find_one(query) is None and not (
                fields.get("is_active")
                and await self._profile_model.find_one(active_scope) is not None
            ):
                raise
            return 0
        return 1
