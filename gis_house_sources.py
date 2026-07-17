"""
Live county assessor GIS loaders — all five markets.

Confirmed working endpoints (researched 2026-07-16):
  Baltimore MD   : geodata.baltimorecity.gov CityView/Realproperty_OB FeatureServer/0
  St. Louis MO   : maps8.stlouis-mo.gov ASSESSOR/Assessor_Public_Parcels MapServer/11
  Kansas City MO : jcgis.jacksongov.org ParcelViewer/ParcelsAscendRelate MapServer/2
  Philadelphia PA: phl.carto.com opa_properties_public (Carto SQL API)
  Cincinnati OH  : cagisonline.hamilton-co.org AuditorParcelInformation MapServer/15 + 17

Value semantics by source (all used as assessed_value in HouseLead):
  Baltimore MD   : CURRLAND + CURRIMPR = full assessed (Maryland uses 100% market value)
  St. Louis MO   : AprLand + AprResImprove = full appraised; AsdTotal = 19% of that
  Kansas City MO : Market_Value_Total = full market value
  Philadelphia PA: market_value = 100% OPA appraised value
  Cincinnati OH  : MKT_TOTAL_VAL = full market value (Ohio assessed = 35% of this)
"""
import datetime
import json
import re
import ssl
import urllib.parse
import urllib.request

from house_data import CURRENT_YEAR, HouseLead, _is_non_individual

_TIMEOUT = 60
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

_BAD_CITIES = {"", "unincorporated", "unknown", "county", "n/a", "none"}

_SUFFIX_MAP = {
    "AVENUE": "Ave", "AVE": "Ave", "AV": "Ave",
    "BOULEVARD": "Blvd", "BLVD": "Blvd", "BL": "Blvd",
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
    """Normalize an all-caps street address to professional mixed-case."""
    if not raw:
        return raw
    tokens = raw.upper().split()
    out = []
    for i, tok in enumerate(tokens):
        if i == 0 and tok.replace("-", "").isdigit():
            out.append(tok)
        elif tok in _SUFFIX_MAP:
            out.append(_SUFFIX_MAP[tok])
        elif tok in _DIRECTION_MAP and i > 0:
            out.append(_DIRECTION_MAP[tok])
        else:
            out.append(tok.capitalize())
    return " ".join(out)


def _valid_address(street: str, city: str, zip_code: str) -> bool:
    if not street or not street[:1].isdigit():
        return False
    if city.lower().strip() in _BAD_CITIES:
        return False
    if not re.fullmatch(r"\d{5}", zip_code.strip()):
        return False
    return True


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _get_json(url, params=None):
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _post_json(url, params=None):
    """Like _get_json but POSTs the query body — avoids URL-length limits some
    ArcGIS reverse proxies impose (seen on cagisonline.hamilton-co.org with a
    long PID IN (...) clause, which 404s over GET past ~1600 chars)."""
    body = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"User-Agent": "HouseWholesalePipeline/1.0"}
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _get_json_no_ssl(url, params=None):
    """Like _get_json but skips SSL cert verification for servers with cert issues."""
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _attrs(feat):
    return feat.get("attributes") or {}


def _best_leads(leads, limit):
    """Sort by motivation_score (desc) and take the top `limit`.

    Only motivation_score >= 8 leads are ever sent (see run.py), and that
    threshold is unreachable from years-held/property-age alone (max 4+2=6
    points) — it requires an out-of-state or out-of-country mailing address.
    Keeping raw fetch order and truncating at `limit` would silently drop
    those highest-value candidates whenever they land later in an unordered
    server response, so rank the whole fetched batch before truncating.
    """
    leads.sort(key=lambda l: l.motivation_score, reverse=True)
    return leads[:limit]


def _year_from_ms(ms) -> int:
    if not ms:
        return 0
    return datetime.datetime.utcfromtimestamp(int(ms) / 1000).year


# ─── Address parsing helpers ──────────────────────────────────────────────────

# Matches "...CITY, STATE, ZIP" or "...CITY STATE ZIP" at end of a combined string
_STATE_ZIP_RE = re.compile(r",?\s+([A-Z]{2})[,\s]+(\d{5})", re.IGNORECASE)


