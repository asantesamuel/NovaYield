# Farm catalog and dated history (NY-39)

The [NY-38 handoff](../../analysis_docs/research/ny-38-research-handoff.md),
[data contract](../../analysis_docs/research/ny-38-data-contract.md), and
[Product Owner decisions](../../novayield-research-and-product-decisions.md#6-finalized-product-decisions-and-provisional-assumptions)
govern this feature. The catalog is a working, **provisional** research record.
It is not a local agronomist's validation or a claim that a crop suits a farm.

## Where the data lives

- `crops` holds immutable crop keys and Mongo ObjectIds. Six approved keys are
  recommendation candidates; plantain and sorghum are history-only options.
  Ambiguous “beans” is deliberately absent. An inactive crop remains stored so
  old history can still resolve its identity.
- `crop_profile_revisions` holds exact crop + variety + production-system
  evidence scopes. Generic profiles have no maturity or numerical decision
  traits. The named-variety maturity ranges currently seeded are provisional,
  and their source start/end meaning is not verified for exact scheduling.
- `crop_calendars` holds immutable, location-scoped versions. The seeded MoFA
  regional maize associations have `planting_window: null`; “mid-March” has not
  been turned into an invented exact day. Kintampo gets no Ejura calendar.
- `farm_reference_options` holds versioned soil-texture and irrigation-access
  choices. These are farmer-reported categories, not measured soil-water storage
  or delivered irrigation.
- Existing `supported_locations` remains the only source of public location
  labels and private NASA POWER reference coordinates.
- `farms` embeds at most three events for one decision plot and stores only a
  reference/status envelope for its NASA snapshot. The daily NASA series stays
  in NY-6's `environmental_snapshots` collection.

The Beanie registry discovers these feature-owned documents automatically.
Unique indexes protect crop keys, reference `(kind,key)`, profile scope/revision,
and calendar scope/version. MongoDB does not enforce relational foreign keys:
the Farm repository resolves and checks references before a write, and every
Farm read/write uses both Farm ID and authenticated owner ID.

## Seed and migration commands

From `backend/` with the documented virtual environment activated and MongoDB
configured in `.env`:

```powershell
python -m app.farms.seed_locations
python -m app.farms.seed_catalogs
python -m app.farms.migrate_legacy
```

Seeding inserts **missing** keys/revisions only, so rerunning it preserves
reviewed records and stable Mongo IDs. It does not overwrite existing evidence.
The migration labels pre-v2 Farms `legacy_unresolved` without manufacturing
crop identities, order, dates, soil categories, or a current-practice baseline.
Their old strings remain stored and visible to the owner under
`legacy_unresolved_inputs` until the owner supplies a new dated profile.
New farm creation requires the reference catalog to be seeded; an unseeded
catalog returns a safe 422 rather than accepting free text.

## Farm setup contract

`GET /api/v1/crops?usage=history` and
`GET /api/v1/farms/reference-options` return public-safe catalog choices.
`GET /api/v1/farms/locations` remains the supported-location source. The
history picker and NY-40 candidate lookup read the same `crops` collection.

For `POST /api/v1/farms`, a complete example is:

```json
{
  "name": "One decision plot",
  "location_key": "ejura",
  "soil_texture_key": "unknown",
  "irrigation_access_key": "unknown",
  "history_status": "complete",
  "crop_history": [
    {
      "crop_key": "maize",
      "sequence_order": 1,
      "start_date": "2024-03-15",
      "end_date": "2024-07-15"
    }
  ],
  "current_plot_available": null,
  "earliest_available_date": null
}
```

The server resolves `crop_key` to `crop_id`, generates `event_id`, and saves
the farmer's exact dates. It rejects unknown/inactive crop keys, reversed or
future dates, duplicate/skipped order, and overlapping crops in a `complete`
sole-crop sequence. A gap between events is **not assumed fallow**: a complete
history must explicitly cover it with `declared_gaps`, while an unconfirmed gap
belongs in `needs_review`. A `needs_review` draft can retain missing dates or
overlap/intercropping but cannot generate a sequential rank. `unknown` has no
asserted events. No caller may submit an owner ID, raw coordinates, arbitrary
crop text, a current-practice field, or a separate NASA date range.

`current_plot_available` is `true`, `false`, or `null` (unknown). When true,
`earliest_available_date` must be explicit; it may be in the past if the plot
is already free. When false, a known future availability date is optional.
Neither a past harvest nor a null date is silently treated as present-day
availability.

## Derived NASA context and retry state

For a complete history, the backend computes an inclusive period using
`ny38-calendar-month-v1`:

```text
history_start = earliest event start_date
history_end = latest event end_date
context_end = history_end
context_start = min(history_start, context_end minus 12 calendar months)
```

The 12-month subtraction keeps month/day and clamps 29 February to 28 February
in a non-leap prior year. It never changes an event date or assumes 365 fixed
days. The Farm is saved first with `pending`; then NY-6's existing snapshot
service looks up or retrieves the exact POWER request. The Farm stores its
snapshot ID, derived period, cache/data status, and safe warning code. A valid
snapshot produces `ready` or `partial`; an unavailable provider yields
`unavailable` while the Farm remains retrievable. A retry uses the same NY-6
cache/freshness logic. Context writes compare the Farm input revision so a
late NASA response cannot attach to a history that changed during retrieval.

`Farm.updated_at` records user input edits; the context envelope's own
`updated_at` records the latest derived-data refresh. Public responses never
include private coordinates, owner IDs, secrets, or raw NASA payloads.

## Verification

```powershell
python -m pytest tests/test_farm_schemas.py tests/test_farm_repository.py tests/test_farm_api.py tests/test_ny39_history_and_catalog.py tests/test_ny39_catalog_repositories.py tests/test_ny39_farm_context_service.py
```

For the opt-in disposable Mongo integration test, set
`NOVAYIELD_TEST_MONGODB_URI` to a test server URI and run
`python -m pytest tests/test_farm_mongodb_integration.py`. That test creates a
random database name and drops only that database in `finally`.

The NY-38 evidence appendix still leaves most pilot crop calendars, stage
lengths, crop-water demand, soil-water storage, labour, and field outcomes
unknown. NY-40 must keep affected future timing and scoring `needs_review` or
`not_assessed` rather than deriving those values from broad labels.
