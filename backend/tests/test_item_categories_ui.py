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
def lib():
    require_node()
    return _run(harness=LIBRARY_HARNESS)["categoryColumn"]


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
def test_the_category_cell_offers_one_select_per_work_type_the_material_is_used_in(lib):
    c = lib["cells"]
    assert c["c1"]["selects"] == ["epoxy"] and c["c1"]["epoxy"] == "epoxy-patch" and not c["c1"]["labelled"]
    assert c["c2"]["selects"] == ["polish"] and c["c2"]["polish"] == ""
    assert c["c3"]["selects"] == ["epoxy", "polish"] and c["c3"]["labelled"], "two work types, each labelled"
    assert (c["c3"]["epoxy"], c["c3"]["polish"]) == ("epoxy-extras", "polish-floor")
    assert c["c6"]["selects"] == ["polish"], "a Defaults-tab work type counts as one the material is used in"
    assert c["c5"]["selects"] == ["epoxy", "polish"], "a material in no work type is offered every one with headings"
    assert lib["epoxyOptions"] == ["", "epoxy-patch", "epoxy-liquids", "epoxy-extras", "epoxy-cove"], (
        "the work type's headings, in the Admin order, after None")


def test_a_removed_heading_reads_as_none(lib):
    assert lib["cells"]["c4"]["epoxy"] == ""


def test_with_no_categories_loaded_the_cell_says_so_and_offers_nothing(lib):
    assert lib["bare"] == {"selects": [], "noneSetUp": True}


def test_choosing_a_category_queues_the_whole_map_as_a_new_object(lib):
    e = lib["edit"]
    assert e["afterAdd"] == {"kind": "items", "id": "c1",
                             "body": {"material_categories": {"epoxy": "epoxy-patch", "polish": "polish-dye"}}}
    assert e["modelAfterAdd"] == {"epoxy": "epoxy-patch", "polish": "polish-dye"}
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


# ── the Material step ────────────────────────────────────────────────────────
def test_the_rows_are_grouped_under_the_headings_in_the_admin_order_with_other_last(ran):
    g = ran["grouped"]
    assert [(x["name"], x["cards"]) for x in g["groups"]] == [("Patch", [3]), ("Floor", [0, 2]), ("Other", [1])], (
        "a material under its own heading, two assemblies whose category names a heading (case and spacing "
        "ignored), and an assembly whose category is another work type's under Other")
    assert sorted(g["cards"]) == list(range(g["rows"])), "every row is drawn exactly once"
    assert g["matTotalStill"], "the Material total line is still there"


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
    assert ran["removedHeading"] == [["Floor", [0, 2]], ["Other", [1, 3]]]
    assert ran["reorderedHeading"] == ["Floor", "Patch", "Other"]


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
    assert [n for n, _ in e["withCats"]["groups"]] == ["Cove", "Other"], (
        "not vacuous: the Epoxy section really was grouped (its cove under Cove, the flake under Other)")
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
        "js/polish-estimate.js", "    html += takeoffRowsHtml();",
        '    html += M.takeoff.map(takeoffRowCard).join("");',
        lambda r: [x["name"] for x in r["grouped"]["groups"]] == ["Patch", "Floor", "Other"]),
    "every row under Other": (
        "js/library-core.js", "      (g || other).keys.push(k);", "      other.keys.push(k);",
        lambda r: [x["name"] for x in r["grouped"]["groups"]] == ["Patch", "Floor", "Other"]),
    "the subtotal not repainted": (
        "js/polish-estimate.js", "      el.textContent = moneyAuto(categorySubtotal(keys));", "      void keys;",
        lambda r: r["grouped"]["repaint"]["shown"] == r["grouped"]["repaint"]["expected"]),
    "an assembly's category ignored": (
        "js/polish-estimate.js",
        '    if (k === "asm") return L.assemblyCategory(asmById(r.assembly_id), CATS, wt);',
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


LIBRARY_MUTATIONS = {
    "the facet ignores the category": (
        "js/library.js", "    if (F.category && !categoryHits(it, F.category)) return false;", "    void categoryHits;",
        lambda c: c["patch"]["shown"] == ["c1"]),
    "the editor writes into the map": (
        "js/library.js", "    if (id) out[wt] = id; else delete out[wt];",
        "    if (id) map[wt] = id; else delete map[wt]; out = map;",
        lambda c: c["edit"]["snapshotUntouched"]),
    "every work type offered to every material": (
        "js/library.js", "    return own.length ? own : withCats;", "    return withCats;",
        lambda c: c["cells"]["c1"]["selects"] == ["epoxy"]),
}


@pytest.mark.parametrize("name", sorted(LIBRARY_MUTATIONS))
def test_library_mutation_goes_red(name, tmp_path):
    rel, old, new, check = LIBRARY_MUTATIONS[name]
    frontend = _scratch(tmp_path, rel, old, new)
    proc = run_node(LIBRARY_HARNESS, frontend)
    if proc.returncode != 0:
        return
    assert not check(last_json_line(proc.stdout)["categoryColumn"]), name + " left its check green"
