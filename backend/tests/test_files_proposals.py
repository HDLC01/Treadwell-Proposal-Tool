"""Step 5 FILES lists every proposal of the project, by its sheet's name (Hanz, 2026-10-29).

"could we also show multiple lump sums here? before we send out", and "show the sheet names in the
5. Files section as well". On the generated card of a draft that is one of several proposals made
from one estimate (Create Multiple Proposals): the LUMP SUM column lists every proposal in the strip's
order, its sheet's name and the figure ITS document prints, this one marked "(this one)" and carrying
the card's own figure, one with none "not priced yet", NO total, each other name a link to its own
Files page; the header names this proposal by its sheet; the Sent versions card says whose versions
they are; the Send card names the proposals its one email is for. The list repaints with the figure on
every arrival (a regenerate, the page Send all comes back to after building) and every download. A
one-proposal project stays exactly as it was.

Run, not read: js/files-proposals-harness.js executes done.js's own functions and the head of
showPostGenerate over a small DOM. The BREAKS prove each check goes red when its line goes.
"""
from __future__ import annotations

import pathlib

import pytest

import drafts
from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-proposals-harness.js"


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def out():
    require_node()
    return run()


def _lines(card):
    return [(r["current"], [p[2] for p in r["parts"]]) for r in card["rows"]]


def _links(card):
    return [r["parts"][0][3] for r in card["rows"]]


UNCHANGED = {"rowHidden": False, "rowClass": "fp-money", "key": "Lump sum", "text": "$7,447.00", "rows": None,
             "note": None, "which": None, "whichName": None, "revWhich": None, "sendWhich": None}


@pytest.mark.parametrize("k", ["single", "singleNoList"])
def test_a_one_proposal_project_is_exactly_as_it_was(out, k):
    c = dict(out[k])
    assert c.pop("asked") == ["S1"]
    assert c.pop("project") == "Acme Plant · EPOXY · Direct"
    assert c == UNCHANGED


def test_three_proposals_list_three_rows_with_their_own_figures_and_no_total(out):
    c = out["three"]
    assert c["asked"] == ["C2"]
    assert _lines(c) == [
        (False, ["Breakroom", "$20,000.00"]),
        (True, ["Polish Room 2", "$15,999.00", "(this one)"]),
        (False, ["Kitchen", "not priced yet"]),
    ], "this one carries the card's own figure (its document's total), the others their documents'"
    assert c["note"] == "Separate proposals, each approved on its own. Each line's buttons download that one's files."
    assert "total" not in c["text"].lower() and "$35,999" not in c["text"] and "$35,000" not in c["text"]
    assert c["key"] == "Lump sums" and "fp-money--list" in c["rowClass"].split() and c["rowHidden"] is False


def test_each_other_proposal_links_to_its_own_files_page(out):
    assert _links(out["three"]) == ["/done.html?d=P1", None, "/done.html?d=C3"]
    assert [r["parts"][0][0] for r in out["three"]["rows"]] == ["A", "SPAN", "A"]


def test_the_header_names_this_proposal_by_its_sheet(out):
    c = out["three"]
    assert c["whichName"] == "Polish Room 2"
    assert c["which"] == "Polish Room 2 · proposal 2 of 3"
    assert c["project"] == "Acme Plant · EPOXY · Direct", "the project line is kept"


def test_sent_versions_and_the_send_card_name_the_proposals(out):
    c = out["three"]
    assert c["revWhich"] == "Sent versions of Polish Room 2 only. Each proposal keeps its own."
    assert c["sendWhich"] == ("One email for Breakroom, Polish Room 2 and Kitchen. It names each one "
                              "that is new or changed since the customer last got it.")


def test_a_project_split_into_scopes_lists_and_names_every_proposal_send_all_sends(out):
    """REVIEW FINDING: the other scope's proposals are in the email too, so they are on the list
    (after the strip, a link to their own Files page) and in the Send card's sentence."""
    c = out["scoped"]
    assert _lines(c) == [
        (False, ["Breakroom", "$20,000.00"]),
        (True, ["Polish Room 2", "$15,999.00", "(this one)"]),
        (False, ["Kitchen", "not priced yet"]),
        (False, ["Office", "$5,100.00"]),
    ]
    assert _links(c)[3] == "/done.html?d=S9"
    assert c["which"] == "Polish Room 2 · proposal 2 of 4"
    assert c["sendWhich"].startswith("One email for Breakroom, Polish Room 2, Kitchen and Office.")


