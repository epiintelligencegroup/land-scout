"""
Cash buyer discovery from deed transfer records.

A "cash buyer" is anyone who purchased residential property in the last 12
months in the same zip codes as our leads, with no accompanying mortgage.
Two metrics per buyer:
  - recent_purchases: cash buys in the last 12 months
  - two_year_purchases: cash buys in the last 24 months

Buyers with two_year_purchases >= 3 are flagged as active flippers/landlords
who close fast — highest-priority contacts for wholesale deals.

Falls through to mock data when live county deed APIs are not reachable.
"""
import datetime
import json
import random
import urllib.parse
import urllib.request
from collections import defaultdict

CURRENT_YEAR = datetime.date.today().year
_TIMEOUT = 20


class CashBuyer:
    def __init__(self, name, mailing_address, zip_codes_active, recent_purchases, two_year_purchases):
        self.name = name
        self.mailing_address = mailing_address
        self.zip_codes_active = zip_codes_active  # zips where they've bought
        self.recent_purchases = recent_purchases   # last 12 months
        self.two_year_purchases = two_year_purchases  # last 24 months

    @property
    def is_active_flipper(self):
        return self.two_year_purchases >= 3


def _get_json(url, params=None):
    full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full_url, headers={"User-Agent": "HouseWholesalePipeline/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _cutoff_date(months_ago):
    return (datetime.date.today() - datetime.timedelta(days=months_ago * 30)).isoformat()


def _aggregate_buyers(features, name_key, addr_key, zip_key, date_key):
    """Aggregate raw deed feature dicts into CashBuyer records."""
    cutoff_12 = _cutoff_date(12)
    by_buyer = defaultdict(list)
    for a in features:
        name = (a.get(name_key) or "").strip().upper()
        if not name:
            continue
        date_val = str(a.get(date_key) or "")
        zip_val = str(a.get(zip_key) or "").strip()
        addr_val = (a.get(addr_key) or "").strip()
        by_buyer[(name, addr_val)].append((date_val, zip_val))

    buyers = []
    for (name, addr), purchases in by_buyer.items():
        two_year = len(purchases)
        recent = sum(1 for d, _ in purchases if d[:10] >= cutoff_12)
        zips = list({z for _, z in purchases if z})
        buyers.append(CashBuyer(
            name=name.title(),
            mailing_address=addr,
            zip_codes_active=zips,
            recent_purchases=recent,
            two_year_purchases=two_year,
        ))
    buyers.sort(key=lambda b: (b.two_year_purchases, b.recent_purchases), reverse=True)
    return buyers[:20]


# ─── Mock generator ───────────────────────────────────────────────────────────

_BUYER_FIRST = [
    "Marcus", "Devon", "Tanya", "Chris", "Kevin", "Regina", "Todd",
    "Angela", "Brian", "Denise", "Victor", "Sandra", "Eddie", "Loretta",
    "Antoine", "Felicia", "Jerome", "Monique", "Darnell", "Yvette",
]
_BUYER_LAST = [
    "Freeman", "Hughes", "Bennett", "Patterson", "Cooper", "Reed",
    "Bailey", "Rivera", "Powell", "Long", "Ross", "Torres", "Simmons",
    "Washington", "Jefferson", "Hayes", "Crawford", "Griffin", "Morrison",
]
_COMPANY_SUFFIXES = [
    " Properties LLC", " Investments LLC", " Holdings LLC",
    " Real Estate Group", " Capital Partners LLC",
]


def generate_mock_cash_buyers(market, count=8):
    rng = random.Random(market.key + "buyers" + str(datetime.date.today()))
    buyers = []
    market_zips = [z for z, _ in market.zips]
    for i in range(count):
        if rng.random() < 0.45:
            name = (
                f"{rng.choice(_BUYER_FIRST)} {rng.choice(_BUYER_LAST)}"
                + rng.choice(_COMPANY_SUFFIXES)
            )
        else:
            name = f"{rng.choice(_BUYER_FIRST)} {rng.choice(_BUYER_LAST)}"
        two_yr = rng.randint(1, 9)
        recent = min(two_yr, rng.randint(0, 5))
        active_zips = rng.sample(market_zips, min(rng.randint(1, 4), len(market_zips)))
        buyers.append(CashBuyer(
            name=name,
            mailing_address=(
                f"{rng.randint(100, 9999)} Commerce Dr, Suite {rng.randint(1, 99)}"
            ),
            zip_codes_active=active_zips,
            recent_purchases=recent,
            two_year_purchases=two_yr,
        ))
    buyers.sort(key=lambda b: (b.two_year_purchases, b.recent_purchases), reverse=True)
    return buyers


def load_cash_buyers(market):
    """Load cash buyers for the given market. All markets currently use mock data;
    wire live county deed API loaders here once endpoints are confirmed per county."""
    return generate_mock_cash_buyers(market)
