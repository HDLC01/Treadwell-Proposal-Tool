"""3 · GENERATE FILES makes the missing proposals first, and names every row after its sheet.

Production, 2026-10-30: "Multiple PRoposals test" (a Test project) had Epoxy, Room 2 and Polish ticked
as base bids on the Estimate step and no proposal made from them, because proposals are made by
Create Multiple Proposals on step 4 and step 3 comes first. Step 3 showed ONE row, named after the
project. Hanz chose "Create them, then build all", then: "it should show the 3 sheet names instead of
this one project name only", for v2 too, on Direct and GC projects, and on Test projects on both.

EXECUTED, NOT READ:
  * js/generate-step-harness.js (GEN_FANOUT=1) runs the real generate.js over the real shared.js and
    price-lines-core.js, each frame the real Proposal page, against a stub of the fan-out route: one
    call, with the button's base-bid order and the saved copy's version, then every row built and
    named after its sheet, without leaving the page; v1 and v2, Direct and GC, Test and real; nothing
    when the proposals exist, on one base bid, on a child, or off a copy the server lacks; a refusal
    said once at the top while Base Bid 1 is built. Each scenario has a mutation that turns it red.
  * the real route (TestClient + fake_supabase) takes the very ids step 3 sends (TWPrice.baseIds,
    executed in node over the draft) for a v1 and a v2 estimate, Direct and GC, Test and real, and
    answers the strip the rows are named from; again, it makes nothing twice.
"""
import copy
import json
import pathlib
import shutil
import subprocess

import pytest

import main
from test_generate_step import FRONTEND, HARNESS, _mutant
from test_multi_proposals import PARENT, V, V2, _kids, _no_portal_row, _row, _seed, client

TESTS = pathlib.Path(__file__).resolve().parent
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
AUTO = "Built from the default wording; review it on its Proposal tab before sending."
PROJECT = "Multiple PRoposals test"


def _fan(front=None):
    import os
    args = ["node", str(HARNESS)] + ([str(front)] if front else [])
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=300,
                          env=dict(os.environ, GEN_FANOUT="1"))
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran_fan():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _fan()


@pytest.fixture(scope="module")
def fan(ran_fan):
    return ran_fan["fan"]


SHEETS = {"v1": (["Epoxy", "Copy1", "Polish"], ["Epoxy", "Room 2", "Polish"], ["$10,000", "$6,000", "$8,000"]),
          "v2": (["Polish", "Epoxy", "Copy1"], ["Breakroom", "Lab 1", "Lab 2"], ["$8,000", "$10,000", "$6,000"])}
CASES = [("v1Direct", "v1", "Direct", True), ("v1GC", "v1", "GC", True),
         ("v2Direct", "v2", "Direct", True), ("v2GC", "v2", "GC", True), ("v1Real", "v1", "Direct", False)]


# ── step 3 makes them, then builds all ───────────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("key, kind, audience, is_test", CASES, ids=[c[0] for c in CASES])
def test_three_base_bids_and_no_proposals_make_two_then_build_three(fan, key, kind, audience, is_test):
    """ONE fan-out, with the base bids in the button's order (Base Bid 1 first, then the sheets' order;
    the draft stores them scrambled) and the version of the saved copy; then all three built, each
    row named after its sheet, Base Bid 1's included, and the project's name said once above."""
    f = fan[key]
    order, names, totals = SHEETS[kind]
    assert f["fanouts"] == [{"id": "d1", "base_ids": order, "versioned": True}]
    assert [(r[0], r[1], r[2], r[3]) for r in f["rows"]] == [
        ("d1", names[0], "built", totals[0]), ("c2", names[1], "built", totals[1]),
        ("c3", names[2], "built", totals[2])], f["rows"]
    assert f["project"] == PROJECT
    assert f["note"] == "Made 2 more proposals from the base bids on the estimate. All 3 proposals are built."
    assert "Generating files: making a proposal for each base bid on the estimate…" in f["notes"]
    assert f["alert"] == "" and f["frameErrors"] == []
    # Each new proposal is the server's: its own base, the project's audience and kind, empty words.
    assert [(k["id"], k["base"], k["audience"], k["test"], k["scope"]) for k in f["kidData"]] == [
        ("c2", order[1], audience, is_test, ""), ("c3", order[2], audience, is_test, "")]


