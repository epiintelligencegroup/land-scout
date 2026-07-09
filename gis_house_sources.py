"""
Live county assessor GIS loaders — all five markets.

Confirmed working endpoints (researched 2026-07-09):
  Cuyahoga OH  : gis.cuyahogacounty.gov Parcel_Fabric_Taxparcels FeatureServer/0
  Shelby TN    : scgis.shelbycountytn.gov CERTParcel MapServer/0 + MapServer/1 (RSALES join)
  Harris TX    : gis.hctx.net HCAD/Parcels MapServer/0
  Jefferson AL : jccgis.jccal.org Basemap/Parcels MapServer/0
  Duval FL     : services5.arcgis.com FL_Parcels FeatureServer/0 (statewide FL roll)

Priority chain per market in run.py:
  real CSV override -> live loader here -> generate_mock_house_leads()

Known field gaps (no live free source):
  Shelby TN   : no assessed value, no year built in any public layer
  Harris TX   : no year built in the HCAD parcels REST layer
  Jefferson AL: no year built, no sale date in any public layer

For Alabama: AssdValue is 10% of market; PrevParcelTotal is the full appraised value.
We use PrevParcelTotal (market-level value) for the $50k-$300k filter and offer calc.
"""
import datetime
import json
import re
import urllib.parse
import urllib.request

from house_data import CURRENT_YEAR, HouseLead, _is_non_individual

_TIMEOUT = 60


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_json(url, params=None):
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
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


# ─── Cuyahoga County OH (Cleveland) ──────────────────────────────────────────
# All needed fields available in one layer.
# tax_market_total = Ohio's full market value estimate (assessed = 35% of market).
# We filter and display on market value so the $50k-$300k range reflects real prices.
# homestead_flag = 1 means owner-occupied homestead; non-1/null = likely absentee.
# min_age = year the oldest structure was built.

_CUYAHOGA_URL = (
    "https://gis.cuyahogacounty.gov/server/rest/services/CCFO"
    "/Parcel_Fabric_Taxparcels/FeatureServer/0/query"
)


