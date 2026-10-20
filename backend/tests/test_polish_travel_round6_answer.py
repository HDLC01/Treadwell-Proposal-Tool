"""ROUND 6, PART 2, THE "NO TRAVEL LABOR" ANSWER (2026-10-20), held on the real estimate page.

The round-5 verification (two skeptics, scripts s1.js, s2.js, f2.js and rootcause.js) found that a session and a reload of the SAME draft priced $783 apart. One line was the root of it:
migrateModel appended a blank Travel Labor row to the ROOT whenever the root had none, even when the root was off (an Epoxy job's Polish) or an option. A job-type switch (or a base pick) moves
the carrier's row off the root, a reload then appended a blank row to the off root, and when the carrier came back to the root the distance filled that row and priced it, but only if a reload
had happened in between. Everything here is run on the page, and every reload is a JSONB reload (the drafts table hands a blob's keys back sorted by length and then bytes).

  X1  THE BLANK ROW. migrateModel appends the row only to a root that carries the job's travel (and the job has not said it has no drive). F1 (far Combo, switched to Epoxy, the x on the Epoxy
      sheet's Travel Labor, back to Combo, 300 miles typed) and F2 (far Polish, the x, an Epoxy sheet added and made the base, Add Travel Labor on it, 300 miles, the Polish option) and the
      auditor's second route (S1) price the same in the session and after a reload.
  X2  THE ANSWER BELONGS TO THE SHEET. The x on the CARRIER's Travel Labor line says the job has no drive (the root's `no_travel_labor`, which the library's own decline sets too); the x on an
      OPTION's says only that the option has none, and the x on a base that does not carry the travel (a leftover row) says nothing. Add Travel Labor is drawn on any sheet that can hold a drive
      (the carrier, or an option) and has none, and takes back only that sheet's answer. A job-type switch after the carrier's x HONOURS it: the job has no drive, so the new carrier is not
      seeded a row and none is carried to it, in the session and after a reload alike. A saved bid's flag, which the round-5 x set for ANY row, is read as the job's answer it is now and is dropped
      when the carrier holds a row (the flag prices nothing: no saved bid moves), and a legacy Travel row is upgraded whether or not the flag is on the bid.
  X3  THE x ON A LABOR LINE, FROM THE KEYBOARD. The panel is drawn again, the button is destroyed with it and focus fell to <body>: it goes to the next row's x, else the previous row's, else the
      Add Travel Labor button (when the Travel line was the one that went), else the Add labor line.

Each test drives js/polish-estimate.js whole (through tests/js/travel-round6-answer-harness.js, on the real js/bid-model.js) and reads the page back; the last block breaks a COPY of the page or the
model one line at a time and requires a fact to change (never a crash).
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round6-answer-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["rootCause", "f1", "oracle", "f2", "s1", "answer", "switchAfterX", "migrate", "stranded", "keyboard"]


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-800:]
    return last_json_line(proc.stdout)


class Ran(dict):
    """The harness's report. A section that threw says so when a test reads it, so one failing section fails the tests that read it and no other."""

    def __getitem__(self, key):
        got = dict.__getitem__(self, key)
        assert not (isinstance(got, dict) and "error" in got), "the %s section of the harness failed: %s" % (key, str(got["error"])[:700])
        return got


@pytest.fixture(scope="module")
def ran():
    require_node()
    return Ran(run())


DRIVE = "4 x 6.5 = $858"          # the crew of 4, one 380 mile round trip (6.5 hours) at $33 an hour


