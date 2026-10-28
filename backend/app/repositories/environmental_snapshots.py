"""MongoDB access for normalized NASA POWER environmental snapshots (NY-6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotIdentity,
    SnapshotSeasonContext,
)

REQUEST_LEASE_COLLECTION_NAME = "environmental_snapshot_request_leases"
REQUEST_LEASE_EXPIRY_INDEX_NAME = "request_lease_expires_at_ttl"


class SnapshotRepositoryError(Exception):
    """Base for safe snapshot-persistence errors."""


class SnapshotStorageUnavailable(SnapshotRepositoryError):
    """MongoDB could not complete a snapshot operation."""


class SnapshotIdentityConflict(SnapshotRepositoryError):
    """MongoDB rejected the identity, but the winning snapshot could not be found."""


@dataclass(frozen=True, slots=True)
class SnapshotInsertOutcome:
    """Result of an idempotent insert attempt."""

    snapshot: EnvironmentalSnapshot
    inserted: bool
    replaced: bool = False


class EnvironmentalSnapshotRepository:
    """Read and write shared snapshots through Beanie's initialized model.

    The unique request-key index is the final guard against concurrent duplicate
    documents. Short-lived request leases coordinate NASA calls across application
    processes; the cache service owns the policy for using those leases.
    """

    def __init__(self, document_model: type[EnvironmentalSnapshot] = EnvironmentalSnapshot) -> None:
        self._document_model = document_model
        self._lease_expiry_index_ready = False

    async def find_by_identity(self, identity: SnapshotIdentity) -> EnvironmentalSnapshot | None:
        """Return stored normalized values for NY-7 without contacting NASA."""

        try:
            return await self._document_model.find_one(
                {"identity.request_key": identity.request_key},
                ignore_cache=True,
            )
        except PyMongoError:
            raise SnapshotStorageUnavailable("MongoDB snapshot lookup failed.") from None

    async def insert_if_absent(self, snapshot: EnvironmentalSnapshot) -> SnapshotInsertOutcome:
        """Insert once; if another worker won the unique-key race, return its row."""

        existing = await self.find_by_identity(snapshot.identity)
        if existing is not None:
            return SnapshotInsertOutcome(snapshot=existing, inserted=False)

        try:
            inserted_snapshot = await snapshot.insert()
        except DuplicateKeyError:
            raced_snapshot = await self.find_by_identity(snapshot.identity)
            if raced_snapshot is not None:
                return SnapshotInsertOutcome(snapshot=raced_snapshot, inserted=False)
            raise SnapshotIdentityConflict(
                "MongoDB rejected the snapshot identity, but no matching snapshot was found."
            ) from None
        except PyMongoError:
            raise SnapshotStorageUnavailable("MongoDB snapshot insert failed.") from None

        return SnapshotInsertOutcome(snapshot=inserted_snapshot, inserted=True)

    async def replace_after_refresh(self, snapshot: EnvironmentalSnapshot) -> SnapshotInsertOutcome:
        """Atomically replace refreshed data while retaining the existing document ID."""

        existing = await self.find_by_identity(snapshot.identity)
        if existing is None or existing.id is None:
            return await self.insert_if_absent(snapshot)

        refreshed_contexts = list(snapshot.request_contexts)
        snapshot.id = existing.id
        snapshot.request_contexts = list(existing.request_contexts)
        for context in refreshed_contexts:
            if context not in snapshot.request_contexts:
                snapshot.request_contexts.append(context)

        try:
            replaced_snapshot = await snapshot.replace()
        except PyMongoError:
            raise SnapshotStorageUnavailable("MongoDB snapshot refresh write failed.") from None

        return SnapshotInsertOutcome(snapshot=replaced_snapshot, inserted=False, replaced=True)

    async def add_request_context(
        self, identity: SnapshotIdentity, context: SnapshotSeasonContext
    ) -> EnvironmentalSnapshot | None:
        """Atomically retain another crop/season use without changing cache identity."""

        snapshot = await self.find_by_identity(identity)
        if snapshot is None or context in snapshot.request_contexts:
            return snapshot

        try:
            await snapshot.update(
                {
                    "$addToSet": {
                        "request_contexts": context.model_dump(mode="python"),
                    }
                }
            )
        except PyMongoError:
            raise SnapshotStorageUnavailable("MongoDB snapshot context update failed.") from None

        return await self.find_by_identity(identity)

    async def try_acquire_request_lease(
        self,
        request_key: str,
        *,
        owner_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool:
        """Acquire a short Mongo-backed lease, preventing cross-process duplicate fetches."""

        collection = self._document_model.get_pymongo_collection().database[
            REQUEST_LEASE_COLLECTION_NAME
        ]
        try:
            # Expired leases left by a terminated worker are safe to remove. MongoDB
            # may take up to about a minute to process an expired TTL document.
            if not self._lease_expiry_index_ready:
                await collection.create_index(
                    "lease_expires_at",
                    expireAfterSeconds=0,
                    name=REQUEST_LEASE_EXPIRY_INDEX_NAME,
                )
                self._lease_expiry_index_ready = True
            lease = await collection.find_one_and_update(
                {
                    "_id": request_key,
                    "$or": [
                        {"lease_expires_at": {"$lte": now}},
                        {"owner_token": owner_token},
                    ],
                },
                {
                    "$set": {
                        "owner_token": owner_token,
                        "lease_expires_at": expires_at,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # An unexpired lease already owns this request key.
            return False
        except PyMongoError:
            raise SnapshotStorageUnavailable("MongoDB request coordination failed.") from None
        return lease is not None and lease.get("owner_token") == owner_token

    async def release_request_lease(self, request_key: str, *, owner_token: str) -> None:
        """Release only the lease owned by this fetch; expired leases are recoverable."""

        collection = self._document_model.get_pymongo_collection().database[
            REQUEST_LEASE_COLLECTION_NAME
        ]
        try:
            await collection.delete_one({"_id": request_key, "owner_token": owner_token})
        except PyMongoError:
            raise SnapshotStorageUnavailable(
                "MongoDB request coordination release failed."
            ) from None
