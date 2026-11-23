"""frontend/bd/js/bd-core.js: the BD rules, as a table of cases run through node.

These functions are the product's rules: the annual pace bar, the cadence chip, the fallback
"next step", the priority score and the Friday pick of 5 new + 5 follow-ups. The backend
(backend/bd/priority.py, backend/bd/pace.py and the Friday batch) must give the same answers, so
this table is the shared spec. Change a row only when the rule changes.

The harness (tests/js/bd/bd-core-harness.js) LIFTS each function out of the file by name with
tests/js/bd/_lib.js, runs every case, then runs the same case through a whole-file VM load and
reports any disagreement.

All dates are Central calendar dates; "today" is always passed in, never read from a clock.
"""
import json
import pathlib

import pytest

from _node import last_json_line, require_node, run_node

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "frontend" / "bd" / "js" / "bd-core.js"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "bd" / "bd-core-harness.js"

DASH = "—"


# ── builders ────────────────────────────────────────────────────────────────────────────────
def contact(cid, freq=4, **kw):
    c = {"id": cid, "name": "Person %d" % cid, "category": "bd", "frequency_per_year": freq,
         "confirmed": True, "importance": 1, "last_live_at": None, "last_attempt_at": None,
         "attempts_since_live": 0, "touches_this_year": 0, "promised_date": None,
         "next_step_date": None, "last_quote_date": None}
    c.update(kw)
    return c


_next_iid = [5000]


def act(cid, kind, at, outcome=None, **kw):
    _next_iid[0] += 1
    i = {"id": _next_iid[0], "contact_id": cid, "kind": kind, "outcome": outcome,
         "occurred_at": at if "T" in at else at + "T10:00:00-06:00",
         "counts_as_touch": kind in ("meeting", "hosted") or outcome in ("answered", "meeting_set")}
    i.update(kw)
    return i


def touches(cid, n, day="2026-03-02"):
    return [act(cid, "call", day, "answered") for _ in range(n)]


def many(n, freq=4):
    return [contact(i, freq) for i in range(1, n + 1)]


# ── pace ────────────────────────────────────────────────────────────────────────────────────
# target = sum(frequency); required = target * day_of_year / days_in_year (1 decimal);
# pct = round(100 * completed / target); delta = round(completed - required).
NOV4_86 = [contact(i, 2) for i in range(1, 44)]          # 43 x 2 = 86
PACE_CASES = [
    ("day_one", [many(2), [], "2026-01-01"],
     {"required_to_date": 0.0, "completed": 0, "target_total": 8, "pct": 0, "delta": 0,
      "label": "2026 BD Pace: 0% " + DASH + " right on pace"}),
    ("mid_year_on_pace", [many(10), touches(1, 20), "2026-07-02"],
     {"required_to_date": 20.1, "completed": 20, "target_total": 40, "pct": 50, "delta": 0,
      "label": "2026 BD Pace: 50% " + DASH + " right on pace"}),
    ("dec_31_full_year_required", [many(10), touches(2, 30), "2026-12-31"],
     {"required_to_date": 40.0, "completed": 30, "target_total": 40, "pct": 75, "delta": -10,
      "label": "2026 BD Pace: 75% " + DASH + " 10 interactions behind pace"}),
    ("leap_year_dec_31", [many(10), touches(3, 40, "2028-02-29"), "2028-12-31"],
     {"required_to_date": 40.0, "completed": 40, "target_total": 40, "pct": 100, "delta": 0,
      "label": "2028 BD Pace: 100% " + DASH + " right on pace"}),
    ("zero_contacts", [[], [], "2026-06-15"],
     {"required_to_date": 0.0, "completed": 0, "target_total": 0, "pct": 0, "delta": 0,
      "label": "2026 BD Pace: 0% " + DASH + " right on pace"}),
    # Frequency 0 or missing counts as the default (4 bd, 3 maintenance), never as 0.
    ("frequency_zero_is_the_default", [[contact(1, 0), contact(2, 0, category="maintenance"), contact(3, None)], [], "2026-01-01"],
     {"target_total": 11}),
    ("ahead", [NOV4_86, touches(5, 81), "2026-11-04"],
     {"required_to_date": 72.6, "completed": 81, "target_total": 86, "pct": 94, "delta": 8,
      "label": "2026 BD Pace: 94% " + DASH + " 8 interactions ahead of pace"}),
    ("behind", [NOV4_86, touches(5, 62), "2026-11-04"],
     {"required_to_date": 72.6, "completed": 62, "target_total": 86, "pct": 72, "delta": -11,
      "label": "2026 BD Pace: 72% " + DASH + " 11 interactions behind pace"}),
    ("one_ahead_is_singular", [NOV4_86, touches(5, 74), "2026-11-04"],
     {"delta": 1, "label": "2026 BD Pace: 86% " + DASH + " 1 interaction ahead of pace"}),
    ("fourteen_behind", [NOV4_86, touches(5, 59), "2026-11-04"],
     {"required_to_date": 72.6, "completed": 59, "pct": 69, "delta": -14,
      "label": "2026 BD Pace: 69% " + DASH + " 14 interactions behind pace"}),
    # Only live calls, meetings and hosted events count; a `counts_as_touch: true` flag on an
    # email is ignored. Last year, the future and other people's contacts don't count either.
    ("only_touches_count", [many(1), [
        act(1, "email", "2026-05-01", counts_as_touch=True),
        act(1, "sms", "2026-05-01"),
        act(1, "note", "2026-05-01"),
        act(1, "voicemail", "2026-05-01", "voicemail"),
        act(1, "call", "2026-05-01", "no_answer"),
        act(1, "call", "2026-05-02", "answered"),
        act(1, "call", "2026-05-03", "meeting_set"),
        act(1, "meeting", "2026-05-04"),
        act(1, "hosted", "2026-05-05"),
        act(1, "meeting", "2025-12-31T23:30:00-06:00"),
        act(1, "meeting", "2026-12-01"),
        act(99, "meeting", "2026-05-06"),
    ], "2026-11-04"], {"completed": 4}),
    # A UTC timestamp is read in Central: 03:00Z on Jan 1 is still Dec 31 in Kansas.
    ("utc_new_years_eve_is_last_year", [many(1), [act(1, "meeting", "2026-01-01T03:00:00Z")], "2026-06-01"],
     {"completed": 0}),
]


