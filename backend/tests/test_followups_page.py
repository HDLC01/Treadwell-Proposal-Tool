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


# ── the page itself ─────────────────────────────────────────────────────────
def test_the_page_exists_and_boots_like_the_others():
    html = (FRONTEND / "followups.html").read_text(encoding="utf-8")
    assert "@supabase/supabase-js" in html
    assert html.index("@supabase/supabase-js") < html.index("/auth.js")
    assert "/shared.js" in html
    # It renders people, so it needs the shared name/initials/colour module first.
    assert html.index("/js/crm-core.js") < html.index("/js/followups.js")
    assert "<script>" not in html.replace("<script src", "<script-src")


# The two sidebar tests that used to sit here are gone. They asserted the FOLLOW-UPS heading
# and its two items, which Hanz had removed on 2026-08-10: "Remove the followups on the
# sidebar." This page is now reachable by URL only, and that is the invariant worth holding, so
# test_sidebar_labels.py owns both halves of it: the sidebar must NOT list /followups.html, and
# followups.html plus js/followups.js must still be on disk and still wired together. Do not
# re-add a "the board is in the sidebar" assertion here without asking him first.


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


# ── the board view ────────────────────────────────────────────────────
# Structural pins for the kanban. The column LOGIC is exercised under node in
# test_followups_board_js.py; these assert the page is wired to it correctly, in the same
# read-the-source style as the rest of this file.
def test_the_board_loads_its_core_before_the_page_script():
    """followups.js reads window.TWFu as it runs, so the order is load-bearing — get it wrong
    and the page throws on boot and renders nothing at all."""
    html = (FRONTEND / "followups.html").read_text(encoding="utf-8")
    assert "/js/followups-core.js" in html
    assert html.index("/js/followups-core.js") < html.index("/js/followups.js")


