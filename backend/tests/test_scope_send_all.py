"""SEND ALL PROPOSALS IN ONE EMAIL (Hanz, 2026-10-27).

"When I send the proposals out it should send out without publishing. That's the point. And it must
come in one email only."

POST /api/portal/scope-group/{gid}/send-all publishes every live proposal of the project the customer
does not have at its current document, through the publish's own _prepare_publish/_commit_publish,
then asks the portal for the ONE combined email exactly once. Every proposal is checked before any is
published, so one that cannot go stops the press and nothing is published or sent. Fake store, fake
portal: no network, no database, no email.
"""
import copy
import json

import pytest
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)

GID = "grp_sendall00001"
EST = "kyle@wetreadwell.com"
CAPS = {"scope_groups": True, "group_followups": True, "version": 1}


def _draft(rid, label, created, files=True, gid=GID, **data):
    d = {"project_name": "Acme HQ", "work_type": "epoxy", "contact_email": "buyer@acme.test",
         "assigned_estimator": EST, "scope_group": {"id": gid, "label": label}}
    if files:
        d["generate_result"] = {"work_type": "epoxy"}
        d["proposal_payload"] = {"values": {"total_formatted": "$1,000", "who": rid}}
    d.update(data)
    return {"id": rid, "data": d, "owner_email": EST, "created_at": created,
            "updated_at": "2026-10-20T10:00:00+00:00", "deleted_at": None}


def _three(**over):
    rows = [_draft("s1", "Room 1", "2026-10-01"), _draft("s2", "Room 2", "2026-10-02"),
            _draft("s3", "Room 3", "2026-10-03")]
    for r in rows:
        r["data"].update(over.get(r["id"], {}))
    return rows


class World:
    """The fake store and the fake portal, and everything the press asked of them."""

    def __init__(self, fake_supabase, monkeypatch, rows, *, fail_publish=None, send_answers=None,
                 pipeline=None):
        self.pipeline = pipeline          # the portal's rows, or an exception to raise
        self.pipeline_asked = 0
        # The pipeline cache is module state: restored after the test so no other test inherits it.
        monkeypatch.setitem(main._PIPELINE_CACHE, "rows", None)
        monkeypatch.setitem(main._PIPELINE_CACHE, "fetched_at", None)
        self.store = {"drafts": [copy.deepcopy(r) for r in rows], "events": [],
                      "draft_revisions": [], "draft_revision_documents": []}
        self.publishes = []       # the bodies /api/admin/publish was sent, in order
        self.sends = []           # the bodies the combined send was sent
        self.caps_asked = 0
        self.fail_publish = fail_publish or set()
        self.send_answers = list(send_answers or [])
        monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(self.store))
        monkeypatch.setattr(main.drafts, "set_assigned_estimator", lambda *a, **k: True)
        monkeypatch.setattr(main, "_render_documents", lambda pp, req, want_estimate: {
            "docx": {"content": b"docx:" + main._canonical_sha256(pp).encode()},
            "xlsx": {"content": b"xlsx"} if want_estimate else None,
            "work_type": "epoxy", "audience": "Direct", "totals": {},
            "payload_sha256": main._canonical_sha256(pp),
            "render_id": "r-" + main._canonical_sha256(pp)[:8]})
        monkeypatch.setattr(main, "_entry_pdf", lambda entry: b"%PDF-1.4")
        monkeypatch.setattr(main, "_stale_document_refusal", lambda digest: None)

        def portal(path, method="GET", body=None):
            if path == "/api/admin/capabilities":
                self.caps_asked += 1
                return CAPS
            if path == "/api/admin/pipeline":
                self.pipeline_asked += 1
                if isinstance(self.pipeline, Exception):
                    raise self.pipeline
                return {"proposals": list(self.pipeline or [])}
            if path == "/api/admin/publish":
                if body["draft_id"] in self.fail_publish:
                    raise main.HTTPException(502, "Portal error.")
                self.publishes.append(body)
                return {"ok": True, "awaiting_group_send": True}
            raise AssertionError("unexpected portal call " + path)
        monkeypatch.setattr(main, "_portal", portal)

        async def raw(path, method, blob, ctype):
            assert path == "/api/admin/scope-group/%s/send" % GID and method == "POST"
            self.sends.append(json.loads(blob))
            status, answer = (self.send_answers.pop(0) if self.send_answers else
                              (200, {"ok": True, "results": [{"email": "buyer@acme.test",
                                                              "delivered": True}]}))
            return main.Response(content=json.dumps(answer).encode(), status_code=status,
                                 headers={"content-type": "application/json"})
        monkeypatch.setattr(main, "_portal_raw", raw)

    @property
    def published_ids(self):
        return [b["draft_id"] for b in self.publishes]

    def revisions(self, rid):
        return [r for r in self.store["draft_revisions"] if r["project_id"] == rid]


