"""
Registry of target markets the pipeline runs against, simultaneously, each
run. Each Market carries:

  - real county/state identity (used in contract templates and the digest
    email -- never invented per-deal)
  - real zip/city/area triples, used only to make mock land leads and mock
    permits plausible (same role JACKSONVILLE_ZIPS played before this was
    multi-market)
  - plausible local builder LLC names, mock flavor only
  - a plausible zoning-code vocabulary for mock enrichment output
  - the real free permit and GIS sources to wire up live later, with honest
    notes on what's actually confirmed vs. not (see README) -- same spirit as
    enrichment.py's original Duval TODOs, just one block per market now.
  - a real free land-data source (land_source) as a PropStream alternative,
    for when PropStream itself isn't usable (e.g. free-trial export limits).
    Bexar's is live-wired in gis_land_sources.py; Duval/Gwinnett's are
    confirmed real and free but not yet fetchable without one manual
    download to pin down the exact column layout.

Going live in a new market is: confirm the permit/GIS endpoints below, then
update land_data.py/permits_data.py/enrichment.py's load-real-data paths --
the Market record itself doesn't need to change.
"""
from dataclasses import dataclass

STATE_NAMES = {
    "FL": "Florida",
    "TX": "Texas",
    "GA": "Georgia",
    "TN": "Tennessee",
}


@dataclass
class Market:
    key: str            # env var suffix, e.g. "BEXAR_TX"
    label: str          # display name for the digest email
    county: str
    state: str          # two-letter abbreviation, matches LandLead.state
    zips: list          # [(zip, city, area_label), ...] -- real, mock-data flavor only
    builder_names: list  # plausible local builder LLC names -- mock flavor only
    zoning_codes: list  # plausible zoning vocabulary -- mock enrichment flavor only
    permit_source: str  # real permit data source(s), for the live-wiring step
    gis_source: str      # real free GIS source(s) for zoning/flood/parcels
    permit_source_is_free: bool  # True only if permit_source is a confirmed free source.
    # run.py skips a market automatically (no mock/digest) when this is False
    # and no real CSV override is configured for it -- see PERMITS_CSV_PATH_<key>
    # in README. The point: never quietly start relying on a paid permit feed.
    # Real free alternative to a PropStream export, for when PropStream itself
    # isn't available (e.g. free-trial export limits) -- purely informational,
    # no run.py gate on this one. See gis_land_sources.py for any that are
    # actually live-wired (currently just Bexar).
    land_source: str = ""


JACKSONVILLE_FL = Market(
    key="JACKSONVILLE_FL",
    label="Jacksonville, FL (Duval County)",
    county="Duval",
    state="FL",
    zips=[
        ("32208", "Jacksonville", "Northwest Jacksonville"),
        ("32209", "Jacksonville", "Northwest Jacksonville"),
        ("32218", "Jacksonville", "North Jacksonville"),
        ("32220", "Jacksonville", "Westside"),
        ("32221", "Jacksonville", "Westside"),
        ("32222", "Jacksonville", "Westside"),
        ("32234", "Jacksonville", "Baldwin"),
        ("32244", "Jacksonville", "Westside"),
        ("32246", "Jacksonville", "Southside"),
        ("32257", "Jacksonville", "Mandarin"),
        ("32277", "Jacksonville", "Arlington"),
    ],
    builder_names=[
        "Jacksonville Custom Homes LLC", "Coastal Bay Builders", "Riverside Construction Group",
        "First Coast Home Builders", "Duval Infill Homes", "Magnolia Park Builders",
        "Sunbelt Residential LLC", "Atlantic Shore Construction", "Northbank Builders Inc",
        "Cypress Creek Homes",
    ],
    zoning_codes=["RS-1", "RS-2", "RLD-60", "RLD-90", "RR-Acre"],
    permit_source=(
        "JaxEPICS (jaxepics.coj.net) -- City of Jacksonville/Duval County's permitting "
        "system. Publishes daily/monthly permit reports; exact export columns not "
        "confirmed against a live fetch (see README)."
    ),
    gis_source=(
        "Duval County GIS / JaxGIS (maps.coj.net), ArcGIS REST-based. Parcel cross-"
        "reference: duvalcad.org (Property Appraiser). maps.coj.net returned a "
        "maintenance page when last checked -- live endpoint not yet confirmed."
    ),
    permit_source_is_free=True,
    land_source=(
        "Florida DOR Property Tax Oversight Data Portal (floridarevenue.com/property/"
        "Pages/DataPortal.aspx) -- free, statewide, per Florida Statute 195.052: NAL "
        "(Name-Address-Legal, real property roll) + SDF (Sale Data File) per county. "
        "Confirmed these file types exist for every FL county; the actual download is "
        "a JS-rendered document library this session couldn't fetch through "
        "programmatically -- needs one manual download to confirm exact NAL/SDF column "
        "layout before a loader is built. Duval Property Appraiser's own site "
        "(duvalcountypropertyappraiser.org/tax-roll) also offers a direct tax-roll "
        "download as a backup."
    ),
)

