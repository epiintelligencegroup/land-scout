#!/usr/bin/env python3
"""
Land Scout -- orchestrates the full pipeline across every configured market
(markets.py): load land leads (real CSV override -> live free GIS source if
one's registered in gis_land_sources.py -> mock, in that priority order) +
builder permits (same priority chain, live loaders in live_permit_sources.py)
-> enrich each lead with zoning/flood/wetland -> match leads to active
builders -> draft a pitch per match -> generate draft contracts -> email one
combined digest covering every market.

Free-permit-source gate: a market only runs if its Market.permit_source_is_free
is True, or a real PERMITS_CSV_PATH_<key> override is configured -- see
_skip_reason() below. The point is to never quietly start relying on a paid
permit feed without the user choosing that explicitly. Skipped markets are
listed in both the console output and the digest email itself.

Setup:
    cp .env.example .env   # fill in ANTHROPIC_API_KEY, RESEND_API_KEY, DIGEST_TO
    python3 run.py
"""
import datetime
import os

from contracts import fill_assignment_of_contract, fill_purchase_agreement
from emailer import send_digest_email
from enrichment import enrich
from gis_land_sources import LIVE_LAND_LOADERS
from land_data import generate_mock_land_leads, load_land_leads
from live_permit_sources import LIVE_PERMIT_LOADERS
from markets import CANDIDATE_MARKETS, JACKSONVILLE_FL, MARKETS
from matcher import match_leads_to_builders
from permits_data import aggregate_builders, generate_mock_permits, load_permits
from pitch import draft_pitch

MOCK_LEAD_COUNT = int(os.environ.get("MOCK_LEAD_COUNT", "12"))
WHOLESALER_NAME = os.environ.get("WHOLESALER_NAME", "Ahmaad Piper")
WHOLESALER_ADDRESS = os.environ.get("WHOLESALER_ADDRESS", "Jacksonville, FL")
ASSIGNMENT_FEE_DEFAULT = float(os.environ.get("ASSIGNMENT_FEE_DEFAULT", "5000"))
# Below this many matched deals in a single run, a market is "running low"
# -- triggers the low-inventory alert + new-market suggestions in the digest.
LOW_INVENTORY_THRESHOLD = int(os.environ.get("LOW_INVENTORY_THRESHOLD", "3"))
# Rough starting-offer anchor, not a real valuation -- the contract draft is
# meant to be edited during actual negotiation, this just avoids a $0 default.
OFFER_PRICE_FACTOR = 0.60


def _market_csv_path(market, kind):
    """kind is "LAND" or "PERMITS". Per-market env var, e.g. LAND_CSV_PATH_BEXAR_TX.
    Jacksonville also accepts the original unprefixed LAND_CSV_PATH/PERMITS_CSV_PATH
    for backward compatibility with existing setups."""
    path = os.environ.get(f"{kind}_CSV_PATH_{market.key}")
    if path:
        return path
    if market is JACKSONVILLE_FL:
        return os.environ.get(f"{kind}_CSV_PATH") or None
    return None


def _skip_reason(market, permits_csv_path):
    """Returns a reason string if this market should be skipped, or None to run it.
    The gate is permits specifically (the thing we're searching for a free source
    of) -- a market never runs on mock or real permit data unless permit_source_is_free
    is True, or the user has explicitly pointed PERMITS_CSV_PATH_<key> at a real
    export (their own sourcing decision, not the code's to second-guess)."""
    if permits_csv_path or market.permit_source_is_free:
        return None
    return (
        f"no confirmed free permit source yet ({market.permit_source.splitlines()[0][:120]}...) "
        f"-- set PERMITS_CSV_PATH_{market.key} to override once you have a real export"
    )


