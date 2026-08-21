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


def test_the_comment_is_stored_and_readable_afterwards(fake_supabase, monkeypatch):
    """The whole point of requiring it. A comment validated on the way in and then dropped would be
    a required field that costs the estimator a sentence and gives the next reader nothing.

    On the SAME blob key as the reason, not a column: an unsent project has no portal row (which is
    why this family of writers exists at all), and the sent half stores its own copy in jsonb too
    (portal_followups.detail). Neither half needed DDL."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", "not_low_bid", "hanz@wetreadwell.com",
                          note="12% over Wilson on the pour.")
    cl = store["drafts"][0]["data"]["closed_lost"]
    assert cl["note"] == "12% over Wilson on the pour."
    ev = [e for e in store["events"] if e["action"] == "closed_lost"]
    assert ev[0]["detail"]["note"] == "12% over Wilson on the pour.", (
        "the History feed cannot show why, so the sentence is only readable by opening the blob")


def test_reopening_logs_no_comment_because_there_is_none(fake_supabase, monkeypatch):
    """`None` rather than `""`. The reopen path takes no comment, and a blank string on the event
    would make "was a reason given" a truthiness test on a key that is always there."""
    fake, store = _seed(fake_supabase, {"project_name": "Nearman Creek",
                                        "closed_lost": {"reason": "timing", "note": "x"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", None, "hanz@wetreadwell.com")
    ev = [e for e in store["events"] if e["action"] == "reactivated"]
    assert ev[0]["detail"]["note"] is None


# ── A2. the hold, which is not a close at all ────────────────────────────────
def test_a_hold_is_its_own_key_and_leaves_the_lost_one_alone(fake_supabase, monkeypatch):
    """Hanz, 2026-08-20. Separate keys because they are different facts with different lifetimes,
    and one key holding a tri-state would turn "is this bid dead" into a string comparison in five
    readers instead of a presence test in one."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_on_hold("a", "on_hold", "GC has gone quiet.", "hanz@wetreadwell.com",
                              until="2026-12-20") is True
    data = store["drafts"][0]["data"]
    assert data["on_hold"] == {"reason": "on_hold", "note": "GC has gone quiet.",
                               "by": "hanz@wetreadwell.com", "at": data["on_hold"]["at"],
                               "until": "2026-12-20"}
    assert "closed_lost" not in data, "holding a bid also closed it"
    ev = [e for e in store["events"] if e["action"] == "on_hold"]
    assert len(ev) == 1 and ev[0]["detail"]["note"] == "GC has gone quiet."


