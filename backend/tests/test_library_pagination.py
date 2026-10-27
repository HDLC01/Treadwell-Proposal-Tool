"""The Items table and the Assemblies rail, 25 at a time (Hanz, 2026-10-27).

Two halves, both executed under node:

  * The page math in library-core.js (pageCount, clampPage, pageOfIndex, pageSlice, pageInfo),
    called directly.
  * The REAL renderItems / renderList out of library.js, driven by library-ui-harness.js's
    `out.pager` block. Each scenario changes the model the way the page's own event does (a search
    assigned, a row unshifted, a row filtered out, an assembly opened) and reads back which rows
    were drawn. The rules are all about WHEN the page moves: renderItems runs on a dozen events,
    and a page that jumped under somebody on a save reply would be worse than no pager at all.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "library-core.js"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "library-ui-harness.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

DASH = "–"


def core(expr: str):
    script = "const L = require(%s); console.log(JSON.stringify(%s));" % (json.dumps(str(CORE)), expr)
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def pager():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    assert proc.stdout.strip(), "the harness printed nothing:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])["pager"]


# ── the page math ─────────────────────────────────────────────────────────────

def test_one_page_size_for_both_lists():
    assert core("L.PAGE_SIZE") == 25


def test_page_count_never_falls_below_one():
    """An empty list is one empty page, so a clamp always has somewhere to land."""
    assert core("[0, 1, 25, 26, 50, 51, 140, -3, null].map((n) => L.pageCount(n, 25))") == \
        [1, 1, 1, 2, 2, 3, 6, 1, 1]


def test_clamp_pulls_a_page_back_inside_the_list():
    """Delete the last row of the last page: page 3 of a list that now fills two is page 2."""
    assert core("[L.clampPage(3, 50, 25), L.clampPage(0, 50, 25), L.clampPage(2, 0, 25),"
                " L.clampPage('x', 60, 25), L.clampPage(2, 60, 25)]") == [2, 1, 1, 1, 2]


def test_a_row_index_maps_to_its_page():
    assert core("[0, 24, 25, 49, 50, -1].map((i) => L.pageOfIndex(i, 25))") == [1, 1, 2, 2, 3, 1]


def test_the_slice_is_the_page_and_leaves_the_list_alone():
    got = core("(() => { const a = Array.from({length: 60}, (_, i) => i + 1);"
               " const s = L.pageSlice(a, 2, 25);"
               " return [s[0], s[s.length - 1], s.length, a.length, L.pageSlice(a, 9, 25)[0],"
               " L.pageSlice(null, 1, 25).length]; })()")
    assert got == [26, 50, 25, 60, 51, 0]


def test_the_pager_text_counts_the_set_it_is_given():
    info = core("L.pageInfo(2, 140, 25)")
    assert info["label"] == "Page 2 of 6"
    assert info["range"] == "26" + DASH + "50 of 140"
    assert info["paged"] is True
    assert core("L.pageInfo(6, 140, 25).range") == "126" + DASH + "140 of 140"
    one = core("L.pageInfo(1, 25, 25)")
    assert one["paged"] is False and one["pages"] == 1
    assert core("L.pageInfo(1, 0, 25)")["range"] == "0" + DASH + "0 of 0"


# ── the Items table ───────────────────────────────────────────────────────────

def test_sixty_materials_draw_twenty_five_and_say_where_they_are(pager):
    it = pager["items"]
    assert it["firstPage"] == "p1..p25 (25)"
    assert it["firstPager"] == {"hidden": False, "page": "Page 1 of 3",
                                "range": "1" + DASH + "25 of 60",
                                "prevSpent": "true", "nextSpent": "false"}
    # The compact copy over the table says the same page.
    assert it["topPager"]["hidden"] is False and it["topPager"]["page"] == "Page 1 of 3"


def test_next_and_previous_walk_the_table(pager):
    it = pager["items"]
    assert it["afterNext"] == "p26..p50 (25)"
    assert it["afterNextPager"]["range"] == "26" + DASH + "50 of 60"
    assert it["afterNextPager"]["prevSpent"] == "false"
    assert it["lastPage"] == "p51..p60 (10)"
    assert it["lastPager"]["nextSpent"] == "true"
    assert it["pastTheEnd"] == "p51..p60 (10)"
    assert it["afterPrevious"] == "p26..p50 (25)"


def test_a_save_reply_more_and_a_full_repaint_keep_the_page(pager):
    it = pager["items"]
    assert it["afterSaveReply"] == "p26..p50 (25)"
    assert it["afterMore"] == "p26..p50 (25)"
    assert it["afterPaint"] == "p26..p50 (25)"


def test_a_search_or_a_facet_goes_back_to_page_one_and_counts_the_hits(pager):
    it = pager["items"]
    assert it["afterSearch"] == "p2..p50 (25)"
    assert it["searchPager"]["page"] == "Page 1 of 2"
    assert it["searchPager"]["range"] == "1" + DASH + "25 of 30"
    assert it["searchHits"] == "30 of 60 shown"
    assert it["searchPageTwo"] == "p52..p60 (5)"
    assert it["beforeFacet"] == 2
    assert it["afterFacet"] == "p2..p50 (25)"


def test_an_added_or_copied_material_lands_on_screen(pager):
    it = pager["items"]
    assert it["beforeAddOnPage"] == 3
    assert it["afterAddFirstRow"] == "pnew"
    assert it["afterAdd"] == "pnew..p24 (25)"
    assert it["copyOnItsPage"] == 2 and it["copyDrawn"] is True
    # Several ids arriving at once is a reload, not a row somebody just made.
    assert it["reloadDidNotMove"] is True


def test_edit_from_another_tab_reaches_a_material_pages_away(pager):
    assert pager["items"]["focusMovedTo"] == 3
    assert pager["items"]["focusRowDrawn"] is True


def test_deleting_the_last_row_of_the_last_page_lands_on_the_new_last_page(pager):
    it = pager["items"]
    assert it["lonePage"] == "p51..p51 (1)"
    assert it["afterDelete"] == "p26..p50 (25)"
    assert it["afterDeletePager"]["page"] == "Page 2 of 2"
    assert it["afterDeletePager"]["nextSpent"] == "true"
    assert it["previousAfterDelete"] == "p1..p25 (25)"


def test_twenty_five_materials_get_no_pager_and_unchanged_rows(pager):
    it = pager["items"]
    assert it["twentyFive"] == "p1..p25 (25)"
    assert it["twentyFivePager"]["hidden"] is True and it["twentyFivePager"]["page"] == ""
    assert it["twentyFiveTop"]["hidden"] is True
    assert it["twentySixPager"]["hidden"] is False
    assert it["twentySixPager"]["range"] == "1" + DASH + "25 of 26"
    assert it["sameRowMarkup"] is True


# ── the Assemblies rail ───────────────────────────────────────────────────────

def test_sixty_assemblies_draw_twenty_five_cards(pager):
    a = pager["asm"]
    assert a["firstPage"] == "q1..q25 (25)"
    assert a["firstPager"]["page"] == "Page 1 of 3"
    assert a["firstPager"]["range"] == "1" + DASH + "25 of 60"
    assert a["afterNext"] == "q26..q50 (25)"
    assert a["afterNextPager"]["page"] == "Page 2 of 3"


def test_rail_repaints_keep_the_page(pager):
    assert pager["asm"]["afterRepaints"] == "q26..q50 (25)"


def test_rail_search_facet_sort_and_area_go_back_to_page_one(pager):
    a = pager["asm"]
    assert a["afterSearch"] == "q2..q50 (25)"
    assert a["searchPager"]["range"] == "1" + DASH + "25 of 30"
    assert a["searchHits"] == "30 of 60 shown"
    assert (a["beforeFacet"], a["afterFacet"]) == (2, 1)
    assert (a["beforeSort"], a["afterSort"]) == (2, 1)
    assert (a["beforeArea"], a["afterArea"]) == (2, 1)


def test_opening_an_assembly_by_id_shows_its_card(pager):
    a = pager["asm"]
    assert a["openedPage"] == 2 and a["openedCurrent"] == ["q47"]
    assert a["deepLinkPage"] == 3 and a["deepLinkCurrent"] == ["q55"]
    # Opening moves the rail once; paging away afterwards is not undone by the next repaint.
    assert a["pagedAwayFromOpen"] == 3


def test_a_new_assembly_is_on_screen_and_current(pager):
    a = pager["asm"]
    assert a["afterNew"] == "qnew..q24 (25)"
    assert a["afterNewCurrent"] == ["qnew"]


def test_a_shrinking_rail_clamps_to_its_new_last_page(pager):
    a = pager["asm"]
    assert a["lastBeforeShrink"] == "q50..q60 (11)"
    assert a["afterShrink"] == "q25..q49 (25)"
    assert a["afterShrinkPager"]["page"] == "Page 2 of 2"
    assert a["previousAfterShrink"] == "qnew..q24 (25)"


def test_twenty_five_assemblies_get_no_pager(pager):
    a = pager["asm"]
    assert a["twentyFive"] == "q1..q25 (25)"
    assert a["twentyFivePager"]["hidden"] is True and a["twentyFivePager"]["range"] == ""


def test_the_pagers_are_named_landmarks_that_start_hidden(pager):
    m = pager["markup"]
    assert m["navs"] == ["items-pager-top", "items-pager", "asm-pager"]
    assert m["steps"] == ["items"] * 4 + ["asm"] * 2
    assert m["spentAtRest"] == 3
