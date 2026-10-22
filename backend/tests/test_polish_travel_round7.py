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

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round7-harness.js"
SECTIONS = ("combo", "single", "gyp", "sheet", "rootSheet", "job", "promotion", "added", "copies", "declined", "legacy")
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

POLISH_DRIVE = "4 x 6.5 = $858"
EPOXY_DRIVE = "5 x 6.5 = $1072.5"
TRIP = "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the %d guys on the labor lines above"
NOTE = ("This sheet's guys drive on their own: its Travel Labor below is one round trip for each of them, from the miles on the Polish section. "
        "Hotel and Per Diem are charged once for the whole job, on the Polish section. Open it to change them.")
# A base whose x took its Travel Labor line away holds no drive to describe, so its note is the Hotel and Per Diem sentence alone (round 7 polish, W1: test_polish_travel_words_polish.py holds it).
NOTE_NO_LINE = "Hotel and Per Diem are charged once for the whole job, on the Polish section. Open it to change them."
# (Since round 7, part 4, P2, a Gyp drive is a round trip for each mobilization on the Gyp card, and the Gyp words say so: test_polish_travel_round7_part4.py.)
FILL_CAP = ("Travel is expected when the job is 70 miles or more from the office. Under 70 miles all three lines below stay gray until you switch one on. On a far job Travel Labor "
            "fills in from the miles, a round trip for each mobilization, and the nights and per diem days from the crew's hours, 10 hours a night; type over any of them to use your own.")
FILL_CARD = ("Drive time is expected at 70 miles or more from the office. There the hours fill in from the miles, one round trip for each mobilization on the Gyp card, and the guys are "
             "the most on any labor line. Under 70 miles this line stays gray.")
FILLED = {"auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hand": False}
NO_ANSWER = {"job": False, "sheets": {}}
# A far Epoxy 5 x 12 bid with its crew's drive (5 x 6.5 = $1,072.50): what the saved one-drive Combo is once it is made Epoxy, the same as an Epoxy job bid from scratch on that crew
# (test_polish_travel_switch.py's demoted Epoxy at 190 miles is $49,281 too). With no drive it was $47,221.
LEGACY_EPOXY_LUMP = 49281


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
    """Each base's Review lists its own crew's drive under its Labor. The Epoxy sheet's Hotel and Per Diem card says they are charged once, on the Polish section, and that this sheet's own
    drive is its Travel Labor line, under Labor (until round 7 it said Travel was charged there too)."""
    r = ran["combo"]["review"]
    assert r["polish"]["drive"]["sentence"] == TRIP % 4 and r["polish"]["drive"]["q"] == "26" and r["polish"]["drive"]["tot"] == "$858"
    assert r["epoxy"]["drive"]["sentence"] == TRIP % 5 and r["epoxy"]["drive"]["q"] == "32.5" and r["epoxy"]["drive"]["tot"] == "$1,072.50"
    assert r["epoxy"]["ownDrive"] is True and r["polish"]["ownDrive"] is False


def test_the_carriers_how_note_lists_the_other_bases_own_drive(ran):
    """The how-it-is-worked-out note on the carrier's Labor step (where the miles are) lists the other base's own drive, on that sheet's own guys, beside its own."""
    how = ran["combo"]["labor"]["polish"]["how"]
    assert "Travel Labor: 4 guys x 6.5 drive hours" in how
    assert "Travel Labor on the Epoxy sheet: 5 guys x 6.5 drive hours x $33.00 = $1,072.50 (that sheet's own guys)." in how
    assert "Guys = the most guys on any one labor line above (4 now), one round trip each." in how


def test_a_far_combo_prices_the_second_crews_drive_and_a_reload_prices_it_the_same(ran):
    """THE PRICE EFFECT (D1). Far Combo, Polish 4 x 12 and Epoxy 5 x 12, 190 miles: the bid is $92,153, the Polish section $52,956 with its own crew's 4 x 6.5 = $858 and the Epoxy section
    $39,197 with its crew's 5 x 6.5 = $1,072.50. The one-drive law priced it at $90,422: the Polish section $53,378 with the bigger crew's drive (5 x 6.5) and the Epoxy section $37,044 with
    none. So the bid rises by the smaller crew's drive, $858 before the markups and $1,731 after them. A jsonb reload of what the session saved opens
    quietly at the same prices; 300 miles typed then moves each base's drive to its own crew x 10 hours, in the session and after the reload alike."""
    c = ran["combo"]
    assert c["price"] == {"lump": 92153, "root": 52956, "sections": {"Epoxy": 39197}}
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
    assert lab["src"] == TRIP % 4 + ". A round trip for each mobilization typed on the Gyp card." and lab["hint"] == "Most guys on one labor line above: 4."


