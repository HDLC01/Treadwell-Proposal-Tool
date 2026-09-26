"""Picking a different base bid moves the proposal to that tab's price, from either picker.

Hanz, 2026-09-26, on staging, on the "Hanz Fix" test project (Epoxy $7,447, "Epoxy copy" $15,149,
a Polish tab): "I had an error in the proposal tool where the base bid was not updating". He picked
another base tab on the Estimate page, and the proposal went on quoting the old tab's price.

WHAT WAS WRONG, three ways at once:

  * THE TWO PICKERS DISAGREED. The Proposal step's sidebar forgot the old base's edited price lines
    when the base changed; the Estimate step's bid strip forgot only the oldest bucket
    (price_overrides.single_bid). A base line saved with the old tab's figure in it -- a figure he
    typed, or one the old whole-line editor froze -- went on printing under the new base, on screen
    and in the customer's document. Now both apply ONE rule, TWPrice.forgetBaseLines.
  * A LINE FROZEN AT THE OLD BASE'S FIGURE was read as his own. Hanz Fix's revisions 2-5 printed
    "$7,447 – Epoxy flooring as described above" as the base bid of a $15,149 job: he had typed a
    note under the base line while Epoxy was the base, the old editor froze Epoxy's figure into it,
    and the migration to the live shape only recognised TODAY's figure. Every figure this draft's
    own tabs priced the line at is the tool's (TWPrice.tabFigures) and becomes a live marker; a
    figure no tab ever priced stays his, marked, and Send asks (Hanz: warn, then let him send).
  * The sidebar's forgetting was never SAVED: the page's pricing save carries the base and the
    money, so leaving by a step pill put the old base's line back into the draft. And the Estimate
    strip's pick saved without re-pricing (a copy made a moment ago and picked at once was a base
    the Proposal step could not find), with the page's cell edits reverted to its load-time copy.

EXECUTED: js/price-lines-harness.js runs the Estimate step's real wireBidBar change handler and
savers, the Proposal step's real rebuildPricing, price box paint, box sweep and sidebar radio
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


# What each base prints, off Hanz Fix's own tabs. One line: the whole tax-inclusive bid with the
# wording for the taxes that tab's sheet says are in it. Broken out: the pre-tax figure and the rows
# that tab's flags call for, adding up.
_EPOXY = "Epoxy flooring as described above"
_POLISH = "Polished Concrete Flooring as described above"
EXPECT = {
    "ONE_LINE": {
        "Copy1": (f"$15,149 – {_EPOXY} (material sales tax INCLUDED)", []),
        "Polish": (f"$9,860 – {_POLISH} (Remodel Tax AND material sales tax INCLUDED)", []),
        "Epoxy": (f"$7,447 – {_EPOXY} (material sales tax INCLUDED)", []),
    },
    "BROKEN_OUT": {
        "Copy1": (f"$14,954 – {_EPOXY}", ["$195 – Material Sales Tax", "$15,149 – Total"]),
        "Polish": (f"$9,005 – {_POLISH}",
                   ["$110 – Material Sales Tax", "$745 – Remodel Tax", "$9,860 – Total"]),
        "Epoxy": (f"$7,351 – {_EPOXY}", ["$96 – Material Sales Tax", "$7,447 – Total"]),
    },
}
# The flow: (step, the base it ends on). 1 Estimate strip Epoxy -> Epoxy copy; 3 Proposal sidebar
# -> Polish (another work type); 4 sidebar -> Epoxy; 5 Estimate strip -> Epoxy copy again.
STEPS = [("proposal2", "Copy1"), ("sidebar3", "Polish"), ("revisit3", "Polish"),
         ("sidebar4", "Epoxy"), ("estimate5", "Copy1")]
LAYOUTS = ["ONE_LINE", "BROKEN_OUT"]


def _editor_rows(step):
    """(the base line, the lines typed under it, the tax rows) as the price box draws them."""
    rows = step["rows"]
    base = [r for r in rows if r["key"] == "base"]
    return (base[0]["text"], [r["text"] for r in base[1:] if r["kind"] == "extra"],
            [r["text"] for r in rows if r["key"] != "base" and r["kind"] == "line"])


# ── the editor ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("step,base", STEPS)
def test_the_price_box_follows_every_base_pick_on_either_picker(ran, layout, step, base):
    """The base line's amount, its description (Epoxy <-> Polished Concrete) and its tax wording,
    and the tax rows under it, are the picked tab's -- after a pick on the Estimate step read by
    the Proposal step, after a pick in the Proposal step's sidebar, and on the next visit after
    leaving it. Nothing is marked as edited and Send has nothing to ask. The note he typed under
    the base line is still there. Mutations: the Estimate strip forgets only single_bid again (the
    base line keeps his $7,500); the sidebar's forgetting is not saved (the revisit brings back his
    $15,000 under the Polish base, Epoxy words and all)."""
    s = ran["basePick"][layout][step]
    line, typed, tax = _editor_rows(s)
    want_line, want_tax = EXPECT[layout][base]
    assert s["base_tab_id"] == base, s["base_tab_id"]
    assert line == want_line, (step, line)
    assert tax == want_tax, (step, tax)
    assert typed == NOTE, (step, typed)
    assert not any(r["cue"] for r in s["rows"] if r["kind"] == "line"), s["rows"]
    assert s["warnings"] == [], s["warnings"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_estimate_strip_applies_the_proposal_steps_rule_and_prices_the_pick(ran, layout):
    """The pick on the Estimate step: the old base's lines go (his hand-typed $7,500 base line, the
    sweep's frozen Epoxy tax rows, the option line of the tab that is now the base), the lines he
    TYPED stay (under the base, around that option line, on the gap above "Options:"), and so does
    everything no base pick changes (a manual price line he re-worded, a total-priced option he
    re-worded). And it is PRICED and saved with this visit's cell edits. Mutations: call
    persistBidOptions again (no pricing snapshot, and the saved cell edit goes back to 2000)."""
    e = ran["basePick"][layout]["estimate1"]
    assert e["base"] == "Copy1"
    assert e["snapshots"] == 1, "the pick was saved without re-pricing"
    assert e["cellValues"] == {"Epoxy!E20": 2400}, e["cellValues"]
    pov = e["pov"]
    assert pov["lines"] == {}, pov["lines"]
    assert pov["lines2"] == {"manual:0": f"{AMT} – Joint filler, per plan",
                             "option:Polish": f"{AMT} – Polished Concrete, 800 grit, warehouse only {TAX}"}
    assert pov["after"] == {"base": NOTE, "option:Copy1": ["Test again 123"]}, pov["after"]
    assert pov["before"] == {"heading_options": ["TEST123"], "option:Copy1": ["", ""]}, pov["before"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_sidebar_pick_forgets_the_old_bases_lines_and_saves_it(ran, layout):
    """He typed a figure of his own into the base line on the Proposal step, then picked Polish in
    its sidebar and left by a step pill. What the page saved no longer carries that line, the
    option line of the tab that is now the base is gone too, the template was reloaded for the
    new work type, and what he typed elsewhere is untouched. Mutations: drop the save; put back
    the sidebar's old loop (every edit except the alternate's goes, his typed lines and the
    manual line's words with them)."""
    p2 = ran["basePick"][layout]["proposal2"]
    assert p2["typed"] == f"$15,000 – {_EPOXY} {TAX}", p2["typed"]
    s = ran["basePick"][layout]["sidebar3"]
    assert s["reloads"] == 1
    saved = s["savedPov"]
    assert "base" not in saved.get("lines2", {}) and "base" not in saved.get("lines", {}), saved
    assert saved["lines2"] == {"manual:0": f"{AMT} – Joint filler, per plan"}, saved["lines2"]
    assert saved["after"] == {"base": NOTE, "option:Copy1": ["Test again 123"]}, saved["after"]
    assert saved["before"]["heading_options"] == ["TEST123"], saved["before"]


