"""Sheets phase 4: the Proposal step reads the base, the options and the deducts a v2 estimate saved.

WHAT CHANGED. A v2 estimate can now hold copies of a sheet and sheets of any type, pick a base bid, and put the others on
the proposal as options (a total, or an Add / Deduct). It saves all that as a price snapshot: `priced_tabs`, each tab marked
`v2: true`, with `base_tab_id`, `tab_opts` and the lump sum. The Proposal step already prices from those keys
(rebuildPricing) and the document already prints options from the rooms that produces (main._build_options), so the options
and deducts print with no new code. What this phase adds is the one thing that would print a wrong price:

  * THE BASE IS PICKED ON THE ESTIMATE. Each v2 option is priced with its own travel, beside the base it was priced against,
    so a base switched on the Proposal step would print a price nobody worked out. On a draft whose every priced tab is v2 the
    panel's base radios are read-only, they say "Pick the base bid on the estimate" and link to it. An option on or off, total or
    add / deduct, the description and the notes stay editable and write the same tab_opts keys. A Seal option stays a total.
    A draft from the spreadsheet is not touched: its radios are live, as they were.

PROVEN BY EXECUTION. Nothing here greps the page for what it says it does.
  1. THE DRAFTS are the real model's (tests/js/v2-proposal-snapshot-harness.js builds a bid with copySection, activateSection and
     pickBase and saves it through composePricingSnapshot): a Polish base with a cheaper Polish copy as a Deduct, an Epoxy
     alternate as a Total and a Seal option, then the same bid with the Epoxy sheet, the pair, and the copy made the base.
  2. THE PANEL runs the page's own renderProposalExtras and rebuildPricing over those drafts (tests/js/v2-options-panel-harness.js)
     and fires changes at the controls it drew.
  3. THE DOCUMENT is rendered from the payload the page composed, through the real renderer and main._build_options: the Options &
     Unit Prices lines, the lump sum, and the template the base picks.

Each mutation at the bottom breaks a scratch copy of the page and the check it belongs to goes red.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
SNAPSHOTS = TESTS / "js" / "v2-proposal-snapshot-harness.js"
PANEL = TESTS / "js" / "v2-options-panel-harness.js"
BLOCKS = TESTS / "js" / "price-block-harness.js"

PANEL_FILES = ["js/proposal-review.js", "js/price-lines-core.js", "shared.js", "js/bid-model.js", "js/bid-engine.js"]
BLOCK_FILES = ["js/proposal-review.js", "js/price-lines-core.js"]

EN = chr(0x2013)   # the document prints an en dash between a figure and its words
BAD = chr(0xFFFD)  # ...and a cell the renderer cannot encode reads back as this


def _money(n):
    return "${:,}".format(n)


# ── the drafts and the panel ─────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def snaps():
    require_node()
    proc = run_node(SNAPSHOTS, FRONTEND)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


def run_panel(frontend=FRONTEND):
    proc = run_node(PANEL, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def panel():
    require_node()
    return run_panel()


def test_the_drafts_are_the_models_and_hold_what_the_proposal_reads(snaps):
    """Four bids from the real model. If these were not v2 snapshots every check below would be about a spreadsheet draft."""
    for name, base, work_type, lump in (("polish", "Polish", "polish", 33798), ("epoxy", "Epoxy", "epoxy", 28086),
                                        ("combined", None, "combo", 61884), ("copy", "Copy1", "polish", 29955)):
        s = snaps[name]["state"]
        assert s["base_tab_id"] == base and s["work_type"] == work_type and s["proposal_lump_sum"] == lump, name
        assert s["priced_tabs"] and all(t["v2"] is True for t in s["priced_tabs"]), name
    s = snaps["polish"]["state"]
    assert [t["id"] for t in s["priced_tabs"]] == ["Polish", "Copy1", "Epoxy", "Seal"]
    assert s["tab_opts"]["Copy1"]["price_mode"] == "deduct" and s["tab_opts"]["Epoxy"]["price_mode"] == "total"
    assert snaps["polish"]["hand"] == {"Polish": 33798, "Copy1": 29955, "Epoxy": 28086, "Seal": 4159}


# ── 1. THE PANEL ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["polish", "epoxy", "combined", "copy"])
def test_a_v2_draft_draws_every_base_radio_read_only_and_says_where_the_base_is_picked(panel, name):
    p = panel["locked"][name]
    assert p["locked"] is True
    assert p["hint"] == "Pick the base bid on the estimate. Open the estimate"
    assert p["link"] == "/estimate-review.html?d=DRAFT-1", "the link goes to the Estimate step's door (it sends a v2 draft on), with this draft's id"
    assert p["radios"] and all(r["disabled"] for r in p["radios"]), "every base radio is read-only"
    # the one that is checked is the base the estimate picked, so the panel still says which sheet is the base
    checked = [r["value"] for r in p["radios"] if r["checked"]]
    assert checked == [p["base_tab_id"] or ""], (checked, p["base_tab_id"])


@pytest.mark.parametrize("name", ["polish", "epoxy", "combined", "copy"])
def test_nothing_on_a_v2_draft_changes_the_base_from_this_page(panel, name):
    """A browser gives a disabled radio no event. And a change dispatched at one by a script still reaches nothing, because no handler
    was wired: the base, the lump sum, the saves and the template are all as they were."""
    p = panel["locked"][name]
    assert p["attempts"] and not any(p["attempts"]), "a disabled radio takes no event"
    assert p["forcedHandlers"] and not any(p["forcedHandlers"]), "no change handler is wired on a v2 draft's radios"
    assert p["afterAttempt"] == p["before"]
    assert p["savesByAttempts"] == 0 and p["reloads"] == 0


def test_the_combined_base_is_shown_checked_and_read_only_too(panel):
    p = panel["locked"]["combined"]
    assert p["radios"][0] == {"value": "", "checked": True, "disabled": True}, "Epoxy + Polish (combined), first"
    assert p["base_tab_id"] is None and p["work_type"] == "combo"
    assert "Part of the combined base bid." in p["rows"]["Polish"]["text"] and "Part of the combined base bid." in p["rows"]["Epoxy"]["text"]


def test_a_draft_from_the_spreadsheet_keeps_live_radios_and_the_old_hint(panel):
    """Unchanged: the same two bids with the v2 marks taken off are a spreadsheet's, and a pick on the radio moves the base."""
    for name, pick, lump in (("polish", "Epoxy", 28086), ("epoxy", "Polish", 33798)):
        p = panel["live"][name]
        assert p["locked"] is False and p["hint"] is None and p["link"] is None
        assert p["radios"] and not any(r["disabled"] for r in p["radios"])
        assert p["fired"] is True, "a live radio takes the event"
        assert p["after"]["base_tab_id"] == pick and p["after"]["lump"] == lump and p["saved"] == pick
        assert p["reloads"] == 1, "a base pick reloads the template for the new base's work type"


