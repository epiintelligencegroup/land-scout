"""
Direct mail letter generator for MAIL_LEAD tier (10+ years tenure).

Generates one plain-text letter per lead, saved to letters/YYYY-MM-DD/
in the project directory. Letters are NOT emailed automatically -- the user
prints and mails them manually. The digest notes the filename for each
mail lead so the user knows what was generated.

Set WHOLESALER_PHONE and WHOLESALER_EMAIL in .env -- they appear in the
letter's closing. If not set, placeholders are printed so the letter is
still usable after manual fill-in.
"""
import datetime
import os
from typing import Optional

WHOLESALER_NAME = os.environ.get("WHOLESALER_NAME", "Ahmaad Piper")
WHOLESALER_PHONE = os.environ.get("WHOLESALER_PHONE", "")
WHOLESALER_EMAIL = os.environ.get("WHOLESALER_EMAIL", "")

_LETTERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "letters")

_TEMPLATE = """\
{date}

{owner_name}
{owner_mailing_address}


Re: Your Vacant Land at {property_address}, {city}, {state} {zip}

Dear {owner_first_name},

My name is {wholesaler_name}. I am a cash buyer and real estate investor
based locally. I came across your property at the address above and I am
interested in making you a straightforward cash offer.

I can close on your timeline -- whether that is two weeks or several months
from now -- with no contingencies, no repairs needed, and no real estate
agent commissions taken from your proceeds.

If you have ever considered selling this land, I would appreciate the chance
to speak with you briefly. There is no pressure and no obligation.

Please call or text me at {wholesaler_phone}, or reach me by email at
{wholesaler_email}. I respond promptly.

Thank you for your time.

Sincerely,

{wholesaler_name}
{wholesaler_phone}
{wholesaler_email}
"""


def generate_letter(lead, run_date: str) -> str:
    """Write a direct mail letter for a MAIL_LEAD and return its file path."""
    day_dir = os.path.join(_LETTERS_DIR, run_date)
    os.makedirs(day_dir, exist_ok=True)

    # First word of owner name as salutation (GIS names are ALL CAPS -- title-case them).
    owner_first = lead.owner_name.split()[0].capitalize() if lead.owner_name else "Property Owner"
    owner_name_display = lead.owner_name.title()

    # Strip embedded city from property_address if present (some markets append it).
    prop_street = lead.property_address.split(",")[0].strip().title()

    content = _TEMPLATE.format(
        date=datetime.date.fromisoformat(run_date).strftime("%B %d, %Y"),
        owner_name=owner_name_display,
        owner_mailing_address=lead.owner_mailing_address,
        property_address=prop_street,
        city=lead.city,
        state=lead.state,
        zip=lead.zip,
        owner_first_name=owner_first,
        wholesaler_name=WHOLESALER_NAME,
        wholesaler_phone=WHOLESALER_PHONE or "[YOUR PHONE NUMBER]",
        wholesaler_email=WHOLESALER_EMAIL or "[YOUR EMAIL ADDRESS]",
    )

    safe_apn = lead.apn.replace("/", "-").replace(" ", "_").replace("\\", "-")
    safe_county = lead.county.replace(" ", "_")
    filename = f"{safe_county}_{safe_apn}.txt"
    filepath = os.path.join(day_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath
