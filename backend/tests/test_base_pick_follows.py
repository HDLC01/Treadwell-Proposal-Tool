"""Picking a different base bid moves the proposal to that tab's price, from either picker, and
keeps the words the estimator typed into the base line.

Hanz, 2026-09-26, on staging, on the "Hanz Fix" test project (Epoxy $7,447, "Epoxy copy" $15,149,
a Polish tab): "I had an error in the proposal tool where the base bid was not updating". He picked
another base tab on the Estimate page, and the proposal went on quoting the old tab's price. Then,
on the rule that fixed it by forgetting his edits: KEEP THE WORDS. A base line he re-worded keeps
his words through a pick; its amount, its words for the tab's system and its tax wording are the
new base's (TWPrice.applyBasePick).

WHAT A PICK DOES, the one rule all three ways the base changes apply (the Estimate step's bid strip,
the Proposal step's sidebar, deleting the base copy on the Estimate step):

  * A LIVE base line (the amount marker in it) keeps his words and resolves against the new base.
  * A FIGURE OF HIS OWN becomes the live amount where one of this draft's tabs prices the line at
    it today (TWPrice.tabFigures) -- the tool's figure. Any other figure stays his: kept, marked,
    and Send, Download and To Dropbox ask (Hanz: warn, then let him send).
  * A LINE IN THE OLD SHAPE is migrated the same way at the pick, while the old base's figures are
    still on the draft, and with the parts drawing it would use (the base line's tax slot and the
    wording it prints before the pick), so a pick and a draw read one line alike; the lines typed
    inside it become lines of their own; a "$0" tax row the old sweep froze is dropped.
  * THE WORDS FOR THE TAB'S SYSTEM ("Epoxy flooring as described above" / "Polished Concrete
    Flooring as described above") are the old base's where they still stand verbatim, and become
    the new base's (TWPrice.baseDesc, whose twin is the page's baseDescLabel).
  * The base's tax rows and Total follow the same rule. The oldest per-field buckets (single_bid,
    rows, combo) still reset; nothing else is touched, option lines included.

Also pinned here, from the base-pick fix before it: WHICH LINE OF AN OLD-SHAPE LINE IS THE PRICE
LINE (a note typed above it that quotes a figure is not it), that the sidebar's pick is SAVED, and
that the Estimate strip's pick is priced and saved with the page's cell edits.

EXECUTED: js/price-lines-harness.js runs the Estimate step's real wireBidBar change handler, savers
and deleteTab, the Proposal step's real rebuildPricing, price box paint, box sweep and sidebar radio
handler; the document half renders what those pages hand /api/generate through the real renderer.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess

import docx
import pytest
from docx.oxml.ns import qn
from starlette.requests import Request

import main
import proposal_writer as pw

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "price-lines-harness.js"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
AMT, TAX = "⟦amount⟧", "⟦tax⟧"
NOTE = ["", "THis is a test send to Hanz"]


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    assert p.returncode == 0, "the harness itself failed:\n" + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


# What the base line prints at each step of the flow, off Hanz Fix's own tabs. His words
# (", warehouse only") ride every pick; the amount, the words for the tab's system and the tax
# wording are the base's; his $15,000 is his until he types a figure a tab prices.
_EPOXY = "Epoxy flooring as described above"
_POLISH = "Polished Concrete Flooring as described above"
_W = ", warehouse only"
EXPECT = {
    "ONE_LINE": {
        "proposal2": (f"$15,149 – {_EPOXY}{_W} (material sales tax INCLUDED)", [], "live"),
        "sidebar3": (f"$15,000 – {_POLISH}{_W} (Remodel Tax AND material sales tax INCLUDED)", [], "money"),
        "revisit3": (f"$15,000 – {_POLISH}{_W} (Remodel Tax AND material sales tax INCLUDED)", [], "money"),
        "sidebar4": (f"$15,000 – {_EPOXY}{_W} (material sales tax INCLUDED)", [], "money"),
        "typed4": (f"$15,149 – {_EPOXY}{_W} (material sales tax INCLUDED)", [], "money"),
        "estimate5": (f"$15,149 – {_EPOXY}{_W} (material sales tax INCLUDED)", [], "live"),
    },
    "BROKEN_OUT": {
        "proposal2": (f"$14,954 – {_EPOXY}{_W}", ["$195 – Material Sales Tax", "$15,149 – Total, all in"], "live"),
        "sidebar3": (f"$15,000 – {_POLISH}{_W}",
                     ["$110 – Material Sales Tax", "$745 – Remodel Tax", "$9,860 – Total, all in"], "money"),
        "revisit3": (f"$15,000 – {_POLISH}{_W}",
                     ["$110 – Material Sales Tax", "$745 – Remodel Tax", "$9,860 – Total, all in"], "money"),
        "sidebar4": (f"$15,000 – {_EPOXY}{_W}", ["$96 – Material Sales Tax", "$7,447 – Total, all in"], "money"),
        "typed4": (f"$14,954 – {_EPOXY}{_W}", ["$96 – Material Sales Tax", "$7,447 – Total, all in"], "money"),
        "estimate5": (f"$14,954 – {_EPOXY}{_W}", ["$195 – Material Sales Tax", "$15,149 – Total, all in"], "live"),
    },
}
# What Send, Download and To Dropbox ask about at each step: the figure on the line, and the one
# the estimate has for it.
ASKS = {
    "ONE_LINE": {"sidebar3": ("$15,000", "$9,860"), "revisit3": ("$15,000", "$9,860"),
                 "sidebar4": ("$15,000", "$7,447"), "typed4": ("$15,149", "$7,447")},
    "BROKEN_OUT": {"sidebar3": ("$15,000", "$9,005"), "revisit3": ("$15,000", "$9,005"),
                   "sidebar4": ("$15,000", "$7,351"), "typed4": ("$14,954", "$7,351")},
}
# The flow: (step, the base it ends on). 1 Estimate strip Epoxy -> Epoxy copy, read by the Proposal
# step (2), where he types $15,000 over the amount; 3 Proposal sidebar -> Polish (another work type)
# and the next visit; 4 sidebar -> Epoxy, then he types the copy's own figure; 5 Estimate strip ->
# Epoxy copy again.
STEPS = [("proposal2", "Copy1"), ("sidebar3", "Polish"), ("revisit3", "Polish"),
         ("sidebar4", "Epoxy"), ("typed4", "Epoxy"), ("estimate5", "Copy1")]
LAYOUTS = ["ONE_LINE", "BROKEN_OUT"]


def _editor_rows(step):
    """(the base line, its mark, the lines typed under it, the tax rows) as the price box draws them."""
    rows = step["rows"]
    base = [r for r in rows if r["key"] == "base"]
    return (base[0]["text"], base[0]["mark"], [r["text"] for r in base[1:] if r["kind"] == "extra"],
            [r["text"] for r in rows if r["key"] != "base" and r["kind"] == "line"])


# ── the editor ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("step,base", STEPS)
def test_a_base_pick_keeps_his_words_and_moves_the_money_on_either_picker(ran, layout, step, base):
    """Hanz, 2026-09-26: keep the words. At every step his ", warehouse only" is on the base line,
    and his "Total, all in" on the Total; the amount, the words for the tab's system (Epoxy <->
    Polished Concrete) and the tax wording are the picked base's -- after a pick on the Estimate
    step read by the Proposal step, after a pick in the Proposal step's sidebar, and on the next
    visit after leaving it. The note he typed under the base line is still there. The $15,000 he
    typed is his through every pick (marked, and asked about), until he types a figure a tab prices
    and the next pick makes it the live amount.
    Mutations: applyBasePick deletes the base lines again (the old rule: every step prints the
    computed line); its description swap off (Epoxy words under the Polish base); its own-figure
    step off (the typed copy's figure stays his, marked, after step 5)."""
    s = ran["basePick"][layout][step]
    line, mark, typed, tax = _editor_rows(s)
    want_line, want_tax, want_mark = EXPECT[layout][step]
    assert s["base_tab_id"] == base, s["base_tab_id"]
    assert line == want_line, (step, line)
    assert mark == want_mark, (step, mark)
    assert tax == want_tax, (step, tax)
    assert typed == NOTE, (step, typed)
    ask = ASKS[layout].get(step)
    assert s["warnings"] == ([{"key": "base", "says": ask[0], "estimate": ask[1]}] if ask else []), s["warnings"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_estimate_strip_applies_the_rule_and_prices_the_pick(ran, layout):
    """The pick on the Estimate step. His re-worded base line and Total are KEPT, still live; the
    sweep's Material Sales Tax row frozen at Epoxy's $96 is a tab's figure, so it becomes the live
    amount and, reading as the tool prints it, is no edit and goes; the phantom "$0 – Remodel Tax"
    goes. Everything no base pick touches stays as it was: the option line of the tab that is now
    the base (still in the old shape, lines typed inside it: it prints again only if that tab is an
    option again), the note under the base line, the gap line above "Options:", a manual line and a
    total-priced option he re-worded. And it is PRICED and saved with this visit's cell edits.
    Mutations: applyBasePick's "$0" check off (a "$0 – Remodel Tax" of his is kept); its
    reads-as-the-tool check off (the $96 row is stored); call persistBidOptions again (no pricing
    snapshot, and the saved cell edit goes back to 2000)."""
    e = ran["basePick"][layout]["estimate1"]
    assert e["base"] == "Copy1"
    assert e["snapshots"] == 1, "the pick was saved without re-pricing"
    assert e["cellValues"] == {"Epoxy!E20": 2400}, e["cellValues"]
    pov = e["pov"]
    assert list(pov["lines"]) == ["option:Copy1"], pov["lines"]
    assert pov["lines2"] == {"base": f"{AMT} – {_EPOXY}{_W} {TAX}", "total": f"{AMT} – Total, all in",
                             "manual:0": f"{AMT} – Joint filler, per plan",
                             "option:Polish": f"{AMT} – Polished Concrete, 800 grit, warehouse only {TAX}"}
    assert pov["after"] == {"base": NOTE}, pov["after"]
    assert pov["before"] == {"heading_options": ["TEST123"]}, pov["before"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_sidebar_pick_keeps_his_figure_moves_the_words_and_saves_it(ran, layout):
    """He typed a figure of his own into the base line on the Proposal step, then picked Polish in
    its sidebar and left by a step pill. What the page saved still carries his line with his
    figure, its words for the system now Polish's; the template was reloaded for the new work type;
    what he typed elsewhere is untouched. Mutations: the old rule (his line is gone from what was
    saved); the description swap off (the Epoxy words are saved under the Polish base)."""
    p2 = ran["basePick"][layout]["proposal2"]
    assert p2["typed"] == f"$15,000 – {_EPOXY}{_W} {TAX}", p2["typed"]
    s = ran["basePick"][layout]["sidebar3"]
    assert s["reloads"] == 1
    saved = s["savedPov"]
    assert saved["lines2"]["base"] == f"$15,000 – {_POLISH}{_W} {TAX}", saved["lines2"]
    assert saved["lines2"]["total"] == f"{AMT} – Total, all in", saved["lines2"]
    assert saved["lines2"]["manual:0"] == f"{AMT} – Joint filler, per plan", saved["lines2"]
    assert saved["after"]["base"] == NOTE, saved["after"]
    assert saved["before"]["heading_options"] == ["TEST123"], saved["before"]


def test_the_sidebars_pick_is_saved(ran):
    """The sidebar's pick changes only the base line's words for the system here (Epoxy copy ->
    Polish), and rebuildPricing's save carries the base and the money, not the price edits. What
    the page leaves with has the Polish words, and the next visit prints them.
    Mutation: drop the sidebar's own save (the Epoxy words come back under the Polish base)."""
    s = ran["sidebarSave"]
    assert s["saved"] == {"base": f"{AMT} – {_POLISH}{_W} {TAX}"}, s["saved"]
    assert s["rows"] == [{"key": "base", "kind": "line", "cue": True, "mark": "live",
                          "text": f"$9,860 – {_POLISH}{_W} (Remodel Tax AND material sales tax INCLUDED)"}], s["rows"]


def test_a_copy_picked_before_it_is_priced_takes_its_role_from_the_page(ran):
    """A Polish copy made a moment ago and picked at once on the Estimate step: priced_tabs does not
    hold it yet (this pick is what prices it), so its role comes from the page's own tab list, and
    the base line's words for the system become the Polish ones.
    Mutation: the Estimate strip passes no `roles` (the Epoxy words stay under a Polish base)."""
    n = ran["newCopyPick"]
    assert n["base"] == "Copy2"
    assert n["lines2"] == {"base": f"{AMT} – {_POLISH}{_W} {TAX}"}, n["lines2"]


def test_the_page_and_the_rule_agree_on_the_words_for_every_system(ran):
    """TWPrice.baseDesc (the rule, on either page) and the Proposal step's own baseDescLabel (through
    effectiveWorkType) give the same words for every work type and base-tab role. Mutation: one
    noun changed in baseDesc."""
    rows = ran["baseDesc"]
    assert len(rows) == 25
    assert [r for r in rows if r["page"] != r["core"]] == []
    got = {(r["wt"], r["role"]): r["core"] for r in rows}
    assert got[("epoxy", "polish")] == _POLISH and got[("polish", "epoxy")] == _EPOXY
    assert got[("combo", "polish")] == "Epoxy & Polished Concrete flooring as described above"
    assert got[("epoxy", "gyp")] == "Gypsum Underlayment System as described above"
    assert got[("sealer", "")] == "Sealed Concrete as described above"
    assert got[("epoxy", "seal")] == _EPOXY


# ── a line frozen at the OLD base's figure (drawn, no pick) ─────────────────────────────────────
def test_a_line_frozen_at_the_old_bases_figure_follows_the_estimate_again(ran):
    """Hanz Fix the moment the base moved: base Epoxy copy $15,149, the base line saved with
    Epoxy's $7,447 and his note inside it, while Epoxy still prices at $7,447 (NOT revisions 2-5,
    where Epoxy had been re-priced: see the revision-5 test below). Drawn once: the computed line
    (nothing stored for it), his note a line of its own, nothing marked, nothing for Send to ask.
    Mutation: migrate against today's figure only (TWPrice.tabFigures dropped) -- the line stays
    at $7,447, marked, and Send asks."""
    f = ran["frozenAtOldBase"]
    assert [(r["kind"], r["text"], r["cue"]) for r in f["rows"]] == [
        ("line", f"$15,149 – {_EPOXY} (material sales tax INCLUDED)", False),
        ("extra", "", False), ("extra", "THis is a test send to Hanz", False)], f["rows"]
    assert f["pov"]["lines"] == {} and f["pov"]["lines2"] == {}, f["pov"]
    assert f["pov"]["after"] == {"base": NOTE}
    assert f["warnings"] == []
    b = ran["frozenAtOldBaseBroken"]
    assert [(r["key"], r["text"]) for r in b["rows"]] == [
        ("base", f"$14,954 – {_EPOXY}"), ("base", "noted"),
        ("sales_tax", "$195 – Material Sales Tax"), ("total", "$15,149 – Total")], b["rows"]
    assert b["pov"]["lines2"] == {}, b["pov"]


def test_a_figure_no_tab_priced_stays_his_marked_and_asked_about(ran):
    """Hanz, 2026-09-25: a hand-typed dollar amount -- warn, then let him send."""
    o = ran["frozenOwnFigure"]
    assert o["pov"]["lines2"] == {"base": f"$9,999 – {_EPOXY} {TAX}"}, o["pov"]
    assert o["pov"]["after"] == {"base": ["", "as agreed"]}
    assert o["rows"][0]["text"] == f"$9,999 – {_EPOXY} (material sales tax INCLUDED)"
    assert "tw-money-off" in o["cls"]
    assert o["warnings"] == [{"key": "base", "says": "$9,999", "estimate": "$15,149"}]


def _node_core(expr, *args):
    core = FRONTEND / "js" / "price-lines-core.js"
    script = ("const P = require(process.argv[1]); const A = process.argv.slice(2).map(JSON.parse);"
              "console.log(JSON.stringify((" + expr + ")(P, ...A)));")
    p = subprocess.run(["node", "-e", script, str(core), *[json.dumps(a) for a in args]],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


_TABS = [{"id": "Epoxy", "role": "epoxy", "total": 7447, "sales_tax": 96, "remodel": 0},
         {"id": "Copy1", "role": "epoxy", "total": 15149, "sales_tax": 195, "remodel": 0},
         {"id": "Polish", "role": "polish", "total": 9860, "sales_tax": 110, "remodel": 745}]
_PICK = "(P, pov, from, to, tabs, opts) => [P.applyBasePick(pov, from, to, tabs, opts), pov]"


def test_the_base_pick_rule_over_every_kind_of_saved_edit():
    """TWPrice.applyBasePick, the one rule, over every kind of saved edit, Epoxy -> Polish.
      * base line, live: kept, the old base's words for its system swapped for the new base's,
        his words round them kept;
      * sales tax row, a figure of his own at a figure a tab prices ($110, Polish's): live now;
      * remodel row, a figure no tab prices: kept as his;
      * Total in the old shape at Epoxy's figure with a line typed inside it: live, and reading
        exactly as the tool prints it, no edit -- the typed line becomes a line of its own;
      * the per-field buckets reset; every option line (the old and the new base tab's included),
        the combo lines, manual lines, headings, the gap, the alternate and the typed lines: as
        they were.
    Mutations: each step of the rule off in turn (every assertion below names its own)."""
    pov = {
        "single_bid": {"amount": "$1"}, "rows": {"x": 1}, "combo": {"y": 2},
        "lines": {
            "total": "$7,447 – Total\nall figures firm", "combo:epoxy.flooring": "$1 – combo",
            "option:Polish": "\n$9,860 – the polish option\nunder it",
            "option:Seal": "Add $1,200 – Sealed Concrete in lieu of flake",
            "manual:0": "$1,500 – Joint filler, per plan", "heading_base": "Base Bid:",
        },
        "lines2": {
            "base": f"{AMT} – Flake Broadcast {_EPOXY}, warehouse only {TAX}",
            "sales_tax": "$110 – Material Sales Tax (by hand)", "remodel": "$10 – Remodel Tax",
            "option:Epoxy": f"{AMT} – was an option once {TAX}", "option:Epoxy:total": f"{AMT} – Total",
            "heading_options": "Options & Alternates:", "alt_total": "$9 – Total",
        },
        "after": {"option:Polish": ["typed before"]},
        "before": {"heading_options": ["on the gap"]},
    }
    changed, out = _node_core(_PICK, pov, "Epoxy", "Polish", _TABS, {"workType": "epoxy"})
    assert changed is True
    assert out["single_bid"] == {} and out["rows"] == {} and out["combo"] == {}
    assert out["lines"] == {k: v for k, v in pov["lines"].items() if k != "total"}, out["lines"]
    assert out["lines2"] == {
        "base": f"{AMT} – Flake Broadcast {_POLISH}, warehouse only {TAX}",     # the words moved
        "sales_tax": f"{AMT} – Material Sales Tax (by hand)",                   # a tab's figure: live
        "remodel": "$10 – Remodel Tax",                                          # his figure: kept
        "option:Epoxy": f"{AMT} – was an option once {TAX}", "option:Epoxy:total": f"{AMT} – Total",
        "heading_options": "Options & Alternates:", "alt_total": "$9 – Total",
    }, out["lines2"]
    assert out["after"] == {"option:Polish": ["typed before"], "total": ["all figures firm"]}, out["after"]
    assert out["before"] == {"heading_options": ["on the gap"]}, out["before"]

    # The old base's words only, and only verbatim: a line naming ANOTHER system in his own words
    # keeps them, and a pick between two tabs of one work type changes no words.
    other = {"lines2": {"base": f"{AMT} – {_POLISH} (his wording) {TAX}"}}
    _, out2 = _node_core(_PICK, other, "Epoxy", "Copy1", _TABS, {"workType": "epoxy"})
    assert out2["lines2"] == other["lines2"]
    # `roles` names a tab priced_tabs does not hold yet.
    fresh = {"lines2": {"base": f"{AMT} – {_EPOXY}, as agreed {TAX}"}}
    _, out3 = _node_core(_PICK, fresh, "Epoxy", "Copy2", _TABS,
                         {"workType": "epoxy", "roles": {"Copy2": "polish"}})
    assert out3["lines2"] == {"base": f"{AMT} – {_POLISH}, as agreed {TAX}"}
    # In the old shape at a tab's figure, reading as the tool prints it: no edit, not kept; the
    # note typed inside it is a line of its own. A "$0" tax row is the old sweep's phantom.
    old = {"lines": {"base": f"$7,447 – {_EPOXY} (material sales tax INCLUDED)\n\nTHis is a test send to Hanz",
                     "remodel": "$0 – Remodel Tax", "sales_tax": "$96 – Material Sales Tax"}}
    changed4, out4 = _node_core(_PICK, old, "Epoxy", "Copy1", _TABS, {"workType": "epoxy"})
    assert changed4 is True and out4["lines"] == {} and out4.get("lines2", {}) == {}, out4
    assert out4["after"] == {"base": NOTE}
    # Nothing base-bound saved: nothing to change, and nothing reported.
    changed5, _ = _node_core(_PICK, {"lines2": {"manual:0": "x"}}, "Epoxy", "Copy1", _TABS, {})
    assert changed5 is False
    assert _node_core("(P) => P.applyBasePick(null, 'Epoxy', 'Copy1')") is False


def test_tab_figures_cover_every_layout_the_old_code_froze_and_nothing_else():
    """The figures a line of each kind could have been frozen at, off every priced tab: a base or
    option line its total and its pre-tax figure under any tax answer, a tax row that tax, a Total
    the total. Manual lines, headings and the alternate belong to no tab."""
    core = FRONTEND / "js" / "price-lines-core.js"
    tabs = [{"id": "Epoxy", "total": 7447, "sales_tax": 96, "remodel": 0},
            {"id": "Polish", "total": 9860.5, "sales_tax": 110, "remodel": 745}]
    keys = ["base", "option:Polish", "combo:epoxy", "sales_tax", "option:Epoxy:remodel", "total",
            "manual:0", "heading_options", "heading_base", "alt_total"]
    script = ("const P = require(process.argv[1]); const t = JSON.parse(process.argv[2]);"
              "console.log(JSON.stringify(JSON.parse(process.argv[3]).map(k => P.tabFigures(t, k))));")
    p = subprocess.run(["node", "-e", script, str(core), json.dumps(tabs), json.dumps(keys)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    got = dict(zip(keys, json.loads(p.stdout)))
    line = ["$7,447", "$7,351", "$9,860.50", "$9,750.50", "$9,115.50", "$9,005.50"]
    assert got["base"] == line and got["option:Polish"] == line and got["combo:epoxy"] == line
    assert got["sales_tax"] == ["$96", "$110"]
    assert got["option:Epoxy:remodel"] == ["$745"]
    assert got["total"] == ["$7,447", "$9,860.50"]
    for k in ("manual:0", "heading_options", "heading_base", "alt_total"):
        assert got[k] == [], k


def test_the_estimate_page_loads_the_rule_it_applies():
    """The bid strip calls TWPrice.applyBasePick, so price-lines-core.js must load on the Estimate
    page, before the page's own script (test_frontend_boot_order pins the order)."""
    html = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    core = html.index('src="/js/price-lines-core.js')
    assert core < html.index('src="/js/estimate-review.js"')


# ── the document ────────────────────────────────────────────────────────────────────────────────
_BASE_VALUES = {"project_name": "Hanz Fix", "job_name": "Hanz Fix", "city_state": "Iloilo City, KS",
                "texture": "Smooth", "system_name": "Treadwell 3/16\" Urethne Cement",
                "scope_notes": "s", "schedule_notes": "s", "exclusions": "e",
                "estimator_name": "Hanz", "bid_date_formatted": "9/25/26"}
_TAX_ROW = re.compile(r"^\$[\d,]+(?:\.\d+)? – (?:Material Sales Tax|Remodel Tax|Total(?:, all in)?)$")


def _document(payload):
    p = dict(payload)
    p["values"] = dict(_BASE_VALUES, **p["values"])
    req = Request({"type": "http", "method": "POST", "path": "/t", "headers": [], "query_string": b""})
    blob = main._render_documents(p, req, want_estimate=False)["docx"]["content"]
    d = docx.Document(io.BytesIO(blob))
    paras = [q for q in d.element.xpath("//w:p")
             if not any(True for _ in q.iterancestors(f"{_MC}Fallback"))
             and q.find(".//" + qn("w:txbxContent")) is None]
    return [pw._own_text(q) for q in paras]


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("step,base", [s for s in STEPS if s[0] != "revisit3"])
def test_the_customer_document_keeps_his_words_through_every_base_pick(ran, layout, step, base):
    """What the page hands /api/generate after each pick, through the real renderer: the base line
    under "Base Bid" is his words with the picked tab's amount (or his own figure), words for the
    system and tax wording; his typed note prints under it as its own lines; the base's tax rows
    under that are that tab's, his "Total, all in" among them. On the Polish base the Polish
    template renders it. Mutations: the old rule, and the description swap off, as the editor test
    above. (The own-figure step changes nothing printed at step 5 -- the figure he typed IS the
    tab's -- so the editor test's mark and warning are what catch that one.)"""
    s = ran["basePick"][layout][step]
    want_line, want_tax, _ = EXPECT[layout][step]
    assert s["doc"]["work_type"] == ("polish" if base == "Polish" else "epoxy")
    texts = _document(s["doc"])
    i = texts.index("Base Bid")
    assert texts[i + 1].rstrip() == want_line, texts[i:i + 4]
    assert texts[i + 2:i + 4] == NOTE, texts[i:i + 6]
    # The base's own tax rows: every one straight after the note, and nothing past them (an
    # option's itemised rows sit under the Options heading, further down).
    j = i + 4
    rows = []
    while j < len(texts) and _TAX_ROW.match(texts[j]):
        rows.append(texts[j])
        j += 1
    assert rows == want_tax, texts[i:j + 1]


# ── which line of a line saved in the old shape is the price line ────────────────────────────────
_COPY_LINE = f"$15,149 – {_EPOXY} (material sales tax INCLUDED)"
_EPOXY_LINE = f"$7,447 – {_EPOXY} (material sales tax INCLUDED)"


def _base_block(texts):
    """The paragraphs from "Base Bid" down to the Options heading (or the next four)."""
    i = texts.index("Base Bid")
    j = next((k for k in range(i + 1, len(texts)) if texts[k].rstrip().startswith("Options")), i + 5)
    return [t.rstrip() for t in texts[i + 1:j] if t.strip()]


@pytest.mark.parametrize("case,note", [
    ("noteAbove", "Includes $500 cove allowance"),
    ("shapedNote", "$500 – cove allowance, included in the price below"),
])
def test_a_note_above_an_old_shape_base_line_survives_an_estimate_pick(ran, case, note):
    """Hanz's own path, the Estimate strip's radio, on a base line saved in the old shape with a
    note typed ABOVE its price line that carries a figure. The pick migrates the price line (at
    Epoxy's figure, a tab's: the live amount, reading as the tool prints it, so no edit) and keeps
    the note as a line of his own; the Proposal step and the customer's document print the note,
    then the picked tab's line, once, with nothing to warn about. It used to take the note for the
    price line (the first line with a "$"): the note was deleted, and the real price line was saved
    as a typed line that printed "$7,447 – …" under the $15,149 one, unwarned.
    Mutations: the migration's price-shape steps off (both cases); applyBasePick given no tab
    figures (the note that reads like a price line itself)."""
    r = ran["oldShape"][case]
    assert r["pov"]["lines"] == {}, r["pov"]
    assert r["pov"]["before"] == {"base": [note]}, r["pov"]
    assert "base" not in (r["pov"].get("after") or {}), r["pov"]
    assert r["rows"] == [{"kind": "extra", "text": note, "money": False},
                         {"kind": "line", "text": _COPY_LINE, "money": False}], r["rows"]
    assert r["warnings"] == []
    block = _base_block(_document(r["doc"]))
    assert block[:2] == [note, _COPY_LINE], block
    assert not any("$7,447" in t for t in block), block


def test_a_note_quoting_another_tabs_figure_is_not_taken_for_the_price_line(ran):
    """"Polish alternative quoted separately at $9,860" -- Polish's own total -- typed above the
    base line in the old shape. Drawn: the note is his line and the price line is the live one;
    after an Estimate-step pick the note is still above the picked tab's line, in the editor and
    the document, and no figure is frozen anywhere. It used to become the base line ("Polish
    alternative quoted separately at $7,447"), and the pick then deleted it. Mutation: the build
    this fixes (every tab's figure a candidate anywhere, no price-shape steps)."""
    q = ran["oldShape"]["quotedTab"]
    note = "Polish alternative quoted separately at $9,860"
    assert q["rows"] == [{"kind": "extra", "text": note, "money": False},
                         {"kind": "line", "text": _EPOXY_LINE, "money": False}], q["rows"]
    assert q["warnings"] == [] and q["pov"]["lines2"] == {} and q["pov"]["before"] == {"base": [note]}, q
    p = q["picked"]
    assert p["rows"] == [{"kind": "extra", "text": note, "money": False},
                         {"kind": "line", "text": _COPY_LINE, "money": False}], p["rows"]
    assert p["warnings"] == []
    assert _base_block(_document(p["doc"]))[:2] == [note, _COPY_LINE]


def test_a_tabs_figure_in_the_lines_own_words_is_never_its_amount(ran):
    """"$7,000 – Epoxy flooring, Polish alternative $9,860 (…)" on the $15,149 copy: no tab prices
    $7,000, so it is his figure -- kept, marked, and Send asks -- and Polish's $9,860 in his words
    stays $9,860. It used to be made the live amount: the line printed "…, Polish alternative
    $15,149" beside his $7,000, and nothing warned (the stored line had a marker, so it was not
    "his figure"). Mutation: a tab's figure matched anywhere in the line."""
    w = ran["oldShape"]["inWords"]
    assert w["pov"]["lines2"] == {"base": f"$7,000 – Epoxy flooring, Polish alternative $9,860 {TAX}"}, w["pov"]
    assert w["rows"] == [{"kind": "line", "text": "$7,000 – Epoxy flooring, Polish alternative $9,860 "
                                                  "(material sales tax INCLUDED)", "money": True}], w["rows"]
    assert w["warnings"] == [{"key": "base", "says": "$7,000", "estimate": "$15,149"}]


def test_hanz_fix_revision_5_stays_his_and_warned_through_base_picks(ran):
    """Revision 5 as staging holds it: base Epoxy copy $15,149, the base line frozen at Epoxy's
    $7,447 in revision 1, and Epoxy re-priced to $7,696 since. No tab prices $7,447 today and
    nothing on the page remembers a tab's old price, so the line is treated as a figure of his
    own: kept, marked, and Send, Download and To Dropbox ask -- the tool does NOT silently re-price
    it. His notes are lines of their own. A base pick away and back on the Estimate step KEEPS it
    (Hanz, 2026-09-26: keep the words, warn on all three): still his figure, still marked, still
    asked about. Mutations: any first figure of an old-shape line made the live amount (the line
    would be rewritten to $15,149 without asking); the old rule (the picks forget it)."""
    r = ran["rev5"]
    notes = [("extra", ""), ("extra", "THis is a test send to Hanz"), ("extra", ""), ("extra", "12312312312312a")]
    assert [(x["kind"], x["text"]) for x in r["rows"]] == [("line", _EPOXY_LINE)] + notes, r["rows"]
    assert r["rows"][0]["money"] is True
    assert r["lines2"] == {"base": f"$7,447 – {_EPOXY} {TAX}"}, r["lines2"]
    assert r["warnings"] == [{"key": "base", "says": "$7,447", "estimate": "$15,149"}]
    a = r["afterPicks"]
    assert [(x["kind"], x["text"]) for x in a["rows"]] == [("line", _EPOXY_LINE)] + notes, a["rows"]
    assert a["rows"][0]["money"] is True
    assert a["warnings"] == [{"key": "base", "says": "$7,447", "estimate": "$15,149"}], a
    assert a["lines2"]["base"] == f"$7,447 – {_EPOXY} {TAX}", a


_DELETE_KEPT = {"manual:0": f"{AMT} – Joint filler, per plan",
                "option:Polish": f"{AMT} – Polished Concrete, 800 grit, warehouse only {TAX}",
                "option:Epoxy": f"{AMT} – Epoxy as an option {TAX}"}


@pytest.mark.parametrize("case,stored,line,money", [
    ("money", f"$15,000 – {_EPOXY} {TAX}", f"$15,000 – {_EPOXY} (material sales tax INCLUDED)", True),
    ("words", f"{AMT} – Epoxy flooring, whole building incl. mezzanine {TAX}",
     "$7,447 – Epoxy flooring, whole building incl. mezzanine (material sales tax INCLUDED)", False),
])
def test_deleting_the_base_copy_keeps_its_base_line_like_a_pick(ran, case, stored, line, money):
    """The base is Epoxy copy and he edited its base line on the Proposal step -- a figure of his
    own ("$15,000 – …") or his words about the copy's scope ("… whole building incl. mezzanine").
    Deleting the copy on the Estimate step moves the base to the one the sheet derives (Epoxy): the
    line keeps his words, a figure of his own stays his (marked, and asked about: $15,000 against
    Epoxy's $7,447), a live amount is Epoxy's. The note he typed under the line stays, and so does
    everything no base pick touches (a manual line, an option line, the option line of the tab that
    is now the base). Mutation: the old rule (applyBasePick deletes the base line: Epoxy's computed
    line, his words and figure gone). Deleting without the rule at all changes nothing here -- the
    frozen case below is the one that needs the rule to run at the delete."""
    r = ran["deleteBase"][case]
    assert r["savedBase"] is None and r["base"] == "Epoxy", r
    assert r["pov"]["lines2"] == dict(_DELETE_KEPT, base=stored), r["pov"]
    assert r["pov"]["after"] == {"base": NOTE}, r["pov"]
    assert r["rows"] == [{"kind": "line", "text": line, "money": money},
                         {"kind": "extra", "text": "", "money": False},
                         {"kind": "extra", "text": "THis is a test send to Hanz", "money": False}], r["rows"]
    assert r["warnings"] == ([{"key": "base", "says": "$15,000", "estimate": "$7,447"}] if money else [])
    block = _base_block(_document(r["doc"]))
    assert block[:2] == [line, "THis is a test send to Hanz"], block


def test_deleting_the_base_copy_migrates_a_line_frozen_at_the_copys_figure_while_it_can(ran):
    """The copy's base line in the old shape, frozen at the COPY's own $15,149, the note he typed
    under it inside it. The rule runs at the delete, while priced_tabs still holds the copy: its
    figure is a tab's, so it is the tool's -- the live amount, reading as the tool prints it, no edit
    -- and the note is a line of its own. The Proposal step then opens the draft priced without the
    copy: Epoxy's own line, the note under it, nothing to ask.
    Mutations: deleteTab without the rule; the rule leaving old-shape lines to be migrated when
    drawn (by then no tab prices $15,149: "$15,149 – …" under Epoxy's $7,447, marked and asked)."""
    r = ran["deleteBase"]["frozen"]
    assert r["savedBase"] is None and r["base"] == "Epoxy", r
    assert r["pov"]["lines"] == {} and r["pov"]["lines2"] == _DELETE_KEPT, r["pov"]
    assert r["pov"]["after"] == {"base": NOTE}, r["pov"]
    assert r["rows"] == [{"kind": "line", "text": _EPOXY_LINE, "money": False},
                         {"kind": "extra", "text": "", "money": False},
                         {"kind": "extra", "text": "THis is a test send to Hanz", "money": False}], r["rows"]
    assert r["warnings"] == []
    block = _base_block(_document(r["doc"]))
    assert block[:2] == [_EPOXY_LINE, "THis is a test send to Hanz"], block
    assert not any("$15,149" in t for t in block), block


# ── an old-shape base line the tool printed under Broken out (review of dfcf589) ─────────────────
_COPY_BROKEN = f"$14,954 – {_EPOXY}"
_COPY_ONE = f"$15,149 – {_EPOXY} (material sales tax INCLUDED)"


@pytest.mark.parametrize("case", ["broken", "undecided"])
def test_a_pick_reads_an_old_shape_base_line_the_way_drawing_it_would(ran, case):
    """"$7,351 – Epoxy flooring as described above": Epoxy's pre-tax figure and the tool's own
    words, frozen by the old sweep under Broken out (set, or undecided on a taxable base), which
    prints no tax wording. Drawn first, the Proposal step migrates it with the base line's tax slot
    and it is no edit. The Estimate strip meeting it FIRST used to migrate it with no slot: kept as
    an edit with no tax marker, so once the layout was One line the customer's base line printed
    the tax-inclusive price with no tax wording. Both orders now agree: nothing kept, and the
    picked tab's line under either layout, in the editor and the document.

    Mutations: applyBasePick's base-line migration without the phrase and slot (the old one); the
    strip's call without basePhrase; draftBasePhrase blind to the layout (always One line's)."""
    r = ran["brokenOutLegacy"][case]
    for order in ("pickedFirst", "drawnFirst"):
        o = r[order]
        assert o["lines2"] == {}, (order, o["lines2"])
        assert not (o.get("lines") or {}).get("base"), (order, o.get("lines"))
        assert o["broken"]["rows"] == [{"kind": "line", "text": _COPY_BROKEN, "money": False}], (order, o["broken"])
        assert o["oneLine"]["rows"] == [{"kind": "line", "text": _COPY_ONE, "money": False}], (order, o["oneLine"])
        assert o["oneLine"]["warnings"] == [] and o["broken"]["warnings"] == []
    assert _base_block(_document(r["pickedFirst"]["oneLine"]["doc"]))[:1] == [_COPY_ONE]
    assert _base_block(_document(r["pickedFirst"]["broken"]["doc"]))[:1] == [_COPY_BROKEN]


def test_a_base_line_with_its_tax_wording_taken_out_under_one_line_keeps_none_through_a_pick(ran):
    """The counterexample, the shape De Soto's prod draft holds: "$1,870.00 – Epoxy flooring as
    described above" under One line, where the tool printed the wording, so its absence is his. A
    pick keeps it without wording in both orders (his words, the new base's amount), under either
    layout. Without this, the test above passes for a rule that gives every line the tax marker."""
    r = ran["brokenOutLegacy"]["deSoto"]
    for order in ("pickedFirst", "drawnFirst"):
        o = r[order]
        assert o["lines2"] == {"base": f"{AMT} – {_EPOXY}"}, (order, o["lines2"])
        assert o["oneLine"]["rows"] == [{"kind": "line", "text": f"$15,149 – {_EPOXY}", "money": False}], o
        assert o["asSaved"]["rows"] == o["oneLine"]["rows"], o
    assert _base_block(_document(r["pickedFirst"]["oneLine"]["doc"]))[:1] == [f"$15,149 – {_EPOXY}"]


def test_the_sidebar_reads_an_undrawn_old_shape_base_line_the_same_way(ran):
    """The sidebar meets such a line only where the price box never drew it: a combined base (its
    base row is hidden) with no document built yet. Picked to one tab under Broken out, the line
    keeps its tax marker, and a later One line prints the wording.

    Mutation: the sidebar's call without basePhrase (the marker is not added: no wording)."""
    s = ran["brokenOutLegacy"]["sidebar"]
    assert s["untouched"] == {"base": f"$7,351 – {_EPOXY}"}, "the scenario lost its point: it was drawn"
    assert s["lines2"] == {"base": f"{AMT} – {_EPOXY} {TAX}"}, s["lines2"]
    assert s["oneLine"]["rows"] == [{"kind": "line", "text": _COPY_ONE, "money": False}], s["oneLine"]


def test_deleting_the_base_copy_reads_an_old_shape_line_printed_under_broken_out_alike(ran):
    """The copy's base line in the old shape, "$14,954 – Epoxy flooring as described above" (its
    pre-tax figure under Broken out, the tool's own words). Deleting the copy moves the base to
    Epoxy; the Proposal step then opens under One line: Epoxy's line with its wording.

    Mutation: deleteTab's call without basePhrase (the line is kept with no tax marker, and the
    One-line document prints no wording)."""
    r = ran["deleteBase"]["brokenOut"]
    assert r["base"] == "Epoxy" and r["pov"]["lines"] == {}, r
    assert "base" not in r["pov"]["lines2"], r["pov"]["lines2"]
    assert r["rows"] == [{"kind": "line", "text": _EPOXY_LINE, "money": False}], r["rows"]
    assert _base_block(_document(r["doc"]))[:1] == [_EPOXY_LINE]


def test_the_tax_wording_the_base_line_prints_is_read_off_the_draft():
    """TWPrice.draftBasePhrase, what the Estimate step hands the pick: "" under Broken out (chosen,
    the old three-way answer, or undecided on a taxable base), the One-line wording otherwise --
    including the four prod drafts' own shapes (EXEMPT on a zero-tax tab, INCLUDED on a taxed one).
    And applyBasePick reading the same old-shape line under each."""
    got = _node_core("""(P) => [
        P.draftBasePhrase({ tax_layout: 'BROKEN_OUT', proposal_sales_tax: 96, proposal_taxable: true }),
        P.draftBasePhrase({ tax_inclusion: 'BROKEN_OUT', proposal_sales_tax: 96 }),
        P.draftBasePhrase({ proposal_sales_tax: 96, proposal_taxable: true }),
        P.draftBasePhrase({ tax_inclusion: 'INCLUDED', proposal_sales_tax: 96, proposal_taxable: true }),
        P.draftBasePhrase({ tax_inclusion: 'EXEMPT', proposal_sales_tax: 0, proposal_remodel_tax: 0 }),
        P.draftBasePhrase({ tax_layout: 'ONE_LINE', proposal_sales_tax: 110, proposal_remodel_tax: 745 }),
        P.draftBasePhrase({ proposal_sales_tax: 0, proposal_remodel_tax: 0, proposal_taxable: false }),
        P.draftBasePhrase(null)]""")
    assert got == ["", "", "", "(material sales tax INCLUDED)", "(tax exempt)",
                   "(Remodel Tax AND material sales tax INCLUDED)", "(tax exempt)", ""], got
    line = {"lines": {"base": f"$7,351 – {_EPOXY}"}}
    outs = [_node_core(_PICK, line, "Epoxy", "Copy1", _TABS, opts)[1]
            for opts in ({"workType": "epoxy", "basePhrase": ""},
                         {"workType": "epoxy", "basePhrase": "(material sales tax INCLUDED)"},
                         {"workType": "epoxy"})]
    assert outs[0].get("lines2", {}) == {}, outs[0]
    assert outs[1]["lines2"] == {"base": f"{AMT} – {_EPOXY}"}, outs[1]
    assert outs[2]["lines2"] == {"base": f"{AMT} – {_EPOXY}"}, outs[2]
