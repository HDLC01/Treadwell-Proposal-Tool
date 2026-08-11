"""The 6am digest surfaces a won job whose deposit has not arrived.

Hanz, 2026-08-12: "remember followups should be automated until a deposit has been received."

WHAT WAS WRONG, AND WHY IT READ AS DELIBERATE. `eligible()` excluded approved proposals outright,
under a comment saying "the deposit column and its own reminders own that". There were no deposit
reminders anywhere in either repo. So the one row on the board with signed work behind it and money
outstanding was the one row the morning list refused to mention, and the code explained the omission
by pointing at a system that did not exist.

WHY IT SCORES HIGH RATHER THAN MERELY BEING ALLOWED IN. A job approved yesterday has almost no age,
no silence and nothing unread — every signal this list ranks on is about a customer going quiet, and
none of them fire. Letting it through the eligibility gate and leaving it to score 32 against a
threshold of 40 would have been the same silence with more code. Dates are not held until the
deposit lands, so the reminder is worth more the FRESHER it is.

THE STAFF READING OF THE DEPOSIT, deliberately. The customer's own emails stop when they tell us the
money is on its way; an estimator's reminders do not stop until it arrives. This list is an
estimator's, so it uses `received` — the later stop. Same split as followup_rules in the portal.
"""
from datetime import datetime, timedelta, timezone

import pytest

import digest_worker as d

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def _row(**kw):
    """A won job, approved five days ago, deposit not in."""
    row = dict(
        proposal_id="p1",
        project_name="Westport Retail Center",
        assigned_estimator="kyle@wetreadwell.com",
        approved_total=48000.0,
        proposal_status="approved",
        approved_at=_ago(5),
        deposit_status="pending",
        sent_at=_ago(12),
        last_viewed_at=_ago(8),
        last_activity_at=_ago(5),
        last_followup_at=_ago(4),
    )
    row.update(kw)
    return row


def _facts(row):
    return d.score(row, NOW)[1]


# ── eligibility ──────────────────────────────────────────────────────────────
def test_a_won_job_with_the_money_out_is_on_the_list():
    assert d.eligible(_row(), NOW) is True


def test_the_money_arriving_takes_it_off():
    assert d.eligible(_row(deposit_status="received"), NOW) is False


def test_a_job_that_never_wanted_a_deposit_is_finished_at_approval():
    assert d.eligible(_row(deposit_required=False), NOW) is False


def test_the_estimator_is_still_reminded_after_the_customer_stops_being_emailed():
    """`submitted` ends the CUSTOMER's reminders and not the estimator's. A cheque that never
    arrives is exactly the case this list exists for."""
    assert d.eligible(_row(deposit_status="submitted"), NOW) is True


def test_a_declined_job_is_still_excluded():
    assert d.eligible(_row(proposal_status="closed_lost"), NOW) is False


def test_a_legacy_row_with_no_deposit_flag_still_counts():
    """Absent is not False — those jobs did take a deposit."""
    row = _row()
    row.pop("deposit_required", None)
    assert d.eligible(row, NOW) is True


def test_the_customer_asking_us_to_wait_still_wins():
    """A pause was requested BY THE CUSTOMER. That the outstanding thing is now money does not
    make it our turn to call."""
    row = _row(followup_state={"paused_until": (NOW + timedelta(days=20)).date().isoformat()})
    assert d.eligible(row, NOW) is False


def test_chasing_it_yesterday_still_buys_a_quiet_day():
    """QUIET_DAYS is about not talking over a colleague who is already on it."""
    assert d.eligible(_row(last_followup_at=_ago(0)), NOW) is False


# ── the score, and the fact behind it ────────────────────────────────────────
def test_a_job_approved_yesterday_clears_the_bar_on_its_own():
    """THE one that matters. Nothing else about a fresh approval scores: no age, no silence,
    nothing unread. Without a weight of its own it lands under the threshold on the morning it is
    most worth a call, and the eligibility change above would be cosmetic."""
    fresh = _row(approved_at=_ago(1), sent_at=_ago(3), last_viewed_at=_ago(2),
                 last_activity_at=_ago(1), last_followup_at=_ago(3), approved_total=None)
    pts, facts = d.score(fresh, NOW)
    assert pts >= d._min_score(), (
        "a job won yesterday with the deposit out scores %s, under the %s threshold — it would be "
        "eligible and still never mentioned" % (pts, d._min_score()))


