"""
Drafts a short, direct email for each lead that Ahmaad can copy and send.
Format: Subject line + body. No formal letter language, no "Dear Mr/Mrs".
"""
import json
import os
import urllib.request

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
_MODEL = "claude-haiku-4-5-20251001"
_API_URL = "https://api.anthropic.com/v1/messages"


def _first_name(owner_name: str) -> str:
    """Extract a usable first name from a county-format owner name.

    County assessor records almost always store names as 'LASTNAME FIRSTNAME'.
    For joint owners ('A & B'), strip the secondary owner first.
    """
    import re as _re
    clean = _re.sub(r"\s+(ET\s+AL|FAMILY|TRUST|TR)\b.*$", "", owner_name, flags=_re.IGNORECASE).strip()
    clean = _re.sub(r"\s*&.*$", "", clean).strip()
    parts = clean.split()
    if len(parts) >= 2:
        return parts[1].title()
    return parts[0].title() if parts else "there"


def draft_outreach(lead):
    """Return a ready-to-copy email (subject + body) for the lead owner.
    Falls back to a template if the API key is not set or the call fails."""
    if not ANTHROPIC_API_KEY:
        return _fallback_outreach(lead)

    first_name = _first_name(lead.owner_name)

    prompt = f"""Write a short, friendly, professional email from Ahmaad Piper at EPI Intelligence Group to a property owner. Under 150 words total including the subject line.

Property: {lead.full_property_address}
Owner first name to use in greeting: {first_name}
Cash offer: ${lead.opening_offer:,.0f}

Output only the subject line and body — exactly this format, no extras:

Subject: Cash Offer for Your Property at {lead.property_address}

Hi {first_name},

[2–3 sentences: Ahmaad Piper / EPI Intelligence Group, we buy homes as-is for cash no repairs needed, offer is ${lead.opening_offer:,.0f}, no obligations]

[1 sentence: invite a call or reply]

Best,
Ahmaad Piper
EPI Intelligence Group
epiintelligencegroup@gmail.com

Tone rules: no "Dear Mr/Mrs", no formal language, warm and direct. Do not add a phone number."""

    body = {
        "model": _MODEL,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        _API_URL,
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "user-agent": "HouseWholesalePipeline/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result["content"][0]["text"].strip()
    except Exception as exc:
        print(f"  [OUTREACH] Claude call failed for {lead.apn} ({exc}), using template")
        return _fallback_outreach(lead)


def _fallback_outreach(lead):
    first_name = _first_name(lead.owner_name)
    return (
        f"Subject: Cash Offer for Your Property at {lead.property_address}\n\n"
        f"Hi {first_name},\n\n"
        f"My name is Ahmaad Piper with EPI Intelligence Group. I came across your property at "
        f"{lead.full_property_address} and wanted to reach out directly.\n\n"
        f"We specialize in buying homes as-is for cash — no repairs needed, no agents, no fees, "
        f"and no lengthy closing process. We can close on your timeline, whether that's 2 weeks "
        f"or 2 months. I'd like to make you a cash offer of ${lead.opening_offer:,.0f} for your "
        f"property. There are no obligations and no pressure — just a straightforward conversation.\n\n"
        f"If you're open to it, give me a call or reply to this email and we can discuss the details.\n\n"
        f"Best,\n"
        f"Ahmaad Piper\n"
        f"EPI Intelligence Group\n"
        f"epiintelligencegroup@gmail.com"
    )
