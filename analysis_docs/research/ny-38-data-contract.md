---
title: NY-38 proposed data dictionary and API contract
status: Research proposal for Product Owner review; no schema has been changed
version: 0.1
prepared: 2026-11-05
baseline: dev at 78e0589
---

# NY-38 Proposed Data Dictionary and API Contract

This is the proposed storage and interface contract for NY-39 and NY-40. It is not an existing MongoDB schema, a migration, or approval to populate crop traits. The [research handoff](ny-38-research-handoff.md) explains the product decisions and the [evidence and method specification](ny-38-crop-climate-evidence.md) explains which values can be populated. The original *NovaYield MVP PRD* and the [canonical decision record](../../novayield-research-and-product-decisions.md), especially Decisions 13 and 14, take precedence over this proposal.

## 1. Conventions and versions

- **One decision plot per Farm is proposed, awaiting Product Owner confirmation.** The existing Farm ID then identifies the plot for its ordered history. Multi-plot support would require a separate Plot identity and history ownership boundary.
- Mongo `_id` and internal references use `ObjectId`, consistent with [NY-4 persistence conventions](../../backend/docs/persistence-conventions.md). The API exposes stable string `crop_key`, `location_key`, and reference-option keys; a server resolves each key to an active Mongo document. `crop_key` is immutable across deployments. A crop rename changes its label, not its key.
- Every stored document proposed below has `schema_version`. Published crop profile and calendar revisions are immutable; an update creates a new revision. A result pins exact revision IDs and copies the inputs/assessments it used so a later catalog edit cannot silently rewrite its explanation.
- `unknown` means the value is not known; `not_assessed` means no rule assessed it; `provisional` means a source supports a scoped hypothesis without local validation; `locally_reviewed` requires a named reviewer and date. These states must remain distinct from numeric zero.
- The API returns labels and dates, but never private coordinates, owner IDs, session secrets, or raw provider payloads. Existing owner-scoped repository queries remain mandatory for Farm and RotationResult.

**Dictionary legend:** `R` = required to store the record; `C` = required when the stated condition applies; `O` = optional and nullable. Privacy: `public` = catalog/reference data; `private` = an owner's farm input; `internal` = service/provider data; `result` = owner-only decision record. `v1` means an existing field, `v2 add` an additive proposal, `new` a new document, and `v2 deprecated` a retained legacy field that new logic must not infer from. All dates below are ISO calendar dates; all timestamps are UTC instants.

## 2. Canonical crop catalog