def run_market(market, today, closing_date):
    label = market.label
    land_csv_path = _market_csv_path(market, "LAND")
    permits_csv_path = _market_csv_path(market, "PERMITS")

    skip_reason = _skip_reason(market, permits_csv_path)
    if skip_reason:
        print(f"[{label}] SKIPPED -- {skip_reason}")
        return None

    if land_csv_path:
        leads = load_land_leads(land_csv_path)
        print(f"[{label}] Loaded {len(leads)} real land leads from {land_csv_path}")
    elif market.key in LIVE_LAND_LOADERS:
        # Same volume knob as mock data on purpose -- MOCK_LEAD_COUNT default
        # of 12 keeps a live run's API/email cost predictable; raise it
        # deliberately, don't let a live source silently pull hundreds.
        leads = LIVE_LAND_LOADERS[market.key](market, limit=MOCK_LEAD_COUNT)
        print(f"[{label}] Fetched {len(leads)} real land leads live from {market.key}'s free GIS source")
    else:
        leads = generate_mock_land_leads(market, MOCK_LEAD_COUNT)
        print(f"[{label}] Generated {len(leads)} mock land leads (no LAND_CSV_PATH_{market.key} set)")

    if permits_csv_path:
        permits = load_permits(permits_csv_path)
        print(f"[{label}] Loaded {len(permits)} real permits from {permits_csv_path}")
    elif market.key in LIVE_PERMIT_LOADERS:
        permits = LIVE_PERMIT_LOADERS[market.key](market)
        print(f"[{label}] Fetched {len(permits)} real permits live from {market.key}'s free source")
    else:
        permits = generate_mock_permits(market)
        print(f"[{label}] Generated {len(permits)} mock permits (no PERMITS_CSV_PATH_{market.key} set)")

    builders = aggregate_builders(permits)
    print(f"[{label}] {len(builders)} builder buyer-candidates after aggregation (min 2 permits)")

    matches, unmatched = match_leads_to_builders(leads, builders)
    print(f"[{label}] {len(matches)} lead-builder matches, {len(unmatched)} leads unmatched")

    deals = []
    for match in matches:
        lead = match.land_lead
        builder = match.builder
        enrichment_data = enrich(lead)
        print(f"  [{label}] Drafting pitch: {lead.property_address} -> {builder.builder_name}")
        pitch_text = draft_pitch(lead, enrichment_data, builder, match.fit_reason)

        offer_price = round(lead.estimated_value * OFFER_PRICE_FACTOR, -2)
        purchase_agreement = fill_purchase_agreement(
            lead, WHOLESALER_NAME, WHOLESALER_ADDRESS, offer_price, today, closing_date,
        )
        assignment_contract = fill_assignment_of_contract(
            lead, WHOLESALER_NAME, builder.builder_name, "[buyer address]",
            today, today, ASSIGNMENT_FEE_DEFAULT,
        )

        deals.append({
            "land_lead": lead,
            "builder": builder,
            "enrichment": enrichment_data,
            "fit_reason": match.fit_reason,
            "pitch": pitch_text,
            "purchase_agreement": purchase_agreement,
            "assignment_contract": assignment_contract,
        })

    return {"market": market, "deals": deals, "unmatched_count": len(unmatched)}


def main():
    today = datetime.date.today().isoformat()
    closing_date = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()

    all_results = [run_market(market, today, closing_date) for market in MARKETS]
    market_results = [r for r in all_results if r is not None]
    skipped_markets = [m for m, r in zip(MARKETS, all_results) if r is None]

    low_inventory_results = [r for r in market_results if len(r["deals"]) < LOW_INVENTORY_THRESHOLD]
    for r in low_inventory_results:
        print(f"[{r['market'].label}] LOW INVENTORY -- {len(r['deals'])} matched deal(s), "
              f"below threshold of {LOW_INVENTORY_THRESHOLD}")

    total_deals = sum(len(r["deals"]) for r in market_results)
    skip_note = f" ({len(skipped_markets)} market(s) skipped -- no free permit source)" if skipped_markets else ""
    print(f"{total_deals} total matched deals across {len(market_results)} markets{skip_note}")

    send_digest_email(
        market_results,
        skipped_markets=skipped_markets,
        low_inventory_results=low_inventory_results,
        candidate_markets=CANDIDATE_MARKETS,
        run_label=today,
    )
    print("Done.")


if __name__ == "__main__":
    main()
