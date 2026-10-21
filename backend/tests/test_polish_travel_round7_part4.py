"""ROUND 7, PART 4 (2026-10-21): THE ROUND-7 AUDIT'S REMAINING FINDINGS THAT MOVE A PRICE OR CONTRADICT A DECISION, on the real estimate page (tests/js/travel-round7-part4-harness.js runs
js/polish-estimate.js over the real js/bid-model.js; every reopen is a jsonb one). Part 3's F1 is held by test_polish_travel_round7_part3.py (part 4's P1, a copy given back keeping the trip
the estimator typed, was withdrawn by the pass-2 audit's A2: a copy given back is refilled by the rule, as part 3 had it); the Review's Rate cell (P8) by test_v2_review_table_fits.py.

  P2 (F2)  A GYP BASE'S DRIVE IS A ROUND TRIP FOR EACH MOBILIZATION on its Gyp card, as Kyle's Gyp travel line multiplies the round trip by them: Gyp (USG 1-8")!B51 is `=((B6*2)/60)*T28`
           (S28 on Gyp (FR)) and E51 `=A51*B51*C51`. Far Gyp at 190 miles, crew 4 x 120 hours: 4 x 6.5 = $858 with the box blank (one trip: the crew comes out at least once), 4 x 19.5 =
           $2,574 with 3 typed, which D2 priced as one trip. The box moves the drive both ways and the miles move it three trips at a time; hours the estimator typed are theirs; a copy of the Gyp
           sheet follows its own box. Each trip is the one round trip the rule fills, to the half hour (Hanz, 2026-10-20), so the drive is the sheet's own B51 wherever a trip is whole half hours.
  P3 (F3)  THE x ON BOTH DRIVES OF A COMBO IS THE JOB'S ANSWER (J), as the x on a single-base job's drive is (D3): a later job-type switch keeps the drive removed, a new Gyp section included,
           and Add Travel Labor on a base takes it back.
  P4 (F7)  A FAR COMBO SAVED UNDER THE ONE-DRIVE LAW opens with its second base's drive filled by the rule (D1, and "let them re-price"): the open, the session and a jsonb reload price two drives,
           the carrier keeps its own crew's drive. A Combo whose second base's x was pressed (S) is left as it is. THE PASS-2 AUDIT'S A1: the open SAVES what it gives, so the price the
           Review and the Proposal read off the draft is the price the bar shows (it showed $92,153 and the Proposal printed the $90,422 the draft was saved at); and the job's one drive the
           estimator switched off, or whose Guys or Hours box they cleared, is said on the line the second base is given, so no drive they took away comes back ($90,468 shown where it was
           saved at $88,312). Figures they typed on it are the carrier crew's; the second crew drives its own, filled by the rule.
  P5 (F4)  ADD TRAVEL LABOR PUTS THE LINE ON THE SHEET IT WAS PRESSED ON, though another sheet is on show by the time the library answers.
  P6 (F5)  AFTER THE x ON THE CARRIER'S OWN DRIVE OF A COMBO the carrier says THIS SHEET has no Travel Labor line and that the Epoxy sheet keeps its own, never that the bid has none or that the
           drive adds nothing; with both drives gone (J) it says the bid has none.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import SHEETS

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round7-part4-harness.js"
SECTIONS = ("mobs", "bothX", "legacy", "addTarget", "words")
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

GYP = 'Gyp (USG 1-8")'
GYP_ROW = GYP + ":base"
GYP_TABS = [GYP, "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"]
POLISH_DRIVE = "4 x 6.5 = $858"
EPOXY_DRIVE = "5 x 6.5 = $1072.5"
FILLED = {"auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hand": False}
ADDED = dict(FILLED, hand=True)
NO_ANSWER = {"job": False, "sheets": {}}
JOB_SAID = {"job": True, "sheets": {}}
QUIET = {"armed": 0, "saves": 0}
# What a far Combo of Polish 4 x 12 and Epoxy 5 x 12 at 190 miles prices with a drive for each crew (round 7, part 1: $92,153, Polish $52,956 and Epoxy $39,197); the one-drive law priced it
# $90,422, and a saved one opened with the Epoxy crew's drive missing priced $89,997 ($52,953 + $37,044) until this part.
COMBO_PRICE = {"lump": 92153, "root": 52956, "sections": {"Epoxy": 39197}}
ONE_DRIVE_OPENED = {"root": 52953, "epoxy": 37044}
# What the one-drive law SAVED that Combo at (round 6's own figures, the audit's gen_r6_combo.js; the harness has the page save the one-drive shape): the job's one drive on the bigger crew,
# 5 x 6.5 on the Polish section ($53,378) and no drive on the Epoxy section ($37,044); and the same bid with no drive priced on either crew (the drive switched off, a box cleared, or the x).
ONE_DRIVE_SAVED = {"lump": 90422, "tabs": [["Polish", "base", 53378], ["Epoxy", "base", 37044]]}
NO_DRIVE_LUMP = 88312
# The open's one save (the pass-2 audit's A1): armed by the open, nothing written until it runs.
ARMED = {"armed": 1, "saves": 0}


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


def _same(a, b):
    assert a == b, "the session and a jsonb reload of what it saved disagree:\n%r\n%r" % (a, b)


# ── P2 (F2): a Gyp drive is a round trip for each mobilization ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_gyp_sheets_own_travel_line_is_the_round_trip_times_the_mobilizations():
    """THE PIN. Every Gyp tab's travel line is the crew (A51, the prep crew's A46) x the hours (B51: the miles there and back over 60 mph, times the mobilizations, T28; S28 on Gyp (FR), a column
    further left) x the rate (C51), and the profile the engine prices a Gyp section by takes that line as the section's travel labor (E51), which the nights take off the labor dollars (B64)."""
    for tab in GYP_TABS:
        mobs = "S28" if tab == "Gyp (FR)" else "T28"
        assert SHEETS[tab].formula("B51") == "=((B6*2)/60)*%s" % mobs, tab
        assert SHEETS[tab].formula("A51") == "=A46" and SHEETS[tab].formula("E51") == "=A51*B51*C51", tab
    profiles = (FRONTEND / "js" / "bid-profiles.js").read_text(encoding="utf-8")
    assert 'travelLabor:   f("E51", "=A51*B51*C51")' in profiles
    assert 'lodgingQty:         f("B64", "=IF(B5=\\"No\\",((E52-E51)/C46)/10)")' in profiles


