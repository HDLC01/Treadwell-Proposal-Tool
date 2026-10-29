"""ONE NAME: a proposal is called what its sheet is called, on every step (Hanz, 2026-10-29).

"I changed the label on these sheets and it didn't change. It should change. Whatever the sheet name
is, that would be the name of the proposals so we have it unified throughout all the steps." On
staging the Estimate step's tabs read "Epoxy", "Polish Room", "Room 2" while step 3 said "Polish
(Polish Room)": the proposal's name was stored once, when Create Multiple Proposals made it.

What is executed here, against the fake store (no network, no database, no email):

  A. a sheet renamed on the estimate (the browser's PUT, v1 tab_labels and v2 section labels)
     renames its proposal: the stored name, the strip, the board's projection, step 3's rows (the
     real generate.js, fed the server's own strip), without bumping any proposal's updated_at and
     with a scope_renamed event; duplicates are numbered; another scope's name is kept free; a save
     of any other draft asks nothing more; a failure never fails the save;
  B. renaming a proposal on its tab renames its SHEET on Base Bid 1's estimate (child, parent, v2
     root and section) and every refusal;
  C. a sent proposal: the rename calls nobody; the next publish carries the new name.
"""
import copy
import json
import pathlib
import subprocess

import pytest
from fastapi.testclient import TestClient

import drafts
import main
import test_multi_proposals as tmp
from _golden_support import break_source
from _node import require_node
from test_hand_it_off import _ProjectingClient
from test_multi_proposals import PARENT, V, V2, _row, _seed

client = TestClient(main.app)
TESTS = pathlib.Path(__file__).resolve().parent
GEN_HARNESS = TESTS / "js" / "generate-step-harness.js"


def _no_portal(*a, **k):
    raise AssertionError("a rename called the portal: %r" % (a,))


def _staging(fake_supabase, monkeypatch, data=None, extra=()):
    """Staging's project: Base Bid 1 Epoxy, then Polish and Room 2 (Copy1), made by Create Multiple
    Proposals while Polish was still called "Polish". Returns (store, {sheet: child id})."""
    store = _seed(fake_supabase, monkeypatch, data, extra=extra)
    out = drafts.fan_out_proposals("p1", ["Epoxy", "Polish", "Copy1"], "rj@x.test")
    monkeypatch.setattr(main, "_portal", _no_portal)
    return store, {c["base_tab_id"]: c["id"] for c in out["children"]}


def _label(store, rid):
    return _row(store, rid)["data"]["scope_group"]["label"]


def _put(store, rid, **changes):
    """The browser's save of `rid` with `changes` laid over its stored blob (PUT /api/draft/{id})."""
    blob = copy.deepcopy(_row(store, rid)["data"])
    blob.update(copy.deepcopy(changes))
    r = client.put("/api/draft/%s" % rid, json={"data": blob})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    return r


def _renamed_polish():
    labels = dict(PARENT["tab_labels"], Polish="Polish Room")
    priced = [dict(t, name="Polish Room") if t["id"] == "Polish" else t for t in PARENT["priced_tabs"]]
    return {"tab_labels": labels, "priced_tabs": priced}


def _without_label(row):
    out = copy.deepcopy(row)
    out["data"]["scope_group"].pop("label", None)
    return out


def _view_names(rid="p1"):
    return [(m["label"], m["display_label"]) for m in drafts.proposals_view(rid)["members"]]


