"""
Lead tenure tier classification.

Every land lead (after dedup and flood/LLC filtering) is assigned a lead_type
based on years_owned:
    PHONE_LEAD     -- 3-10 years held: skip trace via BatchData, call/text owner
    MAIL_LEAD      -- 10+ years held: generate direct mail letter, don't skip trace
    LOW_PRIORITY   -- under 3 years held: likely recent buyer, low motivation; include
                      in digest but sort to bottom
    UNKNOWN_TENURE -- years_owned is None (Bexar TX and Wake NC have no sale history
                      fields in their county GIS layers): show in digest, no auto action

Option A rationale: Option B (treat unknown as phone leads) risks burning BatchData
credits on people who may be long-term owners with low skip-trace success; Option C
(plain cards, no flag) hides the gap. Option A surfaces it so manual case-by-case
judgment can be applied -- will revisit once live deal experience in those markets
clarifies whether manual lookups tend to succeed or fail.
"""

PHONE_LEAD = "PHONE_LEAD"
MAIL_LEAD = "MAIL_LEAD"
LOW_PRIORITY = "LOW_PRIORITY"
UNKNOWN_TENURE = "UNKNOWN_TENURE"

PHONE_MIN_YEARS = 3
MAIL_MIN_YEARS = 10


def classify_lead(lead) -> str:
    if lead.years_owned is None:
        return UNKNOWN_TENURE
    if lead.years_owned < PHONE_MIN_YEARS:
        return LOW_PRIORITY
    if lead.years_owned < MAIL_MIN_YEARS:
        return PHONE_LEAD
    return MAIL_LEAD
