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
  X4  THE ROUND-5 LOWS that reproduce: (b) an answer filled the nights of a Lodging or Per Diem line the estimator had switched OFF (now it leaves a line that is off alone, and switching the line ON
      fills it); (c) a labor or takeoff list holding a null threw on open (the fuzz found it the one hostile shape left; a null is read as no row). (a), a typed drive edit lost when the base flips
      back, reproduces and is left: a demoted base keeps its own copy of the row, so when it comes back both rows are the estimator's and both stay (docs/v2-architecture.md).

Each test drives js/polish-estimate.js whole (through tests/js/travel-round6-answer-harness.js, on the real js/bid-model.js) and reads the page back; the last block breaks a COPY of the page or the
model one line at a time and requires a fact to change (never a crash). The facts that only say the scenario ran as described (a button was pressed, which row a step took away, the carrier a
job-type switch made, the rows a case starts from) are guards against a vacuous run, not claims of the fix; every other fact a test reads is changed by at least one of the breaks below (checked by
running every break and comparing the whole report fact by fact).
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
SECTIONS = ["rootCause", "f1", "oracle", "f2", "s1", "answer", "switchAfterX", "migrate", "savedBid", "stranded", "keyboard"]


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
SAVED_TOTAL = 39742               # the far bid of the savedBid section, priced by the PARENT of this change (f8ba775): the same section run on that tree, with its flag on and with it off


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
    assert f["reopened"]["Polish:option"] is None
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


def test_an_options_add_takes_back_only_the_options_answer_and_fills_its_line_on_the_options_own_crew(ran):
    """A far Polish bid copied as an option whose Polishing the estimator made 2 x 12; the x on the CARRIER's line (the job says it has no drive), the x on the option's, then Add Travel Labor on the
    option: the job's answer is still said (the flag is on and the carrier has no line, though Add was pressed), and the option's new line is its OWN crew's, 2 guys x 6.5 hours = $429, not the
    base's 4. A reload holds the same.

    Mutation: let an option's Add take back the job's answer; fill an option's line on the carrier's crew."""
    o = ran["answer"]["optionKeepsJobAnswer"]
    assert o["before"] == {"flag": True, "rows": {"Polish:base": None, "Copy1:option": None}, "addOnOption": True, "addOnCarrier": True}
    assert o["added"] is True
    assert o["afterAdd"] == {"flag": True, "rows": {"Polish:base": None, "Copy1:option": "2 x 6.5 = $429"}, "saved": True}
    assert o["reloaded"] == {"flag": True, "rows": {"Polish:base": None, "Copy1:option": "2 x 6.5 = $429"}}


def test_an_option_made_the_base_that_holds_a_line_hands_the_job_a_drive_and_the_answer_goes(ran):
    """A far Polish bid copied as an option (its own line), the x on the carrier (the job says it has no drive), then the option made the base: the new carrier holds a line of its own, so the
    job has a drive and the answer, which was the old carrier's, is gone, in the page's save and after a reload. The model's pickBase says it on a bid the page has not settled, and does not touch
    the model it was given.

    Mutation: leave the answer in place when the job is handed a line (the page's settling; pickBase)."""
    p = ran["answer"]["promoted"]
    assert p["said"] == {"flag": True, "rows": {"Polish:base": None, "Copy1:option": DRIVE}}
    assert p["modelSays"] == {"flag": False, "inputFlag": True}
    assert p["after"] == {"flag": False, "rows": {"Polish:option": None, "Copy1:base": DRIVE}, "carrier": "Copy1", "saved": False}
    assert p["reloaded"] == {"flag": False, "rows": p["after"]["rows"]}


def test_a_blank_line_a_new_carrier_already_held_is_not_the_drive_a_job_that_said_no_keeps(ran):
    """A new Epoxy bid's off root is never seeded, so it holds the shipped four rows with a blank Travel line (1.5 guys on the older man-days auto). The x on the Epoxy carrier says the job has no
    drive; switched to Combo the root becomes the carrier and its blank line is taken off it (the distance on file filled it to $858 and put the drive back, and dropped the answer), the answer
    stays, Add Travel Labor is drawn on the carrier, and a reload holds the same bid at the same price.

    Mutation: leave the new carrier's blank line to be filled."""
    e = ran["answer"]["newEpoxy"]
    assert e["start"] == {"rows": {"Polish:off": "1.5 x  = $0", "Epoxy:base": DRIVE}, "flag": False}
    t = e["toCombo"]
    assert t["carrier"] == "Polish" and t["flag"] is True and t["rows"] == {"Polish:base": None, "Epoxy:base": None} and t["addOnCarrier"] is True
    assert e["reloaded"] == {"flag": True, "rows": t["rows"], "price": t["price"]}


