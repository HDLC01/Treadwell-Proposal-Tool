"""ROUND 7, PART 3 (2026-10-21): ONE FIGURE THE ESTIMATOR TYPED IS PRICED ON ONE BASE (the round-7 audit's F1), on the real estimate page (tests/js/travel-round7-part3-harness.js
runs js/polish-estimate.js over the real js/bid-model.js; every reopen is a jsonb one).

THE FINDING. Far (190 miles) Polish, crew 4 x 12, its Travel Labor typed 7 guys x 3.25 hours = $750.75. An Epoxy sheet added (crew 5 x 12) and made the base on the Sheets panel: the job's
one drive follows its one base, so the Epoxy base takes a COPY of the typed row and the demoted Polish option keeps its own (round 6). Then the intake's job type Combo, or "Make Epoxy + Polish
the base": both sheets are bases, and since Hanz's D1 of 2026-10-21 (a far Combo has two drives, one per base crew) a base that stays a base keeps its own drive, so the Epoxy crew of 5 was
priced the Polish crew's typed 7 x 3.25 on top of the Polish row: $90,416, the Epoxy section $37,670. A figure nobody typed for that sheet. Round 6 gave the repeat back ($88,911, the Epoxy crew
with no drive at all, which D1 now says is wrong too). test_polish_travel_hours.py pinned the same thing for a Sheets copy made a base beside its source ($495 + $495).

THE RULE, read from Hanz's decisions of 2026-10-21. D1: each BASE sheet's Travel Labor row is that base's crew size x the round trip x the rate, filled on a far answer, typeable, ITS OWN answer.
D3: typed figures stay the estimator's. A row the TOOL copied is neither: it is the estimator's say on ANOTHER sheet. So the copy the tool makes (the job's one drive following a base pick while
the old base keeps its own, shiftTravelRow; a Sheets copy of a sheet, copySection) is marked as the tool's (`tool_copy`), and the mark goes the moment the estimator types in the row (its Guys,
Hours or Rate box: markTypedByHand, setLaborRate). When a sheet becomes a base beside another base and a base's row is the tool's copy of what the other base's row says (the same typed or cleared
guys and hours, typed rate and switch), the copy is GIVEN BACK and the base drives its own crew, filled from the miles like any base's drive nobody typed: the finding's Epoxy base is 5 x 6.5 =
$1,072.50 and the bid $91,063, exactly the bid of the same pair made at once, where the Epoxy sheet was never handed a copy. Of two copies, the one on the sheet that became a base gives its
back (the base the job's drive was on keeps it). A copy made the base by itself, and a copy beside a base that does not hold the same say, keep the typed row: a copy prices as its source does.
Two drives the estimator typed alike, each on its own sheet, are both theirs.

ROUND 7, PART 4 (P1, part 3's F1 refined by Hanz's D1 evidence). Kyle's combo-like estimates carry the SAME trip on both crews, each its own guys ("Epoxy trv 4x4; Polish trv 6x4"). So the copy given
back KEEPS the trip the estimator typed, the hours (a figure: a cleared box is no trip) and the rate, and takes its own sheet's crew for the guys; it is not refilled from the computed round trip.
The finding's Epoxy base is 5 x 3.25 = $536.25 and the bid $89,988, exactly the pair made at once with the Polish crew's trip typed into the Epoxy drive's Hours box (part 3 refilled it, 5 x 6.5,
$91,063). A copy of a drive whose hours were not typed (the guys alone typed, a rate alone, the Hours box cleared) is refilled from the miles as before; a typed rate stays with it.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round7-part3-harness.js"
SECTIONS = ("picked", "epoxyFirst", "sheetCopy", "copyAlone", "handTyped", "retyped", "hoursOnly", "noTrip", "rated", "twoCopies", "fillCopied", "diverged", "switched", "added")
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

TYPED_DRIVE = "7 x 3.25 = $750.75"
EPOXY_OWN = "5 x 6.5 = $1072.5"
# P1: the Epoxy crew of 5 on the trip the estimator typed for the Polish crew, 3.25 hours
EPOXY_TRIP = "5 x 3.25 = $536.25"
# A base's drive the far answer filled on its own crew: on auto, following the crew, the round trip's 6.5 hours, nobody's, and not a copy (the $33 rate the line was filled with).
FILLED = {"auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hand": False, "copy": False, "rate": 33}
# The estimator's typed 7 x 3.25 on the sheet they typed it on: off auto, typed, their own (not a copy).
TYPED_OWN = {"auto": False, "follow": None, "seed": 6.5, "typed": True, "hand": False, "copy": False, "rate": 33}
# ...and the tool's copy of it on another sheet.
TYPED_COPY = dict(TYPED_OWN, copy=True)
# P1: the copy given back, the trip kept: its own crew on auto and the typed hours (the round trip's 6.5 the tool filled first stays as the seed), the tool's no longer.
TRIP_KEPT = {"auto": True, "follow": "crew", "seed": 6.5, "typed": True, "hand": False, "copy": False, "rate": 33}
NO_ANSWER = {"job": False, "sheets": {}}
QUIET = {"armed": 0, "saves": 0}
# The finding's bid, as round 6, round 7 and round 7's part 3 priced it: the Epoxy crew with no drive (the audit's run of s4.js), with the Polish crew's copied 7 x 3.25, and with its own crew on the
# round trip the tool filled (5 x 6.5).
ROUND6_LUMP, ROUND7_LUMP, PART3_LUMP = 88911, 90416, 91063
FINDING_PRICE = {"lump": 89988, "root": 52746, "sections": {"Epoxy": 37242}}


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


def _same_after_a_reload(end):
    """A jsonb reload of what the path saved opens quietly, at the same rows, answers and prices."""
    assert end["quiet"] == QUIET, "the reload armed a save: %r" % (end["quiet"],)
    assert end["reloaded"] == end["state"], "the session and a jsonb reload of what it saved disagree:\n%r\n%r" % (end["state"], end["reloaded"])


# ── the finding ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_pick_hands_the_new_base_a_copy_of_the_typed_drive_marked_as_the_tools(ran):
    """A single-base job's drive follows its one base (unchanged): Epoxy made the base takes the typed 7 x 3.25 and the demoted Polish option keeps its own. The Epoxy one is marked as the
    TOOL'S COPY (nobody typed it on the Epoxy sheet); the Polish one, which the estimator typed, is not."""
    a = ran["picked"]["afterPick"]
    assert a["rows"] == {"Polish:option": TYPED_DRIVE, "Epoxy:base": TYPED_DRIVE}
    assert a["marks"]["epoxy"] == TYPED_COPY and a["marks"]["polish"] == TYPED_OWN


