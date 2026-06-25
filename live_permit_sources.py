"""
Live free permit sources -- the buyer/builder-discovery half of the pipeline.
All 4 active markets are wired up: Mecklenburg NC, Maricopa/Mesa AZ,
Davidson/Nashville TN, Wake/Raleigh NC.

run.py tries, per market: real CSV override -> a registered live loader
here -> mock. Same priority chain as gis_land_sources.py's land loaders.
"""
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

from permits_data import Permit


def _get_json(url, timeout=30):
    """Plain GET with a spoofed User-Agent -- some government-hosted ArcGIS
    Servers 403 on Python's default urllib User-Agent."""
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


MECKLENBURG_PERMITS_URL = (
    "https://meckgis.mecklenburgcountync.gov/server/rest/services/BuildingPermits/FeatureServer/0/query"
)
# worktype='New' alone is too broad -- catches sheds/decks/garages tagged
# "No Review Bldg Permit" (confirmed live 2026-06-25, $3K-$8K bldgcost rows).
# permitdesc's free-text "SF Dwelling Detached" marker is what actually
# isolates true new-home builds.
MECKLENBURG_NEW_SF_PERMIT_DESC = "SF Dwelling Detached"


def fetch_mecklenburg_permits(market, limit=None):
    """Live query against Mecklenburg County's own 'BuildingPermits' ArcGIS
    Feature Service -- free, no login, countywide (not city-of-Charlotte-
    only). 'ownname' acts as the builder/developer field for new spec-home
    construction (no separate explicit contractor-name field, but functions
    as one here -- this permit type is new ground-up construction, so the
    permit's owner-of-record at issuance is the builder, not a homeowner).
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        f"permittype='One/Two Family' AND permitdesc LIKE '%{MECKLENBURG_NEW_SF_PERMIT_DESC}%' "
        f"AND zipcode IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": "permitnum,projadd,zipcode,issuedate,bldgcost,ownname",
        "orderByFields": "issuedate DESC",
        "returnGeometry": "false",
        "f": "json",
    }
    if limit:
        params["resultRecordCount"] = limit
    url = f"{MECKLENBURG_PERMITS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Mecklenburg permits query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Mecklenburg permits query failed: {data['error']}")

    permits = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        contractor_name = (attrs.get("ownname") or "").strip()
        permit_number = (attrs.get("permitnum") or "").strip()
        # projadd has inconsistent whitespace padding, confirmed live.
        address = " ".join((attrs.get("projadd") or "").split())
        zip_code = (attrs.get("zipcode") or "").strip()[:5]
        if not contractor_name or not permit_number or not address or not zip_code:
            continue
        issue_date_ms = attrs.get("issuedate")
        issue_date = (
            datetime.datetime.utcfromtimestamp(issue_date_ms / 1000).strftime("%Y-%m-%d")
            if issue_date_ms else ""
        )
        permits.append(Permit(
            permit_number=permit_number,
            contractor_name=contractor_name,
            property_address=address,
            zip=zip_code,
            permit_type="New Single Family",
            issue_date=issue_date,
            construction_value=attrs.get("bldgcost"),
        ))
        if limit and len(permits) >= limit:
            break
    return permits


MESA_PERMITS_URL = "https://data.mesaaz.gov/resource/dzpk-hxfb.json"
# 'application_name' starting with "NSFR" (New Single Family Residence) is
# the real signal that isolates ground-up new homes -- confirmed live
# 2026-06-25 that type_of_work='Single Family (Detached)' AND status=
# 'Issued' alone also matches accessory-structure permits on single-family
# lots (e.g. a $4,998 aluminum trellis), since that field describes the
# property type the permit applies to, not what's being built.
MESA_NEW_SF_APPLICATION_PREFIX = "NSFR"


CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"


def _zip_from_latlon(lat, lon):
    """Reverse-geocodes a point to its ZIP Code Tabulation Area (ZCTA, the
    Census Bureau's zip-equivalent) via the free, no-key Census Geocoder.
    Used for Mesa permits below, which have lat/lon but no property-zip
    field at all -- confirmed live 2026-06-25 (only contractor_zip exists,
    the contractor's own mailing zip, not the job site's). A naive fix
    (placeholder zip for every permit) was tried first and rejected: it
    would have collapsed every Mesa builder's active_zips to one zip,
    badly distorting matcher.py's zip-based matching across the rest of
    Mesa. Cross-referencing the Maricopa Assessor's own parcel layer by
    APN or by spatial point-lookup was also tried and both came back
    empty/blank for brand-new subdivision parcels not yet in the
    assessor's system -- the Census Geocoder works regardless of assessor
    data lag since it geocodes the raw coordinate, not parcel records.
    Returns None if the geocoder has no ZCTA at this point (rare).
    """
    params = {
        "x": lon, "y": lat, "benchmark": "Public_AR_Current",
        "vintage": "Current_Current", "layers": "2", "format": "json",
    }
    url = f"{CENSUS_GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url, timeout=15)
    except urllib.error.URLError:
        return None
    zctas = data.get("result", {}).get("geographies", {}).get("2020 Census ZIP Code Tabulation Areas", [])
    return zctas[0]["ZCTA5"] if zctas else None


def fetch_mesa_permits(market, limit=None):
    """Live query against the City of Mesa's 'Building Permits' Socrata
    dataset (data.mesaaz.gov, SoQL query API, no login, updated daily). No
    zip-scoping WHERE clause -- every Mesa permit is in-market by
    definition since the whole Maricopa market is Mesa-only (see
    markets.py's MARICOPA_AZ) -- but each permit's real zip is still
    resolved individually via _zip_from_latlon, since matcher.py needs a
    correct per-permit zip, not just "somewhere in Mesa", to match builders
    to leads in the right part of town.
    """
    where = (
        f"type_of_work='Single Family (Detached)' AND status='Issued' "
        f"AND application_name LIKE '{MESA_NEW_SF_APPLICATION_PREFIX}%'"
    )
    params = {"$where": where, "$order": "issued_date DESC"}
    if limit:
        params["$limit"] = limit
    url = f"{MESA_PERMITS_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Mesa permits query failed: {e}")
    if isinstance(rows, dict):
        raise RuntimeError(f"Mesa permits query failed: {rows}")

    permits = []
    for row in rows:
        contractor_name = (row.get("contractor_name") or "").strip()
        permit_number = (row.get("permit_number") or "").strip()
        address = (row.get("property_address") or "").strip()
        lat, lon = row.get("latitude"), row.get("longitude")
        if not contractor_name or not permit_number or not address or not lat or not lon:
            continue
        zip_code = _zip_from_latlon(float(lat), float(lon))
        if not zip_code:
            continue
        valuation = row.get("total_valuation")
        permits.append(Permit(
            permit_number=permit_number,
            contractor_name=contractor_name,
            property_address=f"{address}, Mesa",
            zip=zip_code,
            permit_type="New Single Family",
            issue_date=(row.get("issued_date") or "")[:10],
            construction_value=float(valuation) if valuation else None,
        ))
        if limit and len(permits) >= limit:
            break
    return permits


NASHVILLE_PERMITS_URL = (
    "https://services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/services/Building_Permits_Issued_2/FeatureServer/0/query"
)


def fetch_nashville_permits(market, limit=None):
    """Live query against Metro Nashville's 'Building_Permits_Issued_2'
    ArcGIS Feature Service -- free, no login. data.nashville.gov's classic
    Socrata portal is defunct (redirects to an "ArcGIS Hub Unsupported"
    page); Nashville migrated permits to ArcGIS Online. 'Contact' is the
    builder field but format is inconsistent -- some last-name-first (e.g.
    "HORTON, D R INC" for D.R. Horton) -- shown as-is rather than guessing
    a normalized name.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        "Permit_Type_Description='Building Residential - New' "
        "AND Permit_Subtype_Description='Single Family Residence' "
        f"AND ZIP IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": "Permit__,Address,City,ZIP,Date_Issued,Const_Cost,Contact",
        "orderByFields": "Date_Issued DESC",
        "returnGeometry": "false",
        "f": "json",
    }
    if limit:
        params["resultRecordCount"] = limit
    url = f"{NASHVILLE_PERMITS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Nashville permits query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Nashville permits query failed: {data['error']}")

    permits = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        contractor_name = (attrs.get("Contact") or "").strip()
        permit_number = (attrs.get("Permit__") or "").strip()
        address = (attrs.get("Address") or "").strip()
        zip_code = (attrs.get("ZIP") or "").strip()[:5]
        if not contractor_name or not permit_number or not address or not zip_code:
            continue
        issue_date_ms = attrs.get("Date_Issued")
        issue_date = (
            datetime.datetime.utcfromtimestamp(issue_date_ms / 1000).strftime("%Y-%m-%d")
            if issue_date_ms else ""
        )
        permits.append(Permit(
            permit_number=permit_number,
            contractor_name=contractor_name,
            property_address=f"{address}, {(attrs.get('City') or 'Nashville').strip()}",
            zip=zip_code,
            permit_type="New Single Family",
            issue_date=issue_date,
            construction_value=attrs.get("Const_Cost"),
        ))
        if limit and len(permits) >= limit:
            break
    return permits