def test_the_models_own_answers_for_the_x_add_and_the_seeding(ran):
    """The same rules read straight off the model (no page to re-sync or settle anything after it, which hides some of what a wrong model does): Add Travel Labor on an option whose crew is 2 x 12
    puts 2 guys x 6.5 hours on it (the carrier's crew is 4) and leaves the job's answer alone; a sheet that already holds a line, a base that does not carry the travel and a sheet the bid
    does not have are refused. The x on an OPTION says nothing about the job even when the carrier holds no line, and the carrier's says it. Add is offered on the carrier and on an option with
    no line, never on one that holds a line, a base that does not carry the travel or a sheet that is not there. A job that said it has no drive is not seeded a line on the section a job-type
    switch adds; one that did not say so is.

    Mutation: add to an option on the carrier's crew; take back the job's answer from an option; refuse an option; offer a base; let any sheet's x say it; seed against the answer."""
    d = ran["answer"]["direct"]
    assert d["addOnOption"] == {"added": True, "guys": 2, "hours": 6.5, "flag": False}
    assert d["refused"] == {"holdsOne": False, "strayBase": False, "unknownTab": False}
    assert d["optionX"] == {"said": False, "flag": False} and d["carrierX"] == {"said": True, "flag": True}
    assert d["canAdd"] == {"carrier": True, "option": False, "carrierWithLine": False, "optionWithLine": False, "optionWithoutLine": True, "strayBase": False, "unknown": False}
    assert d["seeded"] == {"said": False, "notSaid": True}


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


def test_a_saved_far_bid_with_the_flag_over_its_travel_line_opens_at_the_price_it_always_had(ran):
    """No saved bid may change price on open. The saved-bid ratchet's own fixtures feed the golden of what the page saves, which this change must not recut, so this bid's pin lives here. It is a far
    job (190 miles, Kansas City) saved the way the round-5 x left it: the drive's Travel Labor line (3 x 6.5 hours at $33, following the crew) is on the carrier AND the root says
    `no_travel_labor`. The flag prices nothing, so the bid opens at $39,742 with the flag and without it, the figure the PARENT of this change (f8ba775) gives it (measured by running this same
    section on that tree: 39,742 with the flag on, 39,742 with it off). The flag is dropped (the carrier holds a line), the line is exactly as it was (still following the crew, nothing typed,
    $643.50), and opening the bid saves nothing.

    Mutation: let the flag take the Travel line away on open (the price moves); let it change the line without moving the price (the line stops following the crew); keep the stale flag
    (the entry for the migrate table reads it here as well); make the page save a bid it opened."""
    s = ran["savedBid"]
    row = {"guys": 3, "days": 6.5, "auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hoursTyped": False, "on": True, "cost": 643.5}
    for name in ("withFlag", "withoutFlag"):
        got = s[name]
        assert got["total"] == SAVED_TOTAL, (name, got["total"])
        assert got["flag"] is False, name
        assert got["row"] == row, name
        assert got["saves"] == 0, name


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


# ── X4(b). a line the estimator switched off by hand ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _hand(on, qty, auto, follow, typed, hand):
    return {"on": on, "qty": qty, "auto": auto, "follow": follow, "typed": typed, "hand": hand}








# ── X4(c). a labor or takeoff list that holds a null ────────────────────────────────────────────────────────────────────────────────────────────────────────


# ── red without the code: break a COPY of the page or the model one line at a time ──────────────────────────────────────────────────────────────────────────
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"

