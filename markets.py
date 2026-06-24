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
    Live-wired for all 4 active markets in gis_land_sources.py as of
    2026-06-24.

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
    # True only for markets where the user already has a direct, known buyer
    # and doesn't need permit-based builder discovery there at all (Medina/
    # Atascosa, added 2026-06-24). run.py skips permit loading, builder
    # aggregation, and lead-to-builder matching entirely for these -- every
    # fresh land lead becomes a "deal" on its own -- and bypasses the
    # free-permit-source gate below (there's no permit step to gate).
    # emailer.py renders these as a bare-facts property card instead of the
    # usual matched-buyer pitch+contract card.
    skip_builder_matching: bool = False


TRAVIS_TX = Market(
    key="TRAVIS_TX",
    label="Austin, TX (Travis County)",
    county="Travis",
    state="TX",
    # Replaced Jacksonville/Duval 2026-06-24 -- Duval's land side was real
    # (Florida's statewide FL_Parcels service) but its permit side never
    # found a live source (JaxEPICS is an Azure-AD-secured Angular SPA with
    # no public API, confirmed by inspecting its JS bundle; the city's own
    # stats pages just point back to it). Austin/Travis has both sides
    # confirmed live and free -- see permit_source/land_source below.
    zips=[
        ("78745", "Austin", "South Austin/Galindo"),
        ("78704", "Austin", "South Congress/Travis Heights"),
        ("78723", "Austin", "Mueller/Windsor Park"),
        ("78721", "Austin", "East Austin/MLK"),
        ("78744", "Austin", "Southeast Austin/Montopolis"),
        ("78754", "Austin", "Northeast Austin/Springdale"),
        ("78617", "Austin", "Del Valle"),
        ("78753", "Austin", "North Austin/Coronado Hills"),
        ("78758", "Austin", "North Austin/Domain Area"),
        ("78759", "Austin", "Northwest Hills"),
    ],
    builder_names=[
        "South Congress Builders", "East Austin Infill Homes", "Hill Country Custom Homes LLC",
        "Mueller Park Construction Group", "Barton Springs Builders", "Domain Premier Homes",
        "Travis Heights Construction", "Lone Star Infill Builders", "Zilker Park Homes",
        "Austin Premier Construction",
    ],
    zoning_codes=["SF-1", "SF-2", "SF-3", "SF-4A", "SF-6"],
    permit_source=(
        "LIVE AND WIRED UP (2026-06-24): City of Austin's 'Issued Construction Permits' "
        "Socrata dataset (data.austintexas.gov/resource/3syk-w9eu.json) -- free, no "
        "login, queryable via SoQL. Filters on permittype='BP' (the main building "
        "permit, not electrical/mechanical sub-permits), permit_class='R- 101 Single "
        "Family Houses', work_class='New'. Confirmed real, current builders: "
        "Brookfield Residential Texas Homes LLC, Tri Pointe Homes, Trophy Signature "
        "Homes, Sanctuary Builders of Texas Inc, etc. (permits issued into June 2026). "
        "total_job_valuation/building_valuation are unpopulated on these records (same "
        "'unknown, not zero' treatment as Bexar) -- total_new_add_sqft is present but "
        "unused since Permit has no square-footage field."
    ),
    gis_source=(
        "Travis County TNR GeoHub (tnr-traviscountytx.hub.arcgis.com / "
        "tnr-traviscountytx.opendata.arcgis.com), ArcGIS Hub -- free, Parcels/Zoning "
        "Districts/Flood Risk layers. Official TCAD parcel layer also exists "
        "(services.arcgis.com/0L95CJ0VTaxqcmED/.../EXTERNAL_tcad_parcel) but has no "
        "owner field -- see land_source below for the one that does."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-24): 'TCAD_Parcels_Dec_2025' ArcGIS Feature "
        "Service (services1.arcgis.com/HGcSYZ5bvjRswoCb/.../TCAD_Parcels_Dec_2025/"
        "FeatureServer/0) -- free, queryable, no login. A more complete working copy "
        "of Travis Central Appraisal District's parcel data than the 'official' "
        "EXTERNAL_tcad_parcel service (which has land value but no owner field at "
        "all). Filters on land_type_desc='VACANT LOT' AND land_homesite_val>0 (excludes "
        "HOA/common-area slivers) AND py_owner_name NOT LIKE 'CITY OF%'/'TRAVIS COUNTY%' "
        "(land_homesite_val alone didn't exclude government-owned ROW slivers, which "
        "otherwise dominate small samples -- confirmed live). Has owner name/mailing "
        "address/situs address/acreage/value. deed_date exists but was unpopulated on "
        "every record checked, and there's no sale-price field at all on this layer -- "
        "sale history comes back 'unknown', same as Bexar."
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
        "LIVE AND WIRED UP (2026-06-24): Gwinnett County Dept. of Planning & "
        "Development's weekly 'Building Permits Issued' PDF report "
        "(gwinnettcounty.com/.../building-permits-issued) -- free, no login, but PDF "
        "not CSV/API, parsed with pdfplumber (this project's first non-stdlib "
        "dependency -- see live_permit_sources.py's module docstring). The report's "
        "URL slug isn't consistently formatted week to week, so the loader discovers "
        "the latest report from the listing page rather than guessing a URL. Filters "
        "on CENSUS CODE description 'Single Family - Detatched' [sic] / 'Single "
        "Family - Attached'. Confirmed real, current builders: TAYLOR MORRISON OF "
        "GEORGIA, STANLEY MARTIN HOMES, PULTE HOME COMPANY, etc. No property zip "
        "field in the report (only a city name) -- zip is recovered via market.zips' "
        "city list, so a permit in a Gwinnett city outside that list is skipped. "
        "Individual permits are also searchable live via the county's Citizen Access/"
        "Accela portal (aca-prod.accela.com/GWINNETT) as an alternative, not used here."
    ),
    gis_source=(
        "Gwinnett County Open Data Portal (gcgis-gwinnettcountyga.hub.arcgis.com), "
        "ArcGIS Hub -- free, includes a Zoning layer. Parcel/property lookup: GIS Data "
        "Browser (gis.gwinnettcounty.com). Flood: Gwinnett Flood Information Portal "
        "(gwinnettfloodplain.com, FEMA + county data)."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-24): 'Property and Tax Table', layer 3 of the same "
        "Property_and_Tax ArcGIS Feature Service whose layer 0 (cadastral-only parcel "
        "boundaries, no owner/value) was checked and rejected earlier -- the owner/"
        "value table was sitting on the same service the whole time, just a different "
        "layer index. Filters on PROPCLAS='100', Gwinnett's own 'Residential Vacant' "
        "property class code. No sale-history fields in this table -- 'unknown' from "
        "gis_land_sources.py, same as Bexar. (The quarterly Assessor ZIP export "
        "mentioned in earlier research is no longer needed now that this live path "
        "works, but is still a real, free fallback if this service ever goes dark.)"
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
    land_source=(
        "LIVE AND WIRED UP (2026-06-24): Williamson County's own GIS parcels attribute "
        "table (arcgis2.williamsoncounty-tn.gov, IDT/DataPull MapServer layer 4) -- "
        "free, HTTP only (this government server's HTTPS cert doesn't validate; the "
        "data is public record, low risk over plain HTTP). No explicit land-use code "
        "field, so vacant land is inferred as imp_assess<=0 AND total_asse>0 (no "
        "improvement value). Real caveat: no usable property-zip-code field exists on "
        "this table (own_zip is the owner's mailing zip, not the parcel's), and CITY "
        "is a numeric code with no resolvable lookup -- every lead gets market.zips[0] "
        "as a placeholder zip/city. Wrong in that one detail, but this market doesn't "
        "run yet anyway (still gated off on the permit side above) -- worth solving "
        "properly (likely via reverse-geocoding the parcel geometry) before that gate "
        "is ever lifted."
    ),
)