def _press(body=None):
    return client.post("/api/portal/scope-group/%s/send-all" % GID, json=body or {})


def test_every_unpublished_proposal_is_published_once_then_one_email(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three())
    r = _press({"message": "Here are your three proposals."})
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"], "each proposal is published exactly once"
    assert len(w.sends) == 1, "the customer gets ONE email"
    assert w.sends[0]["message"] == "Here are your three proposals."
    j = r.json()
    assert [p["id"] for p in j["published"]] == ["s1", "s2", "s3"]
    assert all(p["revision_no"] == 1 for p in j["published"])
    assert j["results"] == [{"email": "buyer@acme.test", "delivered": True}]
    # Each publish is the real publish body, from the drafts' own estimator and contact (the drawer
    # sends no recipients: the portal falls back to the contact email), and emails nobody itself.
    for b in w.publishes:
        assert b["assigned_estimator"] == EST and b["revision_no"] == 1
        assert "emails" not in b and "message" not in b


def test_a_proposal_the_customer_already_has_is_not_published_again(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three())
    # Room 1 went out before at the document it holds now.
    s1 = next(r for r in w.store["drafts"] if r["id"] == "s1")
    w.store["draft_revisions"].append({"project_id": "s1", "revision_no": 1,
                                       "data": copy.deepcopy(s1["data"])})
    r = _press()
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s2", "s3"]
    assert len(w.sends) == 1
    assert len(w.revisions("s1")) == 1, "an unchanged proposal got a new revision"


def test_a_proposal_whose_document_changed_since_it_was_published_is_published_again(
        fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three())
    s1 = next(r for r in w.store["drafts"] if r["id"] == "s1")
    old = copy.deepcopy(s1["data"])
    old["proposal_payload"]["values"]["total_formatted"] = "$900"
    w.store["draft_revisions"].append({"project_id": "s1", "revision_no": 1, "data": old})
    r = _press()
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"]
    assert len(w.sends) == 1


def test_one_never_built_proposal_asks_for_its_build_and_nothing_is_published(fake_supabase,
                                                                              monkeypatch):
    """Hanz, 2026-10-28: a third base bid made by Create Multiple Proposals has no document. The
    press answers needs_build, naming it, so the page builds it and presses again; nothing is
    published, minted, written or emailed meanwhile."""
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False)
    w = World(fake_supabase, monkeypatch, rows)
    before = copy.deepcopy(w.store["drafts"])
    r = _press()
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "needs_build"
    assert j["build"] == [{"id": "s2", "label": "Room 2"}]
    assert j["error"] == ("Nothing was sent. Room 2 has never been built. Open its Proposal step "
                          "and press Continue to Done, then send again.")
    assert w.publishes == [], "a half-ready project published its other proposals"
    assert w.store["draft_revisions"] == [], "a refused press minted a revision"
    assert w.sends == [], "a refused press emailed the customer"
    assert w.store["drafts"] == before, "a refused press wrote a draft"


def test_two_never_built_proposals_are_both_named(fake_supabase, monkeypatch):
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False)
    rows[2] = _draft("s3", "Room 3", "2026-10-03", files=False)
    w = World(fake_supabase, monkeypatch, rows)
    j = _press().json()
    assert j["code"] == "needs_build"
    assert [b["id"] for b in j["build"]] == ["s2", "s3"]
    assert j["error"].startswith("Nothing was sent. Room 2 and Room 3 have never been built. "
                                 "Open each one's Proposal step")
    assert w.publishes == [] and w.sends == []


def test_every_blocked_proposal_is_named_with_what_to_do(fake_supabase, monkeypatch):
    """A never-built proposal beside one that cannot go for another reason: the press says both,
    and building is not started (it could not end in a send)."""
    rows = _three()
    rows[0] = _draft("s1", "Room 1", "2026-10-01", files=False)
    rows[2]["data"]["assigned_estimator"] = ""
    rows[1]["data"]["assigned_estimator"] = ""
    rows[1]["data"]["contact_email"] = ""
    w = World(fake_supabase, monkeypatch, rows)
    # Room 3 has an estimator now only through the group (Room 1's), so it is not blocked for that.
    r = _press()
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "not_ready_to_send"
    assert j["error"] == ("Nothing was sent. Room 1: it has never been built; Send all builds it "
                          "for you once the others can go."
                          " Room 2: add a customer email on its Files page first.")
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [("s1", "needs_build"),
                                                             ("s2", "no_recipient")]
    assert w.publishes == [] and w.sends == []


def test_a_never_built_proposal_with_no_estimator_anywhere_is_not_built(fake_supabase,
                                                                         monkeypatch):
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False)
    for r in rows:
        r["data"]["assigned_estimator"] = ""
    w = World(fake_supabase, monkeypatch, rows)
    j = _press().json()
    assert j["code"] == "not_ready_to_send"
    assert {b["id"]: b["code"] for b in j["blocked"]}["s2"] == "no_estimator"
    assert w.publishes == [] and w.sends == []


