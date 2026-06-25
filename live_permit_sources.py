"""
Live free permit sources -- the buyer/builder-discovery half of the pipeline
going real, market by market. San Antonio (clean CSV), Austin/Travis (clean
Socrata API), and Gwinnett (PDF report, parsed with pdfplumber) are wired up
as of 2026-06-24.

pdfplumber is this project's first non-stdlib dependency (`pip3 install
pdfplumber`) -- everything else here is deliberately stdlib-only. Adding it
was a real tradeoff (more fragile than a REST API: a report layout change
could silently break the Gwinnett parser) flagged to and approved by the
user before building it -- don't add further PDF/scraping-based sources
without the same explicit check-in.

run.py tries, per market: real CSV override -> a registered live loader
here -> mock. Same priority chain as gis_land_sources.py's land loaders.
"""
import csv
import datetime
import http.client
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import pdfplumber

from permits_data import Permit


def _get_json(url, timeout=30):
    """Plain GET with a spoofed User-Agent -- some government-hosted ArcGIS
    Servers (not Esri's own arcgis.com hosting) 403 on Python's default
    urllib User-Agent, confirmed live 2026-06-25 (same gotcha documented in
    gis_land_sources.py)."""
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


SA_PERMITS_URL = (
    "https://data.sanantonio.gov/dataset/05012dcb-ba1b-4ade-b5f3-7403bc7f52eb/"
    "resource/c21106f9-3ef5-4f3a-8604-f992b4db7512/download/permits_issued.csv"
)
# The real PERMIT TYPE value for new single-family construction in this feed
# -- confirmed live 2026-06-23 (rows show real builders: CHESMAR HOMES,
# LENNAR HOMES, Habitat for Humanity of San Antonio, etc). Every row of this
# type in the feed has a blank DECLARED VALUATION -- not missing-by-error,
# the field just isn't populated for this permit type -- so construction
# value comes back as None ("unknown"), not 0.0.
SA_NEW_CONSTRUCTION_PERMIT_TYPE = "Res New Building Permit"


def _extract_zip(address):
    token = address.strip().split()[-1] if address.strip() else ""
    return token if token.isdigit() and len(token) == 5 else None


def _http_get(url, headers):
    parsed = urllib.parse.urlparse(url)
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=60)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    conn.request("GET", path, headers=headers)
    return conn, conn.getresponse()


def _fetch_following_redirect(url, headers):
    """Plain GET via http.client, deliberately NOT urllib.request -- the
    permits_issued.csv download 302s data.sanantonio.gov to a presigned S3
    URL, and urllib.request's higher-level Request/opener machinery was
    observed re-encoding that URL's query string just enough to break AWS's
    SigV4 signature check (confirmed live 2026-06-24: byte-identical URL and
    headers, 403 via urllib.request, 200 via http.client directly -- root
    cause not fully pinned down, but the fix is proven). Don't swap this
    back to urllib.request without re-testing against the real endpoint."""
    conn, resp = _http_get(url, headers)
    if resp.status in (301, 302, 303, 307, 308):
        location = resp.getheader("Location")
        resp.read()
        conn.close()
        if not location:
            raise RuntimeError(f"Redirect from {url} had no Location header")
        conn, resp = _http_get(location, headers)
    if resp.status != 200:
        body = resp.read(500)
        conn.close()
        raise RuntimeError(f"GET {url} failed: {resp.status} {body!r}")
    return conn, resp


