"""
Live free land-lead sources -- a PropStream alternative for markets where
a county/city/state GIS system publishes parcel ownership data directly,
queried live instead of mocked or CSV-exported. All 4 active markets are
wired up (Mecklenburg NC, Maricopa AZ, Davidson TN, Wake NC).

run.py tries, per market: real CSV override -> a registered live loader here
-> mock. No market currently falls through to mock, but the fallback stays
in case a source ever goes dark.
"""
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from flood_wetlands import centroid_of_rings, passes_flood_wetlands_filter
from land_data import CURRENT_YEAR, LandLead

# Owner-name patterns meaning a business/builder/trust/estate, not an
# individual person -- added 2026-06-24 after live Medina/Atascosa leads
# came back owned by PERRY HOMES, DAVID WEEKLEY HOMES, etc. (the original
# seller already sold to a builder, so there's no raw land deal left to
# wholesale there). Each pattern is wrapped in \b...\b (whole-word, not a
# raw substring check) -- a plain "INC" substring match would wrongly
# exclude a real surname like "PRINCE" or "INCERA", both confirmed present
# in this data. A few patterns allow an optional suffix to catch a real,
# confirmed-live word variant without widening the match into a prefix risk
# -- e.g. \bINC(?:ORPORATED)?\b catches both "INC" and "INCORPORATED" while
# still correctly rejecting "INCERA" (the trailing \b still has to hold).
# User's original list was LLC/INC/CORP/HOMES/CONSTRUCTION/BUILDERS/REALTY/
# TRUST/ESTATE; LP/LTD/HOLDINGS/CO added after by explicit request. COMPANY
# and ASSOCIATION/HOA added 2026-06-25 -- confirmed live in real Mecklenburg
# data ("NISBET OIL COMPANY", a homeowners association) neither matching any
# existing pattern. CENTER added same day -- confirmed live in real Wake
# County data ("BEGINNING & BEYOND CHILD DEVELOPMENT CENTER") slipping
# through despite matching none of the above. TR (abbreviation for Trust)
# added same day -- confirmed live in real Maricopa data ("... FAM REV TR"
# for "Family Revocable Trust") slipping through TRUST's full-word pattern.
# All unambiguously not individuals, same spirit as the rest.
NON_INDIVIDUAL_OWNER_PATTERNS = (
    r"LLC", r"INC(?:ORPORATED)?", r"CORP(?:ORATION)?", r"HOMES", r"CONSTRUCTION",
    r"BUILDERS?", r"REALTY", r"TRUST(?:EES?)?", r"TR", r"ESTATES?", r"LP", r"LTD", r"HOLDINGS?", r"CO",
    r"COMPANY", r"ASSOCIATION", r"HOA", r"CENTER",
)
_NON_INDIVIDUAL_OWNER_RE = re.compile(
    r"\b(?:" + "|".join(NON_INDIVIDUAL_OWNER_PATTERNS) + r")\b", re.IGNORECASE,
)


def _is_non_individual_owner(name):
    return bool(_NON_INDIVIDUAL_OWNER_RE.search(name))

BEXAR_PARCELS_URL = "https://maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0/query"
BEXAR_VACANT_LAND_STATE_CD = "C1"
BEXAR_MAX_ACRES = 2.0


def _clean(value):
    """BCAD's feed uses the literal string "NULL" for empty fields."""
    value = (value or "").strip()
    return "" if value.upper() == "NULL" else value


