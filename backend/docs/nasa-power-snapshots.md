# NASA POWER Snapshot Contract (NY-6)

This document records the NY-6 request identity and MongoDB persistence boundary. The cache/refresh policy remains a follow-up subtask.

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

`EnvironmentalSnapshotRepository.find_by_identity()` retrieves the document by its opaque request key and returns the persisted parameter series for downstream NY-7 processing. It does not call NASA. `insert_if_absent()` checks first, inserts on a miss, and recovers from a duplicate-key race by returning the winning document. The unique index prevents duplicate records, but it cannot prevent two workers from both calling NASA before either writes; per-request coordination belongs in the cache-service subtask. `add_request_context()` uses MongoDB `$addToSet` so repeated crop/season context is not duplicated.

Database driver errors are converted to safe repository exceptions; connection details and driver messages are not exposed. These repository operations require NY-4's Beanie initialization and the registered snapshot model.

## Freshness remains a separate policy decision

No fixed TTL is encoded in this schema. NASA reports that GEOS-IT daily meteorological data is appended daily and generally becomes available around two days after real time; MERRA-2 values in the series are typically updated every several months. Precipitation and temperature metadata can identify differing sources, so one universal interval would not be evidence-based. See NASA's [meteorological data-source notes](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) and [data latency FAQ](https://power.larc.nasa.gov/docs/faqs/data/).

The cache-service subtask must define explicit refresh behavior from the stored parameter/source metadata, allow a configured policy, expose freshness and cached status, support a caller-requested refresh, and preserve the last valid snapshot if NASA refresh fails. NY-13 leaves minimum coverage and cache freshness policy for product/backend approval; this subtask does not silently choose either threshold.

## Research source and open points

The team-provided NY-13 specification is preserved in [`analysis_docs/research/ny-13-nasa-power-input-specification.md`](../../analysis_docs/research/ny-13-nasa-power-input-specification.md). The pilot point and crop-specific seasonal windows remain provisional pending local validation. This module does not add a route, authorize farm access, store farm IDs, or decide agronomic recommendations. Later authenticated farm workflows must authorize access before requesting or returning a snapshot.

The current NY-5 result carries season label, crop, and calendar version, but it does not carry the local municipality/community label. Add that context only when the farm/environmental service has a source-of-truth field; do not infer it from coordinates or NASA's `AG` API community.
