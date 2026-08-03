"""The Follow-ups page: every proposal ever sent, and where its chase stands.

Hanz asked for it as a sidebar tab under Proposals — "a list of the projects like in the
projects but this time the labels are for follow ups". The cadence, the pauses and the
"nobody has chased this in nine days" facts were all real but scattered across the
follow-up worker, a drawer tab you open one project at a time, and a 6 AM email.

The ranking and the "why it's here" sentence are computed SERVER-side from
`digest_worker` — the same code that writes that email. A page that recomputed them in
JavaScript would eventually disagree with the email it exists to explain, which is the
one thing worth pinning here.
"""
import pathlib

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def row(**kw):
    base = {
        "proposal_id": "p1", "project_name": "Oak Grove", "customer_name": "Dave",
        "customer_email": "dave@x.com", "proposal_status": "sent",
        "deposit_status": "pending", "schedule_status": "pending",
        "contacts_status": "pending", "approved_total": 40000.0,
        "assigned_estimator": "kyle@wetreadwell.com", "unread": 0,
        "sent_at": "2026-07-20T12:00:00+00:00",
        "last_activity_at": "2026-07-20T12:00:00+00:00",
        "last_viewed_at": None, "viewed_at": None, "last_followup_at": None,
        "next_followup_at": "2026-08-05T12:00:00+00:00",
        "followup_state": {"enrolled": True, "enabled": True, "paused_until": None,
                           "closed_lost_reason": None, "closed_at": None},
    }
    base.update(kw)
    return base


def _wire(monkeypatch, rows):
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "user"})
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": rows})


# ── the feed ────────────────────────────────────────────────────────────────
def test_it_returns_every_proposal_with_its_score_and_reason(monkeypatch):
    _wire(monkeypatch, [row()])
    body = client.get("/api/portal/followups").json()
    assert body["ok"] is True
    p = body["proposals"][0]
    assert isinstance(p["followup_score"], int) and p["followup_score"] > 0
    assert p["followup_facts"], "no facts, so the page has nothing to explain itself with"
    assert p["reason"], "no sentence for the 'why it's here' column"
    assert p["eligible"] is True


def test_it_keeps_every_field_the_page_needs(monkeypatch):
    """The feed wraps the pipeline row rather than replacing it, so the page keeps the
    estimator, the stage inputs and the timestamps it renders."""
    _wire(monkeypatch, [row()])
    p = client.get("/api/portal/followups").json()["proposals"][0]
    for k in ("proposal_id", "project_name", "customer_name", "assigned_estimator",
              "proposal_status", "followup_state", "next_followup_at",
              "last_followup_at", "last_activity_at", "approved_total"):
        assert k in p, f"the feed dropped {k}"


def test_the_worst_offender_comes_first(monkeypatch):
    """A list whose point is "who have we left longest" has to arrive sorted, so the page
    is right before a single click."""
    _wire(monkeypatch, [
        row(proposal_id="fresh", project_name="Fresh",
            sent_at="2026-08-02T12:00:00+00:00",
            last_activity_at="2026-08-02T12:00:00+00:00",
            last_followup_at="2026-08-02T12:00:00+00:00"),
        row(proposal_id="stale", project_name="Stale", unread=3),
    ])
    got = [p["proposal_id"] for p in client.get("/api/portal/followups").json()["proposals"]]
    assert got[0] == "stale"


def test_what_you_can_act_on_comes_before_what_you_cannot(monkeypatch):
    """Found by reading the real staging feed, not by reasoning about it.

    `score()` was built for the digest, which filters by `eligible()` BEFORE ranking
    matters — so it cheerfully awards age and customer-silence points to a proposal that
    was approved months ago. Sorting the page on the score alone put four approved jobs
    (100, 94, 90, 87 — none of them actionable) above the two live ones somebody could
    actually ring. A column headed "needs attention" has to lead with what needs it."""
    _wire(monkeypatch, [
        # Approved and ancient: scores high, worth nothing.
        row(proposal_id="old_won", project_name="Won Long Ago", proposal_status="approved",
            sent_at="2026-01-01T12:00:00+00:00", last_activity_at="2026-01-01T12:00:00+00:00"),
        # Live, recent, lower score, and the only one you can do something about.
        row(proposal_id="live", project_name="Live", proposal_status="viewed",
            sent_at="2026-08-01T12:00:00+00:00", last_activity_at="2026-08-01T12:00:00+00:00"),
    ])
    got = client.get("/api/portal/followups").json()["proposals"]
    assert [p["proposal_id"] for p in got] == ["live", "old_won"]
    assert got[0]["followup_score"] < got[1]["followup_score"], (
        "the fixture no longer reproduces the bug — the ineligible row must out-SCORE the "
        "eligible one, or this test proves nothing")


