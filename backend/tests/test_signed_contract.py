"""The signed contract: the proposal the customer opened, plus one certificate page.

WHAT THIS FEATURE IS FOR. A customer accepts a proposal in the portal by typing
their name and ticking a consent box. Under ESIGN (15 U.S.C. § 7001) and Kansas
UETA (K.S.A. 16-1601 et seq.) that is a signature; what makes it defensible is
the audit trail — who, when, from where, under which wording, and against WHICH
EXACT DOCUMENT. `/api/admin/signed-contract` is where the paper for that gets
made, because the portal has no python-docx, no LibreOffice and no pypdf.

THE ASSERTION THAT MATTERS MOST is byte-identity of the proposal's own pages.
The certificate prints the SHA-256 of the PDF the customer opened. If this route
ever re-rendered or re-flowed those pages, the document we keep would not hash to
the value printed on its last page, and the certificate would be evidence
AGAINST us. So `test_the_proposal_pages_come_through_untouched` compares every
input page's content stream with the output's, and it is the test to break first
when this handler is changed.

NO LIBREOFFICE ANYWHERE IN HERE. The suite is hermetic (see the CI comment) and
the dev box has no soffice, so the docx→PDF step is stubbed — but not with a
constant blob. `_fake_render` reads the REAL text out of the REAL filled .docx
and emits a real PDF carrying it, so "both hashes appear in full on the
certificate page" is a fact about the document this code actually built, not
about a fixture. The one thing a stub cannot prove — that the page LAYOUT fits on
a single page — has its own test, skipped where LibreOffice is absent.
"""
import hashlib
import io
import json
import os
import re

import pypdf
import pytest
from fastapi.testclient import TestClient

import certificate_writer as cw
import main
import pdf_writer
import proposal_writer

client = TestClient(main.app)
PATH = "/api/admin/signed-contract"
TOKEN = "svc-test"
TEMPLATE = proposal_writer.TEMPLATES_ROOT / cw.TEMPLATE_NAME

PROPOSAL_SHA = "3f2a1b" + "c" * 58
REVISION_SHA = "ab" * 32

CERT = {
    "project_name": "Olathe Distribution Center — Phase 2",
    "proposal_id": "b7f1c2de-4a90-4f21-9f3a-2c1d8e5a6b70",
    "revision_no": 3,
    "signer_name": "Dana Whitfield",
    "signer_title": "Director of Facilities",
    "signer_email": "dwhitfield@olathedc.example.com",
    "signed_at_utc": "2026-09-18T15:42:07Z",
    "signed_at_central": "September 18, 2026 at 10:42 AM CDT",
    "ip_address": "198.51.100.42",
    "user_agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
    "options_summary": "Base bid accepted: epoxy, 24,800 SF. Alternate declined.",
    "total": 187450.75,
    "deposit_amount": 46862.69,
    "consent_text": ("By typing my name and checking this box I agree that this is my legal "
                     "electronic signature and that it binds me to this proposal and its "
                     "Terms and Conditions."),
    "consent_version": "tw-consent-2026-09-01",
    "proposal_pdf_sha256": PROPOSAL_SHA,
    "revision_sha256": REVISION_SHA,
}


