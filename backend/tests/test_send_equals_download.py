"""Send is the Download: one render, and a sent revision's PDF is frozen.

Hanz, 2026-09-25: "Sending out the proposal should be the same PDF from the download button in the
last page." / "When creating a revision and sending out to the portal ... it doesnt show the
correct proposal."

Two renders, by construction. The Files page's Download fetched the token kept in
`generate_result` — files built from whatever payload the last generate had been handed, alive for
up to an hour — while Send pinned the SAVED `proposal_payload` and the portal re-rendered that on
every view, through whatever code was deployed that day. Now:

  * one server function, `_render_documents`, renders a saved payload for the Files page's
    buttons (/api/draft/{id}/documents), Send, the customer's PDF and a revision's file links,
    keyed on the payload, the templates and the code (`_render_key`). A Download and a Send under
    one key are the same document; while the render is cached they are the same BYTES, and a Send
    carrying the key of the Download it follows is refused if the key has moved since;
  * a send stores the .docx and PDF it went out with (draft_revision_documents), and the
    customer's PDF route serves those bytes from then on;
  * the render reads nothing off the request, so a replay with nobody signed in is the document
    the signed-in estimator sent.

EXECUTED, NOT READ. Every test drives the real routes and the real renderer (python-docx, the
real templates). Only three things are doubled, each for a stated reason: LibreOffice (not on a
CI runner) by a function that NEVER RETURNS THE SAME BYTES TWICE — the way LibreOffice stamps a
creation time — so equal PDFs can only mean one render was reused; the portal (another service);
and the database, by the conftest FakeClient behind the REAL drafts.py functions, with revision
numbering done here because the fake's order() is a no-op.
"""
import copy
import hashlib
import io
import re
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import drafts
import main

client = TestClient(main.app)
SVC = {"X-Service-Token": "svc-test"}
EST = "kyle@wetreadwell.com"

PAYLOAD = {
    "work_type": "epoxy", "audience": "Direct",
    "values": {"project_name": "Send Equals Download", "job_name": "Send Equals Download",
               "city_state": "Lenexa, KS", "epoxy_sf": "1000",
               "total_formatted": "$10,000.00", "lump_sum_formatted": "$10,000.00",
               "estimator_name": "Kyle Loseke", "estimator_email": EST,
               "texture": "Orange Peel"},
}


