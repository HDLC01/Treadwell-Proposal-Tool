"""Two project boards: Direct Projects and General Contractor.

Hanz, 2026-09-29: "we actually have two pipelines now. We will need to separate pipelines for
Direct and General Contractors. We relabel Active projects to Direct Projects and we add a new
pipeline named 'General Contractor' as a new sidebar. This is where General Contractor projects
will live; it will have the same steps but just on a different webpage."

WHAT HAS TO HOLD, and the section below that proves it:

  A. ONE RULE, TWO LANGUAGES. A project is GC when its audience is "GC", trimmed and
     case-insensitive; everything else, a missing audience included, is Direct.
     backend/pipelines.py and frontend/js/crm-core.js each carry it, and both run over ONE
     fixture list here.
  B. EVERY CARD CARRIES ITS AUDIENCE. A sent project's portal row has no such column; the choice
     lives on our draft, so the pipeline endpoint has to stamp it, or every sent GC job sits on
     the Direct board. The fast summary projection has to NAME it, or it reaches no card at all.
  C. THE GC PAGE IS portal.html, served at a second address with four strings swapped.
  D. EACH BOARD SHOWS ONLY ITS OWN, on every tab, with every count its own — executed through the
     real portal.js load() and paint, not read as source.
  E. + New on the GC board opens the intake form on GC; on Direct it stays Direct.
  F. A LINK TO THE WRONG BOARD LANDS ON THE RIGHT ONE, query kept, so the drawer still opens.
  G. PERMISSIONS: the new page's default is exactly what everybody has for /portal.html.
  H. THE RELABEL: no user-facing "Active Projects" is left.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import drafts
import main
import nav_access
import pipelines

client = TestClient(main.app)

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "gc-pipeline-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

GC_PAGE = pipelines.BOARD_PAGE[pipelines.GC]
MISSING = {"$missing": True}      # the harness hands this to pipelineOf as `undefined`


# ── A. the rule ──────────────────────────────────────────────────────────────
# (value, board). One list for both languages. MISSING is the key being absent from the card,
# which Python reads as None through dict.get and JavaScript as undefined.
RULE = [
    ("GC", "gc"), ("gc", "gc"), (" GC ", "gc"), ("Gc", "gc"), (" \tGC\n", "gc"), ("\fgC\v", "gc"),
    ("Direct", "direct"), (MISSING, "direct"), (None, "direct"), ("", "direct"), ("   ", "direct"),
    ("other", "direct"), ("Owner", "direct"), ("General Contractor", "direct"), ("G C", "direct"),
    ("gcc", "direct"), ("xgc", "direct"),
    # Exotic whitespace: NOT trimmed by either side, on purpose — see pipelines.py.
    ("﻿GC", "direct"), (" GC", "direct"),
    # Not a string: Direct in both, never coerced. String(["GC"]) is "GC" in JavaScript.
    (["GC"], "direct"), (1, "direct"), (True, "direct"), ({"audience": "GC"}, "direct"),
]


def _py(value):
    return pipelines.pipeline_of(None if value is MISSING else value)


def test_the_python_rule():
    for value, board in RULE:
        assert _py(value) == board, "pipeline_of(%r) should be %r" % (value, board)


@needs_node
def test_the_javascript_rule_agrees_on_every_fixture(harness):
    got = harness["rule"]
    assert len(got) == len(RULE)
    for (value, board), js in zip(RULE, got):
        assert js == board, "pipelineOf(%r) is %r, expected %r" % (value, js, board)
        assert js == _py(value), "the two languages disagree about %r" % (value,)


# ── the board fixture: every tab on both boards has something on it ─────────
def _draft(did, audience="__unset__", **kw):
    """A drafts-list summary shaped the way _build_summaries returns one."""
    s = {"id": did, "project_name": "Project " + did, "has_files": True, "archived": False,
         "is_test": None, "owner_email": "kyle@wetreadwell.com", "assigned_estimator": None,
         "contact_email": "c@example.com", "total": 1000, "work_type": "epoxy",
         "updated_at": "2026-09-20T10:00:00+00:00", "sent_revision": 0}
    if audience != "__unset__":
        s["audience"] = audience
    s.update(kw)
    return s


def _row(pid, status="sent", **kw):
    r = {"proposal_id": pid, "project_name": "Project " + pid, "proposal_status": status,
         "sent_at": "2026-09-10T10:00:00+00:00", "customer_email": pid + "@example.com",
         "assigned_estimator": "kyle@wetreadwell.com"}
    r.update(kw)
    return r


PORTAL_ROWS = [
    _row("s-gc-1"),
    _row("s-gc-2", "viewed", last_viewed_at="2026-09-12T10:00:00+00:00"),
    _row("s-gc-lost", "closed_lost", followup_state={"closed_lost_reason": "price"}),
    _row("s-gc-test"),
    _row("s-gc-hand", "approved", approved_at="2026-09-11T10:00:00+00:00"),
    _row("s-dir-1"),
    _row("s-dir-2", "approved", approved_at="2026-09-11T10:00:00+00:00", deposit_status="pending",
         deposit_required=True),
    _row("s-dir-lost", "closed_lost", followup_state={"closed_lost_reason": "price"}),
    _row("s-dir-test"),
    _row("s-orphan"),            # a portal row whose draft the list has never heard of
]
DRAFTS = [
    _draft("s-gc-1", "GC"), _draft("s-gc-2", "gc"), _draft("s-gc-lost", " GC "),
    _draft("s-gc-test", "GC", is_test=True),
    _draft("s-gc-hand", "GC", handed_off_at="2026-09-15T10:00:00+00:00"),
    _draft("s-dir-1", "Direct"), _draft("s-dir-2", None), _draft("s-dir-lost", "Direct"),
    _draft("s-dir-test", "Direct", is_test=True),
    _draft("u-gc-1", " GC "), _draft("u-gc-lost", "GC", closed_lost_reason="price"),
    _draft("u-dir-1", "Direct"), _draft("u-dir-2"), _draft("u-other", "Owner"),
    _draft("u-dir-hand", "Direct", handed_off_at="2026-09-16T10:00:00+00:00"),
]
# What each board must hold, tab by tab. Typed out rather than derived: deriving it with the
# predicates under test would prove the predicates agree with themselves.
EXPECT = {
    "gc": {"active": {"s-gc-1", "s-gc-2", "u-gc-1"}, "handed_off": {"s-gc-hand"},
           "lost": {"s-gc-lost", "u-gc-lost"}, "test": {"s-gc-test"}},
    "direct": {"active": {"s-dir-1", "s-dir-2", "s-orphan", "u-dir-1", "u-dir-2", "u-other"},
               "handed_off": {"u-dir-hand"}, "lost": {"s-dir-lost"}, "test": {"s-dir-test"}},
}


def _wire(monkeypatch, rows=None, summaries=None):
    rows = [dict(r) for r in (PORTAL_ROWS if rows is None else rows)]
    summaries = [dict(s) for s in (DRAFTS if summaries is None else summaries)]
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": rows})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: summaries)


def _payload():
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return r.json()


def _by_id(payload):
    return {p["proposal_id"]: p for p in payload["proposals"]}


# ── B. every card carries its audience ───────────────────────────────────────
def test_a_sent_project_gets_its_drafts_audience(monkeypatch):
    """The half that carries most of the traffic: nearly every live job was sent, and the portal row
    has no audience column. Without the stamp every sent GC job would sit on the Direct board."""
    _wire(monkeypatch)
    out = _by_id(_payload())
    assert out["s-gc-1"]["audience"] == "GC"
    assert out["s-gc-2"]["audience"] == "gc"
    assert out["s-gc-lost"]["audience"] == " GC "
    assert out["s-dir-1"]["audience"] == "Direct"
    # A draft that never chose: stamped with its own None, which is Direct.
    assert "audience" in out["s-dir-2"] and out["s-dir-2"]["audience"] is None


def test_a_portal_row_with_no_draft_is_left_without_one(monkeypatch):
    """Absent, not invented — and read as Direct, where it has always been."""
    _wire(monkeypatch)
    out = _by_id(_payload())
    assert "audience" not in out["s-orphan"]
    assert out["s-orphan"]["pipeline"] == "direct"


def test_an_unsent_project_carries_its_audience(monkeypatch):
    _wire(monkeypatch)
    out = _by_id(_payload())
    assert out["u-gc-1"]["not_sent"] is True and out["u-gc-1"]["audience"] == " GC "
    assert out["u-other"]["audience"] == "Owner"
    assert out["u-dir-2"]["audience"] is None


def test_every_card_is_stamped_with_the_server_rule(monkeypatch):
    _wire(monkeypatch)
    rows = _payload()["proposals"]
    assert {r["proposal_id"] for r in rows} == {r["proposal_id"] for r in PORTAL_ROWS} | {
        d["id"] for d in DRAFTS}
    for r in rows:
        assert r["pipeline"] == pipelines.pipeline_of(r.get("audience")), r


def test_changing_the_choice_moves_the_project_and_nothing_else(monkeypatch):
    """Hanz's board reads the estimator's live answer, so flipping the Audience radio is the whole
    act of moving a project. The portal hands back the SAME row objects each time here, which is
    what a warm cache does in production, so a stamp that only ever added and never overwrote would
    leave the project on the board it just left."""
    rows = [_row("p1"), _row("p2")]
    summaries = [_draft("p1", "Direct"), _draft("p2", "GC")]
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": rows})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: summaries)
    before = _by_id(_payload())
    assert (before["p1"]["pipeline"], before["p2"]["pipeline"]) == ("direct", "gc")
    summaries[0]["audience"], summaries[1]["audience"] = "GC", "Direct"
    after = _by_id(_payload())
    assert (after["p1"]["pipeline"], after["p2"]["pipeline"]) == ("gc", "direct")
    for pid in ("p1", "p2"):
        changed = {k for k in set(before[pid]) | set(after[pid]) if before[pid].get(k) != after[pid].get(k)}
        assert changed == {"audience", "pipeline"}, (pid, changed)


def test_the_outage_rows_carry_it_too(monkeypatch):
    """Cold cache, portal down: the board is rebuilt from our drafts alone (_sent_unknown_rows).
    Without the audience there, every GC project moves onto the Direct board for the outage."""
    def down(*a, **k):
        raise HTTPException(502, "Could not reach the customer portal.")
    monkeypatch.setattr(main, "_portal", down)
    monkeypatch.setitem(main._PIPELINE_CACHE, "rows", None)
    monkeypatch.setitem(main._PIPELINE_CACHE, "fetched_at", None)
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: [
        _draft("sent-gc", "GC", sent_revision=2), _draft("sent-dir", "Direct", sent_revision=1)])
    body = _payload()
    assert body["portal_status"] == "offline"
    out = _by_id(body)
    assert out["sent-gc"]["portal_unknown"] is True
    assert out["sent-gc"]["audience"] == "GC" and out["sent-gc"]["pipeline"] == "gc"
    assert out["sent-dir"]["pipeline"] == "direct"


# The fast summary path, EXECUTED through a fake that honours the select the way PostgREST does:
# a field that `cols` does not name comes back absent. The same fake as test_hand_it_off.py and
# test_mark_won.py (copied, per the note there, rather than shared by editing those files).
class _ProjectingTable:
    def __init__(self, store, name):
        self.store, self.name, self.cols = store, name, ""

    def select(self, cols="*", *a, **k):
        self.cols = cols
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        rows = self.store.get(self.name) or []
        if self.name != "drafts":
            return type("R", (), {"data": []})()
        out = [{spec.split(":", 1)[0] if ":" in spec else spec:
                _jsonpath(r, spec.split(":", 1)[1] if ":" in spec else spec)
                for spec in self.cols.split(",")} for r in rows]
        return type("R", (), {"data": out})()


def _jsonpath(row, path):
    ops = re.findall(r"->>|->", path)
    parts = re.split(r"->>|->", path)
    cur = row.get(parts[0])
    for key in parts[1:]:
        cur = cur.get(key) if isinstance(cur, dict) else None
    if cur is None:
        return None
    if not ops or ops[-1] == "->>":
        if isinstance(cur, bool):
            return "true" if cur else "false"
        return cur if isinstance(cur, str) else str(cur)
    return cur


class _ProjectingClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _ProjectingTable(self.store, name)


def _projected(monkeypatch, data):
    store = {"drafts": [{"id": "d1", "owner_email": "k@x.com", "deleted_at": None,
                         "created_at": "2026-09-01", "updated_at": "2026-09-02", "data": data}]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    got = drafts._build_summaries(trashed=False, limit=10)
    assert len(got) == 1, "the fake projection broke the read; fix the fake, not the assertion"
    return got[0]


def test_the_fast_summary_projects_the_audience(monkeypatch):
    """The path that serves every real page load. A key it does not name reaches no card, and every
    GC project would sit on the Direct board while the full-blob fallback looked fine."""
    assert _projected(monkeypatch, {"project_name": "Oak", "audience": "GC"})["audience"] == "GC"
    assert _projected(monkeypatch, {"project_name": "Oak"})["audience"] is None


def test_both_summary_paths_agree_about_it(monkeypatch):
    for data in ({"project_name": "Oak", "audience": "GC"}, {"project_name": "Oak", "audience": "Direct"},
                 {"project_name": "Oak"}):
        fast = _projected(monkeypatch, data)["audience"]
        slow = drafts._summary({"id": "d1", "data": data})["audience"]
        assert fast == slow, data


# ── C. the General Contractor page ───────────────────────────────────────────
def _portal_text():
    return (FRONTEND / "portal.html").read_bytes().decode("utf-8")


def _no_comments(html):
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def test_every_swapped_string_is_in_portal_html_exactly_once():
    html = _portal_text()
    for old, _new in pipelines._GC_PAGE_SWAPS:
        assert html.count(old) == 1, "portal.html has %d copies of %r" % (html.count(old), old)


def test_the_gc_address_serves_portal_html_with_only_the_four_swaps():
    r = client.get(GC_PAGE)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.content == pipelines.board_page(_portal_text(), pipelines.GC).encode("utf-8")
    body = _no_comments(r.text)
    assert '<body data-pipeline="gc">' in body and 'data-pipeline="direct"' not in body
    assert "<h1>General Contractor</h1>" in body
    assert "<title>General Contractor · " in body
    assert "Proposals sent to general contractors" in body
    assert "Direct Projects" not in body, "the GC page still names the Direct board"
    # Everything else is the same page: the same scripts in the same order.
    scripts = lambda t: re.findall(r'<script src="([^"]+)"', t)
    assert scripts(r.text) == scripts(_portal_text())
    assert "/js/portal.js" in scripts(r.text)


def test_the_direct_board_is_still_portal_html_and_the_bare_domain():
    for path in ("/portal.html", "/"):
        r = client.get(path)
        assert r.status_code == 200, path
        body = _no_comments(r.text)
        assert '<body data-pipeline="direct">' in body, path
        assert "<h1>Direct Projects</h1>" in body, path


def test_the_gc_page_revalidates_like_every_other_page():
    r = client.get(GC_PAGE)
    assert r.headers["cache-control"] == "no-cache, must-revalidate"
    tag = r.headers["etag"]
    again = client.get(GC_PAGE, headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert client.head(GC_PAGE).status_code == 200


def test_a_portal_html_missing_a_swap_string_is_a_500_not_the_direct_page(tmp_path, monkeypatch):
    """Serving the Direct page's bytes here would put every Direct project under a General Contractor
    address with nothing on screen to say so. Refusing is the honest answer."""
    (tmp_path / "portal.html").write_text(
        _portal_text().replace("<h1>Direct Projects</h1>", "<h1>Projects</h1>"), encoding="utf-8")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    r = TestClient(main.app, raise_server_exceptions=False).get(GC_PAGE)
    assert r.status_code == 500
    with pytest.raises(pipelines.BoardPageError):
        pipelines.board_page("<body data-pipeline=\"direct\"><body data-pipeline=\"direct\">",
                             pipelines.GC)


def test_the_direct_page_is_portal_html_untouched():
    assert pipelines.board_page(_portal_text(), pipelines.DIRECT) == _portal_text()


# ── D/E/F. the page itself, through the real portal.js ───────────────────────
@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    # The endpoint function itself rather than an HTTP round trip: this fixture is module-scoped, so
    # conftest's per-test auth bypass is not in force yet, and the nav gate would go looking up a
    # profile. The payload is JSON-round-tripped so the page gets exactly what the wire carries.
    mp = pytest.MonkeyPatch()
    cache = dict(main._PIPELINE_CACHE)
    try:
        _wire(mp)
        payload = json.loads(json.dumps(main.api_portal_pipeline()))
    finally:
        mp.undo()
        main._PIPELINE_CACHE.update(cache)
    deeplinks = [
        ["gcOnDirect", "direct", "s-gc-1"], ["unsentGcOnDirect", "direct", "u-gc-1"],
        ["gcOnGc", "gc", "s-gc-1"], ["directOnGc", "gc", "s-dir-1"],
        ["orphanOnGc", "gc", "s-orphan"], ["directOnDirect", "direct", "s-dir-1"],
        ["unknownOnDirect", "direct", "nope"], ["unknownOnGc", "gc", "nope"],
    ]
    inp = tmp_path_factory.mktemp("gc") / "input.json"
    inp.write_text(json.dumps({"fixtures": [v for v, _ in RULE], "payload": payload,
                               "deeplinks": deeplinks}), encoding="utf-8")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND), str(inp)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "fatal" not in out, out.get("fatal")
    assert not out["errors"], out["errors"]
    out["_payload"] = payload
    return out


@needs_node
def test_the_page_and_the_server_put_every_card_on_the_same_board(harness):
    """The JavaScript rule over the endpoint's real payload, against the Python stamp on each card."""
    rows = harness["boardOfPayload"]
    assert len(rows) == len(harness["_payload"]["proposals"])
    for r in rows:
        assert r["js"] == r["server"], r


