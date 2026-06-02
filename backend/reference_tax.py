"""
Sales-tax reference data for Treadwell's service area.

This is a server-side lookup table — NOT one of the visible sheets in
the Estimate Review. Used by `/api/reference/tax-rate` when the UI or
the autofill flow needs to suggest a sales-tax rate for a given
city/state.

Sources:
- Missouri DOR sales-tax-rate finder
- Kansas DOR rate tables
- City-specific add-ons compiled from Treadwell's recent jobs

Rates are total combined (state + county + city + special district)
as a decimal (e.g. 0.0975 = 9.75%). Keep the precision the source
publishes — do NOT round in display ([[feedback-treadwell-audit-grade]]).
"""
from __future__ import annotations

import re
from typing import Optional

# (city_lower, state_upper) → combined rate
TAX_RATES: dict[tuple[str, str], float] = {
    # Kansas City metro
    ("kansas city",     "MO"): 0.0975,
    ("independence",    "MO"): 0.0985,
    ("lees summit",     "MO"): 0.08975,
    ("blue springs",    "MO"): 0.09225,
    ("liberty",         "MO"): 0.09475,
    ("gladstone",       "MO"): 0.09475,
    ("north kansas city","MO"): 0.0825,
    ("riverside",       "MO"): 0.09475,
    ("raytown",         "MO"): 0.0935,
    ("grandview",       "MO"): 0.09975,
    ("belton",          "MO"): 0.0935,
    # Kansas side
    ("overland park",   "KS"): 0.09125,
    ("olathe",          "KS"): 0.09475,
    ("lenexa",          "KS"): 0.09475,
    ("shawnee",         "KS"): 0.0975,
    ("kansas city",     "KS"): 0.0975,
    ("leawood",         "KS"): 0.095,
    ("merriam",         "KS"): 0.0975,
    ("mission",         "KS"): 0.0975,
    ("prairie village", "KS"): 0.0935,
    # Greater area
    ("st joseph",       "MO"): 0.08825,
    ("topeka",          "KS"): 0.0935,
    ("lawrence",        "KS"): 0.0935,
}

# State default if no city match (state base + average local)
STATE_FALLBACK: dict[str, float] = {
    "MO": 0.0825,
    "KS": 0.0865,
}

# Kansas state sales-tax rate. Kansas "remodel tax" (sales tax on
# commercial remodel labor) = state + county only (NOT the city/special
# portions). So remodel_rate = KS_STATE_RATE + the county's portion.
KS_STATE_RATE: float = 0.065

# County portions below were pulled one-by-one from the KS DOR Address Tax
# Rate Locator (kssst.kdor.ks.gov) on 2026-06-02 — the authoritative source.
# (The locator only matches via its browser form flow, not a raw POST.)


# ─── County reference (for remodel-tax handling) ───────────────────────
# Treadwell's working area covers the Kansas City metro plus
# broader-Missouri / broader-Kansas territory. Remodel tax in Missouri
# generally follows the contractor-tax rule (contractor pays sales tax
# on materials; labor exempt) unless the customer is itself tax-exempt
# (gov, school, non-profit). The `notes` column captures common
# exemption patterns Troy has run into; the dropdown lets him search
# the county fast and copy the right line into the proposal.

