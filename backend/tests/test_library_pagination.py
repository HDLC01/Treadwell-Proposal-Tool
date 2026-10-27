"""The Items table 25 at a time and the Assemblies rail 8 at a time (Hanz, 2026-10-27).

"Assemblies should have a pagination of 8 only." The Items table stays at 25. Both sizes live in
library-core.js (PAGE_SIZE and ASM_PAGE_SIZE); the page math is shared.

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
def harness():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    assert proc.stdout.strip(), "the harness printed nothing:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def pager(harness):
    return harness["pager"]


@pytest.fixture(scope="module")
def newest(harness):
    return harness["newestFirst"]


# ── the page math ─────────────────────────────────────────────────────────────

def test_items_take_25_a_page_and_assemblies_8():
    """Mutation: put ASM_PAGE_SIZE back to 25, or point the rail at PAGE_SIZE."""
    assert core("L.PAGE_SIZE") == 25
    assert core("L.ASM_PAGE_SIZE") == 8


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
    """Add material from page 3 lands on page 1 as row 1. Under Name A-Z a copy that sits mid-list
    moves the table to ITS page: the jump-to-its-page rule, kept for the sort where a new row is
    not always first."""
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

def test_sixty_assemblies_draw_eight_cards(pager):
    """Sixty cards are eight pages; the ninth card opens page 2."""
    a = pager["asm"]
    assert a["firstPage"] == "q1..q8 (8)"
    assert a["firstPager"]["page"] == "Page 1 of 8"
    assert a["firstPager"]["range"] == "1" + DASH + "8 of 60"
    assert a["afterNext"] == "q9..q16 (8)"
    assert a["afterNextPager"]["page"] == "Page 2 of 8"


def test_rail_repaints_keep_the_page(pager):
    assert pager["asm"]["afterRepaints"] == "q9..q16 (8)"


def test_rail_search_facet_sort_and_area_go_back_to_page_one(pager):
    a = pager["asm"]
    assert a["afterSearch"] == "q2..q16 (8)"
    assert a["searchPager"]["page"] == "Page 1 of 4"
    assert a["searchPager"]["range"] == "1" + DASH + "8 of 30"
    assert a["searchHits"] == "30 of 60 shown"
    assert (a["beforeFacet"], a["afterFacet"]) == (2, 1)
    assert (a["beforeSort"], a["afterSort"]) == (2, 1)
    assert (a["beforeArea"], a["afterArea"]) == (2, 1)


def test_opening_an_assembly_by_id_shows_its_card(pager):
    """q47 is card 47: page 6 at 8 a page (cards 41-48). q55 is on page 7 (49-56)."""
    a = pager["asm"]
    assert a["openedPage"] == 6 and a["openedCurrent"] == ["q47"]
    assert a["deepLinkPage"] == 7 and a["deepLinkCurrent"] == ["q55"]
    # Opening moves the rail once; paging away afterwards is not undone by the next repaint.
    assert a["pagedAwayFromOpen"] == 7


def test_a_new_assembly_is_on_screen_and_current(pager):
    a = pager["asm"]
    assert a["afterNew"] == "qnew..q7 (8)"
    assert a["afterNewCurrent"] == ["qnew"]


def test_a_shrinking_rail_clamps_to_its_new_last_page(pager):
    """61 cards (qnew + q1..q60): page 8 holds q56..q60. Take those five off and page 8 is gone,
    so the rail lands on the new last page, 7, and one Previous reaches page 6."""
    a = pager["asm"]
    assert a["lastBeforeShrink"] == "q56..q60 (5)"
    assert a["afterShrink"] == "q48..q55 (8)"
    assert a["afterShrinkPager"]["page"] == "Page 7 of 7"
    assert a["afterShrinkPager"]["range"] == "49" + DASH + "56 of 56"
    assert a["previousAfterShrink"] == "q40..q47 (8)"


def test_eight_assemblies_get_no_pager_and_nine_do(pager):
    a = pager["asm"]
    assert a["eight"] == "q1..q8 (8)"
    assert a["eightPager"]["hidden"] is True and a["eightPager"]["range"] == ""
    assert a["nine"] == "q1..q8 (8)"
    assert a["ninePager"]["hidden"] is False
    assert a["ninePager"]["page"] == "Page 1 of 2"
    assert a["ninePager"]["range"] == "1" + DASH + "8 of 9"
    assert a["ninePageTwo"] == "q9..q9 (1)"


def test_the_pagers_are_named_landmarks_that_start_hidden(pager):
    m = pager["markup"]
    assert m["navs"] == ["items-pager-top", "items-pager", "asm-pager"]
    assert m["steps"] == ["items"] * 4 + ["asm"] * 2
    assert m["spentAtRest"] == 3


# ── newest first, on both lists (Hanz, 2026-10-27) ───────────────────────────
# "The newest added item should be put on the first page." He chose: always newest first, both
# lists, every time and after a reload, with "Name A-Z" one click away. Driven by the harness's
# `out.newestFirst` block through the real renderItems / renderList and the page's own ITEM_SORT
# and ASM_SORT declaration lines.

def test_the_items_table_opens_newest_first_with_undated_rows_last(newest):
    """created_at descending. m2 and m4 are the SAME instant written two ways ("+00:00" and "Z"),
    so they tie and fall to the name; compared as text, "Z" beats "+" and m4 would come first. m1
    has no created_at and goes LAST, never first.

    Mutation: drop sortItems from visibleItems; put the ITEM_SORT default back to "name"; compare
    created_at as text; or sort blanks first."""
    assert newest["defaultKey"] == "new"
    assert newest["defaultOrder"] == ["m5", "m3", "m2", "m4", "m1"], newest["defaultOrder"]
    assert newest["selectSyncedToDefault"] == "new", (
        "the Sort control does not show the order the table is in")


def test_newest_first_never_reorders_the_model(newest):
    """visibleItems hands ITEMS itself to the sort when nothing is filtered. A sort in place would
    reorder the array every other function on the page reads.

    Mutation: `list.sort(...)` instead of `list.slice().sort(...)` in sortItems."""
    assert newest["modelUntouched"] == ["m1", "m2", "m3", "m4", "m5"], newest["modelUntouched"]
    assert newest["newIsACopy"] is True


def test_name_a_z_is_the_servers_order_passed_through(newest):
    """list_items() does `.order("name")`, so the array the page holds IS name A-Z, and Name A-Z
    hands it back as it is - the same rule as the Assemblies rail, which keeps a just-added row at
    the top for the session and never moves a row while its name is being typed.

    Mutation: make sortItems copy or re-sort for "name"."""
    assert newest["nameOrder"] == ["m1", "m2", "m3", "m4", "m5"], newest["nameOrder"]
    assert newest["namePassesThrough"] is True
    assert newest["selectSyncedToName"] == "name"


def test_a_search_narrows_and_then_the_sort_orders_what_is_left(newest):
    """Filter first, then sort, then the page: "co" leaves Bond Coat and Cove Mix.

    Mutation: return the unsorted filter result from visibleItems."""
    assert newest["searchedNewest"] == ["m3", "m2"], newest["searchedNewest"]
    assert newest["searchedByName"] == ["m2", "m3"], newest["searchedByName"]


def test_page_one_shows_the_latest_materials_after_a_reload(newest):
    """Sixty materials in name order, each a minute newer than the last: the newest sixty-first
    by name is on page 3 under Name A-Z and on page 1 here.

    Mutation: put the ITEM_SORT default back to "name"."""
    assert newest["reloadFirstPage"] == "p60..p36 (25)", newest["reloadFirstPage"]


def test_a_new_material_is_row_one_of_page_one(newest):
    """From page 3, a material arriving at the END of the array (where the server files
    "Zz Sealer" by name) is still the first row of page 1, because it is the newest. Without the
    sort it sits at row 61 and the table would move to page 3 to show it.

    Mutation: drop sortItems from visibleItems."""
    assert newest["beforeAddPage"] == 3
    assert newest["afterAddPage"] == 1, newest["afterAddPage"]
    assert newest["afterAddFirstRow"] == "pnew", newest["afterAddFirstRow"]


def test_changing_the_sort_goes_back_to_page_one(newest):
    """Page 2 of one order means nothing in another, so a sort change starts at page 1, both ways.

    Mutation: leave ITEM_SORT out of itemsPage's view key."""
    assert newest["beforeSortChangePage"] == 2
    assert newest["afterSortChangePage"] == 1, newest["afterSortChangePage"]
    assert newest["afterSortChangeRows"] == "p1..p25 (25)", newest["afterSortChangeRows"]
    assert newest["beforeSortBackPage"] == 2
    assert newest["afterSortBackPage"] == 1, newest["afterSortBackPage"]
    assert newest["afterSortBackFirstRow"] == "pnew"


