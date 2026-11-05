# NY-10 Live Endpoint and Database Verification

**Run date:** 4 November 2026  
**Result:** Partial pass; recommendation-result persistence is blocked by a confirmed defect.  
**Purpose:** Exercise the assembled API against an isolated local MongoDB and the real NASA POWER Daily Point service.

## Safety and fixture manifest

- The checked-in `backend/.env` selects a production environment and remote Atlas database. That configuration was not used for any write or test request.
- Each live run supplied explicit in-memory test settings (`environment=test`), started a local MongoDB process bound to loopback, and used a unique `ny10_*` database. The database and temporary files were dropped after each run.
- The application was invoked through its real FastAPI ASGI app and lifespan. The NASA adapter used its real HTTP client and called NASA POWER; it was not mocked.
- The test fixture used two synthetic accounts and two synthetic Ejura farm records created through the API. Their generated identifiers and passwords were not retained in this report. No fixture records remain in MongoDB.
- The reported historical dates and crop history came from the explicitly synthetic NY-10 fixture. They do not describe an actual farm or validated planting history. The public Ejura catalog point is not a farm coordinate or local agronomic validation. See [the NY-8 profile caveats](../../analysis_docs/research/ny-8-public-demo-profile.md) and the canonical [research and product decisions](../../novayield-research-and-product-decisions.md), §6.
- Live requests used the approved catalog selection by label. Exact coordinates, credentials, raw provider payloads, and Mongo connection strings are intentionally omitted.

## Results

| Area | Observed result |
| --- | --- |
| Mongo readiness and health | Local test Mongo ready; `GET /health/live` → 200; `GET /health/ready` → 200. |
| Authentication | Two accounts registered (201), logged in (204), and resolved through `/api/v1/auth/me` (200). Farms without a session were rejected (401). Expired sessions were rejected (401); logout returned 204 and the following identity request returned 401. |
| Farm APIs | Create 201, list 200, read 200, update 200. Invalid location returned 422. Another account's farm read, update, and environmental request returned 404. Public farm responses did not include coordinate fields. |
| Date validation | An end date before the start date returned 422 and made no NASA request. |
| Real NASA POWER retrieval | `POST /api/v1/farms/{farm_id}/environmental-context` for 1–3 April 2022 returned 200, `data_status=live`, and `cache_action=miss`. All three parameters had 3/3 valid days (100% coverage). |
| Live indicator values | Seasonal precipitation: 14.39 mm/season; mean daily air temperature: 27.5033 °C; mean daily maximum air temperature: 32.44 °C. These are NASA POWER point/grid values for the requested period, not farm measurements. |
| Snapshot persistence and reuse | The first request stored the normalized snapshot in the isolated MongoDB. An equivalent follow-up returned 200, `data_status=cached`, `cache_action=hit`, and made zero additional NASA calls. An explicit refresh returned `live/refreshed` and issued one new NASA request. |
| Recommendation workflow | Generation returned 503 after retrieving and storing three historical snapshots. Mongo held 3 environmental snapshots but 0 rotation results at cleanup. The internal test runner traced the failed insert to the farm update timestamp being timezone-naive after Mongo readback. |
| Result history and detail | Empty owner history returned 200. Unknown result IDs returned 404. A cross-account lookup using another account's farm returned 404. **Cross-account retrieval of an existing result remains unverified because generation did not persist any result.** |
| Repeatability and demo latency | A successful recommendation response was not produced, so this run could not verify the saved result's repeatability, top-three response, or the PRD's 60-second end-to-end target. The live environmental-context request took about 2.1 seconds in one run; that is not a full-workflow benchmark. |

NASA's real response header reported source products `MERRA2` and `POWER`, and the resolution label `NASA/POWER Source Native Resolution Daily Data`. Its per-parameter metadata contained `longname` and `units`, but no per-parameter `source` field. The API currently exposes each indicator's `source` as null, so the available provider-level source list is not represented in the indicator provenance.

## Confirmed bug reports

### Bug 1 — Recommendation result cannot be persisted after Mongo readback

**Bug:** Generating a rotation recommendation for an owned farm returns a safe 503 instead of saving and returning the result.

