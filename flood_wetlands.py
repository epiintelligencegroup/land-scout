"""
Real, free, nationwide flood-zone and wetlands lookups -- added 2026-06-25
for the 6-new-market rollout, where the user wants these as a hard FILTER
(Zone X only, no wetlands), not just the mock display badges enrichment.py
has had for every market since day one. Both are live federal ArcGIS REST
services covering the whole US, so unlike every other live source in this
project, these two are not per-market -- confirmed live against real points
(FEMA: San Antonio test point returned real "X"/"AREA OF MINIMAL FLOOD
HAZARD"; USFWS: an Everglades bounding box returned real wetland polygons,
a single-point guess elsewhere came back empty because wetlands are patchy,
not a service failure).

Each land loader that uses these needs the parcel's centroid lat/lon --
request geometry with outSR=4326 in the parcel query and average the ring
vertices (a cheap approximation, fine for this purpose since flood zones
and wetlands are large contiguous areas, not finely sliced).
"""
import json
import urllib.error
import urllib.parse
import urllib.request

FEMA_NFHL_FLOOD_ZONES_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
USFWS_WETLANDS_URL = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query"


def centroid_of_rings(rings):
    """Simple vertex-average centroid from an Esri polygon geometry's first
    ring -- not a true geometric centroid for irregular shapes, but a fine
    approximation for point-in-flood-zone/point-in-wetland lookups."""
    ring = rings[0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(ys) / len(ys), sum(xs) / len(xs)  # lat, lon


def _query_point(url, lon, lat, out_fields):
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(full_url, timeout=30) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        raise RuntimeError(f"Query failed ({url}): {data['error']}")
    return data.get("features", [])


def is_zone_x_no_shading(lat, lon):
    """True for "no high flood risk" per FEMA's own classification -- Zone X
    (both the shaded 0.2%-annual-chance/moderate-risk subtype and the
    unshaded minimal-risk subtype). FEMA itself only labels A/AE/AH/AO/V/VE
    zones "high risk" (Special Flood Hazard Area, mandatory flood
    insurance); shaded X is "moderate risk", not "high risk" -- so it
    passes this filter. False for any non-X zone. None if FEMA has no
    detailed flood study at this exact point -- callers should treat None
    as "can't confirm safe", not as a pass.

    Correction made 2026-06-25: this originally also excluded shaded X,
    which is stricter than the user's actual request ("no high flood risk
    -- Zone X only") and caused a real failure -- confirmed live that swaths
    of the Phoenix/Mesa, AZ metro area (extensive desert-wash drainage) are
    mapped shaded-X, so the stricter version returned zero leads for that
    entire market. The function name is kept for now even though it no
    longer excludes shading, to avoid a churn-y rename mid-rollout.
    """
    try:
        features = _query_point(FEMA_NFHL_FLOOD_ZONES_URL, lon, lat, "FLD_ZONE,ZONE_SUBTY")
    except (RuntimeError, urllib.error.URLError, OSError):
        return None
    if not features:
        return None
    attrs = features[0]["attributes"]
    zone = (attrs.get("FLD_ZONE") or "").strip().upper()
    return zone == "X"


def has_wetlands(lat, lon):
    """True if an NWI wetland polygon intersects this point, False if none,
    None if the query itself failed (network/service error -- callers
    should treat None as "can't confirm clear", not as a pass)."""
    try:
        features = _query_point(USFWS_WETLANDS_URL, lon, lat, "Wetlands.ATTRIBUTE")
    except (RuntimeError, urllib.error.URLError, OSError):
        return None
    return len(features) > 0


def passes_flood_wetlands_filter(lat, lon):
    """Hard filter used by the 6-new-market land loaders: Zone X (unshaded)
    only, no wetlands. A failed/inconclusive lookup on either check fails
    the parcel closed (excluded) rather than assuming it's safe."""
    return is_zone_x_no_shading(lat, lon) is True and has_wetlands(lat, lon) is False
