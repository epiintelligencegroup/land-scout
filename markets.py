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
    "NC": "North Carolina",
    "AZ": "Arizona",
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
    # True for markets whose land loader applies the full lead-quality filter
    # stack added 2026-06-25 (Mecklenburg/Maricopa/Davidson/Wake): individual
    # owner only, vacant only, real street number required, FEMA Zone X only
    # (unshaded), no NWI wetlands. Older markets keep their original filters
    # (no flood/wetlands filtering -- that enrichment is still mock for them)
    # unless/until asked to upgrade.
    full_lead_quality_filter: bool = False


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
        "bigger; this still excludes the largest ranch tracts. Owners "
        "matching NON_INDIVIDUAL_OWNER_PATTERNS in gis_land_sources.py "
        "(LLC/INC/CORP/HOMES/CONSTRUCTION/BUILDERS/REALTY/TRUST/ESTATE/LP/"
        "LTD/HOLDINGS/CO, added 2026-06-24 after live leads here came back "
        "owned by PERRY HOMES/DAVID WEEKLEY HOMES) are excluded too -- user "
        "wants individual-person-owned land only."
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
        "NON_INDIVIDUAL_OWNER_PATTERNS exclusion (LLC/INC/CORP/HOMES/etc.), "
        "same situs_zip-is-unreliable workaround (scoped/zip-assigned by "
        "situs_city instead), and same 20-acre rural ceiling as Medina -- "
        "see that Market's land_source for the full detail, all confirmed "
        "live against this county's real data too."
    ),
    skip_builder_matching=True,
)

MECKLENBURG_NC = Market(
    key="MECKLENBURG_NC",
    label="Charlotte, NC (Mecklenburg County)",
    county="Mecklenburg",
    state="NC",
    # Added 2026-06-25 -- full lead-quality filter stack (individual owner,
    # vacant, real address, Zone X/no wetlands). Both land and permits are
    # fully real and county-wide.
    zips=[
        ("28202", "Charlotte", "Uptown/Center City"),
        ("28203", "Charlotte", "South End/Dilworth"),
        ("28269", "Charlotte", "University City/North Charlotte"),
        ("28278", "Charlotte", "Steele Creek"),
        ("28213", "Charlotte", "East Charlotte/Eastfield"),
        ("28078", "Huntersville", "Huntersville"),
        ("28031", "Cornelius", "Cornelius/Lake Norman"),
        ("28036", "Davidson", "Davidson"),
        ("28105", "Matthews", "Matthews"),
        ("28227", "Mint Hill", "Mint Hill"),
        ("28134", "Pineville", "Pineville"),
    ],
    builder_names=[
        "Queen City Custom Homes", "Lake Norman Builders LLC", "South End Infill Homes",
        "Steele Creek Construction Group", "Uptown Premier Builders", "Matthews Custom Homes",
        "Cornelius Lakeside Builders", "Mint Hill Construction Co", "Davidson Heritage Homes",
        "Charlotte Premier Construction",
    ],
    zoning_codes=["R-3", "R-4", "R-5", "R-8", "UR-1"],
    permit_source=(
        "LIVE AND WIRED UP (2026-06-25): Mecklenburg County's own "
        "'BuildingPermits' ArcGIS Feature Service (meckgis.mecklenburgcountync.gov/"
        "server/rest/services/BuildingPermits/FeatureServer/0) -- free, no login, "
        "countywide (not city-of-Charlotte-only). Filters permittype='One/Two "
        "Family' AND permitdesc LIKE '%SF Dwelling Detached%' -- worktype='New' "
        "alone is too broad and catches sheds/decks/garages. 'ownname' acts as "
        "the builder/developer field for new spec-home construction (no separate "
        "explicit contractor-name field, but functions as one here). Confirmed "
        "real, current builders (issued into June 2026): Northway Homes 2025 LLC, "
        "TRUE HOMES USA, EASTWOOD CONSTRUCTION, CalAtlantic Group/Lennar, "
        "Northwood Ravin. projadd has inconsistent whitespace padding -- stripped "
        "in the loader."
    ),
    gis_source=(
        "Same meckgis.mecklenburgcountync.gov ArcGIS Server as land_source/"
        "permit_source above -- Mecklenburg County's GIS hosts parcels, "
        "permits, and (per the county's open data catalog) zoning/floodplain "
        "layers under the same server. Flood/wetlands filtering for this "
        "market uses the nationwide FEMA NFHL/USFWS NWI services in "
        "flood_wetlands.py instead of a county-specific layer, for consistency "
        "with the other 3 new markets."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-25): Mecklenburg County's 'TaxParcel_camadata' "
        "ArcGIS Feature Service (meckgis.mecklenburgcountync.gov/server/rest/"
        "services/TaxParcel_camadata/FeatureServer/0) -- free, no login. Has "
        "separate street-number/street-name fields (a sibling layer, "
        "TaxParcel_Camaownershipvalues, only has a single concatenated situs "
        "string -- avoid it). Filters vacorimprov='VAC' AND totalbldgval<=0 -- "
        "vacorimprov alone is NOT reliable: confirmed live 9,720 of 26,035 "
        "'VAC'-coded parcels (37%) actually carry a positive building value, "
        "including one with a $1.18M improvement still coded vacant. "
        "Government-owned parcels (CITY OF/COUNTY) and non-buildable land-use "
        "descriptions (common areas, ROW slivers, wasteland/gullies) are also "
        "excluded. zipcode mixes 5-digit and ZIP+4 formats -- normalized in "
        "the loader."
    ),
    full_lead_quality_filter=True,
)