@pytest.fixture
def world(monkeypatch, fake_supabase):
    store = {"drafts": [{"id": "d1", "owner_email": EST,
                         "data": {"project_name": "Send Equals Download", "rooms": [],
                                  "proposal_payload": copy.deepcopy(PAYLOAD)}}]}
    fake = fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)

    def create_revision(did, data, created_by=None):
        revs = [r for r in store.setdefault("draft_revisions", []) if r["project_id"] == did]
        no = max([r["revision_no"] for r in revs] or [0]) + 1
        # A deep copy, as the real jsonb column is: a later edit of the draft cannot reach back
        # into a snapshot.
        store["draft_revisions"].append({"project_id": did, "revision_no": no,
                                         "data": copy.deepcopy(data), "created_by": created_by})
        return no

    monkeypatch.setattr(drafts, "create_revision", create_revision)
    monkeypatch.setattr(drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setenv("SERVICE_TOKEN", "svc-test")

    renders = []

    def fake_pdf(docx_bytes):
        renders.append(docx_bytes)
        return (b"%PDF-1.4 render #" + str(len(renders)).encode() + b" of "
                + hashlib.sha256(docx_bytes).hexdigest().encode())

    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", fake_pdf)

    portal = {"calls": [], "fail": False}

    def fake_portal(path, method="GET", body=None):
        portal["calls"].append((path, body))
        if portal["fail"]:
            raise main.HTTPException(502, "portal down")
        return {"ok": True}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return SimpleNamespace(store=store, renders=renders, portal=portal,
                           payload=store["drafts"][0]["data"]["proposal_payload"])


def _documents():
    r = client.post("/api/draft/d1/documents", json={})
    assert r.status_code == 200, r.text
    return r.json()


def _download(kind="pdf_download_url"):
    f = client.get(_documents()[kind])
    assert f.status_code == 200, f.text
    return f.content


def _send():
    r = client.post("/api/portal/publish?draft_id=d1", json={"assigned_estimator": EST})
    return r


def _customer_pdf(rev):
    r = client.get("/api/admin/proposal-pdf?draft_id=d1&revision_no=%d" % rev, headers=SVC)
    assert r.status_code == 200, r.text
    return r.content


def _text(docx_bytes):
    xml = zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def _parts(docx_bytes):
    """Every part of a .docx except docProps/core.xml, which python-docx stamps with the time."""
    z = zipfile.ZipFile(io.BytesIO(docx_bytes))
    return {n: z.read(n) for n in z.namelist() if n != "docProps/core.xml"}


# ── Download and Send are one document ───────────────────────────────────────
def test_the_pdf_sent_is_the_pdf_that_was_downloaded(world):
    """THE ONE HANZ ASKED FOR. Download the PDF, send, then read what the customer's portal is
    served for that revision: the same bytes, and ONE LibreOffice render behind both.

    Mutation: render Send's PDF itself (`pdf_writer.docx_to_pdf(...)`) instead of reading the
    memoised one — the stored bytes become render #2 and this goes red."""
    downloaded = _download()
    r = _send()
    assert r.status_code == 200, r.text
    rev = r.json()["revision_no"]
    assert _customer_pdf(rev) == downloaded, "the customer was sent a different PDF"
    assert drafts.get_revision_documents("d1", rev)["pdf"] == downloaded
    assert len(world.renders) == 1, "Download and Send rendered the PDF %d times" % len(world.renders)


def test_a_download_after_the_send_is_the_file_the_customer_has(world):
    """The other order: send first (the send renders and freezes the PDF), then download. While
    the render is cached, the estimator's copy is the customer's copy byte for byte; past the
    cache it is the same content (test_a_send_after_a_restart_freezes_the_same_content)."""
    rev = _send().json()["revision_no"]
    assert _download() == _customer_pdf(rev)
    assert len(world.renders) == 1


def test_the_docx_and_the_pdf_come_from_the_same_render(world):
    """The .docx the estimator downloads is the document the stored PDF was rendered from."""
    docx = _download("docx_download_url")
    rev = _send().json()["revision_no"]
    stored = drafts.get_revision_documents("d1", rev)
    assert stored["docx"] == docx
    assert world.renders == [docx], "the frozen PDF was not rendered from the downloaded .docx"


def test_a_download_is_built_from_the_payload_saved_NOW(world):
    """RC2: a change that moves no price (the texture here) used to leave Download on the files
    built before it. Every press now renders the payload the store holds at that moment, and Send
    freezes that same one.

    Mutation: memoise the render on the draft id instead of the payload's hash — the second
    download comes back with the old texture."""
    assert "Orange Peel" in _text(_download("docx_download_url"))
    # The estimator changes the texture on the Proposal step and presses Continue.
    world.payload["values"]["texture"] = "Smooth Finish"
    now = _download("docx_download_url")
    assert "Smooth Finish" in _text(now) and "Orange Peel" not in _text(now)
    rev = _send().json()["revision_no"]
    assert drafts.get_revision_documents("d1", rev)["docx"] == now


# ── a sent revision is frozen ────────────────────────────────────────────────
def test_a_sent_revision_never_changes_after_a_renderer_change(world, monkeypatch):
    """Goal (b). Send, then land a "later deploy": the writer prints something else, LibreOffice
    renders differently, and the process starts with an empty cache. The customer's PDF for that
    revision, and staff's .docx and PDF of it, are the bytes that went out.

    The last assertion is the counterexample that keeps this honest: the SAME change does reach a
    fresh download of the live draft, so the renderer really did change.

    Mutation: ignore the stored row in /api/admin/proposal-pdf (`stored = None`) — the customer
    gets the new renderer's PDF and this goes red."""
    rev = _send().json()["revision_no"]
    sent_pdf = _customer_pdf(rev)
    sent_docx = drafts.get_revision_documents("d1", rev)["docx"]

    real_fill = main.proposal_writer.fill_proposal

    def later_deploy(**kw):
        # The header's job-name tokens, which print straight from `values`.
        later = {**kw["values"], "job_name": "PRINTED BY A LATER DEPLOY",
                 "project_name": "PRINTED BY A LATER DEPLOY"}
        return real_fill(**{**kw, "values": later})

    monkeypatch.setattr(main.proposal_writer, "fill_proposal", later_deploy)
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b"%PDF-1.4 a later LibreOffice")
    main._RENDER_CACHE.clear()          # a deploy restarts the process

    assert _customer_pdf(rev) == sent_pdf, "a sent revision's PDF changed after a deploy"
    files = client.post("/api/draft/d1/revisions/%d/files" % rev, json={})
    assert files.status_code == 200, files.text
    assert client.get(files.json()["docx_download_url"]).content == sent_docx
    assert client.get(files.json()["pdf_download_url"]).content == sent_pdf
    assert files.json()["xlsx_download_url"], "the revision's workbook link went missing"
    # The counterexample: the live draft DOES render through the changed code.
    assert "PRINTED BY A LATER DEPLOY" in _text(_download("docx_download_url"))


