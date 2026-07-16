"""/api/portal/publish proxy — the optional multi-recipient body.

The endpoint forwards to the external portal's /api/admin/publish. These tests
monkeypatch main._portal to capture exactly what gets forwarded, and
main.drafts.load_draft so the existence check passes without a DB. The conftest
autouse fixture authenticates every request as tester@wetreadwell.com."""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

URL = "/api/portal/publish?draft_id=d1"


def _wire(monkeypatch):
    captured = {}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {}})

    def fake_portal(path, method="GET", body=None):
        captured.update(path=path, method=method, body=body)
        return {"ok": True, "url": "https://portal/x", "customer_email": "c@x.com",
                "recipients": (body or {}).get("emails") or ["c@x.com"]}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return captured


def test_no_body_is_legacy(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL)
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/publish" and cap["method"] == "POST"
    assert cap["body"] == {"draft_id": "d1", "by": "tester@wetreadwell.com"}   # no emails key


def test_forwards_valid_emails(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": [" A@x.com ", "b@y.co"]})
    assert r.status_code == 200, r.text
    assert cap["body"]["emails"] == ["A@x.com", "b@y.co"]        # trimmed, casing preserved
    assert cap["body"]["draft_id"] == "d1"


def test_dedupes_case_insensitively(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["a@x.com", "A@X.COM", "b@y.co"]})
    assert r.status_code == 200
    assert cap["body"]["emails"] == ["a@x.com", "b@y.co"]


def test_empty_or_blank_list_is_legacy(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"emails": []}).status_code == 200
    assert "emails" not in cap["body"]
    assert client.post(URL, json={"emails": ["", "  "]}).status_code == 200
    assert "emails" not in cap["body"]


def test_rejects_invalid_email(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["not-an-email"]})
    assert r.status_code == 400 and "invalid_email" in r.text
    assert cap == {}                                            # _portal never called


def test_caps_at_ten(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": [f"u{i}@x.com" for i in range(11)]})
    assert r.status_code == 400 and "too_many_emails" in r.text
    assert cap == {}


def test_garbage_body_never_500s(monkeypatch):
    _wire(monkeypatch)
    r = client.post(URL, content=b"{{{", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    r = client.post(URL, json={"emails": "a@x.com"})           # string, not list
    assert r.status_code == 422


def test_404_when_draft_missing(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: None)
    assert client.post(URL, json={"emails": ["a@x.com"]}).status_code == 404


def test_rejects_unsafe_draft_id(monkeypatch):
    _wire(monkeypatch)
    r = client.post("/api/portal/publish?draft_id=..%2Fevil", json={"emails": ["a@x.com"]})
    assert r.status_code == 400


# ── deposit-request proxy (staff-triggered) ───────────────────────────────────
def test_deposit_request_no_body_omits_amount(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/p1/deposit-request")
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/proposal/p1/deposit-request" and cap["method"] == "POST"
    assert cap["body"] == {"by": "tester@wetreadwell.com"}     # no amount key when none sent


def test_deposit_request_forwards_amount_override(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/p1/deposit-request", json={"amount": 1500})
    assert r.status_code == 200, r.text
    assert cap["body"]["amount"] == 1500 and cap["body"]["by"] == "tester@wetreadwell.com"


def test_deposit_request_null_amount_omitted(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/p1/deposit-request", json={"amount": None})
    assert r.status_code == 200, r.text
    assert "amount" not in cap["body"]


# ── notify-recipients proxy ───────────────────────────────────────────────────
def test_notify_list_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.get("/api/portal/notify-recipients")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/notify-recipients" and cap["method"] == "GET"


def test_notify_add_forwards_cleaned(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": " Kyle@X.com ", "kind": "deposit"})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/notify-recipients" and cap["method"] == "POST"
    assert cap["body"] == {"email": "kyle@x.com", "kind": "deposit", "by": "tester@wetreadwell.com"}


def test_notify_add_defaults_kind_general(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": "a@x.com"})
    assert r.status_code == 200
    assert cap["body"]["kind"] == "general"


def test_notify_add_rejects_bad_email(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": "nope", "kind": "general"})
    assert r.status_code == 400
    assert cap == {}                                             # _portal never called


def test_notify_add_rejects_bad_kind(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": "a@x.com", "kind": "boss"})
    assert r.status_code == 400
    assert cap == {}


def test_notify_delete_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.delete("/api/portal/notify-recipients/7")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/notify-recipients/7" and cap["method"] == "DELETE"
