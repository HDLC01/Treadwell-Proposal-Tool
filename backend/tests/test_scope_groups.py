"""Scope groups, the store and the routes: one project, several separately approved proposals.

RJ, 2026-10-24: a client gets a few separately priced scopes (Breakroom polish, Lab 1 epoxy, Lab 2
epoxy) under one project name and address, each its OWN proposal the customer approves on its own,
and ONE combined email with every link. The portal side (treadwell-portal, feat/scope-groups) reads
`data.scope_group = {"id", "label"}` out of each draft; this file holds the tool's side to it:

  A. drafts.create_sibling (tier A0): the new scope copies the intake ALLOW-LIST and nothing about
     what is priced or proposed, shares the group id, inherits is_test as it stands;
  B. POST /api/draft/{id}/scope: new and rename, the publish's stale-copy 409, the refusals;
  C. scope_group is server-owned: a stale tab's save can neither clear nor overwrite it;
  D. the publish refuses a malformed group locally, before anything is minted;
  E. the board: the summaries carry the group on BOTH read paths, every card says its place, and a
     scope with no files yet is drawn beside its siblings as "files not built" (never hidden);
  F. POST /api/draft/{id}/split (tier A1): the parent is rewritten as its first scope with every
     piece of multi-sheet proposal state gone, the others are minted, a published project is
     refused, and a save of the pre-split copy (a pending autosave, a second tab) is REFUSED so the
     split survives it.
"""
import copy

from fastapi.testclient import TestClient

import drafts
import main
from test_hand_it_off import _ProjectingClient

client = TestClient(main.app)

GID = "grp_0123456789abcdef"

PARENT = {
    # the intake allow-list
    "project_name": "Acme HQ", "audience": "GC", "is_test": True, "assigned_estimator": "kyle@x.test",
    "bid_date": "2026-11-02", "deadline": "2026-11-02", "address": "1 Main St", "city": "Olathe",
    "state": "KS", "zip": "66061", "city_state": "Olathe, KS", "county": "Johnson County, KS",
    "county_tax_rate": 0.0948, "county_remodel_rate": 0.0948, "county_notes": "n",
    "contact_name": "Pat", "contact_email": "pat@acme.test", "contact_phone": "555",
    "architect": "Arc", "spec_section": "033543",
    # the job's conditions as cells, plus a floor-only one (Dye) that must NOT travel
    "cell_values": {"Epoxy!B4": "No", "Polish!B4": "No", "Epoxy!B6": "Yes", "Epoxy!D6": "No",
                    "Polish!E25": "Yes", "Epoxy!E20": 4000},
    "polish_estimate": {"version": 2, "distance": {"miles": 190, "source": "google", "key": "k"},
                        "prevailing": {"rate": 48}, "conditions": {"local": False, "dye": True},
                        "labor": [{"id": "polishing", "guys": 3, "days": 5}],
                        "travel": {"lodging": {"enabled": True, "qty_auto": False, "qty": 10}},
                        "takeoff": [{"assembly_id": "a1", "measurement": 1000}],
                        "tabs": {"Epoxy": {"kind": "option", "label": "Lab 1"}}},
    "work_type": "polish",
    # everything a sibling must NOT carry
    "proposal_payload": {"values": {"x": 1}}, "generate_result": {"work_type": "polish"},
    "rooms": [{"name": "r"}], "priced_tabs": [{"id": "Polish"}], "tab_opts": {"Epoxy": {}},
    "computed_bid": {"lump_sum": 1}, "dropbox_result": {"folder_path": "/x"},
    "notify_picks": {"add": ["a@x.test"], "mute": []}, "paragraph_overrides": {"p": 1},
    "box_overrides": {"b": 1}, "system_overrides": {"s": 1}, "price_overrides": {"lines": {}},
    "cover_letter_enabled": True, "system_name": "Polished", "texture": "T", "scope_notes": "S",
    "exclusions": "E", "proposal_lump_sum": 41500,
}