BEXAR_TX = Market(
    key="BEXAR_TX",
    label="San Antonio, TX (Bexar County)",
    county="Bexar",
    state="TX",
    zips=[
        ("78201", "San Antonio", "Five Points/Beacon Hill"),
        ("78207", "San Antonio", "West Side"),
        ("78211", "San Antonio", "Highland Park"),
        ("78228", "San Antonio", "Las Palmas/West Side"),
        ("78237", "San Antonio", "West Side"),
        ("78242", "San Antonio", "Southwest Side"),
        ("78244", "San Antonio", "East Side"),
        ("78245", "San Antonio", "Southwest San Antonio"),
        ("78253", "San Antonio", "Far West Side"),
        ("78254", "San Antonio", "Alamo Ranch"),
        ("78258", "San Antonio", "Stone Oak"),
    ],
    builder_names=[
        "Alamo Heights Builders", "Stone Oak Custom Homes LLC", "Riverwalk Construction Group",
        "South Texas Infill Homes", "Helotes Creek Builders", "Live Oak Premier Homes",
        "Northside Construction Group", "Alamo Ranch Builders Inc", "Hill Country Home Builders",
        "Bexar Premier Construction",
    ],
    zoning_codes=["R-20", "R-6", "R-5", "R-4", "RM-4"],
    permit_source=(
        "LIVE AND WIRED UP (2026-06-24): City of San Antonio Open Data SA -- "
        "'permits_issued.csv' (data.sanantonio.gov, CKAN/S3-hosted, ~22MB, free, no "
        "login). live_permit_sources.py streams it and keeps 'Res New Building Permit' "
        "rows in market.zips -- confirmed real builders (CHESMAR HOMES, LENNAR HOMES, "
        "Habitat for Humanity of San Antonio, etc). DECLARED VALUATION is blank on every "
        "row of this permit type in the feed -- construction_value comes back as None "
        "('unknown'), not $0; matcher.py omits the value-range claim when that's the case. "
        "For unincorporated Bexar County itself, permits go through Bexar County Public "
        "Works (bexar.org/1463/Building-Permits) -- not covered by this feed."
    ),
    gis_source=(
        "Bexar County Open Data Portal (gis-bexar.opendata.arcgis.com), ArcGIS Hub -- "
        "free, parcel/zoning layers; also Bexar County Appraisal District GIS "
        "(bexarcountypropertyappraiser.org/gis-maps). Flood: San Antonio River Authority "
        "Floodplain Viewer (sariverauthority.org/maps-reports, FEMA NFHL-based). City "
        "GIS data: sanantonio.gov/GIS/GISData."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-23): Bexar County GIS Parcels ArcGIS REST layer "
        "(maps.bexar.org/arcgis/rest/services/Parcels/MapServer/0) -- free, queryable, "
        "no login. Filters on State_cd='C1', the Texas Comptroller's standard 'vacant "
        "lots and land tracts' classification, plus Houses='0'. Has owner name/mailing "
        "address/situs address/land value/acreage. Does NOT have sale-history fields "
        "(no last sale price/date, years owned, tax-delinquent status) -- those come "
        "back as 'unknown' from gis_land_sources.py rather than invented numbers. "
        "Replaces the PropStream-shaped mock for this market entirely when no "
        "LAND_CSV_PATH_BEXAR_TX override is set."
    ),
)

