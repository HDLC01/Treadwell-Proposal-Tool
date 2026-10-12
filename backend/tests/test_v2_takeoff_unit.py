"""A v2 takeoff row's Unit comes from Items & Assemblies, not from a dropdown.

Hanz, 2026-10-12, looking at the Takeoff step's material rows (a free Unit dropdown with the hint
"SF or LF."): "Unit should be pulled from the items and assemblies tab".

THE RULE.
  * An ASSEMBLY row's unit is the assembly's own `unit` (SF or LF, set on Items & Assemblies).
  * A MATERIAL row's unit is the material's COVERAGE BASIS (`coverage_basis`: "sf" or "lf"). NEVER
    `item.unit`, which is the unit it is BOUGHT in (Gallon, Kit, Pail) and says nothing about how a
    floor is measured. "each" is a count, which a takeoff cannot price (it measures SF and LF only),
    so it prices as SF and the row says so.
  * The control is read-only text with the line "From Items & Assemblies.", linking to the page that
    sets it. Not set in the library: "SF" and "Not set in Items & Assemblies, so SF." Nothing picked
    yet: a dash.
  * The row's `unit` follows the library when the PICK changes (the row's own search, the add-line
    pop-up, a default seeded into a new bid). A SAVED row whose unit differs from the library's keeps
    its saved unit and says "Saved as LF; Items & Assemblies now says SF." Nothing is repriced
    behind the estimator's back.

EXECUTED, NOT READ. js/takeoff-unit-harness.js runs the whole estimate page (js/polish-estimate.js)
on the shared DOM stub, with the real bid-model.js, library-core.js and library-picker.js beneath
it. Every check below is a plain function of what the harness answered, and BREAKS at the bottom
breaks one line of one file in a scratch copy, runs the harness on that, and requires the named check
to fail. The last tests require every check to be named there and every part of the rule to have a
break that turns it red.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "takeoff-unit-harness.js"

# What the page harness reads out of a frontend directory, so a scratch copy that breaks one file can
# be completed with the rest.
FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/library-core.js",
         "js/work-types.js", "js/polish-sandbox.js", "js/library-picker.js", "js/epoxy-takeoff.js"]

DASH = "—"
FROM_LIB = "From Items & Assemblies."
NOT_SET = "Not set in Items & Assemblies, so SF."
EACH = "Items & Assemblies says Each, which a takeoff prices as SF."

# id -> (the unit the row must take, the line under it)
EXPECTED = {
    "u-sf": ("SF", FROM_LIB),
    "u-lf": ("LF", FROM_LIB),          # bought by the Gal, measured per LF
    "u-none": ("SF", NOT_SET),
    "u-each": ("SF", EACH),
    "x-lf": ("LF", FROM_LIB),
    "x-sf": ("SF", FROM_LIB),
    "x-none": ("SF", NOT_SET),
}


def _run(frontend=FRONTEND):
    require_node()
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, (
        "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr)
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _run()


# ── the checks: plain functions of what a harness answered ───────────────────
def _faces_match(path, got):
    for key, (unit, hint) in EXPECTED.items():
        f = got[key]
        assert f["model"] == unit, "%s %s: the row's unit is %r, the library says %r" % (path, key, f["model"], unit)
        assert f["text"] == unit, "%s %s: the Unit box shows %r, not %r" % (path, key, f["text"], unit)
        assert f["hint"] == hint, "%s %s: the line under the box says %r, not %r" % (path, key, f["hint"], hint)
        assert f["note"] is False, "%s %s: an ordinary row drew the saved-bid note" % (path, key)


def check_the_row_search_takes_the_unit_from_the_library(a):
    """A material takes its COVERAGE BASIS (bought by the Gal, measured per LF is LF), an assembly its own unit."""
    _faces_match("search", a["search"])


def check_the_add_line_pop_up_sets_the_same_unit(a):
    """The pop-up and the row's own search go through the same resolve, so they agree on every case."""
    _faces_match("popup", a["popup"])
    assert a["popup"] == a["search"], "the pop-up and the search disagree about a row's unit"


