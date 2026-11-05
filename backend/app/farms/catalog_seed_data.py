"""NY-38-approved initial catalog facts, with unknowns left unknown.

The identity source confirms a crop's presence or broad taxonomy. A maturity
claim belongs only to its named variety. No seed below asserts a local planting
day, a field water balance, a measured soil benefit, or local agronomic review.
"""

from __future__ import annotations

from typing import Any

from app.decisions.crop_profiles import CROP_LIBRARY_VERSION, CROP_PROFILES
from app.models.crop_catalog import EvidenceValue, GrowthStage, SourceEvidence

CSIR_VARIETIES = "https://technologies.csirgh.com/maincropvarieties"
MOFA_MAIZE = "https://mofa.gov.gh/site/images/pdf/production_guides/GUIDE_TO_MAIZE_PRODUCTION.pdf"
MOFA_RICE = "https://mofa.gov.gh/site/images/pdf/production_guides/RICE_Production_Guide.pdf"
FAO_WATER = "https://www.fao.org/4/t7202e/t7202e05.htm"
FAO_CASSAVA = "https://www.fao.org/4/i2929e/i2929e.pdf"
FAO_GHANA_YAM = (
    "https://www.fao.org/fileadmin/templates/agphome/documents/PGR/SoW1/africa/GHANA.PDF"
)
EJURA_TOWN_PROFILE = "https://esma.gov.gh/about-us/town-profile/"
MOFA_EJURA_PROFILE = (
    "https://mofa.gov.gh/site/directorates/55-district-directorates/"
    "district-ashanti/164-ejura-sekyeredumase"
)
LEGACY_GENERIC_PROFILE_NOTE = (
    "Generic identity has no validated local duration or numerical crop traits."
)
GENERIC_PROFILE_SOURCE_NOTE = (
    f"{CROP_LIBRARY_VERSION}: generic identity with provisional NY-8 water class where "
    "sourced; no locally validated calendar, field water balance, or crop-specific threshold."
)

CROP_IDENTITY_SEEDS: tuple[dict[str, Any], ...] = (
    dict(
        crop_key="maize",
        common_name="Maize",
        scientific_name="Zea mays",
        family="Poaceae",
        identity_source_url=MOFA_MAIZE,
        history_selectable=True,
        recommendation_candidate=True,
    ),
    dict(
        crop_key="cowpea",
        common_name="Cowpea",
        scientific_name="Vigna unguiculata",
        family="Fabaceae",
        identity_source_url=CSIR_VARIETIES,
        history_selectable=True,
        recommendation_candidate=True,
    ),
    dict(
        crop_key="groundnut",
        common_name="Groundnut",
        scientific_name="Arachis hypogaea",
        family="Fabaceae",
        identity_source_url=CSIR_VARIETIES,
        history_selectable=True,
        recommendation_candidate=True,
    ),
    dict(
        crop_key="cassava",
        common_name="Cassava",
        scientific_name="Manihot esculenta",
        family="Euphorbiaceae",
        identity_source_url=CSIR_VARIETIES,
        history_selectable=True,
        recommendation_candidate=True,
    ),
    dict(
        crop_key="yam",
        common_name="Yam",
        scientific_name="Dioscorea spp.",
        family="Dioscoreaceae",
        identity_source_url=FAO_GHANA_YAM,
        history_selectable=True,
        recommendation_candidate=True,
    ),
    dict(
        crop_key="rice",
        common_name="Rice",
        scientific_name="Oryza spp.",
        family="Poaceae",
        identity_source_url=MOFA_RICE,
        history_selectable=True,
        recommendation_candidate=True,
        requires_production_system_for_assessment=True,
    ),
    # Approved history-only choices reflect reported pilot crops. They never join
    # the six recommendation candidates; ambiguous "beans" has no identity.
    dict(
        crop_key="plantain",
        common_name="Plantain",
        scientific_name=None,
        family=None,
        identity_source_url=EJURA_TOWN_PROFILE,
        history_selectable=True,
        recommendation_candidate=False,
    ),
    dict(
        crop_key="sorghum",
        common_name="Sorghum (guinea corn)",
        scientific_name=None,
        family=None,
        identity_source_url=MOFA_EJURA_PROFILE,
        history_selectable=True,
        recommendation_candidate=False,
    ),
)