GWINNETT_GA = Market(
    key="GWINNETT_GA",
    label="Atlanta Suburbs, GA (Gwinnett County)",
    county="Gwinnett",
    state="GA",
    zips=[
        ("30017", "Auburn", "Auburn"),
        ("30019", "Dacula", "Dacula"),
        ("30024", "Suwanee", "Suwanee"),
        ("30039", "Snellville", "Snellville"),
        ("30043", "Lawrenceville", "Lawrenceville"),
        ("30044", "Lawrenceville", "Lawrenceville"),
        ("30045", "Lawrenceville", "Lawrenceville"),
        ("30047", "Lilburn", "Lilburn"),
        ("30071", "Norcross", "Norcross"),
        ("30092", "Peachtree Corners", "Peachtree Corners"),
        ("30096", "Duluth", "Duluth"),
    ],
    builder_names=[
        "Peachtree Corners Builders", "Sugarloaf Custom Homes LLC", "Lawrenceville Construction Group",
        "Lilburn Infill Homes", "Suwanee Premier Homes", "Norcross Builders Inc",
        "Duluth Construction Group", "Dacula Custom Homes", "Snellville Builders LLC",
        "Gwinnett Premier Construction",
    ],
    zoning_codes=["R-100", "R-75", "R-60", "RSL", "RTH"],
    permit_source=(
        "Gwinnett County Dept. of Planning & Development publishes weekly 'Building "
        "Permits Issued' reports (gwinnettcounty.com/.../building-permits-issued) -- "
        "free, but PDF format, not a structured CSV (column layout would need to be "
        "confirmed/parsed once live). Individual permits are also searchable for free "
        "via the county's live Citizen Access/Accela portal (aca-prod.accela.com/GWINNETT)."
    ),
    gis_source=(
        "Gwinnett County Open Data Portal (gcgis-gwinnettcountyga.hub.arcgis.com), "
        "ArcGIS Hub -- free, includes a Zoning layer. Parcel/property lookup: GIS Data "
        "Browser (gis.gwinnettcounty.com). Flood: Gwinnett Flood Information Portal "
        "(gwinnettfloodplain.com, FEMA + county data)."
    ),
    permit_source_is_free=True,
    land_source=(
        "Gwinnett County Assessor 'Property Ownership Database' (gwinnettcounty.com -> "
        "County Administrator -> Assessor -> Property Ownership Database) -- free, "
        "quarterly ZIP of Excel files with owner name/mailing address/assessed value, "
        "per the county's own page. The direct download link returned an HTML page "
        "instead of the ZIP when fetched programmatically this session (likely needs "
        "a real browser session/cookies) -- needs one manual download to confirm exact "
        "column layout before a loader is built."
    ),
)

WILLIAMSON_TN = Market(
    key="WILLIAMSON_TN",
    label="Nashville Suburbs, TN (Williamson County)",
    county="Williamson",
    state="TN",
    zips=[
        ("37064", "Franklin", "Franklin"),
        ("37067", "Franklin", "Cool Springs"),
        ("37069", "Franklin", "Berry Farms"),
        ("37027", "Brentwood", "Brentwood"),
        ("37046", "College Grove", "College Grove"),
        ("37062", "Fairview", "Fairview"),
        ("37135", "Nolensville", "Nolensville"),
        ("37174", "Spring Hill", "Spring Hill"),
        ("37179", "Thompson's Station", "Thompson's Station"),
    ],
    builder_names=[
        "Cool Springs Builders", "Berry Farms Custom Homes LLC", "Brentwood Construction Group",
        "Nolensville Infill Homes", "Thompson's Station Premier Homes", "Westhaven Builders Inc",
        "Fairview Construction Group", "College Grove Custom Homes", "Spring Hill Builders LLC",
        "Williamson Premier Construction",
    ],
    zoning_codes=["R-1", "R-2", "RR", "AG", "PUD"],
    permit_source=(
        "NOT CONFIRMED as a free bulk export, unlike the other three markets -- flagging "
        "honestly rather than guessing. Williamson County's Building Codes Dept "
        "(williamsoncounty-tn.gov/393/Permits) only permits unincorporated county land; "
        "its 'Electronic Plan Review System' (williamson.idtplans.com/secure) reads like "
        "a submission portal, not a public search/report tool. Most growth here is "
        "inside incorporated cities (Franklin, Brentwood, Spring Hill, Nolensville) that "
        "permit separately through their own portals (e.g. Franklin's permit portal) -- "
        "going live in this market means wiring up several city portals, or a paid permit "
        "data vendor, not one county export. Real next step, not a code change."
    ),
    gis_source=(
        "Williamson County GIS (arcgis2.williamson-tn.org), ArcGIS/Geocortex-based -- "
        "free, includes a zoning district viewer. A live ArcGIS REST flood layer was "
        "confirmed reachable: arcgis2.williamsoncounty-tn.gov/arcgis/rest/services/"
        "New_Flood_Zones/MapServer. Parcels: Property Assessor search "
        "(inigo.williamson-tn.org/property_search)."
    ),
    # False until a confirmed free bulk/per-city source is wired up -- run.py
    # skips this market by default rather than quietly running on mock data
    # implying a free feed that doesn't actually exist yet.
    permit_source_is_free=False,
    land_source="Not yet researched -- this market is already skipped on the permit gate above.",
)