@needs_node
@pytest.mark.parametrize("key", [c[0] for c in CASES])
def test_the_new_proposals_are_marked_backups_send_all_still_holds(fan, key):
    """They start with empty wording, exactly as after the button: step 3 composes each from the
    template's defaults as a backup, marked `proposal_auto_built` and built without the placeholder
    hold, and its row says to review it, so Send all holds it while it prints placeholders."""
    f = fan[key]
    assert [k["auto"] for k in f["kidData"]] == [True, True]
    assert f["holds"] == {"d1": True, "c2": False, "c3": False}
    assert [r[4] for r in f["rows"]] == ["", AUTO, AUTO]


@needs_node
@pytest.mark.parametrize("key", [c[0] for c in CASES])
def test_it_never_leaves_the_page_and_never_loops(fan, key):
    """No reload and no navigation: the server's copy is taken in place of this browser's (its
    scope group is the fan-out's) and the page goes on. Rebuild all asks nothing again."""
    f = fan[key]
    assert f["nav"] == [] and f["urls"] == ["/generate.html?d=d1"] and f["url"] == "/generate.html?d=d1"
    assert f["slotOwner"] == "d1" and f["slotGroup"] == f["serverGroup"] == SHEETS[key[:2]][1][0]
    assert all(g == f["serverGroup"] for g in f["d1PutsGroup"]), "a save put the copy from before back"
    assert f["next"] == "/proposal-review.html?d=d1" and f["nextDisabled"] is False
    a = f["again"]
    assert a["fanouts"] == 1 and a["fanOutCalls"] == 1 and a["nav"] == []   # the page's one, from its first visit
    assert [r[2] for r in a["rows"]] == ["built"] * 3 and a["note"] == "All 3 proposals are built."


@needs_node
def test_nothing_extra_when_the_proposals_exist(fan):
    e = fan["exist"]
    assert e["fanouts"] == 0 and e["alert"] == "" and e["nav"] == []
    assert e["rows"] == [["d1", "Epoxy", "built"], ["c2", "Room 2", "built"], ["c3", "Polish", "built"]]
    assert e["note"] == "All 3 proposals are built."


@needs_node
def test_only_the_missing_one_is_made_and_the_existing_one_kept(fan):
    p = fan["partial"]
    assert p["fanouts"] == [["Epoxy", "Copy1", "Polish"]]
    assert p["rows"] == [["d1", "Epoxy", "built"], ["c2", "Room 2", "built"], ["c3", "Polish", "built"]]
    assert p["note"] == "Made 1 more proposal from the base bids on the estimate. All 3 proposals are built."


TRASH_SAID = ("Room 2's proposal is in the Trash, so it was not made again. Restore it from the Trash, "
              "or untick it as a base bid.")


@needs_node
def test_a_proposal_in_the_trash_is_not_made_again(fan):
    """Room 2's proposal was deleted. The fan-out still names every base bid (the estimate keeps its
    ticks) and asks the server to leave Room 2 out; Polish's is made. The top says so in one line,
    and Rebuild all asks nothing again (the only one missing is in the Trash)."""
    t = fan["trashed"]
    assert t["asked"] == [{"base_ids": ["Epoxy", "Copy1", "Polish"], "leave_out": ["Copy1"]}]
    assert t["kids"] == ["Polish"]
    assert t["rows"] == [["d1", "Epoxy", "built"], ["c2", "Polish", "built"]]
    assert t["alert"] == TRASH_SAID and t["alerts"] == [TRASH_SAID]
    assert t["note"] == "Made 1 more proposal from the base bids on the estimate. All 2 proposals are built."
    assert t["nav"] == [] and t["nextDisabled"] is False
    assert t["again"] == {"fanouts": 1, "alert": TRASH_SAID, "nav": [], "rows": [["d1", "built"], ["c2", "built"]]}


