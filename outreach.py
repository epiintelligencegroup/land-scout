"""
Drafts a personalized outreach message to the property owner using Claude.
Called once per lead after dedup filtering so no API call is wasted on
properties that have already been sent.
"""
import json
import os
import urllib.error
import urllib.request

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap for bulk outreach drafts
_API_URL = "https://api.anthropic.com/v1/messages"


def draft_outreach(lead):
    """Return a ready-to-send letter/text to the owner. Falls back to a
    template string if the API key is not set or the call fails."""
    if not ANTHROPIC_API_KEY:
        return _fallback_outreach(lead)

    location_note = ""
    if lead.is_out_of_country:
        location_note = "The owner appears to be located outside the United States."
    elif lead.is_out_of_state:
        location_note = f"The owner is located out of state in {lead.owner_mailing_state}."

    prompt = f"""You are a real estate wholesaler writing a short, warm, professional outreach letter to a property owner. The goal is to express genuine interest in buying their property as-is for cash — no repairs, no agents, fast closing.

Property details:
- Address: {lead.full_property_address}
- Owner name: {lead.owner_name}
- Years they have owned the property: {lead.years_owned} years
- Year the house was built: {lead.year_built}
- Assessed value: ${lead.assessed_value:,.0f}
- Our suggested opening offer: ${lead.opening_offer:,.0f}
{location_note}

Write a concise outreach message (3–4 short paragraphs). Do not use high-pressure sales language. Address the owner by their last name if it is clearly a personal name. Mention that we buy as-is, pay cash, and can close on their timeline. Keep it under 200 words. No subject line, no headers — just the message body."""

    body = {
        "model": _MODEL,
        "max_tokens": 350,
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
    last_name = lead.owner_name.split()[-1].title() if lead.owner_name else "there"
    return (
        f"Dear {last_name},\n\n"
        f"My name is Ahmaad Piper and I am a local real estate investor. "
        f"I noticed you have owned the property at {lead.full_property_address} "
        f"for approximately {lead.years_owned} years and wanted to reach out personally.\n\n"
        f"I am interested in purchasing your property as-is for cash — no repairs, "
        f"no real estate agents, no fees. We can close on a timeline that works for you. "
        f"Our starting offer is ${lead.opening_offer:,.0f}, but I am happy to talk through "
        f"the details at your convenience.\n\n"
        f"If you have any interest or questions, please feel free to contact me directly. "
        f"I look forward to hearing from you.\n\n"
        f"Respectfully,\nAhmaad Piper\nepiintelligencegroup@gmail.com"
    )
