"""v2 intake: the quantity boxes edit the takeoff of the section that owns them, not the Polish one alone.

Hanz, 2026-10-13 ("I changed the values but didn't pull in the estimate"). On an Epoxy job he typed 331133 into
System 1's "Epoxy floor SF" and the estimate did not move. The draft held system_1_sf = 331133 and the Epoxy
section's takeoff still held 1000 on every SF row. Since the Epoxy and Gyp sections moved under `tabs`, only the
ROOT (Polish) section's boxes were wired to a takeoff (setAreaSf, measuredSfValues, patchModel's sf_areas, the intake's
paint and save all read `model.takeoff`).

THE RULE NOW. One mapping (js/work-types.js fieldHome) says which tab's takeoff owns each of the nine quantity boxes, in
which unit and in which place of its group. js/bid-model.js turns the tab into the job's section (sectionsOf, so a
section that is off is never touched) and applies, for EVERY section, what the Polish boxes always did:
  * Polish job: the root, as before (polish_sf is the priced area, polish_2_sf blank; the goldens do not move).
  * Epoxy job: System 1 / System 2 are the Epoxy section's first and second SF areas, Cove 1 / Cove 2 its first and
    second measured linear-foot rows.
  * Gyp job: soft, hard and corridor are the Gyp section's three areas (a missing area row is added).
  * Combo: the Polish boxes edit the root, the Epoxy boxes the Epoxy section.
  * Never read-only. Only a box the estimator TYPED writes (a mark good for one save); a figure above zero; blank, 0
    and negative write nothing and delete nothing; areas 3 and on are left to the Takeoff with a note and a link.
  * A section with nothing measured yet: the root and a NEW section are left alone, their boxes seed them on the
    estimate page like any new bid (with the library's default takeoff). A section that was STARTED (the estimator
    edited it: it holds a labor line, a picked assembly or a figure) is never seeded by the estimate page again, so
    the figure typed into it is written into the row it fills here: the first blank row of its unit (a picked row
    before a bare one, never one that is switched off), else a new row. A cove length goes INTO a picked cove row
    whose length is blank, never beside it as a second row that leaves the picked one unpriced.
  * The estimate page, opened on that bid, saves once when ANY live section's price snapshot (the root's polish_sf and
    computed_bid, another section's priced_tabs entry) is behind its takeoff, and writes nothing when they agree.

EXECUTED, NOT READ. js/intake-sections-harness.js runs the real intake page (polish-intake-harness.js's prelude) on
saved models made by B.sectionsForJob; js/estimate-sections-harness.js runs the real estimate page on bids it saved
itself. Every check is a plain function of what a harness answered, and BREAKS at the bottom breaks one line of one
file in a scratch copy, runs the harness on that, and requires the named check to fail.
"""
from __future__ import annotations

import pathlib
import re
import shutil

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
BACKEND = TESTS.parent
INTAKE = TESTS / "js" / "intake-sections-harness.js"
ESTIMATE = TESTS / "js" / "estimate-sections-harness.js"

FILES = ["polish-estimate.html", "polish-intake.html", "js/polish-estimate.js", "js/polish-intake.js", "js/bid-model.js",
         "js/library-core.js", "js/library-picker.js", "js/intake-scope.js", "js/county-picker.js", "js/work-types.js",
         "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/polish-sandbox.js"]


