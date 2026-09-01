"""Revision history endpoints — the staff-facing "what did we send them before".

Nothing binary is stored per revision: only the snapshot of the project state. The
documents are rebuilt from that snapshot's `proposal_payload` on demand, which is
what makes an old quote answerable with a real file rather than a number in a list.
"""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def _gen_out(docx_token="tok"):
    """A minimal valid GenerateOut — the model requires every field."""
    return main.GenerateOut(
        work_type="epoxy", audience="Direct",
        xlsx_download_url="/api/files/x",
        docx_download_url=f"/api/files/{docx_token}",
        pdf_download_url=f"/api/files/{docx_token}/pdf",
        totals={},
    )


def test_lists_revisions_newest_first(monkeypatch):
    monkeypatch.setattr(main.drafts, "list_revisions", lambda did: [
        {"revision_no": 2, "created_by": "kyle@wetreadwell.com", "created_at": "2026-07-31T00:00:00Z",
         "total": 28000.0, "project_name": "Westport", "has_documents": True},
        {"revision_no": 1, "created_by": "troy@wetreadwell.com", "created_at": "2026-07-20T00:00:00Z",
         "total": 27653.0, "project_name": "Westport", "has_documents": True},
    ])
    r = client.get("/api/draft/d1/revisions")
    assert r.status_code == 200, r.text
    revs = r.json()["revisions"]
    assert [x["revision_no"] for x in revs] == [2, 1]
    # The differing totals are the whole point of showing the history.
    assert revs[0]["total"] != revs[1]["total"]


def test_empty_history_is_not_an_error(monkeypatch):
    monkeypatch.setattr(main.drafts, "list_revisions", lambda did: [])
    r = client.get("/api/draft/d1/revisions")
    assert r.status_code == 200 and r.json()["revisions"] == []


def test_unsafe_draft_id_never_reaches_the_database(monkeypatch):
    """_safe_id guards the id before any lookup. A path-encoded slash may be
    rejected by routing rather than the handler, so assert on the outcome that
    matters: no 200, and list_revisions was never called."""
    called = []
    monkeypatch.setattr(main.drafts, "list_revisions", lambda did: called.append(did) or [])
    for bad in ("..%2Fevil", "a b", "x/y"):
        assert client.get(f"/api/draft/{bad}/revisions").status_code != 200
    assert called == []


def test_rebuilds_documents_from_the_snapshot(monkeypatch):
    """The regenerated files must come from the SNAPSHOT, never the live draft —
    that is the difference between "what we sent in March" and "what we'd send now"."""
    seen = {}
    snapshot_payload = {"values": {"project_name": "Westport"}, "work_type": "epoxy"}
    monkeypatch.setattr(main.drafts, "get_revision",
                        lambda did, no: {"revision_no": no, "data": {"proposal_payload": snapshot_payload}})

    def fake_generate(payload, request, *, persist=True, want_cover_letter=True):
        seen["values"] = payload.values
        seen["persist"] = persist
        seen["want_cover_letter"] = want_cover_letter
        return _gen_out()

    # `_generate`, not `api_generate`: the route is a thin wrapper that always persists, and the
    # replay callers deliberately go around it. Stubbing the wrapper intercepted nothing.
    monkeypatch.setattr(main, "_generate", fake_generate)
    r = client.post("/api/draft/d1/revisions/1/files", json={})
    assert r.status_code == 200, r.text
    assert seen["values"]["project_name"] == "Westport"
    assert seen["persist"] is False, (
        "replaying an old revision persisted its values — that writes March over the live draft")
    # EXECUTED, at the call site — the third opt-out, on the same terms as the other two: don't
    # build what you don't serve. The response model has a cover_letter_download_url and this
    # route returns it, but no caller reads it: done.js `downloadRevision` and portal.js both pick
    # from a hardcoded ("xlsx", "docx", "pdf") list, so there is no button for it in the product.
    # The historic letter already has its own route (/api/admin/cover-letter-pdf?revision_no=).
    # Building one here is pure downside: cover_letter_writer raises before the xlsx/docx reach
    # the cache, so a letter template that can't render 500s a revision download that would
    # otherwise have succeeded — and the letter templates are regenerated from Kyle's master by
    # hand (CoverLetter/README.md), so they can break while nothing else has.
    assert seen["want_cover_letter"] is False, (
        "a revision replay is building a cover letter nothing offers — a fault in it now fails "
        "the xlsx and docx download too")