def test_a_revision_sent_before_documents_were_stored_is_rendered_as_before(world):
    """A revision with no stored row keeps today's path: rendered from its own snapshot."""
    world.store.setdefault("draft_revisions", []).append(
        {"project_id": "d1", "revision_no": 1, "created_by": EST,
         "data": {"project_name": "Old", "proposal_payload": copy.deepcopy(PAYLOAD)}})
    pdf = _customer_pdf(1)
    assert pdf.startswith(b"%PDF") and len(world.renders) == 1


def _missing_table(code):
    """What supabase-py raises for a table this database does not have: PGRST205 from PostgREST
    12 (prod, and staging's v12.2.3), 42P01 passed through from Postgres by an older one."""
    return APIError({"code": code, "message": "Could not find the table "
                     "'public.draft_revision_documents' in the schema cache"})


@pytest.mark.parametrize("code", ["PGRST205", "42P01"])
def test_a_missing_documents_table_falls_back_to_the_render(world, monkeypatch, code):
    """A database the DDL has not reached yet must not take every customer's PDF down: a table
    that does not EXIST reads as "nothing stored", which is how every revision was served before.

    Mutation: make `_table_missing` answer False — this is a 503."""
    world.store.setdefault("draft_revisions", []).append(
        {"project_id": "d1", "revision_no": 1, "created_by": EST,
         "data": {"project_name": "Old", "proposal_payload": copy.deepcopy(PAYLOAD)}})

    def missing(*a, **k):
        raise _missing_table(code)

    monkeypatch.setattr(drafts, "get_revision_documents", missing)
    assert _customer_pdf(1).startswith(b"%PDF")


