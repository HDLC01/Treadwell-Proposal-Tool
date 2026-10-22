"""A JOB WITH NO STREET IS MEASURED ON THE ESTIMATE PAGE, AND AN UNKNOWN DISTANCE IS NEVER CALLED LOCAL (Hanz, 2026-10-22).

Hanz, testing staging: a v2 bid with City "Wichita", State "KS", County "Sedgwick County, KS" and no street showed "This job is marked local, so no
travel is expected" and never filled Travel Labor, Hotel or Per Diem. Wichita is about 190 driving miles from the Olathe office. "based on the county
and city and state it should have calculated it already".

HIS DECISIONS, as the page now keeps them (tests/js/distance-approx-harness.js runs the real page over the real js/bid-model.js):
  * A city + state, a zip, or a county is enough to ask (B.distanceKey, the same rule as distance.can_place: test_distance_key_parity.py).
  * The page asks on open for a NEW bid (as before) AND for a saved bid that has no distance at all (never measured, never typed).
  * A figure measured to a centre (zip / city / county) is approximate: kept with its precision, worded "About 190 miles to Wichita, KS (city
    center)", and measured again on open once the address has changed (a street added). A TYPED figure is never replaced without the button; a
    STREET figure keeps today's "the address changed since this was measured" and the button.
  * An UNKNOWN distance is never worded local, on the base sheet or an option. Its price is unchanged (no travel until miles arrive): only words.

Each fact is broken one line at a time in a scratch copy of the page or the model (BREAKS) and must change.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "distance-approx-harness.js"
SECTIONS = ("newCity", "savedNone", "savedTyped", "approxMoved", "approxSame", "streetMoved", "legacyMoved", "legacySame", "unknown", "nearTyped",
            "reload", "blank", "streetMissed", "countyOnly", "cityOnly")
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

CITY_KEY = "|wichita|ks||sedgwick county, ks"
APPROX_NOTE = "About 190 miles to Wichita, KS (city center)"
APPROX_STATUS = "Add the street on the intake step for the exact figure."
MISSED_STATUS = "The street was not found, so this is to the city center. Check the street on the intake step for the exact figure."
MOVED_STATUS = "The address changed since this was measured. Look it up again, or type the miles."
UNKNOWN_CARD = "Distance unknown. Add the job's city and state on the intake step, or type the miles on the Polish sheet."
LOCAL_CARD = "This job is marked local, so no travel is expected — type here anyway if it needs drive time."
INCOMPLETE = "Add the job's city and state, a zip or the county on the intake step, or type the miles."
UNKNOWN_NOTE = "Distance unknown — enter miles"


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    for k in SECTIONS:
        assert "error" not in got[k], "%s threw: %s" % (k, got[k]["error"][:600])
    return got


def test_hanzs_bid_a_new_city_only_bid_asks_on_open_and_fills_the_travel(ran):
    f = ran["newCity"]
    assert f["asked"] == 1
    assert f["bodies"][0] == {"address": "", "city": "Wichita", "state": "KS", "zip": "", "county": "Sedgwick County, KS"}
    assert f["distance"] == {"miles": 190.1, "source": "google", "key": CITY_KEY, "precision": "city", "measured_to": "Wichita, KS"}
    assert f["local"] is False and f["lodging"] is True and f["hours"] == 6.5
    assert f["note"] == APPROX_NOTE and f["status"] == APPROX_STATUS
    assert f["how"].startswith(APPROX_NOTE + ". That is 70 miles or more, so this is NOT a local job"), f["how"]
    assert f["saved"]["precision"] == "city" and f["saved"]["measured_to"] == "Wichita, KS"


def test_a_saved_bid_that_never_had_a_distance_asks_on_open(ran):
    f = ran["savedNone"]
    assert f["asked"] == 1 and f["distance"]["miles"] == 190.1 and f["distance"]["precision"] == "city"
    assert f["lodging"] is True and f["local"] is False and f["hours"] == 6.5
    assert f["saved"]["miles"] == 190.1, "the figure the open measured is saved"


def test_a_typed_figure_is_never_measured_again_without_the_button(ran):
    f = ran["savedTyped"]
    assert f["asked"] == 0 and f["distance"] == {"miles": 40, "source": "typed", "key": ""}
    assert f["note"] == "40 mi from Olathe office (typed by you)"


def test_an_approximate_figure_is_measured_again_once_a_street_is_added(ran):
    f = ran["approxMoved"]
    assert f["asked"] == 1 and f["bodies"][0]["address"] == "100 Main St"
    assert f["distance"]["precision"] == "street" and f["distance"]["miles"] == 177.2
    assert "measured_to" not in f["distance"] or f["distance"]["measured_to"] == "100 Main St, Wichita, KS 67202"
    assert f["note"] == "177.2 mi from Olathe office" and f["status"] == ""


def test_an_approximate_figure_for_the_same_address_is_not_asked_again(ran):
    f = ran["approxSame"]
    assert f["asked"] == 0 and f["distance"]["miles"] == 190.1 and f["note"] == APPROX_NOTE


def test_a_street_figure_keeps_the_address_changed_words_and_the_button(ran):
    for k in ("streetMoved", "legacyMoved"):
        f = ran[k]
        assert f["asked"] == 0, k
        assert f["distance"]["miles"] == 177.2 and f["status"] == MOVED_STATUS, (k, f["status"])
        assert f["note"] == "177.2 mi from Olathe office", k


def test_a_street_figure_saved_before_the_county_existed_still_matches_its_address(ran):
    """Every street key saved before 2026-10-22 is "street|city|st|zip". The county is no part of a street's key, so those keys still match and no
    bid with a county opens saying its address changed."""
    f = ran["legacySame"]
    assert f["asked"] == 0 and f["status"] == ""


def test_an_unknown_distance_is_never_called_local_on_the_base_or_an_option(ran):
    for where in ("base", "option"):
        f = ran["unknown"][where]
        assert f["saysLocal"] is False, (where, f["inert"])
        assert f["inert"] and all(t == UNKNOWN_CARD for t in f["inert"]), (where, f["inert"])
    b = ran["unknown"]["base"]
    assert b["note"] == UNKNOWN_NOTE and b["local"] is True and b["lodging"] is False, "the price of an unknown distance is unchanged"
    assert "That address could not be found" in b["status"]


def test_a_measured_local_job_is_still_called_local(ran):
    f = ran["nearTyped"]
    assert f["distance"]["miles"] == 30 and f["local"] is True
    assert f["inert"] == [LOCAL_CARD] and f["saysLocal"] is True


def test_the_precision_survives_a_reload(ran):
    f = ran["reload"]
    assert f["asked"] == 0
    assert f["distance"]["precision"] == "city" and f["distance"]["measured_to"] == "Wichita, KS" and f["distance"]["key"] == CITY_KEY
    assert f["note"] == APPROX_NOTE and f["status"] == APPROX_STATUS


def test_no_place_at_all_asks_nothing_and_says_what_is_enough(ran):
    f = ran["blank"]
    assert f["asked"] == 0 and f["distance"] is None
    assert f["status"] == INCOMPLETE
    assert f["inert"] == [UNKNOWN_CARD]


def test_a_city_and_state_alone_is_enough(ran):
    f = ran["cityOnly"]
    assert f["asked"] == 1 and f["bodies"][0] == {"address": "", "city": "Wichita", "state": "KS", "zip": "", "county": ""}
    assert f["distance"]["key"] == "|wichita|ks||" and f["note"] == APPROX_NOTE


def test_a_county_alone_is_enough_and_is_worded_as_the_county_center(ran):
    f = ran["countyOnly"]
    assert f["asked"] == 1 and f["bodies"][0]["county"] == "Sedgwick County, KS"
    assert f["distance"]["precision"] == "county"
    assert f["note"] == "About 186 miles to Sedgwick County, KS (county center)"


def test_a_street_the_geocoder_missed_is_said_so(ran):
    f = ran["streetMissed"]
    assert f["asked"] == 1 and f["distance"]["precision"] == "city" and f["distance"]["street_not_found"] is True
    assert f["note"] == APPROX_NOTE and f["status"] == MISSED_STATUS


# ── each guard, broken ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
KEY_GUARD = "    if (!(z || (c && s) || (k && (s || countyState)))) return \"\";"
STREET_KEY = "    if (a && ((c && s) || z)) return [a, c, s, z].join(\"|\");"
WANTS_APPROX = "    if (!isApproxDistance(dist)) return false;"
WANTS_NONE = "    if (!dist) return true;"
INIT_GATE = "    if ((!newBid || laborDefaults) && B.distanceWantsLookup(ROOT.distance, addressKey())) lookupDistance(false);"
SEND_COUNTY = "                               zip: s.zip || \"\", county: s.county || \"\" }),"
KEEP_PRECISION = "    if (APPROX_PRECISIONS.indexOf(d.precision) >= 0 || d.precision === \"street\") out.precision = d.precision;"
APPLY_PRECISION = "    if (precision) model.distance.precision = precision;"
NOTE_APPROX = "    if (isApproxDistance(d)) return \"About \" + Math.round(n) + \" miles to \" + (d.measured_to || \"the job\") + \" (\" + PRECISION_WORDS[d.precision] + \")\";"
INERT_UNKNOWN = "    if (!d || milesOrNull(d.miles) === null) {"
STATUS_APPROX = "    if (d && B.isApproxDistance(d)) return d.street_not_found"

BREAKS = {
    "a county alone is not enough to ask": (
        "js/bid-model.js", KEY_GUARD, "    if (!(z || (c && s))) return \"\";",
        lambda g: g["countyOnly"]["asked"] != 1),
    "a city and state alone is not enough to ask": (
        "js/bid-model.js", KEY_GUARD, "    if (!(z || (k && (s || countyState)))) return \"\";",
        lambda g: g["cityOnly"]["asked"] != 1),
    "a street's key carries the county": (
        "js/bid-model.js", STREET_KEY, "    if (false) return \"\";",
        lambda g: g["legacySame"]["status"] != ""),
    "a street figure is measured again when the address moves": (
        "js/bid-model.js", WANTS_APPROX, "    if (false) return false;",
        lambda g: g["streetMoved"]["asked"] != 0),
    "a saved bid with no distance is not asked on open": (
        "js/bid-model.js", WANTS_NONE, "    if (!dist) return false;",
        lambda g: g["savedNone"]["asked"] != 1),
    "the open asks only for a new bid": (
        "js/polish-estimate.js", INIT_GATE, "    if (newBid && laborDefaults && !ROOT.distance) lookupDistance(false);",
        lambda g: g["savedNone"]["asked"] != 1 or g["approxMoved"]["asked"] != 1),
    "the county is not sent": (
        "js/polish-estimate.js", SEND_COUNTY, "                               zip: s.zip || \"\" }),",
        lambda g: "county" not in g["newCity"]["bodies"][0]),
    "the precision is dropped on a reload": (
        "js/bid-model.js", KEEP_PRECISION, "    void d;",
        lambda g: g["reload"]["distance"].get("precision") != "city" or g["reload"]["note"] != APPROX_NOTE),
    "the precision of an answer is not kept": (
        "js/bid-model.js", APPLY_PRECISION, "    void precision;",
        lambda g: g["newCity"]["distance"].get("precision") != "city"),
    "an approximate figure is worded as exact": (
        "js/bid-model.js", NOTE_APPROX, "    void d;",
        lambda g: g["newCity"]["note"] != APPROX_NOTE),
    "an unknown distance is called local": (
        "js/bid-model.js", INERT_UNKNOWN, "    if (false) {",
        lambda g: g["unknown"]["base"]["saysLocal"] is not False or g["unknown"]["option"]["saysLocal"] is not False),
    "the status does not say the figure is approximate": (
        "js/polish-estimate.js", STATUS_APPROX, "    if (false) return d.street_not_found",
        lambda g: g["newCity"]["status"] != APPROX_STATUS or g["streetMissed"]["status"] != MISSED_STATUS),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """A break that stops the harness, or makes a section throw, is not counted as noticed: it has no facts to compare."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the break stopped the harness outright, so no fact noticed it: " + name + "\n" + proc.stderr[-600:]
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed %s instead of changing a fact: %s (%s)" % (", ".join(crashed), name, "; ".join(got[k]["error"][:200] for k in crashed))
    assert noticed(got), "the scenarios did not notice: " + name
