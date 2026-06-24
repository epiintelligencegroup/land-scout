# Land Scout -- AI-assisted vacant land wholesaling pipeline

Runs four target markets every pass (see `markets.py`):

- **Austin, TX** (Travis County)
- **San Antonio, TX** (Bexar County)
- **Atlanta Suburbs, GA** (Gwinnett County)
- **Nashville Suburbs, TN** (Williamson County) -- currently **skipped**, see below

For each market it finds vacant land leads, enriches each with zoning/flood/
wetland status, matches them to active local home builders (identified from
public permit activity), drafts a buyer pitch and two draft contracts per
match, and emails one combined digest -- sectioned by market -- to you to
forward.

## Current state: 3 of 4 active markets are fully real, end to end

**Austin (Travis), San Antonio (Bexar), and Atlanta Suburbs (Gwinnett) are
fully real on both sides** -- a real property with a real owner, matched to
a real home builder with real, current permit activity. Confirmed real
builders showing up in live data as of 2026-06-24: D R Horton Homes, David
Weekley Homes, Brookfield Residential, Tri Pointe Homes, Trophy Signature
Homes (Austin); LENNAR HOMES, PERRY HOMES, CHESMAR HOMES (San Antonio);
TAYLOR MORRISON OF GEORGIA, STANLEY MARTIN HOMES, PULTE HOME COMPANY
(Gwinnett). **Williamson County (Nashville suburbs) is skipped** every run
-- no confirmed free permit source was found there despite real effort (see
below) -- so it never reaches mock-vs-real territory; it just doesn't run.

Two things are still mocked everywhere: zoning/flood/wetland enrichment
(`enrichment.py`), and comps (would come free with a real PropStream
account, not wired up). Contract drafts are real templates filled with real
deal facts, but are not attorney-reviewed in any state.

**Every run fetches fresh, and never re-sends the same property.** There is
no caching layer anywhere -- every live source (`gis_land_sources.py`,
`live_permit_sources.py`) hits its real API on every single run. Separately,
`sent_log.py` keeps a permanent append-only record (`sent_properties.log`)
of every property ever included in a successfully-sent digest; `run.py`
filters those out before drafting a pitch for them (saving the Anthropic
call too), so the same property is never sent twice across any number of
runs or days. The log only gets written to after a send actually succeeds.

**This file is git-tracked, not gitignored** -- the cloud routine clones a
fresh checkout on every scheduled run, so the dedup log has to live in the
repo itself (committed and pushed back after each successful send) to carry
forward across days; a local-only file would reset to empty on every cloud
run. If you ever run this locally too, expect `git status` to show
`sent_properties.log` as modified after a real send -- commit and push it
so your local runs and the cloud's daily run share the same history.

**Free-permit-source gate:** `run.py` only runs a market if its permit
source is a confirmed free source (`Market.permit_source_is_free` in
`markets.py`), or you've explicitly pointed `PERMITS_CSV_PATH_<MARKET>` at a
real export yourself. This is deliberate -- the pipeline should never start
quietly relying on a paid permit feed. It shows up in both the console
output and the digest email as a clearly-labeled skip, not a silent
omission.

**Low-inventory alert:** if a market's matched-deal count in a given run
falls below `LOW_INVENTORY_THRESHOLD` (default 3), the digest gets a
prominent alert section naming the market and suggesting pre-vetted,
free-permit-friendly backup markets to expand into (`CANDIDATE_MARKETS` in
`markets.py` -- currently Raleigh/Wake NC and Charlotte/Mecklenburg NC).
Adding a suggested market still requires an actual code change (a new
`Market` entry with real zips/builder names, same as the active 4) -- the
alert tells you it's time, it doesn't do it automatically.

## Real sources, per market

Full detail (with honest caveats on what's actually confirmed, including
exact field names and filter values) lives in each `Market` record's
`land_source`/`permit_source`/`gis_source` in `markets.py`. Summary:

| Market | Land source | Permit source |
|---|---|---|
| Austin, TX | Travis Central Appraisal District parcel data (`TCAD_Parcels_Dec_2025` ArcGIS Feature Service) -- live, owner+value+address | City of Austin "Issued Construction Permits" Socrata dataset (data.austintexas.gov) -- live, clean SoQL API |
| San Antonio, TX | Bexar County GIS Parcels (ArcGIS REST) -- live | City of San Antonio Open Data SA "Building Permits" CSV (CKAN/S3-hosted) -- live |
| Atlanta Suburbs, GA | Gwinnett County "Property and Tax Table" (ArcGIS Feature Service) -- live | Gwinnett County weekly "Building Permits Issued" PDF report, parsed with `pdfplumber` -- live but more fragile than the others |
| Nashville Suburbs, TN | Williamson County GIS parcels table (ArcGIS, HTTP only) -- live, with a known zip/city placeholder gap | **Not confirmed as a free bulk export.** County only permits unincorporated land; growth is mostly inside incorporated cities that permit separately. Market is skipped until this changes. |