@pytest.mark.parametrize("failure", [
    httpx.ReadTimeout("timed out"),
    APIError({"code": None, "message": "upstream connect error"}),
    APIError({"code": "57014", "message": "canceling statement due to statement timeout"}),
], ids=["timeout", "5xx", "statement-timeout"])
def test_a_failed_read_of_a_stored_pdf_serves_nothing_rather_than_a_render(world, monkeypatch,
                                                                          failure):
    """Review of fix 3. The table exists and the read FAILED. Falling back to a re-render here
    served a document that was never sent — through whatever code is deployed that day — and the
    portal caches that for ten minutes and hashes it into contract_sha256 if the customer approves
    inside them. So nothing is served: a 503, which the portal shows as no PDF and which leaves an
    approval's hash to be rebuilt from the stored bytes later.

    Mutation: catch every exception in `_stored_revision_documents` again — the customer is served
    `%PDF-1.4 LATER RENDERER` with a 200."""
    rev = _send().json()["revision_no"]
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b"%PDF-1.4 LATER RENDERER")
    main._RENDER_CACHE.clear()

    def unreadable(*a, **k):
        raise failure

    monkeypatch.setattr(drafts, "get_revision_documents", unreadable)
    r = client.get("/api/admin/proposal-pdf?draft_id=d1&revision_no=%d" % rev, headers=SVC)
    assert r.status_code == 503, (r.status_code, r.content[:60])
    assert b"LATER RENDERER" not in r.content
    files = client.post("/api/draft/d1/revisions/%d/files" % rev, json={})
    assert files.status_code == 503, files.text


# ── a send that cannot freeze its document is not sent ───────────────────────
def test_a_failed_portal_call_rolls_back_the_revision_AND_its_document(world):
    """The existing rollback drops the revision; the stored files go with it, so nothing claims a
    version the customer never received.

    Mutation: delete the `drafts.delete_revision_documents` call in the portal-failure branch."""
    world.portal["fail"] = True
    r = _send()
    assert r.status_code == 502
    assert not [x for x in world.store.get("draft_revisions", []) if x["project_id"] == "d1"]
    assert not world.store.get("draft_revision_documents"), "a failed send left its document behind"


def test_a_document_that_cannot_be_stored_refuses_the_send(world, monkeypatch):
    """Sent without a frozen document, the revision would re-render on every view — the thing the
    table ends. So the customer is told nothing, and the revision is rolled back.

    Mutation: swallow the store error and carry on to the portal."""
    def broken(*a, **k):
        raise RuntimeError("413 Request Entity Too Large")

    monkeypatch.setattr(drafts, "store_revision_documents", broken)
    r = _send()
    assert r.status_code == 503, r.text
    assert "Not sent" in r.json()["detail"]
    assert world.portal["calls"] == [], "the customer was emailed a proposal with no frozen PDF"
    assert not world.store.get("draft_revisions"), "the unsent revision was left in the history"


def test_a_database_without_the_table_still_sends_as_before(world, monkeypatch, caplog):
    """Review of fix 3: the rollout trap. Code reaching a database before its DDL refused EVERY
    send with a "try again" no retry could fix. A missing table is not a failed write, it is a
    database where every revision is re-rendered anyway — so the send goes out exactly as it did
    before the table existed, with an error in the log that names the fix. The backfill freezes it
    once the table exists.

    Mutation: treat a missing table like any other store failure — this is a 503 and no portal
    call."""
    def missing(*a, **k):
        raise _missing_table("PGRST205")

    monkeypatch.setattr(drafts, "store_revision_documents", missing)
    with caplog.at_level("ERROR"):
        r = _send()
    assert r.status_code == 200, r.text
    assert len(world.portal["calls"]) == 1, "the send did not reach the portal"
    assert [x["revision_no"] for x in world.store["draft_revisions"]] == [r.json()["revision_no"]]
    assert "MISSING" in caplog.text and "backfill_revision_documents" in caplog.text


def test_a_database_without_the_table_and_a_portal_failure_still_rolls_back(world, monkeypatch):
    """Nothing was stored, so there is no document to delete — and the revision still goes."""
    def missing(*a, **k):
        raise _missing_table("PGRST205")

    def must_not_be_called(*a, **k):
        raise AssertionError("deleted a stored document that was never stored")

    monkeypatch.setattr(drafts, "store_revision_documents", missing)
    monkeypatch.setattr(drafts, "delete_revision_documents", must_not_be_called)
    world.portal["fail"] = True
    assert _send().status_code == 502
    assert not world.store.get("draft_revisions")


