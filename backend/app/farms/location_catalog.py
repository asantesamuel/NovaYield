"""Research-sourced supported-location records for the initial Ghana pilot."""

from app.farms.contracts import LocationCoordinates, SupportedLocationSeed

# These are public inhabited-place reference points for coarse NASA POWER grid
# lookup. They are not precise farm locations, field centroids, or locally
# validated operational points. Keep the provenance on each MongoDB record.
SUPPORTED_LOCATION_SEEDS: tuple[SupportedLocationSeed, ...] = (
    SupportedLocationSeed(
        location_key="ejura",
        label="Ejura",
        locality="Ejura",
        administrative_area="Ejura-Sekyedumase Municipality",
        region="Ashanti Region",
        coordinates=LocationCoordinates(latitude=7.3856, longitude=-1.3562),
        point_scope="inhabited_place_reference",
        coordinate_source="Getty Thesaurus of Geographic Names, record 1090118",
        coordinate_source_url="https://www.getty.edu/vow/TGNFullDisplay?english=Y&find=&nation=&subjectid=1090118",
        sort_order=0,
    ),
    SupportedLocationSeed(
        location_key="anyinasu",
        label="Anyinasu",
        locality="Anyinasu",
        administrative_area="Ejura-Sekyedumase Municipality",
        region="Ashanti Region",
        coordinates=LocationCoordinates(latitude=7.23705, longitude=-1.57696),
        point_scope="inhabited_place_reference",
        coordinate_source="Mapcarta locality record based on OpenStreetMap/GeoNames data",
        coordinate_source_url="https://mapcarta.com/16954496",
        sort_order=1,
    ),
    SupportedLocationSeed(
        location_key="kintampo",
        label="Kintampo",
        locality="Kintampo town",
        administrative_area="Kintampo North Municipal District",
        region="Bono East Region",
        coordinates=LocationCoordinates(latitude=8.0537, longitude=-1.7289),
        point_scope="inhabited_place_reference",
        coordinate_source="Mapcarta locality record based on OpenStreetMap data",
        coordinate_source_url="https://mapcarta.com/16944928",
        sort_order=2,
    ),
)
