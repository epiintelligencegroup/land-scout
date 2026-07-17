"""
Cash buyer discovery from deed transfer records.

A "cash buyer" is anyone who purchased residential property in the target zip
codes in the last 24 months. Two metrics per buyer:
  - recent_purchases : buys in the last 12 months
  - two_year_purchases: buys in the last 24 months

Buyers with two_year_purchases >= 3 are flagged as active flippers who close fast.

Live sources (confirmed endpoints, researched 2026-07-17):
  Baltimore MD   : Realproperty_OB FeatureServer/0 (same layer as parcels) —
                   SALEDATE is a string 'MMDDYYYY' field, no date-typed query
                   possible, so results are over-fetched by year then filtered
                   precisely to a 730-day window in Python.
  St. Louis MO   : Assessor_Public_Parcels MapServer/11 (same layer as parcels) —
                   ResSaleDate is a true Esri date field, queried directly.
  Philadelphia PA: opa_properties_public via Carto SQL API — sale_date is ISO,
                   queried directly.
  Cincinnati OH  : AuditorParcelInformation MapServer/15 (same layer as parcels) —
                   SALDAT is an Excel serial date (days since 1899-12-30),
                   queried directly with a serial cutoff. Layer has no site zip
                   field, so this query is county-wide (not restricted to
                   market zips) — same gap as the property-address workaround
                   used in gis_house_sources.py for this county.
  Kansas City MO : No free deed transfer API found for Jackson County (checked
                   Auditor/ParcelViewer ArcGIS folders — no sale date/price
                   field, no open recorder-of-deeds API) — mock data only.
"""
import datetime
import json
import random
import re
import urllib.parse
import urllib.request
from collections import defaultdict

CURRENT_YEAR = datetime.date.today().year
_TIMEOUT = 25
_EXCEL_EPOCH = datetime.date(1899, 12, 30)

# Keywords in a buyer's name that signal a non-real-estate business — exclude these.
_NON_RE_BUSINESS_RE = re.compile(
    r"\b(?:CLEAN(?:ING|ERS?|UP)?|MAID|JANITORIAL|SANIT"
    r"|MEDICAL|DENTAL|HEALTH(?:CARE)?|CLINIC|HOSPITAL|PHARMACY|PHARMA"
    r"|RESTAURAN?T|FOOD|PIZZA|DINER|CAFE|CATERING|BAR\b|GRILL\b"
    r"|RETAIL|STORE|SHOP\b|BOUTIQUE|SALON|NAIL\b|BARBER|SPA\b"
    r"|LANDSCAP|LAWN|GARDEN|TREE\s*SERVICE|PEST\s*CONTROL"
    r"|MAINTENAN?CE|REPAIR|PLUMB|ELECTRIC|HVAC|ROOFING|PAINTING"
    r"|TRUCKING|TRANSPORT|MOVING|LOGISTICS|DELIVERY"
    r"|CHURCH|MINISTRY|FAITH|TEMPLE|MOSQUE"
    r"|SCHOOL|EDUCAT|ACADEMY|TUTORING"
    r"|INSURANCE|FINANC(?:IAL|E)|ACCOUNTING|TAX\s*SERVICE"
    r"|AUTO\b|CAR\b|VEHICLE|MECHANIC|TIRE\b)\b",
    re.IGNORECASE,
)


class CashBuyer:
    def __init__(self, name, mailing_address, zip_codes_active, recent_purchases, two_year_purchases):
        self.name = name
        self.mailing_address = mailing_address
        self.zip_codes_active = zip_codes_active
        self.recent_purchases = recent_purchases
        self.two_year_purchases = two_year_purchases

    @property
    def is_active_flipper(self):
        return self.two_year_purchases >= 3


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_json(url, params=None):
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _attrs(feat):
    return feat.get("attributes") or {}


