"""Several base bids on one estimate ("Create Multiple Proposals"), plan step 3: the v1 base picks.

On a spreadsheet draft the Proposal step's Pricing options card draws a Base-bid CHECKBOX per sheet: every ticked sheet is a
base bid, tagged "Base Bid N", and becomes its own proposal. The pricing base (base_tab_id) stays the one the page prices off,
is Base Bid 1, and is kept inside the ticked list (base_tab_ids). A tick adds a base bid; unticking the base moves it to the
next ticked sheet; the last one cannot be unticked. A child (a proposal the server made from another draft's estimate) shows
its base read-only and links to Base Bid 1's proposal. The Estimate step keeps the list consistent (its base radio, deleting a
copy) and its pricing snapshot carries each tab's phase, costs and man-hours, which the server copies into a child.

Run, not read: js/multi-proposals-harness.js executes the pages' own code (renderProposalExtras, rebuildPricing, wireBidBar,
deleteTab, snapshotLumpSumsToState) over a small DOM with the real price-lines-core.js. The BREAKS at the bottom prove each
check goes red when the line it pins is taken out.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "multi-proposals-harness.js"
FILES = ["js/proposal-review.js", "js/estimate-review.js", "js/price-lines-core.js", "shared.js", "js/bid-model.js",
         "js/bid-engine.js"]


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def out():
    require_node()
    return run()


def _checked(look):
    return [b["value"] for b in look["boxes"] if b["checked"]]


# ── the Proposal step's card ─────────────────────────────────────────────────────────────────────
def test_a_spreadsheet_draft_draws_a_base_bid_checkbox_per_sheet(out):
    r = out["rows"]
    assert [b["value"] for b in r["boxes"]] == ["Polish", "Copy1", "Epoxy"], "no box on Seal, one on every other sheet"
    assert all(b["type"] == "checkbox" and b["name"] is None and not b["disabled"] for b in r["boxes"])
    assert _checked(r) == ["Epoxy"]
    assert r["tags"] == {"Polish": None, "Copy1": None, "Epoxy": "Base Bid 1", "Seal": None}
    assert r["base_tab_ids"] is None and r["anyBaseIdsSaved"] is False, "opening a draft writes no list it never had"


def test_a_tick_adds_a_base_bid_and_leaves_the_base_and_price_where_they_were(out):
    one, two = out["tick"]["one"], out["tick"]["two"]
    assert one["fired"] is True
    assert one["base_tab_id"] == "Epoxy" and one["lump"] == out["tick"]["before"]["lump"]
    assert one["base_tab_ids"] == ["Epoxy", "Copy1"] and one["saved"] == ["Epoxy", "Copy1"]
    assert one["tags"]["Copy1"] == "Base Bid 2" and one["tags"]["Epoxy"] == "Base Bid 1"
    assert one["notes"]["Copy1"] == "This sheet is Base Bid 2: it gets its own proposal."
    assert one["copyIsOption"] is False and "Copy1" not in one["roomIds"], "a base bid is not also an option"
    assert one["isopt"]["Copy1"] is False, "a ticked sheet offers no option controls"
    assert one["reloads"] == 0, "the base did not move, so the template is not reloaded"
    # the next tick numbers by the sheets' own order (priced_tabs: Polish before Copy1), the base staying Base Bid 1
    assert two["base_tab_ids"] == ["Epoxy", "Polish", "Copy1"] and two["saved"] == ["Epoxy", "Polish", "Copy1"]
    assert two["tags"] == {"Polish": "Base Bid 2", "Copy1": "Base Bid 3", "Epoxy": "Base Bid 1", "Seal": None}


def test_unticking_the_base_moves_it_to_the_next_ticked_sheet(out):
    u = out["untickBase"]
    assert u["fired"] is True
    assert u["base_tab_id"] == "Polish" and u["base_tab_ids"] == ["Polish", "Copy1"]
    assert u["saved"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"]}
    assert u["lump"] == 33798, "the page re-prices off the new base"
    assert u["reloads"] == 1, "a moved base reloads the template for its work type"
    assert u["tags"]["Polish"] == "Base Bid 1" and u["tags"]["Copy1"] == "Base Bid 2" and u["tags"]["Epoxy"] is None


def test_unticking_another_base_bid_takes_only_it_off(out):
    u = out["untickOther"]
    assert u["base_tab_id"] == "Epoxy" and u["base_tab_ids"] == ["Epoxy"] and _checked(u) == ["Epoxy"]
    assert u["isopt"]["Copy1"] is True, "an unticked sheet can be an option again"


def test_the_last_base_bid_cannot_be_unticked(out):
    r = out["last"]
    assert r["boxChecked"] is True and _checked(r) == ["Epoxy"]
    assert r["base_tab_id"] == "Epoxy" and r["base_tab_ids"] is None and r["savesByRefusal"] == 0
    assert r["notes"]["Epoxy"] == "A proposal needs a base bid. Tick another sheet first, then untick this one."


def test_a_child_shows_its_base_read_only_and_links_to_base_bid_1(out):
    c = out["child"]
    assert all(b["disabled"] for b in c["boxes"]) and _checked(c) == ["Copy1"]
    assert c["locked"] == "This proposal's base is Polish copy. Base bids are picked on Base Bid 1's tab. Open Base Bid 1"
    assert c["parentLink"] == "/proposal-review.html?d=PARENT-1"
    assert c["attempts"] == [False, False, False], "a disabled box takes no event"
    assert c["after"] == {"base_tab_id": "Copy1", "base_tab_ids": ["Copy1"]} and c["reloadsAfter"] == 0, \
        "a change forced at a child's box changes nothing"
    assert all(v is None for v in c["tags"].values()), "a child does not number itself"
    assert c["isopt"]["Epoxy"] is True and c["isopt"]["Polish"] is True, "the child's options stay its own to pick"


def test_a_v2_draft_keeps_its_read_only_radios(out):
    v = out["v2"]
    assert all(b["type"] == "radio" and b["name"] == "pr-base" and b["disabled"] for b in v["boxes"])
    assert v["locked"] == "Pick the base bid on the estimate. Open the estimate"
    assert all(t is None for t in v["tags"].values())


def test_rebuild_pricing_keeps_the_base_inside_the_ticked_sheets(out):
    r = out["rebuild"]
    assert r["refused"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy", "Copy1"], "saved": ["Epoxy", "Copy1"]}, \
        "the resolved base takes the refused Seal base's place"
    assert r["noList"] == {"base_tab_id": "Epoxy", "base_tab_ids": None, "saved": False}
    assert r["kept"] == {"base_tab_ids": ["Epoxy", "Copy1"]}


def test_a_combos_combined_base_is_one_base_on_its_own(out):
    c = out["combined"]
    assert _checked(c["start"]) == [""] and c["start"]["base_tab_id"] is None
    assert c["sheetPicked"]["base_tab_id"] == "Epoxy" and c["sheetPicked"]["base_tab_ids"] == ["Epoxy"]
    assert _checked(c["sheetPicked"]) == ["Epoxy"]
    assert c["two"]["base_tab_ids"] == ["Epoxy", "Copy1"]
    assert c["back"]["base_tab_id"] is None and c["back"]["base_tab_ids"] == [] and _checked(c["back"]) == [""]
    assert c["back"]["lump"] == c["start"]["lump"]


def test_the_twprice_helpers(out):
    c = out["core"]
    assert c["ids"] == {"none": ["Epoxy"], "ordered": ["Epoxy", "Polish", "Copy2"], "baseMissing": ["Copy2", "Polish"],
                        "gone": ["Epoxy", "Copy1"], "explicitOrder": ["Epoxy", "Copy1", "Polish"], "noBase": ["Copy1"],
                        "notState": []}
    assert c["labels"] == ["Base Bid 1", "Base Bid 2", "Base Bid 3", ""]
    t = c["toggle"]
    assert t["add"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy", "Copy1"]}
    assert t["addAgain"] is None and t["dropLast"] is None and t["dropUnticked"] is None and t["combinedOff"] is None
    assert t["dropOther"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy"]}
    assert t["dropBase"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"]}
    assert t["combinedOn"] == {"base_tab_id": None, "base_tab_ids": []}
    assert t["sheetOverCombined"] == {"base_tab_id": "Copy1", "base_tab_ids": ["Copy1"]}
    assert c["move"] == {"swap": ["Polish", "Copy1"], "toNull": [], "ordered": ["Copy2", "Polish"]}
    assert c["child"] == [True, False, False, False, False]


# ── the Estimate step ────────────────────────────────────────────────────────────────────────────
def test_the_bid_bar_radio_puts_the_new_base_in_the_old_ones_place(out):
    b = out["bidBar"]
    assert b["swap"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"], "persisted": 1}
    assert b["toTicked"] == {"base_tab_id": "Copy1", "base_tab_ids": ["Copy1"], "persisted": 1}
    assert b["noList"] == {"base_tab_id": "Polish", "base_tab_ids": None, "persisted": 1}


def test_deleting_a_copy_takes_it_off_the_ticked_sheets(out):
    d = out["deleteTab"]
    assert d["other"]["base_tab_id"] == "Epoxy" and d["other"]["base_tab_ids"] == ["Epoxy"]
    assert d["other"]["saved"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy"]}
    assert d["base"]["base_tab_id"] == "Copy2" and d["base"]["base_tab_ids"] == ["Copy2"], \
        "the deleted base's place goes to the next ticked sheet"
    assert d["lastBase"]["base_tab_id"] is None and d["lastBase"]["base_tab_ids"] == [], \
        "no ticked sheet left: the base falls back to the derived one, as it always did"
    assert d["noList"] == {"base_tab_id": "Epoxy", "base_tab_ids": None, "saved": {"base_tab_id": "Epoxy"}}


def test_the_pricing_snapshot_carries_each_tabs_phase_costs_and_man_hours(out):
    assert out["snapshot"] == {
        "Epoxy": {"phase": 4500, "costs": 6100, "man_hours": 40.4},
        "Polish": {"phase": 5100, "costs": 7300, "man_hours": 52},
        "Copy1": {"phase": 3900, "costs": 5200, "man_hours": 31.6},
    }


# ── the checks go red when the code changes ──────────────────────────────────────────────────────
BREAKS = {
    "the base control is still a radio": (
        "js/proposal-review.js", '          const baseKind = v2Locked ? "radio" : "checkbox";', '          const baseKind = "radio";',
        lambda r: any(b["type"] != "checkbox" for b in r["rows"]["boxes"])),
    "a ticked second sheet is not drawn ticked": (
        "js/proposal-review.js", "            const isOtherBase = !isBase && tickIds.indexOf(t.id) >= 0;",
        "            const isOtherBase = false;",
        lambda r: r["tick"]["one"]["tags"]["Copy1"] != "Base Bid 2"),
    "no Base Bid tag": (
        "js/proposal-review.js", '              ? ` <span class="pr-bidtag">${esc(TWPrice.baseLabelFor(state, t.id))}</span>` : "";',
        '              ? "" : "";',
        lambda r: r["rows"]["tags"]["Epoxy"] != "Base Bid 1"),
    "a tick moves the base like the old radio": (
        "js/price-lines-core.js",
        "      return { base_tab_id: base, base_tab_ids: baseIds({ base_tab_id: base, base_tab_ids: current.concat([id]) }, order || orderOf(state)) };",
        "      return { base_tab_id: id, base_tab_ids: [id] };",
        lambda r: r["tick"]["one"]["base_tab_id"] != "Epoxy"),
    "the last base bid can be unticked": (
        "js/price-lines-core.js", "    if (!left.length) return null;             // the last one: refused",
        "    if (!left.length) return { base_tab_id: null, base_tab_ids: [] };",
        lambda r: r["last"]["base_tab_id"] != "Epoxy" or r["last"]["boxChecked"] is not True),
    "a refused untick leaves the box unticked": (
        "js/proposal-review.js", "                rb.checked = true;", "                void 0;",
        lambda r: r["last"]["boxChecked"] is not True),
    "unticking the base leaves it where it was": (
        "js/price-lines-core.js", "    var next = id === base ? left[0] : base;", "    var next = base;",
        lambda r: r["untickBase"]["base_tab_id"] != "Polish"),
    "a ticked base bid stays an option": (
        "js/proposal-review.js",
        "            patch.base_tab_ids.forEach(id => { if (opts[id]) opts[id].is_option = false; });   // a base bid can't also be an option",
        "            void 0;",
        lambda r: r["tick"]["one"]["copyIsOption"] is not False),
    "rebuildPricing does not save the list": (
        "js/proposal-review.js", "      ...(Array.isArray(state.base_tab_ids) ? { base_tab_ids: state.base_tab_ids } : {}),", "",
        lambda r: r["tick"]["one"].get("saved") != ["Epoxy", "Copy1"]),
    "rebuildPricing leaves a refused base in the list": (
        "js/proposal-review.js",
        "    if ((state.base_tab_id || null) !== pickedBaseId && Array.isArray(state.base_tab_ids)) state.base_tab_ids = TWPrice.moveBaseId(state, pickedBaseId, state.base_tab_id);",
        "    void 0;",
        lambda r: r["rebuild"]["refused"]["base_tab_ids"] != ["Epoxy", "Copy1"]),
    "a child's boxes are live": (
        "js/proposal-review.js", "          const childOf = TWPrice.isProposalChild(state) ? state.proposal_of : \"\";",
        '          const childOf = "";',
        lambda r: not all(b["disabled"] for b in r["child"]["boxes"])),
    "a forced change on a child's box is honoured": (
        "js/proposal-review.js", "            if (TWPrice.isProposalChild(state)) return;", "            void 0;",
        lambda r: r["child"]["after"] != {"base_tab_id": "Copy1", "base_tab_ids": ["Copy1"]}),
    "the bid-bar radio leaves the old base ticked": (
        "js/estimate-review.js",
        "          state.base_tab_ids = TWPrice.moveBaseId(state, priorBaseId, state.base_tab_id, tabs.map(t => t.id));",
        "          void 0;",
        lambda r: r["bidBar"]["swap"]["base_tab_ids"] != ["Polish", "Copy1"]),
    "a deleted copy stays ticked": (
        "js/estimate-review.js", "  if (leftBases) state.base_tab_ids = state.base_tab_ids.filter(x => x !== id);", "  void 0;",
        lambda r: r["deleteTab"]["other"]["base_tab_ids"] != ["Epoxy"]),
    "deleting the base copy does not move the base to the next ticked sheet": (
        "js/estimate-review.js",
        "  if (wasBase) state.base_tab_id = (leftBases && leftBases.length) ? leftBases[0] : null;   // else fall back to auto-derive",
        "  if (wasBase) state.base_tab_id = null;",
        lambda r: r["deleteTab"]["base"]["base_tab_id"] != "Copy2"),
    "the snapshot carries no per-tab phase / costs / man-hours": (
        "js/estimate-review.js", "      phase: tabPhase(t.id), costs: costAt(t.id).costs, man_hours: costAt(t.id).mh,", "",
        lambda r: r["snapshot"]["Copy1"] != {"phase": 3900, "costs": 5200, "man_hours": 31.6}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, FILES)
    proc = run_node(HARNESS, frontend)
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name