def test_a_document_that_cannot_be_built_refuses_the_send_before_anything_is_written(world,
                                                                                     monkeypatch):
    """Built BEFORE the revision is minted, so a render failure writes nothing at all.

    Mutation: render after create_revision — a revision is left behind."""
    def no_libreoffice(b):
        raise RuntimeError("LibreOffice (soffice) not found on PATH")

    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", no_libreoffice)
    r = _send()
    assert r.status_code == 500 and "Not sent" in r.json()["detail"], r.text
    assert world.portal["calls"] == []
    assert not world.store.get("draft_revisions")


def test_a_draft_with_no_document_still_sends_and_stores_nothing(world):
    """No payload, no document: sent exactly as before (the customer's PDF route answers "not
    generated yet" for it, as it always has)."""
    del world.store["drafts"][0]["data"]["proposal_payload"]
    r = _send()
    assert r.status_code == 200, r.text
    assert world.renders == [] and not world.store.get("draft_revision_documents")


# ── the render does not depend on who asks ───────────────────────────────────
def _signed_in_and_customer_docx(monkeypatch):
    """The same saved payload rendered for the signed-in estimator (/documents) and for the
    customer (/api/admin/proposal-pdf, nobody signed in), with the cache cleared in between so the
    second really is a second render. LibreOffice is the identity so the customer's route hands
    back the .docx it rendered."""
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b)
    mine = _download("docx_download_url")
    main._RENDER_CACHE.clear()
    r = client.get("/api/admin/proposal-pdf?draft_id=d1", headers=SVC)
    assert r.status_code == 200, r.text
    return mine, r.content


def test_the_document_does_not_depend_on_who_is_signed_in(world, monkeypatch):
    """Goal (c). A payload whose cover letter has no estimator email: the render used to fill it
    from whoever was signed in, so the estimator's copy carried their address and the customer's
    replay of the same payload carried none.

    Mutation: put the request-derived backfill back into `_generate` (call `_sign_as_caller`
    there) — the estimator's copy signs as the test user and this goes red."""
    world.payload["values"]["estimator_email"] = ""
    world.payload["cover_letter_enabled"] = True
    mine, theirs = _signed_in_and_customer_docx(monkeypatch)
    assert _parts(mine) == _parts(theirs), "one payload rendered two documents"
    assert "tester@wetreadwell.com" not in _text(mine), "the signed-in user signed the proposal"


def test_a_missing_name_comes_from_the_payloads_own_email(world, monkeypatch):
    """The fallback that replaced the request: a blank name beside a present email is derived from
    THAT email — a fact of the payload, the same on every replay."""
    world.payload["values"]["estimator_name"] = ""
    world.payload["values"]["estimator_email"] = "kyle.loseke@wetreadwell.com"
    mine, theirs = _signed_in_and_customer_docx(monkeypatch)
    assert _parts(mine) == _parts(theirs)
    assert "Kyle Loseke" in _text(mine) and "Tester" not in _text(mine)


def test_the_live_generate_still_signs_as_the_caller(monkeypatch):
    """The one composition done on the server — /api/generate, the Files page's rebuild for a
    draft with no payload — still fills a blank signature from the caller, as it always did."""
    monkeypatch.setattr(drafts, "log_event", lambda *a, **k: None)
    body = copy.deepcopy(PAYLOAD)
    body["values"]["estimator_name"] = ""
    body["values"]["estimator_email"] = ""
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    assert "Tester" in _text(client.get(r.json()["docx_download_url"]).content)


# ── Send is held to the document that was downloaded ─────────────────────────
def _send_checked(render_id):
    return client.post("/api/portal/publish?draft_id=d1",
                       json={"assigned_estimator": EST, "document_render_id": render_id})


def _nothing_written(world):
    assert world.portal["calls"] == [], "the customer was sent something"
    assert not world.store.get("draft_revisions"), "a revision was minted"
    assert not world.store.get("draft_revision_documents"), "a document was stored"