def test_one_tab_without_the_mark_is_not_a_v2_snapshot(panel):
    """A snapshot from the spreadsheet, or a stale one left on a v2 draft, is read as it always was."""
    assert panel["oneUnmarked"]["locked"] is False
    assert not any(r["disabled"] for r in panel["oneUnmarked"]["radios"])


def test_allv2_and_the_v2_pricing_view_in_shared_js_give_one_answer(panel):
    """Two answers to one question is how a draft reads as v2 "but only sometimes"."""
    assert panel["parity"]["all marked"]["allV2"] is True
    for case, got in panel["parity"].items():
        assert got["allV2"] == got["viewKeepsIt"], case
    assert [k for k, v in panel["parity"].items() if v["allV2"]] == ["all marked", "one marked"]


def test_the_option_controls_stay_and_write_the_keys_they_always_wrote(panel):
    o = panel["options"]
    # the copy and the Epoxy sheet each offer: on / off, shown, total or add / deduct, a description, notes
    for tab in ("start", "epoxy"):
        r = o[tab]
        assert r["isOption"] is True and r["show"] is True and r["desc"] is True and r["notes"] is True and r["mode"] is not None
    # the base row offers none of them
    assert o["root"]["isOption"] is None and o["root"]["desc"] is False and "This sheet is the Base bid." in o["root"]["text"]
    # total / deduct: tab_opts[id].price_mode, and the room the page prints from
    assert o["copyAsTotal"]["opts"]["price_mode"] == "total" and o["copyAsTotal"]["rooms"][1] == ["Copy1", False, "total", 29955]
    assert o["copyAsDeduct"]["opts"]["price_mode"] == "deduct" and o["copyAsDeduct"]["rooms"][1] == ["Copy1", False, "deduct", 29955]
    # on / off: tab_opts[id].is_option, and the room is there or not
    assert o["epoxyOff"]["opts"]["is_option"] is False and o["epoxyOff"]["rooms"] == ["Polish", "Copy1", "Seal"]
    assert o["epoxyOn"]["opts"]["is_option"] is True and o["epoxyOn"]["opts"]["show"] is True and "Epoxy" in o["epoxyOn"]["rooms"]
    # the description: tab_opts[id].desc, and the option's own words on its room
    assert o["desc"]["opts"]["desc"] == "Add for an epoxy floor in the loading dock"
    assert o["desc"]["room"] == "Add for an epoxy floor in the loading dock"
    # notes: tab_notes, saved with the draft
    assert o["notes"]["tab_notes"] == {"Seal": ["Two coats", "Clear"]} and o["notes"]["saved"] == o["notes"]["tab_notes"]
    # only the keys the estimate wrote were touched, and the base never moved
    assert o["keysTouched"] == ["Copy1", "Epoxy", "Seal"] and o["untouchedCopyEntry"] is True
    assert o["base"] == {"id": "Polish", "lump": 33798}