# ── X1. the blank row ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_root_that_does_not_carry_the_jobs_travel_is_never_given_the_blank_row(ran):
    """The draft saved right after a far Combo is switched to Epoxy holds no Travel Labor row on the off Polish root (the row went with the carrier). A reload put a blank one back
    (migrateModel appended it: the root had none, and the job had not said no). Now the root is off and carries nothing, so it is left as saved, and a plain reopen holds exactly what was saved.

    The table: an off root and a root that is an option are left alone, whatever they hold; a root that carries the travel still gets the row a stale draft (saved before 2026-09-12) never had, and
    so does a root whose sections cannot be read (it is its own carrier, as it always was); a root that carries it and said it has no drive keeps none.

    Mutation: append the blank row to any root; to a root that is off; to a root that is an option; leave the stale draft without it."""
    r = ran["rootCause"]
    assert r["savedKinds"] == ["Polish:off", "Epoxy:base"] and r["savedRootRows"] == 0 and r["flag"] is False
    assert r["migratedRootRows"] == 0, "a reload gave the off root a blank Travel Labor row"
    assert r["reopenRows"] == {"Polish:off": None, "Epoxy:base": "0 x 6.5 = $0"}, r["reopenRows"]
    assert r["reopenQuiet"] == {"armed": 0, "saves": 0}
    assert r["table"] == {
        "an off root (an Epoxy job's Polish)": 0,
        "a root that is an option beside an Epoxy base": 0,
        "a stale draft with no sections (saved before 2026-09-12)": 1,
        "a root that is the base beside an Epoxy option": 1,
        "a root whose sections cannot be read": 1,
        "a root that carries the travel and said it has no drive": 0,
        "an off root that carries nothing and said it has no drive": 0,
    }


def test_f1_a_session_and_a_reload_price_a_combo_switched_to_epoxy_and_back_after_the_x_the_same(ran):
    """F1 (audit): a far Combo (Polish 4 x 12, 190 miles, the drive 4 x 6.5 = $858), switched to Epoxy on the intake step, the x on the Epoxy sheet's Travel Labor, switched back to Combo, then 300
    miles typed. With no refresh after the switch the Combo came back with no Travel Labor line and 300 miles changed nothing ($48,133); with one refresh it came back with a blank line that the
    distance filled to 4 x 6.5 = $858 ($48,009) and 300 miles to 4 x 10 = $1,320 ($48,916). Now both are the bid that had the x pressed on a Combo and nothing else: no drive, and the answer stays.

    Mutation: append the blank row to an off root."""
    a, b, o = ran["f1"]["A"], ran["f1"]["B"], ran["oracle"]["combo"]
    assert a["pressed"] is True and b["pressed"] is True and a["flagAfterX"] is True and b["flagAfterX"] is True
    assert a == b, "a session and a reload of the same draft differ:\nA %r\nB %r" % (a, b)
    assert a["rows"] == {"Polish:base": None, "Epoxy:base": None} and a["flag"] is True and a["carrier"] == "Polish"
    assert a["open"] == o["open"] and a["at300"] == o["at300"], "the bid is not the one that had the x pressed on a Combo and nothing else"


def test_f2_the_demoted_polish_option_prices_the_same_in_a_session_and_after_a_reload(ran):
    """F2 (audit): far Polish, the x on its Travel Labor, an Epoxy sheet added and made the base, Add Travel Labor on the Epoxy carrier, then 300 miles typed: the Polish OPTION was $40,988 in
    the session (no line) and $41,771 after a refresh of the same draft (a blank line the distance filled to 4 x 10 = $1,320), +$783. The option has no line in both.

    Mutation: append the blank row to a root that is an option."""
    f = ran["f2"]
    assert f["pressedX"] is True and f["added"] is True and f["flagBeforeAdd"] is True and f["flagAfterAdd"] is False
    assert f["session"] == f["reloaded"], "the session and a reload of the same draft price the option differently:\n%r\n%r" % (f["session"], f["reloaded"])
    assert f["session"]["rows"]["Polish:option"] is None and f["reopened"]["Polish:option"] is None
    assert f["session"]["price"]["root"] == f["reloaded"]["price"]["root"] == 40988


