"""The Files page's "Ready to generate" card lists every proposal of the estimate (Hanz, 2026-10-27).

A draft that is one of several proposals made from one estimate (Create Multiple Proposals) shows, in
the card's LUMP SUM row, one line per proposal: its name and its own lump sum, this one marked
"(this one)" and carrying the very figure the card showed before (the saved document's total), one
with no figure yet "not priced yet", and NO total: they are separate proposals, each approved on its
own. A draft with no proposals keeps the single figure exactly.

Run, not read: js/ready-proposals-harness.js executes done.js's paintReadyProposals and the card's
own figure statements over a small DOM. The BREAKS prove each check goes red when its line goes.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "ready-proposals-harness.js"


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def out():
    require_node()
    return run()


def _lines(card):
    return [(r["current"], [p[1] for p in r["parts"]]) for r in card["rows"]]


def test_a_childs_card_lists_every_proposal_with_its_own_figure(out):
    c = out["child"]
    assert c["asked"] == ["C2"]
    assert _lines(c) == [
        (False, ["Breakroom", "$20,000.00"]),
        (True, ["Room 2", "$15,999.00", "(this one)"]),
        (False, ["Kitchen", "not priced yet"]),
    ], "this one carries the card's own figure (the document's total), not the server's"
    assert c["money"] is False


def test_the_parents_card_marks_the_parent(out):
    assert _lines(out["parent"]) == [
        (True, ["Breakroom", "$20,000.00", "(this one)"]),
        (False, ["Room 2", "$15,000.50"]),
        (False, ["Kitchen", "not priced yet"]),
    ]


def test_no_project_total_is_shown(out):
    for k in ("child", "parent"):
        c = out[k]
        assert "$50,999" not in c["text"] and "$35,999" not in c["text"] and "$35,000" not in c["text"]
        assert "total" not in c["text"].lower()
        assert len(c["rows"]) == 3
        assert c["note"] == "Separate proposals, each approved on its own. Generate builds this one."


@pytest.mark.parametrize("k", ["alone", "noList", "throws", "notAmong"])
def test_a_draft_with_no_proposals_keeps_the_single_figure(out, k):
    c = out[k]
    assert c == {"asked": c["asked"], "text": "$7,447.00", "money": True, "rows": None, "note": None}


def test_the_single_figure_still_falls_back_to_the_display(out):
    assert out["display"]["text"] == "$5,000.00" and out["display"]["rows"] is None


def test_another_built_proposal_shows_the_total_its_document_prints(out):
    """`document_total` (proposals_view: that proposal's saved payload's Total) wins over its
    proposal_lump_sum; one with no digit in it falls back, and an unbuilt one is still not priced."""
    assert _lines(out["built"]) == [
        (True, ["Breakroom", "$20,000.00", "(this one)"]),
        (False, ["Room 2", "$15,250.00"]),
        (False, ["Kitchen", "not priced yet"]),
    ]


BREAKS = {
    "the list is never drawn": (
        "js/done.js", "      paintReadyProposals(pv, TW.getDraftId(), lumpEl ? lumpEl.textContent : \"\");", "      void 0;",
        lambda r: r["child"]["rows"] is None),
    "this one takes the server's figure": (
        "js/done.js", "      const fig = mine ? (currentFigure || theirs) : theirs;",
        "      const fig = n == null ? \"\" : usd(n);",
        lambda r: _lines(r["child"])[1][1][1] != "$15,999.00"),
    "another proposal's figure is its lump_sum, not its document's": (
        "js/done.js", "      const theirs = doc || (n == null ? \"\" : usd(n));",
        "      const theirs = n == null ? \"\" : usd(n);",
        lambda r: _lines(r["built"])[1][1][1] != "$15,250.00"),
    "this one is not marked": (
        "js/done.js", "      if (mine) {", "      if (false) {",
        lambda r: "(this one)" not in r["child"]["text"]),
    "an unpriced proposal reads as a figure": (
        "js/done.js", "      sum.textContent = fig && fig !== \"—\" ? fig : \"not priced yet\";", "      sum.textContent = fig || \"$0.00\";",
        lambda r: "not priced yet" not in r["child"]["text"]),
    "one proposal draws a list": (
        "js/done.js", "    if (!el || ms.length < 2 || !ms.some((m) => m && m.id === currentId)) return false;",
        "    if (!el || !ms.length) return false;",
        lambda r: r["alone"]["rows"] is not None or r["notAmong"]["rows"] is not None),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    proc = run_node(HARNESS, frontend)
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name