def test_seal_is_a_total_only_on_a_v2_draft_and_the_spreadsheets_seal_is_read_as_it_was(panel):
    s = panel["seal"]
    # a v2 Seal sheet: no Price-as choice is drawn, and a stale "deduct" left on it is read as the total it is priced as
    assert s["v2Row"]["totalOnly"] is True and s["v2Row"]["mode"] is None and s["v2Row"]["deductHint"] is False
    assert s["v2Room"] == "total" and s["v2Opts"] == "deduct", "read as a total; the draft's own key is not rewritten by this page"
    # a Seal sheet on a spreadsheet draft: as it was
    assert s["liveRow"]["totalOnly"] is False and s["liveRow"]["mode"] == "deduct" and s["liveRoom"] == "deduct"


def test_a_v2_draft_lists_every_sheet_it_holds_and_has_no_add_another_system(panel):
    s = panel["systems"]
    assert s["v2Rows"] == ["Polish", "Copy1", "Epoxy", "Seal", 'Gyp (USG 1-8")'] and s["v2Add"] is False
    assert 'Gyp (USG 1-8")' not in s["liveRows"] and s["liveAdd"] is True, "a spreadsheet draft hides the other work types' sheets"


# ── 2. THE DOCUMENT ──────────────────────────────────────────────────────────────────────────────
def _drive(state, work_type, template=None):
    """The page opens the draft (rebuildPricing, then the paint) and composes the payload Continue hands /api/generate."""
    import test_price_block_reconciles as R
    st = json.loads(json.dumps(state))
    wt = template or work_type
    res = R._drive(work_type=work_type, blocks=R._template_blocks(wt, "Direct"), rebuild=True,
                   total=0.0, sales_tax=0.0, remodel_tax=0.0, state=st)
    return R, res


def _document(R, res):
    """Every line of the document the real renderer prints from that payload."""
    body = json.loads(json.dumps(res["payload"]))
    body["values"] = dict(R._NARRATIVE, **body["values"])
    return [ln.replace(BAD, EN) for ln in R._price_rows(R._render(body))["all"]]


_OPTION_LINE = re.compile(r"^(\$[\d,]+|Add \$[\d,]+|Deduct \(\$[\d,]+\)) " + EN + " ")