# ── cadence ─────────────────────────────────────────────────────────────────────────────────
MAINT = {"category": "maintenance", "freq": 3}
CADENCE_CASES = [
    ("never_reached", contact(1), "2026-11-04", "never"),
    ("never_even_with_attempts", contact(1, attempts_since_live=3, last_attempt_at="2026-10-01T09:00:00-05:00"), "2026-11-04", "never"),
    # maintenance: due = last touch + 120 days (Jul 1 + 120 = Oct 29)
    ("maintenance_due_day_is_on_track", contact(1, **MAINT, last_live_at="2026-07-01T10:00:00-05:00", touches_this_year=1), "2026-10-29", "on_track"),
    ("maintenance_day_after_due_is_behind", contact(1, **MAINT, last_live_at="2026-07-01T10:00:00-05:00", touches_this_year=1), "2026-10-30", "behind"),
    ("maintenance_three_touches_complete", contact(1, **MAINT, last_live_at="2026-03-01T10:00:00-06:00", touches_this_year=3), "2026-11-04", "complete"),
    ("maintenance_two_touches_not_complete", contact(1, **MAINT, last_live_at="2026-10-01T10:00:00-05:00", touches_this_year=2), "2026-11-04", "on_track"),
    # bd, 4 a year: due = last live + 91 days (Aug 1 + 91 = Oct 31)
    ("bd_on_due_day_on_track", contact(1, 4, last_live_at="2026-08-01T10:00:00-05:00", touches_this_year=2), "2026-10-31", "on_track"),
    ("bd_after_365_over_freq_behind", contact(1, 4, last_live_at="2026-08-01T10:00:00-05:00", touches_this_year=2), "2026-11-01", "behind"),
    ("bd_frequency_met_complete", contact(1, 4, last_live_at="2026-02-01T10:00:00-06:00", touches_this_year=4), "2026-11-04", "complete"),
    ("bd_twice_a_year", contact(1, 2, last_live_at="2026-06-01T10:00:00-05:00", touches_this_year=1), "2026-11-04", "on_track"),
    # Maintenance is complete at 3 touches whatever its frequency says (the workbook's rule).
    ("maintenance_freq_4_complete_at_three", contact(1, 4, category="maintenance", last_live_at="2026-10-01T10:00:00-05:00",
                                                     touches_this_year=3), "2026-11-04", "complete"),
    # Frequency 0 (a bad import row) is the default 4, the same in pace, cadence and score:
    # Aug 1 + 91 = Oct 31, so Nov 4 is behind; 1 touch is not complete.
    ("frequency_zero_is_the_default", contact(1, 0, last_live_at="2026-08-01T10:00:00-05:00", touches_this_year=1), "2026-11-04", "behind"),
    ("frequency_zero_maintenance_needs_three", contact(1, 0, category="maintenance", last_live_at="2026-10-01T10:00:00-05:00",
                                                       touches_this_year=2), "2026-11-04", "on_track"),
]
NEXT_DUE_CASES = [
    ("maintenance_plus_120", contact(1, **MAINT, last_live_at="2026-07-01T10:00:00-05:00"), "2026-10-29"),
    ("bd_four_a_year_plus_91", contact(1, 4, last_live_at="2026-08-01T10:00:00-05:00"), "2026-10-31"),
    ("bd_twice_a_year_plus_182", contact(1, 2, last_live_at="2026-01-12T10:00:00-06:00"), "2026-07-13"),
    ("never_is_null", contact(1), None),
    ("frequency_zero_plus_91", contact(1, 0, last_live_at="2026-08-01T10:00:00-05:00"), "2026-10-31"),
]


# ── the BD cadence: the frequency a contact is held to ─────────────────────────────────────
# BD: the active override (its last day is today or later, the last day itself included), else the
# global cadence: weekly 52, monthly 12, quarterly 4, whatever frequency_per_year says.
# Maintenance: the stored number when it is 1 or more, else 3; never the cadence or an override.
# (case id, contact, global cadence, today, expected frequency)
TODAY = "2026-11-04"
FUTURE, EXPIRED = "2027-01-31", "2026-11-03"
OVR = {"cadence_override": "monthly", "cadence_override_until": FUTURE}
EFFECTIVE_FREQ_CASES = [
    ("bd_quarterly", contact(1), "quarterly", TODAY, 4),
    ("bd_monthly", contact(1), "monthly", TODAY, 12),
    ("bd_weekly", contact(1), "weekly", TODAY, 52),
    ("bd_stored_number_is_ignored", contact(1, 2), "quarterly", TODAY, 4),
    ("bd_stored_number_is_ignored_monthly", contact(1, 52), "monthly", TODAY, 12),
    ("bd_unknown_cadence_is_quarterly", contact(1), "daily", TODAY, 4),
    ("bd_no_cadence_is_quarterly", contact(1), None, TODAY, 4),
    ("bd_inherited_key_is_not_a_cadence", contact(1), "toString", TODAY, 4),
    ("override_beats_global", contact(1, **OVR), "quarterly", TODAY, 12),
    ("override_beats_a_weekly_global", contact(1, cadence_override="quarterly", cadence_override_until=FUTURE), "weekly", TODAY, 4),
    ("override_weekly", contact(1, cadence_override="weekly", cadence_override_until=FUTURE), "quarterly", TODAY, 52),
    ("override_last_day_is_inside", contact(1, cadence_override="monthly", cadence_override_until=TODAY), "quarterly", TODAY, 12),
    ("override_day_after_its_last_day_is_over", contact(1, cadence_override="monthly", cadence_override_until=EXPIRED), "quarterly", TODAY, 4),
    ("expired_override_falls_back_to_the_global", contact(1, cadence_override="monthly", cadence_override_until=EXPIRED), "weekly", TODAY, 52),
    ("override_without_a_last_day_is_ignored", contact(1, cadence_override="monthly"), "quarterly", TODAY, 4),
    ("last_day_without_an_override_is_ignored", contact(1, cadence_override_until=FUTURE), "quarterly", TODAY, 4),
    ("unknown_override_word_is_ignored", contact(1, cadence_override="daily", cadence_override_until=FUTURE), "quarterly", TODAY, 4),
    ("inherited_override_word_is_ignored", contact(1, cadence_override="constructor", cadence_override_until=FUTURE), "monthly", TODAY, 12),
    ("maintenance_keeps_its_number", contact(1, 2, category="maintenance"), "weekly", TODAY, 2),
    ("maintenance_four", contact(1, 4, category="maintenance"), "quarterly", TODAY, 4),
    ("maintenance_zero_is_three", contact(1, 0, category="maintenance"), "weekly", TODAY, 3),
    ("maintenance_missing_is_three", contact(1, None, category="maintenance"), "weekly", TODAY, 3),
    ("maintenance_below_one_is_three", contact(1, 0.5, category="maintenance"), "weekly", TODAY, 3),
    ("maintenance_ignores_an_override", contact(1, 2, category="maintenance", **OVR), "weekly", TODAY, 2),
]
# (case id, contact, global cadence, today, cadence, source)
CADENCE_OF_CASES = [
    ("global", contact(1), "monthly", TODAY, "monthly", "global"),
    ("global_unknown_is_quarterly", contact(1), "never", TODAY, "quarterly", "global"),
    ("override_active", contact(1, **OVR), "weekly", TODAY, "monthly", "override"),
    ("override_last_day", contact(1, cadence_override="weekly", cadence_override_until=TODAY), "monthly", TODAY, "weekly", "override"),
    ("override_expired", contact(1, cadence_override="weekly", cadence_override_until=EXPIRED), "monthly", TODAY, "monthly", "global"),
    ("maintenance_has_none", contact(1, category="maintenance", **OVR), "monthly", TODAY, None, None),
]


# ── follow-ups: when a maintenance contact is due ───────────────────────────────────────────
# last_followup_at = the latest call, voicemail, meeting, hosted, email or text (any outcome,
# never a note) dated on or before today. maintenance_due_date = that day + 120 (maintenance
# only); maintenance_due = never followed up, or the date has come (today counts).
# (case id, category, interactions, today, last follow-up as the timestamp or None, due date, due)
M1 = 1
MAINTENANCE_DUE_CASES = [
    ("never_followed_up_is_due_at_once", "maintenance", [], TODAY, None, None, True),
    ("a_note_alone_is_never_followed_up", "maintenance", [act(M1, "note", "2026-10-30")], TODAY, None, None, True),
    ("due_on_the_120th_day", "maintenance", [act(M1, "call", "2026-07-07", "no_answer")], TODAY,
     "2026-07-07T10:00:00-06:00", "2026-11-04", True),
    ("not_due_the_day_before", "maintenance", [act(M1, "call", "2026-07-08", "no_answer")], TODAY,
     "2026-07-08T10:00:00-06:00", "2026-11-05", False),
    ("an_answered_call_counts", "maintenance", [act(M1, "call", "2026-10-01", "answered")], TODAY,
     "2026-10-01T10:00:00-06:00", "2027-01-29", False),
    ("a_voicemail_counts", "maintenance", [act(M1, "voicemail", "2026-10-01", "voicemail")], TODAY,
     "2026-10-01T10:00:00-06:00", "2027-01-29", False),
    ("an_email_counts", "maintenance", [act(M1, "email", "2026-10-01")], TODAY, "2026-10-01T10:00:00-06:00", "2027-01-29", False),
    ("a_text_counts", "maintenance", [act(M1, "sms", "2026-10-01")], TODAY, "2026-10-01T10:00:00-06:00", "2027-01-29", False),
    ("a_meeting_counts", "maintenance", [act(M1, "meeting", "2026-10-01")], TODAY, "2026-10-01T10:00:00-06:00", "2027-01-29", False),
    ("a_hosted_event_counts", "maintenance", [act(M1, "hosted", "2026-10-01")], TODAY, "2026-10-01T10:00:00-06:00", "2027-01-29", False),
    ("a_later_note_does_not_move_the_date", "maintenance",
     [act(M1, "call", "2026-07-01", "answered"), act(M1, "note", "2026-10-30")], TODAY,
     "2026-07-01T10:00:00-06:00", "2026-10-29", True),
    ("the_latest_follow_up_wins", "maintenance",
     [act(M1, "call", "2026-03-01", "answered"), act(M1, "email", "2026-10-20"), act(M1, "sms", "2026-06-01")], TODAY,
     "2026-10-20T10:00:00-06:00", "2027-02-17", False),
    ("a_follow_up_after_today_is_not_one_yet", "maintenance",
     [act(M1, "call", "2026-07-07", "answered"), act(M1, "email", "2026-12-01")], TODAY,
     "2026-07-07T10:00:00-06:00", "2026-11-04", True),
    ("another_contacts_follow_up_is_not_mine", "maintenance", [act(2, "email", "2026-10-30")], TODAY, None, None, True),
    ("the_day_is_the_central_day", "maintenance", [act(M1, "call", "2026-07-08T03:00:00Z", "answered")], TODAY,
     "2026-07-08T03:00:00Z", "2026-11-04", True),
    ("late_evening_is_still_that_day", "maintenance", [act(M1, "email", "2026-07-07T23:30:00-05:00")], TODAY,
     "2026-07-07T23:30:00-05:00", "2026-11-04", True),
    ("a_bd_contact_has_no_date_and_is_never_due", "bd", [], TODAY, None, None, False),
    ("a_bd_contact_still_has_a_last_follow_up", "bd", [act(M1, "email", "2026-10-01")], TODAY,
     "2026-10-01T10:00:00-06:00", None, False),
]


# ── fallback next action ────────────────────────────────────────────────────────────────────
FALLBACK_CASES = [
    ("answered", ["answered", "", TODAY], "2027-02-17", "Check in again in about 3–4 months"),
    ("meeting_set", ["meeting_set", "", TODAY], "2027-02-17", "Check in again in about 3–4 months"),
    ("meeting_kind", ["meeting", None, TODAY], "2027-02-17", "Check in again in about 3–4 months"),
    ("voicemail", ["voicemail", "Left a voicemail.", TODAY], "2026-11-11", "Try again next week"),
    ("no_answer", ["no_answer", None, TODAY], "2026-11-11", "Try again next week"),
    ("call_me_next_month", ["answered", "Good talk. Call me next month.", TODAY], "2026-12-04", None),
    ("next_month_clamps_jan_31", ["answered", "call me next month", "2026-01-31"], "2026-02-28", None),
    ("in_3_weeks", ["answered", "Try me in 3 weeks", TODAY], "2026-11-25", None),
    ("in_two_weeks_words", ["voicemail", "Assistant said in two weeks", TODAY], "2026-11-18", None),
    ("in_a_couple_of_weeks", ["answered", "check back in a couple of weeks", TODAY], "2026-11-18", None),
    ("in_2_months", ["answered", "Budget opens in 2 months", TODAY], "2027-01-04", None),
    ("after_january", ["answered", "Busy until after January", TODAY], "2027-02-01", None),
    ("after_march_said_in_november", ["answered", "nothing until after March", TODAY], "2027-04-01", None),
    ("after_december_rolls_the_year", ["answered", "after December", TODAY], "2027-01-01", None),
    ("text_beats_voicemail_rule", ["voicemail", "VM said call next month", TODAY], "2026-12-04", None),
]


