"""Tests for backend/reference_tax.py — the Remodel-Tax picker data.

Written 2026-09-02 while fixing Kyle's reported bug ("the remodel tax
calculator is not giving correct tax %"). Root cause: Kansas destination
sourcing (KDOR Pub. KS-1525) requires the FULL combined rate (state + county
+ city + special district) at the job site for taxable remodel labor — the
app was only ever offering state+county, which is a floor rate correct for
unincorporated land only. These tests pin down:

  1. the Overland Park staleness fix (the concrete number Kyle would have hit)
  2. the new city/county merge (`list_tax_areas`) — ordering, `kind` tagging,
     state filtering, non-mutation of the source tables
  3. the KS-only floor-rate caveat getting appended to county notes at serve
     time (and NOT to Missouri counties, which have no such distinction)
  4. two internal-consistency invariants that would silently drift if someone
     edits one table and not the other: every KS county's
     `KS_STATE_RATE + county_portion == remodel_rate`, and every city's
     `remodel_rate` is at least as high as its parent county's floor.
"""
import reference_tax


# ─── Bug fix: Overland Park was stale ──────────────────────────────────────

def test_overland_park_lookup_is_corrected():
    """Kyle's exact complaint: the app's suggested % didn't match the KDOR
    locator. Overland Park was the concrete example (0.09125 stale ->
    0.0935 correct). Locked here so it can't silently regress back."""
    result = reference_tax.lookup("Overland Park, KS")
    assert result["rate"] == 0.0935
    assert result["source"] == "city"


def test_overland_park_city_row_matches_lookup():
    """The new CITIES-table row and the older TAX_RATES/lookup() path must
    agree — they're two different data sources for the same number."""
    rows = [c for c in reference_tax.CITIES if c["name"] == "Overland Park" and c["state"] == "KS"]
    assert len(rows) == 1
    assert rows[0]["remodel_rate"] == reference_tax.TAX_RATES[("overland park", "KS")]


# ─── list_tax_areas: ordering + kind tagging ───────────────────────────────

def test_list_tax_areas_cities_come_before_counties():
    areas = reference_tax.list_tax_areas("KS")
    kinds = [a["kind"] for a in areas]
    first_county_idx = kinds.index("county")
    # every "city" must appear before the first "county"
    assert all(k == "city" for k in kinds[:first_county_idx])
    assert all(k == "county" for k in kinds[first_county_idx:])


def test_list_tax_areas_every_row_tagged():
    areas = reference_tax.list_tax_areas()
    assert areas, "expected a non-empty combined list"
    for row in areas:
        assert row["kind"] in ("city", "county")


def test_list_tax_areas_counts_match_source_tables():
    ks_areas = reference_tax.list_tax_areas("KS")
    cities = [a for a in ks_areas if a["kind"] == "city"]
    counties = [a for a in ks_areas if a["kind"] == "county"]
    assert len(cities) == len(reference_tax.list_cities("KS"))
    assert len(counties) == len(reference_tax.list_counties("KS"))


def test_list_tax_areas_no_state_filter_includes_both_states():
    areas = reference_tax.list_tax_areas()
    states = {a["state"] for a in areas}
    assert states == {"KS", "MO"}


def test_list_tax_areas_does_not_mutate_source_tables():
    """`{**c, "kind": ...}` must copy, not mutate — calling this repeatedly,
    or calling list_cities/list_counties afterward, must never leak a `kind`
    key onto the module-level CITIES/COUNTIES lists."""
    reference_tax.list_tax_areas("KS")
    reference_tax.list_tax_areas("MO")
    for row in reference_tax.CITIES:
        assert "kind" not in row
    for row in reference_tax.COUNTIES:
        assert "kind" not in row


# ─── state filtering on the plain list_* helpers ───────────────────────────

def test_list_cities_state_filter():
    assert all(c["state"] == "KS" for c in reference_tax.list_cities("KS"))
    # every city in the table today is KS; MO has none yet.
    assert reference_tax.list_cities("MO") == []
    assert len(reference_tax.list_cities()) == len(reference_tax.CITIES)


def test_list_counties_state_filter():
    assert all(c["state"] == "KS" for c in reference_tax.list_counties("KS"))
    assert all(c["state"] == "MO" for c in reference_tax.list_counties("MO"))
    assert len(reference_tax.list_counties()) == len(reference_tax.COUNTIES)