@needs_node
def test_each_board_holds_only_its_own_projects(harness):
    gc, direct = set(harness["boards"]["gc"]["ids"]), set(harness["boards"]["direct"]["ids"])
    assert gc == set().union(*EXPECT["gc"].values())
    assert direct == set().union(*EXPECT["direct"].values())
    assert not gc & direct, "a project is on both boards: %s" % (gc & direct)
    everything = {p["proposal_id"] for p in harness["_payload"]["proposals"]}
    assert gc | direct == everything, "a project is on neither board: %s" % (everything - gc - direct)
    assert harness["boards"]["gc"]["pipeline"] == "gc"
    assert harness["boards"]["direct"]["pipeline"] == "direct"


@needs_node
def test_a_page_that_names_no_pipeline_is_the_direct_board(harness):
    assert harness["boards"]["none"]["pipeline"] == "direct"
    assert set(harness["boards"]["none"]["ids"]) == set(harness["boards"]["direct"]["ids"])


@needs_node
@pytest.mark.parametrize("board", ["gc", "direct"])
def test_every_tab_counts_only_its_own_board(harness, board):
    """The pills, the "N proposals" line, and every column heading, read back out of what the page
    wrote — on every tab the page declares."""
    res = harness["boards"][board]
    assert set(harness["tabs"]) == set(EXPECT[board]), "a tab was added; give it a fixture row"
    for tab, want in EXPECT[board].items():
        assert int(res["pills"][tab]) == len(want), (board, tab, res["pills"])
        n = len(want)
        assert res["tabs"][tab]["count"] == "%d proposal%s" % (n, "" if n == 1 else "s"), (board, tab)
        cols = res["tabs"][tab]["columns"]
        drawn = [i for c in cols.values() for i in c["ids"]]
        assert set(drawn) == want and len(drawn) == len(want), (board, tab, cols)
        for name, c in cols.items():
            assert c["n"] == len(c["ids"]), (board, tab, name, c)
        assert not res["tabs"][tab]["undefinedLeak"], (board, tab)