NEVER_COPIED = ["proposal_payload", "generate_result", "rooms", "priced_tabs", "tab_opts",
                "computed_bid", "dropbox_result", "notify_picks", "paragraph_overrides",
                "box_overrides", "system_overrides", "price_overrides", "cover_letter_enabled",
                "system_name", "texture", "scope_notes", "exclusions", "proposal_lump_sum",
                "work_type"]


def _seed(fake_supabase, monkeypatch, data=None, rid="p1", updated="2026-10-20T10:00:00+00:00",
          extra=()):
    store = {"drafts": [{"id": rid, "data": copy.deepcopy(data if data is not None else PARENT),
                         "owner_email": "kyle@x.test", "created_at": "2026-10-01",
                         "updated_at": updated, "deleted_at": None}] + list(extra),
             "events": [], "draft_revisions": []}
    fake = fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    return store


def _row(store, rid):
    return next(r for r in store["drafts"] if r["id"] == rid)


# ── A. the new scope ────────────────────────────────────────────────────────
def test_a_new_scope_copies_exactly_the_intake_allow_list(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = drafts.create_sibling("p1", "Lab 2", "rj@x.test")
    child = _row(store, out["id"])["data"]
    for k in drafts.SIBLING_INTAKE_KEYS:
        assert child.get(k) == PARENT.get(k), k
    assert set(child) - {"cell_values", "polish_estimate", "scope_group"} == \
        {k for k in drafts.SIBLING_INTAKE_KEYS if k in PARENT}
    for k in NEVER_COPIED:
        assert k not in child, "a new scope carried %s from the project it is a scope of" % k
    # the job's conditions, and not one floor's
    assert child["cell_values"] == {"Epoxy!B4": "No", "Polish!B4": "No", "Epoxy!B6": "Yes",
                                    "Epoxy!D6": "No"}
    # a v2 model that states no labor: the estimate page opens it as a new bid, at the job's distance
    assert child["polish_estimate"] == {"version": 2, "distance": PARENT["polish_estimate"]["distance"],
                                        "prevailing": {"rate": 48}}
    assert _row(store, out["id"])["owner_email"] == "rj@x.test"


def test_a_new_scope_does_not_share_objects_with_its_parent(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = drafts.create_sibling("p1", "Lab 2")
    child = _row(store, out["id"])["data"]
    child["polish_estimate"]["distance"]["miles"] = 1
    assert _row(store, "p1")["data"]["polish_estimate"]["distance"]["miles"] == 190


def test_both_share_one_group_and_the_parent_is_named(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = drafts.create_sibling("p1", "Lab 2")
    parent = _row(store, "p1")["data"]
    child = _row(store, out["id"])["data"]
    assert parent["scope_group"]["id"] == child["scope_group"]["id"] == out["group_id"]
    assert drafts.SCOPE_ID_RE.match(out["group_id"])
    assert child["scope_group"]["label"] == "Lab 2"
    # nobody named the first scope: its base sheet's name on the estimate (the root, Polish)
    assert parent["scope_group"]["label"] == out["parent_label"] == "Polish"
    assert drafts.scope_group_problem(parent["scope_group"]) is None
    assert drafts.scope_group_problem(child["scope_group"]) is None


def test_the_parent_keeps_its_place_in_the_projects_list(fake_supabase, monkeypatch):
    """Naming a project's scopes is not work on its estimate."""
    store = _seed(fake_supabase, monkeypatch)
    drafts.create_sibling("p1", "Lab 2")
    assert _row(store, "p1")["updated_at"] == "2026-10-20T10:00:00+00:00"


def test_is_test_is_inherited_as_it_stands(fake_supabase, monkeypatch):
    for said in (True, False):
        data = dict(PARENT, is_test=said)
        store = _seed(fake_supabase, monkeypatch, data)
        out = drafts.create_sibling("p1", "Lab 2")
        assert _row(store, out["id"])["data"]["is_test"] is said
    data = {k: v for k, v in PARENT.items() if k != "is_test"}
    store = _seed(fake_supabase, monkeypatch, data)
    out = drafts.create_sibling("p1", "Lab 2")
    assert "is_test" not in _row(store, out["id"])["data"], (
        "a parent nobody filed gave a child somebody filed")


def test_a_third_scope_joins_the_same_group(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    a = drafts.create_sibling("p1", "Lab 1")
    b = drafts.create_sibling(a["id"], "Lab 2")
    assert a["group_id"] == b["group_id"]
    assert len([r for r in store["drafts"]
                if (r["data"].get("scope_group") or {}).get("id") == a["group_id"]]) == 3


def test_a_name_two_scopes_would_share_is_refused(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    drafts.create_sibling("p1", "Lab 1")
    for clash in ("lab 1", "Polish", "  LAB   1 "):
        try:
            drafts.create_sibling("p1", clash)
        except drafts.ScopeError as exc:
            assert exc.code == "label_taken" and exc.status == 409
        else:
            raise AssertionError("%r was accepted twice in one project" % clash)


def test_a_blank_or_long_name_is_refused_not_cut(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    for bad in ("", "   ", "x" * 81):
        try:
            drafts.create_sibling("p1", bad)
        except drafts.ScopeError as exc:
            assert exc.code == "invalid_label"
        else:
            raise AssertionError("%r was accepted" % bad)
    assert drafts.clean_scope_label("  Lab\t1\n") == "Lab 1"
    assert len(drafts.clean_scope_label("x" * 80)) == 80


# ── B. the route ────────────────────────────────────────────────────────────
def test_the_route_mints_the_scope_and_answers_its_id(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    r = client.post("/api/draft/p1/scope", json={"label": "Lab 1",
                                                 "draft_version": "2026-10-20T10:00:00+00:00"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["label"] == "Lab 1" and j["parent_label"] == "Polish"
    assert _row(store, j["id"])["data"]["scope_group"]["id"] == j["group_id"]


def test_a_stale_draft_version_gets_409_and_mints_nothing(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    r = client.post("/api/draft/p1/scope", json={"label": "Lab 1",
                                                 "draft_version": "2026-10-19T09:00:00+00:00"})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "document_changed" and r.json()["error"]
    assert len(store["drafts"]) == 1
    assert "scope_group" not in _row(store, "p1")["data"]


def test_the_route_renames_a_scope(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    j = client.post("/api/draft/p1/scope", json={"label": "Lab 1"}).json()
    r = client.post("/api/draft/p1/scope", json={"label": "Breakroom", "rename": True})
    assert r.status_code == 200, r.text
    assert _row(store, "p1")["data"]["scope_group"] == {"id": j["group_id"], "label": "Breakroom"}
    clash = client.post("/api/draft/p1/scope", json={"label": "Lab 1", "rename": True})
    assert clash.status_code == 409 and clash.json()["code"] == "label_taken"


def test_renaming_a_project_that_has_no_scopes_says_so(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    r = client.post("/api/draft/p1/scope", json={"label": "Breakroom", "rename": True})
    assert r.status_code == 400 and r.json()["code"] == "not_grouped"


def test_an_unknown_project_is_404(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    r = client.post("/api/draft/nope/scope", json={"label": "Lab 1"})
    assert r.status_code == 404 and r.json()["code"] == "not_found"


# ── C. server-owned ─────────────────────────────────────────────────────────
def test_a_stale_tab_can_neither_clear_nor_overwrite_the_group(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    j = client.post("/api/draft/p1/scope", json={"label": "Lab 1"}).json()
    held = _row(store, "p1")["data"]["scope_group"]
    stale = {k: v for k, v in PARENT.items()}            # read before the scope existed
    assert client.put("/api/draft/p1", json={"data": stale}).json()["ok"] is True
    assert _row(store, "p1")["data"]["scope_group"] == held
    forged = dict(PARENT, scope_group={"id": "other", "label": "Hijack"})
    client.put("/api/draft/p1", json={"data": forged})
    assert _row(store, "p1")["data"]["scope_group"] == held
    assert held["id"] == j["group_id"]


def test_a_browser_save_never_puts_a_project_into_a_group(fake_supabase, monkeypatch):
    """The beta's sandbox PUTs a copy of a real bid under a NEW id. A copy that carried the real bid's
    group would join the customer's project and hold its combined email back. Neither a new row nor an
    ungrouped one takes a group from a browser's blob."""
    store = _seed(fake_supabase, monkeypatch)
    forged = dict(PARENT, scope_group={"id": GID, "label": "Copied along"})
    assert client.put("/api/draft/p1", json={"data": forged}).json()["ok"] is True
    assert "scope_group" not in _row(store, "p1")["data"]
    assert client.put("/api/draft/new-copy", json={"data": forged}).json()["ok"] is True
    assert "scope_group" not in _row(store, "new-copy")["data"]


def test_the_browser_mirror_lists_the_same_keys():
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "shared.js").read_text(encoding="utf-8")
    m = re.search(r"const SERVER_OWNED_KEYS = \[([^\]]*)\]", src)
    keys = [k.strip().strip("\"'") for k in m.group(1).split(",") if k.strip()]
    assert set(keys) == set(drafts._SERVER_OWNED_KEYS)


# ── D. the publish ──────────────────────────────────────────────────────────
def test_a_malformed_group_is_refused_before_the_portal_and_before_a_revision(fake_supabase, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_portal", lambda *a, **k: calls.append(a) or {"ok": True})
    for bad in ({"id": "has a space", "label": "x"}, {"id": "a" * 65}, "grp", {"id": GID, "label": 7},
                {"id": GID, "label": "x" * 81}):
        store = _seed(fake_supabase, monkeypatch, dict(PARENT, scope_group=bad))
        r = client.post("/api/portal/publish?draft_id=p1", json={"assigned_estimator": "kyle@x.test"})
        assert r.status_code == 400, (bad, r.text)
        assert r.json()["code"] == "invalid_scope_group" and "Not sent" in r.json()["error"]
        assert store["draft_revisions"] == [], "a refused publish minted a revision"
    assert calls == [], "the portal was called for a group it would have refused"


def test_a_well_formed_group_is_not_refused_here():
    assert drafts.scope_group_problem({"id": GID, "label": "Lab 1"}) is None
    assert drafts.scope_group_problem({"id": GID}) is None
    assert drafts.scope_group_problem(None) is None


# ── E. the board ────────────────────────────────────────────────────────────
def test_both_summary_paths_carry_the_group():
    s = drafts._summary({"id": "d1", "data": {"scope_group": {"id": GID, "label": "Lab 1"}}})
    assert (s["scope_group_id"], s["scope_label"]) == (GID, "Lab 1")
    s = drafts._summary({"id": "d1", "data": {"scope_group": {"id": "bad id"}}})
    assert (s["scope_group_id"], s["scope_label"]) == (None, None)


def test_the_fast_projection_carries_the_group(monkeypatch):
    store = {"drafts": [{"id": "d1", "owner_email": "k@x.com", "deleted_at": None,
                         "created_at": "2026-08-01", "updated_at": "2026-08-02",
                         "data": {"project_name": "Acme HQ",
                                  "scope_group": {"id": GID, "label": "Lab 1"}}}]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    got = drafts._build_summaries(trashed=False, limit=10)[0]
    assert (got["scope_group_id"], got["scope_label"]) == (GID, "Lab 1")


def _summ(i, label, **kw):
    s = {"id": "s%d" % i, "project_name": "Acme HQ", "has_files": False, "scope_group_id": GID,
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


def test_every_card_says_its_place_in_the_project(monkeypatch):
    summaries = [_summ(2, "Lab 1", has_files=True), _summ(1, "Breakroom", has_files=True),
                 _summ(3, "Lab 2", has_files=True)]
    rows = _board(monkeypatch, [], summaries)
    assert [(rows[i]["scope_index"], rows[i]["scope_count"], rows[i]["scope_label"])
            for i in ("s1", "s2", "s3")] == [(1, 3, "Breakroom"), (2, 3, "Lab 1"), (3, 3, "Lab 2")]
    assert [m["id"] for m in rows["s2"]["scope_members"]] == ["s1", "s2", "s3"]
    assert all(m["on_board"] for m in rows["s2"]["scope_members"])


def test_a_scope_without_files_is_drawn_beside_its_siblings_as_pending(monkeypatch):
    """A freshly split scope has no files (the split cleared the combined ones). It must neither
    vanish from the board nor claim paperwork exists."""
    summaries = [_summ(1, "Breakroom", has_files=True), _summ(2, "Lab 1")]
    rows = _board(monkeypatch, [], summaries)
    assert rows["s2"]["not_sent"] is True and rows["s2"]["files_pending"] is True
    assert rows["s2"]["bid_total"] is None
    assert "files_pending" not in rows["s1"]


def test_a_group_none_of_whose_scopes_reached_the_board_stays_off_it(monkeypatch):
    rows = _board(monkeypatch, [], [_summ(1, "Breakroom"), _summ(2, "Lab 1")])
    assert rows == {}


def test_a_sent_scope_counts_as_on_the_board(monkeypatch):
    portal = [{"proposal_id": "s1", "project_name": "Acme HQ", "proposal_status": "sent",
               "scope_group": GID, "scope_label": "Breakroom", "scope_send_pending": True}]
    rows = _board(monkeypatch, portal, [_summ(1, "Breakroom"), _summ(2, "Lab 1")])
    assert rows["s2"]["files_pending"] is True
    assert rows["s1"]["scope_send_pending"] is True and rows["s1"]["scope_count"] == 2


def test_the_draft_decides_membership_over_a_stale_portal_row(monkeypatch):
    portal = [{"proposal_id": "s1", "project_name": "Acme HQ", "proposal_status": "sent",
               "scope_group": GID, "scope_label": "Breakroom", "scope_send_pending": True}]
    rows = _board(monkeypatch, portal, [_summ(1, None, scope_group_id=None)])
    assert rows["s1"]["scope_group"] is None and rows["s1"]["scope_send_pending"] is False


def test_an_ungrouped_project_gains_no_key(monkeypatch):
    rows = _board(monkeypatch, [], [{"id": "d1", "project_name": "Solo", "has_files": True,
                                     "updated_at": "2026-10-10"}])
    assert not any(k.startswith("scope_") for k in rows["d1"]), rows["d1"]


# ── F. the split ────────────────────────────────────────────────────────────
V = "2026-10-20T10:00:00+00:00"


def _child(tab, work_type, label, **extra):
    pe = {"version": 2, "label": label, "takeoff": [{"assembly_id": tab}], "labor": []}
    data = {"polish_estimate": pe, "work_type": work_type, "base_tab_id": tab,
            "computed_bid": {"lump_sum": 1000}, "proposal_lump_sum": 1000}
    data.update(extra)
    return {"tab_id": tab, "label": label, "data": data}


SPLIT = {"draft_version": V, "children": [_child("Polish", "polish", "Breakroom"),
                                          _child("Epoxy", "epoxy", "Lab 1"),
                                          _child("Copy1", "epoxy", "Lab 2")]}


def _split(monkeypatch, body=None):
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    return client.post("/api/draft/p1/split", json=body or SPLIT)


def _no_portal_row(*a, **k):
    raise main.HTTPException(404, "not_found")


def test_a_split_rewrites_the_parent_and_mints_the_others(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    r = _split(monkeypatch)
    assert r.status_code == 200, r.text
    j = r.json()
    assert [c["label"] for c in j["children"]] == ["Lab 1", "Lab 2"]
    assert [c["tab_id"] for c in j["children"]] == ["Epoxy", "Copy1"]
    parent = _row(store, "p1")
    assert parent["data"]["work_type"] == "polish" and parent["data"]["base_tab_id"] == "Polish"
    assert parent["data"]["scope_group"] == {"id": j["group_id"], "label": "Breakroom"}
    assert parent["updated_at"] != V, "a split is an edit: every page that checked the old copy must be told"
    assert j["parent"]["data"] == parent["data"] and j["parent"]["updated_at"] == parent["updated_at"]
    for c, wt, tab in zip(j["children"], ("epoxy", "epoxy"), ("Epoxy", "Copy1")):
        d = _row(store, c["id"])["data"]
        assert d["work_type"] == wt and d["base_tab_id"] == tab
        assert d["scope_group"] == {"id": j["group_id"], "label": c["label"]}
        assert d["polish_estimate"]["takeoff"] == [{"assembly_id": tab}]


def test_the_split_clears_every_piece_of_multi_sheet_proposal_state(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, dict(PARENT, tab_notes={"Epoxy": "n"},
                                                   price_lines=[1], proposal_sales_tax=9,
                                                   proposal_remodel_tax=3, lump_sum_display="x"))
    j = _split(monkeypatch, {"draft_version": V, "children": [
        {"tab_id": "Polish", "label": "Breakroom",
         "data": {"polish_estimate": {"version": 2}, "work_type": "polish", "base_tab_id": "Polish"}},
        _child("Epoxy", "epoxy", "Lab 1")]}).json()
    parent = _row(store, "p1")["data"]
    for k in drafts.SPLIT_CLEARS:
        if k == "base_tab_id":
            continue
        assert k not in parent, "%s survived the split on the parent" % k
    child = _row(store, j["children"][0]["id"])["data"]
    for k in NEVER_COPIED:
        if k in ("work_type", "computed_bid", "proposal_lump_sum"):
            continue                       # the scope's own, from the page's save of it
        assert k not in child, "%s reached a scope minted by the split" % k
    # the project's identity survives on every scope
    for d in (parent, child):
        assert d["is_test"] is True and d["project_name"] == "Acme HQ"
        assert d["contact_email"] == "pat@acme.test"
        assert d["scope_group"]["id"] == j["group_id"]
    # ...and so does what only the parent was ever told (its recipients, its letter). Its narrative
    # does NOT: it was written for the whole job, and would print Lab 1 and Lab 2 on a Breakroom-only
    # proposal (finding 39, test_scope_group_hardening.py).
    assert parent["notify_picks"] == PARENT["notify_picks"]
    assert parent["cover_letter_enabled"] is True
    for k in ("scope_notes", "exclusions", "system_name", "texture", "dropbox_result"):
        assert k not in parent, "%s of the combined bid survived the split" % k


def test_a_freshly_split_scope_shows_as_files_pending_not_missing(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    j = _split(monkeypatch).json()
    ids = ["p1"] + [c["id"] for c in j["children"]]
    summaries = [drafts._summary(dict(_row(store, i), data=_row(store, i)["data"])) for i in ids]
    for s in summaries:
        assert s["has_files"] is False and s["scope_group_id"] == j["group_id"]
    # once one of them is on the board, all three are, as "files not built yet"
    summaries[0]["has_files"] = True
    rows = _board(monkeypatch, [], summaries)
    assert set(rows) == set(ids)
    assert rows[ids[1]]["files_pending"] is True and rows[ids[2]]["files_pending"] is True


def test_a_split_of_a_sent_proposal_is_refused(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    store["draft_revisions"].append({"project_id": "p1", "revision_no": 1})
    monkeypatch.setattr(drafts, "latest_revision_no", lambda d: 1)
    r = client.post("/api/draft/p1/split", json=SPLIT)
    assert r.status_code == 409 and r.json()["code"] == "already_sent"
    assert len(store["drafts"]) == 1 and "scope_group" not in _row(store, "p1")["data"]


def test_a_portal_row_without_a_revision_still_refuses(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    monkeypatch.setattr(main, "_portal", lambda *a, **k: {"proposal_id": "p1"})
    r = client.post("/api/draft/p1/split", json=SPLIT)
    assert r.status_code == 409 and r.json()["code"] == "already_sent"
    assert len(store["drafts"]) == 1


def test_a_portal_that_cannot_answer_refuses_rather_than_guesses(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)

    def down(*a, **k):
        raise main.HTTPException(502, "Could not reach the customer portal.")
    monkeypatch.setattr(main, "_portal", down)
    r = client.post("/api/draft/p1/split", json=SPLIT)
    assert r.status_code == 502 and r.json()["code"] == "portal_unreachable"
    assert len(store["drafts"]) == 1


def test_a_stale_split_is_refused(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    r = _split(monkeypatch, dict(SPLIT, draft_version="2026-10-19T00:00:00+00:00"))
    assert r.status_code == 409 and r.json()["code"] == "document_changed"
    assert len(store["drafts"]) == 1
    r = _split(monkeypatch, dict(SPLIT, draft_version=""))
    assert r.status_code == 400 and r.json()["code"] == "draft_version_required"


def test_a_split_needs_two_well_formed_sheets_with_their_own_names(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    one = _split(monkeypatch, {"draft_version": V, "children": SPLIT["children"][:1]})
    assert one.status_code == 400 and one.json()["code"] == "too_few_scopes"
    combo = copy.deepcopy(SPLIT)
    combo["children"][0]["data"]["work_type"] = "combo"
    assert _split(monkeypatch, combo).json()["code"] == "invalid_scope"
    twice = copy.deepcopy(SPLIT)
    twice["children"][2]["label"] = "lab 1"
    r = _split(monkeypatch, twice)
    assert r.status_code == 409 and r.json()["code"] == "label_taken"
    assert len(store["drafts"]) == 1, "a refused split wrote a draft"


def test_only_the_scope_keys_of_the_request_reach_a_draft(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    body = copy.deepcopy(SPLIT)
    body["children"][1]["data"].update({"is_test": False, "scope_group": {"id": "x"},
                                        "assigned_estimator": "evil@x.test", "split_at": "x"})
    j = _split(monkeypatch, body).json()
    d = _row(store, j["children"][0]["id"])["data"]
    assert d["is_test"] is True and d["assigned_estimator"] == "kyle@x.test"
    assert d["scope_group"]["id"] == j["group_id"] and "split_at" not in d


def test_a_pending_autosave_of_the_pre_split_copy_cannot_undo_the_split(fake_supabase, monkeypatch):
    """THE RACE: the page's own debounced save (or a second tab) PUTs the blob it held BEFORE the
    split. Stored, it would put all three sheets back on the parent while the two new scopes hold two
    of them as well. The server refuses it, and the page's adopted copy still saves."""
    store = _seed(fake_supabase, monkeypatch)
    j = _split(monkeypatch).json()
    after = copy.deepcopy(_row(store, "p1")["data"])
    pre_split = copy.deepcopy(PARENT)                 # what the old tab was holding
    r = client.put("/api/draft/p1", json={"data": pre_split})
    assert r.status_code == 409 and r.json()["code"] == "split_since"
    assert _row(store, "p1")["data"] == after, "the pre-split copy was stored over the split"
    # the copy the page adopted from the split's answer saves normally
    adopted = copy.deepcopy(j["parent"]["data"])
    adopted["scope_notes"] = "typed after the split"
    r = client.put("/api/draft/p1", json={"data": adopted})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _row(store, "p1")["data"]["scope_notes"] == "typed after the split"
    assert _row(store, "p1")["data"]["work_type"] == "polish"


def test_the_combined_send_is_proxied_whole(monkeypatch):
    seen = {}

    async def raw(path, method, blob, ctype):
        import json as _j
        seen.update(path=path, body=_j.loads(blob), ctype=ctype)
        return main.Response(content=b'{"ok": false, "error": "scopes_not_published", "missing": ["s2"]}',
                             status_code=409, headers={"content-type": "application/json"})
    monkeypatch.setattr(main, "_portal_raw", raw)
    # a portal that handles scope groups (test_scope_group_hardening.py holds the one that does not)
    monkeypatch.setattr(main, "_portal_capabilities",
                        lambda: {"scope_groups": True, "group_followups": True})
    r = client.post("/api/portal/scope-group/%s/send" % GID, json={"message": "hi", "resend": True})
    assert r.status_code == 409 and r.json()["missing"] == ["s2"]
    assert seen["path"] == "/api/admin/scope-group/%s/send" % GID
    assert seen["body"]["message"] == "hi" and seen["body"]["resend"] is True
    bad = client.post("/api/portal/scope-group/has%20space/send", json={})
    assert bad.status_code == 400