def _run(harness, frontend=FRONTEND):
    require_node()
    proc = run_node(harness, frontend)
    assert proc.returncode == 0, (
        "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr)
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def intake():
    return _run(INTAKE)


@pytest.fixture(scope="module")
def estimate():
    return _run(ESTIMATE)


def _pairs(rows):
    return [(r["id"], r["m"], r["carrier"], r["follows"]) for r in rows]


# ══ the intake page ═════════════════════════════════════════════════════════════════════════════════
def check_the_mapping_names_the_section_unit_and_place_of_every_box(a):
    h = a["homes"]
    want = {"system_1_sf": ("epoxy", "SF", 0), "system_2_sf": ("epoxy", "SF", 1),
            "cove_1_lf": ("epoxy", "LF", 0), "cove_2_lf": ("epoxy", "LF", 1),
            "polish_sf": ("polish", "SF", 0), "polish_2_sf": ("polish", "SF", 1),
            "gyp_soft_sf": ("gyp", "SF", 0), "gyp_hard_sf": ("gyp", "SF", 1), "gyp_corridor_sf": ("gyp", "SF", 2)}
    assert set(h) == set(want), sorted(h)
    for name, (tab, unit, index) in want.items():
        assert (h[name]["tab"], h[name]["unit"], h[name]["index"]) == (tab, unit, index), (name, h[name])
    assert h["polish_sf"]["pooled"] is True and h["polish_2_sf"]["pooled"] is True
    assert not any(h[n]["pooled"] for n in want if not n.startswith("polish")), h
    assert a["homeOfNothing"] is None


def check_the_gyp_area_constants_are_the_librarys(a):
    src = (FRONTEND / "js" / "gyp-takeoff.js").read_text(encoding="utf-8")
    block = src[src.index("var AREA_ASSEMBLIES = {"):]
    block = block[:block.index("};")]
    lib = [(m.group(1), m.group(2), m.group(3))
           for m in re.finditer(r'(\w+): \{ id: "([^"]+)", name: "([^"]+)"', block)]
    assert lib and [tuple(x) for x in a["gypAssemblies"]] == lib, (a["gypAssemblies"], lib)
    assert a["gypBuckets"] == [b for b, _, _ in lib]


def check_an_epoxy_job_boxes_mirror_the_epoxy_section(a):
    assert a["epoxyPainted"]["system_1_sf"] == 1000 and a["epoxyPainted"]["system_2_sf"] == 500, a["epoxyPainted"]
    assert a["epoxyPainted"]["cove_1_lf"] == 120 and a["epoxyPainted"]["cove_2_lf"] == 40, a["epoxyPainted"]
    assert a["epoxyNoSave"] == 0, "opening a saved bid wrote something"


def check_typing_system_1_changes_the_epoxy_area_and_nothing_else(a):
    s = a["sys1"]
    # THE BUG: 331133 typed into "Epoxy floor SF" reached nothing. Now the carrier and the line that follows it move.
    assert _pairs(s["epoxy"]) == [
        ("s1", 331133, 1, None), ("e2", 331133, 0, 1), ("s3", 120, 0, None),
        ("s1", 500, 2, None), ("e2", 500, 0, 2), ("", 40, 0, None)], _pairs(s["epoxy"])
    assert s["values"] == [331133, 500] and s["priced"] == 331633, s
    assert s["rootUntouched"] is True and s["kind"] == "off" and s["tabKind"] == "base", s
    assert s["draft"] == {"s1": 331133, "s2": 500, "c1": 120, "c2": 40}, s["draft"]
    assert s["shown"]["system_1_sf"] == "331133"


def check_system_2_and_both_cove_boxes_map_to_their_own_rows(a):
    assert a["sys2"]["measures"] == [331133, 331133, 120, 800, 800, 40], a["sys2"]
    assert a["sys2"]["draft"]["s2"] == 800 and a["sys2"]["draft"]["s1"] == 331133
    assert a["cove1"]["measures"] == [331133, 331133, 200, 800, 800, 40], a["cove1"]
    assert a["cove2"]["measures"] == [331133, 331133, 200, 800, 800, 60], a["cove2"]
    assert a["cove2"]["lfValues"] == [200, 60]
    assert a["cove2"]["draft"] == {"s1": 331133, "s2": 800, "c1": 200, "c2": 60}, a["cove2"]["draft"]


def check_typing_zero_or_nothing_deletes_and_writes_nothing(a):
    assert set(a["zero"]) == {"s2zero", "s2blank", "c1zero", "c2blank", "s1neg", "c2zero"}
    for label, z in a["zero"].items():
        assert z["rowsSame"] is True and z["rowCount"] == 6, (label, z)
        assert z["draft"] == {"s1": 1000, "s2": 500, "c1": 120, "c2": 40}, (label, z["draft"])
    # leaving the box shows the row's own figure back
    assert a["zero"]["s2zero"]["afterBlur"] == 500 and a["zero"]["c1zero"]["afterBlur"] == 120
    assert a["zero"]["c2blank"]["afterBlur"] == 40 and a["zero"]["s1neg"]["afterBlur"] == 1000


def check_the_door_refuses_a_figure_that_is_not_above_zero(a):
    d = a["direct"]
    assert d["zeroLeavesRows"] is True and d["gypZeroLeavesRows"] is True, d
    assert d["pure"] is True, "patchModel changed the model it was handed"
    assert d["moved"] is True and d["typedMeasures"] == [4100, 4100, 150, 500, 500, 40], d


def check_a_cove_box_adds_the_row_it_has_none_for(a):
    assert a["direct"]["addedCove"] == [120, 30], a["direct"]


def check_the_pair_of_polish_boxes_still_goes_through_sf_areas(a):
    assert a["direct"]["pairRoot"] == [8100, 600], a["direct"]


def check_a_box_nobody_typed_in_never_writes_and_a_mark_lasts_one_save(a):
    assert a["untyped"]["measures"] == [1000, 1000, 120, 500, 500, 40] and a["untyped"]["s1"] == 1000, a["untyped"]
    assert a["markOnce"]["once"] == [1200, 1200, 120, 500, 500, 40], a["markOnce"]
    assert a["markOnce"]["after"][0] == 4321, "a later save sent the old typed figure again: %r" % a["markOnce"]


def check_a_third_area_is_left_alone_with_a_note_and_a_link(a):
    t = a["third"]
    assert t["hidden"] is False and t["rowHidden"] is False, t
    assert "3 measured areas" in t["text"] and "1,750 SF" in t["text"] and "Areas 3 and on" in t["text"], t["text"]
    assert t["href"].startswith("/polish-estimate.html?d="), t["href"]
    assert t["measures"] == [1000, 1000, 120, 900, 900, 40, 250], t["measures"]


def check_an_unmeasured_section_is_seeded_by_the_estimate_page_not_written_here(a):
    u = a["unmeasured"]
    assert u["epoxyRows"] == [["SF", ""]], "the intake wrote rows into a takeoff nobody had measured: %r" % u
    assert u["draft"]["s1"] == "5000" and u["draft"]["c1"] == "80", u["draft"]
    assert u["rootKind"] == "off"


def check_a_gyp_job_boxes_are_the_three_areas(a):
    assert a["gypPainted"]["gyp_soft_sf"] == 4000 and a["gypPainted"]["gyp_hard_sf"] == 2000, a["gypPainted"]
    assert a["gypPainted"]["gyp_corridor_sf"] == "", a["gypPainted"]
    assert a["gyp"]["rows"] == [["wb-gyp-area-soft", 4000, "soft", "SF"], ["wb-gyp-area-hard", 2600, "hard", "SF"],
                                ["wb-gyp-area-corridor", 900, "corridor", "SF"]], a["gyp"]["rows"]
    assert a["gyp"]["draft"] == {"g1": 4000, "g2": 2600, "g3": 900}, a["gyp"]["draft"]
    assert a["gypZero"]["rows"] == [["soft", 4000], ["hard", 2000]], a["gypZero"]


def check_a_combo_job_polish_boxes_edit_the_root_and_epoxy_boxes_the_epoxy_section(a):
    assert a["comboPainted"]["polish_sf"] == 7000 and a["comboPainted"]["system_1_sf"] == 1000
    assert a["comboPolish"]["root"] == [9000] and a["comboPolish"]["epoxy"] == [1000, 1000, 120, 500, 500, 40], a["comboPolish"]
    assert a["comboPolish"]["draft"]["p1"] == 9000 and a["comboPolish"]["draft"]["p2"] == ""
    assert a["comboEpoxy"]["root"] == [9000] and a["comboEpoxy"]["epoxy"] == [3500, 3500, 120, 500, 500, 40], a["comboEpoxy"]
    assert a["comboBoth"]["root"] == [8000] and a["comboBoth"]["epoxy"] == [1000, 1000, 120, 650, 650, 40], a["comboBoth"]
    assert a["comboBoth"]["saves"] == 1


def check_a_polish_job_is_what_it_was(a):
    assert a["polishPainted"]["polish_sf"] == 7000 and a["polishPainted"]["polish_2_sf"] == 3000
    p = a["polish"]
    assert p["rows"] == [8000, 3000] and p["hasTabs"] is False, p
    assert p["draft"]["p1"] == 11000 and p["draft"]["p2"] == "", p["draft"]


def check_a_section_that_is_off_is_never_written(a):
    o = a["offRoot"]
    assert o["root"] == [7000] and o["kind"] == "off" and o["epoxy"] == [1000, 1000, 120, 500, 500, 40], o


def check_a_figure_typed_and_tabbed_away_inside_the_save_delay_survives(a):
    r = a["blurRace"]
    assert r["afterBlur"] == 2222 and r["measures"][0] == 2222 and r["shown"] == 2222, r


def check_the_door_never_edits_the_model_it_was_handed(a):
    assert a["direct"]["pure"] is True


def check_a_started_section_nobody_measured_is_seeded_by_the_intake(a):
    s = a["started"]
    # THE BUG: Epoxy held Travel and a blank takeoff, so the estimate page would never seed it; System 1 = 5000 stayed
    # in the draft key and the estimate priced nothing.
    assert s["sys1"]["isNew"] is False, "the fixture must be a section the estimate page would not seed"
    assert s["sys1"]["rows"] == ["-|SF|5000|"], s["sys1"]
    assert s["sys1"]["draft"] == {"s1": 5000, "s2": ""} and s["sys1"]["shown"] == "5000", s["sys1"]
    # all four boxes in one save: System 1 fills the blank row, System 2 and both cove lengths are added after it
    assert s["all"]["sf"] == [5000, 3000] and s["all"]["lf"] == [80, 40] and s["all"]["count"] == 4, s["all"]
    assert s["all"]["draft"] == {"s1": 5000, "s2": 3000, "c1": 80, "c2": 40}, s["all"]["draft"]
    # picked rows with no figure yet take the figures, and no row is added beside them
    assert s["pickedBoth"]["rows"] == ["s1|SF|5000|", "s3|LF|150|"], s["pickedBoth"]
    # a row switched off never carries the floor (a bare row is added to), and follows it, as a new bid's off default does
    assert s["off"]["rows"] == ["s1|SF|900|off", "-|SF|900|"], s["off"]
    # THE DEFAULTS of a bid opened with no floor are one floor, as a new bid seeds them: the first line carries it, the
    # other follows it (same_floor, not counted twice), and a second area gets its own copy of the lines.
    d1, d2 = s["defaults1"], s["defaults2"]
    assert d1["rows"] == ["s1|SF|5000|area1|", "s3|LF|||", "e2|SF|5000||of1"], d1
    assert d1["priced"] == 5000 and d1["sf"] == [5000], d1
    assert d2["fresh"][1] == "s3|LF|||", d2["fresh"]
    assert d2["rows"] == d2["fresh"][:1] + ["s3|LF|150||"] + d2["fresh"][2:], "not what a new bid is given: %r" % d2
    assert d2["priced"] == 8000 and d2["sf"] == [5000, 3000] and d2["lf"] == 150, d2
    g = s["gyp"]
    assert g["areas"] == [["soft", 4000], ["hard", 2000]] and g["draft"] == {"g1": 4000, "g2": 2000, "g3": ""}, g
    # the Epoxy half of a Combo bid is the same section, and its measured Polish root is not touched
    assert s["combo"] == {"epoxy": ["-|SF|5000|"], "root": [7000]}, s["combo"]


def check_the_polish_root_is_left_to_the_estimate_page_even_when_nothing_is_measured(a):
    # The estimate page seeds a new root with the library's default takeoff; a figure written here would stop it.
    assert a["started"]["root"] == {"rows": ["-|SF||"], "draft": "5000"}, a["started"]["root"]


def check_a_cove_length_goes_into_the_picked_row_and_never_beside_it(a):
    s = a["started"]
    # THE BUG: the picked cove row stayed blank (unpriced) and a second, blank-assembly row held the figure
    assert s["picked"]["rows"] == ["s1|SF|1000|", "s3|LF|150|"], s["picked"]
    assert s["picked"]["shown"] == "150" and s["picked"]["lf"] == 150, s["picked"]
    # a row the estimator picked is preferred to a bare blank one
    assert s["prefer"]["rows"] == ["s1|SF|1000|", "-|LF||", "s3|LF|150|"], s["prefer"]


def check_a_second_cove_length_goes_below_the_first_and_one_with_no_first_is_counted_once(a):
    s = a["started"]
    # the blank picked row ABOVE the measured one is not filled: it would become Cove 1 and swap the two boxes
    assert s["second"]["rows"] == ["s1|SF|1000|", "s3|LF||", "s4|LF|120|", "-|LF|40|"], s["second"]
    assert s["second"]["lf"] == [120, 40] and s["second"]["shown"][0] == 120, s["second"]
    # no cove is measured: there is no second cove without a first, so the figure is counted once, as the first
    assert s["lone"] == {"lf": 123, "values": [123]}, s["lone"]


INTAKE_CHECKS = [
    check_the_mapping_names_the_section_unit_and_place_of_every_box,
    check_the_gyp_area_constants_are_the_librarys,
    check_an_epoxy_job_boxes_mirror_the_epoxy_section,
    check_typing_system_1_changes_the_epoxy_area_and_nothing_else,
    check_system_2_and_both_cove_boxes_map_to_their_own_rows,
    check_typing_zero_or_nothing_deletes_and_writes_nothing,
    check_the_door_refuses_a_figure_that_is_not_above_zero,
    check_a_cove_box_adds_the_row_it_has_none_for,
    check_the_pair_of_polish_boxes_still_goes_through_sf_areas,
    check_a_box_nobody_typed_in_never_writes_and_a_mark_lasts_one_save,
    check_a_third_area_is_left_alone_with_a_note_and_a_link,
    check_an_unmeasured_section_is_seeded_by_the_estimate_page_not_written_here,
    check_a_started_section_nobody_measured_is_seeded_by_the_intake,
    check_the_polish_root_is_left_to_the_estimate_page_even_when_nothing_is_measured,
    check_a_cove_length_goes_into_the_picked_row_and_never_beside_it,
    check_a_second_cove_length_goes_below_the_first_and_one_with_no_first_is_counted_once,
    check_a_gyp_job_boxes_are_the_three_areas,
    check_a_combo_job_polish_boxes_edit_the_root_and_epoxy_boxes_the_epoxy_section,
    check_a_polish_job_is_what_it_was,
    check_a_section_that_is_off_is_never_written,
    check_a_figure_typed_and_tabbed_away_inside_the_save_delay_survives,
    check_the_door_never_edits_the_model_it_was_handed,
]


@pytest.mark.parametrize("check", INTAKE_CHECKS, ids=lambda c: c.__name__)
def test_the_intake(check, intake):
    check(intake)


# ══ the estimate page, opened on what the intake left ═══════════════════════════════════════════════
def check_an_epoxy_floor_typed_on_the_intake_reaches_the_estimate_and_its_snapshot(e):
    assert e["epoxyBefore"]["carriers"] == [5000, 3000] and e["epoxyBefore"]["sf"] == {"epoxy_sf": 8000, "cove_lf": 140}
    t = e["epoxyTyped"]
    assert t["areas"] == [331133, 3000], t
    assert t["total"] > e["epoxyBefore"]["total"] * 10, "the estimate did not follow the floor: %r" % t
    assert t["savesBeforeTimer"] == 0 and t["saves"] == 1, t
    # the draft's price snapshot says what the page shows
    assert t["snap"] == {"epoxy_sf": 334133, "cove_lf": 140} and t["sheetArea"] == t["snap"], t
    assert t["lump"] == t["total"] == t["tabTotal"], t


def check_a_cove_length_typed_on_the_intake_reprices_the_epoxy_snapshot(e):
    assert e["epoxyCove"]["saves"] == 1 and e["epoxyCove"]["snap"] == {"epoxy_sf": 8000, "cove_lf": 290}, e["epoxyCove"]


def check_reopening_a_bid_that_agrees_writes_nothing(e):
    assert e["epoxyReopen"]["saves"] == 0 and e["comboReopen"]["saves"] == 0 and e["polish"]["reopenSaves"] == 0, e
    assert e["polish"]["noSnapshotSaves"] == 0, "a draft that never had a price snapshot was written on open"


def check_a_combo_bid_is_checked_for_each_section(e):
    assert e["comboBefore"]["rootSf"] == 7000 and e["comboBefore"]["epoxySf"] == {"epoxy_sf": 8000, "cove_lf": 100}
    r = e["comboRoot"]
    assert r["saves"] == 1 and r["polishSf"] == 9000 and r["computedPolishSf"] == 9000, r
    assert r["epoxy"] == {"epoxy_sf": 8000, "cove_lf": 100}, r
    x = e["comboEpoxy"]
    assert x["saves"] == 1 and x["polishSf"] == 7000 and x["epoxy"] == {"epoxy_sf": 9500, "cove_lf": 100}, x


def check_a_polish_bid_still_reprices_on_open(e):
    p = e["polish"]
    assert p["typedSaves"] == 1 and p["polishSf"] == 9000 and p["computed"] == 9000, p


def check_the_snapshot_check_reads_a_gyp_section_too(e):
    g = e["gypCheck"]
    assert g["agrees"] is False and g["moved"] is True and g["noSnapshot"] is False, g


def check_a_floor_typed_into_a_started_section_nobody_measured_is_priced(e):
    s = e["started"]
    # THE BUG: the section held Travel and the library's blank lines, so this page never seeded it again; the draft said
    # 5000 and the estimate said 0.
    assert s["isNew"] is False, "the fixture must be a section this page would not seed: %r" % s
    assert s["before"] == {"sf": 0, "total": 0}, s["before"]
    assert s["after"]["sf"] == 5000 and s["after"]["total"] > 0, s["after"]
    # priced exactly as the same floor typed before the estimate was opened, every default line included
    assert s["after"]["total"] == s["fresh"], s
    assert s["after"]["snap"] == {"epoxy_sf": 5000, "cove_lf": 0}, s["after"]


def check_a_cove_length_typed_on_the_intake_prices_the_picked_cove_line(e):
    c = e["startedCove"]
    # THE BUG: the figure went into a new blank-assembly row and the picked cove line stayed unmeasured, so unpriced
    assert c["rows"] == c["rowsBefore"] == 3, c
    assert c["typed"] == c["right"] and c["typed"] > c["without"], c


ESTIMATE_CHECKS = [
    check_an_epoxy_floor_typed_on_the_intake_reaches_the_estimate_and_its_snapshot,
    check_a_cove_length_typed_on_the_intake_reprices_the_epoxy_snapshot,
    check_reopening_a_bid_that_agrees_writes_nothing,
    check_a_combo_bid_is_checked_for_each_section,
    check_a_polish_bid_still_reprices_on_open,
    check_the_snapshot_check_reads_a_gyp_section_too,
    check_a_floor_typed_into_a_started_section_nobody_measured_is_priced,
    check_a_cove_length_typed_on_the_intake_prices_the_picked_cove_line,
]


@pytest.mark.parametrize("check", ESTIMATE_CHECKS, ids=lambda c: c.__name__)
def test_the_estimate(check, estimate):
    check(estimate)


# ══ red without the code: break a COPY, run the harness on it, the named check has to fail ══════════
MODEL = "js/bid-model.js"
INTAKE_JS = "js/polish-intake.js"
PAGE = "js/polish-estimate.js"
TYPES = "js/work-types.js"

_UNMEASURED_GATE = "      if (!measured && (hit.entry.root || isNewSection(hit.entry.section, false))) return;"
_BLANK_UNIT = '      if (!(r.unit === unit || (unit === "SF" && !r.unit))) return;'
_PREFER_PICKED = "      if (at < 0 || (!(rows[at].assembly_id || rows[at].item_id) && (r.assembly_id || r.item_id))) at = i;"
_AFTER_FIRST = "      if (i <= after || !r || r.same_floor || !rowOn(r) || num(r.measurement) > 0) return;"
_FOLLOWERS = "      if (i === at || !pickedBlankSf(r)) return;"
_BOX_LOOKUP = '      if (list[i].kind !== "off" && sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };'

# name -> (harness, file, old line, new line, check)
BREAKS = {
    # the bug as it was: only the root section is ever looked at
    "only the Polish root is wired to a box": (
        INTAKE, MODEL, _BOX_LOOKUP,
        '      if (list[i].root && list[i].kind !== "off" && sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };',
        check_typing_system_1_changes_the_epoxy_area_and_nothing_else),
    "the Epoxy boxes mirror the Polish root": (
        INTAKE, MODEL, _BOX_LOOKUP,
        '      if (list[i].root && list[i].kind !== "off" && sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };',
        check_an_epoxy_job_boxes_mirror_the_epoxy_section),
    "the Combo Epoxy boxes edit nothing": (
        INTAKE, MODEL, _BOX_LOOKUP,
        '      if (list[i].root && list[i].kind !== "off" && sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };',
        check_a_combo_job_polish_boxes_edit_the_root_and_epoxy_boxes_the_epoxy_section),
    "the Gyp boxes edit nothing": (
        INTAKE, MODEL, _BOX_LOOKUP,
        '      if (list[i].root && list[i].kind !== "off" && sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };',
        check_a_gyp_job_boxes_are_the_three_areas),
    "a section that is off is written": (
        INTAKE, MODEL, _BOX_LOOKUP,
        '      if (sheets.indexOf(list[i].tab) >= 0) return { entry: list[i], home: home };',
        check_a_section_that_is_off_is_never_written),
    "the edit goes to the root's rows, whatever section owns the box": (
        INTAKE, MODEL, "      var view = sectionView(model, tab), h = hit.home;", "      var view = model, h = hit.home;",
        check_typing_system_1_changes_the_epoxy_area_and_nothing_else),
    "a cove box shows square feet": (
        INTAKE, MODEL, '    var vals = h.unit === "SF" ? measuredSfValues(rows) : measuredLfValues(rows);',
        "    var vals = measuredSfValues(rows);", check_an_epoxy_job_boxes_mirror_the_epoxy_section),
    "a cove box writes a floor area": (
        INTAKE, MODEL, '      else if (h.unit === "LF") setAreaLf(view, h.index, v);',
        "      else if (false) setAreaLf(view, h.index, v);", check_system_2_and_both_cove_boxes_map_to_their_own_rows),
    "a zero cove figure is written into its row": (
        INTAKE, MODEL, "    if (!(v > 0)) return false;", "    if (false) return false;",
        check_the_door_refuses_a_figure_that_is_not_above_zero),
    "a zero Gyp figure is written into its area": (
        INTAKE, MODEL, "    if (!(v > 0) || !(rows instanceof Array) || GYP_BUCKETS.indexOf(bucket) < 0) return false;",
        "    if (!(rows instanceof Array) || GYP_BUCKETS.indexOf(bucket) < 0) return false;",
        check_the_door_refuses_a_figure_that_is_not_above_zero),
    "a cove box with no row to change adds nothing": (
        INTAKE, MODEL, '    if (at < 0) { rows.push({ assembly_id: "", assembly_name: "", measurement: v, unit: unit }); return; }',
        "    if (at < 0) return;", check_a_cove_box_adds_the_row_it_has_none_for),
    "a Gyp area with no row is dropped": (
        INTAKE, MODEL, '    rows.push({ assembly_id: asm.id, assembly_name: asm.name, measurement: v, unit: "SF", bucket: bucket });',
        "    return false;", check_a_gyp_job_boxes_are_the_three_areas),
    "the Gyp area ids drift from the library's": (
        INTAKE, MODEL, '    { bucket: "soft", id: "wb-gyp-area-soft", name: "Gypsum: soft surfaces" },',
        '    { bucket: "soft", id: "gyp-area-soft", name: "Gypsum: soft surfaces" },',
        check_the_gyp_area_constants_are_the_librarys),
    "the model handed to the door is edited in place": (
        INTAKE, MODEL,
        "    out.tabs = Object.assign({}, model.tabs, Object.fromEntries([[tab, Object.assign({}, sec, { takeoff: jsonCopy(sec.takeoff) })]]));",
        "    out.tabs = Object.assign({}, model.tabs, Object.fromEntries([[tab, Object.assign({}, sec, { takeoff: sec.takeoff })]]));",
        check_the_door_never_edits_the_model_it_was_handed),
    "a Polish pair is not the first and second Polish box any more": (
        INTAKE, MODEL, "    model = applyBoxes(model, boxes);", "    void boxes;", check_the_pair_of_polish_boxes_still_goes_through_sf_areas),
    "a Polish draft holds the first area, not the priced total": (
        INTAKE, MODEL, "    if (!hit.home.pooled) return v;", "    return v;", check_a_polish_job_is_what_it_was),
    "a cove box is mapped to Polish": (
        INTAKE, TYPES, '  var SCOPE_TAB = new Map([["epoxy", "epoxy"], ["cove", "epoxy"], ["polish", "polish"], ["gyp", "gyp"]]);',
        '  var SCOPE_TAB = new Map([["epoxy", "epoxy"], ["cove", "polish"], ["polish", "polish"], ["gyp", "gyp"]]);',
        check_the_mapping_names_the_section_unit_and_place_of_every_box),
    "an area 3 is not mentioned": (
        INTAKE, MODEL, "      if (n > 2) out.push({ tab: hit.entry.tab, areas: n, total: measuredSf(rows) });",
        "      if (n > 3) out.push({ tab: hit.entry.tab, areas: n, total: measuredSf(rows) });",
        check_a_third_area_is_left_alone_with_a_note_and_a_link),
    "a section nobody measured is written by the intake": (
        INTAKE, MODEL, _UNMEASURED_GATE, "      if (false) return;",
        check_an_unmeasured_section_is_seeded_by_the_estimate_page_not_written_here),
    "a NEW section is written by the intake, so the library's defaults are skipped": (
        INTAKE, MODEL, _UNMEASURED_GATE, "      if (!measured && hit.entry.root) return;",
        check_an_unmeasured_section_is_seeded_by_the_estimate_page_not_written_here),
    "the Polish root is written by the intake before the estimate seeds it": (
        INTAKE, MODEL, _UNMEASURED_GATE, "      if (!measured && isNewSection(hit.entry.section, false)) return;",
        check_the_polish_root_is_left_to_the_estimate_page_even_when_nothing_is_measured),
    "a started section nobody measured is left for an estimate page that never seeds it": (
        INTAKE, MODEL, _UNMEASURED_GATE, "      if (!measured) return;",
        check_a_started_section_nobody_measured_is_seeded_by_the_intake),
    "the estimate prices nothing of a floor typed into a started section": (
        ESTIMATE, MODEL, _UNMEASURED_GATE, "      if (!measured) return;",
        check_a_floor_typed_into_a_started_section_nobody_measured_is_priced),
    "a picked cove row is never filled, a second row is added beside it": (
        INTAKE, MODEL, _BLANK_UNIT, "      return;",
        check_a_cove_length_goes_into_the_picked_row_and_never_beside_it),
    "the estimate leaves the picked cove line unmeasured": (
        ESTIMATE, MODEL, _BLANK_UNIT, "      return;",
        check_a_cove_length_typed_on_the_intake_prices_the_picked_cove_line),
    "a bare blank row is preferred to a picked one": (
        INTAKE, MODEL, _PREFER_PICKED, "      if (at < 0) at = i;",
        check_a_cove_length_goes_into_the_picked_row_and_never_beside_it),
    "a second cove fills a blank row above the first and swaps the two boxes": (
        INTAKE, MODEL, _AFTER_FIRST, "      if (!r || r.same_floor || !rowOn(r) || num(r.measurement) > 0) return;",
        check_a_second_cove_length_goes_below_the_first_and_one_with_no_first_is_counted_once),
    "a row that is switched off carries the floor": (
        INTAKE, MODEL, _AFTER_FIRST, "      if (i <= after || !r || r.same_floor || num(r.measurement) > 0) return;",
        check_a_started_section_nobody_measured_is_seeded_by_the_intake),
    "the other picked lines of a floor are left blank": (
        INTAKE, MODEL, _FOLLOWERS, "      return;",
        check_a_started_section_nobody_measured_is_seeded_by_the_intake),
    "the estimate leaves the second default line unpriced": (
        ESTIMATE, MODEL, _FOLLOWERS, "      return;",
        check_a_floor_typed_into_a_started_section_nobody_measured_is_priced),
    "a second area gets no copy of the lines": (
        INTAKE, MODEL, "    carrier.floor_area = tag;", "    void tag;",
        check_a_started_section_nobody_measured_is_seeded_by_the_intake),
    "the page paints no box": (
        INTAKE, INTAKE_JS, "      if (box && shown !== null) box.value = shown;", "      if (false) box.value = shown;",
        check_an_epoxy_job_boxes_mirror_the_epoxy_section),
    "a box nobody typed in writes": (
        INTAKE, INTAKE_JS, "      return box && box.sfTyped && v > 0 ? [name, v] : null;", "      return box && v > 0 ? [name, v] : null;",
        check_a_box_nobody_typed_in_never_writes_and_a_mark_lasts_one_save),
    "a typed mark outlives its save": (
        INTAKE, INTAKE_JS, "      if (box) box.sfTyped = false;", "      void box;",
        check_a_box_nobody_typed_in_never_writes_and_a_mark_lasts_one_save),
    "only the Polish boxes are marked as typed": (
        INTAKE, INTAKE_JS, "        if (T.fieldHome(e.target.name)) e.target.sfTyped = true;",
        '        if (e.target.name === "polish_sf" || e.target.name === "polish_2_sf") e.target.sfTyped = true;',
        check_typing_system_1_changes_the_epoxy_area_and_nothing_else),
    "a zero or blank box is written to the draft over the takeoff's figure": (
        INTAKE, INTAKE_JS, "        else delete values[name];", "        else void 0;",
        check_typing_zero_or_nothing_deletes_and_writes_nothing),
    "the draft keeps the old figure after a typed one reached the takeoff": (
        INTAKE, INTAKE_JS, "        if (written) Object.assign(values, Object.fromEntries([[name, now]]));",
        "        if (false) Object.assign(values, Object.fromEntries([[name, now]]));",
        check_typing_system_1_changes_the_epoxy_area_and_nothing_else),
    "a pending save is not flushed before the repaint": (
        INTAKE, INTAKE_JS, "        if (saveTimer) save();", "        void saveTimer;",
        check_a_figure_typed_and_tabbed_away_inside_the_save_delay_survives),
    "the note about areas 3 and on is never shown": (
        INTAKE, INTAKE_JS, "    var extra = M ? B.boxExtras(M)[0] : null;", "    var extra = null;",
        check_a_third_area_is_left_alone_with_a_note_and_a_link),
    # the estimate page
    "the estimate page asks the Polish root only": (
        ESTIMATE, PAGE, "    if (B.snapshotBehind(ROOT, state)) saveSoon();",
        "    if (activeTab === B.ROOT_TAB && B.snapshotBehind(ROOT, state)) saveSoon();",
        check_an_epoxy_floor_typed_on_the_intake_reaches_the_estimate_and_its_snapshot),
    "the estimate page never reprices on open": (
        ESTIMATE, PAGE, "    if (B.snapshotBehind(ROOT, state)) saveSoon();", "    if (false) saveSoon();",
        check_a_polish_bid_still_reprices_on_open),
    "another section's snapshot is never read": (
        ESTIMATE, MODEL, "      var held = priced.filter(function (x) { return isObject(x) && x.id === e.tab; })[0];",
        "      var held = null;", check_a_cove_length_typed_on_the_intake_reprices_the_epoxy_snapshot),
    "a missing snapshot reads as behind": (
        ESTIMATE, MODEL, "      if (!held || !isObject(held.sf)) return false;", "      if (!held || !isObject(held.sf)) return true;",
        check_the_snapshot_check_reads_a_gyp_section_too),
    "the root's snapshot is never read": (
        ESTIMATE, MODEL, "        return tk > 0 && (tk !== num(state.polish_sf) || (snapSf > 0 && snapSf !== tk));",
        "        return false;", check_a_combo_bid_is_checked_for_each_section),
    "a bid that agrees is saved again": (
        ESTIMATE, MODEL, "      return Object.keys(now).some(function (k) { return has.call(held.sf, k) && num(held.sf[k]) !== now[k]; });",
        "      return true;", check_reopening_a_bid_that_agrees_writes_nothing),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    """One line of one file is broken in a scratch copy, the harness runs on it, and the named check has to
    fail on what it answers. The harness runs OUTSIDE the raises block, so a break that merely crashes it is an
    error and not a pass, and break_source refuses an anchor that is not there exactly once."""
    require_node()
    harness, rel, old, new, check = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, FILES)
    # the intake prelude reads the county table out of the backend module that serves it
    (tmp_path / "backend").mkdir(exist_ok=True)
    shutil.copyfile(BACKEND / "reference_tax.py", tmp_path / "backend" / "reference_tax.py")
    broken = _run(harness, frontend)
    with pytest.raises(AssertionError):
        check(broken)


def test_every_check_is_named_by_a_break():
    named = {check for *_, check in BREAKS.values()}
    for check in INTAKE_CHECKS + ESTIMATE_CHECKS:
        assert check in named, "no break turns %s red" % check.__name__


def test_the_harness_ran_each_job_type_it_claims():
    """The intake harness opens Epoxy, Gyp, Combo and Polish bids: a scenario that quietly stopped running would
    leave its check asserting on nothing."""
    require_node()
    ran = _run(INTAKE)
    for key in ("sys1", "gyp", "comboBoth", "polish", "offRoot", "unmeasured", "started", "blurRace", "direct"):
        assert key in ran, key
