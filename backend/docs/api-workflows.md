# Authenticated API workflows (NY-9)

## Historical environmental context

`POST /api/v1/farms/{farm_id}/environmental-context` retrieves NASA POWER daily
precipitation and temperature indicators for a past date range at the selected
farm's supported-location reference point.

The request body is:

```json
{
  "start_date": "2020-04-01",
  "end_date": "2020-07-31",
  "force_refresh": false
}
```

The request does not accept coordinates or a user ID. The route first queries
the farm by both the path farm ID and the authenticated user's ID. Only after
that owner check does it resolve the farm's private location coordinates from
the supported-location catalog. A farm ID owned by someone else receives the
same `404 Farm not found` as a missing farm.

The NY-6 snapshot service checks MongoDB for the equivalent NASA request. A
valid stored snapshot is reused without another provider call; `force_refresh`
lets an authenticated caller explicitly request a refresh. NY-7 calculates
indicators from the returned persisted snapshot. The response includes the
human-readable location label, requested dates, per-indicator units, source,
coverage, resolution and live/cached/unavailable status, plus cache and
freshness metadata. It never includes the catalog coordinates, owner ID,
credentials, or the raw NASA response.

Date ranges must be supported by NASA POWER Daily (1981-01-01 onward), ordered,
and no later than today. This endpoint is historical environmental context,
not a weather forecast and not evidence that a farmer planted in that period.
The analysis periods in the [NY-9 calendar evidence handoff](../../analysis_docs/research/ny-9-pilot-season-calendar-evidence.md)
must not be interpreted as planting events.

For a valid request where NASA data is unavailable, the route returns the
structured response with `data_status: "unavailable"`, null indicator values,
an explicit `error_code`, and warnings. It never substitutes zero. Invalid
periods return `422`; an unauthenticated request returns `401`; a missing or
non-owned farm returns `404`; unavailable database/location dependencies return
a stable `503` response without driver details.

This is a state-changing `POST` because a cache miss may retrieve and persist
the snapshot. Browser callers using the cookie session must send the CSRF token
in `X-CSRF-Token`, following the existing [authentication flow](authentication.md).

## Rotation generation

`POST /api/v1/farms/{farm_id}/rotation-recommendations` separates past
farmer-reported history from future recommendation slots. Its request shape is
illustrated below. The dates are synthetic examples for the schema only; they
are not a crop calendar or planting advice.

```json
{
  "plot_reference": "plot-a",
  "force_refresh": false,
  "historical_seasons": [
    {
      "season_label": "2020 major",
      "analysis_start_date": "2020-04-01",
      "analysis_end_date": "2020-07-31",
      "planted_crop": "maize"
    },
    {
      "season_label": "2020 minor",
      "analysis_start_date": "2020-09-01",
      "analysis_end_date": "2020-10-31",
      "planted_crop": "cowpea"
    },
    {
      "season_label": "2021 major",
      "analysis_start_date": "2021-04-01",
      "analysis_end_date": "2021-07-31",
      "planted_crop": "yam"
    }
  ],
  "recommendation_seasons": [
    {
      "season_label": "future slot 1",
      "window_start": "2027-01-01",
      "window_end": "2027-01-31"
    },
    {
      "season_label": "future slot 2",
      "window_start": "2027-02-01",
      "window_end": "2027-02-28"
    },
    {
      "season_label": "future slot 3",
      "window_start": "2027-03-01",
      "window_end": "2027-03-31"
    }
  ]
}
```

The three `historical_seasons` are past reports. Their inclusive analysis dates
are the **only dates sent to NY-6/NASA POWER**; each cached response is reused
for NY-7 indicators. `planted_crop` is optional and may contribute to the
current-practice baseline only when all three reported crops are known.

The three `recommendation_seasons` are future NY-8 event slots. They are never
sent to NASA POWER. The API checks that they are future, ordered, and
non-overlapping, but does not treat user-entered dates as a reviewed
crop/community calendar. Until a sourced calendar is available, the generated
slots have unknown calendar status and candidate suitability remains under
review. A missing or incomparable criterion continues to withhold the overall
rank under Product Decision 6. The provisional crop evidence and its limits are
recorded in the [NY-8 crop-by-criterion matrix](../../analysis_docs/research/ny-8-crop-criterion-evidence-matrix.md).

`plot_reference` is a short safe identifier; coordinates, owner IDs, crop
rules, and weights are not accepted. The server uses the authenticated user's
farm priorities and supported-location reference point. NY-20 stores the exact
candidate-generation and scoring outputs; the route returns the saved result.
Because this POST may retrieve snapshots and always saves a result, browser
callers using the cookie session must send the CSRF token in `X-CSRF-Token`.

This is an orchestration contract, not a claim that the current evidence can
rank rotations. Farmer-reported history, future slots, and desk-research crop
traits retain their provisional or unknown status. The [evidence matrix](../../analysis_docs/research/ny-8-crop-criterion-evidence-matrix.md)
shows which criterion findings are crop- or sequence-specific and why they do
not yet form a comparable basis for every option. No unsupported hard
agronomic rule is applied. When NASA data is unavailable, null indicators and
the unavailable status remain visible in the saved result; values are never
fabricated.

The current NY-8 generator enumerates all 6³ combinations (216 sequences) and
does not choose a top-three shortlist. Until a reviewed selection method is
available, the endpoint preserves that output and withholds ranking rather
than arbitrarily selecting options. The farm profile stores no plot-level
history, so the farmer supplies the history for each request; it is retained
with the result and is not silently promoted to locally validated evidence.
