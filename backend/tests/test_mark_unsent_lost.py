"""Closing a bid lost when it was never sent.

Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent category."

Kyle's case, and the commonest dead bid there is: priced, paperwork generated, and then the GC went
with somebody else before we ever sent it. The only existing way to close a bid lost is the portal's
`/status` route, and an unsent project has no `portal_proposals` row to close — the third time this
drawer has hit that wall, after the estimator picker and the notify picks. So the draft records it
and the board reads it back through the synthesised row.

Two things worth pinning beyond "it saves":

  - it is NOT archiving, which already existed and hides a project. A lost bid stays visible, on the
    Lost tab, under a reason, so it counts in the numbers Troy reads.
  - the synthesised row has to speak the portal's OWN closed-lost vocabulary, because isLost() reads
    proposal_status and lostReason() reads followup_state.closed_lost_reason. Inventing a field here
    would leave the card, the Lost tab's reason column, the chip and the counts each needing a
    special case.
"""
import importlib

from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)
drafts = importlib.import_module("drafts")


def _seed(fake_supabase, data=None):
    store = {"drafts": [
        {"id": "a", "data": data if data is not None else {"project_name": "Nearman Creek"},
         "owner_email": "u@x.com", "created_at": "2026-01-01", "updated_at": "2026-01-02",
         "deleted_at": None},
    ], "events": []}
    return fake_supabase(store), store


# ── A. the store ─────────────────────────────────────────────────────────────
def test_it_records_the_reason_and_who_closed_it(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_close_lost("a", "another_contractor", "hanz@wetreadwell.com") is True
    cl = store["drafts"][0]["data"]["closed_lost"]
    assert cl["reason"] == "another_contractor"
    assert cl["by"] == "hanz@wetreadwell.com"
    assert cl["at"], "no timestamp, so the Lost tab cannot date the bid"


def test_closing_it_logs_an_event_the_history_can_show(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", "price", "hanz@wetreadwell.com")
    ev = [e for e in store["events"] if e["action"] == "closed_lost"]
    assert len(ev) == 1
    assert ev[0]["detail"]["reason"] == "price"
    assert ev[0]["detail"]["project_name"] == "Nearman Creek"


def test_reopening_removes_it_and_logs_that_too(fake_supabase, monkeypatch):
    """A mis-click must not be permanent. Removing the key rather than storing
    `{"reason": null}` matters: every reader tests for the key's presence."""
    fake, store = _seed(fake_supabase, {"project_name": "Nearman Creek",
                                        "closed_lost": {"reason": "timing", "at": "2026-08-01"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_close_lost("a", None, "hanz@wetreadwell.com") is True
    assert "closed_lost" not in store["drafts"][0]["data"]
    assert [e for e in store["events"] if e["action"] == "reactivated"]


def test_closing_a_bid_does_not_reorder_the_projects_list(fake_supabase, monkeypatch):
    """Same rule as assigning and picking recipients: closing a bid is not work on the estimate,
    and shuffling it to the top of a list sorted by date updated on its way OUT would be
    backwards."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", "canceled")
    assert store["drafts"][0]["updated_at"] == "2026-01-02"


def test_it_keeps_the_rest_of_the_blob(fake_supabase, monkeypatch):
    """Read-modify-write. The estimate has to survive, or reopening the bid loses the numbers."""
    fake, store = _seed(fake_supabase)
    store["drafts"][0]["data"]["proposal_lump_sum"] = 41500
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", "other")
    assert store["drafts"][0]["data"]["proposal_lump_sum"] == 41500


def test_closing_is_not_archiving(fake_supabase, monkeypatch):
    """Archiving already existed and means something else — it HIDES a project. If closing set that
    flag too, the bid would vanish from the board instead of moving to the Lost tab, and the count
    Troy reads would be short by every bid somebody closed properly."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", "price")
    assert store["drafts"][0]["data"].get("archived") in (None, False)


def test_an_unknown_project_says_so(fake_supabase, monkeypatch):
    fake, _ = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_close_lost("nope", "price") is False


# ── B. the summary carries it out ────────────────────────────────────────────
def test_the_summary_exposes_the_reason_and_the_date():
    """_summary is the full-blob read. The board's row is built from these two keys, so a summary
    that drops them leaves the card looking live no matter what the blob says."""
    s = drafts._summary({"id": "a", "data": {
        "project_name": "Nearman Creek", "generate_result": {"work_type": "epoxy"},
        "closed_lost": {"reason": "scope_changed", "at": "2026-08-19T15:00:00+00:00"}}})
    assert s["closed_lost_reason"] == "scope_changed"
    assert s["closed_lost_at"] == "2026-08-19T15:00:00+00:00"


def test_a_live_project_reports_none_not_a_blank():
    """`""` and None both read as falsey to the board, but None is what "nobody closed this" means,
    and `or None` is what stops an empty object from producing a truthy dict."""
    s = drafts._summary({"id": "a", "data": {"project_name": "Live"}})
    assert s["closed_lost_reason"] is None and s["closed_lost_at"] is None
    s2 = drafts._summary({"id": "a", "data": {"project_name": "Live", "closed_lost": {}}})
    assert s2["closed_lost_reason"] is None


# ── C. the board row speaks the portal's vocabulary ──────────────────────────
def _row(**kw):
    s = {"id": "d1", "project_name": "Nearman Creek", "has_files": True,
         "updated_at": "2026-08-10", "total": 41250}
    s.update(kw)
    return main._not_sent_rows([s], [])[0]


def test_a_closed_bid_becomes_the_same_closed_lost_state_a_portal_row_has():
    """isLost() reads proposal_status and lostReason() reads followup_state.closed_lost_reason.
    Matching them is what makes the Lost tab, the chip, the reason column and the counts work with
    nothing added downstream."""
    r = _row(closed_lost_reason="another_contractor", closed_lost_at="2026-08-19T15:00:00+00:00")
    assert r["proposal_status"] == "closed_lost"
    assert r["followup_state"]["closed_lost_reason"] == "another_contractor"


def test_it_carries_the_date_it_was_closed():
    """stageTs() looks for closed_at first and falls back to last activity. Without it the Lost tab
    dates the bid by whenever somebody last opened the estimate, which is not when we lost it."""
    r = _row(closed_lost_reason="price", closed_lost_at="2026-08-19T15:00:00+00:00")
    assert r["followup_state"]["closed_at"] == "2026-08-19T15:00:00+00:00"


def test_a_live_project_gets_no_closed_lost_keys_at_all():
    """Not `proposal_status: ""`. stage() reads several portal states off these rows and the whole
    point of `not_sent` is that a synthesised row carries NONE of them — a blank status is a value,
    and the next reader to use `in` would find one."""
    r = _row()
    assert "proposal_status" not in r and "followup_state" not in r


def test_a_closed_bid_is_still_on_the_board():
    """The card has to exist to be on the Lost tab. Filtering it out here — the tempting shortcut,
    since it is no longer "created but not sent" — would make closing a bid identical to hiding it,
    which is the archiving behaviour this feature exists NOT to be."""
    rows = main._not_sent_rows([{"id": "d1", "project_name": "N", "has_files": True,
                                 "updated_at": "2026-08-10", "closed_lost_reason": "price"}], [])
    assert len(rows) == 1 and rows[0]["not_sent"] is True


# ── D. the endpoint ──────────────────────────────────────────────────────────
def _api(monkeypatch, seen):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_close_lost",
                        lambda pid, reason, actor: (seen.append((pid, reason, actor)), True)[1])


def test_the_route_closes_the_bid(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "closed_lost", "reason": "price"})
    assert r.status_code == 200, r.text
    assert seen == [("d1", "price", "hanz@wetreadwell.com")]
    assert r.json()["status"] == "closed_lost"


def test_the_route_reopens_it(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "active"})
    assert r.status_code == 200, r.text
    assert seen == [("d1", None, "hanz@wetreadwell.com")], (
        "reopening must pass None — a falsey reason string would still be stored")
    assert r.json()["status"] == "active"


def test_a_reason_the_board_has_no_column_for_is_refused(monkeypatch):
    """LOST_COLS is built from LOST_REASON, so a reason outside it files the bid under "Not
    recorded" and reads as though nobody said why — worse than refusing, because it looks saved."""
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "closed_lost", "reason": "vibes"})
    assert r.status_code == 422
    assert seen == [], "it wrote a reason the board cannot display"