# ── S: the x on one base's drive of a Combo is that sheet's answer ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_x_on_one_bases_drive_of_a_combo_is_that_sheets_answer_and_the_other_keeps_its_drive(ran):
    s = ran["sheet"]
    assert s["x"] is True
    assert s["afterX"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": None}
    assert s["afterX"]["answers"] == {"job": False, "sheets": {"Epoxy": True}}
    assert s["labor"]["add"] is True and s["labor"]["none"] == "sheet" and s["labor"]["note"] == NOTE_NO_LINE
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


# ── D1: a sheet that becomes a base with no line is given its own; a copy is a new sheet; the library's decline is a sheet's answer ───────────────────────────────────────
def test_a_sheet_that_becomes_a_base_with_no_line_is_given_its_own_drive_at_the_bids_rate(ran):
    """Far Polish 4 x 12 (the library's Travel at $36), the Epoxy sheet added as an option (a fresh sheet holds no Travel Labor line) with its crew 5 x 12, then the pair made the base: by the Sheets
    panel's combined pick and by the intake's job type Combo alike, the Epoxy sheet is given its own line at the bid's own Travel rate (the root's line's default, $36; the shipped rate is $33) and
    the distance on file fills it on its own crew, 5 x 6.5 x $36 = $1,170, beside the Polish crew's 4 x 6.5 x $36 = $936. Under the one-drive law it was given none. A reload prices the same."""
    a = ran["added"]
    assert a["before"] == {"Polish:base": "4 x 6.5 = $936", "Epoxy:option": None}
    for k in ("pick", "switched"):
        assert a[k]["rows"] == {"Polish:base": "4 x 6.5 = $936", "Epoxy:base": "5 x 6.5 = $1170"} and a[k]["answers"] == NO_ANSWER, k
    assert a["pickMarks"] == FILLED and a["switchMarks"] == FILLED
    assert a["pick"]["price"] == a["switched"]["price"] == {"lump": 91616, "root": 53104, "sections": {"Epoxy": 38512}}
    _same_after_a_reload(a["pick"], a["pickReloaded"])
    _same_after_a_reload(a["switched"], a["switchReloaded"])


def test_a_copy_of_a_sheet_takes_neither_its_answer_nor_the_mark_of_an_added_line(ran):
    """A copy is a new sheet, an option priced apart. The x on the Epoxy base's drive of a far Combo is the Epoxy sheet's own answer (S); a copy of the sheet made then does not say it (it is an
    option, whose x records nothing). Add Travel Labor on the Epoxy sheet marks the line as the estimator's own (`hand_added`, which keeps it when an option is made a base under the job's answer);
    a copy of the sheet made then holds its own line, a copy of the drive, without the mark: nobody added it to the copy."""
    c = ran["copies"]
    assert c["x"] is True and c["added"] is True and (c["first"], c["second"]) == ("Copy1", "Copy2")
    assert c["afterFirst"]["answers"] == {"job": False, "sheets": {"Epoxy": True}}
    assert c["afterFirst"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": None, "Copy1:option": None}
    assert c["answers"] == NO_ANSWER and c["epoxyMarks"]["hand"] is True
    assert c["rows"]["Copy2:option"] == EPOXY_DRIVE and c["secondMarks"] == FILLED


def test_the_librarys_decline_on_a_new_combo_is_each_sheets_own_answer(ran):
    """The library's Travel row on Polish bids only: a new far Combo seeds the Polish sheet's drive, and the Epoxy sheet says it has none as its own answer (S), not the job's (J). On Epoxy bids only:
    the Epoxy sheet's drive, and the Polish sheet's own answer (the root's `sheet_no_travel_labor`), so a reload gives the root no blank line. Until round 7 only the carrier was seeded, and the
    decline read off it said the JOB had no drive. Each reloads quietly at the same prices."""
    d = ran["declined"]
    p, e = d["polishOnly"], d["epoxyOnly"]
    assert p["session"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": None} and p["session"]["answers"] == {"job": False, "sheets": {"Epoxy": True}}
    assert e["session"]["rows"] == {"Polish:base": None, "Epoxy:base": EPOXY_DRIVE} and e["session"]["answers"] == {"job": False, "sheets": {"Polish": True}}
    for s in (p, e):
        assert s["quiet"] == {"armed": 0, "saves": 0}
        _same_after_a_reload(s["session"], s["reloaded"])


def test_a_line_added_on_an_option_made_one_of_a_pair_of_bases_leaves_the_other_sheet_its_answer(ran):
    """The job said it has no drive (the x on far Polish's drive), the Epoxy sheet was added and given its own drive with Add Travel Labor, and then the pair is made the base: by the combined
    pick and by the job type Combo alike, the added line stays (the job has a drive again, on Epoxy) and the job's answer goes on speaking for the Polish sheet, which has no line, as its own (S),
    so a reload gives the root no blank line. A reload prices the same."""
    a = ran["promotion"]["addedUnderJobPair"]
    for k in ("pick", "switched"):
        assert a[k]["rows"] == {"Polish:base": None, "Epoxy:base": EPOXY_DRIVE} and a[k]["answers"] == {"job": False, "sheets": {"Polish": True}}, k
    assert a["pick"]["price"] == a["switched"]["price"]
    _same_after_a_reload(a["pick"], a["pickReloaded"])
    _same_after_a_reload(a["switched"], a["switchReloaded"])


# ── a Combo saved under the one-drive law (before round 7) ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_combo_saved_under_the_one_drive_law_opens_with_the_epoxy_crews_own_drive(ran):
    """A far Combo saved before round 7: the job's one drive on the Polish root, for the bigger crew (Epoxy's 5), and no Travel Labor line on the Epoxy sheet. Opened plainly, nothing is asked.
    Since round 7, part 4 (P4: the round-7 audit's F7, Hanz's D1 and "let them re-price") the Epoxy base is given its own drive on open, filled by the rule on its own crew (5 x 6.5), and
    the root's drive reads the Polish crew's own 4 (the guys are kept in step with the crews on every open), so the page shows $52,956 + $39,197, the price of the same Combo bid since round 7, and
    the Epoxy sheet's Labor step draws its drive. Until part 4 nothing gave a saved bid a line on open, and the page showed $52,953 + $37,044 = $89,997 with the Epoxy crew's drive missing; the
    one-drive law priced it at $53,378 + $37,044 = $90,422. The open arms ONE save, so the draft, and the Proposal that reads it, holds the price the page shows (the pass-2 audit's A1;
    test_polish_travel_round7_part4.py holds that save, the session and the reloads)."""
    o = ran["legacy"]["opened"]
    assert o["quiet"] == {"armed": 1, "saves": 0}
    assert o["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE}
    assert o["bid"] == {"root": 52956, "epoxy": 39197}
    assert o["epoxy"]["add"] is False and o["epoxy"]["none"] is None and o["epoxy"]["note"] == NOTE and o["epoxy"]["card"] is True


def test_a_combo_saved_under_the_one_drive_law_made_one_base_keeps_each_crews_own_drive(ran):
    """The same saved Combo made Epoxy (the intake's job type) or with Epoxy picked alone (the Sheets panel). The Epoxy base opened with its own drive (P4), so it keeps it, on the Epoxy crew's
    5 x 6.5, the Polish root, off, gives its fill back, and the Epoxy job prices $49,281 both ways (round 7's first cut priced it with no Travel Labor at all, $47,221; part 1 carried the root's line
    to Epoxy). A reload prices the same. Made Polish, the root keeps its own drive and the Epoxy sheet, off, gives its fill back."""
    leg = ran["legacy"]
    e = leg["toEpoxy"]
    assert e["state"]["rows"] == {"Polish:off": " x  = $0", "Epoxy:base": EPOXY_DRIVE} and e["state"]["answers"] == NO_ANSWER
    assert e["marks"] == FILLED
    assert e["state"]["price"]["lump"] == LEGACY_EPOXY_LUMP and e["state"]["price"]["lump"] > 47221
    _same_after_a_reload(e["state"], e["reloaded"])
    k = leg["picked"]
    assert k["state"]["rows"] == {"Polish:option": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE} and k["state"]["answers"] == NO_ANSWER
    assert k["state"]["price"]["lump"] == LEGACY_EPOXY_LUMP
    _same_after_a_reload(k["state"], k["reloaded"])
    p = leg["toPolish"]
    assert p["state"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:off": " x  = $0"}
    _same_after_a_reload(p["state"], p["reloaded"])


# ── red without the code: break a COPY of the page or the model one line at a time; a fact must change, never a crash ───────────────────────────────────────────────────
BREAKS = {
    # --- D1: every base drives its own crew ---
    "only the first base drives": (
        "js/bid-model.js", "      if (list.length) return list;", "      if (list.length) return list.slice(0, 1);",
        lambda g: g["combo"]["session"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    "a base's drive follows the biggest crew of both bases": (
        "js/bid-model.js", 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? ownCrewSize(model, lines) : manDays;',
        'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? crewSize(model) : manDays;',
        lambda g: g["combo"]["session"]["rows"].get("Polish:base") != POLISH_DRIVE),
    "a sheet that becomes a base with no line is given none": (
        "js/bid-model.js", "        e.section.labor.push(freshDriveRow(model));", "        void freshDriveRow;",
        lambda g: g["added"]["pick"]["rows"].get("Epoxy:base") != "5 x 6.5 = $1170" or g["added"]["switched"]["rows"].get("Epoxy:base") != "5 x 6.5 = $1170"),
    "the line a new base is given is not at the bid's own Travel rate": (
        "js/bid-model.js", "if (rate === null && !isBlank(r.rate_default) && isFinite(Number(r.rate_default)) && Number(r.rate_default) > 0) rate = Number(r.rate_default);",
        "void r;",
        lambda g: g["added"]["pick"]["rows"].get("Epoxy:base") != "5 x 6.5 = $1170"),
    "the page does not say what every sheet was before a base pick": (
        "js/polish-estimate.js", "      kindsBefore = B.sectionKinds(ROOT);", "      kindsBefore = null;",
        lambda g: g["added"]["pick"]["rows"].get("Epoxy:base") != "5 x 6.5 = $1170"),
    "the page does not say what every sheet was before a job-type switch": (
        "js/polish-estimate.js", "      var kindsBefore = B.sectionKinds(ROOT);", "      var kindsBefore = null;",
        lambda g: g["added"]["switched"]["rows"].get("Epoxy:base") != "5 x 6.5 = $1170"),
    # (The settling's sync of a carried drive's guys, and the carry of a one-drive-law Combo's drive to the one base left, moved to test_polish_travel_round7_part4.py with round 7, part 4's P4: the
    # open now gives that Combo's second base its own drive, so no page path here reaches the carry, and the part-4 harness holds it on the model.)
    # --- D2: a Gyp base's drive fills ---
    "a Gyp base's drive is not filled": (
        "js/bid-model.js", "    if (row) followDistanceOnRow(model, row, lines, miles, false, driveTripsOf(e));",
        '    if (row && e.layout !== "gyp") followDistanceOnRow(model, row, lines, miles, false, driveTripsOf(e));',
        lambda g: g["gyp"]["filled"]["rows"].get('Gyp (USG 1-8"):base') != POLISH_DRIVE),
    "the Gyp travel block says to type the drive": (
        "js/polish-estimate.js", "          ? 'On a far job Travel Labor fills in from the miles, a round trip for each mobilization, and the nights and per diem days from the crew\\'s hours, ' +",
        "          ? 'On a far Gyp job type the drive hours, because the Gyp sheet works its own drive time. The nights and per diem days fill in from the crew\\'s hours, ' +",
        lambda g: g["gyp"]["labor"]["cap"] != FILL_CAP),
    "the Gyp Travel Labor card says to type its guys and hours": (
        "js/polish-estimate.js", "              (r.id !== \"travel\" ? ''", "              (r.id !== \"travel\" || gypOpen() ? ''",
        lambda g: g["gyp"]["labor"]["cardNote"] != FILL_CARD),
    # --- the second base's own words ---
    "a base with no line is offered an option's Add": (
        "js/polish-estimate.js", '      if (ownDrive) html += travelRows || addTravelHtml("sheet");', "      if (ownDrive) html += travelRows || addTravelHtml(true);",
        lambda g: g["sheet"]["labor"]["none"] != "sheet"),
    "a base with no line is offered no Add": (
        "js/polish-estimate.js", '      if (ownDrive) html += travelRows || addTravelHtml("sheet");', "      if (ownDrive) html += travelRows;",
        lambda g: g["sheet"]["labor"]["add"] is not True),
    "the second base's Review says Travel is charged on the carrier": (
        "js/polish-estimate.js", '      trvRows.push([travelNote(true), "", "", "", ""]);', '      trvRows.push([travelNote(), "", "", "", ""]);',
        lambda g: g["combo"]["review"]["epoxy"]["ownDrive"] is not True),
    "the carrier's how-note leaves out the other base's drive": (
        "js/bid-model.js", "    driveEntries(W).forEach(function (e) {", "    [].forEach(function (e) {",
        lambda g: "Travel Labor on the Epoxy sheet" not in (g["combo"]["labor"]["polish"]["how"] or "")),
    # --- the answers ---
    "the x on one base of a Combo is the job's answer": (
        "js/bid-model.js", "    if (drives.length > 1) hit.section.sheet_no_travel_labor = true;", "    if (false) hit.section.sheet_no_travel_labor = true;",
        lambda g: g["sheet"]["afterX"]["answers"] != {"job": False, "sheets": {"Epoxy": True}}),
    "a reload gives a root that said it has no drive a blank line": (
        "js/bid-model.js", "if (!said && model.sheet_no_travel_labor !== true && carrierTabOf(model) === ROOT_TAB) out.labor = laborIn.concat([travelSeed()]);",
        "if (!said && carrierTabOf(model) === ROOT_TAB) out.labor = laborIn.concat([travelSeed()]);",
        lambda g: g["rootSheet"]["reloaded"]["state"]["rows"].get("Polish:base") is not None),
    "a sheet's answer does not keep the job's drive off it when the job goes back to one base": (
        "js/bid-model.js", '      if (model.no_travel_labor === true || sheetSaidNoDrive(toSection)) return "";', '      if (model.no_travel_labor === true) return "";',
        lambda g: g["sheet"]["oneBase"]["state"]["rows"].get("Epoxy:base") is not None),
    "Add Travel Labor on a base is refused": (
        "js/bid-model.js", "        if (!drive && hit.kind !== \"option\") return false;", "        if (want !== travelCarrier(model) && hit.kind !== \"option\") return false;",
        lambda g: g["job"]["afterAdd"]["state"]["rows"].get("Epoxy:base") != EPOXY_DRIVE or g["copies"]["epoxyMarks"]["hand"] is not True),
    "Add Travel Labor leaves the sheet's own answer": (
        "js/bid-model.js", "    delete holder.sheet_no_travel_labor;", "    void holder;",
        lambda g: g["sheet"]["afterAdd"]["state"]["answers"] != NO_ANSWER),
    "Add Travel Labor under the job's answer leaves the other base nothing to say": (
        "js/bid-model.js", "          if (e.section !== holder && isObject(e.section) && !travelRowsIn(e.section).length) e.section.sheet_no_travel_labor = true;", "          void e;",
        lambda g: g["job"]["afterAdd"]["state"]["answers"] != {"job": False, "sheets": {"Polish": True}} or g["job"]["addReloaded"]["rows"].get("Polish:base") is not None),
    "a restructure that brings back a line under the job's answer leaves the other base nothing to say": (
        "js/bid-model.js", "      if (drives.length > 1) drives.forEach(function (e) { if (isObject(e.section) && !travelRowsIn(e.section).length) e.section.sheet_no_travel_labor = true; });",
        "      void drives;",
        lambda g: g["promotion"]["addedUnderJobPair"]["pick"]["answers"] != {"job": False, "sheets": {"Polish": True}}
        or g["promotion"]["addedUnderJobPair"]["switched"]["answers"] != {"job": False, "sheets": {"Polish": True}}),
    "the library's decline on a base of a Combo is not that sheet's answer": (
        "js/bid-model.js", "      if (drive && drives.length > 1 && travelDeclined(ctx.laborRows, kindOfSection(e.layout))) s.sheet_no_travel_labor = true;", "      void drive;",
        lambda g: g["declined"]["polishOnly"]["session"]["answers"] != {"job": False, "sheets": {"Epoxy": True}}),
    "the library's decline on a Combo's carrier is the job's answer": (
        "js/bid-model.js", "      if (drives.length < 2 && travelDeclined(ctx.laborRows, kindOfSection(sectionOf(out, carrierTab).layout))) out = Object.assign(out, { no_travel_labor: true });",
        "      if (travelDeclined(ctx.laborRows, kindOfSection(sectionOf(out, carrierTab).layout))) out = Object.assign(out, { no_travel_labor: true });",
        lambda g: g["declined"]["epoxyOnly"]["session"]["answers"] != {"job": False, "sheets": {"Polish": True}}),
    "a copy takes the sheet's own answer": (
        "js/bid-model.js", "      delete body.sheet_no_travel_labor;", "      void body;",
        lambda g: g["copies"]["afterFirst"]["answers"] != {"job": False, "sheets": {"Epoxy": True}}),
    "a copy's line keeps the mark of a line the estimator added": (
        "js/bid-model.js", "(body.labor instanceof Array ? body.labor : []).forEach(function (r) { if (isTravelRow(r)) delete r.hand_added; });", "void body;",
        lambda g: (g["copies"]["secondMarks"] or {}).get("hand") is not False),
    # --- an option made a base (F-C): the promotion rule ---
    "the line Add brings back is not marked as the estimator's": (
        "js/bid-model.js", "    added.hand_added = true;", "    void added;",
        lambda g: g["promotion"]["addedUnderJob"]["pick"]["rows"].get("Epoxy:base") != EPOXY_DRIVE or g["sheet"]["afterAdd"]["marks"]["hand"] is not True),
    "an option made a base under the job's answer loses the line the estimator added": (
        "js/bid-model.js", "        releaseNobodysTravelRow(model, tab, wasKind === \"option\");", "        releaseNobodysTravelRow(model, tab, false);",
        lambda g: g["promotion"]["addedUnderJob"]["pick"]["rows"].get("Epoxy:base") != EPOXY_DRIVE or g["promotion"]["addedUnderJob"]["switched"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    "a line nobody added is kept as if it had been": (
        "js/bid-model.js", "!(keepAdded === true && r.hand_added === true)", "!(keepAdded === true)",
        lambda g: g["promotion"]["toolUnderJob"]["pick"]["rows"].get("Epoxy:base") is not None or g["promotion"]["toolUnderJob"]["switched"]["rows"].get("Epoxy:base") is not None),
    "an option made a base under the job's answer keeps the line the tool filled": (
        "js/bid-model.js", "      if (model.no_travel_labor === true || sheetSaidNoDrive(e.section)) {", "      if (false) {",
        lambda g: g["promotion"]["toolUnderJob"]["pick"]["rows"].get("Epoxy:base") is not None or g["promotion"]["toolUnderJob"]["switched"]["rows"].get("Epoxy:base") is not None),
    "the old base's typed line changes places with an option made the base": (
        "js/bid-model.js", '      if (newKind === "option" && travelRowsIn(toSection).length) return "";', "      void newKind;",
        lambda g: g["promotion"]["refill"]["session"]["rows"] != {"Polish:option": "3 x 5 = $495", "Epoxy:base": EPOXY_DRIVE}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line round 7's law depends on, broken in a scratch copy of the page or the model; a FACT must change. A break that stops the harness, or makes a section throw, is not
    counted as noticed: it has no facts to compare."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the break stopped the harness outright, so no fact noticed it: " + name + "\n" + proc.stderr[-600:]
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed %s instead of changing a fact: %s" % (", ".join(crashed), name)
    assert noticed(got), "the scenarios did not notice: " + name
