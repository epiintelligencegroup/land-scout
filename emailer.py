"""
Sends the House Wholesale Daily Digest via Resend.

One email covers all markets. Sections per market contain lead cards
(color-coded by motivation score and owner location) followed by a cash
buyer panel for that market. All styling is inline — Gmail strips <head>.
"""
import datetime
import json
import os
import urllib.error
import urllib.request

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM", "House Wholesale <onboarding@resend.dev>")
DIGEST_TO = os.environ.get("DIGEST_TO")

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"


# ─── Badges ──────────────────────────────────────────────────────────────────

def _badge(label, bg, fg):
    return (
        f'<span style="display:inline-block; background:{bg}; color:{fg}; '
        f'font-size:11px; font-weight:700; padding:4px 10px; border-radius:12px; '
        f'margin:0 6px 6px 0;">{label}</span>'
    )


def _score_badge(score):
    if score >= 8:
        bg, fg = "#dc2626", "#ffffff"
    elif score >= 6:
        bg, fg = "#ea580c", "#ffffff"
    elif score >= 4:
        bg, fg = "#ca8a04", "#1f2937"
    else:
        bg, fg = "#6b7280", "#ffffff"
    return _badge(f"Motivation {score}/10", bg, fg)


def _location_badge(lead):
    if lead.is_out_of_country:
        return _badge("&#127758; Out of Country — Extremely Motivated", "#7c3aed", "#ffffff")
    if lead.is_out_of_state:
        return _badge(f"&#11088; Out of State ({lead.owner_mailing_state})", "#1d4ed8", "#ffffff")
    return _badge("Absentee Owner", "#065f46", "#ffffff")


def _year_badge(year_built):
    if year_built < 1960:
        return _badge(f"Built {year_built} (pre-1960)", "#78350f", "#fef3c7")
    if year_built < 1970:
        return _badge(f"Built {year_built} (1960s)", "#92400e", "#fffbeb")
    if year_built < 1980:
        return _badge(f"Built {year_built} (1970s)", "#374151", "#f3f4f6")
    return _badge(f"Built {year_built}", "#374151", "#f3f4f6")


# ─── Lead card ───────────────────────────────────────────────────────────────

def _lead_card_html(deal):
    lead = deal["lead"]
    outreach = deal["outreach"]
    score = lead.motivation_score

    # Card border color by score
    if score >= 8:
        border_color = "#dc2626"
    elif score >= 6:
        border_color = "#ea580c"
    elif score >= 4:
        border_color = "#ca8a04"
    else:
        border_color = "#d1d5db"

    # Header flag
    if lead.is_out_of_country:
        flag = "&#127758; OUT OF COUNTRY OWNER — EXTREMELY MOTIVATED"
        flag_bg = "#7c3aed"
        flag_fg = "#ffffff"
    elif lead.is_out_of_state:
        flag = f"&#11088; OUT OF STATE OWNER ({lead.owner_mailing_state}) — HIGHEST PRIORITY"
        flag_bg = "#1d4ed8"
        flag_fg = "#ffffff"
    else:
        flag = "ABSENTEE OWNER"
        flag_bg = "#065f46"
        flag_fg = "#ffffff"

    badges = _score_badge(score) + _location_badge(lead) + _year_badge(lead.year_built)

    rows = [
        ("Owner", lead.owner_name),
        ("Owner Mailing Address", lead.full_mailing_address),
        ("Years Owned", f"{lead.years_owned} years (since ~{datetime.date.today().year - lead.years_owned})"),
        ("Year Built", str(lead.year_built)),
        ("Assessed Value", f"${lead.assessed_value:,.0f}"),
        ("Suggested Opening Offer", f"<b style='color:#15803d;'>${lead.opening_offer:,.0f}</b> (60% of assessed)"),
    ]
    rows_html = "".join(
        f'<tr style="background:{"#f9fafb" if i % 2 == 0 else "#ffffff"};">'
        f'<td style="padding:7px 12px; font-weight:600; width:200px; font-size:13px; color:#374151;">{label}</td>'
        f'<td style="padding:7px 12px; font-size:13px;">{value}</td></tr>'
        for i, (label, value) in enumerate(rows)
    )

    return f"""
    <div style="border:2px solid {border_color}; border-radius:10px; margin-bottom:24px; background:#ffffff; overflow:hidden;">
      <div style="background:{flag_bg}; color:{flag_fg}; padding:8px 16px; font-size:12px; font-weight:700; letter-spacing:0.05em;">
        {flag}
      </div>
      <div style="padding:18px 20px;">
        <h2 style="margin:0 0 10px 0; font-size:18px; color:#111827;">{lead.full_property_address}</h2>
        <div style="margin-bottom:12px;">{badges}</div>
        <table style="border-collapse:collapse; width:100%; margin-bottom:16px;">{rows_html}</table>
        <div style="background:#fefce8; border-left:4px solid #ca8a04; padding:12px 14px; border-radius:4px;">
          <div style="font-weight:700; color:#854d0e; margin-bottom:8px; font-size:13px;">
            &#9993; Drafted Outreach — ready to copy &amp; send
          </div>
          <div style="font-size:13px; color:#1e293b; white-space:pre-wrap; line-height:1.6;">{outreach}</div>
        </div>
      </div>
    </div>
    """


