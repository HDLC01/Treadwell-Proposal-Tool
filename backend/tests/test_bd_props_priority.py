"""Generated (property) coverage of backend/bd/priority.py, the contact priority score.

tests/test_priority.py pins a hand-built table, 300 random contacts against bd-core.js and the
database rows. This file adds what a table cannot say: invariants that must hold for EVERY
contact, found by hypothesis over a generator shaped like the real field vocabulary.

  * purity: scoring twice gives the same answer, never touches its inputs, and does not care
    about the order of the keys of the contact or of the facts.
  * shape and bounds: the score is a whole number from 0 to 148 (40 + 50 + 15 + 20 + 15 + 8, the
    most the factors can add up to); every reason is a non-empty string; at most one per factor.
  * every reason text appears exactly when its condition holds, both directions: "Never
    contacted" / "Never reached after N tries", "Last live talk", "Promised a call by" / "Next
    step due", "Recent quote activity", "Key account", "N tries since the last live talk",
    "Needs confirming".
  * exclusion: archived, then on the list, then tried in the last 3 days, then a maintenance contact
    that is not due; depends on nothing else;
    never changes the score; a fact laid over a field replaces it.
  * monotone: more importance never lowers the score (+10 for 2, +20 for 3 or more); an older
    last live talk never lowers it; a higher frequency never lowers the cadence; more tries since
    the last live talk add 5 each and stop adding after 3.
  * the factors are additive: each factor's points do not depend on the other factors.
  * the reasons come most points first, ties in the rule order.
  * the helpers: Central-day arithmetic (days_between, biz_date_of), js_round, ago_text,
    short_date, plural, freq_of, reason_text; database types (date, aware datetime) score like
    the text they stand for.
  * ONE batched cross-check against BDCore.scoreContact through node on boundary-shaped cases.

All data is fictional and every date is an explicit argument: nothing here reads a clock.
"""
import copy
import datetime as dt
import json
import pathlib
import re
import tempfile

import pytest
from hypothesis import HealthCheck, Phase, example, given, settings
from hypothesis import strategies as st

from bd import bizdate
from bd import priority
from _node import last_json_line, run_node
from test_bd_core_js import CORE, HARNESS, contact

CONFIRM = "Needs confirming: still the right person?"
MAX_SCORE = 40 + 50 + 15 + 20 + 15 + 8
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# the order points are added in (it breaks ties between reasons of equal points)
CATEGORIES = ["main", "date", "quote", "key", "tries", "confirm"]

FAST = settings(max_examples=50)                # the scenario tests: 50 examples each keep the file fast
DATES = st.dates(min_value=dt.date(2024, 1, 1), max_value=dt.date(2029, 12, 31))
LATER_DATES = st.dates(min_value=dt.date(2025, 1, 1), max_value=dt.date(2029, 12, 31))


def sd(d):
    """A date as the reasons print it: "Fri, Nov 6" (own tables, not the module's)."""
    return "%s, %s %d" % (WEEKDAYS[d.weekday()], MONTHS[d.month - 1], d.day)


# ── the generator: a scenario is the facts of one contact in plain numbers ──────────────────────
# live_ago, quote_ago, attempt_ago: days before today (None = never); promised, next_step: days
# from today (negative = past; None = none). build() turns it into (contact, facts, today).
BASE = {"today": dt.date(2026, 11, 4), "live_ago": None, "category": "bd", "freq": 4, "attempts": 0, "importance": None,
        "confirmed": True, "promised": None, "next_step": None, "quote_ago": None, "attempt_ago": None,
        "archived": False, "open_task": None, "quote_as_fact": False,
        "maint_due": True}       # only read for a maintenance contact: not due = left off the list


def spec(**kw):
    s = dict(BASE)
    s.update(kw)
    return s


def iso(today, off):
    return (today + dt.timedelta(days=off)).isoformat()


def build(s):
    t = s["today"]
    c = contact(1, s["freq"], category=s["category"], confirmed=s["confirmed"], importance=s["importance"],
                attempts_since_live=s["attempts"])
    if s["live_ago"] is not None:
        c["last_live_at"] = iso(t, -s["live_ago"])
    if s["attempt_ago"] is not None:
        c["last_attempt_at"] = iso(t, -s["attempt_ago"])
    if s["promised"] is not None:
        c["promised_date"] = iso(t, s["promised"])
    if s["next_step"] is not None:
        c["next_step_date"] = iso(t, s["next_step"])
    if s["archived"]:
        c["archived_at"] = iso(t, -5)
    if s["maint_due"] is not None:
        c["maintenance_due"] = s["maint_due"]
    facts = {}
    if s["open_task"] is not None:
        facts["has_open_task"] = s["open_task"]
    if s["quote_ago"] is not None:
        (facts if s["quote_as_fact"] else c)["last_quote_date"] = iso(t, -s["quote_ago"])
    return c, facts, t.isoformat()


def run(s):
    return priority.score(*build(s))