def test_a_built_proposal_without_files_is_published_and_its_files_recorded(fake_supabase,
                                                                             monkeypatch):
    """Built (the door composed its document) but never downloaded: it needs no page. It is
    published, and its files are recorded on the draft as its Files page's Download records them."""
    rows = _three()
    del rows[1]["data"]["generate_result"]
    w = World(fake_supabase, monkeypatch, rows)
    r = _press()
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"] and len(w.sends) == 1
    s2 = next(x for x in w.store["drafts"] if x["id"] == "s2")["data"]
    assert s2["generate_result"]["render_id"] == "r-" + main._canonical_sha256(
        s2["proposal_payload"])[:8]
    # The others' own records are left as they were.
    s1 = next(x for x in w.store["drafts"] if x["id"] == "s1")["data"]
    assert s1["generate_result"] == {"work_type": "epoxy"}
    # THE SAME FILES ITS FILES PAGE'S DOWNLOAD HANDS OVER: POST /documents on the same draft.
    d = client.post("/api/draft/s2/documents", json={})
    assert d.status_code == 200, d.text
    assert d.json()["render_id"] == s2["generate_result"]["render_id"]
    tok = lambda url: url.rsplit("/", 1)[-1]
    assert (main._FILE_CACHE[tok(d.json()["docx_download_url"])]["content"]
            == main._FILE_CACHE[tok(s2["generate_result"]["docx_download_url"])]["content"])


def test_a_member_with_files_is_not_rebuilt_or_rerecorded(fake_supabase, monkeypatch):
    """A proposal that HAS its document and files is untouched by the new path: published from its
    own payload, its generate_result never rewritten, and today's refusals still fire for it."""
    w = World(fake_supabase, monkeypatch, _three())
    renders = []
    real = main._render_documents
    monkeypatch.setattr(main, "_render_documents", lambda pp, req, want_estimate: (
        renders.append(want_estimate), real(pp, req, want_estimate=want_estimate))[1])
    r = _press()
    assert r.status_code == 200, r.text
    assert renders == [False, False, False], "a member with files had its workbook rebuilt"
    for x in w.store["drafts"]:
        assert x["data"]["generate_result"] == {"work_type": "epoxy"}


def test_after_the_build_the_second_press_sends_everything_in_one_email(fake_supabase,
                                                                        monkeypatch):
    """THE CASE, server half: the first press asks for Room 2's build; the Proposal step's door
    composes its document (a payload, no files: continueToDone never visits its Files page in the
    chain); the press made again publishes all three, records Room 2's files, and sends ONE email."""
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False)
    w = World(fake_supabase, monkeypatch, rows)
    first = _press({"message": "All three."})
    assert first.status_code == 409 and first.json()["code"] == "needs_build"
    s2 = next(x for x in w.store["drafts"] if x["id"] == "s2")
    s2["data"]["proposal_payload"] = {"values": {"total_formatted": "$2,000", "who": "s2"}}
    again = _press({"message": "All three."})
    assert again.status_code == 200, again.text
    assert w.published_ids == ["s1", "s2", "s3"], "each proposal is published exactly once"
    assert len(w.sends) == 1 and w.sends[0]["message"] == "All three."
    assert s2["data"]["generate_result"]["render_id"]
    assert [len(w.revisions(i)) for i in ("s1", "s2", "s3")] == [1, 1, 1]


def test_a_proposal_with_no_estimator_anywhere_is_blocked(fake_supabase, monkeypatch):
    rows = _three()
    for r in rows:
        r["data"]["assigned_estimator"] = ""
    w = World(fake_supabase, monkeypatch, rows)
    r = _press()
    assert r.status_code == 409
    assert "Room 1: choose its assigned estimator on its Files page first." in r.json()["error"]
    assert w.publishes == [] and w.sends == []


def test_a_document_that_does_not_match_its_price_blocks_the_press(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three())
    monkeypatch.setattr(main, "_stale_document_refusal", lambda digest: (
        {"ok": False, "code": main.STALE_DOCUMENT_CODE, "error": "x", "differences": ["price"]}
        if (digest.get("project_name") or "") == "never" else None))
    real = main._publish_digest
    monkeypatch.setattr(main, "_publish_digest", lambda data: dict(
        real(data), project_name="never" if data["scope_group"]["label"] == "Room 3" else ""))
    r = _press()
    assert r.status_code == 409, r.text
    assert r.json()["error"] == ("Nothing was sent. Room 3: its document does not match its price. "
                                 "Open its Proposal step, press Continue, then send again.")
    assert w.publishes == [] and w.sends == []