The six approved **recommendation candidates** are `maize`, `cowpea`, `groundnut`, `cassava`, `yam`, and `rice` ([Decision 2](../../novayield-research-and-product-decisions.md#decision-2--candidate-crop-library)). The same `crops` collection supplies selectable history crops and recommendation candidates. A separate frontend crop list and free-text history crop are not valid sources of identity. Whether extra `history_only` records may be added for plantain, sorghum, or another locally reported crop requires Product Owner review; it does not automatically expand the six recommendation candidates.

### `crops` identity collection

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `_id` | ObjectId, stable internal document reference | Mongo; R | public | new; never recycle |
| `schema_version` | string, identity schema revision | Backend contract; R | public | new `crop-identity-v1` |
| `crop_key` | immutable unique slug, e.g. `maize`; API selection ID | Approved candidate list or later approved history-only addition; R | public | new; unique index; never rename |
| `common_name` | display name, e.g. `Maize` | Cited catalog/taxonomy; R | public | new; edits do not alter key |
| `local_names` | list of `LocalName` records below; an empty list means unverified | Locally sourced terminology; O | public display / internal review provenance | new; no invented translation |
| `scientific_name` | taxon name or explicit genus-level designation where species varies | Taxonomic source; C when known | public | new; `yam` may stay *Dioscorea* spp.; no guessed species |
| `family` | botanical family string | Taxonomic source; C when known | public | new; version if taxonomy changes |
| `history_selectable` | boolean, whether the API offers this crop for a reported event | Product catalog policy; R | public | new; existing history remains valid after deactivation |
| `recommendation_candidate` | boolean, whether the engine may consider it | Decision 2 plus scoped eligibility review; R | public | new; only six approved keys can initially be true |
| `catalog_status` | `active` / `inactive` / `needs_review` | Catalog governance; R | public | new; never delete an identity referenced by history |
| `created_at`, `updated_at` | UTC timestamps of identity record changes | Database; R | internal | new; audit fields |

The unique index is `crop_key`; `history_selectable` and `recommendation_candidate` support catalog filtering. A recommendation must still check the resolved profile, production system, calendar and evidence status; the candidate flag alone is not a suitability claim.

| `LocalName` field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `language_tag`, `name` | BCP-47 language tag and nonempty local display name | Local language source; R for a populated record | public | new; no machine-guessed translation |
| `source_url`, `reviewer_ref` | nullable public source URL or internal reviewer ID; at least one required for a populated name | Source/reviewer; C for a populated name | public URL / internal reviewer ID | new; preserve earlier spelling evidence without publishing reviewer PII |
| `recorded_at` | UTC capture instant | Catalog audit; R | internal | new; retain revision history |
| `review_status` | `unverified` / `locally_reviewed` | Evidence review; R | public | new; local review requires `reviewer_ref` |

### `crop_profile_revisions` collection

One immutable revision is scoped to one crop, variety (or explicitly unspecified variety), and production system. A generic crop identity must not inherit a named variety's duration, water need, heat limit, or residue effect.

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `_id`, `schema_version` | ObjectId and profile schema string | Mongo/backend; R | public | new; `crop-profile-v1` |
| `crop_id` | ObjectId reference to `crops._id` | Resolved canonical crop; R | public | new; application validates existence |
| `revision` | monotonically increasing integer within crop/variety/system | Catalog publication process; R | public | new; immutable after publication |
| `is_active` | boolean; whether this revision is the selected one **for its exact variety/system scope** | Catalog publication process; R | public | new; deactivation never deletes a revision used by a result |
| `variety_key` | stable variety key or null for an unspecified variety | CSIR/MoFA/local source; O | public | new; null never inherits a named variety's traits |
| `production_system_key` | scoped system such as `upland`, `rainfed_lowland`, `irrigated`, or null | Source and farmer/system evidence; O | public | new; rice water traits require a known ecology |
| `maturity_days` | `EvidenceValue<{min_days,max_days,meaning}>` or null; days from stated starting event to stated maturity/harvest endpoint | Named variety/system source; O | public | new; invalid zero/reversed ranges stay null with source note |
| `growth_stages` | ordered list of `GrowthStage` records defined below | Crop/variety/stage research; O | public | new; missing stage placement/duration remains null |
| `decision_traits` | closed nullable `DecisionTraits` object defined below | Trait-specific research; O | public | new; no default trait from family alone |
| `evidence_status` | `unknown` / `provisional` / `locally_reviewed` / `conflicted` | Evidence review; R | public | new; conflict blocks affected assessment |
| `published_at`, `reviewer_ref` | UTC publication instant; reviewer ID or null | Catalog governance; C when published/reviewed | internal | new; reviewer null for desk evidence |

Unique revision index: `(crop_id, variety_key, production_system_key, revision)`. A partial unique index on `(crop_id, variety_key, production_system_key)` where `is_active=true` permits one active revision **per scope**, not one for an entire crop. An unpublished profile has no active revision; a new revision may become active only through the reviewed publication workflow, while older revisions remain readable for stored results. Stage and trait values use this envelope:

| `EvidenceValue` field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `value`, `unit` | Typed value and unit; `value=null` if unknown, `unit=null` for a qualitative value | Source observation; value C for a populated trait, unit C for a numeric populated trait | public | new; zero is meaningful only when sourced |
| `source_url`, `source_title` | Direct citation and document/title | Primary source; C for a populated trait | public | new; source record retained with revision |
| `source_publication_date` | ISO date or null when unavailable | Source metadata; O | public | new; CSIR variety release year is not page publication date |
| `study_location`, `agroecological_zone` | Geographic scope or null | Source methods; C when reported | public | new; never silently imply Ejura |
| `variety`, `production_system`, `management` | Scope strings or null | Source methods; C when reported | public | new; null means unspecified, not universal |
| `source_confidence`, `pilot_transferability` | `low` / `moderate` / `high` with rationale | Research review; C for populated value | public | new; neither is local validation |
| `applicability`, `limitations` | Plain-language intended use and excluded inferences | Research review; R for populated value | public | new; retained with revision |
| `validation_status`, `reviewer_ref`, `reviewed_at` | Evidence status and local-review record or null | Reviewer process; R status, reviewer/date C if locally reviewed | public | new; desk evidence remains provisional |

`GrowthStage` is a nested record, not an assertion that every crop has a known stage schedule. Each non-null offset, duration or sensitivity uses the complete `EvidenceValue` envelope above.

| `GrowthStage` field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `stage_key` | controlled string naming the source-defined stage | Crop/profile source; R for a stage record | public | new; version stage vocabulary |
| `start_offset_days` | `EvidenceValue<{min_days:int,max_days:int}>` or null; offset from the recorded planting/establishment date | Variety/system stage study; O | public | new; null blocks an exact stage placement |
| `duration_days` | `EvidenceValue<{min_days:int,max_days:int}>` or null; inclusive stage duration with stated endpoint meaning | Variety/system stage study; O | public | new; null blocks an exact stage window |
| `sensitivity` | `EvidenceValue<{factor:string,direction:string}>` or null; e.g. source-described water-shortage sensitivity, never an invented damage threshold | Stage-specific source; O | public | new; null means no crop-specific climate interpretation |

`DecisionTraits` is a **closed set of nullable keys** for a profile revision. A populated value has the full `EvidenceValue` source/scope/status envelope; a null stays unknown and cannot become a High/Moderate/Low rating by default. These are storage slots, not approved MVP scores or thresholds.

| `DecisionTraits` key | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `crop_water_need_mm` | `EvidenceValue<{min_mm:number,max_mm:number,period:string}>` or null, scoped requirement over a defined stage/season | Crop-water study; O | public | new; null until crop/system/stage basis is supported |
| `crop_coefficient_by_stage` | list of `EvidenceValue<{stage_key:string,kc:number}>` or null | FAO/local crop-coefficient evidence; O | public | new; never derive from crop name alone |
| `temperature_response` | `EvidenceValue<{metric_key:string,min_c:number or null,max_c:number or null,threshold_c:number or null,exposure_days:int or null}>` or null; source must define the metric and at least one numeric bound | Variety/stage temperature study; O | public | new; current `T2M_MAX` has no approved damage cutoff |
| `soil_nutrient_residue_effect` | `EvidenceValue<{condition:string,direction:string,quantity:number or null,unit:string or null}>` or null | Management-specific soil/residue study; O | public | new; no unconditional soil credit |
| `nitrogen_fixation_kg_ha` | `EvidenceValue<{min:number,max:number}>` or null | Variety/management N-fixation study; O | public | new; legume family alone does not populate it |
| `erosion_context` | `EvidenceValue<{management:string,direction:string}>` or null | Site/management-specific erosion study; O | public | new; no field diagnosis from broad texture |
| `rotation_relationships` | list of `EvidenceValue<{predecessor_crop_key:string,successor_crop_key:string,condition:string,effect:string}>` or null | Sequence and management study; O | public | new; no invented pest-break interval |
| `yield_stability_proxy` | `EvidenceValue<{metric_key:string,estimate:number,unit:string,comparison_basis:string}>` or null | Comparable local trial/time-series evidence; O | public | new; no guaranteed yield or probability |
| `labour_operations` | list of `EvidenceValue<{operation:string,timing:string,effort_person_days_ha:number or null}>` or null | Crop/system operations study; O | public | new; operation names do not prove farm feasibility |

### `crop_calendars` collection

A calendar is a separate, versioned record because one crop may have multiple community, variety, season and system windows, and sources may conflict. A planting window is not a farmer's actual planting date or NASA analysis period.

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `_id`, `schema_version`, `calendar_version` | ObjectId and immutable schema/content versions | Backend/research publication; R | public | new; preserve old versions |
| `location_key` | supported community/location scope | SupportedLocation catalog; R | public | new; never apply Ejura window to Kintampo by default |
| `crop_id`, `profile_revision_id` | canonical crop and scoped profile references | Resolved catalog; R crop, C profile when trait-dependent | public | new; application validates references |
| `season_key` | source-defined season label, not an assumed calendar year | Local/official source; R | public | new; names do not supply dates |
| `planting_window` | `PlantingWindow` object below or null | Source calendar; C if an exact window is claimed | public | new; null if only broad season association exists |
| `harvest_or_maturity_basis` | `EvidenceValue<{profile_revision_id:ObjectId or null,end_event_definition:string}>` or null | Profile/source; O | public | new; no assumed 4-month slot |
| `evidence` | `EvidenceValue` envelope for the window's source/date/place/system/limits, or null when window unknown | Research record; C when a window is populated | public | new; conflicting sources retained separately |
| `status` | `provisional` / `locally_reviewed` / `conflicted` / `unknown` | Review; R | public | new; conflict blocks automated timing |

Unique revision key: `(location_key, crop_id, profile_revision_id, season_key, calendar_version)`; list queries filter by location and crop. An unsupported/missing duration or conflicting window yields no asserted future date.

| `PlantingWindow` field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `start_month_day`, `end_month_day` | `MM-DD` strings; inclusive recurring bounds | Calendar source; R for a populated window | public | new; no invented midpoint day |
| `crosses_year` | boolean; end falls in the next calendar year | Calendar source/derived from bounds; R | public | new; review leap-day rule before use |
| `valid_from_year`, `valid_to_year` | nullable integer years limiting the source's applicability | Calendar source; O | public | new; null means source did not state a limit, not perpetual validity |

## 3. Farm and history

The Farm remains owner-scoped. One proposed Farm represents the decision plot, so its history events are embedded and edited atomically. This is a product assumption to confirm, not a claim about every farmer's real holdings. The selected `location_key` resolves privately to an existing `SupportedLocation` public reference point; no farm coordinate enters a public response.

### `farms` collection: proposed v2 additions and retained v1 fields

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `_id`, `owner_user_id` | ObjectIds; farm/decision-plot ID and authenticated owner | Existing NY-19/auth; R | private | v1; retain; owner from session only |
| `schema_version`, `revision` | schema string and monotonic edit number | Backend; R for new v2 | private | v2 add; absent on old docs means v1 |
| `name`, `location_key` | owner label and supported public-location key | Farmer selection; R | private | v1; keep; catalog resolution required |
| `soil_texture_key` | selected reference-option key, or explicit `unknown` | Farmer/soil-test report; C for completed v2 profile | private | v2 add; do not infer from v1 free text |
| `soil_texture_source` | `farmer_reported` / `measured` / `unknown`; provenance of selection | Farmer/soil record; C when key known | private | v2 add; texture alone is not water storage |
| `irrigation_access_key` | selected access option, or explicit `unknown` | Farmer report; C for completed v2 profile | private | v2 add; access alone is not applied water |
| `history_status` | `complete` / `unknown` / `needs_review` / `legacy_unresolved` | Farmer report and validation; R for new v2 | private | v2 add; old docs interpreted `legacy_unresolved` |
| `crop_history` | ordered array of 1–3 CropHistoryEvent objects when complete | Farmer report; C for `complete` | private | v2 add; never derive from `previous_crops` |
| `declared_gaps` | list of `HistoryGap` records below; explicit farmer-reported intervals between crop events | Farmer report; O | private | v2 add; absent gap is unknown, not fallow |
| `farmer_priorities` | existing map of nonnegative points for `water_resilience`, `soil_health_potential`, `yield_stability_proxy`, `labor_feasibility`; an empty map uses Decision 13 default weights | Farmer; O for profile | private | v1; retain and validate at use |
| `soil_texture`, `irrigation_access`, `previous_crops`, `current_practice` | retained v1 free-text fields | Legacy farmer inputs; O | private | v2 deprecated; preserve on reads; not an authority for new IDs, dates, water values, or baseline |
| `created_at`, `updated_at` | UTC timestamps | Existing NY-19; R | private | v1; retain |

### Embedded `CropHistoryEvent`

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `event_id` | immutable UUID/string unique within Farm | Backend at creation; R | private | new; supports targeted updates/audit |
| `crop_id` | ObjectId reference to a history-selectable `crops` document | Server resolves selected `crop_key`; R | private | new; no free-text substitute |
| `crop_key_snapshot` | immutable stable key at report time | Resolved Crop identity; R | private | new; human-readable audit if label changes |
| `sequence_order` | integer `1..n`, oldest first, no skipped/duplicate order | Farmer ordered input; R | private | new; dates verify but do not silently reorder |
| `start_date` | inclusive local calendar date of planting/establishment on this plot | Farmer report; R for completed event | private | new; actual history, not generic season start |
| `end_date` | inclusive local date crop was harvested/removed or ceased occupying plot | Farmer report; R for completed event | private | new; must be on/after start and not future |
| `variety_key` | named variety or null if unknown | Farmer report + catalog resolution; O | private | new; null blocks variety-specific inference |
| `production_system_key` | crop ecology/system or null if unknown | Farmer report + scoped catalog; O generally, C for rice assessment | private | new; no ecology inference from irrigation label |
| `date_precision`, `date_source` | `day` and `farmer_reported` for a complete event; other precision awaits policy | Farmer report; R | private | new; do not turn approximate dates into exact ones |

All events must belong to this same Farm/plot. A repeated crop in non-overlapping events is valid history and may cause a review warning; duplicate `event_id`/order is invalid. Overlapping crop events describe intercropping and are not flattened into a sole-crop sequence. **Seasonal gaps are not invalid merely because crops do not touch date-to-date.** An unexplained interval stays unknown until the farmer confirms what happened there. A confirmed idle/fallow interval can preserve a valid sole-crop sequence but is not evidence of a measured soil benefit. The exact UI for unknown dates, fallow and intercrops awaits Product Owner review.

| `HistoryGap` field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `start_date`, `end_date` | inclusive local dates between two reported events | Farmer report; R for a gap record | private | new; no inferred gap dates beyond event-boundary validation |
| `status` | `fallow` / `idle_unknown_management` / `unknown`; declared state, not agronomic evidence | Farmer report; R | private | new; absent confirmation remains unknown |
| `source` | `farmer_reported` / `extension_verified` with reviewer/date only if verified | Farmer/extension; R | private | new; no silent verification upgrade |
| `reviewer_ref`, `reviewed_at` | reviewer identity and UTC instant, or null | Extension record; C when `extension_verified` | private | new; no anonymous verified state |

### `farm_reference_options` collection

Backend-managed selectable soil and irrigation options use one small collection, distinguished by `kind`. Proposed farmer-readable soil labels are `sandy`, `loamy`, `clayey`, and `unknown`; they are self-reported broad texture descriptions, not the USDA 12-class measured taxonomy. Proposed irrigation access labels are `none`, `supplemental`, `regular`, and `unknown`; these do not give delivered millimetres. These labels require Product Owner review before publishing.

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `_id`, `schema_version` | ObjectId and catalog schema version | Backend; R | public | new `farm-reference-v1` |
| `kind`, `key` | `soil_texture` / `irrigation_access` plus immutable unique option key | Controlled catalog; R | public | new; unique `(kind,key)` |
| `label`, `definition` | plain-language selectable text and exact meaning | Product copy + [FAO texture guide](https://www.fao.org/4/r4082e/r4082e03.htm) for soil context; R | public | new; version copy changes |
| `source_url`, `source_status` | URL for a scientific definition, or null URL with `source_status=product_taxonomy` for a UI choice | Research/product; `source_status` R, URL C for a sourced scientific claim | public | new; do not present product labels as measurements |
| `selectable`, `version`, `updated_at` | active flag, revision and UTC update time | Catalog governance; R | public | new; deactivate instead of deleting used keys |

## 4. Environmental data and saved results

### Existing `environmental_snapshots` remains NY-6 owned

The current document already stores an opaque HMAC `identity.request_key` built from provider, service, AG community, UTC, parameter set, source location fingerprint, date range and adapter/schema version; normalized daily parameter series; provider metadata; and `retrieved_at`. Its unique request-key index and cache/refresh service remain the sole NASA persistence path. No coordinate or raw provider payload is added in NY-38. The future implementation may store a separately versioned **derived context DTO**, but it need not create another copy of the NASA series.

| Existing field | Meaning/source | Requiredness and privacy | Version/migration |
| --- | --- | --- | --- |
| `identity` including `request_key`, location fingerprint, UTC range and parameters | Deterministic NY-6 query identity | R; internal | Existing `v1`; new parameter sets/ranges get new keys |
| `provider_metadata` | Exact returned NASA parameter metadata/source; inspect per parameter | R; internal | Existing; preserve GEOS-IT versus MERRA-2 provenance |
| `parameters` | Normalized dated values, units, fill handling and coverage | R for valid snapshot; internal | Existing; no invented zero for missing |
| `retrieved_at`, `retrieval_status`, `source_url` | Retrieval provenance | R; internal | Existing; refresh replaces only under NY-6 rules |
| `request_contexts` | Optional calling season/crop labels, not request identity | O; internal | Existing; new context derivation may reference snapshot ID |

**Proposed service-only `FarmEnvironmentalContext` DTO:** `{farm_id, farm_revision, derived_period, source_snapshot_ids, long_term_reference_snapshot_ids, indicators, climate_features, data_status, freshness, method_version, warnings}`. It is owner-scoped in the route and can be copied into a new result for audit; it does not need its own collection unless a measured usage case later justifies one. Daily series must not be duplicated in every RotationResult.

### `rotation_results`: proposed v2 extension of NY-20

| Field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `_id`, `owner_user_id`, `farm_id`, `created_at` | Existing result identity, owner, farm and UTC creation time | NY-20/auth; R | result | v1; retain index `(owner_user_id,farm_id,created_at desc)` |
| `schema_version` | `ny38-result-v2` for new records | Backend; R | result | v2 add; v1 documents stay readable without rewrite |
| `farm_revision`, `farm_inputs` | integer revision and v2 `FarmDecisionInputSnapshot` copied from the authorized Farm | Farm service; R | result | v1 snapshot extended in v2; never use live Farm to explain an old result |
| `history_event_snapshots` | ordered list of event ID, crop key, actual dates, variety/system and source from `CropHistoryEvent`; optional scoped profile ID | Farm history at generation; R | result | v2 add; never synthesize from legacy free text |
| `derived_context_period` | `{start_date:date,end_date:date,policy_version:string}` calculated as the inclusive ≥12-calendar-month range | Pure date derivation; R | result | v2 add; preserve even when NASA unavailable |
| `decision_inputs` | v2 decision-input object retaining existing generation/scoring requests and adding the versioned references below | NY-8/9 orchestration; R | result | v1 nested object retained and extended; no duplicate top-level snapshot fields |
| `decision_inputs.environmental_snapshot_ids`, `decision_inputs.climate_reference_ids` | lists of exact NY-6 ObjectId references for recent and 1991–2020 sources | Snapshot service; R as lists, populated when used | result | v1 recent refs retained in place; v2 reference IDs add; no raw coordinates |
| `climate_features` | list of `ClimateFeature` records below; empty with an explicit reason when no feature is assessed | Pure feature service; R as a list | result | v2 add; historical context and reference separated |
| `decision_inputs.crop_profile_revision_ids`, `decision_inputs.calendar_version_ids` | lists of exact catalog ObjectId/version references used per candidate/event | Catalog service; R as lists, populated for assessed events | result | v2 add; immutable version links |
| `decision_inputs.rule_set_version`, `decision_inputs.assessment_version`, `decision_inputs.scoring_version` | nonempty engine method-version strings | Decision modules; R | result | first two exist in v1 decision inputs; scoring version adds in v2; changes bump versions |
| `candidate_generation`, `scoring_result` | preserved option set, criteria, weights, warnings, ties, explanations | NY-8 output; R | result | v1 fields; v2 shape must remain backward-readable |
| `baseline_status` | `deferred` for new flow; never derive baseline from past events | Approved NY-38 Product Owner clarification; R | result | v2 add; old results retain historical baseline as generated |
| `decision_status` | `ranked_provisional` / `needs_review` / `unranked` / `unavailable` | Decision service; R | result | v2 add; no fabricated rank on missing evidence |

Existing result reads remain owner and farm constrained. `v1` results keep their original logic and provenance; do not recalculate or silently relabel them as v2. A new result with missing climate data records the reason/status rather than a zero-valued feature.

| `ClimateFeature` field | Type and meaning | Source and requiredness | Privacy | Version/migration |
| --- | --- | --- | --- | --- |
| `feature_key`, `method_version` | controlled strings identifying calculation and its exact version | Pure feature method; R | result | new v2; changes create a new version |
| `value`, `unit` | numeric value or a numeric interval (`min`,`max`) plus unit; null when not assessed | Calculated from complete NY-6 series; C when status is assessed | result | new v2; missing is never zero |
| `status`, `reason` | `assessed` / `partial_observed` / `not_assessed`; reason code and safe explanation | Feature validation; R status, C reason when not assessed | result | new v2; no hidden imputation |
| `stage_window`, `reference_period` | inclusive date/range envelope and fixed reference years, or null when unavailable | Versioned crop calendar/stage and 1991–2020 proposal; C when assessed | result | new v2; future weather is never claimed |
| `reference_distribution` | `{statistic:"median_of_annual_cdd",start_year:int,end_year:int,feasible_placement_count:int,complete_years_per_placement:int,exposure_min_days:number,exposure_max_days:number}` or null | Pure CDD method over complete matching reference windows; C for an assessed CDD feature | result | new v2; source IDs/method permit per-year recomputation without copying the daily series |
| `coverage` | `{expected_days:int,valid_days:int,missing_days:int}` for every used series | NY-5/6 normalized data; C when series queried | result | new v2; exact counts retained |
| `source_snapshot_ids` | list of NY-6 ObjectId references for recent/reference input | Snapshot service; R when feature attempted | result | new v2; no raw NASA response copy |
| `crop_profile_revision_id`, `calendar_version_id` | scoped evidence references or null if not resolved | Catalog resolver; C when stage/window used | result | new v2; pins interpretation |
| `confidence`, `limitations` | source/transferability status and plain-language bounds | Research/feature method; R when assessed | result | new v2; remains provisional without local review |

## 5. Illustrative records

These examples show document relationships only. Dates, IDs and daily values below are **synthetic contract fixtures**, not a real farmer, a NASA observation, a validated crop calendar, or a recommended rotation. The Mongo IDs are illustrative. The real implementation must use its typed DTOs and validation.

```json
{
  "crops": {"_id": "000000000000000000000101", "schema_version": "crop-identity-v1", "crop_key": "maize", "common_name": "Maize", "scientific_name": "Zea mays", "family": "Poaceae", "local_names": [], "history_selectable": true, "recommendation_candidate": true, "catalog_status": "active"},
  "farm_reference_option": {"_id": "000000000000000000000201", "schema_version": "farm-reference-v1", "kind": "soil_texture", "key": "unknown", "label": "I do not know", "definition": "No soil texture identified", "source_url": null, "source_status": "product_taxonomy", "selectable": true, "version": 1},
  "farm": {"_id": "000000000000000000000301", "owner_user_id": "000000000000000000000401", "schema_version": "farm-v2", "revision": 1, "name": "Example plot", "location_key": "ejura", "soil_texture_key": "unknown", "soil_texture_source": "unknown", "irrigation_access_key": "unknown", "history_status": "complete", "crop_history": [{"event_id": "history-1", "crop_id": "000000000000000000000101", "crop_key_snapshot": "maize", "sequence_order": 1, "start_date": "2026-03-01", "end_date": "2026-06-15", "variety_key": null, "production_system_key": null, "date_precision": "day", "date_source": "farmer_reported"}], "declared_gaps": [], "farmer_priorities": {"water_resilience": 1, "soil_health_potential": 0, "yield_stability_proxy": 0, "labor_feasibility": 0}},
  "environmental_context": {"farm_id": "000000000000000000000301", "farm_revision": 1, "derived_period": {"start_date": "2025-06-15", "end_date": "2026-06-15", "policy_version": "ny38-calendar-month-v1"}, "source_snapshot_ids": ["000000000000000000000501"], "long_term_reference_snapshot_ids": [], "indicators": [], "climate_features": [], "data_status": "not_assessed", "method_version": "ny38-research-v1"},
  "environmental_snapshot": {"_id": "000000000000000000000501", "identity": {"provider": "NASA POWER", "service": "Daily Point", "community": "AG", "parameters": ["PRECTOTCORR", "T2M", "T2M_MAX"], "time_standard": "UTC", "start_date": "2025-06-15", "end_date": "2026-06-15", "location_key": "<opaque HMAC>", "request_key": "<opaque HMAC>"}, "retrieved_at": "2026-06-18T12:00:00Z", "retrieval_status": "live", "provider_metadata": {"source": "<returned NASA source>"}, "parameters": {"PRECTOTCORR": "<normalized dated series with metadata>"}},
  "rotation_result": {"_id": "000000000000000000000601", "owner_user_id": "000000000000000000000401", "farm_id": "000000000000000000000301", "created_at": "2026-06-18T12:05:00Z", "schema_version": "ny38-result-v2", "farm_revision": 1, "farm_inputs": "<typed farm input snapshot>", "history_event_snapshots": [{"event_id": "history-1", "crop_key": "maize", "start_date": "2026-03-01", "end_date": "2026-06-15"}], "derived_context_period": {"start_date": "2025-06-15", "end_date": "2026-06-15", "policy_version": "ny38-calendar-month-v1"}, "decision_inputs": {"generation_request": "<typed generation request>", "scoring_request": "<typed scoring request>", "environmental_snapshot_ids": ["000000000000000000000501"], "climate_reference_ids": [], "crop_profile_revision_ids": [], "calendar_version_ids": [], "rule_set_version": "<version>", "assessment_version": "<version>", "scoring_version": "<version>"}, "climate_features": [], "baseline_status": "deferred", "decision_status": "unranked", "candidate_generation": "<typed generation result>", "scoring_result": "<typed scoring result>"}
}
```

The current NY-6 `EnvironmentalSnapshot` has more required nested identity fields than this shortened illustration shows. The implementation must build it through the existing typed `build_snapshot_identity` and model mapper; the fixture is not a seedable Beanie document. The example `history-1` duration does not imply that any named maize variety grows for that many days.

## 6. Proposed API and service boundaries

All farm and result routes require the existing NY-11 cookie session and CSRF protection on mutations. A wrong-owner ID must produce the same 404 as a missing ID. Catalog GETs expose only public labels/status, never private farm data or internal coordinate values.

| Route / service | Request contract | Success contract | Error / ownership behavior |
| --- | --- | --- | --- |
| `GET /api/v1/crops?usage=...` | Optional `history` or `recommendation` usage filter; no free text lookup used as identity | Same canonical collection: stable crop keys/labels, selectable/candidate flags, profile evidence status, variety/system requirements | Invalid filter 422; catalog outage 503 |
| `GET /api/v1/farms/reference-options` | No body | Soil and irrigation keys/labels/definitions; `unknown` choices visible | Catalog outage 503 |
| Existing `GET /api/v1/farms/locations` | No body | Supported key/label and limited-coverage notice | Existing behavior retained |
| `POST /api/v1/farms` / `PATCH /api/v1/farms/{id}` | Farm v2 data, selected reference keys and 1–3 dated crop events when history is complete; no owner ID or coordinates | Safe Farm DTO with ordered crop labels/keys, dates, status and revision | 401 unauthenticated; 404 wrong-owner/missing; 422 unknown key, invalid dates/order/overlap; 409 stale revision if concurrency token adopted |
| `POST /api/v1/farms/{id}/environmental-context` | No farmer-supplied dates; internal/advanced `force_refresh` only if retained | Derived period, NY-6 cache/source/coverage/freshness, NY-7 indicators and feature status | Ownership checked first; invalid/incomplete history reported safely; NASA/Mongo 503 or explicit unavailable state, no fabricated values |
| `POST /api/v1/farms/{id}/rotation-recommendations` | No resubmitted history or future windows; uses saved Farm and versioned catalog/calendar | Up to three alternatives with Decision 13 mode/weights, source IDs, timing and missing-evidence reasons; `baseline_status=deferred` | 401/404 as above; missing calendar/traits produces `needs_review` or unranked, no invented slot dates |
| Existing result history/detail | Farm/result IDs only | Saved v1 and v2 envelopes with version-aware serialization | Owner+farm query filters retained; 404 for another user's result |

**Proposed DTO shape for the completed-history path** (research contract, not an existing OpenAPI schema):

```text
FarmCreateOrUpdateV2 = {
  name: string,
  location_key: string,                 // existing supported-location catalog key
  soil_texture_key: string,             // backend reference-option key, may be "unknown"
  irrigation_access_key: string,        // backend reference-option key, may be "unknown"
  history_status: "complete",
  crop_history: 1..3 ordered {
    crop_key: string,                   // resolved server-side to crops._id
    sequence_order: integer,            // 1..n, oldest first
    start_date: ISO date,               // actual reported establishment
    end_date: ISO date,                 // actual reported removal/harvest
    variety_key?: string | null,
    production_system_key?: string | null
  },
  declared_gaps?: HistoryGap[],
  farmer_priorities?: existing PriorityPoints | null
}
FarmSafeResponseV2 = {
  id: string, revision: integer, name: string,
  location: { key: string, label: string },
  soil_texture: { key: string, label: string },
  irrigation_access: { key: string, label: string },
  history_status: string,
  crop_history: ordered { event_id: string, crop: { key: string, label: string },
                          sequence_order: integer, start_date: ISO date, end_date: ISO date,
                          variety_key?: string | null, production_system_key?: string | null }[],
  farmer_priorities?: PriorityPoints | null
}
EnvironmentalContextResponseV2 = {
  farm_id: string, farm_revision: integer,
  derived_period: { start_date: ISO date, end_date: ISO date, policy_version: string },
  indicators: existing NY-7 DTO[], climate_features: ClimateFeature[],
  sources: { snapshot_id: string, source: string, period: ISO date range,
             retrieved_at: UTC instant, status: "live" | "cached" | "unavailable",
             coverage: counts, documented_source_grid?: string }[],
  warnings: string[]
}
RecommendationResponseV2 = {
  id: string, farm_id: string, decision_status: string, baseline_status: "deferred",
  options: at most 3 existing NY-8 option DTOs with timing/evidence additions,
  scoring_mode: existing Decision 13 mode, weights: existing Decision 13 weights,
  assumptions: string[], limitations: string[], provenance: result version/reference IDs
}
```

The server never accepts `owner_user_id`, raw coordinates, an environmental date range, or future planting windows in these request bodies. The farm response omits owner ID and the public reference point's coordinates. A missing/incomplete-history DTO would be a separate explicit variant **only if** the Product Owner approves it. Existing `/api/v1` clients are prelaunch; NY-39 must inventory consumers before changing their request shape, coordinate a frontend switch, and retire the old date/baseline generation request. If an external consumer must remain compatible, publish this new workflow under `/api/v2` instead of silently changing its v1 contract.

Proposed service interfaces for implementation review:

```text
CropCatalog.resolve_history_key(crop_key) -> CropIdentity | validation_error
CropCatalog.list_candidates(location_key, system_context) -> scoped profiles with statuses
FarmHistory.validate(events, gaps, as_of_date) -> valid | needs_review | invalid
ContextWindow.derive(valid_events) -> inclusive start/end + policy_version
EnvironmentalSnapshotService.retrieve(PowerRequest) -> existing cache/service outcome
ClimateFeatureService.calculate(snapshot, reference, stage_window, method_version) -> value | not_assessed
CalendarService.derive_next_events(farm, profiles, calendars) -> dated events | needs_review
RotationService.generate_and_score(authorized_farm, features, catalog_versions) -> exact NY-8 result
RotationResultRepository.create_for_farm(authorized_farm, exact_result, provenance) -> saved v2 result
```

The pure date, climate-feature, calendar and decision functions must not call MongoDB or NASA. The API orchestration owns coordination and version-aware error mapping. NY-6 remains the only NASA snapshot repository; NY-20 remains the only result writer.

## 7. Migration and compatibility gates

1. Inventory existing Farm documents and API consumers, then add v2 fields without deleting v1 text. Old documents lacking `schema_version` are interpreted as v1 with `history_status=legacy_unresolved`; no automatic date, crop-key, soil or irrigation mapping is allowed.
2. Publish `crops`, profile revisions, calendars and farm reference options only after evidence review. Resolve selected crop keys to ObjectIds server-side. Do not fill traits from the current in-memory six-crop dictionary without retaining its provisional evidence and scope.
3. Read old results with their `ny20-result-v1` schema and original explanations. New results use v2 with pinned catalog, context, feature and rule versions. Never recompute an old rank against a newer catalog.
4. Coordinate the changed `/api/v1` request bodies with the frontend before rollout. A transition adapter may continue returning legacy farm text for old clients, but a legacy array never becomes valid dated history; return an explicit upgrade/needs-review state for recommendation generation.
5. Add repository indexes with NY-4's model registry and migration plan. Validate referential existence in application logic; MongoDB does not provide relational foreign keys. Preserve the existing farm/result owner filters and HMAC snapshot identity.

## 8. Open contract choices for Product Owner review

1. Confirm one Farm means one decision plot. A farm containing multiple plots cannot truthfully share one crop history or soil state.
2. Decide whether extra `history_only` crop records may be added to the same catalog, or whether unsupported crop histories stop recommendation. The six recommendation candidates remain unchanged either way.
3. Decide whether an unknown/approximate historical date, explicit fallow, or intercropping can be saved as an incomplete profile, and what the user sees before a decision can be generated. The proposed strict complete-event path does not invent dates or sequences.
4. Approve the broad soil and irrigation option labels and whether the farmer can choose `unknown`. No option estimates field water storage or irrigation volume.
5. Agree on the public API transition for existing farm clients and the future calendar/variety inputs. NY-39/40 implementation waits for this research handoff review.
