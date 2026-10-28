"""MongoDB access for normalized NASA POWER environmental snapshots (NY-6)."""

from __future__ import annotations

from dataclasses import dataclass

from pymongo.errors import DuplicateKeyError, PyMongoError

from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotIdentity,
    SnapshotSeasonContext,
)


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


class EnvironmentalSnapshotRepository:
    """Read and write shared snapshots through Beanie's initialized model.

    The unique request-key index is the final guard against concurrent duplicate
    documents. This repository does not control NASA request concurrency; the
    cache service owns that behavior in a later NY-6 subtask.
    """

    def __init__(self, document_model: type[EnvironmentalSnapshot] = EnvironmentalSnapshot) -> None:
        self._document_model = document_model

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