def test_a_portal_publish_failure_midway_sends_no_email(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three(), fail_publish={"s2"})
    r = _press()
    assert r.status_code == 502, r.text
    j = r.json()
    assert j["code"] == "publish_failed" and j["failed"] == {"id": "s2", "label": "Room 2"}
    assert [p["id"] for p in j["published"]] == ["s1"]
    assert j["error"].startswith("Nothing was emailed. Room 2 could not be published")
    assert "Room 1 was published and will go in the email." in j["error"]
    assert w.sends == [], "a failed publish still emailed the customer"
    assert w.published_ids == ["s1"], "the press went on past the failure"
    assert w.revisions("s2") == [], "the failed publish kept its revision"


def test_a_second_press_with_nothing_new_is_the_portals_nothing_to_send(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three(),
              send_answers=[(200, {"ok": True, "results": [{"email": "buyer@acme.test",
                                                            "delivered": True}]}),
                            (409, {"ok": False, "error": "nothing_to_send"})])
    assert _press().status_code == 200
    assert w.published_ids == ["s1", "s2", "s3"]
    again = _press()
    assert again.status_code == 409, again.text
    assert again.json()["error"] == "nothing_to_send" and again.json()["published"] == []
    assert w.published_ids == ["s1", "s2", "s3"], "the second press published again"
    assert len(w.sends) == 2


def test_a_test_and_a_real_proposal_in_one_project_are_refused_before_anything(fake_supabase,
                                                                                 monkeypatch):
    rows = _three()
    rows[2]["data"]["is_test"] = True
    w = World(fake_supabase, monkeypatch, rows)
    r = _press()
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "test_mix" and r.json()["error"].startswith("Nothing was sent. ")
    assert w.publishes == [] and w.sends == [] and w.caps_asked == 0
    assert w.store["draft_revisions"] == []


def test_the_files_page_choices_ride_every_proposal_it_publishes(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three())
    r = _press({"draft_id": "s2", "message": "hi",
                "publish": {"emails": ["buyer@acme.test", "pm@acme.test"],
                            "assigned_estimator": "rj@wetreadwell.com", "require_deposit": False,
                            "no_followups": ["pm@acme.test"],
                            "draft_version": "2026-10-20T10:00:00+00:00"}})
    assert r.status_code == 200, r.text
    by = {b["draft_id"]: b for b in w.publishes}
    assert set(by) == {"s1", "s2", "s3"}
    for b in by.values():
        assert b["emails"] == ["buyer@acme.test", "pm@acme.test"]
        assert b["assigned_estimator"] == "rj@wetreadwell.com"
        assert b["no_followups"] == ["pm@acme.test"]
    # The page's own deposit choice is its proposal's; each other one gets what its own Files page
    # would tick: on for Direct work that never chose.
    assert by["s2"]["require_deposit"] is False
    assert by["s1"]["require_deposit"] is True and by["s3"]["require_deposit"] is True
    assert w.sends == [{"by": w.sends[0]["by"], "message": "hi"}]


def test_the_files_page_copy_saved_again_since_stops_the_press(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three())
    r = _press({"draft_id": "s2", "publish": {"assigned_estimator": EST,
                                              "draft_version": "an older save"}})
    assert r.status_code == 409, r.text
    assert r.json()["error"] == ("Nothing was sent. Room 2: it changed after this page read it. "
                                 "Reload, check it, then send again.")
    assert w.publishes == [] and w.sends == []


def test_a_page_whose_proposal_left_the_project_is_refused(fake_supabase, monkeypatch):
    rows = _three() + [_draft("solo", "Solo", "2026-10-04", gid="grp_other000001")]
    w = World(fake_supabase, monkeypatch, rows)
    r = _press({"draft_id": "solo", "publish": {"assigned_estimator": EST}})
    assert r.status_code == 400 and r.json()["code"] == "not_in_group"
    assert w.publishes == [] and w.sends == []


@pytest.mark.parametrize("caps", [{}, {"scope_groups": True}])
def test_a_portal_not_ready_for_one_email_gets_nothing(fake_supabase, monkeypatch, caps):
    w = World(fake_supabase, monkeypatch, _three())
    monkeypatch.setattr(main, "_portal_capabilities", lambda: caps)
    r = _press()
    assert r.status_code == 409 and r.json()["code"] == "portal_not_ready"
    assert w.publishes == [] and w.sends == []


def test_a_bad_group_id_is_refused():
    r = client.post("/api/portal/scope-group/has%20space/send-all", json={})
    assert r.status_code == 400 and r.json()["code"] == "invalid_scope_group"