def test_the_drive_is_the_sheets_own_b51_wherever_a_round_trip_is_whole_half_hours(ran):
    """The model's drive hours for a far answer, beside the sheet's own B51 at 1 to 4 mobilizations: equal at 90, 180 and 300 miles (round trips of 3, 6 and 10 hours), and at 190 miles each trip
    is the 6.5 hours the rule fills (the 380 mile round trip is 6.33 hours, to the half hour as Kyle types it), so 3 trips are 19.5 where the sheet's unrounded figure is 19."""
    table = {(t["miles"], t["mobs"]): (t["hours"], t["sheet"]) for t in ran["mobs"]["table"]}
    assert len(table) == 16
    for miles in (90, 180, 300):
        for mobs in (1, 2, 3, 4):
            hours, sheet = table[(miles, mobs)]
            assert hours == pytest.approx(sheet, abs=1e-12) and hours == sheet, (miles, mobs, hours, sheet)
    assert [table[(190, m)][0] for m in (1, 2, 3, 4)] == [6.5, 13, 19.5, 26]
    assert table[(190, 3)][1] == pytest.approx(19)


def test_three_mobilizations_at_190_miles_are_three_round_trips(ran):
    """Far Gyp, crew 4 x 120 hours, 190 miles. The Mobilizations box blank: one round trip, 4 x 6.5 = $858 ($44,321, round 7's D2). Three typed on the Gyp card: three round trips, 4 x 19.5 =
    $2,574, and the bid is $47,878. The nights do not move (Gyp!B64 takes the drive off the labor dollars: 48 both ways). A jsonb reload opens quietly at the same rows and prices."""
    m = ran["mobs"]
    assert m["blank"]["rows"][GYP_ROW] == POLISH_DRIVE and m["blank"]["price"]["lump"] == 44321
    assert m["typed3"] is True
    assert m["three"]["rows"][GYP_ROW] == "4 x 19.5 = $2574" and m["three"]["marks"] == dict(FILLED, seed=19.5)
    assert m["three"]["price"]["lump"] == 47878 and m["three"]["nights"] == m["blank"]["nights"] == 48
    assert m["reloaded"]["quiet"] == QUIET and m["reloaded"]["state"]["rows"][GYP_ROW] == "4 x 19.5 = $2574" and m["reloaded"]["state"]["price"] == m["three"]["price"]


def test_the_box_and_the_miles_move_the_drive_and_hours_the_estimator_typed_stay_theirs(ran):
    """300 miles typed: three trips of 10 hours, 4 x 30, in the session and after a reload. The box cleared: one trip again. Hours typed (5), then 2 mobilizations and 300 miles: still 4 x 5, theirs.
    At 180 miles (a whole 6 hour round trip) three trips are 4 x 18, the sheet's own figure."""
    m = ran["mobs"]
    assert m["at300"]["session"][GYP_ROW] == "4 x 30 = $3960" and m["at300"]["session"] == m["at300"]["reload"]
    assert m["cleared"][GYP_ROW] == POLISH_DRIVE
    assert m["typedHours"]["rows"][GYP_ROW] == "4 x 5 = $660" and m["typedHours"]["marks"]["typed"] is True
    assert m["at180"][GYP_ROW] == "4 x 18 = $2376"


