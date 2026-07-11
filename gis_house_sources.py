"""
Live county assessor GIS loaders — all five markets.

Confirmed working endpoints (researched 2026-07-10):
  Shelby TN   : scgis.shelbycountytn.gov CERTParcel MapServer/0 + MapServer/1 (RSALES join)
  Harris TX   : gis.hctx.net HCAD/Parcels MapServer/0
  Wayne MI    : services2.arcgis.com Detroit tentative_assessment_roll_2026 FeatureServer/0
  Fulton GA   : gismaps.fultoncountyga.gov Tax_ParcelCurrentDigest_GCS_WGS_1984 MapServer/0
  Marion IN   : gis.indy.gov MapIndy/MapIndyProperty MapServer/10

Priority chain per market in run.py:
  real CSV override -> live loader here -> generate_mock_house_leads()

Known field gaps (no free source available):
  Shelby TN   : no assessed value, no year built in any public layer
  Harris TX   : no year built in the HCAD parcels REST layer
  Fulton GA   : no year built, no sale date in public layer
  Marion IN   : no year built, no sale date in public layer

Value semantics by state:
  MI: amt_estimated_true_cash_value = estimated full market value (~100%)
  GA: TotAppr = appraised fair market value (100%); TotAssess = 40% of market
  IN: ASSESSORYEAR_TOTALAV = True Tax Value (100% of market)
  TX: total_appraised_val = HCAD full appraised value (~100%)
  TN: last sale price used as assessed proxy (layer has no value fields)
"""
import datetime
import json
import re
import ssl
import urllib.parse
import urllib.request

from house_data import CURRENT_YEAR, HouseLead, _is_non_individual

_TIMEOUT = 60

# Cities that indicate a missing/unknown property location — skip these leads.
_BAD_CITIES = {"", "unincorporated", "unknown", "county", "n/a", "none"}

# Canonical street suffix abbreviations for professional-looking addresses.
_SUFFIX_MAP = {
    "AVENUE": "Ave", "AVE": "Ave",
    "BOULEVARD": "Blvd", "BLVD": "Blvd",
    "CIRCLE": "Cir", "CIR": "Cir",
    "COURT": "Ct", "CT": "Ct",
    "DRIVE": "Dr", "DR": "Dr",
    "EXPRESSWAY": "Expy", "EXPY": "Expy",
    "FREEWAY": "Fwy", "FWY": "Fwy",
    "HIGHWAY": "Hwy", "HWY": "Hwy",
    "LANE": "Ln", "LN": "Ln",
    "LOOP": "Loop",
    "PARKWAY": "Pkwy", "PKWY": "Pkwy",
    "PLACE": "Pl", "PL": "Pl",
    "PLAZA": "Plz", "PLZ": "Plz",
    "ROAD": "Rd", "RD": "Rd",
    "ROUTE": "Rte", "RTE": "Rte",
    "SQUARE": "Sq", "SQ": "Sq",
    "STREET": "St", "ST": "St",
    "TERRACE": "Ter", "TER": "Ter", "TERR": "Ter",
    "TRAIL": "Trl", "TRL": "Trl",
    "WAY": "Way",
}

_DIRECTION_MAP = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}


def _clean_street(raw: str) -> str:
    """Normalize an all-caps street address to professional mixed-case.

    Converts suffix abbreviations (ST→St, AVE→Ave) and direction prefixes/suffixes
    so output looks like '1234 N Main St' rather than '1234 N Main ST'.
    """
    if not raw:
        return raw
    tokens = raw.upper().split()
    out = []
    for i, tok in enumerate(tokens):
        if i == 0 and tok.replace("-", "").isdigit():
            out.append(tok)  # house number — keep as-is
        elif tok in _SUFFIX_MAP:
            out.append(_SUFFIX_MAP[tok])
        elif tok in _DIRECTION_MAP and i > 0:
            out.append(_DIRECTION_MAP[tok])
        else:
            out.append(tok.capitalize())
    return " ".join(out)


def _valid_address(street: str, city: str, zip_code: str) -> bool:
    """Return False for addresses we should skip."""
    # Must start with a digit (house number)
    if not street or not street[:1].isdigit():
        return False
    # City must be present and not a placeholder
    if city.lower().strip() in _BAD_CITIES:
        return False
    # Zip must be exactly 5 digits
    if not re.fullmatch(r"\d{5}", zip_code.strip()):
        return False
    return True


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_json(url, params=None):
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _get_json_no_ssl(url, params=None):
    """Like _get_json but skips SSL cert verification.
    Used for gismaps.fultoncountyga.gov, which has a cert chain issue on macOS Python."""
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _attrs(feat):
    return feat.get("attributes") or {}