RALEIGH_PERMITS_URL = "https://services.arcgis.com/v400IkDOw1ad7Yad/arcgis/rest/services/Building_Permits/FeatureServer/0/query"


def fetch_raleigh_permits(market, limit=None):
    """Live query against the City of Raleigh's 'Building_Permits' ArcGIS
    Feature Service -- free, no login. Wake County's OWN 'Building_Permits'
    layer exists but its CONTRACTOR/ISSUE_DATE fields are null on every
    record sampled live (county describes the data as legacy/incomplete) --
    not usable, hence Raleigh's own feed here. jurisdiction on this feed is
    100% Raleigh's FIPS place code -- it is Raleigh-city-only, matching
    WAKE_NC's Raleigh-only zip scope in markets.py. proposeduse/streettype
    strings have inconsistent leading whitespace/tabs -- stripped here.
    """
    zips = [z for z, _city, _area in market.zips]
    where = (
        "workclassmapped='New' AND proposeduse LIKE '%SINGLE FAMILY%' "
        f"AND originalzip IN ({','.join(repr(z) for z in zips)})"
    )
    params = {
        "where": where,
        "outFields": "permitnum,contractorcompanyname,streetnum,streetname,streettype,originalzip,issueddate",
        "orderByFields": "issueddate DESC",
        "returnGeometry": "false",
        "f": "json",
    }
    if limit:
        params["resultRecordCount"] = limit
    url = f"{RALEIGH_PERMITS_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Raleigh permits query failed: {e}")
    if "error" in data:
        raise RuntimeError(f"Raleigh permits query failed: {data['error']}")

    permits = []
    for feature in data.get("features", []):
        attrs = feature["attributes"]
        contractor_name = (attrs.get("contractorcompanyname") or "").strip()
        permit_number = (attrs.get("permitnum") or "").strip()
        street = " ".join(
            p.strip() for p in [attrs.get("streetnum"), attrs.get("streetname"), attrs.get("streettype")]
            if p and p.strip()
        )
        zip_code = (attrs.get("originalzip") or "").strip()[:5]
        if not contractor_name or not permit_number or not street or not zip_code:
            continue
        issue_date_ms = attrs.get("issueddate")
        issue_date = (
            datetime.datetime.utcfromtimestamp(issue_date_ms / 1000).strftime("%Y-%m-%d")
            if issue_date_ms else ""
        )
        permits.append(Permit(
            permit_number=permit_number,
            contractor_name=contractor_name,
            property_address=f"{street}, Raleigh",
            zip=zip_code,
            permit_type="New Single Family",
            issue_date=issue_date,
            construction_value=None,  # not exposed on this feed
        ))
        if limit and len(permits) >= limit:
            break
    return permits


# Keyed by Market.key -- run.py checks this before falling back to mock.
LIVE_PERMIT_LOADERS = {
    "MECKLENBURG_NC": fetch_mecklenburg_permits,
    "MARICOPA_AZ": fetch_mesa_permits,
    "DAVIDSON_TN": fetch_nashville_permits,
    "WAKE_NC": fetch_raleigh_permits,
}
