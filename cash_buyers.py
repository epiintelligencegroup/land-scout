"""
Cash buyer discovery from deed transfer records.

A "cash buyer" is anyone who purchased residential property in the target zip
codes in the last 24 months. Two metrics per buyer:
  - recent_purchases : buys in the last 12 months
  - two_year_purchases: buys in the last 24 months

Buyers with two_year_purchases >= 3 are flagged as active flippers who close fast.

Live sources (confirmed endpoints):
  Cuyahoga OH  : APPRAISAL_PARCELS_CAMA_WGS84 layer (grantee + transfer date)
  Shelby TN    : Data Midsouth Socrata API (warranty deeds 2016-2023)
  Harris TX    : HCAD Parcels layer (recent owner_name + new_owner_date)
  Duval FL     : FL_Parcels FeatureServer (OWN_NAME + SALE_YR1/SALE_MO1)
  Jefferson AL : No free deed transfer API — mock data only
"""
import datetime
import json
import random
import urllib.parse
import urllib.request
from collections import defaultdict

CURRENT_YEAR = datetime.date.today().year
_TIMEOUT = 25


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


def _date_lit(d: datetime.date) -> str:
    return f"date '{d.isoformat()}'"


def _ago_date(days: int) -> str:
    return _date_lit(datetime.date.today() - datetime.timedelta(days=days))


def _attrs(feat):
    return feat.get("attributes") or {}


def _build_buyers(records, top_n=20):
    """Deduplicate and sort buyer records. Each record: (name, addr, zip, date_iso)."""
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


# ─── Cuyahoga County OH ───────────────────────────────────────────────────────
# CAMA layer has grantee (buyer), last_transfer_date (Unix ms), par_addr_all, mail_zip.
# We look at transfers in the last 24 months and count per grantee.

_CUYAHOGA_CAMA_URL = (
    "https://gis.cuyahogacounty.us/server/rest/services/CCFO"
    "/APPRAISAL_PARCELS_CAMA_WGS84/MapServer/0/query"
)