@needs_node
def test_the_unsent_gc_card_is_in_the_gc_boards_first_column(harness):
    cols = harness["boards"]["gc"]["tabs"]["active"]["columns"]
    assert cols["Created but not sent"]["ids"] == ["u-gc-1"]
    assert "u-gc-1" not in [i for c in harness["boards"]["direct"]["tabs"]["active"]["columns"].values()
                            for i in c["ids"]]


@needs_node
def test_both_boards_offer_new_on_the_same_tabs(harness):
    for board in ("gc", "direct"):
        tabs = harness["boards"][board]["tabs"]
        assert tabs["active"]["newButton"] and tabs["test"]["newButton"], board
        assert not tabs["lost"]["newButton"] and not tabs["handed_off"]["newButton"], board


# E. + New
@needs_node
def test_new_on_the_gc_board_opens_the_intake_form_on_gc(harness):
    got = harness["newproj"]["gc"]
    assert got["state"] == {"audience": "GC"}, "the fresh project's state is not just its audience"
    assert got["checked"] == ["GC"], "the intake form's Audience radio did not open on GC"
    assert got["went"] == ["/?new=1"] and got["intents"] == [False]
    assert got["draftIdLeft"] is False, "the previous project's id survived, so this is not new"


@needs_node
def test_new_on_the_direct_board_stays_direct(harness):
    got = harness["newproj"]["direct"]
    assert got["state"] == {}, "the Direct board wrote something into the new project"
    assert got["checked"] == ["Direct"]
    assert got["went"] == ["/?new=1"] and got["intents"] == [False]


