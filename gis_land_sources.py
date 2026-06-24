"""
Live free land-lead sources -- a PropStream alternative for markets where
a county/city/state GIS system publishes parcel ownership data directly,
queried live instead of mocked or CSV-exported. All 4 active markets are
wired up as of 2026-06-24 (Travis/Austin replaced Jacksonville/Duval that
day -- Duval's land side was actually fine, but its permit side never found
a live source; see markets.py for why). Williamson and Gwinnett needed
re-research that found a live ArcGIS layer where the original plan (a
static bulk-file download) had hit a JS-rendering wall; Gwinnett's owner/
value table turned out to be a different layer on a FeatureServer already
partially checked (layer 0 was cadastral-only); Travis's similarly needed
checking a second, more-complete unofficial copy after the "official" TCAD
service turned out to have land value but no owner field. Lesson
generalized: a live ArcGIS REST/Feature Service with owner fields beats a
bulk-download page almost every time, and a disappointing layer/service is
worth checking siblings of before moving on -- search sharing.arcgis.com's
API broadly (by county name, "tax assessor", "CAMA", "property owner")
before concluding a market has no live option.

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

    ImprVal<=0 added 2026-06-24: Houses='0' alone isn't reliable -- confirmed
    live 23 parcels with Houses='0' but ImprVal>0 (e.g. fences/septic/paving,
    in a few cases up to $500K+ of actual improvement value on parcels BCAD
    still codes as vacant). ImprVal is BCAD's real improvement-value field;
    filtering on it directly catches stale Houses flags that a Street View
    check would otherwise catch manually.
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


TRAVIS_PARCELS_URL = (
    "https://services1.arcgis.com/HGcSYZ5bvjRswoCb/arcgis/rest/services/"
    "TCAD_Parcels_Dec_2025/FeatureServer/0/query"
)
# This is a more complete working copy of TCAD's parcel data than the
# "official" EXTERNAL_tcad_parcel service, which has a land value field but
# no owner field at all -- confirmed live 2026-06-24.
TRAVIS_VACANT_LAND_TYPE_DESC = "VACANT LOT"
TRAVIS_MAX_ACRES = 2.0


def fetch_travis_vacant_land_leads(market, limit=12):
    """Live query against a Travis Central Appraisal District parcel
    Feature Service. Confirmed live 2026-06-24.

    land_homesite_val>0 excludes HOA/common-area slivers, which otherwise
    dominate small samples of 'VACANT LOT' rows (greenbelts, retention
    ponds, etc. carry a token land value but no homesite value). That
    filter alone still let City of Austin-owned right-of-way slivers
    through (confirmed live -- they carry a real homesite value despite
    being unsellable), so owner name is also excluded when it starts with
    a government-entity prefix. deed_date exists on this layer but was
    unpopulated on every record checked -- sale history comes back
    "unknown", same treatment as Bexar.

    imprv_homesite_val<=0 AND imprv_non_homesite_val<=0 added 2026-06-24:
    land_type_desc='VACANT LOT' is stale on a meaningful slice of this data
    -- confirmed live 36 of 3673 candidate rows actually carry a positive
    improvement value, several with F1year_imprv of 2024 and imprv values
    in the hundreds of thousands (i.e. a brand-new house TCAD hasn't
    relabeled yet). Both imprv fields are 0, never NULL, across this
    universe, so the plain <=0 comparison is safe.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"land_type_desc='{TRAVIS_VACANT_LAND_TYPE_DESC}' AND land_homesite_val>0 "
        f"AND imprv_homesite_val<=0 AND imprv_non_homesite_val<=0 "
        f"AND GIS_acres<={TRAVIS_MAX_ACRES} "
        f"AND py_owner_name NOT LIKE 'CITY OF%' AND py_owner_name NOT LIKE 'TRAVIS COUNTY%' "
        f"AND situs_zip IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": (
            "geo_id,py_owner_name,py_address,situs_address,situs_city,situs_zip,"
            "GIS_acres,market_value,land_homesite_val,deed_date"
        ),
        "resultRecordCount": limit,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{TRAVIS_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Travis/TCAD query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Travis/TCAD query failed: {data['error']}")

    leads = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        situs = (attrs.get("situs_address") or "").strip()
        owner_name = (attrs.get("py_owner_name") or "").strip()
        zip_code = (attrs.get("situs_zip") or "").strip()[:5]
        acreage = attrs.get("GIS_acres") or 0.0
        if not situs or not owner_name or not zip_code or acreage <= 0:
            continue

        owner_mailing_address = (attrs.get("py_address") or "").strip()
        owner_occupied = bool(owner_mailing_address) and situs.split()[0] in owner_mailing_address

        # This layer has deed_date but no sale-price field at all -- pitch.py/
        # emailer.py expect price+date together, so there's no useful partial
        # state to report; always "unknown" rather than a date with no price.
        last_sale_price, last_sale_date, years_owned = None, "unknown", None

        market_val = attrs.get("market_value") or attrs.get("land_homesite_val") or 0.0
        leads.append(LandLead(
            apn=(attrs.get("geo_id") or "").strip(),
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=f"{situs}, {(attrs.get('situs_city') or 'Austin').strip()}",
            city=(attrs.get("situs_city") or "Austin").strip(),
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Lot",
            acreage=acreage,
            assessed_value=attrs.get("land_homesite_val") or 0.0,
            estimated_value=market_val,
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
    sale history, which this table doesn't carry).

    DWLGVAL1='0' added 2026-06-24: PROPCLAS='100' alone is stale on at least
    one confirmed-live row (a parcel with LANDVAL1=65300/DWLGVAL1=227200 --
    an actual house -- still coded as Residential Vacant). DWLGVAL1 is this
    table's dwelling-value field; despite being typed as a string, every
    PROPCLAS='100' row checked has it populated as a literal '0' (never
    NULL/blank), so an exact-string filter is safe here.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"PROPCLAS='{GWINNETT_VACANT_RESIDENTIAL_PROPCLAS}' AND DWLGVAL1='0' "
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


def _fetch_bis_cad_vacant_land_leads(market, service_url, max_acres, limit, city_aliases=None):
    """Shared loader for any county on BIS Consulting's CAD web-service schema
    (file_as_name/legal_acreage/land_val/imprv_val/situs_*/addr_line*) --
    Medina and Atascosa Counties' CADs are both hosted on this exact vendor,
    byte-identical field names, confirmed live 2026-06-24.

    No explicit land-use/state-class code field exists on this schema at all
    -- vacant land is inferred the same way Williamson's was: imprv_val<=0
    AND land_val>0 (no improvement value). No sale-price field either (only
    Deed_Date, never paired with a price) -- sale history always comes back
    "unknown", same treatment as Travis's TCAD layer.

    situs_zip is unreliable on this schema -- confirmed live malformed values
    ("778059", "7/8065", "X", plain nulls) on both counties' real data -- so
    leads are scoped and zip-assigned by situs_city instead, matched against
    market.zips' city list (case-insensitive). city_aliases covers any town
    whose CAD-recorded spelling differs from its market.zips display name
    (e.g. Medina CAD spells the town normally written "Lacoste" as "LA COSTE").

    Government/school-district-owned parcels ('CITY OF ...'/'... ISD', in
    either word order, confirmed live on both counties -- e.g. both "CITY OF
    CASTROVILLE" and "HONDO CITY OF") and 'MULTIPLE OWNERS' rows (no single
    contactable owner, and every mailing-address field blank on those rows,
    confirmed live) are excluded. A handful of parcels share one geo_id with
    multiple polygon features (confirmed live on Atascosa) -- deduped here.
    """
    aliases = city_aliases or {}
    cad_city_to_real_city = {aliases.get(c.upper(), c.upper()): c for _z, c, _a in market.zips}
    city_to_zip = {c.upper(): z for z, c, _a in market.zips}

    where = (
        f"imprv_val<=0 AND land_val>0 AND legal_acreage<={max_acres} "
        f"AND NOT (UPPER(file_as_name) LIKE '%CITY OF%' OR UPPER(file_as_name) LIKE '%COUNTY OF%' "
        f"OR UPPER(file_as_name) LIKE '%ISD%') "
        f"AND situs_city IN ({','.join(repr(c) for c in sorted(cad_city_to_real_city))})"
    )
    params = {
        "where": where,
        "outFields": (
            "geo_id,file_as_name,addr_line1,addr_line2,addr_line3,addr_city,addr_state,zip,"
            "situs_num,situs_street,situs_street_sufix,situs_city,legal_acreage,land_val,"
            "imprv_val,market,Deed_Date"
        ),
        "resultRecordCount": limit,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{service_url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"BIS CAD query failed ({service_url}): {e}")
    if "error" in data:
        raise RuntimeError(f"BIS CAD query failed ({service_url}): {data['error']}")

    leads = []
    seen_geo_ids = set()
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        geo_id = (attrs.get("geo_id") or "").strip()
        if geo_id and geo_id in seen_geo_ids:
            continue

        owner_name = (attrs.get("file_as_name") or "").strip()
        if not owner_name or owner_name.upper() == "MULTIPLE OWNERS":
            continue

        situs_street = (attrs.get("situs_street") or "").strip()
        situs_sufix = (attrs.get("situs_street_sufix") or "").strip()
        # situs_street already includes the suffix on some rows (confirmed
        # live, e.g. "CANNON RD" with situs_street_sufix also "RD") -- don't
        # double it up.
        if situs_sufix and situs_street.upper().endswith(situs_sufix.upper()):
            situs_sufix = ""
        situs_parts = [attrs.get("situs_num"), situs_street, situs_sufix]
        situs = " ".join(p.strip() for p in situs_parts if p and p.strip())
        cad_city = (attrs.get("situs_city") or "").strip().upper()
        city = cad_city_to_real_city.get(cad_city)
        zip_code = city_to_zip.get(city.upper()) if city else None
        acreage = attrs.get("legal_acreage") or 0.0
        if not situs or not city or not zip_code or acreage <= 0:
            continue

        addr_lines = [attrs.get("addr_line1"), attrs.get("addr_line2"), attrs.get("addr_line3")]
        owner_street = ", ".join(p.strip() for p in addr_lines if p and p.strip())
        owner_mailing_address = (
            f"{owner_street}, {(attrs.get('addr_city') or '').strip()}, "
            f"{(attrs.get('addr_state') or '').strip()} {(attrs.get('zip') or '').strip()}"
        )
        owner_occupied = bool(owner_street) and situs.split()[0] in owner_street

        land_val = attrs.get("land_val") or 0.0
        market_val = attrs.get("market") or land_val

        if geo_id:
            seen_geo_ids.add(geo_id)
        leads.append(LandLead(
            apn=geo_id,
            owner_name=owner_name,
            owner_mailing_address=owner_mailing_address,
            property_address=f"{situs}, {city}",
            city=city,
            state=market.state,
            zip=zip_code,
            county=market.county,
            land_use="Vacant Land",
            acreage=acreage,
            assessed_value=land_val,
            estimated_value=market_val,
            last_sale_price=None,    # unknown -- this schema has Deed_Date but no price field
            last_sale_date="unknown",
            years_owned=None,
            owner_occupied=owner_occupied,
            tax_delinquent=False,    # unknown -- no delinquency field on this schema
        ))
        if len(leads) >= limit:
            break
    return leads


MEDINA_PARCELS_URL = (
    "https://services6.arcgis.com/j94FvPaik4etwHFk/arcgis/rest/services/MedinaCADWebService/FeatureServer/0/query"
)
MEDINA_MAX_ACRES = 20.0
# Medina CAD's situs_city spells the town normally written "Lacoste" with a
# space -- confirmed live 2026-06-24.
MEDINA_CITY_ALIASES = {"LACOSTE": "LA COSTE"}


def fetch_medina_vacant_land_leads(market, limit=12):
    """Live query against Medina CAD's parcel data (Natalia/Devine/Hondo/
    Castroville/Lacoste). See markets.py's MEDINA_TX.land_source and
    _fetch_bis_cad_vacant_land_leads's docstring for the full detail."""
    return _fetch_bis_cad_vacant_land_leads(
        market, MEDINA_PARCELS_URL, MEDINA_MAX_ACRES, limit, city_aliases=MEDINA_CITY_ALIASES,
    )


ATASCOSA_PARCELS_URL = (
    "https://services8.arcgis.com/q1dyPay4QViMab9g/arcgis/rest/services/AtascosaCADWebService/FeatureServer/0/query"
)
ATASCOSA_MAX_ACRES = 20.0


def fetch_atascosa_vacant_land_leads(market, limit=12):
    """Live query against Atascosa CAD's parcel data (Poteet/Jourdanton/
    Pleasanton). See markets.py's ATASCOSA_TX.land_source and
    _fetch_bis_cad_vacant_land_leads's docstring for the full detail."""
    return _fetch_bis_cad_vacant_land_leads(market, ATASCOSA_PARCELS_URL, ATASCOSA_MAX_ACRES, limit)


# Keyed by Market.key -- run.py checks this before falling back to mock.
LIVE_LAND_LOADERS = {
    "BEXAR_TX": fetch_bexar_vacant_land_leads,
    "TRAVIS_TX": fetch_travis_vacant_land_leads,
    "GWINNETT_GA": fetch_gwinnett_vacant_land_leads,
    "WILLIAMSON_TN": fetch_williamson_vacant_land_leads,
    "MEDINA_TX": fetch_medina_vacant_land_leads,
    "ATASCOSA_TX": fetch_atascosa_vacant_land_leads,
}