MEDINA_TX = Market(
    key="MEDINA_TX",
    label="Medina County, TX (Natalia Area)",
    county="Medina",
    state="TX",
    # Added 2026-06-24: user has a direct, known buyer in this market already
    # and asked for real land leads only -- see skip_builder_matching below.
    zips=[
        ("78059", "Natalia", "Natalia"),
        ("78016", "Devine", "Devine"),
        ("78039", "Lacoste", "Lacoste"),
        ("78009", "Castroville", "Castroville"),
        ("78861", "Hondo", "Hondo"),
    ],
    # Never used -- skip_builder_matching=True means mock permits/builders
    # are never generated for this market either.
    builder_names=[],
    zoning_codes=["R-1", "R-2", "RR", "AG", "C-1"],
    permit_source=(
        "NOT CONFIRMED as a free bulk/API source, despite checking the county "
        "itself and every incorporated city in it (Natalia, Devine, Hondo, "
        "Castroville, LaCoste) -- every one is application-only (email/PDF/"
        "in-person, e.g. Devine's iWORQ portal requires a permit number to "
        "search, not browsable), no searchable issued-permit list, and an "
        "ArcGIS Online search for a 'permits' feature service under any of "
        "these town names found nothing. Same dead end as Williamson. Moot "
        "for this market anyway -- skip_builder_matching=True because the "
        "user already has a direct buyer here and doesn't need permit-based "
        "buyer discovery."
    ),
    gis_source=(
        "Medina CAD's own parcel data (medinacad.org, GIS mirror at "
        "gis.bisconsultants.com/medinacad) -- same source as land_source "
        "below. This vendor doesn't separate out a distinct zoning/flood "
        "viewer; FEMA's National Flood Hazard Layer (msc.fema.gov) covers "
        "flood risk for any TX county without its own viewer."
    ),
    permit_source_is_free=False,
    land_source=(
        "LIVE AND WIRED UP (2026-06-24): Medina CAD's parcel data, hosted on "
        "ArcGIS Online by BIS Consulting (services6.arcgis.com/"
        "j94FvPaik4etwHFk/.../MedinaCADWebService/FeatureServer/0) -- free, "
        "queryable, no login. No explicit land-use/state-class code field "
        "exists on this schema at all (unlike Bexar/Travis/Gwinnett) -- "
        "vacant land is inferred the same way Williamson's was: "
        "imprv_val<=0 AND land_val>0. Has owner name (file_as_name)/mailing "
        "address/situs address/land value/acreage/Deed_Date -- but no "
        "sale-price field at all, so sale history is unconditionally "
        "'unknown', same treatment as Travis. Government/school-district-"
        "owned parcels ('CITY OF ...'/'... ISD') and 'MULTIPLE OWNERS' rows "
        "(no single contactable owner) are confirmed live in this data and "
        "explicitly excluded. situs_zip is unreliable on this schema "
        "(confirmed live malformed values like '778059', '7/8065', 'X', and "
        "plain nulls) -- leads are scoped and zip-assigned by situs_city "
        "instead (matched against this Market's zips list; Medina CAD spells "
        "Lacoste as 'LA COSTE', handled via an alias in gis_land_sources.py). "
        "Acreage capped at 20 here (vs. the 2-acre infill ceiling used in the "
        "four urban/suburban markets) -- rural lot sizes are naturally "
        "bigger; this still excludes the largest ranch tracts."
    ),
    skip_builder_matching=True,
)