def load_cuyahoga_oh(market, limit=15):
    # Cuyahoga par_addr_all format: "NUMBER STREET, CITY, OH, ZIP"
    # Use separate parcel_city + parcel_zip fields to avoid parsing.
    ten_yr_date = _ten_years_ago_date()
    params = {
        "where": (
            "property_class='R' AND min_age > 0 AND min_age < 1990 "
            "AND tax_market_total >= 50000 AND tax_market_total <= 300000 "
            "AND tax_assessed_improvement > 0 "
            f"AND last_transfer_date < {ten_yr_date}"
        ),
        "outFields": (
            "parcel_id,parcel_owner,mail_addr_street,mail_city,mail_state,mail_zip,"
            "par_addr_all,parcel_city,parcel_zip,"
            "min_age,tax_assessed_improvement,tax_market_total,last_transfer_date"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_CUYAHOGA_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [CUYAHOGA_OH] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("parcel_owner") or "").strip()
        if not name or _is_non_individual(name):
            continue

        # Street is everything before the first comma in par_addr_all
        par_addr_all = (a.get("par_addr_all") or "").strip()
        street = par_addr_all.split(",")[0].strip().title() if par_addr_all else ""
        city = (a.get("parcel_city") or "").strip().title()
        zip_code = str(a.get("parcel_zip") or "").strip()
        if not street or not street[:1].isdigit():
            continue

        mail_addr = (a.get("mail_addr_street") or "").strip().title()
        mail_zip = str(a.get("mail_zip") or "").strip()
        mail_state = (a.get("mail_state") or "").strip().upper()
        mail_city = (a.get("mail_city") or "").strip().title()

        # Absentee: mailing ≠ property. Compare 5-digit base zip (mail may have +4 format).
        if mail_addr.upper() == street.upper() and mail_zip[:5] == zip_code[:5]:
            continue

        year_built = int(a.get("min_age") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue

        assessed = float(a.get("tax_market_total") or 0)
        improvement = float(a.get("tax_assessed_improvement") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue

        transfer_ms = a.get("last_transfer_date")
        if not transfer_ms:
            continue
        sale_year = _year_from_ms(transfer_ms)
        years_owned = CURRENT_YEAR - sale_year
        if years_owned < 10:
            continue

        leads.append(HouseLead(
            apn=str(a.get("parcel_id") or "").strip(),
            property_address=street,
            city=city,
            state="OH",
            zip_code=zip_code,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip[:5],  # normalize to 5-digit
            year_built=year_built,
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
        mail_addr = " ".join(p for p in [adrno, adrstr, adrsuf] if p).title()
        mail_city = (a.get("OWN_CITY") or "").strip().title()
        mail_state = (a.get("OWN_STATE") or "").strip().upper()
        mail_zip = str(a.get("OWN_ZIP") or "").strip()

        par_addr = (a.get("PAR_ADDR1") or "").strip()
        city = (a.get("MUNI") or "Memphis").strip().title()

        # Absentee check (state differs is already filtered server-side)
        # No assessed value / year built from this source — set sentinels
        leads.append(HouseLead(
            apn=parid,
            property_address=par_addr,
            city=city,
            state="TN",
            zip_code="",  # no zip in this layer; left blank
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
        prop_addr = " ".join(p for p in [num, street_name, street_sfx] if p).title()
        if not prop_addr or not prop_addr[:1].isdigit():
            continue

        prop_city = (a.get("site_city") or "Houston").strip().title()
        prop_zip = str(a.get("site_zip") or "").strip()

        # Mailing address
        mail1 = (a.get("mail_addr_1") or "").strip().title()
        mail2 = (a.get("mail_addr_2") or "").strip().title()
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


# ─── Jefferson County AL (Birmingham) ────────────────────────────────────────
# Basemap/Parcels MapServer/0 at jccgis.jccal.org.
# Alabama residential assessed value = 10% of market. PrevParcelTotal = full appraised value.
# We use PrevParcelTotal for the $50k–$300k filter (market-level, not assessed-level).
# No year built or sale date in any public layer — those filters are skipped.

_JEFFERSON_URL = (
    "https://jccgis.jccal.org/server/rest/services/Basemap/Parcels/MapServer/0/query"
)


def load_jefferson_al(market, limit=15):
    params = {
        "where": (
            "Cls='R' AND BLDG_IND='YES' "
            "AND PrevParcelTotal >= 50000 AND PrevParcelTotal <= 300000 "
            "AND PrevParcelImp > 0 "
            "AND OWNERNAME IS NOT NULL "
            "AND STATE_Mail IS NOT NULL AND STATE_Mail NOT IN ('AL','')"
        ),
        "outFields": (
            "PARCELID,OWNERNAME,PROP_MAIL,CITYMAIL,ZIP_MAIL,STATE_Mail,"
            "ADDR_PSPR,CITY,ZIP,PrevParcelImp,PrevParcelTotal"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 1000),
        "f": "json",
    }
    try:
        data = _get_json(_JEFFERSON_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [JEFFERSON_AL] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWNERNAME") or "").strip()
        if not name or _is_non_individual(name):
            continue

        prop_addr = (a.get("ADDR_PSPR") or "").strip()
        if not prop_addr or not prop_addr[:1].isdigit():
            continue
        prop_city = (a.get("CITY") or "Birmingham").strip().title()
        prop_zip = str(a.get("ZIP") or "").strip()

        mail_addr = (a.get("PROP_MAIL") or "").strip().title()
        mail_city = (a.get("CITYMAIL") or "").strip().title()
        mail_state = (a.get("STATE_Mail") or "").strip().upper()
        mail_zip = str(a.get("ZIP_MAIL") or "").strip()

        # Absentee (already filtered server-side to non-AL; also check same-state)
        if mail_addr.upper() == prop_addr.upper() and mail_zip == prop_zip:
            continue

        # PrevParcelTotal = full appraised (market) value for AL
        assessed = float(a.get("PrevParcelTotal") or 0)
        improvement = float(a.get("PrevParcelImp") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue

        leads.append(HouseLead(
            apn=str(a.get("PARCELID") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="AL",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=0,        # not in any public Jefferson AL layer
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=0,       # not in any public Jefferson AL layer
            last_sale_date="",
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Duval County FL (Jacksonville) ──────────────────────────────────────────
# Florida statewide FL_Parcels FeatureServer/0 — annual DOR property roll (Aug 2025).
# DOR_UC='001' = Single Family Residential.
# JV = just value (FL market value). LND_VAL = land value. JV > LND_VAL → structure exists.
# SALE_YR1/SALE_MO1 = most recent recorded sale year/month.
# ACT_YR_BLT = actual year built.

_DUVAL_URL = (
    "https://services5.arcgis.com/GcvM6vDlR2gM4x31/arcgis/rest/services"
    "/FL_Parcels/FeatureServer/0/query"
)
_DUVAL_10YR = CURRENT_YEAR - 10  # SALE_YR1 <= this means 10+ yr hold


def load_duval_fl(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            "CountyName='Duval' AND DOR_UC='001' "
            "AND ACT_YR_BLT > 0 AND ACT_YR_BLT < 1990 "
            "AND JV >= 50000 AND JV <= 300000 "
            "AND JV > LND_VAL "
            f"AND (SALE_YR1 IS NULL OR SALE_YR1 <= {_DUVAL_10YR}) "
            f"AND PHY_ZIPCD IN ({zip_list}) "
            "AND OWN_NAME IS NOT NULL"
        ),
        "outFields": (
            "PARCEL_ID,OWN_NAME,OWN_ADDR1,OWN_ADDR2,OWN_CITY,OWN_STATE,OWN_ZIPCD,"
            "PHY_ADDR1,PHY_CITY,PHY_ZIPCD,ACT_YR_BLT,JV,LND_VAL,SALE_PRC1,SALE_YR1,SALE_MO1"
        ),
        "returnGeometry": "false",
        "resultRecordCount": min(limit * 6, 2000),
        "f": "json",
    }
    try:
        data = _get_json(_DUVAL_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [DUVAL_FL] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = _attrs(feat)
        name = (a.get("OWN_NAME") or "").strip()
        if not name or _is_non_individual(name):
            continue

        prop_addr = (a.get("PHY_ADDR1") or "").strip()
        if not prop_addr or not prop_addr[:1].isdigit():
            continue
        prop_city = (a.get("PHY_CITY") or "Jacksonville").strip().title()
        prop_zip = str(a.get("PHY_ZIPCD") or "").strip()

        # Mailing address (OWN_ADDR2 is continuation/unit; OWN_ADDR1 is street)
        mail_addr = (a.get("OWN_ADDR1") or "").strip().title()
        addr2 = (a.get("OWN_ADDR2") or "").strip()
        if addr2:
            mail_addr = f"{mail_addr} {addr2.title()}".strip()
        mail_city = (a.get("OWN_CITY") or "").strip().title()
        mail_state = (a.get("OWN_STATE") or "").strip().upper()
        mail_zip = str(a.get("OWN_ZIPCD") or "").strip()

        # Absentee: out-of-state OR different zip from property
        if mail_state == "FL" and mail_zip == prop_zip:
            continue  # same state + same zip = likely owner-occupied

        year_built = int(a.get("ACT_YR_BLT") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue

        jv = float(a.get("JV") or 0)
        lnd = float(a.get("LND_VAL") or 0)
        improvement = jv - lnd
        if not (50000 <= jv <= 300000) or improvement <= 0:
            continue

        sale_yr = int(a.get("SALE_YR1") or 0)
        _mo_raw = str(a.get("SALE_MO1") or "").strip()
        sale_mo = int(_mo_raw) if _mo_raw.isdigit() else 1
        years_owned = CURRENT_YEAR - sale_yr if sale_yr > 1900 else 20
        if years_owned < 10:
            continue

        leads.append(HouseLead(
            apn=str(a.get("PARCEL_ID") or "").strip(),
            property_address=prop_addr,
            city=prop_city,
            state="FL",
            zip_code=prop_zip,
            owner_name=name.title(),
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=jv,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=f"{sale_yr}-{sale_mo:02d}" if sale_yr else "",
            last_sale_price=float(a.get("SALE_PRC1") or 0),
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break

    return leads


# ─── Registry ─────────────────────────────────────────────────────────────────

LIVE_HOUSE_LOADERS = {
    "CUYAHOGA_OH": load_cuyahoga_oh,
    "SHELBY_TN": load_shelby_tn,
    "HARRIS_TX": load_harris_tx,
    "JEFFERSON_AL": load_jefferson_al,
    "DUVAL_FL": load_duval_fl,
}