def fetch_san_antonio_permits(market, limit=None):
    """Streams City of San Antonio's public 'permits_issued.csv' (Open Data
    SA, CKAN-hosted on S3, ~22MB, no login) and keeps only new-construction
    permits in market.zips. Scoped to market.zips for the same reason as
    gis_land_sources.py's Bexar land loader: keeps matching meaningful while
    other markets are still mock.
    """
    zips = {z for z, _city, _area in market.zips}
    conn, resp = _fetch_following_redirect(SA_PERMITS_URL, {"User-Agent": "curl/8.4.0"})

    permits = []
    try:
        reader = csv.DictReader(io.TextIOWrapper(resp, encoding="utf-8", errors="replace"))
        for row in reader:
            if row.get("PERMIT TYPE") != SA_NEW_CONSTRUCTION_PERMIT_TYPE:
                continue
            address = row.get("ADDRESS") or ""
            zip_code = _extract_zip(address)
            if zip_code not in zips:
                continue
            contractor_name = (row.get("PRIMARY CONTACT") or "").strip()
            permit_number = (row.get("PERMIT #") or "").strip()
            if not contractor_name or not permit_number:
                continue
            valuation = (row.get("DECLARED VALUATION") or "").strip()
            permits.append(Permit(
                permit_number=permit_number,
                contractor_name=contractor_name,
                property_address=address,
                zip=zip_code,
                permit_type=row.get("PERMIT TYPE") or SA_NEW_CONSTRUCTION_PERMIT_TYPE,
                issue_date=row.get("DATE ISSUED") or "",
                construction_value=float(valuation) if valuation else None,
            ))
            if limit and len(permits) >= limit:
                break
    finally:
        conn.close()
    return permits


GWINNETT_PERMITS_LISTING_URL = (
    "https://www.gwinnettcounty.com/government/departments/planning-development/"
    "building-services/building-permits-issued"
)
# The county's own typo, not ours -- must match exactly to find new builds.
GWINNETT_NEW_CONSTRUCTION_CENSUS_DESC = ("Single Family - Detatched", "Single Family - Attached")


