"""Item categories on screen: the Admin card, the Items tab's Category column, and the v2 estimate's Material step.

Hanz, 2026-10-27: categories are set on the Admin page per work type, each material picks one per work type it
is used in, and "we also need to separate these categories in the Estimates": the Material step draws its rows
under the headings in the Admin order, each with a subtotal, and "Other" last.

PROVEN BY EXECUTION, never by reading the source:
  * tests/js/item-categories-harness.js lifts the Admin card's two functions out of js/admin.js and runs them,
    then boots js/polish-estimate.js whole (through polish-estimate-harness.js's boot code) with
    GET /api/library/items carrying the categories the way main.py answers it, and reads the headings, the cards
    under them and the subtotals back off the panel the page drew. The same bids are booted with and without
    categories, on the harness's Polish job and on the Epoxy job priced off the library the seed plans from
    Kyle's workbook, and the totals and every save are compared.
  * tests/js/library-ui-harness.js renders the real Items row and drives the real onItemEdit and facets.

The mutation tests at the bottom break a scratch copy of the page and prove the check it belongs to goes red.
"""
from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

import item_categories as ic

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "item-categories-harness.js"
LIBRARY_HARNESS = TESTS / "js" / "library-ui-harness.js"


def _run(frontend=FRONTEND, tmp=None, harness=HARNESS):
    args = [frontend] + ([plan_json(tmp)] if tmp is not None and harness == HARNESS else [])
    proc = run_node(harness, *args)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return _run(tmp=tmp_path_factory.mktemp("cats"))


@pytest.fixture(scope="module")
def lib_out():
    require_node()
    return _run(harness=LIBRARY_HARNESS)


@pytest.fixture(scope="module")
def lib(lib_out):
    return lib_out["categoryColumn"]


# ── the Admin card ───────────────────────────────────────────────────────────
def test_the_card_draws_every_work_type_in_hanzs_order_with_the_sheets_headings(ran):
    a = ran["admin"]
    assert a["blocks"] == ["epoxy", "polish", "gyp", "seal", "leveling"]
    assert a["epoxy"] == ["Patch", "Epoxy Liquids", "Extras", "Cove"]
    assert a["polish"] == ["Patch", "Floor", "Dye", "Joint Filler"]
    assert a["gyp"] == [] and a["emptyWtSays"], "a work type with none says what that means"
    assert a["addBoxes"] == 5, "every work type has its own Add box"
    assert a["firstUpDisabled"] and a["lastDownDisabled"]
    assert a["saysSeeded"] and a["status"] and a["escapes"]


def test_the_card_says_removing_a_category_leaves_its_materials_uncategorized(ran):
    assert ran["admin"]["saysUncategorized"]


def test_the_card_says_which_headings_are_fed_by_fixed_lines_rather_than_rows(ran):
    """Epoxy's patch is a flat charge in the caption, and Polish's Joint Filler and Dye are condition cards."""
    assert ran["admin"]["saysFixedLines"]


def test_a_card_whose_store_did_not_load_says_so(ran):
    assert "didn't load" in ran["admin"]["failed"] and "data-ic-act" not in ran["admin"]["failed"]


def test_each_edit_sends_the_whole_set_with_ids_kept(ran):
    a = ran["admin"]
    names = lambda m, wt: [c["name"] for c in m[wt]]
    ids = lambda m, wt: [c.get("id") for c in m[wt]]
    assert a["add"]["gyp"] == [{"name": "Bags"}], "a new heading is trimmed and goes without an id (the server mints it)"
    assert names(a["add"], "epoxy") == ["Patch", "Epoxy Liquids", "Extras", "Cove"], "the other lists ride along"
    assert names(a["rename"], "epoxy")[0] == "Patch and Prep" and ids(a["rename"], "epoxy")[0] == "epoxy-patch", (
        "a rename keeps the id, which is how every material in it follows the new name")
    assert "polish-dye" not in ids(a["remove"], "polish") and len(a["remove"]["polish"]) == 3
    assert ids(a["up"], "epoxy") == ["epoxy-patch", "epoxy-liquids", "epoxy-cove", "epoxy-extras"]
    assert ids(a["down"], "polish")[:2] == ["polish-floor", "polish-patch"]
    for no_op in ("addDup", "addBlank", "renameDup", "upAtTop", "unknown"):
        assert a[no_op] is None, no_op + " should change nothing"
    assert a["storeUntouched"], "an edit changed the store the card was drawn from"