def test_made_a_combo_the_epoxy_base_drives_its_own_crew_on_the_trip_the_estimator_typed(ran):
    """THE FINDING, by the intake's job type. Both sheets are bases: the Polish sheet keeps the 7 x 3.25 the estimator typed on it, and the Epoxy base's copy is given back: the trip the estimator
    typed, 3.25 hours, stays (P1: Kyle's sheets carry the same trip on both crews), and the guys are the Epoxy crew's own 5 (D1): 5 x 3.25 = $536.25. Part 3 refilled it from the round trip, 5 x 6.5.
    Its labor is the crew's 5 x 12 days and that drive. A reload opens quietly at the same rows and prices."""
    c = ran["picked"]["combo"]
    assert c["state"]["rows"] == {"Polish:base": TYPED_DRIVE, "Epoxy:base": EPOXY_TRIP} and c["state"]["answers"] == NO_ANSWER
    assert c["marks"]["Epoxy"] == TRIP_KEPT and c["marks"]["Polish"] == TYPED_OWN
    assert ran["picked"]["epoxyLabor"] == 15840 + 536.25
    _same_after_a_reload(c)


def test_the_bid_prices_exactly_as_the_pair_made_at_once_with_the_same_trip_typed_on_both_crews(ran):
    """THE PRICE. The oracle is the same sheets made the pair at once from the Polish base (the Epoxy sheet never handed a copy, so it is given its own line, filled on its own crew, 5 x 6.5), and the
    estimator then typing the Polish crew's trip, 3.25 hours, into the Epoxy drive's Hours box. The finding's bid prices exactly as that one, rows, marks and prices: $89,988 (the Polish section $52,746,
    Epoxy $37,242), by the job type and by "Make Epoxy + Polish the base" alike. Round 6 priced it at $88,911 (no drive on the Epoxy crew), round 7 at $90,416 (the Polish crew's 7 guys on the Epoxy
    sheet) and part 3 at $91,063 (the Epoxy crew on the computed round trip, a trip nobody typed for it)."""
    p = ran["picked"]
    d = p["direct"]
    assert p["filled"]["rows"] == {"Polish:base": TYPED_DRIVE, "Epoxy:base": EPOXY_OWN} and p["filled"]["marks"] == FILLED
    assert d["state"]["rows"] == {"Polish:base": TYPED_DRIVE, "Epoxy:base": EPOXY_TRIP} and d["marks"]["Epoxy"] == TRIP_KEPT
    assert d["state"]["price"] == FINDING_PRICE
    assert p["combo"]["state"]["price"] == d["state"]["price"]
    assert p["pair"]["state"] == d["state"] and p["pair"]["marks"] == d["marks"]
    assert ROUND6_LUMP < d["state"]["price"]["lump"] < ROUND7_LUMP < PART3_LUMP
    _same_after_a_reload(p["pair"])


