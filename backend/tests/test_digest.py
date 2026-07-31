"""The 6 AM digest: when it runs, what it picks, how it ranks, and what it says.

The whole feature is judged on one thing — does the right proposal reach the right
estimator's inbox, once. So the load-bearing tests here are the ones that keep it
from sending twice, from sending nothing, and from sending something wrong: the
day stamp, the eligibility rules that respect a customer's pause, the score bounds,
and the guarantee that a broken Claude call still produces an email.
"""
from datetime import datetime, timezone

import pytest

import digest_worker as dw

NOW = datetime(2026, 7, 31, 13, 0, tzinfo=timezone.utc)     # 8 AM Central


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Every test gets its own state file — `last_run` is the idempotency key, so a
    leaked one would silently make half these tests vacuous."""
    monkeypatch.setattr(dw, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(dw, "_STATE_FILE", tmp_path / "digest_state.json")
    monkeypatch.setattr(dw, "_MEM_STATE", {})
    dw._HOOKS.clear()


def row(**kw):
    """A pipeline row as /api/admin/pipeline actually sends it."""
    base = {
        "proposal_id": "p1", "project_name": "Oak Grove", "customer_name": "Dave",
        "customer_email": "dave@x.com", "proposal_status": "sent",
        "deposit_status": "pending", "schedule_status": "pending",
        "contacts_status": "pending", "approved_total": 40000.0,
        "assigned_estimator": "kyle@wetreadwell.com", "unread": 0,
        "sent_at": "2026-07-20T12:00:00+00:00",
        "last_activity_at": "2026-07-20T12:00:00+00:00",
        "last_viewed_at": None, "viewed_at": None, "last_followup_at": None,
        "followup_state": {"enrolled": True, "enabled": True, "paused_until": None,
                           "closed_lost_reason": None, "closed_at": None},
    }
    base.update(kw)
    return base


# ── when it runs ────────────────────────────────────────────────────────────
def test_it_waits_for_the_hour():
    early = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)   # 5 AM Central
    assert dw.should_run({}, early) is False
    assert dw.should_run({}, NOW) is True


def test_it_will_not_send_twice_in_one_day():
    assert dw.should_run({"last_run": "2026-07-31"}, NOW) is False
    assert dw.should_run({"last_run": "2026-07-30"}, NOW) is True


def test_a_restart_after_the_hour_still_sends_the_morning_digest():
    """Down at 6:00, back at 11:00. The digest is late, not void — an estimator with
    nothing in their inbox has no reason to think the system tried."""
    late = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)    # 11 AM Central
    assert dw.should_run({}, late) is True


def test_the_day_is_central_not_utc():
    """01:00 UTC on the 1st is still 8 PM on the 31st in Kansas. Stamping the UTC day
    would let a late-evening manual run block the next actual morning."""
    late_utc = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
    assert dw.biz_now(late_utc).date().isoformat() == "2026-07-31"
    assert dw.should_run({"last_run": "2026-07-31"}, late_utc) is False


def test_the_hour_is_configurable(monkeypatch):
    monkeypatch.setenv("DIGEST_HOUR", "9")
    assert dw.should_run({}, NOW) is False          # 8 AM Central < 9
    monkeypatch.setenv("DIGEST_HOUR", "nonsense")
    assert dw.should_run({}, NOW) is True           # falls back to 6


# ── eligibility ─────────────────────────────────────────────────────────────
def test_a_live_proposal_is_eligible():
    assert dw.eligible(row(), NOW) is True


def test_a_booked_job_is_done():
    assert dw.eligible(row(schedule_status="scheduled"), NOW) is False


def test_a_lost_deal_is_never_chased():
    assert dw.eligible(row(proposal_status="closed_lost"), NOW) is False


def test_an_approved_proposal_leaves_this_list():
    """It isn't finished — the deposit still has to land — but the deposit column and
    its own reminders own that. Two systems nagging about one proposal is worse than
    one."""
    assert dw.eligible(row(proposal_status="approved"), NOW) is False


def test_a_customer_pause_is_respected():
    """The strongest rule here. The customer asked us to come back later; putting the
    proposal in front of an estimator invites exactly the call they declined."""
    paused = row(followup_state={"paused_until": "2026-09-01"})
    assert dw.eligible(paused, NOW) is False


def test_a_pause_that_has_lapsed_no_longer_hides_it():
    assert dw.eligible(row(followup_state={"paused_until": "2026-07-01"}), NOW) is True


def test_a_pause_ending_today_still_counts_as_paused():
    """Compared as dates in Central. A pause "until the 31st" includes the 31st, and
    reading it as a timestamp in another timezone is how it expires a day early."""
    assert dw.eligible(row(followup_state={"paused_until": "2026-07-31"}), NOW) is False


def test_a_proposal_someone_just_chased_is_left_alone():
    """Whoever called yesterday is on it. Recommending it this morning reads as the
    system not noticing their work — which is how a digest loses its credibility."""
    assert dw.eligible(row(last_followup_at="2026-07-31T02:00:00+00:00"), NOW) is False
    assert dw.eligible(row(last_followup_at="2026-07-27T02:00:00+00:00"), NOW) is True


# ── scoring ─────────────────────────────────────────────────────────────────
def test_the_score_stays_in_range_however_bad_it_gets():
    pts, _ = dw.score(row(approved_total=5_000_000.0, unread=99,
                          sent_at="2020-01-01T00:00:00+00:00",
                          last_activity_at="2020-01-01T00:00:00+00:00"), NOW)
    assert 0 <= pts <= 100


def test_an_unanswered_message_outranks_a_bigger_quieter_deal():
    """A customer waiting on a reply is the one thing in this list with a deadline
    attached to somebody's patience."""
    talking, _ = dw.score(row(unread=2, approved_total=20000.0), NOW)
    silent, _ = dw.score(row(unread=0, approved_total=200000.0), NOW)
    assert talking > silent