def _load_cash_buyers_cuyahoga(market):
    date_24mo = _ago_date(730)
    params = {
        "where": (
            f"last_transfer_date > {date_24mo} "
            "AND last_sales_amount > 25000 "
            "AND property_class='R'"
        ),
        "outFields": "grantee,mail_addr_street,mail_zip,par_addr_all,last_transfer_date",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    try:
        data = _get_json(_CUYAHOGA_CAMA_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [CUYAHOGA cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("grantee") or "").strip()
        if not name:
            continue
        transfer_ms = a.get("last_transfer_date") or 0
        date_iso = datetime.datetime.utcfromtimestamp(transfer_ms / 1000).date().isoformat()
        addr = (a.get("mail_addr_street") or "").strip().title()
        zip_code = str(a.get("mail_zip") or "").strip()
        records.append((name, addr, zip_code, date_iso))

    return _build_buyers(records)


# ─── Shelby County TN (Data Midsouth Socrata) ────────────────────────────────
# Warranty deed transactions 2016–2023. group by property_grantee1.
# Dataset is annual; most recent data = 2023 so "recent" = 2022-2023.
# record_date format: "YYYY-MM-DDTHH:MM:SS+00:00"

_DATASOUTH_URL = (
    "https://www.datamidsouth.org/api/explore/v2.1/catalog/datasets"
    "/shelby-county-register-of-deeds-property-transactions/records"
)


def _load_cash_buyers_shelby(market):
    zip_list = " OR ".join(f'zipcode="{z}"' for z, _ in market.zips)
    params = {
        "select": "property_grantee1,property_address,record_date,val_consideration,zipcode",
        "where": f"transaction_type_desc='WARRANTY DEED' AND ({zip_list})",
        "order_by": "record_date DESC",
        "limit": 100,
    }
    try:
        data = _get_json(_DATASOUTH_URL, params)
        results = data.get("results") or []
    except Exception as exc:
        print(f"  [SHELBY cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for row in results:
        name = (row.get("property_grantee1") or "").strip()
        if not name:
            continue
        record_date = (row.get("record_date") or "")[:10]
        zip_code = str(row.get("zipcode") or "").strip()
        addr = (row.get("property_address") or "").strip().title()
        records.append((name, addr, zip_code, record_date))

    return _build_buyers(records)


# ─── Harris County TX (HCAD recent transfers) ────────────────────────────────
# Use HCAD Parcels to find who recently took ownership in target zips.
# new_owner_date is in Unix ms. Filter to last 24 months, group by owner_name_1.

_HARRIS_PARCELS_URL = "https://www.gis.hctx.net/arcgis/rest/services/HCAD/Parcels/MapServer/0/query"


def _load_cash_buyers_harris(market):
    date_24mo = _ago_date(730)
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"land_use=1001 AND site_zip IN ({zip_list}) "
            f"AND new_owner_date > {date_24mo} "
            "AND total_appraised_val > 25000"
        ),
        "outFields": "owner_name_1,mail_addr_1,mail_zip,site_zip,new_owner_date",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    try:
        data = _get_json(_HARRIS_PARCELS_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [HARRIS cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("owner_name_1") or "").strip()
        if not name:
            continue
        transfer_ms = a.get("new_owner_date") or 0
        date_iso = datetime.datetime.utcfromtimestamp(transfer_ms / 1000).date().isoformat()
        addr = (a.get("mail_addr_1") or "").strip().title()
        zip_code = str(a.get("mail_zip") or a.get("site_zip") or "").strip()
        records.append((name, addr, zip_code, date_iso))

    return _build_buyers(records)


# ─── Duval County FL (FL_Parcels recent sales) ───────────────────────────────
# SALE_YR1/SALE_MO1 = most recent recorded sale year/month. Current owner = buyer.
# Look at SALE_YR1 >= CURRENT_YEAR - 2 for "recent" transfers in target zips.

_DUVAL_PARCELS_URL = (
    "https://services5.arcgis.com/GcvM6vDlR2gM4x31/arcgis/rest/services"
    "/FL_Parcels/FeatureServer/0/query"
)
_DUVAL_RECENT_YR = CURRENT_YEAR - 2


def _load_cash_buyers_duval(market):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"CountyName='Duval' AND DOR_UC='001' "
            f"AND SALE_YR1 >= {_DUVAL_RECENT_YR} "
            f"AND PHY_ZIPCD IN ({zip_list}) "
            "AND SALE_PRC1 > 25000 "
            "AND OWN_NAME IS NOT NULL"
        ),
        "outFields": "OWN_NAME,OWN_ADDR1,OWN_ZIPCD,PHY_ZIPCD,SALE_YR1,SALE_MO1",
        "returnGeometry": "false",
        "resultRecordCount": 2000,
        "f": "json",
    }
    try:
        data = _get_json(_DUVAL_PARCELS_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [DUVAL cash buyers] fetch failed ({exc}), using mock")
        return None

    records = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWN_NAME") or "").strip()
        if not name:
            continue
        yr = int(a.get("SALE_YR1") or 0)
        mo = int(a.get("SALE_MO1") or 1)
        date_iso = f"{yr}-{mo:02d}-01" if yr else ""
        addr = (a.get("OWN_ADDR1") or "").strip().title()
        zip_code = str(a.get("OWN_ZIPCD") or a.get("PHY_ZIPCD") or "").strip()
        records.append((name, addr, zip_code, date_iso))

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
        two_yr = rng.randint(1, 9)
        recent = min(two_yr, rng.randint(0, 5))
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
    "CUYAHOGA_OH": _load_cash_buyers_cuyahoga,
    "SHELBY_TN":   _load_cash_buyers_shelby,
    "HARRIS_TX":   _load_cash_buyers_harris,
    "DUVAL_FL":    _load_cash_buyers_duval,
    # JEFFERSON_AL: no free deed transfer API → always mock
}


def load_cash_buyers(market):
    """
    Load cash buyers for a market. Falls back to mock if the live fetch fails or
    returns no results. Jefferson AL always uses mock (no free deed records API).
    """
    loader = _LIVE_BUYER_LOADERS.get(market.key)
    if loader:
        buyers = loader(market)
        if buyers:
            print(f"  [{market.key}] {len(buyers)} live cash buyers loaded")
            return buyers
        print(f"  [{market.key}] no live cash buyers — using mock")
    return generate_mock_cash_buyers(market)