def test_three_hundred_miles_leaves_both_typed_trips_as_typed(ran):
    """300 miles typed after the Combo, in the session and after a reload alike: the trip the estimator typed is theirs on both sheets, the Polish crew's 7 x 3.25 and the Epoxy crew's 5 x 3.25 (part
    3's Epoxy drive, the tool's, went to 5 x 10)."""
    t = ran["picked"]["at300"]
    assert t["session"]["rows"] == {"Polish:base": TYPED_DRIVE, "Epoxy:base": EPOXY_TRIP}
    assert t["session"] == t["reload"]


# ── the same from Epoxy, and through a Sheets copy ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_from_epoxy_the_polish_sheet_made_the_base_then_the_pair_gives_the_copy_back(ran):
    """Far Epoxy 5 x 10 typed 7 x 3.25, a Polish sheet added (crew 4 x 12) and made the base (it takes the tool's copy), then the pair: Epoxy keeps what the estimator typed on it, and the Polish
    sheet drives its own crew on the same typed trip, 4 x 3.25 = $429."""
    e = ran["epoxyFirst"]
    pol = e["polish"]
    assert e["afterPick"]["marks"]["polish"] == TYPED_COPY and e["afterPick"]["marks"]["epoxy"] == TYPED_OWN
    assert e["state"]["rows"]["Epoxy:base"] == TYPED_DRIVE and e["state"]["rows"][pol + ":base"] == "4 x 3.25 = $429"
    assert e["marks"][pol] == TRIP_KEPT and e["marks"]["Epoxy"] == TYPED_OWN
    _same_after_a_reload(e)


def test_a_sheets_copy_made_a_base_beside_the_typed_drive_gives_its_copy_back(ran):
    """Far Polish 3 x 12 typed 7 x 3.25, the sheet copied (the copy holds the tool's copy of the row, priced apart as an option), the job made Epoxy (the typed drive goes with the job's base to
    Epoxy, the estimator's own row), then the copy and Epoxy made the pair: Epoxy keeps the typed drive, and the copy, a base now, drives its own crew on the typed trip, 3 x 3.25 = $321.75. Until
    round 7, part 3 it priced the one typed figure on both crews; part 3 refilled the copy from the round trip (3 x 6.5)."""
    s = ran["sheetCopy"]
    cp = s["copy"]
    assert s["afterCopy"]["marks"]["copy"] == TYPED_COPY and s["afterCopy"]["marks"]["polish"] == TYPED_OWN
    assert s["asEpoxy"]["rows"] == {"Polish:off": " x  = $0", cp + ":option": TYPED_DRIVE, "Epoxy:base": TYPED_DRIVE}
    assert s["asEpoxy"]["marks"]["epoxy"] == TYPED_OWN and s["asEpoxy"]["marks"]["copy"] == TYPED_COPY and s["asEpoxy"]["pair"] == ["Epoxy", cp]
    assert s["state"]["rows"] == {"Polish:off": " x  = $0", cp + ":base": "3 x 3.25 = $321.75", "Epoxy:base": TYPED_DRIVE}
    assert s["marks"][cp] == TRIP_KEPT and s["marks"]["Epoxy"] == TYPED_OWN
    _same_after_a_reload(s)