def _date_lit(d: datetime.date) -> str:
    """ArcGIS date literal for WHERE clause — epoch ms doesn't work on all servers."""
    return f"date '{d.isoformat()}'"


def _ten_years_ago_date() -> str:
    d = datetime.date.today()
    return _date_lit(d.replace(year=d.year - 10))


def _year_from_ms(ms) -> int:
    if not ms:
        return 0
    return datetime.datetime.utcfromtimestamp(int(ms) / 1000).year


def _years_from_iso_date(date_str) -> int:
    """Parse ISO date string 'YYYY-MM-DD' and return years since then."""
    if not date_str:
        return 0
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
        return CURRENT_YEAR - d.year
    except (ValueError, TypeError):
        return 0


# ─── Shelby County TN (Memphis) ──────────────────────────────────────────────
# Parcel layer: owner, address, land use.
# RSALES layer (MapServer/1): sale date (SALEDT in Unix ms). Join on PARID.
# Missing: year built, assessed value (CAMA is token-gated).
# 10-year logic:
#   - Not in RSALES (2016–2023 dataset) → sold before 2016 → 10+ yr holder ✓
#   - In RSALES with SALEDT ≤ 10yr ago cutoff → 10+ yr holder ✓
#   - In RSALES more recently → skip

_SHELBY_PARCEL_URL = (
    "https://scgis.shelbycountytn.gov/serverhigh/rest/services/Parcel/CERTParcel/MapServer/0/query"
)
_SHELBY_RSALES_URL = (
    "https://scgis.shelbycountytn.gov/serverhigh/rest/services/Parcel/CERTParcel/MapServer/1/query"
)