# ── the Items tab ────────────────────────────────────────────────────────────
def test_the_category_cell_offers_one_select_per_division_the_material_is_in(lib):
    c = lib["cells"]
    assert c["c1"]["selects"] == ["epoxy"] and c["c1"]["epoxy"] == "epoxy-patch" and not c["c1"]["labelled"]
    assert c["c2"]["selects"] == ["polish"] and c["c2"]["polish"] == ""
    assert c["c3"]["selects"] == ["epoxy", "polish"] and c["c3"]["labelled"], "two divisions, each labelled"
    assert (c["c3"]["epoxy"], c["c3"]["polish"]) == ("epoxy-extras", "polish-floor")
    assert c["c6"]["selects"] == [], "a Defaults-tab work type is not a division: it offers no select"
    assert c["c5"]["selects"] == [], "a material in no division is offered nothing"
    assert lib["epoxyOptions"] == ["", "epoxy-patch", "epoxy-liquids", "epoxy-extras", "epoxy-cove"], (
        "the work type's headings, in the Admin order, after None")


def test_a_removed_heading_reads_as_none(lib):
    assert lib["cells"]["c4"]["epoxy"] == ""


def test_with_no_categories_loaded_the_cell_says_so_and_offers_nothing(lib):
    assert lib["bare"] == {"selects": [], "noneSetUp": True}


def test_a_database_without_the_column_offers_no_select(lib):
    """GET /api/library/items' categories_writable false: a pick there could not be saved."""
    assert lib["noColumn"] == {"selects": [], "says": True}


def test_a_pick_the_database_refuses_is_dropped_so_the_material_still_saves(lib_out):
    """update_item's 400 for a missing column. Requeued, the pick rode every later edit of the row and failed
    each one (None too: {} is stored as NULL, which still names the column) until a reload."""
    r = lib_out["categoryRefused"]
    a = r["alone"]
    assert a["pending"] == 0 and a["marked"] is False and a["stillUnsaved"] is False, (
        "the refused pick was requeued, so the row stays unsaved")
    assert a["writable"] is False and a["model"] == {}, "the selects stay on offer, or the pick still shows"
    assert "item_categories.sql" in a["said"], "the estimator is told why"
    assert a["nextSaved"] and "material_categories" not in a["nextBody"], "the next edit carried the pick again"
    m = r["mixed"]
    assert m["pending"] == 1 and m["marked"], "the cost typed with it was lost"
    assert '"unit_cost"' in m["resentBody"] and "material_categories" not in m["resentBody"]
    assert m["thenClean"]
    o = r["other"]
    assert o["pending"] == 1 and o["writable"] is True and o["model"] == {"epoxy": "epoxy-patch"}, (
        "any other failure is requeued as before")
    assert r["noErrors"]


def test_choosing_a_category_queues_the_whole_map_as_a_new_object(lib):
    e = lib["edit"]
    assert e["afterAdd"] == {"kind": "items", "id": "c3",
                             "body": {"material_categories": {"epoxy": "epoxy-extras", "polish": "polish-dye"}}}
    assert e["modelAfterAdd"] == {"epoxy": "epoxy-extras", "polish": "polish-dye"}
    assert e["afterClear"]["body"] == {"material_categories": {"polish": "polish-dye"}}, "None takes the work type out"
    assert e["snapshotUntouched"], "the map was written into, so a Cancel could not put the old one back"


