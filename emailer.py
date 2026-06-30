"""
Sends the run's digest via Resend -- same call pattern as Rolli's
rolli_core.py:send_order_email (plain urllib, HTML body, silently skips if
no API key is set rather than crashing a local test run).

One digest email covers every market run.py ran this pass, sectioned by
market so a buyer pitch in Bexar County never gets confused with one in
Duval County. Styled to be forward-to-a-buyer presentable: a summary
dashboard, a "best deal of the day" highlight, and color-coded risk badges
(flood/wetlands/motivated-seller) on every card. All styling is inline
(no <style> block) because Gmail strips <head> styles -- inline is the
only style that reliably survives across email clients.
"""
import datetime
import json
import os
import urllib.error
import urllib.request

from lead_routing import MAIL_LEAD, PHONE_LEAD, LOW_PRIORITY, UNKNOWN_TENURE

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM", "Land Scout <onboarding@resend.dev>")
DIGEST_TO = os.environ.get("DIGEST_TO")

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"
# Owner-held threshold that flags as a "motivated seller" signal -- a
# wholesaling rule of thumb, not derived from any of this lead's own data.
MOTIVATED_SELLER_YEARS = 5


def _badge(label, bg, fg):
    return (
        f'<span style="display:inline-block; background:{bg}; color:{fg}; '
        f'font-size:11px; font-weight:700; padding:4px 10px; border-radius:12px; '
        f'margin:0 6px 6px 0;">{label}</span>'
    )


def _flood_badge(enrichment_data):
    if enrichment_data["flood_risk"] == "high":
        return _badge(f"⚠ High Flood Risk ({enrichment_data['flood_zone']})", "#fee2e2", "#b91c1c")
    return _badge(f"✓ Minimal Flood Risk ({enrichment_data['flood_zone']})", "#dcfce7", "#15803d")


def _wetlands_badge(enrichment_data):
    if enrichment_data["wetlands_present"]:
        return _badge("⚠ Wetlands Present", "#ffedd5", "#c2410c")
    return _badge("✓ No Wetlands", "#dcfce7", "#15803d")


def _motivated_seller_badge(lead):
    if lead.years_owned is None:
        return _badge("Ownership history unknown", "#f3f4f6", "#4b5563")
    if lead.years_owned >= MOTIVATED_SELLER_YEARS:
        return _badge(f"$ Motivated Seller ({lead.years_owned}y held)", "#fef9c3", "#92400e")
    return ""


def _lead_type_box(deal):
    """Colored action box shown at the top of every deal card.
    Phone leads show skip trace contact info (or 'not found').
    Mail leads show the generated letter filename.
    Low priority and unknown tenure get a brief informational note only.
    """
    lead = deal["land_lead"]
    lead_type = deal.get("lead_type", UNKNOWN_TENURE)
    years = lead.years_owned

    if lead_type == PHONE_LEAD:
        st = deal.get("skip_trace_result")
        if st is None:
            contact_html = (
                '<span style="color:#6b7280;">BATCHDATA_API_KEY not configured -- '
                'set it in .env to enable skip tracing</span>'
            )
        elif st.error:
            contact_html = f'<span style="color:#dc2626;">Skip trace error: {st.error}</span>'
        elif not st.found:
            contact_html = '<span style="color:#6b7280;">No contact info found</span>'
        else:
            phone_html = ""
            if st.best_phone:
                p = st.best_phone
                pct = f"{int(p.score * 100)}%" if p.score else "?"
                phone_html = (
                    f'<b>Best number:</b> {p.number} [{p.type}] &middot; Confidence: {pct}<br>'
                )
            email_html = ""
            if st.emails:
                email_html = f'<b>Email:</b> {", ".join(st.emails[:2])}<br>'
            name_html = (
                '<b>Name match:</b> <span style="color:#15803d;">&#10003; Verified</span>'
                if st.name_verified else
                '<b>Name match:</b> <span style="color:#dc2626;">&#9888; Mismatch -- verify manually</span>'
            )
            contact_html = phone_html + email_html + name_html
        return (
            '<div style="background:#f0fdf4; border-left:4px solid #16a34a; padding:10px 14px; '
            'margin-bottom:14px; border-radius:4px;">'
            f'<div style="font-weight:700; color:#14532d; margin-bottom:6px; font-size:14px;">'
            f'&#128222; Phone Lead &mdash; {years}y held</div>'
            f'<div style="font-size:13px; line-height:1.6;">{contact_html}</div>'
            '</div>'
        )

    if lead_type == MAIL_LEAD:
        letter_path = deal.get("letter_path")
        letter_html = (
            f'<b>Letter file:</b> {os.path.basename(letter_path)}'
            if letter_path else
            '<span style="color:#dc2626;">Letter generation failed</span>'
        )
        return (
            '<div style="background:#eff6ff; border-left:4px solid #2563eb; padding:10px 14px; '
            'margin-bottom:14px; border-radius:4px;">'
            f'<div style="font-weight:700; color:#1e3a8a; margin-bottom:6px; font-size:14px;">'
            f'&#9993; Mail Lead &mdash; {years}y held &mdash; print &amp; mail this one</div>'
            f'<div style="font-size:13px;">{letter_html}</div>'
            '</div>'
        )

    if lead_type == LOW_PRIORITY:
        return (
            '<div style="background:#f9fafb; border-left:4px solid #d1d5db; padding:10px 14px; '
            'margin-bottom:14px; border-radius:4px;">'
            '<div style="font-weight:700; color:#4b5563; font-size:13px;">'
            f'&#8675; Low Priority &mdash; {years}y held (recently acquired, low motivation likely)'
            '</div></div>'
        )

    # UNKNOWN_TENURE
    return (
        '<div style="background:#fffbeb; border-left:4px solid #d97706; padding:10px 14px; '
        'margin-bottom:14px; border-radius:4px;">'
        '<div style="font-weight:700; color:#92400e; font-size:13px;">'
        '&#63; Unknown Tenure &mdash; no sale history in this county\'s GIS layer. '
        'Review manually to decide whether to skip trace or mail.'
        '</div></div>'
    )


