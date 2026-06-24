"""
Land lead loading -- normalizes a PropStream-shaped CSV export into LandLead
records, or generates realistic mock leads for any configured market (see
markets.py) when no real export is configured yet.

PropStream has no public API for retail accounts (web UI + CSV export only),
so swapping in real data later is just pointing a market's LAND_CSV_PATH at a
real export -- the column names below match PropStream's standard export
headers, and PropStream's own County/state columns mean load_land_leads
needs no market-specific handling.
"""
import csv
import datetime
import random
from dataclasses import dataclass
from typing import Optional

CURRENT_YEAR = datetime.date.today().year

LAND_USE_TYPES = ["Vacant Land - Residential", "Vacant Land - Commercial", "Vacant Land - Unimproved"]

PROPSTREAM_FIELDS = [
    "APN", "Owner Name", "Owner Mailing Address", "Owner Mailing City",
    "Owner Mailing State", "Owner Mailing Zip", "Property Address",
    "Property City", "Property State", "Property Zip", "County",
    "Land Use", "Lot Size (Acres)", "Assessed Value", "Estimated Value",
    "Last Sale Price", "Last Sale Date", "Years Owned", "Owner Occupied",
    "Tax Delinquent",
]


@dataclass
class LandLead:
    apn: str
    owner_name: str
    owner_mailing_address: str
    property_address: str
    city: str
    state: str
    zip: str
    county: str
    land_use: str
    acreage: float
    assessed_value: float
    estimated_value: float
    # last_sale_price/years_owned are Optional because not every free data
    # source has sale history (e.g. Bexar's live GIS parcels layer) -- None
    # means "unknown", not zero. last_sale_date doubles as the signal: the
    # literal string "unknown" pairs with both being None.
    last_sale_price: Optional[float]
    last_sale_date: str
    years_owned: Optional[int]
    owner_occupied: bool
    tax_delinquent: bool


def _row_to_lead(row):
    return LandLead(
        apn=row["APN"],
        owner_name=row["Owner Name"],
        owner_mailing_address=row["Owner Mailing Address"],
        property_address=row["Property Address"],
        city=row["Property City"],
        state=row["Property State"],
        zip=row["Property Zip"],
        county=row["County"],
        land_use=row["Land Use"],
        acreage=float(row["Lot Size (Acres)"]),
        assessed_value=float(row["Assessed Value"]),
        estimated_value=float(row["Estimated Value"]),
        last_sale_price=float(row["Last Sale Price"]),
        last_sale_date=row["Last Sale Date"],
        years_owned=int(row["Years Owned"]),
        owner_occupied=row["Owner Occupied"].strip().upper() == "Y",
        tax_delinquent=row["Tax Delinquent"].strip().upper() == "Y",
    )


def load_land_leads(csv_path):
    """Load a real PropStream export. Raises if a column is missing/renamed --
    that's a signal to update PROPSTREAM_FIELDS/_row_to_lead to match the
    actual export rather than silently guessing."""
    with open(csv_path, newline="") as f:
        return [_row_to_lead(row) for row in csv.DictReader(f)]


def generate_mock_land_leads(market, count=15, seed=None):
    rng = random.Random(seed)
    owner_first = ["James", "Maria", "Robert", "Linda", "Michael", "Patricia", "David", "Barbara"]
    owner_last = ["Johnson", "Williams", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor"]
    leads = []
    for i in range(count):
        zip_code, city, area_label = rng.choice(market.zips)
        acreage = round(rng.uniform(0.1, 0.6), 2)
        # Infill vacant lots in this price band is exactly the wholesaling sweet spot.
        assessed_value = round(rng.uniform(4000, 28000), -2)
        estimated_value = round(assessed_value * rng.uniform(1.1, 1.6), -2)
        years_owned = rng.randint(2, 22)
        leads.append(LandLead(
            apn=f"{rng.randint(100000, 999999)}-{rng.randint(0,99):02d}",
            owner_name=f"{rng.choice(owner_first)} {rng.choice(owner_last)}",
            owner_mailing_address=f"{rng.randint(100,9900)} {rng.choice(['Oak','Pine','Cedar','Beach','River'])} St, {city}, {market.state} {zip_code}",
            property_address=f"{rng.randint(100,9900)} {rng.choice(['Cypress','Magnolia','Palm','Sunset','Lakeview'])} Ave, {area_label}, {market.state} {zip_code}",
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use=rng.choice(LAND_USE_TYPES),
            acreage=acreage,
            assessed_value=assessed_value,
            estimated_value=estimated_value,
            last_sale_price=round(assessed_value * rng.uniform(0.5, 0.9), -2),
            last_sale_date=f"{CURRENT_YEAR - years_owned}-0{rng.randint(1,9)}-1{rng.randint(0,9)}",
            years_owned=years_owned,
            owner_occupied=False,
            tax_delinquent=rng.random() < 0.15,
        ))
    return leads