@st.composite
def scenarios(draw):
    t = draw(DATES)
    live_ago = draw(st.one_of(st.none(), st.integers(-3, 70), st.integers(70, 3000)))

    def day_offset():
        kind = draw(st.sampled_from(["none", "none", "near", "live"]))
        if kind == "none":
            return None
        if kind == "near" or live_ago is None:
            return draw(st.integers(-20, 12))
        # on, just before or just after the last live talk: the met-by-that-talk boundary
        return -live_ago + draw(st.sampled_from([-1, 0, 1, 2]))

    return spec(
        today=t, live_ago=live_ago,
        category=draw(st.sampled_from(["bd", "bd", "maintenance"])),
        freq=draw(st.sampled_from([None, 0, -1, 1, 2, 3, 4, 4, 6, 12, 52])),
        attempts=draw(st.one_of(st.none(), st.integers(0, 6))),
        importance=draw(st.sampled_from([None, 0, 1, 2, 3, 4])),
        confirmed=draw(st.sampled_from([True, False, None])),
        promised=day_offset(), next_step=day_offset(),
        quote_ago=draw(st.one_of(st.none(), st.integers(-5, 45))),
        attempt_ago=draw(st.one_of(st.none(), st.integers(0, 10))),
        archived=draw(st.booleans()),
        open_task=draw(st.sampled_from([None, False, True])),
        quote_as_fact=draw(st.booleans()),
        maint_due=draw(st.sampled_from([True, True, False, None])))       # None = the field is missing


# ── purity ────────────────────────────────────────────────────────────────────────────────────────
@FAST
@given(scenarios())
def test_scoring_is_deterministic_and_leaves_its_inputs_alone(s):
    c, facts, today = build(s)
    c0, f0 = copy.deepcopy(c), copy.deepcopy(facts)
    first = priority.score(c, facts, today)
    assert c == c0 and facts == f0
    first_copy = copy.deepcopy(first)
    first["reasons"].append("scribble")          # a caller scribbling on an answer...
    first["score"] = -1
    second = priority.score(c, facts, today)      # ...never reaches the next one
    assert second == first_copy
    assert priority.score(c, facts, today) == second


@FAST
@given(scenarios())
def test_key_order_does_not_matter(s):
    c, facts, today = build(s)
    rc = dict(reversed(list(c.items())))
    rf = dict(reversed(list(facts.items())))
    assert priority.score(rc, rf, today) == priority.score(c, facts, today)


@FAST
@given(scenarios())
def test_today_as_a_date_or_as_text_is_the_same_day(s):
    c, facts, today = build(s)
    assert priority.score(c, facts, s["today"]) == priority.score(c, facts, today)
    assert priority.score(c, facts, today + "T23:59:59-06:00") == priority.score(c, facts, today)


def test_today_is_required_and_a_blank_contact_is_never_contacted():
    with pytest.raises(ValueError):
        priority.score({}, {}, None)
    assert priority.score(None, None, "2026-11-04") == {
        "score": 40, "reasons": ["Never contacted"], "excluded": False, "exclude_reason": None}
    assert priority.score({}, {}, dt.date(2026, 11, 4))["score"] == 40


# ── shape and bounds ──────────────────────────────────────────────────────────────────────────────
@FAST
@given(scenarios())
def test_the_score_is_a_bounded_whole_number_with_well_formed_reasons(s):
    r = run(s)
    assert set(r) == {"score", "reasons", "excluded", "exclude_reason"}
    assert type(r["score"]) is int
    assert 0 <= r["score"] <= MAX_SCORE
    assert isinstance(r["reasons"], list) and len(r["reasons"]) <= len(CATEGORIES)
    assert all(isinstance(x, str) and x.strip() for x in r["reasons"])
    assert len(set(r["reasons"])) == len(r["reasons"])
    assert isinstance(r["excluded"], bool)
    assert (r["exclude_reason"] is None) == (not r["excluded"])
    assert r["exclude_reason"] in (None, "archived", "already in this week's list", "tried in the last 3 days",
                                   "maintenance, not due yet")


def test_the_largest_score_is_reached_and_not_passed():
    everything = {"importance": 3, "confirmed": False, "promised": -1, "quote_ago": 0, "attempts": 9}
    # never reached: 40 + 50 (promise past due) + 15 (quote today) + 20 (key) + 15 (3 tries) + 8
    assert run(spec(**everything))["score"] == MAX_SCORE
    # a very old live talk: the cadence is capped at the same 40
    assert run(spec(live_ago=5000, **everything))["score"] == MAX_SCORE


# ── every reason appears exactly when its condition holds ─────────────────────────────────────────
def _interval_and_need(s):
    maint = s["category"] == "maintenance"
    f = s["freq"] if (s["freq"] is not None and s["freq"] > 0) else (3 if maint else 4)
    return (120 if maint else 365 / f), (3 if maint else f)


