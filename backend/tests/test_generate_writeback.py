"""A generate must never push its own frozen pricing back over a newer draft.

THE PATH. `/api/generate` receives a payload whose `values` is a SPREAD OF THE WHOLE PAGE STATE as
it stood when the payload was built — the last time somebody pressed Continue on the Proposal step.
Since generation moved to the Done page, the write-back at the end of the handler exists so a
belt-and-suspenders save happens even if the browser's own persist failed. It merged `values` over
the stored draft.

That merge is time travel. Every re-generate replays an OLD moment:

    • "View files" on a project opens the Done page in files mode, which re-POSTs the stored payload
    • a download token expires on a container restart and the Done page self-heals by regenerating
    • the customer's portal PDF is re-rendered on demand from the pinned revision's payload
    • "Rebuild documents" on a revision from March replays MARCH

Each of those carried that moment's `rooms`, `base_tab_id`, `proposal_lump_sum` — and its own
nested copy of `proposal_payload` — straight over whatever the estimator has since re-priced. The
portal PAGE reads `rooms` from the draft and falls back to `computed_bid` for a base-only price, so
a replay could revert what a customer sees WITHOUT anyone touching the Proposal screen.

TWO DEFENCES, BOTH TESTED HERE:
1. `_GENERATE_WRITEBACK_DRAFT_AUTHORITY` — the draft outranks the payload's echo for these keys
   whenever the draft already has them. The payload may still SEED them on a first save.
2. `persist=False` on the three server-side replay callers, so those paths cannot write at all.

Belt AND braces on purpose: (1) protects the browser route that legitimately persists, (2) makes the
replays incapable of touching a draft even if a future key is added to the payload and forgotten in
the authority list.
"""
import inspect

import main
import pytest
from fastapi.testclient import TestClient


def _payload(**values):
    """A generate body carrying an echo of page state, as the frontend sends it."""
    return {"work_type": "epoxy", "audience": "Direct",
            "values": {"project_name": "Westport", **values}}


@pytest.fixture
def captured(monkeypatch):
    """Run a generate against stubbed file writers and capture what got saved."""
    saved = {}

    def _save(draft_id, data, owner_email=None, **kw):
        saved["draft_id"] = draft_id
        saved["data"] = data
        return {"ok": True}

    monkeypatch.setattr(main.drafts, "save_draft", _save)
    monkeypatch.setattr(main.estimate_writer, "fill_estimate", lambda *a, **k: b"xlsx")
    monkeypatch.setattr(main.proposal_writer, "fill_proposal", lambda *a, **k: b"docx")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    return saved


# ── the authority list ───────────────────────────────────────────────────────
STALE_ECHO = {
    "rooms": [{"name": "Polish", "is_base": True, "bid": {"total": 13265}}],
    "base_tab_id": "Polish",
    "proposal_lump_sum": 13265,
    "proposal_sales_tax": 420,
    "proposal_remodel_tax": 0,
    "sheet_area": {"polish_sf": 5000},
    "price_lines": [{"label": "old line"}],
    "price_overrides": {"lines": {"base": "old wording"}},
    "computed_bid": {"full_bid": {"total": 13265}},
    "alternate_computed_bid": {"full_bid": {"total": 1}},
    "tab_notes": {"Polish": "old note"},
    "tab_opts": {"Polish": {}},
    "priced_tabs": [{"id": "Polish", "role": "polish"}],
    "proposal_payload": {"values": {"total_formatted": "$13,265.00"}},
    "generate_result": {"docx_download_url": "/api/files/old"},
}
LIVE_DRAFT = {
    "project_name": "Westport",
    "rooms": [{"name": "Epoxy", "is_base": True, "bid": {"total": 18670}}],
    "base_tab_id": "Epoxy",
    "proposal_lump_sum": 18670,
    "proposal_sales_tax": 610,
    "proposal_remodel_tax": 900,
    "sheet_area": {"epoxy_sf": 7400},
    "price_lines": [{"label": "new line"}],
    "price_overrides": {"lines": {"base": "new wording"}},
    "computed_bid": {"full_bid": {"total": 18670}},
    "alternate_computed_bid": {"full_bid": {"total": 2}},
    "tab_notes": {"Epoxy": "new note"},
    "tab_opts": {"Epoxy": {}},
    "priced_tabs": [{"id": "Epoxy", "role": "epoxy"}],
    "proposal_payload": {"values": {"total_formatted": "$18,670.00"}},
    "generate_result": {"docx_download_url": "/api/files/new"},
}