def _is_real_estate_buyer(name: str) -> bool:
    """Return True if the name looks like a genuine real estate investor/buyer.

    Rules:
    - Must have 3+ purchases in last 2 years (enforced in _build_buyers, not here)
    - Excluded: names matching non-RE business keywords (cleaning, medical, restaurant, etc.)
    """
    return not bool(_NON_RE_BUSINESS_RE.search(name))


def _build_buyers(records, top_n=20):
    """Deduplicate and sort buyer records. Each record: (name, addr, zip, date_iso).

    Inclusion criteria:
    - 3+ purchases in the last 2 years (both individuals and entities)
    - Not a non-real-estate business (cleaning, medical, restaurant, etc.)
    """
    cutoff_12 = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    by_buyer: dict = defaultdict(list)
    for name, addr, zip_code, date_iso in records:
        name = name.strip().upper()
        if not name or len(name) < 3:
            continue
        by_buyer[(name, addr.strip())].append((date_iso, zip_code))

    buyers = []
    for (name, addr), purchases in by_buyer.items():
        two_year = len(purchases)
        # Require at least 3 purchases in 2 years for everyone
        if two_year < 3:
            continue
        # Exclude non-real-estate businesses
        if not _is_real_estate_buyer(name):
            continue
        recent = sum(1 for d, _ in purchases if d >= cutoff_12)
        zips = list({z for _, z in purchases if z})
        buyers.append(CashBuyer(
            name=name.title(),
            mailing_address=addr,
            zip_codes_active=zips,
            recent_purchases=recent,
            two_year_purchases=two_year,
        ))
    buyers.sort(key=lambda b: (b.two_year_purchases, b.recent_purchases), reverse=True)
    return buyers[:top_n]


# ─── Baltimore City, MD ───────────────────────────────────────────────────────
# Realproperty_OB FeatureServer/0 — same layer used for parcels in
# gis_house_sources.py. SALEDATE is a string 'MMDDYYYY' field with no date-typed
# query support, so we over-fetch by matching the trailing year (covers a bit
# more than 24 months) then filter precisely to a 730-day window in Python.

_BALT_PARCEL_URL = (
    "https://geodata.baltimorecity.gov/egis/rest/services"
    "/CityView/Realproperty_OB/FeatureServer/0/query"
)


def _balt_parse_saledate(raw: str):
    """Parse Baltimore SALEDATE 'MMDDYYYY' -> date, or None if unparseable."""
    if not raw or len(raw) < 8:
        return None
    try:
        mm, dd, yyyy = int(raw[0:2]), int(raw[2:4]), int(raw[4:8])
        return datetime.date(yyyy, mm, dd)
    except (ValueError, TypeError):
        return None