def test_a_saved_sort_choice_is_restored_on_both_lists(newest):
    """Per viewer, in localStorage: the page's own declaration lines read it as they run. A stored
    key the select no longer offers, and storage that throws (a private window, blocked site
    data), both open on the default rather than breaking the page.

    Mutation: drop the savedSort call from either declaration; drop the SORT_KEYS check; or drop
    the try/catch in savedSort."""
    assert newest["restoredItemSort"] == "name", newest["restoredItemSort"]
    assert newest["restoredAsmSort"] == "owner", newest["restoredAsmSort"]
    assert newest["restoredOrder"] == ["m1", "m2", "m3", "m4", "m5"], newest["restoredOrder"]
    assert newest["unknownSavedKey"] == ["new", "new"], newest["unknownSavedKey"]
    assert newest["blockedStorage"] == ["new", "new"], newest["blockedStorage"]


def test_picking_a_sort_remembers_it_and_moves_nothing_else(newest):
    """What a pick stores, under one key per list; a store that refuses does not throw out of the
    listener. The listeners are top-level wiring, so their bodies are read from source: each one
    remembers the pick and repaints its own list, and neither clears the filters nor moves the
    focus off the select somebody is standing in.

    Mutation: drop the rememberSort call from either listener, or the try/catch in rememberSort."""
    assert newest["written"] == {"tw_library_sort_items": "name",
                                 "tw_library_sort_asm": "vendor"}, newest["written"]
    assert newest["refusedWriteThrew"] is False
    item_body, asm_body = newest["itemListener"], newest["asmListener"]
    assert 'rememberSort("items", ITEM_SORT)' in item_body, item_body
    assert "renderItems()" in item_body, item_body
    assert 'rememberSort("asm", ASM_SORT)' in asm_body, asm_body
    for body in (item_body, asm_body):
        assert "clearFilters" not in body and "clearAsmFilters" not in body, body
        assert ".focus(" not in body, body