def _deal_score(deal):
    """Transparent heuristic for 'best deal of the day' -- not a valuation.
    Rewards higher estimated value plus the same three signals badged above
    (low flood/wetlands risk, motivated seller); a lead missing ownership
    history just doesn't get that bonus, it isn't penalized for unknown."""
    lead = deal["land_lead"]
    enrichment_data = deal["enrichment"]
    score = lead.estimated_value
    if enrichment_data["flood_risk"] != "high":
        score += 20000
    if not enrichment_data["wetlands_present"]:
        score += 20000
    if lead.years_owned is not None and lead.years_owned >= MOTIVATED_SELLER_YEARS:
        score += 30000
    return score


def _format_date(run_label):
    try:
        return datetime.date.fromisoformat(run_label).strftime("%B %d, %Y")
    except (TypeError, ValueError):
        return run_label or ""


def _property_card_html(deal):
    """Bare-facts card for skip_builder_matching markets (Medina/Atascosa
    Counties TX, added 2026-06-24) -- the user already has a direct buyer
    there, so there's no pitch or contract draft, just the property facts.
    Deliberately mirrors _deal_card_html's h2-title + row-table styling for
    visual consistency with the rest of the digest (no badges/buyer-box/
    pitch/contract sections, since none of that applies here). lead.
    property_address doesn't include state/zip on its own (matches every
    other market's convention) -- appended here so the address is complete
    enough to hand straight to a buyer."""
    lead = deal["land_lead"]
    enrichment_data = deal["enrichment"]
    full_address = f"{lead.property_address}, {lead.state} {lead.zip}"
    rows = [
        ("Acreage", f"{lead.acreage:g} acres"),
        ("Zoning", enrichment_data["zoning"]),
        ("Flood Zone", f"{enrichment_data['flood_zone']} ({enrichment_data['flood_risk']} risk)"),
        ("Wetlands", "Present" if enrichment_data["wetlands_present"] else "Not present"),
        ("Assessed Value", f"${lead.assessed_value:,.0f}"),
        ("Owner", lead.owner_name),
    ]
    rows_html = "".join(
        f'<tr style="background:{"#f9fafb" if i % 2 == 0 else "#ffffff"};">'
        f'<td style="padding:7px 12px; font-weight:600; width:170px; font-size:13px;">{label}</td>'
        f'<td style="padding:7px 12px; font-size:13px;">{value}</td></tr>'
        for i, (label, value) in enumerate(rows)
    )
    return f"""
    <div style="border:1px solid #e5e7eb; border-radius:10px; padding:20px; margin-bottom:24px; background:#ffffff;">
      <h2 style="margin:0 0 10px 0; font-size:19px; color:#111827;">{full_address}</h2>
      {_lead_type_box(deal)}
      <table style="border-collapse:collapse; width:100%;">{rows_html}</table>
    </div>
    """


