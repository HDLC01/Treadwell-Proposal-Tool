"""One intake, one estimate, several proposals ("Create Multiple Proposals"), the store and routes.

Hanz, 2026-10-27: the estimator prices the rooms as sheets of ONE estimate, ticks several sheets as
base bids ("Base Bid 1", "Base Bid 2"...), and presses Create Multiple Proposals. The portal knows a
proposal as one row of `drafts`, so every base bid after the first is a CHILD draft the server makes
and refreshes from the parent (drafts.fan_out_proposals / refresh_proposals / proposals_view):

  A. the child: exactly the estimate + its base's money + empty words, sharing no object;
  B. labels, idempotency, the parent's side (base_tab_ids, options, updated_at), the test rule and
     MAX_SCOPES, every refusal code;
  C. the digest and the refresh: the words stay, the estimate moves, `sheet_gone`;
  D. children first, taken back on a failure;
  E. the routes: stale 409, a child resolves to its parent, /split refuses with has_proposals, the
     trash cascade, the sign-in gate and nav_access;
  F. the projections carry proposal_of to the board;
  G. a v2 child is the kind-flipped model, and the project workbook reads it.
"""
import copy

import pytest
from fastapi.testclient import TestClient

import drafts
import estimate_writer
import main
import nav_access
from conftest import FakeClient, FakeTable
from test_hand_it_off import _ProjectingClient

client = TestClient(main.app)

V = "2026-10-20T10:00:00+00:00"


def _tab(tid, role, total, name=None, **kw):
    t = {"id": tid, "name": name or tid, "role": role, "kind": "base", "total": total,
         "sales_tax": round(total * 0.04, 2), "remodel": 0, "system_desc": role + " system",
         "notes_auto": [], "sf": ({"polish_sf": 1500} if role in ("polish", "seal")
                                  else {"epoxy_sf": 4000, "cove_lf": 200}),
         "sys_names": [], "taxable": True, "remodel_on": False}
    t.update(kw)
    return t


PARENT = {
    # intake
    "project_name": "Acme HQ", "audience": "Direct", "is_test": True,
    "assigned_estimator": "kyle@x.test", "bid_date": "2026-11-02", "address": "1 Main St",
    "city": "Olathe", "state": "KS", "zip": "66061", "contact_name": "Pat",
    "contact_email": "pat@acme.test",
    # the estimate
    "cell_values": {"Epoxy!E20": 4000, "Copy1!E20": 3000, "Epoxy!B4": "No"},
    "tab_copies": {"Copy1": "Epoxy"}, "tab_labels": {"Copy1": "Room 2"},
    "tab_order": ["Epoxy", "Copy1", "Polish", "Seal"], "tab_structs": {"Copy1": {"rows": []}},
    "lock_overrides": {"Epoxy!D88": True}, "extras": {"Epoxy": [{"name": "x", "cost": 10}]},
    "priced_tabs": [_tab("Epoxy", "epoxy", 20000, phase=4500, costs=12000, man_hours=160.4),
                    _tab("Copy1", "epoxy", 15000, name="Room 2", phase=3500, costs=9000,
                         man_hours=99.6, taxable=False, remodel_on=True),
                    _tab("Polish", "polish", 9000),
                    _tab("Seal", "seal", 3000)],
    "hf_lump_sums": {"epoxy": 20000, "polish": 9000, "combined": 29000, "gyp": 0},
    "tax_flags_per_sheet": True, "cove_height_v2": "",
    # the money of the parent's own base, and the base
    "work_type": "epoxy", "base_tab_id": "Epoxy", "proposal_lump_sum": 20000,
    "proposal_sales_tax": 800, "proposal_remodel_tax": 0, "proposal_taxable": True,
    "proposal_remodel_on": False, "sheet_area": {"epoxy_sf": 4000, "cove_lf": 200},
    "polish_sf": 1500, "phase_price": 4500, "cost_snapshot": {"costs": 12000, "man_hours": 160},
    "computed_bid": None, "rooms": [{"id": "Epoxy", "is_base": True}],
    # the parent's own proposal: never a child's
    "tab_opts": {"Copy1": {"is_option": True, "show": True}, "Seal": {"is_option": True}},
    "tab_notes": {"Epoxy": ["n"]}, "price_lines": [{"x": 1}], "price_overrides": {"lines": {}},
    "paragraph_overrides": {"p": 1}, "box_overrides": {"b": 1}, "system_overrides": {"s": 1},
    "scope_notes": "Parent words", "schedule_notes": "S", "exclusions": "E",
    "system_name": "Flake", "texture": "T", "cover_letter_enabled": True,
    "proposal_payload": {"values": {"x": 1}}, "generate_result": {"work_type": "epoxy"},
    "dropbox_result": {"folder_path": "/x"}, "notify_picks": {"add": ["a@x.test"]},
}


def _seed(fake_supabase, monkeypatch, data=None, rid="p1", extra=(), client_cls=None):
    store = {"drafts": [{"id": rid, "data": copy.deepcopy(data if data is not None else PARENT),
                         "owner_email": "kyle@x.test", "created_at": "2026-10-01",
                         "updated_at": V, "deleted_at": None}] + list(extra),
             "events": [], "draft_revisions": []}
    fake = client_cls(store) if client_cls else fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    return store


def _row(store, rid):
    return next(r for r in store["drafts"] if r["id"] == rid)


def _kids(store, parent="p1"):
    return [r for r in store["drafts"] if (r["data"] or {}).get("proposal_of") == parent]