def test_the_auditors_second_route_prices_the_same_in_a_session_and_after_a_reload(ran):
    """S1 (audit): far Polish, an Epoxy sheet added as an alternate, the job type Epoxy, the x on the Epoxy carrier's Travel Labor, the job type back to Polish, 300 miles typed: with no refresh in
    the middle the Polish bid had no line ($40,988); with one it had the blank line the distance filled, 4 x 10 = $1,320 ($41,771).

    Mutation: append the blank row to an off root."""
    a, b = ran["s1"]["A"], ran["s1"]["B"]
    assert a["pressed"] is True and a["flagAfterX"] is True
    assert a["afterSwitch"]["carrier"] == "Epoxy" and a["afterSwitch"]["rows"]["Polish:off"] is None
    assert a == b, "a session and a reload of the same draft differ:\nA %r\nB %r" % (a, b)
    assert a["rows"]["Polish:base"] is None and a["at300"]["price"]["lump"] == a["open"]["lump"] == 40988


# ── X2. the answer belongs to the sheet ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_carriers_x_says_the_job_has_no_drive_and_add_travel_labor_takes_it_back(ran):
    """The x on the carrier's Travel Labor: the job's answer is recorded (the root's `no_travel_labor`), the line stays away through a reload (a plain reopen arms no save), the card draws Add Travel
    Labor where the line was, and pressing it puts the line back, filled by the distance on file (4 x 6.5 = $858) and takes the answer back, to the price the bid had before the x.

    Mutation: leave the carrier's x unrecorded; leave the answer in place when the line is added back."""
    c = ran["answer"]["carrier"]
    assert c["before"]["rows"] == {"Polish:base": DRIVE} and c["pressed"] is True
    assert c["afterX"] == {"flag": True, "rows": {"Polish:base": None}, "addShown": True, "saved": True}
    assert c["reloaded"] == {"flag": True, "rows": {"Polish:base": None}, "addShown": True, "quiet": {"armed": 0, "saves": 0}}
    assert c["added"] is True
    assert c["afterAdd"] == {"flag": False, "rows": {"Polish:base": DRIVE}, "saved": False, "price": c["before"]["price"]}


def test_an_options_x_says_only_that_the_option_has_none_and_add_brings_its_own_line_back(ran):
    """A far Polish bid copied as an option (Copy1, with a Travel Labor line of its own): the x on the OPTION's line records nothing about the job (the root's flag stays off, the carrier keeps its
    line), a reload does not bring the option's line back, the card draws Add Travel Labor on the option (and not on the carrier, which has its line), and pressing it adds a line to the option
    alone, filled by the distance on its own crew (4 x 6.5 = $858), with the job's answer untouched. 300 miles then reaches it the same in the session and after a reload.

    Mutation: let an option's x say the job has no drive; draw Add Travel Labor only on the carrier."""
    o = ran["answer"]["option"]
    assert o["copy"] == "Copy1" and o["pressed"] is True
    assert o["before"] == {"rows": {"Polish:base": DRIVE, "Copy1:option": DRIVE}, "addOnOption": False, "addOnCarrier": False}
    assert o["afterX"] == {"flag": False, "rows": {"Polish:base": DRIVE, "Copy1:option": None}, "saved": False, "addOnOption": True, "addOnCarrier": False}
    assert o["reloaded"] == {"flag": False, "rows": {"Polish:base": DRIVE, "Copy1:option": None}, "addOnOption": True}
    assert o["added"] is True
    assert o["afterAdd"] == {"flag": False, "rows": {"Polish:base": DRIVE, "Copy1:option": DRIVE}, "saved": False}
    assert o["at300"]["session"] == o["at300"]["reloaded"]
    assert o["at300"]["session"]["rows"] == {"Polish:base": "4 x 10 = $1320", "Copy1:option": "4 x 10 = $1320"}


