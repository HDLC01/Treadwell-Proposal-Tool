"""The County remodel tax box fills itself from the job address, on BOTH intake pages.

Hanz, 2026-10-13, looking at the empty box: "shouldn't this autofill based on the address?"

The server half (POST /api/county, the Census geographies lookup) is tests/test_county_lookup.py. This
file is the page half, and it is EXECUTED: tests/js/county-autofill-harness.js runs the real
js/county-picker.js, js/county-autofill.js and js/address-lookup.js, with the page wiring lifted out
of js/index.js (the live intake) and js/polish-intake.js (the v2 intake) and run as written, against
the REAL county table out of backend/reference_tax.py. Every scenario runs once per page and the two
must answer identically: one shared module, not two copies.

The rules pinned here, in the order the estimator meets them:
  * an empty box + a picked address fills (Photon's county at once, the Census answer confirms);
  * a verified city row beats the county floor row, unless the city row belongs to another county;
  * a county picked by hand, or held by a saved draft, is NEVER overwritten and costs no lookup;
  * a later address re-fills only a county that was itself a fill;
  * a county or city the list has no row for stays empty (and clears a stale fill);
  * a fill belongs to its address: it goes when the street is emptied or nothing answers for the new one;
  * a county the estimator cleared is theirs too, and their typing in the county box is never interrupted;
  * a city with no row of its own gets the county rate AND a sentence saying the city may charge more;
  * opening a saved bid fires nothing;
  * any failure is silent and a later change retries; a slow answer for a left address is dropped.
"""
import json
import pathlib
import re

import pytest

import reference_tax
from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "county-autofill-harness.js"
FILES = ["js/county-picker.js", "js/county-autofill.js", "js/address-lookup.js", "js/index.js",
         "js/polish-intake.js"]
AUTO_NOTE = "Filled from the address. Change it if it's wrong."
PAGES = ("live", "polish")


def _run(tmp_path, frontend=FRONTEND):
    table = tmp_path / "county-table.json"
    table.write_text(json.dumps(reference_tax.list_tax_areas()), encoding="utf-8")
    proc = run_node(HARNESS, frontend, table)
    assert proc.returncode == 0, "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return _run(tmp_path_factory.mktemp("county-autofill"))


@pytest.fixture(params=PAGES)
def page(request, ran):
    return ran[request.param]


# ---------------------------------------------------------------- one module, two pages

def test_both_pages_answer_every_scenario_identically(ran):
    """The point of sharing: nothing page-specific is left to drift."""
    assert ran["live"] == ran["polish"]


# ---------------------------------------------------------------- it fills

def test_a_picked_address_fills_an_empty_box_and_the_remodel_rate(page):
    f = page["pickFills"]
    # Photon's county is on screen BEFORE the Census answer lands (the lookup was still pending).
    assert f["guess"]["lookups"] == 1
    assert f["guess"]["keys"]["county"] == "Sedgwick County, KS"
    assert f["guess"]["keys"]["county_remodel_rate"] == pytest.approx(0.075)
    assert f["guess"]["input"] == "Sedgwick County, KS" and f["guess"]["auto"] is True
    # ...and the Census answer confirms it without a second save or a flicker.
    assert f["final"]["keys"] == f["guess"]["keys"]
    assert f["saves"] == 1, "the confirming answer wrote the draft again"
    assert f["lookups"] == 1
    assert f["body"] == {"address": "455 N Main St", "city": "Wichita", "state": "KS", "zip": "67202"}
    assert f["auth"] == "Bearer t", "the lookup went out without the sign-in header"


def test_the_note_says_it_was_filled_and_only_while_it_is_a_fill(page):
    assert page["pickFills"]["final"]["note"].endswith(AUTO_NOTE)
    assert AUTO_NOTE not in page["handPickKept"]["note"]
    assert AUTO_NOTE not in page["savedDraft"]["opened"]["note"]
    assert "—" not in AUTO_NOTE and "–" not in AUTO_NOTE, "plain words: no dashes"


def test_the_census_answer_replaces_photons_guess(page):
    r = page["censusReplacesGuess"]
    assert r["keys"]["county"] == "Wyandotte County, KS"
    assert r["keys"]["county_remodel_rate"] == pytest.approx(0.075)
    assert r["auto"] is True


