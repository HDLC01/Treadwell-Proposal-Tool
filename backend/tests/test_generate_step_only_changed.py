"""3 · Generate Files builds only what changed, in parallel: the server half (Hanz, 2026-10-29).

"there are multiple proposals why not generate them in parallel also and to make this faster if we
only edited one proposal then it should only regenerate that proposal". Step 3 (js/generate.js)
asks POST /api/draft/{id}/documents/held of every proposal whose document holds for its draft; the
answer is "held", with the files under fresh tokens, only when the render of EXACTLY that saved
document is in the render cache with all three files made. Anything else is "not held" and the
page builds as before. "Rebuild all" sends `rebuild: true` to /documents, which builds again past
the cache. LibreOffice never runs more than two at once (main._PDF_RENDER_SEM).

Executed: the real routes, the real render cache (`_render_documents`, `_render_key`,
`_documents_out`, `_entry_pdf`) and the real /api/file routes. Only `_generate` (the template fill)
and LibreOffice are stood in for, and each call to them is counted.
"""
from __future__ import annotations

import copy
import inspect
import re
import threading
import time

import cachetools
import pytest
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)
V1 = "2026-10-29T10:00:00+00:00"


def _payload(total="$12,500", cell="10000"):
    return {"work_type": "epoxy", "audience": "Direct",
            "cell_values": {"Epoxy!E20": cell},
            "values": {"project_name": "Acme HQ", "total_formatted": total}}