def _no_portal_row(*a, **k):
    raise main.HTTPException(404, "not_found")


def _fan(store_ids=("Epoxy", "Copy1"), **kw):
    return drafts.fan_out_proposals("p1", list(store_ids), "rj@x.test", **kw)


def _refused(code, fn, *a, **k):
    with pytest.raises(drafts.ScopeError) as ei:
        fn(*a, **k)
    assert ei.value.code == code, (ei.value.code, ei.value.message)
    assert ei.value.message
    return ei.value


# ── A. the child ────────────────────────────────────────────────────────────
def test_a_child_holds_exactly_the_estimate_its_money_and_empty_words(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = _fan()
    child = _row(store, out["children"][0]["id"])["data"]
    estimate = {k for k in drafts.PROPOSAL_ESTIMATE_KEYS if k in PARENT}
    assert set(child) == (estimate | set(drafts.PROPOSAL_MONEY_KEYS) | set(drafts.PROPOSAL_BASE_KEYS)
                          | {"tab_opts", "scope_group", "proposal_of", "estimate_digest",
                             "estimate_synced_at"}), sorted(set(child) ^ estimate)
    for k in estimate:
        assert child[k] == PARENT[k], k
    for k in drafts.PROPOSAL_NARRATIVE_KEYS:
        if k != "tab_opts":
            assert k not in child, "a child carried the parent's %s" % k
    assert child["tab_opts"] == {}
    assert "notify_picks" not in child
    # its base's money, by rebuildPricing's rule
    assert (child["base_tab_id"], child["base_tab_ids"], child["work_type"]) == ("Copy1", ["Copy1"], "epoxy")
    assert (child["proposal_lump_sum"], child["proposal_sales_tax"], child["proposal_remodel_tax"]) == (15000, 600, 0)
    assert (child["proposal_taxable"], child["proposal_remodel_on"]) == (False, True)
    assert child["sheet_area"] == {"epoxy_sf": 4000, "cove_lf": 200}
    assert child["phase_price"] == 3500 and child["cost_snapshot"] == {"costs": 9000, "man_hours": 100}
    assert child["polish_sf"] == 1500
    assert child["computed_bid"] is None and child["rooms"] == []
    assert child["proposal_of"] == "p1" and child["estimate_digest"] == drafts.estimate_digest(PARENT)
    assert _row(store, out["children"][0]["id"])["owner_email"] == "rj@x.test"


def test_a_child_shares_no_object_with_its_parent_or_its_siblings(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = _fan(("Epoxy", "Copy1", "Polish"))
    a, b = (_row(store, c["id"])["data"] for c in out["children"])
    a["cell_values"]["Epoxy!E20"] = 1
    a["priced_tabs"][0]["total"] = 1
    a["tab_copies"]["Copy1"] = "nope"
    assert _row(store, "p1")["data"]["cell_values"]["Epoxy!E20"] == 4000
    assert _row(store, "p1")["data"]["priced_tabs"][0]["total"] == 20000
    assert b["cell_values"]["Epoxy!E20"] == 4000 and b["tab_copies"]["Copy1"] == "Epoxy"
    assert b["priced_tabs"][0]["total"] == 20000


def test_the_parents_own_base_money_is_used_when_the_tab_carries_none(fake_supabase, monkeypatch):
    """A snapshot from before priced_tabs carried phase/costs: a child never prints another sheet's
    cost, so it says 0 rather than the parent's base figure."""
    data = copy.deepcopy(PARENT)
    for t in data["priced_tabs"]:
        for k in ("phase", "costs", "man_hours"):
            t.pop(k, None)
    store = _seed(fake_supabase, monkeypatch, data)
    child = _row(store, _fan()["children"][0]["id"])["data"]
    assert child["phase_price"] == 0 and child["cost_snapshot"] == {"costs": 0, "man_hours": 0}


# ── B. labels, idempotency, the parent, refusals ───────────────────────────
def test_labels_are_base_bid_n_and_the_parent_is_named_when_unnamed(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = _fan(("Epoxy", "Copy1", "Polish"))
    assert out["parent"]["label"] == "Base Bid 1"
    assert [c["label"] for c in out["children"]] == ["Base Bid 2", "Base Bid 3"]
    parent = _row(store, "p1")["data"]
    assert parent["scope_group"] == {"id": out["group_id"], "label": "Base Bid 1"}
    for c in out["children"]:
        assert _row(store, c["id"])["data"]["scope_group"]["id"] == out["group_id"]
        assert drafts.scope_group_problem(_row(store, c["id"])["data"]["scope_group"]) is None


def test_a_named_parent_keeps_its_name_and_a_clash_is_numbered(fake_supabase, monkeypatch):
    data = dict(PARENT, scope_group={"id": "grp_a", "label": "Breakroom"})
    other = {"id": "s9", "data": {"project_name": "Acme HQ", "is_test": True,
                                  "scope_group": {"id": "grp_a", "label": "Base Bid 2"}},
             "owner_email": "k", "created_at": "2026-10-02", "updated_at": V, "deleted_at": None}
    _seed(fake_supabase, monkeypatch, data, extra=[other])
    out = _fan()
    assert out["parent"]["label"] == "Breakroom"
    assert out["children"][0]["label"] == "Base Bid 2 2"


def test_fanning_out_twice_makes_nothing_twice(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    first = _fan()
    again = _fan()
    assert [c["id"] for c in again["children"]] == [c["id"] for c in first["children"]]
    assert again["children"][0]["created"] is False and first["children"][0]["created"] is True
    assert len(_kids(store)) == 1
    more = _fan(("Epoxy", "Copy1", "Polish"))
    assert [c["created"] for c in more["children"]] == [False, True]
    assert len(_kids(store)) == 2
    assert more["children"][1]["label"] == "Base Bid 3"


def test_the_parent_records_its_bases_and_stops_offering_them_as_options(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    _fan()
    parent = _row(store, "p1")
    assert parent["data"]["base_tab_ids"] == ["Epoxy", "Copy1"]
    assert parent["data"]["tab_opts"]["Copy1"] == {"is_option": False, "show": True}
    assert parent["data"]["tab_opts"]["Seal"] == {"is_option": True}
    assert parent["updated_at"] == V, "making the proposals is not an edit of the estimate"
    # everything else about the parent is as it was
    for k, v in PARENT.items():
        if k not in ("tab_opts",):
            assert parent["data"][k] == v, k


def test_a_sent_parent_keeps_its_options_as_they_are(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    _fan(sent=True)
    assert _row(store, "p1")["data"]["tab_opts"] == PARENT["tab_opts"]
    assert len(_kids(store)) == 1


def test_every_refusal_says_its_code(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    _refused("too_few_bases", _fan, ("Epoxy",))
    _refused("too_few_bases", _fan, ("Epoxy", "Epoxy"))
    _refused("no_such_sheet", _fan, ("Epoxy", "Copy7"))
    _refused("option_only_base", _fan, ("Epoxy", "Seal"))
    _refused("base_order", _fan, ("Copy1", "Epoxy"))
    _seed(fake_supabase, monkeypatch, dict(PARENT, base_tab_id=None, work_type="combo"))
    _refused("combined_base", _fan, ("Epoxy", "Copy1"))
    _seed(fake_supabase, monkeypatch, dict(PARENT, base_tab_id=None))
    _refused("base_order", _fan, ("Epoxy", "Copy1"))
    _seed(fake_supabase, monkeypatch, dict(PARENT, scope_group={"id": "bad id"}))
    _refused("invalid_scope_group", _fan)
    store = _seed(fake_supabase, monkeypatch)
    kid = _fan()["children"][0]["id"]
    _refused("not_fanned_from_child", drafts.fan_out_proposals, kid, ["Copy1", "Epoxy"])
    assert _refused("not_found", drafts.fan_out_proposals, "nope", ["a", "b"]).status == 404
    assert len(_kids(store)) == 1


def test_a_label_that_cannot_be_freed_is_label_taken(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    monkeypatch.setattr(drafts, "_free_label", lambda want, taken: "Base Bid 1")
    assert _refused("label_taken", _fan).status == 409


def test_a_test_parent_in_a_real_project_is_refused_and_children_inherit_its_kind(fake_supabase, monkeypatch):
    data = dict(PARENT, scope_group={"id": "grp_a", "label": "Breakroom"})
    real = {"id": "s9", "data": {"project_name": "Acme HQ", "is_test": False,
                                 "scope_group": {"id": "grp_a", "label": "Lab"}},
            "owner_email": "k", "created_at": "2026-10-02", "updated_at": V, "deleted_at": None}
    store = _seed(fake_supabase, monkeypatch, data, extra=[real])
    assert _refused("test_mix", _fan).status == 409
    assert _kids(store) == []
    store = _seed(fake_supabase, monkeypatch, dict(PARENT, is_test=False))
    kid = _row(store, _fan()["children"][0]["id"])["data"]
    assert kid["is_test"] is False


def test_max_scopes_counts_the_group_and_the_new_children(fake_supabase, monkeypatch):
    data = dict(PARENT, scope_group={"id": "grp_a", "label": "Breakroom"})
    others = [{"id": "s%d" % i, "data": {"project_name": "Acme HQ", "is_test": True,
                                         "scope_group": {"id": "grp_a", "label": "L%d" % i}},
               "owner_email": "k", "created_at": "2026-10-02", "updated_at": V, "deleted_at": None}
              for i in range(drafts.MAX_SCOPES - 2)]
    store = _seed(fake_supabase, monkeypatch, data, extra=others)
    assert _refused("too_many_scopes", _fan, ("Epoxy", "Copy1", "Polish")).status == 409
    assert _kids(store) == []
    assert len(_fan()["children"]) == 1          # exactly at the limit


# ── C. the digest and the refresh ───────────────────────────────────────────
def test_the_digest_moves_on_every_estimate_key_and_on_nothing_else():
    base = drafts.estimate_digest(PARENT)
    for k in drafts.PROPOSAL_ESTIMATE_KEYS:
        if k in drafts.PROPOSAL_REFRESH_SKIPS:
            continue
        assert drafts.estimate_digest(dict(PARENT, **{k: ["changed", k]})) != base, k
    for k in (set(drafts.PROPOSAL_NARRATIVE_KEYS) | set(drafts.PROPOSAL_MONEY_KEYS)
              | set(drafts.PROPOSAL_REFRESH_SKIPS) | {"base_tab_id", "base_tab_ids", "rooms",
                                                     "scope_group", "notify_picks"}):
        assert drafts.estimate_digest(dict(PARENT, **{k: ["changed", k]})) == base, k
    # a jsonb read-back reorders keys
    shuffled = dict(reversed(list(PARENT.items())))
    shuffled["cell_values"] = dict(reversed(list(PARENT["cell_values"].items())))
    assert drafts.estimate_digest(shuffled) == base


NARRATIVE = {k: {"kept": k} for k in drafts.PROPOSAL_NARRATIVE_KEYS}


def _fan_then_edit_parent(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kid = _fan()["children"][0]["id"]
    k = _row(store, kid)
    k["data"].update(copy.deepcopy(NARRATIVE))
    k["data"].update(is_test=True, assigned_estimator="troy@x.test", notify_picks={"add": ["c"]})
    k["updated_at"] = "2026-10-21T00:00:00+00:00"
    p = _row(store, "p1")["data"]
    for key in drafts.PROPOSAL_ESTIMATE_KEYS:
        if key not in drafts.PROPOSAL_REFRESH_SKIPS and key in p and key != "priced_tabs":
            p[key] = {"new": key}
    p["priced_tabs"][1]["total"] = 17000
    p["assigned_estimator"] = "kyle@x.test"    # the child was handed to Troy on the board
    return store, kid


def test_refresh_replaces_every_estimate_key_and_keeps_every_word(fake_supabase, monkeypatch):
    store, kid = _fan_then_edit_parent(fake_supabase, monkeypatch)
    parent_before = copy.deepcopy(_row(store, "p1"))
    out = drafts.refresh_proposals("p1", "rj@x.test")
    assert out["refreshed"] == [kid] and out["skipped"] == []
    child = _row(store, kid)
    for key in drafts.PROPOSAL_ESTIMATE_KEYS:
        if key in drafts.PROPOSAL_REFRESH_SKIPS or key not in parent_before["data"]:
            continue
        assert child["data"][key] == parent_before["data"][key], key
    for key, v in NARRATIVE.items():
        assert child["data"][key] == v, "refresh lost the child's own %s" % key
    assert child["data"]["proposal_lump_sum"] == 17000
    assert (child["data"]["is_test"], child["data"]["assigned_estimator"]) == (True, "troy@x.test")
    assert child["data"]["notify_picks"] == {"add": ["c"]}
    assert child["data"]["proposal_of"] == "p1" and child["data"]["scope_group"]["label"] == "Base Bid 2"
    assert child["data"]["estimate_digest"] == drafts.estimate_digest(parent_before["data"])
    assert child["updated_at"] != "2026-10-21T00:00:00+00:00", "the child's document must be rebuilt"
    assert _row(store, "p1") == parent_before, "refresh touched the parent"


def test_refresh_from_a_child_id_refreshes_the_whole_project(fake_supabase, monkeypatch):
    store, kid = _fan_then_edit_parent(fake_supabase, monkeypatch)
    assert drafts.refresh_proposals(kid)["refreshed"] == [kid]
    assert _row(store, kid)["data"]["proposal_lump_sum"] == 17000


def test_a_child_whose_sheet_is_gone_is_skipped(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kid = _fan()["children"][0]["id"]
    before = copy.deepcopy(_row(store, kid))
    _row(store, "p1")["data"]["priced_tabs"] = [t for t in PARENT["priced_tabs"] if t["id"] != "Copy1"]
    out = drafts.refresh_proposals("p1")
    assert out["refreshed"] == [] and out["skipped"] == [{"id": kid, "label": "Base Bid 2",
                                                          "code": "sheet_gone"}]
    assert _row(store, kid) == before


# ── D. children first, taken back on a failure ─────────────────────────────
class _Flaky(FakeClient):
    """Draft inserts fail after `ok` of them; the parent's update fails when `update_fails`."""

    def __init__(self, store, ok=99, update_fails=False):
        super().__init__(store)
        self.ok, self.update_fails, self.inserts = ok, update_fails, 0

    def table(self, name):
        outer = self
        t = FakeTable(self.store, name, self.captures)
        real = t.execute

        def execute():
            if name == "drafts" and t._op == "insert":
                if outer.inserts >= outer.ok:
                    raise RuntimeError("PostgREST blip")
                outer.inserts += 1
            if name == "drafts" and t._op == "update" and outer.update_fails:
                raise RuntimeError("PostgREST blip")
            return real()
        t.execute = execute
        return t


@pytest.mark.parametrize("kw", [{"ok": 1}, {"update_fails": True}])
def test_a_failure_part_way_takes_back_every_child_and_leaves_the_parent(monkeypatch, kw):
    store = _seed(None, monkeypatch, client_cls=lambda s: _Flaky(s, **kw))
    before = copy.deepcopy(_row(store, "p1"))
    assert _refused("split_failed", _fan, ("Epoxy", "Copy1", "Polish")).status == 503
    assert _row(store, "p1") == before
    assert [r["id"] for r in store["drafts"]] == ["p1"]


# ── E. the routes ───────────────────────────────────────────────────────────
def test_the_route_makes_the_proposals_and_answers_the_strip(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    r = client.post("/api/draft/p1/proposals", json={"draft_version": V,
                                                     "base_ids": ["Epoxy", "Copy1", "Polish"]})
    assert r.status_code == 200, r.text
    j = r.json()
    kids = [c["id"] for c in j["children"]]
    assert [m["id"] for m in j["proposals"]["members"]] == ["p1"] + kids
    assert [m["label"] for m in j["proposals"]["members"]] == ["Base Bid 1", "Base Bid 2", "Base Bid 3"]
    assert [m["index"] for m in j["proposals"]["members"]] == [1, 2, 3]
    assert [m["is_parent"] for m in j["proposals"]["members"]] == [True, False, False]
    assert [m["base_tab_id"] for m in j["proposals"]["members"]] == ["Epoxy", "Copy1", "Polish"]
    assert not any(m["stale"] for m in j["proposals"]["members"])
    assert _row(store, "p1")["data"]["tab_opts"]["Copy1"]["is_option"] is False


def test_a_child_id_answers_its_parents_strip_and_flags_a_changed_estimate(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    out = _fan(("Epoxy", "Copy1", "Polish"))
    kid = out["children"][1]["id"]
    _row(store, "p1")["data"]["base_tab_ids"] = ["Epoxy", "Polish", "Copy1"]   # order follows the parent
    g = client.get("/api/draft/%s/proposals" % kid).json()
    assert g["parent_id"] == "p1" and g["group_id"] == out["group_id"]
    assert [m["base_tab_id"] for m in g["members"]] == ["Epoxy", "Polish", "Copy1"]
    assert not any(m["stale"] for m in g["members"])
    _row(store, "p1")["data"]["cell_values"]["Copy1!E20"] = 3100
    g = client.get("/api/draft/p1/proposals").json()
    assert [m["stale"] for m in g["members"]] == [False, True, True]
    assert g["estimate_digest"] == drafts.estimate_digest(_row(store, "p1")["data"])
    # the refresh route, pressed from a child's tab
    r = client.post("/api/draft/%s/proposals/refresh" % kid,
                    json={"draft_version": _row(store, kid)["updated_at"]})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["refreshed"]) == sorted(c["id"] for c in out["children"])
    assert not any(m["stale"] for m in r.json()["proposals"]["members"])


def test_a_draft_with_no_proposals_answers_itself_alone(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch)
    g = client.get("/api/draft/p1/proposals").json()
    assert g["ok"] is True and [m["id"] for m in g["members"]] == ["p1"]
    assert client.get("/api/draft/nope/proposals").status_code == 404


def test_the_routes_refuse_a_stale_copy_a_child_and_a_silent_portal(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    monkeypatch.setattr(main, "_portal", _no_portal_row)
    body = {"draft_version": "2026-10-19T00:00:00+00:00", "base_ids": ["Epoxy", "Copy1"]}
    r = client.post("/api/draft/p1/proposals", json=body)
    assert r.status_code == 409 and r.json()["code"] == "document_changed"
    r = client.post("/api/draft/p1/proposals/refresh", json={"draft_version": "2026-10-19"})
    assert r.status_code == 409 and r.json()["code"] == "document_changed"
    assert _kids(store) == []
    r = client.post("/api/draft/p1/proposals", json={"base_ids": ["Epoxy"]})
    assert r.status_code == 400 and r.json()["code"] == "too_few_bases"
    r = client.post("/api/draft/p1/proposals", json={"base_ids": ["Epoxy", "Seal"]})
    assert r.status_code == 400 and r.json()["code"] == "option_only_base"
    kid = client.post("/api/draft/p1/proposals", json={"base_ids": ["Epoxy", "Copy1"]}).json()["children"][0]["id"]
    r = client.post("/api/draft/%s/proposals" % kid, json={"base_ids": ["Copy1", "Epoxy"]})
    assert r.status_code == 400 and r.json()["code"] == "not_fanned_from_child"
    assert client.post("/api/draft/nope/proposals", json={}).status_code == 404

    def boom(*a, **k):
        raise main.HTTPException(502, "down")
    monkeypatch.setattr(main, "_portal", boom)
    r = client.post("/api/draft/p1/proposals", json={"base_ids": ["Epoxy", "Copy1", "Polish"]})
    assert r.status_code == 502 and r.json()["code"] == "portal_unreachable"
    assert len(_kids(store)) == 1


def test_a_sent_parent_through_the_route_keeps_its_options(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    monkeypatch.setattr(main, "_portal", lambda *a, **k: {"ok": True})        # a portal row exists
    r = client.post("/api/draft/p1/proposals", json={"base_ids": ["Epoxy", "Copy1"]})
    assert r.status_code == 200, r.text
    assert _row(store, "p1")["data"]["tab_opts"] == PARENT["tab_opts"]


def test_split_refuses_a_fanned_out_parent_and_its_child(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, V2)
    kid = drafts.fan_out_proposals("p1", ["Polish", "Copy1"])["children"][0]["id"]
    for rid in ("p1", kid):
        version = _row(store, rid)["updated_at"]
        r = client.post("/api/draft/%s/split" % rid, json={"draft_version": version, "children": []})
        assert r.status_code == 409 and r.json()["code"] == "has_proposals", r.text


def test_split_still_answers_as_before_for_a_project_with_no_proposals(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch, dict(PARENT, polish_estimate={"version": 2}))
    r = client.post("/api/draft/p1/split", json={"draft_version": V, "children": []})
    assert r.status_code == 400 and r.json()["code"] == "too_few_scopes"


def test_trashing_a_parent_trashes_its_proposals_and_restore_brings_back_the_parent(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kids = [c["id"] for c in _fan(("Epoxy", "Copy1", "Polish"))["children"]]
    r = client.delete("/api/draft/p1")
    assert r.status_code == 200 and sorted(r.json()["cascaded"]) == sorted(kids)
    assert all(_row(store, k).get("deleted_at") for k in kids + ["p1"])
    monkeypatch.setattr(main, "_portal_visibility", lambda *a, **k: False)
    assert client.post("/api/draft/p1/restore").status_code == 200
    assert _row(store, "p1")["deleted_at"] is None
    assert all(_row(store, k).get("deleted_at") for k in kids)


def test_trashing_a_child_trashes_the_child_alone(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kids = [c["id"] for c in _fan(("Epoxy", "Copy1", "Polish"))["children"]]
    r = client.delete("/api/draft/%s" % kids[0])
    assert r.json()["cascaded"] == []
    assert _row(store, kids[0]).get("deleted_at") and not _row(store, kids[1]).get("deleted_at")
    assert not _row(store, "p1")["deleted_at"]


PATHS = [("GET", "/api/draft/p1/proposals"), ("POST", "/api/draft/p1/proposals"),
         ("POST", "/api/draft/p1/proposals/refresh")]


@pytest.mark.parametrize("method,path", PATHS)
def test_the_new_routes_are_signed_in_and_open_to_every_role(method, path):
    """Behind the sign-in gate like every /api route, and never denied by a tab: they are the
    proposal step's, which every role that makes proposals uses (nav_access: /api/draft/*)."""
    assert not main._auth_is_public(path, method)
    everything = {"deny": {role: list(nav_access.TABS) for role in nav_access.ROLES}}
    for role in nav_access.ROLES:
        assert not nav_access.is_api_denied(role, path, everything), role
    routes = {(m, r.path) for r in main.app.routes for m in (getattr(r, "methods", None) or ())}
    assert (method, path.replace("p1", "{draft_id}")) in routes


# ── server-owned ────────────────────────────────────────────────────────────
def test_a_browser_save_can_neither_clear_nor_seed_the_proposal_keys(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kid = _fan()["children"][0]["id"]
    held = {k: _row(store, kid)["data"][k] for k in ("proposal_of", "estimate_digest", "estimate_synced_at")}
    # A blob that dropped two of the keys, still carrying the refresh stamp it was read with (a
    # blob without that stamp is refused outright: test_a_page_holding_a_copy_from_before_a_refresh...).
    stale = {k: v for k, v in _row(store, kid)["data"].items()
             if k not in held or k == "estimate_synced_at"}
    assert client.put("/api/draft/%s" % kid, json={"data": stale}).json()["ok"] is True
    assert {k: _row(store, kid)["data"][k] for k in held} == held
    forged = dict(stale, proposal_of="other", estimate_digest="x", estimate_synced_at="y")
    client.put("/api/draft/%s" % kid, json={"data": forged})
    assert {k: _row(store, kid)["data"][k] for k in held} == held
    # a copy under a new id, or an ungrouped row, never takes them from a browser
    assert client.put("/api/draft/new-copy", json={"data": forged}).json()["ok"] is True
    assert not set(held) & set(_row(store, "new-copy")["data"])
    client.put("/api/draft/p1", json={"data": dict(PARENT, proposal_of="x")})
    assert "proposal_of" not in _row(store, "p1")["data"]


def test_every_mirror_of_the_server_owned_keys_agrees():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "frontend" / "shared.js").read_text(encoding="utf-8")
    m = re.search(r"const SERVER_OWNED_KEYS = \[([^\]]*)\]", src)
    assert {k.strip().strip("\"'") for k in m.group(1).split(",") if k.strip()} == set(drafts._SERVER_OWNED_KEYS)
    for k in ("proposal_of", "estimate_digest", "estimate_synced_at"):
        assert k in drafts._SERVER_OWNED_KEYS and k in drafts._NEVER_SEEDED_BY_A_BROWSER


# ── F. the projections ──────────────────────────────────────────────────────
def test_every_read_path_carries_proposal_of(fake_supabase, monkeypatch):
    assert drafts._summary({"id": "d", "data": {"proposal_of": "p1"}})["proposal_of"] == "p1"
    assert drafts._summary({"id": "d", "data": {}})["proposal_of"] is None
    store = {"drafts": [{"id": "d1", "owner_email": "k", "deleted_at": None, "created_at": "2026-08-01",
                         "updated_at": "2026-08-02",
                         "data": {"project_name": "Acme HQ", "proposal_of": "p1",
                                  "scope_group": {"id": "grp_a", "label": "Base Bid 2"}}}]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    assert drafts._build_summaries(trashed=False, limit=10)[0]["proposal_of"] == "p1"
    assert drafts._group_rows_all("grp_a")[0]["proposal_of"] == "p1"


def test_the_board_says_which_member_is_a_proposal_of_another(monkeypatch):
    def s(i, label, **kw):
        out = {"id": "s%d" % i, "project_name": "Acme HQ", "has_files": True, "scope_group_id": "grp_a",
               "scope_label": label, "created_at": "2026-10-0%d" % i, "updated_at": "2026-10-1%d" % i,
               "total": None}
        out.update(kw)
        return out
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": []})
    monkeypatch.setattr(main.drafts, "list_drafts",
                        lambda *a, **k: [s(1, "Base Bid 1"), s(2, "Base Bid 2", proposal_of="s1")])
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    rows = {p["proposal_id"]: p for p in r.json()["proposals"]}
    assert [(m["id"], m["proposal_of"]) for m in rows["s1"]["scope_members"]] == [("s1", None), ("s2", "s1")]


def test_the_board_says_which_member_is_a_v2_estimate(monkeypatch):
    """Plan step 6: the drawer's project-workbook button reads the group home's `v2` (the summary's
    polish_beta): a v1 home goes to its Files page, a v2 home builds /api/scope-group/{gid}/workbook."""
    def s(i, label, beta, **kw):
        out = {"id": "s%d" % i, "project_name": "Acme HQ", "has_files": True, "scope_group_id": "grp_a",
               "scope_label": label, "created_at": "2026-10-0%d" % i, "updated_at": "2026-10-1%d" % i,
               "total": None, "polish_beta": beta}
        out.update(kw)
        return out
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": []})
    monkeypatch.setattr(main.drafts, "list_drafts",
                        lambda *a, **k: [s(1, "Base Bid 1", True), s(2, "Base Bid 2", False, proposal_of="s1"),
                                         s(3, "Lab 3", None)])
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    rows = {p["proposal_id"]: p for p in r.json()["proposals"]}
    assert [(m["id"], m["v2"]) for m in rows["s2"]["scope_members"]] == [("s1", True), ("s2", False), ("s3", False)]


# ── G. v2 ───────────────────────────────────────────────────────────────────
V2 = dict(PARENT, polish_estimate={
    "version": 2, "label": "Breakroom",
    "takeoff": [{"assembly_id": "a1", "measurement": 1500}],
    "tabs": {"Epoxy": {"kind": "option", "label": "Lab 1", "takeoff": []},
             "Copy1": {"kind": "option", "sheet": "Epoxy", "label": "Lab 2", "takeoff": []},
             "Seal": {"kind": "option", "label": "Seal"},
             "Copy2": {"kind": "off", "sheet": "Epoxy", "label": "Old"}}},
    base_tab_id="Polish", work_type="polish",
    priced_tabs=[dict(_tab("Polish", "polish", 9000), v2=True),
                 dict(_tab("Epoxy", "epoxy", 20000), kind="option", v2=True),
                 dict(_tab("Copy1", "epoxy", 15000), kind="option", v2=True),
                 dict(_tab("Seal", "seal", 3000), kind="option", v2=True),
                 dict(_tab("Unpriced", "epoxy", 0), kind="option", total=None, v2=True)])


def test_a_v2_child_is_the_kind_flipped_model_and_the_workbook_reads_it(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, V2)
    out = drafts.fan_out_proposals("p1", ["Polish", "Copy1"])
    child = _row(store, out["children"][0]["id"])["data"]
    pe = child["polish_estimate"]
    assert pe["kind"] == "option" and pe["tabs"]["Copy1"]["kind"] == "base"
    assert pe["tabs"]["Epoxy"]["kind"] == "option" and pe["tabs"]["Copy2"]["kind"] == "off"
    assert {t["id"]: t["kind"] for t in child["priced_tabs"]}["Polish"] == "option"
    assert {t["id"]: t["kind"] for t in child["priced_tabs"]}["Copy1"] == "base"
    assert estimate_writer.group_member_sheet(child) == ("Copy1", "Epoxy")
    assert child["proposal_lump_sum"] == 15000 and child["work_type"] == "epoxy"
    assert _row(store, "p1")["data"]["polish_estimate"] == V2["polish_estimate"], "the parent's model moved"


def test_v2_refusals(fake_supabase, monkeypatch):
    _seed(fake_supabase, monkeypatch, V2)
    _refused("option_only_base", drafts.fan_out_proposals, "p1", ["Polish", "Seal"])
    _refused("no_such_sheet", drafts.fan_out_proposals, "p1", ["Polish", "Unpriced"])
    _seed(fake_supabase, monkeypatch, dict(V2, base_tab_id=None))
    _refused("combined_base", drafts.fan_out_proposals, "p1", ["Polish", "Copy1"])
    combined = copy.deepcopy(V2["polish_estimate"])
    combined["tabs"]["Epoxy"]["kind"] = "base"
    _refused("combined_base", drafts._v2_child_model, combined, "Copy1")
    _refused("no_such_sheet", drafts._v2_child_model, V2["polish_estimate"], "Copy2")


def test_a_v2_sheet_the_estimate_could_not_price_has_no_price(fake_supabase, monkeypatch):
    data = copy.deepcopy(V2)
    data["priced_tabs"][2]["total"] = None
    store = _seed(fake_supabase, monkeypatch, data)
    child = _row(store, drafts.fan_out_proposals("p1", ["Polish", "Copy1"])["children"][0]["id"])["data"]
    assert child["proposal_lump_sum"] is None


# ── review fixes ────────────────────────────────────────────────────────────
def test_a_page_holding_a_copy_from_before_a_refresh_cannot_save_it_back(fake_supabase, monkeypatch):
    """A child's estimate keys are browser-written and its digest is server-owned: a stale page's
    PUT would put the old price back under the new digest, and the banner would never return.
    `estimate_synced_at` is the fence (drafts.StaleProposalWrite)."""
    store, kid = _fan_then_edit_parent(fake_supabase, monkeypatch)
    old_page = copy.deepcopy(_row(store, kid)["data"])          # read before the Refresh
    drafts.refresh_proposals("p1")
    after = copy.deepcopy(_row(store, kid))
    assert after["data"]["proposal_lump_sum"] == 17000
    r = client.put("/api/draft/%s" % kid, json={"data": old_page})
    assert r.status_code == 409 and r.json()["code"] == "refreshed_since", r.text
    assert _row(store, kid) == after, "the old copy was stored over the refresh"
    # a page that read the refreshed copy saves as before, and the parent (no stamp) is untouched
    fresh = dict(after["data"], scope_notes="New words")
    assert client.put("/api/draft/%s" % kid, json={"data": fresh}).json()["ok"] is True
    assert _row(store, kid)["data"]["scope_notes"] == "New words"
    assert client.put("/api/draft/p1", json={"data": dict(PARENT)}).json()["ok"] is True


def _cove(aid, lf=120, **kw):
    return dict({"assembly_id": aid, "unit": "LF", "measurement": lf}, **kw)


def test_a_v2_child_prints_its_own_bases_cove_height(fake_supabase, monkeypatch):
    """bid-model composePricingSnapshot reads `cove_height_v2` off the BASE sections only, so the
    parent's value is the parent base's cove. A child is never re-priced on the estimate page, so
    the server reads its own base's."""
    data = copy.deepcopy(V2)
    pe = data["polish_estimate"]
    pe["takeoff"] = [{"assembly_id": "a1", "measurement": 1500}, _cove("wb-epoxy-cove-flake-6in")]
    pe["tabs"]["Copy1"]["takeoff"] = [_cove("wb-epoxy-cove-flake-8in", enabled=False),
                                      _cove("wb-epoxy-cove-flake-5in", lf=0),
                                      _cove("wb-epoxy-cove-flake-4in", lf="1,200")]
    data["cove_height_v2"] = "6"
    store = _seed(fake_supabase, monkeypatch, data)
    out = drafts.fan_out_proposals("p1", ["Polish", "Copy1", "Epoxy"])
    lab2, lab1 = (_row(store, c["id"])["data"] for c in out["children"])
    assert lab2["cove_height_v2"] == "4"
    assert lab1["cove_height_v2"] == "", "a base with no cove printed the parent's"
    assert _row(store, "p1")["data"]["cove_height_v2"] == "6"
    # and a refresh reads it again
    _row(store, "p1")["data"]["polish_estimate"]["tabs"]["Copy1"]["takeoff"] = [
        _cove("wb-epoxy-cove-wr-8in-plus-cap")]
    drafts.refresh_proposals("p1")
    assert _row(store, out["children"][0]["id"])["data"]["cove_height_v2"] == "8"


class _Portal:
    """Holds which proposal ids have a portal row, hides them on /delete; `fail` raises instead."""

    def __init__(self, rows=()):
        self.rows, self.hidden, self.fail = set(rows), [], None

    def __call__(self, path, method="GET", body=None):
        if self.fail is not None:
            raise self.fail
        pid = path.split("/")[4]
        if path.endswith("/delete") and pid in self.rows:
            self.hidden.append(pid)
            return {"ok": True}
        raise main.HTTPException(404, "not_found")


def test_deleting_a_parent_off_the_board_takes_its_proposals_and_their_portal_rows(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kids = [c["id"] for c in _fan(("Epoxy", "Copy1", "Polish"))["children"]]
    portal = _Portal(["p1", kids[0]])                       # the parent and Base Bid 2 were sent
    monkeypatch.setattr(main, "_portal", portal)
    import profiles
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "a1", "email": e, "role": "admin"})
    r = client.post("/api/project/p1/delete")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["cascaded"]) == sorted(kids)
    assert all(_row(store, k).get("deleted_at") for k in kids + ["p1"])
    assert sorted(portal.hidden) == sorted(["p1", kids[0]])


def test_the_x_on_a_sent_childs_tab_hides_its_portal_row_and_a_silent_portal_stops_it(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kids = [c["id"] for c in _fan(("Epoxy", "Copy1", "Polish"))["children"]]
    portal = _Portal([kids[0], kids[1]])                    # Base Bid 2 and 3 were sent
    monkeypatch.setattr(main, "_portal", portal)
    r = client.delete("/api/draft/%s" % kids[0])            # the proposal page's tab x
    assert r.status_code == 200 and r.json()["cascaded"] == []
    assert portal.hidden == [kids[0]]
    assert _row(store, kids[0]).get("deleted_at") and not _row(store, kids[1]).get("deleted_at")
    portal.fail = main.HTTPException(502, "down")
    assert client.delete("/api/draft/%s" % kids[1]).status_code == 502
    assert not _row(store, kids[1]).get("deleted_at")
    # the board's delete hides the child once, not twice
    portal.fail, portal.hidden = None, []
    import profiles
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "a1", "email": e, "role": "admin"})
    assert client.post("/api/project/%s/delete" % kids[1]).status_code == 200
    assert portal.hidden == [kids[1]]


def test_trashing_a_parent_hides_a_sent_proposals_portal_row(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch)
    kids = [c["id"] for c in _fan(("Epoxy", "Copy1", "Polish"))["children"]]
    portal = _Portal([kids[1]])
    monkeypatch.setattr(main, "_portal", portal)
    r = client.delete("/api/draft/p1")
    assert r.status_code == 200 and sorted(r.json()["cascaded"]) == sorted(kids)
    assert portal.hidden == [kids[1]]
    # a portal that cannot answer stops the delete before anything of ours moves
    store2 = _seed(fake_supabase, monkeypatch)
    kids2 = [c["id"] for c in _fan(("Epoxy", "Copy1"))["children"]]
    portal.fail = main.HTTPException(502, "down")
    for call in (lambda: client.delete("/api/draft/p1"), lambda: client.post("/api/project/p1/delete")):
        import profiles
        monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "a1", "email": e, "role": "admin"})
        assert call().status_code == 502
        assert not any(_row(store2, k).get("deleted_at") for k in kids2 + ["p1"])
