#!/usr/bin/env python3
"""
House Wholesale Pipeline — daily orchestrator.

For each market:
  1. Load house leads (real CSV -> live GIS source -> mock)
  2. Deduplicate against sent_properties.log
  3. Draft outreach message per fresh lead (Claude)
  4. Load cash buyers from deed records in same zip codes

Then send one combined "House Wholesale Daily Digest" email covering all
markets. On a confirmed send, log the new lead keys so they are never resent.

Setup:
    cp .env.example .env   # fill in ANTHROPIC_API_KEY, RESEND_API_KEY, DIGEST_TO
    python3 run.py
"""
import datetime
import os

from cash_buyers import load_cash_buyers
from emailer import send_digest_email
from gis_house_sources import LIVE_HOUSE_LOADERS
from house_data import generate_mock_house_leads, load_house_leads
from markets import MARKETS
from outreach import draft_outreach
from sent_log import append_sent_keys, lead_key, load_sent_keys

MOCK_LEAD_COUNT = int(os.environ.get("MOCK_LEAD_COUNT", "10"))


def _market_csv_path(market):
    return os.environ.get(f"HOUSE_CSV_PATH_{market.key}") or None


def run_market(market, sent_keys):
    label = market.label
    csv_path = _market_csv_path(market)

    if csv_path:
        leads = load_house_leads(csv_path)
        print(f"[{label}] Loaded {len(leads)} leads from {csv_path}")
    elif market.key in LIVE_HOUSE_LOADERS:
        leads = LIVE_HOUSE_LOADERS[market.key](market, limit=MOCK_LEAD_COUNT)
        if not leads:
            leads = generate_mock_house_leads(market, MOCK_LEAD_COUNT)
            print(f"[{label}] Live fetch returned 0 leads — using {len(leads)} mock leads")
        else:
            print(f"[{label}] Fetched {len(leads)} leads live from county GIS")
    else:
        leads = generate_mock_house_leads(market, MOCK_LEAD_COUNT)
        print(f"[{label}] Generated {len(leads)} mock leads (no HOUSE_CSV_PATH_{market.key} set)")

    fresh_leads = [lead for lead in leads if lead_key(market, lead) not in sent_keys]
    already_sent = len(leads) - len(fresh_leads)
    print(f"[{label}] {len(fresh_leads)} fresh lead(s), {already_sent} already sent before")

    deals = []
    for lead in fresh_leads:
        print(f"  [{label}] Drafting outreach: {lead.full_property_address}")
        outreach_text = draft_outreach(lead)
        deals.append({"lead": lead, "outreach": outreach_text})

    buyers = load_cash_buyers(market)
    print(f"[{label}] {len(buyers)} cash buyer(s) identified, "
          f"{sum(1 for b in buyers if b.is_active_flipper)} active flipper(s)")

    return {"market": market, "deals": deals, "buyers": buyers}


def main():
    today = datetime.date.today().isoformat()
    sent_keys = load_sent_keys()
    print(f"{len(sent_keys)} properties already sent in past runs")

    market_results = [run_market(market, sent_keys) for market in MARKETS]

    total_deals = sum(len(r["deals"]) for r in market_results)
    print(f"{total_deals} total fresh leads across {len(market_results)} markets")

    sent_ok = send_digest_email(market_results, run_label=today)
    if sent_ok:
        new_keys = [lead_key(r["market"], d["lead"]) for r in market_results for d in r["deals"]]
        append_sent_keys(new_keys)
        print(f"Logged {len(new_keys)} newly-sent properties to sent_log.")
    print("Done.")


if __name__ == "__main__":
    main()