def check_a_material_never_takes_its_purchase_unit(a):
    """Every material in the fixture is bought in Gal. If the row ever read item.unit, no row here
    could be LF and the unset ones could not be SF by the library's rule."""
    assert a["search"]["u-lf"]["text"] == "LF", "a material measured per LF did not become LF"
    for key in ("u-sf", "u-lf", "u-none", "u-each"):
        assert a["search"][key]["text"] in ("SF", "LF"), "a material row shows %r" % a["search"][key]["text"]


def check_an_lf_material_prices_per_lf(a):
    lf, sf = a["pricedPerLf"], a["pricedPerSf"]
    assert lf["unit"] == "LF" and lf["lf"] == 200 and lf["sf"] == 0, (
        "an LF material measured at 200 is 200 LF of takeoff and no SF: %r" % lf)
    assert lf["perUnit"].endswith("/ LF"), "the per-unit line does not say LF: %r" % lf["perUnit"]
    assert sf["unit"] == "SF" and sf["sf"] == 200 and sf["lf"] == 0, sf
    assert sf["perUnit"].endswith("/ SF"), sf["perUnit"]
    assert lf["cost"] and lf["cost"] != "—", "the LF row did not price"


def check_nothing_picked_shows_a_dash(a):
    assert a["noPick"]["text"] == DASH, "a row with no pick shows %r" % a["noPick"]["text"]
    assert a["noPick"]["hint"] == FROM_LIB


def check_the_control_is_not_editable(a):
    c = a["control"]
    assert c["selects"] == 0, "the takeoff row still has a dropdown"
    assert c["unitInputs"] == 0, "the takeoff row still has an editable unit field"
    assert c["tag"] == "div", "the Unit box is %r, not read-only text" % c["tag"]
    assert c["unitAfterStrayChange"] == "LF", "a change event aimed at the unit moved the row"


def check_the_hint_links_to_items_and_assemblies(a):
    for key, f in a["search"].items():
        assert f["href"] == "/library.html", "%s: the hint does not link to Items & Assemblies" % key


def check_a_saved_row_keeps_its_unit_and_says_so(a):
    s = a["saved"]
    # saved SF, library LF (material and assembly); saved SF, library SF; saved LF, library SF; saved LF, unset
    assert s["modelUnits"] == ["SF", "SF", "SF", "LF", "LF"], (
        "opening a saved bid changed a row's unit: %r" % s["modelUnits"])
    notes = [(f["text"], f["hint"], f["note"]) for f in s["rows"]]
    assert notes[0] == ("SF", "Saved as SF; Items & Assemblies now says LF.", True), notes[0]
    assert notes[1] == ("SF", "Saved as SF; Items & Assemblies now says LF.", True), notes[1]
    assert notes[2] == ("SF", FROM_LIB, False), "a saved row that matches the library drew a note: %r" % (notes[2],)
    assert notes[3] == ("LF", "Saved as LF; Items & Assemblies now says SF.", True), notes[3]
    assert notes[4][0] == "LF" and notes[4][1].startswith("Saved as LF;") and notes[4][2] is True, notes[4]


def check_retyping_a_saved_row_does_not_restamp_it_but_a_new_pick_follows_the_library(a):
    s = a["saved"]
    assert s["afterRetype"] == "SF", "re-typing the same name re-stamped a saved row's unit"
    assert s["afterNewPick"]["model"] == "LF" and s["afterNewPick"]["text"] == "LF", (
        "a genuinely new pick did not take the library's unit: %r" % s["afterNewPick"])
    assert s["afterNewPick"]["note"] is False


def check_a_new_bids_default_materials_take_their_coverage_basis(a):
    got = {r["id"]: r for r in a["seeded"]}
    assert got["u-lf"]["unit"] == "LF" and got["u-lf"]["measurement"] == "", (
        "an LF default is measured with square feet, or took the wrong unit: %r" % got["u-lf"])
    assert got["u-sf"]["unit"] == "SF" and got["u-sf"]["measurement"] == 5000
    assert got["u-none"]["unit"] == "SF" and got["u-each"]["unit"] == "SF"