def _heading(lines):
    """Where the Options heading prints: "Options:" on the Epoxy and Combo templates, "Options" on the Polish one."""
    at = [i for i, ln in enumerate(lines) if ln in ("Options", "Options:")]
    assert len(at) == 1, "the Options heading prints once, not %d times" % len(at)
    return at[0]


def _options(lines):
    """The lines under the Options heading, as printed. (Not _price_rows' list: its stop rule ends the block at a line that starts
    "Add $", which is the NOTES bullet "Add $4,500 for each additional phase" and also an Add option.)"""
    out = []
    for ln in lines[_heading(lines) + 1:]:
        if not _OPTION_LINE.match(ln):
            break
        out.append(ln)
    return out


def _rooms(res):
    return [(r["id"], r["is_base"], r["price_mode"], r["bid"]["total"]) for r in res["payload"]["rooms"]]


def test_a_polish_base_with_a_polish_copy_as_a_deduct_an_epoxy_total_and_a_seal_total(snaps):
    R, res = _drive(snaps["polish"]["state"], "polish")
    hand = snaps["polish"]["hand"]
    v = res["payload"]["values"]
    assert res["payload"]["work_type"] == "polish"
    assert v["proposal_lump_sum"] == hand["Polish"] == 33798, "the lump sum is the base alone"
    assert _rooms(res) == [("Polish", True, "total", 33798), ("Copy1", False, "deduct", 29955),
                           ("Epoxy", False, "total", 28086), ("Seal", False, "total", 4159)]
    lines = _document(R, res)
    assert _options(lines) == [
        "Deduct ($3,843) " + EN + " VE for Polish 400 Grit, in lieu of Polish 800 Grit.",
        "$28,086 " + EN + " Flake as described above (material sales tax INCLUDED)",
        "$4,159 " + EN + " Sealed Concrete as described above (material sales tax INCLUDED)",
    ]
    # the Deduct is the difference of the two tax-inclusive totals, and the base's own block is the base alone
    assert 33798 - 29955 == 3843
    assert "$33,798 " + EN + " Total" in lines
    assert not any("28,086" in ln for ln in lines[:_heading(lines)]), "an option's price is not in the base block"


def test_the_same_options_come_out_of_main_build_options_in_the_words_the_document_prints(snaps):
    """_build_options is the one function the document's option lines come from; run on the rooms the page composed."""
    import main
    R, res = _drive(snaps["polish"]["state"], "polish")
    built = main._build_options(res["payload"]["rooms"], res["payload"]["values"], res["payload"]["work_type"])
    assert [(b["id"], b["price_formatted"], b["price_desc"]) for b in built] == [
        ("Copy1", "Deduct ($3,843)", "VE for Polish 400 Grit, in lieu of Polish 800 Grit."),
        ("Epoxy", "$28,086", "Flake as described above (material sales tax INCLUDED)"),
        ("Seal", "$4,159", "Sealed Concrete as described above (material sales tax INCLUDED)"),
    ]


def test_making_epoxy_the_base_changes_the_template_the_lump_sum_and_turns_the_deduct_into_an_add(snaps):
    """Everything follows the base: the Epoxy template, $28,086, Polish listed as an option priced as a total, and the Polish copy,
    now DEARER than the base, reads as an Add by sign (option minus base) with no change to what the estimator marked."""
    R, res = _drive(snaps["epoxy"]["state"], "epoxy")
    assert res["payload"]["work_type"] == "epoxy"
    assert res["payload"]["values"]["proposal_lump_sum"] == 28086
    assert _rooms(res) == [("Epoxy", True, "total", 28086), ("Polish", False, "total", 33798),
                           ("Copy1", False, "deduct", 29955), ("Seal", False, "total", 4159)]
    lines = _document(R, res)
    assert _options(lines) == [
        "$33,798 " + EN + " Polish 800 Grit as described above (material sales tax INCLUDED)",
        "Add $1,869 " + EN + " Polish 400 Grit",
        "$4,159 " + EN + " Sealed Concrete as described above (material sales tax INCLUDED)",
    ]
    assert any("Epoxy flooring as described above" in ln for ln in lines) and "$28,086 " + EN + " Total" in lines
    assert 29955 - 28086 == 1869


