# Land Scout -- AI-assisted vacant land wholesaling pipeline

Runs four target markets every pass (see `markets.py`):

- **Jacksonville, FL** (Duval County)
- **San Antonio, TX** (Bexar County)
- **Atlanta Suburbs, GA** (Gwinnett County)
- **Nashville Suburbs, TN** (Williamson County) -- currently **skipped**, see below

For each market it finds vacant land leads, enriches each with zoning/flood/
wetland status, matches them to active local home builders (identified from
public permit activity), drafts a buyer pitch and two draft contracts per
match, and emails one combined digest -- sectioned by market -- to you to
forward.

**Every run fetches fresh, and never re-sends the same property.** There is
no caching layer anywhere -- every live source (`gis_land_sources.py`,
`live_permit_sources.py`) hits its real API on every single run, and mock
data is freshly randomized every run too. Separately, `sent_log.py` keeps a
permanent append-only record (`sent_properties.log`, gitignored) of every
property ever included in a successfully-sent digest; `run.py` filters
those out before drafting a pitch for them (saving the Anthropic call too),
so the same property is never sent twice across any number of runs or days.
The log only gets written to after a send actually succeeds.

**Free-permit-source gate:** `run.py` only runs a market if its permit
source is a confirmed free source (`Market.permit_source_is_free` in
`markets.py`), or you've explicitly pointed `PERMITS_CSV_PATH_<MARKET>` at a
real export yourself. This is deliberate -- the pipeline should never start
quietly relying on a paid permit feed. Right now that means **Williamson
County (Nashville suburbs) is skipped** every run (no confirmed free bulk
source -- see table below); it shows up in both the console output and the
digest email as a clearly-labeled skip, not a silent omission.

**Low-inventory alert:** if a market's matched-deal count in a given run
falls below `LOW_INVENTORY_THRESHOLD` (default 3), the digest gets a
prominent alert section naming the market and suggesting pre-vetted,
free-permit-friendly backup markets to expand into (`CANDIDATE_MARKETS` in
`markets.py` -- currently Austin/Travis TX, Raleigh/Wake NC, Charlotte/
Mecklenburg NC, all researched with the same rigor as the active 4). Adding
a suggested market still requires an actual code change (a new `Market`
entry with real zips/builder names, same as the original 4) -- the alert
tells you it's time, it doesn't do it automatically.

## Current state: land leads are fully real in all 4 markets; buyer data is real only for San Antonio

- **Land leads -- LIVE in all 4 markets as of 2026-06-24.** A per-market
  priority chain in `run.py`: real CSV override (`LAND_CSV_PATH_<MARKET>`)
  -> a live free GIS source registered in `gis_land_sources.py` -> mock
  data shaped like a PropStream export. Every market now has a live
  loader: Bexar queries its own ArcGIS Parcels layer; Jacksonville queries
  Florida's *statewide* parcels Feature Service (same DOR data the original
  plan wanted, just live instead of a static file download); Gwinnett
  queries the owner/value table sitting on the same ArcGIS service whose
  cadastral-only layer was checked and rejected earlier; Williamson queries
  its own GIS parcels table over HTTP (its HTTPS cert doesn't validate --
  low risk for public records). Williamson's loader has one known
  approximation (no real zip-code field exists on that table -- see
  `Market.land_source` in `markets.py`), but it doesn't matter yet since
  that market still won't run until its permit gate clears (see below).
- **Builder/buyer data -- still only real for Bexar/San Antonio.** Same
  priority chain, live loaders registered in `live_permit_sources.py`.
  San Antonio streams real new-construction permits (real builders: LENNAR
  HOMES, PERRY HOMES, CHESMAR HOMES, etc. -- 600+ permits from LENNAR
  alone). Jacksonville and Atlanta Suburbs are still mock on this side --
  JaxEPICS is a JS-rendered SPA with no discoverable API; Gwinnett's
  options are PDF reports or an Accela search portal, neither cleanly
  machine-readable. **This means Jacksonville and Atlanta Suburbs deals
  right now have a real property matched to a fictional buyer** -- same
  caveat as before, just shifted: the unreal half moved from land to
  permits for those two markets.