def test_list_cities_state_filter_is_case_insensitive():
    assert reference_tax.list_cities("ks") == reference_tax.list_cities("KS")


# ─── the KS floor-rate caveat gets appended at serve time, KS only ─────────

def test_ks_county_notes_get_floor_rate_caveat():
    areas = reference_tax.list_tax_areas("KS")
    counties = [a for a in areas if a["kind"] == "county"]
    assert counties, "expected at least one KS county row"
    for row in counties:
        assert "unincorporated" in row["notes"]
        assert "search the city name" in row["notes"]


def test_mo_county_notes_do_not_get_the_ks_caveat():
    areas = reference_tax.list_tax_areas("MO")
    counties = [a for a in areas if a["kind"] == "county"]
    assert counties, "expected at least one MO county row"
    for row in counties:
        assert "unincorporated" not in row["notes"]


def test_caveat_injection_does_not_mutate_underlying_notes():
    """Calling list_tax_areas twice must not double-append the caveat."""
    reference_tax.list_tax_areas("KS")
    areas = reference_tax.list_tax_areas("KS")
    counties = [a for a in areas if a["kind"] == "county"]
    for row in counties:
        assert row["notes"].count("unincorporated") == 1


def test_sedgwick_notes_document_the_wichita_exception():
    """Wichita levies no general city sales tax, so Sedgwick's county-only
    rate happens to be correct there — but not for other cities in the
    county. This nuance must survive the caveat append, not get clobbered."""
    sedgwick = next(c for c in reference_tax.COUNTIES if c["name"] == "Sedgwick" and c["state"] == "KS")
    assert "Wichita" in sedgwick["notes"]
    areas = reference_tax.list_tax_areas("KS")
    row = next(a for a in areas if a["kind"] == "county" and a["name"] == "Sedgwick")
    assert "Wichita" in row["notes"]
    assert "unincorporated" in row["notes"]


# ─── internal consistency invariants ───────────────────────────────────────

def test_ks_state_rate_plus_county_portion_equals_remodel_rate():
    """If someone edits county_portion (or KS_STATE_RATE) without updating
    remodel_rate, this catches the drift instead of it silently shipping."""
    for c in reference_tax.list_counties("KS"):
        expected = round(reference_tax.KS_STATE_RATE + c["county_portion"], 6)
        assert abs(expected - c["remodel_rate"]) < 1e-9, (
            f"{c['name']} County, KS: {reference_tax.KS_STATE_RATE} + "
            f"{c['county_portion']} != {c['remodel_rate']}"
        )


def test_every_ks_city_rate_is_at_least_its_county_floor():
    """A city's full combined rate should never be LOWER than its own
    county's unincorporated floor — that would mean the city has a negative
    add-on, which never happens in KS. Catches a fat-fingered city rate."""
    counties_by_name = {
        c["name"]: c for c in reference_tax.list_counties("KS")
    }
    for city in reference_tax.list_cities("KS"):
        county = counties_by_name.get(city["county"])
        assert county is not None, f"{city['name']} claims parent county {city['county']!r}, not found in COUNTIES"
        assert city["remodel_rate"] >= county["remodel_rate"], (
            f"{city['name']}, KS ({city['remodel_rate']}) is below its own "
            f"county floor {city['county']} ({county['remodel_rate']})"
        )


def test_every_city_has_a_resolvable_parent_county():
    """Every KS city's `county` field must name a county that's actually in
    COUNTIES — otherwise the floor-rate comparison above is vacuous."""
    county_names = {c["name"] for c in reference_tax.list_counties("KS")}
    for city in reference_tax.list_cities("KS"):
        assert city["county"] in county_names


# ─── lookup() sanity, unaffected by this fix ───────────────────────────────

def test_lookup_unknown_city_falls_back_to_state():
    result = reference_tax.lookup("Nowhereville, KS")
    assert result["source"] == "state_fallback"
    assert result["rate"] == reference_tax.STATE_FALLBACK["KS"]


def test_lookup_blank_input():
    assert reference_tax.lookup(None)["source"] == "unknown"
    assert reference_tax.lookup("")["source"] == "unknown"


def test_lookup_unparseable_input():
    assert reference_tax.lookup("not a city state pair")["source"] == "unknown"