# ── score ───────────────────────────────────────────────────────────────────────────────────
SCORE_CASES = [
    ("never_contacted_unconfirmed", contact(1, confirmed=False), {}, 48,
     ["Never contacted", "Needs confirming: still the right person?"]),
    ("never_reached_with_tries_key", contact(1, importance=3, attempts_since_live=2,
                                             last_attempt_at="2026-10-20T09:00:00-05:00"), {}, 70,
     ["Never reached after 2 tries", "Key account"]),
    ("tries_capped_at_three", contact(1, attempts_since_live=7, last_attempt_at="2026-10-20T09:00:00-05:00"), {}, 55, None),
    ("promised_past_due", contact(1, last_live_at="2026-10-01T10:00:00-05:00", promised_date="2026-11-02"), {}, None,
     ["Promised a call by Mon, Nov 2"]),
    ("cadence_capped_at_40", contact(1, last_live_at="2025-01-01T10:00:00-06:00"), {}, 40, None),
    ("importance_two_adds_points_not_words", contact(1, importance=2, confirmed=False), {}, 58,
     ["Never contacted", "Needs confirming: still the right person?"]),
    ("recent_quote", contact(1, last_live_at="2026-10-28T10:00:00-05:00", last_quote_date="2026-10-21"), {}, 17,
     ["Recent quote activity (Wed, Oct 21)", "Last live talk 7 days ago; needs 4 a year"]),
    ("old_quote_ignored", contact(1, last_live_at="2026-10-28T10:00:00-05:00", last_quote_date="2026-09-01"), {}, 2, None),
    # A next step or promise dated on or before the last live talk was met by that talk: no +50.
    # Last live 5 days ago (round(30 * 5 / 91.25) = 2), next step due 10 days ago.
    ("stale_next_step_after_live_talk", contact(1, last_live_at="2026-10-30T10:00:00-05:00", next_step_date="2026-10-25"), {}, 2,
     ["Last live talk 5 days ago; needs 4 a year"]),
    ("promise_met_by_live_talk_same_day", contact(1, last_live_at="2026-10-30T10:00:00-05:00", promised_date="2026-10-30"), {}, 2, None),
    ("promise_after_live_talk_still_counts", contact(1, last_live_at="2026-10-30T10:00:00-05:00", promised_date="2026-11-02"), {}, 52,
     ["Promised a call by Mon, Nov 2"]),
    # Frequency 0 scores like the default 4: last live Jan 2 is 306 days, capped at 40.
    ("frequency_zero_scores_like_four", contact(1, 0, last_live_at="2026-01-02T10:00:00-06:00"), {}, 40,
     ["Last live talk 10 months ago; needs 4 a year"]),
    ("maintenance_needs_three", contact(1, 4, category="maintenance", last_live_at="2026-07-01T10:00:00-05:00"), {}, None,
     ["Last live talk 4 months ago; needs 3 a year"]),
]
# Promise windows: due or past +50, within 7 days +25, 8 days 0. Score minus the cadence part
# (last live 2026-10-28 is 7 days before TODAY: round(30 * 7 / 91.25) = 2 points).
PROMISE_CASES = [("past", "2026-11-03", 52), ("today", "2026-11-04", 52), ("in_7_days", "2026-11-11", 27),
                 ("in_8_days", "2026-11-12", 2)]


# ── weekly pick ─────────────────────────────────────────────────────────────────────────────
def news(ids):           # never reached -> "new"; ordered by a descending score via importance
    return [contact(i, confirmed=False, importance=3 if i % 2 else 1) for i in ids]


def follows(ids, base="2026-06-01T10:00:00-05:00"):
    return [contact(i, last_live_at=base, touches_this_year=1) for i in ids]


RECENT = "2026-11-02T09:00:00-06:00"     # 2 days before TODAY: still cooling off
THREE_AGO = "2026-11-01T09:00:00-05:00"  # 3 days before TODAY: eligible again
WEEKLY_CASES = [
    ("five_and_five", [news(range(1, 9)) + follows(range(101, 109)), None, [], TODAY], 10, 5, 5),
    ("short_new_filled_by_followups", [news([1, 2]) + follows(range(101, 111)), None, [], TODAY], 10, 2, 8),
    ("short_followups_filled_by_new", [news(range(1, 11)) + follows([101]), None, [], TODAY], 10, 9, 1),
    ("fewer_than_ten_returns_all", [news([1, 2, 3]) + follows([101, 102]), None, [], TODAY], 5, 3, 2),
    ("open_tasks_excluded", [news(range(1, 9)) + follows(range(101, 109)), None, [1, 3, 5, 101, 103], TODAY], 10, 5, 5),
    # "new" means never had a live talk. Unconfirmed does not change the kind (it adds +8 and a chip).
    ("unconfirmed_with_live_talk_is_followup",
     [[contact(1, confirmed=False, last_live_at="2026-06-01T10:00:00-05:00", touches_this_year=1)], None, [], TODAY], 1, 0, 1),
    # The reviewer's case: every contact unconfirmed (as the workbook imports them), half with a
    # past live talk. The 5 + 5 split must hold.
    ("all_unconfirmed_still_five_and_five",
     [[contact(i, confirmed=False) for i in range(1, 9)] +
      [contact(i, confirmed=False, last_live_at="2026-06-01T10:00:00-05:00", touches_this_year=1) for i in range(101, 109)],
      None, [], TODAY], 10, 5, 5),
]


# ── maintenance, pinned to the top ──────────────────────────────────────────────────────────
# A maintenance contact is on the list ONLY when due, as a "maintenance" task above the BD picks
# (most overdue first: the earliest follow-up date, never followed up before any date, then the
# lower id). Not due = excluded from both the Friday build and Give Me 10 More (exclusion 4, checked
# after archived / already in a batch / tried in the last 3 days).
LAST_FU = "2026-07-01T10:00:00-05:00"      # any follow-up timestamp: the reason reads the due date


def mdue(cid, due_date=None, **kw):
    """A DUE maintenance contact as the view hands it over: never followed up when due_date is None."""
    return contact(cid, 3, category="maintenance", maintenance_due=True, maintenance_due_date=due_date,
                   last_followup_at=LAST_FU if due_date else None, **kw)


def mwait(cid, **kw):
    """A maintenance contact that is NOT due yet."""
    return contact(cid, 3, category="maintenance", maintenance_due=False, maintenance_due_date="2027-01-29",
                   last_followup_at="2026-10-01T10:00:00-05:00", **kw)


# (case id, contact, expected kind)
TASK_KIND_CASES = [
    ("due_maintenance", mdue(1, "2026-10-01"), "maintenance"),
    ("due_maintenance_never_followed_up", mdue(1), "maintenance"),
    ("due_maintenance_with_a_live_talk", mdue(1, "2026-10-01", last_live_at="2026-06-01T10:00:00-05:00"), "maintenance"),
    ("not_due_maintenance_keeps_the_old_kind", mwait(1), "new"),
    ("not_due_maintenance_with_a_live_talk", mwait(1, last_live_at="2026-10-01T10:00:00-05:00"), "followup"),
    ("bd_never_reached", contact(1), "new"),
    ("bd_reached", contact(1, last_live_at="2026-10-01T10:00:00-05:00"), "followup"),
    ("bd_ignores_the_due_flag", contact(1, maintenance_due=True), "new"),
    ("bd_unconfirmed_is_still_new", contact(1, confirmed=False), "new"),
]

# (case id, contact, facts, excluded, why)
EXCLUSION_CASES = [
    ("maintenance_not_due", mwait(1), {}, True, "maintenance, not due yet"),
    ("maintenance_field_missing_is_not_due", contact(1, 3, category="maintenance"), {}, True, "maintenance, not due yet"),
    ("maintenance_due_is_in", mdue(1, "2026-10-01"), {}, False, None),
    ("maintenance_never_followed_up_is_in", mdue(1), {}, False, None),
    ("bd_with_a_false_flag_is_in", contact(1, maintenance_due=False), {}, False, None),
    # the order of the exclusions: archived, in a batch, tried in the last 3 days, then this one
    ("archived_comes_first", mwait(1, archived_at="2026-10-01T10:00:00-05:00"), {}, True, "archived"),
    ("open_task_before_not_due", mwait(1), {"has_open_task": True}, True, "already in this week's list"),
    ("tried_recently_before_not_due", mwait(1, last_attempt_at="2026-11-03T09:00:00-06:00"), {}, True, "tried in the last 3 days"),
    ("due_but_tried_recently", mdue(1, "2026-10-01", last_attempt_at="2026-11-03T09:00:00-06:00"), {}, True, "tried in the last 3 days"),
    ("due_but_in_a_batch", mdue(1, "2026-10-01"), {"has_open_task": True}, True, "already in this week's list"),
]