def test_missing_revision_is_404(monkeypatch):
    monkeypatch.setattr(main.drafts, "get_revision", lambda did, no: None)
    assert client.post("/api/draft/d1/revisions/9/files", json={}).status_code == 404


def test_revision_without_generated_documents_is_422(monkeypatch):
    """Sent before the estimator ever pressed Generate. Inventing defaults would
    hand staff a document that was never sent to anyone."""
    monkeypatch.setattr(main.drafts, "get_revision",
                        lambda did, no: {"revision_no": no, "data": {"project_name": "Westport"}})
    r = client.post("/api/draft/d1/revisions/1/files", json={})
    assert r.status_code == 422


def test_proposal_pdf_renders_a_specific_revision(monkeypatch):
    """The portal passes the revision it pinned, so the PDF a customer downloads can
    never disagree with the prices on the page above it."""
    import os
    monkeypatch.setitem(os.environ, "SERVICE_TOKEN", "svc-test")
    monkeypatch.setattr(main.drafts, "get_revision",
                        lambda did, no: {"data": {"proposal_payload": {"values": {"project_name": "Snap"}}}})
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda did: {"data": {"proposal_payload": {"values": {"project_name": "LIVE"}}}})
    seen = {}

    def fake_generate(payload, request, *, persist=True, want_cover_letter=True):
        seen["name"] = payload.values.get("project_name")
        seen["persist"] = persist
        seen["want_cover_letter"] = want_cover_letter
        return _gen_out("tok")

    monkeypatch.setattr(main, "_generate", fake_generate)
    monkeypatch.setitem(main._FILE_CACHE, "tok", {"content": b"docx", "_pdf": b"%PDF-1.4"})
    r = client.get("/api/admin/proposal-pdf?draft_id=d1&revision_no=2",
                   headers={"X-Service-Token": "svc-test"})
    assert r.status_code == 200, r.text
    assert seen["name"] == "Snap"        # the snapshot, not the live draft
    assert seen["persist"] is False, "a customer's PDF render wrote to the estimator's draft"
    # EXECUTED, at the call site. This route returns the PROPOSAL pdf; the letter has its own
    # endpoint (/api/admin/cover-letter-pdf). A pinned revision whose payload has the box ticked
    # replays with it ticked, so without the gate a customer opening their proposal would build a
    # letter nobody reads here — and a fault in it would 500 the PDF the portal is waiting on.
    assert seen["want_cover_letter"] is False, (
        "the customer's proposal PDF is building a cover letter it never serves")


def test_proposal_pdf_without_revision_still_uses_the_live_draft(monkeypatch):
    """Legacy proposals have no pin; they must keep rendering as they always have."""
    import os
    monkeypatch.setitem(os.environ, "SERVICE_TOKEN", "svc-test")
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda did: {"data": {"proposal_payload": {"values": {"project_name": "LIVE"}}}})
    seen = {}

    def fake_generate(payload, request, *, persist=True, want_cover_letter=True):
        seen["name"] = payload.values.get("project_name")
        seen["persist"] = persist
        seen["want_cover_letter"] = want_cover_letter
        return _gen_out("tok2")

    monkeypatch.setattr(main, "_generate", fake_generate)
    monkeypatch.setitem(main._FILE_CACHE, "tok2", {"content": b"docx", "_pdf": b"%PDF-1.4"})
    r = client.get("/api/admin/proposal-pdf?draft_id=d1", headers={"X-Service-Token": "svc-test"})
    assert r.status_code == 200, r.text
    assert seen["name"] == "LIVE"
    assert seen["persist"] is False, "a customer's PDF render wrote to the estimator's draft"