def check_two_library_rows_of_one_name_each_get_their_own_unit(a):
    got = {r["id"]: r["unit"] for r in a["twins"]}
    assert got == {"u-t1": "SF", "u-t2": "LF", "x-t1": "SF", "x-t2": "LF"}, got


def check_changing_the_pick_repaints_the_unit_in_place(a):
    r = a["repick"]
    assert (r["first"]["text"], r["first"]["model"]) == ("LF", "LF")
    assert r["same"] == r["first"], "re-typing the same pick changed the row"
    assert (r["second"]["text"], r["second"]["model"]) == ("SF", "SF"), (
        "the Unit box did not follow a changed material pick: %r" % r["second"])
    assert (r["third"]["text"], r["third"]["model"]) == ("LF", "LF"), (
        "the Unit box did not follow a changed assembly pick: %r" % r["third"])


def check_a_repick_never_turns_a_measurement_into_another_units_number(a):
    r = a["repickMeasured"]
    c = r["carrier"]
    assert c["row"]["unit"] == "LF" and c["row"]["measurement"] == "", (
        "a 5000 SF floor re-picked to an LF material kept its digits as LF: %r" % c["row"])
    assert c["sums"] == {"sf": 0, "lf": 0}, "the floor's number came back as cove: %r" % c["sums"]
    assert c["box"] == "", "the model was cleared but the measurement box still shows %r" % c["box"]
    assert c["follower"]["measurement"] == "", "a same-floor row still holds the floor the carrier lost"
    lone = r["lone"]
    assert lone["row"]["unit"] == "LF" and lone["row"]["measurement"] == "" and "same_floor" not in lone["row"], (
        "a same-floor row re-picked to LF kept a number nothing counts: %r" % lone["row"])
    assert lone["carrier"]["measurement"] == 5000 and lone["sums"] == {"sf": 5000, "lf": 0}, (
        "re-picking the follower disturbed the floor: %r" % lone)
    assert lone["box"] == ""
    # nothing to clear when the unit does not move, or when the row was never on a unit of its own
    assert r["sameUnit"]["row"]["measurement"] == 5000 and r["sameUnit"]["sums"]["sf"] == 5000, (
        "a re-pick to a material of the same unit lost the measurement: %r" % r["sameUnit"])
    assert r["firstPick"]["row"]["measurement"] == 200 and r["firstPick"]["sums"]["sf"] == 200, (
        "the first pick on a row that already had a number lost it: %r" % r["firstPick"])
    asm = r["asmRepick"]
    assert asm["row"]["unit"] == "LF" and asm["row"]["measurement"] == "" and asm["box"] == "" and asm["sums"]["lf"] == 0, (
        "an assembly re-pick turned 300 SF into LF: %r" % asm)


def check_leaving_a_pop_up_added_row_keeps_the_library_row_that_was_ticked(a):
    t = a["twinBlur"]
    assert t["itemId"] == "u-t2" and t["asmId"] == "x-t2", (
        "leaving the field re-resolved the name to the first twin: %r" % ((t["itemId"], t["asmId"]),))
    for key in ("item", "asm"):
        assert t[key] == t["before"][key], "leaving the field changed the %s row's unit or note: %r" % (key, t[key])
        assert t[key]["text"] == "LF" and t[key]["note"] is False


def check_a_saved_row_with_no_usable_unit_says_so_and_retyping_fixes_it(a):
    for key, got in a["noUnit"].items():
        o = got["opened"]
        assert o["text"] == DASH and o["note"] is True and o["hint"].startswith("No unit is saved on this row"), (
            "%s: the box says %r over a row the totals ignore: %r" % (key, o["text"], o))
        assert got["openedSums"] == {"sf": 0, "lf": 0}, "%s: %r" % (key, got["openedSums"])
        assert got["retyped"]["text"] == "LF" and got["retyped"]["model"] == "LF" and got["retyped"]["note"] is False, (
            "%s: retyping the name did not set the library's unit: %r" % (key, got["retyped"]))
        assert got["measurement"] == 200 and got["retypedSums"] == {"sf": 0, "lf": 200}, (
            "%s: the row's number was lost or not counted: %r" % (key, got))


