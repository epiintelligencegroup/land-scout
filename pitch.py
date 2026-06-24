"""
Drafts a buyer pitch message per matched deal using the Anthropic API --
same call pattern as Rolli's rolli_core.py:call_claude, just a one-shot
text completion instead of a tool-using conversation loop.
"""
import json
import os
import re
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
API_KEY = os.environ.get("ANTHROPIC_API_KEY")

SYSTEM_PROMPT = (
    "You write short, direct outreach messages from a land wholesaler to a home "
    "builder about a specific vacant lot that fits the builder's known buying "
    "pattern. Sound like a real investor texting another investor, not a "
    "marketing email: no exclamation-point hype, no markdown, 3-5 sentences. "
    "Lead with the address and price, mention why it fits them specifically "
    "(their permit activity in that zip), and end with a clear, low-pressure "
    "call to action to a callback number/email placeholder. Never invent "
    "facts beyond what's given."
)


def draft_pitch(land_lead, enrichment_data, builder, fit_reason):
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    if land_lead.last_sale_date and land_lead.last_sale_date != "unknown":
        ownership_line = (
            f"Owner has held it {land_lead.years_owned} years (last sale "
            f"${land_lead.last_sale_price:,.0f} on {land_lead.last_sale_date})\n"
        )
    else:
        # Some free data sources (e.g. Bexar's live GIS parcels layer) have no
        # sale-history fields -- say so rather than inventing $0/0-years, which
        # would misread as "just bought it," the opposite of unknown.
        ownership_line = "Ownership/sale history: not available from this data source\n"

    deal_facts = (
        f"Property: {land_lead.property_address}\n"
        f"Acreage: {land_lead.acreage}\n"
        f"Zoning: {enrichment_data['zoning']}\n"
        f"Flood zone: {enrichment_data['flood_zone']} ({enrichment_data['flood_risk']} risk)\n"
        f"Wetlands present: {enrichment_data['wetlands_present']}\n"
        f"Estimated value: ${land_lead.estimated_value:,.0f}\n"
        f"{ownership_line}"
        f"Target builder: {builder.builder_name}\n"
        f"Why this builder: {fit_reason}"
    )

    body = {
        "model": MODEL,
        "max_tokens": 300,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": deal_facts}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API error {e.code}: {e.read().decode()}")

    text = "".join(block["text"] for block in result["content"] if block["type"] == "text").strip()
    return re.sub(r"\*\*?|__?", "", text)  # model sometimes adds markdown despite the system prompt