**Expected:** The API returns 201 with the generated recommendation persisted in the user's result history.

**Actual:** `POST /api/v1/farms/{farm_id}/rotation-recommendations` returns `503` with `The rotation result could not be saved. Please retry.` The live NASA snapshots are already in Mongo. The isolated test runner traced the insert failure to `FarmDecisionInputSnapshot.farm_updated_at`: Beanie/PyMongo returned the farm's `updated_at` as timezone-naive, while the snapshot validator rejects naive timestamps. Relevant code: [Farm](../app/models/farms.py), [result input snapshot](../app/models/rotation_results.py), and [NY-9 workflow](../app/api/workflows.py).

**How to reproduce:** With an isolated test MongoDB, register and log in, create a farm using `{"name":"NY-10 synthetic test farm","location_key":"ejura"}`, then POST a valid NY-10 recommendation request to `/api/v1/farms/{created_farm_id}/rotation-recommendations`. Use the fixed historical windows from [the integration fixture](../tests/integration/demo_profile.py); future recommendation slots can be generated by its `recommendation_request()` helper.

**Impact:** The core recommendation flow cannot complete, the result-history feature receives no new results, and NY-10 cannot verify a saved recommendation or successful end-to-end latency.

### Bug 2 — Live indicator response omits available NASA source provenance

**Bug:** Live environmental indicators contain `source: null` even though NASA returns provider-level source metadata.

**Expected:** The response preserves traceable source provenance for each indicator, while accurately describing whether NASA supplied it at parameter or response-header level.

**Actual:** All three live indicators had `source: null`. NASA's response header contained `sources: ["MERRA2", "POWER"]`, but each parameter metadata object lacked a `source` key. The adapter stores header source products in provider metadata, while the indicator calculation reads only the parameter-level field. Relevant code: [NASA POWER normalization](../app/integrations/nasa/power.py) and [indicator calculation](../app/indicators/environmental.py).

**How to reproduce:** Create and authenticate an account, create an Ejura farm, then POST `{"start_date":"2022-04-01","end_date":"2022-04-03"}` to `/api/v1/farms/{farm_id}/environmental-context` against the live NASA client. Inspect `indicators[*].source` and the provider response header metadata.

**Impact:** A farmer or reviewer cannot see the source product on the indicator itself, weakening the provenance required by NY-5/NY-7 and the frontend workflow. Do not arbitrarily label each parameter as `MERRA2` or `POWER`; the live response does not establish a single per-parameter product attribution.

### Bug 3 — NY-10 real-Mongo integration accounts use email addresses rejected by validation

**Bug:** The opt-in NY-10 real-Mongo integration suite cannot register its configured `example.test` accounts with the current email validator.

**Expected:** The prepared integration fixture uses synthetically unique addresses accepted by the same validation rules as account registration.

**Actual:** Registration returns 422 because `EmailStr` treats `.test` as a reserved/special-use domain. The existing fixture uses addresses such as `ny10-owner@example.test` in [the integration workflow](../tests/integration/test_authenticated_workflow.py). This was independently reproduced by validating those addresses with `RegistrationRequest`; the live endpoint run used synthetic `example.com` addresses to continue testing.

**How to reproduce:** Configure `NOVAYIELD_TEST_MONGODB_URI` to point to an isolated test MongoDB, then run `python -m pytest tests/integration/test_authenticated_workflow.py -q`. The first registration request using `ny10-owner@example.test` fails with 422.

**Impact:** The reusable NY-10 integration suite stops before testing the workflow whenever its real-Mongo tests are enabled, so it cannot provide its intended verification evidence until the fixture emails match the API's validator.

## Coverage limits and follow-up

- NASA success, persisted snapshot reuse, explicit refresh, and invalid-date rejection were exercised live. NASA upstream failure and refresh-failure preservation were not forced against the live provider; those failure modes remain covered only by the existing mocked integration tests.
- The result service's successful save/history/detail path, actual-result cross-account IDOR, and successful generation latency need a rerun after Bug 1 is fixed.
- This report does not change backend feature logic or Jira. It records test findings for follow-up work.
