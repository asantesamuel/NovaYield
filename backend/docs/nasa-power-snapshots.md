# NASA POWER Snapshot Contract (NY-6)

This document records the NY-6 request identity, MongoDB persistence boundary, and cache/refresh behavior.

## Request identity

`build_snapshot_identity()` creates two keyed SHA-256 HMAC values:

- `location_key` identifies the exact latitude/longitude pair without persisting or returning the coordinates.
- `request_key` identifies the full provider request and adapter contract.

The request key includes NASA POWER provider/service/endpoint, `AG` community, normalized sorted parameter set, exact location identity, inclusive start/end dates, metric units, UTC time standard, and identity/adapter/document schema versions. It deliberately excludes crop and season-calendar context: two uses of the same environmental time series should be able to reuse the same snapshot. The document keeps those contextual uses separately so later reuse can add another context without changing the provider-data key.

Coordinates are not rounded to a presumed grid. NASA POWER exposes variables at their native source resolutions, and the requested precipitation and temperature parameters do not necessarily share one grid. Until returned grid identity can be established safely for the complete parameter set, exact-point identity avoids treating nearby farms as interchangeable. This may miss some possible same-grid reuse; it does not falsely merge locations.

The HMAC secret is supplied to the identity builder and must be stable across app instances for cache reuse. It must contain at least 32 bytes. Never log or store it. Rotating it intentionally changes all derived keys, which makes old records cache misses until a separately defined retention/cleanup policy handles them. NY-9 reads it from `NOVAYIELD_LOCATION_HASH_SECRET`; provide a stable private value in the backend environment, separate from the CSRF key. The committed `.env.example` documents how to generate a local value without containing a real secret.

## Application resource lifecycle

The FastAPI lifespan creates one reusable `httpx.AsyncClient` for NASA POWER requests, wraps it in the NY-5 client/service, and shares one NY-6 snapshot service through app state. The lifespan closes the HTTP client and MongoDB connection at shutdown. The snapshot service receives the stable location-hash key from settings; it does not persist raw coordinates.

## Persisted document

`EnvironmentalSnapshot` stores the request identity, NASA URL without query coordinates, retrieval status/time, provider metadata, normalized daily/seasonal parameter series, and the season/crop context associated with each use. The unique index on `identity.request_key` prevents duplicate snapshot records. The model excludes raw coordinates and the raw provider response; the normalized result from NY-5 is the persisted payload.

A stored record's `retrieval_status` records that the original provider retrieval was live. A later cache-service response must report `cached` for a cache hit; it must not relabel the original retrieval or call cached values live.

## Repository boundary

`EnvironmentalSnapshotRepository.find_by_identity()` retrieves the document by its opaque request key and returns the persisted parameter series for downstream NY-7 processing. It does not call NASA. `insert_if_absent()` checks first, inserts on a miss, and recovers from a duplicate-key race by returning the winning document. A short-lived MongoDB request lease is acquired before a NASA call so concurrent requests in separate API processes coordinate on the same opaque request key; an in-process lock avoids duplicate work within one process. The lease expires if a worker terminates unexpectedly and its expiry index is TTL-cleaned. The lease is coordination metadata, not environmental or farm data. `add_request_context()` uses MongoDB `$addToSet` so repeated crop/season context is not duplicated.

Database driver errors are converted to safe repository exceptions; connection details and driver messages are not exposed. These repository operations require NY-4's Beanie initialization and the registered snapshot model.

## Cache and refresh behavior

No fixed TTL is encoded in this schema. NASA reports that GEOS-IT daily meteorological data is appended daily and generally becomes available around two days after real time; MERRA-2 values in the series are typically updated every several months. Precipitation and temperature metadata can identify differing sources, so one universal interval would not be evidence-based. See NASA's [meteorological data-source notes](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) and [data latency FAQ](https://power.larc.nasa.gov/docs/faqs/data/).

`EnvironmentalSnapshotService.retrieve()` returns a matching stored snapshot without calling NASA unless it is stale under a configured source policy or the caller explicitly requests refresh. The response distinguishes `live`, `cached`, and `unavailable` data, reports freshness as `fresh`, `stale`, or `unknown`, and states whether a refresh was attempted. A cache hit also returns the stored normalized values directly for later processing; it does not require an upstream request.

The approved NY-38/NY-39/NY-40 policy now configures three publication checks in the app lifespan: a three-day check for a period retrieved before expected first publication, a 60-day check for possible replacement of GEOS-IT by MERRA-2, and a 30-day recheck while a post-replacement GEOS-IT snapshot remains. The values are configurable with `NOVAYIELD_NASA_RECENT_PUBLICATION_LAG_DAYS`, `NOVAYIELD_NASA_GEOS_IT_REPLACEMENT_LAG_DAYS`, and `NOVAYIELD_NASA_GEOS_IT_RECHECK_INTERVAL_DAYS`. They are operational checks informed by [NASA POWER service guidance](https://power.larc.nasa.gov/docs/services/), not guaranteed publication deadlines. Old matching MERRA-2 history has no universal expiry; absent a documented correction or explicit refresh, its freshness may be `unknown` and the stored data is reused with its retrieval age visible.

If an automatic refresh fails, the service retains and returns the previous snapshot labeled `cached`, with stale freshness and a safe warning. It stores only a failure class and retry timestamps in `auto_refresh_retry`; subsequent automatic calls return `refresh_deferred` during the configurable 30-minute default backoff (`NOVAYIELD_NASA_REFRESH_FAILURE_BACKOFF_MINUTES`). A requested `force_refresh` bypasses that delay. A successful replacement clears the retry marker. If no snapshot exists and retrieval fails, the outcome is `unavailable`; the service never fabricates a fallback. If another process currently owns the request lease, a stored snapshot can be served with `refresh_in_progress`; without one, the caller receives an unavailable/in-progress result and can retry. Lease coordination is bounded by a duration longer than the NASA HTTP client's timeout.

An injectable per-source correction interval remains available for a documented future source policy. No numeric minimum-coverage threshold is silently selected: partial daily series preserve missing values and coverage, and NY-40 withholds a decision feature that requires complete reference windows.

## Research source and access boundary

The [NY-13 specification](../../analysis_docs/research/ny-13-nasa-power-input-specification.md) and [NY-38 handoff](../../analysis_docs/research/ny-38-research-handoff.md) define the current research and product limits. This snapshot module does not expose data directly or decide crop suitability. The authenticated Farm workflow checks ownership, derives the actual-history period, then invokes this service. NY-40 may request a distinct 1991–2020 reference snapshot through the same service only when scoped crop-stage and calendar evidence can use it. The supported-location record supplies a public place identity and private provider point; neither NASA's `AG` community nor coordinates are used to infer a municipality or a field measurement.