# (case id, contact, today, reason)
DUE_REASON_CASES = [
    ("never_followed_up", mdue(1), TODAY, "No follow-up logged yet"),
    ("due_today", mdue(1, TODAY), TODAY, "Follow-up due today"),
    ("was_due_yesterday", mdue(1, "2026-11-03"), TODAY, "Follow-up was due Tue, Nov 3"),
    ("was_due_weeks_ago", mdue(1, "2026-10-01"), TODAY, "Follow-up was due Thu, Oct 1"),
    ("was_due_last_year", mdue(1, "2025-12-31"), TODAY, "Follow-up was due Wed, Dec 31"),
    ("never_wins_over_a_stray_date", contact(1, 3, category="maintenance", maintenance_due=True,
                                             maintenance_due_date="2026-10-01", last_followup_at=None), TODAY,
     "No follow-up logged yet"),
]

# Contacts as the view hands them over (derived fields set), nothing derived from interactions.
RANK_CONTACTS = [
    mdue(9, "2026-10-20"),
    contact(1, importance=3, confirmed=False),                  # BD, a high score
    mdue(7, "2026-09-01"),                                      # the most overdue
    mdue(5),                                                    # never followed up: before every date
    mdue(3),                                                    # never followed up, lower id than 5
    mwait(11),                                                  # not due: not on the list
    contact(2, last_live_at="2026-10-01T10:00:00-05:00"),       # BD, a low score
    mdue(8, "2026-10-20"),                                      # same date as 9: lower id first
]


def pick_mix(n_maintenance, n_new, n_follow):
    """Due maintenance contacts 100.., BD 'new' 1.., BD follow-ups 300.. (ids ascending)."""
    return ([mdue(100 + i, "2026-10-%02d" % (1 + i % 20)) for i in range(n_maintenance)] +
            news(range(1, n_new + 1)) + follows(range(300, 300 + n_follow)))


# From interactions: the view's fields are derived by the same call (null interactions = trust the contact).
MAINT_FROM_INTERACTIONS = [
    contact(1, 3, category="maintenance"),                     # never followed up: due, first
    contact(2, 3, category="maintenance"),                     # a call on 2026-06-01: due 2026-09-29
    contact(3, 3, category="maintenance"),                     # an email on 2026-07-07: due today
    contact(4, 3, category="maintenance"),                     # an email on 2026-10-01: not due
    contact(5, 3, category="maintenance"),                     # a note only: still never followed up
    contact(6, 3, category="maintenance"),                     # a follow-up dated tomorrow: not one yet
    contact(7, 4, confirmed=False),                            # BD
]
MAINT_INTERACTIONS = [
    act(2, "call", "2026-06-01", "no_answer"),
    act(3, "email", "2026-07-07"),
    act(4, "email", "2026-10-01"),
    act(5, "note", "2026-10-30"),
    act(6, "email", "2026-11-05"),
]


# deriveContact end to end: the cadence fields, the derived frequency, and what reads it.
LIVE_OCT1 = [act(1, "call", "2026-10-01", "answered")]
# (case id, args, expected fields)
DERIVE_CASES = [
    ("global_weekly", [contact(1, 2), LIVE_OCT1, TODAY, "weekly"],
     {"cadence": "weekly", "cadence_source": "global", "frequency_per_year": 52, "next_due_date": "2026-10-08",
      "cadence_status": "behind", "cadence_override": None, "cadence_override_until": None}),
    ("global_monthly", [contact(1, 2), LIVE_OCT1, TODAY, "monthly"],
     {"cadence": "monthly", "cadence_source": "global", "frequency_per_year": 12, "next_due_date": "2026-10-31",
      "cadence_status": "behind"}),
    ("global_quarterly", [contact(1, 2), LIVE_OCT1, TODAY, "quarterly"],
     {"cadence": "quarterly", "cadence_source": "global", "frequency_per_year": 4, "next_due_date": "2026-12-31",
      "cadence_status": "on_track"}),
    ("override_active", [contact(1, 4, **OVR), LIVE_OCT1, TODAY, "quarterly"],
     {"cadence": "monthly", "cadence_source": "override", "frequency_per_year": 12, "next_due_date": "2026-10-31",
      "cadence_status": "behind", "cadence_override": "monthly", "cadence_override_until": FUTURE}),
    ("override_last_day", [contact(1, 4, cadence_override="monthly", cadence_override_until=TODAY), LIVE_OCT1, TODAY, "quarterly"],
     {"cadence": "monthly", "cadence_source": "override", "frequency_per_year": 12}),
    ("override_expired_the_next_day", [contact(1, 12, cadence_override="monthly", cadence_override_until=TODAY),
                                       LIVE_OCT1, "2026-11-05", "quarterly"],
     {"cadence": "quarterly", "cadence_source": "global", "frequency_per_year": 4, "next_due_date": "2026-12-31",
      "cadence_override": "monthly", "cadence_override_until": TODAY}),
    ("override_expired_follows_a_weekly_global", [contact(1, 4, cadence_override="monthly", cadence_override_until=EXPIRED),
                                                  LIVE_OCT1, TODAY, "weekly"],
     {"cadence": "weekly", "cadence_source": "global", "frequency_per_year": 52}),
    ("maintenance_has_no_cadence", [contact(1, 2, category="maintenance", **OVR), LIVE_OCT1, TODAY, "weekly"],
     {"cadence": None, "cadence_source": None, "frequency_per_year": 2, "next_due_date": "2027-01-29",
      "cadence_override": "monthly"}),
    ("maintenance_bad_number_is_three", [contact(1, 0, category="maintenance"), LIVE_OCT1, TODAY, "weekly"],
     {"frequency_per_year": 3}),
    ("no_cadence_given_is_quarterly", [contact(1, 2), LIVE_OCT1, TODAY],
     {"cadence": "quarterly", "frequency_per_year": 4}),
]
# The same BD contact (last live talk Oct 1, 34 days ago) picked for the week under each global
# cadence: its cadence points follow the number a year (min(40, round(30 x days / (365 / freq)))).
GLOBAL_CHANGE_CASES = [("weekly", "weekly", 40, "Last live talk 4 weeks ago; needs 52 a year"),
                       ("monthly", "monthly", 34, "Last live talk 4 weeks ago; needs 12 a year"),
                       ("quarterly", "quarterly", 11, "Last live talk 4 weeks ago; needs 4 a year")]