def test_an_ungrouped_publish_is_unchanged(fake_supabase, monkeypatch):
    """The refactor into _prepare_publish/_commit_publish leaves the ordinary publish's body, its
    revision and its answer as they were."""
    w = World(fake_supabase, monkeypatch, [])
    solo = _draft("solo", "x", "2026-10-01")
    del solo["data"]["scope_group"]
    w.store["drafts"].append(solo)
    r = client.post("/api/portal/publish?draft_id=solo",
                    json={"assigned_estimator": EST, "emails": ["buyer@acme.test"],
                          "message": "hello", "require_deposit": True})
    assert r.status_code == 200, r.text
    assert w.caps_asked == 0 and w.sends == []
    (b,) = w.publishes
    assert b == {"draft_id": "solo", "by": b["by"], "created_by": EST,
                 "emails": ["buyer@acme.test"], "message": "hello", "require_deposit": True,
                 "assigned_estimator": EST, "revision_no": 1}
    assert r.json()["revision_no"] == 1 and "scope_group" not in r.json()
    assert len(w.revisions("solo")) == 1


# ─── a proposal the customer already decided on is never republished by a neighbour's press ──
def _sent_before_and_changed(w, rid):
    """`rid` went out as revision 1, and its document has changed since."""
    row = next(r for r in w.store["drafts"] if r["id"] == rid)
    old = copy.deepcopy(row["data"])
    old["proposal_payload"]["values"]["total_formatted"] = "$900"
    w.store["draft_revisions"].append({"project_id": rid, "revision_no": 1, "data": old})


@pytest.mark.parametrize("portal_row, words", [
    ({"proposal_status": "approved", "approved_at": "2026-10-20T10:00:00Z"},
     "Room 1: the customer already approved it; send its revision from its own Files page."),
    ({"proposal_status": "approved", "deposit_status": "received"},
     "Room 1: the customer already paid its deposit; send its revision from its own Files page."),
    ({"proposal_status": "closed_lost"},
     "Room 1: it is closed as lost; reopen it and send its revision from its own Files page."),
])
def test_a_decided_proposal_whose_document_changed_blocks_the_press(fake_supabase, monkeypatch,
                                                                     portal_row, words):
    w = World(fake_supabase, monkeypatch, _three(),
              pipeline=[dict(portal_row, proposal_id="s1")])
    _sent_before_and_changed(w, "s1")
    r = _press({"draft_id": "s2", "publish": {"assigned_estimator": EST}})
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "not_ready_to_send"
    assert words in j["error"], j["error"]
    assert [b["id"] for b in j["blocked"]] == ["s1"]
    assert w.publishes == [], "a decided proposal's neighbours were published anyway"
    assert w.sends == [], "the customer was emailed a cancelled approval"
    assert len(w.revisions("s1")) == 1, "the approved proposal got a new revision"


def test_the_pages_own_decided_proposal_goes_through(fake_supabase, monkeypatch):
    """Its own Files page is where a revision of an approved proposal is sent from."""
    w = World(fake_supabase, monkeypatch, _three(),
              pipeline=[{"proposal_id": "s1", "proposal_status": "approved"}])
    _sent_before_and_changed(w, "s1")
    r = _press({"draft_id": "s1", "publish": {"assigned_estimator": EST}})
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"]
    assert w.pipeline_asked == 0, "nothing else needed republishing, so the portal was not asked"


def test_a_sent_undecided_proposal_whose_document_changed_is_republished(fake_supabase,
                                                                          monkeypatch):
    w = World(fake_supabase, monkeypatch, _three(),
              pipeline=[{"proposal_id": "s1", "proposal_status": "viewed"}])
    _sent_before_and_changed(w, "s1")
    r = _press()
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"] and w.pipeline_asked == 1
    assert len(w.sends) == 1


def test_a_portal_that_cannot_say_who_approved_blocks_a_republish(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three(),
              pipeline=main.HTTPException(502, "Portal error."))
    _sent_before_and_changed(w, "s1")
    r = _press()
    assert r.status_code == 409, r.text
    assert "Room 1: the portal could not say whether the customer already approved it"         in r.json()["error"]
    assert w.publishes == [] and w.sends == []


# ─── each other proposal gets its own deposit choice ──
def test_a_gc_proposal_published_by_a_neighbour_asks_no_deposit(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _three(s1={"audience": "GC"}, s3={"audience": "GC",
                                                                             "require_deposit": True}))
    r = _press({"draft_id": "s2", "publish": {"assigned_estimator": EST, "require_deposit": False}})
    assert r.status_code == 200, r.text
    by = {b["draft_id"]: b for b in w.publishes}
    assert by["s1"]["require_deposit"] is False, "a GC scope was asked for a 25% deposit"
    assert by["s3"]["require_deposit"] is True, "its own stored choice was overridden"
    assert by["s2"]["require_deposit"] is False