@FAST
@given(scenarios())
@example(spec(live_ago=10, promised=-10))                   # met by the talk: same day
@example(spec(live_ago=10, promised=-9, next_step=-10))
@example(spec(live_ago=0, next_step=0))
@example(spec(promised=7, next_step=7))
@example(spec(promised=8))
@example(spec(quote_ago=30))
@example(spec(quote_ago=31))
@example(spec(quote_ago=0))
@example(spec(quote_ago=-1))
@example(spec(importance=2))
@example(spec(importance=3, confirmed=None, attempts=1, live_ago=3))
def test_every_reason_appears_exactly_when_its_condition_holds(s):
    reasons = priority.score(*build(s))["reasons"]
    t, live = s["today"], s["live_ago"]
    n = s["attempts"] or 0
    imp = s["importance"] or 1

    never = [x for x in reasons if x.startswith("Never")]
    if live is None:
        want = ("Never reached after %d %s" % (n, "try" if n == 1 else "tries")) if n > 0 else "Never contacted"
        assert never == [want]
    else:
        assert never == []

    tries = [x for x in reasons if x.endswith("since the last live talk")]
    if live is not None and n > 0:
        assert tries == ["%d %s since the last live talk" % (n, "try" if n == 1 else "tries")]
    else:
        assert tries == []

    assert ("Key account" in reasons) == (imp >= 3)
    assert (CONFIRM in reasons) == (s["confirmed"] is False)

    quote = [x for x in reasons if x.startswith("Recent quote activity")]
    if s["quote_ago"] is not None and 0 <= s["quote_ago"] <= 30:
        assert quote == ["Recent quote activity (%s)" % sd(t - dt.timedelta(days=s["quote_ago"]))]
    else:
        assert quote == []

    cadence = [x for x in reasons if x.startswith("Last live talk")]
    interval, need = _interval_and_need(s)
    if live is None or live <= 0:
        assert cadence == []
    else:
        raw = 30 * live / interval
        if raw >= 1:                                         # rounds to at least 1 whatever the rounding
            assert len(cadence) == 1 and cadence[0].endswith("; needs %d a year" % need)
        elif raw < 0.4:
            assert cadence == []

    promised, nxt = s["promised"], s["next_step"]
    eligible = [d for d in (promised, nxt) if d is not None and (live is None or d > -live)]
    dated = [x for x in reasons if x.startswith(("Promised a call by", "Next step due"))]
    if eligible and min(eligible) <= 7:
        e = min(eligible)
        lead = "Promised a call by " if promised == e else "Next step due "
        assert dated == [lead + sd(t + dt.timedelta(days=e))]
    else:
        assert dated == []

    expected = (len(never) + len(tries) + len(quote) + len(cadence) + len(dated)
                + (imp >= 3) + (s["confirmed"] is False))
    assert len(reasons) == expected                           # nothing else is ever said


# ── exclusion ─────────────────────────────────────────────────────────────────────────────────────
@FAST
@given(scenarios())
def test_exclusion_follows_archived_then_on_the_list_then_tried_lately_then_not_due(s):
    r = run(s)
    if s["archived"]:
        want = (True, "archived")
    elif s["open_task"]:
        want = (True, "already in this week's list")
    elif s["attempt_ago"] is not None and s["attempt_ago"] < 3:
        want = (True, "tried in the last 3 days")
    elif s["category"] == "maintenance" and not s["maint_due"]:
        want = (True, "maintenance, not due yet")
    else:
        want = (False, None)
    assert (r["excluded"], r["exclude_reason"]) == want


@FAST
@given(scenarios(), scenarios())
def test_exclusion_depends_on_nothing_but_its_four_fields(s1, s2):
    # (archived, on the list, last attempt, and for a maintenance contact: due. The category stays.)
    swapped = {k: s2[k] for k in ("live_ago", "freq", "attempts", "importance", "confirmed",
                                  "promised", "next_step", "quote_ago", "quote_as_fact")}
    a, b = run(s1), run({**s1, **swapped})
    assert (a["excluded"], a["exclude_reason"]) == (b["excluded"], b["exclude_reason"])


@FAST
@given(scenarios())
def test_an_excluded_contact_keeps_its_score_and_reasons(s):
    clean = run({**s, "archived": False, "open_task": None, "attempt_ago": None, "maint_due": True})
    got = run(s)
    assert got["score"] == clean["score"] and got["reasons"] == clean["reasons"]
    c, facts, today = build(s)
    c.update(name="Someone Else", id=999, touches_this_year=77, unknown_field="x")
    again = priority.score(c, facts, today)
    assert again["score"] == got["score"] and again["reasons"] == got["reasons"]


@FAST
@given(scenarios(), st.booleans())
def test_only_a_maintenance_contact_waits_for_its_due_date(s, due):
    """A BD contact never reads maintenance_due; a maintenance one is left off the list exactly
    while it is not due, and a fact laid over the field replaces it."""
    clear = {**s, "archived": False, "open_task": None, "attempt_ago": None}
    c, facts, today = build({**clear, "maint_due": due})
    got = priority.score(c, facts, today)
    maint = s["category"] == "maintenance"
    assert got["excluded"] == (maint and not due)
    assert got["exclude_reason"] == ("maintenance, not due yet" if maint and not due else None)
    over = priority.score(c, {**facts, "maintenance_due": not due}, today)
    assert over["excluded"] == (maint and due)