@needs_node
def test_the_test_tab_still_files_the_new_project_as_a_test_on_both_boards(harness):
    assert harness["newproj"]["gcTest"]["intents"] == [True]
    assert harness["newproj"]["gcTest"]["checked"] == ["GC"]
    assert harness["newproj"]["directTest"]["intents"] == [True]


@needs_node
def test_the_intake_forms_default_is_still_direct(harness):
    """What "stays Direct" rests on: the form's own default, unchanged."""
    radios = {r["value"]: r["checked"] for r in harness["radios"]}
    assert radios == {"Direct": True, "GC": False}


# F. deep links
@needs_node
@pytest.mark.parametrize("label,dest", [
    ("gcOnDirect", "/gc-projects.html?open=s-gc-1&sec=followup#here"),
    ("unsentGcOnDirect", "/gc-projects.html?open=u-gc-1&sec=followup#here"),
    ("directOnGc", "/portal.html?open=s-dir-1&sec=followup#here"),
    ("orphanOnGc", "/portal.html?open=s-orphan&sec=followup#here"),
])
def test_a_link_to_the_other_boards_project_goes_there_with_its_query(harness, label, dest):
    d = harness["deeplink"][label]
    assert d["first"]["replaced"] == [dest], d
    assert d["first"]["opened"] == [], "the drawer opened on the wrong board before leaving"
    assert d["first"]["painted"] is False, "the wrong board painted before the redirect"
    assert d["replaced"] == [dest], "a second load redirected again"
    assert d["opened"] == []