def test_a_republished_neighbour_with_no_stored_choice_keeps_the_portals(fake_supabase,
                                                                          monkeypatch):
    w = World(fake_supabase, monkeypatch, _three(s1={"audience": "GC"}),
              pipeline=[{"proposal_id": "s1", "proposal_status": "sent"}])
    _sent_before_and_changed(w, "s1")
    r = _press({"draft_id": "s2", "publish": {"assigned_estimator": EST}})
    assert r.status_code == 200, r.text
    by = {b["draft_id"]: b for b in w.publishes}
    assert "require_deposit" not in by["s1"]


# ─── what the Proposal step's tab says is asked before the press builds a proposal unattended ──
# Review of the build-what-was-never-built change: a proposal of Create Multiple Proposals whose tab
# says "Estimate changed" or "same sheet as Base Bid 1" was built from its old copy and emailed,
# because the walk opens its Proposal step with nobody looking. Real fan-out children, real
# drafts.proposals_view.
def _fanned(fake_supabase, monkeypatch, parent, bases):
    """A World holding `parent` (built, with files) and the never-built children Create Multiple
    Proposals makes for `bases`; returns (world, group id, child ids)."""
    import test_multi_proposals as tmp
    p = copy.deepcopy(parent)
    p["is_test"] = False
    w = World(fake_supabase, monkeypatch, [{"id": "p1", "data": p, "owner_email": EST,
                                            "created_at": "2026-10-01", "updated_at": tmp.V,
                                            "deleted_at": None}])
    out = drafts.fan_out_proposals("p1", list(bases), "rj@x.test")
    kids = [c["id"] for c in out["children"]]
    for k in kids:
        row = next(r for r in w.store["drafts"] if r["id"] == k)
        assert not (row["data"].get("proposal_payload") or {}).get("values"), "a child came built"
    return w, out["group_id"], kids


def _press_group(gid, body=None):
    return client.post("/api/portal/scope-group/%s/send-all" % gid, json=body or {})


def test_a_fresh_never_built_child_still_asks_for_its_build(fake_supabase, monkeypatch):
    """The control: a child whose tab warns about nothing is needs_build, as before."""
    import test_multi_proposals as tmp
    w, gid, kids = _fanned(fake_supabase, monkeypatch, tmp.PARENT, ("Epoxy", "Copy1"))
    j = _press_group(gid).json()
    assert j["code"] == "needs_build", j
    assert [b["id"] for b in j["build"]] == kids
    assert w.publishes == [] and w.sends == []


def test_a_stale_never_built_child_is_not_built_and_starts_no_walk(fake_supabase, monkeypatch):
    """The parent's estimate changed after Room 2 was copied: its tab says "Estimate changed". The
    press must not build it from its old copy and email that price."""
    import test_multi_proposals as tmp
    w, gid, kids = _fanned(fake_supabase, monkeypatch, tmp.PARENT, ("Epoxy", "Copy1"))
    parent = next(r for r in w.store["drafts"] if r["id"] == "p1")
    parent["data"]["cell_values"]["Copy1!E20"] = 3100
    assert [m["stale"] for m in drafts.proposals_view("p1")["members"]] == [False, True]
    r = _press_group(gid)
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "not_ready_to_send", "a stale proposal started an unattended build"
    assert "build" not in j
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [(kids[0], "needs_refresh")]
    assert ("Room 2: the estimate changed after it was copied; press Refresh on its Proposal step "
            "first.") in j["error"], j["error"]
    assert w.publishes == [] and w.sends == [] and w.store["draft_revisions"] == []


def test_a_same_as_base_never_built_child_is_not_built(fake_supabase, monkeypatch):
    """A Base Bid 1 swap left the child on Base Bid 1's sheet: its tab says "same sheet as Base Bid
    1: press Refresh". Built unattended it would be a second copy of the parent's price."""
    import test_multi_proposals as tmp
    w, gid, kids = _fanned(fake_supabase, monkeypatch, tmp.POLISH_FIRST, ("Polish", "Epoxy"))
    parent = next(r for r in w.store["drafts"] if r["id"] == "p1")
    parent["data"].update(base_tab_id="Epoxy", base_tab_ids=["Epoxy", "Polish"],
                          proposal_lump_sum=20000)
    assert [m["out_of_step"] for m in drafts.proposals_view("p1")["members"]] == [None,
                                                                                  "same_as_base"]
    r = _press_group(gid)
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "not_ready_to_send", "an out-of-step proposal started an unattended build"
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [(kids[0], "needs_refresh")]
    assert ("it prices no base bid of its own (same sheet as Base Bid 1); press Refresh on its "
            "Proposal step first.") in j["error"], j["error"]
    assert w.publishes == [] and w.sends == []