def test_a_verified_city_row_beats_the_county_floor_row(page):
    """A county row is the floor rate for unincorporated land; Olathe's own row is the full rate."""
    c = page["cityRow"]
    assert c["keys"]["county"] == "Olathe, KS"
    assert c["keys"]["county_remodel_rate"] == pytest.approx(0.09475)
    assert c["input"] == "Olathe, KS"


def test_a_city_row_of_another_county_is_not_used(page):
    """Shawnee, KS is in Johnson County; an address in Shawnee COUNTY must not get its rate."""
    c = page["cityRowOfAnotherCounty"]
    assert c["keys"]["county"] == "Shawnee County, KS"
    assert c["keys"]["county_remodel_rate"] == pytest.approx(0.0785)


def test_a_typed_address_is_looked_up_once_after_the_pause_and_never_while_thin(page):
    t = page["typed"]
    assert t["thin"] == 0, "a street with nothing to place it was looked up"
    assert t["once"] == 1 and t["repeat"] == 1, "the same address was asked twice"
    assert t["county"] == "Sedgwick County, KS"
    assert t["photon"] == 0
    assert t["body"] == {"address": "455 N Main St", "city": "Wichita", "state": "KS", "zip": ""}


def test_the_fill_waits_for_the_county_list_if_it_is_still_loading(page):
    n = page["listNotLoaded"]
    assert n["early"] == "" and n["late"] == "Sedgwick County, KS"
    assert n["lookups"] == 1
    # A typed address has no Photon guess: only the Census answer can fill it, and it must wait too.
    assert n["typed"] == {"early": "", "late": "Sedgwick County, KS", "lookups": 1}


# ---------------------------------------------------------------- it never overwrites them

def test_a_county_picked_by_hand_is_never_overwritten_and_costs_no_lookup(page):
    h = page["handPickKept"]
    assert h["keys"]["county"] == "Jackson County, MO"
    assert h["auto"] is False
    assert h["lookups"] == 0, "a hand-picked bid spent a lookup"
    assert h["saves"] == 0, "the draft was written over a hand pick"


def test_a_hand_pick_made_while_the_answer_is_on_its_way_wins(page):
    assert page["handPickDuringLookup"]["keys"]["county"] == "Jackson County, MO"
    assert page["handPickDuringLookup"]["auto"] is False


def test_changing_the_address_refills_a_fill_but_not_a_hand_pick(page):
    a = page["addressChange"]
    assert a["first"] == "Sedgwick County, KS"
    assert a["second"]["keys"]["county"] == "Kansas City, KS"           # the city row, still a fill
    assert a["second"]["keys"]["county_remodel_rate"] == pytest.approx(0.09125)
    assert a["second"]["auto"] is True
    assert a["afterHandPick"]["keys"]["county"] == "Jackson County, MO"
    assert a["afterHandPick"]["auto"] is False
    assert a["lookupsAfter"] == a["lookupsBefore"], "an address change asked about a hand-picked county"


def test_a_saved_draft_opens_unchanged_and_stays_theirs(page):
    s = page["savedDraft"]
    o = s["opened"]
    assert o["keys"]["county"] == "Wyandotte County, KS" and o["input"] == "Wyandotte County, KS"
    # An address already in the boxes fires no event, so nothing is asked and nothing is saved.
    assert o["lookups"] == 0 and o["saves"] == 0 and o["timers"] == 0
    assert o["auto"] is False
    # Picking another address afterwards does not touch the saved county either.
    assert s["afterPick"]["keys"]["county"] == "Wyandotte County, KS"
    assert s["afterPick"]["lookups"] == 0
    # And a draft with no county is not filled just by being opened.
    assert s["noCountyOpened"] == {"keys": {"county": "", "county_tax_rate": None,
                                            "county_remodel_rate": None, "county_notes": ""},
                                   "lookups": 0}


def test_clearing_is_the_estimators_too(page):
    c = page["cleared"]
    assert c["cleared"] == "" and c["afterRepeat"] == "" and c["lookups"] == 1


# ---------------------------------------------------------------- it never approximates

