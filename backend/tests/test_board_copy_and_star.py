"""Copy a project and Star a project, from the pipeline boards (Direct and GC).

Hanz, 2026-10-29: "In the pipeline, both we should be able to copy a project. For example, we want to
copy the Multiple Proposals project but there is no way. When we copy a project, the copied project
should live under Created but not sent. Also we must have the ability to Star a project and it always
gets put up to the top of the pipeline."

  A. drafts.copy_project: the job without its send history, new ids for everything, one event, the
     kind kept; a project of several proposals copied whole into ONE new group whose children point
     at the new parent, up to date, named after their sheets; nothing shared with the original;
  B. the routes (/copy, /star), their refusals, nav_access;
  C. the board: a copy lands in "Created but not sent", the star reaches sent and unsent rows;
  D. the star is server-owned: a stale tab's whole-blob PUT neither clears nor seeds it;
  E. the board's own code, EXECUTED (tests/js/board-copy-star-harness.js): the buttons, the star on
     top of its column under every sort on both boards, the presses and what they request.

Tests marked MUTATION break the shipped code (a scratch copy, or a monkeypatched constant) and
require the assertion to notice: a test that cannot go red proves nothing.
"""
import copy

import pytest
from fastapi.testclient import TestClient

import drafts
import main
import nav_access
from _golden_support import break_source
from _node import last_json_line, run_node
from test_hand_it_off import _ProjectingClient
from test_multi_proposals import PARENT, V2, _tab

client = TestClient(main.app)

V = "2026-10-20T10:00:00+00:00"
HARNESS = __import__("pathlib").Path(__file__).resolve().parent / "js" / "board-copy-star-harness.js"
FRONTEND = __import__("pathlib").Path(__file__).resolve().parents[2] / "frontend"

# What a project carries once it has been SENT, won and handed off: every key the copy must drop.
SENT_HISTORY = {
    "generate_result": {"work_type": "epoxy", "docx_download_url": "/api/file/x"},
    "generated_lump_sum": "$20,000", "dropbox_result": {"folder_path": "/Kyle/Acme"},
    "portal_message": "Here is your revised proposal.",
    "won": {"at": "2026-10-21T10:00:00+00:00", "by": "kyle@x.test"},
    "handed_off": {"at": "2026-10-22T10:00:00+00:00", "by": "kyle@x.test"},
    "closed_lost": {"reason": "not_low_bid", "at": "2026-10-23", "by": "k", "note": "x"},
    "on_hold": {"reason": "on_hold", "note": "", "by": "k", "at": "2026-10-23", "until": ""},
    "job_number": "J-1042", "info_cell_values": {"A1": "x"}, "info_tab_structs": {"t": 1},
    "info_template_version": "abc", "archived": True,
    "starred": {"at": "2026-10-24T10:00:00+00:00", "by": "troy@x.test"},
    "split_at": "2026-10-19T00:00:00+00:00", "split_had_files": True, "split_from": "old",
    "sheet_names_at": "2026-10-19T00:00:00+00:00",
}


def _store(rows):
    return {"drafts": rows, "events": [], "draft_revisions": []}


def _draft(rid, data, created="2026-10-01T00:00:00+00:00", **kw):
    row = {"id": rid, "data": copy.deepcopy(data), "owner_email": "kyle@x.test",
           "created_at": created, "updated_at": V, "deleted_at": None}
    row.update(kw)
    return row


def _seed(fake_supabase, monkeypatch, rows):
    store = _store(rows)
    fake = fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts._cache_clear()
    return store


def _row(store, rid):
    return next(r for r in store["drafts"] if r["id"] == rid)


def _events(store, rid=None):
    return [e for e in store["events"] if rid is None or e["project_id"] == rid]