def _deal_card_html(deal):
    if "builder" not in deal:
        return _property_card_html(deal)
    lead = deal["land_lead"]
    enrichment_data = deal["enrichment"]
    builder = deal["builder"]
    sale_known = bool(lead.last_sale_date) and lead.last_sale_date != "unknown"
    years_held_html = f"{lead.years_owned} years" if sale_known else "not available"
    last_sale_html = (
        f"${lead.last_sale_price:,.0f} on {lead.last_sale_date}" if sale_known
        else "not available from this data source"
    )
    badges = _flood_badge(enrichment_data) + _wetlands_badge(enrichment_data) + _motivated_seller_badge(lead)
    rows = [
        ("Acreage", lead.acreage),
        ("Zoning", enrichment_data["zoning"]),
        ("Flood Zone", f"{enrichment_data['flood_zone']} ({enrichment_data['flood_risk']} risk)"),
        ("Wetlands", "Present" if enrichment_data["wetlands_present"] else "Not present"),
        ("Owner", lead.owner_name),
        ("Years Held", years_held_html),
        ("Last Sale", last_sale_html),
        ("Assessed / Estimated Value", f"${lead.assessed_value:,.0f} / ${lead.estimated_value:,.0f}"),
    ]
    rows_html = "".join(
        f'<tr style="background:{"#f9fafb" if i % 2 == 0 else "#ffffff"};">'
        f'<td style="padding:7px 12px; font-weight:600; width:170px; font-size:13px;">{label}</td>'
        f'<td style="padding:7px 12px; font-size:13px;">{value}</td></tr>'
        for i, (label, value) in enumerate(rows)
    )
    return f"""
    <div style="border:1px solid #e5e7eb; border-radius:10px; padding:20px; margin-bottom:24px; background:#ffffff;">
      <h2 style="margin:0 0 10px 0; font-size:19px; color:#111827;">{lead.property_address}</h2>
      {_lead_type_box(deal)}
      <div style="margin-bottom:14px;">{badges}</div>
      <table style="border-collapse:collapse; width:100%; margin-bottom:14px;">{rows_html}</table>
      <div style="background:#f0f9ff; border-left:4px solid #0284c7; padding:10px 14px; margin-bottom:14px; border-radius:4px;">
        <div style="font-weight:700; color:#0c4a6e; margin-bottom:4px; font-size:14px;">Matched Buyer: {builder.builder_name}</div>
        <div style="font-size:13px; color:#334155;">{deal['fit_reason']}</div>
      </div>
      <div style="background:#fefce8; border:1px dashed #ca8a04; padding:12px 14px; margin-bottom:14px; border-radius:6px;">
        <div style="font-weight:700; color:#854d0e; margin-bottom:6px; font-size:13px;">&#9993; Drafted Pitch -- ready to copy &amp; send</div>
        <div style="font-size:14px; color:#1e293b; white-space:pre-wrap;">{deal['pitch']}</div>
      </div>
      <details style="margin-bottom:8px;">
        <summary style="cursor:pointer; font-weight:600; color:#0f172a; font-size:13px;">&#128196; Draft Purchase Agreement (attorney review required)</summary>
        <pre style="white-space:pre-wrap; font-size:11px; background:#f8fafc; padding:10px; border-radius:4px;">{deal['purchase_agreement']}</pre>
      </details>
      <details>
        <summary style="cursor:pointer; font-weight:600; color:#0f172a; font-size:13px;">&#128196; Draft Assignment of Contract (attorney review required)</summary>
        <pre style="white-space:pre-wrap; font-size:11px; background:#f8fafc; padding:10px; border-radius:4px;">{deal['assignment_contract']}</pre>
      </details>
    </div>
    """


_TIER_ORDER = [PHONE_LEAD, MAIL_LEAD, LOW_PRIORITY, UNKNOWN_TENURE]
_TIER_HEADER = {
    PHONE_LEAD:     ("&#128222; Phone Leads", "#f0fdf4", "#15803d"),
    MAIL_LEAD:      ("&#9993; Mail Leads",    "#eff6ff", "#1e3a8a"),
    LOW_PRIORITY:   ("&#8675; Low Priority",  "#f9fafb", "#4b5563"),
    UNKNOWN_TENURE: ("&#63; Unknown Tenure",  "#fffbeb", "#92400e"),
}


def _tier_counts_badge(deals):
    from collections import Counter
    counts = Counter(d.get("lead_type", UNKNOWN_TENURE) for d in deals)
    parts = []
    icons = {PHONE_LEAD: "&#128222;", MAIL_LEAD: "&#9993;", LOW_PRIORITY: "&#8675;", UNKNOWN_TENURE: "&#63;"}
    for tier in _TIER_ORDER:
        if counts.get(tier):
            parts.append(f"{icons[tier]}&nbsp;{counts[tier]}")
    return " &middot; ".join(parts) if parts else "0"