def test_closing_with_no_reason_at_all_is_refused(monkeypatch):
    """An empty reason would store `closed_lost` with nothing in it, and every reader treats the
    key's presence as "this is lost" — so the bid would go quiet with no explanation."""
    seen = []
    _api(monkeypatch, seen)
    assert client.post("/api/draft/d1/status", json={"status": "closed_lost"}).status_code == 422
    assert seen == []


def test_an_unknown_status_is_refused(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    assert client.post("/api/draft/d1/status",
                       json={"status": "approved"}).status_code == 422
    assert seen == []


def test_a_missing_project_is_a_404(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_close_lost", lambda *a: False)
    r = client.post("/api/draft/gone/status", json={"status": "closed_lost", "reason": "price"})
    assert r.status_code == 404


def test_a_store_failure_does_not_claim_success(monkeypatch):
    """The drawer repaints itself as closed on `ok`. A 200 over a failed write would show the rep a
    bid filed under a reason that was never saved."""
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    def boom(*a):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(main.drafts, "set_close_lost", boom)
    r = client.post("/api/draft/d1/status", json={"status": "closed_lost", "reason": "price"})
    assert r.status_code == 502


def test_the_reasons_the_route_accepts_are_the_ones_the_dialog_offers():
    """Two lists, one meaning. The dialog is built from LOST_REASON in crm-core.js and the route
    validates against LOST_REASONS in main.py; a key in one and not the other is either a dropdown
    option that 422s or a reason nothing can produce."""
    import pathlib
    import re
    core = (pathlib.Path(main.__file__).parent.parent / "frontend" / "js" / "crm-core.js") \
        .read_text(encoding="utf-8")
    block = re.search(r"var LOST_REASON = \{(.*?)\};", core, re.S)
    assert block, "LOST_REASON is gone from crm-core.js"
    keys = re.findall(r"(\w+):\s*\"", block.group(1))
    assert sorted(keys) == sorted(main.LOST_REASONS), (
        "dialog offers %s, route accepts %s" % (sorted(keys), sorted(main.LOST_REASONS)))
