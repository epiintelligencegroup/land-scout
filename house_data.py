"""HouseLead dataclass, filter logic, mock data generator, and CSV loader."""
import csv
import datetime
import random
import re
from dataclasses import dataclass

CURRENT_YEAR = datetime.date.today().year

# Whole-word patterns that disqualify an owner name as a non-individual entity.
# \b boundaries prevent partial matches (e.g. "INC" won't reject "PRINCE").
_NON_INDIVIDUAL_RE = re.compile(
    r"\b(?:LLC|INC(?:ORPORATED)?|CORP(?:ORATION)?|TRUST(?:EES?)?|TR|ESTATE[S]?"
    r"|HEIR[S]?|LP|LTD|HOLDINGS?|CO(?:MPANY)?|ASSOCIATION|HOA|REALTY|PROPERTIES"
    r"|INVESTMENTS?|PARTNERS?|BUILDERS?|HOMES|BANK|MORTGAGE|FUND)\b",
    re.IGNORECASE,
)

# US state abbreviations used to detect out-of-country mailing addresses
_US_STATE_ABBRS = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","VI","GU","MP","AS",
}


@dataclass
class HouseLead:
    apn: str
    property_address: str
    city: str
    state: str
    zip_code: str
    owner_name: str
    owner_mailing_address: str
    owner_mailing_city: str
    owner_mailing_state: str
    owner_mailing_zip: str
    year_built: int
    assessed_value: float
    improvement_value: float
    years_owned: int
    last_sale_date: str
    last_sale_price: float
    property_class: str = "SFR"

    @property
    def full_property_address(self):
        return f"{self.property_address}, {self.city}, {self.state} {self.zip_code}"

    @property
    def full_mailing_address(self):
        parts = [
            self.owner_mailing_address,
            self.owner_mailing_city,
            self.owner_mailing_state,
            self.owner_mailing_zip,
        ]
        return ", ".join(p for p in parts if p)

    @property
    def is_absentee(self):
        return (
            self.owner_mailing_address.upper().strip() != self.property_address.upper().strip()
            or self.owner_mailing_zip.strip() != self.zip_code.strip()
        )

    @property
    def is_out_of_state(self):
        return (
            self.owner_mailing_state.upper() not in ("", self.state.upper())
            and not self.is_out_of_country
        )

    @property
    def is_out_of_country(self):
        return self.owner_mailing_state.upper() not in _US_STATE_ABBRS

    @property
    def opening_offer(self):
        return round(self.assessed_value * 0.60, -2)

    @property
    def motivation_score(self):
        """1-10 score based on years held, owner location, and property age."""
        score = 0
        # Years held: 1-4 points
        if self.years_owned >= 30:
            score += 4
        elif self.years_owned >= 20:
            score += 3
        elif self.years_owned >= 15:
            score += 2
        else:
            score += 1  # 10-14 years
        # Owner location: 0-4 points
        if self.is_out_of_country:
            score += 4
        elif self.is_out_of_state:
            score += 3
        elif self.is_absentee:
            score += 1
        # Property age: 0-2 points
        if self.year_built < 1970:
            score += 2
        elif self.year_built < 1980:
            score += 1
        return max(1, min(10, score))


def _is_non_individual(name):
    return bool(_NON_INDIVIDUAL_RE.search(name))


