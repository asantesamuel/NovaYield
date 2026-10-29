---
title: NY-8 public-data demo profile candidate
status: Provisional evidence-backed profile; not a farm record or rankable recommendation profile
version: 0.1
prepared: 2026-10-29
---

# NY-8 Public-Data Demo Profile Candidate

## Purpose and status

This profile assembles public information for a repeatable NovaYield decision-support scenario without inventing the characteristics or history of a real farm. It is an **area-level archetype**, not an individual farm, and is not locally validated. It can support input-contract work, source/provenance handling, rule-status behavior, and tests for missing evidence. It is **not yet sufficient to verify NY-8's acceptance criterion requiring three scored/ranked options**.

The Product Owner's approved decisions in [the NovaYield research and product-decision record](../../novayield-research-and-product-decisions.md) remain controlling: use Ejura-Sekyedumase provisionally; keep unvalidated agronomic assumptions provisional; expose partial criterion information; and withhold an overall rank when evidence is missing or incomparable.

## Proposed profile

| Field | Publicly supported value for this profile | Evidence and limit |
| --- | --- | --- |
| Profile ID / type | `ejura-public-evidence-v1`; public-data area archetype | A reproducible research fixture, not a registered farmer or field. |
| Pilot area | Ejura-Sekyedumase Municipality, Ashanti Region, Ghana | Approved provisionally by the Product Owner. The municipal profile describes a forest–savanna transition with differing rainfall regimes within the municipality. |
| Candidate reference communities | Ejura and Anyinasu; Kasei may be retained as a third candidate | A 2022 study sampled Ejura, Kasei, and Anyinasu and says the communities were selected with the Municipal Agriculture Directorate to cover a wider spread. That study selection is supporting evidence, not NovaYield extension approval. |
| Public place coordinates | Ejura: `7.3856, -1.3562`; Anyinasu: `7.23705, -1.57696` | Gazetteer/place points, not farm coordinates or field centroids. Both fall inside the municipality bounds published by the Assembly. Keep the points provisional and verify their location/grid metadata in an actual NASA response. |
| Farming-system context | Smallholder-oriented and predominantly rain-fed for the surveyed food crops | In the 2020 maize-failure study, 88% of 40 respondents reported no irrigation farming; crop production other than vegetables was described as rain-fed. This is a sample-level context, not a fact about a particular farm. |
| Farm size | Unknown for the profile | Survey respondents covered multiple farm-size categories; selecting one value would fabricate a representative individual. |
| Plot soil texture / soil test | Unknown | Published municipality-level soil descriptions are not plot measurements. Do not infer a soil-health score or crop-specific soil threshold from the municipal description. |
| Plot irrigation access | Unknown; the scenario is labelled `rainfed_archetype` only for area-level context | The 88% survey result does not identify the irrigation status of any individual farm. Do not silently turn the group statistic into a farmer answer. |
| Candidate crop records | Maize, cowpea, groundnut, cassava, yam, and rice | These are the approved MVP candidates. Public municipal and study sources confirm crop presence, not every crop's traits, suitability, or eligibility for every sequence. |
| Plot's previous crops / current practice | Unknown | The published sources describe area practices and survey responses, not a complete three-event history for a particular plot. Therefore this profile has no asserted current-practice baseline. |
| Farmer priorities | Product default: 25% each for water resilience, soil-health potential, yield-stability proxy, and labor feasibility | This is the approved neutral product default. It is not a preference reported by a surveyed farmer. |

### Candidate public reference points