def test_a_copy_of_the_gyp_sheet_follows_its_own_mobilizations(ran):
    """A copy of the Gyp sheet (an option, priced apart) comes with the sheet's 3 mobilizations and so its drive (4 x 19.5); 2 typed on the copy put the copy's drive at 4 x 13 and leave the base's
    alone; a jsonb reload agrees, and a later answer (300 miles) reaches each by its own count of trips: 4 x 30 and 4 x 20."""
    m = ran["mobs"]
    cp = m["copy"] + ":option"
    assert m["copied"][cp] == "4 x 19.5 = $2574" and m["copyTyped2"] is True and m["copyState"]["mobs"] == "2"
    assert m["copyState"]["rows"][cp] == "4 x 13 = $1716" and m["copyState"]["rows"][GYP_ROW] == "4 x 19.5 = $2574"
    assert m["copyReloaded"]["quiet"] == QUIET and m["copyReloaded"]["rows"] == m["copyState"]["rows"]
    assert m["copyAt300"][GYP_ROW] == "4 x 30 = $3960" and m["copyAt300"][cp] == "4 x 20 = $2640"


def test_add_travel_labor_on_a_gyp_sheet_fills_a_round_trip_for_each_mobilization(ran):
    r = ran["mobs"]["readded"]
    assert r["x"] is True and r["add"] is True
    assert r["rows"][GYP_ROW] == "4 x 19.5 = $2574" and r["marks"] == dict(ADDED, seed=19.5)


def test_the_gyp_words_say_the_trips_are_the_mobilizations(ran):
    """The card, the travel block, the note on where the hours came from, the Review's trip sentence and the Mobilizations box's own hint say a round trip for each mobilization."""
    m = ran["mobs"]
    trip = ("19.5 hrs: 3 round trips of 380 miles at 60 mph from the Olathe office, 6.5 hrs each, one for each mobilization, for each of the 4 guys on the labor lines above")
    assert m["labor"]["src"] == trip + ". A round trip for each mobilization typed on the Gyp card."
    assert m["blank"]["src"] == ("6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above. "
                                 "A round trip for each mobilization typed on the Gyp card.")
    assert m["trip"] == trip
    assert "a round trip for each mobilization" in m["labor"]["cap"]
    assert "one round trip for each mobilization on the Gyp card" in m["labor"]["cardNote"]
    assert "(3 round trips of 380 miles at 60 mph from the Olathe office, 6.5 hrs each, one for each mobilization, for each guy)" in m["labor"]["how"]
    assert m["hint"] == "How many times the crew comes out. It sets the hours the sheet suggests on the Labor step, and on a far job the drive: one round trip each."


# ── P3 (F3): the x on both drives of a Combo is the job's answer ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_x_on_both_drives_of_a_combo_is_the_jobs_answer(ran):
    """Far Combo, the x on the Epoxy drive (that sheet's answer), then on the Polish drive: no base holds a line, so the job has no drive (J), the sheets' answers folded into it; in either order.
    A reload opens quietly at the same answer and prices."""
    x = ran["bothX"]
    assert x["x1"] is True and x["x2"] is True
    assert x["afterOne"] == {"job": False, "sheets": {"Epoxy": True}}
    assert x["afterBoth"]["rows"] == {"Polish:base": None, "Epoxy:base": None} and x["afterBoth"]["answers"] == JOB_SAID
    assert x["otherOrder"] == JOB_SAID
    assert x["reloaded"]["quiet"] == QUIET
    _same(x["afterBoth"], x["reloaded"]["state"])


def test_a_job_type_switch_keeps_the_drive_removed(ran):
    """D3, as for a single-base job's x: the job type Epoxy, then Gyp (a NEW section, which the library would seed a drive), then Polish, then Combo again: no base holds a line and the job still
    says it has no drive."""
    x = ran["bothX"]
    for k, rows in (("toEpoxy", {"Polish:off": None, "Epoxy:base": None}), ("toGyp", {"Polish:off": None, "Epoxy:off": None, GYP_ROW: None}),
                    ("toPolish", {"Polish:base": None, "Epoxy:off": None, GYP + ":off": None}), ("toCombo", {"Polish:base": None, "Epoxy:base": None, GYP + ":off": None})):
        assert x[k]["rows"] == rows and x[k]["answers"] == JOB_SAID, k


def test_add_travel_labor_on_a_base_takes_the_jobs_answer_back(ran):
    """Add Travel Labor on the Epoxy base: its own crew's drive, filled (5 x 6.5); the job has a drive again and the Polish sheet says it has none as its own answer. A reload agrees."""
    x = ran["bothX"]
    a = x["afterAdd"]
    assert x["added"] is True and a["state"]["rows"]["Epoxy:base"] == EPOXY_DRIVE and a["state"]["rows"]["Polish:base"] is None
    assert a["state"]["answers"] == {"job": False, "sheets": {"Polish": True}} and a["marks"] == ADDED
    _same(a["state"], x["addReloaded"])