def test_a_scope_whose_own_strip_is_one_still_lists_the_project(out):
    """Office's own page: one row in its strip, three more in its group. The button is Send all, so
    the page says what it sends and lists every price, never a single LUMP SUM."""
    c = out["scopeAlone"]
    assert c["key"] == "Lump sums"
    assert _lines(c) == [
        (True, ["Office", "$5,100.00", "(this one)"]),
        (False, ["Breakroom", "$20,000.00"]),
        (False, ["Polish Room 2", "$15,000.50"]),
        (False, ["Kitchen", "not priced yet"]),
    ]
    assert c["sendWhich"].startswith("One email for Office, Breakroom, Polish Room 2 and Kitchen.")


def test_the_send_card_says_nothing_where_the_button_is_not_send_all(out):
    assert out["unpriced"]["sendWhich"] is None and out["late"]["sendWhich"] is None


def test_a_proposal_with_no_figure_says_not_priced_yet_and_the_list_still_shows(out):
    c = out["unpriced"]
    assert c["rowHidden"] is False, "paintLumpSum hid the single row; the list brings it back"
    assert _lines(c) == [
        (False, ["Breakroom", "$20,000.00"]),
        (False, ["Polish Room 2", "$15,000.50"]),
        (True, ["Kitchen", "not priced yet", "(this one)"]),
    ]
    assert c["which"] == "Kitchen · proposal 3 of 3"


def test_the_list_repaints_with_new_figures_after_a_regenerate(out):
    assert _lines(out["before"]) == [
        (True, ["Breakroom", "$20,000.00", "(this one)"]),
        (False, ["Polish Room 2", "$15,000.50"]),
        (False, ["Kitchen", "not priced yet"]),
    ]
    assert out["after"]["asked"] == ["P1", "P1"]
    assert _lines(out["after"]) == [
        (True, ["Breakroom", "$21,500.00", "(this one)"]),
        (False, ["Polish Room 2", "$15,000.50"]),
        (False, ["Kitchen", "$9,100.00"]),
    ]


def test_a_failed_read_keeps_the_last_list(out):
    c = out["readFails"]
    assert c["asked"] == ["P1", "P1", "P1"]
    assert _lines(c) == _lines(out["after"]) and c["key"] == "Lump sums"


def test_an_older_read_answering_late_is_dropped(out):
    assert _lines(out["late"])[2] == (False, ["Kitchen", "not priced yet"])


def test_a_project_back_to_one_proposal_gets_its_single_figure_back(out):
    c = dict(out["backToOne"])
    c.pop("asked"), c.pop("project")
    assert c == dict(UNCHANGED, text="$20,000.00")