# ── A. the copy ─────────────────────────────────────────────────────────────
def test_a_single_project_is_copied_as_the_job_without_its_send_history(fake_supabase, monkeypatch):
    original = dict(PARENT, audience="GC", is_test=False, job_name="Acme HQ",
                    proposal_payload={"values": {"project_name": "Acme HQ", "x": 1}},
                    estimator_name="Kyle Loseke", portal_emails=["b@acme.test"],
                    require_deposit=False, __draft_id="p1", **SENT_HISTORY)
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", original)])
    out = drafts.copy_project("p1", "troy@x.test")

    assert out["id"] != "p1" and out["ids"] == [out["id"]] and out["group_id"] is None
    row = _row(store, out["id"])
    d = row["data"]
    assert row["owner_email"] == "troy@x.test", "the copy is owned by whoever pressed Copy"
    assert d["project_name"] == "Acme HQ (copy)" == out["project_name"]
    assert d["job_name"] == "Acme HQ (copy)"
    assert d["proposal_payload"]["values"]["project_name"] == "Acme HQ (copy)"
    # Dropped: the send history, every one of them.
    for k in drafts.COPY_DROPS:
        if k != "copied_from":
            assert k not in d, "the copy carried the original's %s" % k
    # Reset: the kind, the record of the copy, the blob's own stamp.
    assert d["is_test"] is False
    assert d["copied_from"]["id"] == "p1" and d["copied_from"]["project_name"] == "Acme HQ"
    assert d["copied_from"]["by"] == "troy@x.test"
    assert d["__draft_id"] == out["id"]
    # Kept: the customer, the intake, the estimate and the proposal's own wording.
    for k in ("audience", "assigned_estimator", "contact_name", "contact_email", "address", "bid_date",
              "cell_values", "tab_copies", "tab_labels", "tab_order", "priced_tabs", "base_tab_id",
              "proposal_lump_sum", "tab_opts", "tab_notes", "price_lines", "price_overrides",
              "paragraph_overrides", "box_overrides", "system_overrides", "scope_notes",
              "schedule_notes", "exclusions", "system_name", "texture", "cover_letter_enabled",
              "notify_picks", "estimator_name", "portal_emails", "require_deposit"):
        assert d[k] == original[k], k
    assert d["audience"] == "GC", "GC stays GC"
    assert "scope_group" not in d and "proposal_of" not in d
    # One event on the new draft, and none on the original.
    assert [(e["project_id"], e["action"]) for e in store["events"]] == [(out["id"], "copied")]
    assert store["events"][0]["detail"]["from"] == "p1"
    # The original is exactly as it was.
    assert _row(store, "p1")["data"] == original


def test_a_copy_shares_no_object_with_the_original(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", PARENT)])
    cid = drafts.copy_project("p1", "t@x")["id"]
    copy_data, orig_data = _row(store, cid)["data"], _row(store, "p1")["data"]
    copy_data["cell_values"]["Epoxy!E20"] = 1
    copy_data["priced_tabs"][0]["total"] = 1
    copy_data["tab_opts"]["Copy1"]["show"] = "changed"
    assert orig_data["cell_values"]["Epoxy!E20"] == 4000
    assert orig_data["priced_tabs"][0]["total"] == 20000
    assert orig_data["tab_opts"]["Copy1"]["show"] is True
    orig_data["paragraph_overrides"]["p"] = 99
    assert copy_data["paragraph_overrides"]["p"] == 1


def test_a_v2_project_is_copied_as_a_v2_project(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("v1", V2)])
    cid = drafts.copy_project("v1", "t@x")["id"]
    d = _row(store, cid)["data"]
    assert d["polish_estimate"] == V2["polish_estimate"]
    assert d["polish_estimate"] is not _row(store, "v1")["data"]["polish_estimate"]
    # The board opens it on the v2 pages (the routing guard reads polish_beta off the summary).
    assert drafts._summary(_row(store, cid))["polish_beta"] is True


@pytest.mark.parametrize("flag, name, want", [
    (True, "Acme HQ", True),          # a Test project's copy is Test
    (None, "QA sample bid", True),    # nobody said, and the name says Test: still Test
    (False, "Test Treadwell", False),  # a real bid with a test-looking name stays real
    (None, "Acme HQ", False),         # a real project's copy is real
])
def test_a_copy_is_the_same_kind_as_its_original(fake_supabase, monkeypatch, flag, name, want):
    data = dict(PARENT, project_name=name)
    data.pop("is_test")
    if flag is not None:
        data["is_test"] = flag
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", data)])
    d = _row(store, drafts.copy_project("p1", "t@x")["id"])["data"]
    assert d["is_test"] is want
    assert drafts.draft_is_test(d) is drafts.draft_is_test(data)


