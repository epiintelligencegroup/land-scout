"""
Live county assessor data loaders for house wholesale leads.

Each loader queries the county's open data API directly, filters server-side
where possible, then applies the full filter stack from house_data.py client-side.
Falls through to mock data if the endpoint is unreachable or returns nothing.

Priority chain per market (run.py):
  real CSV override -> live loader here -> generate_mock_house_leads()
"""
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from house_data import (
    CURRENT_YEAR,
    HouseLead,
    _is_non_individual,
    _US_STATE_ABBRS,
)

_TIMEOUT = 20  # seconds per HTTP request


def _get_json(url, params=None):
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "HouseWholesalePipeline/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


# ─── Cuyahoga County OH ──────────────────────────────────────────────────────
# ArcGIS REST service: Cuyahoga County Open Data Parcel layer
_CUYAHOGA_URL = (
    "https://services2.arcgis.com/qvkbeam8lgZ7xKP2/arcgis/rest/services"
    "/Parcel_Data/FeatureServer/0/query"
)


def load_cuyahoga_oh(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"PROP_CLASS='510' AND ZIP5 IN ({zip_list})"
            f" AND YR_BLT < 1990 AND TOTAL_VALUE >= 50000 AND TOTAL_VALUE <= 300000"
        ),
        "outFields": (
            "PARCELID,ADDRESS,CITY,STATE,ZIP5,OWNER1,OWNER_ADDR,OWNER_CITY,"
            "OWNER_STATE,OWNER_ZIP,YR_BLT,TOTAL_VALUE,BUILDING_VALUE,TRANSFER_DATE"
        ),
        "resultRecordCount": limit * 4,  # over-fetch; filters trim it down
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
        a = feat.get("attributes") or {}
        name = (a.get("OWNER1") or "").strip()
        if not name or _is_non_individual(name):
            continue
        prop_addr = (a.get("ADDRESS") or "").strip()
        mail_addr = (a.get("OWNER_ADDR") or "").strip()
        zip_code = str(a.get("ZIP5") or "").strip()
        mail_zip = str(a.get("OWNER_ZIP") or "").strip()
        mail_state = (a.get("OWNER_STATE") or "").strip().upper()
        # Absentee check
        if prop_addr.upper() == mail_addr.upper() and zip_code == mail_zip:
            continue
        assessed = float(a.get("TOTAL_VALUE") or 0)
        improvement = float(a.get("BUILDING_VALUE") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue
        year_built = int(a.get("YR_BLT") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue
        transfer_ms = a.get("TRANSFER_DATE")
        if transfer_ms:
            sale_year = datetime.datetime.utcfromtimestamp(transfer_ms / 1000).year
            years_owned = CURRENT_YEAR - sale_year
        else:
            years_owned = 0
        if years_owned < 10:
            continue
        leads.append(HouseLead(
            apn=str(a.get("PARCELID") or "").strip(),
            property_address=prop_addr,
            city=(a.get("CITY") or "").strip().title(),
            state="OH",
            zip_code=zip_code,
            owner_name=name,
            owner_mailing_address=mail_addr,
            owner_mailing_city=(a.get("OWNER_CITY") or "").strip().title(),
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=str(sale_year) if transfer_ms else "",
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break
    return leads


# ─── Shelby County TN (Memphis) ──────────────────────────────────────────────
# Shelby County Assessor of Property public records API
_SHELBY_URL = (
    "https://services2.arcgis.com/qvkbeam8lgZ7xKP2/arcgis/rest/services"
    "/Shelby_Parcels/FeatureServer/0/query"
)


def load_shelby_tn(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"ZIPCODE IN ({zip_list}) AND PROP_TYPE='R' AND YEAR_BUILT < 1990"
            f" AND APPR_VALUE >= 50000 AND APPR_VALUE <= 300000"
        ),
        "outFields": (
            "PARCEL_ID,SITUS_ADDR,SITUS_CITY,ZIPCODE,OWNER_NAME,MAIL_ADDR,"
            "MAIL_CITY,MAIL_STATE,MAIL_ZIP,YEAR_BUILT,APPR_VALUE,IMPR_VALUE,SALE_DATE"
        ),
        "resultRecordCount": limit * 4,
        "f": "json",
    }
    try:
        data = _get_json(_SHELBY_URL, params)
        features = data.get("features") or []
    except Exception as exc:
        print(f"  [SHELBY_TN] live fetch failed ({exc}), using mock data")
        return []

    leads = []
    for feat in features:
        a = feat.get("attributes") or {}
        name = (a.get("OWNER_NAME") or "").strip()
        if not name or _is_non_individual(name):
            continue
        prop_addr = (a.get("SITUS_ADDR") or "").strip()
        mail_addr = (a.get("MAIL_ADDR") or "").strip()
        zip_code = str(a.get("ZIPCODE") or "").strip()
        mail_zip = str(a.get("MAIL_ZIP") or "").strip()
        mail_state = (a.get("MAIL_STATE") or "").strip().upper()
        if prop_addr.upper() == mail_addr.upper() and zip_code == mail_zip:
            continue
        assessed = float(a.get("APPR_VALUE") or 0)
        improvement = float(a.get("IMPR_VALUE") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue
        year_built = int(a.get("YEAR_BUILT") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue
        sale_date = str(a.get("SALE_DATE") or "")
        sale_year = int(sale_date[:4]) if len(sale_date) >= 4 else 0
        years_owned = CURRENT_YEAR - sale_year if sale_year > 1900 else 0
        if years_owned < 10:
            continue
        leads.append(HouseLead(
            apn=str(a.get("PARCEL_ID") or "").strip(),
            property_address=prop_addr,
            city=(a.get("SITUS_CITY") or "Memphis").strip().title(),
            state="TN",
            zip_code=zip_code,
            owner_name=name,
            owner_mailing_address=mail_addr,
            owner_mailing_city=(a.get("MAIL_CITY") or "").strip().title(),
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=sale_date,
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break
    return leads


# ─── Harris County TX (Houston) ──────────────────────────────────────────────
# HCAD open data REST endpoint for residential parcels
_HARRIS_URL = "https://arcgis.hcad.org/arcgis/rest/services/Public/HCAD_Public/MapServer/0/query"


def load_harris_tx(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"STATE_CLASS='A' AND ZIP_CODE IN ({zip_list})"
            f" AND YR_IMPR < 1990 AND TOT_APPR_VAL >= 50000 AND TOT_APPR_VAL <= 300000"
        ),
        "outFields": (
            "ACCOUNT,SITE_ADDR_1,SITE_CITY,SITE_ZIP,OWNER_NAME,MAIL_ADDR_1,"
            "MAIL_CITY,MAIL_STATE,MAIL_ZIP,YR_IMPR,IMPR_VAL,TOT_APPR_VAL,DEED_DT"
        ),
        "resultRecordCount": limit * 4,
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
        a = feat.get("attributes") or {}
        name = (a.get("OWNER_NAME") or "").strip()
        if not name or _is_non_individual(name):
            continue
        prop_addr = (a.get("SITE_ADDR_1") or "").strip()
        mail_addr = (a.get("MAIL_ADDR_1") or "").strip()
        zip_code = str(a.get("SITE_ZIP") or "").strip()
        mail_zip = str(a.get("MAIL_ZIP") or "").strip()
        mail_state = (a.get("MAIL_STATE") or "").strip().upper()
        if prop_addr.upper() == mail_addr.upper() and zip_code == mail_zip:
            continue
        assessed = float(a.get("TOT_APPR_VAL") or 0)
        improvement = float(a.get("IMPR_VAL") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue
        year_built = int(a.get("YR_IMPR") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue
        deed_ms = a.get("DEED_DT")
        if deed_ms:
            sale_year = datetime.datetime.utcfromtimestamp(deed_ms / 1000).year
            years_owned = CURRENT_YEAR - sale_year
            sale_date = str(sale_year)
        else:
            years_owned = 0
            sale_date = ""
        if years_owned < 10:
            continue
        leads.append(HouseLead(
            apn=str(a.get("ACCOUNT") or "").strip(),
            property_address=prop_addr,
            city=(a.get("SITE_CITY") or "Houston").strip().title(),
            state="TX",
            zip_code=zip_code,
            owner_name=name,
            owner_mailing_address=mail_addr,
            owner_mailing_city=(a.get("MAIL_CITY") or "").strip().title(),
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=sale_date,
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break
    return leads


# ─── Jefferson County AL (Birmingham) ────────────────────────────────────────
_JEFFERSON_URL = (
    "https://gis.jccal.org/arcgis/rest/services/Property/JCCParcelData/MapServer/0/query"
)


def load_jefferson_al(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"PROP_CLASS='R1' AND ZIP IN ({zip_list})"
            f" AND YEAR_BUILT < 1990 AND TOTAL_VALUE >= 50000 AND TOTAL_VALUE <= 300000"
        ),
        "outFields": (
            "PARCEL_NUM,PROP_ADDR,CITY,ZIP,OWNER,MAIL_ADDR,MAIL_CITY,"
            "MAIL_STATE,MAIL_ZIP,YEAR_BUILT,IMPR_VALUE,TOTAL_VALUE,DEED_DATE"
        ),
        "resultRecordCount": limit * 4,
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
        a = feat.get("attributes") or {}
        name = (a.get("OWNER") or "").strip()
        if not name or _is_non_individual(name):
            continue
        prop_addr = (a.get("PROP_ADDR") or "").strip()
        mail_addr = (a.get("MAIL_ADDR") or "").strip()
        zip_code = str(a.get("ZIP") or "").strip()
        mail_zip = str(a.get("MAIL_ZIP") or "").strip()
        mail_state = (a.get("MAIL_STATE") or "").strip().upper()
        if prop_addr.upper() == mail_addr.upper() and zip_code == mail_zip:
            continue
        assessed = float(a.get("TOTAL_VALUE") or 0)
        improvement = float(a.get("IMPR_VALUE") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue
        year_built = int(a.get("YEAR_BUILT") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue
        deed_date = str(a.get("DEED_DATE") or "")
        sale_year = int(deed_date[:4]) if len(deed_date) >= 4 else 0
        years_owned = CURRENT_YEAR - sale_year if sale_year > 1900 else 0
        if years_owned < 10:
            continue
        leads.append(HouseLead(
            apn=str(a.get("PARCEL_NUM") or "").strip(),
            property_address=prop_addr,
            city=(a.get("CITY") or "Birmingham").strip().title(),
            state="AL",
            zip_code=zip_code,
            owner_name=name,
            owner_mailing_address=mail_addr,
            owner_mailing_city=(a.get("MAIL_CITY") or "").strip().title(),
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=deed_date,
            last_sale_price=0.0,
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break
    return leads


# ─── Duval County FL (Jacksonville) ──────────────────────────────────────────
# Duval County Property Appraiser open data ArcGIS REST
_DUVAL_URL = (
    "https://services1.arcgis.com/O1JpcwDW8sjYuddV/arcgis/rest/services"
    "/PAO_Parcel_Data/FeatureServer/0/query"
)


def load_duval_fl(market, limit=15):
    zip_list = ",".join(f"'{z}'" for z, _ in market.zips)
    params = {
        "where": (
            f"DOR_CODE='0100' AND ZIPCODE IN ({zip_list})"
            f" AND YEAR_BLT < 1990 AND JV >= 50000 AND JV <= 300000"
        ),
        "outFields": (
            "PARCEL_ID,SITE_ADDR,SITE_CITY,ZIPCODE,OWN1,MAILING_ADDR1,MAILING_CITY,"
            "MAILING_STATE,MAILING_ZIP,YEAR_BLT,BLDG_VAL,JV,SALE_DATE,SALE_PRC"
        ),
        "resultRecordCount": limit * 4,
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
        a = feat.get("attributes") or {}
        name = (a.get("OWN1") or "").strip()
        if not name or _is_non_individual(name):
            continue
        prop_addr = (a.get("SITE_ADDR") or "").strip()
        mail_addr = (a.get("MAILING_ADDR1") or "").strip()
        zip_code = str(a.get("ZIPCODE") or "").strip()
        mail_zip = str(a.get("MAILING_ZIP") or "").strip()
        mail_state = (a.get("MAILING_STATE") or "").strip().upper()
        if prop_addr.upper() == mail_addr.upper() and zip_code == mail_zip:
            continue
        assessed = float(a.get("JV") or 0)
        improvement = float(a.get("BLDG_VAL") or 0)
        if not (50000 <= assessed <= 300000) or improvement <= 0:
            continue
        year_built = int(a.get("YEAR_BLT") or 0)
        if year_built < 1800 or year_built >= 1990:
            continue
        sale_date = str(a.get("SALE_DATE") or "")
        sale_year = int(sale_date[:4]) if len(sale_date) >= 4 else 0
        years_owned = CURRENT_YEAR - sale_year if sale_year > 1900 else 0
        if years_owned < 10:
            continue
        leads.append(HouseLead(
            apn=str(a.get("PARCEL_ID") or "").strip(),
            property_address=prop_addr,
            city=(a.get("SITE_CITY") or "Jacksonville").strip().title(),
            state="FL",
            zip_code=zip_code,
            owner_name=name,
            owner_mailing_address=mail_addr,
            owner_mailing_city=(a.get("MAILING_CITY") or "").strip().title(),
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=assessed,
            improvement_value=improvement,
            years_owned=years_owned,
            last_sale_date=sale_date,
            last_sale_price=float(a.get("SALE_PRC") or 0),
            property_class="SFR",
        ))
        if len(leads) >= limit:
            break
    return leads


# Registry: market key -> live loader function
LIVE_HOUSE_LOADERS = {
    "CUYAHOGA_OH": load_cuyahoga_oh,
    "SHELBY_TN": load_shelby_tn,
    "HARRIS_TX": load_harris_tx,
    "JEFFERSON_AL": load_jefferson_al,
    "DUVAL_FL": load_duval_fl,
}