def test_the_base_decides_the_template_even_when_the_job_type_left_on_the_draft_is_another(snaps):
    """effectiveWorkType reads the base's role: an Epoxy base on a draft whose job type still says polish prints as an Epoxy bid."""
    state = json.loads(json.dumps(snaps["epoxy"]["state"]))
    state["work_type"] = "polish"
    R, res = _drive(state, "polish", template="epoxy")
    assert res["payload"]["work_type"] == "epoxy"
    assert any("Epoxy flooring as described above" in ln for ln in _document(R, res))
    # and the other way: a Polish copy as the base on a draft whose job type says epoxy is a Polish bid
    state = json.loads(json.dumps(snaps["copy"]["state"]))
    state["work_type"] = "epoxy"
    R, res = _drive(state, "epoxy", template="polish")
    assert res["payload"]["work_type"] == "polish" and res["payload"]["values"]["proposal_lump_sum"] == 29955


def test_the_pair_made_the_base_adds_the_two_totals_and_prints_each_system_as_an_option(snaps):
    R, res = _drive(snaps["combined"]["state"], "combo")
    assert res["payload"]["work_type"] == "combo"
    assert res["payload"]["values"]["proposal_lump_sum"] == 61884 == 33798 + 28086, "Epoxy and Polish added"
    assert _rooms(res) == [("Epoxy", True, "total", 61884), ("Copy1", False, "deduct", 29955), ("Seal", False, "total", 4159)]
    lines = _document(R, res)
    assert "$28,086 " + EN + " Total" in lines and "$33,798 " + EN + " Total" in lines, "each system's own total"
    assert any("Option 1: Epoxy flooring as described above" in ln for ln in lines)
    assert any("Option 2: Polished Concrete flooring as described above" in ln for ln in lines)
    opts = _options(lines)
    assert opts[0].startswith("Deduct ($31,929) " + EN + " "), "the copy against the pair: 29,955 less 61,884"
    assert opts[1] == "$4,159 " + EN + " Sealed Concrete as described above (material sales tax INCLUDED)"
    assert 61884 - 29955 == 31929


def test_the_polish_copy_made_the_base_prints_the_copy_as_the_base_and_the_old_base_as_an_option(snaps):
    R, res = _drive(snaps["copy"]["state"], "polish")
    assert res["payload"]["work_type"] == "polish" and res["payload"]["values"]["proposal_lump_sum"] == 29955
    assert _rooms(res)[0] == ("Copy1", True, "total", 29955)
    lines = _document(R, res)
    assert _options(lines) == [
        "$33,798 " + EN + " Polish 800 Grit as described above (material sales tax INCLUDED)",
        "$28,086 " + EN + " Flake as described above (material sales tax INCLUDED)",
        "$4,159 " + EN + " Sealed Concrete as described above (material sales tax INCLUDED)",
    ]
    assert "$29,955 " + EN + " Total" in lines


def test_a_copy_that_is_not_on_the_proposal_and_an_option_the_estimator_hid_print_nothing(snaps):
    state = json.loads(json.dumps(snaps["polish"]["state"]))
    state["tab_opts"]["Copy1"]["is_option"] = False        # a copy starts here
    state["tab_opts"]["Seal"]["show"] = False              # hidden in the Proposal step's own box
    R, res = _drive(state, "polish")
    assert [r[0] for r in _rooms(res)] == ["Polish", "Epoxy"]
    assert _options(_document(R, res)) == ["$28,086 " + EN + " Flake as described above (material sales tax INCLUDED)"]