def _load_cash_buyers_baltimore(market):
    cutoff = datetime.date.today() - datetime.timedelta(days=730)
    year_filter = " OR ".join(
        f"SALEDATE LIKE '%{y}'" for y in {cutoff.year, cutoff.year + 1, CURRENT_YEAR + 1}
    )
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"USEGROUP='R' AND SALEPRIC > 25000 AND ({year_filter}) "
            f"AND ZIP_CODE IN ({zip_list})"
        ),
        "outFields": "OWNER_1,MAILTOADD,FULLADDR,ZIP_CODE,SALEDATE,SALEPRIC",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    try:
        data = _get_json(_BALT_PARCEL_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [BALTIMORE_MD cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWNER_1") or "").strip()
        if not name:
            continue
        sale_date = _balt_parse_saledate(str(a.get("SALEDATE") or "").strip())
        if not sale_date or sale_date < cutoff:
            continue
        addr = (a.get("MAILTOADD") or "").strip().title()
        zip_code = str(a.get("ZIP_CODE") or "").strip()[:5]
        records.append((name, addr, zip_code, sale_date.isoformat()))

    return _build_buyers(records)


# ─── St. Louis City, MO ──────────────────────────────────────────────────────
# Assessor_Public_Parcels MapServer/11 — same layer used for parcels.
# ResSaleDate is a true Esri date field; query directly with a date literal.

_STLOUIS_PARCEL_URL = (
    "https://maps8.stlouis-mo.gov/arcgis/rest/services"
    "/ASSESSOR/Assessor_Public_Parcels/MapServer/11/query"
)


def _load_cash_buyers_stlouis(market):
    cutoff = datetime.date.today() - datetime.timedelta(days=730)
    zip_ints = ",".join(str(z) for z, _ in market.zips)
    params = {
        "where": (
            f"PropertyClassCode = 15 AND ResSaleDate >= date '{cutoff.isoformat()}' "
            f"AND ResSalePrice > 25000 AND ZIP IN ({zip_ints})"
        ),
        "outFields": "OwnerName,OwnerAddr,OwnerCity,OwnerState,OwnerZIP,ZIP,ResSaleDate,ResSalePrice",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    try:
        data = _get_json(_STLOUIS_PARCEL_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [STLOUIS_MO cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OwnerName") or "").strip()
        if not name:
            continue
        sale_ms = a.get("ResSaleDate")
        if not sale_ms:
            continue
        sale_date = datetime.datetime.utcfromtimestamp(int(sale_ms) / 1000).date()
        addr = (a.get("OwnerAddr") or "").strip().title()
        zip_code = str(a.get("OwnerZIP") or a.get("ZIP") or "").split(".")[0].strip()[:5]
        records.append((name, addr, zip_code, sale_date.isoformat()))

    return _build_buyers(records)


# ─── Philadelphia, PA (Philadelphia County) ───────────────────────────────────
# opa_properties_public via Carto SQL API — sale_date is ISO, query directly.

_PHILLY_CARTO_URL = "https://phl.carto.com/api/v2/sql"


def _load_cash_buyers_philadelphia(market):
    cutoff = datetime.date.today() - datetime.timedelta(days=730)
    zip_list = "', '".join(z for z, _ in market.zips)
    sql = (
        "SELECT owner_1, mailing_street, mailing_zip, sale_date, sale_price "
        "FROM opa_properties_public "
        "WHERE category_code = '1' "
        f"AND zip_code IN ('{zip_list}') "
        f"AND sale_date >= '{cutoff.isoformat()}' "
        "AND sale_price > 25000 "
        "AND owner_1 IS NOT NULL "
        "LIMIT 2000"
    )
    params = {"q": sql, "format": "json"}
    try:
        data = _get_json(_PHILLY_CARTO_URL, params)
        rows = data.get("rows") or []
        if data.get("error"):
            raise ValueError(data["error"])
    except Exception as exc:
        print(f"  [PHILADELPHIA_PA cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for row in rows:
        name = (row.get("owner_1") or "").strip()
        if not name:
            continue
        sale_date_raw = (row.get("sale_date") or "")[:10]
        if not sale_date_raw:
            continue
        addr = (row.get("mailing_street") or "").strip().title()
        zip_code = str(row.get("mailing_zip") or "").strip()[:5]
        records.append((name, addr, zip_code, sale_date_raw))

    return _build_buyers(records)


# ─── Cincinnati, OH (Hamilton County) ────────────────────────────────────────
# AuditorParcelInformation MapServer/15 — same layer used for parcels.
# SALDAT is an Excel serial date (days since 1899-12-30); query directly with a
# serial cutoff. Layer has no site zip field, so this is county-wide rather
# than restricted to market zips (same gap accepted in gis_house_sources.py).

_CIN_PARCEL_URL = (
    "https://cagisonline.hamilton-co.org/arcgis/rest/services"
    "/COUNTYWIDE/AuditorParcelInformation/MapServer/15/query"
)


def _load_cash_buyers_cincinnati(market):
    cutoff = datetime.date.today() - datetime.timedelta(days=730)
    cutoff_serial = (cutoff - _EXCEL_EPOCH).days
    params = {
        "where": (
            f"LUCLASS >= 510 AND LUCLASS <= 519 "
            f"AND SALDAT >= {cutoff_serial} AND SALAMT > 25000"
        ),
        "outFields": "OWNNM1,OWNNM2,OWNAD1,OWNAD2,SALAMT,SALDAT",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    try:
        data = _get_json(_CIN_PARCEL_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [CINCINNATI_OH cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWNNM1") or "").strip()
        suffix = (a.get("OWNNM2") or "").strip()
        full_name = f"{name} {suffix}".strip() if suffix else name
        if not full_name:
            continue
        serial = a.get("SALDAT")
        if not serial:
            continue
        sale_date = _EXCEL_EPOCH + datetime.timedelta(days=int(serial))
        addr = (a.get("OWNAD1") or "").strip().title()
        ownad2 = (a.get("OWNAD2") or "").strip().upper().split()
        zip_code = ownad2[-1][:5] if ownad2 and re.fullmatch(r"\d{5}(?:-\d{4})?", ownad2[-1]) else ""
        records.append((full_name, addr, zip_code, sale_date.isoformat()))

    return _build_buyers(records)


# ─── Mock generator ───────────────────────────────────────────────────────────

_BUYER_FIRST = [
    "Marcus", "Devon", "Tanya", "Chris", "Kevin", "Regina", "Todd",
    "Angela", "Brian", "Denise", "Victor", "Sandra", "Eddie", "Loretta",
    "Antoine", "Felicia", "Jerome", "Monique", "Darnell", "Yvette",
]
_BUYER_LAST = [
    "Freeman", "Hughes", "Bennett", "Patterson", "Cooper", "Reed",
    "Bailey", "Rivera", "Powell", "Long", "Ross", "Torres", "Simmons",
    "Washington", "Jefferson", "Hayes", "Crawford", "Griffin", "Morrison",
]
_COMPANY_SUFFIXES = [
    " Properties LLC", " Investments LLC", " Holdings LLC",
    " Real Estate Group", " Capital Partners LLC",
]


def generate_mock_cash_buyers(market, count=8):
    rng = random.Random(market.key + "buyers" + str(datetime.date.today()))
    buyers = []
    market_zips = [z for z, _ in market.zips]
    for i in range(count):
        if rng.random() < 0.45:
            name = (
                f"{rng.choice(_BUYER_FIRST)} {rng.choice(_BUYER_LAST)}"
                + rng.choice(_COMPANY_SUFFIXES)
            )
        else:
            name = f"{rng.choice(_BUYER_FIRST)} {rng.choice(_BUYER_LAST)}"
        two_yr = rng.randint(3, 9)  # minimum 3 to match live-data filter threshold
        recent = min(two_yr, rng.randint(1, 5))
        active_zips = rng.sample(market_zips, min(rng.randint(1, 4), len(market_zips)))
        buyers.append(CashBuyer(
            name=name,
            mailing_address=(
                f"{rng.randint(100, 9999)} Commerce Dr, Suite {rng.randint(1, 99)}"
            ),
            zip_codes_active=active_zips,
            recent_purchases=recent,
            two_year_purchases=two_yr,
        ))
    buyers.sort(key=lambda b: (b.two_year_purchases, b.recent_purchases), reverse=True)
    return buyers


# ─── Public entry point ───────────────────────────────────────────────────────

_LIVE_BUYER_LOADERS = {
    "BALTIMORE_MD":    _load_cash_buyers_baltimore,
    "STLOUIS_MO":      _load_cash_buyers_stlouis,
    "PHILADELPHIA_PA": _load_cash_buyers_philadelphia,
    "CINCINNATI_OH":   _load_cash_buyers_cincinnati,
    # KANSASCITY_MO: no free deed transfer API found for Jackson County → mock
}


def load_cash_buyers(market):
    """
    Load cash buyers for a market. Falls back to mock if the live fetch fails or
    returns no results. Kansas City MO always uses mock (no free deed API).
    """
    loader = _LIVE_BUYER_LOADERS.get(market.key)
    if loader:
        buyers = loader(market)
        if buyers:
            print(f"  [{market.key}] {len(buyers)} live cash buyers loaded")
            return buyers
        print(f"  [{market.key}] no live cash buyers — using mock")
    return generate_mock_cash_buyers(market)