MARICOPA_AZ = Market(
    key="MARICOPA_AZ",
    label="Phoenix Metro, AZ (Mesa/Maricopa County)",
    county="Maricopa",
    state="AZ",
    # Added 2026-06-25. Land data covers all of Maricopa County, but the
    # only confirmed-free permit source with a real builder-name field is
    # the City of Mesa's own dataset -- City of Phoenix's permit layers have
    # no clean new-SFR isolation and Gilbert's has no contractor field at
    # all. Scoped to Mesa zips only so both sides of every match are real,
    # same pattern as Austin/Travis being scoped to Austin city zips rather
    # than all of Travis County.
    zips=[
        ("85201", "Mesa", "Downtown Mesa"),
        ("85202", "Mesa", "West Mesa"),
        ("85203", "Mesa", "North Mesa"),
        ("85204", "Mesa", "Mesa"),
        ("85205", "Mesa", "East Mesa"),
        ("85206", "Mesa", "East Mesa"),
        ("85207", "Mesa", "East Mesa"),
        ("85208", "Mesa", "East Mesa"),
        ("85209", "Mesa", "Mesa"),
        ("85210", "Mesa", "South Mesa"),
        ("85212", "Mesa", "Eastmark/Southeast Mesa"),
        ("85213", "Mesa", "East Mesa"),
    ],
    builder_names=[
        "Sonoran Custom Homes", "Eastmark Builders LLC", "Red Mountain Construction Group",
        "Superstition Premier Homes", "Desert Sky Builders Inc", "Val Vista Custom Homes",
        "East Mesa Construction Co", "Falcon Field Builders", "Riverview Premier Homes",
        "Mesa Heritage Construction",
    ],
    zoning_codes=["RS-7", "RS-9", "RS-15", "R1-6", "R1-9"],
    permit_source=(
        "LIVE AND WIRED UP (2026-06-25): City of Mesa's 'Building Permits' "
        "Socrata dataset (data.mesaaz.gov/resource/dzpk-hxfb.json) -- free, no "
        "login, live-updated daily (confirmed permits issued the same day as "
        "the research session). Filters type_of_work='Single Family (Detached)' "
        "AND status='Issued'. Has a real contractor_name field (unlike Phoenix's "
        "or Gilbert's permit layers). Confirmed real, current builders: Brighton "
        "Homes LLC, Taylor Morrison, Pulte, Meritage, Lennar, Shea Homes. An "
        "older/retired Mesa Socrata resource ID (2gkz-7z4f) is dead-ended at Feb "
        "2018 -- don't use it. City of Phoenix's own permit data has no clean "
        "new-SFR isolation (its CSV is annual aggregates only, its ArcGIS "
        "Permits layer is dominated by sub-trade permits); Gilbert's ArcGIS "
        "permit table (maps.gilbertaz.gov, EnergovPermitData) is current but has "
        "NO contractor/builder field at all, only a subdivision project name -- "
        "checked both, neither is usable for buyer discovery, hence the Mesa-only "
        "market scope."
    ),
    gis_source=(
        "gis.maricopa.gov (county) and Mesa's own GIS for zoning; flood/wetlands "
        "filtering for this market uses the nationwide FEMA NFHL/USFWS NWI "
        "services in flood_wetlands.py instead."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-25): Maricopa County Assessor's 'Parcel' "
        "layer (gis.maricopa.gov/arcgis/rest/services/IndividualService/Parcel/"
        "MapServer/1) -- free, no login, 1.76M parcels countywide, scoped to "
        "Mesa zips here. Has dedicated Longitude_DD/Latitude_DD fields already "
        "in decimal degrees (no Web Mercator conversion needed for the flood/"
        "wetlands filter). Filters PropertyUseCode IN ('0011','0012') (Vacant "
        "Residential Urban Subdivided/Non-Subdivided) AND ImprovementFullCashValue"
        "<=0 -- confirmed live this combination is needed (the use-code alone "
        "isn't sufficient cross-check, same lesson as every other market). "
        "Government/municipal-owned vacant parcels (codes 9400/9405/9700/9705) "
        "excluded. The Assessor's documented token-auth REST API "
        "(mcassessor.maricopa.gov) requires manual registration -- not used; "
        "the anonymous MapServer above needs no auth and has everything required."
    ),
    full_lead_quality_filter=True,
)

