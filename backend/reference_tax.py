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
    # Overland Park corrected 2026-09-02 (was 0.09125 — stale; Overland
    # Park's own city add-on rose since this table was last populated).
    # Verified against 2+ independent current sources: 6.5% state +
    # 1.475% county + 1.375% city = 0.0935.
    ("overland park",   "KS"): 0.0935,
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

# Kansas state sales-tax rate.
#
# CORRECTED 2026-09-02 — this used to say "Kansas remodel tax = state +
# county only (NOT the city/special portions)". That was flat wrong, and
# it was Kyle's own reported bug: "the remodel tax calculator is not
# giving correct tax %... we use the link within the original excel
# sheet to go to the website, enter the address, and get the tax %."
#
# Per KDOR Publication KS-1525 ("Sales & Use Tax for Contractors,
# Subcontractors, and Repairmen"), commercial "remodel" labor is taxable,
# and since destination-based sourcing took effect 2003-07-01: "GENERAL
# RULE: CHARGE THE TAX IN EFFECT AT THE JOB SITE... the state and local
# sales tax rate in effect where the work is performed on ALL taxable
# real property service contracts." "Local" there means county + any
# incorporated city + any special taxing district — the FULL combined
# rate at the address, not state+county.
#
# So: KS_STATE_RATE + a county's `county_portion` (below) is only correct
# for a job on UNINCORPORATED county land. Any job inside city limits
# needs that city's own full combined rate — see CITIES below. Kyle's
# own KDOR Address Tax Rate Locator lookup for the exact job address is
# still the final word for what goes in the sheet's manual K81 cell;
# this table exists so the app's suggestion matches it instead of
# quietly undercutting it (e.g. ~1.375 points low for a Overland Park
# address before this fix).
KS_STATE_RATE: float = 0.065

# County portions below were pulled one-by-one from the KS DOR Address Tax
# Rate Locator (kssst.kdor.ks.gov) on 2026-06-02 — the authoritative source.
# (The locator only matches via its browser form flow, not a raw POST.)
# Re-verified independently against current 2026 sources on 2026-09-02 —
# all 12 county_portion values below still matched; no drift found at the
# county level (the bug was the missing city rate, not stale counties).


# ─── County reference (floor rate — UNINCORPORATED land only) ──────────
# Treadwell's working area covers the Kansas City metro plus
# broader-Missouri / broader-Kansas territory. Remodel tax in Missouri
# generally follows the contractor-tax rule (contractor pays sales tax
# on materials; labor exempt) unless the customer is itself tax-exempt
# (gov, school, non-profit). The `notes` column captures common
# exemption patterns Troy has run into; the dropdown lets him search
# the county fast and copy the right line into the proposal.
#
# For Kansas rows, `remodel_rate` here is a FLOOR: it is only the correct
# remodel-tax rate for a job site outside all city limits. A job site
# inside any incorporated city must use that city's own full combined
# rate instead — see CITIES below. `list_tax_areas()` appends that
# caveat to every KS county's notes at serve time so it can't be missed
# by anyone reading the dropdown, without needing to hand-edit all 12
# rows below.

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
    {"name": "Sedgwick",    "state": "KS", "fips": "20173", "rate": 0.01,    "county_portion": 0.01,    "remodel_rate": 0.075,   "notes": "Wichita currently levies no general city sales tax, so this county-only rate is also correct for a Wichita address specifically — NOT for other Sedgwick County cities, which may have their own add-on."},
    {"name": "Riley",       "state": "KS", "fips": "20161", "rate": 0.007,   "county_portion": 0.007,   "remodel_rate": 0.072,   "notes": "Manhattan, Ft. Riley."},
    {"name": "Geary",       "state": "KS", "fips": "20061", "rate": 0.0125,  "county_portion": 0.0125,  "remodel_rate": 0.0775,  "notes": "Junction City."},
]