@needs_node
def test_an_archived_proposal_is_not_made_again_and_is_called_archived(fan):
    a = fan["archived"]
    assert a["asked"] == [["Polish"]] and a["kids"] == ["Copy1"]
    assert a["alert"] == ("Polish's proposal is archived, so it was not made again. Unarchive it on the "
                          "board, or untick it as a base bid.")


MOVED_ON = "so no new proposals were made here. Press Create Multiple Proposals on the Proposal step if you want them."


@needs_node
@pytest.mark.parametrize("key, said, asked", [
    ("won", "This project is won, ", []), ("lost", "This project is closed as lost, ", []),
    ("hold", "This project is on hold, ", []), ("sent", "This project was already sent, ", [True])])
def test_a_project_that_moved_on_or_was_sent_gets_no_proposals_on_its_own(fan, key, said, asked):
    """Won, lost or on hold: step 3 does not ask. Sent: it asks as `auto`, and the server says no.
    Either way nothing is made, the top says so once, Base Bid 1 is built, Continue as always."""
    m = fan["movedOn_" + key]
    assert m["fanouts"] == asked and m["kids"] == 0
    assert m["alert"] == said + MOVED_ON and m["alerts"] == [said + MOVED_ON]
    assert m["rows"] == [["d1", "Epoxy", "built"]] and m["nav"] == [] and m["nextDisabled"] is False


@needs_node
def test_a_save_that_failed_says_so(fan):
    a = fan["aheadFailed"]
    assert a["fanouts"] == 0 and a["nav"] == []
    assert a["alert"] == ("No proposals were made for the other base bids: this browser's changes could not "
                          "be saved. Check your connection, then reload this page.")


@needs_node
def test_a_copy_saved_since_is_said_in_one_sentence(fan):
    c = fan["changedSince"]
    assert c["alert"] == ("No proposals were made for the other base bids: this project was saved again after "
                          "this page read it, from another page or computer. Reload this page and they will be made.")
    assert "Nothing changed" not in c["alert"] and c["rows"] == [["d1", "built"]]


@needs_node
def test_one_base_bid_makes_nothing_and_keeps_the_project_name(fan):
    o = fan["oneBase"]
    assert o["fanouts"] == 0 and o["alert"] == "" and o["nav"] == []
    assert o["rows"] == [["d1", PROJECT, "built"]] and o["project"] == ""
    assert o["note"] == "The files are built."


@needs_node
def test_a_child_makes_nothing(fan):
    c = fan["child"]
    assert c["fanouts"] == 0 and c["alert"] == "" and c["nav"] == []
    assert [r[1] for r in c["rows"]] == ["Epoxy", "Room 2"]


@needs_node
def test_a_copy_the_server_lacks_makes_nothing_and_says_why(fan):
    k = fan["kept"]
    assert k["fanouts"] == 0 and k["nav"] == []
    assert k["alert"].startswith("No proposals were made for the other base bids: this browser's copy")


@needs_node
@pytest.mark.parametrize("key, said", [
    ("refusedTestMix", "No proposals were made for the other base bids. Acme HQ is a test project and Lab "
                       "is not: a project's scopes are all test or all real."),
    ("refusedPortal", "No proposals were made. The customer portal is not answering, so the tool cannot "
                      "tell whether this proposal was already sent. Try again in a minute.")])
def test_a_refusal_is_said_once_and_base_bid_1_is_still_built(fan, key, said):
    """The server's sentence once, at the top; Base Bid 1 built and named after its sheet; Continue
    as always; no navigation. Rebuild all asks once more, and says it once more."""
    r = fan[key]
    assert r["alert"] == said and r["alerts"] == [said]
    assert r["rows"] == [["d1", "Epoxy", "built", "$10,000"]]
    assert r["project"] == PROJECT and r["note"] == "The files are built."
    assert r["nav"] == [] and r["next"] == "/proposal-review.html?d=d1" and r["nextDisabled"] is False
    assert r["again"] == {"fanouts": 2, "nav": [], "alerts": 2, "rows": [["d1", "built"]]}