DAVIDSON_TN = Market(
    key="DAVIDSON_TN",
    label="Nashville, TN (Davidson County)",
    county="Davidson",
    state="TN",
    # Added 2026-06-25 -- Nashville PROPER (consolidated Metro government),
    # distinct from Williamson County (Nashville suburbs, skipped market --
    # no confirmed free permit source there). Both land and permits are
    # fully real and county-wide here.
    zips=[
        ("37013", "Antioch", "Antioch"),
        ("37207", "Nashville", "North Nashville"),
        ("37208", "Nashville", "North Nashville/Germantown"),
        ("37206", "Nashville", "East Nashville"),
        ("37076", "Hermitage", "Hermitage"),
        ("37115", "Madison", "Madison"),
        ("37214", "Nashville", "Donelson"),
        ("37221", "Nashville", "Bellevue"),
        ("37138", "Old Hickory", "Old Hickory"),
        ("37211", "Nashville", "South Nashville/Antioch border"),
        ("37189", "Whites Creek", "Whites Creek"),
        ("37072", "Goodlettsville", "Goodlettsville (Davidson portion)"),
    ],
    builder_names=[
        "Music City Custom Homes", "East Nashville Infill Builders", "Antioch Premier Homes LLC",
        "Donelson Construction Group", "Hermitage Heritage Homes", "Bellevue Custom Builders",
        "Madison Premier Construction", "Old Hickory Builders Inc", "Germantown Infill Homes",
        "Nashville Metro Construction",
    ],
    zoning_codes=["RS5", "RS7.5", "RS10", "RS15", "R6"],
    permit_source=(
        "LIVE AND WIRED UP (2026-06-25): Metro Nashville's "
        "'Building_Permits_Issued_2' ArcGIS Feature Service "
        "(services2.arcgis.com/HdTo6HJqh92wn4D8/arcgis/rest/services/"
        "Building_Permits_Issued_2/FeatureServer/0) -- free, no login. "
        "data.nashville.gov's classic Socrata portal is defunct (redirects to "
        "an 'ArcGIS Hub Unsupported' page) -- Nashville migrated permits to "
        "ArcGIS Online under org HdTo6HJqh92wn4D8. Filters "
        "Permit_Type_Description='Building Residential - New' AND "
        "Permit_Subtype_Description='Single Family Residence'. The 'Contact' "
        "field is the builder name but format is inconsistent (some "
        "last-name-first, e.g. 'HORTON, D R INC' for D.R. Horton) -- match with "
        "LIKE '%HORTON%' not the full company name. Confirmed real, current "
        "builders (issued into June 2026): Meritage Homes of Tennessee Inc, "
        "Regent Homes, Goodall Homes, Beazer Homes LLC, Ole South Properties "
        "Inc, NVR/Ryan Homes, Lennar Homes of Tennessee LLC."
    ),
    gis_source=(
        "maps.nashville.gov (Metro Nashville's own GIS) hosts parcels/zoning; "
        "flood/wetlands filtering for this market uses the nationwide FEMA "
        "NFHL/USFWS NWI services in flood_wetlands.py instead."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-25): Metro Nashville's 'Parcels' layer "
        "(maps.nashville.gov/arcgis/rest/services/Cadastral/Parcels/MapServer/0, "
        "also hosted at services2.arcgis.com/HdTo6HJqh92wn4D8/.../Parcels_view, "
        "updated daily) -- free, no login. Filters LUCode IN ('010','020','030',"
        "'070','080','80M','090') (vacant residential/commercial/multi-family/"
        "industrial/rural/exempt) AND ImprAppr<=0 -- confirmed live 16% of "
        "LUCode='010' (vacant residential) parcels actually carry a positive "
        "improvement value, same lesson as every other market in this project. "
        "PropHouse (street number) is a real separate field. No sale-price field "
        "issue here -- LandAppr/ImprAppr/TotlAppr are all populated and split "
        "cleanly."
    ),
    full_lead_quality_filter=True,
)