def build_cases():
    cases = []
    for cid, args, _ in PACE_CASES:
        cases.append({"id": "pace:" + cid, "fn": "pace", "args": args})
    cases.append({"id": "progress", "fn": "weeklyProgress", "args": [
        [{"status": "done"}] * 7 + [{"status": "open"}, {"status": "snoozed"}, {"status": "open"}]]})
    cases.append({"id": "progress:empty", "fn": "weeklyProgress", "args": [[]]})
    for cid, c, today, _ in CADENCE_CASES:
        cases.append({"id": "cadence:" + cid, "fn": "cadenceStatus", "args": [c, today]})
    for cid, c, _ in NEXT_DUE_CASES:
        cases.append({"id": "due:" + cid, "fn": "nextDueDate", "args": [c]})
    for cid, c, cadence, today, _ in EFFECTIVE_FREQ_CASES:
        cases.append({"id": "freq:" + cid, "fn": "effectiveFrequency", "args": [c, cadence, today]})
    for cid, c, cadence, today, *_ in CADENCE_OF_CASES:
        cases.append({"id": "cadof:" + cid, "fn": "cadenceOf", "args": [c, cadence, today]})
    for cid, category, acts, today, *_ in MAINTENANCE_DUE_CASES:
        cases.append({"id": "mdue:" + cid, "fn": "deriveContact",
                      "args": [contact(M1, 3, category=category), acts, today, "quarterly"]})
    for cid, args, *_ in DERIVE_CASES:
        cases.append({"id": "derive:" + cid, "fn": "deriveContact", "args": args})
    for cid, cadence, *_ in GLOBAL_CHANGE_CASES:
        cases.append({"id": "global:" + cid, "fn": "pickWeekly", "args": [
            [contact(1, 2)], [act(1, "call", "2026-10-01", "answered")], [], TODAY, 5, 5, cadence]})
    for cid, args, _, _ in FALLBACK_CASES:
        cases.append({"id": "fallback:" + cid, "fn": "fallbackNextAction", "args": args})
    for cid, c, facts, _, _ in SCORE_CASES:
        cases.append({"id": "score:" + cid, "fn": "scoreContact", "args": [c, facts, TODAY]})
    for cid, date, _ in PROMISE_CASES:
        c = contact(1, last_live_at="2026-10-28T10:00:00-05:00", promised_date=date)
        cases.append({"id": "promise:" + cid, "fn": "scoreContact", "args": [c, {}, TODAY]})
    for cid, args, *_ in WEEKLY_CASES:
        cases.append({"id": "weekly:" + cid, "fn": "pickWeekly", "args": args})
    # The 3-day cooling-off: tried 2 days ago is left out, 3 days ago is back in.
    cooling = [contact(1, confirmed=False, attempts_since_live=1, last_attempt_at=RECENT),
               contact(2, confirmed=False, attempts_since_live=1, last_attempt_at=THREE_AGO),
               contact(3, confirmed=False, attempts_since_live=1, last_attempt_at="2026-11-04T08:00:00-06:00")]
    cases.append({"id": "weekly:cooling_off", "fn": "pickWeekly", "args": [cooling, None, [], TODAY]})
    # Derived from interactions: a voicemail today makes the contact "tried today" -> left out.
    cases.append({"id": "weekly:from_interactions", "fn": "pickWeekly", "args": [
        [contact(1, confirmed=False), contact(2, confirmed=False)],
        [act(1, "voicemail", "2026-11-04T09:00:00-06:00", "voicemail")], [], TODAY]})
    cases.append({"id": "next:ten_more_by_score", "fn": "pickNext", "args": [
        news(range(1, 9)) + follows(range(101, 109)), None, [1, 2], TODAY, 10]})
    for cid, c, _ in TASK_KIND_CASES:
        cases.append({"id": "kind:" + cid, "fn": "taskKind", "args": [c]})
    for cid, c, facts, *_ in EXCLUSION_CASES:
        cases.append({"id": "excl:" + cid, "fn": "scoreContact", "args": [c, facts, TODAY]})
    for cid, c, today, _ in DUE_REASON_CASES:
        cases.append({"id": "reason:" + cid, "fn": "maintenanceDueReason", "args": [c, today]})
    cases.append({"id": "rank:maintenance_first", "fn": "rankContacts", "args": [RANK_CONTACTS, None, [], TODAY]})
    cases.append({"id": "rank:skips_open_tasks", "fn": "rankContacts", "args": [RANK_CONTACTS, None, [3, 7, 1], TODAY]})
    for n in (0, 3, 12):
        cases.append({"id": "pickm:%d" % n, "fn": "pickWeekly", "args": [pick_mix(n, 8, 8), None, [], TODAY]})
    cases.append({"id": "pickm:short_bd_side", "fn": "pickWeekly", "args": [pick_mix(4, 2, 10), None, [], TODAY]})
    cases.append({"id": "pickm:custom_split", "fn": "pickWeekly", "args": [pick_mix(2, 8, 8), None, [], TODAY, 3, 2]})
    cases.append({"id": "pickm:only_maintenance", "fn": "pickWeekly", "args": [pick_mix(3, 0, 0), None, [], TODAY]})
    cases.append({"id": "pickm:only_not_due", "fn": "pickWeekly", "args": [[mwait(1), mwait(2)], None, [], TODAY]})
    cases.append({"id": "pickm:open_task_skipped", "fn": "pickWeekly", "args": [pick_mix(3, 2, 2), None, [100, 1], TODAY]})
    cases.append({"id": "pickm:from_interactions", "fn": "pickWeekly", "args": [
        MAINT_FROM_INTERACTIONS, MAINT_INTERACTIONS, [], TODAY]})
    cases.append({"id": "pickm:next_heads_with_maintenance", "fn": "pickNext", "args": [
        pick_mix(2, 8, 8), None, [], TODAY, 10]})
    cases.append({"id": "pickm:next_skips_what_is_on_the_list", "fn": "pickNext", "args": [
        pick_mix(3, 4, 4), None, [100, 2, 300], TODAY, 10]})
    cases.append({"id": "pickm:next_more_maintenance_than_n", "fn": "pickNext", "args": [
        pick_mix(5, 4, 4), None, [], TODAY, 3]})
    cases.append({"id": "pickm:next_from_interactions", "fn": "pickNext", "args": [
        MAINT_FROM_INTERACTIONS, MAINT_INTERACTIONS, [], TODAY, 10]})
    return cases


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    require_node()
    path = tmp_path_factory.mktemp("bdcore") / "cases.json"
    path.write_text(json.dumps(build_cases()), encoding="utf-8")
    proc = run_node(HARNESS, CORE, path)
    assert proc.returncode == 0, "the bd-core harness failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


def result(harness, cid):
    r = harness["results"][cid]
    assert not (isinstance(r, dict) and set(r) == {"error"}), "%s raised: %s" % (cid, r["error"])
    return r


# ── the file itself ─────────────────────────────────────────────────────────────────────────
def test_every_case_agrees_with_the_whole_file_run(harness):
    """Lifted-by-name and loaded-whole must answer the same, or the lifting is lying."""
    assert harness["vm_disagrees"] == []


def test_file_creates_only_window_bdcore(harness):
    assert harness["vm_globals"] == []
    assert harness["vm_window_keys"] == ["BDCore"]


