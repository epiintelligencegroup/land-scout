"""
Live free permit sources -- the buyer/builder-discovery half of the pipeline
going real, market by market. Currently just San Antonio (Bexar). See
Market.permit_source in markets.py for why Jacksonville/Gwinnett aren't
wired up yet.

run.py tries, per market: real CSV override -> a registered live loader
here -> mock. Same priority chain as gis_land_sources.py's land loaders.
"""
import csv
import http.client
import io
import urllib.parse

from permits_data import Permit

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


# Keyed by Market.key -- run.py checks this before falling back to mock.
LIVE_PERMIT_LOADERS = {
    "BEXAR_TX": fetch_san_antonio_permits,
}