@given(LATER_DATES, st.booleans(), st.integers(0, 6))
def test_the_cooling_off_is_exactly_three_central_days(today, late_in_day, ago):
    """Tried 0-2 days ago: out; 3 or more: in. Written as a UTC instant at the first or the last
    second of the Central day, so the Central day is not always the UTC day."""
    day = today - dt.timedelta(days=ago)
    hour = dt.time(23, 59, 59) if late_in_day else dt.time(0, 0, 0)
    instant = dt.datetime.combine(day, hour, tzinfo=bizdate.BIZ_TZ).astimezone(bizdate.UTC)
    c = contact(1, last_attempt_at=instant.strftime("%Y-%m-%dT%H:%M:%SZ"))
    r = priority.score(c, {}, today)
    assert r["excluded"] == (ago < 3)
    assert r["exclude_reason"] == ("tried in the last 3 days" if ago < 3 else None)


@FAST
@given(scenarios(), st.booleans())
def test_a_fact_laid_over_a_field_replaces_it(s, on_list):
    c, _, today = build(s)
    c.update(has_open_task=on_list, archived_at=None, last_attempt_at=None, maintenance_due=True)
    assert priority.score(c, {}, today)["excluded"] == on_list
    assert priority.score(c, {"has_open_task": not on_list}, today)["excluded"] == (not on_list)
    # a quote date sent as a fact beats the column
    c["last_quote_date"] = iso(s["today"], -200)
    old = priority.score(c, {}, today)["score"]
    new = priority.score(c, {"last_quote_date": iso(s["today"], -1)}, today)["score"]
    assert new == old + 15


# ── monotone ──────────────────────────────────────────────────────────────────────────────────────
IMPORTANCES = [None, -2, 0, 1, 2, 3, 4, 5, 6, "2", "3"]


def _effective(imp):
    e = int(imp) if isinstance(imp, str) else (imp or 1)
    return e if e != 0 else 1


@FAST
@given(scenarios())
def test_more_importance_never_lowers_the_score(s):
    base = run({**s, "importance": 1})["score"]
    seen = []
    for imp in IMPORTANCES:
        r = run({**s, "importance": imp})
        e = _effective(imp)
        assert r["score"] - base == (0 if e <= 1 else 10 if e == 2 else 20), imp
        assert ("Key account" in r["reasons"]) == (e >= 3), imp
        seen.append((e, r["score"]))
    seen.sort()
    scores = [x[1] for x in seen]
    assert scores == sorted(scores)


@FAST
@given(scenarios(), st.integers(-3, 3000), st.integers(-3, 3000))
def test_an_older_last_live_talk_never_lowers_the_score(s, a, b):
    young, old = sorted((a, b))
    assert run({**s, "live_ago": old})["score"] >= run({**s, "live_ago": young})["score"]


@given(st.sampled_from([1, 2, 3, 4, 6, 12, 52]), st.booleans(), st.integers(0, 3000), st.integers(0, 3000),
       LATER_DATES)
def test_the_cadence_is_zero_proportional_capped_and_monotone(freq, maint, a, b, today):
    interval = 120 if maint else 365 / freq

    def cad(d):
        return run(spec(today=today, freq=freq, category="maintenance" if maint else "bd", live_ago=d))

    lo, hi = sorted((a, b))
    assert cad(lo)["score"] <= cad(hi)["score"]
    r = cad(a)
    assert 0 <= r["score"] <= 40
    assert bool(r["reasons"]) == (r["score"] > 0)
    if r["score"] < 40:
        assert abs(r["score"] - 30 * a / interval) <= 0.5 + 1e-9
    else:
        assert 30 * a / interval >= 39.5 - 1e-9
    if a >= interval * 40 / 30 + 1:
        assert r["score"] == 40                                # saturated
    assert cad(0) == {"score": 0, "reasons": [], "excluded": False, "exclude_reason": None}
    assert cad(-2)["score"] == 0                               # a live talk dated in the future


@given(st.integers(1, 60), st.integers(1, 60), st.integers(0, 1500))
def test_a_higher_frequency_never_lowers_the_cadence(f1, f2, d):
    lo, hi = sorted((f1, f2))
    assert run(spec(freq=lo, live_ago=d))["score"] <= run(spec(freq=hi, live_ago=d))["score"]


@given(st.integers(-5, 60), st.integers(1, 1500))
def test_maintenance_ignores_the_frequency_and_says_three_a_year(freq, d):
    a = run(spec(category="maintenance", freq=freq, live_ago=d))
    b = run(spec(category="maintenance", freq=4, live_ago=d))
    assert a == b
    assert all(r.endswith("needs 3 a year") for r in a["reasons"])


@pytest.mark.parametrize("bad", [None, 0, -3, "abc", ""])
def test_a_missing_or_bad_frequency_counts_as_the_default_four(bad):
    c = contact(1, bad, last_live_at="2026-09-01")
    good = contact(1, 4, last_live_at="2026-09-01")
    got = priority.score(c, {}, "2026-11-04")
    assert got == priority.score(good, {}, "2026-11-04")
    assert got["reasons"] == ["Last live talk 2 months ago; needs 4 a year"]


