"""
Matches land leads to builder buyer-candidates. Zip/area overlap is the
real signal here -- a builder repeatedly pulling permits in a zip is
genuine, observed demand for buildable lots there. Permit construction
value is also used as a rough affordability gate: a lot whose assessed
value exceeds 3x the builder's max typical construction spend is almost
certainly priced out of their range and is dropped from that pairing.
The filter is skipped when either value is unknown (None or zero).
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
            # Drop pairings where the lot is priced way beyond what this
            # builder typically spends on construction. 3x their max is a
            # generous ceiling -- a builder at $135k/build won't touch a
            # $1.5M lot. Only applied when both values are known and nonzero.
            if (
                builder.max_construction_value
                and lead.assessed_value
                and lead.assessed_value > 3 * builder.max_construction_value
            ):
                continue

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