def test_the_deposit_weight_only_applies_to_an_approved_job():
    """Mutation this kills: dropping the status check and scoring every unpaid proposal, which is
    all of them — every row would gain 22 points and the threshold would stop meaning anything."""
    plain = _row(proposal_status="viewed", approved_at=None, deposit_status="pending")
    assert not any("deposit" in f for f in _facts(plain)), (
        "a proposal nobody has approved is being scored for an outstanding deposit")


def test_the_fact_says_how_long_the_money_has_been_out():
    facts = _facts(_row())
    assert any("approved 5 days ago" in f for f in facts), facts
    assert any("deposit not in yet" in f for f in facts), facts


def test_the_fact_distinguishes_told_us_from_silent():
    """"Deposit recorded but not arrived" is a different phone call from "deposit not in yet" —
    one confirms a cheque, the other asks for one."""
    facts = _facts(_row(deposit_status="submitted"))
    assert any("recorded but not arrived" in f for f in facts), facts


def test_a_missing_approval_stamp_does_not_produce_a_nonsense_sentence():
    """`approved_at` predates some rows. "approved 0 days ago" on a job that has been waiting
    weeks is worse than not saying when."""
    facts = _facts(_row(approved_at=None))
    assert any("deposit not in yet" in f for f in facts), facts
    assert not any("0 day" in f for f in facts), facts


# ── what the estimator reads ─────────────────────────────────────────────────
def test_the_stage_label_does_not_call_a_won_job_undecided():
    """An approved proposal has been viewed, so the old label chain called it "Viewed" — which
    reads as nobody having decided on work that is signed."""
    assert d._stage_label(_row()) == "Approved — deposit outstanding"


def test_a_recorded_deposit_keeps_the_more_specific_label():
    assert d._stage_label(_row(deposit_status="submitted")) == "Deposit submitted"


def test_a_paid_job_is_not_labelled_outstanding():
    assert d._stage_label(_row(deposit_status="received")) == "Approved"


@pytest.mark.parametrize("status", ["pending", "submitted"])
def test_the_no_claude_sentence_asks_for_the_deposit_not_a_decision(status):
    """The fallback runs whenever the model is unavailable, which is precisely when nobody is
    checking the wording. "Worth a nudge" on a won job sends the estimator to ask for a decision
    the customer already made."""
    row = _row(deposit_status=status)
    item = {"stage": d._stage_label(row), "facts": _facts(row), "unread": 0}
    assert d.fallback_reason(item).startswith("Won, waiting on the deposit"), (
        "the digest asks a customer who has signed to decide again")


def test_an_unanswered_message_still_outranks_the_deposit_sentence():
    """A customer waiting on a reply is the one thing more urgent than money in transit."""
    row = _row(unread=2)
    item = {"stage": d._stage_label(row), "facts": _facts(row), "unread": 2}
    assert d.fallback_reason(item).startswith("They're waiting on a reply")


def test_an_ordinary_proposal_still_reads_as_a_nudge():
    """Guard against the deposit lead swallowing the general case."""
    row = _row(proposal_status="viewed", approved_at=None)
    item = {"stage": d._stage_label(row), "facts": _facts(row), "unread": 0}
    assert item["stage"] == "Viewed, not approved"
    assert d.fallback_reason(item).startswith("Worth a nudge")


# ── end to end through pick() ────────────────────────────────────────────────
def test_it_reaches_the_estimators_email():
    """Every gate in one pass: eligible, over the bar, assigned, and carrying the right label."""
    by = d.pick([_row()], NOW, {})
    assert "kyle@wetreadwell.com" in by, "the won job never reaches an estimator's digest"
    item = by["kyle@wetreadwell.com"][0]
    assert item["stage"] == "Approved — deposit outstanding"
    assert any("deposit" in f for f in item["facts"])


def test_a_paid_job_reaches_nobody():
    assert d.pick([_row(deposit_status="received")], NOW, {}) == {}


def test_the_stale_comment_about_deposit_reminders_owning_it_is_gone():
    """It described a system that did not exist and justified the silence this change fixes.
    Left in place, the next person reads it and puts the exclusion back."""
    import inspect
    src = inspect.getsource(d.eligible)
    assert "its own reminders own that" not in src, (
        "the comment still points at deposit reminders as the reason to skip approved jobs")
