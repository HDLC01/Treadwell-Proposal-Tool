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
    ("the-saved-copys-version", G, "                       { draft_version: row.version, base_ids: ids });",
     "                       { base_ids: ids });",
     lambda f: len(f["v1Direct"]["rows"]) != 3),
    ("existing-kept", G,
     "      return !members.some(function (m) { return m && !m.is_parent && m.base_tab_id === tab; });",
     "      return true;", lambda f: f["exist"]["fanouts"] != 0),
    ("not-on-a-child", G,
     '    if (!st || typeof st !== "object" || (typeof st.proposal_of === "string" && st.proposal_of)) return [];',
     '    if (!st || typeof st !== "object") return [];', lambda f: f["child"]["fanouts"] != 0),
    ("not-off-a-kept-copy", G, "    if (missing.length && NOT_SAVED[seen.status]) {", "    if (false) {",
     lambda f: f["kept"]["fanouts"] != 0),
    ("refusal-said", G, "        alertTop(notMade(fan.error));", '        alertTop("");',
     lambda f: f["refusedTestMix"]["alert"] == "" and f["refusedPortal"]["alert"] == ""),
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
