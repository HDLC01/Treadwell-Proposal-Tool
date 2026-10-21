"""ROUND 7, PART 1 (2026-10-21): TWO DRIVES ON A COMBO, AND THE ANSWER MODEL THEY NEED, on the real estimate page (tests/js/travel-round7-harness.js runs js/polish-estimate.js over
the real js/bid-model.js; every reopen is a jsonb one).

HANZ'S DECISIONS OF 2026-10-21:
  D1  A FAR COMBO HAS TWO DRIVES, ONE PER BASE CREW. The Epoxy and the Polish crews travel separately: Kyle's own combo-like estimates put a drive on BOTH sheets, each its own crew x
      its own round trip ("Epoxy trv 4x4; Polish trv 6x4"). Each BASE sheet carries its own Travel Labor row, that base's crew size x the round trip x the rate, filled on a far
      answer, typeable, its own answer. The job's Lodging and Per Diem stay ONE pair of lines whose nights are summed over the bases (round 6). An option still prices its own drive
      and nights. A single-base job keeps one drive on its base. Until now the Combo charged ONE drive, on the Polish carrier, for the bigger of the two crews: far Polish 4 x 12 and
      Epoxy 5 x 12 were 5 x 6.5 = $1,072.50 on Polish and nothing on Epoxy. Now Polish 4 x 6.5 = $858 and Epoxy 5 x 6.5 = $1,072.50.
  D2  A GYP BASE'S DRIVE FILLS FROM THE MILES like Polish and Epoxy (crew size x round trip x rate), still typeable; the crew size is read off its crew lines (entered in hours) by the rule
      ownCrewSize uses. It was typed and never filled ($0 on a far Gyp quote until somebody typed it).
  D3  After the drive of a SINGLE-base job is removed with its x, a job-type switch keeps the drive removed (no seed, no carry; Add Travel Labor brings it back).

THE ANSWER MODEL:
  J  the x on the drive of a single-base job says the job has no drive (the root's `no_travel_labor`), and it survives job-type switches (D3); Add Travel Labor clears it.
  S  on a two-base Combo the x on ONE base's drive is that sheet's own answer (`sheet_no_travel_labor` on the section; the root's own key when the sheet is the root): the other base keeps
     its drive, Add Travel Labor on the sheet takes it back, and when the job goes back to one base the remaining base keeps its own answer.
  O  an option's x is the option's own answer and records nothing (round 6).
  P  a job-type switch or base pick that turns an option into a base keeps a drive line the estimator ADDED (Add Travel Labor) or TYPED on it; a line the TOOL filled is refilled by the
     rule of its new role, and while the job says it has no drive (J) it is released, not re-added (the round-6 audit's F-C).
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round7-harness.js"
SECTIONS = ("combo", "single", "gyp", "sheet", "rootSheet", "job", "promotion")

POLISH_DRIVE = "4 x 6.5 = $858"
EPOXY_DRIVE = "5 x 6.5 = $1072.5"
TRIP = "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the %d guys on the labor lines above"
NOTE = ("This sheet's crew drives on its own: its Travel Labor below is one round trip for each of its guys, from the miles on the Polish section. "
        "Hotel and Per Diem are charged once for the whole job, on the Polish section. Open it to change them.")
FILL_CAP = ("Travel is expected when the job is 70 miles or more from the office. Under 70 miles all three lines below stay gray until you switch one on. On a far job Travel Labor "
            "fills in from the miles, and the nights and per diem days from the crew's hours, 10 hours a night; type over any of them to use your own.")
FILL_CARD = ("Drive time is expected at 70 miles or more from the office. There the hours fill in from the miles, one round trip, and the guys are the most on any labor line. "
             "Under 70 miles this line stays gray.")
FILLED = {"auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hand": False}
NO_ANSWER = {"job": False, "sheets": {}}


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


def _same_after_a_reload(session, reloaded):
    assert session["rows"] == reloaded["rows"] and session["answers"] == reloaded["answers"] and session["price"] == reloaded["price"], \
        "the session and a jsonb reload of what it saved disagree:\n%r\n%r" % (session, reloaded)


# ── D1: a far Combo has two drives, one per base crew ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_far_combo_carries_one_drive_per_base_crew_each_on_its_own_crew(ran):
    s = ran["combo"]["session"]
    assert s["carrier"] == "Polish"
    assert s["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE}
    assert s["marks"] == {"polish": FILLED, "epoxy": FILLED}, "each base's drive is filled on the far answer and follows its own crew"
    assert s["answers"] == NO_ANSWER
    assert s["epoxyLabor"] == 15840 + 1072.5, "the Epoxy crew's drive is the Epoxy sheet's labor"


def test_the_jobs_lodging_and_per_diem_stay_one_pair_of_lines_with_the_nights_of_both_bases(ran):
    """One pair of lines, on the carrier, its nights summed over the two bases (48 + 60 and the Epoxy drive's half dollar, which the sheet's own count carries: 108.0019)."""
    s = ran["combo"]["session"]
    assert s["lodging"] == {"qty": 108, "follow": "labor", "on": True} and s["perDiem"] == {"qty": 108, "follow": "labor"}
    assert s["nights"] == pytest.approx(108 + 0.5 / 264)
    r = ran["combo"]["review"]
    assert r["polish"]["lodging"] == "108.0019" and r["epoxy"]["lodging"] is None
    assert r["epoxy"]["hotelOnce"] is True and r["polish"]["hotelOnce"] is False


def test_each_base_shows_its_own_travel_card_on_the_labor_step(ran):
    """The carrier's Labor step keeps the miles, its own Travel Labor card and the job's Lodging and Per Diem. The other base's Labor step has its own Travel Labor card in its travel
    block, under a note that says its crew drives on its own and that Hotel and Per Diem are charged once, on the Polish section; it has no miles box and no Lodging card."""
    p, e = ran["combo"]["labor"]["polish"], ran["combo"]["labor"]["epoxy"]
    assert p["card"] is True and p["miles"] is True and p["lodging"] is True and p["note"] is None
    assert p["src"] == TRIP % 4 + ". Type more trips for a long job." and p["hint"] == "Most guys on one labor line above: 4."
    assert e["card"] is True and e["miles"] is False and e["lodging"] is False and e["add"] is False
    assert e["note"] == NOTE
    assert e["src"] == TRIP % 5 + ". Type more trips for a long job." and e["hint"] == "Most guys on one labor line above: 5."


def test_each_bases_drive_is_under_its_own_section_on_the_review(ran):
    r = ran["combo"]["review"]
    assert r["polish"]["drive"]["sentence"] == TRIP % 4 and r["polish"]["drive"]["q"] == "26" and r["polish"]["drive"]["tot"] == "$858"
    assert r["epoxy"]["drive"]["sentence"] == TRIP % 5 and r["epoxy"]["drive"]["q"] == "32.5" and r["epoxy"]["drive"]["tot"] == "$1,072.50"


def test_a_far_combo_prices_the_second_crews_drive_and_a_reload_prices_it_the_same(ran):
    """The price effect: the Epoxy section carries its crew's drive (the one-drive law priced the bid at $90,422, the Polish section at $53,378 with the bigger crew's drive and the Epoxy section at
    $37,044 with none). A jsonb reload of what the session saved opens quietly at the same prices; 300 miles typed then moves each base's drive to its own crew x 10 hours, in the session and
    after the reload alike."""
    c = ran["combo"]
    assert c["price"]["sections"]["Epoxy"] > 37044 and c["price"]["root"] < 53378
    assert c["reopened"]["quiet"] == {"armed": 0, "saves": 0}
    assert c["reopened"]["state"]["rows"] == c["session"]["rows"] and c["reopened"]["state"]["price"] == c["price"]
    assert c["at300"]["session"]["rows"] == {"Polish:base": "4 x 10 = $1320", "Epoxy:base": "5 x 10 = $1650"}
    _same_after_a_reload(c["at300"]["session"], c["at300"]["reload"])


def test_a_single_base_job_keeps_one_drive_on_its_base(ran):
    s = ran["single"]
    assert s["polish"] == {"Polish:base": POLISH_DRIVE}
    assert s["epoxyCarrier"] == "Epoxy" and s["epoxy"]["Epoxy:base"] == EPOXY_DRIVE


# ── D2: a Gyp base's drive fills from the miles ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_far_gyp_bases_drive_fills_from_the_miles_on_its_crews_size(ran):
    g = ran["gyp"]
    assert g["filled"]["rows"]['Gyp (USG 1-8"):base'] == POLISH_DRIVE and g["filled"]["marks"] == FILLED
    assert g["grown"]['Gyp (USG 1-8"):base'] == "6 x 6.5 = $1287", "the guys follow the crew line's guys (6 on the pour)"
    assert g["reloaded"]["quiet"] == {"armed": 0, "saves": 0} and g["reloaded"]["rows"] == g["grown"]
    assert g["local"]['Gyp (USG 1-8"):base'] == " x  = $0", "a job under 70 miles fills nothing"


def test_the_gyp_cards_say_the_drive_fills_in(ran):
    lab = ran["gyp"]["labor"]
    assert lab["cap"] == FILL_CAP and lab["cardNote"] == FILL_CARD
    assert lab["src"] == TRIP % 4 + ". Type more trips for a long job." and lab["hint"] == "Most guys on one labor line above: 4."


# ── S: the x on one base's drive of a Combo is that sheet's answer ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_x_on_one_bases_drive_of_a_combo_is_that_sheets_answer_and_the_other_keeps_its_drive(ran):
    s = ran["sheet"]
    assert s["x"] is True
    assert s["afterX"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": None}
    assert s["afterX"]["answers"] == {"job": False, "sheets": {"Epoxy": True}}
    assert s["labor"]["add"] is True and s["labor"]["none"] == "sheet" and s["labor"]["note"] == NOTE
    _same_after_a_reload(s["afterX"], s["reloaded"])
    assert s["at300"]["session"]["rows"] == {"Polish:base": "4 x 10 = $1320", "Epoxy:base": None}
    _same_after_a_reload(s["at300"]["session"], s["at300"]["reload"])


def test_back_to_one_base_the_remaining_base_keeps_its_own_answer_and_add_takes_it_back(ran):
    s = ran["sheet"]
    one = s["oneBase"]
    assert one["state"]["rows"]["Epoxy:base"] is None and one["state"]["answers"] == {"job": False, "sheets": {"Epoxy": True}}
    assert one["labor"]["add"] is True
    _same_after_a_reload(one["state"], s["oneBaseReloaded"])
    a = s["afterAdd"]
    assert a["added"] is True and a["state"]["rows"]["Epoxy:base"] == "5 x 10 = $1650" and a["state"]["answers"] == NO_ANSWER
    assert a["marks"]["hand"] is True and a["marks"]["follow"] == "crew"


def test_the_x_on_the_carriers_drive_of_a_combo_is_the_polish_sheets_answer_and_not_the_jobs(ran):
    """The x on the Polish root's drive of a far Combo records the Polish sheet's own answer (the root's `sheet_no_travel_labor`), not the job's: the Epoxy base keeps its drive. A reload gives
    the root no blank Travel Labor row (migrateModel reads the sheet's answer too), so the session and the reload price the same, and so do they after 300 miles. Back to Polish alone, the
    root keeps its own answer."""
    s = ran["rootSheet"]
    assert s["x"] is True
    assert s["afterX"]["rows"] == {"Polish:base": None, "Epoxy:base": EPOXY_DRIVE}
    assert s["afterX"]["answers"] == {"job": False, "sheets": {"Polish": True}}
    assert s["reloaded"]["quiet"] == {"armed": 0, "saves": 0}
    _same_after_a_reload(s["afterX"], s["reloaded"]["state"])
    assert s["at300"]["session"]["rows"] == {"Polish:base": None, "Epoxy:base": "5 x 10 = $1650"}
    _same_after_a_reload(s["at300"]["session"], s["at300"]["reload"])
    assert s["polish"]["rows"]["Polish:base"] is None and s["polish"]["answers"] == {"job": False, "sheets": {"Polish": True}}


# ── J and D3: the x on a single-base job's drive is the job's answer ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_jobs_answer_holds_through_a_switch_to_combo_and_add_on_one_base_leaves_the_other_its_answer(ran):
    """Far Polish, the x on its drive (J), the job type Combo: neither base is given a drive (no seed, no carry), and Add Travel Labor is drawn on both. Add on the Epoxy sheet gives Epoxy its
    drive and takes the job's answer back; the Polish sheet goes on saying it has none, as its own answer. Back to Polish alone, Polish has no drive. A reload agrees at every point."""
    j = ran["job"]
    assert j["x"] is True
    c = j["combo"]
    assert c["state"]["rows"] == {"Polish:base": None, "Epoxy:base": None} and c["state"]["answers"] == {"job": True, "sheets": {}}
    assert c["addOnPolish"] is True and c["addOnEpoxy"] is True
    _same_after_a_reload(c["state"], j["comboReloaded"])
    a = j["afterAdd"]
    assert a["added"] is True and a["state"]["rows"] == {"Polish:base": None, "Epoxy:base": EPOXY_DRIVE}
    assert a["state"]["answers"] == {"job": False, "sheets": {"Polish": True}} and a["marks"]["hand"] is True
    _same_after_a_reload(a["state"], j["addReloaded"])
    assert j["backToPolish"]["rows"]["Polish:base"] is None and j["backToPolish"]["answers"] == {"job": False, "sheets": {"Polish": True}}


# ── P: an option made a base (the round-6 audit's F-C) ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_tool_filled_line_on_an_option_made_the_base_is_released_while_the_job_says_it_has_no_drive(ran):
    """A far Combo's Epoxy base, demoted by picking Polish alone, keeps its own drive as an option (5 x 6.5, filled by the tool). The x on the Polish drive (J), then Epoxy made the base: by the
    Sheets panel's pick and by the intake's job type alike, the tool's line is released, not re-added, and the job still says it has no drive. A reload agrees."""
    t = ran["promotion"]["toolUnderJob"]
    assert t["demoted"] == {"Polish:base": POLISH_DRIVE, "Epoxy:option": EPOXY_DRIVE}
    assert t["x"] is True and t["before"] == {"job": True, "sheets": {}}
    assert t["pick"]["rows"] == {"Polish:option": None, "Epoxy:base": None} and t["pick"]["answers"] == {"job": True, "sheets": {}}
    assert t["switched"]["rows"] == {"Polish:off": None, "Epoxy:base": None} and t["switched"]["answers"] == {"job": True, "sheets": {}}
    assert t["pick"]["price"]["lump"] == t["switched"]["price"]["lump"]
    _same_after_a_reload(t["pick"], t["pickReloaded"])
    _same_after_a_reload(t["switched"], t["switchReloaded"])


def test_a_line_the_estimator_added_on_an_option_made_the_base_is_kept_and_the_job_has_a_drive_again(ran):
    a = ran["promotion"]["addedUnderJob"]
    assert a["x"] is True and a["added"] is True and a["marks"]["hand"] is True
    assert a["pick"]["rows"] == {"Polish:option": None, "Epoxy:base": EPOXY_DRIVE} and a["pick"]["answers"] == NO_ANSWER
    assert a["switched"]["rows"] == {"Polish:off": None, "Epoxy:base": EPOXY_DRIVE} and a["switched"]["answers"] == NO_ANSWER
    assert a["pick"]["price"]["lump"] == a["switched"]["price"]["lump"]
    _same_after_a_reload(a["pick"], a["pickReloaded"])
    _same_after_a_reload(a["switched"], a["switchReloaded"])


def test_a_copys_tool_filled_line_is_released_and_a_typed_one_is_kept_when_the_copy_is_made_the_base(ran):
    c = ran["promotion"]["copyUnderJob"]
    assert c["copy"] == "Copy1" and c["x"] is True
    assert c["toolPick"]["rows"] == {"Polish:option": None, "Copy1:base": None} and c["toolPick"]["answers"] == {"job": True, "sheets": {}}
    assert c["typedPick"]["rows"] == {"Polish:option": None, "Copy1:base": "3 x 5 = $495"} and c["typedPick"]["answers"] == NO_ANSWER
    assert c["typedMarks"]["typed"] is True
    _same_after_a_reload(c["toolPick"], c["toolReloaded"])
    _same_after_a_reload(c["typedPick"], c["typedReloaded"])


def test_an_option_made_the_base_keeps_its_own_drive_refilled_and_the_old_bases_typed_line_stays_its_own(ran):
    """Not under the job's answer. The Epoxy option's own drive (its crew, 5 x 6.5, filled by the tool) is refilled by its new role when it is made the base; the Polish sheet's typed 3 x 5,
    demoted with it, stays the Polish option's own. Until now the two changed places (followOwnedRow): the Epoxy base took the Polish crew's 3 x 5 and its own drive was emptied onto the
    Polish option. A reload agrees, and 300 miles moves the Epoxy base's own drive (the typed line stays as typed)."""
    r = ran["promotion"]["refill"]
    assert r["session"]["rows"] == {"Polish:option": "3 x 5 = $495", "Epoxy:base": EPOXY_DRIVE}
    assert r["epoxyMarks"]["follow"] == "crew" and r["epoxyMarks"]["typed"] is False
    _same_after_a_reload(r["session"], r["reloaded"])
    assert r["at300"] == {"Polish:option": "3 x 5 = $495", "Epoxy:base": "5 x 10 = $1650"}
