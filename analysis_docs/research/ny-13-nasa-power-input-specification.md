---
title: NY-13 NASA POWER inputs and indicators
status: Research specification; validation still required before NY-13 is Done
source: Team-provided research attachment, preserved for implementation traceability
---

# NY-13 NASA POWER Inputs and Indicators

Purpose: Give implementation a concrete, auditable starting contract for the provisional Ejura-Sekyedumase pilot recommended in NY-12. This is a research specification, not a claim that the data are field measurements or that agronomic thresholds have been validated.
Use the NASA POWER Daily Point API for the pilot location:
- Endpoint: https://power.larc.nasa.gov/api/temporal/daily/point
- Community: AG (Agroclimatology)
- Format: JSON
- Parameters for the first release: PRECTOTCORR,T2M,T2M_MAX
- Required request inputs: latitude, longitude, inclusive start/end dates, community, parameters, format, and explicit time-standard=UTC.
- Do not invent a farm coordinate. Use a validated pilot/community reference point for municipality-level demonstration; use the farm's supplied coordinate only where the product has permission and a legitimate need. Keep private farm coordinates out of public logs and user-facing provenance.
- Validate the exact returned parameter metadata (long name, unit, fill value, source) from each API response and persist it with the snapshot. Fail clearly if a requested parameter is unavailable; do not silently substitute another variable.
The Daily API supports point time series, JSON, and daily values; it defaults to Local Solar Time (LST), so the implementation must explicitly request UTC if using UTC date boundaries. Daily UTC/LST records are documented from 1981-01-01 to near real time. NASA documents a 20-parameter maximum for a single-point request. The API exposes parameters at their original source spatial resolution; the documentation also warns about grid-cell request reuse and blocking repeated requests for the same relative location.
Indicator
Required POWER variable
Formula over selected season window
Output unit
User-facing meaning
Seasonal rainfall total
PRECTOTCORR
Sum daily valid precipitation values for dates inside the selected season
mm/season (if API metadata confirms mm/day)
Estimated total precipitation represented by the POWER grid cell during the selected planting/growing window
Mean daily air temperature
T2M
Arithmetic mean of valid daily values in the selected season
°C (confirm response metadata)
Average near-surface air temperature represented by the grid cell
Mean daily maximum air temperature
T2M_MAX
Arithmetic mean of valid daily maximum-temperature values in the selected season
°C (confirm response metadata)
Average of the daily maximum temperatures; not the season's single hottest reading
Implementation note: These are candidate POWER parameter names commonly used in the Daily service. The returned POWER response's parameters metadata is the runtime authority for units, long names and fill values. Store the exact metadata. Do not hard-code a unit if the response says otherwise. If PRECTOTCORR is returned in mm/day, its seasonal sum is mm/season; do not sum an already aggregated monthly/seasonal value.
- Season start/end dates must come from a separately reviewed local crop/season calendar, not from arbitrary Jan–Dec years.
- For Ejura-Sekyedumase, the MOFA district profile describes a transition area with a bimodal rainfall pattern and differing crop/season conditions across the district. Treat any municipality-wide calendar as provisional until checked with extension officers and farmers.
- Store the selected season label, start date, end date, calendar source/version and the crop/community context used to select it.
- Use inclusive date boundaries. For UTC requests, dates refer to the POWER UTC daily record. If product language uses Ghana local dates, document the conversion explicitly and do not mix UTC and LST records in one time series.
- If the season is not yet validated for a crop/community, return a clearly labelled provisional window or mark the indicator unavailable; do not imply a locally validated planting recommendation.
- Treat NASA POWER fill/sentinel values (commonly documented as -999; still verify the actual response metadata) as missing, never as zero.
- Calculate each indicator using valid daily observations only. Return expected day count, valid day count, missing day count and coverage percentage alongside the value.
- If no valid values exist, return unavailable, not 0.
- If coverage is incomplete, show the value with an explicit partial-coverage warning; do not interpolate or impute in P0.
- Define a product-approved minimum coverage threshold before using an indicator in ranking. Until that threshold is agreed, expose coverage and keep the indicator not_assessed for decision scoring when data are insufficient; do not invent a threshold.
- Distinguish live, cached, and sample/demo data in every response. Sample/demo data must never be presented as a live observation.
- A cached snapshot is reusable only when provider/service, community, normalized location/grid identity, parameter set, time standard, and inclusive date range match. Store retrieval time and source metadata; if no matching snapshot exists and the API is unavailable, return an explicit unavailable state rather than fabricated fallback values.
- POWER is gridded/reanalysis-derived environmental data. A point request is not an on-farm rain gauge or field thermometer.
- The API says parameters retain their original source spatial resolution; do not advertise a single universal resolution for all variables. Preserve returned source/grid metadata and verify variable-specific resolution before displaying it.
- A municipality reference point can support area-level screening and a demonstration, not plot-level prescriptions. Nearby farms may map to the same grid cell; avoid false precision in maps and explanations.
- Do not derive soil moisture, soil fertility, crop water requirement, yield, profitability, or a dry-spell/heat-stress diagnosis from these three indicators alone.
- Dry-spell and heat-stress thresholds are deferred until supported by crop-specific and pilot-specific agronomic evidence (NY-14/NY-15 and local validation).
provider, service, community, requested_location (access-controlled), returned_grid_or_spatial_metadata, parameters, parameter_metadata, time_standard, start_date, end_date, season_label, calendar_source_version, daily_values, indicator_values, unit, expected_days, valid_days, missing_days, coverage_pct, retrieved_at, source_url, request_identity, data_status (live|cached|sample|unavailable), warnings, schema_version.
1. NY-12 / local agronomist: approve the demonstration coordinate(s) and crop-specific seasonal windows for Ejura-Sekyedumase.
2. NY-14 / agronomy review: confirm which indicators are useful for each shortlisted crop and whether any additional crop-specific parameter is genuinely needed.
3. Product/backend: set a minimum coverage policy and cache freshness policy; neither is supplied by the research evidence in this ticket.
4. Backend: confirm exact returned units, fill values, source names and native spatial resolution from a real API response at the approved location before freezing the DTO.
5. Product: agree how provisional season windows and partial coverage are worded in the UI.
- NASA POWER Daily API: [NASA POWER | Docs | Data Services | Daily API - NASA POWER | Docs](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
- NASA POWER parameter guide: [NASA POWER | Docs | Tutorials | Parameters - NASA POWER | Docs](https://power.larc.nasa.gov/docs/tutorials/parameters/)
- NASA POWER API request tutorial: [NASA POWER | Docs | Tutorials | API - NASA POWER | Docs](https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/)
- MOFA Ejura-Sekyedumase District Directorate: [MOFA - Ejura-Sekyeredumase](https://mofa.gov.gh/site/sports/district-directorates/ashanti-region/164-ejura-sekyeredumase)
- Ejura-Sekyedumase Municipal Assembly town profile: [Town Profile](https://esma.gov.gh/about-us/town-profile/)
Decision: This specification is sufficiently concrete to guide NY-5/NY-6/NY-7 implementation scaffolding, but NY-13 should not be marked Done until a real API response is tested at the approved pilot coordinate, response metadata/units/fill values are captured, and the local season window plus coverage policy are approved.