COUNTIES: list[dict] = [
    # Missouri — KC metro core
    {"name": "Jackson",     "state": "MO", "fips": "29095", "rate": 0.06225, "notes": "KC metro core. Remodels for taxable-orgs: taxable. Gov/school: exempt."},
    {"name": "Clay",        "state": "MO", "fips": "29047", "rate": 0.06225, "notes": "Liberty, Gladstone. Standard MO contractor rule."},
    {"name": "Platte",      "state": "MO", "fips": "29165", "rate": 0.06225, "notes": "KCI, Parkville, Riverside."},
    {"name": "Cass",        "state": "MO", "fips": "29037", "rate": 0.06225, "notes": "Belton, Raymore, Harrisonville."},
    {"name": "Buchanan",    "state": "MO", "fips": "29021", "rate": 0.06225, "notes": "St. Joseph."},
    {"name": "Ray",         "state": "MO", "fips": "29177", "rate": 0.06225, "notes": "Richmond."},
    {"name": "Lafayette",   "state": "MO", "fips": "29107", "rate": 0.06225, "notes": "Higginsville, Lexington."},
    {"name": "Henry",       "state": "MO", "fips": "29083", "rate": 0.06225, "notes": "Clinton."},
    {"name": "Bates",       "state": "MO", "fips": "29013", "rate": 0.06225, "notes": "Butler."},
    {"name": "Caldwell",    "state": "MO", "fips": "29025", "rate": 0.06225, "notes": ""},
    {"name": "Clinton",     "state": "MO", "fips": "29049", "rate": 0.06225, "notes": ""},
    {"name": "DeKalb",      "state": "MO", "fips": "29063", "rate": 0.06225, "notes": ""},
    {"name": "Andrew",      "state": "MO", "fips": "29003", "rate": 0.06225, "notes": ""},
    {"name": "Johnson",     "state": "MO", "fips": "29101", "rate": 0.06225, "notes": "Warrensburg, Whiteman AFB."},
    {"name": "Saline",      "state": "MO", "fips": "29195", "rate": 0.06225, "notes": "Marshall."},
    {"name": "Boone",       "state": "MO", "fips": "29019", "rate": 0.06225, "notes": "Columbia."},
    {"name": "Cole",        "state": "MO", "fips": "29051", "rate": 0.06225, "notes": "Jefferson City."},
    {"name": "Greene",      "state": "MO", "fips": "29077", "rate": 0.06225, "notes": "Springfield."},
    {"name": "St. Louis",   "state": "MO", "fips": "29189", "rate": 0.06225, "notes": "STL metro."},
    {"name": "St. Charles", "state": "MO", "fips": "29183", "rate": 0.06225, "notes": ""},

    # Kansas — KC metro + east.
    # `county_portion` = the county's own sales-tax rate (from the KS DOR
    # locator). `remodel_rate` = KS_STATE_RATE + county_portion (what the KS
    # remodel tax actually is). `rate` kept = county_portion for the picker.
    {"name": "Johnson",     "state": "KS", "fips": "20091", "rate": 0.01475, "county_portion": 0.01475, "remodel_rate": 0.07975, "notes": "Overland Park, Olathe, Lenexa, Shawnee — high job density."},
    {"name": "Wyandotte",   "state": "KS", "fips": "20209", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": "KCK, Bonner Springs."},
    {"name": "Leavenworth", "state": "KS", "fips": "20103", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": "Leavenworth, FBOP facility."},
    {"name": "Miami",       "state": "KS", "fips": "20121", "rate": 0.015,   "county_portion": 0.015,   "remodel_rate": 0.08,    "notes": "Paola."},
    {"name": "Linn",        "state": "KS", "fips": "20107", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": ""},
    {"name": "Douglas",     "state": "KS", "fips": "20045", "rate": 0.0125,  "county_portion": 0.0125,  "remodel_rate": 0.0775,  "notes": "Lawrence, KU."},
    {"name": "Shawnee",     "state": "KS", "fips": "20177", "rate": 0.0135,  "county_portion": 0.0135,  "remodel_rate": 0.0785,  "notes": "Topeka."},
    {"name": "Atchison",    "state": "KS", "fips": "20005", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": ""},
    {"name": "Jefferson",   "state": "KS", "fips": "20087", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": ""},
    {"name": "Sedgwick",    "state": "KS", "fips": "20173", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": "Wichita."},
    {"name": "Riley",       "state": "KS", "fips": "20161", "rate": 0.007,   "county_portion": 0.007,   "remodel_rate": 0.072,   "notes": "Manhattan, Ft. Riley."},
    {"name": "Geary",       "state": "KS", "fips": "20061", "rate": 0.0125,  "county_portion": 0.0125,  "remodel_rate": 0.0775,  "notes": "Junction City."},
]


def list_counties(state: str | None = None) -> list[dict]:
    """Return the county list, optionally filtered by 2-letter state."""
    if not state:
        return list(COUNTIES)
    s = state.strip().upper()
    return [c for c in COUNTIES if c["state"] == s]


def lookup(city_state: str | None) -> dict:
    """Return a structured tax-rate result for a 'City, ST' input.

    Result shape:
        {"rate": 0.0975, "city": "Kansas City", "state": "MO",
         "source": "city" | "state_fallback" | "unknown"}
    """
    if not city_state:
        return {"rate": None, "source": "unknown"}

    # "Kansas City, MO" / "Olathe KS" / "kansas city, mo  "
    m = re.match(r"\s*(.+?)[\s,]+([A-Za-z]{2})\s*$", city_state.strip())
    if not m:
        return {"rate": None, "source": "unknown"}

    city = m.group(1).strip().lower()
    state = m.group(2).strip().upper()

    if (city, state) in TAX_RATES:
        return {
            "rate":   TAX_RATES[(city, state)],
            "city":   m.group(1).strip().title(),
            "state":  state,
            "source": "city",
        }

    if state in STATE_FALLBACK:
        return {
            "rate":   STATE_FALLBACK[state],
            "city":   m.group(1).strip().title(),
            "state":  state,
            "source": "state_fallback",
        }

    return {"rate": None, "source": "unknown"}
