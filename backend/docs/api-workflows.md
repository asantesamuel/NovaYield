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

`POST /api/v1/farms/{farm_id}/rotation-recommendations` accepts three
chronological, non-overlapping farmer-reported past periods for one plot. The
farmer identifies the three consecutive seasons; the API does not infer season
boundaries from an unvalidated crop calendar. Each period has a label, inclusive
historical start/end dates strictly before today, and an optional planted crop
from the approved six-crop library. `plot_reference` is a short safe identifier such as `plot-a`;
coordinates, owner IDs, crop rules, and weights are not accepted. The server
uses the persisted farm's priority points and supported-location reference
point. If all three reported crops are known, they are retained as the
farmer-reported baseline; otherwise the baseline is absent.

For each period, NY-6 retrieves or reuses its matching persisted NASA snapshot
and NY-7 calculates indicators over the same dates. NY-8 receives those
indicators and the farm's persisted priorities. NY-20 stores the exact
candidate-generation and scoring outputs; the route returns the saved result.
Because this POST may retrieve snapshots and always saves a result, browser
callers using the cookie session must send the CSRF token in `X-CSRF-Token`.

This is an orchestration contract, not a claim that the current evidence can
rank rotations. Reported history is provisional, no locally reviewed planting
calendar is asserted by the request, the area-level candidate crop records have
unknown suitability, and the farm profile lacks labor/soil/yield evidence. The
four criteria therefore remain `not_assessed`, and the overall rank is
withheld. No unsupported hard agronomic rule is applied. When NASA data is
unavailable, null indicators and the unavailable status remain visible in the
saved result; values are never fabricated.

The current NY-8 generator enumerates all 6³ combinations (216 sequences) and
does not choose a top-three shortlist. Until a reviewed selection method is
available, the endpoint preserves that output and withholds ranking rather
than arbitrarily selecting options. The farm profile stores no plot-level
history, so the farmer supplies the history for each request; it is retained
with the result and is not silently promoted to locally validated evidence.
