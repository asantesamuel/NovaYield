# Supported location catalog

Farm profiles select a catalog `location_key`; they do not accept farmer-entered coordinates. A catalog record stores the public reference-point coordinates needed by NASA POWER, its display label, administrative context, source URL, and validation status. Farm responses and the future location-options endpoint expose only the key and label. The frontend displays the label; it must never display or log the coordinates.

These points are public inhabited-place references for area-level data lookup. They are **not** exact farm coordinates, field centroids, or evidence that every farm in the named community shares the point's conditions. All are selectable for the current limited demo, but their records remain marked `provisional` pending local verification.

| Key | Label | Administrative context | Latitude, longitude | Source |
| --- | --- | --- | --- | --- |
| `ejura` | Ejura | Ejura-Sekyedumase Municipality, Ashanti Region | `7.3856, -1.3562` | [Getty TGN record 1090118](https://www.getty.edu/vow/TGNFullDisplay?english=Y&find=&nation=&subjectid=1090118) |
| `anyinasu` | Anyinasu | Ejura-Sekyedumase Municipality, Ashanti Region | `7.23705, -1.57696` | [Mapcarta locality record](https://mapcarta.com/16954496), based on OpenStreetMap/GeoNames place data |
| `kintampo` | Kintampo | Kintampo North Municipal District, Bono East Region | `8.0537, -1.7289` | [Mapcarta locality record](https://mapcarta.com/16944928), based on OpenStreetMap place data |

Ejura is the provisional first pilot. Anyinasu is another candidate community in the selected municipality. Kintampo is a broader fallback point; the stored coordinate is for Kintampo town in Kintampo North, while NY-12's research brief also mentions Kintampo South. Confirm the intended fallback geography with local partners before presenting it as a validated regional alternative. The broader Upper East comparison remains a later expansion area, not one of these three current options.

## Seed and persistence

From `backend/`, after configuring `.env` and making MongoDB available, run:

```powershell
python -m app.farms.seed_locations
```

The seed command uses the app's shared Mongo connection and Beanie registry. It inserts only absent location keys, so rerunning it does not overwrite records that have been edited or reviewed. The `supported_locations` collection has a unique `location_key` index and an index for stable selectable-option ordering. Disable a location by setting `is_selectable` to `false`; farm creation/update must reject disabled or unknown keys.

The coordinate stays inside `SupportedLocation` in MongoDB. A farm document stores only its reference key. NASA ingestion may resolve that key internally to the coordinates; API DTOs remain coordinate-free. This keeps a reusable, centrally maintained point and avoids duplicating or trusting coordinates supplied by each user.

## Scope and validation

The farm feature router exposes a public `GET /api/v1/farms/locations` response with the stable keys, display labels, and a coverage notice explaining that NovaYield has not expanded to other parts of Ghana. Farm CRUD remains authenticated. NY-9 must mount `create_farm_router` into the versioned API and supply NY-11's `current_active_user` dependency.

The point source establishes a named-place coordinate, not local agronomic suitability or the accuracy of gridded NASA data at a particular farm. Verify the point and NASA grid metadata with local extension partners and source responses before making stronger claims. Add or change a location only with a sourced record and explicit pilot-scope review.
