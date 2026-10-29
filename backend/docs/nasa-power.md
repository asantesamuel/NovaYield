# NASA POWER Daily Integration (NY-5)

NY-5 owns a non-persistent NASA POWER Daily Point integration. It provides the primary historical P0 inputs identified by NY-13. It does not select crop seasons, invent a pilot coordinate, write MongoDB documents, cache responses, use sample fallback data, or make agronomic recommendations.

## Request contract

`PowerRequest` requires a latitude, longitude, and inclusive date range. The caller must supply a location that is approved for its use: a validated municipality/community demonstration point or an authorized farm location. There is no default coordinate. The request validator enforces geographic bounds, NASA POWER's daily-data start date of 1981-01-01, start-before-or-equal-to-end, and no future end date.

The client calls `https://power.larc.nasa.gov/api/temporal/daily/point` with:

| Parameter | Value |
| --- | --- |
| `community` | `AG` (Agroclimatology) |
| `parameters` | `PRECTOTCORR,T2M,T2M_MAX` |
| `format` | `JSON` |
| `units` | `metric` |
| `time-standard` | `UTC` |
| `start`, `end` | Inclusive `YYYYMMDD` dates |

POWER Daily defaults to Local Solar Time unless the request explicitly sets UTC. NASA documents JSON point responses, the date availability and parameter limits, and its source-native spatial resolution behavior in the [Daily API reference](https://power.larc.nasa.gov/docs/services/api/temporal/daily/). The current [OpenAPI schema](https://power.larc.nasa.gov/api/temporal/daily/openapi.json) places daily series under `properties.parameter`, parameter units/long names under `parameters`, and the fill sentinel in `header.fill_value`.

## Normalized output

`NASAPowerService.retrieve()` returns a `PowerResult` with:

- Provider/service, retrieval timestamp, live retrieval status, UTC time standard, and static NASA POWER source URL (the URL contains no query coordinates).
- Date window, with optional caller-provided season label, calendar version, and crop context. The integration does not choose or validate a local planting calendar.
- NASA API title/version/source products and any per-parameter source/resolution metadata available in the response. It does not return requested or returned point coordinates. If NASA provides only a source-native-resolution label, the integration preserves that wording and does not invent a numeric grid size.
- One daily value for each date in the inclusive range and each required parameter. A missing key or the response's `header.fill_value` becomes `None`, never zero.
- A window summary: sum of valid `PRECTOTCORR` days (reported as `mm/season` when NASA metadata says `mm/day`), arithmetic mean of valid `T2M` values, and arithmetic mean of valid daily `T2M_MAX` values. `T2M_MAX` is not the hottest value of the whole period.
- Per-parameter expected, valid, missing, and percentage coverage, plus `complete`, `partial`, or `unavailable` status. Partial summaries use only valid values and include a warning; zero valid values produce a null result. No interpolation, imputation, fallback, or minimum decision-coverage threshold is applied.

The normalized service result intentionally omits exact coordinates. It is an internal service output, not a public route response or persistence model. A later route must apply the project's location-access policy before exposing location details. NY-6 owns stable request identity, response reuse, and persistence.

## Typed failures and transport ownership

- `PowerRequest` validation errors identify invalid coordinates/date windows before a network call.
- `PowerTimeoutError` represents client timeouts; `PowerTransportError` represents other network failures.
- `PowerHTTPError` includes the HTTP status but not NASA's response body or request URL, which could contain sensitive coordinates.
- `PowerMissingParameterError`, `PowerUnsupportedUnitsError`, and `PowerMalformedResponseError` distinguish missing variables/metadata, unrecognized units, and invalid JSON/data shape.
- Individual fill/missing days are represented in coverage and daily series, not raised as request-level exceptions.

`NASAPowerHttpClient` receives an injected `httpx.AsyncClient`; its caller owns the HTTP client's lifetime. `create_nasa_power_http_client()` supplies an explicit 30-second default timeout. A later application integration should create one reusable client in the FastAPI lifespan and close it on shutdown. Tests inject an in-memory mock client, not live NASA calls.

## Research limits carried forward

- Ejura-Sekyedumase remains a provisional pilot area. This module does not embed coordinates or represent NASA grid data as station/plot measurements.
- NY-12/NY-13 require validating representative points, variable metadata, units, fill values, and spatial information with an approved point. No project coordinate was present in the attached research notes, so this implementation does not make a live NASA request.
- NASA metadata is authoritative at runtime. If units are missing or do not match the supported metric forms for the required indicators, the service fails explicitly rather than silently converting or relabeling values.
- The client does not cache or persist. NASA asks clients to avoid repeatedly requesting the same relative grid location; NY-6 is the ticket responsible for reuse.