# ── P4 (F7): a far Combo saved under the one-drive law opens with every base's drive ────────────────────────────────────────────────────────────────────────────────────
def test_a_combo_saved_under_the_one_drive_law_opens_with_the_epoxy_crews_own_drive(ran):
    """The job's one drive on the Polish root (the bigger crew's 5), no line and no answer on the Epoxy base. Opened: the Epoxy base's drive is filled by the rule on its own crew (5 x 6.5), the
    carrier's drive reads its own crew (4 x 6.5), and the bid is $92,153, the price of the same Combo bid since round 7, where it opened at $89,997 with the Epoxy crew's drive missing. The open
    arms ONE save (the pass-2 audit's A1: below) and writes nothing until it runs. The Epoxy sheet's Labor step draws its drive and no Add Travel Labor."""
    o = ran["legacy"]["opened"]
    assert o["quiet"] == ARMED
    assert o["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE} and o["answers"] == NO_ANSWER and o["marks"] == FILLED
    assert o["bid"] == {"root": COMBO_PRICE["root"], "epoxy": COMBO_PRICE["sections"]["Epoxy"]} and o["bid"] != ONE_DRIVE_OPENED
    assert o["epoxy"]["add"] is False and o["epoxy"]["src"].startswith("6.5 hrs: one 380 mile round trip")


def test_the_open_saves_the_drive_it_gives_so_the_review_and_the_proposal_read_the_price_on_the_bar(ran):
    """THE PASS-2 AUDIT'S A1. The draft was saved at the one-drive price, $90,422 (Polish $53,378, Epoxy $37,044), and the open shows $92,153. Nothing typed, the save the open armed runs, and the
    draft holds the price the bar shows: the lump sum $92,153 and each sheet's total ($52,956 and $39,197), which is what the Review's figures and the Proposal step read (priced_tabs,
    proposal_lump_sum). Before, the open wrote nothing, the bar said $92,153 and Continue to proposal printed $90,422 until some edit saved."""
    s = ran["legacy"]["openSave"]
    assert s["bar"] == COMBO_PRICE["lump"] and s["saves"] == 1
    assert s["lump"] == COMBO_PRICE["lump"] and s["lump"] != ONE_DRIVE_SAVED["lump"]
    assert s["pricedTabs"] == [["Polish", "base", COMBO_PRICE["root"]], ["Epoxy", "base", COMBO_PRICE["sections"]["Epoxy"]]] and s["pricedTabs"] != ONE_DRIVE_SAVED["tabs"]


def test_the_page_left_at_once_writes_the_price_it_showed(ran):
    """The same draft, opened and left inside the save's debounce window (Continue to proposal pressed at once): the page's exit writes the save the open armed, so the Proposal reads $92,153."""
    q = ran["legacy"]["leftAtOnce"]
    assert q["bar"] == COMBO_PRICE["lump"] and q["flushed"] == 1 and q["saves"] == 1 and q["lump"] == COMBO_PRICE["lump"]


@pytest.mark.parametrize("say, polish, epoxy, epoxy_says", [
    ("off", "4 x 6.5 = $0", "5 x 6.5 = $0", {"guys": 5, "hours": 6.5, "on": False, "guysTyped": False, "hoursTyped": False, "follow": "crew"}),
    ("clearedHours", "4 x  = $0", "5 x  = $0", {"guys": 5, "hours": "", "on": True, "guysTyped": False, "hoursTyped": True, "follow": "crew"}),
    ("clearedGuys", " x 6.5 = $0", " x 6.5 = $0", {"guys": "", "hours": 6.5, "on": True, "guysTyped": True, "hoursTyped": False, "follow": None}),
])
def test_a_drive_the_estimator_switched_off_or_cleared_on_the_jobs_one_drive_stays_off_for_every_crew(ran, say, polish, epoxy, epoxy_says):
    """THE PASS-2 AUDIT'S A1. Under the one-drive law the job's one drive was EVERY crew's, so switching it off, or clearing its Hours or Guys box, said the job's crews are charged no drive: the
    draft was saved at $88,312, the price of the same bid with no drive at all (the x). The open gives the Epoxy base its line and that line says the same, switched off or with the same box
    cleared, as the estimator's: the bar is $88,312 and the open saves it (it showed $90,468, the Epoxy crew's 5 x 6.5 = $1,072.50 back on a bid whose drive was taken away). A jsonb reload of what
    it saved agrees and opens quietly, and 300 miles typed after it charges neither crew a drive (a box the estimator never touched follows the miles: the Guys-cleared lines' hours go to 10)."""
    s = ran["legacy"]["said"][say]
    none = ran["legacy"]["said"]["removed"]
    o = s["opened"]
    assert o["armed"] == 1 and o["saves"] == 0 and o["answers"] == NO_ANSWER
    assert o["rows"] == {"Polish:base": polish, "Epoxy:base": epoxy} and o["epoxy"] == epoxy_says
    assert o["bar"] == none["opened"]["bar"] == NO_DRIVE_LUMP
    assert s["kept"] == {"saves": 1, "lump": NO_DRIVE_LUMP}
    assert s["reloaded"]["quiet"] == QUIET and s["reloaded"]["rows"] == o["rows"] and s["reloaded"]["epoxy"] == epoxy_says and s["reloaded"]["bar"] == NO_DRIVE_LUMP
    assert s["at300"]["bar"] == NO_DRIVE_LUMP and s["at300"]["rows"] == ({k: v.replace("6.5", "10") for k, v in o["rows"].items()} if say == "clearedGuys" else o["rows"])


def test_figures_typed_on_the_jobs_one_drive_stay_the_carrier_crews_and_the_epoxy_crew_drives_its_own(ran):
    """7 guys x 3.25 hours typed on the job's one drive (saved at $89,790): the Polish sheet keeps the figures the estimator typed on it, and the Epoxy crew's own drive is the rule's, 5 x 6.5, as every
    route that gives a base its drive beside a typed one gives it (the pass-2 audit's A2: test_polish_travel_round7_part3.py). The open saves the $91,943 the bar shows; a reload agrees, and 300 miles
    moves the Epoxy crew's drive and leaves the typed one."""
    s = ran["legacy"]["said"]["typed"]
    o = s["opened"]
    assert o["armed"] == 1 and o["rows"] == {"Polish:base": "7 x 3.25 = $750.75", "Epoxy:base": EPOXY_DRIVE}
    assert o["epoxy"] == {"guys": 5, "hours": 6.5, "on": True, "guysTyped": False, "hoursTyped": False, "follow": "crew"}
    assert o["bar"] == 91943 and s["kept"] == {"saves": 1, "lump": 91943}
    assert s["reloaded"]["quiet"] == QUIET and s["reloaded"]["rows"] == o["rows"] and s["reloaded"]["bar"] == 91943
    assert s["at300"]["rows"] == {"Polish:base": "7 x 3.25 = $750.75", "Epoxy:base": "5 x 10 = $1650"}


def test_a_combo_whose_one_drive_was_removed_opens_as_saved(ran):
    """The x on the job's one drive (the job's answer, J, and no line on any sheet): no base holds a line, so the open gives none, arms nothing, and shows the $88,312 it was saved at."""
    s = ran["legacy"]["said"]["removed"]
    assert s["opened"]["armed"] == 0 and s["opened"]["rows"] == {"Polish:base": None, "Epoxy:base": None} and s["opened"]["answers"] == JOB_SAID
    assert s["opened"]["bar"] == NO_DRIVE_LUMP and s["kept"] == {"saves": 0, "lump": NO_DRIVE_LUMP}


def test_the_open_the_session_and_a_reload_price_two_drives(ran):
    leg = ran["legacy"]
    for k in ("session", "savedReloaded"):
        assert leg[k]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE} and leg[k]["price"] == COMBO_PRICE, k
    assert leg["sessionReloaded"]["quiet"] == QUIET
    _same(leg["session"], leg["sessionReloaded"]["state"])


