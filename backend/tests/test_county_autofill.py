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
        "js/county-picker.js", 'if (pick && !autoPick) return "hand";', 'if (false) return "hand";',
        lambda r: r["live"]["handPickKept"]["keys"]["county"] != "Jackson County, MO"),
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
        "js/county-picker.js", "if (pick && autoPick) clear();", ";",
        lambda r: r["live"]["notInList"]["staleFillCleared"]["keys"]["county"] != ""),
    "the note forgets to say it was filled": (
        "js/county-picker.js", 'return baseNote() + (pick && autoPick ? " " + AUTO_NOTE : "");',
        "return baseNote();",
        lambda r: not r["live"]["pickFills"]["final"]["note"].endswith(r["autoNote"])),
    "a slow answer overwrites a newer address": (
        "js/county-autofill.js", "var stale = function () { return mine !== seq || key !== keyNow(); };",
        "var stale = function () { return false; };",
        lambda r: r["live"]["staleAnswer"]["after"] != "Wyandotte County, KS"),
    "a doubted city is trusted anyway": (
        "js/county-autofill.js", "ans.place_sure === false ? val(els.city) : ans.place);",
        "ans.place);",
        lambda r: r["live"]["placeUnsure"]["unsure"]["keys"]["county"] != "Kansas City, KS"),
    "a failed lookup is never retried": (
        "js/county-autofill.js", 'if (!ans || ans.ok !== true) { lastKey = ""; return; }   // no answer: a later change retries',
        "if (!ans || ans.ok !== true) { return; }",
        lambda r: r["live"]["failures"]["seen"]["throw"]["afterRetry"]["county"] != "Sedgwick County, KS"),
    "the fill does not wait for the list": (
        "js/county-autofill.js", "await county.whenLoaded();", "",
        lambda r: r["live"]["listNotLoaded"]["typed"]["late"] != "Sedgwick County, KS"),
    "a hand-picked bid still spends a lookup": (
        "js/county-autofill.js", "if (county.hasPick() && !county.isAuto()) return;", "",
        lambda r: r["live"]["handPickKept"]["lookups"] != 0),
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
