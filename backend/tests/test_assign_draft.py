"""Assigning an estimator from the Projects tab.

Projects rows are DRAFTS, most never sent, so the assignment lives in the draft's
`data` blob (the copy that pre-fills the Files-page picker). A project the customer
already has ALSO carries it on the portal row — the copy the CRM board and the morning
digest actually read — so a sent project has to be forwarded there too.

The two failure modes worth pinning: an unsent draft must not make a pointless portal
call, and a portal failure on a sent draft must not throw away the draft write that
already succeeded.
"""
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)
URL = "/api/draft/proj-9/assign"
KYLE = "kyle@wetreadwell.com"


def _seed(fake_supabase):
    store = {"drafts": [
        {"id": "a", "data": {"project_name": "Oak Grove"}, "owner_email": "u@x.com",
         "created_at": "2026-01-01", "updated_at": "2026-01-02", "deleted_at": None},
    ], "events": []}
    return fake_supabase(store), store


# ── drafts.py logic (against the in-memory Supabase fake) ───────────────
def test_it_writes_the_blob_and_logs_who_it_went_to(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)

    assert drafts.set_assigned_estimator("a", KYLE, "hanz@wetreadwell.com") is True
    assert store["drafts"][0]["data"]["assigned_estimator"] == KYLE
    ev = [e for e in store["events"] if e["action"] == "assigned"]
    assert len(ev) == 1
    assert ev[0]["detail"]["to"] == KYLE
    assert ev[0]["detail"]["project_name"] == "Oak Grove"
    assert ev[0]["actor_email"] == "hanz@wetreadwell.com"


def test_assigning_does_not_reorder_the_projects_list(fake_supabase, monkeypatch):
    """Handing a project to a colleague isn't work on the estimate. Bumping
    updated_at would shuffle it to the top of a list sorted by date updated, which
    reads as somebody having touched the numbers."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_assigned_estimator("a", KYLE)
    assert store["drafts"][0]["updated_at"] == "2026-01-02"


def test_it_keeps_the_rest_of_the_blob(fake_supabase, monkeypatch):
    """Read-modify-write, so the estimate must survive the assignment."""
    fake, store = _seed(fake_supabase)
    store["drafts"][0]["data"]["computed_bid"] = {"total": 41500}
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_assigned_estimator("a", KYLE)
    assert store["drafts"][0]["data"]["computed_bid"] == {"total": 41500}
    assert store["drafts"][0]["data"]["project_name"] == "Oak Grove"


def test_reassigning_replaces_rather_than_accumulates(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_assigned_estimator("a", KYLE)
    drafts.set_assigned_estimator("a", "troy@wetreadwell.com")
    assert store["drafts"][0]["data"]["assigned_estimator"] == "troy@wetreadwell.com"


def test_a_missing_project_reports_false(fake_supabase, monkeypatch):
    fake, _ = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_assigned_estimator("nope", KYLE) is False


def test_the_summary_surfaces_it_for_the_projects_list(fake_supabase):
    row = {"id": "z", "data": {"project_name": "P", "assigned_estimator": KYLE},
           "owner_email": "u@x.com"}
    assert drafts._summary(row)["assigned_estimator"] == KYLE
    assert drafts._summary({"id": "z2", "data": {}, "owner_email": "u@x.com"}
                           )["assigned_estimator"] is None


# ── the endpoint ────────────────────────────────────────────────────────
def _wire(monkeypatch, *, sent=0, portal=None):
    """Stub the draft write, the revision lookup and the portal call."""
    cap = {"assigned": [], "portal": []}
    monkeypatch.setattr(main.drafts, "set_assigned_estimator",
                        lambda i, e, actor=None: cap["assigned"].append((i, e, actor)) or True)
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda i: sent or None)

    def fake_portal(path, method="GET", body=None):
        cap["portal"].append((path, method, body))
        if portal == "fail":
            raise RuntimeError("portal down")
        return {"ok": True}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return cap


def test_an_unsent_draft_is_saved_without_calling_the_portal(monkeypatch):
    """There is no portal row for a project that was never sent, so the round-trip
    would be a guaranteed 404 on the one path that must stay fast."""
    cap = _wire(monkeypatch, sent=0)
    r = client.post(URL, json={"estimator_email": KYLE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "assigned_estimator": KYLE,
                    "portal_updated": False, "sent": False}
    assert cap["assigned"] == [("proj-9", KYLE, "tester@wetreadwell.com")]
    assert cap["portal"] == []


def test_a_sent_project_also_moves_on_the_portal(monkeypatch):
    """The portal row is what the CRM board and the digest read, so assigning only
    the draft would leave the customer-facing side pointing at the wrong person."""
    cap = _wire(monkeypatch, sent=2)
    r = client.post(URL, json={"estimator_email": KYLE})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "assigned_estimator": KYLE,
                        "portal_updated": True, "sent": True}
    assert cap["portal"] == [("/api/admin/proposal/proj-9/assign", "POST",
                              {"estimator_email": KYLE, "by": "tester@wetreadwell.com"})]


def test_a_portal_failure_keeps_the_draft_write_and_says_so(monkeypatch):
    """The draft write already succeeded. Failing the request would report a loss that
    didn't happen; reporting success would hide that the CRM is behind."""
    cap = _wire(monkeypatch, sent=1, portal="fail")
    r = client.post(URL, json={"estimator_email": KYLE})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "assigned_estimator": KYLE,
                        "portal_updated": False, "sent": True}
    assert len(cap["assigned"]) == 1


