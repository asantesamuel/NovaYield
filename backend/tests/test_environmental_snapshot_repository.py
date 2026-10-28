"""Mock-backed tests for the NY-6 snapshot repository."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from app.integrations.nasa.power import PowerRequest
from app.models.environmental_snapshots import (
    EnvironmentalSnapshot,
    SnapshotSeasonContext,
    build_snapshot_identity,
)
from app.repositories.environmental_snapshots import (
    EnvironmentalSnapshotRepository,
    SnapshotIdentityConflict,
    SnapshotStorageUnavailable,
)

TEST_IDENTITY_SECRET = "repository-test-secret-value-has-at-least-32-bytes"
TEST_IDENTITY = build_snapshot_identity(
    PowerRequest(
        latitude=0.0,
        longitude=0.0,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    ),
    location_secret=TEST_IDENTITY_SECRET,
)


def run_immediately(awaitable: Any) -> Any:
    """Run repository coroutines backed only by immediate in-memory fakes."""
    try:
        awaitable.send(None)
    except StopIteration as result:
        return result.value
    awaitable.close()
    pytest.fail("The in-memory repository fake unexpectedly suspended.")


def make_snapshot() -> EnvironmentalSnapshot:
    return EnvironmentalSnapshot.model_construct(
        identity=TEST_IDENTITY,
        request_contexts=[],
    )


def test_lookup_uses_opaque_request_key_and_returns_persisted_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = make_snapshot()
    calls: list[tuple[dict[str, str], bool]] = []

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        calls.append((query, ignore_cache))
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))

    found = run_immediately(EnvironmentalSnapshotRepository().find_by_identity(TEST_IDENTITY))

    assert found is snapshot
    assert calls == [({"identity.request_key": TEST_IDENTITY.request_key}, True)]


def test_insert_if_absent_returns_existing_snapshot_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = make_snapshot()

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        assert ignore_cache
        return existing

    async def unexpected_insert(_snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        pytest.fail("An existing snapshot must not be inserted again.")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", unexpected_insert)

    outcome = run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(make_snapshot()))

    assert outcome.snapshot is existing
    assert outcome.inserted is False


def test_insert_if_absent_stores_snapshot_after_cache_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = make_snapshot()
    find_calls = 0
    insert_calls = 0

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> None:
        nonlocal find_calls
        find_calls += 1
        assert ignore_cache
        return None

    async def fake_insert(snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        nonlocal insert_calls
        insert_calls += 1
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", fake_insert)

    outcome = run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(candidate))

    assert outcome.snapshot is candidate
    assert outcome.inserted is True
    assert find_calls == 1
    assert insert_calls == 1


def test_duplicate_insert_race_returns_the_winning_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = make_snapshot()
    find_calls = 0

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot | None:
        nonlocal find_calls
        find_calls += 1
        assert ignore_cache
        return None if find_calls == 1 else winner

    async def fake_insert(_snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        raise DuplicateKeyError("duplicate key details must not escape")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", fake_insert)

    outcome = run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(make_snapshot()))

    assert outcome.snapshot is winner
    assert outcome.inserted is False
    assert find_calls == 2


def test_duplicate_conflict_and_storage_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing_find(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> None:
        assert ignore_cache
        return None

    async def duplicate_insert(_snapshot: EnvironmentalSnapshot) -> None:
        raise DuplicateKeyError("raw details: mongodb://user:private-password@host")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(missing_find))
    monkeypatch.setattr(EnvironmentalSnapshot, "insert", duplicate_insert)

    with pytest.raises(SnapshotIdentityConflict) as conflict:
        run_immediately(EnvironmentalSnapshotRepository().insert_if_absent(make_snapshot()))
    assert "private-password" not in str(conflict.value)

    async def unavailable_find(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> None:
        assert ignore_cache
        raise ServerSelectionTimeoutError("mongodb://user:private-password@host")

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(unavailable_find))

    with pytest.raises(SnapshotStorageUnavailable) as unavailable:
        run_immediately(EnvironmentalSnapshotRepository().find_by_identity(TEST_IDENTITY))
    assert "private-password" not in str(unavailable.value)


def test_request_context_is_added_with_atomic_add_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = make_snapshot()
    update_calls: list[dict[str, Any]] = []

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        assert ignore_cache
        return snapshot

    async def fake_update(
        _snapshot: EnvironmentalSnapshot, update: dict[str, Any]
    ) -> EnvironmentalSnapshot:
        update_calls.append(update)
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "update", fake_update)
    context = SnapshotSeasonContext(
        season_label="major-season-v1",
        calendar_source_version="research-v1",
        crop="maize",
    )

    updated = run_immediately(
        EnvironmentalSnapshotRepository().add_request_context(TEST_IDENTITY, context)
    )

    assert updated is snapshot
    assert update_calls == [
        {
            "$addToSet": {
                "request_contexts": {
                    "season_label": "major-season-v1",
                    "calendar_source_version": "research-v1",
                    "crop": "maize",
                }
            }
        }
    ]


def test_replace_after_refresh_keeps_document_id_and_merges_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_context = SnapshotSeasonContext(
        season_label="major-season-v1",
        calendar_source_version="research-v1",
        crop="maize",
    )
    second_context = SnapshotSeasonContext(
        season_label="minor-season-v1",
        calendar_source_version="research-v1",
        crop="sorghum",
    )
    document_id = ObjectId()
    existing = make_snapshot()
    existing.id = document_id
    existing.request_contexts = [first_context]
    candidate = make_snapshot()
    candidate.request_contexts = [second_context]
    replace_calls: list[EnvironmentalSnapshot] = []

    async def fake_find_one(
        _model: type[EnvironmentalSnapshot],
        _query: dict[str, str],
        *,
        ignore_cache: bool,
    ) -> EnvironmentalSnapshot:
        assert ignore_cache
        return existing

    async def fake_replace(snapshot: EnvironmentalSnapshot) -> EnvironmentalSnapshot:
        replace_calls.append(snapshot)
        return snapshot

    monkeypatch.setattr(EnvironmentalSnapshot, "find_one", classmethod(fake_find_one))
    monkeypatch.setattr(EnvironmentalSnapshot, "replace", fake_replace)

    outcome = run_immediately(EnvironmentalSnapshotRepository().replace_after_refresh(candidate))

    assert outcome.inserted is False
    assert outcome.replaced is True
    assert outcome.snapshot.id == document_id
    assert outcome.snapshot.request_contexts == [first_context, second_context]
    assert replace_calls == [candidate]


class FakeLeaseCollection:
    def __init__(
        self, *, result: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self.result = result
        self.error = error
        self.index_calls: list[tuple[str, dict[str, Any]]] = []
        self.find_update_calls: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        self.delete_calls: list[dict[str, str]] = []

    async def create_index(self, field: str, **options: Any) -> str:
        self.index_calls.append((field, options))
        return options["name"]

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        **options: Any,
    ) -> dict[str, Any] | None:
        self.find_update_calls.append((query, update, options))
        if self.error:
            raise self.error
        return self.result

    async def delete_one(self, query: dict[str, str]) -> None:
        self.delete_calls.append(query)


class FakeDatabase(dict[str, FakeLeaseCollection]):
    pass


class FakeSnapshotCollection:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database


@pytest.mark.parametrize("lease_result", [{"owner_token": "worker-a"}, None])
def test_request_lease_acquisition_uses_expiry_and_owner_token(
    monkeypatch: pytest.MonkeyPatch,
    lease_result: dict[str, str] | None,
) -> None:
    lease_collection = FakeLeaseCollection(result=lease_result)
    database = FakeDatabase(environmental_snapshot_request_leases=lease_collection)
    monkeypatch.setattr(
        EnvironmentalSnapshot,
        "get_pymongo_collection",
        classmethod(lambda _model: FakeSnapshotCollection(database)),
    )
    now = datetime(2026, 10, 1, tzinfo=UTC)
    expires_at = now + timedelta(seconds=60)

    acquired = run_immediately(
        EnvironmentalSnapshotRepository().try_acquire_request_lease(
            "opaque-request-key",
            owner_token="worker-a",
            now=now,
            expires_at=expires_at,
        )
    )

    query, update, options = lease_collection.find_update_calls[0]
    assert lease_collection.index_calls == [
        (
            "lease_expires_at",
            {"expireAfterSeconds": 0, "name": "request_lease_expires_at_ttl"},
        )
    ]
    assert query == {
        "_id": "opaque-request-key",
        "$or": [
            {"lease_expires_at": {"$lte": now}},
            {"owner_token": "worker-a"},
        ],
    }
    assert update["$set"] == {
        "owner_token": "worker-a",
        "lease_expires_at": expires_at,
    }
    assert options["upsert"] is True
    assert acquired is (lease_result is not None)


def test_active_request_lease_duplicate_key_means_another_worker_owns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_collection = FakeLeaseCollection(error=DuplicateKeyError("opaque key already exists"))
    database = FakeDatabase(environmental_snapshot_request_leases=lease_collection)
    monkeypatch.setattr(
        EnvironmentalSnapshot,
        "get_pymongo_collection",
        classmethod(lambda _model: FakeSnapshotCollection(database)),
    )

    acquired = run_immediately(
        EnvironmentalSnapshotRepository().try_acquire_request_lease(
            "opaque-request-key",
            owner_token="worker-b",
            now=datetime(2026, 10, 1, tzinfo=UTC),
            expires_at=datetime(2026, 10, 1, 0, 1, tzinfo=UTC),
        )
    )

    assert acquired is False


def test_request_lease_database_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_collection = FakeLeaseCollection(
        error=ServerSelectionTimeoutError("mongodb://user:private-password@host")
    )
    database = FakeDatabase(environmental_snapshot_request_leases=lease_collection)
    monkeypatch.setattr(
        EnvironmentalSnapshot,
        "get_pymongo_collection",
        classmethod(lambda _model: FakeSnapshotCollection(database)),
    )

    with pytest.raises(SnapshotStorageUnavailable) as unavailable:
        run_immediately(
            EnvironmentalSnapshotRepository().try_acquire_request_lease(
                "opaque-request-key",
                owner_token="worker-b",
                now=datetime(2026, 10, 1, tzinfo=UTC),
                expires_at=datetime(2026, 10, 1, 0, 1, tzinfo=UTC),
            )
        )
    assert "private-password" not in str(unavailable.value)


def test_request_lease_release_only_deletes_its_owner_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease_collection = FakeLeaseCollection()
    database = FakeDatabase(environmental_snapshot_request_leases=lease_collection)
    monkeypatch.setattr(
        EnvironmentalSnapshot,
        "get_pymongo_collection",
        classmethod(lambda _model: FakeSnapshotCollection(database)),
    )

    run_immediately(
        EnvironmentalSnapshotRepository().release_request_lease(
            "opaque-request-key", owner_token="worker-a"
        )
    )

    assert lease_collection.delete_calls == [
        {"_id": "opaque-request-key", "owner_token": "worker-a"}
    ]