def test_a_seal_option_with_a_stale_deduct_prints_as_a_total_on_a_v2_draft_and_as_it_did_on_a_spreadsheet_draft(snaps):
    state = json.loads(json.dumps(snaps["polish"]["state"]))
    state["tab_opts"]["Seal"]["price_mode"] = "deduct"
    R, res = _drive(state, "polish")
    seal = [r for r in res["payload"]["rooms"] if r["id"] == "Seal"][0]
    assert seal["price_mode"] == "total"
    assert _options(_document(R, res))[-1] == "$4,159 " + EN + " Sealed Concrete as described above (material sales tax INCLUDED)"
    # the same draft from the spreadsheet (marks off): unchanged, a Deduct by sign
    for t in state["priced_tabs"]:
        del t["v2"]
    R, res = _drive(state, "polish")
    seal = [r for r in res["payload"]["rooms"] if r["id"] == "Seal"][0]
    assert seal["price_mode"] == "deduct"
    assert _options(_document(R, res))[-1].startswith("Deduct ($29,639) " + EN + " VE for Sealed Concrete")
    assert 33798 - 4159 == 29639


def test_the_words_typed_on_an_option_are_its_line_on_a_v2_draft_as_on_any_other(snaps):
    state = json.loads(json.dumps(snaps["polish"]["state"]))
    state["tab_opts"]["Copy1"]["desc"] = "Deduct for the lower grit polish in the back rooms."
    state["tab_opts"]["Epoxy"]["desc"] = "Add for epoxy in the loading dock, if required."
    R, res = _drive(state, "polish")
    assert _options(_document(R, res))[:2] == [
        "Deduct ($3,843) " + EN + " Deduct for the lower grit polish in the back rooms.",
        "$28,086 " + EN + " Add for epoxy in the loading dock, if required. (material sales tax INCLUDED)",
    ]


# ── the checks go red when the code changes ──────────────────────────────────────────────────────
PANEL_BREAKS = {
    "the radios are not drawn disabled": (
        "js/proposal-review.js", '          const baseRO = v2Locked ? " disabled" : "";', '          const baseRO = "";',
        lambda r: any(not x["disabled"] for x in r["locked"]["polish"]["radios"])),
    "the change handler is wired on a v2 draft": (
        "js/proposal-review.js", '          if (!v2Locked) optsPanel.querySelectorAll("input.pr-base")',
        '          optsPanel.querySelectorAll("input.pr-base")',
        lambda r: any(r["locked"]["polish"]["forcedHandlers"])),
    "the hint is gone": (
        "js/proposal-review.js", "Pick the base bid on the estimate. <a ", "Choose a base bid here. <a ",
        lambda r: r["locked"]["polish"]["hint"] != "Pick the base bid on the estimate. Open the estimate"),
    "the link does not go to the estimate": (
        "js/proposal-review.js", '          const estimateHref = v2Locked ? TW.withDraft("/estimate-review.html") : "";',
        '          const estimateHref = "/estimate-review.html";',
        lambda r: r["locked"]["polish"]["link"] != "/estimate-review.html?d=DRAFT-1"),
    "every draft is read as v2": (
        "js/proposal-review.js", "          const v2Locked = TWPrice.allV2(allTabs);", "          const v2Locked = true;",
        lambda r: r["live"]["polish"]["locked"] is not False),
    "no draft is read as v2": (
        "js/proposal-review.js", "          const v2Locked = TWPrice.allV2(allTabs);", "          const v2Locked = false;",
        lambda r: r["locked"]["polish"]["locked"] is not True),
    "a mixed snapshot is read as v2": (
        "js/price-lines-core.js", '      if (!tabs[i] || typeof tabs[i] !== "object" || tabs[i].v2 !== true) return false;',
        '      if (!tabs[i] || typeof tabs[i] !== "object") return false;',
        lambda r: r["oneUnmarked"]["locked"] is not False),
    "a Seal sheet is offered Add / Deduct": (
        "js/proposal-review.js", "              const totalOnly = v2Locked && isOptionOnlyTab(t);", "              const totalOnly = false;",
        lambda r: r["seal"]["v2Row"]["totalOnly"] is not True),
    "a stale Seal deduct prints as a deduct": (
        "js/proposal-review.js", '    if (v2Snapshot) shown.forEach(room => { if (isOptionOnlyTab(byId(room.id))) room.price_mode = "total"; });',
        "    void 0;",
        lambda r: r["seal"]["v2Room"] != "total"),
    "a v2 draft hides the other work types' sheets": (
        "js/proposal-review.js", "          const visTabs = (revealSystems || v2Locked) ? allTabs.slice() : allTabs.filter(defaultVis);",
        "          const visTabs = revealSystems ? allTabs.slice() : allTabs.filter(defaultVis);",
        lambda r: 'Gyp (USG 1-8")' not in r["systems"]["v2Rows"]),
    "a v2 draft offers Add another system": (
        "js/proposal-review.js", "          const hasHiddenSystems = !v2Locked && allTabs.some(t => !defaultVis(t));",
        "          const hasHiddenSystems = allTabs.some(t => !defaultVis(t));",
        lambda r: r["systems"]["v2Add"] is not False),
    "the option switch writes another key": (
        "js/proposal-review.js", "              const o = ensureOpt(id); o.is_option = iso.checked;",
        "              const o = ensureOpt(id); o.is_on = iso.checked;",
        lambda r: r["options"]["epoxyOff"]["opts"]["is_option"] is not False),
    "total or deduct writes another key": (
        "js/proposal-review.js", '              ensureOpt(id).price_mode = md.value === "deduct" ? "deduct" : "total";',
        '              ensureOpt(id).mode = md.value === "deduct" ? "deduct" : "total";',
        lambda r: r["options"]["copyAsTotal"]["opts"]["price_mode"] != "total"),
}