@given(st.booleans(), st.integers(1, 800), st.integers(0, 12), st.integers(0, 12))
def test_tries_since_live_add_five_each_and_stop_after_three(live, d, n1, n2):
    def sc(n):
        return run(spec(live_ago=d if live else None, attempts=n))["score"]

    zero = sc(0)
    assert sc(n1) - zero == 5 * min(3, n1)
    lo, hi = sorted((n1, n2))
    assert sc(lo) <= sc(hi) <= sc(lo) + 15
    assert sc(3) == sc(3 + n1)
    assert sc(None) == zero


# ── the factors are separate ──────────────────────────────────────────────────────────────────────
EXTRAS = [("importance",), ("confirmed",), ("quote_ago",), ("promised", "next_step")]


@FAST
@given(scenarios())
def test_the_factors_are_additive(s):
    stripped = {**s, "importance": None, "confirmed": True, "quote_ago": None, "promised": None, "next_step": None}
    base = run(stripped)["score"]
    total = 0
    for keys in EXTRAS:
        delta = run({**stripped, **{k: s[k] for k in keys}})["score"] - base
        assert delta >= 0
        total += delta
    assert run(s)["score"] == base + total
    # and the tries are one more separate piece of the stripped contact
    n = s["attempts"] or 0
    assert base - run({**stripped, "attempts": 0})["score"] == 5 * min(3, n)


def _category(reason):
    if reason.startswith(("Never", "Last live talk")):
        return "main"
    if reason.startswith(("Promised a call by", "Next step due")):
        return "date"
    if reason.startswith("Recent quote activity"):
        return "quote"
    if reason == "Key account":
        return "key"
    if reason.endswith("since the last live talk"):
        return "tries"
    assert reason == CONFIRM, reason
    return "confirm"


@FAST
@given(scenarios())
@example(spec(category="bd", freq=12, importance=3, live_ago=20))                   # cadence 20 = key account 20
@example(spec(category="bd", freq=12, importance=3, live_ago=20, confirmed=False, quote_ago=3))
@example(spec(live_ago=40, attempts=3, confirmed=False, importance=3))               # 40 > 20 > 15 > 8
@example(spec(promised=-1, quote_ago=1, importance=3, attempts=3, live_ago=None))
@example(spec(quote_ago=1, attempts=3, live_ago=60, freq=1, importance=3))           # cadence 5 vs tries 15
def test_reasons_come_most_points_first_ties_in_rule_order(s):
    stripped = {**s, "importance": None, "confirmed": True, "quote_ago": None, "promised": None,
                "next_step": None, "attempts": 0}
    main = run(stripped)["score"]

    def gain(**kw):
        return run({**stripped, **kw})["score"] - main

    pts = {"main": main,
           "date": gain(promised=s["promised"], next_step=s["next_step"]),
           "quote": gain(quote_ago=s["quote_ago"]),
           "key": gain(importance=s["importance"]),
           "tries": gain(attempts=s["attempts"]),
           "confirm": gain(confirmed=s["confirmed"])}
    got = [_category(r) for r in run(s)["reasons"]]
    assert len(set(got)) == len(got)
    assert got == sorted(got, key=lambda k: (-pts[k], CATEGORIES.index(k)))


# ── database types ───────────────────────────────────────────────────────────────────────────────
@FAST
@given(scenarios())
def test_dates_and_aware_datetimes_score_like_the_text_they_stand_for(s):
    t = s["today"]
    c, facts, today = build(s)
    as_text, as_objects = copy.deepcopy(c), copy.deepcopy(c)
    for field, ago in (("last_live_at", s["live_ago"]), ("last_attempt_at", s["attempt_ago"])):
        if ago is None:
            continue
        moment = dt.datetime.combine(t - dt.timedelta(days=ago), dt.time(12, 0), tzinfo=bizdate.BIZ_TZ)
        as_text[field] = bizdate.to_iso_central(moment)
        as_objects[field] = moment                            # what the database driver hands over
    for field in ("promised_date", "next_step_date", "last_quote_date", "archived_at"):
        if as_objects.get(field):
            as_objects[field] = dt.date.fromisoformat(as_objects[field])
    expected = priority.score(as_text, facts, today)
    assert priority.score(as_objects, facts, t) == expected
    assert priority.score(as_objects, facts, today) == expected


# ── the day arithmetic and the phrase helpers ────────────────────────────────────────────────────
@given(DATES, DATES, DATES)
def test_days_between_is_signed_and_additive(a, b, c):
    f = priority.days_between
    assert f(a.isoformat(), b.isoformat()) == (b - a).days
    assert f(a.isoformat(), b.isoformat()) == -f(b.isoformat(), a.isoformat())
    assert f(a.isoformat(), a.isoformat()) == 0
    assert f(a.isoformat(), c.isoformat()) == f(a.isoformat(), b.isoformat()) + f(b.isoformat(), c.isoformat())


@given(st.integers(0, 2 * 365 * 86400))
def test_a_moment_belongs_to_its_central_day_however_it_is_written(seconds):
    """Across the DST changes of 2026 and 2027: UTC text, Central text and a datetime object give
    the one Central calendar day."""
    instant = dt.datetime(2026, 1, 1, tzinfo=bizdate.UTC) + dt.timedelta(seconds=seconds)
    day = instant.astimezone(bizdate.BIZ_TZ).date()
    utc_text = instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    central_text = bizdate.to_iso_central(instant)
    assert priority.biz_date_of(utc_text) == day.isoformat()
    assert priority.biz_date_of(central_text) == day.isoformat() == central_text[:10]
    assert priority.biz_date_of(instant) == day.isoformat()
    today = day + dt.timedelta(days=9)
    assert priority.days_between(utc_text, today.isoformat()) == 9
    assert priority.days_between(instant, today) == 9