WAKE_NC = Market(
    key="WAKE_NC",
    label="Raleigh, NC (Wake County)",
    county="Wake",
    state="NC",
    # Added 2026-06-25 -- promoted from CANDIDATE_MARKETS (see below) after
    # live verification. Land data covers all of Wake County, but the only
    # confirmed-free permit source with real builder names is the City of
    # Raleigh's own open data -- Wake County's own permits layer has null
    # contractor/issue-date fields on every record, and no other town in the
    # county (Cary, Apex, Wake Forest, Garner, Fuquay-Varina, Holly Springs,
    # Knightdale, Morrisville) publishes permit data at all. Scoped to
    # Raleigh zips only so both sides of every match are real, same pattern
    # as Austin/Travis and Mesa/Maricopa above.
    zips=[
        ("27601", "Raleigh", "Downtown Raleigh"),
        ("27610", "Raleigh", "Southeast Raleigh"),
        ("27616", "Raleigh", "North Raleigh"),
        ("27613", "Raleigh", "Northwest Raleigh"),
        ("27604", "Raleigh", "North Raleigh/Capital Blvd"),
        ("27606", "Raleigh", "West Raleigh/NCSU"),
        ("27607", "Raleigh", "West Raleigh/Cameron Village"),
        ("27609", "Raleigh", "North Raleigh/Six Forks"),
        ("27612", "Raleigh", "West Raleigh/Brier Creek"),
        ("27615", "Raleigh", "North Raleigh"),
        ("27603", "Raleigh", "South Raleigh"),
    ],
    builder_names=[
        "Oak City Custom Homes", "North Raleigh Builders LLC", "Cameron Village Infill Homes",
        "Brier Creek Construction Group", "Six Forks Premier Builders", "Southeast Raleigh Custom Homes",
        "NCSU Area Infill Builders", "Capital Blvd Construction Co", "Downtown Raleigh Builders Inc",
        "Raleigh Premier Construction",
    ],
    zoning_codes=["R-1", "R-2", "R-4", "R-6", "R-10"],
    permit_source=(
        "LIVE AND WIRED UP (2026-06-25): City of Raleigh's 'Building_Permits' "
        "ArcGIS Feature Service (services.arcgis.com/v400IkDOw1ad7Yad/arcgis/"
        "rest/services/Building_Permits/FeatureServer/0, siblings: "
        "Building_Permits_Past_31_Days/Issued_Past_180_Days/Pending/"
        "ADU_Building_Permits) -- free, no login, data current (most recent "
        "record issued the day before the research session). Filters "
        "workclassmapped='New' AND proposeduse LIKE '%SINGLE FAMILY%'. Has a "
        "real contractorcompanyname field. Confirmed real, current builders: "
        "Lennar Carolinas LLC, M/I Homes, Smith Douglas Homes, Davidson Homes, "
        "McKee Homes, Pulte. Wake County's OWN 'Building_Permits' layer "
        "(maps.wake.gov/arcgis/rest/services/Inspections/Building_Permits/"
        "MapServer/0, 195K records) exists but its CONTRACTOR and ISSUE_DATE "
        "fields are null on every record sampled -- explicitly described by the "
        "county as legacy/incomplete data, not usable. proposeduse/streettype "
        "strings have inconsistent leading whitespace/tabs -- stripped in the "
        "loader. jurisdiction is 100% Raleigh's FIPS place code across this "
        "whole feed -- it is Raleigh-city-only, hence the Raleigh-only zip scope. "
        "Honest caveat confirmed live 2026-06-25: genuinely NEW new-single-"
        "family-on-an-individually-owned-lot activity is thin right now -- "
        "only 4 of 100 sampled vacant Raleigh parcels were individually owned "
        "(most buildable infill is already builder/LLC-controlled), and the "
        "permit feed's last-31-days layer had only one new-SFH permit "
        "citywide (with no contractor name on it). Matches found will likely "
        "skew toward older (sometimes years-old) permit history rather than "
        "this week's activity -- expect low volume here, by the nature of "
        "this specific market right now, not a bug."
    ),
    gis_source=(
        "maps.wake.gov (Wake County's own GIS, also mirrored at "
        "maps.wakegov.com) hosts parcels/zoning; flood/wetlands filtering for "
        "this market uses the nationwide FEMA NFHL/USFWS NWI services in "
        "flood_wetlands.py instead."
    ),
    permit_source_is_free=True,
    land_source=(
        "LIVE AND WIRED UP (2026-06-25): Wake County's 'Parcels' layer "
        "(maps.wake.gov/arcgis/rest/services/Property/Parcels/MapServer/0) -- "
        "free, no login, countywide, scoped to Raleigh zips here. Filters "
        "LAND_CLASS='VAC' AND BLDG_VAL<=0. STNUM is a real numeric street-number "
        "field. ADDR2 (owner mailing) is an unparsed 'CITY ST ZIP' string, not "
        "separate fields -- parsed via regex in the loader. ZIPNUM (situs zip) "
        "is null on ~7% of vacant parcels -- those are skipped rather than "
        "guessed. BILLCLASS field distinguishes Individual vs Business owners "
        "directly (a useful cross-check alongside the project's own "
        "NON_INDIVIDUAL_OWNER_PATTERNS name-based filter)."
    ),
    full_lead_quality_filter=True,
)

MARKETS = [
    TRAVIS_TX, BEXAR_TX, GWINNETT_GA, WILLIAMSON_TN, MEDINA_TX, ATASCOSA_TX,
    MECKLENBURG_NC, MARICOPA_AZ, DAVIDSON_TN, WAKE_NC,
]


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
    # Wake/Raleigh and Mecklenburg/Charlotte promoted to active Markets above
    # on 2026-06-25, both fully real on both sides after live verification --
    # removed from this backup-suggestion pool. No researched backups remain
    # at the moment; the low-inventory alert in emailer.py just shows no
    # suggestions until new candidates are researched and added here.
]