APPEND = "if (!said && carrierTabOf(model) === ROOT_TAB) out.labor = laborIn.concat([travelSeed()]);"
KEEP_FLAG = "if (said && !carrierHoldsTravel(model, hasTravel ? out.labor : laborIn)) out.no_travel_labor = true;"
ADD_FILL = '    if (miles !== null && layout !== "gyp") followDistanceOnRow(model, added, holder.labor, miles, !isCarrier);'
REFOCUS_ROWS = "    if (left > 1) { refocus('[data-del-lab=\"' + (at < left ? at : left - 1) + '\"]'); return; }"
REFOCUS_TRAVEL = '    if (wasTravel && document.querySelector("[data-add-travel]")) { refocus("[data-add-travel]"); return; }'
OFF_LINE = "      if (far && l.enabled !== true && !qtyFollows(l)) return;      // a line that is off is left as it is (see above)"
SWITCH_ON = "        if (tl.enabled && B.isFarMiles(dist)) B.followDistanceNights(ROOT, dist, tlKey);"
HOLES_LABOR = "      var laborIn = withoutHoles(model.labor);        // a null row is no row (withoutHoles)"
HOLES_TAKEOFF = "        takeoff: withoutHoles(model.takeoff), labor: laborIn,"
HOLES_SECTION_LABOR = "      if (badLabor) section.labor = s.labor instanceof Array ? withoutHoles(s.labor) : [];"
HOLES_SECTION_TAKEOFF = "      if (badTakeoff) section.takeoff = s.takeoff instanceof Array ? withoutHoles(s.takeoff) : [];"
HOLES_FILTER = "    return hasHoles(rows) ? rows.filter(function (r) { return r !== null && r !== undefined; }) : rows;"
SETTLE = "    if (isObject(model) && model.no_travel_labor === true && carrierHoldsTravel(model)) delete model.no_travel_labor;"
TABLE_OFF_ROOT = "an off root (an Epoxy job's Polish)"
TABLE_OPTION_ROOT = "a root that is an option beside an Epoxy base"
TABLE_STALE = "a stale draft with no sections (saved before 2026-09-12)"
TABLE_UNREADABLE = "a root whose sections cannot be read"
TABLE_SAID = "a root that carries the travel and said it has no drive"

def _holey(g, name):
    """Did this bid with a null in a list fail to open, throw on a step, or price differently from the same bid without it?"""
    h = g["holes"][name]
    return h["opened"] is not True or h["threw"] != {} or h["same"] is not True


