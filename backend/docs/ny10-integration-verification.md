# NY-10: Authenticated Backend Integration Verification

## What this verifies

The opt-in suite in `tests/integration/test_authenticated_workflow.py` runs the
real FastAPI app, Beanie models, Mongo repositories, authentication adapters,
farm routes, NASA snapshot service, indicator calculation, rotation engine, and
result history routes together. NASA's HTTP boundary is replaced with a local
`httpx.MockTransport`, so the suite is repeatable and never calls NASA.

The fixed profile in `tests/integration/demo_profile.py` is synthetic test data.
Its past seasons, crops, farm, and NASA-shaped values do not describe a real
farmer or validated agronomic conditions. Future recommendation windows are
computed from the current UTC date only to satisfy the API's future-window
validation; they are not a crop calendar or planting advice.

## Run safely on Windows PowerShell

1. Start or select a MongoDB instance/database dedicated to tests. Never point
   this variable at production or a database containing data you need to keep.
2. From `backend/`, set the explicit test connection string. A local MongoDB
   example is:

   ```powershell
   $env:NOVAYIELD_TEST_MONGODB_URI = "mongodb://localhost:27017"
   ```

3. Run the integration suite:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests\integration -q
   ```

4. Remove the test-only setting when finished:

   ```powershell
   Remove-Item Env:\NOVAYIELD_TEST_MONGODB_URI
   ```

Each test creates a database named `ny10_test_<random-id>` and drops only that
database during cleanup. It does not use the application's default
`nova_yield` database. If `NOVAYIELD_TEST_MONGODB_URI` is absent, the Mongo
integration tests skip; they do not silently connect to the developer's normal
database.

## Scenarios covered

- Register and log in two users through the JSON API and cookie/CSRF flow.
- Create, list, read, and update farms; reject client-supplied ownership and
  unsupported locations.
- Reject unauthenticated, invalid-date, expired-session, and logged-out requests.
- Check that user B cannot list, read, update, generate for, or retrieve user A's
  farm/results by changing identifiers.
- Retrieve a synthetic NASA response, calculate indicators, verify date
  coverage, cache the normalized snapshot, and reuse it across later analysis.
- Force a refresh failure after a successful fetch and confirm the cached values
  are kept and labeled as cached with the failure status.
- Save recommendations and fetch result history/detail; compare stable decision
  fields across repeated requests while allowing retrieval-status metadata to
  change from live to cached.
- Preserve partial-data counts and values without treating NASA fill values as
  zero; return unavailable indicators and withhold ranking when neither a live
  response nor a stored snapshot is available.
- Inject a Mongo repository error at the API boundary and verify the response
  hides the connection string/diagnostic detail.
- Measure the recommendation request against the mocked provider and assert it
  stays below the PRD's 60-second target. This is not a live NASA latency or
  deployment benchmark.

## Status labels and known scope gap

The current environmental contract supports `live`, `cached`, and `unavailable`
data statuses. It does not currently implement a sample-data provider or a
`sample` status. NY-10 verifies live-like success (through the mock), cached
reuse/fallback, and explicit unavailability without invented values. The mock's
synthetic payload is confined to a randomly named test database and must not be
presented as live NASA data or as a public demo recommendation. If product still
requires an offline sample mode, it needs a separate, explicitly labeled feature
implementation before that branch can be integration-tested.

When NASA fails and no stored snapshot exists, the current environmental-context
route returns HTTP 200 with `data_status: unavailable`, a stable `error_code`,
coverage metadata, and null indicator values. Recommendation generation still
stores a result and returns HTTP 201 with a `withheld` ranking and reasons. NY-10
verifies that these responses clearly disclose the unavailable state and never
invent values. If “clear error” is intended to require a non-2xx HTTP response,
that changes NY-9 behavior and needs a separately approved feature change; this
verification ticket does not alter it.

## Learning note: why the suite has two boundaries

The request path uses real feature modules and MongoDB so the test can catch
contract and persistence mismatches that unit tests cannot. `MockTransport`
replaces only the external NASA network call; the actual NASA adapter still
builds the request, parses the response, normalizes units, and maps provider
errors. The unique database name isolates test writes, and teardown removes the
temporary data after each scenario.