def _parse_mail_combined(raw: str):
    """Parse 'STREET [CITY] STATE ZIP' → (street_or_street_city, state, zip5).

    Used for Jackson County address_compl, e.g. '... OAK GROVE, MO 64075',
    where city and street cannot be reliably separated without a city-name
    lookup, and state+zip are space-separated (not double-comma-delimited).
    """
    raw = raw.strip()
    m = _STATE_ZIP_RE.search(raw)
    if m:
        return raw[:m.start()].rstrip(", ").strip(), m.group(1).upper(), m.group(2)[:5]
    return raw, "", ""


def _parse_balt_mailtoadd(raw: str):
    """Parse Baltimore MAILTOADD → (street_or_street_city, state, zip5).

    Two observed formats, distinguished by comma count:
      Local (no state):        'STREET SUFFIX, ZIP'            (2 parts)
      Out-of-town:              'STREET CITY, STATE, ZIP'       (3+ parts)
    A regex like Jackson County's would misread the trailing street suffix
    ('ST', 'CT', ...) in the local format as a state code — comma-splitting
    avoids that ambiguity entirely.
    """
    parts = [p.strip() for p in raw.strip().split(",")]
    if (
        len(parts) >= 3
        and re.fullmatch(r"[A-Za-z]{2}", parts[-2])
        and re.fullmatch(r"\d{5}(?:-\d{4})?", parts[-1])
    ):
        return ", ".join(parts[:-2]).strip(), parts[-2].upper(), parts[-1][:5]
    if len(parts) == 2 and re.fullmatch(r"\d{5}(?:-\d{4})?", parts[-1]):
        return parts[0].strip(), "", parts[-1][:5]
    return raw.strip(), "", ""


def _parse_city_state_zip(raw: str):
    """Parse 'CITY STATE ZIP' combined field → (city, state, zip5).

    Used for Cincinnati OWNAD2/MLADR2 like 'CINCINNATI OH 45211'.
    """
    parts = raw.strip().upper().split()
    if len(parts) >= 3 and re.fullmatch(r"\d{5}(?:-\d{4})?", parts[-1]) and len(parts[-2]) == 2:
        return " ".join(parts[:-2]).title(), parts[-2], parts[-1][:5]
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        return " ".join(parts[:-1]).title(), parts[-1], ""
    return raw.strip().title(), "", ""


def _parse_philly_city_state(raw: str):
    """Parse Philadelphia's 'CITY STATE' mailing_city_state field → (city, state)."""
    parts = raw.strip().rsplit(None, 1)
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        return parts[0].title(), parts[1].upper()
    return raw.strip().title(), ""


def _balt_saledate_to_years(saledate: str) -> int:
    """Parse Baltimore SALEDATE 'MMDDYYYY' → years since sale."""
    if not saledate or len(saledate) < 8:
        return 25
    try:
        yyyy = int(saledate[4:8])
        return CURRENT_YEAR - yyyy if 1900 < yyyy <= CURRENT_YEAR else 25
    except (ValueError, TypeError):
        return 25


def _excel_serial_to_year(serial) -> int:
    """Convert Excel serial date (days since 1899-12-30) to calendar year."""
    if not serial:
        return 0
    try:
        d = _EXCEL_EPOCH + datetime.timedelta(days=int(serial))
        return d.year
    except (ValueError, TypeError, OverflowError):
        return 0


# ─── Baltimore City, MD ───────────────────────────────────────────────────────
# Realproperty_OB FeatureServer/0 — Baltimore City's public real property layer.
# USEGROUP='R' = residential. Maryland assesses at 100% market value.
# assessed_value = CURRLAND + CURRIMPR (full cash value).
# MAILTOADD is a single combined string: 'STREET CITY, STATE, ZIP'.
# SALEDATE format: MMDDYYYY string (e.g., '06042021' = June 4, 2021).
# Absentee: compare first 2 tokens of MAILTOADD vs FULLADDR.

_BALT_PARCEL_URL = (
    "https://geodata.baltimorecity.gov/egis/rest/services"
    "/CityView/Realproperty_OB/FeatureServer/0/query"
)