def test_a_stale_echo_cannot_revert_the_live_draft(monkeypatch, captured):
    """The incident's shape, server side: the browser replays a payload built when Polish was the
    base at $13,265, over a draft that now says Epoxy at $18,670."""
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": dict(LIVE_DRAFT)})
    r = TestClient(main.app).post("/api/generate", json=_payload(**STALE_ECHO),
                                  headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    data = captured["data"]
    for key, live in LIVE_DRAFT.items():
        if key == "project_name":
            continue
        assert data[key] == live, f"{key} was reverted to the payload's stale copy"


def test_every_authority_key_is_actually_defended(monkeypatch, captured):
    """Names the list rather than a hand-picked subset, so adding a key to
    `_GENERATE_WRITEBACK_DRAFT_AUTHORITY` without defending it fails here."""
    live = {k: f"live-{k}" for k in main._GENERATE_WRITEBACK_DRAFT_AUTHORITY}
    live["project_name"] = "Westport"
    stale = {k: f"stale-{k}" for k in main._GENERATE_WRITEBACK_DRAFT_AUTHORITY}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": dict(live)})
    r = TestClient(main.app).post("/api/generate", json=_payload(**stale),
                                  headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    for k in main._GENERATE_WRITEBACK_DRAFT_AUTHORITY:
        assert captured["data"][k] == f"live-{k}", f"{k} is in the list but not defended"


def test_the_pricing_keys_the_portal_reads_are_in_the_list():
    """The portal page renders `rooms` and falls back to `computed_bid` for a base-only price, and
    the customer's PDF is rebuilt from `proposal_payload`. Those three are the ones whose loss a
    customer can SEE, so pin them by name — a refactor that trims the list must fail here."""
    for k in ("rooms", "computed_bid", "proposal_payload", "proposal_lump_sum", "base_tab_id"):
        assert k in main._GENERATE_WRITEBACK_DRAFT_AUTHORITY


def test_a_first_save_still_seeds_everything(monkeypatch, captured):
    """The write-back's original purpose. On a draft that has never stored pricing, the payload IS
    the only copy — refusing it here would lose the estimate instead of protecting it."""
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {"project_name": "Westport"}})
    r = TestClient(main.app).post("/api/generate", json=_payload(**STALE_ECHO),
                                  headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    for key, seeded in STALE_ECHO.items():
        assert captured["data"][key] == seeded, f"{key} was not seeded on a first save"


def test_a_missing_draft_row_still_seeds(monkeypatch, captured):
    """`load_draft` returning None (a draft id that isn't in the table yet) is the same case."""
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: None)
    r = TestClient(main.app).post("/api/generate", json=_payload(**STALE_ECHO),
                                  headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    assert captured["data"]["proposal_lump_sum"] == 13265


def test_non_authority_fields_still_write_through(monkeypatch, captured):
    """The guard is a scalpel, not a wall: the narrative and intake fields a generate legitimately
    carries must still reach the draft, or a Continue-then-generate would stop saving edits."""
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {
        **LIVE_DRAFT, "scope_notes": "old scope", "address": "old address"}})
    r = TestClient(main.app).post("/api/generate", json=_payload(
        scope_notes="new scope", address="new address", **STALE_ECHO),
        headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    assert captured["data"]["scope_notes"] == "new scope"
    assert captured["data"]["address"] == "new address"
    assert captured["data"]["proposal_lump_sum"] == 18670, "pricing leaked through anyway"


def test_computed_bid_is_seed_only(monkeypatch, captured):
    """`payload.computed_bid` was assigned unconditionally, AFTER the merge — so it overwrote the
    draft's engine totals even though `values` was already guarded. The portal's base-only price
    reads this field, so a replay could change what a customer is quoted."""
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {
        "project_name": "Westport", "computed_bid": {"full_bid": {"total": 18670}}}})
    body = {**_payload(), "computed_bid": {"full_bid": {"total": 13265}}}
    r = TestClient(main.app).post("/api/generate", json=body, headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    assert captured["data"]["computed_bid"] == {"full_bid": {"total": 18670}}


def test_computed_bid_seeds_when_the_draft_has_none(monkeypatch, captured):
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {"project_name": "Westport"}})
    body = {**_payload(), "computed_bid": {"full_bid": {"total": 13265}}}
    r = TestClient(main.app).post("/api/generate", json=body, headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    assert captured["data"]["computed_bid"] == {"full_bid": {"total": 13265}}


def test_the_work_type_and_name_still_travel(monkeypatch, captured):
    """`work_type` is authoritative on the payload (it picks the template), and the project name is
    a setdefault. Neither is in the authority list and both must keep working."""
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {"work_type": "polish"}})
    r = TestClient(main.app).post("/api/generate", json=_payload(), headers={"X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    assert captured["data"]["work_type"] == "epoxy"
    assert captured["data"]["project_name"] == "Westport"


def test_no_project_id_header_writes_nothing(monkeypatch):
    """An anonymous generate (no draft) must not invent a row."""
    called = []
    monkeypatch.setattr(main.drafts, "save_draft", lambda *a, **k: called.append(a))
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: None)
    monkeypatch.setattr(main.estimate_writer, "fill_estimate", lambda *a, **k: b"xlsx")
    monkeypatch.setattr(main.proposal_writer, "fill_proposal", lambda *a, **k: b"docx")
    c = TestClient(main.app)
    assert c.post("/api/generate", json=_payload()).status_code == 200
    assert c.post("/api/generate", json=_payload(),
                  headers={"X-Project-Id": "no-draft"}).status_code == 200
    assert called == []


# ── the replay callers ───────────────────────────────────────────────────────
def test_a_browser_generate_persists_and_a_replay_does_not():
    """The one behavioural difference between the route and `_generate`. Asserted on the DEFAULT so
    a future caller that forgets the keyword still persists (the safe direction for the browser)
    while the three replays opt out explicitly."""
    sig = inspect.signature(main._generate)
    assert sig.parameters["persist"].default is True
    assert sig.parameters["persist"].kind is inspect.Parameter.KEYWORD_ONLY
    route = inspect.getsource(main.api_generate)
    assert "persist=True" in route


def _statements(fn):
    """A function's source with comment-only lines removed.

    Every one of these routes carries a comment EXPLAINING why it passes persist=False, so a naive
    `"persist=False" in source` check is satisfied by the prose while the call itself says True. A
    mutation flipping api_to_dropbox survived on exactly that."""
    lines = [l for l in inspect.getsource(fn).splitlines() if not l.strip().startswith("#")]
    return "\n".join(l.split("#")[0] for l in lines)


@pytest.mark.parametrize("caller", ["api_admin_proposal_pdf", "api_draft_revision_files",
                                    "api_to_dropbox"])
def test_every_replay_caller_opts_out_of_persisting(caller):
    """These three re-run a payload frozen at some earlier moment. Named individually because each
    one is a separate route somebody could add a fourth sibling to — and because the customer PDF
    path is reachable by anyone holding a portal link."""
    src = _statements(getattr(main, caller))
    assert "_generate(" in src, f"{caller} no longer calls _generate — recheck this guard"
    assert "persist=False" in src, f"{caller} replays a stored payload AND persists it"


def test_to_dropbox_replays_read_only(monkeypatch):
    """Executed, not read: To Dropbox regenerates from the SAVED payload so the filed copy matches
    the latest estimate. Feeding those values back into the draft can only re-age it — and the two
    other replay paths are covered behaviourally in test_revision_endpoints.py."""
    seen = {}
    payload = {"work_type": "epoxy", "audience": "Direct",
               "values": {"project_name": "Westport", "proposal_lump_sum": 13265}}
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {"proposal_payload": payload,
                                                     "project_name": "Westport"}})

    def fake_generate(gi, request, *, persist=True):
        seen["persist"] = persist
        return main.GenerateOut(work_type="epoxy", audience="Direct",
                                xlsx_download_url="/api/files/x",
                                docx_download_url="/api/files/d",
                                pdf_download_url="/api/files/d/pdf", totals={})

    monkeypatch.setattr(main, "_generate", fake_generate)
    monkeypatch.setitem(main._FILE_CACHE, "x", {"content": b"xlsx"})
    monkeypatch.setitem(main._FILE_CACHE, "d", {"content": b"docx", "_pdf": b"%PDF-1.4"})
    monkeypatch.setattr(main.dropbox_client, "destination_path", lambda d: "/Estimating/Gyp")
    monkeypatch.setattr(main.dropbox_client, "upload_project_files",
                        lambda **kw: {"ok": True, "folder_url": "https://dropbox/x"})
    r = TestClient(main.app).post("/api/to-dropbox",
                                  json={"draft_id": "d1", "destination": "gyp"})
    assert r.status_code == 200, r.text
    assert seen.get("persist") is False, "filing to Dropbox wrote the stored payload back"