@pytest.mark.parametrize("mark, code", [
    ({"closed_lost": {"reason": "price", "by": EST, "at": "2026-10-20", "note": "went elsewhere"}},
     "closed_lost"),
    ({"on_hold": {"reason": "on_hold", "note": "owner paused", "by": EST, "at": "2026-10-20",
                  "until": "2026-11-20"}}, "on_hold"),
])
@pytest.mark.parametrize("files", ["never_built", "built_no_files"])
def test_a_proposal_closed_or_paused_on_the_board_is_never_built_or_sent(fake_supabase, monkeypatch,
                                                                         mark, code, files):
    """Before the press built proposals itself, one without files stopped it. A proposal closed lost
    or on hold on the board must still stop it, not be built and emailed by its neighbours' press."""
    rows = _three()
    if files == "never_built":
        rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False)
    else:
        del rows[1]["data"]["generate_result"]
    rows[1]["data"].update(copy.deepcopy(mark))
    w = World(fake_supabase, monkeypatch, rows)
    r = _press()
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "not_ready_to_send", j
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [("s2", code)]
    assert w.publishes == [] and w.sends == [] and w.store["draft_revisions"] == []


# ─── Kyle's placeholders are never sent unattended (Hanz, 2026-10-28) ──
# A GC proposal's defaults are Kyle's file with its blanks in it ("xx gallons/kits", "[ 1 mob/phase ]",
# "-or-" choices, "xx Architects", the Sealer's "03xx"). Send all's walk builds a proposal nobody
# opened, so one that would print them is held, and the press says which and what to do.
GC_HELD = ("Nothing was sent. Room 2: its scope still has template placeholders (xx gallons, xx kits, "
           "[ 1 mob/phase ], xx Architects). Open its Proposal step, fill them, then send again.")


def _gc_never_built(**data):
    return _draft("s2", "Room 2", "2026-10-02", files=False, audience="GC", **data)


def test_a_never_built_gc_proposal_with_placeholders_is_held_before_any_walk(fake_supabase,
                                                                            monkeypatch):
    rows = _three()
    rows[1] = _gc_never_built()
    w = World(fake_supabase, monkeypatch, rows)
    before = copy.deepcopy(w.store["drafts"])
    r = _press()
    assert r.status_code == 409, r.text
    j = r.json()
    assert j["code"] == "not_ready_to_send", "a proposal that would print placeholders was walked"
    assert "build" not in j
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [("s2", "placeholders")]
    assert j["error"] == GC_HELD
    assert w.publishes == [] and w.sends == [] and w.store["draft_revisions"] == []
    assert w.store["drafts"] == before, "a held press wrote a draft"


def test_a_gc_sealer_names_its_choices_and_spec(fake_supabase, monkeypatch):
    rows = _three()
    rows[1] = _gc_never_built(work_type="sealer", architect="Gould Evans")
    w = World(fake_supabase, monkeypatch, rows)
    j = _press().json()
    assert j["code"] == "not_ready_to_send"
    assert ("Room 2: its scope still has template placeholders ([ 1 mob/phase ], -or- choices, "
            "03xx).") in j["error"], j["error"]
    assert w.publishes == []


def test_a_never_built_gc_proposal_whose_words_are_filled_is_still_built(fake_supabase,
                                                                        monkeypatch):
    """The control: nothing of Kyle's left to fill, so the press asks for its build as before."""
    rows = _three()
    rows[1] = _gc_never_built(scope_notes="Install 3/16in Resinous System. 12 kits of patch.",
                              schedule_notes="2 mobs. Approx. 1 week.", architect="Gould Evans")
    w = World(fake_supabase, monkeypatch, rows)
    j = _press().json()
    assert j["code"] == "needs_build", j
    assert w.publishes == []


def test_a_never_built_direct_proposal_is_still_built(fake_supabase, monkeypatch):
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False)
    World(fake_supabase, monkeypatch, rows)
    assert _press().json()["code"] == "needs_build"


def _walk_built(values, **data):
    """Room 2 as Send all's walk left it: a document, no files, `proposal_auto_built`."""
    rows = _three()
    rows[1] = _draft("s2", "Room 2", "2026-10-02", files=False, audience="GC",
                     proposal_auto_built=True, **data)
    rows[1]["data"]["proposal_payload"] = {"work_type": "epoxy", "audience": "GC",
                                           "values": dict(values, total_formatted="$2,000")}
    return rows


def test_a_walk_built_proposal_that_prints_placeholders_is_not_sent(fake_supabase, monkeypatch):
    """THE CASE: the first press walked Room 2; the document the walk composed still prints Kyle's
    blanks (blank words print the GC defaults), and the second press holds it."""
    w = World(fake_supabase, monkeypatch, _walk_built({"scope_notes": "", "schedule_notes": "",
                                                       "architect": ""}))
    r = _press({"message": "All three."})
    assert r.status_code == 409, r.text
    j = r.json()
    assert [(b["id"], b["code"]) for b in j["blocked"]] == [("s2", "placeholders")]
    assert j["error"] == GC_HELD
    assert w.publishes == [] and w.sends == [] and w.store["draft_revisions"] == []