def test_made_one_base_it_keeps_each_crews_own_drive(ran):
    """Made Epoxy: the Epoxy base keeps the drive it opened with (5 x 6.5, $49,281, an Epoxy job of that crew bid from scratch), and the Polish root, off, gives its fill back. Made Polish: the root
    keeps its own and the Epoxy sheet, off, gives its fill back."""
    leg = ran["legacy"]
    assert leg["toEpoxy"]["rows"] == {"Polish:off": " x  = $0", "Epoxy:base": EPOXY_DRIVE} and leg["toEpoxy"]["price"]["lump"] == 49281
    assert leg["toPolish"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:off": " x  = $0"}


def test_a_combo_whose_second_base_said_it_has_no_drive_is_left_as_it_is(ran):
    s = ran["legacy"]["sheetSaid"]
    assert s["quiet"] == QUIET and s["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": None} and s["answers"] == {"job": False, "sheets": {"Epoxy": True}}


def test_on_a_local_job_the_line_is_given_and_the_rule_fills_nothing(ran):
    """The same Combo saved at 40 miles: the Epoxy base is given its line, empty, as a far answer would find it (the rule fills nothing under 70 miles); nothing is priced, and the open arms its one
    save, which writes the line it gave (the pass-2 audit's A1)."""
    loc = ran["legacy"]["local"]
    assert loc["rows"]["Epoxy:base"] == " x  = $0" and loc["quiet"] == ARMED


def test_a_model_handed_the_old_shape_without_the_open_still_carries_the_one_drive(ran):
    """THE GUARD (model-level, B.followDistance alone, the open's fill not applied): the old shape made Epoxy carries the job's one drive to the one base left, and puts it on that base's own crew (5,
    where the drive was the Polish crew's 6)."""
    g = ran["legacy"]["guard"]
    assert g["rows"] == {"Polish:off": None, "Epoxy:base": EPOXY_DRIVE} and g["answers"] == NO_ANSWER


# ── P5 (F4): Add Travel Labor goes on the sheet it was pressed on ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_add_travel_labor_puts_the_line_on_the_sheet_it_was_pressed_on(ran):
    """The x on the Epoxy drive of a far Combo, Add Travel Labor pressed on the Epoxy sheet, and the Polish sheet opened while the library answers: the line is the Epoxy sheet's, filled on its crew,
    marked as the estimator's, and the Epoxy sheet's answer is gone; the Polish sheet stays on show. Until this part it went to the sheet on show when the library answered (the Polish sheet, which
    holds one: so nowhere) and the Epoxy sheet went on saying it had no line. A reload agrees."""
    a = ran["addTarget"]["a"]
    assert a["pressed"] is True and a["rootOnShow"] is True
    assert a["state"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE} and a["state"]["answers"] == NO_ANSWER and a["marks"] == ADDED
    assert a["state"]["price"] == COMBO_PRICE
    assert ran["addTarget"]["aReloaded"]["quiet"] == QUIET
    _same(a["state"], ran["addTarget"]["aReloaded"]["state"])


def test_add_travel_labor_under_the_jobs_answer_and_from_the_carrier_goes_where_it_was_pressed(ran):
    """With both drives taken away (J) the Polish sheet holds no line either, so the old page put the line THERE: pressed on Epoxy, the line is Epoxy's and the Polish sheet says it has none, as its own
    answer. And the other way round, pressed on the Polish carrier with the Epoxy sheet opened while the library answers: the Polish sheet's."""
    b, c = ran["addTarget"]["b"], ran["addTarget"]["c"]
    assert b["pressed"] is True and b["state"]["rows"] == {"Polish:base": None, "Epoxy:base": EPOXY_DRIVE}
    assert b["state"]["answers"] == {"job": False, "sheets": {"Polish": True}} and b["marks"] == ADDED
    assert c["pressed"] is True and c["state"]["rows"] == {"Polish:base": POLISH_DRIVE, "Epoxy:base": EPOXY_DRIVE} and c["state"]["answers"] == NO_ANSWER and c["marks"] == ADDED


# ── P6 (F5): the carrier's words after the x on its own drive of a Combo ───────────────────────────────────────────────────────────────────────────────────────────────────
SHEET_WORDS = "This sheet has no Travel Labor line, so its own crew's drive is not charged. The Epoxy sheet keeps its own Travel Labor line."
BID_WORDS = "This bid has no Travel Labor line, so the drive adds nothing to the price."


def test_the_carriers_words_say_this_sheet_has_no_line_and_the_epoxy_sheet_keeps_its_own(ran):
    """The x on the Polish drive of a far Combo: the Epoxy crew's drive is still priced (5 x 6.5), so the Polish sheet's Labor step says THIS SHEET has no line and the Epoxy sheet keeps its own, and
    its working says the same; it said "This bid has no Travel Labor line, so the drive adds nothing to the price", "there is no Travel Labor line to price the drive" and "no line on this bid".
    A reload draws the same words."""
    w = ran["words"]
    c = w["carrier"]
    assert w["x"] is True and w["epoxyDrive"] == EPOXY_DRIVE
    assert c["add"] is True and c["none"] == "sheet" and c["noneWords"] == SHEET_WORDS
    how = c["how"].split("\n")
    assert how[0].endswith("so this is NOT a local job: Lodging and Per Diem come on. This sheet has no Travel Labor line, so its own crew's drive is not charged: add it below. "
                           "The Epoxy sheet keeps its own Travel Labor line.")
    assert how[1] == "Travel Labor on this sheet: no line, $0"
    assert how[2] == "Travel Labor on the Epoxy sheet: 5 guys x 6.5 drive hours x $33.00 = $1,072.50 (that sheet's own guys)."
    for words in (c["noneWords"], c["how"]):
        assert "This bid has no" not in words and "no line on this bid" not in words and "the drive adds nothing" not in words and "no Travel Labor line to price the drive" not in words
    assert w["reloaded"] == c


def test_with_both_drives_gone_and_on_a_single_base_job_the_words_say_the_bid_has_none(ran):
    w = ran["words"]
    for k in ("both", "single"):
        assert w[k]["noneWords"] == BID_WORDS and w[k]["none"] == "", k
        assert "there is no Travel Labor line to price the drive: add it below." in w[k]["how"] and "Travel Labor: no line on this bid, $0" in w[k]["how"], k


# ── red without the code: break a COPY of the page or the model one line at a time; a fact must change, never a crash ─────────────────────────────────────────────────────
# name -> (file, old, new, the facts that notice)
BREAKS = {
    # --- P2 ---
    "a Gyp drive is one round trip whatever the mobilizations": (
        "js/bid-model.js", '    var hours = trip === "" ? "" : trip * (trips === undefined ? 1 : trips);', "    var hours = trip;",
        lambda g: g["mobs"]["three"]["rows"].get(GYP_ROW) != "4 x 19.5 = $2574"),
    "the mobilizations are not read off the Gyp card": (
        "js/bid-model.js", "    var mobs = num(isObject(entry.section.gyp) ? entry.section.gyp.mobs : 0);", "    var mobs = 0;",
        lambda g: g["mobs"]["three"]["rows"].get(GYP_ROW) != "4 x 19.5 = $2574"),
    "a blank Mobilizations box drives nobody": (
        "js/bid-model.js", "    return mobs > 0 ? mobs : 1;", "    return mobs;",
        lambda g: g["mobs"]["blank"]["rows"].get(GYP_ROW) != POLISH_DRIVE),
    "the box moves nothing (the page)": (
        "js/polish-estimate.js", '    if (key === "mobs") B.followDriveTrips(ROOT, e.tab);', "    void key;",
        lambda g: g["mobs"]["three"]["rows"].get(GYP_ROW) != "4 x 19.5 = $2574"),
    "the box writes over hours the estimator typed": (
        "js/bid-model.js", "    var fills = !row.hours_typed && (isBlank(row.days) || wrote);", "    var fills = true;",
        lambda g: g["mobs"]["typedHours"]["rows"].get(GYP_ROW) != "4 x 5 = $660"),
    "a copy's own box moves nothing": (
        "js/bid-model.js", '    rows.forEach(function (r) { if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true, driveTripsOf(e)); });', "    void rows;",
        lambda g: g["mobs"]["copyState"]["rows"].get(g["mobs"]["copy"] + ":option") != "4 x 13 = $1716"),
    "an answer gives a Gyp option one trip": (
        "js/bid-model.js", '        if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true, driveTripsOf(e));',
        '        if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true, 1);',
        lambda g: g["mobs"]["copyAt300"].get(g["mobs"]["copy"] + ":option") != "4 x 20 = $2640"),
    "Add Travel Labor on a Gyp sheet fills one trip": (
        "js/bid-model.js", "        trips = driveTripsOf(hit);       // a Gyp section's drive is a round trip for each mobilization (round 7, part 4, P2)", "        void hit;",
        lambda g: g["mobs"]["readded"]["rows"].get(GYP_ROW) != "4 x 19.5 = $2574"),
    "the words say one round trip": (
        "js/bid-model.js", "    if (src.trips > 1) {", "    if (false) {",
        lambda g: "3 round trips" not in (g["mobs"]["labor"]["src"] or "") or "3 round trips" not in (g["mobs"]["trip"] or "")),
    "the note says to type more trips on a Gyp drive": (
        "js/bid-model.js", '    var trips = src.gyp ? "A round trip for each mobilization typed on the Gyp card." : "Type more trips for a long job.";',
        '    var trips = "Type more trips for a long job.";',
        lambda g: not (g["mobs"]["labor"]["src"] or "").endswith("A round trip for each mobilization typed on the Gyp card.")),
    "the Gyp card says one round trip": (
        "js/polish-estimate.js", "                : 'There the hours fill in from the miles, ' + (gypOpen() ? 'one round trip for each mobilization on the Gyp card' : 'one round trip') +",
        "                : 'There the hours fill in from the miles, ' + ('one round trip') +",
        lambda g: "one round trip for each mobilization on the Gyp card" not in (g["mobs"]["labor"]["cardNote"] or "")),
    # --- P3 ---
    "the x on both drives of a Combo leaves each sheet its own answer": (
        "js/bid-model.js", "    if (drives.length > 1 && !drivesHoldTravel(model)) {", "    if (false) {",
        lambda g: g["bothX"]["afterBoth"]["answers"] != JOB_SAID or g["bothX"]["toGyp"]["rows"].get(GYP_ROW) is not None),
    "the sheets' answers stay beside the job's": (
        "js/bid-model.js", "      drives.forEach(function (e) { if (isObject(e.section)) delete e.section.sheet_no_travel_labor; });", "      void drives;",
        lambda g: g["bothX"]["afterBoth"]["answers"] != JOB_SAID),
    # --- P4 ---
    "a Combo saved under the one-drive law opens with one drive (the page)": (
        "js/polish-estimate.js", "    ROOT = B.giveEveryBaseItsDrive(B.withSectionOrder(B.migrateModel(state.polish_estimate), state.priced_tabs));",
        "    ROOT = B.withSectionOrder(B.migrateModel(state.polish_estimate), state.priced_tabs);",
        lambda g: g["legacy"]["opened"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    "the line the open gives is not filled": (
        "js/bid-model.js", "      if (miles !== null) followDistanceOnRow(out, row, held.labor, miles, false, driveTripsOf(entryOrNull(out, e.tab)));", "      void miles;",
        lambda g: g["legacy"]["opened"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    "a sheet that said it has no drive is given a line on open": (
        "js/bid-model.js",
        "    var bare = drives.filter(function (e) { return isObject(e.section) && Array.isArray(e.section.labor) && !travelRowsIn(e.section).length && !sheetSaidNoDrive(e.section); });",
        "    var bare = drives.filter(function (e) { return isObject(e.section) && Array.isArray(e.section.labor) && !travelRowsIn(e.section).length; });",
        lambda g: g["legacy"]["sheetSaid"]["rows"].get("Epoxy:base") is not None),
    "a job of several bases none of which holds a line is given lines on open": (
        "js/bid-model.js", "    if (drives.length < 2 || !drives.some(function (e) { return travelRowsIn(e.section).length > 0; })) return model;",
        "    if (drives.length < 2) return model;",
        lambda g: g["bothX"]["reloaded"]["state"]["rows"] != {"Polish:base": None, "Epoxy:base": None}),
    # (moved here from test_polish_travel_round7.py: since the open fills the second base, no page path reaches the one-drive carry, and the guard is held on the model)
    "a Combo saved under the one-drive law made Epoxy has no drive (the model)": (
        "js/bid-model.js", "    return !!e && !travelRowsIn(e.section).length;", "    return false;",
        lambda g: g["legacy"]["guard"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    "the settling leaves a carried drive on the old base's crew": (
        "js/bid-model.js", "    syncAutoGuys(model);", "    void model;",
        lambda g: g["legacy"]["guard"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    # --- the pass-2 audit's A1: the open saves what it gives, and the job's one drive switched off or cleared is said on the line it gives ---
    "the open asks no save for the drive it gave (the page)": (
        "js/polish-estimate.js", "    if (drivesGiven) saveSoon();", "    void drivesGiven;",
        lambda g: g["legacy"]["openSave"]["lump"] != COMBO_PRICE["lump"] or g["legacy"]["leftAtOnce"]["lump"] != COMBO_PRICE["lump"]),
    "the open does not say that it gave a drive (the page)": (
        "js/polish-estimate.js", "    drivesGiven = ROOT !== ordered;", "    drivesGiven = false;",
        lambda g: g["legacy"]["openSave"]["lump"] != COMBO_PRICE["lump"] or g["legacy"]["opened"]["quiet"] != ARMED),
    "the job's one drive is not read for what it said of every crew": (
        "js/bid-model.js", "    var said = oneDriveSaid(drives);", "    var said = null;",
        lambda g: any(g["legacy"]["said"][k]["opened"]["bar"] != NO_DRIVE_LUMP for k in ("off", "clearedHours", "clearedGuys"))),
    "the line the open gives says nothing the job's one drive said": (
        "js/bid-model.js", "      if (said) sayNoDrive(row, said);", "      void said;",
        lambda g: any(g["legacy"]["said"][k]["opened"]["bar"] != NO_DRIVE_LUMP for k in ("off", "clearedHours", "clearedGuys"))),
    "a drive switched off comes back switched on": (
        "js/bid-model.js", "    if (said.off) row.enabled = false;", "    void said;",
        lambda g: g["legacy"]["said"]["off"]["opened"]["bar"] != NO_DRIVE_LUMP),
    "the switch is not read as the job's answer": (
        "js/bid-model.js", "      off: !rowOn(row),", "      off: false,",
        lambda g: g["legacy"]["said"]["off"]["opened"]["epoxy"].get("on") is not False),
    "a cleared Hours box is not said on the line the open gives": (
        "js/bid-model.js", "    if (said.hours !== undefined) { row.days = said.hours; row.hours_typed = true; }", "    void said;",
        lambda g: g["legacy"]["said"]["clearedHours"]["opened"]["bar"] != NO_DRIVE_LUMP),
    "a cleared Guys box is not said on the line the open gives": (
        "js/bid-model.js", "    if (said.guys !== undefined) { row.guys = said.guys; row.guys_auto = false; row.guys_typed = true; delete row.guys_follow; }", "    void said;",
        lambda g: g["legacy"]["said"]["clearedGuys"]["opened"]["bar"] != NO_DRIVE_LUMP),
    "a trip typed on the job's one drive is said on the Epoxy crew's line too": (
        "js/bid-model.js", "      hours: hoursSaid && !(num(row.days) > 0) ? row.days : undefined", "      hours: hoursSaid ? row.days : undefined",
        lambda g: g["legacy"]["said"]["typed"]["opened"]["rows"].get("Epoxy:base") != EPOXY_DRIVE),
    # --- P5 ---
    "Add Travel Labor goes on the sheet on show when the library answers": (
        "js/polish-estimate.js", "      if (!B.addTravelLabor(ROOT, B.freshTravelRow(rows, LABOR_RATE), pressedOn)) return;",
        "      if (!B.addTravelLabor(ROOT, B.freshTravelRow(rows, LABOR_RATE), activeTab)) return;",
        lambda g: g["addTarget"]["a"]["state"]["rows"].get("Epoxy:base") != EPOXY_DRIVE or g["addTarget"]["b"]["state"]["rows"].get("Polish:base") is not None),
    # --- P6 ---
    "the carrier's Add says the bid has no line": (
        "js/polish-estimate.js", "    var others = option ? [] : B.otherDrives(ROOT, activeTab);", "    var others = [];",
        lambda g: g["words"]["carrier"]["noneWords"] != SHEET_WORDS),
    "the carrier's working says the bid has no line": (
        "js/bid-model.js", "    var others = tr ? [] : otherDrives(W, carrierTabOf(W));", "    var others = [];",
        lambda g: "Travel Labor on this sheet: no line, $0" not in (g["words"]["carrier"]["how"] or "")),
    "with both drives gone the words still say this sheet": (
        "js/bid-model.js", "    if (!isObject(model) || model.no_travel_labor === true) return [];", "    if (!isObject(model)) return [];",
        lambda g: g["words"]["both"]["noneWords"] != BID_WORDS),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line this part depends on, broken in a scratch copy of the page or the model; a FACT must change. A break that stops the harness, or makes a section throw, is not counted as
    noticed: it has no facts to compare."""
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