def test_the_category_facet_filters_like_the_others(lib):
    assert lib["patch"]["shown"] == ["c1"] and lib["patch"]["active"]
    assert lib["patch"]["summary"] == "in the Patch category"
    assert lib["floor"]["shown"] == ["c3"], "case does not matter"
    assert lib["none"]["shown"] == ["c2", "c4", "c5", "c6"] and lib["none"]["summary"] == "with no category"
    assert lib["off"]["shown"] == ["c1", "c2", "c3", "c4", "c5", "c6"] and not lib["off"]["active"]
    assert lib["barOptions"] == ["", "Patch", "Epoxy Liquids", "Extras", "Cove", "Floor", "Dye", "Joint Filler",
                                 lib["NONE"]], "every name once, in the Admin order"
    assert lib["patch"]["barValue"] == "Patch"


# ── category follows division (Hanz, 2026-10-29) ─────────────────────────────
# "Category and Division should always be tied together. How is it that Paint Blie has Epoxy and Polish in the
# categories but is not selected in the divisions?"
def test_a_material_in_no_division_says_to_pick_one_and_offers_no_select(lib):
    t = lib["tied"]["before"]
    assert t["t1"] == {"selects": [], "pickDivision": True, "noneSetUp": False}, (
        "Paint Blie: no division ticked, so no Epoxy or Polish select, whatever categories it holds")
    assert t["t5"]["selects"] == [] and t["t5"]["pickDivision"], "Defaults-tab work types do not widen the pickers"
    assert t["t6"]["selects"] == ["epoxy"], "a Defaults-tab Polish on an Epoxy material offers no Polish select"


def test_only_the_ticked_divisions_get_a_select(lib):
    t = lib["tied"]["before"]
    assert t["t2"]["selects"] == ["epoxy"] and t["t2"]["epoxy"] == "epoxy-patch", (
        "a category the material holds for a division it is not in offers no select")
    assert t["t3"] == {"selects": [], "pickDivision": False, "noneSetUp": True}, (
        "a division whose work type has no categories set up shows no select for it")
    assert t["t4"]["selects"] == ["epoxy", "polish"]


def test_unticking_a_division_takes_its_category_out_in_the_same_save(lib):
    u = lib["tied"]["afterUntick"]
    assert u["body"] == {"kind": "items", "id": "t4",
                         "body": {"divisions": ["Epoxy"], "material_categories": {"epoxy": "epoxy-extras"}}}
    assert u["model"] == {"epoxy": "epoxy-extras"} and u["cell"]["selects"] == ["epoxy"]
    assert u["snapshotUntouched"], "the map was written into, so a Cancel could not put the old one back"
    off = lib["tied"]["afterAllOff"]
    assert off["epoxyOff"]["body"] == {"divisions": ["Polished Concrete"], "material_categories": {}}
    assert off["body"]["body"] == {"divisions": []}, "nothing left to take out: the map is not re-sent"
    assert off["cell"] == {"selects": [], "pickDivision": True, "noneSetUp": False}


def test_ticking_a_division_brings_its_select_back_at_none(lib):
    r = lib["tied"]["afterRetick"]
    assert r["body"]["body"] == {"divisions": ["Polished Concrete", "Epoxy"]}, "a tick takes nothing out"
    assert r["cell"]["selects"] == ["epoxy", "polish"] and r["cell"]["polish"] == ""
    t1 = lib["tied"]["afterTickT1"]
    assert t1["body"]["body"] == {"divisions": ["Epoxy"], "material_categories": {"epoxy": "epoxy-patch"}}, (
        "Paint Blie's first tick keeps the Epoxy category and drops the Polish one it had no division for")
    assert t1["cell"]["selects"] == ["epoxy"] and t1["cell"]["epoxy"] == "epoxy-patch"