def _gwinnett_latest_report_url():
    """Confirmed live 2026-06-24: this listing page's report links are NOT
    consistently slugged week to week (seen both 'building-permits-
    MMDDYYYY-MMDDYYYY' and 'building-permits-issued-MMDDYY-MMDDYY' in the
    same link list) -- so don't guess next week's URL. Fetch the listing
    fresh and pick whichever linked report has the latest end date."""
    req = urllib.request.Request(GWINNETT_PERMITS_LISTING_URL, headers={"User-Agent": "curl/8.4.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    links = re.findall(r'href="(/documents/d/gwinnett-county/gwinnett-county-building-permits[^"]*)"', html)

    def _end_date(slug):
        nums = re.findall(r"\d+", slug)
        if not nums:
            return None
        last = nums[-1]
        if len(last) == 8:
            return (int(last[4:8]), int(last[0:2]), int(last[2:4]))
        if len(last) == 6:
            return (2000 + int(last[4:6]), int(last[0:2]), int(last[2:4]))
        return None

    dated = sorted((d, link) for link in links if (d := _end_date(link)) is not None)
    if not dated:
        raise RuntimeError("No Gwinnett building-permits report links found on the listing page.")
    return f"https://www.gwinnettcounty.com{dated[-1][1]}"


def _gwinnett_pdf_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    # This CMS wraps the actual PDF in a small HTML/JS preamble before the
    # real "%PDF" marker -- confirmed live 2026-06-24.
    pdf_start = raw.find(b"%PDF")
    if pdf_start < 0:
        raise RuntimeError(f"No PDF marker found in document at {url}")
    with pdfplumber.open(io.BytesIO(raw[pdf_start:])) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def fetch_gwinnett_permits(market, limit=None):
    """Gwinnett has no permit API or CSV -- only a weekly 'Building Permits
    Issued' PDF report. Parsed with pdfplumber; see this module's docstring
    for why that's a deliberate, approved exception to the stdlib-only rule.

    The report has no property zip code field, only a city name, so zip is
    recovered via market.zips' city list -- a permit in a Gwinnett city
    outside that list is skipped (it couldn't match a land lead anyway,
    since land leads are also scoped to market.zips). Contractor names are
    occasionally truncated (e.g. a trailing "INC." lost) because of how the
    PDF's two-column layout linearizes in text extraction -- an accepted
    imprecision, not a crash.
    """
    city_to_zip = {city.upper(): z for z, city, _area in market.zips}

    text = _gwinnett_pdf_text(_gwinnett_latest_report_url())
    blocks = re.findall(r"CASE NUMBER.*?(?=CASE NUMBER|TOTAL PERMITS)", text, re.DOTALL)

    permits = []
    for block in blocks:
        if not any(desc in block for desc in GWINNETT_NEW_CONSTRUCTION_CENSUS_DESC):
            continue
        permit_m = re.search(r"CASE NUMBER\s+(\S+)", block)
        issued_m = re.search(r"ISSUED ON\s+(\d{1,2}/\d{1,2}/\d{4})", block)
        cost_m = re.search(r"ESTIMATED COST:\s*\$([0-9,]+\.\d{2})", block)
        addr_m = re.search(r"ST ADDRESS, CITY:\s*(.*?)\s*TENANT:", block)
        contractor_m = re.search(r"CONTRACTOR:\s*(.*?)\s*ZONING DISTRICT:", block)
        if not (permit_m and issued_m and cost_m and addr_m and contractor_m):
            continue

        contractor_name = contractor_m.group(1).strip().rstrip(",")
        address_city = addr_m.group(1).strip()
        if "," not in address_city:
            continue
        street, city = (s.strip() for s in address_city.rsplit(",", 1))
        zip_code = city_to_zip.get(city.upper())
        if not contractor_name or not zip_code:
            continue

        mm, dd, yyyy = issued_m.group(1).split("/")
        permits.append(Permit(
            permit_number=permit_m.group(1),
            contractor_name=contractor_name,
            property_address=f"{street}, {city}",
            zip=zip_code,
            permit_type="New Single Family",
            issue_date=f"{yyyy}-{int(mm):02d}-{int(dd):02d}",
            construction_value=float(cost_m.group(1).replace(",", "")),
        ))
        if limit and len(permits) >= limit:
            break
    return permits


AUSTIN_PERMITS_URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"
# Confirmed live 2026-06-24 against this exact dataset's real column names
# (discovered via a deliberately wrong query -- the Socrata error response
# echoes the full column list). 'BP' is the main building permit; a new
# house also pulls separate MP/EP/PP sub-permits under the same
# masterpermitnum for the electrical/mechanical/plumbing subcontractors --
# those aren't the builder and are excluded by this filter.
AUSTIN_NEW_SF_PERMIT_CLASS = "R- 101 Single Family Houses"


def fetch_austin_permits(market, limit=None):
    """Live query against the City of Austin's 'Issued Construction Permits'
    Socrata dataset (data.austintexas.gov, SoQL query API, no login).
    total_job_valuation/building_valuation are unpopulated on permittype='BP'
    records in this feed -- "unknown", not 0, same treatment as Bexar.
    """
    zips = [z for z, _city, _area in market.zips]
    zip_list = ",".join(f"'{z}'" for z in zips)
    where = (
        f"permittype='BP' AND permit_class='{AUSTIN_NEW_SF_PERMIT_CLASS}' "
        f"AND work_class='New' AND original_zip in({zip_list})"
    )
    params = {"$where": where, "$order": "issue_date DESC"}
    if limit:
        params["$limit"] = limit
    url = f"{AUSTIN_PERMITS_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.4.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Austin permits query failed: {e}")
    if isinstance(rows, dict):
        raise RuntimeError(f"Austin permits query failed: {rows}")

    permits = []
    for row in rows:
        contractor_name = (row.get("contractor_company_name") or "").strip()
        permit_number = (row.get("permit_number") or "").strip()
        address = (row.get("original_address1") or "").strip()
        zip_code = (row.get("original_zip") or "").strip()[:5]
        if not contractor_name or not permit_number or not address or not zip_code:
            continue
        permits.append(Permit(
            permit_number=permit_number,
            contractor_name=contractor_name,
            property_address=f"{address}, {(row.get('original_city') or 'Austin').strip()}",
            zip=zip_code,
            permit_type="New Single Family",
            issue_date=(row.get("issue_date") or "")[:10],
            construction_value=None,
        ))
    return permits


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
    "BEXAR_TX": fetch_san_antonio_permits,
    "TRAVIS_TX": fetch_austin_permits,
    "GWINNETT_GA": fetch_gwinnett_permits,
    "MECKLENBURG_NC": fetch_mecklenburg_permits,
    "MARICOPA_AZ": fetch_mesa_permits,
    "DAVIDSON_TN": fetch_nashville_permits,
    "WAKE_NC": fetch_raleigh_permits,
}