@pytest.mark.parametrize("name", ["pace", "weeklyProgress", "freqOf", "touchesNeeded", "cadenceStatus", "fallbackNextAction",
                                  "scoreContact", "pickWeekly", "pickNext", "deriveContact", "nextDueDate",
                                  "taskKind", "rankContacts", "maintenanceDueReason"])
def test_public_rules_are_exported(harness, name):
    assert name in harness["exports"]
    assert name in harness["lifted"]


# ── pace ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid, args, expected", PACE_CASES, ids=[c[0] for c in PACE_CASES])
def test_pace(harness, cid, args, expected):
    got = result(harness, "pace:" + cid)
    assert got["year"] == int(args[2][:4]) and got["as_of"] == args[2]
    for key, value in expected.items():
        assert got[key] == value, "%s: %s is %r, expected %r" % (cid, key, got[key], value)


def test_weekly_progress(harness):
    assert result(harness, "progress") == {"done": 7, "total": 10, "label": "7 of 10 done"}
    assert result(harness, "progress:empty") == {"done": 0, "total": 0, "label": "0 of 0 done"}


# ── cadence ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid, c, today, expected", CADENCE_CASES, ids=[c[0] for c in CADENCE_CASES])
def test_cadence_status(harness, cid, c, today, expected):
    assert result(harness, "cadence:" + cid) == expected


@pytest.mark.parametrize("cid, c, expected", NEXT_DUE_CASES, ids=[c[0] for c in NEXT_DUE_CASES])
def test_next_due_date(harness, cid, c, expected):
    assert result(harness, "due:" + cid) == expected


# ── the BD cadence and the follow-up clock ──────────────────────────────────────────────────
@pytest.mark.parametrize("cid, c, cadence, today, expected", EFFECTIVE_FREQ_CASES, ids=[c[0] for c in EFFECTIVE_FREQ_CASES])
def test_effective_frequency(harness, cid, c, cadence, today, expected):
    assert result(harness, "freq:" + cid) == expected


@pytest.mark.parametrize("cid, c, cadence, today, want, source", CADENCE_OF_CASES, ids=[c[0] for c in CADENCE_OF_CASES])
def test_cadence_of(harness, cid, c, cadence, today, want, source):
    assert result(harness, "cadof:" + cid) == {"cadence": want, "source": source}


@pytest.mark.parametrize("cid, category, acts, today, last, due_date, due", MAINTENANCE_DUE_CASES,
                         ids=[c[0] for c in MAINTENANCE_DUE_CASES])
def test_maintenance_due(harness, cid, category, acts, today, last, due_date, due):
    got = result(harness, "mdue:" + cid)
    assert got["last_followup_at"] == last
    assert got["maintenance_due_date"] == due_date
    assert got["maintenance_due"] is due


@pytest.mark.parametrize("cid, args, expected", DERIVE_CASES, ids=[c[0] for c in DERIVE_CASES])
def test_derive_contact_cadence_fields(harness, cid, args, expected):
    got = result(harness, "derive:" + cid)
    for key, value in expected.items():
        assert got[key] == value, "%s: %s is %r, expected %r" % (cid, key, got[key], value)


@pytest.mark.parametrize("cid, cadence, score, reason", GLOBAL_CHANGE_CASES, ids=[c[0] for c in GLOBAL_CHANGE_CASES])
def test_changing_the_global_cadence_changes_the_score(harness, cid, cadence, score, reason):
    tasks = result(harness, "global:" + cid)
    assert len(tasks) == 1
    assert tasks[0]["score"] == score
    assert tasks[0]["reasons"][0] == reason


def test_maintenance_due_fields_are_exported(harness):
    for name in ("effectiveFrequency", "cadenceOf", "lastFollowupAt", "maintenanceDueDate", "isMaintenanceDue"):
        assert name in harness["exports"] and name in harness["lifted"], name
    assert "CADENCE_FREQ" in harness["consts"]


def test_cadence_numbers_are_weekly_52_monthly_12_quarterly_4(harness):
    for _cid, cadence, *_ in GLOBAL_CHANGE_CASES:
        want = {"weekly": 52, "monthly": 12, "quarterly": 4}[cadence]
        assert result(harness, "freq:bd_" + cadence) == want


# ── fallback next action ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid, args, due, action", FALLBACK_CASES, ids=[c[0] for c in FALLBACK_CASES])
def test_fallback_next_action(harness, cid, args, due, action):
    got = result(harness, "fallback:" + cid)
    assert got["due_date"] == due
    assert got["source"] == "fallback"
    assert got["reason"].strip()
    if action:
        assert got["action"] == action


# ── score ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid, c, facts, score, reasons", SCORE_CASES, ids=[c[0] for c in SCORE_CASES])
def test_score_contact(harness, cid, c, facts, score, reasons):
    got = result(harness, "score:" + cid)
    if score is not None:
        assert got["score"] == score
    if reasons is not None:
        assert got["reasons"][:len(reasons)] == reasons


@pytest.mark.parametrize("cid, date, score", PROMISE_CASES, ids=[c[0] for c in PROMISE_CASES])
def test_promise_window(harness, cid, date, score):
    assert result(harness, "promise:" + cid)["score"] == score


# ── weekly pick ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid, args, total, n_new, n_follow", WEEKLY_CASES, ids=[c[0] for c in WEEKLY_CASES])
def test_pick_weekly_split(harness, cid, args, total, n_new, n_follow):
    tasks = result(harness, "weekly:" + cid)
    kinds = [t["kind"] for t in tasks]
    assert len(tasks) == total
    assert kinds.count("new") == n_new and kinds.count("followup") == n_follow
    excluded = set(args[2])
    assert not excluded & {t["contact_id"] for t in tasks}, "a contact with an open task came back"
    assert len({t["contact_id"] for t in tasks}) == len(tasks), "a contact was picked twice"
    scores = [t["score"] for t in tasks]
    assert scores == sorted(scores, reverse=True), "tasks are not best-first"
    assert all(t["reason"] and t["reasons"] for t in tasks), "every task says why it was picked"


def test_pick_weekly_takes_the_best_of_each_side(harness):
    tasks = result(harness, "weekly:five_and_five")
    new_ids = {t["contact_id"] for t in tasks if t["kind"] == "new"}
    # the odd ids are key accounts (+20), so they outrank the even ones
    assert new_ids == {1, 3, 5, 7, 2}


def test_pick_weekly_skips_anyone_tried_in_the_last_three_days(harness):
    ids = [t["contact_id"] for t in result(harness, "weekly:cooling_off")]
    assert ids == [2]
    assert [t["contact_id"] for t in result(harness, "weekly:from_interactions")] == [2]


def test_pick_next_is_top_n_by_score_whatever_the_kind(harness):
    tasks = result(harness, "next:ten_more_by_score")
    assert len(tasks) == 10
    assert not {1, 2} & {t["contact_id"] for t in tasks}
    scores = [t["score"] for t in tasks]
    assert scores == sorted(scores, reverse=True)