@needs_node
@pytest.mark.parametrize("label,pid", [
    ("gcOnGc", "s-gc-1"), ("directOnDirect", "s-dir-1"),
    # On neither board: the drawer is asked, exactly as before there were two boards.
    ("unknownOnDirect", "nope"), ("unknownOnGc", "nope"),
])
def test_a_link_to_this_boards_project_opens_the_drawer_here(harness, label, pid):
    """(Only the first load's openDetail is asserted: the stub stands in for the drawer, whose own
    DEEPLINK_USED latch is drawer-render-harness.js's business.)"""
    d = harness["deeplink"][label]
    assert d["first"]["replaced"] == [] and d["replaced"] == [], d
    assert d["first"]["opened"] == [pid], d
    assert d["first"]["painted"] is True, "the board did not paint under its own drawer"


def test_every_link_the_backend_builds_still_says_portal_html():
    """The redirect above is what makes these right for a GC project, which is why none of them had
    to change. If one of them starts naming a board itself, it needs the rule, not a guess."""
    src = (ROOT / "backend" / "notifications.py").read_text(encoding="utf-8")
    links = re.findall(r'"link":\s*f?"([^"]+)"|link = f"([^"]+)"', src)
    boards = [a or b for a, b in links if "portal.html" in (a or b) or "open=" in (a or b)]
    assert len(boards) >= 3, "the bell's project links moved; re-read this inventory: %s" % boards
    assert all(l.startswith("/portal.html") for l in boards), boards
    assert "gc-projects" not in src