def test_the_page_and_the_server_read_a_division_as_the_same_work_type(lib):
    pairs = lib["tied"]["divisionWorkTypes"]
    assert len(pairs) > 5 and any(wt == "" for _, wt in pairs) and any(wt == "seal" for _, wt in pairs)
    assert [[n, ic.division_work_type(n)] for n, _ in pairs] == pairs


# ── the Material step ────────────────────────────────────────────────────────
def test_the_rows_are_grouped_under_the_headings_in_the_admin_order_with_other_last(ran):
    g = ran["grouped"]
    assert [(x["name"], x["cards"]) for x in g["groups"]] == [
        ("Patch", [3]), ("Floor", [0, 2]), ("Dye", []), ("Joint Filler", []), ("Other", [1])], (
        "a material under its own heading, two assemblies whose category names a heading (case and spacing "
        "ignored), the Dye and Joint Filler cards under theirs, and an assembly whose category is another work "
        "type's under Other")
    assert [x["conds"] for x in g["groups"]] == [[], [], ["dye"], ["joint_filler", "remove_existing_jf"], []]
    assert sorted(g["cards"]) == list(range(g["rows"])), "every row is drawn exactly once"
    assert sorted(g["conds"]) == ["dye", "joint_filler", "remove_existing_jf"], "every condition card drawn once"
    assert g["matTotalStill"], "the Material total line is still there"


def test_the_condition_cards_sit_under_their_heading_and_count_in_its_subtotal(ran):
    """Drawn after the groups, Joint Filler and Dye sat under the last heading (Other) with no heading of their
    own and outside its subtotal, and Polish's seeded Dye and Joint Filler headings never appeared."""
    c = ran["condCards"]
    by = {x["name"]: x for x in c["groups"]}
    assert [x["name"] for x in c["groups"]] == ["Patch", "Floor", "Dye", "Joint Filler", "Other"]
    assert by["Dye"]["conds"] == ["dye"] and by["Dye"]["shown"] == c["dye"] > 0
    assert by["Joint Filler"]["conds"] == ["joint_filler", "remove_existing_jf"], "Remove Existing follows Joint Filler"
    assert by["Joint Filler"]["shown"] == c["jf"] > 0
    assert by["Other"]["conds"] == [] and by["Other"]["shown"] == pytest.approx(398.79), "Other holds only its row"
    for x in c["groups"]:
        assert x["shown"] == pytest.approx(x["byCards"], abs=0.011), "a heading's subtotal is what is drawn under it"
    assert c["repaint"]["rebuilt"] is False and c["repaint"]["shown"] == c["repaint"]["card"], (
        "a typed measurement moves the condition card and its heading together, in place")


def test_a_reserved_material_filed_on_the_items_tab_takes_its_card_with_it(ran):
    d = ran["condCards"]["dyeFiled"]
    by = {x["name"]: x for x in d["groups"]}
    assert "Dye" not in by and by["Patch"]["conds"] == ["dye"]
    assert by["Patch"]["shown"] == pytest.approx(400 + d["dye"], abs=0.011)


def test_an_assembly_with_no_scope_heading_sits_under_the_one_its_materials_agree_on(ran):
    """The seeded library's Scope is the division ("Epoxy", "Polished Concrete"), which names no heading."""
    assert ran["derived"] == [["Patch", [2, 3]], ["Floor", [0]], ["Other", [1]]]
    assert ran["derivedSplit"] == [["Patch", [2, 3]], ["Other", [0, 1]]], "two headings between them is none"


def test_each_heading_shows_the_subtotal_of_the_rows_under_it(ran):
    for x in ran["grouped"]["groups"]:
        assert x["shown"] == pytest.approx(x["byCards"], abs=0.011), x
        assert x["shown"] == pytest.approx(x["byHand"], abs=0.006), x
    assert ran["grouped"]["shownText"] == ran["grouped"]["moneyAutoOf"]


