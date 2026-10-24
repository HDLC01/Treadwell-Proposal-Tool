"""Scope groups, HARDENED (2026-10-24 review of RJ's "one project, many proposals, one email").

What test_scope_groups.py built, made safe against the review's findings, tool side:

  1. CAPABILITY CHECK: a grouped publish and the combined send ask the portal what it can do first,
     and an older (or silent) portal is refused BEFORE a revision or a portal row exists: an older
     portal would email every scope on its own and chase each one separately. Ungrouped publishes
     never ask.
  2. HONEST DRAWER: "Sent" only when somebody got it, every contact it missed named (and only those
     retried), the scopes left out named, every refusal a sentence (executed in the drawer harness).
  3. THE PROJECT'S EMAIL FOLLOWS THE PORTAL: the card's chip and the drawer's button come from the
     portal's scope_send_state ("Email again: 1 new, 1 revised"); a project sent BEFORE it gained
     scopes joins the group without a new revision and is never told to be published again.
  4. ONE MEMBERSHIP RULE (drafts.live_scope_members): not archived, never test beside real.
  5. THE TEST RULE: a new scope and a publish refuse to put a Test project and a real one together.
  6. SPLIT CLEANUP: a half-failed split takes back what it minted; a split bid stays on the board;
     the parent drops the combined bid's Dropbox record and narrative.
  7. DROPBOX NAMES: the scope is never cut off a file name, so two scopes never share one.
"""
import copy
import json
import pathlib
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

import drafts
import dropbox_client
import main
from conftest import FakeClient, FakeTable
from test_hand_it_off import _ProjectingClient

client = TestClient(main.app)

GID = "grp_hardening0001"
EST = "kyle@wetreadwell.com"
TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _draft(rid, label=None, gid=GID, created="2026-10-01", **data):
    d = {"project_name": "Acme HQ", "work_type": "epoxy"}
    d.update(data)
    if label is not None:
        d["scope_group"] = {"id": gid, "label": label}
    return {"id": rid, "data": d, "owner_email": EST, "created_at": created,
            "updated_at": "2026-10-20T10:00:00+00:00", "deleted_at": None}


def _store(fake_supabase, monkeypatch, *rows):
    store = {"drafts": [copy.deepcopy(r) for r in rows], "events": [], "draft_revisions": []}
    monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(store))
    return store


def _row(store, rid):
    return next(r for r in store["drafts"] if r["id"] == rid)


# ── 1. the capability check ─────────────────────────────────────────────────
def _wire_publish(monkeypatch, caps):
    """The publish route with everything but the scope logic stubbed. `caps` is what the portal's
    /api/admin/capabilities answers: a dict, or an int for an HTTP error status."""
    cap = {"paths": [], "revisions": []}
    monkeypatch.setattr(main.drafts, "create_revision",
                        lambda did, data, by=None: cap["revisions"].append(did) or 1)
    monkeypatch.setattr(main.drafts, "delete_revision", lambda *a: None)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.drafts, "set_assigned_estimator", lambda *a, **k: True)

    def fake_portal(path, method="GET", body=None):
        cap["paths"].append(path)
        if path == "/api/admin/capabilities":
            if isinstance(caps, int):
                raise main.HTTPException(caps if caps < 500 else 502, "Not Found" if caps == 404 else "x")
            return caps
        return {"ok": True, "awaiting_group_send": True}
    monkeypatch.setattr(main, "_portal", fake_portal)
    return cap


def _publish(rid="s1"):
    return client.post("/api/portal/publish?draft_id=%s" % rid, json={"assigned_estimator": EST})


@pytest.mark.parametrize("caps", [404, {}, {"scope_groups": False}, {"ok": True}])
def test_an_old_portal_gets_no_grouped_publish_and_nothing_is_minted(fake_supabase, monkeypatch, caps):
    _store(fake_supabase, monkeypatch, _draft("s1", "Breakroom"), _draft("s2", "Lab 1"))
    cap = _wire_publish(monkeypatch, caps)
    r = _publish()
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "portal_not_ready" and "nothing was sent" in j["error"]
    assert cap["revisions"] == [], "a refused grouped publish minted a revision"
    assert cap["paths"] == ["/api/admin/capabilities"], "the publish reached the portal anyway"


def test_a_portal_that_cannot_be_asked_is_refused_too(fake_supabase, monkeypatch):
    _store(fake_supabase, monkeypatch, _draft("s1", "Breakroom"), _draft("s2", "Lab 1"))
    cap = _wire_publish(monkeypatch, 502)
    r = _publish()
    assert r.status_code == 502 and r.json()["code"] == "portal_unreachable"
    assert cap["revisions"] == [] and "/api/admin/publish" not in cap["paths"]


