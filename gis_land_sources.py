"""
Live free land-lead sources -- a PropStream alternative for markets where
a county/city/state GIS system publishes parcel ownership data directly,
queried live instead of mocked or CSV-exported. All 4 markets are wired up
as of 2026-06-24 -- Duval and Williamson via re-research that found a live
ArcGIS layer where the original plan (a static bulk-file download) had hit
a JS-rendering wall; Gwinnett by finding the *other* layer on a FeatureServer
already partially checked (layer 0 was cadastral-only, layer 3 has owner +
value). Lesson generalized: a live ArcGIS REST/Feature Service with owner
fields beats a bulk-download page almost every time -- check sharing.
arcgis.com's search API broadly (by county name, "tax assessor", "CAMA",
"property owner") before concluding a market has no live option.

run.py tries, per market: real CSV override -> a registered live loader here
-> mock. No market currently falls through to mock as of 2026-06-24, but the
fallback stays in case a source ever goes dark.
"""
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

from land_data import CURRENT_YEAR, LandLead

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


FL_PARCELS_URL = "https://services5.arcgis.com/GcvM6vDlR2gM4x31/arcgis/rest/services/FL_Parcels/FeatureServer/0/query"
# Florida DOR's statewide standard Use Code for "Vacant Residential" --
# confirmed live 2026-06-24 (rows filtered on this have no street number on
# PHY_ADDR1, the same vacant-land signature seen in every other market).
DUVAL_VACANT_RESIDENTIAL_DOR_UC = "000"
DUVAL_MAX_ACRES = 2.0