@pytest.mark.parametrize("name", sorted(PANEL_BREAKS))
def test_the_panel_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = PANEL_BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PANEL_FILES)
    proc = run_node(PANEL, frontend)
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name


def _blocks(frontend, state, work_type):
    """The price-block harness over a scratch frontend: the page's pricing, run, and the payload it composes."""
    import test_price_block_reconciles as R
    case = {"name": "x", "work_type": work_type, "audience": "Direct", "blocks": R._template_blocks(work_type, "Direct"),
            "select_options": R._tax_select_options(), "rebuild": True, "total": 0.0, "sales_tax": 0.0, "remodel_tax": 0.0,
            "state": state}
    proc = subprocess.run(["node", str(BLOCKS), str(frontend)], input=json.dumps([case]), capture_output=True,
                          text=True, encoding="utf-8")
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)[0]["pick"]


DOCUMENT_BREAKS = {
    "the base's role no longer picks the template": (
        "js/proposal-review.js", '    return (role === "epoxy" || role === "polish" || role === "gyp") ? role : wt;', "    return wt;",
        "epoxy", lambda r: r["payload"]["work_type"] != "epoxy"),
    "a Seal option's stale deduct prints as a deduct": (
        "js/proposal-review.js", '    if (v2Snapshot) shown.forEach(room => { if (isOptionOnlyTab(byId(room.id))) room.price_mode = "total"; });',
        "    void 0;",
        "seal", lambda r: [x for x in r["payload"]["rooms"] if x["id"] == "Seal"][0]["price_mode"] != "total"),
    "the lump sum is the base and the options added": (
        "js/proposal-review.js", "    state.proposal_lump_sum = shownBase;", "    state.proposal_lump_sum = shownBase + 1;",
        "polish", lambda r: r["payload"]["values"]["proposal_lump_sum"] != 33798),
}


@pytest.mark.parametrize("name", sorted(DOCUMENT_BREAKS))
def test_the_document_checks_go_red_when_the_code_changes(tmp_path, snaps, name):
    require_node()
    rel, old, new, which, noticed = DOCUMENT_BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, BLOCK_FILES)
    state = json.loads(json.dumps(snaps["epoxy" if which == "epoxy" else "polish"]["state"]))
    work_type = "epoxy" if which == "epoxy" else "polish"
    if which == "epoxy":
        state["work_type"] = "polish"    # the base, not the job type left on the draft, decides
    if which == "seal":
        state["tab_opts"]["Seal"]["price_mode"] = "deduct"
    got = _blocks(frontend, state, "polish" if which == "epoxy" else work_type)
    if got is None:
        return   # the break stopped the page outright: noticed
    assert noticed(got), "the checks did not notice: " + name