def test_the_assemblies_rail_opens_newest_first(newest):
    """Same instruction, the other list: sixty assemblies, each a minute newer, page 1 is the
    latest eight and the Sort select says so.

    Mutation: put the ASM_SORT default back to "name"."""
    assert newest["railFirstPage"] == "q60..q53 (8)", newest["railFirstPage"]
    assert newest["railSelect"] == "new"


def test_the_assemblies_rail_opens_on_page_1_after_a_reload(newest):
    """The rail as the page actually loads: load() opens an assembly when nothing is open, and
    asmPage moves the rail to the page holding the open card. Under Newest first that pick has to
    be the TOP card of the sorted rail. ASMS[0] is the first by NAME (the server's order), which
    with sixty dated assemblies is q1, the oldest, on page 3 -- so the rail would reopen on the
    oldest work every time. The delete path asks the same function.

    Mutation: return ASMS[0].id from firstAssemblyId (or put `ASMS[0].id` back in load())."""
    r = newest["railOnLoad"]
    assert "error" not in r, r
    assert r["page"] == 1, r
    assert r["firstCard"] == "q60", r
    assert r["open"] == ["q60"], r
    assert r["namePage"] == 1, r
    assert r["nameOpen"] == ["q1"], r
    assert r["empty"] is None, r


def test_the_items_sort_control_is_two_choices_in_the_items_filter_bar(newest):
    """The Assemblies rail's control in the same shape (.facet + .flabel), over the Items table,
    with exactly the two orders Hanz asked for, the default first. The rail's select lists its
    default first too.

    Mutation: delete #f-sort, add a third option, or reorder them."""
    assert newest["itemOptionValues"] == ["new", "name"], newest["itemOptionValues"]
    assert newest["itemOptionLabels"] == ["Newest first", "Name A–Z"], newest["itemOptionLabels"]
    assert newest["labelled"] is True
    assert newest["inTheItemsBar"] is True
    assert newest["asmFirstOption"] == "new"