def test_a_ready_portal_publishes_and_is_asked_once_a_minute(fake_supabase, monkeypatch):
    _store(fake_supabase, monkeypatch, _draft("s1", "Breakroom"), _draft("s2", "Lab 1"))
    cap = _wire_publish(monkeypatch, {"scope_groups": True, "group_followups": True, "version": 1})
    assert _publish("s1").status_code == 200
    assert _publish("s2").status_code == 200
    assert cap["paths"].count("/api/admin/capabilities") == 1, cap["paths"]
    assert cap["paths"].count("/api/admin/publish") == 2 and cap["revisions"] == ["s1", "s2"]
    # ...and asked again once the minute is up
    main._CAPS_CACHE["at"] = time.time() - main._CAPS_TTL_S - 1
    assert _publish("s1").status_code == 200
    assert cap["paths"].count("/api/admin/capabilities") == 2


def test_an_ungrouped_publish_never_asks(fake_supabase, monkeypatch):
    _store(fake_supabase, monkeypatch, _draft("solo"))
    cap = _wire_publish(monkeypatch, 404)
    assert _publish("solo").status_code == 200
    assert "/api/admin/capabilities" not in cap["paths"]
    assert cap["revisions"] == ["solo"]


def test_the_combined_send_is_not_forwarded_to_an_old_portal(monkeypatch):
    forwarded = []

    async def raw(*a, **k):
        forwarded.append(a)
        return main.Response(content=b'{"detail": "Not Found"}', status_code=404)
    monkeypatch.setattr(main, "_portal_raw", raw)
    monkeypatch.setattr(main, "_portal", lambda *a, **k: (_ for _ in ()).throw(
        main.HTTPException(404, "Not Found")))
    r = client.post("/api/portal/scope-group/%s/send" % GID, json={})
    assert r.status_code == 409 and r.json()["code"] == "portal_not_ready"
    assert "not been updated" in r.json()["error"]
    assert forwarded == [], "the send reached a portal that would have answered a bare Not Found"


def test_the_combined_send_forwards_a_retry_of_only_the_failed_contacts(monkeypatch):
    seen = {}

    async def raw(path, method, blob, ctype):
        seen["body"] = json.loads(blob)
        return main.Response(content=b'{"ok": true}', status_code=200,
                             headers={"content-type": "application/json"})
    monkeypatch.setattr(main, "_portal_raw", raw)
    monkeypatch.setattr(main, "_portal_capabilities", lambda: {"scope_groups": True})
    assert client.post("/api/portal/scope-group/%s/send" % GID,
                       json={"retry_failed": True}).status_code == 200
    assert seen["body"]["retry_failed"] is True and "resend" not in seen["body"]
    client.post("/api/portal/scope-group/%s/send" % GID, json={})
    assert "retry_failed" not in seen["body"]


# ── 3. the project's one email, from the portal's own record ────────────────
def _summ(i, label, **kw):
    s = {"id": "s%d" % i, "project_name": "Acme HQ", "has_files": True, "scope_group_id": GID,
         "scope_label": label, "created_at": "2026-10-0%d" % i, "updated_at": "2026-10-1%d" % i,
         "total": None}
    s.update(kw)
    return s


def _board(monkeypatch, portal_rows, summaries):
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": portal_rows})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: summaries)
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return {p["proposal_id"]: p for p in r.json()["proposals"]}


def _prow(i, state, **kw):
    r = {"proposal_id": "s%d" % i, "project_name": "Acme HQ", "proposal_status": "sent",
         "scope_group": GID, "scope_send_state": state}
    r.update(kw)
    return r


SUMS = [_summ(1, "Breakroom"), _summ(2, "Lab 1"), _summ(3, "Lab 2")]


def test_a_scope_added_and_one_revised_after_the_email_are_emailable_again(monkeypatch):
    state = {"announced": True, "pending_scope_ids": ["s2", "s3"], "not_included": []}
    rows = _board(monkeypatch, [_prow(1, state, last_sent_at="2026-10-02"),
                                _prow(2, state, last_sent_at="2026-10-02"),   # revised since
                                _prow(3, state)],                             # added since
                  SUMS)
    for pid in ("s1", "s2", "s3"):
        ss = rows[pid]["scope_send"]
        assert ss["label"] == "Email again: 1 new, 1 revised" and ss["pending"] == ["s2", "s3"]
    assert [rows[p]["scope_send"]["mine"] for p in ("s1", "s2", "s3")] == [False, True, True]
    assert [m["pending"] for m in rows["s1"]["scope_members"]] == [False, True, True]