def test_value_alone_cannot_dominate():
    """A 900k proposal sent yesterday must not outrank a 40k one nobody has touched
    in three weeks — otherwise the list is a leaderboard, not a work queue."""
    big_fresh, _ = dw.score(row(approved_total=900000.0,
                                sent_at="2026-07-30T12:00:00+00:00",
                                last_activity_at="2026-07-30T12:00:00+00:00",
                                last_followup_at="2026-07-30T12:00:00+00:00"), NOW)
    small_stale, _ = dw.score(row(approved_total=40000.0,
                                  sent_at="2026-07-08T12:00:00+00:00",
                                  last_activity_at="2026-07-08T12:00:00+00:00"), NOW)
    assert small_stale > big_fresh


def test_never_followed_up_scores_worse_than_followed_up_recently():
    """No data must read as "nobody has done anything", not as "nothing to report"."""
    never, facts = dw.score(row(last_followup_at=None), NOW)
    recent, _ = dw.score(row(last_followup_at="2026-07-29T12:00:00+00:00"), NOW)
    assert never > recent
    assert any("nobody has followed up" in f for f in facts)


def test_the_facts_read_as_english():
    _, facts = dw.score(row(approved_total=42000.0, unread=1,
                            sent_at="2026-07-30T13:00:00+00:00"), NOW)
    assert "worth $42,000" in facts
    assert "sent 1 day ago" in facts
    assert "1 unanswered message" in facts


def test_a_future_timestamp_does_not_read_as_negative_age():
    """Clock skew between the portal and here would otherwise score a proposal as
    sent tomorrow."""
    assert dw.days_since("2026-08-05T00:00:00+00:00", NOW) == 0.0


def test_a_naive_timestamp_is_read_as_utc():
    """A hand-built payload (a test, a manual trigger) may omit the offset. Guessing
    local time there shifts every age by hours."""
    assert dw.days_since("2026-07-30T13:00:00", NOW) == pytest.approx(1.0, abs=0.01)


def test_garbage_and_missing_timestamps_are_simply_absent():
    assert dw.days_since("not a date", NOW) is None
    assert dw.days_since(None, NOW) is None


# ── selection ───────────────────────────────────────────────────────────────
def test_it_groups_by_estimator():
    got = dw.pick([row(proposal_id="a", assigned_estimator="kyle@wetreadwell.com"),
                   row(proposal_id="b", assigned_estimator="troy@wetreadwell.com")], NOW)
    assert sorted(got) == ["kyle@wetreadwell.com", "troy@wetreadwell.com"]


def test_an_unassigned_proposal_is_skipped_not_broadcast():
    """A digest addressed to the whole roster is a digest nobody owns. These stay
    visible on the board, which is where an unowned proposal should be noticed."""
    got = dw.pick([row(assigned_estimator=None), row(assigned_estimator="  ")], NOW)
    assert got == {}


