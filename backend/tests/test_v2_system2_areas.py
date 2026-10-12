"""v2: System 1 and System 2 are two separate takeoff areas from the start.

Hanz, 2026-10-13 ("Separate areas"). On the v2 intake, System 1 and System 2 floor SF are TWO takeoff areas, not
one combined floor with System 2 left blank. Before this, a new bid seeded ONE carrier row holding the SUM of
both boxes, the intake then showed System 1 = the sum and System 2 blank, and typing System 2 added a third
plain row on top of the carrier (the floor counted twice).

THE RULE.
  * A new bid with System 1 5,000 and System 2 3,000 gets two areas. Each area has ITS OWN copy of the default
    lines: the System 1 lines measured 5,000, the System 2 lines measured 3,000. The first enabled SF default of
    an area carries it (`floor_area: n`); the rest of that area's lines follow it (`same_floor: true`,
    `same_floor_of: n`). The floor is the two areas added. A linear-foot default is not a floor and is seeded
    once, with the first area.
  * The intake boxes show area 1 and area 2. Typing into one changes that area (its carrier and the lines that
    follow it) and nothing of the other, even when both areas hold the same number. Clearing a box never
    deletes. Typing System 2 on a bid that only has area 1 gives it its own copy of the defaults.
  * A SAVED bid made before this (one carrier holding the whole floor, same_floor rows carrying the same number,
    no marks) opens as saved, prices as saved and edits as it always did.
  * The TOTAL: a line costs its rate times its measurement, so the two copies price the same as one copy on the
    combined floor. The one place that is not exact is a material bought in whole packs, which rounds up once
    per area instead of once overall (`test_two_areas_never_cost_less_than_one_combined_floor` measures it).

EXECUTED, NOT READ. js/system2-areas-harness.js opens a NEW BID on the whole estimate page (js/polish-estimate.js,
through the shared page harness) with the real js/bid-model.js and js/library-core.js, then does to the saved model
what the intake's two boxes do to it. Every check below is a plain function of what the harness answered, and BREAKS
at the bottom breaks one line of one file in a scratch copy, runs the harness on that, and requires the named check
to fail.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "system2-areas-harness.js"

FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/library-core.js",
         "js/work-types.js", "js/polish-sandbox.js", "js/library-picker.js", "js/epoxy-takeoff.js"]


def _run(frontend=FRONTEND):
    require_node()
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, (
        "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr)
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _run()


# What the defaults of ONE area look like on the even library: the first enabled SF default carries the area,
# a second SF default and a material follow it, and the linear-foot default is the one blank row.
def _area(rows, n):
    """The rows of area n: its carrier and the rows that follow it."""
    return [r for r in rows if r["carrier"] == n or r["follows"] == n]


def _strip(rows):
    return [(r["id"], r["m"], r["carrier"], r["follows"]) for r in rows]


# ── the checks: plain functions of what a harness answered ───────────────────
def check_a_new_bid_is_two_areas_each_with_its_own_defaults(a):
    s = a["seeded"]
    assert _strip(s["rows"]) == [
        ("s1", 5000, 1, None), ("s2", 5000, 0, 1), ("s3", "", 0, None), ("e3", 5000, 0, 1),
        ("s1", 3000, 2, None), ("s2", 3000, 0, 2), ("e3", 3000, 0, 2)], _strip(s["rows"])
    assert s["areas"] == 2 and s["measured"] == 8000 and s["priced"] == 8000, s


def check_the_intake_boxes_show_area_1_and_area_2(a):
    assert a["seeded"]["values"] == [5000, 3000], a["seeded"]["values"]


def check_the_new_bid_total_is_what_one_combined_floor_prices(a):
    assert a["seeded"]["total"] == a["combined"]["total"] and a["seeded"]["total"] > 0, (
        "5,000 + 3,000 priced %r, one 8,000 SF floor priced %r" % (a["seeded"]["total"], a["combined"]["total"]))
    assert a["combined"]["values"] == [8000], "the combined floor is one area: %r" % a["combined"]["values"]
    assert a["seeded"]["priced"] == a["combined"]["priced"] == 8000


def check_a_linear_foot_default_is_seeded_once(a):
    lf = [r for r in a["seeded"]["rows"] if r["u"] == "LF"]
    assert len(lf) == 1 and lf[0]["m"] == "", "an LF default was copied per area: %r" % lf


def check_typing_system_2_changes_only_area_2(a):
    s2, seeded = a["sys2"], a["seeded"]
    assert s2["values"] == [5000, 3500] and s2["measured"] == 8500 and s2["priced"] == 8500, s2
    assert s2["rowCount"] == s2["was"] == 7, "typing System 2 added or dropped a row: %r" % s2
    assert _strip(_area(s2["rows"], 1)) == _strip(_area(seeded["rows"], 1)), "area 1 moved: %r" % s2["rows"]
    assert [r["m"] for r in _area(s2["rows"], 2)] == [3500, 3500, 3500], _area(s2["rows"], 2)
    assert not [r for r in s2["rows"] if r["id"] == ""], "System 2 became a third plain row: %r" % s2["rows"]
    # ...and the bid prices what one combined 8,500 SF floor prices
    assert a["sys2Priced"]["total"] == a["sys2Priced"]["combined"] > 0, a["sys2Priced"]


def check_typing_system_1_changes_only_area_1(a):
    s1, seeded = a["sys1"], a["seeded"]
    assert s1["values"] == [4000, 3000] and s1["measured"] == 7000 and s1["rowCount"] == 7, s1
    assert [r["m"] for r in _area(s1["rows"], 1)] == [4000, 4000, 4000], _area(s1["rows"], 1)
    assert _strip(_area(s1["rows"], 2)) == _strip(_area(seeded["rows"], 2)), "area 2 moved: %r" % s1["rows"]
    both = a["both"]
    assert both["values"] == [6000, 2000] and both["measured"] == 8000 and both["priced"] == 8000, both


def check_two_areas_holding_the_same_number_are_still_two_areas(a):
    e = a["equal"]
    assert e["seeded"]["values"] == [4000, 4000] and e["seeded"]["measured"] == 8000, e["seeded"]
    assert [r["m"] for r in _area(e["sys1"]["rows"], 1)] == [5000] * 3, "System 1 did not move: %r" % e["sys1"]["rows"]
    assert [r["m"] for r in _area(e["sys1"]["rows"], 2)] == [4000] * 3, "System 1 dragged area 2: %r" % e["sys1"]["rows"]
    assert [r["m"] for r in _area(e["sys2"]["rows"], 1)] == [4000] * 3, "System 2 dragged area 1: %r" % e["sys2"]["rows"]
    assert [r["m"] for r in _area(e["sys2"]["rows"], 2)] == [5000] * 3, e["sys2"]["rows"]
    assert e["sys1"]["measured"] == e["sys2"]["measured"] == 9000


def check_the_page_moves_only_the_area_of_the_carrier_typed_into(a):
    t = a["typedCarrier"]
    assert [r["m"] for r in _area(t["rows"], 1)] == ["5000"] * 3, _area(t["rows"], 1)
    assert [r["m"] for r in _area(t["rows"], 2)] == [4000] * 3, "the page dragged area 2: %r" % t["rows"]
    assert t["measured"] == 9000 and t["values"] == [5000, 4000], t


def check_a_reload_keeps_both_areas(a):
    r = a["reload"]
    assert r["savedValues"] == [5000, 3000] and r["savedPolishSf"] == 8000, r
    assert r["values"] == [5000, 3000] and r["measured"] == 8000 and r["saves"] == 0, r
    assert r["total"] == a["seeded"]["total"], "reopening repriced the bid: %r" % r
    assert _strip(r["rows"]) == _strip(a["seeded"]["rows"]), "reopening changed the rows: %r" % r["rows"]


def check_a_second_area_typed_later_gets_its_own_defaults(a):
    l = a["late"]
    assert l["before"] == 4 and l["rowCount"] == 7, "area 2 was added as %r rows: %r" % (l["rowCount"], l)
    assert _strip(l["rows"]) == _strip(a["seeded"]["rows"]), l["rows"]
    assert l["values"] == [5000, 3000] and l["total"] == a["seeded"]["total"], l
    assert l["idempotent"] is True, "typing the same two figures again changed the takeoff"


def check_clearing_a_box_never_deletes(a):
    for key, got in a["cleared"].items():
        assert got["rowCount"] == 7, "%s deleted or added a row: %r" % (key, got)
    for key in ("c0", "c1", "c2"):
        assert _strip(a["cleared"][key]["rows"]) == _strip(a["seeded"]["rows"]), a["cleared"][key]
    assert a["cleared"]["c3"]["values"] == [5000, 3000] and a["cleared"]["c4"]["values"] == [5000, 3000]


def check_a_saved_combined_bid_opens_and_edits_as_it_always_did(a):
    o = a["old"]
    assert o["asSaved"] is True and o["saves"] == 0, "a saved bid was rewritten on open: %r" % o
    assert o["view"]["values"] == [8000] and o["view"]["areas"] == 1 and o["view"]["priced"] == 8000, o["view"]
    # System 2 ADDS a plain row, and the line that held the whole floor moves with it (the pre-areas behaviour)
    assert _strip(o["sys2"]["rows"]) == [("s1", 8000, 0, None), ("s3", "", 0, None), ("e3", 11000, 0, 0), ("", 3000, 0, None)], o["sys2"]
    assert o["sys2"]["values"] == [8000, 3000] and o["sys2"]["measured"] == 11000, o["sys2"]
    assert o["sys1"]["values"] == [9000] and [r["m"] for r in o["sys1"]["rows"]] == [9000, "", 9000], o["sys1"]


def check_no_enabled_default_still_gives_one_plain_row_per_area(a):
    off = a["allOff"]
    assert off["values"] == [5000, 3000] and off["measured"] == 8000 and off["priced"] == 8000, off
    plain = [r for r in off["rows"] if r["id"] == ""]
    assert [(r["m"], r["carrier"]) for r in plain] == [(5000, 1), (3000, 2)], plain
    assert all(r["follows"] in (1, 2) for r in off["rows"] if r["id"] != ""), off["rows"]
    lf = a["lfOnly"]
    assert lf["values"] == [5000, 3000] and [r["id"] for r in lf["rows"]] == ["s3", "", ""], lf


def check_an_area_whose_carrier_was_deleted_is_still_an_area(a):
    c = a["carrierGone"]
    assert c["values"] == [5000, 3000] and c["measured"] == 8000, c
    assert c["typed"]["values"] == [4500, 3000] and [r["m"] for r in _area(c["typed"]["rows"], 1)] == [4500, 4500], c["typed"]


def check_a_unit_change_takes_the_row_out_of_its_area(a):
    u = a["unitChange"]
    assert "floor_area" not in u["row"] and "same_floor_of" not in u["row"] and u["row"]["unit"] == "LF", u["row"]
    assert u["values"] == [3000], u["values"]


CHECKS = [
    check_a_new_bid_is_two_areas_each_with_its_own_defaults,
    check_the_intake_boxes_show_area_1_and_area_2,
    check_the_new_bid_total_is_what_one_combined_floor_prices,
    check_a_linear_foot_default_is_seeded_once,
    check_typing_system_2_changes_only_area_2,
    check_typing_system_1_changes_only_area_1,
    check_two_areas_holding_the_same_number_are_still_two_areas,
    check_the_page_moves_only_the_area_of_the_carrier_typed_into,
    check_a_reload_keeps_both_areas,
    check_a_second_area_typed_later_gets_its_own_defaults,
    check_clearing_a_box_never_deletes,
    check_a_saved_combined_bid_opens_and_edits_as_it_always_did,
    check_no_enabled_default_still_gives_one_plain_row_per_area,
    check_an_area_whose_carrier_was_deleted_is_still_an_area,
    check_a_unit_change_takes_the_row_out_of_its_area,
]


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_the_two_systems_are_two_areas(ran, check):
    check(ran)


def test_two_areas_never_cost_less_than_one_combined_floor(ran):
    """The caveat, measured on the real library fixture: a material bought in whole packs rounds up once per
    area, so two areas can cost a pack or two MORE than one combined floor and never less. Both read 8,000 SF."""
    p = ran["packs"]
    assert p["twoPriced"] == p["onePriced"] == 8000, p
    assert p["two"] >= p["one"] > 0, p


# ── RED WITHOUT THE CHANGE ───────────────────────────────────────────────────
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"

BREAKS = {
    "the sum goes on one carrier again": (
        MODEL, "    var areas = [num(sf1), num(sf2)].filter(function (v) { return v > 0; });",
        "    var areas = [num(sf1) + num(sf2)].filter(function (v) { return v > 0; });",
        check_a_new_bid_is_two_areas_each_with_its_own_defaults),
    "the sum on one carrier leaves System 2 blank on the intake": (
        MODEL, "    var areas = [num(sf1), num(sf2)].filter(function (v) { return v > 0; });",
        "    var areas = [num(sf1) + num(sf2)].filter(function (v) { return v > 0; });",
        check_the_intake_boxes_show_area_1_and_area_2),
    "every line of an area counts the floor, so it is priced three times over": (
        MODEL, "          if (on && !carried) { carried = true; r.floor_area = tag; }",
        "          if (on) { carried = true; r.floor_area = tag; }",
        check_the_new_bid_total_is_what_one_combined_floor_prices),
    "a reload reads the sum back as one area": (
        MODEL, "    var areas = [num(sf1), num(sf2)].filter(function (v) { return v > 0; });",
        "    var areas = [num(sf1) + num(sf2)].filter(function (v) { return v > 0; });",
        check_a_reload_keeps_both_areas),
    "a blank box is written into its area as zero": (
        MODEL, "    if (!(v > 0) || !(rows instanceof Array) || (k !== 0 && k !== 1)) return false;",
        "    if (!(rows instanceof Array) || (k !== 0 && k !== 1)) return false;",
        check_clearing_a_box_never_deletes),
    "the second area is a bare row, not a copy of the defaults": (
        MODEL, "        var group = rows.filter(function (x) { return isRow(x) && (carrierTag(x) === tag || (x.same_floor && followerTag(x) === tag)); });",
        "        var group = rows.filter(function (x) { return false; });",
        check_a_second_area_typed_later_gets_its_own_defaults),
    "a linear-foot default is copied for every area": (
        MODEL, '        if (unit !== "SF" && a > 0) return;',
        "        if (false) return;", check_a_linear_foot_default_is_seeded_once),
    "a row that follows an area does not say which": (
        MODEL, "          else { r.same_floor = true; r.same_floor_of = tag; }",
        "          else { r.same_floor = true; }", check_typing_system_1_changes_only_area_1),
    "System 2 drags the rows of System 1 that hold its old number": (
        MODEL, "          if (isRow(x) && x.same_floor && followerTag(x) === ct && num(x.measurement) === old) x.measurement = v;",
        "          if (isRow(x) && x.same_floor && num(x.measurement) === old) x.measurement = v;",
        check_two_areas_holding_the_same_number_are_still_two_areas),
    "the page's typed carrier drags the other area's rows": (
        MODEL, "      if (k !== i && o && o.same_floor && followerTag(o) === tag && num(o.measurement) === num(old)) o.measurement = value;",
        "      if (k !== i && o && o.same_floor && num(o.measurement) === num(old)) o.measurement = value;",
        check_the_page_moves_only_the_area_of_the_carrier_typed_into),
    "an all-off bid's plain rows carry no area mark": (
        MODEL, '        plain.push({ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF", floor_area: tag });',
        '        plain.push({ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF" });',
        check_no_enabled_default_still_gives_one_plain_row_per_area),
    "an area whose carrier is gone stops being an area": (
        MODEL, "      if (carriers.indexOf(ft) < 0 && seen.indexOf(ft) < 0) { seen.push(ft); areas.push(i); }",
        "      if (carriers.indexOf(ft) < 0 && seen.indexOf(ft) < 0) { seen.push(ft); }",
        check_an_area_whose_carrier_was_deleted_is_still_an_area),
    "an area whose carrier is gone drops out of the floor": (
        MODEL, "    held.forEach(function (g) { if (carriers.indexOf(g.tag) < 0) t += g.max; });",
        "    held.forEach(function () {});",
        check_an_area_whose_carrier_was_deleted_is_still_an_area),
    "a unit change leaves the row marked as an area's carrier": (
        MODEL, "    delete r.floor_area;",
        "    r.floor_area = r.floor_area;", check_a_unit_change_takes_the_row_out_of_its_area),
    "a saved combined bid reads its unmarked rows as separate areas": (
        MODEL, "      if (!ft) { if (same < 0) same = i; continue; }",
        "      if (!ft) { areas.push(i); continue; }",
        check_a_saved_combined_bid_opens_and_edits_as_it_always_did),
    "a typed System 2 is a plain row on a bid that has areas": (
        MODEL, "      if (tag) {",
        "      if (false) {", check_a_second_area_typed_later_gets_its_own_defaults),
    "the second box can only add an area, never change one": (
        MODEL, "    var areas = measuredSfRows(rows);",
        "    var areas = measuredSfRows(rows).slice(0, 1);", check_typing_system_2_changes_only_area_2),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    """One line of one file is broken in a scratch copy, the harness runs on it, and the named check has to
    fail on what it answers. The harness runs OUTSIDE the raises block, so a break that merely crashes it is
    an error and not a pass, and break_source refuses an anchor that is not there exactly once."""
    require_node()
    rel, old, new, check = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, FILES)
    broken = _run(frontend)
    with pytest.raises(AssertionError):
        check(broken)


def test_every_check_is_named_by_a_break():
    named = {check for *_, check in BREAKS.values()}
    for check in CHECKS:
        assert check in named, "no break turns %s red" % check.__name__
