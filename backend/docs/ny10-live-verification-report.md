# NY-10 Live Endpoint and Database Verification

**Run dates:** 4–5 November 2026

**Result:** Final live rerun passed after fixing four confirmed defects. Full local suite: 171 passed, 9 opt-in Mongo tests skipped.

**Purpose:** Exercise every published API route over HTTP, persist test data through the configured MongoDB connection, and call the real NASA POWER Daily Point service.

## Safety and fixture manifest

- On 4 November, the then-effective configuration selected production and remote Atlas; that configuration was not used. On 5 November, the effective settings were `development`, database `nova_yield`, and a remote MongoDB host. The Product Owner explicitly authorized use of that connection for this test.
- A fresh `ny10_manual_*` database was attempted first, but the MongoDB principal could not list collections or drop that namespace (Mongo error code 8000). The app reported not-ready there and no account or farm fixtures were written to it. The namespace did not appear in the principal's authorized database listing; this principal could not verify or drop it.
- The 5 November live API run therefore used the explicitly authorized `nova_yield` database with unique synthetic account emails and farm names. Before the run, counts were: 1 user, 0 farms, 0 environmental snapshots, 0 rotation results, 1 access token, and 3 supported locations. The run deleted only its synthetic users, farms, sessions, results, and snapshot keys; final counts returned to those exact values. It did not drop the database or delete the existing user, access token, or location catalog.
- The API was served by Uvicorn on an ephemeral loopback port and called over HTTP. Its real FastAPI lifespan, Mongo repositories, and NASA adapter ran. NASA requests used the real HTTP client and provider; they were not mocked.
- Two synthetic accounts and two synthetic Ejura farm records were created through the API. Their generated identifiers and passwords were not retained in this report. No fixture records remain in `nova_yield`.
- The reported historical dates and crop history came from the explicitly synthetic NY-10 fixture. They do not describe an actual farm or validated planting history. The public Ejura catalog point is not a farm coordinate or local agronomic validation. See [the NY-8 profile caveats](../../analysis_docs/research/ny-8-public-demo-profile.md) and the canonical [research and product decisions](../../novayield-research-and-product-decisions.md), §6.
- Live requests used the approved catalog selection by label. Exact coordinates, credentials, raw provider payloads, and Mongo connection strings are intentionally omitted.

## Initial pre-fix results from the 5 November manual-style run

| Area | Observed result |
| --- | --- |
| Application and contract | `/openapi.json`, `/docs`, `/redoc`, `/health/live`, and `/health/ready` returned 200. OpenAPI exposed 14 path templates / 16 methods. CORS preflight returned 200 with the configured origin and credentials enabled. |
| Authentication | Two synthetic accounts registered (201), logged in (204), and resolved through `/api/v1/auth/me` (200). Anonymous identity/farm requests returned 401; duplicate account returned 400; invalid registration returned 422; wrong password returned 400. Missing CSRF on registration returned 403. Session cookie was HttpOnly and SameSite=Lax; Secure was disabled for this HTTP-only test server, so HTTPS cookie behavior was not exercised. |
| Session lifecycle | An expired session returned 401; relogin returned 204; logout returned 204; the following identity request returned 401. |
| Farm APIs | Location list returned 200 with three choices. Create (201), list (200), detail (200), and patch (200) worked. Invalid location and client-supplied owner ID returned 422; missing IDs returned 404. Another account's farm read/update returned 404. Owner list isolation passed, and public farm responses omitted coordinate fields. |
| Environmental context | Invalid date order returned 422 without a NASA request; a foreign user's farm returned 404. A live request for 1–3 April 2022 returned 200 with `data_status=live` and `cache_action=miss`; each parameter had 3/3 valid days. |
| Live indicator values | Seasonal precipitation: 14.39 mm/season; mean daily air temperature: 27.5033 °C; mean daily maximum air temperature: 32.44 °C. These are NASA POWER point/grid values for the requested period, not farm measurements. |
| Snapshot persistence and reuse | An equivalent request returned 200, `data_status=cached`, `cache_action=hit`, and made zero additional NASA calls. Explicit refresh returned `live/refreshed` and made one NASA call. Before cleanup, three distinct normalized snapshots were present in Mongo. |
| NASA request count | Four real provider requests were observed: 1–3 April 2022 (initial), the same period (explicit refresh), 1–3 September 2022, and 1–3 April 2023 (the other two periods used by recommendation generation). No coordinates or full URLs were retained. |
| Recommendation workflow | Generation returned 503 after 6.94 seconds with `The rotation result could not be saved. Please retry.` The first historical period reused its snapshot; two other periods were fetched live. Mongo held 3 snapshots and 0 results before cleanup. The result insert failure is described in Bug 1. |
| Result history/detail | Empty owner history returned 200; unknown result detail returned 404; foreign farm history returned 404. Cross-user generation against another user's farm returned 404. **Cross-account retrieval of an existing result remains unverified because generation did not persist any result.** |
| Database cleanup | Two test users, two test farms, three new snapshots, and session records were created. An initial cleanup missed one farm because its name had been updated during the test; the remaining synthetic name was identified and removed. Final counts exactly matched the pre-run baseline. No existing user/session/location data was deleted. |
| Repeatability and demo latency | A successful recommendation response was not produced, so the saved result's repeatability, top-three response, and PRD's 60-second end-to-end target remain unverified. The 6.94-second measurement ended in 503 and is not a successful-workflow benchmark. |