def _market_section_html(market, deals, unmatched_count):
    if not deals:
        cards_html = '<p style="color:#6b7280; font-size:13px;">No leads this run.</p>'
    else:
        # Group by lead type, render each tier with a subsection header.
        by_tier = {t: [] for t in _TIER_ORDER}
        for d in deals:
            by_tier.setdefault(d.get("lead_type", UNKNOWN_TENURE), []).append(d)

        sections = []
        for tier in _TIER_ORDER:
            tier_deals = by_tier[tier]
            if not tier_deals:
                continue
            label, bg, fg = _TIER_HEADER[tier]
            header = (
                f'<div style="background:{bg}; color:{fg}; font-weight:700; font-size:13px; '
                f'padding:7px 12px; border-radius:6px; margin:18px 0 10px 0;">'
                f'{label} ({len(tier_deals)})</div>'
            )
            cards = "\n".join(_deal_card_html(d) for d in tier_deals)
            sections.append(header + cards)
        cards_html = "\n".join(sections)

    badge_text = (
        f"{len(deals)} lead(s) &middot; {_tier_counts_badge(deals)}" if market.skip_builder_matching
        else f"{len(deals)} deal(s) &middot; {unmatched_count} unmatched &middot; {_tier_counts_badge(deals)}"
    )
    return f"""
    <div style="margin-top:32px;">
      <div style="background:#111827; color:#ffffff; padding:12px 18px; border-radius:8px 8px 0 0;">
        <span style="font-size:16px; font-weight:700;">&#128205; {market.label}</span>
        <span style="float:right; font-size:12px; background:#374151; padding:4px 10px; border-radius:10px;">{badge_text}</span>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; border-radius:0 0 8px 8px; padding:18px; background:#f9fafb;">
        {cards_html}
      </div>
    </div>
    """


def _best_deal_html(market_results):
    all_deals = [(r["market"], d) for r in market_results for d in r["deals"]]
    if not all_deals:
        return ""
    best_market, best_deal = max(all_deals, key=lambda md: _deal_score(md[1]))
    return f"""
    <div style="margin-bottom:28px;">
      <div style="background:#f59e0b; color:#1f2937; padding:10px 18px; border-radius:8px 8px 0 0; font-weight:700; font-size:15px;">
        &#127942; Best Deal of the Day -- {best_market.label}
      </div>
      <div style="border:2px solid #f59e0b; border-top:none; border-radius:0 0 8px 8px; padding:4px;">
        {_deal_card_html(best_deal)}
      </div>
    </div>
    """


def _dashboard_html(market_results, skipped_markets, total_deals, total_unmatched):
    market_pills = "".join(
        '<div style="display:inline-block; background:#fff; border:1px solid #e5e7eb; '
        'border-radius:8px; padding:10px 16px; margin:0 8px 8px 0; text-align:center;">'
        f'<div style="font-size:22px; font-weight:700; color:#111827;">{len(r["deals"])}</div>'
        f'<div style="font-size:12px; color:#6b7280;">{r["market"].label}</div>'
        f'<div style="font-size:11px; color:#9ca3af; margin-top:3px;">{_tier_counts_badge(r["deals"])}</div>'
        '</div>'
        for r in market_results
    )
    skipped_pills = "".join(
        '<div style="display:inline-block; background:#fff; border:1px dashed #d1d5db; '
        'border-radius:8px; padding:10px 16px; margin:0 8px 8px 0; text-align:center;">'
        '<div style="font-size:22px; font-weight:700; color:#9ca3af;">&mdash;</div>'
        f'<div style="font-size:12px; color:#9ca3af;">{m.label} (skipped)</div></div>'
        for m in (skipped_markets or [])
    )
    return f"""
    <div style="background:#f3f4f6; border-radius:10px; padding:20px; margin-bottom:28px;">
      <div style="font-size:32px; font-weight:800; color:#111827;">{total_deals} Deals Found Today</div>
      <div style="font-size:13px; color:#6b7280; margin-bottom:14px;">{total_unmatched} lead(s) had no active-builder match this run.</div>
      <div>{market_pills}{skipped_pills}</div>
    </div>
    """


def _skipped_markets_html(skipped_markets):
    if not skipped_markets:
        return ""
    items = "\n".join(
        f"<li><b>{m.label}</b> -- no confirmed free permit source yet "
        f"(see PERMITS_CSV_PATH_{m.key} to override once you have a real export)</li>"
        for m in skipped_markets
    )
    return f"""
    <div style="background:#fff8e1; border:1px solid #e0c66b; border-radius:8px; padding:14px 18px; margin-bottom:20px;">
      <b>Skipped this run -- free permit areas only:</b>
      <ul style="margin:6px 0 0 0; font-size:13px;">{items}</ul>
    </div>
    """