MARKETS = [JACKSONVILLE_FL, BEXAR_TX, GWINNETT_GA, WILLIAMSON_TN]


@dataclass
class CandidateMarket:
    """A vetted, not-yet-active backup market -- suggestion fodder for the
    low-inventory alert in run.py/emailer.py. No mock-data fields (zips,
    builder_names, zoning_codes) because these never run the pipeline until
    promoted to a real Market; they're here purely as researched, confirmed-
    free options to expand into."""
    label: str
    county: str
    state: str
    permit_source: str
    gis_source: str
    permit_source_is_free: bool
    note: str  # why this is a reasonable next market, and any caveats


CANDIDATE_MARKETS = [
    CandidateMarket(
        label="Austin, TX (Travis County)",
        county="Travis",
        state="TX",
        permit_source=(
            "City of Austin Open Data (data.austintexas.gov) -- Socrata-based, free, "
            "multiple ready CSV exports ('Issued Construction Permits', 'Issued "
            "Building Permits', 'Building Permits Issued since 2010'), BLDS-compliant "
            "(standardized building-permit schema). Best-confirmed permit source of "
            "any market researched so far, active or candidate."
        ),
        gis_source=(
            "Travis County Open Data Portal / TNR GeoHub (tnr-traviscountytx.opendata."
            "arcgis.com), ArcGIS Hub -- free, has Parcels, Zoning Districts, and a "
            "Flood Risk web map layer."
        ),
        permit_source_is_free=True,
        note="Strongest candidate -- a real Socrata CSV with a standardized schema beats every other market's permit source.",
    ),
    CandidateMarket(
        label="Raleigh, NC (Wake County)",
        county="Wake",
        state="NC",
        permit_source=(
            "Wake County Open Data (data-wake.opendata.arcgis.com / data.wake.gov) -- "
            "ArcGIS Hub, free, has a 'Building Permits' dataset (also mirrored at "
            "data.raleighnc.gov) downloadable as CSV/GeoJSON."
        ),
        gis_source=(
            "iMAPS (maps.raleighnc.gov/iMAPS), the joint Raleigh/Wake County GIS viewer "
            "-- free, includes Property/Tax Parcels, Zoning, and flood-related layers. "
            "Same data also in the Wake County Open Data Portal above."
        ),
        permit_source_is_free=True,
        note="Clean ArcGIS Hub CSV like Gwinnett's GIS data, but for permits too -- no PDF-parsing needed.",
    ),
    CandidateMarket(
        label="Charlotte, NC (Mecklenburg County)",
        county="Mecklenburg",
        state="NC",
        permit_source=(
            "Mecklenburg County Code Enforcement publishes 'Building Permits Issued "
            "Daily' via a public Power BI report (Mecklenburg Open Data), free but not "
            "a one-click CSV -- same caveat tier as Gwinnett's PDF reports. County is "
            "also mid-migration to Accela (WebPermit) for permit search/applications."
        ),
        gis_source=(
            "Mecklenburg County GIS / POLARIS 3G (polaris3g.mecklenburgcountync.gov) -- "
            "free, explicitly has zoning and floodplain overlays. GeoPortal "
            "(mcmap.org/geoportal) for parcel/address lookup."
        ),
        permit_source_is_free=True,
        note="Free but the permit export format needs more legwork than Austin/Wake before it's truly wire-up-ready.",
    ),
]