# ─── Cash buyer panel ─────────────────────────────────────────────────────────

def _buyer_row_html(buyer, idx):
    flipper_badge = (
        _badge("&#9889; Active Flipper — Closes Fast", "#059669", "#ffffff")
        if buyer.is_active_flipper else ""
    )
    zips_str = ", ".join(buyer.zip_codes_active[:5])
    bg = "#f0fdf4" if buyer.is_active_flipper else ("#f9fafb" if idx % 2 == 0 else "#ffffff")
    return (
        f'<tr style="background:{bg};">'
        f'<td style="padding:8px 12px; font-weight:600; font-size:13px;">'
        f'{buyer.name}<br><span style="font-weight:400; color:#6b7280; font-size:11px;">'
        f'{buyer.mailing_address}</span></td>'
        f'<td style="padding:8px 12px; text-align:center; font-size:13px;">{buyer.recent_purchases}</td>'
        f'<td style="padding:8px 12px; text-align:center; font-size:13px; font-weight:700;">'
        f'{buyer.two_year_purchases}</td>'
        f'<td style="padding:8px 12px; font-size:11px; color:#6b7280;">{zips_str}</td>'
        f'<td style="padding:8px 12px;">{flipper_badge}</td>'
        f'</tr>'
    )


def _cash_buyers_panel_html(buyers):
    if not buyers:
        return '<p style="color:#6b7280; font-size:13px;">No cash buyers identified this run.</p>'
    rows = "\n".join(_buyer_row_html(b, i) for i, b in enumerate(buyers))
    header_style = (
        "padding:8px 12px; font-size:11px; font-weight:700; color:#374151; "
        "background:#f3f4f6; text-transform:uppercase; letter-spacing:0.05em;"
    )
    return f"""
    <div style="margin-top:20px;">
      <div style="font-size:14px; font-weight:700; color:#1e3a8a; margin-bottom:8px;">
        &#128176; Cash Buyers in These Zip Codes
      </div>
      <table style="border-collapse:collapse; width:100%; font-size:13px;">
        <tr>
          <th style="{header_style} text-align:left;">Buyer</th>
          <th style="{header_style} text-align:center;">Last 12mo</th>
          <th style="{header_style} text-align:center;">Last 2yr</th>
          <th style="{header_style}">Active Zips</th>
          <th style="{header_style}">Flag</th>
        </tr>
        {rows}
      </table>
    </div>
    """


# ─── Market section ───────────────────────────────────────────────────────────

def _market_section_html(result):
    market = result["market"]
    deals = result["deals"]
    buyers = result["buyers"]
    active_flippers = sum(1 for b in buyers if b.is_active_flipper)

    if deals:
        cards_html = "\n".join(_lead_card_html(d) for d in deals)
    else:
        cards_html = '<p style="color:#6b7280; font-size:13px; padding:8px 0;">No fresh leads this run.</p>'

    return f"""
    <div style="margin-top:32px;">
      <div style="background:#111827; color:#ffffff; padding:12px 18px; border-radius:8px 8px 0 0;">
        <span style="font-size:16px; font-weight:700;">&#128205; {market.label}</span>
        <span style="float:right; font-size:12px; background:#374151; padding:4px 10px; border-radius:10px;">
          {len(deals)} lead(s) &middot; {len(buyers)} buyer(s) &middot; {active_flippers} flipper(s)
        </span>
      </div>
      <div style="border:1px solid #e5e7eb; border-top:none; border-radius:0 0 8px 8px; padding:18px; background:#f9fafb;">
        {cards_html}
        {_cash_buyers_panel_html(buyers)}
      </div>
    </div>
    """


# ─── Best deal of the day ─────────────────────────────────────────────────────

def _best_deal_html(market_results):
    all_pairs = [(r["market"], d) for r in market_results for d in r["deals"]]
    if not all_pairs:
        return ""
    best_market, best_deal = max(all_pairs, key=lambda md: md[1]["lead"].motivation_score)
    return f"""
    <div style="margin-bottom:28px;">
      <div style="background:#f59e0b; color:#1f2937; padding:10px 18px; border-radius:8px 8px 0 0;
                  font-weight:700; font-size:15px;">
        &#127942; Best Deal of the Day &mdash; {best_market.label}
      </div>
      <div style="border:2px solid #f59e0b; border-top:none; border-radius:0 0 8px 8px; padding:4px;">
        {_lead_card_html(best_deal)}
      </div>
    </div>
    """


