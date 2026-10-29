# NASA POWER Snapshot Contract (NY-6)

This document records the NY-6 request identity, MongoDB persistence boundary, and cache/refresh behavior.

## Request identity

`build_snapshot_identity()` creates two keyed SHA-256 HMAC values:

- `location_key` identifies the exact latitude/longitude pair without persisting or returning the coordinates.
- `request_key` identifies the full provider request and adapter contract.

The request key includes NASA POWER provider/service/endpoint, `AG` community, normalized sorted parameter set, exact location identity, inclusive start/end dates, metric units, UTC time standard, and identity/adapter/document schema versions. It deliberately excludes crop and season-calendar context: two uses of the same environmental time series should be able to reuse the same snapshot. The document keeps those contextual uses separately so later reuse can add another context without changing the provider-data key.

Coordinates are not rounded to a presumed grid. NASA POWER exposes variables at their native source resolutions, and the requested precipitation and temperature parameters do not necessarily share one grid. Until returned grid identity can be established safely for the complete parameter set, exact-point identity avoids treating nearby farms as interchangeable. This may miss some possible same-grid reuse; it does not falsely merge locations.

The HMAC secret is supplied to the identity builder and must be stable across app instances for cache reuse. It must contain at least 32 bytes. Never log or store it. Rotating it intentionally changes all derived keys, which makes old records cache misses until a separately defined retention/cleanup policy handles them. Deployment configuration for this secret is a follow-up integration task; this model does not invent a development secret.

## Persisted document

`EnvironmentalSnapshot` stores the request identity, NASA URL without query coordinates, retrieval status/time, provider metadata, normalized daily/seasonal parameter series, and the season/crop context associated with each use. The unique index on `identity.request_key` prevents duplicate snapshot records. The model excludes raw coordinates and the raw provider response; the normalized result from NY-5 is the persisted payload.

A stored record's `retrieval_status` records that the original provider retrieval was live. A later cache-service response must report `cached` for a cache hit; it must not relabel the original retrieval or call cached values live.

## Repository boundary

`EnvironmentalSnapshotRepository.find_by_identity()` retrieves the document by its opaque request key and returns the persisted parameter series for downstream NY-7 processing. It does not call NASA. `insert_if_absent()` checks first, inserts on a miss, and recovers from a duplicate-key race by returning the winning document. A short-lived MongoDB request lease is acquired before a NASA call so concurrent requests in separate API processes coordinate on the same opaque request key; an in-process lock avoids duplicate work within one process. The lease expires if a worker terminates unexpectedly and its expiry index is TTL-cleaned. The lease is coordination metadata, not environmental or farm data. `add_request_context()` uses MongoDB `$addToSet` so repeated crop/season context is not duplicated.

Database driver errors are converted to safe repository exceptions; connection details and driver messages are not exposed. These repository operations require NY-4's Beanie initialization and the registered snapshot model.

## Cache and refresh behavior

No fixed TTL is encoded in this schema. NASA reports that GEOS-IT daily meteorological data is appended daily and generally becomes available around two days after real time; MERRA-2 values in the series are typically updated every several months. Precipitation and temperature metadata can identify differing sources, so one universal interval would not be evidence-based. See NASA's [meteorological data-source notes](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) and [data latency FAQ](https://power.larc.nasa.gov/docs/faqs/data/).

`EnvironmentalSnapshotService.retrieve()` returns a matching stored snapshot without calling NASA unless it is stale under a configured source policy or the caller explicitly requests refresh. The response distinguishes `live`, `cached`, and `unavailable` data, reports freshness as `fresh`, `stale`, or `unknown`, and states whether a refresh was attempted. A cache hit also returns the stored normalized values directly for later processing; it does not require an upstream request.

No source refresh interval is enabled by default. NY-13 records NASA update behavior that differs by source: daily GEOS-IT meteorological values are generally appended around two days behind real time, while MERRA-2 values are typically updated every several months. The NY-13 specification explicitly leaves the cache freshness policy for product/backend approval. Therefore, until source-specific intervals are approved and configured, a matching snapshot has `unknown` freshness and is reused; an explicit refresh can request new values. This is a deliberate no-implicit-TTL behavior, not a claim that the snapshot is current. The age remains available in the freshness assessment.

When a configured source interval has elapsed, the service attempts refresh. If NASA fails, it retains and returns the previous snapshot labeled `cached`, with stale/unknown freshness and a warning. If no snapshot exists and retrieval fails, the outcome is `unavailable`; the service never fabricates a fallback. If another process currently owns the request lease, a stored snapshot can be served with `refresh_in_progress`; without one, the caller receives an unavailable/in-progress result and can retry. Lease coordination is bounded by the lease duration, which must exceed the NASA HTTP client's timeout.

The service accepts an injectable per-source refresh policy. Configure one only after the team approves the source-specific interval; do not supply a universal fixed TTL. Minimum coverage and source freshness policy remain open product/backend decisions in NY-13, and no coverage threshold is silently selected here.

## Research source and open points

The team-provided NY-13 specification is preserved in [`analysis_docs/research/ny-13-nasa-power-input-specification.md`](../../analysis_docs/research/ny-13-nasa-power-input-specification.md). The pilot point and crop-specific seasonal windows remain provisional pending local validation. This module does not add a route, authorize farm access, store farm IDs, or decide agronomic recommendations. Later authenticated farm workflows must authorize access before requesting or returning a snapshot.

The current NY-5 result carries season label, crop, and calendar version, but it does not carry the local municipality/community label. Add that context only when the farm/environmental service has a source-of-truth field; do not infer it from coordinates or NASA's `AG` API community. The NY-6 service/repository are not yet exposed through an authenticated farm API route; downstream route work must enforce farm ownership before accessing a snapshot.