def test_a_county_not_in_the_list_stays_empty_and_clears_a_stale_fill(page):
    n = page["notInList"]
    assert n["empty"]["keys"]["county"] == "" and n["empty"]["has"] is False
    assert n["empty"]["saves"] == 0, "an empty box was saved as if something had been filled"
    assert n["staleFillCleared"]["keys"]["county"] == "", "a county from the OLD address was left standing"
    assert n["staleFillCleared"]["has"] is False


# ---------------------------------------------------------------- it fails quietly

def test_any_failure_changes_nothing_throws_nothing_and_a_later_change_retries(page):
    f = page["failures"]
    assert f["unhandled"] == [], "a failed lookup left an unhandled rejection"
    for mode in ("throw", "badjson", "notok", "emptyobj"):
        s = f["seen"][mode]
        assert s["has"] is False and s["keys"]["county"] == "", mode
        assert s["lookups"] == 1, mode
        # No answer is not an answer: committing the same address again asks again.
        assert s["afterRetry"] == {"county": "Sedgwick County, KS", "lookups": 2}, mode


def test_a_city_the_census_doubts_is_replaced_by_the_one_typed(page):
    """Real, 2026-10-13: the Census put 701 N 7th St, Kansas City KS 66101 in Edwardsville (it matched the
    street in zip 66111). The county was right; the city was not."""
    u = page["placeUnsure"]
    assert u["unsure"]["keys"]["county"] == "Kansas City, KS"
    assert u["unsure"]["keys"]["county_remodel_rate"] == pytest.approx(0.09125)
    # Trusted, the same answer has no row for Edwardsville, so the county row it is.
    assert u["sure"]["keys"]["county"] == "Wyandotte County, KS"


def test_a_slow_answer_for_an_address_already_left_is_dropped(page):
    s = page["staleAnswer"]
    assert s["before"] == "Wyandotte County, KS"
    assert s["after"] == "Wyandotte County, KS", "the old address's answer overwrote the new one"


# ---------------------------------------------------------------- a fill belongs to its address

def test_no_answer_for_a_new_address_removes_the_fill_made_for_the_old_one(page):
    """Not found (a new build, a rural road), down, or an empty answer: the county from the OLD address
    must not stay on screen under a note that says it was filled from the address."""
    rows = page["staleAfterNoAnswer"]
    assert [r["mode"] for r in rows] == ["not_found", "down", "empty"]
    for r in rows:
        assert r["before"] == "Sedgwick County, KS", r["mode"]
        assert r["keys"]["county"] == "" and r["keys"]["county_remodel_rate"] is None, r["mode"]
        assert r["has"] is False and r["input"] == "", r["mode"]
        assert AUTO_NOTE not in r["note"], r["mode"]


def test_emptying_the_street_removes_the_fill_and_typing_it_back_asks_again(page):
    s = page["streetCleared"]
    assert s["emptied"]["keys"]["county"] == "" and s["emptied"]["has"] is False
    assert s["back"]["keys"]["county"] == "Sedgwick County, KS" and s["back"]["auto"] is True
    assert s["back"]["lookups"] == 2, "the same street typed back was not looked up again"


def test_a_picked_address_keeps_photons_guess_when_the_census_never_answers(page):
    """The guess is for THIS address, so only an older address's fill is removed on a failure."""
    g = page["guessSurvivesNoAnswer"]
    assert g["keys"]["county"] == "Sedgwick County, KS" and g["auto"] is True and g["lookups"] == 1


def test_an_address_that_moved_on_while_the_list_loaded_gets_no_stale_fill(page):
    m = page["movedOnWhileLoading"]
    assert m["typed"] == "", "an answer for an address already left landed when the list arrived"
    assert m["guess"] == "", "Photon's guess for an address already left landed when the list arrived"
    assert m["typedSaves"] == 0 and m["guessSaves"] == 0, "a stale county was written to the draft, even briefly"
    assert m["guessAlone"] == "Sedgwick County, KS", "the guess never lands once the list does"


# ---------------------------------------------------------------- the typed city, and the Census's doubts