def _passes_filters(row):
    """Return True if this row passes all required house wholesale filters."""
    name = (row.get("owner_name") or "").strip()

    # Individual owners only — no entities or excluded keywords
    if not name or _is_non_individual(name):
        return False

    # Full street address required (must start with a number)
    addr = (row.get("property_address") or "").strip()
    if not addr or not addr[:1].isdigit():
        return False

    # Single family residential only
    prop_class = (row.get("property_class") or "").upper().strip()
    if prop_class and not any(k in prop_class for k in ("SFR", "SINGLE", "RES", "R1", "SF", "01", "0100")):
        return False

    # Built before 1990
    try:
        year_built = int(row.get("year_built") or 0)
        if year_built < 1800 or year_built >= 1990:
            return False
    except (ValueError, TypeError):
        return False

    # Assessed value $50k-$300k
    try:
        assessed = float(row.get("assessed_value") or 0)
        if not (50000 <= assessed <= 300000):
            return False
    except (ValueError, TypeError):
        return False

    # Must have a structure (improvement value > 0)
    try:
        improvement = float(row.get("improvement_value") or 0)
        if improvement <= 0:
            return False
    except (ValueError, TypeError):
        return False

    # Owner held 10+ years
    try:
        years = int(row.get("years_owned") or 0)
        if years < 10:
            return False
    except (ValueError, TypeError):
        return False

    # Absentee: mailing address must differ from property address
    prop_addr = addr.upper()
    mail_addr = (row.get("owner_mailing_address") or "").upper().strip()
    prop_zip = (row.get("zip_code") or "").strip()
    mail_zip = (row.get("owner_mailing_zip") or "").strip()
    if prop_addr == mail_addr and prop_zip == mail_zip:
        return False

    # Skip tax liens / delinquent taxes
    if (row.get("tax_delinquent") or "").strip().upper() in ("YES", "Y", "TRUE", "1"):
        return False

    # Skip foreclosure and bank-owned
    if (row.get("in_foreclosure") or "").strip().upper() in ("YES", "Y", "TRUE", "1"):
        return False
    if (row.get("bank_owned") or "").strip().upper() in ("YES", "Y", "TRUE", "1"):
        return False

    return True


def load_house_leads(csv_path):
    leads = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not _passes_filters(row):
                continue
            leads.append(HouseLead(
                apn=row.get("apn", "").strip(),
                property_address=row.get("property_address", "").strip(),
                city=row.get("city", "").strip(),
                state=row.get("state", "").strip(),
                zip_code=row.get("zip_code", "").strip(),
                owner_name=row.get("owner_name", "").strip(),
                owner_mailing_address=row.get("owner_mailing_address", "").strip(),
                owner_mailing_city=row.get("owner_mailing_city", "").strip(),
                owner_mailing_state=row.get("owner_mailing_state", "").strip(),
                owner_mailing_zip=row.get("owner_mailing_zip", "").strip(),
                year_built=int(row.get("year_built") or 1970),
                assessed_value=float(row.get("assessed_value") or 0),
                improvement_value=float(row.get("improvement_value") or 0),
                years_owned=int(row.get("years_owned") or 0),
                last_sale_date=row.get("last_sale_date", ""),
                last_sale_price=float(row.get("last_sale_price") or 0),
                property_class=row.get("property_class", "SFR").strip(),
            ))
    return leads


_FIRST_NAMES = [
    "James", "Robert", "Patricia", "Linda", "Barbara", "William", "David",
    "Richard", "Mary", "Charles", "Michael", "Dorothy", "Helen", "Margaret",
    "Betty", "Ruth", "Gloria", "Eugene", "Harold", "Frances", "Shirley",
    "Walter", "Raymond", "Clarence", "Willie", "Ethel", "Annie", "Mildred",
]
_LAST_NAMES = [
    "Williams", "Johnson", "Brown", "Davis", "Wilson", "Moore", "Taylor",
    "Anderson", "Harris", "Thomas", "Jackson", "White", "Martin", "Garcia",
    "Thompson", "Robinson", "Lewis", "Walker", "Hall", "Young", "Allen",
    "King", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson", "Carter",
    "Mitchell", "Perez", "Roberts", "Turner", "Phillips", "Campbell", "Parker",
]
_STREET_NAMES = [
    "Oak", "Maple", "Cedar", "Elm", "Pine", "Willow", "Cherry", "Walnut",
    "Birch", "Poplar", "Highland", "Lincoln", "Madison", "Jefferson", "Adams",
    "Prospect", "Market", "Spring", "River", "Lake", "Forest", "Sunset",
    "Church", "Park", "Main", "Washington", "Franklin", "Grant", "Sherman",
]
_STREET_TYPES = ["St", "Ave", "Rd", "Blvd", "Dr", "Ln", "Way", "Ct", "Pl", "Ter"]