def test_the_assignee_is_matched_case_insensitively():
    got = dw.pick([row(proposal_id="a", assigned_estimator="Kyle@WeTreadwell.com"),
                   row(proposal_id="b", assigned_estimator="kyle@wetreadwell.com")], NOW)
    assert list(got) == ["kyle@wetreadwell.com"] and len(got["kyle@wetreadwell.com"]) == 2


def test_low_scoring_proposals_do_not_make_the_list(monkeypatch):
    monkeypatch.setenv("DIGEST_MIN_SCORE", "95")
    assert dw.pick([row()], NOW) == {}


def test_it_caps_at_five_and_says_how_many_it_dropped():
    """Silently truncating would read as "these are all of them" — which is how a
    proposal falls out of view entirely."""
    rows = [row(proposal_id=f"p{i}", approved_total=1000.0 * (i + 1)) for i in range(8)]
    got = dw.pick(rows, NOW)["kyle@wetreadwell.com"]
    assert len(got) == 5
    assert got[-1]["and_more"] == 3


def test_the_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("DIGEST_MAX_ITEMS", "2")
    rows = [row(proposal_id=f"p{i}") for i in range(4)]
    assert len(dw.pick(rows, NOW)["kyle@wetreadwell.com"]) == 2


def test_the_worst_offender_is_first():
    rows = [row(proposal_id="quiet", unread=0),
            row(proposal_id="waiting", unread=3)]
    got = dw.pick(rows, NOW)["kyle@wetreadwell.com"]
    assert got[0]["proposal_id"] == "waiting"


def test_a_tie_breaks_on_the_name_so_the_order_is_stable():
    """Two identical proposals must not swap places between mornings — a list that
    reshuffles for no reason is one people stop trusting."""
    rows = [row(proposal_id="b", project_name="Zebra"),
            row(proposal_id="a", project_name="Acme")]
    got = dw.pick(rows, NOW)["kyle@wetreadwell.com"]
    assert [x["project_name"] for x in got] == ["Acme", "Zebra"]


# ── streaks ─────────────────────────────────────────────────────────────────
def test_a_repeat_recommendation_counts_up():
    state = {"streaks": {"p1": 2}}
    got = dw.pick([row()], NOW, state)["kyle@wetreadwell.com"][0]
    assert got["streak"] == 3


def test_a_first_appearance_starts_at_one():
    assert dw.pick([row()], NOW, {})["kyle@wetreadwell.com"][0]["streak"] == 1


def test_only_what_was_recommended_today_carries_a_streak():
    """A proposal that dropped off has been dealt with — or paused, or lost. Carrying
    its old count forward would misstate how long it had been waiting if it ever came
    back."""
    by = dw.pick([row(proposal_id="still")], NOW, {"streaks": {"still": 1, "gone": 6}})
    assert dw.next_streaks(by) == {"still": 2}


# ── the sentence ────────────────────────────────────────────────────────────
def test_every_item_gets_a_sentence_when_claude_answers():
    dw._HOOKS["run_claude"] = lambda prompt, system: {"reasons": {"p1": "Call Dave today."}}
    items = dw.with_reasons([{"proposal_id": "p1", "project_name": "Oak", "customer": "Dave",
                              "stage": "Sent", "facts": ["sent 11 days ago"], "unread": 0}])
    assert items[0]["reason"] == "Call Dave today."


def test_a_broken_claude_call_still_produces_a_sentence():
    """The guarantee this whole module is built around: a missing email is a proposal
    nobody chases, so a templated sentence beats no send."""
    def boom(prompt, system):
        raise RuntimeError("CLI auth expired")

    dw._HOOKS["run_claude"] = boom
    items = dw.with_reasons([{"proposal_id": "p1", "project_name": "Oak", "customer": "Dave",
                              "stage": "Sent", "facts": ["sent 11 days ago",
                                                         "nobody has followed up yet"], "unread": 0}])
    assert "sent 11 days ago" in items[0]["reason"]
    assert items[0]["reason"].endswith(".")


@pytest.mark.parametrize("payload", [
    {"reasons": "a string"},
    {"reasons": ["a", "list"]},
    {"nothing": "useful"},
    "not even a dict",
    None,
])
def test_garbage_json_falls_back_instead_of_rendering_it(payload):
    dw._HOOKS["run_claude"] = lambda prompt, system: payload
    got = dw.claude_reasons([{"proposal_id": "p1", "project_name": "Oak",
                              "customer": "", "stage": "Sent", "facts": []}])
    assert got == {}


