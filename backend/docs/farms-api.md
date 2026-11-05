# Farm and supported-location API (NY-19)

The farm feature owns an `APIRouter` factory in `app/farms/routes.py`. NY-9 mounts it under the configured API v1 prefix and supplies the current-active-user dependency created by NY-11. Until NY-9 mounts the router, these routes will not appear in the running application's OpenAPI page.

## Browse the supported locations

`GET /api/v1/farms/locations` is public so the frontend can explain coverage before a user creates a profile. The response contains only stable keys, display labels, and the approved coverage notice; it never returns the internal reference coordinates.

```json
{
  "coverage_notice": "NovaYield currently supports only the locations listed here. Coverage has not yet expanded to other parts of Ghana.",
  "locations": [
    {"location_key": "ejura", "label": "Ejura"},
    {"location_key": "anyinasu", "label": "Anyinasu"},
    {"location_key": "kintampo", "label": "Kintampo"}
  ]
}
```

The UI should show `label`; it sends `location_key` when creating or changing a farm.

## Farm endpoints

All farm endpoints require the authenticated user's session cookie:

| Method and path | Purpose | Success |
| --- | --- | --- |
| `POST /api/v1/farms` | Create a farm owned by the signed-in user | `201` |
| `GET /api/v1/farms` | List only that user's farms | `200` |
| `GET /api/v1/farms/{farm_id}` | Read one owned farm | `200`; `404` if absent or not owned |
| `PATCH /api/v1/farms/{farm_id}` | Update one owned farm | `200`; `404` if absent or not owned |

There is no farm delete endpoint in this ticket. A farm profile uses the catalog key instead of client-supplied coordinates or owner IDs:

```json
{
  "name": "North field",
  "location_key": "ejura",
  "soil_texture": "sandy loam",
  "irrigation_access": "rain-fed",
  "previous_crops": ["maize", "cowpea"],
  "current_practice": "maize followed by cowpea",
  "farmer_priorities": {
    "water_resilience": 25,
    "soil_health_potential": 25,
    "yield_stability_proxy": 25,
    "labor_feasibility": 25
  }
}
```

`current_practice` is optional and must be a non-empty string when supplied; omit it when unknown. Optional fields can be set to `null` in a patch to clear them. `name`, `location_key`, and `farmer_priorities` cannot be cleared.

The response contains a string farm ID, the selected key/label, profile inputs, priorities, and timestamps. It omits `owner_user_id`, the catalog coordinates, and internal source metadata. A location that is later disabled remains resolvable for its existing farm profiles, but cannot be selected for new or changed profiles.

## Browser session and CSRF

Registration and login use the NY-11 cookie session. Before a state-changing request, the browser gets the CSRF cookie from `GET /api/v1/auth/csrf`, sends credentials on the request, and copies the readable `nova_yield_csrf` cookie into the `X-CSRF-Token` header. `POST /farms` and `PATCH /farms/{farm_id}` require this header when the session cookie is present. The session cookie itself is HttpOnly and is not read by frontend JavaScript.

## Client-safe errors

- `401`: no valid active session for a farm operation.
- `404` with `Farm not found.`: the ID is missing or belongs to another user; the API does not distinguish those cases.
- `422`: request fields are invalid or the location key is missing/disabled. Validation responses omit submitted raw values, so coordinates or other request content are not echoed.
- `500` with a generic location error: an existing farm references a missing catalog record. The response contains no catalog coordinates.