def test_before_the_first_email_the_button_sends_every_scope(monkeypatch):
    state = {"announced": False, "pending_scope_ids": ["s1", "s2", "s3"], "not_included": []}
    rows = _board(monkeypatch, [_prow(i, state) for i in (1, 2, 3)], SUMS)
    ss = rows["s2"]["scope_send"]
    assert ss["label"] == "Send every scope in one email" and ss["chip"] == "Email not sent"


def test_with_nothing_new_there_is_no_button_and_no_chip(monkeypatch):
    state = {"announced": True, "pending_scope_ids": [], "not_included": ["s3"]}
    rows = _board(monkeypatch, [_prow(1, state), _prow(2, state)], SUMS)
    ss = rows["s1"]["scope_send"]
    assert ss["label"] is None and ss["chip"] is None and ss["mine"] is False
    assert ss["not_included"] == ["s3"]


def test_an_older_portal_leaves_the_old_fields_alone(monkeypatch):
    rows = _board(monkeypatch, [{"proposal_id": "s1", "project_name": "Acme HQ",
                                 "proposal_status": "sent", "scope_group": GID,
                                 "scope_send_pending": True}], SUMS[:2])
    assert "scope_send" not in rows["s1"] and rows["s1"]["scope_send_pending"] is True


def test_a_project_sent_before_it_had_scopes_joins_without_a_new_revision(fake_supabase, monkeypatch):
    """Finding 1/30: 'New scope' on a SENT project. The sent parent joins the group in the tool, with
    no revision (a revision would reopen the customer's approval) and no portal call, and the board
    calls it a SENT member rather than one to publish."""
    store = _store(fake_supabase, monkeypatch, _draft("p1"))
    store["draft_revisions"].append({"project_id": "p1", "revision_no": 1})
    monkeypatch.setattr(main, "_portal", lambda *a, **k: (_ for _ in ()).throw(AssertionError("portal called")))
    j = client.post("/api/draft/p1/scope", json={"label": "Lab 1"}).json()
    assert j["ok"] is True
    assert store["draft_revisions"] == [{"project_id": "p1", "revision_no": 1}], "a new revision was minted"
    assert _row(store, "p1")["data"]["scope_group"]["id"] == j["group_id"]
    gid = j["group_id"]
    summaries = [drafts._summary(dict(_row(store, rid))) for rid in ("p1", j["id"])]
    summaries[0]["has_files"] = True
    rows = _board(monkeypatch, [{"proposal_id": "p1", "project_name": "Acme HQ",
                                 "proposal_status": "approved", "last_sent_at": "2026-10-01"}],
                  summaries)
    assert rows["p1"]["scope_group"] == gid
    assert {m["id"]: m["sent"] for m in rows["p1"]["scope_members"]} == {"p1": True, j["id"]: False}


# ── 4. one membership rule ──────────────────────────────────────────────────
def test_the_live_member_rule():
    ms = [{"id": "a", "created_at": "1", "archived": False, "is_test": None},
          {"id": "b", "created_at": "2", "archived": True, "is_test": None},
          {"id": "c", "created_at": "3", "archived": "false", "is_test": "true"},
          {"id": "d", "created_at": "4", "archived": None, "is_test": False}]
    assert [m["id"] for m in drafts.live_scope_members(ms)] == ["a", "d"]
    # ONE real active scope makes the group real (the portal's rule, finding 7): the home being a
    # Test no longer turns the project into a test group.
    ms[0]["is_test"] = True
    assert [m["id"] for m in drafts.live_scope_members(ms)] == ["d"]
    # ...and a group whose active scopes are ALL tests keeps every one of them.
    ms[3]["is_test"] = True
    assert [m["id"] for m in drafts.live_scope_members(ms)] == ["a", "c", "d"]
    assert drafts.live_scope_members([]) == []


CASES = json.loads((TESTS / "scope_member_cases.json").read_text(encoding="utf-8"))["cases"]
PORTAL_REPO = pathlib.Path(__import__("os").environ.get("TW_PORTAL_REPO")
                           or (TESTS.parents[2] / "treadwell-portal"))
_IN_CI = (__import__("os").environ.get("CI", "").strip().lower() in ("1", "true", "yes")
          or bool(__import__("os").environ.get("GITHUB_ACTIONS")))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_shared_member_table_holds_in_the_tool(case):
    """tests/scope_member_cases.json: the cases the tool AND the portal assert (finding 7). Four of
    the first five disagreed before: the tool let the home decide the kind and ignored the name."""
    live = [m["id"] for m in drafts.live_scope_members(copy.deepcopy(case["states"]))]
    assert live == case["live"]
    assert [s["id"] for s in case["states"] if s["id"] not in live] == case["parked"]


