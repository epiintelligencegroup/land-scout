"""
Generates two DRAFT contract documents for a land wholesale deal in any of
the configured markets (markets.py): an assignable purchase agreement (you
and the seller) and a separate assignment-of-contract document (you handing
it to the end buyer for a fee). County/state get filled in per-deal from the
land lead -- the template language itself isn't state-specific beyond that.

These are deterministic string templates, not LLM-generated -- legal
documents should be consistent and reviewable, not improvised per-run.
THESE ARE DRAFTS ONLY. Real estate contract requirements vary by state and
this has not been reviewed by an attorney -- have one review and customize
this before using it in an actual transaction, in every market.
"""
from markets import STATE_NAMES


def _disclaimer(state_name):
    return (
        "*** DRAFT -- FOR REVIEW ONLY ***\n"
        "This is a template, not a finished legal document. It has not been\n"
        f"reviewed by a {state_name}-licensed real estate attorney. Have one\n"
        "review and customize this before using it in an actual transaction.\n"
    )

PURCHASE_AGREEMENT_TEMPLATE = """{disclaimer}
VACANT LAND PURCHASE AND SALE AGREEMENT

This Agreement is made as of {agreement_date}, between:

SELLER: {seller_name}
  Mailing address: {seller_mailing_address}

BUYER: {buyer_name} and/or assigns
  Address: {buyer_address}

1. PROPERTY. Seller agrees to sell and Buyer agrees to buy the vacant land
   located at {property_address}, {county} County, {state_name}, Parcel ID
   (APN) {apn}, together with all rights, easements, and appurtenances
   ("the Property"). [Insert full legal description before execution.]

2. PURCHASE PRICE. The total purchase price is ${purchase_price:,.0f},
   payable in cash at closing, subject to the terms below.

3. EARNEST MONEY. Buyer shall deposit ${earnest_money:,.0f} in earnest
   money within 3 business days of full execution, held in escrow by a
   licensed {state_name} title company or attorney pending closing.

4. INSPECTION PERIOD. Buyer shall have {inspection_days} days from full
   execution to inspect the Property, including title, zoning, utilities,
   flood zone, and wetlands status, and may terminate this Agreement for
   any reason during this period with a full refund of earnest money.

5. ASSIGNMENT. Buyer may assign this Agreement, in whole or in part, to
   any person or entity without Seller's further consent. Any assignee
   shall assume all of Buyer's rights and obligations hereunder.

6. CLOSING. Closing shall occur on or before {closing_date}, at a title
   company or attorney's office of Buyer's choosing, unless extended by
   mutual written agreement.

7. TITLE. Seller shall convey marketable title by general warranty deed,
   free of liens and encumbrances except those of record and acceptable
   to Buyer.

8. AS-IS. The Property is sold in its current "AS-IS" condition. Seller
   makes no warranties as to condition, zoning, or suitability for any
   particular use.

9. GOVERNING LAW. This Agreement is governed by the laws of the State of
   {state_name}.

SELLER: _________________________________  DATE: ____________
        {seller_name}

BUYER:  _________________________________  DATE: ____________
        {buyer_name}, and/or assigns
"""

ASSIGNMENT_TEMPLATE = """{disclaimer}
ASSIGNMENT OF REAL ESTATE PURCHASE AND SALE AGREEMENT

This Assignment is made as of {assignment_date}, between:

ASSIGNOR: {assignor_name}
ASSIGNEE: {assignee_name}
  Address: {assignee_address}

RECITALS

Assignor is the Buyer under that certain Vacant Land Purchase and Sale
Agreement dated {agreement_date} (the "Agreement") with {seller_name} as
Seller, for the property located at {property_address}, {county} County,
{state_name}, Parcel ID (APN) {apn}.

ASSIGNMENT

1. Assignor hereby assigns all of Assignor's rights, title, and interest
   in and to the Agreement to Assignee, who accepts the assignment and
   assumes all of Assignor's obligations under the Agreement.

2. ASSIGNMENT FEE. In consideration of this Assignment, Assignee shall
   pay Assignor an assignment fee of ${assignment_fee:,.0f}, due
   {fee_due_terms}.

3. Assignee shall close on the Agreement directly with Seller in
   accordance with its terms.

4. This Assignment is governed by the laws of the State of {state_name}.

ASSIGNOR: _________________________________  DATE: ____________
          {assignor_name}

ASSIGNEE: _________________________________  DATE: ____________
          {assignee_name}
"""


def fill_purchase_agreement(land_lead, buyer_name, buyer_address, purchase_price,
                             agreement_date, closing_date, earnest_money=100,
                             inspection_days=14):
    state_name = STATE_NAMES[land_lead.state]
    return PURCHASE_AGREEMENT_TEMPLATE.format(
        disclaimer=_disclaimer(state_name),
        agreement_date=agreement_date,
        seller_name=land_lead.owner_name,
        seller_mailing_address=land_lead.owner_mailing_address,
        buyer_name=buyer_name,
        buyer_address=buyer_address,
        property_address=land_lead.property_address,
        county=land_lead.county,
        state_name=state_name,
        apn=land_lead.apn,
        purchase_price=purchase_price,
        earnest_money=earnest_money,
        inspection_days=inspection_days,
        closing_date=closing_date,
    )


def fill_assignment_of_contract(land_lead, assignor_name, assignee_name, assignee_address,
                                 agreement_date, assignment_date, assignment_fee,
                                 fee_due_terms="at closing"):
    state_name = STATE_NAMES[land_lead.state]
    return ASSIGNMENT_TEMPLATE.format(
        disclaimer=_disclaimer(state_name),
        assignment_date=assignment_date,
        assignor_name=assignor_name,
        assignee_name=assignee_name,
        assignee_address=assignee_address,
        agreement_date=agreement_date,
        seller_name=land_lead.owner_name,
        property_address=land_lead.property_address,
        county=land_lead.county,
        state_name=state_name,
        apn=land_lead.apn,
        assignment_fee=assignment_fee,
        fee_due_terms=fee_due_terms,
    )