# ── what is NOT given back ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_copy_made_the_base_by_itself_keeps_the_typed_drive_and_beside_a_base_that_does_not_hold_it_too(ran):
    """A copy prices as its source does: the copy of the typed Polish sheet made the base by itself keeps 7 x 3.25 (the tool's copy, and the only base), and so it does on a Combo beside an Epoxy
    base, which holds its own drive (5 x 6.5) and not the typed one: the one figure is still on one base. The source is an option, priced apart."""
    a = ran["copyAlone"]
    cp = a["copy"]
    assert a["alone"]["rows"] == {"Polish:option": TYPED_DRIVE, cp + ":base": TYPED_DRIVE} and a["alone"]["marks"] == TYPED_COPY
    assert a["state"]["rows"] == {"Polish:option": TYPED_DRIVE, cp + ":base": TYPED_DRIVE, "Epoxy:base": EPOXY_OWN}
    assert a["marks"][cp] == TYPED_COPY and a["marks"]["Epoxy"] == FILLED
    _same_after_a_reload(a)


def test_two_drives_typed_alike_each_on_its_own_sheet_are_both_kept(ran):
    """A far Combo whose two drives the estimator typed 4 x 4, each on its own sheet (Kyle's own sheets often carry the same hours on both crews), through Polish picked alone and the pair made
    again: both are theirs and both stay. Nothing was copied, so nothing is given back, though the two rows say exactly the same."""
    h = ran["handTyped"]
    assert h["picked"] == {"Polish:base": "4 x 4 = $528", "Epoxy:option": "4 x 4 = $528"}
    assert h["state"]["rows"] == {"Polish:base": "4 x 4 = $528", "Epoxy:base": "4 x 4 = $528"}
    assert not h["marks"]["Polish"]["copy"] and not h["marks"]["Epoxy"]["copy"]
    _same_after_a_reload(h)


def test_a_copy_the_estimator_typed_in_is_theirs_and_stays(ran):
    """After the pick the estimator types 7 again in the Epoxy base's Guys box: the row is no longer the tool's copy, and made a Combo it keeps 7 x 3.25, as typed on both sheets."""
    r = ran["retyped"]
    assert r["before"] == TYPED_COPY and r["after"] == TYPED_OWN
    assert r["state"]["rows"] == {"Polish:base": TYPED_DRIVE, "Epoxy:base": TYPED_DRIVE}
    _same_after_a_reload(r)


# ── every say of the estimator's, and two copies ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_typed_hours_alone_stay_with_the_copy_given_back(ran):
    """Only the hours typed (3.25), the guys on each crew: the Epoxy base's copy carries the typed hours (5 x 3.25 while it is the job's one drive), and made a Combo it is given back, the tool's no
    longer, and keeps the trip: 5 x 3.25 on its own crew (part 3 refilled it, 5 x 6.5); the Polish sheet keeps its typed hours, 4 x 3.25 = $429."""
    h = ran["hoursOnly"]
    assert h["afterPick"]["rows"] == {"Polish:option": "4 x 3.25 = $429", "Epoxy:base": EPOXY_TRIP}
    assert h["afterPick"]["marks"] == dict(TRIP_KEPT, copy=True)
    assert h["state"]["rows"] == {"Polish:base": "4 x 3.25 = $429", "Epoxy:base": EPOXY_TRIP}
    assert h["marks"]["Epoxy"] == TRIP_KEPT
    _same_after_a_reload(h)