def test_a_sentence_for_a_proposal_we_did_not_ask_about_is_dropped():
    """A hallucinated id would otherwise ride into an email as a sentence about
    nothing."""
    dw._HOOKS["run_claude"] = lambda prompt, system: {
        "reasons": {"p1": "Real one.", "invented": "Sentence about nothing."}}
    got = dw.claude_reasons([{"proposal_id": "p1", "project_name": "Oak",
                              "customer": "", "stage": "Sent", "facts": []}])
    assert got == {"p1": "Real one."}


def test_an_empty_or_non_string_sentence_is_dropped():
    dw._HOOKS["run_claude"] = lambda prompt, system: {"reasons": {"p1": "   ", "p2": 42}}
    got = dw.claude_reasons([{"proposal_id": "p1", "project_name": "O", "customer": "",
                              "stage": "S", "facts": []},
                             {"proposal_id": "p2", "project_name": "T", "customer": "",
                              "stage": "S", "facts": []}])
    assert got == {}


def test_the_prompt_carries_only_the_facts_we_computed():
    """No estimate, no messages, no price breakdown. The sentence is a summary of
    known facts, and more room to reason is more room to invent."""
    seen = {}
    dw._HOOKS["run_claude"] = lambda prompt, system: seen.update(prompt=prompt, system=system) or {}
    dw.claude_reasons([{"proposal_id": "p1", "project_name": "Oak Grove",
                        "customer": "Dave", "stage": "Sent, not opened",
                        "facts": ["worth $40,000"], "score": 71}])
    assert "Oak Grove" in seen["prompt"] and "worth $40,000" in seen["prompt"]
    assert "71" not in seen["prompt"]          # the number is ours, not the model's
    assert "STRICT JSON" in seen["system"]


def test_no_claude_hook_at_all_is_not_an_error():
    assert dw.claude_reasons([{"proposal_id": "p1"}]) == {}


def test_a_waiting_customer_leads_the_fallback_sentence():
    got = dw.fallback_reason({"unread": 2, "facts": ["2 unanswered messages",
                                                     "worth $40,000"]})
    assert got.startswith("They're waiting on a reply")
    assert "unanswered" not in got             # already said by the lead


# ── the run ─────────────────────────────────────────────────────────────────
def _portal_stub(calls, rows):
    def portal(path, method="GET", body=None):
        calls.append((path, method, body))
        if path == "/api/admin/pipeline":
            return {"ok": True, "proposals": rows}
        return {"ok": True}
    return portal


def test_a_run_sends_one_email_per_estimator_and_stamps_the_day():
    calls = []
    dw._HOOKS["portal"] = _portal_stub(calls, [
        row(proposal_id="a", assigned_estimator="kyle@wetreadwell.com"),
        row(proposal_id="b", assigned_estimator="troy@wetreadwell.com")])
    dw._HOOKS["run_claude"] = lambda p, s: {}
    out = dw.run_once(NOW)
    sends = [c for c in calls if c[0] == "/api/admin/send-digest"]
    assert len(sends) == 2
    assert out["date"] == "2026-07-31"
    assert dw.load_state()["last_run"] == "2026-07-31"
    assert dw.should_run(dw.load_state(), NOW) is False       # won't repeat today


def test_the_day_is_stamped_before_the_sends():
    """A crash halfway through must not mean a second full round of emails on the next
    tick. Some estimators missing today's digest is recoverable; two copies is what
    gets the feature switched off."""
    def portal(path, method="GET", body=None):
        if path == "/api/admin/pipeline":
            return {"proposals": [row()]}
        raise RuntimeError("resend down")

    dw._HOOKS["portal"] = portal
    dw._HOOKS["run_claude"] = lambda p, s: {}
    out = dw.run_once(NOW)
    assert out["failed"] == ["kyle@wetreadwell.com"]
    assert dw.load_state()["last_run"] == "2026-07-31"


def test_one_bad_address_does_not_stop_the_others():
    sent = []

    def portal(path, method="GET", body=None):
        if path == "/api/admin/pipeline":
            return {"proposals": [row(proposal_id="a", assigned_estimator="bad@x.com"),
                                  row(proposal_id="b", assigned_estimator="kyle@wetreadwell.com")]}
        if (body or {}).get("estimator_email") == "bad@x.com":
            raise RuntimeError("rejected")
        sent.append(body["estimator_email"])
        return {"ok": True}

    dw._HOOKS["portal"] = portal
    dw._HOOKS["run_claude"] = lambda p, s: {}
    out = dw.run_once(NOW)
    assert sent == ["kyle@wetreadwell.com"] and out["failed"] == ["bad@x.com"]