CHECKS = [
    check_the_row_search_takes_the_unit_from_the_library,
    check_the_add_line_pop_up_sets_the_same_unit,
    check_a_material_never_takes_its_purchase_unit,
    check_an_lf_material_prices_per_lf,
    check_nothing_picked_shows_a_dash,
    check_the_control_is_not_editable,
    check_the_hint_links_to_items_and_assemblies,
    check_a_saved_row_keeps_its_unit_and_says_so,
    check_retyping_a_saved_row_does_not_restamp_it_but_a_new_pick_follows_the_library,
    check_a_new_bids_default_materials_take_their_coverage_basis,
    check_two_library_rows_of_one_name_each_get_their_own_unit,
    check_changing_the_pick_repaints_the_unit_in_place,
    check_a_repick_never_turns_a_measurement_into_another_units_number,
    check_leaving_a_pop_up_added_row_keeps_the_library_row_that_was_ticked,
    check_a_saved_row_with_no_usable_unit_says_so_and_retyping_fixes_it,
]


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_the_page_does_what_the_rule_says(ran, check):
    check(ran)


# ── RED WITHOUT THE CHANGE ───────────────────────────────────────────────────
PAGE = "js/polish-estimate.js"
MODEL = "js/bid-model.js"

BREAKS = {
    "a material reads item.unit, the pack it is bought in, not its coverage basis": (
        MODEL, '    var word = kind === "asm" ? lib.unit : lib.coverage_basis;',
        "    var word = lib.unit;", check_a_material_never_takes_its_purchase_unit),
    "a material is read as SF whatever its basis says": (
        MODEL, '    var word = kind === "asm" ? lib.unit : lib.coverage_basis;',
        '    var word = kind === "asm" ? lib.unit : "sf";', check_the_row_search_takes_the_unit_from_the_library),
    "picking a material adopts nothing": (
        PAGE, "    if (hit && (row.item_id !== before || !B.validTakeoffUnit(row.unit))) {",
        "    if (false) {", check_the_row_search_takes_the_unit_from_the_library),
    "picking an assembly adopts nothing": (
        PAGE, '      B.adoptTakeoffUnit(M.takeoff, i, B.takeoffUnit("asm", asm).unit);',
        "      row.unit = row.unit;", check_the_row_search_takes_the_unit_from_the_library),
    "an LF material stays an SF row, so it is priced and counted as area": (
        PAGE, "    if (hit && (row.item_id !== before || !B.validTakeoffUnit(row.unit))) {",
        "    if (false) {", check_an_lf_material_prices_per_lf),
    "a pick re-stamps the unit on every keystroke": (
        PAGE, "    if (hit && (row.item_id !== before || !B.validTakeoffUnit(row.unit))) {",
        "    if (hit) {", check_retyping_a_saved_row_does_not_restamp_it_but_a_new_pick_follows_the_library),
    "the Unit box is a dropdown again": (
        PAGE, "      '<div class=\"costbox txt\" data-unit-for=\"' + i + '\">' + esc(unitView(r).text) + '</div>' +",
        "      '<select class=\"costbox txt\" data-tk=\"' + i + '\" data-k=\"unit\" data-unit-for=\"' + i + '\">' + "
        "esc(unitView(r).text) + '</select>' +",
        check_the_control_is_not_editable),
    "the box shows the library's unit over a saved row's own": (
        MODEL, "    if (saved === lu.unit) return { text: saved, hint: ordinary, note: false };",
        "    return { text: lu.unit, hint: ordinary, note: false };", check_a_saved_row_keeps_its_unit_and_says_so),
    "a saved row that differs says nothing": (
        MODEL, '    return { text: saved, hint: "Saved as " + saved + "; " + now, note: true };',
        "    return { text: saved, hint: ordinary, note: false };", check_a_saved_row_keeps_its_unit_and_says_so),
    "the pop-up sets its own unit and not the one the row's search would": (
        PAGE, '      if (ticked) row.unit = B.takeoffUnit("asm", ticked).unit;',
        '      if (ticked) row.unit = "SF";', check_the_add_line_pop_up_sets_the_same_unit),
    "the pop-up takes the first of two same-named assemblies' unit": (
        PAGE, '      if (ticked) row.unit = B.takeoffUnit("asm", ticked).unit;',
        "      if (false) row.unit = null;", check_two_library_rows_of_one_name_each_get_their_own_unit),
    "the pop-up takes the first of two same-named materials' unit": (
        PAGE, '      if (tickedItem) { row.unit = B.takeoffUnit("item", tickedItem).unit; paintUnits(); }',
        "      if (false) { paintUnits(); }", check_two_library_rows_of_one_name_each_get_their_own_unit),
    "a default material is always seeded as SF": (
        MODEL, '      var unit = takeoffUnit(p.kind, p.row).unit;',
        '      var unit = p.kind === "asm" ? takeoffUnit(p.kind, p.row).unit : "SF";',
        check_a_new_bids_default_materials_take_their_coverage_basis),
    "Each is read as unset": (
        MODEL, '    if (kind !== "asm" && word === "EACH") return { unit: "SF", state: "each" };',
        '    if (false) return { unit: "SF", state: "each" };', check_the_row_search_takes_the_unit_from_the_library),
    "the Unit box never repaints": (
        PAGE, '      el.textContent = unitView(M.takeoff[parseInt(el.getAttribute("data-unit-for"), 10)]).text;',
        "      el.textContent = el.textContent;", check_changing_the_pick_repaints_the_unit_in_place),
    "the hint is not a link": (
        PAGE, "    return '<a class=\"hint unithint' + (v.note ? ' note' : '') + '\" href=\"/library.html\" ' +",
        "    return '<a class=\"hint unithint' + (v.note ? ' note' : '') + '\" href=\"/\" ' +",
        check_the_hint_links_to_items_and_assemblies),
    "a re-pick keeps the old unit's digits under the new unit": (
        MODEL, '    if (held && validTakeoffUnit(r.unit)) setMeasurement(rows, i, "");',
        "    if (false) setMeasurement(rows, i, \"\");", check_a_repick_never_turns_a_measurement_into_another_units_number),
    "a same-floor row keeps its marker when it changes unit": (
        MODEL, "    delete r.same_floor;",
        "    r.same_floor = r.same_floor;", check_a_saved_row_with_no_usable_unit_says_so_and_retyping_fixes_it),
    "the measurement box is not told it was cleared": (
        PAGE, "      if (String(box.value) !== want) box.value = want;",
        "      if (false) box.value = want;", check_a_repick_never_turns_a_measurement_into_another_units_number),
    "a material is re-resolved by name on every blur": (
        PAGE, "      hit = cur;", "      hit = hit;", check_leaving_a_pop_up_added_row_keeps_the_library_row_that_was_ticked),
    "an assembly is re-resolved by name on every blur": (
        PAGE, "      asm = cur;", "      asm = asm;", check_leaving_a_pop_up_added_row_keeps_the_library_row_that_was_ticked),
    "a row with no usable unit shows the library's unit": (
        MODEL, "    if (!validTakeoffUnit(saved)) {", "    if (false) {", check_a_saved_row_with_no_usable_unit_says_so_and_retyping_fixes_it),
    "retyping the name does not repair a row with no usable unit": (
        PAGE, "    if (hit && (row.item_id !== before || !B.validTakeoffUnit(row.unit))) {",
        "    if (hit && row.item_id !== before) {", check_a_saved_row_with_no_usable_unit_says_so_and_retyping_fixes_it),
    "an empty row shows SF instead of a dash": (
        MODEL, '    if (!lu) return { text: "' + DASH + '", hint: "From Items & Assemblies.", note: false };',
        '    if (!lu) return { text: "SF", hint: "From Items & Assemblies.", note: false };',
        check_nothing_picked_shows_a_dash),
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