def _low_inventory_html(low_inventory_results, candidate_markets):
    if not low_inventory_results:
        return ""
    low_items = "\n".join(
        f"<li><b>{r['market'].label}</b> -- only {len(r['deals'])} matched deal(s) this run</li>"
        for r in low_inventory_results
    )
    suggestion_items = "\n".join(
        f"<li><b>{c.label}</b> -- {c.note}<br>"
        f"<span style=\"font-size:12px; color:#555;\">Permits: {c.permit_source}</span><br>"
        f"<span style=\"font-size:12px; color:#555;\">GIS: {c.gis_source}</span></li>"
        for c in candidate_markets
    )
    return f"""
    <div style="background:#fdeaea; border:1px solid #d98c8c; border-radius:8px; padding:14px 18px; margin-bottom:20px;">
      <b>Running low -- consider adding a new market:</b>
      <ul style="margin:6px 0; font-size:13px;">{low_items}</ul>
      <p style="margin:10px 0 4px 0; font-size:13px;">Ask Claude Code to add one of these pre-vetted, free-permit-friendly
      markets to <code>markets.py</code>:</p>
      <ul style="margin:6px 0; font-size:13px;">{suggestion_items}</ul>
    </div>
    """


def send_digest_email(market_results, skipped_markets=None, low_inventory_results=None,
                       candidate_markets=None, run_label=""):
    """market_results: list of {"market": Market, "deals": [...], "unmatched_count": int},
    one entry per market run.py actually ran this pass -- all combined into one email.
    skipped_markets: Markets run.py declined to run because there's no confirmed free
    permit source for them (and no real CSV override was configured) -- surfaced here
    so a market silently missing from the digest is never a surprise.
    low_inventory_results: subset of market_results whose matched-deal count fell below
    run.py's LOW_INVENTORY_THRESHOLD this run -- paired with candidate_markets (pre-vetted,
    free-permit-friendly backup markets) so the alert always comes with concrete next steps.

    Returns True only on a confirmed successful send -- run.py uses this to decide
    whether to commit this run's leads to sent_log (never mark a lead as sent unless
    it actually went out)."""
    if not RESEND_API_KEY or not DIGEST_TO:
        print("  [EMAIL SKIPPED -- RESEND_API_KEY or DIGEST_TO not set]")
        return False

    total_deals = sum(len(r["deals"]) for r in market_results)
    total_unmatched = sum(r["unmatched_count"] for r in market_results)
    date_human = _format_date(run_label)
    sections_html = "\n".join(
        _market_section_html(r["market"], r["deals"], r["unmatched_count"])
        for r in market_results
    )
    html = f"""
    <html><body style="font-family:{FONT_STACK}; background:#f3f4f6; margin:0; padding:24px; color:#1f2937;">
      <div style="max-width:680px; margin:0 auto;">
        <h1 style="font-size:24px; margin:0 0 4px 0;">&#127968; Land Scout Daily Digest</h1>
        <div style="color:#6b7280; font-size:14px; margin-bottom:20px;">{date_human}</div>
        {_dashboard_html(market_results, skipped_markets, total_deals, total_unmatched)}
        {_best_deal_html(market_results)}
        {_skipped_markets_html(skipped_markets)}
        {_low_inventory_html(low_inventory_results, candidate_markets or [])}
        {sections_html}
        <p style="color:#9ca3af; font-size:11px; margin-top:30px; border-top:1px solid #e5e7eb; padding-top:14px;">
          All land data, builder data, and enrichment fields in this run were generated mock data unless real
          CSVs or a live free source were configured for that market -- verify before forwarding any of it to a buyer.
        </p>
      </div>
    </body></html>
    """

    subject = f"\U0001F3E1 Land Scout Daily Digest — {date_human} — {total_deals} Deals Found" if date_human \
        else f"\U0001F3E1 Land Scout Daily Digest — {total_deals} Deals Found"

    body = {
        "from": RESEND_FROM,
        "to": [DIGEST_TO],
        "subject": subject,
        "html": html,
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {RESEND_API_KEY}",
            "user-agent": "curl/8.4.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
        print(f"  [DIGEST EMAIL SENT -> {DIGEST_TO}]")
        return True
    except urllib.error.HTTPError as e:
        print(f"  [EMAIL FAILED: {e.code} {e.read().decode()}]")
        return False
