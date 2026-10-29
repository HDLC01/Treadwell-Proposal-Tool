"""Several base bids, ticked on the Estimate step's "Base bid & options" bar.

Hanz, 2026-10-27: "we must be able to set a base bid in the excel sheet tab options at the top already". Picking
several base bids (Base Bid 1, 2, 3) for Create Multiple Proposals was only on the Proposal step's Pricing options
card; the Estimate bar had one round radio per sheet. The bar now draws the card's control: a Base-bid CHECKBOX per
sheet that may be a base, tagged "Base Bid N" as the card tags the same sheet, under the card's rule
(TWPrice.toggleBaseId): a tick adds a base bid, unticking the pricing base moves it to the next ticked sheet, the
last one is refused. An option-only sheet (Seal) has no box, the combo's combined chip is one base on its own, and a
child's boxes are disabled. A tick only adds a base bid, so the one-click base move the radio gave is a "Make Base
Bid 1" button on each ticked sheet that is not the pricing base (TWPrice.moveBaseId with `keep`, then the same
base-change path a box takes).

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


def test_every_base_able_sheet_has_a_base_bid_segment(out):
    # The Base segment of each sheet's Base bid | Option | Off switch (one radio group per sheet).
    m = out["multiBase"]
    assert m["boxes"] == [
        {"id": "Epoxy", "type": "radio", "checked": True, "disabled": False},
        {"id": "Polish", "type": "radio", "checked": False, "disabled": False},
        {"id": "Copy1", "type": "radio", "checked": True, "disabled": False},
    ]


def test_the_tags_read_as_the_proposal_card_reads_them(out):
    m = out["multiBase"]
    assert m["tags"] == {"Epoxy": "Base Bid 1", "Polish": "", "Copy1": "Base Bid 2"}
    assert m["tags"] == m["proposalLabels"], "Base Bid N differs between the two steps"
    assert m["stripLabels"] == {"Epoxy": "Base Bid 1", "Copy1": "Base Bid 2"}
    assert out["multiFreshCopy"]["copyTag"] == "Base Bid 2", "a copy not priced yet lost its number"


def test_a_base_bid_shows_no_option_controls(out):
    assert out["multiBase"]["copyOffersOption"] is False
    assert out["multiBase"]["polishOffersOption"] is True


def test_seal_has_no_base_bid_box(out):
    assert out["multiBase"]["sealHasBox"] is False


def test_the_legend_explains_several_base_bids(out):
    assert HINT in out["multiBase"]["hint"]
    assert "<b>Option</b> = listed inside the proposal under the base" in out["multiBase"]["hint"]
    assert "<b>Off</b> = not on the proposal" in out["multiBase"]["hint"]


# ── one switch per sheet: Base bid | Option | Off ───────────────────────────────────────────────────
# Hanz, 2026-10-27: "you removed the functionality of a sheet to be an option in one proposal" ... "I couldn't add more
# base bids as well to create 3 or more proposals" ... "There should be an option to make multiple base bids and there
# should be an option to make it an option in one proposal, get it?"
SWITCH_REFUSED = "A proposal needs a base bid. Make another sheet a Base bid first, then switch this one."


def test_every_sheet_has_the_three_way_switch_and_seal_has_no_base_bid(out):
    s = out["sw"]
    assert s["segs"] == {"Epoxy": ["bb-base", "bb-isopt", "bb-off"], "Polish": ["bb-base", "bb-isopt", "bb-off"],
                         "Seal": ["bb-isopt", "bb-off"]}
    assert s["roles"] == {"Epoxy": "bb-base", "Polish": "bb-off"}


def test_base_plus_option_is_one_proposal_with_the_option_in_it(out):
    o = out["sw"]["optionIn"]
    assert o["base_tab_id"] == "Epoxy" and o["ids"] == ["Epoxy"] and o["base_tab_ids"] is None, o
    assert o["polish"] is True and o["role"] == "bb-isopt" and o["controls"] is True and o["persisted"] == 1
    assert o["basePicks"] == []


def test_option_to_base_bid_clears_the_option(out):
    o = out["sw"]["optToBase"]
    assert o["base_tab_ids"] == ["Epoxy", "Polish"] and o["polish"] is False and o["role"] == "bb-base"
    assert o["tag"] == "Base Bid 2" and o["persisted"] == 1


def test_three_base_bids_with_a_sheet_from_behind_show_other_sheets(out):
    t = out["sw"]["three"]
    assert t["showLabel"] == "+ Show other sheets (Gyp)" and t["gypBefore"] is False
    assert t["base_tab_ids"] == ["Epoxy", "Polish", "Gyp"]
    assert t["tags"] == {"Epoxy": "Base Bid 1", "Polish": "Base Bid 2", "Gyp": "Base Bid 3"}


def test_a_base_bid_switched_to_option_leaves_the_base_bids(out):
    b = out["sw"]["baseToOption"]
    assert b["base_tab_id"] == "Epoxy" and b["base_tab_ids"] == ["Epoxy"] and b["copy"] is True
    assert b["role"] == "bb-isopt" and b["persisted"] == 1 and b["basePicks"] == []


def test_the_pricing_base_switched_away_hands_base_bid_1_on(out):
    p = out["sw"]["pricingToOption"]
    assert p["base_tab_id"] == "Copy1" and p["base_tab_ids"] == ["Copy1"] and p["epoxy"] is True
    assert p["basePicks"] == [["Epoxy", "Copy1"]] and p["persisted"] == 1 and p["role"] == "bb-isopt"
    f = out["sw"]["pricingToOff"]
    assert f["base_tab_id"] == "Copy1" and f["epoxy"] is False and f["role"] == "bb-off"
    assert f["basePicks"] == [["Epoxy", "Copy1"]]


def test_an_option_switched_off(out):
    o = out["sw"]["optionOff"]
    assert o["polish"] is False and o["role"] == "bb-off" and o["persisted"] == 1


def test_the_last_base_bid_cannot_be_switched_off_or_to_option(out):
    last = out["sw"]["last"]
    for k in ("off", "option"):
        assert last[k]["base_tab_id"] == "Epoxy" and last[k]["persisted"] == 0, last[k]
        assert last[k]["epoxy"] is False and last[k]["role"] == "bb-base", last[k]
    assert last["off"]["hint"] == SWITCH_REFUSED


def test_a_childs_base_segments_are_read_only_and_its_options_are_its_own(out):
    c = out["sw"]["child"]
    assert c["segsCopy"] == ["bb-base:disabled", "bb-isopt:disabled", "bb-off:disabled"]
    assert c["segsEpoxy"] == ["bb-base:disabled", "bb-isopt", "bb-off"]
    assert c["epoxy"] is True and c["copy"] is False
    assert c["base_tab_id"] == "Copy1" and c["base_tab_ids"] == ["Copy1"] and c["basePicks"] == []
    t = out["sw"]["childTwo"]
    assert t["base_tab_ids"] == ["Copy1", "Polish"] and t["polish"] is False and t["persisted"] == 0, \
        "a child's base bids are its parent's: Option forced at one changes nothing"


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
    assert c["gypBox"] == {"id": "Gyp", "type": "radio", "checked": True, "disabled": False}
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


def test_a_ticked_sheet_that_is_not_the_base_offers_make_base_bid_1(out):
    m = out["makeBase"]
    assert m["buttons"] == ["Copy1"], "only a ticked sheet that is not the pricing base offers the move"
    assert m["comboButtons"] == [], "a combined base has no ticked sheet to move to"


def test_make_base_bid_1_moves_the_base_in_one_click(out):
    # The finding's walk: Polish ticked out of habit is Base Bid 2 and Epoxy is still the price ...
    m = out["makeBase"]
    assert m["afterTick"] == {"buttons": ["Polish"], "base_tab_id": "Epoxy"}
    # ... and one click on Polish's "Make Base Bid 1" makes Polish the price, Epoxy staying a base bid.
    h = m["habit"]
    assert h["base_tab_id"] == "Polish" and h["base_tab_ids"] == ["Polish", "Epoxy"], h
    assert h["basePicks"] == [["Epoxy", "Polish"]], "the move must run the base-change path (applyBasePick)"
    assert h["persistedByClick"] == 1, "the move must price and save (persistTabState)"
    assert h["polishIsOption"] is False
    assert h["tags"] == {"Epoxy": "Base Bid 2", "Polish": "Base Bid 1"}
    assert h["buttons"] == ["Epoxy"], "the old base now offers the move back"


def test_make_base_bid_1_picks_any_ticked_sheet_not_only_the_next(out):
    t = out["makeBase"]["three"]
    assert t["base_tab_id"] == "Copy1" and t["base_tab_ids"] == ["Copy1", "Epoxy", "Polish"], t
    assert t["basePicks"] == [["Epoxy", "Copy1"]] and t["persistedByClick"] == 1


def test_a_child_has_no_make_base_bid_1(out):
    c = out["makeBase"]["child"]
    assert c["buttons"] == []
    assert c["base_tab_id"] == "Copy1" and c["persistedByClick"] == 0 and c["basePicks"] == [], c


ER = "js/estimate-review.js"
BREAKS = {
    "the combined chip's box is a radio again": (
        ER, '    `<label class="bb-baselbl" title="Base bid: tick to give this its own proposal"><input type="checkbox" class="bb-base" value="${_escBB(val)}"${checked ? " checked" : ""}${childLocked ? " disabled" : ""}> <span class="bb-name">${_escBB(label)}</span></label>`;',
        '    `<label class="bb-baselbl"><input type="radio" name="bb-base" class="bb-base" value="${_escBB(val)}"${checked ? " checked" : ""}${childLocked ? " disabled" : ""}> <span class="bb-name">${_escBB(label)}</span></label>`;',
        lambda r: (r["multiCombo"]["combinedBox"] or {}).get("type") != "checkbox"),
    "the switch has no Option segment": (
        ER, '      one("base", "bb-base", "Base bid") + one("option", "bb-isopt", "Option") + one("off", "bb-off", "Off") + `</span>`;',
        '      one("base", "bb-base", "Base bid") + one("off", "bb-off", "Off") + `</span>`;',
        lambda r: r["sw"]["segs"]["Epoxy"] != ["bb-base", "bb-isopt", "bb-off"]),
    "Seal gets a Base segment": (
        ER, '    const segs = inCombined ? ["base"] : (optOnly ? ["option", "off"] : ["base", "option", "off"]);',
        '    const segs = inCombined ? ["base"] : ["base", "option", "off"];',
        lambda r: r["sw"]["segs"]["Seal"] != ["bb-isopt", "bb-off"]),
    "an Option opens no controls": (
        ER, "    } else if (isOpt) {", "    } else if (false) {",
        lambda r: r["sw"]["optionIn"]["controls"] is not True),
    "a base bid switched to Option stays a base bid": (
        ER, "      if (TWPrice.baseIds(state, order).indexOf(wrap.dataset.id) >= 0) {", "      if (false) {",
        lambda r: r["sw"]["baseToOption"]["base_tab_ids"] != ["Epoxy"] or r["sw"]["pricingToOption"]["base_tab_id"] != "Copy1"),
    "leaving the base bids skips the base-change path": (
        ER, "        applyBasePatch(patch, priorBaseId);   // redraws, prices and saves (is_option with it)", "        void 0;",
        lambda r: r["sw"]["pricingToOption"]["base_tab_id"] != "Copy1" or r["sw"]["pricingToOption"]["basePicks"] != [["Epoxy", "Copy1"]]),
    "Off does not clear the option": (
        ER, "        o.is_option = false;", "        void 0;",
        lambda r: r["sw"]["optionOff"]["polish"] is not False),
    "the last base bid can be switched off": (
        ER, "        if (!patch) {", "        if (false) {",
        lambda r: r["sw"]["last"]["off"]["role"] != "bb-base" or r["sw"]["last"]["off"]["persisted"] != 0),
    "a refused switch says nothing": (
        ER, '            hint.innerHTML = "A proposal needs a base bid. Make another sheet a Base bid first, then switch this one.";',
        "            void 0;",
        lambda r: r["sw"]["last"]["off"]["hint"] != SWITCH_REFUSED),
    "a child's base bid switch is live": (
        ER, '    const lock = childLocked ? (isBase ? ["base", "option", "off"] : ["base"]) : [];',
        '    const lock = childLocked ? ["base"] : [];',
        lambda r: r["sw"]["child"]["segsCopy"] != ["bb-base:disabled", "bb-isopt:disabled", "bb-off:disabled"]),
    "a forced Option on a child's base bid is honoured": (
        ER, "        patch = TWPrice.isProposalChild(state) ? null : TWPrice.toggleBaseId(state, wrap.dataset.id, false, order);",
        "        patch = TWPrice.toggleBaseId(state, wrap.dataset.id, false, order);",
        lambda r: r["sw"]["childTwo"]["base_tab_ids"] != ["Copy1", "Polish"] or r["sw"]["childTwo"]["polish"] is not False),
    "the other sheets stay hidden behind an unnamed button": (
        ER, '      : "+ Show other sheets (" + kinds.slice(0, 3).join(", ") + (kinds.length > 3 ? "…" : "") + ")";',
        '      : "+ Add another system";',
        lambda r: r["sw"]["three"]["showLabel"] != "+ Show other sheets (Gyp)"),
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
        ER, "    state.base_tab_ids = patch.base_tab_ids;", "    void 0;",
        lambda r: r["multiTick"]["base_tab_ids"] != ["Epoxy", "Polish", "Copy1"]),
    "the base-change path does not run": (
        ER, "    if (state.base_tab_id !== priorBaseId) {", "    if (false) {",
        lambda r: r["multiUntickBase"]["basePicks"] != [["Epoxy", "Polish"]]),
    "a ticked base bid stays an option": (
        ER, "    patch.base_tab_ids.forEach(id => { if (state.tab_opts[id]) state.tab_opts[id].is_option = false; });  // base ≠ option",
        "    void 0;",
        lambda r: r["multiTick"]["polishIsOption"] is not False),
    "a tick is not saved": (
        ER, "    persistTabState();   // a base bid change: priced and saved", "    void 0;",
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
    "no Make Base Bid 1 button": (
        ER, "      if (baseId && t.id !== baseId && !childLocked) {", "      if (false) {",
        lambda r: r["makeBase"]["buttons"] != ["Copy1"]),
    "Make Base Bid 1 on a child": (
        ER, "      if (baseId && t.id !== baseId && !childLocked) {",
        "      if (baseId && t.id !== baseId) {",
        lambda r: r["makeBase"]["child"]["buttons"] != []),
    "Make Base Bid 1 does nothing": (
        ER, '    if (e.target.classList.contains("bb-mkbase")) {   // "Make Base Bid 1" on a ticked sheet',
        "    if (false) {",
        lambda r: r["makeBase"]["habit"]["base_tab_id"] != "Polish"),
    "Make Base Bid 1 drops the old base": (
        ER, "                       base_tab_ids: TWPrice.moveBaseId(state, priorBaseId, to, tabs.map(t => t.id), true) },",
        "                       base_tab_ids: TWPrice.moveBaseId(state, priorBaseId, to, tabs.map(t => t.id), false) },",
        lambda r: r["makeBase"]["habit"]["base_tab_ids"] != ["Polish", "Epoxy"]),
    "a forced Make Base Bid 1 on a child is honoured": (
        ER, "      if (TWPrice.isProposalChild(state) || !to) return;   // a child's base is its parent's",
        "      if (!to) return;",
        lambda r: r["makeBase"]["child"]["base_tab_id"] != "Copy1" or r["makeBase"]["child"]["persistedByClick"] != 0),
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
