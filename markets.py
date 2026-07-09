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
        key="CUYAHOGA_OH",
        label="Cleveland, OH (Cuyahoga County)",
        county="Cuyahoga",
        state="OH",
        zips=[
            ("44102", "Cleveland"), ("44103", "Cleveland"), ("44104", "Cleveland"),
            ("44105", "Cleveland"), ("44108", "Cleveland"), ("44109", "Cleveland"),
            ("44111", "Cleveland"), ("44113", "Cleveland"), ("44114", "Cleveland"),
            ("44120", "Cleveland"), ("44121", "South Euclid"), ("44122", "Beachwood"),
            ("44125", "Garfield Heights"), ("44128", "Warrensville Heights"),
            ("44130", "Middleburg Heights"), ("44134", "Parma"), ("44135", "Cleveland"),
        ],
        gis_url="https://data-cuyahoga.opendata.arcgis.com/",
        deed_url="https://cuyahogacounty.us/recorder/search",
    ),
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
        gis_url="https://www.assessor.shelby-tn.us/",
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
        gis_url="https://pdata.hcad.org/download/index.html",
        deed_url="https://www.cclerk.hctx.net/",
    ),
    Market(
        key="JEFFERSON_AL",
        label="Birmingham, AL (Jefferson County)",
        county="Jefferson",
        state="AL",
        zips=[
            ("35203", "Birmingham"), ("35204", "Birmingham"), ("35205", "Birmingham"),
            ("35206", "Birmingham"), ("35207", "Birmingham"), ("35208", "Birmingham"),
            ("35209", "Birmingham"), ("35210", "Birmingham"), ("35211", "Birmingham"),
            ("35212", "Birmingham"), ("35214", "Birmingham"), ("35215", "Birmingham"),
            ("35217", "Birmingham"), ("35218", "Birmingham"), ("35221", "Birmingham"),
        ],
        gis_url="https://www.jccal.org/Sites/Jefferson_County/pages/page/Assessor-Property-Search",
        deed_url="https://www.jccal.org/Sites/Jefferson_County/pages/page/Judge-of-Probate",
    ),
    Market(
        key="DUVAL_FL",
        label="Jacksonville, FL (Duval County)",
        county="Duval",
        state="FL",
        zips=[
            ("32202", "Jacksonville"), ("32204", "Jacksonville"), ("32205", "Jacksonville"),
            ("32206", "Jacksonville"), ("32208", "Jacksonville"), ("32209", "Jacksonville"),
            ("32210", "Jacksonville"), ("32211", "Jacksonville"), ("32216", "Jacksonville"),
            ("32218", "Jacksonville"), ("32219", "Jacksonville"), ("32220", "Jacksonville"),
            ("32221", "Jacksonville"), ("32244", "Jacksonville"), ("32254", "Jacksonville"),
        ],
        gis_url="https://paopropertydata.coj.net/",
        deed_url="https://oncore.duvalclerk.com/",
    ),
]