def test_no_internal_caller_uses_the_route_function():
    """`api_generate` is the HTTP route and always persists. An internal caller reaching for it
    instead of `_generate` is how a fourth replay path would quietly regain the ability to
    overwrite a draft."""
    src = inspect.getsource(main)
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    calls = body.count("api_generate(")
    assert calls == 1, f"api_generate is called {calls - 1} time(s) internally; use _generate"


def test_the_customer_pdf_render_cannot_write_to_the_draft(monkeypatch):
    """The end-to-end version of the case that matters most: a customer opening their portal PDF
    triggers a full generate on our side. It must be read-only."""
    saved = []
    payload = {"work_type": "epoxy", "audience": "Direct",
               "values": {"project_name": "Westport", "proposal_lump_sum": 13265}}
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {"proposal_payload": payload,
                                                     "proposal_lump_sum": 18670}})
    monkeypatch.setattr(main.drafts, "save_draft", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(main.estimate_writer, "fill_estimate", lambda *a, **k: b"xlsx")
    monkeypatch.setattr(main.proposal_writer, "fill_proposal", lambda *a, **k: b"docx")
    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", lambda b: b"%PDF-1.4")
    monkeypatch.setenv("SERVICE_TOKEN", "tok")
    r = TestClient(main.app).get("/api/admin/proposal-pdf?draft_id=d1",
                                 headers={"X-Service-Token": "tok", "X-Project-Id": "d1"})
    assert r.status_code == 200, r.text
    assert saved == [], "rendering a customer's PDF wrote to the estimator's draft"
