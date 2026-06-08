"""PDF export endpoint (/api/file/{token}/pdf) + pdf_writer guards.

The proposal .docx is rendered to PDF on demand via LibreOffice. These tests
mock the LibreOffice call so they run anywhere (no soffice needed) and verify:
  - a cached .docx token converts → application/pdf with a .pdf filename
  - the rendered PDF is memoized on the cache entry (no double conversion)
  - unknown token → 404; a non-.docx token → 400; conversion failure → 500
  - pdf_writer._soffice() raises a clear error when LibreOffice is absent
"""
import pytest
from fastapi.testclient import TestClient

import main
import pdf_writer

client = TestClient(main.app)

DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FAKE_PDF = b"%PDF-1.7\nfake-rendered-proposal\n%%EOF"


def test_pdf_endpoint_converts_cached_docx(monkeypatch):
    calls = {"n": 0}

    def fake_convert(docx_bytes, **kw):
        calls["n"] += 1
        assert docx_bytes == b"DOCXBYTES"
        return FAKE_PDF

    monkeypatch.setattr(pdf_writer, "docx_to_pdf", fake_convert)
    token = main._cache_file(b"DOCXBYTES", "Acme — Proposal.docx", DOCX_CT)

    r = client.get(f"/api/file/{token}/pdf")
    assert r.status_code == 200
    assert r.content == FAKE_PDF
    assert r.headers["content-type"] == "application/pdf"
    cd = r.headers["content-disposition"]
    assert cd.split(";")[0] == "attachment"
    assert ".pdf" in cd and ".docx" not in cd            # extension swapped
    assert "filename*=UTF-8''" in cd                      # RFC 5987 (non-ASCII safe)
    assert "—" not in cd.split("filename*=")[0]           # ASCII fallback is clean

    # Second hit is served from the memoized PDF — LibreOffice runs only once.
    r2 = client.get(f"/api/file/{token}/pdf")
    assert r2.status_code == 200 and r2.content == FAKE_PDF
    assert calls["n"] == 1


def test_pdf_endpoint_404_for_unknown_token():
    assert client.get("/api/file/does-not-exist/pdf").status_code == 404


def test_pdf_endpoint_400_for_non_docx(monkeypatch):
    # A non-.docx entry must be rejected before LibreOffice is ever invoked.
    monkeypatch.setattr(pdf_writer, "docx_to_pdf",
                        lambda *a, **k: pytest.fail("tried to convert a non-docx"))
    token = main._cache_file(
        b"xlsxbytes", "estimate.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert client.get(f"/api/file/{token}/pdf").status_code == 400


def test_pdf_endpoint_500_when_conversion_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("libreoffice exploded")

    monkeypatch.setattr(pdf_writer, "docx_to_pdf", boom)
    token = main._cache_file(b"DOCX", "p.docx", DOCX_CT)
    assert client.get(f"/api/file/{token}/pdf").status_code == 500


def test_soffice_missing_raises_clear_error(monkeypatch):
    monkeypatch.setattr(pdf_writer.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="LibreOffice"):
        pdf_writer.docx_to_pdf(b"anything")