def test_a_copy_whose_hours_were_not_typed_is_refilled_from_the_miles_and_a_typed_rate_stays(ran):
    """No trip typed: the guys alone typed (7), a rate alone ($40), the Hours box cleared (a cleared box is no trip). The copy given back drives the Epoxy crew on the round trip the tool fills, 5 x 6.5,
    as part 3 refilled every copy (the copy of the guys or the rate holds the tool's own 6.5, which the fill writes again; the cleared copy is given back empty and filled), and a rate the
    estimator typed stays with it (5 x 6.5 x $40 = $1,300). The Polish sheet keeps what was said on it. A reload agrees."""
    n = ran["noTrip"]
    assert n["guys"]["afterPick"]["marks"]["copy"] is True and n["rate"]["afterPick"]["marks"]["copy"] is True and n["cleared"]["afterPick"]["marks"]["copy"] is True
    assert n["guys"]["state"]["rows"] == {"Polish:base": "7 x 6.5 = $1501.5", "Epoxy:base": EPOXY_OWN} and n["guys"]["marks"]["Epoxy"] == FILLED
    assert n["rate"]["state"]["rows"] == {"Polish:base": "4 x 6.5 = $1040", "Epoxy:base": "5 x 6.5 = $1300"} and n["rate"]["marks"]["Epoxy"] == dict(FILLED, rate="40")
    assert n["cleared"]["state"]["rows"] == {"Polish:base": "4 x  = $0", "Epoxy:base": EPOXY_OWN} and n["cleared"]["marks"]["Epoxy"] == FILLED
    for k in ("guys", "rate", "cleared"):
        _same_after_a_reload(n[k])


def test_a_typed_rate_copied_stays_with_the_trip_and_a_rate_typed_on_the_copy_stays(ran):
    """The rate typed too ($40 over the line's $33): the copy given back keeps the trip, the hours and the rate, on its own crew, 5 x 3.25 x $40 = $650 (part 3 put it back to its own default rate,
    5 x 6.5 x $33), and the Polish sheet keeps 7 x 3.25 x $40 = $910. Typed again on the Epoxy base's copy (the same $40), the row is the estimator's on that sheet and stays at $910."""
    r = ran["rated"]
    assert r["afterPick"]["rows"] == {"Polish:option": "7 x 3.25 = $910", "Epoxy:base": "7 x 3.25 = $910"} and r["afterPick"]["marks"]["copy"] is True
    g = r["given"]
    assert g["state"]["rows"] == {"Polish:base": "7 x 3.25 = $910", "Epoxy:base": "5 x 3.25 = $650"}
    assert g["marks"]["Epoxy"] == dict(TRIP_KEPT, rate="40") and g["marks"]["Polish"]["rate"] == "40"
    _same_after_a_reload(g)
    assert r["retypedMarks"]["copy"] is False
    assert r["kept"]["state"]["rows"] == {"Polish:base": "7 x 3.25 = $910", "Epoxy:base": "7 x 3.25 = $910"}
    _same_after_a_reload(r["kept"])


def test_of_two_copies_the_one_on_the_sheet_that_became_a_base_gives_its_back(ran):
    """Far Epoxy typed 7 x 3.25; a Polish sheet and a second Epoxy sheet added; the Polish sheet made the base (it takes a copy), then the second Epoxy sheet (it takes a copy of that copy, and
    the Polish sheet keeps its own); then the pair, the two copies: the Polish sheet, which became a base, gives its repeat back and drives its own crew on the typed trip (4 x 3.25 = $429), and the
    second Epoxy sheet, the base the job's drive was on, keeps it. The estimator's own row is the first Epoxy sheet's, an option."""
    t = ran["twoCopies"]
    pol, ep2 = t["polish"], t["epoxy2"]
    b = t["beforePair"]
    assert b["pair"] == [ep2, pol]
    assert b["marks"]["epoxy"] == TYPED_OWN and b["marks"]["polish"] == TYPED_COPY and b["marks"]["epoxy2"] == TYPED_COPY
    assert t["state"]["rows"][pol + ":base"] == "4 x 3.25 = $429" and t["state"]["rows"][ep2 + ":base"] == TYPED_DRIVE and t["state"]["rows"]["Epoxy:option"] == TYPED_DRIVE
    assert t["marks"][pol] == TRIP_KEPT and t["marks"][ep2] == TYPED_COPY
    _same_after_a_reload(t)