# ── G. permissions ───────────────────────────────────────────────────────────
@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
    return tmp_path / "nav_access.json"


def test_the_new_tab_is_in_the_capability_table():
    row = next(t for t in nav_access.capability_table() if t["href"] == GC_PAGE)
    assert row["label"] == "General Contractor"
    assert row["pages"] == [GC_PAGE]
    assert row["api"] == [], "it shares every route with the Direct board, so it may own none"
    assert row["locked"] is False and row["no_sidebar"] is False
    assert nav_access.TABS["/portal.html"]["label"] == "Direct Projects"
    order = list(nav_access.TABS)
    assert order.index(GC_PAGE) == order.index("/portal.html") + 1


@pytest.mark.parametrize("policy", [
    None,                                                    # no file at all: today on every box
    {"deny": {}},
    {"deny": {"user": ["/leads.html", "/trash.html"], "admin": ["/analytics.html"]}},
    # hand-edited to deny the Direct board — stripped, because it is LOCKED
    {"deny": {"user": ["/portal.html"], "admin": ["/PORTAL.HTML", "portal.html"],
              "super_admin": ["/portal.html"]}},
    "{not json",
])
def test_by_default_everybody_has_the_gc_board_exactly_when_they_have_the_direct_one(policy_file,
                                                                                    policy):
    if policy is not None:
        policy_file.write_text(policy if isinstance(policy, str) else json.dumps(policy),
                               encoding="utf-8")
    for role in nav_access.ROLES:
        direct = nav_access.page_denied(role, "/portal.html")
        gc = nav_access.page_denied(role, GC_PAGE)
        assert gc == direct, (role, policy, gc, direct)
        assert gc is None, "the GC board is denied by default to %s" % role
        assert (GC_PAGE in nav_access.denied_paths(role)) == ("/portal.html" in nav_access.denied_paths(role))