def test_the_root_that_is_an_option_has_its_own_answer_not_the_jobs(ran):
    """A far Polish bid with an Epoxy sheet made the base: the demoted Polish root is an option and keeps its own Travel Labor line while the Epoxy carrier gets a copy. The x on the root option's
    line is the option's, not the job's: the flag stays off, a reload gives the root no blank line (it carries nothing), the card draws Add Travel Labor on it, and pressing it adds the line to
    that option alone.

    Mutation: let the root option's x set the job's answer; append the blank row to a root that is an option."""
    o = ran["answer"]["optionRoot"]
    assert o["before"]["flag"] is False and o["before"]["carrier"] == "Epoxy" and o["before"]["rows"]["Polish:option"] == DRIVE
    assert o["pressed"] is True
    assert o["afterX"] == {"flag": False, "rows": {"Polish:option": None, "Epoxy:base": o["before"]["rows"]["Epoxy:base"]}, "saved": False, "addOnOption": True, "addOnCarrier": False}
    assert o["reloaded"] == {"flag": False, "rows": {"Polish:option": None, "Epoxy:base": o["before"]["rows"]["Epoxy:base"]}, "addOnOption": True}
    assert o["added"] is True
    assert o["afterAdd"]["flag"] is False and o["afterAdd"]["saved"] is False and o["afterAdd"]["rows"]["Polish:option"] == DRIVE


def test_the_x_on_a_leftover_row_says_nothing_and_add_is_never_drawn_on_a_base_that_does_not_carry_the_travel(ran):
    """A Combo's Epoxy base holding a leftover Travel Labor line the estimator typed (2 x 3): its x removes the line and says nothing about the job (the flag stays off, the carrier keeps its
    line), a reload does not bring it back, and Add Travel Labor is not drawn there before or after: the job's drive is charged once, on the carrier.

    Mutation: let a leftover row's x say the job has no drive; draw Add Travel Labor on every section."""
    s = ran["answer"]["stray"]
    assert s["before"] == {"rows": {"Polish:base": DRIVE, "Epoxy:base": "2 x 3 = $198"}, "addOnStray": False} and s["pressed"] is True
    assert s["afterX"] == {"flag": False, "rows": {"Polish:base": DRIVE, "Epoxy:base": None}, "saved": False, "addOnStray": False}
    assert s["reloaded"] == {"flag": False, "rows": {"Polish:base": DRIVE, "Epoxy:base": None}}


def test_a_job_type_switch_after_the_carriers_x_honours_the_answer(ran):
    """DECIDED (2026-10-20): "the job has no drive" is the job's, so it survives a job-type switch. Far Polish, the x on its Travel Labor, the intake switched to Epoxy: the new Epoxy carrier is NOT
    seeded a Travel Labor line (it was seeded 4 x 6.5 = $858 while the flag still said none), the answer stays, the card draws Add Travel Labor, and a reload holds the same bid at the same price.
    Back on Polish the root carries no line and the bid is the one the x left ($40,988); pressing Add Travel Labor on the Epoxy carrier takes the answer back: the line is the distance's
    (4 x 6.5 = $858), the flag is gone, and a reload keeps both.

    Mutation: seed the new carrier a line against the answer; leave the answer in place when the line is added back."""
    s = ran["switchAfterX"]
    assert s["afterX"] == {"flag": True, "rows": {"Polish:base": None}}
    t = s["toEpoxy"]
    assert t["carrier"] == "Epoxy" and t["flag"] is True and t["saved"] is True
    assert t["rows"] == {"Polish:off": None, "Epoxy:base": None}, "the new carrier was given a line the estimator had said the job does not have"
    assert t["addOnCarrier"] is True
    assert s["epoxyReloaded"] == {"flag": True, "rows": t["rows"], "price": t["price"], "quiet": {"armed": 0, "saves": 0}}
    p = s["toPolish"]
    assert p["carrier"] == "Polish" and p["flag"] is True and p["rows"] == {"Polish:base": None, "Epoxy:off": None}
    assert p["price"] == s["priceAfterX"] == 40988
    assert s["polishReloaded"] == {"flag": True, "rows": p["rows"], "price": p["price"]}
    a = s["afterAdd"]
    assert a["added"] is True and a["flag"] is False and a["saved"] is False
    assert a["rows"] == {"Polish:off": None, "Epoxy:base": DRIVE}
    assert s["afterAddReloaded"] == {"flag": False, "rows": a["rows"]}