def test_the_distances_own_fill_copied_by_the_pick_is_not_marked_and_each_crew_drives_its_own(ran):
    """Nothing typed: far Polish's drive is the distance's fill (4 x 6.5), and the pick hands the Epoxy base a copy of it that follows the Epoxy crew (5 x 6.5). Nothing in it is anything the
    estimator said, so it is not marked as the tool's copy of a say; made a Combo, each crew drives its own, $858 and $1,072.50, as D1 has it."""
    f = ran["fillCopied"]
    assert f["afterPick"]["rows"] == {"Polish:option": "4 x 6.5 = $858", "Epoxy:base": EPOXY_OWN}
    assert f["afterPick"]["marks"]["epoxy"] == FILLED and f["afterPick"]["marks"]["polish"] == FILLED
    assert f["state"]["rows"] == {"Polish:base": "4 x 6.5 = $858", "Epoxy:base": EPOXY_OWN} and f["marks"]["Epoxy"] == FILLED
    _same_after_a_reload(f)


@pytest.mark.parametrize("change, polish", [("guys", "6 x 3.25 = $643.5"), ("hours", "7 x 4 = $924"), ("rate", "7 x 3.25 = $1023.75"), ("off", "7 x 3.25 = $0")])
def test_a_copy_that_says_something_no_other_base_says_stays(ran, change, polish):
    """After the pick the estimator changes the Polish option's own drive (its guys to 6, its hours to 4, its rate to $45, or switches it off), then Combo: the Epoxy base's copy no longer says
    what any other base says, so the one figure, 7 x 3.25, is priced once, on Epoxy, and it stays there (still the tool's copy). Each clause of "says the same" is held here alone."""
    d = ran["diverged"][change]
    assert d["state"]["rows"] == {"Polish:base": polish, "Epoxy:base": TYPED_DRIVE}
    assert d["marks"]["Epoxy"] == TYPED_COPY
    _same_after_a_reload(d)


def test_a_copy_whose_switch_the_estimator_flipped_is_theirs_and_a_combo_leaves_it_off(ran):
    """After the pick the estimator switches the Epoxy base's drive off on its own card (the row is theirs on that sheet from then on), and the Polish option's off too: made a Combo, both drives
    stay off as they left them. Were the Epoxy row still the tool's copy, it would say what the Polish row says and be given back, switched on and filled."""
    s = ran["switched"]
    assert s["flipped"] is True and s["after"] == TYPED_OWN
    assert s["off"] == {"polish": True, "epoxy": True}
    assert s["state"]["rows"] == {"Polish:base": "7 x 3.25 = $0", "Epoxy:base": "7 x 3.25 = $0"}
    _same_after_a_reload(s)


def test_a_copy_of_a_drive_the_estimator_added_loses_the_mark_of_an_added_line_when_it_is_given_back(ran):
    """The x on the Polish drive, Add Travel Labor (the line is marked as the estimator's addition), 7 x 3.25 typed, then the pick and the Combo: the Epoxy base's copy carried the mark of an
    added line, and given back it is not an added line (a line nobody added to that sheet, which the promotion rule would not keep under the job's answer); it keeps the typed trip on its crew."""
    a = ran["added"]
    assert a["x"] is True and a["add"] is True
    assert a["afterPick"]["marks"]["hand"] is True and a["afterPick"]["marks"]["copy"] is True
    assert a["state"]["rows"] == {"Polish:base": TYPED_DRIVE, "Epoxy:base": EPOXY_TRIP} and a["state"]["answers"] == NO_ANSWER
    assert a["marks"]["Epoxy"] == TRIP_KEPT and a["marks"]["Polish"]["hand"] is True
    _same_after_a_reload(a)