# ── a real, tiny PDF ─────────────────────────────────────────────────────────
def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(lines_per_page) -> bytes:
    """A genuine multi-page PDF, one content stream per page.

    Hand-built rather than `PdfWriter.add_blank_page()`: a blank page has NO
    content stream, so a byte-identity test over blank pages would compare
    nothing against nothing and pass whatever the handler did to them.
    """
    objs, n = {}, len(lines_per_page)
    font_id = 3 + 2 * n
    kids = " ".join("%d 0 R" % (3 + 2 * i) for i in range(n))
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode()
    for i, lines in enumerate(lines_per_page):
        pid, cid = 3 + 2 * i, 4 + 2 * i
        objs[pid] = ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                     "<< /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font_id, cid)).encode()
        body = "BT /F1 9 Tf 36 750 Td 12 TL\n"
        body += "".join("(%s) Tj T*\n" % _esc(line) for line in lines)
        body += "ET"
        stream = body.encode("latin-1", "replace")
        objs[cid] = (b"<< /Length %d >>\nstream\n" % len(stream)) + stream + b"\nendstream"
    objs[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref, top = len(out), max(objs) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % top
    for num in range(1, top):
        out += b"%010d 00000 n \n" % offsets.get(num, 0)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (top, xref)
    return bytes(out)


PROPOSAL_PDF = make_pdf([
    ["TREADWELL PROPOSAL", "Olathe Distribution Center - Phase 2"],
    ["Scope of work", "24,800 SF epoxy"],
    ["TERMS AND CONDITIONS", "1. through 27."],
])


def _docx_lines(docx_bytes: bytes) -> list:
    """Every paragraph of a .docx, in order — what a reader would see."""
    from docx import Document
    d = Document(io.BytesIO(docx_bytes))
    return [p.text for p in d.paragraphs if p.text.strip()]


def _fake_render(docx_bytes: bytes, **kw) -> bytes:
    """Stand in for LibreOffice: carry the .docx's REAL text into a real PDF.

    A constant `b"%PDF stub"` would make every downstream assertion vacuous — the
    hashes would "appear" because the fixture put them there. This renders what
    `certificate_writer` actually produced, so the text assertions are about the
    document under test.
    """
    return make_pdf([_docx_lines(docx_bytes)])


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", TOKEN)
    monkeypatch.setattr(pdf_writer, "docx_to_pdf", _fake_render)


def _post(pdf_bytes=PROPOSAL_PDF, cert=None, token=TOKEN, raw_cert=None, omit_pdf=False):
    files = {} if omit_pdf else {"proposal_pdf": ("proposal.pdf", pdf_bytes, "application/pdf")}
    data = {}
    if raw_cert is not None:
        data["certificate"] = raw_cert
    elif cert is not False:
        data["certificate"] = json.dumps(CERT if cert is None else cert)
    headers = {} if token is None else {"X-Service-Token": token}
    return client.post(PATH, files=files or None, data=data or None, headers=headers)


# ── the template and the fill ────────────────────────────────────────────────
def test_the_template_ships():
    assert TEMPLATE.is_file(), (
        "Signature_Certificate.docx must ship in backend/templates/ — regenerate it with "
        "backend/prepare_signature_certificate_template.py and commit it.")


def test_the_template_offers_a_slot_for_every_field():
    """A field with nowhere to print is evidence silently lost."""
    from docx import Document
    text = "\n".join(p.text for p in Document(str(TEMPLATE)).paragraphs)
    for name in cw.FIELDS:
        assert "{{" + name + "}}" in text, name + " has no placeholder on the certificate"


def test_the_fill_leaves_no_placeholder_behind():
    """`_ensure_value_aliases` exists because a customer-facing document must never
    show a literal {{token}}. A certificate is the last place that can be allowed."""
    lines = _docx_lines(cw.build_certificate_docx(CERT, TEMPLATE))
    leftover = [t for line in lines for t in re.findall(r"\{\{[a-z0-9_]+\}\}", line)]
    assert leftover == [], leftover


def test_every_value_reaches_the_page():
    text = "\n".join(_docx_lines(cw.build_certificate_docx(CERT, TEMPLATE)))
    for value in cw.certificate_fields(CERT).values():
        assert value in text, value


def test_the_label_formatting_survives_the_fill():
    """The value is written into the run that owns the token, not over the whole
    paragraph — so the bold label beside it keeps its formatting. Collapsing the
    paragraph into one run (the shortcut `invoice_writer` can take, because its
    placeholders ARE whole paragraphs) would lose it silently."""
    from docx import Document
    d = Document(io.BytesIO(cw.build_certificate_docx(CERT, TEMPLATE)))
    row = [p for p in d.paragraphs if p.text.startswith("Name\t")][0]
    assert row.runs[0].text == "Name" and row.runs[0].bold is True
    assert "Dana Whitfield" in row.text


def test_an_empty_title_prints_a_phrase_not_a_blank():
    """A blank beside a label reads as "the fill failed", which is the one thing
    this page must never be ambiguous about."""
    f = cw.certificate_fields({**CERT, "signer_title": ""})
    assert f["signer_title"] == cw.NO_TITLE
    assert cw.certificate_fields({**CERT, "deposit_amount": None})["deposit_amount"] == cw.NO_DEPOSIT


def test_money_and_revision_are_formatted_for_a_reader():
    f = cw.certificate_fields(CERT)
    assert f["total"] == "$187,450.75" and f["deposit_amount"] == "$46,862.69"
    assert f["revision_no"] == "3"


def test_the_central_timestamp_is_taken_verbatim():
    """No timezone maths here, ever. The portal knows when the signature was taken;
    this box's clock runs ~13 hours off Central."""
    f = cw.certificate_fields(CERT)
    assert f["signed_at_central"] == CERT["signed_at_central"]
    assert f["signed_at_utc"] == CERT["signed_at_utc"]


# ── what the writer refuses ──────────────────────────────────────────────────
def test_a_missing_required_field_is_named():
    for name in ("signer_email", "consent_text", "proposal_pdf_sha256"):
        short = {k: v for k, v in CERT.items() if k != name}
        assert any(name in p for p in cw.field_problems(short)), name


def test_a_blank_required_field_counts_as_missing():
    assert any("signer_name" in p for p in cw.field_problems({**CERT, "signer_name": "   "}))


def test_the_optional_fields_really_are_optional():
    short = {k: v for k, v in CERT.items() if k not in ("signer_title", "deposit_amount")}
    assert cw.field_problems(short) == []


def test_a_mis_shaped_digest_is_refused():
    """The digests are the evidentiary point of the page. A truncated or
    non-hex one printed under "Document integrity" is worse than no page."""
    for bad in ("3f2a1b", "not-a-hash", "z" * 64):
        probs = cw.field_problems({**CERT, "proposal_pdf_sha256": bad})
        assert any("proposal_pdf_sha256" in p for p in probs), bad


def test_a_non_numeric_total_is_refused_by_name():
    assert any("total" in p for p in cw.field_problems({**CERT, "total": "about twenty grand"}))


def test_the_writer_shouts_if_the_template_loses_a_row(tmp_path):
    """A template edited to drop a row would otherwise print a certificate that
    quietly omits a fact — the module raises instead."""
    from docx import Document
    d = Document(str(TEMPLATE))
    for p in d.paragraphs:
        if "{{signer_email}}" in p.text:
            for t in p._p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
                t.text = (t.text or "").replace("{{signer_email}}", "")
    hacked = tmp_path / "hacked.docx"
    d.save(str(hacked))
    with pytest.raises(RuntimeError) as exc:
        cw.build_certificate_docx(CERT, hacked)
    assert "signer_email" in str(exc.value)


# ── the endpoint ─────────────────────────────────────────────────────────────
def test_no_token_is_401(wired):
    assert _post(token=None).status_code == 401


def test_a_wrong_token_is_401(wired):
    r = _post(token="not-the-token")
    assert r.status_code == 401 and r.json()["detail"] == "unauthorized"


def test_an_unset_server_token_cannot_be_matched_by_an_empty_header(monkeypatch):
    """An unconfigured SERVICE_TOKEN must lock the door, not open it to everybody
    who sends no header."""
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    assert _post(token="").status_code == 401


def test_malformed_certificate_json_is_400(wired):
    r = _post(raw_cert="{not json at all")
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False and "certificate" in body["error"]


def test_a_missing_field_is_named_in_the_400(wired):
    for name in ("signer_email", "signed_at_central"):
        short = {k: v for k, v in CERT.items() if k != name}
        r = _post(cert=short)
        assert r.status_code == 400, name
        assert r.json()["ok"] is False
        assert name in r.json()["error"], (name, r.json()["error"])


def test_a_missing_proposal_pdf_is_400(wired):
    r = _post(omit_pdf=True)
    assert r.status_code == 400 and "proposal_pdf" in r.json()["error"]


def test_an_unreadable_proposal_pdf_is_400_not_502(wired):
    """The caller's fault and our fault get paged very differently."""
    r = _post(pdf_bytes=b"this is not a pdf")
    assert r.status_code == 400 and "proposal_pdf" in r.json()["error"]


def test_a_render_failure_is_502_render_failed(wired, monkeypatch):
    def boom(docx_bytes, **kw):
        raise RuntimeError("LibreOffice produced no PDF (rc=1)")
    monkeypatch.setattr(pdf_writer, "docx_to_pdf", boom)
    r = _post()
    assert r.status_code == 502
    assert r.json() == {"ok": False, "error": "render_failed"}


def test_a_signed_contract_comes_back_as_a_pdf(wired):
    r = _post()
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_the_output_is_the_proposal_plus_exactly_one_page(wired):
    n_in = len(pypdf.PdfReader(io.BytesIO(PROPOSAL_PDF)).pages)
    out = pypdf.PdfReader(io.BytesIO(_post().content))
    assert len(out.pages) == n_in + 1


def _page_fingerprint(page):
    """What must not change about a page we are only passing through.

    The DECODED content stream alone is not enough, and that is not a guess: the
    first version of this test compared only `get_data()` and stayed GREEN when the
    handler was mutated to call `compress_content_streams()` on every page. A
    re-encode leaves the drawing operators identical while changing the bytes we
    store — so the stream's FILTER and the page geometry are pinned beside it.
    """
    contents = page["/Contents"].get_object()
    return (contents.get("/Filter"), contents.get_data(),
            str(page.get("/MediaBox")), str(page.get("/Rotate")))


def test_the_proposal_pages_come_through_untouched(wired):
    """THE guarantee. The certificate prints the SHA-256 of the PDF the customer
    opened; if these pages were re-rendered, re-encoded or re-flowed, the document
    we keep would not hash to the value printed on its own last page, and the
    certificate would be evidence against us instead of for us."""
    before = [_page_fingerprint(p)
              for p in pypdf.PdfReader(io.BytesIO(PROPOSAL_PDF)).pages]
    after = [_page_fingerprint(p)
             for p in pypdf.PdfReader(io.BytesIO(_post().content)).pages]
    assert after[:len(before)] == before


def test_both_hashes_appear_in_full_on_the_certificate_page(wired):
    """In full, never elided: a truncated digest proves nothing."""
    page = pypdf.PdfReader(io.BytesIO(_post().content)).pages[-1]
    text = page.extract_text()
    assert PROPOSAL_SHA in text
    assert REVISION_SHA in text


def test_the_certificate_page_carries_the_statute_sentence(wired):
    page = pypdf.PdfReader(io.BytesIO(_post().content)).pages[-1]
    text = page.extract_text()
    # CodeQL's py/incomplete-url-substring-sanitization pattern-matches on the
    # shape `"host" in some_string` wherever it appears -- this is a plain text
    # assertion on a rendered PDF page, not a URL host check gating anything, so
    # there is no arbitrary-position bypass to have. An inline lgtm[] suppression
    # here did not stick; dismissed as a false positive on the alert itself
    # instead (code-scanning alert #91, 2026-09-18).
    assert "portal.wetreadwell.com" in text
    assert "15 U.S.C." in text and "7001" in text
    assert "16-1601" in text


def test_the_certificate_page_carries_the_consent_wording_verbatim(wired):
    """What the customer was shown is the operative text; it is reproduced, not
    paraphrased."""
    text = pypdf.PdfReader(io.BytesIO(_post().content)).pages[-1].extract_text()
    assert CERT["consent_text"] in text.replace("\n", " ")


def test_the_route_is_public_to_the_auth_gate_and_gated_by_the_token():
    """It is server-to-server: the portal has no Google session. The SERVICE_TOKEN
    check inside the handler is the whole gate, so the path has to be in the
    public set AND the handler has to check."""
    assert PATH in main._AUTH_PUBLIC_PATHS
    assert main._auth_is_public(PATH, "POST") is True


@pytest.mark.skipif(not (os.environ.get("TW_RENDER_TESTS") or __import__("shutil").which("soffice")),
                    reason="needs LibreOffice; CI and the dev box render nothing")
def test_the_real_render_is_one_page():
    """The one thing a stubbed renderer cannot prove: the layout fits the page.

    `prepare_signature_certificate_template` budgets ~440pt of a 576pt column with
    every field at a realistic length. Runs wherever soffice exists (the container
    does); skipped elsewhere rather than faked."""
    pdf = cw.build_certificate_pdf(CERT, TEMPLATE)
    assert len(pypdf.PdfReader(io.BytesIO(pdf)).pages) == 1


# ── a caller-controlled value cannot forge a log line or leak an exception ────
# CodeQL flagged this route: `cert` is arbitrary JSON off an authenticated but
# still external POST, and three log calls used to print `cert["proposal_id"]`
# straight into a %s slot -- an embedded CRLF would let anyone holding
# SERVICE_TOKEN write a fabricated log line under a real one. Two other spots
# echoed str(exc) straight into the 400 response body, which is an information
# exposure risk for a library exception whose message is not meant for a caller.
def test_log_safe_strips_control_characters_and_caps_length():
    """The unit itself: repr() is the actual mechanism (CodeQL recognizes it as a
    sanitizer for py/log-injection; a hand-rolled character replace was tried
    first and kept getting flagged), so what lands in a log line is the escaped
    two-character sequence, never the raw byte -- and a value past the cap is
    truncated rather than flooding a log line."""
    forged = "real-id\r\n2026-01-01 ERROR fake admin login succeeded"
    safe = main._log_safe(forged)
    assert "\r" not in safe and "\n" not in safe
    # The escape sequences themselves show up as visible text -- that is the
    # point, not an accident: a log reader sees exactly what was sent.
    assert "\\r\\n" in safe
    # The forged line's own text survives (it is not secret), just unable to
    # start a new log record -- \r and \n are the only bytes that matter here.
    assert "fake admin login succeeded" in safe

    assert main._log_safe(None) == "''"
    long_value = "x" * 500
    capped = main._log_safe(long_value, limit=50)
    # 50 chars + the ellipsis mark, then repr()'s own quoting around all of it.
    assert capped.startswith("'") and capped.endswith("…'")
    assert len(capped) == 50 + len("…") + 2  # + the two quote characters repr() adds


def test_a_forged_proposal_id_cannot_inject_a_second_log_line(monkeypatch, caplog):
    """DRIVEN THROUGH THE REAL ENDPOINT, not the helper in isolation -- a sanitizer
    that exists but is never called on the actual request path protects nothing.

    Forces the render itself to fail (rather than a field-validation refusal,
    which never reaches the proposal_id log line at all) so this actually
    exercises the "certificate render failed for proposal %s" site -- one of
    the three that used to log proposal_id unsanitized."""
    monkeypatch.setenv("SERVICE_TOKEN", TOKEN)

    def _boom(docx_bytes, **kw):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(pdf_writer, "docx_to_pdf", _boom)
    caplog.set_level("WARNING")
    forged_id = "legit-1\r\nCRITICAL admin_override=true"
    bad_cert = dict(CERT)
    bad_cert["proposal_id"] = forged_id
    resp = _post(cert=bad_cert)
    assert resp.status_code == 502
    assert any("render failed" in r.getMessage() for r in caplog.records), (
        "this test did not actually reach the log line it means to check")
    for record in caplog.records:
        assert "\r" not in record.getMessage()
        assert "\n" not in record.getMessage()


def test_a_bad_certificate_json_does_not_echo_the_parser_exception(wired):
    """400, but the body says what is wrong in one plain sentence -- not whatever
    text json.JSONDecodeError happened to compose (position, line/column, quoted
    fragments of the bad input)."""
    resp = _post(raw_cert="{not json")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "certificate is not valid JSON"
    assert "line" not in body["error"] and "column" not in body["error"]


def test_an_unreadable_proposal_pdf_does_not_echo_the_reader_exception(wired):
    """Same guarantee for the other exception-message site: pypdf's own error text
    (which can quote raw bytes) never reaches the response body."""
    resp = _post(pdf_bytes=b"not a pdf at all")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "proposal_pdf is not a readable PDF"
