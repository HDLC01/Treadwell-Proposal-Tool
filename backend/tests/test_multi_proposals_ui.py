"""Several base bids on one estimate ("Create Multiple Proposals"), plan step 3: the v1 base picks.

On a spreadsheet draft the Proposal step's Pricing options card draws a Base-bid CHECKBOX per sheet: every ticked sheet is a
base bid, tagged "Base Bid N", and becomes its own proposal. The pricing base (base_tab_id) stays the one the page prices off,
is Base Bid 1, and is kept inside the ticked list (base_tab_ids). A tick adds a base bid; unticking the base moves it to the
next ticked sheet; the last one cannot be unticked. A child (a proposal the server made from another draft's estimate) shows
its base read-only and links to Base Bid 1's proposal. The Estimate step keeps the list consistent (its Base-bid boxes, deleting a
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
         "js/bid-engine.js", "js/index.js", "js/polish-intake.js", "js/polish-estimate.js"]


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
    assert c["move"] == {"swap": ["Polish", "Copy1"], "toNull": [], "ordered": ["Copy2", "Polish"],
                         "keepTicked": ["Copy1", "Epoxy"], "keepImplicit": ["Copy1", "Epoxy"],
                         "noKeepTicked": ["Copy1"], "keepUnticked": ["Polish", "Copy1"]}
    assert c["child"] == [True, False, False, False, False]


# ── the Estimate step ────────────────────────────────────────────────────────────────────────────
def test_the_bid_bar_boxes_follow_the_proposal_cards_rule(out):
    """The Estimate step's bar ticks base bids as the Proposal card does (2026-10-27): every change saves."""
    b = out["bidBar"]
    assert b["swap"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"], "persisted": 2}
    assert b["toTicked"] == {"base_tab_id": "Copy1", "base_tab_ids": ["Copy1"], "persisted": 1}, \
        "unticking the base hands it to the next ticked sheet"
    assert b["noList"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy", "Polish"], "persisted": 1}


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


# ── plan step 4: the proposal page's tabs, button and Estimate-changed strip ────────────────────
def _tabs(look):
    return [(t["id"], t["label"], t["open"], t["x"], t["stale"]) for t in look["tabs"]]


def test_the_strip_draws_a_tab_per_proposal_with_this_one_open(out):
    p = out["page"]["parent"]
    assert p["asked"] == ["P1"] and p["stripHidden"] is False
    assert _tabs(p) == [("P1", "Base Bid 1", True, False, False), ("C2", "Room <2>", False, True, True),
                        ("C3", "Base Bid 3", False, True, False)], "an unnamed child is called by its place"
    assert [t["selected"] for t in p["tabs"]] == ["true", "false", "false"]
    assert p["multi"] == {"hidden": False, "disabled": False, "text": "Create Multiple Proposals",
                          "title": "Make one proposal for each of the 3 ticked base bids. Each gets its own wording and its own options."}


def test_an_estimate_change_is_said_with_the_proposal_it_left_behind(out):
    p = out["page"]["parent"]
    assert p["note"]["hidden"] is False
    assert p["note"]["what"].startswith("Room <2> still has the figures from before. Refresh copies the estimate")


def test_a_draft_on_its_own_has_no_strip_and_an_off_button_that_says_why(out):
    a = out["page"]["alone"]
    assert a["before"]["stripHidden"] is True and a["before"]["tabs"] == [] and a["before"]["note"]["hidden"] is True
    assert a["before"]["multi"]["disabled"] is True and a["before"]["multi"]["hidden"] is False
    assert a["before"]["multi"]["title"].startswith("Tick two or more sheets as a Base bid")
    assert a["afterTick"]["disabled"] is False, "a second tick in the Pricing options card turns the button on"
    assert a["pressedOff"]["log"] == [], "an off button asks nothing"


def test_a_childs_page_hides_the_button_and_opens_on_its_own_tab(out):
    c = out["page"]["child"]
    assert c["multi"]["hidden"] is True
    assert [t["id"] for t in c["tabs"] if t["open"]] == ["C2"]


def test_a_tab_click_saves_then_opens_that_proposal(out):
    n = out["page"]["navigate"]
    assert n["self"] == [], "the open tab is not opened again"
    assert n["other"] == ["flush", "assign", "/proposal-review.html?d=C3"]


def test_create_saves_reads_the_version_asks_then_adopts_and_reloads(out):
    c = out["page"]["create"]
    assert c["pressed"] is True
    assert c["steps"] == ["setState", "flush", "readRow", "POST /api/draft/P1/proposals", "adopt", "reload"]
    assert c["body"] == {"draft_version": "V-1", "base_ids": ["Epoxy", "Copy1", "Polish"]}, \
        "the ticked base bids go in Base Bid order, this draft's own base first"
    assert c["look"]["multi"]["disabled"] is True, "the button stays shut while the page reloads"


def test_a_refused_create_says_the_servers_sentence_and_adopts_nothing(out):
    r = out["page"]["refused"]
    assert r["steps"] == ["setState", "flush", "readRow", "POST /api/draft/P1/proposals"]
    assert r["look"]["resync"] == {"hidden": False, "head": "No proposals were made.",
                                   "doIt": "Nothing changed. This project was saved again after this page read it."}
    assert r["look"]["multi"]["disabled"] is False and r["look"]["multi"]["text"] == "Create Multiple Proposals"
    u = out["page"]["unsaved"]
    assert u["steps"] == ["setState", "flush"], "a save that did not land asks nothing of the server"
    assert u["look"]["resync"]["doIt"].startswith("This page's changes did not reach the server")


def test_refresh_runs_the_same_sequence_against_the_refresh_route(out):
    r = out["page"]["refresh"]
    assert r["steps"] == ["setState", "flush", "readRow", "POST /api/draft/C2/proposals/refresh", "adopt", "reload"]
    assert r["body"] == {"draft_version": "V-1"}
    s = out["page"]["refreshSkipped"]
    assert s["steps"] == ["setState", "flush", "readRow", "POST /api/draft/P1/proposals/refresh"], \
        "this page's draft did not change, so it says what was skipped instead of reloading"
    assert s["look"]["note"]["what"].startswith("Refreshed, except Room <2>: its sheet is not on the estimate any more")
    f = out["page"]["refreshRefused"]
    assert "adopt" not in f["steps"] and f["look"]["note"]["what"] == "Not refreshed. Nothing changed."


def test_a_double_click_on_the_open_tab_renames_it(out):
    r = out["page"]["rename"]
    assert r["other"] == [False, False, False], "another tab is not renamed from here"
    assert r["open"] == [False, True, False]
    assert r["fetches"] == [["POST", "/api/draft/C2/scope", {"label": "Lab 2", "rename": True}]]
    assert r["local"] == [[{"scope_group": {"id": "G1", "label": "Lab 2"}}, {"alreadyOnServer": True}]]
    assert r["labels"] == ["Base Bid 1", "Lab 2", "Base Bid 3"]
    assert r["escape"] == {"fetches": 0, "renaming": False}


def test_the_x_asks_then_sends_a_child_to_the_trash(out):
    d = out["page"]["del"]
    assert d["steps"] == ["confirm", "DELETE /api/draft/C3"] and d["tabs"] == ["P1", "C2"]
    assert d["cancel"] == {"steps": ["confirm"], "tabs": ["P1", "C2", "C3"]}
    assert d["self"]["steps"] == ["confirm", "DELETE /api/draft/C3", "assign"]
    assert d["self"]["went"] == ["/proposal-review.html?d=P1"], "a child that deleted itself goes to Base Bid 1"


def test_a_childs_intake_and_estimate_links_open_its_parents(out):
    links = out["page"]["links"]
    assert links["child"] == ["/?edit=1&d=P1", "/estimate-review.html?d=P1", "/polish-estimate.html?d=P1",
                              "/polish-intake.html?d=P1", None, None]
    assert links["parent"] == [None] * 6


def test_shared_js_sends_a_child_to_its_parent_and_reads_the_list(out):
    s = out["shared"]
    assert s["child"] == {"answer": True, "replaced": ["/estimate-review.html?d=P1"]}
    assert s["childQuery"] == {"answer": True, "replaced": ["/?edit=1&d=P1"]}
    assert s["parent"] == {"answer": False, "replaced": []}
    assert s["notThisDraft"] == {"answer": False, "replaced": []}, "another project's blob is not acted on"
    assert s["read"]["members"] == ["P1", "C2", "C3"] and s["read"]["other"] is True
    assert s["read"]["asked"] == ["/api/draft/P1/proposals", "/api/draft/C2/proposals"]
    assert s["read"]["missing"] is None


def test_every_intake_and_estimate_page_stops_on_a_child(out):
    """Each page's own guard statement, run: it asks shared.js's guard at its own path, and a yes stops the page there
    (the rest of the script, which would save, does not run); a no lets it go on."""
    g = out["guards"]
    assert g == {
        "js/estimate-review.js": {"child": ["stopped", ["/estimate-review.html"]], "other": ["continued", ["/estimate-review.html"]]},
        "js/index.js": {"child": ["stopped", ["/?edit=1"]], "other": ["continued", ["/?edit=1"]]},
        "js/polish-intake.js": {"child": ["stopped", ["/polish-intake.html"]], "other": ["continued", ["/polish-intake.html"]]},
        "js/polish-estimate.js": {"child": ["stopped", ["/polish-estimate.html"]], "other": ["continued", ["/polish-estimate.html"]]},
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
    "the bid-bar boxes do not keep the ticked list": (
        "js/estimate-review.js", "      state.base_tab_ids = patch.base_tab_ids;", "      void 0;",
        lambda r: r["bidBar"]["swap"]["base_tab_ids"] != ["Polish", "Copy1"]),
    "the bid-bar boxes do not move the base on an untick": (
        "js/estimate-review.js", "      state.base_tab_id = patch.base_tab_id;", "      void 0;",
        lambda r: r["bidBar"]["toTicked"]["base_tab_id"] != "Copy1"),
    "moveBaseId never swaps": (
        "js/price-lines-core.js",
        "    var ids = raw.map(function (x) { return x === from ? to : (swap && x === to ? from : x); });",
        "    var ids = raw.map(function (x) { return x === from ? to : x; });",
        lambda r: r["core"]["move"]["keepTicked"] != ["Copy1", "Epoxy"]),
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
    # plan step 4: the proposal page
    "the strip is never drawn": (
        "js/proposal-review.js", '      if (ms.length < 2) { strip.hidden = true; strip.innerHTML = ""; return; }',
        '      if (true) { strip.hidden = true; strip.innerHTML = ""; return; }',
        lambda r: r["page"]["parent"]["stripHidden"] is not True),
    "no tab is drawn open": (
        "js/proposal-review.js", "        const open = m.id === id;", "        const open = false;",
        lambda r: not any(t["open"] for t in r["page"]["parent"]["tabs"])),
    "Base Bid 1 gets an x": (
        "js/proposal-review.js", '(m.is_parent ? "" : `<button type="button" class="pt-x"', '(false ? "" : `<button type="button" class="pt-x"',
        lambda r: r["page"]["parent"]["tabs"][0]["x"] is True),
    "a stale proposal is not said": (
        "js/proposal-review.js", "      const stale = members().filter((m) => m.stale);", "      const stale = [];",
        lambda r: r["page"]["parent"]["note"]["hidden"] is True),
    "the button ignores how many base bids are ticked": (
        "js/proposal-review.js", "      multi.disabled = child || busy || n < 2;", "      multi.disabled = child || busy;",
        lambda r: r["page"]["alone"]["before"]["multi"]["disabled"] is False),
    "the button shows on a child": (
        "js/proposal-review.js", "      multi.hidden = child;", "      multi.hidden = false;",
        lambda r: r["page"]["child"]["multi"]["hidden"] is False),
    "a tick does not repaint the button": (
        "js/proposal-review.js", '    if (panel && panel.addEventListener) panel.addEventListener("change", paintMulti);', "    void 0;",
        lambda r: r["page"]["alone"]["afterTick"]["disabled"] is True),
    "create does not save first": (
        "js/proposal-review.js", "      const saved = await TW.flushState();", "      const saved = true;",
        lambda r: "flush" not in r["page"]["create"]["steps"]),
    "create asks without the version it read": (
        "js/proposal-review.js", "Object.assign({ draft_version: row.version }, body || {})", "Object.assign({}, body || {})",
        lambda r: "draft_version" not in (r["page"]["create"]["body"] or {})),
    "create sends the ticked sheets out of order": (
        "js/proposal-review.js", "      const ids = TWPrice.baseIds(state);", "      const ids = (state.base_tab_ids || []).slice().reverse();",
        lambda r: (r["page"]["create"]["body"] or {}).get("base_ids") != ["Epoxy", "Copy1", "Polish"]),
    "the server's copy is not adopted before the reload": (
        "js/proposal-review.js", "      const adopted = TW.useServerCopy ? await TW.useServerCopy() : false;", "      const adopted = true;",
        lambda r: "adopt" not in r["page"]["create"]["steps"]),
    "a refused create is not said": (
        "js/proposal-review.js", '        repaintNote("No proposals were made.", (err && err.message) || "Try again.");', "        void 0;",
        lambda r: r["page"]["refused"]["look"]["resync"]["hidden"] is True),
    "refresh asks the create route": (
        "js/proposal-review.js", '        const j = await post("/proposals/refresh", {}, "refreshed");',
        '        const j = await post("/proposals", {}, "refreshed");',
        lambda r: "POST /api/draft/C2/proposals/refresh" not in r["page"]["refresh"]["steps"]),
    "a skipped refresh reloads and says nothing": (
        "js/proposal-review.js", "        if (skipped.length && (j.refreshed || []).indexOf(id) < 0) {", "        if (false) {",
        lambda r: "adopt" in r["page"]["refreshSkipped"]["steps"]),
    "a tab click leaves without saving": (
        "js/proposal-review.js", "      try { await TW.flushState(); } catch {}", "      void 0;",
        lambda r: r["page"]["navigate"]["other"][:1] != ["flush"]),
    "any tab can be renamed": (
        "js/proposal-review.js", "{ if (b.dataset.ptOpen === id) startRename(b.dataset.ptOpen); }", "{ startRename(b.dataset.ptOpen); }",
        lambda r: any(r["page"]["rename"]["other"])),
    "a rename of this page's draft is not remembered": (
        "js/proposal-review.js", "if (m.id === id && TW.setLocalState) TW.setLocalState(", "if (false) TW.setLocalState(",
        lambda r: r["page"]["rename"]["local"] == []),
    "the x deletes without asking": (
        "js/proposal-review.js", "      const ok = await TW.confirmDanger({", "      const ok = true; void ({",
        lambda r: "DELETE /api/draft/C3" in r["page"]["del"]["cancel"]["steps"]),
    "a child that deleted itself stays on its page": (
        "js/proposal-review.js", "      if (pid === id) { window.location.assign(pageOf(view.parent_id)); return; }", "      void 0;",
        lambda r: r["page"]["del"]["self"]["went"] != ["/proposal-review.html?d=P1"]),
    "a child's links keep its own id": (
        "js/proposal-review.js", '    u.searchParams.set("d", state.proposal_of);', "    void 0;",
        lambda r: r["page"]["links"]["child"][1] != "/estimate-review.html?d=P1"),
    "the redirect ignores whose blob it is": (
        "shared.js", "    if (!parent || !isThisDraft(blob)) return false;", "    if (!parent) return false;",
        lambda r: r["shared"]["notThisDraft"]["answer"] is not False),
    "the redirect never moves": (
        "shared.js", '    window.location.replace(path + (path.indexOf("?") >= 0 ? "&" : "?") + "d=" + encodeURIComponent(parent));',
        "    void 0;",
        lambda r: r["shared"]["child"]["replaced"] != ["/estimate-review.html?d=P1"]),
    "the estimate page does not stop a child": (
        "js/estimate-review.js",
        'if (typeof TW.redirectProposalChild === "function" && TW.redirectProposalChild("/estimate-review.html")) {',
        "if (false) {",
        lambda r: r["guards"]["js/estimate-review.js"] is None),
    "the v2 estimate page does not stop a child": (
        "js/polish-estimate.js", 'TW.redirectProposalChild("/polish-estimate.html")) return;', "false) return;",
        lambda r: r["guards"]["js/polish-estimate.js"] is None),
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