def test_only_our_columns_are_drop_targets():
    """Sent / Viewed / Approved record what the CUSTOMER did. A drop there would assert a view
    or an approval that never happened, and viewed_at feeds the digest's 6 AM sentence — so the
    lie would reach an email. The renderer must only mark our columns droppable."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("function paintBoard()")
    block = js[i:i + 2000]
    assert 'data-drop="1"' in block
    assert "c.ours" in block, "the droppable flag no longer comes from the column definition"


def test_the_drop_handler_asks_the_core_not_the_dom():
    """canMove() knows an approved card cannot be closed-lost (the portal 400s it). Trusting
    only the DOM's data-drop would light up a column the server will refuse."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index('addEventListener("dragover"')
    assert "B.canMove(" in js[i:i + 700]


def test_a_drag_changes_the_cadence_not_just_the_label():
    """The whole point of the board. A move posts to the real status endpoint; a relabel would
    leave the reminders running and the board lying about them."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("async function moveTo(")
    block = js[i:i + 1800]
    # `actionPlan`, not `movePlan`: Pause and Resume stopped being columns when the board moved
    # to customer-journey categories, so the plan is keyed on an ACTION now. The behaviour it
    # guards is unchanged — a real status write, not a relabel.
    assert "/status" in block and "B.actionPlan(" in block
    assert "enable_automation" in block, (
        "the two-write resume is gone — resume_followups() does not re-enable automation, so "
        "a paused+disabled card would land in Chasing with nothing sending")


def test_the_board_has_a_keyboard_path():
    """A drag-only control would be the only thing on this page you cannot reach without a
    mouse; every row already has tabindex + Enter."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    # `data-do` (an action) rather than `data-move` (a column): with one axis of columns, Pause
    # and Resume have no column to move to, so the buttons carry actions.
    assert "data-do=" in js
    i = js.index("[data-do]")
    assert "moveTo(" in js[i:i + 200]


def test_the_poll_holds_off_during_a_drag():
    """A 45s repaint mid-drag pulls the card out from under the pointer."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("const busy = ()")
    assert "DRAGGING" in js[i:i + 260]


def test_the_board_ignores_the_tab_filter():
    """Its columns ARE those tabs. Honouring "In play" on the board would leave Paused,
    Approved and Closed lost permanently empty and make it look broken."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("function visible()")
    assert 'VIEW === "board"' in js[i:i + 600]


def test_the_view_choice_survives_a_reload():
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    assert "tw_fu_view" in js


def test_a_board_card_is_not_a_button_element():
    """`button` may only contain PHRASING content, and a card holds <p> and <div>. Rendering it
    as a <button> made the HTML parser close the button early — and with it the enclosing
    .fu-board — which dumped Paused / Approved / Closed lost outside the grid as full-width
    rows. It looked like a CSS bug and was a nesting bug.

    Found by measuring the rendered DOM on staging: the first three columns had parent
    `.fu-board`, the last three had parent `.boardwrap`. None of the source-text assertions
    above could see it, because every string in the file was correct."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("function cardHtml(")
    block = js[i:js.index("function autoBadge(")]
    assert '<div class="fu-card' in block, "the card wrapper is no longer a div"
    assert '`<button class="fu-card' not in block and '"button" : "div"' not in block, (
        "a board card is being rendered as a <button> again — it cannot legally contain the "
        "<p>/<div> it holds, and the parser will break the board grid")
    assert 'role="button"' in block, "the card lost its button semantics"


def test_the_board_card_can_be_activated_from_the_keyboard():
    """A div[role=button] does not fire on Enter/Space by itself, so the card needs an explicit
    handler — otherwise the whole board is mouse-only."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    # Anchor on the card SELECTOR, not on the first keydown listener in the file — there are
    # several (two dialogs and the table row), and picking the wrong one made this pass or fail
    # for reasons unrelated to the board.
    i = js.index('.fu-card[role="button"]')
    around = js[max(0, i - 400):i + 260]
    assert 'addEventListener("keydown"' in around, "the card selector is not in a keydown handler"
    assert '"Enter"' in around and '" "' in around, "Enter/Space are not both handled"
    assert "card.click()" in around, "the handler does not actually activate the card"


# ── sending, versus merely logging ────────────────────────────────────────────
def test_the_board_can_actually_email_the_customer():
    """The gap Hanz found: the page that tells you who needs chasing had no way to chase them.
    "Log" records a call made OUTSIDE the system and sends nothing, which is easy to mistake for
    the action itself — so sending meant leaving for the Customer Portal CRM."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    assert 'data-act="send"' in js, "no send control on the board"
    i = js.index("async function sendFollowup(")
    block = js[i:i + 1600]
    assert '"/reply"' in block, "sending must post to the reply endpoint, not merely log"


def test_sending_reuses_the_thread_the_customer_already_replies_into():
    """The same endpoint the Customer Portal CRM chat uses. A separate channel would make a
    follow-up invisible in the conversation the customer answers."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    portal = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    assert "/reply" in js and "/reply" in portal


def test_a_sent_follow_up_is_also_logged_so_the_digest_stops_nagging():
    """Without the log the estimator would send a chase and still be told tomorrow to chase."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("async function sendFollowup(")
    block = js[i:i + 1600]
    assert '"/followups"' in block and '"email"' in block


def test_a_logging_failure_does_not_read_as_a_failure_to_send():
    """The customer already has the email by then. Reporting "couldn't send" would be false and
    would invite a second one."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("async function sendFollowup(")
    block = js[i:i + 1600]
    assert "Sent, but couldn't log it" in block


def test_an_empty_follow_up_is_never_sent():
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("function sendDialog(")
    block = js[i:i + 2200]
    assert "if (!body)" in block, "an empty message could be emailed to a customer"


def test_enter_does_not_send():
    """This one leaves the building. Enter in a textarea should make a new line, and a stray
    keystroke must not email a customer a half-written sentence — unlike the log dialog, where
    Enter-to-submit is harmless."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("function sendDialog(")
    block = js[i:i + 2200]
    onkey = block[block.index("const onKey"):block.index("document.addEventListener(\"keydown\"")]
    # Strip comments first. The handler's own comment explains why Enter is absent, and matching
    # that would be a test failing on its own documentation rather than on the product — the same
    # mistake that made the earlier wording guard useless.
    code = "\n".join(l for l in onkey.split("\n") if not l.strip().startswith("//"))
    assert "Escape" in code
    assert "Enter" not in code, "Enter-to-send on a customer-facing message"


def test_sending_is_not_offered_on_a_decided_proposal():
    """Nothing to chase once it is approved or lost, and offering it invites emailing somebody
    about a decision they already made."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    i = js.index("function sendButton(")
    block = js[i:i + 600]
    assert 'colId === "approved"' in block and 'colId === "lost"' in block


def test_the_two_buttons_cannot_be_confused():
    """They sit a keystroke apart and have very different consequences, so the labels and the
    tooltips have to make the difference unmissable — and the sending one is the emphasised one."""
    js = (FRONTEND / "js" / "followups.js").read_text(encoding="utf-8")
    css = (FRONTEND / "followups.html").read_text(encoding="utf-8")
    assert "Log a call" in js, "the log button still reads as the generic action"
    assert "Does NOT email the customer" in js, "the log button does not say what it will not do"
    assert "go-send" in js and ".go-send" in css, "the sending button carries no emphasis"