@pytest.mark.parametrize("blank", [None, "", 0, False])
def test_biz_date_of_nothing_is_blank(blank):
    assert priority.biz_date_of(blank) == ""
    assert priority.days_between(blank, "2026-11-04") is None


@given(st.floats(min_value=-1e6, max_value=1e6, allow_nan=False), st.integers(-10**6, 10**6))
def test_js_round_is_math_round(x, n):
    r = priority.js_round(x)
    assert type(r) is int
    assert abs(r - x) <= 0.5
    assert priority.js_round(n) == n
    assert priority.js_round(n + 0.5) == n + 1             # halves go up, also below zero
    assert priority.js_round(n - 0.5) == n
    assert r <= priority.js_round(x + 1e-3)


@given(st.integers(-5, 400))
def test_ago_text_changes_unit_only_forward_and_says_one_correctly(days):
    text = priority.ago_text(days)
    if days <= 0:
        assert text == "today"
    elif days == 1:
        assert text == "yesterday"
    else:
        m = re.fullmatch(r"(\d+) (day|week|month)s? ago", text)
        assert m, text
        number, unit = int(m.group(1)), m.group(2)
        assert text == "%d %s%s ago" % (number, unit, "" if number == 1 else "s")
        assert unit == ("day" if days < 14 else "week" if days < 45 else "month")
        assert number == days // {"day": 1, "week": 7, "month": 30}[unit]


@pytest.mark.parametrize("days, text", [
    (0, "today"), (-3, "today"), (1, "yesterday"), (2, "2 days ago"), (13, "13 days ago"),
    (14, "2 weeks ago"), (44, "6 weeks ago"), (45, "1 month ago"), (59, "1 month ago"), (60, "2 months ago"),
])
def test_ago_text_boundaries(days, text):
    assert priority.ago_text(days) == text


@given(DATES)
def test_short_date_reads_back_to_its_date(d):
    text = priority.short_date(d.isoformat())
    assert text == sd(d)
    assert priority.short_date(d.isoformat() + "T10:00:00-06:00") == text
    assert re.fullmatch(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun), (%s) \d{1,2}" % "|".join(MONTHS), text)


@given(st.integers(0, 50), st.sampled_from([None, "tries"]))
def test_plural_counts(n, many):
    text = priority.plural(n, "try", many)
    assert text.startswith("%d " % n)
    assert text.endswith("try" if n == 1 else (many or "trys"))


@given(st.one_of(st.none(), st.integers(-5, 400), st.floats(-5, 400, allow_nan=False),
                 st.sampled_from(["4", "abc", "", "  7 ", "1_0", "nan", "12"])),
       st.sampled_from(["bd", "maintenance", None]))
def test_frequency_helpers_never_give_zero_and_maintenance_is_three_touches(raw, category):
    c = {"frequency_per_year": raw, "category": category}
    assert priority.freq_of(c) > 0
    assert priority.touches_needed(c) == (3 if category == "maintenance" else priority.freq_of(c))
    assert priority.freq_of(None) == 4 and priority.touches_needed({}) == 4


# ── reason_text ──────────────────────────────────────────────────────────────────────────────────
WORDS = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp")), min_size=1, max_size=30)


@given(st.lists(WORDS, max_size=6))
def test_reason_text_is_the_top_two_each_ending_as_a_sentence(reasons):
    before = list(reasons)
    text = priority.reason_text(reasons)
    assert reasons == before
    if len(reasons) >= 2:
        assert text == priority.reason_text(reasons + ["more words here"])        # the third is never shown
    if not reasons:
        assert text == ""
        return
    sentences = [r if r[-1] in ".?!" else r + "." for r in reasons[:2]]
    assert text == " ".join(sentences)
    assert text[-1] in ".?!"
    assert priority.reason_text([text]) == text                       # a finished sentence is left alone


# ── ONE batched node cross-check on boundary-shaped cases ────────────────────────────────────────
MOMENT_FORMATS = ["date", "central_start", "central_end", "central_noon", "utc_start", "utc_before_start"]


