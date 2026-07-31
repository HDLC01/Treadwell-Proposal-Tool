"""/api/portal/publish proxy — the optional multi-recipient body.

The endpoint forwards to the external portal's /api/admin/publish. These tests
monkeypatch main._portal to capture exactly what gets forwarded, and
main.drafts.load_draft so the existence check passes without a DB. The conftest
autouse fixture authenticates every request as tester@wetreadwell.com."""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

URL = "/api/portal/publish?draft_id=d1"


def _wire(monkeypatch, role="admin"):
    captured = {}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {}})
    # _require_admin / _caller_is_admin resolve the caller's role via profiles;
    # stub it so the admin-gated notify endpoints don't hit Supabase in CI.
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": role})
    # Every publish snapshots the draft as a revision (the portal pins the customer
    # view to it). Recorded LAZILY — several tests assert `cap == {}` to mean "the
    # request never reached the portal", so pre-seeding keys here would break them.
    monkeypatch.setattr(main.drafts, "create_revision",
                        lambda did, data, by=None:
                        captured.setdefault("revisions", []).append((did, by)) or 1)
    monkeypatch.setattr(main.drafts, "delete_revision",
                        lambda did, no: captured.setdefault("deleted", []).append((did, no)))
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)

    def fake_portal(path, method="GET", body=None):
        captured.update(path=path, method=method, body=body)
        return {"ok": True, "url": "https://portal/x", "customer_email": "c@x.com",
                "recipients": (body or {}).get("emails") or ["c@x.com"]}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return captured


def test_no_body_sends_only_the_essentials(monkeypatch):
    """A body-less call must still forward nothing optional — no emails key, no
    require_deposit — so the portal's own defaults apply. `revision_no` is not
    optional: every send snapshots what it sent, which is what the customer's view
    is then pinned to."""
    cap = _wire(monkeypatch)
    r = client.post(URL)
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/publish" and cap["method"] == "POST"
    assert cap["body"] == {"draft_id": "d1", "by": "tester@wetreadwell.com", "revision_no": 1}


def test_snapshot_is_taken_before_the_portal_call(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.post(URL).status_code == 200
    assert cap.get("revisions") == [("d1", "tester@wetreadwell.com")]
    assert cap["body"]["revision_no"] == 1
    assert cap.get("deleted", []) == []


def test_snapshot_is_rolled_back_when_the_send_fails(monkeypatch):
    """A snapshot represents a version the customer RECEIVED. If the portal call
    fails, nothing was received, so the revision must not survive and misreport the
    history to staff."""
    cap = _wire(monkeypatch)

    def boom(path, method="GET", body=None):
        raise main.HTTPException(502, "portal down")

    monkeypatch.setattr(main, "_portal", boom)
    r = client.post(URL)
    assert r.status_code == 502
    assert cap.get("revisions") == [("d1", "tester@wetreadwell.com")]
    assert cap.get("deleted") == [("d1", 1)]


def test_no_snapshot_when_validation_rejects_the_request(monkeypatch):
    """A 400 must not mint a revision — otherwise a typo in an email address would
    leave a phantom "sent" version in the project's history."""
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["not-an-email"]})
    assert r.status_code == 400
    assert cap.get("revisions", []) == [] and cap.get("deleted", []) == []


def test_forwards_require_deposit_both_ways(monkeypatch):
    """The Files-page checkbox. False is the interesting one — it must survive as an
    explicit False rather than being dropped as falsy, or a GC job would silently
    get a deposit invoice on approval."""
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"require_deposit": True}).status_code == 200
    assert cap["body"]["require_deposit"] is True
    cap2 = _wire(monkeypatch)
    assert client.post(URL, json={"require_deposit": False}).status_code == 200
    assert cap2["body"]["require_deposit"] is False


def test_require_deposit_omitted_when_not_specified(monkeypatch):
    """A body without the field must not send one: the portal reads a missing field
    as "keep what you have", so a re-send from an older page can't flip a job that
    was deliberately sent without a deposit."""
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"emails": ["a@x.com"]}).status_code == 200
    assert "require_deposit" not in cap["body"]


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


def test_notify_add_requires_admin(monkeypatch):
    _wire(monkeypatch, role="user")                              # non-admin caller
    r = client.post("/api/portal/notify-recipients", json={"email": "a@x.com"})
    assert r.status_code == 403


def test_notify_toggle_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.patch("/api/portal/notify-recipients/5", json={"enabled": False})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/notify-recipients/5" and cap["method"] == "PATCH"
    assert cap["body"] == {"enabled": False}


# ── per-project notify overrides proxy ────────────────────────────────────────
def test_overrides_get_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.get("/api/portal/proposal/p1/notify-overrides")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/proposal/p1/notify-overrides" and cap["method"] == "GET"


def test_overrides_all_proxies(monkeypatch):
    cap = _wire(monkeypatch)                                     # read-only, not admin-gated
    r = client.get("/api/portal/notify-overrides-all")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/notify-overrides" and cap["method"] == "GET"


def test_overrides_put_admin_forwards(monkeypatch):
    cap = _wire(monkeypatch)                                     # admin
    r = client.put("/api/portal/proposal/p1/notify-overrides", json={"email": "Dane@X.com", "mode": "add"})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/proposal/p1/notify-overrides" and cap["method"] == "PUT"
    assert cap["body"] == {"email": "dane@x.com", "mode": "add"}


def test_overrides_put_nonadmin_self_ok(monkeypatch):
    cap = _wire(monkeypatch, role="user")                        # non-admin toggling THEMSELVES
    r = client.put("/api/portal/proposal/p1/notify-overrides",
                   json={"email": "tester@wetreadwell.com", "mode": "mute"})
    assert r.status_code == 200, r.text
    assert cap["body"] == {"email": "tester@wetreadwell.com", "mode": "mute"}


def test_overrides_put_nonadmin_other_forbidden(monkeypatch):
    cap = _wire(monkeypatch, role="user")                        # non-admin toggling SOMEONE ELSE
    r = client.put("/api/portal/proposal/p1/notify-overrides", json={"email": "dane@x.com", "mode": "add"})
    assert r.status_code == 403
    assert cap == {}                                             # _portal never called


def test_overrides_put_rejects_bad_mode(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.put("/api/portal/proposal/p1/notify-overrides", json={"email": "a@x.com", "mode": "boss"})
    assert r.status_code == 400
    assert cap == {}
