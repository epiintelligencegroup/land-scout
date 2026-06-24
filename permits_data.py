"""
Builder/buyer discovery -- normalizes a building-permit CSV export (see each
Market's permit_source in markets.py for the real free source per county)
into Permit records, then aggregates by contractor into BuyerCandidate
profiles. A builder pulling repeat permits in the same zips, at a consistent
construction-value range, is real demand signal for vacant infill lots there
-- that's the whole "find buyers" angle, and it's the same logic regardless
of which market the permits came from.

None of the four markets' permit exports have been live-fetched and confirmed
column-for-column yet (see markets.py/README), so PERMIT_FIELDS below assumes
a reasonable schema. Swapping in a real export later means updating
PERMIT_FIELDS/_row_to_permit to match its actual headers -- everything
downstream (matching, pitching) works off the normalized Permit/BuyerCandidate
records either way.
"""
import csv
import datetime
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

TODAY = datetime.date.today()
MIN_PERMITS_FOR_BUYER_CANDIDATE = 2

PERMIT_FIELDS = [
    "Permit Number", "Contractor Name", "Property Address", "Property Zip",
    "Permit Type", "Issue Date", "Construction Value",
]

NEW_CONSTRUCTION_TYPES = ["New Single Family", "New Construction - Residential"]


@dataclass
class Permit:
    permit_number: str
    contractor_name: str
    property_address: str
    zip: str
    permit_type: str
    issue_date: str
    # Optional because not every real permit feed populates this for every
    # permit type -- e.g. San Antonio's feed never has a declared valuation
    # on "Res New Building Permit" rows. None means "unknown", not zero.
    construction_value: Optional[float]


@dataclass
class BuyerCandidate:
    builder_name: str
    active_zips: list
    permit_count: int
    most_recent_issue_date: str
    # None when none of this builder's permits had a known construction
    # value (see Permit.construction_value) -- not zero.
    avg_construction_value: Optional[float]
    min_construction_value: Optional[float]
    max_construction_value: Optional[float]


def _row_to_permit(row):
    return Permit(
        permit_number=row["Permit Number"],
        contractor_name=row["Contractor Name"],
        property_address=row["Property Address"],
        zip=row["Property Zip"],
        permit_type=row["Permit Type"],
        issue_date=row["Issue Date"],
        construction_value=float(row["Construction Value"]),
    )


def load_permits(csv_path):
    """Load a real JaxEPICS export. Raises if a column is missing/renamed --
    that's a signal to update PERMIT_FIELDS/_row_to_permit to match the
    actual export rather than silently guessing."""
    with open(csv_path, newline="") as f:
        return [_row_to_permit(row) for row in csv.DictReader(f)]


def generate_mock_permits(market, builder_count=10, seed=None):
    rng = random.Random(seed)
    builder_names = market.builder_names[:builder_count]

    permits = []
    permit_num = 100000
    for builder in builder_names:
        # Each builder is active in 1-3 of the same zips land leads show up in,
        # at a fairly consistent construction-value range -- that consistency
        # is the actual buyer-matching signal.
        builder_zips = rng.sample(market.zips, k=rng.randint(1, min(3, len(market.zips))))
        value_floor = rng.randint(180000, 260000)
        value_span = rng.randint(40000, 90000)
        num_permits = rng.randint(2, 9)
        for _ in range(num_permits):
            zip_code, city, area_label = rng.choice(builder_zips)
            days_ago = rng.randint(0, 540)  # spread across roughly the last 18 months
            issue_date = TODAY - datetime.timedelta(days=days_ago)
            permits.append(Permit(
                permit_number=f"BP-{permit_num}",
                contractor_name=builder,
                property_address=f"{rng.randint(100,9900)} {rng.choice(['Cypress','Magnolia','Palm','Sunset','Lakeview'])} Ave, {area_label}, {market.state} {zip_code}",
                zip=zip_code,
                permit_type=rng.choice(NEW_CONSTRUCTION_TYPES),
                issue_date=issue_date.isoformat(),
                construction_value=float(value_floor + rng.randint(0, value_span)),
            ))
            permit_num += 1
    return permits


def aggregate_builders(permits, min_permits=MIN_PERMITS_FOR_BUYER_CANDIDATE):
    by_builder = defaultdict(list)
    for permit in permits:
        by_builder[permit.contractor_name].append(permit)

    candidates = []
    for builder_name, builder_permits in by_builder.items():
        if len(builder_permits) < min_permits:
            continue
        zip_counts = defaultdict(int)
        for p in builder_permits:
            zip_counts[p.zip] += 1
        active_zips = sorted(zip_counts, key=zip_counts.get, reverse=True)
        values = [p.construction_value for p in builder_permits if p.construction_value is not None]
        candidates.append(BuyerCandidate(
            builder_name=builder_name,
            active_zips=active_zips,
            permit_count=len(builder_permits),
            most_recent_issue_date=max(p.issue_date for p in builder_permits),
            avg_construction_value=sum(values) / len(values) if values else None,
            min_construction_value=min(values) if values else None,
            max_construction_value=max(values) if values else None,
        ))

    return sorted(candidates, key=lambda c: c.permit_count, reverse=True)