def test_with_no_zip_the_typed_city_beats_a_census_place_it_may_have_got_wrong(page):
    """Real, 2026-10-13: 701 N 7th St, Kansas City KS with no zip comes back as Edwardsville, place_sure
    true (nothing to disprove it). Kansas City KS has a verified row in that county; Edwardsville has
    none, so the county floor of 7.5% would under-tax the bid by 1.625 points."""
    t = page["typedCityWins"]
    for how in ("noZip", "photon"):
        assert t[how]["keys"]["county"] == "Kansas City, KS", how
        assert t[how]["keys"]["county_remodel_rate"] == pytest.approx(0.09125), how
    # A postal name with no row (Shawnee Mission) never beats the Census place.
    assert t["postalName"]["keys"]["county"] == "Overland Park, KS"
    # A typed city whose row is in ANOTHER county never beats the Census county.
    assert t["otherCounty"]["keys"]["county"] == "Shawnee County, KS"


# ---------------------------------------------------------------- a city with no row of its own

def test_a_city_the_list_has_no_row_for_gets_the_county_rate_and_a_warning(page):
    c = page["cityNotOnList"]
    for name, county, rate in (("gardner", "Johnson County, KS", 0.07975),
                               ("bonner", "Wyandotte County, KS", 0.075),
                               ("derby", "Sedgwick County, KS", 0.075)):
        row = c[name]
        assert row["keys"]["county"] == county and row["keys"]["county_remodel_rate"] == pytest.approx(rate), name
        assert "is not on the list, so this is the county rate only" in row["note"], name
        assert "A city can charge its own tax on top." in row["note"], name
        assert row["note"].endswith(AUTO_NOTE), name        # the fill sentence stays last
        said = row["note"].split("Never on materials.")[1]  # the sentences this change added
        assert "—" not in said and "–" not in said, "plain words: no dashes (%s)" % name
    assert c["gardner"]["note"].count("Gardner is not on the list") == 1
    assert "Bonner Springs is not on the list" in c["bonner"]["note"]
    assert "Derby is not on the list" in c["derby"]["note"]


def test_the_warning_arrives_when_a_later_answer_names_the_city(page):
    """Photon gave a county and no city; the Census then names Gardner: same county row, new sentence."""
    c = page["cityNotOnList"]["lateCity"]
    assert c["keys"]["county"] == "Johnson County, KS" and c["auto"] is True
    assert "Gardner is not on the list" in c["note"]


def test_no_warning_where_the_county_rate_is_the_right_one(page):
    c = page["cityNotOnList"]
    # A city with its own verified row, an address outside any city, a hand pick: nothing to warn about.
    for name in ("withRow", "unincorporated", "hand"):
        assert "is not on the list" not in c[name]["note"], name
    # Wichita levies no city tax of its own (the Sedgwick row's city_ok), so the county rate is right.
    assert c["wichita"]["keys"]["county"] == "Sedgwick County, KS"
    assert "is not on the list" not in c["wichita"]["note"]
    # Missouri labor is exempt: there is no rate for a city to add to.
    assert c["missouri"]["keys"]["county"] == "Jackson County, MO"
    assert "is not on the list" not in c["missouri"]["note"]


def test_the_city_ok_list_names_real_places_and_only_where_the_row_says_so():
    rows = {(r["kind"], r["name"], r["state"]): r for r in reference_tax.list_tax_areas()}
    assert rows[("county", "Sedgwick", "KS")]["city_ok"] == ["Wichita"]
    city_rows = {r["name"] for r in rows.values() if r["kind"] == "city"}
    for r in rows.values():
        for name in r.get("city_ok", []):
            assert r["kind"] == "county" and name not in city_rows, "a city with its own row needs no city_ok"
    assert "Wichita currently levies no general city sales tax" in rows[("county", "Sedgwick", "KS")]["notes"]


# ---------------------------------------------------------------- the state guards

def test_missouri_and_kansas_twins_are_told_apart(page):
    """Both states have a Johnson County (7.975% in KS, exempt in MO), and a Missouri city named like a
    Kansas one is not that city."""
    g = page["stateGuards"]
    assert g["johnsonKS"]["keys"]["county"] == "Johnson County, KS"
    assert g["johnsonKS"]["keys"]["county_remodel_rate"] == pytest.approx(0.07975)
    assert g["johnsonMO"]["keys"]["county"] == "Johnson County, MO"
    assert g["johnsonMO"]["keys"]["county_remodel_rate"] is None
    assert g["photonMoCityNoCounty"]["keys"]["county"] == "", "Kansas City, MO was filled as Kansas City, KS"


# ---------------------------------------------------------------- the box is the estimator's