# ── maintenance, pinned to the top ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("cid, c, kind", TASK_KIND_CASES, ids=[c[0] for c in TASK_KIND_CASES])
def test_task_kind(harness, cid, c, kind):
    assert result(harness, "kind:" + cid) == kind


@pytest.mark.parametrize("cid, c, facts, excluded, why", EXCLUSION_CASES, ids=[c[0] for c in EXCLUSION_CASES])
def test_exclusion_four_maintenance_not_due(harness, cid, c, facts, excluded, why):
    got = result(harness, "excl:" + cid)
    assert got["excluded"] is excluded
    assert got["exclude_reason"] == why


def test_an_excluded_maintenance_contact_still_gets_its_score(harness):
    got = result(harness, "excl:maintenance_not_due")
    assert got["excluded"] is True
    assert got["score"] == 40 and got["reasons"] == ["Never contacted"], "scored as any contact is"


@pytest.mark.parametrize("cid, c, today, reason", DUE_REASON_CASES, ids=[c[0] for c in DUE_REASON_CASES])
def test_maintenance_due_reason(harness, cid, c, today, reason):
    assert result(harness, "reason:" + cid) == reason


def ids_of(tasks):
    return [t["contact_id"] for t in tasks]


def test_rank_puts_due_maintenance_first_most_overdue_first(harness):
    ranked = result(harness, "rank:maintenance_first")
    # never followed up (ids 3, 5), then by due date (Sep 1, then Oct 20 twice: 8 before 9), then BD by score
    assert [r["contact"]["id"] for r in ranked] == [3, 5, 7, 8, 9, 1, 2]
    assert [r["kind"] for r in ranked] == ["maintenance"] * 5 + ["new", "followup"]


def test_rank_leaves_a_not_due_maintenance_contact_out(harness):
    assert 11 not in [r["contact"]["id"] for r in result(harness, "rank:maintenance_first")]


def test_rank_skips_contacts_already_on_the_list(harness):
    assert [r["contact"]["id"] for r in result(harness, "rank:skips_open_tasks")] == [5, 8, 9, 2]


def test_a_maintenance_task_carries_the_normal_score_and_the_due_reason_first(harness):
    by_id = {r["contact"]["id"]: r for r in result(harness, "rank:maintenance_first")}
    assert by_id[3]["reasons"][0] == "No follow-up logged yet"
    assert by_id[7]["reasons"][0] == "Follow-up was due Tue, Sep 1"
    assert by_id[3]["score"] == 40, "the score is the priority score (never contacted = 40), not the pin"
    assert by_id[7]["reasons"][1:] == ["Never contacted"]
    assert by_id[7]["reason"] == "Follow-up was due Tue, Sep 1. Never contacted."


def test_the_reason_chip_is_the_top_two_reasons(harness):
    by_id = {r["contact"]["id"]: r for r in result(harness, "rank:maintenance_first")}
    # due reason, then the strongest scored reason
    assert by_id[9]["reason"] == "Follow-up was due Tue, Oct 20. Never contacted."


@pytest.mark.parametrize("n_maintenance", [0, 3, 12])
def test_pick_weekly_maintenance_first_then_five_and_five(harness, n_maintenance):
    tasks = result(harness, "pickm:%d" % n_maintenance)
    kinds = [t["kind"] for t in tasks]
    assert kinds[:n_maintenance] == ["maintenance"] * n_maintenance
    bd = tasks[n_maintenance:]
    assert [t["kind"] for t in bd].count("new") == 5 and [t["kind"] for t in bd].count("followup") == 5
    assert len(tasks) == n_maintenance + 10, "more than 10 due makes the batch longer, never the BD part shorter"
    scores = [t["score"] for t in bd]
    assert scores == sorted(scores, reverse=True), "the BD picks are best-first"


def test_pick_weekly_orders_maintenance_by_due_date_then_id(harness):
    tasks = result(harness, "pickm:3")
    dates = [t["contact"]["maintenance_due_date"] for t in tasks[:3]]
    assert dates == sorted(dates)


def test_pick_weekly_bd_split_ignores_the_maintenance_count(harness):
    tasks = result(harness, "pickm:short_bd_side")
    kinds = [t["kind"] for t in tasks]
    assert kinds.count("maintenance") == 4
    assert kinds.count("new") == 2 and kinds.count("followup") == 8, "the short side is filled from the other"


def test_pick_weekly_custom_split_applies_to_bd_only(harness):
    kinds = [t["kind"] for t in result(harness, "pickm:custom_split")]
    assert kinds.count("maintenance") == 2 and kinds.count("new") == 3 and kinds.count("followup") == 2


def test_pick_weekly_with_only_maintenance_due(harness):
    assert [t["kind"] for t in result(harness, "pickm:only_maintenance")] == ["maintenance"] * 3


def test_pick_weekly_never_lists_a_not_due_maintenance_contact(harness):
    assert result(harness, "pickm:only_not_due") == []


def test_pick_weekly_skips_a_maintenance_contact_already_in_a_batch(harness):
    tasks = result(harness, "pickm:open_task_skipped")
    assert 100 not in ids_of(tasks) and 1 not in ids_of(tasks)
    assert [t["kind"] for t in tasks].count("maintenance") == 2


def test_pick_weekly_derives_the_due_clock_from_the_interactions(harness):
    tasks = result(harness, "pickm:from_interactions")
    # never followed up (1, and 5: a note is not a follow-up), 6 (its email is dated tomorrow: not one
    # yet), then Sep 29 (2), then due today (3); BD last. 4 emailed on Oct 1: not due.
    assert ids_of(tasks) == [1, 5, 6, 2, 3, 7]
    assert [t["kind"] for t in tasks] == ["maintenance"] * 5 + ["new"]
    assert [t["reasons"][0] for t in tasks[:5]] == ["No follow-up logged yet"] * 3 + [
        "Follow-up was due Tue, Sep 29", "Follow-up due today"]


def test_pick_next_heads_with_the_due_maintenance_contacts(harness):
    tasks = result(harness, "pickm:next_heads_with_maintenance")
    assert [t["kind"] for t in tasks[:2]] == ["maintenance", "maintenance"]
    assert len(tasks) == 10
    assert "maintenance" not in [t["kind"] for t in tasks[2:]]
    bd = [t["score"] for t in tasks[2:]]
    assert bd == sorted(bd, reverse=True)


def test_pick_next_skips_anyone_already_on_this_weeks_list(harness):
    ids = ids_of(result(harness, "pickm:next_skips_what_is_on_the_list"))
    assert not {100, 2, 300} & set(ids)
    assert ids[:2] == [101, 102], "the remaining due maintenance contacts still lead"


def test_pick_next_takes_the_top_n_even_when_all_are_maintenance(harness):
    tasks = result(harness, "pickm:next_more_maintenance_than_n")
    assert [t["kind"] for t in tasks] == ["maintenance"] * 3


def test_pick_next_derives_the_due_clock_from_the_interactions(harness):
    assert ids_of(result(harness, "pickm:next_from_interactions")) == [1, 5, 6, 2, 3, 7]