def fetch_bexar_vacant_land_leads(market, limit=12):
    """Live query against Bexar County's public ArcGIS REST Parcels layer.
    ImprVal<=0 added as a secondary guard: Houses='0' alone is stale on
    confirmed-live parcels with fence/septic improvement value.
    No sale-history fields on this layer -- those come back as 'unknown'.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"State_cd='{BEXAR_VACANT_LAND_STATE_CD}' AND Houses='0' AND ImprVal<=0 "
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
        if not situs or not owner_name or not zip_code or acreage <= 0:
            continue

        addr_lines = [_clean(attrs.get("AddrLn1")), _clean(attrs.get("AddrLn2")), _clean(attrs.get("AddrLn3"))]
        owner_street = ", ".join(line for line in addr_lines if line)
        owner_mailing_address = (
            f"{owner_street}, {_clean(attrs.get('AddrCity'))}, "
            f"{_clean(attrs.get('AddrSt'))} {zip_code}"
        )
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
            last_sale_price=None,
            last_sale_date="unknown",
            years_owned=None,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
    return leads


def _get_json(url, timeout=30):
    """Plain GET with a spoofed User-Agent -- some government-hosted ArcGIS
    Servers (not Esri's own arcgis.com hosting) 403 on Python's default
    urllib User-Agent, confirmed live on Mecklenburg's server 2026-06-25
    (same family of gotcha as live_permit_sources.py's S3/Resend note)."""
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _sale_history_or_unknown(sale_price, sale_date_epoch_ms, min_price=100):
    """Several of the 2026-06-25 markets have real sale price/date fields,
    but with some trivial/non-arm's-length values mixed in (family
    transfers, $0/$1 nominal deeds -- confirmed live on Mecklenburg/
    Maricopa/Davidson). A floor on price avoids showing those as if they
    were real market sales, same spirit as Williamson's inline version of
    this same check."""
    if not sale_price or sale_price < min_price or not sale_date_epoch_ms:
        return None, "unknown", None
    sale_dt = datetime.datetime.utcfromtimestamp(sale_date_epoch_ms / 1000)
    years_owned = max(CURRENT_YEAR - sale_dt.year, 0)
    return sale_price, sale_dt.strftime("%Y-%m-%d"), years_owned


MECKLENBURG_PARCELS_URL = (
    "https://meckgis.mecklenburgcountync.gov/server/rest/services/TaxParcel_camadata/FeatureServer/0/query"
)
MECKLENBURG_MAX_ACRES = 2.0
# Confirmed live 2026-06-25: vacorimprov='VAC' alone is unreliable (37% of
# "VAC"-coded parcels actually carry a positive building value, one up to
# $1.18M) and isn't restricted to residential land by default (returns
# INDUSTRIAL/COMMERCIAL/MOBILE HOME PARK/golf-course/utility-ROW/no-build-
# floodway parcels too) -- both totalbldgval<=0 and an 'R1' land-use-code
# prefix (single-family-residential variants) are needed together.
MECKLENBURG_RESIDENTIAL_LUSECODE_PREFIX = "R1"


def fetch_mecklenburg_vacant_land_leads(market, limit=12):
    """Live query against Mecklenburg County's own 'TaxParcel_camadata'
    ArcGIS Feature Service. xcoord/ycoord are latitude/longitude
    respectively despite the names (confirmed live -- NOT the usual
    x=longitude/y=latitude convention) -- used directly for the flood/
    wetlands filter, no centroid computation needed. Full lead-quality
    filter stack applied: individual owner only, vacant only, real street
    number required, FEMA Zone X (unshaded) only, no NWI wetlands.
    """
    zips = [z for z, _c, _a in market.zips]
    where = (
        f"vacorimprov='VAC' AND totalbldgval<=0 AND totalac<={MECKLENBURG_MAX_ACRES} "
        f"AND lusecode LIKE '{MECKLENBURG_RESIDENTIAL_LUSECODE_PREFIX}%' "
        f"AND streetnumber IS NOT NULL "
        f"AND ownrlstnme NOT LIKE '%CITY OF%' AND ownrlstnme NOT LIKE '%COUNTY%' "
        f"AND ownrlstnme NOT LIKE '%TOWN OF%' AND totlandval>=2000 "
        f"AND zipcode IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": (
            "pid,streetnumber,streetname,city,zipcode,ownrlstnme,ownrfrstnme,"
            "mailaddr1,mailaddr2,state,totlandval,totalbldgval,totalvalue,totalac,"
            "xcoord,ycoord,saledate,saleprice"
        ),
        "resultRecordCount": limit * 3,  # over-fetch -- flood/wetlands filtering happens after this
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{MECKLENBURG_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Mecklenburg parcels query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Mecklenburg parcels query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        owner_name = " ".join(
            p.strip() for p in [attrs.get("ownrfrstnme"), attrs.get("ownrlstnme")] if p and p.strip()
        )
        if not owner_name or _is_non_individual_owner(owner_name):
            continue
        street_number = (attrs.get("streetnumber") or "").strip()
        if not street_number:
            continue
        situs = f"{street_number} {(attrs.get('streetname') or '').strip()}"
        city = (attrs.get("city") or "").strip()
        zip_code = (attrs.get("zipcode") or "").strip()[:5]
        acreage = attrs.get("totalac") or 0.0
        if not city or not zip_code or acreage <= 0:
            continue
        try:
            lat, lon = float(attrs.get("xcoord")), float(attrs.get("ycoord"))
        except (TypeError, ValueError):
            continue
        if not passes_flood_wetlands_filter(lat, lon):
            continue

        mail_addr = (attrs.get("mailaddr1") or "").strip()
        mail_addr2 = (attrs.get("mailaddr2") or "").strip()
        owner_mailing_address = ", ".join(p for p in [mail_addr, mail_addr2] if p)
        owner_occupied = bool(owner_mailing_address) and situs.split()[0] in owner_mailing_address

        sale_price, sale_date, years_owned = _sale_history_or_unknown(
            attrs.get("saleprice"), attrs.get("saledate"),
        )
        land_val = attrs.get("totlandval") or 0.0
        leads.append(LandLead(
            apn=(attrs.get("pid") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=f"{situs}, {city}",
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Residential Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=attrs.get("totalvalue") or land_val,
            last_sale_price=sale_price,
            last_sale_date=sale_date,
            years_owned=years_owned,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
        if len(leads) >= limit:
            break
    return leads


MARICOPA_PARCELS_URL = "https://gis.maricopa.gov/arcgis/rest/services/IndividualService/Parcel/MapServer/1/query"
MARICOPA_MAX_ACRES = 2.0
# Vacant Residential Urban Subdivided / Non-Subdivided -- confirmed live
# 2026-06-25; excludes commercial/industrial/federal/municipal vacant codes
# (0021/0022/0031/9400/9405/9700/9705).
MARICOPA_VACANT_USE_CODES = ("0011", "0012")


def fetch_maricopa_vacant_land_leads(market, limit=12):
    """Live query against the Maricopa County Assessor's 'Parcel' layer.
    Longitude_DD/Latitude_DD are already decimal degrees (no Web Mercator
    conversion needed) -- used directly for the flood/wetlands filter. Full
    lead-quality filter stack applied, scoped to Mesa zips (see
    markets.py's MARICOPA_AZ for why -- Mesa is the only confirmed-free
    permit source with real builder names in this county).
    """
    zips = [z for z, _c, _a in market.zips]
    use_codes = ",".join(repr(c) for c in MARICOPA_VACANT_USE_CODES)
    where = (
        f"PropertyUseCode IN ({use_codes}) AND ImprovementFullCashValue<=0 "
        f"AND LotSize_Acre<={MARICOPA_MAX_ACRES} AND LandFullCashValue>=2000 "
        f"AND PropertyStreetNumber IS NOT NULL "
        f"AND OwnerName NOT LIKE '%CITY OF%' AND OwnerName NOT LIKE '%COUNTY%' "
        f"AND OwnerName NOT LIKE '%TOWN OF%' "
        f"AND PropertyZipCode IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": (
            "APN,OwnerName,OwnerAddressLine1,OwnerAddressLine2,OwnerCity,OwnerState,OwnerZipCode,"
            "PropertyStreetNumber,PropertyStreetName,PropertyStreetType,PropertyCity,PropertyZipCode,"
            "LandFullCashValue,ImprovementFullCashValue,LotSize_Acre,Longitude_DD,Latitude_DD,"
            "SalePrice,SaleDate"
        ),
        "resultRecordCount": limit * 3,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{MARICOPA_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Maricopa parcels query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Maricopa parcels query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        owner_name = (attrs.get("OwnerName") or "").strip()
        if not owner_name or _is_non_individual_owner(owner_name):
            continue
        street_number = (attrs.get("PropertyStreetNumber") or "").strip()
        if not street_number:
            continue
        situs = " ".join(
            p.strip() for p in [street_number, attrs.get("PropertyStreetName"), attrs.get("PropertyStreetType")]
            if p and p.strip()
        )
        city = (attrs.get("PropertyCity") or "").strip()
        zip_code = (attrs.get("PropertyZipCode") or "").strip()[:5]
        acreage = attrs.get("LotSize_Acre") or 0.0
        if not situs or not city or not zip_code or acreage <= 0:
            continue
        lat, lon = attrs.get("Latitude_DD"), attrs.get("Longitude_DD")
        if lat is None or lon is None or not passes_flood_wetlands_filter(lat, lon):
            continue

        addr_lines = [attrs.get("OwnerAddressLine1"), attrs.get("OwnerAddressLine2")]
        owner_street = ", ".join(p.strip() for p in addr_lines if p and p.strip())
        owner_mailing_address = (
            f"{owner_street}, {(attrs.get('OwnerCity') or '').strip()}, "
            f"{(attrs.get('OwnerState') or '').strip()} {(attrs.get('OwnerZipCode') or '').strip()}"
        )
        owner_occupied = bool(owner_street) and situs.split()[0] in owner_street

        sale_price, sale_date, years_owned = _sale_history_or_unknown(
            attrs.get("SalePrice"), attrs.get("SaleDate"),
        )
        land_val = attrs.get("LandFullCashValue") or 0.0
        leads.append(LandLead(
            apn=(attrs.get("APN") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=f"{situs}, {city}",
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Residential Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=land_val,
            last_sale_price=sale_price,
            last_sale_date=sale_date,
            years_owned=years_owned,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
        if len(leads) >= limit:
            break
    return leads


DAVIDSON_PARCELS_URL = "https://maps.nashville.gov/arcgis/rest/services/Cadastral/Parcels/MapServer/0/query"
DAVIDSON_MAX_ACRES = 2.0
# Vacant residential/commercial/multi-family/industrial/rural/exempt codes
# -- confirmed live 2026-06-25, restricted further to plain residential
# below via an 'R'-prefix-style filter isn't available on this schema (no
# such convention here), so all of LUCode 010/020/030/070/080/80M/090 are
# allowed through and the acreage cap + improvement-value check do the
# real work of keeping leads in the wholesaling sweet spot.
DAVIDSON_VACANT_LU_CODES = ("010", "020", "030", "070", "080", "80M", "090")


def fetch_davidson_vacant_land_leads(market, limit=12):
    """Live query against Metro Nashville's 'Parcels' layer. No direct lat/
    lon fields on this schema (unlike Mecklenburg/Maricopa) -- geometry is
    requested with outSR=4326 and centroid-averaged for the flood/wetlands
    filter, same technique used for Williamson/Davidson's TN neighbor
    markets' rural land loaders elsewhere in this file.
    """
    zips = [z for z, _c, _a in market.zips]
    codes = ",".join(repr(c) for c in DAVIDSON_VACANT_LU_CODES)
    where = (
        f"LUCode IN ({codes}) AND ImprAppr<=0 AND Acres<={DAVIDSON_MAX_ACRES} AND LandAppr>=2000 "
        f"AND PropHouse IS NOT NULL AND PropHouse<>'0' "
        f"AND Owner NOT LIKE '%METRO%' AND Owner NOT LIKE '%CITY OF%' AND Owner NOT LIKE '%COUNTY%' "
        f"AND Owner NOT LIKE '%TOWN OF%' "
        f"AND PropZip IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": (
            "APN,Owner,OwnAddr1,OwnAddr2,OwnAddr3,OwnCity,OwnState,OwnZip,"
            "PropHouse,PropStreet,PropCity,PropZip,Acres,LandAppr,ImprAppr,TotlAppr,"
            "SalePrice,OwnDate"
        ),
        "resultRecordCount": limit * 3,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    url = f"{DAVIDSON_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Davidson parcels query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Davidson parcels query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        owner_name = (attrs.get("Owner") or "").strip()
        if not owner_name or _is_non_individual_owner(owner_name):
            continue
        street_number = (attrs.get("PropHouse") or "").strip()
        if not street_number or street_number == "0":
            continue
        situs = f"{street_number} {(attrs.get('PropStreet') or '').strip()}"
        city = (attrs.get("PropCity") or "").strip()
        zip_code = (attrs.get("PropZip") or "").strip()[:5]
        acreage = attrs.get("Acres") or 0.0
        if not city or not zip_code or acreage <= 0:
            continue
        geometry = feature.get("geometry")
        if not geometry or not geometry.get("rings"):
            continue
        lat, lon = centroid_of_rings(geometry["rings"])
        if not passes_flood_wetlands_filter(lat, lon):
            continue

        addr_lines = [attrs.get("OwnAddr1"), attrs.get("OwnAddr2"), attrs.get("OwnAddr3")]
        owner_street = ", ".join(p.strip() for p in addr_lines if p and p.strip())
        owner_mailing_address = (
            f"{owner_street}, {(attrs.get('OwnCity') or '').strip()}, "
            f"{(attrs.get('OwnState') or '').strip()} {(attrs.get('OwnZip') or '').strip()}"
        )
        owner_occupied = bool(owner_street) and situs.split()[0] in owner_street

        sale_price, sale_date, years_owned = _sale_history_or_unknown(
            attrs.get("SalePrice"), attrs.get("OwnDate"),
        )
        land_val = attrs.get("LandAppr") or 0.0
        leads.append(LandLead(
            apn=(attrs.get("APN") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=f"{situs}, {city}",
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Residential Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=attrs.get("TotlAppr") or land_val,
            last_sale_price=sale_price,
            last_sale_date=sale_date,
            years_owned=years_owned,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
        if len(leads) >= limit:
            break
    return leads


WAKE_PARCELS_URL = "https://maps.wake.gov/arcgis/rest/services/Property/Parcels/MapServer/0/query"
WAKE_MAX_ACRES = 2.0


def fetch_wake_vacant_land_leads(market, limit=12):
    """Live query against Wake County's 'Parcels' layer, scoped to Raleigh
    zips (see markets.py's WAKE_NC for why -- Raleigh's own open data is the
    only confirmed-free permit source with real builder names in this
    county; Wake County's own permits layer has null contractor fields).

    CITY is unreliable on this schema -- confirmed live truncated to 3
    characters on some rows (e.g. "CAR" for Cary) -- city is derived from
    market.zips via ZIPNUM instead, never trusted directly from CITY.

    No direct lat/lon field -- geometry requested with outSR=4326 and
    centroid-averaged for the flood/wetlands filter. TOTSALPRICE/SALE_DATE
    were confirmed null on every vacant parcel sampled live -- sale history
    always comes back "unknown" for this market, no point even querying it.
    """
    zip_to_city = {z: c for z, c, _a in market.zips}
    zips = list(zip_to_city)
    where = (
        f"LAND_CLASS='VAC' AND BLDG_VAL<=0 AND DEED_ACRES<={WAKE_MAX_ACRES} AND LAND_VAL>=2000 "
        f"AND STNUM IS NOT NULL "
        f"AND OWNER NOT LIKE '%CITY OF%' AND OWNER NOT LIKE '%COUNTY%' AND OWNER NOT LIKE '%TOWN OF%' "
        f"AND ZIPNUM IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": "PIN_NUM,OWNER,ADDR1,ADDR2,SITE_ADDRESS,STNUM,FULL_STREET_NAME,ZIPNUM,DEED_ACRES,LAND_VAL,BLDG_VAL,TOTAL_VALUE_ASSD",
        "resultRecordCount": limit * 3,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    url = f"{WAKE_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Wake parcels query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Wake parcels query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        owner_name = (attrs.get("OWNER") or "").strip()
        if not owner_name or _is_non_individual_owner(owner_name):
            continue
        street_number = str(attrs.get("STNUM") or "").strip()
        if not street_number:
            continue
        situs = f"{street_number} {(attrs.get('FULL_STREET_NAME') or '').strip()}"
        zip_code = (attrs.get("ZIPNUM") or "").strip()[:5]
        city = zip_to_city.get(zip_code)
        acreage = attrs.get("DEED_ACRES") or 0.0
        if not city or not zip_code or acreage <= 0:
            continue
        geometry = feature.get("geometry")
        if not geometry or not geometry.get("rings"):
            continue
        lat, lon = centroid_of_rings(geometry["rings"])
        if not passes_flood_wetlands_filter(lat, lon):
            continue

        # ADDR1/ADDR2 are owner mailing -- ADDR2 is an unparsed "CITY ST ZIP"
        # string on this schema (confirmed live), not separate fields.
        owner_street = (attrs.get("ADDR1") or "").strip()
        owner_mailing_address = ", ".join(p for p in [owner_street, (attrs.get("ADDR2") or "").strip()] if p)
        owner_occupied = bool(owner_street) and situs.split()[0] in owner_street

        land_val = attrs.get("LAND_VAL") or 0.0
        leads.append(LandLead(
            apn=(attrs.get("PIN_NUM") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=f"{situs}, {city}",
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Residential Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=attrs.get("TOTAL_VALUE_ASSD") or land_val,
            last_sale_price=None,    # unknown -- confirmed null on every vacant parcel sampled
            last_sale_date="unknown",
            years_owned=None,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
        if len(leads) >= limit:
            break
    return leads


# Keyed by Market.key -- run.py checks this before falling back to mock.
LIVE_LAND_LOADERS = {
    "MECKLENBURG_NC": fetch_mecklenburg_vacant_land_leads,
    "MARICOPA_AZ": fetch_maricopa_vacant_land_leads,
    "BEXAR_TX": fetch_bexar_vacant_land_leads,
    "WAKE_NC": fetch_wake_vacant_land_leads,
}