def test_a_county_the_estimator_cleared_is_not_filled_again_by_an_address_edit(page):
    c = page["clearIsTheirs"]
    for name in ("afterHandClear", "afterClearedFill"):
        assert c[name]["keys"]["county"] == "" and c[name]["has"] is False, name
    assert c["afterHandClear"]["lookups"] == 0, "a cleared box spent a lookup"
    assert c["afterClearedFill"]["lookups"] == 1, "a cleared fill asked again"
    # A fill the PAGE removed (a new address with no row) is not the estimator's Clear: the next fills.
    assert c["pageRemovalIsNot"]["removedByPage"] is False
    assert c["pageRemovalIsNot"]["keys"]["county"] == "Sedgwick County, KS"


def test_the_estimators_typing_in_the_county_box_is_never_overwritten(page):
    t = page["typingInCountyBox"]
    assert t["typing"] == {"input": "john", "open": True}
    assert t["during"]["input"] == "john" and t["during"]["open"] is True, "the answer overwrote their text"
    assert t["during"]["keys"]["county"] == "" and t["during"]["has"] is False
    # Once they are done, the same address is looked up again and fills.
    assert t["afterEscape"]["keys"]["county"] == "Sedgwick County, KS" and t["afterEscape"]["lookups"] == 2


def test_an_answer_before_the_list_was_requested_is_asked_again_later(page):
    """The live intake requests the list after its condition defaults arrive; an answer that lands first
    cannot be filled, and committing the same address afterwards must not be swallowed as a repeat."""
    b = page["beforeLoadCalled"]
    assert b["before"] == "" and b["after"] == "Sedgwick County, KS" and b["lookups"] == 2


# ---------------------------------------------------------------- the pages carry it

@pytest.mark.parametrize("html, script", [("index.html", "js/index.js"),
                                           ("polish-intake.html", "js/polish-intake.js")])
def test_each_page_loads_the_module_after_the_picker_and_before_its_own_script(html, script):
    text = (FRONTEND / html).read_text(encoding="utf-8")
    tags = re.findall(r'<script[^>]*src="([^"]+)"', text)
    for need in ("/js/county-picker.js", "/js/county-autofill.js", "/js/address-lookup.js", "/" + script):
        assert need in tags, "%s does not load %s" % (html, need)
    assert tags.index("/js/county-picker.js") < tags.index("/js/county-autofill.js") < tags.index("/" + script)
    assert tags.index("/js/address-lookup.js") < tags.index("/" + script)


@pytest.mark.parametrize("html", ["index.html", "polish-intake.html"])
def test_the_placeholder_has_no_dash(html):
    text = (FRONTEND / html).read_text(encoding="utf-8")
    m = re.search(r'id="county-input"[^>]*placeholder="([^"]*)"', text, flags=re.S)
    assert m, "the county box lost its placeholder"
    assert "—" not in m.group(1) and "&mdash;" not in m.group(1), m.group(1)


def test_the_frontend_calls_the_route_the_server_serves():
    src = (FRONTEND / "js" / "county-autofill.js").read_text(encoding="utf-8")
    assert '"/api/county"' in src
    import main
    assert any(getattr(r, "path", "") == "/api/county" and "POST" in getattr(r, "methods", ())
               for r in main.app.routes)


# ---------------------------------------------------------------- the checks go red when the code changes