# ── red without the code: break a COPY of the model one line at a time; a fact must change, never a crash ─────────────────────────────────────────────────────────────────────
# name -> (file, old, new, the facts that notice)
BREAKS = {
    "a copy that repeats another base's row is never given back": (
        "js/bid-model.js", "    var gaveBack = giveBackRepeatedCopies(model, arrived);", "    var gaveBack = [];",
        lambda g: g["picked"]["combo"]["state"]["rows"].get("Epoxy:base") != EPOXY_TRIP or g["picked"]["pair"]["state"] != g["picked"]["direct"]["state"]),
    "a base that stayed a base and gave its copy back is not filled": (
        "js/bid-model.js", "    if (miles !== null) fillArrivals(model, gaveBack.filter(function (tab) { return arrived.indexOf(tab) < 0; }), miles);", "    void gaveBack;",
        lambda g: g["noTrip"]["cleared"]["state"]["rows"].get("Epoxy:base") != EPOXY_OWN or g["noTrip"]["cleared"]["marks"]["Epoxy"] != FILLED),
    "the copy the pick hands the new base is not marked as the tool's": (
        "js/bid-model.js", "    if (keep === true) travelRowsIn(to).forEach(markToolCopy);", "    void keep;",
        lambda g: g["picked"]["afterPick"]["marks"]["epoxy"] != TYPED_COPY or g["picked"]["combo"]["state"]["rows"].get("Epoxy:base") != EPOXY_TRIP),
    "a Sheets copy of a sheet is not marked as the tool's": (
        "js/bid-model.js", "    travelRowsIn(body).forEach(markToolCopy);", "    void body;",
        lambda g: g["sheetCopy"]["state"]["rows"].get(g["sheetCopy"]["copy"] + ":base") != "3 x 3.25 = $321.75"),
    # round 7, part 4 (P1): the trip the copy holds stays, a copy with no figure in its Hours box is refilled, and the guys are the new base's crew
    "a copy given back is refilled from the round trip (part 3's rule)": (
        "js/bid-model.js", "    if (isBlank(row.days)) {", "    if (true) {",
        lambda g: g["picked"]["combo"]["state"]["rows"].get("Epoxy:base") != EPOXY_TRIP or g["rated"]["given"]["state"]["rows"].get("Epoxy:base") != "5 x 3.25 = $650"),
    "a cleared Hours box is kept as a trip": (
        "js/bid-model.js", "    if (isBlank(row.days)) {", "    if (false) {",
        lambda g: g["noTrip"]["cleared"]["state"]["rows"].get("Epoxy:base") != EPOXY_OWN),
    "a copy with no trip is not given back empty": (
        "js/bid-model.js", "      releaseTravelRow(row);", "      void row;",
        lambda g: g["noTrip"]["cleared"]["state"]["rows"].get("Epoxy:base") != EPOXY_OWN or g["noTrip"]["cleared"]["marks"]["Epoxy"] != FILLED),
    "the guys of a copy that keeps its trip stay the source crew's": (
        "js/bid-model.js", "      row.guys_auto = true;", "      void row;",
        lambda g: g["picked"]["combo"]["state"]["rows"].get("Epoxy:base") != EPOXY_TRIP),
    "the guys of a copy that keeps its trip are not marked as its crew's": (
        "js/bid-model.js", '      row.guys_follow = "crew";', "      void row;",
        lambda g: g["picked"]["combo"]["state"]["rows"].get("Epoxy:base") != EPOXY_TRIP),
    "a copy that keeps its trip is still the tool's": (
        "js/bid-model.js", "      delete row.guys_typed; delete row.enabled; delete row.tool_copy;", "      void row;",
        lambda g: g["picked"]["combo"]["marks"]["Epoxy"] != TRIP_KEPT),
    "a copy given back is put back to its own default rate (part 3's rule)": (
        "js/bid-model.js", "    delete row.hand_added;", "    delete row.hand_added; row.rate = 33; delete row.rate_typed;",
        lambda g: g["rated"]["given"]["state"]["rows"].get("Epoxy:base") != "5 x 3.25 = $650" or g["noTrip"]["rate"]["state"]["rows"].get("Epoxy:base") != "5 x 6.5 = $1300"),
    "a copy of a row nobody said anything on is marked too": (
        "js/bid-model.js", "    if (isTravelRow(row) && travelRowIsTheEstimators(row)) row.tool_copy = true;", "    if (isTravelRow(row)) row.tool_copy = true;",
        lambda g: g["fillCopied"]["afterPick"]["marks"]["epoxy"] != FILLED),
    "flipping a copy's switch on its card leaves it the tool's (the page)": (
        "js/polish-estimate.js", "        B.markSwitchedByHand(M.labor[ol]);", "        void ol;",
        lambda g: g["switched"]["after"] != TYPED_OWN or g["switched"]["state"]["rows"].get("Epoxy:base") != "7 x 3.25 = $0"),
    "flipping a copy's switch on its card leaves it the tool's (the model)": (
        "js/bid-model.js", '    if (row && typeof row === "object") delete row.tool_copy;', "    void row;",
        lambda g: g["switched"]["after"] != TYPED_OWN or g["switched"]["state"]["rows"].get("Epoxy:base") != "7 x 3.25 = $0"),
    "the guys typed are not part of what a row says": (
        "js/bid-model.js", "    var guys = travelGuysAreTyped(row) ? text(row.guys) : null;", "    var guys = null;",
        lambda g: g["diverged"]["guys"]["state"]["rows"].get("Epoxy:base") != TYPED_DRIVE),
    "the rate typed is not part of what a row says": (
        "js/bid-model.js", "    var rate = travelRateIsTyped(row) ? text(num(row.rate)) : null;", "    var rate = null;",
        lambda g: g["diverged"]["rate"]["state"]["rows"].get("Epoxy:base") != TYPED_DRIVE),
    "the switch is not part of what a row says": (
        "js/bid-model.js", "    var off = !rowOn(row);", "    var off = false;",
        lambda g: g["diverged"]["off"]["state"]["rows"].get("Epoxy:base") != TYPED_DRIVE),
    "typing in a copy leaves it the tool's": (
        "js/bid-model.js", "    delete row.tool_copy;", "    void row;",
        lambda g: g["retyped"]["after"] != TYPED_OWN or g["retyped"]["state"]["rows"].get("Epoxy:base") != TYPED_DRIVE),
    "typing a rate on a copy leaves it the tool's": (
        "js/bid-model.js", "    if (isTravelRow(row)) delete row.tool_copy;", "    void row;",
        lambda g: g["rated"]["retypedMarks"]["copy"] is not False or g["rated"]["kept"]["state"]["rows"].get("Epoxy:base") != "7 x 3.25 = $910"),
    "a row given back keeps the mark of the tool's copy": (
        "js/bid-model.js", "delete row.hours_typed; delete row.tool_copy;", "delete row.hours_typed;",
        lambda g: g["noTrip"]["cleared"]["marks"]["Epoxy"] != FILLED),
    "a copy that repeats no other base is given back": (
        "js/bid-model.js", "        if (!repeats) return;", "        void repeats;",
        lambda g: g["copyAlone"]["state"]["rows"].get(g["copyAlone"]["copy"] + ":base") != TYPED_DRIVE),
    "a row the estimator typed on its own sheet is given back as if the tool had copied it": (
        "js/bid-model.js", '        if (!isToolCopy(r) || say === "") return;', '        if (say === "") return;',
        lambda g: g["handTyped"]["state"]["rows"] != {"Polish:base": "4 x 4 = $528", "Epoxy:base": "4 x 4 = $528"}
        or g["picked"]["combo"]["state"]["rows"].get("Polish:base") != TYPED_DRIVE),
    "of two copies the base the job's drive was on gives its back": (
        "js/bid-model.js", "    var order = last.filter(function (e) { return came.indexOf(e.tab) >= 0; }).concat(last.filter(function (e) { return came.indexOf(e.tab) < 0; }));",
        "    var order = last.filter(function (e) { return came.indexOf(e.tab) < 0; }).concat(last.filter(function (e) { return came.indexOf(e.tab) >= 0; }));",
        lambda g: g["twoCopies"]["state"]["rows"].get(g["twoCopies"]["epoxy2"] + ":base") != TYPED_DRIVE),
    "a copy given back keeps the mark of an added line": (
        "js/bid-model.js", "    delete row.hand_added;", "    void row;",
        lambda g: g["added"]["marks"]["Epoxy"] != TRIP_KEPT),
    "the hours typed are not part of what a row says": (
        "js/bid-model.js", "    var hours = row.hours_typed === true || (!isBlank(row.days) && !driveHoursAreTools(row)) ? text(row.days) : null;", "    var hours = null;",
        lambda g: g["diverged"]["hours"]["state"]["rows"].get("Epoxy:base") != TYPED_DRIVE),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_model_changes(tmp_path, name):
    """Each change is a line the rule depends on, broken in a scratch copy of the model; a FACT must change. A break that stops the harness, or makes a section throw, is not counted as
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