ATASCOSA_TX = Market(
    key="ATASCOSA_TX",
    label="Atascosa County, TX (Poteet Area)",
    county="Atascosa",
    state="TX",
    # Added 2026-06-24, same reasoning as Medina above -- user has a direct,
    # known buyer here too.
    zips=[
        ("78065", "Poteet", "Poteet"),
        ("78026", "Jourdanton", "Jourdanton"),
        ("78064", "Pleasanton", "Pleasanton"),
    ],
    builder_names=[],
    zoning_codes=["R-1", "R-2", "RR", "AG", "C-1"],
    permit_source=(
        "NOT CONFIRMED as a free bulk/API source, despite checking the "
        "county itself (Atascosa County Fire Marshal's office handles "
        "permits for unincorporated land, application-only, voluntary for "
        "residential) and every incorporated city in it (Poteet, "
        "Jourdanton, Pleasanton) -- all application-only (email/PDF/in-"
        "person), no searchable issued-permit list, and an ArcGIS Online "
        "search for a 'permits' feature service under any of these town "
        "names found nothing. Same dead end as Williamson/Medina. Moot for "
        "this market anyway -- skip_builder_matching=True, user already has "
        "a direct buyer here."
    ),
    gis_source=(
        "Atascosa CAD's own parcel data (esearch.atascosacad.com, GIS "
        "mirror at gis.bisconsultants.com) -- same source as land_source "
        "below. No distinct zoning/flood viewer; FEMA's National Flood "
        "Hazard Layer (msc.fema.gov) covers flood risk here."
    ),
    permit_source_is_free=False,
    land_source=(
        "LIVE AND WIRED UP (2026-06-24): Atascosa CAD's parcel data, hosted "
        "on ArcGIS Online by the same vendor as Medina CAD above "
        "(services8.arcgis.com/q1dyPay4QViMab9g/.../AtascosaCADWebService/"
        "FeatureServer/0), byte-identical schema -- free, queryable, no "
        "login. Same vacant-land inference (imprv_val<=0 AND land_val>0), "
        "same 'unknown' sale-history treatment (no sale-price field), same "
        "'CITY OF .../... ISD'/'MULTIPLE OWNERS' exclusions, same "
        "situs_zip-is-unreliable workaround (scoped/zip-assigned by "
        "situs_city instead), and same 20-acre rural ceiling as Medina -- "
        "see that Market's land_source for the full detail, all confirmed "
        "live against this county's real data too."
    ),
    skip_builder_matching=True,
)

MARKETS = [TRAVIS_TX, BEXAR_TX, GWINNETT_GA, WILLIAMSON_TN, MEDINA_TX, ATASCOSA_TX]


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