# name -> (file, old, new, a fact that must change). Each is one line, which break_source requires to be there exactly once.
BREAKS = {
    # X1: the blank row
    "the blank row is appended to any root": (
        MODEL, APPEND, "if (!said) out.labor = laborIn.concat([travelSeed()]);",
        lambda g: g["rootCause"]["migratedRootRows"] != 0 or g["f1"]["A"] != g["f1"]["B"] or g["s1"]["A"] != g["s1"]["B"]),
    "the blank row is appended to a root that is an option": (
        MODEL, APPEND, 'if (!said && model.kind !== "off") out.labor = laborIn.concat([travelSeed()]);',
        lambda g: g["rootCause"]["table"][TABLE_OPTION_ROOT] != 0 or g["f2"]["session"] != g["f2"]["reloaded"]),
    "the blank row is appended to a root that is off": (
        MODEL, APPEND, 'if (!said && model.kind !== "option") out.labor = laborIn.concat([travelSeed()]);',
        lambda g: g["rootCause"]["table"][TABLE_OFF_ROOT] != 0 or g["f1"]["A"] != g["f1"]["B"]),
    "a stale draft is no longer given its row": (
        MODEL, APPEND, "if (false) out.labor = laborIn.concat([travelSeed()]);",
        lambda g: g["rootCause"]["table"][TABLE_STALE] != 1),
    "a root whose sections cannot be read is given no row": (
        MODEL, APPEND, "if (!said && readableSections(model) !== null && carrierTabOf(model) === ROOT_TAB) out.labor = laborIn.concat([travelSeed()]);",
        lambda g: g["rootCause"]["table"][TABLE_UNREADABLE] != 1),
    "a job that said it has no drive is given the row": (
        MODEL, APPEND, "if (carrierTabOf(model) === ROOT_TAB) out.labor = laborIn.concat([travelSeed()]);",
        lambda g: g["rootCause"]["table"][TABLE_SAID] != 0),
    # X2: a saved bid's flag
    "a flag over a carrier that holds a row is carried": (
        MODEL, KEEP_FLAG, "if (said) out.no_travel_labor = true;",
        lambda g: g["migrate"]["the carrier (the root) holds a row"]["flag"] is not False or g["savedBid"]["withFlag"]["flag"] is not False),
    "a saved bid's flag takes its Travel line away on open": (
        MODEL, KEEP_FLAG, 'if (said) out.labor = out.labor.filter(function (r) { return !(r && r.id === "travel"); });',
        lambda g: g["savedBid"]["withFlag"]["total"] != SAVED_TOTAL and g["migrate"]["priceWithFlag"] != 13530),
    "a saved bid's flag changes its Travel line on open without moving the price": (
        MODEL, KEEP_FLAG, 'if (said) out.labor = out.labor.map(function (r) { if (!r || r.id !== "travel") return r; var c = copyInto({}, r); c.guys_auto = false; return c; });',
        lambda g: g["savedBid"]["withFlag"]["row"]["auto"] is not True and g["savedBid"]["withFlag"]["total"] == SAVED_TOTAL),
    "a job-type switch leaves the drive's row on the sheet it left": (
        MODEL, "      carryTravelRow(model, fromTab);", "      void fromTab;",
        lambda g: g["s1"]["A"]["afterSwitch"]["rows"]["Polish:off"] is not None),
    "a bid is migrated differently the second time": (
        MODEL, KEEP_FLAG, "if (said !== carrierHoldsTravel(model, hasTravel ? out.labor : laborIn)) out.no_travel_labor = true;",
        lambda g: g["migrate"]["idempotent"] is not True),
    "the legacy upgrade is never made": (
        MODEL, "            if (current) return r;", "            return r;",
        lambda g: g["migrate"]["legacy"]["plain"]["cost"] != 132),
    "the page saves a bid it opened": (
        PAGE, "    if (B.snapshotBehind(ROOT, state)) saveSoon();", "    saveSoon();",
        lambda g: g["savedBid"]["withFlag"]["saves"] != 0),
    "a flag that is still the carrier's is dropped": (
        MODEL, KEEP_FLAG, "void said;",
        lambda g: g["migrate"]["the carrier (the root) holds no row"]["flag"] is not True),
    "the legacy upgrade is skipped when the flag is on": (
        MODEL, "        if (!hasTravel) {", "        if (!hasTravel || said) {",
        lambda g: g["migrate"]["legacy"]["flagged"]["cost"] != 132),
    # X2: whose answer the x is
    "an option's x says the job has no drive": (
        PAGE, "      if (B.isTravelRow(gone)) B.travelLaborRemoved(ROOT, activeTab);", "      if (B.isTravelRow(gone)) ROOT.no_travel_labor = true;",
        lambda g: g["answer"]["option"]["afterX"]["flag"] is not False or g["answer"]["stray"]["afterX"]["flag"] is not False or g["answer"]["optionRoot"]["afterX"]["flag"] is not False),
    "the x is recorded whichever sheet it was pressed on": (
        MODEL, 'if (typeof tab === "string" && tab !== "" && tab !== carrier) return false;', "void tab;",
        lambda g: g["answer"]["direct"]["optionX"] != {"said": False, "flag": False}),
    "the carrier's x is not recorded": (
        MODEL, "    model.no_travel_labor = true;", "    void model;",
        lambda g: g["answer"]["carrier"]["afterX"]["flag"] is not True),
    # X2: Add Travel Labor on any sheet that can hold a drive
    "Add Travel Labor is refused on an option": (
        MODEL, 'if (hit.tab !== carrierTab && hit.kind !== "option") return false;', "if (hit.tab !== carrierTab) return false;",
        lambda g: g["answer"]["direct"]["addOnOption"]["added"] is not True or g["answer"]["option"]["afterAdd"]["rows"]["Copy1:option"] != DRIVE or g["answer"]["optionRoot"]["afterAdd"]["rows"]["Polish:option"] != DRIVE),
    "Add Travel Labor is offered on every base": (
        MODEL, 'if (want !== carrier && entry.kind !== "option") return false;', "void want;",
        lambda g: g["answer"]["stray"]["afterX"]["addOnStray"] is not False or g["answer"]["direct"]["canAdd"]["strayBase"] is not False),
    "Add Travel Labor is accepted on a base that does not carry the travel": (
        MODEL, 'if (hit.tab !== carrierTab && hit.kind !== "option") return false;', "void carrierTab;",
        lambda g: g["answer"]["direct"]["refused"]["strayBase"] is not False),
    "Add Travel Labor adds a second line to a sheet that has one": (
        MODEL, "    if (holder.labor.some(function (r) { return isTravelRow(r); })) return false;", "    void holder;",
        lambda g: g["answer"]["direct"]["refused"]["holdsOne"] is not False),
    "Add Travel Labor on a sheet the bid does not have goes to the carrier": (
        MODEL, "        if (!hit || !isObject(hit.section)) return false;", "        if (!hit) hit = entries.filter(function (e) { return e.tab === carrierTab; })[0];",
        lambda g: g["answer"]["direct"]["refused"]["unknownTab"] is not False),
    "Add Travel Labor is not drawn on an option": (
        PAGE, "      if (B.travelLaborCanBeAdded(ROOT, activeTab)) html += addTravelHtml(true);", "      if (false) html += addTravelHtml(true);",
        lambda g: g["answer"]["option"]["afterX"]["addOnOption"] is not True),
    "an option's Add takes back the job's answer": (
        MODEL, "    if (isCarrier) delete model.no_travel_labor;", "    delete model.no_travel_labor;",
        lambda g: g["answer"]["optionKeepsJobAnswer"]["afterAdd"]["flag"] is not True),
    "the carrier's Add leaves the answer in place": (
        MODEL, "    if (isCarrier) delete model.no_travel_labor;", "    void isCarrier;",
        lambda g: g["answer"]["carrier"]["afterAdd"]["flag"] is not False),
    "an option's line is filled on the carrier's crew": (
        MODEL, ADD_FILL, '    if (miles !== null && layout !== "gyp") followDistanceOnRow(model, added, holder.labor, miles, false);',
        lambda g: g["answer"]["direct"]["addOnOption"]["guys"] != 2),
    # X2: a job-type switch honours the answer
    "the new carrier is seeded a line against the answer": (
        MODEL, "      var drives = carrierTab === e.tab && out.no_travel_labor !== true;", "      var drives = carrierTab === e.tab;",
        lambda g: g["switchAfterX"]["toEpoxy"]["rows"]["Epoxy:base"] is not None or g["answer"]["direct"]["seeded"]["said"] is not False),
    "a new carrier keeps a blank line the job said it does not have": (
        MODEL, "      if (model.no_travel_labor === true) releaseNobodysTravelRow(model);", "      void model;",
        lambda g: g["answer"]["newEpoxy"]["toCombo"]["rows"]["Polish:base"] is not None),
    "the answer is left in place when the job is handed a line": (
        MODEL, SETTLE, "    void model;",
        lambda g: g["answer"]["promoted"]["after"]["flag"] is not False or g["answer"]["promoted"]["modelSays"]["flag"] is not False),
    "pickBase leaves the answer in place": (
        MODEL, "    if (out !== model) settleTravelAnswer(out);", "    void out;",
        lambda g: g["answer"]["promoted"]["modelSays"]["flag"] is not False),
    "the stranded-row guard is gone": (
        MODEL, 'if (model.no_travel_labor === true) return "";', "void 0;",
        lambda g: g["stranded"]["said"]["rootRow"] is not True),
    # X3: focus
    # X4(b): a line switched off by hand
    # X4(c): a null in a list
}


def test_no_fact_a_break_looks_for_is_already_changed_on_the_real_tree(ran):
    """The other half of every entry below: the fact it reads is NOT changed on the tree as it is (a break that is "noticed" because its check was already true would prove nothing)."""
    already = sorted(name for name, (_rel, _old, _new, noticed) in BREAKS.items() if noticed(ran))
    assert already == [], "these breaks are noticed on the real tree, so they prove nothing: %s" % already


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line a fact above depends on, broken in a scratch copy of the page or the model; a FACT must change. A break that stops the harness, or makes a section throw, is
    not counted as noticed: it has no facts to compare."""
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
