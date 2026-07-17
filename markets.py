"""Target markets for the house wholesale pipeline."""
from dataclasses import dataclass


@dataclass
class Market:
    key: str
    label: str
    county: str
    state: str
    zips: list  # [(zip, city), ...]
    gis_url: str = ""
    deed_url: str = ""


MARKETS = [
    Market(
        key="BALTIMORE_MD",
        label="Baltimore, MD (Baltimore City)",
        county="Baltimore City",
        state="MD",
        zips=[
            ("21201", "Baltimore"), ("21202", "Baltimore"), ("21205", "Baltimore"),
            ("21206", "Baltimore"), ("21207", "Baltimore"), ("21209", "Baltimore"),
            ("21210", "Baltimore"), ("21211", "Baltimore"), ("21212", "Baltimore"),
            ("21213", "Baltimore"), ("21214", "Baltimore"), ("21215", "Baltimore"),
            ("21216", "Baltimore"), ("21217", "Baltimore"), ("21218", "Baltimore"),
            ("21223", "Baltimore"), ("21224", "Baltimore"), ("21225", "Baltimore"),
            ("21226", "Baltimore"), ("21229", "Baltimore"), ("21230", "Baltimore"),
            ("21231", "Baltimore"),
        ],
        gis_url="https://geodata.baltimorecity.gov/egis/rest/services/",
        deed_url="https://sdat.dat.maryland.gov/RealProperty/",
    ),
    Market(
        key="STLOUIS_MO",
        label="St. Louis, MO (St. Louis City)",
        county="St. Louis City",
        state="MO",
        zips=[
            ("63101", "St. Louis"), ("63102", "St. Louis"), ("63103", "St. Louis"),
            ("63104", "St. Louis"), ("63106", "St. Louis"), ("63107", "St. Louis"),
            ("63108", "St. Louis"), ("63109", "St. Louis"), ("63110", "St. Louis"),
            ("63111", "St. Louis"), ("63112", "St. Louis"), ("63113", "St. Louis"),
            ("63115", "St. Louis"), ("63116", "St. Louis"), ("63118", "St. Louis"),
            ("63119", "St. Louis"), ("63120", "St. Louis"),
        ],
        gis_url="https://www.stlouis-mo.gov/data/",
        deed_url="https://www.stlouis-mo.gov/government/departments/recorder/",
    ),
    Market(
        key="KANSASCITY_MO",
        label="Kansas City, MO (Jackson County)",
        county="Jackson",
        state="MO",
        zips=[
            ("64101", "Kansas City"), ("64105", "Kansas City"), ("64106", "Kansas City"),
            ("64108", "Kansas City"), ("64109", "Kansas City"), ("64110", "Kansas City"),
            ("64111", "Kansas City"), ("64112", "Kansas City"), ("64113", "Kansas City"),
            ("64114", "Kansas City"), ("64116", "Kansas City"), ("64117", "Kansas City"),
            ("64118", "Kansas City"), ("64119", "Kansas City"), ("64120", "Kansas City"),
            ("64123", "Kansas City"), ("64124", "Kansas City"), ("64125", "Kansas City"),
            ("64126", "Kansas City"), ("64127", "Kansas City"), ("64128", "Kansas City"),
            ("64129", "Kansas City"), ("64130", "Kansas City"), ("64131", "Kansas City"),
            ("64132", "Kansas City"), ("64133", "Kansas City"), ("64134", "Kansas City"),
            ("64136", "Kansas City"), ("64137", "Kansas City"), ("64138", "Kansas City"),
        ],
        gis_url="https://maps.jacksongov.org/arcgis/rest/services/",
        deed_url="https://www.jacksongov.org/departments/recorder/",
    ),
    Market(
        key="PHILADELPHIA_PA",
        label="Philadelphia, PA (Philadelphia County)",
        county="Philadelphia",
        state="PA",
        zips=[
            ("19102", "Philadelphia"), ("19103", "Philadelphia"), ("19104", "Philadelphia"),
            ("19106", "Philadelphia"), ("19107", "Philadelphia"), ("19111", "Philadelphia"),
            ("19114", "Philadelphia"), ("19115", "Philadelphia"), ("19116", "Philadelphia"),
            ("19118", "Philadelphia"), ("19119", "Philadelphia"), ("19120", "Philadelphia"),
            ("19121", "Philadelphia"), ("19122", "Philadelphia"), ("19123", "Philadelphia"),
            ("19124", "Philadelphia"), ("19125", "Philadelphia"), ("19126", "Philadelphia"),
            ("19128", "Philadelphia"), ("19129", "Philadelphia"), ("19130", "Philadelphia"),
            ("19131", "Philadelphia"), ("19132", "Philadelphia"), ("19133", "Philadelphia"),
            ("19134", "Philadelphia"), ("19135", "Philadelphia"), ("19136", "Philadelphia"),
            ("19137", "Philadelphia"), ("19138", "Philadelphia"), ("19139", "Philadelphia"),
            ("19140", "Philadelphia"), ("19141", "Philadelphia"), ("19142", "Philadelphia"),
            ("19143", "Philadelphia"), ("19144", "Philadelphia"), ("19145", "Philadelphia"),
            ("19146", "Philadelphia"), ("19147", "Philadelphia"), ("19148", "Philadelphia"),
            ("19149", "Philadelphia"), ("19150", "Philadelphia"), ("19151", "Philadelphia"),
            ("19152", "Philadelphia"), ("19153", "Philadelphia"), ("19154", "Philadelphia"),
        ],
        gis_url="https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/",
        deed_url="https://recorder.phila.gov/",
    ),
    Market(
        key="CINCINNATI_OH",
        label="Cincinnati, OH (Hamilton County)",
        county="Hamilton",
        state="OH",
        zips=[
            ("45202", "Cincinnati"), ("45203", "Cincinnati"), ("45204", "Cincinnati"),
            ("45205", "Cincinnati"), ("45206", "Cincinnati"), ("45207", "Cincinnati"),
            ("45208", "Cincinnati"), ("45209", "Cincinnati"), ("45211", "Cincinnati"),
            ("45212", "Cincinnati"), ("45213", "Cincinnati"), ("45214", "Cincinnati"),
            ("45215", "Cincinnati"), ("45216", "Cincinnati"), ("45217", "Cincinnati"),
            ("45218", "Cincinnati"), ("45219", "Cincinnati"), ("45220", "Cincinnati"),
            ("45223", "Cincinnati"), ("45224", "Cincinnati"), ("45225", "Cincinnati"),
            ("45226", "Cincinnati"), ("45227", "Cincinnati"), ("45229", "Cincinnati"),
            ("45230", "Cincinnati"), ("45231", "Cincinnati"), ("45232", "Cincinnati"),
            ("45233", "Cincinnati"), ("45236", "Cincinnati"), ("45237", "Cincinnati"),
            ("45238", "Cincinnati"), ("45239", "Cincinnati"), ("45240", "Cincinnati"),
            ("45241", "Cincinnati"), ("45248", "Cincinnati"),
        ],
        gis_url="https://gis.hamiltonco.org/arcgis/rest/services/",
        deed_url="https://www.hamiltoncountyauditor.org/",
    ),
]