The 5 November OpenAPI paths were: `/api/v1/auth/csrf`, `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me`, `/api/v1/auth/register`, `/api/v1/farms`, `/api/v1/farms/locations`, `/api/v1/farms/{farm_id}`, `/api/v1/farms/{farm_id}/environmental-context`, `/api/v1/farms/{farm_id}/rotation-recommendations`, `/api/v1/farms/{farm_id}/rotation-results`, `/api/v1/farms/{farm_id}/rotation-results/{result_id}`, `/health/live`, and `/health/ready`.

NASA's real response header reported source products `MERRA2` and `POWER`, and the resolution label `NASA/POWER Source Native Resolution Daily Data`. Its per-parameter metadata contained `longname` and `units`, but no per-parameter `source` field. The API currently exposes each indicator's `source` as null, so the available provider-level source list is not represented in the indicator provenance.

## Fixture setup limitation (not an endpoint defect)

The MongoDB principal could ping the remote host and read/write the configured `nova_yield` database, but could not list collections in or drop a newly named database; those operations returned Mongo error code 8000. The first isolated-database startup consequently reported not-ready. The attempted namespace `ny10_manual_5f3af07e0aea483f9e63571631e777c5` did not appear in the principal's authorized database listing, and no test account or farm was written there. Because this principal was denied database listing/drop, its existence could not be independently confirmed. The full run proceeded in the Product Owner-authorized `nova_yield` database with unique synthetic records and restored its original document counts afterward.

## Confirmed bug reports

### Bug 1 — Recommendation result could not be persisted after Mongo readback

**Bug:** Generating a rotation recommendation for an owned farm returns a safe 503 instead of saving and returning the result.

**Expected:** The API returns 201 with the generated recommendation persisted in the user's result history.

**Actual before the fix:** `POST /api/v1/farms/{farm_id}/rotation-recommendations` returned `503` with `The rotation result could not be saved. Please retry.` Mongo's default BSON date decoding returned a naive datetime; the farm's `updated_at` then failed `FarmDecisionInputSnapshot`'s timezone-aware validator before insert.

**Resolution:** The shared `AsyncMongoClient` now uses `tz_aware=True`, preserving BSON UTC timestamps as aware datetimes. The connection test asserts this client option. The final live API rerun saved two recommendations and read them back successfully. Relevant code: [Mongo connection](../app/database/connection.py), [Farm](../app/models/farms.py), [result input snapshot](../app/models/rotation_results.py), and [NY-9 workflow](../app/api/workflows.py).

**How to reproduce:** With a MongoDB database the test principal can write to, register and log in using a unique valid test email such as `ny10@example.com`, create a farm using `{"name":"NY-10 synthetic test farm","location_key":"ejura"}`, then POST a valid NY-10 recommendation request to `/api/v1/farms/{created_farm_id}/rotation-recommendations`. Use the fixed historical windows from [the integration fixture](../tests/integration/demo_profile.py); future recommendation slots can be generated by its `recommendation_request()` helper. The existing fixture's `.test` email domain is separately rejected (Bug 3).

**Impact before the fix:** The recommendation workflow could not save a result. The final rerun confirms this is resolved.

### Bug 2 — Live indicator response omitted available NASA source provenance

**Bug:** Live environmental indicators contain `source: null` even though NASA returns provider-level source metadata.

**Expected:** The response preserves traceable source provenance for each indicator, while accurately describing whether NASA supplied it at parameter or response-header level.

**Actual before the fix:** NASA's response header contained `sources: ["MERRA2", "POWER"]`, but parameter metadata did not contain a `source` key. The adapter retained provider-level sources while the indicator calculation used only parameter metadata.

**Resolution:** Indicators now include `source_scope` (`parameter` or `provider`) and `source_products`. When NASA does not attribute one source product to an individual parameter, the API reports `source: "NASA POWER"`, `source_scope: "provider"`, and retains the header products. The final live response showed `source_products: ["MERRA2", "POWER"]`; it does not incorrectly assign either product to a specific variable. A missing-parameter indicator also keeps provider provenance. Focused tests cover both cases. Relevant code: [NASA POWER normalization](../app/integrations/nasa/power.py) and [indicator calculation](../app/indicators/environmental.py).

**How to reproduce:** Create and authenticate an account, create an Ejura farm, then POST `{"start_date":"2022-04-01","end_date":"2022-04-03"}` to `/api/v1/farms/{farm_id}/environmental-context` against the live NASA client. Inspect `indicators[*].source` and the provider response header metadata.

**Impact before the fix:** The indicator omitted available provenance. The final live response now makes its provider-level scope explicit without asserting a per-parameter attribution.