**Pattern that worked repeatedly when hunting for these:** a live ArcGIS
REST/Feature Service with owner+value fields beats a bulk-download page or
a login-gated portal almost every time. Search `sharing.arcgis.com`'s
search API broadly (by county name, "tax assessor", "CAMA", "property
owner") before concluding a market has no live option -- and when a
service's first layer disappoints (cadastral-only, no owner field), check
its *other* layers/tables before moving on. This is exactly how Gwinnett's
and Austin's owner data were found: sitting on a different layer of a
service whose first layer had already been checked and rejected.

`pdfplumber` (Gwinnett's permit parser) is this project's only non-stdlib
dependency (`pip3 install pdfplumber`) -- everything else is deliberately
stdlib-only (`urllib`, `http.client`, `csv`, `json`). That was a real
tradeoff (more fragile than a REST API -- a report layout change could
silently break it) made with explicit user sign-off; don't add further
PDF/scraping-based sources without the same check-in.

## Files

- `markets.py` -- registry of the 4 target markets: real county/state, real
  zip/city/area triples (mock-data flavor only), mock builder names, mock
  zoning vocabulary, and the real land/permit/GIS sources above.
- `gis_land_sources.py` -- live land-lead loaders, keyed by market in
  `LIVE_LAND_LOADERS`.
- `live_permit_sources.py` -- live permit loaders, keyed by market in
  `LIVE_PERMIT_LOADERS`.
- `land_data.py` -- PropStream-shaped land lead CSV loader + mock generator,
  per market.
- `permits_data.py` -- permit CSV loader + mock generator per market,
  aggregates permits into builder buyer-candidate profiles (active zips,
  permit count, recency, construction-value range when known). Builders
  need 2+ permits to count as a candidate (`MIN_PERMITS_FOR_BUYER_CANDIDATE`).
- `enrichment.py` -- zoning/flood/wetland lookups (mocked); zoning
  vocabulary is per-market, flood zone codes (X/AE/A) are FEMA's national
  standard so that part is market-agnostic by design.
- `matcher.py` -- matches leads to builders by zip overlap within the same
  market run, ranked by builder activity (permit count, recency).
- `pitch.py` -- drafts a buyer pitch message per match via the Anthropic
  API. Market-agnostic -- it only ever sees one deal's facts at a time.
- `contracts.py` -- fills two DRAFT contract templates per match: an
  assignable purchase agreement and a separate assignment-of-contract
  document, with county/state filled in from the lead. **Not reviewed by an
  attorney in any state -- have one review before use.**
- `sent_log.py` -- permanent dedup log so a property is never sent twice.
- `emailer.py` -- emails one combined digest via Resend, sectioned by
  market, with a summary dashboard and a "Best Deal of the Day" highlight.
- `run.py` -- orchestrates the full pipeline end to end across all active
  markets and sends the one combined digest.

## Run it

```
cp .env.example .env   # fill in ANTHROPIC_API_KEY, RESEND_API_KEY, DIGEST_TO
set -a && source .env && set +a   # .env is not auto-loaded -- source it first
python3 run.py
```

Every run covers the markets in `markets.py` that pass the free-permit-
source gate above, and sends one combined digest email. Leave a market's
`LAND_CSV_PATH_<MARKET>`/`PERMITS_CSV_PATH_<MARKET>` blank to use its live
source (default for all 3 active markets); point them at a real CSV export
to override the live source, or unset the live source entirely to fall
back to mock. `MOCK_LEAD_COUNT` (default 12) also caps how many leads a
live land source pulls per run, to keep API/email cost predictable.

Note on email delivery: Resend accounts without a verified sending domain
can only deliver to the account's own signup address -- same caveat as the
Rolli project. Set `DIGEST_TO` to that address until a domain is verified.

## Known gaps / next steps

- Zoning/flood/wetland enrichment is still mocked in every market -- real
  GIS sources exist (see `Market.gis_source` in `markets.py`) but none of
  those endpoints have been wired up live yet.
- Williamson County (Nashville suburbs) has no confirmed free bulk permit
  export, so it's **skipped by the free-permit-source gate**. Going live
  there likely means per-city portals (Franklin, Brentwood, Spring Hill,
  Nolensville) or a paid permit data vendor; to turn it back on with a real
  source, either flip `permit_source_is_free=True` once one's confirmed, or
  set `PERMITS_CSV_PATH_WILLIAMSON_TN` to override directly. Its land
  loader also has a known zip/city placeholder gap (no real zip field on
  that table) worth fixing first if this market is ever revived.
- Gwinnett's permit loader depends on a weekly PDF report whose URL slug
  isn't consistently formatted -- the loader discovers the latest report
  from the listing page rather than guessing a URL, but a real CMS/layout
  change could still break the `pdfplumber` parsing.
- Offer price in the purchase agreement draft is a rough `0.60 x estimated
  value` placeholder (`OFFER_PRICE_FACTOR` in `run.py`), not a real
  valuation -- edit before sending any real offer, in any market.
- Contract templates are generic drafts, not attorney-reviewed or
  state-bar-specific forms, in any of the 4 states.