# ── a project of several proposals ──
THREE = dict(PARENT, priced_tabs=PARENT["priced_tabs"] + [_tab("Copy2", "epoxy", 7000, name="Lab 3")],
             tab_labels={"Copy1": "Room 2", "Copy2": "Lab 3"},
             tab_order=["Epoxy", "Copy1", "Copy2", "Polish", "Seal"], is_test=False,
             project_name="Multiple Proposals")


def _three(fake_supabase, monkeypatch, extra=()):
    """A Create Multiple Proposals project made the real way (fan_out_proposals): Epoxy (Base Bid 1),
    Room 2 and Lab 3, each a child pointing at p1."""
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", THREE)] + list(extra))
    drafts.fan_out_proposals("p1", ["Epoxy", "Copy1", "Copy2"], "rj@x.test")
    store["events"].clear()
    return store


def _family(store, parent):
    kids = [r for r in store["drafts"] if r["data"].get("proposal_of") == parent]
    return _row(store, parent), sorted(kids, key=lambda r: r["created_at"])


def test_a_project_of_three_proposals_is_copied_whole_into_one_new_group(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    old_parent, old_kids = _family(store, "p1")
    old_gid = old_parent["data"]["scope_group"]["id"]
    out = drafts.copy_project("p1", "troy@x.test")

    assert len(out["ids"]) == 3 and out["id"] == out["ids"][0]
    new_parent, new_kids = _family(store, out["id"])
    gid = new_parent["data"]["scope_group"]["id"]
    assert gid == out["group_id"] and gid != old_gid
    assert drafts.scope_group_problem(new_parent["data"]["scope_group"]) is None
    assert [k["id"] for k in new_kids] == out["ids"][1:]
    for k in new_kids:
        assert k["data"]["scope_group"]["id"] == gid
        assert k["data"]["proposal_of"] == out["id"], "a child points at the NEW parent"
        assert k["data"]["project_name"] == "Multiple Proposals (copy)"
        assert k["owner_email"] == "troy@x.test"
    assert "proposal_of" not in new_parent["data"]
    # The sheets, the base list and what the parent last matched, as the original has them.
    assert [k["data"]["base_tab_id"] for k in new_kids] == ["Copy1", "Copy2"]
    assert new_parent["data"]["base_tab_ids"] == old_parent["data"]["base_tab_ids"]
    # Named after their sheets (proposal_names), as #741 named the original's.
    assert [new_parent["data"]["scope_group"]["label"]] + [k["data"]["scope_group"]["label"] for k in new_kids] \
        == ["Epoxy", "Room 2", "Lab 3"]
    # The original group is untouched and still exactly three.
    assert [r["id"] for r in store["drafts"] if (r["data"].get("scope_group") or {}).get("id") == old_gid] \
        == ["p1"] + [k["id"] for k in old_kids]
    # One `copied` event per new draft, nothing else.
    assert sorted((e["project_id"], e["action"]) for e in store["events"]) \
        == sorted((i, "copied") for i in out["ids"])


def test_no_copied_proposal_says_estimate_changed(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    out = drafts.copy_project("p1", "t@x")
    view = drafts.proposals_view(out["id"])
    assert view["parent_id"] == out["id"]
    assert [m["id"] for m in view["members"]] == out["ids"]
    assert [m["stale"] for m in view["members"]] == [False, False, False]
    assert [m["display_label"] for m in view["members"]] == ["Epoxy", "Room 2", "Lab 3"]
    assert [m["out_of_step"] for m in view["members"]] == [None, None, None]
    # …and the digest is the COPY's (its name differs from the original's, so the original's digest
    # would have called every copy stale).
    assert all(_row(store, i)["data"]["estimate_digest"] == drafts.estimate_digest(_row(store, out["id"])["data"])
               for i in out["ids"][1:])
    assert drafts.estimate_digest(_row(store, out["id"])["data"]) != drafts.estimate_digest(_row(store, "p1")["data"])


def test_the_copies_are_named_after_their_sheets_even_when_the_original_was_not(fake_supabase, monkeypatch):
    """An original made before #741 still says "Base Bid 2" (or a sheet renamed since, before its next
    save renamed the proposal): the copy's board cards say the sheet names from the start."""
    store = _three(fake_supabase, monkeypatch)
    parent, kids = _family(store, "p1")
    for n, r in enumerate([parent] + kids, start=1):
        r["data"]["scope_group"] = dict(r["data"]["scope_group"], label="Base Bid %d" % n)
    out = drafts.copy_project("p1", "t@x")
    assert [_row(store, i)["data"]["scope_group"]["label"] for i in out["ids"]] == ["Epoxy", "Room 2", "Lab 3"]


def test_a_child_that_was_out_of_date_stays_out_of_date(fake_supabase, monkeypatch):
    """Its numbers still differ from its parent's; calling it fresh would hide that."""
    store = _three(fake_supabase, monkeypatch)
    _parent, kids = _family(store, "p1")
    kids[1]["data"]["estimate_digest"] = "an-old-digest"
    out = drafts.copy_project("p1", "t@x")
    assert [m["stale"] for m in drafts.proposals_view(out["id"])["members"]] == [False, False, True]


def test_pressing_copy_on_a_child_card_copies_the_whole_project(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    _parent, kids = _family(store, "p1")
    out = drafts.copy_project(kids[1]["id"], "t@x")
    assert len(out["ids"]) == 3
    new_parent = _row(store, out["ids"][0])
    assert "proposal_of" not in new_parent["data"] and new_parent["data"]["base_tab_id"] == "Epoxy"
    assert out["id"] == out["ids"][2], "the answer names the copy of the card that was pressed"
    assert _row(store, out["id"])["data"]["proposal_of"] == out["ids"][0]


def test_a_trashed_or_archived_proposal_is_not_copied(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    _parent, kids = _family(store, "p1")
    kids[0]["deleted_at"] = "2026-10-25T00:00:00+00:00"
    kids[1]["data"]["archived"] = True
    out = drafts.copy_project("p1", "t@x")
    assert len(out["ids"]) == 1
    assert _row(store, out["id"])["data"]["scope_group"]["label"] == "Epoxy"


def test_a_scope_group_with_no_proposal_of_is_copied_as_one_project(fake_supabase, monkeypatch):
    """RJ's scopes (#711): three separately priced scopes, none made from another's estimate."""
    base = {"project_name": "RJ Labs", "is_test": False, "work_type": "polish", "contact_email": "rj@c.test"}
    rows = [_draft("s%d" % i, dict(base, scope_group={"id": "grp_rj", "label": lab}),
                   created="2026-10-0%dT00:00:00+00:00" % i)
            for i, lab in enumerate(("Breakroom", "Lab 1", "Lab 2"), start=1)]
    store = _seed(fake_supabase, monkeypatch, rows)
    out = drafts.copy_project("s2", "t@x")
    copies = [_row(store, i)["data"] for i in out["ids"]]
    assert [c["scope_group"]["label"] for c in copies] == ["Breakroom", "Lab 1", "Lab 2"]
    assert {c["scope_group"]["id"] for c in copies} == {out["group_id"]} != {"grp_rj"}
    assert all("proposal_of" not in c for c in copies)
    assert [_row(store, i)["created_at"] for i in out["ids"]] == sorted(_row(store, i)["created_at"] for i in out["ids"])


def test_a_copy_that_fails_part_way_leaves_nothing_behind(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    real = drafts.get_client()
    before = [r["id"] for r in store["drafts"]]
    inserts = {"n": 0}

    class Flaky:
        def table(self, name):
            t = real.table(name)
            if name == "drafts":
                orig = t.insert

                def insert(row):
                    inserts["n"] += 1
                    if inserts["n"] == 2:
                        raise RuntimeError("postgrest down")
                    return orig(row)
                t.insert = insert
            return t
    monkeypatch.setattr(drafts, "get_client", lambda: Flaky())
    with pytest.raises(drafts.ScopeError) as ei:
        drafts.copy_project("p1", "t@x")
    assert ei.value.code == "copy_failed" and ei.value.status == 503
    assert [r["id"] for r in store["drafts"]] == before
    assert not [e for e in store["events"] if e["action"] == "copied"]


def test_MUTATION_without_the_drop_list_the_send_history_rides_along(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", dict(PARENT, **SENT_HISTORY))])
    monkeypatch.setattr(drafts, "COPY_DROPS", ())
    d = _row(store, drafts.copy_project("p1", "t@x")["id"])["data"]
    assert d.get("generate_result") and d.get("won"), "the drop list is what keeps them out"


# ── B. the routes ───────────────────────────────────────────────────────────
def test_the_copy_route(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    monkeypatch.setattr(main, "_user_email", lambda request: "troy@x.test")
    monkeypatch.setattr(main, "_portal", lambda *a, **k: pytest.fail("copy must never call the portal"))
    r = client.post("/api/draft/p1/copy")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and len(j["ids"]) == 3 and j["project_name"] == "Multiple Proposals (copy)"
    assert _row(store, j["id"])["owner_email"] == "troy@x.test"
    assert client.post("/api/draft/nope/copy").json()["code"] == "not_found"
    assert client.post("/api/draft/nope/copy").status_code == 404
    _row(store, "p1")["deleted_at"] = "2026-10-25"
    assert client.post("/api/draft/p1/copy").status_code == 404, "a trashed project is not copied"


def test_the_star_route(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", PARENT)])
    monkeypatch.setattr(main, "_user_email", lambda request: "troy@x.test")
    r = client.post("/api/draft/p1/star", json={"starred": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "starred": True}
    row = _row(store, "p1")
    assert row["data"]["starred"]["by"] == "troy@x.test" and row["data"]["starred"]["at"]
    assert row["updated_at"] == V, "a star is not work on the estimate"
    r = client.post("/api/draft/p1/star", json={"starred": False})
    assert r.json() == {"ok": True, "starred": False} and "starred" not in _row(store, "p1")["data"]
    assert [e["action"] for e in store["events"]] == ["starred", "unstarred"]
    assert client.post("/api/draft/nope/star", json={"starred": True}).status_code == 404


@pytest.mark.parametrize("method, path", [("POST", "/api/draft/p1/copy"), ("POST", "/api/draft/p1/star")])
def test_the_new_routes_are_signed_in_and_open_to_whoever_can_see_the_board(method, path):
    assert not main._auth_is_public(path, method)
    everything = {"deny": {role: list(nav_access.TABS) for role in nav_access.ROLES}}
    for role in nav_access.ROLES:
        assert not nav_access.is_api_denied(role, path, everything), role
    routes = {(m, r.path) for r in main.app.routes for m in (getattr(r, "methods", None) or ())}
    assert (method, path.replace("p1", "{draft_id}")) in routes


# ── C. the board ────────────────────────────────────────────────────────────
def _board(monkeypatch, store, portal_rows):
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    drafts._cache_clear()
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": portal_rows})
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return {p["proposal_id"]: p for p in r.json()["proposals"]}


def test_a_copy_of_a_sent_and_won_project_lands_in_created_but_not_sent(fake_supabase, monkeypatch):
    original = dict(PARENT, is_test=False, **{k: v for k, v in SENT_HISTORY.items()
                                              if k not in ("archived", "closed_lost", "on_hold", "handed_off")})
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", original)])
    store["draft_revisions"].append({"draft_id": "p1", "revision_no": 2, "data": {}})
    out = drafts.copy_project("p1", "t@x")
    assert not [r for r in store["draft_revisions"] if r["draft_id"] == out["id"]]
    sent = {"proposal_id": "p1", "project_name": "Acme HQ", "proposal_status": "approved",
            "sent_at": "2026-10-10", "approved_at": "2026-10-12"}
    rows = _board(monkeypatch, store, [sent])
    card = rows[out["id"]]
    assert card["not_sent"] is True and card["files_pending"] is True
    assert "proposal_status" not in card and card["won_at"] is None and card["handed_off_at"] is None
    assert card["project_name"] == "Acme HQ (copy)" and card["is_test"] is False
    assert card["pipeline"] == "direct"
    assert rows["p1"]["won_at"], "the original keeps its own mark"


def test_every_proposal_of_a_copied_project_is_on_the_board(fake_supabase, monkeypatch):
    store = _three(fake_supabase, monkeypatch)
    out = drafts.copy_project("p1", "t@x")
    rows = _board(monkeypatch, store, [])
    assert all(rows[i]["not_sent"] and rows[i]["files_pending"] for i in out["ids"])
    assert [rows[i]["scope_index"] for i in out["ids"]] == [1, 2, 3]
    assert {rows[i]["scope_count"] for i in out["ids"]} == {3}
    # The copies are a project of their own: the original's cards still count three, not six.
    assert rows["p1"]["scope_count"] == 3 and rows["p1"]["scope_group"] != rows[out["id"]]["scope_group"]


def test_MUTATION_without_the_copy_check_a_copy_never_reaches_the_board():
    s = {"id": "c1", "project_name": "X (copy)", "has_files": False, "updated_at": V, "total": None,
         "copied_from": "p1"}
    assert main._not_sent_rows([s], [])[0]["files_pending"] is True
    assert main._not_sent_rows([dict(s, copied_from=None)], []) == []


def test_the_star_reaches_sent_and_unsent_cards_and_leaves_with_the_star(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [
        _draft("ns", dict(PARENT, is_test=False, starred={"at": "2026-10-28T00:00:00+00:00", "by": "k"})),
        _draft("s1", dict(PARENT, is_test=False, audience="GC", starred={"at": "2026-10-27T00:00:00+00:00", "by": "k"})),
        _draft("s2", dict(PARENT, is_test=False))])
    sent = [{"proposal_id": "s1", "proposal_status": "sent"},
            {"proposal_id": "s2", "proposal_status": "sent", "starred_at": "left over from a cached read"}]
    rows = _board(monkeypatch, store, sent)
    assert rows["ns"]["starred_at"] == "2026-10-28T00:00:00+00:00"
    assert rows["s1"]["starred_at"] == "2026-10-27T00:00:00+00:00" and rows["s1"]["pipeline"] == "gc"
    assert rows["s2"]["starred_at"] is None, "a star taken off is off, even on a cached row"


def test_both_summary_paths_carry_the_star_and_the_copy(monkeypatch):
    data = {"project_name": "X", "starred": {"at": "2026-10-28", "by": "k"}, "copied_from": {"id": "p1"}}
    slow = drafts._summary({"id": "d1", "data": data})
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(
        {"drafts": [{"id": "d1", "data": data, "owner_email": "k", "deleted_at": None,
                     "created_at": "2026-10-01", "updated_at": V}]}))
    fast = drafts._build_summaries(trashed=False, limit=10)[0]
    for s in (slow, fast):
        assert (s["starred_at"], s["copied_from"]) == ("2026-10-28", "p1")
    blank = drafts._summary({"id": "d1", "data": {"starred": {}, "copied_from": {}}})
    assert (blank["starred_at"], blank["copied_from"]) == (None, None)


# ── D. the star is server-owned ─────────────────────────────────────────────
def test_a_stale_tab_neither_clears_nor_seeds_the_star(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", PARENT)])
    stale = copy.deepcopy(_row(store, "p1")["data"])        # read before anybody starred it
    assert client.post("/api/draft/p1/star", json={"starred": True}).status_code == 200
    held = _row(store, "p1")["data"]["starred"]
    r = client.put("/api/draft/p1", json={"data": dict(stale, scope_notes="typed later")})
    assert r.status_code == 200, r.text
    assert _row(store, "p1")["data"]["starred"] == held, "the stale tab's save took the star off"
    assert _row(store, "p1")["data"]["scope_notes"] == "typed later"
    # …and the other way round: a tab that still holds the star cannot put it back once it is off.
    holding = copy.deepcopy(_row(store, "p1")["data"])
    client.post("/api/draft/p1/star", json={"starred": False})
    client.put("/api/draft/p1", json={"data": holding})
    assert "starred" not in _row(store, "p1")["data"]
    # A browser cannot seed one on a new draft either (the beta sandbox PUTs copies under new ids).
    client.put("/api/draft/fresh", json={"data": {"project_name": "Sandbox", "starred": held,
                                                  "copied_from": {"id": "p1"}}})
    assert "starred" not in _row(store, "fresh")["data"] and "copied_from" not in _row(store, "fresh")["data"]


def test_a_browser_save_of_a_copy_keeps_it_a_copy(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", PARENT)])
    cid = drafts.copy_project("p1", "t@x")["id"]
    blob = copy.deepcopy(_row(store, cid)["data"])
    blob.pop("copied_from")
    assert client.put("/api/draft/%s" % cid, json={"data": blob}).status_code == 200
    assert _row(store, cid)["data"]["copied_from"]["id"] == "p1"


def test_MUTATION_the_server_owned_list_is_what_keeps_the_star(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, [_draft("p1", PARENT)])
    stale = copy.deepcopy(_row(store, "p1")["data"])
    drafts.set_starred("p1", True, "k")
    monkeypatch.setattr(drafts, "_SERVER_OWNED_KEYS",
                        tuple(k for k in drafts._SERVER_OWNED_KEYS if k != "starred"))
    drafts.save_draft("p1", stale, keep_server_owned=True)
    assert "starred" not in _row(store, "p1")["data"], "without the entry, a stale save clears it"


# ── E. the board's own code, executed ───────────────────────────────────────
@pytest.fixture(scope="module")
def ran():
    return _run(FRONTEND)


def _run(frontend):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    out = last_json_line(proc.stdout)
    assert not out.get("error") and not out.get("errors"), out
    return out


def _star_on_top(order):
    """Per column: the starred cards first, each half in the order the sort gives without stars."""
    bad = []
    for col, plain in order["without"].items():
        want = [i for i in plain if i in order["starred"]] + [i for i in plain if i not in order["starred"]]
        if order["withStars"][col] != want:
            bad.append((order["pipeline"], order["field"], order["dir"], col, order["withStars"][col], want))
    return bad


def test_a_starred_card_is_on_top_of_its_column_under_every_sort_on_both_boards(ran):
    orders = ran["orders"]
    assert {(o["pipeline"], o["field"], o["dir"]) for o in orders} == {
        (p, f, d) for p in ("direct", "gc") for f in ("stage", "activity", "estimator", "total")
        for d in ("asc", "desc")}
    assert [b for o in orders for b in _star_on_top(o)] == []
    # Not vacuous: the stars are the WORST cards by every sort, so for every board and every sort
    # field one direction would sink them without the rule, in both columns.
    for o in orders:
        for col in ("Created but not sent", "Sent"):
            assert o["withStars"][col][0] in o["starred"], (o["pipeline"], o["field"], o["dir"], col)
    for p in ("direct", "gc"):
        for f in ("stage", "activity", "estimator", "total"):
            for col in ("Created but not sent", "Sent"):
                assert any(o["without"][col][0] not in o["starred"] for o in orders
                           if (o["pipeline"], o["field"]) == (p, f)), (p, f, col)
    # The Direct board never shows a GC card and the reverse.
    for o in orders:
        ids = [i for col in o["withStars"].values() for i in col]
        assert all(i.startswith("g-") for i in ids) if o["pipeline"] == "gc" else \
            all(not i.startswith("g-") for i in ids)


def test_MUTATION_without_the_star_rule_the_stars_sink(tmp_path):
    broken = break_source(tmp_path, "js/crm-core.js", "if (sx !== sy) return sx ? -1 : 1;",
                          "if (false) return 0;", also=("js/portal.js",))
    assert [b for o in _run(broken)["orders"] for b in _star_on_top(o)]


def test_every_card_carries_copy_and_a_star_that_says_whether_it_is_on(ran):
    cards = ran["cards"]
    assert cards and all(c["copy"] and c["star"] and c["starIcon"] and c["copyIcon"] for c in cards.values())
    assert {i for i, c in cards.items() if c["pressed"]} == {"d-c3", "d-c4", "d-s2"}
    assert {i for i, c in cards.items() if c["on"]} == {"d-c3", "d-c4", "d-s2"}
    # The table marks a starred row, and lists the stars first.
    marks = ran["tableStars"]
    assert {i for i, on in marks if on} == {"d-c3", "d-c4", "d-s2"}
    assert [on for _i, on in marks] == sorted((on for _i, on in marks), reverse=True)
    # A lost card offers no outcome, but can still be copied or starred.
    assert ran["lostCard"] == {"copy": True, "star": True, "won": False}


def test_pressing_the_star_posts_it_and_moves_the_card_without_opening_the_drawer(ran):
    on, off = ran["starOn"], ran["starOff"]
    assert on["requests"] == [{"path": "/api/draft/d-c1/star", "method": "POST", "body": {"starred": True}}]
    assert off["requests"] == [{"path": "/api/draft/d-c3/star", "method": "POST", "body": {"starred": False}}]
    assert ran["starOnRow"] and ran["starOffRow"] is None
    for p in (on, off):
        assert p["openedDrawer"] == [] and p["rendered"] == 1 and p["reloaded"] == 1 and p["prompts"] == []


def test_a_star_that_did_not_save_leaves_the_card_as_it_was(ran):
    f = ran["starFailed"]
    assert ran["starFailedRow"] is None
    assert f["disabled"] is False and "not saved" in f["title"] and f["rendered"] == 0


def test_copy_asks_first_then_posts_and_opens_the_copy(ran):
    assert ran["copyRefused"]["requests"] == [] and ran["copyRefused"]["prompts"][0]["title"] == "Copy this project?"
    done = ran["copyDone"]
    assert done["requests"] == [{"path": "/api/draft/d-c2/copy", "method": "POST", "body": None}]
    assert "Proj d-c2 (copy)" in done["prompts"][0]["message"]
    assert "Created but not sent" in done["prompts"][0]["message"]
    assert done["reloaded"] == 1 and done["openedDrawer"] == ["new-copy"]
    assert ran["copyLanded"]["not_sent"] is True


def test_copy_on_a_card_of_several_proposals_says_it_copies_all_of_them(ran):
    many = ran["copyMany"]
    assert "with all 3 of its proposals" in many["prompts"][0]["message"]
    assert many["requests"][0]["path"] == "/api/draft/m-1/copy"
    assert many["openedDrawer"] == [], "the drawer is opened only on a card the board has"


def test_a_copy_that_failed_says_so_and_opens_nothing(ran):
    f = ran["copyFailed"]
    assert [p["title"] for p in f["prompts"]] == ["Copy this project?", "Nothing was copied"]
    assert f["openedDrawer"] == [] and f["disabled"] is False


def test_MUTATION_a_star_press_that_reaches_the_row_branch_opens_the_drawer(tmp_path):
    broken = break_source(tmp_path, "js/portal.js", "if (star) { toggleCardStar(star); return; }",
                          "if (false) { toggleCardStar(star); return; }", also=("js/crm-core.js",))
    out = _run(broken)
    assert out["starOn"]["requests"] == [] and out["starOn"]["openedDrawer"] == ["d-c1"]


def test_MUTATION_a_lookup_that_cannot_read_the_star_or_copy_id_does_nothing(tmp_path):
    broken = break_source(tmp_path, "js/portal.js", "|| btn.dataset.star || btn.dataset.copy || \"\";",
                          "|| \"\";", also=("js/crm-core.js",))
    out = _run(broken)
    assert out["starOn"]["requests"] == [] and out["copyDone"]["requests"] == []