BREAKS = {
    "the card never reads the proposals": (
        "js/done.js", "    refreshFilesProposals();   // every proposal of the project, beside the figure", "",
        lambda r: r["three"]["rows"] is None),
    "no links": (
        "js/done.js", "      if (opts && opts.link && !mine) nm.href = \"/done.html?d=\" + encodeURIComponent(m.id);", "",
        lambda r: _links(r["three"]) != ["/done.html?d=P1", None, "/done.html?d=C3"]),
    "the header does not name the proposal": (
        "js/done.js", "      which.hidden = false;", "      which.hidden = true;",
        lambda r: r["three"]["which"] is None),
    "sent versions do not say whose": (
        "js/done.js", "      revWhich.hidden = false;", "      revWhich.hidden = true;",
        lambda r: r["three"]["revWhich"] is None),
    "the send card names them without a Send all button": (
        "js/done.js", "    if (sendWhich && g && typeof g === \"object\" && g.id && pv.group_id === g.id) {",
        "    if (sendWhich) {",
        lambda r: r["unpriced"]["sendWhich"] is not None),
    "this one's figure is read after the list replaced it": (
        "js/done.js", "    const figure = row && val && !row.hidden ? val.textContent : \"\";", "    const figure = \"\";",
        lambda r: _lines(r["three"])[1][1][1] != "$15,999.00"),
    "an unpriced card keeps its row hidden": (
        "js/done.js", "    if (row) row.hidden = false;", "",
        lambda r: r["unpriced"]["rowHidden"] is not False),
    "the key keeps saying one lump sum": (
        "js/done.js", "    if (key) key.textContent = many ? \"Lump sums\" : \"Lump sum\";", "",
        lambda r: r["three"]["key"] != "Lump sums"),
    "a late read overwrites the newer one": (
        "js/done.js", "    if (seq !== filesProposals.seq) return;", "",
        lambda r: _lines(r["late"])[2][1][1] != "not priced yet"),
    "a failed read drops the list": (
        "js/done.js", "    if (pv) filesProposals.pv = pv;", "    filesProposals.pv = pv;",
        lambda r: r["readFails"]["rows"] is None),
    "back to one keeps the old list": (
        "js/done.js",
        "      if (row && val) { if (currentFigure) val.textContent = currentFigure; else row.hidden = true; }", "",
        lambda r: r["backToOne"]["text"] != "$20,000.00"),
    "the rest of the scope group is left out": (
        "js/done.js", "    if (pv && Array.isArray(pv.members) && others.length) {", "    if (false) {",
        lambda r: len(r["scoped"]["rows"] or []) != 4 or r["scopeAlone"]["rows"] is not None),
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


# ── the server's half: each proposal's document Total ─────────────────────────────────────────────


def test_the_view_carries_each_built_proposals_document_total(fake_supabase, monkeypatch):
    """proposals_view's `document_total` is that proposal's saved payload's Total, as written; None
    before it is built or when it holds no digit.

    Mutation: return None from drafts._document_total -- every row falls back to its lump_sum."""
    from test_multi_proposals import _fan, _row, _seed
    store = _seed(fake_supabase, monkeypatch)
    kids = [c["id"] for c in _fan(("Epoxy", "Copy1", "Polish"))["children"]]
    assert [m["document_total"] for m in drafts.proposals_view("p1")["members"]] == [None, None, None]
    _row(store, "p1")["data"]["proposal_payload"] = {"values": {"total_formatted": "$20,400.00 "}}
    _row(store, kids[0])["data"]["proposal_payload"] = {"values": {"total_formatted": "—"}}
    _row(store, kids[1])["data"]["proposal_payload"] = {"values": {"total_formatted": "$9,150.50"}}
    ms = drafts.proposals_view(kids[1])["members"]
    assert [m["document_total"] for m in ms] == ["$20,400.00", None, "$9,150.50"]
    assert [m["lump_sum"] for m in ms] == [20000, 15000, 9000], "lump_sum is unchanged"


def test_the_view_carries_the_rest_of_the_scope_group_send_all_sends(fake_supabase, monkeypatch):
    """REVIEW FINDING: a project split into scopes (#711) and then given Create Multiple Proposals
    holds proposals outside this estimate's strip, and Send all (main.py _send_all_publish, over
    drafts._group_rows) emails every one. proposals_view names them in `group_others`, oldest first,
    with their own figures; an archived scope is not one (it is not sent). A strip in no group: [].

    Mutation: return [] from drafts._group_others -- Office is never named."""
    import copy as _copy
    from test_multi_proposals import PARENT, _fan, _seed
    data = _copy.deepcopy(PARENT)
    data["scope_group"] = {"id": "G711", "label": "Warehouse"}
    office = {"id": "s2", "owner_email": "kyle@x.test", "created_at": "2026-10-02", "updated_at": "x",
              "deleted_at": None,
              "data": {"project_name": "Acme HQ", "is_test": True, "base_tab_id": "Epoxy",
                       "scope_group": {"id": "G711", "label": "Office"}, "proposal_lump_sum": 5000,
                       "proposal_payload": {"values": {"total_formatted": "$5,100.00"}}}}
    gone = {"id": "s3", "owner_email": "kyle@x.test", "created_at": "2026-10-03", "updated_at": "x",
            "deleted_at": None,
            "data": {"project_name": "Acme HQ", "is_test": True, "archived": True,
                     "scope_group": {"id": "G711", "label": "Old"}, "proposal_lump_sum": 1}}
    _seed(fake_supabase, monkeypatch, data, extra=(office, gone))
    kids = [c["id"] for c in _fan(("Epoxy", "Polish"))["children"]]
    for rid in ("p1", kids[0]):
        v = drafts.proposals_view(rid)
        assert [m["id"] for m in v["members"]] == ["p1", kids[0]]
        assert v["group_others"] == [{"id": "s2", "label": "Office", "lump_sum": 5000,
                                      "document_total": "$5,100.00"}]
    alone = drafts.proposals_view("s2")
    assert [m["id"] for m in alone["members"]] == ["s2"]
    assert [o["id"] for o in alone["group_others"]] == ["p1", kids[0]]
    assert [o["label"] for o in alone["group_others"]] == ["Warehouse", "Polish"], \
        "the names the press says: a scope keeps the name a person gave it"
    assert [o["lump_sum"] for o in alone["group_others"]] == [20000, 9000]


def test_a_strip_in_no_group_has_no_others(fake_supabase, monkeypatch):
    from test_multi_proposals import _seed
    _seed(fake_supabase, monkeypatch)
    assert drafts.proposals_view("p1")["group_others"] == []