- **Zoning/flood/wetland enrichment** -- mocked in `enrichment.py`, with a
  plausible zoning-code vocabulary per market. Real GIS sources exist for
  all four counties (see below), but none of those endpoints have been
  wired up live yet -- see the TODOs in `enrichment.py`.
- **Comps** -- solved for free once real PropStream data is in use
  (PropStream provides comps natively); mocked for now same as everything
  else.

**Bexar (San Antonio) is the one market where both sides of a "matched
deal" are real** -- real owner/property from county GIS, real builder from
real permit activity. Every other market's matched-buyer side is still
fictional even where the property itself might be real; the digest email
doesn't currently mark this distinction visually, so don't forward anything
to a buyer without checking which market it's from first.

## Real permit + GIS sources found per market

Researched but **not yet wired up live** -- this is the next concrete step
per market, same spirit as the original Duval-only TODOs. Full detail (with
honest caveats on what's actually confirmed) lives in each `Market` record
in `markets.py`; summary:

| Market | Permit source | GIS source |
|---|---|---|
| Jacksonville, FL | JaxEPICS (jaxepics.coj.net) | Duval County GIS/JaxGIS (maps.coj.net) -- returned a maintenance page when checked |
| San Antonio, TX | City of San Antonio Open Data SA "Building Permits" dataset (free CSV, data.sanantonio.gov) for in-city permits; Bexar County Public Works for unincorporated county | Bexar County Open Data Portal (gis-bexar.opendata.arcgis.com, ArcGIS Hub); flood via San Antonio River Authority Floodplain Viewer |
| Atlanta Suburbs, GA | Gwinnett County weekly "Building Permits Issued" PDF reports (free, PDF not CSV); live Citizen Access/Accela search portal | Gwinnett County Open Data Portal (ArcGIS Hub, has a Zoning layer); flood via Gwinnett Flood Information Portal |
| Nashville Suburbs, TN | **Not confirmed as a free bulk export.** County only permits unincorporated land; its Electronic Plan Review System looks like a submission portal, not a public search/report tool. Most growth is inside incorporated cities (Franklin, Brentwood, Spring Hill, Nolensville) that permit separately through their own portals -- going live here means wiring up several city sources or a paid vendor, not one county export. | Williamson County GIS (ArcGIS/Geocortex-based) -- a live ArcGIS REST flood layer was confirmed reachable; zoning district viewer also available |

## PropStream alternative: free county/state land data

PropStream's free trial blocks CSV export, so `gis_land_sources.py` queries
county/state GIS systems directly as a free alternative, live, in all 4
markets as of 2026-06-24. Pattern that worked repeatedly: a live ArcGIS
REST/Feature Service with owner+value fields beats a bulk-download page --
check `sharing.arcgis.com`'s search API broadly (by county name, "tax
assessor", "CAMA", "property owner") rather than concluding too early that
a market has no live option.

- **Bexar (San Antonio) -- live.** Queries `maps.bexar.org`'s public ArcGIS
  Parcels layer (`State_cd='C1'`, the Texas Comptroller's standard "vacant
  lots and land tracts" code). Has owner name, mailing address, situs
  address, land value, acreage. **Does not have sale-history** (no last
  sale price/date, years owned, tax-delinquent status) -- PropStream
  provided those; this source doesn't, so `pitch.py`/`emailer.py` show
  "not available from this data source" rather than inventing numbers.
- **Jacksonville (Duval) -- live.** Queries Florida's *statewide* parcels
  Feature Service (`FL_Parcels`, ArcGIS Online) -- the exact same annual
  DOR data the original plan wanted as a static NAL file download (blocked
  by a JS-rendered document library), exposed live instead. Filters on
  `DOR_UC='000'`, Florida's statewide "Vacant Residential" code. Unlike
  Bexar, **does** carry real sale history when available.
- **Atlanta Suburbs (Gwinnett) -- live.** The owner/value table (layer 3,
  "Property and Tax Table") was sitting on the *same* `Property_and_Tax`
  Feature Service whose cadastral-only layer 0 was checked and rejected
  earlier -- just a different layer index on a service already found.
  Filters on `PROPCLAS='100'`, Gwinnett's own "Residential Vacant" code.
  No sale-history fields in this table.
- **Nashville Suburbs (Williamson) -- live, with one known gap.** Queries
  Williamson County's own GIS parcels table over plain HTTP (its HTTPS
  cert doesn't validate -- low risk for public records). No explicit
  land-use code field, so vacant land is inferred as `imp_assess<=0 AND
  total_asse>0` (no improvement value). **Real limitation:** the table has
  no usable property-zip-code field and its `CITY` field is a numeric code
  with no resolvable lookup, so every lead gets `market.zips[0]` as a
  placeholder zip/city -- wrong in that one detail. Doesn't matter yet
  since this market still won't run until its permit gate clears (above).

## Files

- `markets.py` -- registry of the 4 target markets: real county/state, real
  zip/city/area triples (mock-data flavor only), mock builder names, mock
  zoning vocabulary, and the real permit/GIS sources above.
- `land_data.py` -- land lead loading/mock generation, per market.
- `permits_data.py` -- permit loading/mock generation per market, aggregates
  permits into builder buyer-candidate profiles (active zips, permit count,
  recency, construction-value range). Builders need 2+ permits to count as a
  candidate (`MIN_PERMITS_FOR_BUYER_CANDIDATE`).
- `enrichment.py` -- zoning/flood/wetland lookups (mocked, see above);
  zoning vocabulary is per-market, flood zone codes (X/AE/A) are FEMA's
  national standard so that part is market-agnostic by design.
- `matcher.py` -- matches leads to builders by zip overlap within the same
  market run, ranked by builder activity (permit count, recency).
- `pitch.py` -- drafts a buyer pitch message per match via the Anthropic
  API. Market-agnostic -- it only ever sees one deal's facts at a time.
- `contracts.py` -- fills two DRAFT contract templates per match: an
  assignable purchase agreement and a separate assignment-of-contract
  document, with county/state filled in from the lead. **Not reviewed by an
  attorney in any state -- have one review before use.**
- `emailer.py` -- emails one combined digest via Resend, sectioned by
  market.
- `run.py` -- orchestrates the full pipeline end to end across all 4
  markets and sends the one combined digest.

## Run it

```
cp .env.example .env   # fill in ANTHROPIC_API_KEY, RESEND_API_KEY, DIGEST_TO
python3 run.py
```

Every run covers the markets in `markets.py` that pass the free-permit-
source gate above, and sends one combined digest email. Leave a market's
`LAND_CSV_PATH_<MARKET>`/`PERMITS_CSV_PATH_<MARKET>` blank to run that
market on mock data (default for the 3 markets with a confirmed free
source). `MOCK_LEAD_COUNT` (default 12) controls how many mock leads are
generated per market.

Note on email delivery: Resend accounts without a verified sending domain
can only deliver to the account's own signup address -- same caveat as the
Rolli project. Set `DIGEST_TO` to that address until a domain is verified.

## Known gaps / next steps

- Live GIS/permit integrations not wired up yet in any market (see table
  above) -- the loaders are isolated specifically so this is a contained
  follow-up per market, not a rewrite.
- Williamson County (Nashville suburbs) has no confirmed free bulk permit
  export, so it's **skipped by the free-permit-source gate** (see above)
  rather than run on mock data that implies a free feed that doesn't exist.
  Going live there likely means per-city portals (Franklin, Brentwood,
  Spring Hill, Nolensville) or a paid permit data vendor; to turn it back on
  with a real source, either flip `permit_source_is_free=True` once one's
  confirmed, or set `PERMITS_CSV_PATH_WILLIAMSON_TN` to override directly.
- Offer price in the purchase agreement draft is a rough `0.60 x estimated
  value` placeholder (`OFFER_PRICE_FACTOR` in `run.py`), not a real
  valuation -- edit before sending any real offer, in any market.
- Contract templates are generic drafts, not attorney-reviewed or
  state-bar-specific forms, in any of the 4 states.