def _portal_scope_groups():
    path = PORTAL_REPO / "backend" / "scope_groups.py"
    if not PORTAL_REPO.is_dir():
        if _IN_CI:
            pytest.fail("the portal is not checked out at %s" % PORTAL_REPO)
        pytest.skip("the customer portal is not checked out beside this repo")
    assert path.exists(), "the portal has no scope_groups.py: its membership rule moved; re-read it"
    import importlib.util
    spec = importlib.util.spec_from_file_location("_portal_scope_groups_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_shared_member_table_holds_in_the_portal(case):
    """The same table through the PORTAL's own split_members, executed from its checkout, so the two
    rules cannot drift apart while each repo's own tests stay green."""
    live, parked = _portal_scope_groups().split_members(copy.deepcopy(case["states"]))
    assert (live, parked) == (case["live"], case["parked"])


def test_the_portals_copy_of_the_table_is_this_one():
    """Each repo keeps the table in its own tests folder. Once the portal has its copy, the two must
    be identical; until then this says so instead of passing on nothing."""
    theirs = PORTAL_REPO / "backend" / "tests" / "scope_member_cases.json"
    if not theirs.exists():
        if _IN_CI:
            pytest.fail("the portal has no tests/scope_member_cases.json beside its split_members")
        pytest.skip("the portal's copy of scope_member_cases.json is not there yet")
    assert json.loads(theirs.read_text(encoding="utf-8")) == json.loads(
        (TESTS / "scope_member_cases.json").read_text(encoding="utf-8"))


# ── set_test_flag never splits a project into test and real ───────────────────
@pytest.mark.parametrize("now,want", [
    (None, True),     # a real project: one scope marked Test
    (True, False),    # a test project: one scope marked real
])
def test_marking_one_scope_of_a_project_the_other_kind_is_refused(fake_supabase, monkeypatch, now, want):
    store = _store(fake_supabase, monkeypatch,
                   _draft("s1", "Breakroom", is_test=now),
                   _draft("s2", "Lab 1", created="2026-10-02", is_test=now),
                   _draft("s3", "Lab 2", created="2026-10-03", is_test=now))
    before = copy.deepcopy(store["drafts"])
    events = len(store["events"])
    r = client.post("/api/draft/s1/test", json={"is_test": want})
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["ok"] is False and j["code"] == "test_mix"
    assert j["error"].startswith("Nothing changed:") and "cannot be one project" in j["error"]
    assert store["drafts"] == before, "a refused flag was written"
    assert len(store["events"]) == events, "a refused flag was logged"


def test_a_flag_that_keeps_the_scope_its_kind_or_is_on_no_group_is_written(fake_supabase, monkeypatch):
    store = _store(fake_supabase, monkeypatch,
                   _draft("s1", "Breakroom", project_name="Sample HQ"),     # a test by its name
                   _draft("s2", "Lab 1", created="2026-10-02", project_name="Sample HQ"),
                   _draft("solo"))
    # marking a test-named scope Test by hand changes nothing about the group
    assert client.post("/api/draft/s1/test", json={"is_test": True}).json()["ok"] is True
    assert _row(store, "s1")["data"]["is_test"] is True
    # an ungrouped project is filed as before, either way
    assert client.post("/api/draft/solo/test", json={"is_test": True}).json()["ok"] is True
    assert client.post("/api/draft/solo/test", json={"is_test": False}).json()["ok"] is True
    assert _row(store, "solo")["data"]["is_test"] is False


def test_an_archived_sibling_does_not_block_the_flag(fake_supabase, monkeypatch):
    store = _store(fake_supabase, monkeypatch, _draft("s1", "Breakroom"),
                   _draft("s2", "Lab 1", created="2026-10-02", archived=True))
    assert client.post("/api/draft/s1/test", json={"is_test": True}).json()["ok"] is True
    assert _row(store, "s1")["data"]["is_test"] is True


def test_the_test_rule_reads_the_project_name_too(fake_supabase, monkeypatch):
    """The name check reaches the publish and the new-scope refusals: a real customer's group never
    takes a scope whose project name reads as a test and that nobody has marked either way."""
    _store(fake_supabase, monkeypatch, _draft("s1", "Breakroom"),
           _draft("s2", "Lab 1", created="2026-10-02", project_name="Acme QA Lab"))
    r = client.post("/api/draft/s2/scope", json={"label": "Lab 2"})
    assert r.status_code == 409 and r.json()["code"] == "test_mix", r.text


def test_an_archived_scope_holds_no_name_and_no_place(fake_supabase, monkeypatch):
    store = _store(fake_supabase, monkeypatch, _draft("p1", "Breakroom"),
                   _draft("old", "Lab 2", created="2026-10-02", archived=True))
    out = drafts.create_sibling("p1", "Lab 2")
    assert _row(store, out["id"])["data"]["scope_group"] == {"id": GID, "label": "Lab 2"}
    assert [m["id"] for m in drafts._group_rows(GID)] == ["p1", out["id"]]


def test_the_projection_reads_archived_and_test(monkeypatch):
    store = {"drafts": [_draft("p1", "Breakroom"), _draft("p2", "Lab 1", created="2026-10-02",
                                                          archived=True),
                        _draft("p3", "Lab 2", created="2026-10-03", is_test=True)]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    every = drafts._group_rows_all(GID)
    assert [(m["id"], m["archived"]) for m in every] == [("p1", False), ("p2", True), ("p3", False)]
    assert [m["id"] for m in drafts._group_rows(GID)] == ["p1"]


def test_the_projection_reads_the_project_name_the_test_rule_falls_back_on(monkeypatch):
    store = {"drafts": [_draft("p1", "Breakroom"),
                        _draft("p2", "Lab 1", created="2026-10-02", project_name="Acme QA Lab")]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    assert [m["project_name"] for m in drafts._group_rows_all(GID)] == ["Acme HQ", "Acme QA Lab"]
    assert [m["id"] for m in drafts._group_rows(GID)] == ["p1"]


def test_the_board_draws_only_live_members(monkeypatch):
    rows = _board(monkeypatch, [], [_summ(1, "Breakroom"), _summ(2, "Lab 1", archived=True),
                                    _summ(3, "Lab 2", is_test=True)])
    assert [m["id"] for m in rows["s1"]["scope_members"]] == ["s1"]
    assert rows["s1"]["scope_count"] == 1


def test_an_excluded_scope_is_not_drawn_as_a_member_itself(monkeypatch):
    """The live-member rule judges the card being stamped as well as its list: an archived scope and
    a Test scope of a real project are ordinary proposals, never 'Scope 0 of 1' beside Breakroom."""
    state = {"announced": True, "pending_scope_ids": [], "not_included": []}
    rows = _board(monkeypatch, [_prow(1, state), _prow(2, state), _prow(3, state)],
                  [_summ(1, "Breakroom"), _summ(2, "Lab 1", archived=True),
                   _summ(3, "Lab 2", is_test=True)])
    assert rows["s1"]["scope_index"] == 1 and rows["s1"]["scope_count"] == 1
    for pid in ("s2", "s3"):
        r = rows[pid]
        assert r["scope_group"] is None and r["scope_label"] is None, (pid, r)
        assert "scope_index" not in r and "scope_members" not in r and "scope_send" not in r, (pid, r)


# ── 5. the test rule ────────────────────────────────────────────────────────
@pytest.mark.parametrize("parent_test,other_test", [(True, None), (None, True), (False, True)])
def test_a_new_scope_never_mixes_test_and_real(fake_supabase, monkeypatch, parent_test, other_test):
    store = _store(fake_supabase, monkeypatch, _draft("p1", "Breakroom", is_test=parent_test),
                   _draft("p2", "Lab 1", created="2026-10-02", is_test=other_test))
    r = client.post("/api/draft/p1/scope", json={"label": "Lab 2"})
    assert r.status_code == 409 and r.json()["code"] == "test_mix", r.text
    assert "Test" in r.json()["error"]
    assert len(store["drafts"]) == 2, "a refused scope was minted"


def test_a_new_scope_of_one_kind_is_made(fake_supabase, monkeypatch):
    _store(fake_supabase, monkeypatch, _draft("p1", "Breakroom", is_test=True),
           _draft("p2", "Lab 1", created="2026-10-02", is_test=True))
    assert client.post("/api/draft/p1/scope", json={"label": "Lab 2"}).status_code == 200


def test_a_publish_never_mixes_test_and_real(fake_supabase, monkeypatch):
    _store(fake_supabase, monkeypatch, _draft("s1", "Breakroom", is_test=True), _draft("s2", "Lab 1"))
    cap = _wire_publish(monkeypatch, {"scope_groups": True})
    for rid in ("s1", "s2"):
        r = _publish(rid)
        assert r.status_code == 409 and r.json()["code"] == "test_mix", r.text
        assert r.json()["error"].startswith("Not sent.")
    assert cap["revisions"] == [] and cap["paths"] == [], "a mixed group reached the portal"


# ── 6. split cleanup ────────────────────────────────────────────────────────
V = "2026-10-20T10:00:00+00:00"


def _child(tab, work_type, label):
    return {"tab_id": tab, "label": label,
            "data": {"polish_estimate": {"version": 2, "label": label}, "work_type": work_type,
                     "base_tab_id": tab, "proposal_lump_sum": 1000}}


SPLIT = {"draft_version": V, "children": [_child("Polish", "polish", "Breakroom"),
                                          _child("Epoxy", "epoxy", "Lab 1"),
                                          _child("Copy1", "epoxy", "Lab 2")]}
COMBINED = {"project_name": "Acme HQ", "work_type": "combo", "polish_estimate": {"version": 2},
            "generate_result": {"work_type": "combo"}, "dropbox_result": {"folder_path": "/x"},
            "scope_notes": "Breakroom, Lab 1 and Lab 2", "schedule_notes": "S", "exclusions": "E",
            "system_name": "Combined", "system_name_manual": True, "texture": "T"}


def _no_portal_row(*a, **k):
    raise main.HTTPException(404, "not_found")


class _Flaky(FakeClient):
    """Inserts fail after `ok` of them; deletes fail when `deletes_fail`."""

    def __init__(self, store, ok, deletes_fail=False):
        super().__init__(store)
        self.ok, self.deletes_fail, self.inserts = ok, deletes_fail, 0

    def table(self, name):
        outer = self
        t = FakeTable(self.store, name, self.captures)
        real = t.execute

        def execute():
            if t._op == "insert" and name == "drafts":
                if outer.inserts >= outer.ok:
                    raise RuntimeError("PostgREST blip")
                outer.inserts += 1
            if t._op == "delete" and outer.deletes_fail:
                raise RuntimeError("PostgREST blip")
            return real()
        t.execute = execute
        return t


@pytest.mark.parametrize("deletes_fail", [False, True])
def test_a_half_failed_split_takes_back_what_it_minted(fake_supabase, monkeypatch, deletes_fail):
    store = {"drafts": [_draft("p1", data_marker=1, **COMBINED)], "events": [], "draft_revisions": []}
    before = copy.deepcopy(store["drafts"][0])
    monkeypatch.setattr(drafts, "get_client", lambda: _Flaky(store, ok=1, deletes_fail=deletes_fail))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    r = client.post("/api/draft/p1/split", json=SPLIT)
    assert r.status_code == 503 and r.json()["code"] == "split_failed", r.text
    assert _row(store, "p1") == before, "the parent changed in a split that failed"
    grouped = [x for x in store["drafts"] if x["id"] != "p1" and (x["data"] or {}).get("scope_group")]
    assert grouped == [], "a child of a failed split still holds the group"
    if deletes_fail:
        orphan = [x for x in store["drafts"] if x["id"] != "p1"]
        assert len(orphan) == 1 and orphan[0]["data"]["archived"] is True
    else:
        assert [x["id"] for x in store["drafts"]] == ["p1"]


class _InsertLostAnswer(FakeClient):
    """The `n`-th draft insert COMMITS, then its answer is lost (a read timeout after the write)."""

    def __init__(self, store, n):
        super().__init__(store)
        self.n, self.inserts = n, 0

    def table(self, name):
        outer = self
        t = FakeTable(self.store, name, self.captures)
        real = t.execute

        def execute():
            if t._op == "insert" and name == "drafts":
                outer.inserts += 1
                if outer.inserts == outer.n:
                    real()
                    raise RuntimeError("read timeout")
            return real()
        t.execute = execute
        return t


def test_a_child_whose_insert_committed_but_lost_its_answer_is_taken_back(fake_supabase, monkeypatch):
    """Finding 24: the second child's insert commits and its answer is lost. The split is refused,
    and that child goes too: left behind it would hold the group's id and Lab 2's name, join the
    project, block a retry with label_taken and be expected by the combined email."""
    store = {"drafts": [_draft("p1", **COMBINED)], "events": [], "draft_revisions": []}
    before = copy.deepcopy(store["drafts"][0])
    monkeypatch.setattr(drafts, "get_client", lambda: _InsertLostAnswer(store, n=2))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    r = client.post("/api/draft/p1/split", json=SPLIT)
    assert r.status_code == 503 and r.json()["code"] == "split_failed", r.text
    assert _row(store, "p1") == before
    assert [x["id"] for x in store["drafts"]] == ["p1"], "a committed child of a failed split survived"


class _LostAnswer(FakeClient):
    """The parent's update COMMITS, then the answer is lost (a read timeout after the write).
    `reads_fail` makes the read-back fail too."""

    def __init__(self, store, reads_fail=False):
        super().__init__(store)
        self.reads_fail, self.updated = reads_fail, False

    def table(self, name):
        outer = self
        t = FakeTable(self.store, name, self.captures)
        real = t.execute

        def execute():
            if name == "drafts" and t._op == "update" and not outer.updated:
                real()
                outer.updated = True
                raise RuntimeError("read timeout")
            if name == "drafts" and t._op == "select" and outer.updated and outer.reads_fail:
                raise RuntimeError("PostgREST blip")
            return real()
        t.execute = execute
        return t


@pytest.mark.parametrize("reads_fail", [False, True])
def test_a_split_whose_parent_write_landed_keeps_every_sheet(fake_supabase, monkeypatch, reads_fail):
    """The parent update committed and only its answer was lost: the parent already holds only the
    Breakroom sheet, so deleting the Lab 1 and Lab 2 children would lose those sheets for good."""
    store = {"drafts": [_draft("p1", **COMBINED)], "events": [], "draft_revisions": []}
    monkeypatch.setattr(drafts, "get_client", lambda: _LostAnswer(store, reads_fail=reads_fail))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    r = client.post("/api/draft/p1/split", json=SPLIT)
    labels = sorted(((x["data"] or {}).get("scope_group") or {}).get("label", "")
                    for x in store["drafts"])
    assert labels == ["Breakroom", "Lab 1", "Lab 2"], "a sheet of a split that happened was deleted"
    assert _row(store, "p1")["data"].get("split_at")
    if reads_fail:
        assert r.status_code == 503 and r.json()["code"] == "split_unconfirmed", r.text
        assert "Nothing was removed" in r.json()["error"]
    else:
        assert r.status_code == 200, r.text
        assert sorted(c["label"] for c in r.json()["children"]) == ["Lab 1", "Lab 2"]


def test_a_split_bid_stays_on_the_board_as_its_scopes(fake_supabase, monkeypatch):
    """Finding 26: no hand-flipped has_files. The real split of a 'Created but not sent' bid, the real
    summaries, the real board."""
    store = _store(fake_supabase, monkeypatch, _draft("p1", **COMBINED))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    j = client.post("/api/draft/p1/split", json=SPLIT).json()
    ids = ["p1"] + [c["id"] for c in j["children"]]
    summaries = [drafts._summary(dict(_row(store, i))) for i in ids]
    assert not any(s["has_files"] for s in summaries)
    rows = _board(monkeypatch, [], summaries)
    assert set(rows) == set(ids), "the split bid left the board"
    assert all(rows[i]["not_sent"] and rows[i]["files_pending"] for i in ids)


def test_a_bid_split_before_it_had_files_stays_off_the_board(fake_supabase, monkeypatch):
    data = {k: v for k, v in COMBINED.items() if k != "generate_result"}
    store = _store(fake_supabase, monkeypatch, _draft("p1", **data))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    j = client.post("/api/draft/p1/split", json=SPLIT).json()
    assert "split_had_files" not in _row(store, "p1")["data"]
    ids = ["p1"] + [c["id"] for c in j["children"]]
    assert _board(monkeypatch, [], [drafts._summary(dict(_row(store, i))) for i in ids]) == {}


def test_the_split_parent_drops_the_combined_dropbox_record_and_narrative(fake_supabase, monkeypatch):
    store = _store(fake_supabase, monkeypatch, _draft("p1", **COMBINED))
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    assert client.post("/api/draft/p1/split", json=SPLIT).status_code == 200
    parent = _row(store, "p1")["data"]
    for k in ("dropbox_result", "scope_notes", "schedule_notes", "exclusions", "system_name",
              "system_name_manual", "texture"):
        assert k not in parent, "%s of the combined bid survived on the split parent" % k
    assert parent["split_had_files"] is True and parent["project_name"] == "Acme HQ"


def test_the_fast_projection_carries_the_split_mark(monkeypatch):
    store = {"drafts": [dict(_draft("d1", "Breakroom"), data={"project_name": "Acme HQ",
                                                             "split_had_files": True})]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    assert drafts._build_summaries(trashed=False, limit=10)[0]["split_had_files"] is True
    assert drafts._summary({"id": "x", "data": {}})["split_had_files"] is False


# ── 7. Dropbox names ────────────────────────────────────────────────────────
LONG = "Kansas City Kansas Community College - Technical Education Center Phase 2 Renovation"


@pytest.mark.parametrize("project", [LONG, LONG * 2])
def test_the_scope_is_never_cut_off_a_file_name(project):
    names = {}
    for scope in ("Lab 1", "Lab 2", "x" * 80):
        prop = dropbox_client._project_proposal_name(project, "epoxy", "2026-11-02", None, scope)
        est = dropbox_client._estimate_file_name(project, scope)
        assert prop.endswith(" - " + scope) and len(prop) <= 120, prop
        assert est.endswith(" - " + scope + ".xlsx"), est
        assert len(est) <= len("$ estimate sheet - .xlsx") + 120
        names[scope] = (prop, est)
    assert len({p for p, _ in names.values()}) == 3 and len({e for _, e in names.values()}) == 3


def test_a_name_that_fits_and_every_unscoped_name_are_unchanged():
    def old(head, project, scope):
        return dropbox_client._sanitize_folder_name(
            head + dropbox_client._scoped_name(project, scope))
    head = "11.02.26 TREADWELL EPOXY PROPOSAL - "
    for project, scope in (("Acme HQ", "Lab 1"), (LONG, None), (LONG * 2, None), ("A/B: C", "Lab 1")):
        assert dropbox_client._project_proposal_name(project, "epoxy", "2026-11-02", None, scope) \
            == old(head, project, scope)
        assert dropbox_client._estimate_file_name(project, scope) \
            == "$ estimate sheet - %s.xlsx" % old("", project, scope)


# ── 2/3. the drawer and the card, EXECUTED ──────────────────────────────────
def _node(*args):
    proc = subprocess.run(["node", *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def drawer():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _node(TESTS / "js" / "drawer-render-harness.js", FRONTEND)


@pytest.fixture(scope="module")
def board():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return _node(TESTS / "js" / "board-render-harness.js", FRONTEND / "js" / "crm-core.js",
                 FRONTEND / "js" / "portal.js", FRONTEND / "portal.html")


@needs_node
def test_the_honest_scenarios_ran(drawer):
    assert "honest" not in drawer["errors"], drawer["errors"].get("honest")


@needs_node
def test_the_button_names_what_it_will_send(drawer):
    h = drawer["honest"]
    assert '<button type="button" class="btn btn-p" id="scope-send" data-resend="">Email again: 1 new, 1 revised</button>' in h["html"]
    assert 'id="scope-send"' not in h["allSentHtml"], "a button with nothing to send"
    assert "has every scope of this project in their email" in h["allSentHtml"]


@needs_node
def test_nobody_reached_is_never_called_sent(drawer):
    h = drawer["honest"]
    for k in ("noOne", "legacyNoOne", "failed502"):
        assert h[k]["note"].startswith("Nobody got the email"), (k, h[k]["note"])
        assert "Sent to" not in h[k]["note"] and h[k]["retryShown"] is False
    assert "a@x.test, b@x.test" in h["noOne"]["note"]
    assert h["noOne"]["requests"][0]["body"] == {}


@needs_node
def test_a_partial_send_names_who_it_missed_and_retries_only_them(drawer):
    h = drawer["honest"]
    assert h["partial"]["note"].startswith("Sent to 1 contact,")
    assert "It did NOT reach: b@x.test." in h["partial"]["note"]
    assert "Not in this email (publish it first): Lab 2." in h["partial"]["note"]
    assert h["partial"]["retryShown"] is True
    assert h["retry"]["requests"] == [{"path": "/api/portal/scope-group/grp_h/send", "method": "POST",
                                       "body": {"retry_failed": True}}]
    assert h["retry"]["retryShown"] is False


@needs_node
def test_who_the_email_missed_survives_the_drawer_poll(drawer):
    """The 12s poll rebuilds the drawer, and the portal by then calls every scope emailed (one
    contact got it). The contacts it missed and the retry must still be on screen, not "the customer
    has every scope"; a retry that reaches them clears it on the next rebuild."""
    h = drawer["honest"]
    assert "It did NOT reach: b@x.test." in h["afterPoll"]["note"], h["afterPoll"]
    assert h["afterPoll"]["retryShown"] is True
    assert h["afterPoll"]["allSentShown"] is False, "the drawer said the customer has everything"
    assert "b@x.test" not in h["afterRetryPoll"]["note"]
    assert h["afterRetryPoll"]["retryShown"] is False
    assert h["afterRetryPoll"]["allSentShown"] is True


@needs_node
def test_every_refusal_is_a_sentence(drawer):
    h = drawer["honest"]
    assert h["nothing"]["note"].startswith("Nothing was sent: the customer already has every scope")
    assert "Not Found" not in h["notFound"]["note"] and "needs an update" in h["notFound"]["note"]
    assert h["notReady"]["note"] == ("Couldn't send it. The customer portal has not been updated for "
                                     "projects with several proposals yet.")
    note = h["sentMissing"]["note"]
    assert "Not published yet: Lab 2." in note
    assert "Already with the customer as its own proposal" in note and "Breakroom" in note
    assert "Publish every scope from its Files page first. Not published yet: Breakroom" not in note


@needs_node
def test_the_card_chip_follows_the_portal(board):
    assert board["errors"] == {}, board["errors"]
    s = board["scopeSend"]
    assert s["legacy"] == ["Email not sent"]
    assert s["again"] == ["Email again: 1 new, 1 revised"]
    assert s["notMine"] == [] and s["nothing"] == []
    assert s["escaped"] == ["Email &lt;b&gt;"]