def test_a_proposal_nobody_should_chase_carries_no_reason(monkeypatch):
    """Approved, paused and just-chased proposals still appear — Hanz wanted every
    proposal ever sent — but presenting a nag for them would be wrong. `eligible` is the
    digest's own filter, reused so the page and the email agree on who is worth a call."""
    _wire(monkeypatch, [
        row(proposal_id="won", proposal_status="approved"),
        row(proposal_id="paused",
            followup_state={"enrolled": True, "enabled": True,
                            "paused_until": "2026-12-01", "closed_lost_reason": None,
                            "closed_at": None}),
    ])
    by = {p["proposal_id"]: p for p in client.get("/api/portal/followups").json()["proposals"]}
    assert by["won"]["eligible"] is False and by["won"]["reason"] == ""
    assert by["paused"]["eligible"] is False and by["paused"]["reason"] == ""


def test_it_needs_a_signed_in_user(monkeypatch, real_verify_token):
    """conftest authenticates every request by default, so this restores the genuine
    verifier — the feed lists every customer a proposal was ever sent to."""
    monkeypatch.setattr(main.supabase_client, "verify_token", real_verify_token)
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"proposals": []})
    assert client.get("/api/portal/followups").status_code in (401, 403)


def test_an_empty_portal_is_not_an_error(monkeypatch):
    _wire(monkeypatch, [])
    body = client.get("/api/portal/followups").json()
    assert body["ok"] is True and body["proposals"] == []


def test_it_does_not_spend_an_ai_call_per_row(monkeypatch):
    """This endpoint is hit on every page load AND a 45s poll. The written-out sentence
    belongs in the digest, where it's worth the spend; here the templated one is free,
    instant and deterministic."""
    _wire(monkeypatch, [row(), row(proposal_id="p2")])

    def boom(*a, **k):
        raise AssertionError("the page called Claude")

    monkeypatch.setattr(main, "_autofill_via_cli", boom)
    monkeypatch.setattr(main.digest_worker, "claude_reasons", boom)
    body = client.get("/api/portal/followups").json()
    assert all(p["reason"] for p in body["proposals"])


# ── the page + the sidebar ──────────────────────────────────────────────────
def test_the_page_exists_and_boots_like_the_others():
    html = (FRONTEND / "followups.html").read_text(encoding="utf-8")
    assert "@supabase/supabase-js" in html
    assert html.index("@supabase/supabase-js") < html.index("/auth.js")
    assert "/shared.js" in html
    # It renders people, so it needs the shared name/initials/colour module first.
    assert html.index("/js/crm-core.js") < html.index("/js/followups.js")
    assert "<script>" not in html.replace("<script src", "<script-src")


def test_it_is_in_the_sidebar_under_proposals():
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    # auth.js builds the nav with single-quoted strings.
    i = auth.index("tw-section\">Proposals")
    j = auth.index("tw-section\">Analytics", i)
    section = auth[i:j]
    assert "/followups.html" in section, "the nav entry is not in the Proposals section"


def test_the_page_reads_the_feed_and_nothing_else():
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    assert '"/api/portal/followups"' in js
    # The score and the sentence must come from the server, not be re-derived here.
    assert "followup_score" in js and "p.reason" in js


def test_logging_a_follow_up_reuses_the_existing_proxy():
    """Same endpoint the CRM drawer posts to, so a call logged here shows up in the
    drawer's History and suppresses the digest identically."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    assert '"/followups"' in js and "logDialog" in js


def test_the_row_click_and_the_log_button_do_not_fight():
    """The row opens the CRM drawer; the Log button must not also navigate. Without
    stopPropagation the dialog opens and the page leaves underneath it."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index('data-act="log"]')
    assert "stopPropagation" in js[i:i + 120]


def test_the_poll_holds_off_while_somebody_is_typing():
    """A 45s repaint that wipes a half-written note is worse than stale data."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    assert "busy()" in js and "document.hidden" in js