def test_documents_names_its_render_and_its_total(world):
    """The answer carries `render_id` (payload + templates + code) and the Total the rendered
    payload was filled with, which the Files page shows on its card."""
    out = _documents()
    gi = main.GenerateIn(**copy.deepcopy(world.payload))
    assert out["render_id"] == main._render_key(world.payload, gi)
    assert out["document_total"] == "$10,000.00"


def test_a_send_holding_the_downloaded_key_freezes_that_download(world):
    downloaded = _download()
    key = _documents()["render_id"]
    r = _send_checked(key)
    assert r.status_code == 200, r.text
    assert _customer_pdf(r.json()["revision_no"]) == downloaded


def test_a_send_refuses_a_document_saved_over_since_the_download(world):
    """Review of fix 3, finding 1. The estimator downloaded one document; then the SAVED payload
    changed (a colleague's Continue elsewhere, or a stale copy of the page PUT back over it). Send
    used to freeze the new payload with no word to anybody. It is refused, and nothing is written.

    Mutation: drop the `document_render_id` check in api_portal_publish — this is a 200 and the
    customer gets a document nobody downloaded."""
    key = _documents()["render_id"]
    world.payload["values"]["texture"] = "Smooth Finish"
    r = _send_checked(key)
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "document_changed" and "Download it again" in body["error"]
    _nothing_written(world)


def test_a_send_refuses_after_a_deploy_changed_the_renderer(world, monkeypatch):
    """Review of fix 3, finding 3 (E3). Download, then a deploy that changes what the writer
    prints lands before Send. The same payload now renders differently, and freezing that would
    freeze text the estimator never downloaded. The code is part of the key, so it is refused.

    Mutation: leave `_RENDERER_ID` out of `_render_key` — the key does not move and the new
    renderer's text is frozen."""
    key = _documents()["render_id"]
    real_fill = main.proposal_writer.fill_proposal

    def later_deploy(**kw):
        return real_fill(**{**kw, "values": {**kw["values"], "job_name": "A LATER DEPLOY"}})

    monkeypatch.setattr(main.proposal_writer, "fill_proposal", later_deploy)
    monkeypatch.setattr(main, "_RENDERER_ID", "the code after the deploy")
    main._RENDER_CACHE.clear()
    r = _send_checked(key)
    assert r.status_code == 409 and r.json()["code"] == "document_changed", r.text
    _nothing_written(world)


def test_a_send_after_a_restart_freezes_the_same_content(world):
    """Review of fix 3, finding 3 (E2/P1). The render fell out of the cache between Download and
    Send (a restart, an hour, 24 other renders) with nothing changed. The key still matches, so the
    send goes through, and it freezes the SAME document: every part of the .docx but python-docx's
    timestamp. The bytes are not the download's — LibreOffice and python-docx stamp the time — and
    this pins that honestly instead of claiming otherwise."""
    docx = _download("docx_download_url")
    pdf = _download()
    key = _documents()["render_id"]
    main._RENDER_CACHE.clear()
    r = _send_checked(key)
    assert r.status_code == 200, r.text
    stored = drafts.get_revision_documents("d1", r.json()["revision_no"])
    assert _parts(stored["docx"]) == _parts(docx), "a re-render of the same key changed the content"
    assert len(world.renders) == 2 and _parts(world.renders[1]) == _parts(docx)
    assert stored["pdf"] != pdf, "this fake LibreOffice never returns the same bytes twice"


def test_a_send_holding_a_key_for_a_draft_that_lost_its_document_is_refused(world):
    """Something was downloaded and there is now nothing to freeze: not the document either."""
    key = _documents()["render_id"]
    del world.store["drafts"][0]["data"]["proposal_payload"]
    r = _send_checked(key)
    assert r.status_code == 409 and r.json()["code"] == "document_changed", r.text
    _nothing_written(world)