def load_baltimore_md(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    # SALEDATE is a string 'MMDDYYYY' field. SUBSTRING is supported by this
    # layer's SQL backend (RIGHT/SUBSTR are not) — use it to push the 20+
    # years-held filter server-side, since the unfiltered result set is huge
    # (~100k rows) and a naive top-N fetch is dominated by recent flips.
    cutoff_year = str(CURRENT_YEAR - 20)
    params = {
        "where": (
            "USEGROUP='R' "
            "AND (CURRLAND + CURRIMPR) >= 100000 "
            "AND (CURRLAND + CURRIMPR) <= 300000 "
            "AND CURRIMPR > 0 "
            "AND YEAR_BUILD > 0 AND YEAR_BUILD < 1990 "
            f"AND SUBSTRING(SALEDATE,5,4) <= '{cutoff_year}' "
            f"AND ZIP_CODE IN ({zip_list})"
        ),
        "outFields": (
            "PIN,OWNER_1,MAILTOADD,FULLADDR,ZIP_CODE,"
            "CURRLAND,CURRIMPR,YEAR_BUILD,SALEDATE,SALEPRIC"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 8, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_BALT_PARCEL_URL, params)
        features = data.get("features") or []
        if data.get("error"):
            raise ValueError(data["error"])
    except Exception as exc:
        print(f"  [BALTIMORE_MD] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWNER_1") or "").strip()
        if not name or _is_non_individual(name):
            continue

        prop_addr = _clean_street((a.get("FULLADDR") or "").strip())
        prop_zip = str(a.get("ZIP_CODE") or "").strip()[:5]
        prop_city = "Baltimore"
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        mail_raw = (a.get("MAILTOADD") or "").strip()
        mail_street, mail_state, mail_zip = _parse_balt_mailtoadd(mail_raw)
        # MAILTOADD omits state/zip entirely for most in-state addresses
        # (only genuinely out-of-town mail includes 'CITY, STATE, ZIP').
        # Leaving mail_state blank would make is_out_of_country() misread
        # every local owner as international — default to the property's
        # own state instead.
        mail_state = mail_state or "MD"
        mail_street = _clean_street(mail_street)
        # mail_street includes city since MAILTOADD has no separate city field
        # Use it as-is for absentee token comparison and display
        mail_city = ""

        # Absentee: compare first 2 tokens (house number + street name).
        # MAILTOADD zero-pads house numbers ('0007') while FULLADDR doesn't
        # ('7') — strip leading zeros so a same-address owner-occupant isn't
        # misclassified as absentee.
        p_tok = prop_addr.upper().split()
        m_tok = mail_street.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0].lstrip("0") == m_tok[0].lstrip("0")
            and p_tok[1] == m_tok[1]
        )
        if same_addr and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(a.get("CURRLAND") or 0) + float(a.get("CURRIMPR") or 0)
        improvement = float(a.get("CURRIMPR") or 0)
        if not (100000 <= assessed <= 300000) or improvement <= 0:
            continue

        year_built = int(a.get("YEAR_BUILD") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue

        sale_date_raw = str(a.get("SALEDATE") or "").strip()
        years_owned = _balt_saledate_to_years(sale_date_raw)
        if years_owned < 20:
            continue

        leads.append(HouseLead(
            apn=str(a.get("PIN") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="MD",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_street,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=sale_date_raw,
            last_sale_price=float(a.get("SALEPRIC") or 0),
            property_class="SFR",
        ))
    return _best_leads(leads, limit)


# ─── St. Louis City, MO ──────────────────────────────────────────────────────
# Assessor_Public_Parcels MapServer/11 at maps8.stlouis-mo.gov.
# PropertyClassCode=15 = residential buildings.
# AsdTotal = actual assessed dollars (Missouri residential = 19% of appraised).
# AprLand + AprResImprove = full appraised/market value — use for $100k-$300k filter.
# Mailing address: OwnerAddr, OwnerCity, OwnerState, OwnerZIP (split fields).
# ResSaleDate = Unix ms timestamp.
# ZIP field is a float (e.g., 63115.0) — cast in WHERE clause without quotes.

_STLOUIS_PARCEL_URL = (
    "https://maps8.stlouis-mo.gov/arcgis/rest/services"
    "/ASSESSOR/Assessor_Public_Parcels/MapServer/11/query"
)


def load_stlouis_mo(market, limit=15):
    # Push the 20+ years-held filter server-side (ResSaleDate IS NULL treated
    # as long-held, matching the years_owned=25 default used below when a
    # sale date is missing) — otherwise a top-N fetch is dominated by recent
    # sales and starves the higher-scoring long-held/absentee candidate pool.
    today = datetime.date.today()
    cutoff = datetime.date(CURRENT_YEAR - 20, today.month, today.day)
    zip_ints = ",".join(str(z) for z, _ in market.zips)
    params = {
        "where": (
            "PropertyClassCode = 15 "
            "AND FirstYearBuilt > 0 AND FirstYearBuilt < 1990 "
            f"AND (ResSaleDate <= date '{cutoff.isoformat()}' OR ResSaleDate IS NULL) "
            f"AND ZIP IN ({zip_ints})"
        ),
        "outFields": (
            "ParcelId,OwnerName,OwnerAddr,OwnerCity,OwnerState,OwnerZIP,"
            "SITEADDR,ZIP,AsdTotal,AprLand,AprResImprove,FirstYearBuilt,"
            "AsrLandUse1,ResSaleDate,ResSalePrice"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 40, 2000),
        "f": "json",
    }
    try:
        data = _get_json(_STLOUIS_PARCEL_URL, params)
        features = data.get("features") or []
        if data.get("error"):
            raise ValueError(data["error"])
    except Exception as exc:
        print(f"  [STLOUIS_MO] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OwnerName") or "").strip()
        if not name or _is_non_individual(name) or name.upper() in ("LRA",):
            continue

        # SITEADDR has extra internal spaces — _clean_street handles via split()
        prop_addr = _clean_street((a.get("SITEADDR") or "").strip())
        zip_raw = str(a.get("ZIP") or "").split(".")[0].strip()
        prop_zip = zip_raw.zfill(5)
        prop_city = "St. Louis"
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        mail_addr = _clean_street((a.get("OwnerAddr") or "").strip())
        mail_city = (a.get("OwnerCity") or "").strip().title()
        mail_state = (a.get("OwnerState") or "").strip().upper()
        mail_zip = str(a.get("OwnerZIP") or "").strip()[:5]

        # Absentee check
        p_tok = prop_addr.upper().split()
        m_tok = mail_addr.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0] == m_tok[0] and p_tok[1] == m_tok[1]
        )
        if same_addr and mail_zip[:5] == prop_zip[:5]:
            continue

        # Missouri: use full appraised value for $100k-$300k filter
        apr_land = float(a.get("AprLand") or 0)
        apr_res = float(a.get("AprResImprove") or 0)
        market_val = apr_land + apr_res
        if not (100000 <= market_val <= 300000) or apr_res <= 0:
            continue

        year_built = int(a.get("FirstYearBuilt") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue

        sale_ms = a.get("ResSaleDate")
        if sale_ms:
            sale_year = _year_from_ms(sale_ms)
            years_owned = CURRENT_YEAR - sale_year
            if years_owned < 20:
                continue
        else:
            years_owned = 25

        leads.append(HouseLead(
            apn=str(a.get("ParcelId") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="MO",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=market_val,
            improvement_value=apr_res,
            years_owned=years_owned,
            last_sale_date=str(_year_from_ms(sale_ms)) if sale_ms else "",
            last_sale_price=float(a.get("ResSalePrice") or 0),
            property_class="SFR",
        ))
    return _best_leads(leads, limit)


# ─── Kansas City, MO (Jackson County) ────────────────────────────────────────
# ParcelsAscendRelate MapServer/2 at jcgis.jacksongov.org.
# Use MapServer (not FeatureServer) — FeatureServer consistently returns 400.
# landuse_cd 11xx series = residential (single family, condo, townhome).
# Market_Value_Total = full market value in dollars.
# address_compl = combined mailing string: 'STREET CITY, STATE ZIP'.
# situs_address/city/zip = separate property address fields.
# No sale date or price in this layer — default years_owned=25.

_KC_PARCEL_URL = (
    "https://jcgis.jacksongov.org/arcgis/rest/services"
    "/ParcelViewer/ParcelsAscendRelate/MapServer/2/query"
)


def load_kansascity_mo(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            "Market_Value_Total >= 100000 AND Market_Value_Total <= 300000 "
            "AND Res_Impr > 0 "
            "AND year_built > 0 AND year_built < 1990 "
            f"AND situs_zip IN ({zip_list})"
        ),
        "outFields": (
            "parcel_number,owner_info,address_compl,"
            "situs_address,situs_city,situs_zip,"
            "Market_Value_Total,Res_Impr,year_built,landuse_cd,landuse_cd_descr"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        # This server 400s on any resultRecordCount without an explicit sort order.
        "orderByFields": "OBJECTID",
        "f": "json",
    }
    try:
        data = _get_json(_KC_PARCEL_URL, params)
        features = data.get("features") or []
        if data.get("error"):
            raise ValueError(data["error"])
    except Exception as exc:
        print(f"  [KANSASCITY_MO] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("owner_info") or "").strip()
        if not name or _is_non_individual(name):
            continue

        # Filter to single-family detached only. 1110 = SF RESIDENCE; the
        # broader "11xx" series also includes 1112 SF CONDO and 1120 DUPLEX,
        # which slip in units/duplexes we don't want to wholesale as houses.
        lc = str(a.get("landuse_cd") or "0")
        if lc != "1110":
            continue

        prop_addr = _clean_street((a.get("situs_address") or "").strip())
        prop_city = (a.get("situs_city") or "").strip().title()
        prop_zip = str(a.get("situs_zip") or "").strip()[:5]
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        mail_raw = (a.get("address_compl") or "").strip()
        mail_street, mail_state, mail_zip = _parse_mail_combined(mail_raw)
        mail_street = _clean_street(mail_street)
        mail_city = ""  # city embedded in street; can't reliably separate

        # Absentee: token comparison
        p_tok = prop_addr.upper().split()
        m_tok = mail_street.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0] == m_tok[0] and p_tok[1] == m_tok[1]
        )
        if same_addr and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(a.get("Market_Value_Total") or 0)
        improvement = float(a.get("Res_Impr") or 0)
        if not (100000 <= assessed <= 300000) or improvement <= 0:
            continue

        year_built = int(a.get("year_built") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue

        leads.append(HouseLead(
            apn=str(a.get("parcel_number") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="MO",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_street,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=25,      # no sale date in Jackson County layer
            last_sale_date="",
            last_sale_price=0.0,
            property_class="SFR",
        ))
    return _best_leads(leads, limit)


# ─── Philadelphia, PA (Philadelphia County) ───────────────────────────────────
# OPA Properties via Carto SQL API — full PostgreSQL-style SQL queries supported.
# category_code='1' = single family residential.
# market_value = 100% OPA appraised value (no separate "assessed" value needed).
# mailing_city_state = combined 'CITY STATE' — split on last whitespace.
# year_built is a string field (e.g., '1955'); cast to int.
# sale_date is ISO 8601: '2026-05-15T04:00:00Z'.

_PHILLY_CARTO_URL = "https://phl.carto.com/api/v2/sql"


def load_philadelphia_pa(market, limit=15):
    zip_list = "', '".join(z for z, _ in market.zips)
    cutoff_year = CURRENT_YEAR - 20  # sold before this year = 20+ years owned

    sql = (
        "SELECT parcel_number, owner_1, owner_2, "
        "mailing_street, mailing_city_state, mailing_zip, "
        "location, zip_code, market_value, taxable_building, "
        "year_built, sale_date, sale_price "
        "FROM opa_properties_public "
        "WHERE category_code = '1' "
        f"AND zip_code IN ('{zip_list}') "
        "AND market_value >= 100000 AND market_value <= 300000 "
        "AND taxable_building > 0 "
        "AND year_built IS NOT NULL AND year_built != '' "
        "AND year_built::integer > 0 AND year_built::integer < 1990 "
        f"AND (sale_date IS NULL OR sale_date < '{cutoff_year}-01-01') "
        "AND owner_1 IS NOT NULL "
        f"LIMIT {min(limit * 40, 1000)}"
    )
    params = {"q": sql, "format": "json"}
    try:
        data = _get_json(_PHILLY_CARTO_URL, params)
        rows = data.get("rows") or []
        if data.get("error"):
            raise ValueError(data["error"])
    except Exception as exc:
        print(f"  [PHILADELPHIA_PA] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for row in rows:
        name = (row.get("owner_1") or "").strip()
        if not name or _is_non_individual(name):
            continue

        prop_addr = _clean_street((row.get("location") or "").strip())
        prop_zip = str(row.get("zip_code") or "").strip()[:5]
        prop_city = "Philadelphia"
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        mail_addr = _clean_street((row.get("mailing_street") or "").strip())
        city_state = (row.get("mailing_city_state") or "").strip()
        mail_city, mail_state = _parse_philly_city_state(city_state)
        mail_zip = str(row.get("mailing_zip") or "").strip()[:5]

        # Absentee: address token comparison
        p_tok = prop_addr.upper().split()
        m_tok = mail_addr.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0] == m_tok[0] and p_tok[1] == m_tok[1]
        )
        if same_addr and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(row.get("market_value") or 0)
        improvement = float(row.get("taxable_building") or 0)
        if not (100000 <= assessed <= 300000) or improvement <= 0:
            continue

        try:
            year_built = int(row.get("year_built") or 0)
        except (ValueError, TypeError):
            year_built = 0
        if year_built < 1800 or year_built >= 1990:
            continue

        sale_date_raw = (row.get("sale_date") or "")[:10]
        try:
            sale_year = int(sale_date_raw[:4]) if sale_date_raw else 0
        except (ValueError, TypeError):
            sale_year = 0
        years_owned = CURRENT_YEAR - sale_year if sale_year else 25
        if years_owned < 20:
            continue

        leads.append(HouseLead(
            apn=str(row.get("parcel_number") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="PA",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=sale_date_raw,
            last_sale_price=float(row.get("sale_price") or 0),
            property_class="SFR",
        ))
    return _best_leads(leads, limit)


# ─── Cincinnati, OH (Hamilton County) ────────────────────────────────────────
# AuditorParcelInformation MapServer/15 for parcel/value data.
# AuditorParcelInformation MapServer/17 for year built (YEARBUILT, join on PID=PARCELID).
# LUCLASS 510-519 = single family residential.
# MKT_TOTAL_VAL = full market value (Ohio assessed = 35% of this; use market value).
# OWNAD1 = owner's mailing street; OWNAD2 = 'CITY STATE ZIP' combined.
# Property address: ADDRNO + ADDRST + ADDRSF (no zip in layer — default '45202').
# SALDAT = Excel serial date (days since 1899-12-30).

_CIN_PARCEL_URL = (
    "https://cagisonline.hamilton-co.org/arcgis/rest/services"
    "/COUNTYWIDE/AuditorParcelInformation/MapServer/15/query"
)
_CIN_YRBUILT_URL = (
    "https://cagisonline.hamilton-co.org/arcgis/rest/services"
    "/COUNTYWIDE/AuditorParcelInformation/MapServer/17/query"
)


def load_cincinnati_oh(market, limit=15):
    # Push the 20+ years-held filter server-side. Without it, an unfiltered
    # top-N fetch from this ~large, unsorted table lands almost entirely on
    # owner-occupied/recently-sold parcels and starves the absentee-owner
    # candidate pool (observed 1 qualifying lead out of 120 fetched).
    cutoff_serial = (datetime.date.today().replace(year=CURRENT_YEAR - 20) - _EXCEL_EPOCH).days
    params = {
        "where": (
            "LUCLASS >= 510 AND LUCLASS <= 519 "
            "AND MKT_TOTAL_VAL >= 100000 AND MKT_TOTAL_VAL <= 300000 "
            "AND MKTIMP > 0 "
            f"AND (SALDAT <= {cutoff_serial} OR SALDAT IS NULL)"
        ),
        "outFields": (
            "PARCELID,OWNNM1,OWNNM2,OWNAD1,OWNAD2,"
            "ADDRNO,ADDRST,ADDRSF,MKTLND,MKTIMP,MKT_TOTAL_VAL,"
            "SALAMT,SALDAT,LUCLASS"
        ),
        "returnGeometry": "false",
        # Owner-occupied parcels dominate this table even after the sale-date
        # filter above, so fetch closer to the server's row cap to leave
        # enough absentee-owner candidates after in-Python filtering.
        "resultRecordCount": min(limit * 40, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_CIN_PARCEL_URL, params)
        features = data.get("features") or []
        if data.get("error"):
            raise ValueError(data["error"])
    except Exception as exc:
        print(f"  [CINCINNATI_OH] live fetch failed ({exc}), using mock data")
        return []

    if not features:
        return []

    # Step 2: fetch year built from layer 17 for candidate parcels
    parcel_ids = [str(_attrs(f).get("PARCELID") or "") for f in features if _attrs(f).get("PARCELID")]
    year_by_parcel = {}
    if parcel_ids:
        pid_list = ",".join(f"'{p}'" for p in parcel_ids[:500])
        try:
            yr_data = _post_json(_CIN_YRBUILT_URL, {
                "where": f"PID IN ({pid_list})",
                "outFields": "PID,YEARBUILT",
                "returnGeometry": "false",
                "resultRecordCount": len(parcel_ids) + 50,
                "f": "json",
            })
            for yf in (yr_data.get("features") or []):
                ya = _attrs(yf)
                pid = str(ya.get("PID") or "").strip()
                yb = int(ya.get("YEARBUILT") or 0)
                if pid and yb:
                    year_by_parcel[pid] = yb
        except Exception:
            pass  # proceed with year_built=0 if layer 17 fails

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWNNM1") or "").strip()
        suffix = (a.get("OWNNM2") or "").strip()
        full_name = f"{name} {suffix}".strip() if suffix else name
        if not full_name or _is_non_individual(full_name):
            continue

        # Build property address from split fields
        num = str(a.get("ADDRNO") or "").strip().split(".")[0]
        sname = (a.get("ADDRST") or "").strip()
        sfx = (a.get("ADDRSF") or "").strip()
        raw_addr = " ".join(p for p in [num, sname, sfx] if p)
        prop_addr = _clean_street(raw_addr)
        prop_city = "Cincinnati"
        # Layer 15 has no property zip; derive from owner zip if local else default
        ownad2_raw = (a.get("OWNAD2") or "").strip()
        _, own_state, own_zip = _parse_city_state_zip(ownad2_raw)
        prop_zip = own_zip if own_state == "OH" and own_zip else "45202"
        if not _valid_address(prop_addr, prop_city, prop_zip):
            continue

        # Mailing: OWNAD1 = owner street, OWNAD2 = 'CITY STATE ZIP'
        mail_addr = _clean_street((a.get("OWNAD1") or "").strip())
        mail_city, mail_state, mail_zip = _parse_city_state_zip(ownad2_raw)

        # Absentee: address token comparison
        p_tok = prop_addr.upper().split()
        m_tok = mail_addr.upper().split()
        same_addr = (
            len(p_tok) >= 2 and len(m_tok) >= 2
            and p_tok[0] == m_tok[0] and p_tok[1] == m_tok[1]
        )
        if same_addr and mail_zip[:5] == prop_zip[:5]:
            continue

        assessed = float(a.get("MKT_TOTAL_VAL") or 0)
        improvement = float(a.get("MKTIMP") or 0)
        if not (100000 <= assessed <= 300000) or improvement <= 0:
            continue

        pid = str(a.get("PARCELID") or "").strip()
        year_built = year_by_parcel.get(pid, 0)
        if year_built and (year_built < 1800 or year_built >= 1990):
            continue

        sale_serial = a.get("SALDAT")
        sale_year = _excel_serial_to_year(sale_serial)
        years_owned = CURRENT_YEAR - sale_year if sale_year else 25
        if years_owned < 20:
            continue

        leads.append(HouseLead(
            apn=pid,
            property_address=prop_addr,
            city=prop_city,
            state="OH",
            zip_code=prop_zip,
            owner_name=full_name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=str(sale_year) if sale_year else "",
            last_sale_price=float(a.get("SALAMT") or 0),
            property_class="SFR",
        ))
    return _best_leads(leads, limit)


# ─── Registry ─────────────────────────────────────────────────────────────────

LIVE_HOUSE_LOADERS = {
    "BALTIMORE_MD":   load_baltimore_md,
    "STLOUIS_MO":     load_stlouis_mo,
    "KANSASCITY_MO":  load_kansascity_mo,
    "PHILADELPHIA_PA": load_philadelphia_pa,
    "CINCINNATI_OH":  load_cincinnati_oh,
}