def test_a_quiet_morning_sends_nothing_at_all():
    """No eligible proposals → no email. A daily message that often says "nothing to
    do" is one people filter away, and then the one that matters goes unread too."""
    calls = []
    dw._HOOKS["portal"] = _portal_stub(calls, [row(schedule_status="scheduled")])
    dw._HOOKS["run_claude"] = lambda p, s: {}
    out = dw.run_once(NOW)
    assert out["sent"] == []
    assert not [c for c in calls if c[0] == "/api/admin/send-digest"]


def test_one_claude_call_covers_the_whole_morning():
    """Per-item calls would be 20-30s each — a ten-item morning would be five minutes
    of a thread and ten times the spend."""
    runs = []
    dw._HOOKS["portal"] = _portal_stub([], [
        row(proposal_id=f"p{i}", assigned_estimator=f"e{i}@wetreadwell.com") for i in range(4)])
    dw._HOOKS["run_claude"] = lambda p, s: runs.append(p) or {}
    dw.run_once(NOW)
    assert len(runs) == 1


def test_the_items_posted_are_what_the_email_needs():
    calls = []
    dw._HOOKS["portal"] = _portal_stub(calls, [row()])
    dw._HOOKS["run_claude"] = lambda p, s: {"reasons": {"p1": "Give Dave a call."}}
    dw.run_once(NOW)
    body = [c for c in calls if c[0] == "/api/admin/send-digest"][0][2]
    assert body["estimator_email"] == "kyle@wetreadwell.com"
    item = body["items"][0]
    assert item["project_name"] == "Oak Grove"
    assert item["reason"] == "Give Dave a call."
    assert item["stage"] and isinstance(item["score"], int)


def test_the_kill_switch_stops_the_tick(monkeypatch):
    monkeypatch.setenv("DIGEST_ENABLED", "off")
    dw._HOOKS["portal"] = lambda *a, **k: pytest.fail("must not touch the portal when off")
    dw._tick()


def test_the_worker_never_starts_under_pytest():
    """A background thread reaching for the portal turns a 1.5s suite into minutes of
    connection timeouts. Learned the hard way on the follow-up worker."""
    assert dw.ensure_started(portal=lambda *a, **k: {}, run_claude=lambda *a, **k: {}) is False


# ── the admin endpoints ─────────────────────────────────────────────────────
def _client():
    import main
    from fastapi.testclient import TestClient
    return main, TestClient(main.app)


def test_only_an_admin_can_trigger_a_send(monkeypatch):
    """It emails the whole estimating team. Any signed-in user being able to fire it
    is a way to spam colleagues."""
    main, client = _client()
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "estimator"})
    assert client.post("/api/admin/digest/run").status_code == 403
    assert client.get("/api/admin/digest/preview").status_code == 403


def test_the_manual_trigger_sends_now(monkeypatch):
    main, client = _client()
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setattr(main, "_portal", _portal_stub([], [row()]))
    monkeypatch.setattr(main, "_autofill_via_cli", lambda p, s=None: {})
    r = client.post("/api/admin/digest/run")
    assert r.status_code == 200 and r.json()["sent"] == ["kyle@wetreadwell.com"]


def test_the_preview_shows_the_scores_without_emailing_or_stamping_the_day(monkeypatch):
    """Where "why is this one first?" gets answered — before anyone is phoned about
    it. It must not consume the day, or reading the preview would cancel the 6 AM
    send."""
    main, client = _client()
    calls = []
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setattr(main, "_portal", _portal_stub(calls, [row()]))
    monkeypatch.setattr(main, "_autofill_via_cli", lambda p, s=None: {})
    r = client.get("/api/admin/digest/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["would_send"] == ["kyle@wetreadwell.com"]
    assert body["estimators"]["kyle@wetreadwell.com"][0]["facts"]
    assert not [c for c in calls if c[0] == "/api/admin/send-digest"]
    assert "last_run" not in dw.load_state()


def test_an_unreachable_portal_reports_instead_of_500ing(monkeypatch):
    main, client = _client()
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})

    def boom(*a, **k):
        raise RuntimeError("portal down")

    monkeypatch.setattr(main, "_portal", boom)
    monkeypatch.setattr(main, "_autofill_via_cli", lambda p, s=None: {})
    assert client.post("/api/admin/digest/run").status_code == 502
