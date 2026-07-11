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
        key="SHELBY_TN",
        label="Memphis, TN (Shelby County)",
        county="Shelby",
        state="TN",
        zips=[
            ("38106", "Memphis"), ("38107", "Memphis"), ("38108", "Memphis"),
            ("38109", "Memphis"), ("38111", "Memphis"), ("38112", "Memphis"),
            ("38114", "Memphis"), ("38115", "Memphis"), ("38116", "Memphis"),
            ("38117", "Memphis"), ("38118", "Memphis"), ("38119", "Memphis"),
            ("38122", "Memphis"), ("38127", "Memphis"), ("38128", "Memphis"),
        ],
        gis_url="https://scgis.shelbycountytn.gov/serverhigh/rest/services/Parcel/CERTParcel/MapServer/",
        deed_url="https://register.shelby-tn.us/",
    ),
    Market(
        key="HARRIS_TX",
        label="Houston, TX (Harris County)",
        county="Harris",
        state="TX",
        zips=[
            ("77002", "Houston"), ("77004", "Houston"), ("77005", "Houston"),
            ("77008", "Houston"), ("77009", "Houston"), ("77011", "Houston"),
            ("77012", "Houston"), ("77016", "Houston"), ("77020", "Houston"),
            ("77021", "Houston"), ("77026", "Houston"), ("77028", "Houston"),
            ("77033", "Houston"), ("77051", "Houston"), ("77087", "Houston"),
        ],
        gis_url="https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/",
        deed_url="https://www.cclerk.hctx.net/",
    ),
    Market(
        key="WAYNE_MI",
        label="Detroit, MI (Wayne County)",
        county="Wayne",
        state="MI",
        zips=[
            ("48201", "Detroit"), ("48202", "Detroit"), ("48203", "Detroit"),
            ("48204", "Detroit"), ("48205", "Detroit"), ("48206", "Detroit"),
            ("48207", "Detroit"), ("48208", "Detroit"), ("48209", "Detroit"),
            ("48210", "Detroit"), ("48211", "Detroit"), ("48212", "Detroit"),
            ("48213", "Detroit"), ("48214", "Detroit"), ("48215", "Detroit"),
            ("48216", "Detroit"), ("48217", "Detroit"), ("48219", "Detroit"),
            ("48221", "Detroit"), ("48223", "Detroit"), ("48224", "Detroit"),
            ("48227", "Detroit"), ("48228", "Detroit"), ("48235", "Detroit"),
        ],
        gis_url="https://gis.waynecounty.com/arcgis/rest/services/",
        deed_url="https://www.waynecounty.com/elected/coc/register-of-deeds.aspx",
    ),
    Market(
        key="FULTON_GA",
        label="Atlanta, GA (Fulton County)",
        county="Fulton",
        state="GA",
        zips=[
            ("30303", "Atlanta"), ("30305", "Atlanta"), ("30306", "Atlanta"),
            ("30307", "Atlanta"), ("30308", "Atlanta"), ("30309", "Atlanta"),
            ("30310", "Atlanta"), ("30311", "Atlanta"), ("30312", "Atlanta"),
            ("30313", "Atlanta"), ("30314", "Atlanta"), ("30315", "Atlanta"),
            ("30316", "Atlanta"), ("30317", "Atlanta"), ("30318", "Atlanta"),
            ("30319", "Atlanta"), ("30324", "Atlanta"), ("30331", "Atlanta"),
            ("30336", "Atlanta"), ("30337", "Atlanta"), ("30349", "Atlanta"),
        ],
        gis_url="https://gisdata.fultoncountyga.gov/arcgis/rest/services/",
        deed_url="https://www.fultoncountyga.gov/services/property-and-tax",
    ),
    Market(
        key="MARION_IN",
        label="Indianapolis, IN (Marion County)",
        county="Marion",
        state="IN",
        zips=[
            ("46201", "Indianapolis"), ("46202", "Indianapolis"), ("46203", "Indianapolis"),
            ("46204", "Indianapolis"), ("46205", "Indianapolis"), ("46208", "Indianapolis"),
            ("46218", "Indianapolis"), ("46219", "Indianapolis"), ("46221", "Indianapolis"),
            ("46222", "Indianapolis"), ("46224", "Indianapolis"), ("46225", "Indianapolis"),
            ("46226", "Indianapolis"), ("46227", "Indianapolis"), ("46228", "Indianapolis"),
            ("46229", "Indianapolis"), ("46231", "Indianapolis"), ("46235", "Indianapolis"),
            ("46236", "Indianapolis"), ("46239", "Indianapolis"), ("46241", "Indianapolis"),
            ("46254", "Indianapolis"), ("46259", "Indianapolis"), ("46268", "Indianapolis"),
        ],
        gis_url="https://openindy.maps.arcgis.com/arcgis/rest/services/",
        deed_url="https://www.indy.gov/activity/access-property-information",
    ),
]