def test_a_typed_measurement_moves_the_subtotal_in_place(ran):
    r = ran["grouped"]["repaint"]
    assert r["rebuilt"] is False, "typing rebuilt the panel, which takes the caret out of the box"
    assert r["shown"] == r["expected"] and r["shown"] != ran["grouped"]["shownText"][1]


def test_a_work_type_with_no_headings_draws_one_list_as_before(ran):
    assert ran["flatWhenNone"] == {"groups": 0, "cards": [0, 1, 2, 3]}
    assert ran["flatWhenAbsent"] == {"groups": 0, "cards": [0, 1, 2, 3]}


def test_rename_remove_and_reorder_reach_the_estimate_with_no_write_to_a_material(ran):
    assert ran["renamedHeading"][0] == ["Patch and Prep", [3]]
    assert ran["removedHeading"] == [["Floor", [0, 2]], ["Dye", []], ["Joint Filler", []], ["Other", [1, 3]]]
    assert ran["reorderedHeading"] == ["Joint Filler", "Dye", "Floor", "Patch", "Other"]


def test_a_saved_bid_reloaded_from_jsonb_groups_the_same(ran):
    assert ran["reloaded"] == [[x["name"], x["cards"]] for x in ran["grouped"]["groups"]]


def test_grouping_is_display_only_on_the_polish_job(ran):
    w, wo = ran["polishTotals"]["withCats"], ran["polishTotals"]["withoutCats"]
    assert w["saved"] > 0, "nothing was saved, so there was nothing to compare"
    assert w["total"] == wo["total"] > 0 and w["lump"] == wo["lump"] == w["total"]
    assert w["material"] == wo["material"]
    assert w["saves"] == wo["saves"], "the page saved something different because of the headings"
    assert "categor" not in w["saves"], "a heading leaked into the bid"


def test_grouping_is_display_only_on_the_epoxy_golden_job(ran):
    e = ran["epoxyTotals"]
    assert e["scopes"] == ["Epoxy", "Epoxy"], "the seeded assemblies, their Scope the division and no heading"
    assert e["withCats"]["groups"] == [["Epoxy Liquids", [0]], ["Cove", [1]]], (
        "not vacuous: the seeded flake and cove assemblies grouped by the headings their materials are filed under")
    assert e["split"] == [["Cove", [1]], ["Other", [0]]], "the flake's materials disagree, so it has no heading"
    assert e["noneFiled"] == [], "nothing filed anywhere: no lone Other heading over the whole takeoff"
    assert e["withoutCats"]["groups"] == []
    assert e["withCats"]["total"] == e["withoutCats"]["total"] > 0
    assert e["withCats"]["lump"] == e["withoutCats"]["lump"] == e["withCats"]["computed"] == e["withCats"]["total"]
    assert e["withCats"]["saves"] == e["withoutCats"]["saves"]


# ── mutations: each check above goes red when its change is taken out ─────────
def _scratch(tmp_path, rel, old, new):
    """A scratch frontend with one line broken and every other file the harnesses read copied unmodified."""
    frontend = break_source(tmp_path, rel, old, new)
    for path in FRONTEND.rglob("*"):
        if path.is_file() and path.suffix in (".js", ".html", ".css", ".json", ".svg"):
            target = frontend / path.relative_to(FRONTEND)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    return frontend