def _moment(day, fmt):
    if fmt == "date":
        return day.isoformat()
    hour = dt.time(23, 59, 59) if fmt == "central_end" else dt.time(12, 0) if fmt == "central_noon" else dt.time(0, 0)
    at = dt.datetime.combine(day, hour, tzinfo=bizdate.BIZ_TZ)
    if fmt.startswith("utc"):
        if fmt == "utc_before_start":
            at -= dt.timedelta(seconds=1)                     # still the day before, in Central
        return at.astimezone(bizdate.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return bizdate.to_iso_central(at)


@st.composite
def edge_cases(draw):
    s = draw(scenarios())
    c, facts, today = build(s)
    for field, ago in (("last_live_at", s["live_ago"]), ("last_attempt_at", s["attempt_ago"])):
        if ago is not None:
            c[field] = _moment(s["today"] - dt.timedelta(days=ago), draw(st.sampled_from(MOMENT_FORMATS)))
    # blanks and text numbers where the app could send them
    for field in ("last_live_at", "last_attempt_at", "promised_date", "next_step_date", "last_quote_date",
                  "importance", "attempts_since_live"):
        if c.get(field) is None and draw(st.booleans()):
            c[field] = ""
    c["frequency_per_year"] = draw(st.one_of(st.just(c["frequency_per_year"]),
                                             st.sampled_from(["4", "abc", 2.5, "", "12"])))
    if draw(st.booleans()) and c.get("importance") not in (None, ""):
        c["importance"] = str(c["importance"])
    return {"c": c, "facts": facts, "today": today}


def _batch(cases):
    """One node run for a whole batch: {id: BDCore.scoreContact(...)}."""
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "cases.json"
        path.write_text(json.dumps([{"id": "n%d" % i, "fn": "scoreContact", "args": [k["c"], k["facts"], k["today"]]}
                                    for i, k in enumerate(cases)]), encoding="utf-8")
        proc = run_node(HARNESS, CORE, path)
    assert proc.returncode == 0, "the bd-core harness failed:\n" + proc.stderr
    out = last_json_line(proc.stdout)
    assert out["vm_disagrees"] == []
    return out["results"]


@pytest.mark.node
@settings(max_examples=5, deadline=None, suppress_health_check=list(HealthCheck),
          phases=(Phase.explicit, Phase.generate))
@given(st.lists(edge_cases(), min_size=50, max_size=150))
def test_boundary_cases_score_exactly_as_bd_core_js(cases):
    results = _batch(cases)
    wrong = []
    for i, k in enumerate(cases):
        want = results["n%d" % i]
        got = priority.score(k["c"], k["facts"], k["today"])
        if json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
            wrong.append((k, want, got))
    assert not wrong, "%d of %d differ; first: %r" % (len(wrong), len(cases), wrong[:2])


# ── pinned by mutation testing: boundaries and helper rules the generators above cannot reach ────
TODAY = "2026-11-04"


@pytest.mark.parametrize("importance, points", [
    (None, 0), (0, 0), (1, 0), (1.5, 0), (2, 10), (2.0, 10), ("2", 10), (2.5, 0), (2.99, 0),
    (3, 20), (3.0, 20), ("3", 20), (3.5, 20), (4, 20),
])
def test_importance_points_are_exact_and_only_whole_two_gets_ten(importance, points):
    """Only importance 2 adds ten and only 3 or more adds twenty: nothing in between adds anything."""
    r = priority.score({"importance": importance}, {}, TODAY)
    assert r["score"] == 40 + points
    assert r["reasons"] == (["Never contacted", "Key account"] if points == 20 else ["Never contacted"])


@pytest.mark.parametrize("field", [
    "last_live_at", "archived_at", "has_open_task", "last_attempt_at", "last_quote_date", "promised_date",
    "next_step_date",
])
def test_a_nan_field_is_as_good_as_blank(field):
    """JavaScript's NaN is falsy: a NaN field behaves like a missing one, never like a date or a flag."""
    blank = priority.score({}, {}, TODAY)
    assert priority.score({field: float("nan")}, {}, TODAY) == blank
    assert priority.score({}, {field: float("nan")}, TODAY) == blank


@pytest.mark.parametrize("raw, want", [
    (None, 0), ("", 0), ("   ", 0), (True, 1), (False, 0), (7, 7), (2.5, 2.5), ("  7 ", 7), ("2.50", 2.5),
    ("4.0", 4), ("Infinity", float("inf")), ("+Infinity", float("inf")), ("-Infinity", float("-inf")),
    ("1_2", None), ("inf", None), ("-inf", None), ("infinity", None), ("nan", None), ("NaN", None),
    ("abc", None), ("12abc", None), (float("nan"), None),
])
def test_js_number_reads_values_as_javascript_Number_does(raw, want):
    got = priority._js_number(raw)
    assert got == want and (got is None) == (want is None)


@given(st.integers(-5, 5), st.integers(-5, 5))
def test_or_falls_back_on_zero_and_nothing_only(v, default):
    assert priority._or(None, default) == default
    assert priority._or(0, default) == default
    assert priority._or(0.0, default) == default
    assert priority._or(v, default) == (v if v != 0 else default)


@pytest.mark.parametrize("n, text", [
    (4, "4"), (4.0, "4"), (2.5, "2.5"), (-3.0, "-3"), (1e20, "100000000000000000000"), (1e21, "1e+21"),
    (10**25, str(10**25)),
])
def test_js_str_prints_numbers_as_javascript_String_does(n, text):
    assert priority.js_str(n) == text


def test_a_huge_frequency_is_worded_as_javascript_would_print_it():
    for freq, said in ((1e20, "100000000000000000000"), (1e21, "1e+21")):
        r = priority.score({"last_live_at": "2026-10-25", "frequency_per_year": freq}, {}, TODAY)
        assert r["score"] == 40                                          # a talk every instant: the cap
        assert r["reasons"] == ["Last live talk 10 days ago; needs %s a year" % said]


@pytest.mark.parametrize("raw, said", [("1_2", 4), ("inf", 4), ("nan", 4), ("0x10", 4), ("12", 12), (" 12 ", 12),
                                        ("2.5", 2.5), ("-3", 4), ("0", 4), ("", 4), ("abc", 4)])
def test_a_frequency_text_javascript_cannot_read_falls_back_to_the_default(raw, said):
    r = priority.score({"last_live_at": "2026-10-25", "frequency_per_year": raw}, {}, TODAY)
    assert r["reasons"][0].endswith("; needs %s a year" % priority.js_str(said))


@pytest.mark.parametrize("stamp, day", [
    # a Central offset is read off the text, whatever the season (the same rule as bd-core.js)
    ("2026-07-04T23:30:00-06:00", "2026-07-04"),            # in July Central is -05:00; the text still wins
    ("2026-07-04T23:30:00.5-06:00", "2026-07-04"),          # fractional seconds take the same path
    ("2026-12-05T00:30:00-05:00", "2026-12-05"),            # in December Central is -06:00; the text wins
    ("2026-12-05T00:30:00.250-05:00", "2026-12-05"),
    # any other offset is converted to the real Central day
    ("2026-07-04T23:30:00-07:00", "2026-07-05"),
    ("2026-07-04T23:30:00-04:00", "2026-07-04"),
    ("2026-07-05T03:30:00Z", "2026-07-04"),
    ("2026-12-05T05:30:00Z", "2026-12-04"),
])
def test_biz_date_of_reads_a_central_offset_off_the_text_and_converts_anything_else(stamp, day):
    assert priority.biz_date_of(stamp) == day


def test_today_text_is_cut_to_its_first_ten_characters_not_converted():
    """`today` is already the Central date: a UTC-looking stamp is not shifted to the evening before."""
    c = {"last_live_at": "2026-10-25", "promised_date": "2026-11-05"}
    want = priority.score(c, {}, "2026-11-05")
    assert priority.score(c, {}, "2026-11-05T03:00:00Z") == want            # not "2026-11-04"
    assert priority.score(c, {}, "2026-11-05T03:00:00Z") != priority.score(c, {}, "2026-11-04")
    assert priority.score(c, {}, dt.date(2026, 11, 5)) == want


@pytest.mark.parametrize("ago, excluded", [(0, True), (1, True), (2, True), (3, False), (4, False)])
def test_exclusion_for_a_recent_attempt_is_exactly_under_three_days(ago, excluded):
    day = (dt.date(2026, 11, 4) - dt.timedelta(days=ago)).isoformat()
    r = priority.score({"last_attempt_at": day}, {}, TODAY)
    assert r["excluded"] is excluded
    assert r["exclude_reason"] == ("tried in the last 3 days" if excluded else None)


def test_exclusion_reasons_are_worded_and_ranked_archived_then_open_task_then_attempt():
    c = {"archived_at": "2026-10-01", "last_attempt_at": TODAY}
    assert priority.score(c, {"has_open_task": True}, TODAY)["exclude_reason"] == "archived"
    assert priority.score({"last_attempt_at": TODAY}, {"has_open_task": True}, TODAY)["exclude_reason"] == \
        "already in this week's list"
    assert priority.score({"last_attempt_at": TODAY}, {}, TODAY)["exclude_reason"] == "tried in the last 3 days"
    assert priority.score({"last_attempt_at": TODAY, "has_open_task": True}, {"has_open_task": 0}, TODAY)[
        "exclude_reason"] == "tried in the last 3 days"


@pytest.mark.parametrize("reasons, text", [
    (["Wow!"], "Wow!"), (["Really?"], "Really?"), (["Done."], "Done."), (["Plain"], "Plain."),
    (["A", "B!", "C"], "A. B!"), (["A?", "B", "C", "D"], "A? B."), ([], ""), (None, ""),
])
def test_reason_text_leaves_any_sentence_end_alone(reasons, text):
    assert priority.reason_text(reasons) == text


@pytest.mark.parametrize("junk", ["garbage", "not a date", "T"])
def test_a_date_field_nobody_can_read_adds_nothing_and_never_raises(junk):
    """JavaScript turns an unreadable date into NaN, and every comparison with NaN is false: the
    field simply earns no points, whichever date field it is."""
    base = priority.score({"importance": 3}, {}, TODAY)
    assert priority.score({"importance": 3, "promised_date": junk}, {}, TODAY) == base
    assert priority.score({"importance": 3, "next_step_date": junk}, {}, TODAY) == base
    assert priority.score({"importance": 3, "last_quote_date": junk}, {}, TODAY) == base
    assert priority.score({"importance": 3}, {"last_quote_date": junk}, TODAY) == base
    # an unreadable last live talk is a live talk (so not "never contacted") that earns no cadence
    r = priority.score({"importance": 3, "last_live_at": junk}, {}, TODAY)
    assert r["score"] == 20 and r["reasons"] == ["Key account"]
    # an unreadable attempt date never excludes
    assert priority.score({"last_attempt_at": junk}, {}, TODAY) == priority.score({}, {}, TODAY)
