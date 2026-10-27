"""Several base bids, ticked on the Estimate step's "Base bid & options" bar.

Hanz, 2026-10-27: "we must be able to set a base bid in the excel sheet tab options at the top already". Picking
several base bids (Base Bid 1, 2, 3) for Create Multiple Proposals was only on the Proposal step's Pricing options
card; the Estimate bar had one round radio per sheet. The bar now draws the card's control: a Base-bid CHECKBOX per
sheet that may be a base, tagged "Base Bid N" as the card tags the same sheet, under the card's rule
(TWPrice.toggleBaseId): a tick adds a base bid, unticking the pricing base moves it to the next ticked sheet, the
last one is refused. An option-only sheet (Seal) has no box, the combo's combined chip is one base on its own, and a
child's boxes are disabled.

Run, not read: js/combo-base-harness.js executes the real renderBidOptions and the real #bid-bar change handler out
of estimate-review.js, with the real price-lines-core.js. The BREAKS at the bottom prove each check goes red when the
line it pins is taken out.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "combo-base-harness.js"
FILES = ["js/estimate-review.js", "js/price-lines-core.js"]
HINT = "Create Multiple Proposals"
REFUSED = "A proposal needs a base bid"


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def out():
    require_node()
    return run()


def test_every_base_able_sheet_has_a_base_bid_checkbox(out):
    m = out["multiBase"]
    assert m["boxes"] == [
        {"id": "Epoxy", "type": "checkbox", "checked": True, "disabled": False},
        {"id": "Polish", "type": "checkbox", "checked": False, "disabled": False},
        {"id": "Copy1", "type": "checkbox", "checked": True, "disabled": False},
    ]


def test_the_tags_read_as_the_proposal_card_reads_them(out):
    m = out["multiBase"]
    assert m["tags"] == {"Epoxy": "Base Bid 1", "Polish": "", "Copy1": "Base Bid 2"}
    assert m["tags"] == m["proposalLabels"], "Base Bid N differs between the two steps"
    assert m["stripLabels"] == {"Epoxy": "Base Bid 1", "Copy1": "Base Bid 2"}
    assert out["multiFreshCopy"]["copyTag"] == "Base Bid 2", "a copy not priced yet lost its number"


def test_a_ticked_sheet_shows_no_option_controls(out):
    assert out["multiBase"]["copyOffersOption"] is False
    assert out["multiBase"]["polishOffersOption"] is True


def test_seal_has_no_base_bid_box(out):
    assert out["multiBase"]["sealHasBox"] is False


def test_the_legend_explains_several_base_bids(out):
    assert HINT in out["multiBase"]["hint"]
    assert "add&nbsp;as&nbsp;option" in out["multiBase"]["hint"]


def test_a_tick_adds_a_base_bid_and_takes_it_off_the_options(out):
    t = out["multiTick"]
    assert t["base_tab_id"] == "Epoxy" and t["base_tab_ids"] == ["Epoxy", "Polish", "Copy1"], t
    assert t["polishIsOption"] is False
    assert t["persisted"] == 1, "a tick that only changes the list must still save (persistTabState)"
    assert t["basePicks"] == [], "the pricing base did not move, so the base-change path must not run"
    assert t["tags"] == {"Epoxy": "Base Bid 1", "Polish": "Base Bid 2", "Copy1": "Base Bid 3"}
    assert out["multiTickFresh"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy", "Copy1"], "persisted": 1,
                                     "basePicks": []}


def test_unticking_the_base_moves_it_by_the_base_change_path(out):
    u = out["multiUntickBase"]
    assert u == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"], "persisted": 1,
                 "basePicks": [["Epoxy", "Polish"]]}
    assert out["multiUntickOther"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy"], "persisted": 1,
                                       "basePicks": []}


def test_the_last_base_bid_cannot_be_unticked(out):
    last = out["multiLast"]
    assert last["base_tab_id"] == "Epoxy" and last["base_tab_ids"] is None and last["persisted"] == 0, last
    assert last["boxChecked"] is True, "the refused box must go back on"
    assert REFUSED in last["hint"]


def test_a_ticked_cross_type_sheet_stays_on_the_bar(out):
    c = out["multiCrossType"]
    assert c["gypBox"] == {"id": "Gyp", "type": "checkbox", "checked": True, "disabled": False}
    assert c["gypTag"] == "Base Bid 2"


def test_the_combos_combined_chip_is_one_base_on_its_own(out):
    c = out["multiCombo"]
    assert c["combinedBox"] == {"id": "", "type": "checkbox", "checked": True, "disabled": False}
    assert c["epoxyBox"]["checked"] is False
    assert c["tick"] == {"base_tab_id": "Epoxy", "base_tab_ids": ["Epoxy"], "persisted": 1,
                         "basePicks": [[None, "Epoxy"]]}
    assert c["back"] == {"base_tab_id": None, "base_tab_ids": [], "persisted": 1, "basePicks": [["Epoxy", None]]}
    assert c["untick"]["base_tab_id"] is None and c["untick"]["persisted"] == 0 and c["untick"]["boxChecked"] is True


def test_a_childs_boxes_are_disabled_and_change_nothing(out):
    c = out["multiChild"]
    assert c["boxes"] and all(b["disabled"] for b in c["boxes"]), c["boxes"]
    assert c["base_tab_id"] == "Copy1" and c["base_tab_ids"] == ["Copy1"] and c["persisted"] == 0, c


ER = "js/estimate-review.js"
BREAKS = {
    "the box is a radio again": (
        ER, '    `<label class="bb-baselbl" title="Base bid: tick to give this its own proposal"><input type="checkbox" class="bb-base" value="${_escBB(val)}"${checked ? " checked" : ""}${childLocked ? " disabled" : ""}> <span class="bb-name">${_escBB(label)}</span></label>`;',
        '    `<label class="bb-baselbl"><input type="radio" name="bb-base" class="bb-base" value="${_escBB(val)}"${checked ? " checked" : ""}${childLocked ? " disabled" : ""}> <span class="bb-name">${_escBB(label)}</span></label>`;',
        lambda r: [b["type"] for b in r["multiBase"]["boxes"]] != ["checkbox"] * 3),
    "a ticked sheet is not drawn ticked": (
        ER, "      && (baseId === t.id || soloBase === t.id || tickIds.indexOf(t.id) >= 0);",
        "      && (baseId === t.id || soloBase === t.id);",
        lambda r: r["multiBase"]["tags"]["Copy1"] != "Base Bid 2" or r["multiBase"]["copyOffersOption"] is not False),
    "the tag is not the Proposal card's label": (
        ER, '      inner += `<span class="bb-tag">${_escBB(TWPrice.baseLabelFor(state, t.id, tabOrder) || "base bid")}</span>`;',
        '      inner += `<span class="bb-tag">base bid</span>`;',
        lambda r: r["multiBase"]["tags"] != r["multiBase"]["proposalLabels"]),
    "the numbering ignores the tab strip": (
        ER, "  const tickIds = TWPrice.baseIds(state, tabOrder);", "  const tickIds = TWPrice.baseIds(state);",
        lambda r: r["multiFreshCopy"]["copyTag"] != "Base Bid 2"),
    "a ticked cross-type sheet hides": (
        ER, "    t.id === baseId || tickIds.indexOf(t.id) >= 0 ||", "    t.id === baseId ||",
        lambda r: r["multiCrossType"]["gypBox"] is None),
    "an untick reads as a tick": (
        ER, "      const patch = TWPrice.toggleBaseId(state, el.value, el.checked, tabs.map(t => t.id));",
        "      const patch = TWPrice.toggleBaseId(state, el.value, true, tabs.map(t => t.id));",
        lambda r: r["multiUntickBase"]["base_tab_id"] != "Polish"),
    "the list is not kept": (
        ER, "      state.base_tab_ids = patch.base_tab_ids;", "      void 0;",
        lambda r: r["multiTick"]["base_tab_ids"] != ["Epoxy", "Polish", "Copy1"]),
    "the base-change path does not run": (
        ER, "      if (state.base_tab_id !== priorBaseId) {", "      if (false) {",
        lambda r: r["multiUntickBase"]["basePicks"] != [["Epoxy", "Polish"]]),
    "a ticked base bid stays an option": (
        ER, "      patch.base_tab_ids.forEach(id => { if (state.tab_opts[id]) state.tab_opts[id].is_option = false; });  // base ≠ option",
        "      void 0;",
        lambda r: r["multiTick"]["polishIsOption"] is not False),
    "a tick is not saved": (
        ER, "      persistTabState();", "      void 0;",
        lambda r: r["multiTick"]["persisted"] != 1),
    "a refused untick leaves the box off": (
        ER, "          el.checked = true;", "          void 0;",
        lambda r: r["multiLast"]["boxChecked"] is not True),
    "a refused untick says nothing": (
        ER, '          if (hint) hint.innerHTML = "A proposal needs a base bid. Tick another sheet first, then untick this one.";',
        "          void 0;",
        lambda r: REFUSED not in r["multiLast"]["hint"]),
    "the legend is not redrawn": (
        ER, "  } else if (hint) {", "  } else if (false) {",
        lambda r: HINT not in r["multiBase"]["hint"]),
    "a child's boxes are live": (
        ER, "  const childLocked = TWPrice.isProposalChild(state);", "  const childLocked = false;",
        lambda r: not all(b["disabled"] for b in r["multiChild"]["boxes"])),
    "a forced change on a child's box is honoured": (
        ER, "      if (TWPrice.isProposalChild(state)) return;", "      void 0;",
        lambda r: r["multiChild"]["base_tab_ids"] != ["Copy1"] or r["multiChild"]["persisted"] != 0),
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