MUTATIONS = {
    "the takeoff drawn ungrouped": (
        "js/polish-estimate.js", "    html += takeoffRowsHtml(conds);",
        '    html += M.takeoff.map(takeoffRowCard).join("") + conds.map(function (c) { return c.cost ? condMaterialCard(c) : condSwitchCard(c); }).join("");',
        lambda r: [x["name"] for x in r["grouped"]["groups"]] == ["Patch", "Floor", "Dye", "Joint Filler", "Other"]),
    "every row under Other": (
        "js/library-core.js", "      (g || other).keys.push(k);", "      other.keys.push(k);",
        lambda r: [x["name"] for x in r["grouped"]["groups"]] == ["Patch", "Floor", "Dye", "Joint Filler", "Other"]),
    "the condition cards drawn after the groups": (
        "js/polish-estimate.js", '      .concat(conds.map(function (c) { return "c:" + c.key; }));',
        "      .concat([]);",
        lambda r: r["condCards"]["groups"][2]["conds"] == ["dye"]),
    "a condition card's cost left out of its subtotal": (
        "js/polish-estimate.js",
        '      if (typeof i === "string" && i.indexOf("c:") === 0) return sum + condSubtotal(i.slice(2));',
        '      if (typeof i === "string" && i.indexOf("c:") === 0) return sum;',
        lambda r: r["condCards"]["groups"][2]["shown"] == r["condCards"]["dye"]),
    "a condition card ignores its material's heading": (
        "js/polish-estimate.js", "    if (own) return own;", "    void own;",
        lambda r: r["condCards"]["dyeFiled"]["groups"][0]["conds"] == ["dye"]),
    "an assembly ignores what its materials agree on": (
        "js/library-core.js", "      agreed = c;", "      void c;",
        lambda r: r["derived"] == [["Patch", [2, 3]], ["Floor", [0]], ["Other", [1]]]),
    "an assembly whose materials disagree takes one of them": (
        "js/library-core.js", "      if (agreed && agreed.id !== c.id) return null;", "",
        lambda r: r["derivedSplit"] == [["Patch", [2, 3]], ["Other", [0, 1]]]),
    "a lone Other heading drawn": (
        "js/library-core.js", "    return drawn.length === 1 && drawn[0].other ? [] : drawn;", "    return drawn;",
        lambda r: r["epoxyTotals"]["noneFiled"] == []),
    "the subtotal not repainted": (
        "js/polish-estimate.js", "      el.textContent = moneyAuto(categorySubtotal(keys));", "      void keys;",
        lambda r: r["grouped"]["repaint"]["shown"] == r["grouped"]["repaint"]["expected"]),
    "an assembly's category ignored": (
        "js/polish-estimate.js",
        '    if (k === "asm") return L.assemblyCategory(asmById(r.assembly_id), CATS, wt, ITEMS);',
        "    if (k === \"asm\") return null;",
        lambda r: [x["cards"] for x in r["grouped"]["groups"]][:2] == [[3], [0, 2]]),
    "the Admin add lets a duplicate through": (
        "js/admin.js", "        if (!clean || taken(clean)) return null;", "        if (!clean) return null;",
        lambda r: r["admin"]["addDup"] is None),
    "the Admin card stops saying what a remove does": (
        "js/admin.js", "          category renames it for every material in it. <strong>Removing a category leaves its materials",
        "          category renames it for every material in it. <strong>Removing a category drops its materials",
        lambda r: r["admin"]["saysUncategorized"]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_mutation_goes_red(name, tmp_path):
    rel, old, new, check = MUTATIONS[name]
    frontend = _scratch(tmp_path, rel, old, new)
    proc = run_node(HARNESS, frontend, plan_json(tmp_path))
    if proc.returncode != 0:
        return                                   # a crash is the loudest way to go red
    assert not check(last_json_line(proc.stdout)), name + " left its check green"


PICKERS = "    return order.filter(function (wt) { return mine[wt] && L.categoriesFor(CATS, wt).length > 0; });"
LIBRARY_MUTATIONS = {
    "the facet ignores the category": (
        "js/library.js", "    if (F.category && !categoryHits(it, F.category)) return false;", "    void categoryHits;",
        lambda c: c["patch"]["shown"] == ["c1"]),
    "the editor writes into the map": (
        "js/library.js", "    if (id) out[wt] = id; else delete out[wt];",
        "    if (id) map[wt] = id; else delete map[wt]; out = map;",
        lambda c: c["edit"]["snapshotUntouched"]),
    "the selects offered on a database without the column": (
        "js/library.js", "    if (!CATS_WRITABLE) return '<span", "    if (false) return '<span",
        lambda c: c["noColumn"]["selects"] == []),
    "every work type offered to every material": (
        "js/library.js", PICKERS,
        "    return order.filter(function (wt) { return L.categoriesFor(CATS, wt).length > 0; });",
        lambda c: c["cells"]["c1"]["selects"] == ["epoxy"]),
    "a held category widens the pickers": (
        "js/library.js", PICKERS,
        "    return order.filter(function (wt) { return (mine[wt] || (it.material_categories || {})[wt]) && "
        "L.categoriesFor(CATS, wt).length > 0; });",
        lambda c: c["tied"]["before"]["t2"]["selects"] == ["epoxy"]),
    "the Defaults-tab work types widen the pickers": (
        "js/library.js", PICKERS,
        "    return order.filter(function (wt) { return (mine[wt] || (it.default_work_types || []).indexOf(wt) >= 0) "
        "&& L.categoriesFor(CATS, wt).length > 0; });",
        lambda c: c["tied"]["before"]["t6"]["selects"] == ["epoxy"]),
    "no sentence for a material in no division": (
        "js/library.js",
        "    if (!itemDivisions(it).length) return '<span class=\"catnote\">Pick a division first</span>';",
        "    void 0;",
        lambda c: c["tied"]["before"]["t1"]["pickDivision"]),
    "an unticked division keeps its category": (
        "js/library.js",
        "      if (Object.keys(keptCats).length !== Object.keys(it.material_categories || {}).length) {",
        "      if (false) {",
        lambda c: c["tied"]["afterUntick"]["model"] == {"epoxy": "epoxy-extras"}),
    "a division the page reads differently from the server": (
        "js/library.js", "    return DIVISION_WORK_TYPE[key] ||", "    return DIVISION_WORK_TYPE[key.replace(/ /g, \"\")] ||",
        lambda c: [[n, ic.division_work_type(n)] for n, _ in c["tied"]["divisionWorkTypes"]]
        == c["tied"]["divisionWorkTypes"]),
}


@pytest.mark.parametrize("name", sorted(LIBRARY_MUTATIONS))
def test_library_mutation_goes_red(name, tmp_path):
    rel, old, new, check = LIBRARY_MUTATIONS[name]
    frontend = _scratch(tmp_path, rel, old, new)
    proc = run_node(LIBRARY_HARNESS, frontend)
    if proc.returncode != 0:
        return
    assert not check(last_json_line(proc.stdout)["categoryColumn"]), name + " left its check green"


LIBRARY_SAVE_MUTATIONS = {
    "a refused category pick requeued": (
        "js/library.js",
        "        if (!dropRefusedCategory(kind, id, payload, j.detail || j.error)) requeueFailed(key, payload);",
        "        requeueFailed(key, payload);",
        lambda r: r["alone"]["pending"] == 0 and "material_categories" not in r["alone"]["nextBody"]),
    "every refused save treated as the missing column": (
        "js/library.js", "        !/material_categories/.test(String(detail || \"\"))) return false;",
        "        false) return false;",
        lambda r: r["other"]["pending"] == 1 and r["other"]["writable"] is True),
    "the rest of a refused payload dropped with the pick": (
        "js/library.js", "    if (left.length) return false;", "    void left;",
        lambda r: r["mixed"]["pending"] == 1 and '"unit_cost"' in r["mixed"]["resentBody"]),
}


@pytest.mark.parametrize("name", sorted(LIBRARY_SAVE_MUTATIONS))
def test_library_save_mutation_goes_red(name, tmp_path):
    rel, old, new, check = LIBRARY_SAVE_MUTATIONS[name]
    frontend = _scratch(tmp_path, rel, old, new)
    proc = run_node(LIBRARY_HARNESS, frontend)
    if proc.returncode != 0:
        return
    assert not check(last_json_line(proc.stdout)["categoryRefused"]), name + " left its check green"
