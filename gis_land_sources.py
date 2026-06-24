"""
Live free land-lead sources -- a PropStream alternative for markets where
a county/city GIS system publishes parcel ownership data directly, queried
live instead of mocked or CSV-exported. Currently just Bexar County (see
Market.land_source in markets.py for why the other three aren't wired up
yet -- confirmed real and free, but each needs one manual download first to
pin down its exact column layout, same "raise rather than guess" philosophy
as every other loader in this project).

run.py tries, per market: real CSV override -> a registered live loader here
-> mock. A market with no entry in LIVE_LAND_LOADERS just falls through to
mock, unchanged from before this module existed.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from land_data import LandLead

BEXAR_PARCELS_URL = "https://maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0/query"

# Texas Comptroller's standard State Property Classification Code for
# "vacant lots and land tracts" -- confirmed live 2026-06-23 against this
# exact layer (State_cd='C1' rows have Houses='0' and TotVal == LandVal).
BEXAR_VACANT_LAND_STATE_CD = "C1"
# Infill-lot ceiling, not a hard rule -- keeps results to the wholesaling
# sweet spot rather than 100+ acre ranch tracts this layer also contains.
BEXAR_MAX_ACRES = 2.0


def _clean(value):
    """BCAD's feed uses the literal string "NULL" for empty fields rather
    than an actual null -- has to be filtered explicitly or it ends up
    printed straight into the mailing address."""
    value = (value or "").strip()
    return "" if value.upper() == "NULL" else value


def fetch_bexar_vacant_land_leads(market, limit=12):
    """Live query against Bexar County's public ArcGIS REST Parcels layer.
    No login, no rate-limit observed, maxRecordCount=1000 per the service's
    own metadata (we ask for far fewer).

    Scoped to market.zips on purpose: permits for Bexar are still mocked
    (see markets.py), and mock builders only ever operate in market.zips,
    so a lead outside that list could never match a builder anyway. Drop
    this filter once Bexar's permit side also goes live on a wider zip set.

    This layer has no sale-history fields -- no last sale price/date, years
    owned, or tax-delinquent status, unlike PropStream. Those come back as
    explicit "unknown" markers (see pitch.py/emailer.py for how that's
    displayed) rather than invented numbers.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"State_cd='{BEXAR_VACANT_LAND_STATE_CD}' AND Houses='0' "
        f"AND LglAcres<={BEXAR_MAX_ACRES} "
        f"AND Zip IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": "Situs,Owner,AddrLn1,AddrLn2,AddrCity,AddrSt,Zip,LandVal,TotVal,LglAcres,Acres,AcctNumb",
        "resultRecordCount": limit,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{BEXAR_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Bexar GIS query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Bexar GIS query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        situs = (attrs.get("Situs") or "").strip()
        owner_name = (attrs.get("Owner") or "").strip()
        zip_code = (attrs.get("Zip") or "").strip()[:5]
        acreage = attrs.get("LglAcres") or attrs.get("Acres") or 0.0
        # Some large/unplatted tracts have no assigned street number, and a
        # few records carry 0 acres (ROW slivers, missing legal description)
        # -- neither is a usable lead, skip rather than show garbage.
        if not situs or not owner_name or not zip_code or acreage <= 0:
            continue

        addr_lines = [_clean(attrs.get("AddrLn1")), _clean(attrs.get("AddrLn2")), _clean(attrs.get("AddrLn3"))]
        owner_street = ", ".join(line for line in addr_lines if line)
        owner_mailing_address = (
            f"{owner_street}, {_clean(attrs.get('AddrCity'))}, "
            f"{_clean(attrs.get('AddrSt'))} {zip_code}"
        )
        # Rough absentee-owner proxy: mailing address doesn't mention the
        # property's own street -- this layer has no explicit flag for it.
        owner_occupied = bool(owner_street) and situs.split()[0] in owner_street

        land_val = attrs.get("LandVal") or 0.0
        tot_val = attrs.get("TotVal") or land_val

        leads.append(LandLead(
            apn=str(attrs.get("AcctNumb") or ""),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=situs,
            city="San Antonio",
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=tot_val,
            last_sale_price=None,    # unknown -- this layer has no sale history
            last_sale_date="unknown",
            years_owned=None,        # unknown -- same reason
            owner_occupied=owner_occupied,
            tax_delinquent=False,    # unknown, not "confirmed not delinquent"
        ))
    return leads


# Keyed by Market.key -- run.py checks this before falling back to mock.
LIVE_LAND_LOADERS = {
    "BEXAR_TX": fetch_bexar_vacant_land_leads,
}
