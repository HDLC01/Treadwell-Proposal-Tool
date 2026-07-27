"""Staff invoice preview: render the review-form fields WITHOUT sending.

The point of edit-before-send is that what staff approve on screen is exactly
what the customer receives, so the preview must use the same fields and the same
renderer as the real send — and must not write or email anything.
"""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
PATH = "/api/portal/proposal/testpid123/invoice-preview"


def _stub(monkeypatch, box):
    monkeypatch.setattr(main.invoice_writer, "build_invoice_pdf",
                        lambda payload, tpl: box.update(payload=payload) or b"%PDF-1.4 stub")
    # No portal round-trip in tests; the handler must survive it failing.
    monkeypatch.setattr(main, "_portal", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))


def test_preview_returns_a_pdf(monkeypatch):
    box = {}
    _stub(monkeypatch, box)
    r = client.post(PATH, json={"amount": 8246.25,
                                "invoice": {"invoice_no": "26.114-01", "customer_name": "Acme LLC"}})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_preview_uses_the_edited_fields(monkeypatch):
    box = {}
    _stub(monkeypatch, box)
    client.post(PATH, json={"amount": 999.0, "invoice": {
        "invoice_no": "26.999-07", "customer_name": "Edited Name", "city_state": "Olathe, KS"}})
    p = box["payload"]
    assert p["invoice_no"] == "26.999-07"
    assert p["customer_name"] == "Edited Name"
    assert p["city_state"] == "Olathe, KS"
    assert p["deposit_amount"] == 999.0 and p["total_due"] == 999.0


def test_preview_survives_the_portal_being_unreachable(monkeypatch):
    """A preview is a staff convenience — it must still render when the portal
    lookup for the contract value fails."""
    box = {}
    _stub(monkeypatch, box)
    r = client.post(PATH, json={"amount": 10.0, "invoice": {"invoice_no": "1"}})
    assert r.status_code == 200


def test_preview_never_sends_or_writes(monkeypatch):
    """Guard the invariant: the preview path must not touch the send helpers."""
    box = {}
    _stub(monkeypatch, box)
    called = []
    monkeypatch.setattr(main, "_portal",
                        lambda path, *a, **k: called.append(path) or {"proposal": {}})
    client.post(PATH, json={"amount": 10.0, "invoice": {}})
    assert not any("deposit-request" in c for c in called)