# ── a line frozen at the OLD base's figure ───────────────────────────────────────────────────────
def test_a_line_frozen_at_the_old_bases_figure_follows_the_estimate_again(ran):
    """Hanz Fix's revisions 2-5, exactly: base Epoxy copy $15,149, the base line saved with Epoxy's
    $7,447 and his note inside it. Drawn once: the computed line (nothing stored for it), his note
    a line of its own, nothing marked, nothing for Send to ask. Mutation: migrate against today's
    figure only (TWPrice.tabFigures dropped) -- the line stays at $7,447, marked, and Send asks."""
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


def test_the_base_pick_rule_forgets_the_old_bases_lines_and_nothing_else():
    """TWPrice.forgetBaseLines, the one rule both pickers apply, over every kind of saved edit:
    the base line, its tax rows and Total and the combo lines go, both shapes; so do the option
    lines of the tab that was the base and the one that now is, their own tax rows included. Every
    other option keeps its edit -- priced at its own total or as add/deduct, whose amount is a live
    marker that follows the new base -- and so do manual lines, the headings, the lines typed on
    the gap and the alternate. A line saved in the old shape gives up the lines typed inside it
    first, and lines typed next to a forgotten line stay where they were."""
    pov = {
        "single_bid": {"amount": "$1"}, "rows": {"x": 1}, "combo": {"y": 2},
        "lines": {
            "base": "$7,447 – Epoxy flooring as described above\n\nnote under it",
            "total": "$0 – Total", "combo:epoxy": "$1 – combo",
            "option:Copy1": "\n$15,149 – the copy\nunder the copy",
            "option:Seal": "Add $1,200 – Sealed Concrete in lieu of flake",
            "manual:0": "$1,500 – Joint filler, per plan", "heading_base": "Base Bid:",
        },
        "lines2": {
            "sales_tax": f"{AMT} – Material Sales Tax (by hand)", "remodel": "$10 – Remodel Tax",
            "option:Epoxy": f"{AMT} – was an option once {TAX}", "option:Epoxy:total": f"{AMT} – Total",
            "option:Polish": f"{AMT} – Polished Concrete, warehouse only {TAX}",
            "option:Polish:total": f"{AMT} – Total, Polish", "heading_options": "Options & Alternates:",
            "alt_total": "$9 – Total",
        },
        "after": {"base": ["kept"], "option:Copy1": ["typed before"]},
        "before": {"heading_options": ["on the gap"]},
    }
    changed, out = _node_core("(P, pov) => [P.forgetBaseLines(pov, 'Epoxy', 'Copy1'), pov]", pov)
    assert changed is True
    assert out["single_bid"] == {} and out["rows"] == {} and out["combo"] == {}
    assert out["lines"] == {"option:Seal": "Add $1,200 – Sealed Concrete in lieu of flake",
                            "manual:0": "$1,500 – Joint filler, per plan", "heading_base": "Base Bid:"}
    assert out["lines2"] == {"option:Polish": f"{AMT} – Polished Concrete, warehouse only {TAX}",
                             "option:Polish:total": f"{AMT} – Total, Polish",
                             "heading_options": "Options & Alternates:", "alt_total": "$9 – Total"}
    # Typed lines already stored stay as they are; the old-shape line gives up the ones inside it
    # only where nothing is stored for that line yet.
    assert out["after"] == {"base": ["kept"], "option:Copy1": ["typed before"]}
    assert out["before"] == {"heading_options": ["on the gap"], "option:Copy1": [""]}
    # And from the old shape into empty buckets: the note typed inside the base line survives.
    changed2, out2 = _node_core("(P, pov) => [P.forgetBaseLines(pov, 'Epoxy', 'Copy1'), pov]",
                                {"lines": {"base": "$7,447 – Epoxy flooring\n\nTHis is a test send to Hanz"}})
    assert changed2 is True and out2["lines"] == {} and out2["after"] == {"base": NOTE}
    # Nothing base-bound saved: nothing to forget, and nothing reported.
    changed3, _ = _node_core("(P, pov) => [P.forgetBaseLines(pov, 'Epoxy', 'Copy1'), pov]",
                             {"lines2": {"manual:0": "x"}})
    assert changed3 is False
    assert _node_core("(P) => P.forgetBaseLines(null, 'Epoxy', 'Copy1')") is False


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
    """The bid strip calls TWPrice.forgetBaseLines, so price-lines-core.js must load on the
    Estimate page, before the page's own script (test_frontend_boot_order pins the order)."""
    html = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    core = html.index('src="/js/price-lines-core.js')
    assert core < html.index('src="/js/estimate-review.js"')


# ── the document ────────────────────────────────────────────────────────────────────────────────
_BASE_VALUES = {"project_name": "Hanz Fix", "job_name": "Hanz Fix", "city_state": "Iloilo City, KS",
                "texture": "Smooth", "system_name": "Treadwell 3/16\" Urethne Cement",
                "scope_notes": "s", "schedule_notes": "s", "exclusions": "e",
                "estimator_name": "Hanz", "bid_date_formatted": "9/25/26"}
_TAX_ROW = re.compile(r"^\$[\d,]+(?:\.\d+)? – (?:Material Sales Tax|Remodel Tax|Total)$")


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
def test_the_customer_document_follows_every_base_pick(ran, layout, step, base):
    """What the page hands /api/generate after each pick, through the real renderer: the base line
    under "Base Bid" is the picked tab's (amount, description, tax wording), his typed note prints
    under it as its own lines, and the base's tax rows under that are that tab's and only those. On
    the Polish base the Polish template renders it. Mutations: as the editor test above."""
    s = ran["basePick"][layout][step]
    want_line, want_tax = EXPECT[layout][base]
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
    assert not any("$7,500" in t or "$15,000" in t for t in texts)