@needs_node
def test_no_row_offers_a_download_here_either(ran_fan):
    """Every list these scenarios drew (made, refused, one base bid, a child) holds no download
    control (test_generate_step.py proves the check sees one put back)."""
    from test_generate_step import _download_controls
    assert len(ran_fan["lists"]) >= 15
    assert _download_controls(ran_fan["lists"]) == []


def test_the_page_loads_the_base_bid_order_before_its_script():
    html = (FRONTEND / "generate.html").read_text(encoding="utf-8")
    assert html.index("/shared.js") < html.index("/js/price-lines-core.js") < html.index("/js/generate.js")
    assert '<p id="gen-alert"' in html and '<p id="gen-project"' in html


# ── mutations: each scenario above goes red without the line it relies on ───────────────────
G = "js/generate.js"
MUTATIONS = [
    ("fans-out", G, "    } else if (missing.length) {", "    } else if (false) {",
     lambda f: len(f["v1Direct"]["rows"]) != 3 or f["v1Direct"]["fanouts"] != []),
    ("the-buttons-order", G, "    var ids = TWPrice.baseIds(TW.v2PricingView ? TW.v2PricingView(st) : st);",
     "    var ids = [st.base_tab_id].concat(st.base_tab_ids.filter(function (x) { return x !== st.base_tab_id; }));",
     lambda f: f["v1Direct"]["fanouts"][0]["base_ids"] != ["Epoxy", "Copy1", "Polish"]
     or f["v2Direct"]["fanouts"][0]["base_ids"] != ["Polish", "Epoxy", "Copy1"]),
    ("the-saved-copys-version", G,
     "                       { draft_version: row.version, base_ids: ids, leave_out: leaveOut || [], auto: true });",
     "                       { base_ids: ids, leave_out: leaveOut || [], auto: true });",
     lambda f: len(f["v1Direct"]["rows"]) != 3),
    ("existing-kept", G,
     "      return !members.some(function (m) { return m && !m.is_parent && m.base_tab_id === tab; });",
     "      return true;", lambda f: f["exist"]["fanouts"] != 0),
    ("not-on-a-child", G,
     '    if (!st || typeof st !== "object" || (typeof st.proposal_of === "string" && st.proposal_of)) return [];',
     '    if (!st || typeof st !== "object") return [];', lambda f: f["child"]["fanouts"] != 0),
    ("not-off-a-kept-copy", G, "    } else if (missing.length && NOT_SAVED[seen.status]) {", "    } else if (false) {",
     lambda f: f["kept"]["fanouts"] != 0),
    ("trashed-not-made-again", G,
     "    var leaveOut = missing.filter(function (tab) { return Object.prototype.hasOwnProperty.call(binned, tab); });",
     "    var leaveOut = [];",
     lambda f: "Copy1" in f["trashed"]["kids"] or f["trashed"]["alert"] == ""),
    ("refusal-said", G, "        tops.push(notMade(fan));", "",
     lambda f: f["refusedTestMix"]["alert"] == "" and f["refusedPortal"]["alert"] == ""),
    ("not-on-its-own-when-moved-on", G, "    var moved = movedOn(st);", '    var moved = "";',
     lambda f: f["movedOn_won"]["fanouts"] != [] or f["movedOn_lost"]["kids"] != 0),
    ("says-it-is-step-3s-own-call", G,
     "                       { draft_version: row.version, base_ids: ids, leave_out: leaveOut || [], auto: true });",
     "                       { draft_version: row.version, base_ids: ids, leave_out: leaveOut || [] });",
     lambda f: f["movedOn_sent"]["kids"] != 0),
    ("ahead-says-the-save-failed", G, '    } else if (missing.length && seen.status === "ahead") {',
     "    } else if (false) {",
     lambda f: "could not be saved" not in f["aheadFailed"]["alert"]),
    ("changed-since-said-once", G, '    if (code === "document_changed") {', "    if (false) {",
     lambda f: not f["changedSince"]["alert"].endswith("Reload this page and they will be made.")),
    ("archived-said-as-archived", G,
     '        out[t.base_tab_id] = { name: t.sheet_label || t.base_tab_id, where: t.where === "archived" ? "archived" : "trash" };',
     '        out[t.base_tab_id] = { name: t.sheet_label || t.base_tab_id, where: "trash" };',
     lambda f: "archived" not in f["archived"]["alert"]),
    ("no-reload", G, "    if (TW.useServerCopy) await TW.useServerCopy();",
     "    if (TW.useServerCopy && await TW.useServerCopy()) window.location.reload();",
     lambda f: f["v1Direct"]["nav"] != []),
    ("says-what-it-made", G, '    say((made ? made + " " : "") + summary());', "    say(summary());",
     lambda f: not f["v1Direct"]["note"].startswith("Made 2 more proposals")),
    ("rows-by-sheet", G, "      if (bySheet) {", "      if (false) {",
     lambda f: f["refusedTestMix"]["rows"][0][1] != "Epoxy"),
    ("one-base-keeps-its-title", G, "    bySheet = bases.length >= 2 || members.length > 1;",
     "    bySheet = true;", lambda f: f["oneBase"]["rows"][0][1] != PROJECT),
    ("project-said-once-above", G,
     '    bySheet = bases.length >= 2 || members.length > 1;\n    heading(bySheet ? st.project_name : "");',
     '    bySheet = bases.length >= 2 || members.length > 1;\n    heading("");',
     lambda f: f["v1Direct"]["project"] != PROJECT),
]