def _source(
    url: str,
    title: str,
    *,
    variety: str | None = None,
    production_system: str | None = None,
    source_confidence: str = "moderate",
    pilot_transferability: str = "low",
    applicability: str,
    limitations: str,
    study_location: str | None = None,
) -> SourceEvidence:
    return SourceEvidence(
        source_url=url,
        source_title=title,
        study_location=study_location,
        agroecological_zone="Ghana forest–savanna transition" if url == CSIR_VARIETIES else None,
        variety=variety,
        production_system=production_system,
        source_confidence=source_confidence,
        pilot_transferability=pilot_transferability,
        applicability=applicability,
        limitations=limitations,
        validation_status="provisional",
    )


def _water_class_evidence(crop_key: str) -> EvidenceValue | None:
    """Copy reviewed NY-8 desk evidence into the versioned Mongo crop profile."""

    crop_profile = CROP_PROFILES[crop_key]
    trait = crop_profile.trait("water_resilience_class")
    if trait is None or trait.value not in {"low", "moderate", "high"}:
        return None
    references = tuple(
        reference.strip()
        for reference in (trait.source_reference or "").split(";")
        if reference.strip()
    )
    if not references:
        return None
    return EvidenceValue(
        value={"class": trait.value},
        source=SourceEvidence(
            source_url=references[0],
            additional_source_urls=references[1:],
            source_title=trait.source_title or "NY-8 provisional crop-by-criterion evidence matrix",
            source_publication_date=trait.source_date,
            study_location=trait.study_location,
            agroecological_zone=trait.agroecological_zone,
            variety=trait.variety,
            production_system=trait.production_system,
            management=trait.management_conditions,
            source_confidence=trait.confidence or "low",
            pilot_transferability=trait.pilot_transferability or "low",
            applicability=trait.applicability_notes or "Scoped desk-research crop evidence.",
            limitations=trait.limitations
            or "Pilot transfer and farm-specific suitability are unknown.",
            validation_status="provisional",
        ),
    )


WATER_RESILIENCE_EVIDENCE = {
    crop_key: evidence
    for crop_key in CROP_PROFILES
    if (evidence := _water_class_evidence(crop_key)) is not None
}


def _sensitive_stage(stage_key: str, url: str, title: str, crop: str) -> GrowthStage:
    from app.models.crop_catalog import EvidenceValue

    return GrowthStage(
        stage_key=stage_key,
        start_offset_days=None,
        duration_days=None,
        sensitivity=EvidenceValue(
            value={"factor": "water_shortage", "direction": "sensitive"},
            source=_source(
                url,
                title,
                applicability=f"Broad qualitative {crop} stage sensitivity only.",
                limitations=(
                    "No named pilot variety, exact stage offset/duration, field water balance, "
                    "or damage threshold is established."
                ),
            ),
        ),
    )


GENERIC_STAGE_SEEDS: dict[str, tuple[GrowthStage, ...]] = {
    "maize": (
        _sensitive_stage(
            "flowering-grain-filling", FAO_WATER, "FAO crop water shortage sensitivity", "maize"
        ),
    ),
    "groundnut": (
        _sensitive_stage(
            "flowering-pod-setting", FAO_WATER, "FAO crop water shortage sensitivity", "groundnut"
        ),
    ),
    "cassava": (
        _sensitive_stage(
            "early-establishment", FAO_CASSAVA, "FAO Save and Grow: Cassava", "cassava"
        ),
    ),
    "rice": (
        _sensitive_stage(
            "head-development-flowering", FAO_WATER, "FAO crop water shortage sensitivity", "rice"
        ),
    ),
}