# ── A. a sheet renamed on the estimate renames its proposal ────────────────────────────────────
def test_staging_a_sheet_renamed_on_the_estimate_renames_its_proposal(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    assert [_label(store, x) for x in ("p1", kid["Polish"], kid["Copy1"])] == ["Epoxy", "Polish", "Room 2"]
    before = {x: copy.deepcopy(_row(store, x)) for x in kid.values()}
    _put(store, "p1", **_renamed_polish())
    assert [_label(store, x) for x in ("p1", kid["Polish"], kid["Copy1"])] == ["Epoxy", "Polish Room", "Room 2"]
    # Only the name of the renamed sheet's proposal changed, and its updated_at did not move.
    assert _without_label(_row(store, kid["Polish"])) == _without_label(before[kid["Polish"]])
    assert _row(store, kid["Polish"])["updated_at"] == before[kid["Polish"]]["updated_at"]
    assert _row(store, kid["Copy1"]) == before[kid["Copy1"]]
    ev = [e for e in store["events"] if e["action"] == "scope_renamed"]
    assert [(e["project_id"], e["detail"]["from"], e["detail"]["to"]) for e in ev] == \
        [(kid["Polish"], "Polish", "Polish Room")]
    assert _view_names() == [("Epoxy", "Epoxy"), ("Polish Room", "Polish Room"), ("Room 2", "Room 2")]


def test_the_board_reads_the_new_name(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    _put(store, "p1", **_renamed_polish())
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    cards = {s["id"]: s for s in drafts._build_summaries(trashed=False, limit=10)}
    assert cards[kid["Polish"]]["scope_label"] == "Polish Room"
    assert cards[kid["Copy1"]]["scope_label"] == "Room 2"


def test_the_strip_shows_the_sheet_name_before_any_save(fake_supabase, monkeypatch):
    """The strip reads the rule itself, so a sheet renamed by an older save (or a name typed before
    2026-10-29) shows its sheet's name at once; reading it writes nothing."""
    store, kid = _staging(fake_supabase, monkeypatch)
    _row(store, "p1")["data"].update(_renamed_polish())       # stored without going through a save
    _row(store, kid["Copy1"])["data"]["scope_group"]["label"] = "Kitchen"     # typed by hand
    _row(store, "p1")["data"]["scope_group"]["label"] = "Main"
    snapshot = copy.deepcopy(store["drafts"])
    assert _view_names() == [("Main", "Epoxy"), ("Polish", "Polish Room"), ("Kitchen", "Room 2")]
    assert store["drafts"] == snapshot


def test_a_name_typed_before_this_change_gives_way_to_the_sheet_on_the_next_save(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    _row(store, kid["Copy1"])["data"]["scope_group"]["label"] = "Kitchen"
    _row(store, "p1")["data"]["scope_group"]["label"] = "Base Bid 1 East"
    _put(store, "p1")
    assert [_label(store, x) for x in ("p1", kid["Polish"], kid["Copy1"])] == ["Epoxy", "Polish", "Room 2"]


def test_a_v2_section_renamed_on_the_estimate_renames_its_proposal(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, V2)
    out = drafts.fan_out_proposals("p1", ["Polish", "Copy1", "Epoxy"])
    lab2, lab1 = [c["id"] for c in out["children"]]
    assert [_label(store, x) for x in ("p1", lab2, lab1)] == ["Breakroom", "Lab 2", "Lab 1"]
    pe = copy.deepcopy(_row(store, "p1")["data"]["polish_estimate"])
    pe["label"] = "Polish Room"
    pe["tabs"]["Copy1"]["label"] = "Room 2"
    _put(store, "p1", polish_estimate=pe)
    assert [_label(store, x) for x in ("p1", lab2, lab1)] == ["Polish Room", "Room 2", "Lab 1"]
    assert _view_names() == [("Polish Room", "Polish Room"), ("Room 2", "Room 2"), ("Lab 1", "Lab 1")]


def test_two_sheets_of_one_name_stay_two_names(fake_supabase, monkeypatch):
    """The estimate pages refuse a duplicate sheet name, but a stored blob can hold one: the
    proposals are told apart by _free_label, in the strip's order."""
    store, kid = _staging(fake_supabase, monkeypatch)
    _put(store, "p1", tab_labels={"Copy1": "Polish"})
    assert [_label(store, x) for x in ("p1", kid["Polish"], kid["Copy1"])] == ["Epoxy", "Polish", "Polish 2"]
    assert [m["display_label"] for m in drafts.proposals_view("p1")["members"]] == ["Epoxy", "Polish", "Polish 2"]


def test_another_scopes_name_is_kept_free(fake_supabase, monkeypatch):
    """An RJ scope of the same project (not a proposal of this estimate) keeps its name, and a
    proposal whose sheet takes that name is numbered."""
    store, kid = _staging(fake_supabase, monkeypatch)
    gid = _row(store, "p1")["data"]["scope_group"]["id"]
    store["drafts"].append({"id": "rj1", "data": {"project_name": "Acme HQ", "is_test": True,
                                                  "scope_group": {"id": gid, "label": "Polish Room"}},
                            "owner_email": "k", "created_at": "2026-10-30", "updated_at": V,
                            "deleted_at": None})
    _put(store, "p1", **_renamed_polish())
    assert _label(store, kid["Polish"]) == "Polish Room 2"
    assert _label(store, "rj1") == "Polish Room"


def test_a_save_of_any_other_draft_asks_the_database_nothing_more(fake_supabase, monkeypatch):
    """The guard is read off the blob: a draft in no group, an RJ scope with no proposals and a
    proposal itself never read the group."""
    store, kid = _staging(fake_supabase, monkeypatch)

    reads = []
    real = drafts._group_rows

    def no_read(*a, **k):
        reads.append(a)
        return real(*a, **k)
    for rid, data in (("solo", {"project_name": "Solo"}),
                      ("rj", {"project_name": "RJ", "scope_group": {"id": "grp_rj", "label": "Lab"}})):
        store["drafts"].append({"id": rid, "data": data, "owner_email": "k", "created_at": "2026-10-30",
                                "updated_at": V, "deleted_at": None})
    monkeypatch.setattr(drafts, "_group_rows", no_read)
    _put(store, "solo", notes="x")
    _put(store, "rj", notes="x")
    _put(store, kid["Polish"], scope_notes="words")
    assert reads == [], "a save of a draft with no proposals read the scope group"
    _put(store, "p1")
    assert reads, "the control: a save of the estimate with proposals reads it"


def test_a_failed_rename_never_fails_the_save(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("database blip")
    monkeypatch.setattr(drafts, "_sync_names", boom)
    _put(store, "p1", **_renamed_polish())
    assert _row(store, "p1")["data"]["tab_labels"]["Polish"] == "Polish Room"
    assert _label(store, kid["Polish"]) == "Polish"


def _gen_names(view, frontend=None):
    """Step 3's rows (the real generate.js) for the server's strip `view`, re-keyed to the harness's
    drafts d1 / c2 / c3."""
    require_node()
    ids = ["d1", "c2", "c3"]
    members = [dict(m, id=ids[i], stale=False, out_of_step=None) for i, m in enumerate(view["members"])]
    env = dict(__import__("os").environ,
               GEN_NAMES_VIEW=json.dumps(dict(view, parent_id="d1", members=members)))
    args = ["node", str(GEN_HARNESS)] + ([str(frontend)] if frontend else [])
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=240, env=env)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])["names"]


def test_step_3_names_each_row_as_the_server_does_with_no_bracket(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    _row(store, "p1")["data"].update(_renamed_polish())       # the stored name is still "Polish"
    view = drafts.proposals_view("p1")
    g = _gen_names(view)
    assert g["rows"] == ["Epoxy", "Polish Room", "Room 2"]
    assert "Polish (Polish Room)" not in " ".join(g["text"]) and "gen-sheet" not in g["list"]
    assert [t for t in g["text"] if t.startswith("Polish")] == ["Polish Room"]


def test_step_3_with_its_old_bracket_goes_red(tmp_path, fake_supabase, monkeypatch):
    """The mutation proof of the one above: put the "(sheet)" bracket back and a numbered duplicate
    ("Polish 2" of sheet "Polish") prints it."""
    store, kid = _staging(fake_supabase, monkeypatch)
    _row(store, "p1")["data"]["tab_labels"] = {"Copy1": "Polish"}
    view = drafts.proposals_view("p1")
    assert [m["display_label"] for m in view["members"]] == ["Epoxy", "Polish", "Polish 2"]
    assert "gen-sheet" not in _gen_names(view)["list"]
    front = break_source(tmp_path, "js/generate.js", "      var name = esc(r.name)",
                         "      var name = esc(r.name) + (r.sheet && r.sheet !== r.name ? ' <span class=\"gen-sheet\">(' + esc(r.sheet) + \")</span>\" : \"\")")
    assert "gen-sheet" in _gen_names(view, front)["list"], "the mutation did not apply"


# ── B. renaming a proposal on its tab renames its sheet ────────────────────────────────────────
def _rename(rid, label, store):
    return client.post("/api/draft/%s/scope" % rid,
                       json={"label": label, "rename": True, "draft_version": _row(store, rid)["updated_at"]})


def test_a_childs_tab_rename_renames_its_sheet_on_the_estimate(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    parent_at = _row(store, "p1")["updated_at"]
    r = _rename(kid["Polish"], "Polish Room", store)
    assert r.status_code == 200, r.text
    j = r.json()
    parent = _row(store, "p1")["data"]
    assert parent["tab_labels"] == {"Copy1": "Room 2", "Polish": "Polish Room"}, "the estimate's tab says it"
    assert drafts._sheet_names(parent)["Polish"] == "Polish Room"
    assert {t["id"]: t["name"] for t in parent["priced_tabs"]}["Polish"] == "Polish Room"
    assert _row(store, "p1")["updated_at"] == parent_at
    assert _label(store, kid["Polish"]) == "Polish Room" and _label(store, "p1") == "Epoxy"
    assert (j["label"], j["parent_id"], j["sheet"]) == ("Polish Room", "p1", {"id": "Polish", "label": "Polish Room"})
    assert j["parent_patch"]["tab_labels"] == parent["tab_labels"]
    assert [m["display_label"] for m in j["proposals"]["members"]] == ["Epoxy", "Polish Room", "Room 2"]
    # The parent's next save carries the new name (its page took parent_patch): nothing reverts.
    _put(store, "p1")
    assert _label(store, kid["Polish"]) == "Polish Room"


def test_base_bid_1s_tab_rename_renames_its_own_sheet(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    r = _rename("p1", "Main Floor", store)
    assert r.status_code == 200, r.text
    assert _row(store, "p1")["data"]["tab_labels"]["Epoxy"] == "Main Floor"
    assert [_label(store, x) for x in ("p1", kid["Polish"], kid["Copy1"])] == ["Main Floor", "Polish", "Room 2"]
    assert r.json()["parent_patch"]["tab_labels"]["Epoxy"] == "Main Floor"


def test_a_v2_tab_rename_renames_the_section_and_the_root(fake_supabase, monkeypatch):
    store = _seed(fake_supabase, monkeypatch, V2)
    out = drafts.fan_out_proposals("p1", ["Polish", "Copy1", "Epoxy"])
    lab2, lab1 = [c["id"] for c in out["children"]]
    assert _rename(lab2, "Room 2", store).status_code == 200
    assert _rename("p1", "Polish Room", store).status_code == 200
    pe = _row(store, "p1")["data"]["polish_estimate"]
    assert (pe["label"], pe["tabs"]["Copy1"]["label"], pe["tabs"]["Epoxy"]["label"]) == ("Polish Room", "Room 2", "Lab 1")
    assert [_label(store, x) for x in ("p1", lab2, lab1)] == ["Polish Room", "Room 2", "Lab 1"]


@pytest.mark.parametrize("label,status,code", [
    ("Room 2", 409, "label_taken"),            # another sheet's name, any case
    ("room 2", 409, "label_taken"),
    ("Polish: Room", 400, "invalid_label"),    # a workbook refuses the colon
    ("x" * 32, 400, "invalid_label"),
    ("   ", 400, "invalid_label"),
])
def test_a_name_the_estimate_would_refuse_is_refused_and_nothing_changes(fake_supabase, monkeypatch,
                                                                         label, status, code):
    store, kid = _staging(fake_supabase, monkeypatch)
    before = copy.deepcopy(store["drafts"])
    r = _rename(kid["Polish"], label, store)
    assert (r.status_code, r.json()["code"]) == (status, code), r.text
    assert r.json()["error"]
    assert store["drafts"] == before


def test_a_parent_saved_again_meanwhile_is_not_overwritten(fake_supabase, monkeypatch):
    """The parent is written only if it is still the copy that was read (its updated_at)."""
    store, kid = _staging(fake_supabase, monkeypatch)
    real = drafts.load_draft

    def stale_parent(rid):
        row = real(rid)
        if rid == "p1" and row:
            row = dict(row, updated_at="2026-10-01T00:00:00+00:00")     # what this request read
        return row
    monkeypatch.setattr(drafts, "load_draft", stale_parent)
    before = copy.deepcopy(store["drafts"])
    r = _rename(kid["Polish"], "Polish Room", store)
    assert (r.status_code, r.json()["code"]) == (409, "parent_changed"), r.text
    assert r.json()["error"].startswith("Base Bid 1's estimate was saved again")
    assert store["drafts"] == before


def test_a_proposal_whose_estimate_is_gone_is_not_renamed(fake_supabase, monkeypatch):
    store, kid = _staging(fake_supabase, monkeypatch)
    _row(store, "p1")["deleted_at"] = "2026-10-29T00:00:00+00:00"
    r = _rename(kid["Polish"], "Polish Room", store)
    assert (r.status_code, r.json()["code"]) == (409, "parent_gone"), r.text


def test_a_scope_that_is_no_proposal_is_renamed_as_before(fake_supabase, monkeypatch):
    """RJ's scopes have no proposals: their name is their own (rename_scope), no sheet is touched."""
    store = _seed(fake_supabase, monkeypatch, dict(PARENT, scope_group={"id": "grp_rj", "label": "Lab"}))
    r = _rename("p1", "Lab 1", store)
    assert r.status_code == 200, r.text
    assert _label(store, "p1") == "Lab 1" and _row(store, "p1")["data"]["tab_labels"] == PARENT["tab_labels"]
    assert "proposals" not in r.json()


# ── C. a sent proposal: nobody is called at the rename, the next publish carries the name ─────
def test_a_sent_proposals_new_name_reaches_the_portal_only_at_its_next_publish(fake_supabase, monkeypatch):
    from test_scope_send_all import EST, World
    p = copy.deepcopy(PARENT)
    p.update(is_test=False, contact_email="buyer@acme.test", assigned_estimator=EST)
    w = World(fake_supabase, monkeypatch, [{"id": "p1", "data": p, "owner_email": EST,
                                            "created_at": "2026-10-01", "updated_at": V,
                                            "deleted_at": None}])
    out = drafts.fan_out_proposals("p1", ["Epoxy", "Polish", "Copy1"], "rj@x.test")
    kid = {c["base_tab_id"]: c["id"] for c in out["children"]}
    for rid in kid.values():
        _row(w.store, rid)["data"].update(generate_result={"work_type": "epoxy"},
                                          proposal_payload={"values": {"total_formatted": "$1"}})
    r = client.post("/api/portal/publish?draft_id=%s" % kid["Polish"], json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert r.json()["scope_label"] == "Polish"
    sent = len(w.publishes)
    # The rename: the drafts follow, the portal hears nothing and nobody is emailed.
    _put(w.store, "p1", **_renamed_polish())
    assert _label(w.store, kid["Polish"]) == "Polish Room"
    assert len(w.publishes) == sent and w.sends == []
    # The next publish: the revision the portal pins, and the name it is told, are the new one.
    r = client.post("/api/portal/publish?draft_id=%s" % kid["Polish"], json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert r.json()["scope_label"] == "Polish Room"
    assert w.revisions(kid["Polish"])[-1]["data"]["scope_group"]["label"] == "Polish Room"


def test_the_publish_renames_a_proposal_whose_sheet_was_renamed_without_a_save(fake_supabase, monkeypatch):
    """adopt_sheet_label, generalised: not only an old "Base Bid N", any stored name that is not the
    sheet's, every proposal of the estimate at once."""
    from test_scope_send_all import EST, World
    p = copy.deepcopy(PARENT)
    p.update(is_test=False, contact_email="buyer@acme.test", assigned_estimator=EST)
    w = World(fake_supabase, monkeypatch, [{"id": "p1", "data": p, "owner_email": EST,
                                            "created_at": "2026-10-01", "updated_at": V,
                                            "deleted_at": None}])
    out = drafts.fan_out_proposals("p1", ["Epoxy", "Polish", "Copy1"], "rj@x.test")
    kid = {c["base_tab_id"]: c["id"] for c in out["children"]}
    _row(w.store, kid["Polish"])["data"].update(generate_result={"work_type": "epoxy"},
                                                 proposal_payload={"values": {"total_formatted": "$1"}})
    _row(w.store, "p1")["data"].update(_renamed_polish())
    _row(w.store, kid["Copy1"])["data"]["scope_group"]["label"] = "Kitchen"
    r = client.post("/api/portal/publish?draft_id=%s" % kid["Polish"], json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert r.json()["scope_label"] == "Polish Room"
    assert [_label(w.store, x) for x in ("p1", kid["Polish"], kid["Copy1"])] == ["Epoxy", "Polish Room", "Room 2"]


def test_send_all_names_every_proposal_after_its_sheet_first(fake_supabase, monkeypatch):
    from test_scope_send_all import EST, GID, World
    p = copy.deepcopy(PARENT)
    p.update(is_test=False, contact_email="buyer@acme.test", assigned_estimator=EST,
             scope_group={"id": GID, "label": "Epoxy"})
    w = World(fake_supabase, monkeypatch, [{"id": "p1", "data": p, "owner_email": EST,
                                            "created_at": "2026-10-01", "updated_at": V,
                                            "deleted_at": None}])
    out = drafts.fan_out_proposals("p1", ["Epoxy", "Polish", "Copy1"], "rj@x.test")
    kid = {c["base_tab_id"]: c["id"] for c in out["children"]}
    for rid in ["p1"] + list(kid.values()):
        _row(w.store, rid)["data"].update(generate_result={"work_type": "epoxy"},
                                          proposal_payload={"values": {"total_formatted": "$1",
                                                                       "who": rid}})
    _row(w.store, "p1")["data"].update(_renamed_polish())
    r = client.post("/api/portal/scope-group/%s/send-all" % out["group_id"], json={})
    assert r.status_code == 200, r.text
    names = {x["id"]: x["label"] for x in r.json()["published"]}
    assert names[kid["Polish"]] == "Polish Room"
    assert len(w.sends) == 1