# ─── Dashboard ───────────────────────────────────────────────────────────────

def _dashboard_html(market_results, total_deals):
    pills = "".join(
        '<div style="display:inline-block; background:#fff; border:1px solid #e5e7eb; '
        'border-radius:8px; padding:10px 16px; margin:0 8px 8px 0; text-align:center;">'
        f'<div style="font-size:22px; font-weight:700; color:#111827;">{len(r["deals"])}</div>'
        f'<div style="font-size:12px; color:#6b7280;">{r["market"].label}</div>'
        f'<div style="font-size:11px; color:#9ca3af; margin-top:3px;">'
        f'{sum(1 for b in r["buyers"] if b.is_active_flipper)} active flipper(s)</div>'
        '</div>'
        for r in market_results
    )
    return f"""
    <div style="background:#f3f4f6; border-radius:10px; padding:20px; margin-bottom:28px;">
      <div style="font-size:32px; font-weight:800; color:#111827;">{total_deals} Leads Found Today</div>
      <div style="font-size:13px; color:#6b7280; margin-bottom:14px;">
        Vacant house wholesale pipeline — individual absentee owners, 10+ years held, SFR pre-1990
      </div>
      <div>{pills}</div>
    </div>
    """


# ─── Legend ──────────────────────────────────────────────────────────────────

def _legend_html():
    return """
    <div style="background:#fff; border:1px solid #e5e7eb; border-radius:8px; padding:14px 18px; margin-bottom:20px;">
      <div style="font-weight:700; font-size:13px; color:#374151; margin-bottom:8px;">Score &amp; Flag Guide</div>
      <div style="font-size:12px; line-height:1.8;">
        <span style="display:inline-block; background:#dc2626; color:#fff; border-radius:6px; padding:2px 8px; margin-right:6px;">8-10</span> Extremely motivated &nbsp;|&nbsp;
        <span style="display:inline-block; background:#ea580c; color:#fff; border-radius:6px; padding:2px 8px; margin-right:6px;">6-7</span> Highly motivated &nbsp;|&nbsp;
        <span style="display:inline-block; background:#ca8a04; color:#1f2937; border-radius:6px; padding:2px 8px; margin-right:6px;">4-5</span> Motivated &nbsp;|&nbsp;
        <span style="display:inline-block; background:#6b7280; color:#fff; border-radius:6px; padding:2px 8px; margin-right:6px;">1-3</span> Standard<br>
        &#11088; Out of state owner — highest priority &nbsp;|&nbsp;
        &#127758; Out of country owner — extremely motivated
      </div>
    </div>
    """


# ─── Send ─────────────────────────────────────────────────────────────────────

def _format_date(run_label):
    try:
        return datetime.date.fromisoformat(run_label).strftime("%B %d, %Y")
    except (TypeError, ValueError):
        return run_label or ""


def send_digest_email(market_results, run_label=""):
    """Build and send the House Wholesale Daily Digest.
    Returns True only on confirmed send — run.py uses this to update sent_log."""
    if not RESEND_API_KEY or not DIGEST_TO:
        print("  [EMAIL SKIPPED — RESEND_API_KEY or DIGEST_TO not set]")
        return False

    total_deals = sum(len(r["deals"]) for r in market_results)
    date_human = _format_date(run_label)
    sections_html = "\n".join(_market_section_html(r) for r in market_results)

    html = f"""
    <html><body style="font-family:{FONT_STACK}; background:#f3f4f6; margin:0; padding:24px; color:#1f2937;">
      <div style="max-width:720px; margin:0 auto;">
        <h1 style="font-size:24px; margin:0 0 4px 0;">&#127968; House Wholesale Daily Digest</h1>
        <div style="color:#6b7280; font-size:14px; margin-bottom:20px;">{date_human}</div>
        {_dashboard_html(market_results, total_deals)}
        {_legend_html()}
        {_best_deal_html(market_results)}
        {sections_html}
        <p style="color:#9ca3af; font-size:11px; margin-top:30px; border-top:1px solid #e5e7eb; padding-top:14px;">
          Property data and cash buyer records are generated mock data unless a real county GIS source
          returned results or a CSV override (HOUSE_CSV_PATH_&lt;MARKET&gt;) was configured.
          Verify all values before contacting any owner or buyer.
        </p>
      </div>
    </body></html>
    """

    subject = (
        f"\U0001F3E0 House Wholesale Daily Digest — {date_human} — {total_deals} Leads"
        if date_human
        else f"\U0001F3E0 House Wholesale Daily Digest — {total_deals} Leads"
    )

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