| Community | Latitude | Longitude | Coordinate source | Status |
| --- | ---: | ---: | --- | --- |
| Ejura | 7.3856 | -1.3562 | [Getty Thesaurus of Geographic Names](https://www.getty.edu/vow/TGNFullDisplay?english=Y&find=&nation=&subjectid=1090118), whose record identifies Ejura as an inhabited place and cites the Times Atlas / NGA gazetteer | Candidate public place point; not an approved farm coordinate |
| Anyinasu | 7.23705 | -1.57696 | [Mapcarta locality record](https://mapcarta.com/16954496), based on OpenStreetMap / GeoNames place data | Candidate public place point; confirm with local extension before treating as a representative pilot point |
| Kasei | Not set | Not set | Named as a study community in the [2020 maize-failure study](https://www.mdpi.com/2071-1050/14/6/3514) | Keep as a candidate until an authoritative public place point is verified |

NASA POWER's meteorology products are gridded, and nearby points can resolve to the same grid cell. Do not assume these two points provide independent climate observations. Capture and compare the returned grid metadata before describing any spatial difference.

## Season and environmental-data inputs

The 2020 maize-failure paper used **April–July** as its major-season analysis window and **September–October** as its minor-season analysis window for its 2015–2020 analysis. Those month ranges provide reproducible **historical analysis windows** for the profile; they are not verified planting dates or an approved crop/community calendar. A KNUST study of 1993–2006 rainfall estimated planting dates of 8 April and 31 August, demonstrating that published timing is source- and period-dependent; do not treat those historical dates as current prescriptions.

For a three-event climate-input fixture, the candidate windows are:

| Planting-event label | Inclusive environmental-data window | Calendar status |
| --- | --- | --- |
| `major-2019` | 2019-04-01 through 2019-07-31 | Provisional study-defined analysis window |
| `minor-2019` | 2019-09-01 through 2019-10-31 | Provisional study-defined analysis window |
| `major-2020` | 2020-04-01 through 2020-07-31 | Provisional study-defined analysis window |

The three windows are consecutive named seasonal periods for repeatable historical data retrieval, not a claim that a specific farm planted a crop on a known date. They must not activate calendar-dependent hard rules or be presented as validated planting advice.

The intended public data contract is the NY-13 / NASA POWER Daily Point request: `PRECTOTCORR`, `T2M`, and `T2M_MAX`, `community=AG`, JSON, inclusive dates, and explicit `time-standard=UTC`. **No API response values are stored in this profile yet.** The browsing tool could confirm NASA's API contract but could not retrieve the live JSON response for these query URLs. Before using numeric values, run the existing NY-5 client at the selected public points, capture the response, and verify each parameter's units, fill value, source, coverage, and spatial resolution from NASA's response metadata. Do not treat this evidence file as a cache or runtime-data store.

## Public evidence relevant to rotation patterns

The sources support some rotation relationships, but **do not establish an ordered three-event history on a named plot for this profile**:

- **Cowpea before maize:** A Ghana forest–savanna transition-zone field study evaluated cowpea varieties followed by maize and found variety/biomass-dependent outcomes. This supports a possible legume-to-maize relationship; it is not a universal nitrogen credit or a complete three-season Ejura rotation.
- **Maize with groundnut/beans:** The Ejura-Sekyedumase study reports that some respondents rotated maize with legumes, mainly groundnuts and beans. It does not give a named plot's full sequence or establish the order and dates of three planting events.
- **Repeated maize:** The older MoFA district profile says maize may be grown on the same land for multiple years with fertilizer. This is broad historic context, not this profile's current practice or a verified baseline.

Do not stitch these separate facts into three asserted sequences. The exact three-event patterns must come from a source that documents the sequence or remain explicit synthetic mechanics-only fixtures, never public recommendation data.

NY-15's safe rules still apply: enforce three consecutive events on the same plot and data-integrity requirements; apply only explicitly reviewed, scoped agronomic constraints. Unknown rule inputs should produce `needs_review` or an inactive rule, not a guessed exclusion. Do not force the engine to return three options if fewer remain valid.

## Criterion evidence and ranking readiness

| PRD criterion | Public evidence available | Profile status for scoring |
| --- | --- | --- |
| Water resilience | Local studies document rain-fed farming and a serious 2020 minor-season maize failure; NASA daily indicator values have not yet been retrieved for these points/windows. A municipal survey statistic does not supply this profile's water access or crop-specific water response. | `not_assessed` |
| Soil-health potential | Broad municipal soil descriptions and research on legume/residue effects exist, but no soil test or plot-specific residue/management history exists for this profile. | `not_assessed` |
| Yield-stability proxy | The local study documents a maize-specific failure and reports farmers' experience; it does not provide comparable stability evidence for these candidate three-season options. | `not_assessed` |
| Labor feasibility | The local study describes maize operations among respondents (mechanized ploughing/harvesting; manual sowing/weeding), but it does not provide comparable operation/labor data for all six candidates or this farm. | `not_assessed` |

Under the approved missing-evidence policy, this profile **must not receive an overall score or rank**. It can verify the input contract, provenance labels, unknown-data behavior, hard data-integrity gates, and withholding of a rank. It cannot truthfully verify NY-8's full acceptance criterion for three *ranked* options. That criterion needs a profile with comparable, adequately sourced evidence for all four criteria, plus an actual NASA response; the profile must not be completed by inventing farm history, soil texture, crop traits, labor values, or scores.

## Recommended use for NY-8

- Use this profile as an evidence-aware integration/test scenario and assert that unknown or incomparable evidence yields partial criterion output with no overall rank.
- Preserve the cited rotation findings as evidence with their scope limits; do not turn them into unverified three-event sequences or universal hard agronomic rules.
- Test ranking mechanics separately with clearly artificial unit-test values, labelled as synthetic test data and never reused as a public recommendation/demo result.
- Before claiming NY-8 acceptance, either obtain additional public evidence that is comparable across the four criteria and an actual NASA response, or revisit the acceptance/demo scope with the Product Owner. Do not treat this profile as sufficient for ranked recommendations.

## References

- Ejura-Sekyedumase Municipal Assembly, [About the Municipality](https://esma.gov.gh/about-us/) and [Town Profile](https://esma.gov.gh/about-us/town-profile/): municipal boundaries, capital, agroecology, rainfall variation, and local crop context.
- Obour, Arthur & Owusu (2022), [The 2020 Maize Production Failure in Ghana: A Case Study of Ejura-Sekyedumase Municipality](https://www.mdpi.com/2071-1050/14/6/3514), *Sustainability* 14(6), 3514: three study communities, survey/farm context, local crop practices, seasonal analysis windows, and the 2020 failure. Its sample is not a specific demo farm.
- Obeng (2008), [KNUST thesis on rainfall, temperature, and maize in Ejura-Sekyedumase](https://ir.knust.edu.gh/handle/123456789/1050): historical rainfall-derived planting-date analysis for 1993–2006; not a current calendar.
- Adjei-Nsiah et al. (2008), [Cowpea varieties and succeeding maize in Ghana's forest–savanna transition zone](https://link.springer.com/article/10.1007/s10705-007-9133-3): variety-specific cowpea/maize field evidence; not a universal legume benefit.
- Ghana Ministry of Food and Agriculture, [Ejura-Sekyedumase district profile](https://mofa.gov.gh/site/directorates/district-directorates/ashanti-region/164-ejura-sekyeredumase): local crops and historic farming-system observations; treat dated generalizations cautiously.
- NASA POWER, [Daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) and [data methodology](https://power.larc.nasa.gov/docs/methodology/): request/time-standard contract, daily data and spatial-resolution limitations.
- Coordinates: [Getty TGN record for Ejura](https://www.getty.edu/vow/TGNFullDisplay?english=Y&find=&nation=&subjectid=1090118); [Anyinasu place record](https://mapcarta.com/16954496) (open geographic gazetteer data; community point requires local confirmation).
