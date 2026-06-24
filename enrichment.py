"""
Per-parcel enrichment: zoning, flood zone, and wetland status -- the "tell
the buyer everything they need to know" fields that PropStream doesn't
provide.

Every market in markets.py genuinely publishes this for free -- see each
Market's gis_source for the real portal/endpoint -- but none of those
endpoints have been wired up live yet (Duval's maps.coj.net returned a
maintenance page when checked; the other three are documented but unverified
against a real query). Rather than wire up an unconfirmed live dependency,
these are mocked for v1 -- deterministic per APN so re-running on the same
lead gives the same answer. Swap each function's body for a real ArcGIS REST
query (typically `<server>/MapServer/<layer>/query?geometry=...&f=json`)
once a given market's live endpoint is confirmed.

Zoning vocabulary differs by market (real local convention, used only to
make mock output plausible -- see each Market.zoning_codes in markets.py).
Flood zone codes (X/AE/A) are FEMA's national standard, so that part of the
mock is market-agnostic by design, not an oversight.
"""
import random

from markets import MARKETS

# Real per-market zoning vocabulary, keyed by (county, state) -- mirrors
# markets.py since LandLead carries county/state but not the Market object.
ZONING_CODES_BY_MARKET = {(m.county, m.state): m.zoning_codes for m in MARKETS}

FLOOD_ZONES = [
    ("X", "minimal", 0.70),   # outside the 500-year floodplain -- most common inland
    ("AE", "high", 0.20),     # 100-year floodplain, common near major rivers/marsh
    ("A", "high", 0.10),      # 100-year floodplain, no base flood elevation determined
]


def _rng_for(apn):
    return random.Random(f"enrichment-{apn}")


def zoning_lookup(land_lead):
    """TODO: replace with a real query against the parcel's market-specific
    zoning GIS layer (see Market.gis_source in markets.py) once a live
    endpoint is confirmed for that market -- query by the parcel's lat/lon
    or APN."""
    zoning_codes = ZONING_CODES_BY_MARKET[(land_lead.county, land_lead.state)]
    return _rng_for(land_lead.apn).choice(zoning_codes)


def flood_lookup(land_lead):
    """TODO: replace with a real query against the FEMA-sourced flood zone
    layer for the parcel's market (see Market.gis_source in markets.py) once
    a live endpoint is confirmed."""
    rng = _rng_for(land_lead.apn + "-flood")
    roll = rng.random()
    cumulative = 0.0
    for zone, risk, weight in FLOOD_ZONES:
        cumulative += weight
        if roll <= cumulative:
            return {"zone": zone, "risk_level": risk}
    return {"zone": FLOOD_ZONES[-1][0], "risk_level": FLOOD_ZONES[-1][1]}


def wetland_lookup(land_lead):
    """TODO: replace with a real query against the parcel's market-specific
    wetlands/environmental overlay layer once a live endpoint is confirmed.
    Most platted residential infill lots aren't wetlands -- that's reflected
    in the low mock probability below, same across all markets."""
    rng = _rng_for(land_lead.apn + "-wetland")
    return rng.random() < 0.10


def enrich(land_lead):
    flood = flood_lookup(land_lead)
    return {
        "zoning": zoning_lookup(land_lead),
        "flood_zone": flood["zone"],
        "flood_risk": flood["risk_level"],
        "wetlands_present": wetland_lookup(land_lead),
    }