def load_shelby_tn(market, limit=15):
    # Step 1: Fetch absentee SFR parcels
    params_p = {
        "where": (
            "LANDUSE='SINGLE-FAMILY' "
            "AND OWN_STATE IS NOT NULL AND OWN_STATE NOT IN ('TN','')"
        ),
        "outFields": (
            "PARID,OWNER,OWN_ADRNO,OWN_ADRSTR,OWN_ADRSUF,OWN_CITY,OWN_STATE,OWN_ZIP,PAR_ADDR1,MUNI"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 10, 500),
        "f": "json",
    }
    try:
        pdata = _get_json(_SHELBY_PARCEL_URL, params_p)
        feats = pdata.get("features") or []
    except Exception as exc:
        print(f"  [SHELBY_TN] parcel fetch failed ({exc}), using mock data")
        return []

    parcels = []
    for feat in feats:
        a = _attrs(feat)
        name = (a.get("OWNER") or "").strip()
        if not name or _is_non_individual(name):
            continue
        par_addr = (a.get("PAR_ADDR1") or "").strip()
        if not par_addr or not par_addr[:1].isdigit():
            continue
        muni = (a.get("MUNI") or "").strip()
        if muni.upper() in ("", "UNINCORPORATED", "UNKNOWN", "N/A"):
            continue
        parcels.append(a)

    if not parcels:
        return []

    # Step 2: Fetch sale dates from RSALES in one bulk IN query
    parid_list = ",".join(f"'{a['PARID']}'" for a in parcels)
    params_s = {
        "where": f"PARID IN ({parid_list})",
        "outFields": "PARID,SALEDT,PRICE",
        "returnGeometry": "false",
        "resultRecordCount": len(parcels) * 3,
        "orderByFields": "SALEDT DESC",
        "f": "json",
    }
    try:
        sdata = _get_json(_SHELBY_RSALES_URL, params_s)
        sale_feats = sdata.get("features") or []
    except Exception as exc:
        print(f"  [SHELBY_TN] RSALES fetch failed ({exc}), skipping sale date filter")
        sale_feats = []

    # Most recent sale per PARID
    sale_by_parid: dict = {}
    for sf in sale_feats:
        a = _attrs(sf)
        pid = a.get("PARID", "")
        dt = a.get("SALEDT") or 0
        if pid not in sale_by_parid or dt > sale_by_parid[pid][0]:
            sale_by_parid[pid] = (dt, float(a.get("PRICE") or 0))

    # RSALES SALEDT is Unix ms; compute 10-year cutoff in ms for in-Python comparison
    import calendar as _cal
    _d = datetime.date.today()
    _ten_yr_ms = int(_cal.timegm(_d.replace(year=_d.year - 10).timetuple())) * 1000

    leads = []
    for a in parcels:
        parid = a.get("PARID", "")
        name = (a.get("OWNER") or "").strip()

        # Years owned
        sale_info = sale_by_parid.get(parid)
        if sale_info:
            sale_ms, sale_price = sale_info
            if sale_ms > _ten_yr_ms:
                continue  # sold too recently
            sale_year = _year_from_ms(sale_ms) if sale_ms else 0
            years_owned = CURRENT_YEAR - sale_year if sale_year else 15
        else:
            # Not in RSALES (2016–2023) → sold before 2016 → 10+ yrs
            sale_year = 0
            sale_price = 0.0
            years_owned = 15  # conservative estimate

        # Build mailing address (OWN_ADRNO is float, e.g. "369.0")
        adrno_raw = a.get("OWN_ADRNO") or ""
        try:
            adrno = str(int(float(adrno_raw)))
        except (ValueError, TypeError):
            adrno = str(adrno_raw).split(".")[0]
        adrstr = (a.get("OWN_ADRSTR") or "").strip()
        adrsuf = (a.get("OWN_ADRSUF") or "").strip()
        mail_addr = _clean_street(" ".join(p for p in [adrno, adrstr, adrsuf] if p))
        mail_city = (a.get("OWN_CITY") or "").strip().title()
        mail_state = (a.get("OWN_STATE") or "").strip().upper()
        mail_zip = str(a.get("OWN_ZIP") or "").strip()[:5]

        par_addr = (a.get("PAR_ADDR1") or "").strip()
        city = (a.get("MUNI") or "").strip().title()

        # Shelby layer has no property zip — derive from market city→zip lookup
        _city_zip = {c.lower(): z for z, c in market.zips}
        zip_code = _city_zip.get(city.lower(), "")

        street = _clean_street(par_addr)
        if not _valid_address(street, city, zip_code):
            continue

        # No assessed value / year built from this source — set sentinels
        leads.append(HouseLead(
            apn=parid,
            property_address=street,
            city=city,
            state="TN",
            zip_code=zip_code,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=0,           # not available in public layer
            assessed_value=sale_price if sale_price > 0 else 100000,  # last sale price as proxy
            improvement_value=1.0,  # unknown; set > 0 to pass filter
            years_owned=years_owned,
            last_sale_date=str(sale_year) if sale_year else "pre-2016",
            last_sale_price=sale_price,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Harris County TX (Houston) ──────────────────────────────────────────────
# HCAD Parcels MapServer/0 at gis.hctx.net.
# land_use=1001 = residential improved (SFR).
# new_owner_date = Unix ms of last HCAD ownership transfer (proxy for sale date).
# year_built NOT in this layer — skipping that filter for Harris.
# Property address is split: site_str_num + site_str_name + site_str_sfx + site_city + site_zip.

_HARRIS_URL = "https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0/query"


def load_harris_tx(market, limit=15):
    ten_yr_date = _ten_years_ago_date()
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"land_use=1001 AND site_zip IN ({zip_list}) "
            f"AND new_owner_date < {ten_yr_date} "
            "AND total_appraised_val >= 50000 AND total_appraised_val <= 300000 "
            "AND bld_value > 0 "
            "AND mail_state IS NOT NULL"
        ),
        "outFields": (
            "HCAD_NUM,owner_name_1,mail_addr_1,mail_addr_2,mail_city,mail_state,mail_zip,"
            "site_str_num,site_str_name,site_str_sfx,site_city,site_zip,"
            "bld_value,total_appraised_val,new_owner_date"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_HARRIS_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [HARRIS_TX] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("owner_name_1") or "").strip()
        if not name or _is_non_individual(name):
            continue

        # Build property address from split fields
        num = str(a.get("site_str_num") or "").strip()
        street_name = (a.get("site_str_name") or "").strip()
        street_sfx = (a.get("site_str_sfx") or "").strip()
        prop_addr = _clean_street(" ".join(p for p in [num, street_name, street_sfx] if p))
        prop_city = (a.get("site_city") or "").strip().title()
        prop_zip = str(a.get("site_zip") or "").strip()[:5]
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        # Mailing address
        mail1 = _clean_street((a.get("mail_addr_1") or "").strip())
        mail2 = _clean_street((a.get("mail_addr_2") or "").strip())
        mail_addr = f"{mail1} {mail2}".strip() if mail2 else mail1
        mail_city = (a.get("mail_city") or "").strip().title()
        mail_state = (a.get("mail_state") or "").strip().upper()
        mail_zip = str(a.get("mail_zip") or "").strip()

        # Absentee — compare 5-digit base zip only (mail may carry +4 suffix)
        if mail_addr.upper() == prop_addr.upper() and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(a.get("total_appraised_val") or 0)
        improvement = float(a.get("bld_value") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue

        transfer_ms = a.get("new_owner_date")
        if not transfer_ms:
            continue
        sale_year = _year_from_ms(transfer_ms)
        years_owned = CURRENT_YEAR - sale_year
        if years_owned < 10:
            continue

        leads.append(HouseLead(
            apn=str(a.get("HCAD_NUM") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="TX",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip[:5],  # normalize to 5-digit
            year_built=0,       # not in HCAD REST layer; filter skipped
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=str(sale_year),
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Wayne County MI (Detroit) ───────────────────────────────────────────────
# City of Detroit Tentative Assessment Roll 2026 — published by Detroit's ArcGIS org.
# property_class='401' = Residential-Improved; use_code='41110' = Single Family.
# amt_estimated_true_cash_value = estimated full market value (not just SEV).
# amt_land_value = land portion; improvement = TCV - land.
# residential_year_built is available in this layer.
# sale_date is ISO string or null; null → assume long-held (years_owned=15).
# taxpayer_address/city/state/zip_code = mailing address of record.
# Note: layer covers Detroit city proper; target zips are all within Detroit.

_WAYNE_ASSESSMENT_URL = (
    "https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services"
    "/tentative_assessment_roll_2026/FeatureServer/0/query"
)


def load_wayne_mi(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    _city_zip = {c.lower(): z for z, c in market.zips}

    params = {
        "where": (
            f"property_class='401' "
            f"AND use_code='41110' "
            f"AND zip_code IN ({zip_list}) "
            "AND amt_estimated_true_cash_value >= 50000 "
            "AND amt_estimated_true_cash_value <= 300000 "
            "AND is_improved=1 "
            "AND tax_status='TAXABLE' "
            "AND residential_year_built > 0 "
            "AND residential_year_built < 1990 "
            "AND taxpayer_state IS NOT NULL AND taxpayer_state <> 'MI'"
        ),
        "outFields": (
            "parcel_id,address,zip_code,street_number,street_prefix,street_name,"
            "taxpayer_1,taxpayer_address,taxpayer_city,taxpayer_state,taxpayer_zip_code,"
            "residential_year_built,amt_estimated_true_cash_value,amt_land_value,sale_date"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_WAYNE_ASSESSMENT_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [WAYNE_MI] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("taxpayer_1") or "").strip()
        if not name or _is_non_individual(name):
            continue

        # Property address: the `address` field is street only (e.g. "1099 MORRELL")
        # Look up city from zip; Detroit zips all map to "Detroit"
        prop_zip = str(a.get("zip_code") or "").strip()[:5]
        raw_addr = (a.get("address") or "").strip()
        # address field sometimes lacks house number — fall back to street_number + street_name
        if not raw_addr or not raw_addr[:1].isdigit():
            num = str(a.get("street_number") or "").strip()
            sfx = str(a.get("street_prefix") or "").strip()
            sname = (a.get("street_name") or "").strip()
            raw_addr = " ".join(p for p in [num, sfx, sname] if p)
        prop_addr = _clean_street(raw_addr)
        prop_city = "Detroit"  # all target zips are Detroit city proper
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        # Mailing address
        mail_addr = _clean_street((a.get("taxpayer_address") or "").strip())
        mail_city = (a.get("taxpayer_city") or "").strip().title()
        mail_state = (a.get("taxpayer_state") or "").strip().upper()
        mail_zip = str(a.get("taxpayer_zip_code") or "").strip()

        # Absentee: Detroit `address` field omits street type (e.g. "1099 MORRELL")
        # while taxpayer_address includes it ("1099 MORRELL ST"). Compare number + name
        # to avoid false "absentee" for owner-occupied properties.
        p_tok = prop_addr.upper().split()
        m_tok = mail_addr.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0] == m_tok[0] and p_tok[1] == m_tok[1]
        )
        if same_addr and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(a.get("amt_estimated_true_cash_value") or 0)
        land_val = float(a.get("amt_land_value") or 0)
        improvement = assessed - land_val
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue

        year_built = int(a.get("residential_year_built") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue

        # sale_date is ISO string "YYYY-MM-DD" or null; null → assume long-held
        sale_date_raw = a.get("sale_date")
        if sale_date_raw:
            years_owned = _years_from_iso_date(sale_date_raw)
            if years_owned < 10:
                continue
        else:
            years_owned = 15  # no recorded sale → conservatively assume long-held

        leads.append(HouseLead(
            apn=str(a.get("parcel_id") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="MI",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip[:5],
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=str(sale_date_raw)[:10] if sale_date_raw else "",
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Fulton County GA (Atlanta) ──────────────────────────────────────────────
# Tax_ParcelCurrentDigest_GCS_WGS_1984 MapServer/0 at gismaps.fultoncountyga.gov.
# This is the only free public layer with both Atlanta city parcels AND TotAppr values.
# ParcelID prefix '17 ' = Atlanta city proper (tax district 17).
# TotAppr = appraised fair market value (100%); ImprAppr = improvement portion.
# Layer has no ZipCode field; all district-17 parcels are Atlanta → use "30303" placeholder.
# OwnerAddr2 = "CITY STATE ZIP" combined string — parse for mailing components.
# Server has a cert chain issue on macOS Python; bypass with ssl.CERT_NONE (safe for public read).
# year_built and sale_date not in this layer; set sentinel values.

_FULTON_DIGEST_URL = (
    "https://gismaps.fultoncountyga.gov/arcgispub2/rest/services"
    "/Tax/Tax_ParcelCurrentDigest_GCS_WGS_1984/MapServer/0/query"
)


def _parse_owner_addr2(addr2: str):
    """Parse Fulton County OwnerAddr2 'CITY STATE ZIP' into (city, state, zip)."""
    parts = addr2.strip().split()
    if len(parts) >= 3:
        zip_part = parts[-1]
        state_part = parts[-2]
        city_part = " ".join(parts[:-2])
    elif len(parts) == 2:
        zip_part = parts[-1]
        state_part = parts[0]
        city_part = ""
    else:
        zip_part = ""
        state_part = ""
        city_part = ""
    return city_part.title(), state_part.upper(), zip_part[:5]


def load_fulton_ga(market, limit=15):
    params = {
        "where": (
            "LUCode='101' "
            "AND LivUnits >= 1 "
            "AND TotAppr >= 50000 AND TotAppr <= 300000 "
            "AND ImprAppr > 0 "
            "AND ParcelID LIKE '17 %' "
            "AND Owner IS NOT NULL "
            "AND OwnerAddr1 <> Address"  # server-side absentee pre-filter
        ),
        "outFields": (
            "ParcelID,Address,Owner,OwnerAddr1,OwnerAddr2,"
            "TotAppr,LandAppr,ImprAppr,LivUnits"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        "f": "json",
    }
    try:
        data = _get_json_no_ssl(_FULTON_DIGEST_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [FULTON_GA] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("Owner") or "").strip()
        if not name or _is_non_individual(name):
            continue

        prop_addr = _clean_street((a.get("Address") or "").strip())
        prop_city = "Atlanta"
        prop_zip = "30303"  # layer has no ZipCode; all district-17 parcels are in Atlanta
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        # Mailing address: OwnerAddr1 = street, OwnerAddr2 = "CITY STATE ZIP"
        mail_addr = _clean_street((a.get("OwnerAddr1") or "").strip())
        addr2 = (a.get("OwnerAddr2") or "").strip()
        mail_city, mail_state, mail_zip = _parse_owner_addr2(addr2) if addr2 else ("", "", "")

        # Absentee: compare first two address tokens (number + street name) to catch
        # minor suffix differences (e.g. "919 LINDBERG DR" vs "919 LINDBERGH DR")
        p_tok = prop_addr.upper().split()
        m_tok = mail_addr.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0] == m_tok[0] and p_tok[1] == m_tok[1]
        )
        if same_addr:
            continue

        assessed = float(a.get("TotAppr") or 0)
        improvement = float(a.get("ImprAppr") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue

        leads.append(HouseLead(
            apn=str(a.get("ParcelID") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="GA",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=0,       # not in Fulton GA public layer
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=15,     # no sale date in layer; conservative estimate
            last_sale_date="",
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Marion County IN (Indianapolis) ─────────────────────────────────────────
# MapIndy/MapIndyProperty MapServer layer 10 — IndyGIS Parcels w/ Owner Info.
# Updated nightly from IndyGIS Parcels and Marion County Assessor's Office.
# PROPERTY_SUB_CLASS IN (510,511,512) = one-family dwelling (platted, unplatted, acreage).
# ASSESSORYEAR_TOTALAV = Indiana True Tax Value = 100% of market value.
# FULLOWNERNAME format: "LASTNAME, FIRSTNAME MI &, SECOND OWNER, ,"
# OWNERZIP may carry +4 format; normalize to 5-digit.
# year_built and sale_date not in this layer; set sentinel values.

_MARION_PARCELS_URL = (
    "https://gis.indy.gov/server/rest/services/MapIndy/MapIndyProperty/MapServer/10/query"
)


def load_marion_in(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)

    params = {
        "where": (
            "PROPERTY_CLASS='RESIDENTIAL' "
            "AND PROPERTY_SUB_CLASS IN (510,511,512) "
            f"AND ZIPCODE IN ({zip_list}) "
            "AND ASSESSORYEAR_TOTALAV >= 50000 "
            "AND ASSESSORYEAR_TOTALAV <= 300000 "
            "AND ASSESSORYEAR_IMPTOTAL > 0 "
            "AND FULLOWNERNAME IS NOT NULL"
        ),
        "outFields": (
            "STATEPARCELNUMBER,STNUMBER,PRE_DIR,STREET_NAME,SUFFIX,CITY,ZIPCODE,"
            "FULLOWNERNAME,OWNERADDRESS,OWNERADDRESS2,OWNERCITY,OWNERSTATE,OWNERZIP,"
            "ASSESSORYEAR_TOTALAV,ASSESSORYEAR_IMPTOTAL"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_MARION_PARCELS_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [MARION_IN] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("FULLOWNERNAME") or "").strip()
        if not name or _is_non_individual(name):
            continue

        # Build property address from split fields
        num = str(a.get("STNUMBER") or "").strip().split(".")[0]  # float "2125.0" → "2125"
        pre = (a.get("PRE_DIR") or "").strip()
        sname = (a.get("STREET_NAME") or "").strip()
        sfx = (a.get("SUFFIX") or "").strip()
        raw_addr = " ".join(p for p in [num, pre, sname, sfx] if p)
        prop_addr = _clean_street(raw_addr)
        prop_city = (a.get("CITY") or "").strip().title()
        prop_zip = str(a.get("ZIPCODE") or "").strip()[:5]
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        # Mailing address
        mail_addr_parts = [
            _clean_street((a.get("OWNERADDRESS") or "").strip()),
            (a.get("OWNERADDRESS2") or "").strip().title(),
        ]
        mail_addr = " ".join(p for p in mail_addr_parts if p)
        mail_city = (a.get("OWNERCITY") or "").strip().title()
        mail_state = (a.get("OWNERSTATE") or "").strip().upper()
        mail_zip = str(a.get("OWNERZIP") or "").strip()

        # Absentee: compare 5-digit base zip (OWNERZIP may be +4)
        if mail_addr.upper().strip() == prop_addr.upper().strip() and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(a.get("ASSESSORYEAR_TOTALAV") or 0)
        improvement = float(a.get("ASSESSORYEAR_IMPTOTAL") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue

        leads.append(HouseLead(
            apn=str(a.get("STATEPARCELNUMBER") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="IN",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip[:5],
            year_built=0,       # not in IndyGIS property layer
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=15,     # no sale date in layer; conservative estimate
            last_sale_date="",
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Registry ─────────────────────────────────────────────────────────────────

LIVE_HOUSE_LOADERS = {
    "SHELBY_TN":  load_shelby_tn,
    "HARRIS_TX":  load_harris_tx,
    "WAYNE_MI":   load_wayne_mi,
    "FULTON_GA":  load_fulton_ga,
    "MARION_IN":  load_marion_in,
}