### Bug 3 — NY-10 real-Mongo integration accounts used email addresses rejected by validation

**Bug:** The opt-in NY-10 real-Mongo integration suite cannot register its configured `example.test` accounts with the current email validator.

**Expected:** The prepared integration fixture uses synthetically unique addresses accepted by the same validation rules as account registration.

**Actual before the fix:** Registration returned 422 because the email validator rejects the fixture's `.test` addresses.

**Resolution:** The NY-10 fixtures now use valid `example.com` addresses, which match the application's email validation rules. The fixture continues to use synthetic passwords and a disposable database when enabled. Relevant code: [the integration workflow](../tests/integration/test_authenticated_workflow.py).

**How to reproduce:** Configure `NOVAYIELD_TEST_MONGODB_URI` to point to an isolated test MongoDB, then run `python -m pytest tests/integration/test_authenticated_workflow.py -q`. The first registration request using `ny10-owner@example.test` fails with 422.

**Impact before the fix:** The opt-in suite stopped at account registration. Its current fixture addresses pass local validation; the tests remain skipped unless `NOVAYIELD_TEST_MONGODB_URI` points to a disposable database.

### Bug 4 — Persisted scoring percentages failed to deserialize from BSON Decimal128

**Bug:** Recommendation generation succeeded and Mongo contained two saved results, but `GET /api/v1/farms/{farm_id}/rotation-results` returned `500` when reading them.

**Cause:** Scoring uses Python `Decimal` for exact percentage weights. PyMongo stores these values as BSON `Decimal128` and returns `bson.decimal128.Decimal128` on read. Pydantic's `Decimal` validator does not accept that wrapper by default, so nested `equal_weight_percent` and `selected_weight_percent` fields could not be reconstructed.

**Resolution:** The scoring model now uses a shared `WeightPercent` type that converts BSON `Decimal128` to an exact Python `Decimal` before Pydantic validates it. It does not convert through float, so four-decimal percentage precision is preserved. A focused test builds a scored result, converts its decimals to `Decimal128` as Mongo does, and verifies the entire `ScoringResult` round-trip. The final live run read two saved results through history and retrieved an individual result successfully. Relevant code: [scoring models](../app/decisions/scoring.py) and [scoring round-trip test](../tests/test_rotation_scoring.py).

## Final verification after fixes

The final run used a loopback Uvicorn server with the actual `development` settings and configured `nova_yield` MongoDB database, plus real NASA POWER requests. Cookie `Secure` was disabled only for this local HTTP run; HTTPS cookie behavior was not exercised.

| Area | Final result |
| --- | --- |
| Contract and health | All 14 OpenAPI path templates and 16 operations were exercised. OpenAPI, Swagger, ReDoc, liveness, readiness, and CORS preflight for the configured origin passed. |
| Authentication | CSRF enforcement, registration, duplicate and invalid registration, valid and invalid login, current identity, anonymous rejection, persisted session expiry, logout revocation, and post-logout rejection passed. |
| Farm ownership | Create/list/detail/update passed. Invalid location and forged owner input were rejected. Another user could not read, update, or generate from the owner's farm. Farm and environmental responses omitted precise coordinates. |
| NASA POWER and persistence | Real NASA daily data was fetched for a cache miss; an equivalent request returned the cached snapshot; explicit refresh returned live/refreshed data. Three date windows were stored once and reused during rotation generation. |
| Source provenance | Live indicators returned `source: "NASA POWER"`, `source_scope: "provider"`, and provider source products `MERRA2` and `POWER`. No per-parameter product attribution was invented. |
| Rotation and results | Generation returned `201` with exactly three options and `ranking_status=ranked`. Repeating the same inputs reproduced the scoring signature and reused the same snapshot IDs. Two distinct results appeared in owner history; detail retrieval passed. Other-user history and result-IDOR requests returned `404`. |
| Response time | The first saved recommendation completed in 10.49 seconds in this local run, under the PRD's 60-second target. This is one synthetic-profile observation, not a production or load benchmark. |
| Cleanup | The test removed its two users, two farms, two results, sessions, and exactly three request-keyed NASA snapshots. Counts returned to baseline: 1 user, 0 farms, 0 snapshots, 0 results, 1 access token, and 3 supported locations. |
| Automated checks | `python -m pytest -q`: 171 passed, 9 skipped. `python -m ruff check app tests`: passed. |

## Coverage limits and follow-up

- Nine tests are opt-in Mongo integration tests and were skipped because they require an explicit disposable `NOVAYIELD_TEST_MONGODB_URI`. The live workflow was separately exercised against the authorized existing database, since this MongoDB principal cannot create/drop a separate test database namespace.
- NASA upstream failure, malformed upstream responses, and refresh-failure preservation cannot be forced through the real NASA service safely/reliably; their mocked tests are part of the passing automated suite. This run verified real successful retrieval, reuse, and refresh.
- The final local HTTP run does not verify `Secure` cookie behavior over HTTPS, production CORS settings, or concurrent/load performance.
- No Jira issues or comments were modified. This report records both the original defects and their verified resolutions.