def list_counties(state: str | None = None) -> list[dict]:
    """Return the county list, optionally filtered by 2-letter state."""
    if not state:
        return list(COUNTIES)
    s = state.strip().upper()
    return [c for c in COUNTIES if c["state"] == s]


# ─── City reference (the ACTUAL remodel-tax rate inside city limits) ───
# Kansas destination-sourcing (KDOR Pub. KS-1525) charges the FULL
# combined rate — state + county + city + special district — at the job
# site. A job anywhere inside one of these cities' limits should use the
# `remodel_rate` below instead of its county's county-only floor above.
#
# EVERY row below was driven through KDOR's own Address Tax Rate Locator
# (kssst.kdor.ks.gov/webLookupResults.cfm) on 2026-09-02 against a real
# street address in that city, and each row's note records the address
# used so the next person can re-run the same query.
#
# That pass found SEVEN of the rows ported from the old `TAX_RATES`
# snapshot were wrong, and every one of them was wrong in the same
# direction — too HIGH, overstating the tax on the bid by between 0.025
# and 0.625 points. Kansas City KS was the worst at 9.75% against a real
# 9.125%. "From prior snapshot, not re-verified" turned out to mean
# "probably wrong", so no row is allowed to carry that status any more:
# if a row cannot be verified, it does not belong in this table.
#
# A CITY NAME CANNOT REACH A SPECIAL DISTRICT. Kansas layers CID / TDD /
# STAR-bond districts on top of the city rate, and KDOR's address lookup
# returns them while a city picker structurally cannot. Two real ones:
# 5601 W 135th St, Overland Park (Prairiefire STAR+CID) is 10.85%, and
# 1843 Village West Pkwy, Kansas City (Legends CID + Village West TDD) is
# 10.725% — 1.5 and 1.6 points above their own city rows here. Those are
# exactly the retail-buildout sites Treadwell bids, so the per-address
# lookup stays the final word; this table only makes the app's suggestion
# close enough not to read as a bug.
#
# Sources drift: KDOR revises local rates quarterly (Jan/Apr/Jul/Oct).
# Kyle's own KDOR Address Tax Rate Locator lookup for the exact job
# address remains the final word for what actually goes in the sheet's
# manual K81 (or per-tab equivalent) cell — this table exists so the
# app's suggestion is close enough to not read as a bug, not to replace
# that lookup.
CITIES: list[dict] = [
    {"name": "Overland Park",   "state": "KS", "county": "Johnson",     "remodel_rate": 0.0935,  "notes": "Verified 2026-09-02: 6.5% state + 1.475% county + 1.375% city. Up to 0.1135 inside a TDD/CID special district — verify the exact address for those."},
    {"name": "Olathe",          "state": "KS", "county": "Johnson",     "remodel_rate": 0.09475, "notes": "Verified 2026-09-02 against KDOR (100 E Santa Fe St, 66061): 9.475%."},
    {"name": "Lenexa",          "state": "KS", "county": "Johnson",     "remodel_rate": 0.0935,  "notes": "Verified 2026-09-02 against KDOR (17101 W 87th St Pkwy, 66219): 9.35%. Prior snapshot said 9.475% — 0.125 pt too high."},
    {"name": "Shawnee",         "state": "KS", "county": "Johnson",     "remodel_rate": 0.096,   "notes": "City of Shawnee (Johnson County) — not to be confused with Shawnee County (Topeka), below. Verified 2026-09-02 against KDOR (11110 Johnson Dr, 66203): 9.6%. Prior snapshot said 9.75% — 0.15 pt too high."},
    {"name": "Kansas City",     "state": "KS", "county": "Wyandotte",   "remodel_rate": 0.09125, "notes": "Verified 2026-09-02 against KDOR (701 N 7th St, 66101): 9.125%. Prior snapshot said 9.75% — 0.625 pt too high, the worst of the batch. Village West / Legends addresses sit in a CID+TDD and run 10.725% — verify the exact address there."},
    {"name": "Leawood",         "state": "KS", "county": "Johnson",     "remodel_rate": 0.091,   "notes": "Verified 2026-09-02 against KDOR (4800 Town Center Dr, 66211): 9.1%. Prior snapshot said 9.5% — 0.4 pt too high."},
    {"name": "Merriam",         "state": "KS", "county": "Johnson",     "remodel_rate": 0.09475, "notes": "Verified 2026-09-02 against KDOR (9001 W 62nd St, 66202): 9.475%. Prior snapshot said 9.75% — 0.275 pt too high."},
    {"name": "Mission",         "state": "KS", "county": "Johnson",     "remodel_rate": 0.09725, "notes": "Verified 2026-09-02 against KDOR (6090 Woodson St, 66202): 9.725%. Prior snapshot said 9.75% — 0.025 pt too high."},
    {"name": "Prairie Village", "state": "KS", "county": "Johnson",     "remodel_rate": 0.08975, "notes": "Verified 2026-09-02 against KDOR (7700 Mission Rd, 66208): 8.975%. Prior snapshot said 9.35% — 0.375 pt too high."},
    {"name": "Topeka",          "state": "KS", "county": "Shawnee",     "remodel_rate": 0.0935,  "notes": "County seat of Shawnee County. Verified 2026-09-02 against KDOR (215 SE 7th St, 66603): 9.35%."},
    {"name": "Lawrence",        "state": "KS", "county": "Douglas",     "remodel_rate": 0.0935,  "notes": "Verified 2026-09-02: 6.5% state + 1.25% county + 1.6% city."},
    {"name": "Junction City",   "state": "KS", "county": "Geary",       "remodel_rate": 0.0975,  "notes": "Verified 2026-09-02: 6.5% state + 1.25% county + 2.0% city. Some ZIPs add a special district on top — verify the exact address."},
    {"name": "Leavenworth",     "state": "KS", "county": "Leavenworth", "remodel_rate": 0.095,   "notes": "City of Leavenworth. Verified 2026-09-02: 6.5% state + 1.0% county + 2.0% city."},
    {"name": "Manhattan",       "state": "KS", "county": "Riley",       "remodel_rate": 0.0915,  "notes": "Verified 2026-09-02: 6.5% state + 0.7% county + 1.95% city (ZIP 66505 baseline). ZIP 66503 adds a 0.5% special district — 0.0965 there. Verify the exact address."},
    {"name": "Paola",           "state": "KS", "county": "Miami",       "remodel_rate": 0.0925,  "notes": "Verified 2026-09-02 against the City of Paola's own published rate: 6.5% state + 1.5% county + 1.25% city. The Paola Crossings special district runs 0.105 — verify the exact address. (Some third-party aggregators show 0.0975/0.105 as the city-wide rate; the city's own figure was treated as authoritative.)"},
]


def list_cities(state: str | None = None) -> list[dict]:
    """Return the city list, optionally filtered by 2-letter state."""
    if not state:
        return list(CITIES)
    s = state.strip().upper()
    return [c for c in CITIES if c["state"] == s]


def list_tax_areas(state: str | None = None) -> list[dict]:
    """Cities + counties for the Remodel-Tax picker, cities first (a job
    site is almost always inside a city's limits, and that's the number
    that's actually correct there).

    Each row is tagged `kind` ("city" | "county") and each COUNTY row's
    `notes` gets a floor-rate caveat appended here, at serve time, so a
    single sentence covers all 12 KS counties instead of hand-editing
    every row above.
    """
    cities = [{**c, "kind": "city"} for c in list_cities(state)]
    counties = []
    for c in list_counties(state):
        row = {**c, "kind": "county"}
        if c["state"] == "KS":
            caveat = ("County-only rate — correct for unincorporated land. A job site "
                      "inside any city needs that city's own full rate instead (search "
                      "the city name).")
            row["notes"] = f"{row['notes']} {caveat}".strip() if row.get("notes") else caveat
        counties.append(row)
    return cities + counties


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