# These ranges are exactly scoped to named varieties. Source table endpoint
# meaning was not verified, so endpoint_verified=False blocks exact scheduling.
NAMED_PROFILE_SEEDS: tuple[dict[str, Any], ...] = (
    dict(
        crop_key="maize",
        variety_key="obatanpa",
        production_system_key=None,
        min_days=105,
        max_days=110,
        source_url=CSIR_VARIETIES,
        variety="Obatanpa",
    ),
    dict(
        crop_key="cowpea",
        variety_key="cri-nketewade",
        production_system_key=None,
        min_days=62,
        max_days=65,
        source_url=CSIR_VARIETIES,
        variety="CRI-Nketewade",
    ),
    dict(
        crop_key="cowpea",
        variety_key="cri-zamzam",
        production_system_key=None,
        min_days=64,
        max_days=67,
        source_url=CSIR_VARIETIES,
        variety="CRI-Zamzam",
    ),
    dict(
        crop_key="groundnut",
        variety_key="crops-nkatie",
        production_system_key=None,
        min_days=90,
        max_days=95,
        source_url=CSIR_VARIETIES,
        variety="Crops nkatie",
    ),
    dict(
        crop_key="groundnut",
        variety_key="crops-agbeyeye",
        production_system_key=None,
        min_days=90,
        max_days=95,
        source_url=CSIR_VARIETIES,
        variety="Crops Agbeyeye",
    ),
    dict(
        crop_key="cassava",
        variety_key="cri-doku-duade",
        production_system_key=None,
        min_days=365,
        max_days=458,
        source_url=CSIR_VARIETIES,
        variety="CRI-Doku Duade",
    ),
    # MoFA and CSIR give conflicting Nabogo ranges. Preserve a scoped record,
    # but no usable duration until an expert resolves the source conflict.
    dict(
        crop_key="rice",
        variety_key="nabogo",
        production_system_key=None,
        min_days=None,
        max_days=None,
        source_url=MOFA_RICE,
        variety="Nabogo",
        evidence_status="conflicted",
    ),
)


REFERENCE_OPTION_SEEDS: tuple[dict[str, Any], ...] = (
    dict(
        kind="soil_texture",
        key="sandy",
        label="Sandy",
        definition="Farmer-reported broad sandy texture; water storage has not been measured.",
    ),
    dict(
        kind="soil_texture",
        key="loamy",
        label="Loamy",
        definition="Farmer-reported broad loamy texture; water storage has not been measured.",
    ),
    dict(
        kind="soil_texture",
        key="clayey",
        label="Clayey",
        definition="Farmer-reported broad clayey texture; water storage has not been measured.",
    ),
    dict(
        kind="soil_texture",
        key="unknown",
        label="I do not know",
        definition="Soil texture is not known or has not been selected.",
    ),
    dict(
        kind="irrigation_access",
        key="none",
        label="No irrigation access",
        definition="Farmer reports no irrigation access; actual rainfall use is not measured.",
    ),
    dict(
        kind="irrigation_access",
        key="supplemental",
        label="Supplemental irrigation access",
        definition="Farmer reports occasional irrigation access; delivered water is unknown.",
    ),
    dict(
        kind="irrigation_access",
        key="regular",
        label="Regular irrigation access",
        definition="Farmer reports regular irrigation access; delivered water is unknown.",
    ),
    dict(
        kind="irrigation_access",
        key="unknown",
        label="I do not know",
        definition="Irrigation access is not known or has not been selected.",
    ),
)


REGIONAL_CALENDAR_SEEDS: tuple[dict[str, str], ...] = (
    dict(
        location_key="ejura",
        crop_key="maize",
        season_key="major-rainy-season",
        source_note="MoFA regional forest–savanna guide says mid-March to end April. "
        "No exact local day, variety or rain-onset rule has been reviewed.",
    ),
    dict(
        location_key="ejura",
        crop_key="maize",
        season_key="minor-rainy-season",
        source_note="MoFA regional forest–savanna guide says mid-July to August/early "
        "September. No exact local day, variety or rain-onset rule has been reviewed.",
    ),
    dict(
        location_key="anyinasu",
        crop_key="maize",
        season_key="major-rainy-season",
        source_note="MoFA regional forest–savanna guide says mid-March to end April. "
        "No exact local day, variety or rain-onset rule has been reviewed.",
    ),
    dict(
        location_key="anyinasu",
        crop_key="maize",
        season_key="minor-rainy-season",
        source_note="MoFA regional forest–savanna guide says mid-July to August/early "
        "September. No exact local day, variety or rain-onset rule has been reviewed.",
    ),
)
