"""
Matches land leads to builder buyer-candidates. Zip/area overlap is the
real signal here -- a builder repeatedly pulling permits in a zip is
genuine, observed demand for buildable lots there. Permit construction
value doesn't reliably bound what a builder will pay for raw land (it's
the cost to build the house, not the lot), so it's surfaced as context for
the human pitching the deal rather than used as a hard price filter.
"""
from dataclasses import dataclass

MAX_BUILDERS_PER_LEAD = 2


@dataclass
class Match:
    land_lead: object
    builder: object
    fit_reason: str


def match_leads_to_builders(land_leads, builders):
    matches = []
    unmatched = []
    for lead in land_leads:
        candidates = [b for b in builders if lead.zip in b.active_zips]
        candidates.sort(key=lambda b: (b.permit_count, b.most_recent_issue_date), reverse=True)
        top_candidates = candidates[:MAX_BUILDERS_PER_LEAD]
        if not top_candidates:
            unmatched.append(lead)
            continue
        for builder in top_candidates:
            if builder.min_construction_value is not None:
                value_clause = (
                    f", building in the ${builder.min_construction_value:,.0f}-"
                    f"${builder.max_construction_value:,.0f} construction-value range"
                )
            else:
                # Real permit feeds don't always carry a declared value (e.g.
                # San Antonio's "Res New Building Permit" rows never do) --
                # omit the claim rather than print a misleading $0-$0 range.
                value_clause = ""
            matches.append(Match(
                land_lead=lead,
                builder=builder,
                fit_reason=(
                    f"{builder.builder_name} has pulled {builder.permit_count} permits in "
                    f"{lead.zip} (most recently {builder.most_recent_issue_date}){value_clause} "
                    f"-- active, repeat demand in this exact zip."
                ),
            ))
    return matches, unmatched