@needs_node
@pytest.mark.parametrize("name, rel, old, new, red", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_fan_out_scenario_goes_red_without_its_line(tmp_path, name, rel, old, new, red):
    assert red(_fan(_mutant(tmp_path, rel, old, new))["fan"]), "%s: the scenario did not notice" % name


# ── the route takes exactly what step 3 sends ─────────────────────────────────────────────────
def _step3_ids(blob):
    """The base_ids step 3 sends for `blob`: generate.js baseBidsOf is TWPrice.baseIds over
    TW.v2PricingView of the draft. Every fixture below is a v1 draft or a v2 one whose priced_tabs are
    all its own (`v2: true`), which v2PricingView hands back as it is; price-lines-core.js runs here."""
    core = FRONTEND / "js" / "price-lines-core.js"
    js = ("const P = require(%s); let s = ''; process.stdin.on('data', (c) => s += c);"
          "process.stdin.on('end', () => process.stdout.write(JSON.stringify(P.baseIds(JSON.parse(s)))));"
          % json.dumps(str(core)))
    proc = subprocess.run(["node", "-e", js], input=json.dumps(blob), capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


ROUTE = [("v1", "Direct", True), ("v1", "GC", True), ("v2", "Direct", True), ("v2", "GC", True),
         ("v1", "GC", False), ("v2", "Direct", False)]


@needs_node
@pytest.mark.parametrize("kind, audience, is_test", ROUTE,
                         ids=["%s-%s-%s" % (k, a, "test" if t else "real") for k, a, t in ROUTE])
def test_the_route_makes_every_missing_proposal_from_what_step_3_sends(fake_supabase, monkeypatch,
                                                                       kind, audience, is_test):
    if kind == "v1":
        data = dict(copy.deepcopy(PARENT), base_tab_ids=["Polish", "Copy1", "Epoxy"])
        want_ids, names = ["Epoxy", "Copy1", "Polish"], ["Epoxy", "Room 2", "Polish"]
    else:
        data = dict(copy.deepcopy(V2), base_tab_ids=["Copy1", "Polish", "Epoxy"])
        assert all(t.get("v2") is True for t in data["priced_tabs"])
        want_ids, names = ["Polish", "Epoxy", "Copy1"], ["Breakroom", "Lab 1", "Lab 2"]
    data.update(audience=audience, is_test=is_test)
    ids = _step3_ids(data)
    assert ids == want_ids
    store = _seed(fake_supabase, monkeypatch, data)
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    # Before: the strip is Base Bid 1 alone, unnamed, its sheet said (step 3 names its row by it).
    g = client.get("/api/draft/p1/proposals").json()
    assert [(m["display_label"], m["sheet_label"]) for m in g["members"]] == [("", names[0])]
    r = client.post("/api/draft/p1/proposals", json={"draft_version": V, "base_ids": ids})
    assert r.status_code == 200, r.text
    j = r.json()
    assert [m["display_label"] for m in j["proposals"]["members"]] == names
    assert [m["base_tab_id"] for m in j["proposals"]["members"]] == ids
    assert [c["created"] for c in j["children"]] == [True, True]
    kids = _kids(store)
    assert sorted(k["data"]["base_tab_id"] for k in kids) == sorted(ids[1:])
    for k in kids:
        assert k["data"]["audience"] == audience and k["data"]["is_test"] is is_test
    # AGAIN (Rebuild all, or the next visit): nothing is made twice.
    r = client.post("/api/draft/p1/proposals", json={"draft_version": _row(store, "p1")["updated_at"],
                                                     "base_ids": ids})
    assert r.status_code == 200 and [c["created"] for c in r.json()["children"]] == [False, False]
    assert len(_kids(store)) == 2


def test_the_route_refuses_flat_so_step_3_can_say_it(fake_supabase, monkeypatch):
    """The Test rule stays the server's: a Test project in a real project's group is refused, flat,
    with the sentence step 3 shows at its top."""
    data = dict(copy.deepcopy(PARENT), scope_group={"id": "grp_a", "label": "Breakroom"},
                base_tab_ids=["Epoxy", "Copy1"])
    real = {"id": "s9", "data": {"project_name": "Acme HQ", "is_test": False,
                                 "scope_group": {"id": "grp_a", "label": "Lab"}},
            "owner_email": "k", "created_at": "2026-10-02", "updated_at": V, "deleted_at": None}
    store = _seed(fake_supabase, monkeypatch, data, extra=[real])
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    r = client.post("/api/draft/p1/proposals", json={"draft_version": V, "base_ids": ["Epoxy", "Copy1"]})
    assert r.status_code == 409
    j = r.json()
    assert j["ok"] is False and j["code"] == "test_mix" and isinstance(j["error"], str) and j["error"]
    assert _kids(store) == []


# ── a proposal in the Trash is not made again (Hanz, 2026-10-30) ──────────────────────────────
def _binned(rid, parent, tab, **data):
    """A proposal of `parent` on sheet `tab`, sent to the Trash (deleted_at set)."""
    return {"id": rid, "data": dict({"project_name": "Acme HQ", "is_test": True, "proposal_of": parent,
                                     "base_tab_id": tab, "scope_group": {"id": "grp_x", "label": "Room 2"}},
                                    **data),
            "owner_email": "k", "created_at": "2026-10-02", "updated_at": V,
            "deleted_at": "2026-10-29T12:00:00+00:00"}


def test_the_strip_names_a_base_bid_whose_proposal_is_in_the_trash(fake_supabase, monkeypatch):
    """`trashed`: Room 2's proposal is in the Trash and no live one prices Room 2. A trashed proposal
    of ANOTHER project, one on a sheet that is no base bid, and a sheet a live proposal prices are
    not listed."""
    data = dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy", "Copy1", "Polish"])
    store = _seed(fake_supabase, monkeypatch, data,
                  extra=[_binned("t1", "p1", "Copy1"), _binned("t2", "other", "Polish"),
                         _binned("t3", "p1", "Seal")])
    g = client.get("/api/draft/p1/proposals").json()
    assert g["trashed"] == [{"id": "t1", "base_tab_id": "Copy1", "where": "trash", "sheet_label": "Room 2"}]
    # Once a live proposal prices Polish and Room 2, nothing is listed.
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    assert client.post("/api/draft/p1/proposals", json={"draft_version": V, "base_ids": ["Epoxy", "Copy1", "Polish"]}).status_code == 200
    assert client.get("/api/draft/p1/proposals").json()["trashed"] == []
    # One base bid: the Trash is not even read.
    store2 = _seed(fake_supabase, monkeypatch, dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy"]),
                   extra=[_binned("t1", "p1", "Copy1")])
    assert client.get("/api/draft/p1/proposals").json()["trashed"] == []
    assert store and store2


def test_leave_out_keeps_the_tick_and_makes_nothing_for_it(fake_supabase, monkeypatch):
    """What step 3 sends for Room 2 in the Trash: every base bid, Room 2 left out. Polish's proposal
    is made, Room 2's is not, and the parent still records all three ticks. Without `leave_out` the
    same press makes Room 2's again (the button's behaviour, unchanged)."""
    for leave in (["Copy1"], []):
        data = dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy", "Copy1", "Polish"])
        store = _seed(fake_supabase, monkeypatch, data, extra=[_binned("t1", "p1", "Copy1")])
        monkeypatch.setattr(main, "_portal", _no_portal_row)
        r = client.post("/api/draft/p1/proposals", json={"draft_version": V, "leave_out": leave,
                                                         "base_ids": ["Epoxy", "Copy1", "Polish"]})
        assert r.status_code == 200, r.text
        j = r.json()
        live = sorted(k["data"]["base_tab_id"] for k in _kids(store) if not k.get("deleted_at"))
        if leave:
            assert live == ["Polish"] and j["left_out"] == ["Copy1"]
            assert [c["base_tab_id"] for c in j["children"]] == ["Polish"]
            assert [m["display_label"] for m in j["proposals"]["members"]] == ["Epoxy", "Polish"]
            assert j["proposals"]["trashed"] == [{"id": "t1", "base_tab_id": "Copy1", "where": "trash",
                                                  "sheet_label": "Room 2"}]
        else:
            assert live == ["Copy1", "Polish"] and j["left_out"] == []
        assert _row(store, "p1")["data"]["base_tab_ids"] == ["Epoxy", "Copy1", "Polish"], "a tick was lost"
    # Base Bid 1 is never left out.
    store = _seed(fake_supabase, monkeypatch, dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy", "Copy1"]))
    r = client.post("/api/draft/p1/proposals", json={"draft_version": V, "leave_out": ["Epoxy"],
                                                     "base_ids": ["Epoxy", "Copy1"]})
    assert r.status_code == 200 and r.json()["left_out"] == [] and len(_kids(store)) == 1


# ── step 3's own call: nothing for a project that moved on or was sent (review of 99c5cff0) ──
@pytest.mark.parametrize("mark, code", [({"won": {"at": "x"}}, "closed"),
                                        ({"closed_lost": {"reason": "price"}}, "closed"),
                                        ({"on_hold": {"reason": "budget"}}, "closed"),
                                        ({"handed_off": {"at": "x"}}, "closed"),
                                        (None, "already_sent")])
def test_an_auto_fan_out_of_a_project_that_moved_on_makes_nothing(fake_supabase, monkeypatch, mark, code):
    """`auto` (step 3): 409, flat, the sentence step 3 shows, and nothing written. The same press
    without `auto` (the button) goes through as before."""
    for auto in (True, False):
        data = dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy", "Copy1"], **(mark or {}))
        store = _seed(fake_supabase, monkeypatch, data)
        if mark is None:
            store["draft_revisions"].append({"project_id": "p1", "revision_no": 1})
        monkeypatch.setattr(main, "_portal", _no_portal_row)
        before = copy.deepcopy(_row(store, "p1")["data"])
        r = client.post("/api/draft/p1/proposals", json={"draft_version": V, "auto": auto,
                                                         "base_ids": ["Epoxy", "Copy1"]})
        if auto:
            assert r.status_code == 409, r.text
            j = r.json()
            assert j["ok"] is False and j["code"] == code
            assert j["error"].endswith(" so no new proposals were made here. Press Create Multiple "
                                       "Proposals on the Proposal step if you want them.")
            assert _kids(store) == [] and _row(store, "p1")["data"] == before
        else:
            assert r.status_code == 200, r.text
            assert len(_kids(store)) == 1


# ── two fan-outs of one parent at once make one group (review of 99c5cff0) ────────────────────
def _race(fake_supabase, monkeypatch, locked):
    """Two presses of one parent at once. Each, once it has read the parent, waits (up to 1 s) for
    the other to have read it too: without the lock both read it before either writes."""
    import threading
    import contextlib
    import drafts
    store = _seed(fake_supabase, monkeypatch, dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy", "Copy1", "Polish"]))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    if not locked:
        monkeypatch.setattr(drafts, "_fan_lock", lambda pid: contextlib.nullcontext())
    real_copy = drafts._proposal_copy
    arrived = []
    both = threading.Event()

    def slow_copy(*a, **k):
        if threading.current_thread().name not in arrived:
            arrived.append(threading.current_thread().name)
            if len(arrived) >= 2:
                both.set()
            both.wait(1.0)
        return real_copy(*a, **k)
    monkeypatch.setattr(drafts, "_proposal_copy", slow_copy)
    out = []

    def press():
        out.append(client.post("/api/draft/p1/proposals", json={
            "draft_version": V, "auto": True, "base_ids": ["Epoxy", "Copy1", "Polish"]}))
    ts = [threading.Thread(target=press, name="press-%d" % i) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    return store, out


def test_two_fan_outs_at_once_make_one_group_and_no_duplicate(fake_supabase, monkeypatch):
    store, out = _race(fake_supabase, monkeypatch, locked=True)
    assert [r.status_code for r in out] == [200, 200], [r.text for r in out]
    kids = _kids(store)
    assert sorted(k["data"]["base_tab_id"] for k in kids) == ["Copy1", "Polish"], "a duplicate proposal"
    assert len({k["data"]["scope_group"]["id"] for k in kids}) == 1
    assert {r.json()["group_id"] for r in out} == {_row(store, "p1")["data"]["scope_group"]["id"]}
    assert sorted(c["created"] for r in out for c in r.json()["children"]) == [False, False, True, True]


def test_the_race_is_real_without_the_lock(fake_supabase, monkeypatch):
    """The control: the same two presses with the lock taken away make two groups and duplicate
    proposals, so the test above proves the lock and not the timing."""
    store, out = _race(fake_supabase, monkeypatch, locked=False)
    kids = _kids(store)
    assert len(kids) == 4 and len({k["data"]["scope_group"]["id"] for k in kids}) == 2


# ── an archived proposal is not made again either ─────────────────────────────────────────────
def test_the_strip_names_a_base_bid_whose_proposal_is_archived(fake_supabase, monkeypatch):
    """Room 2's proposal is archived on the board (not deleted): `trashed` lists it as archived, and
    one in the Trash as trash."""
    data = dict(copy.deepcopy(PARENT), base_tab_ids=["Epoxy", "Copy1", "Polish"],
                scope_group={"id": "grp_x", "label": "Epoxy"})
    arch = {"id": "a1", "data": {"project_name": "Acme HQ", "is_test": True, "proposal_of": "p1",
                                 "base_tab_id": "Copy1", "archived": True,
                                 "scope_group": {"id": "grp_x", "label": "Room 2"}},
            "owner_email": "k", "created_at": "2026-10-02", "updated_at": V, "deleted_at": None}
    _seed(fake_supabase, monkeypatch, data, extra=[arch, _binned("t1", "p1", "Polish")])
    g = client.get("/api/draft/p1/proposals").json()
    assert [m["id"] for m in g["members"]] == ["p1"], "an archived proposal is in the strip"
    assert g["trashed"] == [{"id": "a1", "base_tab_id": "Copy1", "where": "archived", "sheet_label": "Room 2"},
                            {"id": "t1", "base_tab_id": "Polish", "where": "trash", "sheet_label": "Polish"}]