def test_holding_a_bid_does_not_reorder_the_projects_list(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_on_hold("a", "small_bid_pending", "Waiting on the owner.")
    assert store["drafts"][0]["updated_at"] == "2026-01-02"


def test_reopening_clears_the_hold_as_well(fake_supabase, monkeypatch):
    """"Active" is one word meaning one thing to the estimator pressing it. A hold that survived
    reactivation would leave the card reading "Paused to ..." with no control left to clear it,
    because the drawer offers exactly one way back."""
    fake, store = _seed(fake_supabase, {"project_name": "N",
                                        "on_hold": {"reason": "on_hold", "until": "2026-12-20"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_close_lost("a", None, "hanz@wetreadwell.com")
    assert "on_hold" not in store["drafts"][0]["data"]


# ── A3. bringing it back, which clears every mark at once ────────────────────
def test_bringing_it_back_clears_all_three_marks_in_one_write(fake_supabase, monkeypatch):
    """A job marked won and THEN closed lost reads as Lost only (every reader asks isLost first),
    so clearing one mark leaves the card on the other tab and the button the estimator just pressed
    looks broken. One act, one write, one event."""
    fake, store = _seed(fake_supabase, {
        "project_name": "N", "proposal_lump_sum": 41500,
        "closed_lost": {"reason": "not_low_bid", "note": "over on the pour"},
        "on_hold": {"reason": "on_hold"},
        "won": {"at": "2026-08-01T00:00:00+00:00"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.clear_outcome("a", "hanz@wetreadwell.com") is True
    data = store["drafts"][0]["data"]
    for key in ("closed_lost", "on_hold", "won"):
        assert key not in data, "%s survived the bring-back" % key
    assert data["proposal_lump_sum"] == 41500, "the estimate went with the marks"
    assert len([e for e in store["events"] if e["action"] == "brought_back"]) == 1


def test_bringing_back_a_bid_nobody_closed_is_a_no_op_that_still_succeeds(fake_supabase,
                                                                          monkeypatch):
    """IDEMPOTENT, which is what makes the route's second leg safe to retry: forwarding `active` to
    the portal can fail after the blob is already clear, and the drawer tells the estimator to press
    it again."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.clear_outcome("a", "hanz@wetreadwell.com") is True
    assert drafts.clear_outcome("a", "hanz@wetreadwell.com") is True
    assert drafts.clear_outcome("nope", "hanz@wetreadwell.com") is False


# ── B. the summary carries it out ────────────────────────────────────────────
def test_the_summary_exposes_the_reason_and_the_date():
    """_summary is the full-blob read. The board's row is built from these two keys, so a summary
    that drops them leaves the card looking live no matter what the blob says."""
    s = drafts._summary({"id": "a", "data": {
        "project_name": "Nearman Creek", "generate_result": {"work_type": "epoxy"},
        "closed_lost": {"reason": "scope_changed", "at": "2026-08-19T15:00:00+00:00",
                        "note": "Owner shrank the pour."}}})
    assert s["closed_lost_reason"] == "scope_changed"
    assert s["closed_lost_at"] == "2026-08-19T15:00:00+00:00"
    # The comment too, because it has to be READABLE and the drawer reads it off this row. A
    # required field that never comes back out is a required field for nothing.
    assert s["closed_lost_note"] == "Owner shrank the pour."


def test_the_summary_exposes_the_hold_too():
    """Selected by NAME on the fast projection in _build_summaries, which is why it has to be
    listed on BOTH summary paths: that path selects named JSON paths rather than the blob, so a key
    nobody names reaches no card and the hold appears to save and then vanish."""
    s = drafts._summary({"id": "a", "data": {
        "project_name": "N", "generate_result": {"work_type": "epoxy"},
        "on_hold": {"reason": "on_hold", "until": "2026-12-20", "note": "GC quiet"}}})
    assert s["on_hold_reason"] == "on_hold" and s["on_hold_until"] == "2026-12-20"
    assert s["closed_lost_reason"] is None, "a held bid reads as lost"


def test_the_fast_projection_names_the_hold_fields():
    """The other read path, and the one that serves every real page load. A field on only one of
    them is a bug that reproduces about once a month, on the day PostgREST refuses the projection."""
    import inspect
    src = inspect.getsource(drafts._build_summaries)
    for path in ("on_hold_reason:data->on_hold->>reason",
                 "on_hold_until:data->on_hold->>until",
                 "on_hold_note:data->on_hold->>note",
                 "closed_lost_note:data->closed_lost->>note"):
        assert path in src, "%s is not selected, so the hold never reaches a card" % path


def test_every_field_the_fast_projection_selects_is_also_mapped_onto_the_row():
    """TWO LISTS, ONE FUNCTION, and the gap between them is silent. _build_summaries selects named
    JSON paths and then copies them into the dict it returns, and a field that is selected and not
    copied is fetched from Postgres and dropped on the floor — no error, no log, just a drawer that
    shows nothing. Derived from the source rather than listed here, so the next field added to that
    projection is covered the day it lands."""
    import inspect
    import re
    src = inspect.getsource(drafts._build_summaries)
    aliases = set(re.findall(r'"([a-z_]+):data->', src))
    assert aliases, "the projection has stopped selecting named JSON paths, or the regex has rotted"
    # `r.get("name")` rather than `"name": r.get(` — four of these are wrapped on the way through
    # (`bool(...)`, `_tribool(...)`, `_polish_beta(...)`), and the question is whether the value is
    # read at all, not how it is spelled when it is.
    missing = sorted(a for a in aliases if ('r.get("%s")' % a) not in src)
    assert not missing, (
        "selected from Postgres and never copied onto the row, so it reaches no screen: %s"
        % missing)


def test_a_live_project_reports_none_not_a_blank():
    """`""` and None both read as falsey to the board, but None is what "nobody closed this" means,
    and `or None` is what stops an empty object from producing a truthy dict."""
    s = drafts._summary({"id": "a", "data": {"project_name": "Live"}})
    assert s["closed_lost_reason"] is None and s["closed_lost_at"] is None
    s2 = drafts._summary({"id": "a", "data": {"project_name": "Live", "closed_lost": {}}})
    assert s2["closed_lost_reason"] is None
    assert s["closed_lost_note"] is None and s2["closed_lost_note"] is None, (
        "an absent comment reads as a value, and the drawer would draw an empty pair of quotes")


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
    r = _row(closed_lost_reason="another_contractor", closed_lost_at="2026-08-19T15:00:00+00:00",
             closed_lost_note="They signed with Wilson on Friday.")
    assert r["proposal_status"] == "closed_lost"
    assert r["followup_state"]["closed_lost_reason"] == "another_contractor"
    # The comment rides on the same key so the DRAWER can print it back. Not the card: a card is
    # 224px wide and this is a paragraph.
    assert r["followup_state"]["closed_lost_note"] == "They signed with Wilson on Friday."


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


def test_a_held_bid_stays_in_the_created_column_and_says_it_is_paused():
    """The OPPOSITE instruction to the branch above, and the whole of Hanz's 2026-08-20 decision:
    two of Kyle's eight answers pause a bid instead of killing it, and the card STAYS on the Active
    board. So no proposal_status is written — stage() still reads `not_sent` — and the only visible
    change is the "Paused to ..." chip, which chipsHtml already draws off followup_state.
    paused_until. One chip for both halves, rather than an on-hold vocabulary only unsent cards can
    speak."""
    r = _row(on_hold_reason="on_hold", on_hold_until="2026-12-20",
             on_hold_note="GC has gone quiet.")
    assert "proposal_status" not in r, "a held bid was given a portal status, so the card moved"
    assert r["followup_state"] == {"paused_until": "2026-12-20", "on_hold_reason": "on_hold",
                                  # The sentence rides along so the DRAWER can print it. The card
                                  # never draws it; see nsCloseNote in portal.js.
                                  "on_hold_note": "GC has gone quiet."}


def test_a_bid_held_and_then_lost_reads_as_lost():
    """isLost wins everywhere, which is right: it IS lost. The two branches write the SAME key, so
    an `if` where the `elif` is would let the hold overwrite the closed-lost state and put a dead
    bid back on the live board with no reason column to file it under."""
    r = _row(closed_lost_reason="not_low_bid", closed_lost_at="2026-08-19T15:00:00+00:00",
             on_hold_reason="on_hold", on_hold_until="2026-12-20")
    assert r["proposal_status"] == "closed_lost"
    assert r["followup_state"]["closed_lost_reason"] == "not_low_bid"
    assert "paused_until" not in r["followup_state"], (
        "the hold overwrote the close, so a dead bid is back on the Active board")


def test_a_closed_bid_is_still_on_the_board():
    """The card has to exist to be on the Lost tab. Filtering it out here — the tempting shortcut,
    since it is no longer "created but not sent" — would make closing a bid identical to hiding it,
    which is the archiving behaviour this feature exists NOT to be."""
    rows = main._not_sent_rows([{"id": "d1", "project_name": "N", "has_files": True,
                                 "updated_at": "2026-08-10", "closed_lost_reason": "price"}], [])
    assert len(rows) == 1 and rows[0]["not_sent"] is True


# ── D. the endpoint ──────────────────────────────────────────────────────────
def _api(monkeypatch, seen):
    """The route with its store stubbed. `note` is captured alongside the reason, because it is
    required from 2026-08-20 and a route that validated it and then dropped it on the floor would
    pass every refusal test in this file."""
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_close_lost",
                        lambda pid, reason, actor, note=None:
                        (seen.append((pid, reason, actor, note)), True)[1])


#: A comment good enough to get past the required field. One sentence, which is all it asks for.
NOTE = "We were 12% over Wilson on the pour."


def test_the_route_closes_the_bid(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status",
                    json={"status": "closed_lost", "reason": "not_low_bid", "note": NOTE})
    assert r.status_code == 200, r.text
    assert seen == [("d1", "not_low_bid", "hanz@wetreadwell.com", NOTE)]
    assert r.json()["status"] == "closed_lost"


def test_the_route_reopens_it(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "active"})
    assert r.status_code == 200, r.text
    assert seen == [("d1", None, "hanz@wetreadwell.com", None)], (
        "reopening must pass None — a falsey reason string would still be stored")
    assert r.json()["status"] == "active"


# ── THE REQUIRED COMMENT, at the server ─────────────────────────────────────
# Hanz, 2026-08-20. The dialog disables its own button until the box has something in it, but a
# stale tab, a browser that fires click on a disabled control, or a hand-rolled request all reach
# the route with nothing, and the reason on its own tells the next person nothing: "Not Low Bid" is
# eight identical cards by the end of a quarter.
def test_closing_with_no_comment_is_refused(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status",
                    json={"status": "closed_lost", "reason": "not_low_bid"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == main.NOTE_REQUIRED
    assert seen == [], "the bid was closed with no comment on it"


def test_whitespace_is_not_a_comment(monkeypatch):
    """A required field that accepts a space is decoration. Spaces, tabs and newlines, because the
    box is a textarea and Enter is the easiest thing in the world to press in one."""
    seen = []
    _api(monkeypatch, seen)
    for blank in ("   ", "\t", "\n\n", " \r\n \t "):
        r = client.post("/api/draft/d1/status",
                        json={"status": "closed_lost", "reason": "no_response", "note": blank})
        assert r.status_code == 422, "%r got through" % blank
    assert seen == []


def test_a_long_comment_is_capped_rather_than_refused(monkeypatch):
    """The dialog's textarea has maxlength=2000 on it, so anything longer arrived some other way.
    Truncating keeps the close; refusing would lose both the close and the sentence."""
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status",
                    json={"status": "closed_lost", "reason": "to_rebid", "note": "x" * 5000})
    assert r.status_code == 200, r.text
    assert len(seen[0][3]) == main._NOTE_MAX


def test_reopening_needs_no_comment(monkeypatch):
    """The requirement is on the way OUT of the pipeline, and only there. Nobody has to justify
    putting a live bid back to work, and a prompt that asked would be one more thing between a
    mis-click and its fix."""
    seen = []
    _api(monkeypatch, seen)
    assert client.post("/api/draft/d1/status", json={"status": "active"}).status_code == 200
    assert seen == [("d1", None, "hanz@wetreadwell.com", None)]


# ── the hold answers take the other branch ──────────────────────────────────
def _hold_api(monkeypatch, seen):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_on_hold",
                        lambda pid, reason, note, actor, until="":
                        (seen.append((pid, reason, note, actor, until)), True)[1])


def test_a_hold_is_stored_with_a_date_and_never_as_a_loss(monkeypatch):
    """Hanz, 2026-08-20: "Project on Hold" and "Small Bid <$25k - Pending" leave the card on the
    Active board. An unsent bid has no portal row and no cadence to pause, so the draft records the
    fact and the board reads it back as a paused card in the Created column."""
    for reason in main.HOLD_REASONS:
        seen = []
        _hold_api(monkeypatch, seen)
        r = client.post("/api/draft/d1/status",
                        json={"status": "on_hold", "reason": reason, "note": NOTE})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "on_hold" and r.json()["reason"] == reason
        assert len(seen) == 1 and seen[0][:4] == ("d1", reason, NOTE, "hanz@wetreadwell.com")
        assert seen[0][4] == r.json()["paused_until"], (
            "the date stored and the date reported to the drawer are computed twice")
        assert seen[0][4] > "2026-08-20", seen[0][4]


def test_a_hold_needs_its_comment_too(monkeypatch):
    seen = []
    _hold_api(monkeypatch, seen)
    for note in (None, "", "   "):
        body = {"status": "on_hold", "reason": "on_hold"}
        if note is not None:
            body["note"] = note
        assert client.post("/api/draft/d1/status", json=body).status_code == 422, note
    assert seen == []


def test_the_two_vocabularies_do_not_cross(monkeypatch):
    """A close-lost reason must not pause a bid somebody meant to kill, and a hold answer must not
    close one somebody meant to keep. Two accept-lists, checked in both directions, because the
    dialog sends the same field on both branches and one typo in the branch would swap them."""
    seen = []
    _api(monkeypatch, seen)
    _hold_api(monkeypatch, seen)
    for reason in main.HOLD_REASONS:
        r = client.post("/api/draft/d1/status",
                        json={"status": "closed_lost", "reason": reason, "note": NOTE})
        assert r.status_code == 422, "%s closed the bid" % reason
    for reason in main.LOST_REASONS:
        r = client.post("/api/draft/d1/status",
                        json={"status": "on_hold", "reason": reason, "note": NOTE})
        assert r.status_code == 422, "%s put the bid on hold" % reason
    assert seen == []


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
    monkeypatch.setattr(main.drafts, "set_close_lost", lambda *a, **kw: False)
    monkeypatch.setattr(main.drafts, "set_on_hold", lambda *a, **kw: False)
    for body in ({"status": "closed_lost", "reason": "not_low_bid", "note": NOTE},
                 {"status": "on_hold", "reason": "on_hold", "note": NOTE}):
        r = client.post("/api/draft/gone/status", json=body)
        assert r.status_code == 404, body


def test_a_store_failure_does_not_claim_success(monkeypatch):
    """The drawer repaints itself as closed on `ok`. A 200 over a failed write would show the rep a
    bid filed under a reason that was never saved."""
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    def boom(*a, **kw):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(main.drafts, "set_close_lost", boom)
    monkeypatch.setattr(main.drafts, "set_on_hold", boom)
    for body in ({"status": "closed_lost", "reason": "not_low_bid", "note": NOTE},
                 {"status": "on_hold", "reason": "on_hold", "note": NOTE}):
        assert client.post("/api/draft/d1/status", json=body).status_code == 502, body


def test_the_route_refuses_a_reason_the_board_cannot_column_either_way():
    """Two accept-lists, and every key in them has to be a column or a chip somewhere.

    This test used to REGEX `var LOST_REASON = {...}` out of crm-core.js and compare the keys. That
    stopped being possible on 2026-08-20: LOST_REASON is now DERIVED from CLOSE_CHOICES, so the
    source text is an expression rather than a map, and a regex over it reads nothing. The
    comparison moved to test_close_reason_vocabulary.py, which EXECUTES crm-core and checks all
    five copies of the vocabulary across both repositories in every direction.

    What is left here is the property this file is actually about: the unsent route's own two
    accept-lists are disjoint and non-empty, and neither has quietly become "anything"."""
    assert main.LOST_REASONS and main.HOLD_REASONS
    assert not (set(main.LOST_REASONS) & set(main.HOLD_REASONS)), (
        "a reason both closes a bid and holds it: %s"
        % sorted(set(main.LOST_REASONS) & set(main.HOLD_REASONS)))
    assert "on_hold" in main.HOLD_REASONS and "small_bid_pending" in main.HOLD_REASONS, (
        "Kyle's two non-closing answers are not the hold answers any more")
    assert "other" in main.LOST_REASONS, (
        "the dialog falls back to `other` when the select has no value at all, so dropping it "
        "turns a mis-click into a 422 the estimator has to decode")


# ── E. bringing it back ─────────────────────────────────────────────────────
# Hanz, 2026-08-20: "if projects are both won and lost there should be an option to bring it back to
# its latest step in the CRM but before they do that there should be a prompt saying are they sure".
# The prompt is the drawer's (test_not_sent_lost.py runs it); these are the two legs of the write.
def _bring_back_api(monkeypatch, seen, *, sent, portal_ok=True):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "clear_outcome",
                        lambda pid, actor: (seen.append(("clear", pid, actor)), True)[1])
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda pid: 2 if sent else None)

    def portal(path, method, body):
        seen.append(("portal", path, method, body))
        if not portal_ok:
            raise RuntimeError("portal down")
        return {"ok": True}

    monkeypatch.setattr(main, "_portal", portal)


def test_an_unsent_bid_is_brought_back_without_troubling_the_portal(monkeypatch):
    """There is no portal row to reopen — which is the wall this whole family of draft-side routes
    exists to get around. Posting there anyway would 404 and the estimator would be told the
    bring-back failed on a bid that is already back."""
    seen = []
    _bring_back_api(monkeypatch, seen, sent=False)
    r = client.post("/api/draft/d1/status", json={"status": "bring_back"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "status": "active", "portal_updated": False, "sent": False}
    assert seen == [("clear", "d1", "hanz@wetreadwell.com")]


def test_a_sent_bid_clears_both_stores(monkeypatch):
    """The won mark is OURS and a sent project's closed_lost is the PORTAL's, and isLost is asked
    first by every reader — so a card whose portal row is still closed stays on the Lost tab no
    matter what our blob says. Draft first, portal second, both idempotent."""
    seen = []
    _bring_back_api(monkeypatch, seen, sent=True)
    r = client.post("/api/draft/d1/status", json={"status": "bring_back"})
    assert r.status_code == 200, r.text
    assert r.json()["portal_updated"] is True and r.json()["sent"] is True
    assert seen[0][0] == "clear", "the portal was updated before our own blob"
    assert seen[1] == ("portal", "/api/admin/proposal/d1/status", "POST",
                       {"status": "active", "by": "hanz@wetreadwell.com"})


def test_a_failed_portal_leg_is_reported_rather_than_swallowed(monkeypatch):
    """Unlike /assign, which shrugs. A bid that LOOKS brought back and is still filed as lost is
    the exact confusion this feature exists to end, and both legs are idempotent, so the drawer can
    honestly tell the estimator to press it again."""
    seen = []
    _bring_back_api(monkeypatch, seen, sent=True, portal_ok=False)
    r = client.post("/api/draft/d1/status", json={"status": "bring_back"})
    assert r.status_code == 502
    assert seen[0][0] == "clear", "our own blob was never cleared, so nothing is retryable"


def test_bringing_back_a_missing_project_is_a_404(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "clear_outcome", lambda pid, actor: False)
    assert client.post("/api/draft/gone/status",
                       json={"status": "bring_back"}).status_code == 404


def test_bringing_it_back_needs_no_reason_and_no_comment(monkeypatch):
    """The requirement is on the way OUT. A stray reason riding along on the way back in must not
    turn a one-click undo into a 422."""
    seen = []
    _bring_back_api(monkeypatch, seen, sent=False)
    r = client.post("/api/draft/d1/status",
                    json={"status": "bring_back", "reason": "vibes", "note": ""})
    assert r.status_code == 200, r.text