def fetch_duval_vacant_land_leads(market, limit=12):
    """Live query against Florida's statewide parcels Feature Service --
    sourced from the same annual DOR NAL submission every FL county
    property appraiser makes (the exact static file markets.py originally
    pointed at, which a JS-rendered document library blocked downloading
    programmatically) -- just exposed here as a live, queryable Feature
    Service instead. Confirmed live 2026-06-24.

    Unlike Bexar, this layer DOES carry real sale history (SALE_PRC1/
    SALE_YR1/SALE_MO1) and a Wetlands flag when available -- richer than
    even PropStream would have given for this market. Still falls back to
    "unknown" rather than 0 when a given parcel's sale fields are blank.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"CountyName='Duval' AND DOR_UC='{DUVAL_VACANT_RESIDENTIAL_DOR_UC}' "
        f"AND Acres<={DUVAL_MAX_ACRES} "
        f"AND PHY_ZIPCD IN ({','.join(zips)})"
    )
    params = {
        "where": where,
        "outFields": (
            "PARCEL_ID,OWN_NAME,OWN_ADDR1,OWN_ADDR2,OWN_CITY,OWN_STATE,OWN_ZIPCD,"
            "PHY_ADDR1,PHY_ADDR2,PHY_CITY,PHY_ZIPCD,LND_VAL,JV,Acres,"
            "SALE_PRC1,SALE_YR1,SALE_MO1"
        ),
        "resultRecordCount": limit,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{FL_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Duval/FL_Parcels query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Duval/FL_Parcels query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        situs = " ".join(s for s in [str(attrs.get("PHY_ADDR1") or "").strip(),
                                      str(attrs.get("PHY_ADDR2") or "").strip()] if s)
        owner_name = (attrs.get("OWN_NAME") or "").strip()
        zip_code = str(int(attrs["PHY_ZIPCD"])) if attrs.get("PHY_ZIPCD") else ""
        acreage = attrs.get("Acres") or 0.0
        if not situs or not owner_name or not zip_code or acreage <= 0:
            continue

        owner_street = ", ".join(s.strip() for s in
                                  [attrs.get("OWN_ADDR1") or "", attrs.get("OWN_ADDR2") or ""] if s and s.strip())
        owner_zip = str(int(attrs["OWN_ZIPCD"])) if attrs.get("OWN_ZIPCD") else ""
        owner_mailing_address = (
            f"{owner_street}, {(attrs.get('OWN_CITY') or '').strip()}, "
            f"{(attrs.get('OWN_STATE') or '').strip()} {owner_zip}"
        )
        owner_occupied = bool(owner_street) and situs.split()[0] in owner_street

        sale_price = attrs.get("SALE_PRC1") or 0
        sale_year = int(attrs.get("SALE_YR1") or 0)
        if sale_price > 0 and sale_year > 0:
            last_sale_price = sale_price
            last_sale_date = f"{sale_year}-{(attrs.get('SALE_MO1') or '01').strip().zfill(2)}"
            years_owned = max(CURRENT_YEAR - sale_year, 0)
        else:
            last_sale_price, last_sale_date, years_owned = None, "unknown", None

        land_val = attrs.get("LND_VAL") or 0.0
        leads.append(LandLead(
            apn=str(attrs.get("PARCEL_ID") or ""),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=situs,
            city=(attrs.get("PHY_CITY") or "Jacksonville").strip(),
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Land - Residential",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=attrs.get("JV") or land_val,
            last_sale_price=last_sale_price,
            last_sale_date=last_sale_date,
            years_owned=years_owned,
            owner_occupied=owner_occupied,
            tax_delinquent=False,  # unknown -- not in this layer
        ))
        if len(leads) >= limit:
            break
    return leads


GWINNETT_PROPERTY_TAX_URL = (
    "https://services3.arcgis.com/RfpmnkSAQleRbndX/arcgis/rest/services/Property_and_Tax/FeatureServer/3/query"
)
# Gwinnett's own property-class code for "Residential Vacant" -- confirmed
# live 2026-06-24 against this exact table (distinct from PROPCLAS 300/600/
# 650/700, the commercial/exempt/other/utility vacant-land variants).
GWINNETT_VACANT_RESIDENTIAL_PROPCLAS = "100"
GWINNETT_MAX_ACRES = 2.0


def fetch_gwinnett_vacant_land_leads(market, limit=12):
    """Live query against Gwinnett County's own 'Property and Tax Table'
    (layer 3 of the Property_and_Tax FeatureServer -- layer 0 on this same
    service is cadastral-only, no owner/value, and was correctly rejected
    earlier; layer 3 has everything PropStream would have given except
    sale history, which this table doesn't carry)."""
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"PROPCLAS='{GWINNETT_VACANT_RESIDENTIAL_PROPCLAS}' "
        f"AND LOCZIP IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": "PIN,LOCADDR,LOCCITY,LOCSTATE,LOCZIP,OWNER1,MAILADDR,MAILCITY,MAILSTAT,MAILZIP,LEGALAC,LANDVAL1,TOTVAL1",
        "resultRecordCount": limit,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{GWINNETT_PROPERTY_TAX_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gwinnett property/tax query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Gwinnett property/tax query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        situs = (attrs.get("LOCADDR") or "").strip()
        owner_name = (attrs.get("OWNER1") or "").strip()
        zip_code = (attrs.get("LOCZIP") or "").strip()[:5]
        try:
            acreage = float((attrs.get("LEGALAC") or "0").strip())
        except ValueError:
            acreage = 0.0
        if not situs or not owner_name or not zip_code or acreage <= 0 or acreage > GWINNETT_MAX_ACRES:
            continue

        mail_addr = (attrs.get("MAILADDR") or "").strip()
        owner_mailing_address = (
            f"{mail_addr}, {(attrs.get('MAILCITY') or '').strip()}, "
            f"{(attrs.get('MAILSTAT') or '').strip()} {(attrs.get('MAILZIP') or '').strip()}"
        )
        owner_occupied = bool(mail_addr) and situs.split()[0] in mail_addr

        try:
            land_val = float(attrs.get("LANDVAL1") or 0)
            tot_val = float(attrs.get("TOTVAL1") or 0) or land_val
        except ValueError:
            land_val = tot_val = 0.0

        leads.append(LandLead(
            apn=(attrs.get("PIN") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=situs,
            city=(attrs.get("LOCCITY") or "").strip(),
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Residential Vacant",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=tot_val,
            last_sale_price=None,     # unknown -- this table has no sale history
            last_sale_date="unknown",
            years_owned=None,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
        if len(leads) >= limit:
            break
    return leads


# HTTP, not HTTPS -- this government server's TLS cert doesn't validate
# (confirmed live 2026-06-24); the data is public record, low risk over
# plain HTTP, and curl/urllib both fail closed on the broken cert otherwise.
WILLIAMSON_PARCELS_URL = "http://arcgis2.williamsoncounty-tn.gov/arcgis/rest/services/IDT/DataPull/MapServer/4/query"
WILLIAMSON_MAX_ACRES = 2.0


def fetch_williamson_vacant_land_leads(market, limit=12):
    """Live query against Williamson County's own GIS parcels attribute
    table (IDT/DataPull MapServer, layer 4). Confirmed live 2026-06-24.

    No explicit land-use code field like Duval's DOR_UC or Gwinnett's
    PROPCLAS -- vacant land is inferred as imp_assess<=0 AND total_asse>0
    (no improvement value), the same style of inference used for Bexar.

    Real caveat, not glossed over: this layer's CITY field turned out to be
    a numeric municipality code with no resolvable lookup table (checked --
    the REST metadata's domain is None), and there's no property-zip field
    at all (own_zip is the OWNER's mailing zip, not the parcel's). Rather
    than fake a precise city/zip, every lead here gets market.zips[0] as a
    placeholder -- wrong in detail but structurally valid. This is fine for
    now because this market doesn't run yet regardless (still gated off on
    the permit side, see markets.py) -- solve city/zip for real (most likely
    via reverse-geocoding the parcel geometry) before that gate ever lifts.
    """
    placeholder_zip, placeholder_city, _area = market.zips[0]

    where = f"imp_assess<=0 AND total_asse>0 AND PARCEL_TYP=1 AND AC<={WILLIAMSON_MAX_ACRES}"
    params = {
        "where": where,
        "outFields": "parcel_id,owner1,own_street,own_city,own_state,own_zip,ADDRESS,AC,land_asses,total_asse,pxfer_date,considerat",
        "resultRecordCount": limit,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{WILLIAMSON_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Williamson parcels query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Williamson parcels query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        situs = (attrs.get("ADDRESS") or "").strip()
        owner_name = (attrs.get("owner1") or "").strip()
        city = placeholder_city
        zip_code = placeholder_zip
        acreage = attrs.get("AC") or 0.0
        if not situs or not owner_name or acreage <= 0:
            continue

        own_street = (attrs.get("own_street") or "").strip()
        owner_mailing_address = (
            f"{own_street}, {(attrs.get('own_city') or '').strip()}, "
            f"{(attrs.get('own_state') or '').strip()} {(attrs.get('own_zip') or '').strip()}"
        )
        owner_occupied = bool(own_street) and situs.split()[0] in own_street

        sale_price = attrs.get("considerat") or 0
        pxfer_ms = attrs.get("pxfer_date")
        if sale_price > 0 and pxfer_ms:
            sale_dt = datetime.datetime.utcfromtimestamp(pxfer_ms / 1000)
            last_sale_price = sale_price
            last_sale_date = sale_dt.strftime("%Y-%m-%d")
            years_owned = max(CURRENT_YEAR - sale_dt.year, 0)
        else:
            last_sale_price, last_sale_date, years_owned = None, "unknown", None

        land_val = attrs.get("land_asses") or 0.0
        leads.append(LandLead(
            apn=(attrs.get("parcel_id") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=situs,
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=attrs.get("total_asse") or land_val,
            last_sale_price=last_sale_price,
            last_sale_date=last_sale_date,
            years_owned=years_owned,
            owner_occupied=owner_occupied,
            tax_delinquent=False,
        ))
        if len(leads) >= limit:
            break
    return leads


# Keyed by Market.key -- run.py checks this before falling back to mock.
LIVE_LAND_LOADERS = {
    "BEXAR_TX": fetch_bexar_vacant_land_leads,
    "JACKSONVILLE_FL": fetch_duval_vacant_land_leads,
    "GWINNETT_GA": fetch_gwinnett_vacant_land_leads,
    "WILLIAMSON_TN": fetch_williamson_vacant_land_leads,
}