def test_a_walk_built_proposal_with_typed_placeholders_is_held(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _walk_built({
        "scope_notes": "Apply [1 coat -or- up to 2 coats of sealer", "schedule_notes": "1 week",
        "architect": "Gould", "spec_section": "03xx"}))
    j = _press().json()
    assert "(-or- choices, 03xx)" in j["error"], j["error"]
    assert w.publishes == []


def test_a_walk_built_proposal_without_placeholders_goes(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _walk_built({
        "scope_notes": "Install Resinous System. 12 kits of patch included.",
        "schedule_notes": "2 mobs, approx. 1 week", "architect": "Gould Evans"}))
    r = _press()
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"] and len(w.sends) == 1


def test_a_proposal_a_person_composed_is_theirs_to_send_as_written(fake_supabase, monkeypatch):
    """No mark: somebody opened its Proposal step and pressed Continue, and read what it says."""
    rows = _walk_built({"scope_notes": "", "schedule_notes": "", "architect": ""})
    rows[1]["data"]["proposal_auto_built"] = False
    w = World(fake_supabase, monkeypatch, rows)
    r = _press()
    assert r.status_code == 200, r.text
    assert w.published_ids == ["s1", "s2", "s3"]


def test_the_placeholder_list_is_kyles_own_words():
    """Each placeholder the press names is in the GC defaults or the GC template words it guards."""
    words = "\n".join([main._DEFAULT_SCOPE_GC_RESINOUS, main._DEFAULT_SCOPE_GC_SEALER,
                       main._DEFAULT_SCHEDULE_GC]
                      + [v for t in main.proposal_writer.TEMPLATE_TOKEN_DEFAULTS.values()
                         for v in t.values()])
    for shown, rx in main._PLACEHOLDERS:
        assert rx.search(words), shown
    # And none of the Direct defaults trips it: a Direct proposal is never held for its defaults.
    assert main._placeholders_in({}, "epoxy", "Direct") == []
    assert main._placeholders_in({}, "polish", "Direct") == []
    assert main._placeholders_in({}, "polish", "GC") == ["[ 1 mob/phase ]", "xx Architects"]


# ─── a proposal still named "Base Bid N" is named after its sheet when it is published ──
def _old_named(label="Base Bid 2", sheet="Breakroom"):
    rows = _three()
    rows[1]["data"]["scope_group"]["label"] = label
    rows[1]["data"].update(base_tab_id="Copy1", tab_labels={"Copy1": sheet},
                           priced_tabs=[{"id": "Copy1", "name": sheet, "role": "epoxy"}])
    return rows


def _label_of(w, rid):
    return next(r for r in w.store["drafts"] if r["id"] == rid)["data"]["scope_group"]["label"]


def test_send_all_stores_the_sheet_name_before_publishing(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _old_named())
    r = _press()
    assert r.status_code == 200, r.text
    assert _label_of(w, "s2") == "Breakroom", "the customer would read Base Bid 2"
    assert {p["id"]: p["label"] for p in r.json()["published"]}["s2"] == "Breakroom"
    (rev,) = w.revisions("s2")
    assert rev["data"]["scope_group"]["label"] == "Breakroom", "the snapshot kept the old name"
    ev = [e for e in w.store["events"] if e.get("action") == "scope_renamed"]
    assert [(e["detail"]["from"], e["detail"]["to"]) for e in ev] == [("Base Bid 2", "Breakroom")]
    # The others were named by a person and keep their names.
    assert (_label_of(w, "s1"), _label_of(w, "s3")) == ("Room 1", "Room 3")


def test_the_single_publish_stores_the_sheet_name(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _old_named())
    r = client.post("/api/portal/publish?draft_id=s2", json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert _label_of(w, "s2") == "Breakroom"
    assert r.json()["scope_label"] == "Breakroom"


def test_a_typed_name_is_never_replaced(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _old_named(label="Upstairs"))
    assert _press().status_code == 200
    assert _label_of(w, "s2") == "Upstairs"
    assert not [e for e in w.store["events"] if e.get("action") == "scope_renamed"]


def test_a_sheet_name_another_proposal_has_is_numbered(fake_supabase, monkeypatch):
    w = World(fake_supabase, monkeypatch, _old_named(sheet="Room 1"))
    assert _press().status_code == 200
    assert _label_of(w, "s2") == "Room 1 2"


def test_a_refused_press_renames_nothing_but_says_the_sheet_name(fake_supabase, monkeypatch):
    rows = _old_named()
    rows[1]["data"]["contact_email"] = ""
    w = World(fake_supabase, monkeypatch, rows)
    r = _press()
    assert r.status_code == 409, r.text
    assert "Breakroom: add a customer email on its Files page first." in r.json()["error"]
    assert _label_of(w, "s2") == "Base Bid 2"