class Server:
    """The fake store, a fresh render cache, and a count of every template fill and PDF render."""

    def __init__(self, fake_supabase, monkeypatch, *, payload=None, data=None):
        d = {"project_name": "Acme HQ", "work_type": "epoxy",
             "proposal_payload": copy.deepcopy(payload or _payload())}
        d.update(data or {})
        self.store = {"drafts": [{"id": "p1", "data": d, "owner_email": "kyle@wetreadwell.com",
                                  "created_at": "2026-10-01", "updated_at": V1,
                                  "deleted_at": None}], "events": []}
        self.fills = []
        self.pdfs = []
        monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(self.store))
        monkeypatch.setattr(main, "_RENDER_CACHE", cachetools.TTLCache(maxsize=24, ttl=3600))

        def fill(gi, request, *, persist=True, want_estimate=True, fit_report=None):
            self.fills.append(copy.deepcopy(gi.values))
            n = len(self.fills)
            docx = main._cache_file(b"docx %d" % n, "p_proposal.docx",
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            xlsx = (main._cache_file(b"xlsx %d" % n, "p_estimate.xlsx", "application/vnd.ms-excel")
                    if want_estimate else "")
            return main.GenerateOut(work_type="epoxy", audience="Direct",
                                    xlsx_download_url=f"/api/file/{xlsx}" if xlsx else "",
                                    docx_download_url=f"/api/file/{docx}",
                                    pdf_download_url=f"/api/file/{docx}/pdf", totals={})
        monkeypatch.setattr(main, "_generate", fill)

        def pdf(docx_bytes, **kw):
            self.pdfs.append(docx_bytes)
            return b"%PDF " + docx_bytes
        monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", pdf)

    @property
    def row(self):
        return self.store["drafts"][0]

    def build(self, **body):
        r = client.post("/api/draft/p1/documents", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def held(self, version=V1, **body):
        r = client.post("/api/draft/p1/documents/held", json=dict(body, draft_version=version))
        assert r.status_code == 200, r.text
        return r.json()


def _get(url):
    return client.get(url)


def test_held_only_once_all_three_files_are_built(fake_supabase, monkeypatch):
    """Not before the first build; not after a build whose PDF was never made; held once the PDF
    is, with fresh tokens that download, and without a template fill or a LibreOffice run."""
    s = Server(fake_supabase, monkeypatch)
    assert s.held() == {"ok": True, "held": False}
    built = s.build(hold_placeholders=True)
    assert s.held() == {"ok": True, "held": False}, "held before its PDF was made"
    assert _get(built["pdf_download_url"]).status_code == 200
    fills, pdfs = len(s.fills), len(s.pdfs)
    j = s.held(hold_placeholders=True)
    assert j["held"] is True
    f = j["files"]
    assert f["render_id"] == built["render_id"] and f["document_total"] == "$12,500"
    for k in ("xlsx_download_url", "docx_download_url", "pdf_download_url"):
        assert f[k] and f[k] != built[k], "not a fresh token: " + k
        assert _get(f[k]).status_code == 200, k
    assert _get(f["pdf_download_url"]).content == _get(built["pdf_download_url"]).content
    assert (len(s.fills), len(s.pdfs)) == (fills, pdfs), "the held answer rendered something"


def test_an_estimate_cell_change_is_not_held(fake_supabase, monkeypatch):
    """The .xlsx is filled from the document's own estimate keys (cell_values etc.). A document
    whose estimate cell moved is another render: not held, though the old one is cached whole."""
    s = Server(fake_supabase, monkeypatch)
    _get(s.build()["pdf_download_url"])
    assert s.held()["held"] is True
    s.row["data"]["proposal_payload"] = _payload(cell="12500")
    assert s.held()["held"] is False
    s.row["data"]["proposal_payload"] = _payload(total="$13,000")
    assert s.held()["held"] is False


def test_a_copy_saved_since_or_no_version_is_not_held(fake_supabase, monkeypatch):
    s = Server(fake_supabase, monkeypatch)
    _get(s.build()["pdf_download_url"])
    assert s.held()["held"] is True
    assert s.held(version="")["held"] is False
    s.row["updated_at"] = "2026-10-29T11:00:00+00:00"
    assert s.held(version=V1)["held"] is False


def test_a_document_still_printing_placeholders_is_not_held_when_asked(fake_supabase, monkeypatch):
    """Send all's walk built it unattended and it still prints Kyle's placeholders: step 3 asks with
    the hold, so it is not "up to date" but built, and the build says why it is refused."""
    gc = {"work_type": "epoxy", "audience": "GC", "values": {
        "scope_notes": "", "schedule_notes": "", "architect": "", "total_formatted": "$2,000"}}
    s = Server(fake_supabase, monkeypatch, payload=gc, data={"proposal_auto_built": True})
    _get(s.build(hold_placeholders=False)["pdf_download_url"])
    assert s.held(hold_placeholders=False)["held"] is True
    assert s.held(hold_placeholders=True)["held"] is False


def test_held_records_the_files_on_the_board_once(fake_supabase, monkeypatch):
    """A render built from another proposal's line (record: false) and then found held here: the
    board's "Created but not sent" column learns the files exist, as /documents would have told it."""
    s = Server(fake_supabase, monkeypatch)
    _get(s.build(record=False)["pdf_download_url"])
    assert not s.row["data"].get("generate_result")
    assert s.held()["held"] is True
    assert s.row["data"].get("generate_result")


def test_no_document_or_no_draft(fake_supabase, monkeypatch):
    s = Server(fake_supabase, monkeypatch)
    s.row["data"].pop("proposal_payload")
    assert s.held() == {"ok": True, "held": False}
    assert client.post("/api/draft/nope/documents/held", json={"draft_version": V1}).status_code == 404


def test_rebuild_all_fills_again_and_a_plain_build_reuses_the_render(fake_supabase, monkeypatch):
    s = Server(fake_supabase, monkeypatch)
    first = s.build()
    s.build()
    assert len(s.fills) == 1, "a second build of the same document filled the templates again"
    again = s.build(rebuild=True)
    assert len(s.fills) == 2, "Rebuild all reused the cached render"
    assert again["render_id"] == first["render_id"], "the same document is the same key"
    # The rebuilt render's PDF is not the old one's: it is made again.
    _get(again["pdf_download_url"])
    assert len(s.pdfs) == 1
    assert s.held()["held"] is True


# ── LibreOffice is capped ────────────────────────────────────────────────────────────────────
def _peak_concurrent_pdf_renders(monkeypatch, n=6):
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow(docx_bytes, **kw):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.2)
        with lock:
            live["now"] -= 1
        return b"%PDF"
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", slow)
    entries = [{"content": b"docx %d" % i} for i in range(n)]
    threads = [threading.Thread(target=main._entry_pdf, args=(e,)) for e in entries]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert all(e.get("_pdf") == b"%PDF" for e in entries)
    return live["peak"]


def test_at_most_two_libreoffice_renders_run_at_once(monkeypatch):
    """Three builds at once from step 3 (and two compose frames feeding more) must not start more
    than two LibreOffice processes on the shared 2 GB box: six PDFs asked together, two at a time."""
    assert _peak_concurrent_pdf_renders(monkeypatch) == 2


def test_the_cap_check_sees_an_uncapped_server(monkeypatch):
    """The control: with the semaphore opened wide the same six run together, so the check above
    measures the cap and not the thread scheduler."""
    monkeypatch.setattr(main, "_PDF_RENDER_SEM", threading.Semaphore(100))
    assert _peak_concurrent_pdf_renders(monkeypatch) > 2


# ── the template fills are capped too (review of c6016a9d) ──────────────────────────────────
def _peak_concurrent_fills(fake_supabase, monkeypatch, n=6):
    """`n` different documents rendered together through the real `_render_documents` (distinct
    keys, so the per-document lock does not serialise them); the peak number of `_generate` calls
    running at once."""
    Server(fake_supabase, monkeypatch)
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow(gi, request, *, persist=True, want_estimate=True, fit_report=None):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.2)
        with lock:
            live["now"] -= 1
        docx = main._cache_file(b"docx", "p_proposal.docx", "application/octet-stream")
        xlsx = main._cache_file(b"xlsx", "p_estimate.xlsx", "application/octet-stream")
        return main.GenerateOut(work_type="epoxy", audience="Direct",
                                xlsx_download_url=f"/api/file/{xlsx}", docx_download_url=f"/api/file/{docx}",
                                pdf_download_url=f"/api/file/{docx}/pdf", totals={})
    monkeypatch.setattr(main, "_generate", slow)
    out = []
    threads = [threading.Thread(target=lambda i=i: out.append(main._render_documents(
        _payload(total="$%d" % (1000 + i)), None, want_estimate=True))) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(out) == n and len({d["render_id"] for d in out}) == n
    return live["peak"]


def test_at_most_three_template_fills_run_at_once(fake_supabase, monkeypatch):
    """Step 3 builds several proposals at once and two estimators can press it together: however
    many builds arrive, no more than three workbook-and-document fills run at once on the 2 GB box."""
    assert _peak_concurrent_fills(fake_supabase, monkeypatch) == 3


def test_the_fill_cap_check_sees_an_uncapped_server(fake_supabase, monkeypatch):
    """The control: with the cap opened wide the same six fills run together."""
    monkeypatch.setattr(main, "_GENERATE_SEM", threading.Semaphore(100))
    assert _peak_concurrent_fills(fake_supabase, monkeypatch) > 3


def test_every_libreoffice_call_in_main_is_under_the_cap():
    """Every place main.py starts LibreOffice (a .docx to PDF, the invoice PDF) holds the semaphore."""
    lines = inspect.getsource(main).splitlines()
    calls = [i for i, ln in enumerate(lines)
             if re.search(r"\b(docx_to_pdf|build_invoice_pdf|build_certificate_pdf)\(", ln)
             and not ln.lstrip().startswith(("#", "def "))]
    assert calls, "no LibreOffice call found: repoint this check"
    for i in calls:
        assert "with _PDF_RENDER_SEM" in lines[i - 1], "uncapped LibreOffice call: " + lines[i].strip()