_NEIGHBOR_STATES = {
    "OH": ["PA", "WV", "KY", "IN", "MI"],
    "TN": ["GA", "AL", "MS", "AR", "KY", "MO", "NC", "VA"],
    "TX": ["LA", "AR", "OK", "NM", "CO"],
    "AL": ["GA", "TN", "MS", "FL"],
    "FL": ["GA", "AL", "NY", "NJ"],
}
_CITIES_BY_STATE = {
    "PA": ["Pittsburgh", "Philadelphia"], "WV": ["Charleston", "Huntington"],
    "KY": ["Louisville", "Lexington"], "IN": ["Indianapolis", "Fort Wayne"],
    "MI": ["Detroit", "Grand Rapids"], "GA": ["Atlanta", "Savannah"],
    "AL": ["Birmingham", "Montgomery"], "MS": ["Jackson", "Gulfport"],
    "AR": ["Little Rock", "Fort Smith"], "MO": ["Kansas City", "St. Louis"],
    "NC": ["Charlotte", "Raleigh"], "VA": ["Richmond", "Virginia Beach"],
    "LA": ["New Orleans", "Baton Rouge"], "OK": ["Oklahoma City", "Tulsa"],
    "NM": ["Albuquerque", "Santa Fe"], "CO": ["Denver", "Colorado Springs"],
    "FL": ["Miami", "Orlando", "Tampa"], "OH": ["Columbus", "Cincinnati"],
    "TN": ["Nashville", "Knoxville"], "TX": ["Dallas", "Austin"],
    "NY": ["New York", "Buffalo"], "NJ": ["Newark", "Jersey City"],
    "CA": ["Los Angeles", "San Diego"], "IL": ["Chicago", "Rockford"],
}


def generate_mock_house_leads(market, count=10):
    rng = random.Random(market.key + str(datetime.date.today()))
    leads = []
    for i in range(count):
        zip_code, city = rng.choice(market.zips)
        street_num = rng.randint(100, 9999)
        street = f"{street_num} {rng.choice(_STREET_NAMES)} {rng.choice(_STREET_TYPES)}"
        owner_name = f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"
        year_built = rng.randint(1945, 1989)
        assessed = rng.randint(55, 280) * 1000
        improvement = round(assessed * rng.uniform(0.6, 0.85), -2)
        years_owned = rng.randint(10, 42)
        last_sale_year = max(1980, CURRENT_YEAR - years_owned)
        last_sale_price = round(assessed * rng.uniform(0.25, 0.65), -2)

        roll = rng.random()
        if roll < 0.55:
            # Out of state mailing address
            neighbors = _NEIGHBOR_STATES.get(market.state, ["CA", "NY", "TX"])
            mail_state = rng.choice(neighbors)
            mail_city = rng.choice(_CITIES_BY_STATE.get(mail_state, ["Unknown City"]))
            mail_zip = f"{rng.randint(10000, 99999)}"
            mail_addr = f"{rng.randint(1, 9999)} {rng.choice(_STREET_NAMES)} {rng.choice(_STREET_TYPES)}"
        elif roll < 0.70:
            # Same state, different city
            mail_state = market.state
            state_cities = {"OH": "Columbus", "TN": "Nashville", "TX": "Dallas",
                            "AL": "Huntsville", "FL": "Tampa"}
            mail_city = state_cities.get(market.state, "Capitol City")
            mail_zip = f"{rng.randint(10000, 99999)}"
            mail_addr = f"{rng.randint(1, 9999)} {rng.choice(_STREET_NAMES)} {rng.choice(_STREET_TYPES)}"
        else:
            # Absentee same city, different address
            mail_state = market.state
            mail_city = city
            mail_zip = f"{rng.randint(10000, 99999)}"
            mail_addr = f"{rng.randint(10000, 99999)} {rng.choice(_STREET_NAMES)} {rng.choice(_STREET_TYPES)}"

        leads.append(HouseLead(
            apn=f"{market.key}-{str(i + 1).zfill(5)}",
            property_address=street,
            city=city,
            state=market.state,
            zip_code=zip_code,
            owner_name=owner_name,
            owner_mailing_address=mail_addr,
            owner_mailing_city=mail_city,
            owner_mailing_state=mail_state,
            owner_mailing_zip=mail_zip,
            year_built=year_built,
            assessed_value=float(assessed),
            improvement_value=float(improvement),
            years_owned=years_owned,
            last_sale_date=f"{last_sale_year}-06-15",
            last_sale_price=float(last_sale_price),
            property_class="SFR",
        ))
    return leads