MUTATIONS = {
    "the picker overwrites a hand pick": (
        "js/county-picker.js", 'if ((pick && !autoPick) || handCleared) return "hand";', 'if (false) return "hand";',
        lambda r: r["live"]["handPickKept"]["keys"]["county"] != "Jackson County, MO"),
    "a Clear is not remembered": (
        "js/county-picker.js", "handCleared = true;", "handCleared = false;",
        lambda r: r["live"]["clearIsTheirs"]["afterHandClear"]["keys"]["county"] != ""),
    "the picker fills over the estimator's typing": (
        "js/county-picker.js", 'if (input && String(input.value || "") !== (pick ? pick.county : "")) return "busy";',
        "",
        lambda r: r["live"]["typingInCountyBox"]["during"]["input"] != "john"),
    "a saved county counts as a fill": (
        "js/county-picker.js", "autoPick = false;                      // a saved county is treated as chosen, never refilled",
        "autoPick = !!state.county;",
        lambda r: r["live"]["savedDraft"]["afterPick"]["keys"]["county"] != "Wyandotte County, KS"),
    "a city row of another county is used": (
        "js/county-picker.js", "if (cn && c.county && bareName(c.county) !== cn) continue;", ";",
        lambda r: r["live"]["cityRowOfAnotherCounty"]["keys"]["county"] != "Shawnee County, KS"),
    "the county floor row always wins": (
        "js/county-picker.js", "if (pl) {", "if (false) {",
        lambda r: r["live"]["cityRow"]["keys"]["county"] != "Olathe, KS"),
    "a stale fill is left standing": (
        "js/county-picker.js", "if (pick && autoPick) reset();", ";",
        lambda r: r["live"]["notInList"]["staleFillCleared"]["keys"]["county"] != ""),
    "the note forgets to say it was filled": (
        "js/county-picker.js", 'return baseNote() + gap + " " + AUTO_NOTE;', "return baseNote() + gap;",
        lambda r: not r["live"]["pickFills"]["final"]["note"].endswith(r["autoNote"])),
    "the county state is ignored": (
        "js/county-picker.js", 'if (c.kind !== "city" && c.state === st && bareName(c.name) === cn) return c;',
        'if (c.kind !== "city" && bareName(c.name) === cn) return c;',
        lambda r: r["live"]["stateGuards"]["johnsonKS"]["keys"]["county"] != "Johnson County, KS"),
    "the city state is ignored": (
        "js/county-picker.js", 'if (c.kind !== "city" || c.state !== st || bareName(c.name) !== pl) continue;',
        'if (c.kind !== "city" || bareName(c.name) !== pl) continue;',
        lambda r: r["live"]["stateGuards"]["photonMoCityNoCounty"]["keys"]["county"] != ""),
    "a city with no row gets no warning": (
        "js/county-picker.js",
        '? " " + autoGap + " is not on the list, so this is the county rate only. A city can charge its own tax on top."',
        '? ""',
        lambda r: "Gardner is not on the list" not in r["live"]["cityNotOnList"]["gardner"]["note"]),
    "the warning ignores a row that vouches for its city": (
        "js/county-picker.js",
        "var verified = (row.city_ok || []).some(function (n) { return bareName(n) === bareName(placeName); });",
        "var verified = false;",
        lambda r: "is not on the list" in r["live"]["cityNotOnList"]["wichita"]["note"]),
    "the warning is said about Missouri labor": (
        "js/county-picker.js", 'var gap = autoGap && stateOf(pick) !== "MO"', "var gap = autoGap",
        lambda r: "is not on the list" in r["live"]["cityNotOnList"]["missouri"]["note"]),
    "a later answer's city never reaches the note": (
        "js/county-picker.js", "if (autoGap !== gap) { autoGap = gap; renderNote(); }", ";",
        lambda r: "Gardner is not on the list" not in r["live"]["cityNotOnList"]["lateCity"]["note"]),
    "a slow answer overwrites a newer address": (
        "js/county-autofill.js", "var stale = function () { return mine !== seq || key !== keyNow(); };",
        "var stale = function () { return false; };",
        lambda r: r["live"]["staleAnswer"]["after"] != "Wyandotte County, KS"),
    "a doubted city is trusted anyway": (
        "js/county-autofill.js", "if (ans.place_sure === false) return typed;", "if (false) return typed;",
        lambda r: r["live"]["placeUnsure"]["unsure"]["keys"]["county"] != "Kansas City, KS"),
    "the typed city never beats the Census place": (
        "js/county-autofill.js", "if (row && row.kind === \"city\") return typed;", ";",
        lambda r: r["live"]["typedCityWins"]["noZip"]["keys"]["county"] != "Kansas City, KS"),
    "the typed city beats the Census place even with a zip": (
        "js/county-autofill.js", 'if (typed && val(els.zip).replace(/\\D/g, "").length < 5) {', "if (typed) {",
        lambda r: r["live"]["placeUnsure"]["sure"]["keys"]["county"] != "Wyandotte County, KS"),
    "a typed city with no row is trusted over the Census": (
        "js/county-autofill.js", "if (row && row.kind === \"city\") return typed;", "return typed;",
        lambda r: r["live"]["typedCityWins"]["postalName"]["keys"]["county"] != "Overland Park, KS"),
    "a failed lookup is never retried": (
        "js/county-autofill.js", 'lastKey = "";                // no answer: a later change asks again', "",
        lambda r: r["live"]["failures"]["seen"]["throw"]["afterRetry"]["county"] != "Sedgwick County, KS"),
    "no answer leaves the old address's fill standing": (
        "js/county-autofill.js", "dropStaleFill(key);          // and an older address's fill is not left standing as this one's",
        ";",
        lambda r: r["live"]["staleAfterNoAnswer"][0]["keys"]["county"] != ""),
    "an emptied street leaves its fill standing": (
        "js/county-autofill.js", "dropStaleFill(key);   // the address is gone", ";",
        lambda r: r["live"]["streetCleared"]["emptied"]["keys"]["county"] != ""),
    "a dropped fill keeps the repeat guard": (
        "js/county-autofill.js", 'lastKey = "";                // the same address typed again is asked again', "",
        lambda r: r["live"]["streetCleared"]["back"]["lookups"] != 2),
    "a failure removes the guess made for the same address": (
        "js/county-autofill.js", "if (!county.isAuto() || fillKey === key) return;", "if (!county.isAuto()) return;",
        lambda r: r["live"]["guessSurvivesNoAnswer"]["keys"]["county"] != "Sedgwick County, KS"),
    "a fill forgets which address it was for": (
        "js/county-autofill.js", 'if (res === "filled" || res === "same") fillKey = key;',
        'if (false) fillKey = key;',
        lambda r: r["live"]["guessSurvivesNoAnswer"]["keys"]["county"] != "Sedgwick County, KS"),
    "an answer that could not be filled is swallowed as a repeat": (
        "js/county-autofill.js", 'else if (res === "pending" || res === "busy") lastKey = "";   // nothing written: ask again later',
        ";",
        lambda r: r["live"]["beforeLoadCalled"]["after"] != "Sedgwick County, KS"),
    "an answer for an address left during the list load lands": (
        "js/county-autofill.js", "if (stale()) return;           // the address moved on while the list loaded", "",
        lambda r: r["live"]["movedOnWhileLoading"]["typed"] != ""),
    "a guess for an address left during the list load lands": (
        "js/county-autofill.js", "if (keyNow() !== pickKey) return;", "",
        lambda r: r["live"]["movedOnWhileLoading"]["guessSaves"] != 0),
    "the guess does not wait for the list": (
        "js/county-autofill.js", "guess = county.whenLoaded().then(function () {",
        "guess = Promise.resolve().then(function () {",
        lambda r: r["live"]["movedOnWhileLoading"]["guessAlone"] != "Sedgwick County, KS"),
    "the fill does not wait for the list": (
        "js/county-autofill.js", "await county.whenLoaded();", "",
        lambda r: r["live"]["listNotLoaded"]["typed"]["late"] != "Sedgwick County, KS"),
    "a hand-picked bid still spends a lookup": (
        "js/county-autofill.js", "if (county.isTheirs()) return;", "",
        lambda r: r["live"]["handPickKept"]["lookups"] != 0),
    "a cleared box still spends a lookup": (
        "js/county-autofill.js", "if (county.isTheirs()) return;", "if (county.hasPick() && !county.isAuto()) return;",
        lambda r: r["live"]["clearIsTheirs"]["afterHandClear"]["lookups"] != 0),
    "the address pick never reaches the autofill": (
        "js/address-lookup.js", 'if (typeof els.onPick === "function") {', "if (false) {",
        lambda r: r["live"]["pickFills"]["lookups"] != 1 or r["polish"]["pickFills"]["lookups"] != 1),
    "the live intake does not hook the pick": (
        "js/index.js", "onPick:   countyAuto ? countyAuto.onPick : undefined,", "",
        lambda r: r["live"]["pickFills"]["lookups"] != 1),
    "the v2 intake does not hook the pick": (
        "js/polish-intake.js", "onPick:   countyAuto ? countyAuto.onPick : undefined", "",
        lambda r: r["polish"]["pickFills"]["lookups"] != 1),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, FILES)
    proc_out = _run(tmp_path, frontend)
    assert noticed(proc_out), "the checks did not notice: " + name