# ── the Files page's build is recorded by the server, not by the page ────────
def test_documents_records_has_files_on_the_servers_copy(world):
    """Review of fix 3, finding 1. The page used to record `generate_result` with TW.setState,
    which PUT its whole — possibly stale — blob. The server records it on its own copy instead,
    touching nothing else, so the "Created but not sent" column still sees the project.

    Mutation: drop the `record_generate_result` call — generate_result never appears."""
    before = copy.deepcopy(world.store["drafts"][0]["data"])
    _documents()
    after = world.store["drafts"][0]["data"]
    assert after.get("generate_result", {}).get("work_type") == "epoxy"
    assert {k: v for k, v in after.items() if k != "generate_result"} == before


def test_a_recorded_build_is_never_overwritten(world):
    """Only its existence is read; rewriting it on every press is a write for nothing. Asked of
    the route AND of the writer itself, which re-reads the row: a build recorded by another press
    between the route's load and its write must not be replaced either.

    Mutation: drop the writer's own `if data.get("generate_result")` guard — the direct call
    overwrites."""
    world.store["drafts"][0]["data"]["generate_result"] = {"work_type": "epoxy", "mine": 1}
    _documents()
    assert world.store["drafts"][0]["data"]["generate_result"] == {"work_type": "epoxy", "mine": 1}
    assert drafts.record_generate_result("d1", {"work_type": "epoxy", "other": 2}) is False
    assert world.store["drafts"][0]["data"]["generate_result"] == {"work_type": "epoxy", "mine": 1}
    world.store["drafts"][0]["data"]["generate_result"] = None   # nulled by a letter change
    assert drafts.record_generate_result("d1", {"work_type": "epoxy", "other": 2}) is True


# ── the endpoint and the store ───────────────────────────────────────────────
def test_documents_needs_a_saved_payload(world):
    del world.store["drafts"][0]["data"]["proposal_payload"]
    r = client.post("/api/draft/d1/documents", json={})
    assert r.status_code == 422 and "Continue" in r.json()["detail"]
    assert client.post("/api/draft/nope/documents", json={}).status_code == 404


def test_documents_hands_out_the_workbook_too(world):
    out = _documents()
    assert out["xlsx_download_url"] and client.get(out["xlsx_download_url"]).status_code == 200


def test_storing_a_revision_number_again_replaces_the_orphan(world):
    """A failed rollback can leave a row behind, and the next send reuses the number. The new
    send's files must be the ones served.

    Mutation: drop the delete in store_revision_documents — the orphan is read back."""
    drafts.store_revision_documents("d1", 1, payload_sha256="old", docx=b"old docx", pdf=b"old pdf")
    drafts.store_revision_documents("d1", 1, payload_sha256="new", docx=b"new docx", pdf=b"new pdf")
    got = drafts.get_revision_documents("d1", 1)
    assert got == {"docx": b"new docx", "pdf": b"new pdf", "payload_sha256": "new"}
    assert len(world.store["draft_revision_documents"]) == 1


def test_the_stored_row_names_its_bytes_and_its_payload(world):
    """The sha256 columns are what anyone auditing a frozen PDF compares against, so they must be
    the hashes of what is stored, and payload_sha256 the canonical hash of the pinned payload."""
    rev = _send().json()["revision_no"]
    row = world.store["draft_revision_documents"][0]
    stored = drafts.get_revision_documents("d1", rev)
    assert row["pdf_sha256"] == hashlib.sha256(stored["pdf"]).hexdigest()
    assert row["docx_sha256"] == hashlib.sha256(stored["docx"]).hexdigest()
    pinned = [r for r in world.store["draft_revisions"] if r["revision_no"] == rev][0]
    assert row["payload_sha256"] == main._canonical_sha256(pinned["data"]["proposal_payload"])
    assert row["created_by"] == "tester@wetreadwell.com"