def test_a_saved_bids_flag_is_read_as_the_jobs_answer_and_dropped_when_the_carrier_holds_a_row(ran):
    """The round-5 x set the root's `no_travel_labor` for ANY Travel line, so a saved bid can hold the flag over a carrier that has its row (an option's own, a leftover's). The flag is the job's
    answer now: it is kept only while the carrier has no Travel Labor line (the library's decline, the carrier's x) and dropped when the carrier holds one, whichever section the carrier is and
    whether or not its sections can be read. The flag prices nothing, so no bid moves (the labor total is read before and after), and what is read twice is read the same.

    A legacy Travel row (2026-09-12: no unit, no rate) is upgraded to the sheet's hours at the company rate, 2 x 2 x $33 = $132, whether or not the bid says the flag: it was left at $0 under the flag.

    Mutation: leave a stale flag in place; drop a flag that is still the carrier's; skip the legacy upgrade when the flag is on."""
    m = ran["migrate"]
    held = {"flag": False, "carrier": "Polish", "carrierRows": 1, "rootRows": 1, "rootLabor": 13530}
    assert m["the carrier (the root) holds a row"] == held
    assert m["the carrier (the root) holds no row"] == {"flag": True, "carrier": "Polish", "carrierRows": 0, "rootRows": 0, "rootLabor": 12672}
    assert m["an Epoxy carrier holds a row, the root is off"] == {"flag": False, "carrier": "Epoxy", "carrierRows": 1, "rootRows": 0, "rootLabor": 12672}
    assert m["an Epoxy carrier holds no row, the root is off"] == {"flag": True, "carrier": "Epoxy", "carrierRows": 0, "rootRows": 0, "rootLabor": 12672}
    assert m["the root carries and an option holds a row"] == {"flag": True, "carrier": "Polish", "carrierRows": 0, "rootRows": 0, "rootLabor": 12672}
    assert m["the sections cannot be read, the root holds a row"] == held
    assert m["legacy"]["plain"] == {"unit": "hours", "rate": 33, "cost": 132, "flag": False}
    assert m["legacy"]["flagged"] == {"unit": "hours", "rate": 33, "cost": 132, "flag": False}
    assert m["priceWithFlag"] == m["priceWithoutFlag"] == 13530
    assert m["idempotent"] is True


def test_the_flag_still_stops_a_stranded_row_being_carried_when_no_carrier_is_named(ran):
    """followDistance with no old carrier named looks for a stranded row; a job that said it has no drive carries none to the new carrier, and one that did not say so does.

    Mutation: take the guard out of the search for a stranded row."""
    s = ran["stranded"]
    assert s["said"] == {"epoxyRow": False, "rootRow": True, "flag": True}
    assert s["notSaid"] == {"epoxyRow": True, "rootRow": False, "flag": False}


# ── X3. the x from the keyboard ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_x_on_a_labor_line_leaves_focus_on_a_control_that_exists(ran):
    """Tab to a labor line's x and press Enter: the line goes and the panel is drawn again, so the button is destroyed and focus fell to <body>. Four lines (Polishing, Mock-up, Joint filler,
    Travel Labor): the x on Mock-up moves focus to the x of the line that took its place (Joint filler); the x on the last line (Travel Labor) to the x of the line before it; with one line
    left no x is drawn, so the x on Joint filler lands on the Add labor line, and the x on the Travel Labor line lands on the Add Travel Labor button that stands where the line was.
    The control focused is always one that is on the page after the redraw.

    Mutation: leave focus where it falls; always take the Add labor line; take the line before the next one."""
    k = ran["keyboard"]
    assert k["start"] == ["polishing", "mockup", "jointfill", "travel"]
    assert (k["middle"]["removed"], k["middle"]["focused"], k["middle"]["alive"]) == ("mockup", ["x:1"], True)
    assert (k["last"]["removed"], k["last"]["focused"], k["last"]["alive"]) == ("travel", ["x:2"], True)
    assert (k["toOne"]["removed"], k["toOne"]["rows"], k["toOne"]["focused"], k["toOne"]["alive"]) == ("jointfill", ["travel"], ["add-lab"], True)
    assert (k["travelToOne"]["removed"], k["travelToOne"]["rows"], k["travelToOne"]["focused"], k["travelToOne"]["alive"]) == ("travel", ["jointfill"], ["add-travel"], True)