def test_the_address_is_normalised(monkeypatch):
    cap = _wire(monkeypatch, sent=0)
    r = client.post(URL, json={"estimator_email": "  Kyle@WeTreadwell.com "})
    assert r.status_code == 200
    assert cap["assigned"][0][1] == KYLE


def test_a_missing_or_malformed_address_writes_nothing(monkeypatch):
    cap = _wire(monkeypatch, sent=0)
    for bad, err in (("", "missing_estimator"), ("   ", "missing_estimator"),
                     ("not-an-email", "invalid_estimator")):
        r = client.post(URL, json={"estimator_email": bad})
        assert r.status_code == 400, bad
        assert err in r.text
    r = client.post(URL, json={})
    assert r.status_code == 400 and "missing_estimator" in r.text
    assert cap["assigned"] == [] and cap["portal"] == []


def test_an_unknown_project_is_a_404(monkeypatch):
    _wire(monkeypatch, sent=0)
    monkeypatch.setattr(main.drafts, "set_assigned_estimator", lambda i, e, actor=None: False)
    r = client.post(URL, json={"estimator_email": KYLE})
    assert r.status_code == 404 and "project_not_found" in r.text


def test_a_broken_revision_lookup_does_not_undo_the_assignment(monkeypatch):
    """The draft is already written by then. Reading the revision table is only how we
    decide whether a portal call is warranted."""
    cap = _wire(monkeypatch, sent=0)

    def boom(_id):
        raise RuntimeError("revisions table missing")

    monkeypatch.setattr(main.drafts, "latest_revision_no", boom)
    r = client.post(URL, json={"estimator_email": KYLE})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(cap["assigned"]) == 1 and cap["portal"] == []


def test_a_failed_draft_write_is_reported_not_swallowed(monkeypatch):
    _wire(monkeypatch, sent=0)

    def boom(i, e, actor=None):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(main.drafts, "set_assigned_estimator", boom)
    assert client.post(URL, json={"estimator_email": KYLE}).status_code == 502


# ── the Projects-page wiring, checked against the source ────────────────
# The markup is built in one function and the click is handled in another, and a
# mismatch between them is a button that silently does nothing. Same class of bug the
# drawer shipped twice; same style of guard.
import pathlib  # noqa: E402

PROJECTS_JS = (pathlib.Path(__file__).resolve().parents[2]
               / "frontend" / "js" / "projects.js").read_text(encoding="utf-8")
PROJECTS_HTML = (pathlib.Path(__file__).resolve().parents[2]
                 / "frontend" / "projects.html").read_text(encoding="utf-8")


def test_the_pencil_renders_in_both_views():
    """Cards and table both show an Estimator now, so both need the affordance —
    a table-only control leaves whoever prefers cards with no way to assign."""
    cards = PROJECTS_JS[PROJECTS_JS.index("function cardsHtml"):PROJECTS_JS.index("// ── the same projects as one table")]
    table = PROJECTS_JS[PROJECTS_JS.index("function tableHtml"):PROJECTS_JS.index("// ── one delegated listener")]
    assert "estBtn(p)" in cards, "the cards view renders no assign button"
    assert "estBtn(p)" in table, "the table view renders no assign button"
    assert 'class="est-btn"' in PROJECTS_JS


def test_the_delegated_handler_reaches_for_it():
    wire = PROJECTS_JS[PROJECTS_JS.index("(function wireList()"):]
    assert '.est-btn' in wire, "nothing routes a pencil click"
    # Without stopPropagation the row's own click opens the project underneath the dialog.
    i = wire.index('.est-btn')
    assert "stopPropagation" in wire[i:i + 160]


def test_the_dialog_is_styled():
    """It's built by createElement against classes that live in the page's CSS; a
    missing rule renders an unstyled block over the list."""
    for cls in (".est-ov", ".est-dlg", ".est-btn"):
        assert cls in PROJECTS_HTML, f"{cls} has no CSS"


def test_it_posts_to_the_endpoint_this_module_tests():
    assert '"/api/draft/" + encodeURIComponent(id) + "/assign"' in PROJECTS_JS


def test_the_roster_comes_from_the_shared_endpoint():
    """Same source as the Files-page picker and the drawer, so the three can't offer
    different people."""
    assert '"/api/estimators"' in PROJECTS_JS


def test_a_stale_portal_copy_is_surfaced_to_the_user():
    """The draft saved but the CRM didn't. Silence here would leave the follow-ups and
    the digest pointing at the wrong estimator with nobody aware."""
    assert "portal_updated === false" in PROJECTS_JS