def test_switching_it_off_is_a_separate_decision_that_leaves_the_direct_board_alone(policy_file):
    nav_access.save({"user": [GC_PAGE]}, "hanz@wetreadwell.com")
    assert nav_access.page_denied("user", GC_PAGE) == GC_PAGE
    assert nav_access.page_denied("user", "/portal.html") is None
    assert nav_access.page_denied("admin", GC_PAGE) is None
    # and the pipeline route stays open: the Direct board is the same call
    assert nav_access.is_api_denied("user", "/api/portal/pipeline") is False


# ── H. the relabel ───────────────────────────────────────────────────────────
def _in_comment(line, at):
    """Is the text at column `at` of this JS/CSS line inside a comment?

    LINE-BASED ON PURPOSE. A regex that strips /* ... */ across the file is fooled by a string that
    contains "/*" — admin.js prints "/api/admin/*" — and swallows the real text up to the next
    comment's "*/", which is exactly how an early draft of this test passed with a reverted label
    sitting in a template literal. Comment lines here all START with //, /* or * (the house style),
    and a trailing comment is " // " after code."""
    head = line[:at]
    stripped = line.lstrip()
    if stripped.startswith(("//", "/*", "*")):
        return True
    return bool(re.search(r"(^|\s)//\s", head))


def test_no_user_facing_active_projects_is_left():
    """Every string a person can read — markup, labels, tooltips, alerts, refusal cards — across the
    whole frontend, with comments taken out (the history in them quotes the old name on purpose)."""
    hits = []
    for p in sorted(list(FRONTEND.rglob("*.js")) + list(FRONTEND.rglob("*.html"))):
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".html":
            text = _no_comments(text)
        for line in text.splitlines():
            for m in re.finditer(r"Active Projects", line):
                if not _in_comment(line, m.start()):
                    hits.append("%s: %s" % (p.name, line.strip()[:160]))
    assert not hits, "\n".join(hits)
    labels = [t["label"] for t in nav_access.capability_table()]
    assert "Active Projects" not in labels and "Direct Projects" in labels


def test_the_refusal_card_sends_you_to_direct_projects():
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert ">Go to Direct Projects</a>" in auth
