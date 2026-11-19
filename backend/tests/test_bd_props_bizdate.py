"""bizdate.py: generated (property) coverage of the Central business-date maths.

tests/test_bizdate.py pins hand-picked examples. This file states the invariants those examples
are samples of, and checks them over generated dates (1990..2100) and instants:

  * weeks are Monday..Sunday and tile the calendar; years follow the Gregorian rule;
  * add_days / days_between are inverses; add_months keeps the day or clamps it;
  * parse_date accepts exactly YYYY-MM-DD; parse_ts needs an offset, "Z" or a (Central) naive time;
  * the Central UTC offset follows the real US DST rule (second Sunday of March, first Sunday of
    November, both at 02:00 local), so a day is 23, 24 or 25 hours long and the days tile in UTC.

The DST oracle below is written from the legal rule (nth Sunday, 02:00 local), NOT taken from
zoneinfo, so a module that drifted from the rule (a fixed -06:00, the pre-2007 April/October
rule, a wrong Sunday) fails here. The rule has been in force since 2007, so every DST assertion
draws its dates from 2007..2100.

Pure: no database, no node, no network, no clock. The BD_TODAY / BD_NOW overrides are set inside
`pytest.MonkeyPatch.context()` so they are always restored.
"""
from __future__ import annotations

import datetime as dt
import re

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from bd import bizdate
UTC = dt.UTC
H = dt.timedelta(hours=1)

DATES = st.dates(dt.date(1990, 1, 1), dt.date(2100, 12, 31))
MODERN = st.dates(dt.date(2007, 1, 1), dt.date(2100, 12, 31))
# naive datetimes (fold=0: the first of an ambiguous hour; fold=1 has its own test) whose UTC and
# Central dates both stay inside 2007..2100
NAIVE = st.datetimes(dt.datetime(2007, 1, 5), dt.datetime(2100, 12, 25)).map(lambda x: x.replace(fold=0))
SMALL_K = st.integers(-600, 600)
DAYS_N = st.integers(-20000, 20000)


# ── an independent DST oracle (the US rule since 2007) ────────────────────────────────────────
def nth_sunday(year, month, n):
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def spring_day(year):
    return nth_sunday(year, 3, 2)


def fall_day(year):
    return nth_sunday(year, 11, 1)


def central_offset_of_instant(utc_naive):
    """Central UTC offset at a (naive, UTC) instant: CDT from 02:00 CST (08:00 UTC) on the spring
    day to 02:00 CDT (07:00 UTC) on the fall day."""
    y = utc_naive.year
    start = dt.datetime.combine(spring_day(y), dt.time(8, 0))
    end = dt.datetime.combine(fall_day(y), dt.time(7, 0))
    return -5 * H if start <= utc_naive < end else -6 * H


def central_date_of_instant(utc_naive):
    return (utc_naive + central_offset_of_instant(utc_naive)).date()


def midnight_offset(d):
    """Offset at 00:00 Central on `d`: the spring day starts in CST (the jump is at 02:00), the
    fall day starts still in CDT (the jump back is at 02:00 CDT)."""
    return -5 * H if spring_day(d.year) < d <= fall_day(d.year) else -6 * H


def day_length(d):
    if d == spring_day(d.year):
        return 23 * H
    if d == fall_day(d.year):
        return 25 * H
    return 24 * H


def fmt_offset(delta):
    total = int(delta.total_seconds() // 60)
    sign = "-" if total < 0 else "+"
    return "%s%02d:%02d" % (sign, abs(total) // 60, abs(total) % 60)


def as_utc(naive):
    return naive.replace(tzinfo=UTC)


# ── weeks ─────────────────────────────────────────────────────────────────────────────────────
@given(DATES)
def test_week_start_is_the_monday_on_or_before_the_day(d):
    mon = bizdate.week_start(d)
    assert mon.weekday() == 0 and bizdate.is_monday(mon)
    assert mon <= d
    assert 0 <= (d - mon).days <= 6
    assert (d - mon).days == d.weekday()                       # not 6 - weekday (a Sunday-first week)
    assert bizdate.week_start(mon) == mon                      # idempotent
    assert bizdate.is_monday(d) == (mon == d)


@given(DATES)
def test_week_bounds_is_monday_to_sunday_and_contains_the_day(d):
    mon, sun = bizdate.week_bounds(d)
    assert (mon.weekday(), sun.weekday()) == (0, 6)
    assert (sun - mon).days == 6
    assert mon <= d <= sun
    assert mon == bizdate.week_start(d)


@given(st.dates(dt.date(1990, 1, 8), dt.date(2100, 12, 20)))
def test_weeks_tile_the_calendar_with_no_gap_or_overlap(d):
    mon, sun = bizdate.week_bounds(d)
    for k in range(7):                                          # all seven days share one week
        assert bizdate.week_bounds(mon + dt.timedelta(days=k)) == (mon, sun)
    nxt = bizdate.week_bounds(sun + dt.timedelta(days=1))       # the next week starts the day after
    assert nxt[0] == sun + dt.timedelta(days=1)
    assert nxt[0] - mon == dt.timedelta(days=7)
    prev = bizdate.week_bounds(mon - dt.timedelta(days=1))      # the previous one ends the day before
    assert prev[1] == mon - dt.timedelta(days=1)
    assert mon - prev[0] == dt.timedelta(days=7)


@given(NAIVE)
def test_the_week_of_an_instant_is_the_week_of_its_central_date(naive):
    t = as_utc(naive)
    central = central_date_of_instant(naive)
    assert bizdate.biz_date(t) == central
    assert bizdate.iso_date(t) == central.isoformat()
    assert bizdate.week_start(t) == bizdate.week_start(central)
    assert bizdate.week_bounds(t) == bizdate.week_bounds(central)
    assert bizdate.day_of_year(t) == central.timetuple().tm_yday
    assert bizdate.year_bounds(t)[0].year == central.year      # not the UTC year


# ── days and months ───────────────────────────────────────────────────────────────────────────
@given(DATES, DAYS_N)
def test_add_days_and_days_between_are_inverses(d, n):
    assume(dt.date.min < d + dt.timedelta(days=n) < dt.date.max)
    e = bizdate.add_days(d, n)
    assert (e - d).days == n
    assert bizdate.days_between(d, e) == n
    assert bizdate.days_between(e, d) == -n
    assert bizdate.add_days(e, -n) == d
    assert bizdate.add_days(d.isoformat(), n) == e             # an ISO string means the same date
    assert bizdate.add_days(d, 0) == d


@given(DATES, DATES)
def test_days_between_is_the_signed_difference_and_chains(a, b):
    assert bizdate.days_between(a, b) == (b - a).days
    assert bizdate.days_between(a, b) == -bizdate.days_between(b, a)
    assert bizdate.days_between(a, a) == 0
    c = dt.date(2050, 6, 15)
    assert bizdate.days_between(a, b) + bizdate.days_between(b, c) == bizdate.days_between(a, c)


@given(NAIVE, NAIVE)
def test_days_between_instants_counts_central_calendar_days(n1, n2):
    d1, d2 = central_date_of_instant(n1), central_date_of_instant(n2)
    assert bizdate.days_between(as_utc(n1), as_utc(n2)) == (d2 - d1).days
    # an instant and a bare date mix: the bare date is already Central
    assert bizdate.days_between(as_utc(n1), d2) == (d2 - d1).days


@given(DATES, SMALL_K)
def test_add_months_moves_whole_months_and_keeps_or_clamps_the_day(d, k):
    r = bizdate.add_months(d, k)
    assert (r.year * 12 + r.month) - (d.year * 12 + d.month) == k
    last = nth_month_end(r.year, r.month)
    assert r.day == min(d.day, last)
    assert 1 <= r.day <= last
    if d.day <= 28:
        assert r.day == d.day                                  # never clamped
    assert bizdate.add_months(d, 0) == d
    assert bizdate.add_months(d.isoformat(), k) == r


def nth_month_end(year, month):
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - dt.timedelta(days=1)).day


@given(DATES, SMALL_K)
def test_add_months_round_trip_returns_the_same_month_on_or_before_the_day(d, k):
    back = bizdate.add_months(bizdate.add_months(d, k), -k)
    assert (back.year, back.month) == (d.year, d.month)
    assert back <= d
    assert back.day == min(d.day, nth_month_end(bizdate.add_months(d, k).year,
                                                bizdate.add_months(d, k).month))
    if d.day <= 28:
        assert back == d


@given(DATES, st.integers(-300, 300), st.integers(-300, 300))
def test_add_months_composes_up_to_clamping(d, a, b):
    stepwise = bizdate.add_months(bizdate.add_months(d, a), b)
    direct = bizdate.add_months(d, a + b)
    assert (stepwise.year, stepwise.month) == (direct.year, direct.month)
    assert stepwise <= direct                                  # clamping only ever moves the day earlier
    if d.day <= 28:
        assert stepwise == direct


@given(DATES, DATES, SMALL_K)
def test_add_months_is_monotone(d1, d2, k):
    lo, hi = sorted((d1, d2))
    assert bizdate.add_months(lo, k) <= bizdate.add_months(hi, k)


@given(DATES)
def test_twelve_months_is_a_year_except_for_feb_29(d):
    r = bizdate.add_months(d, 12)
    assert r.year == d.year + 1 and r.month == d.month
    if (d.month, d.day) == (2, 29):
        assert r.day == 28 or bizdate.days_in_year(r.year) == 366
    else:
        assert r.day == d.day


@pytest.mark.parametrize("start,k,want", [
    (dt.date(2026, 1, 31), 1, dt.date(2026, 2, 28)),
    (dt.date(2028, 1, 31), 1, dt.date(2028, 2, 29)),
    (dt.date(2026, 8, 31), -2, dt.date(2026, 6, 30)),
    (dt.date(2024, 2, 29), 12, dt.date(2025, 2, 28)),
    (dt.date(2024, 2, 29), 48, dt.date(2028, 2, 29)),
    (dt.date(2026, 12, 31), 1, dt.date(2027, 1, 31)),          # across the year
    (dt.date(2026, 1, 15), -1, dt.date(2025, 12, 15)),
    (dt.date(2026, 1, 15), -13, dt.date(2024, 12, 15)),
])
def test_add_months_year_boundaries_and_leap_days(start, k, want):
    assert bizdate.add_months(start, k) == want


# ── years ─────────────────────────────────────────────────────────────────────────────────────
@given(st.integers(1, 9998))
def test_days_in_year_follows_the_gregorian_rule(y):
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    assert bizdate.days_in_year(y) == (366 if leap else 365)
    assert bizdate.days_in_year(y) == (dt.date(y + 1, 1, 1) - dt.date(y, 1, 1)).days


@pytest.mark.parametrize("y,n", [(1900, 365), (2000, 366), (2100, 365), (2024, 366), (2026, 365), (2028, 366)])
def test_days_in_year_century_rule(y, n):
    assert bizdate.days_in_year(y) == n


@given(DATES)
def test_day_of_year_and_year_bounds(d):
    jan1, dec31 = bizdate.year_bounds(d)
    assert jan1 <= d <= dec31
    assert (jan1.year, jan1.month, jan1.day) == (d.year, 1, 1)
    assert (dec31.year, dec31.month, dec31.day) == (d.year, 12, 31)
    assert (dec31 - jan1).days + 1 == bizdate.days_in_year(d.year)
    n = bizdate.day_of_year(d)
    assert 1 <= n <= bizdate.days_in_year(d.year)
    assert n == (d - jan1).days + 1
    assert bizdate.day_of_year(jan1) == 1
    assert bizdate.day_of_year(dec31) == bizdate.days_in_year(d.year)


@given(st.dates(dt.date(1990, 1, 1), dt.date(2100, 12, 30)))
def test_day_of_year_steps_by_one_inside_a_year_and_resets_on_jan_1(d):
    nxt = d + dt.timedelta(days=1)
    if nxt.year == d.year:
        assert bizdate.day_of_year(nxt) == bizdate.day_of_year(d) + 1
    else:
        assert bizdate.day_of_year(nxt) == 1
        assert bizdate.day_of_year(d) == bizdate.days_in_year(d.year)


# ── parsing ───────────────────────────────────────────────────────────────────────────────────
@given(DATES)
def test_parse_date_round_trips_every_iso_date(d):
    assert bizdate.parse_date(d.isoformat()) == d
    assert bizdate.parse_date(d) is d                          # a date passes through
    assert bizdate.iso_date(d) == d.isoformat()
    assert bizdate.parse_date(bizdate.iso_date(d)) == d


_STRICT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)


def _oracle_date(text):
    """What a strict YYYY-MM-DD reader returns for `text`, or None. No whitespace handling."""
    if not _STRICT.fullmatch(text):
        return None
    try:
        return dt.date(int(text[:4]), int(text[5:7]), int(text[8:]))
    except ValueError:
        return None


_NEAR_MISS = st.one_of(
    st.text(max_size=14),
    st.from_regex(r"[0-9]{1,5}[-/. ][0-9]{1,3}[-/. ][0-9]{1,3}", fullmatch=True),
    st.from_regex(r"[0-9]{4}-[0-9]{2}-[0-9]{2}.{1,6}", fullmatch=True),
    st.tuples(DATES, st.integers(0, 9), st.sampled_from(list("0123456789-/ x:T+Z"))).map(
        lambda t: t[0].isoformat()[:t[1]] + t[2] + t[0].isoformat()[t[1] + 1:]),
    DATES.map(lambda d: d.strftime("%Y%m%d")),
    DATES.map(lambda d: d.strftime("%m/%d/%Y")),
    DATES.map(lambda d: "%d-%d-%d" % (d.year, d.month, d.day)),
    DATES.map(lambda d: d.isoformat() + "T00:00:00"),
    DATES.map(lambda d: "%d-W%02d-%d" % tuple(d.isocalendar())),
)


@given(_NEAR_MISS)
@example("20261104")
@example("2026-W45-3")
@example("2026-11-04T10:00:00-06:00")
@example("2026-11-4")
@example("2026-02-30")
@example("0000-01-01")
@example("٢٠٢٦-١١-٠٤")   # Arabic-Indic digits
@example("２０２６-１１-０４")   # full-width digits
def test_parse_date_accepts_exactly_yyyy_mm_dd(text):
    try:
        got = bizdate.parse_date(text)
    except ValueError:
        got = None
    if got is not None:
        assert got.isoformat() == text.strip()                 # only a YYYY-MM-DD text can succeed
    if not any(c.isspace() for c in text):
        assert got == _oracle_date(text)


def test_parse_date_refuses_timestamps_and_nothing():
    for bad in (dt.datetime(2026, 11, 4), dt.datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
                None, "", "   ", "2026-11-04T10:00:00Z"):
        with pytest.raises(ValueError):
            bizdate.parse_date(bad)
    with pytest.raises(ValueError):
        bizdate.add_days(dt.datetime(2026, 11, 4, 10, 0), 1)   # the date maths refuse a datetime too
    with pytest.raises(ValueError):
        bizdate.central_midnight(dt.datetime(2026, 11, 4, 10, 0))


@given(DATES)
def test_parse_ts_refuses_a_bare_date_in_any_year(d):
    with pytest.raises(ValueError):
        bizdate.parse_ts(d.isoformat())
    with pytest.raises(ValueError):
        bizdate.parse_ts(" %s " % d.isoformat())


@pytest.mark.parametrize("bad", ["", "   ", None, "garbage", "not a time", "2026-11-04T", "10:00",
                                 "2026-13-01T10:00:00", "2026-02-30T10:00:00", "2026-11-04T25:00:00",
                                 "2026-11-04T10:00:00+99:00", "Z", "tomorrow"])
def test_parse_ts_refuses_garbage(bad):
    with pytest.raises(ValueError):
        bizdate.parse_ts(bad)


@given(st.text(max_size=30))
def test_parse_ts_only_ever_fails_with_value_error_and_always_returns_aware(text):
    try:
        got = bizdate.parse_ts(text)
    except ValueError:
        return
    assert got.tzinfo is not None and got.utcoffset() is not None


@given(NAIVE, st.integers(-14 * 60, 14 * 60), st.sampled_from(["T", " "]))
def test_parse_ts_reads_an_offset_and_keeps_the_instant(naive, minutes, sep):
    off = dt.timedelta(minutes=minutes)
    text = naive.isoformat(sep=sep) + fmt_offset(off)
    got = bizdate.parse_ts(text)
    assert got.utcoffset() == off
    assert got.replace(tzinfo=None) == naive                   # wall clock untouched
    assert got.astimezone(UTC).replace(tzinfo=None) == naive - off


@given(NAIVE, st.sampled_from(["Z", "z"]))
def test_parse_ts_z_means_utc(naive, z):
    got = bizdate.parse_ts(naive.isoformat() + z)
    assert got.utcoffset() == dt.timedelta(0)
    assert got.replace(tzinfo=None) == naive


@given(NAIVE)
def test_parse_ts_passes_a_datetime_through_and_reads_a_naive_one_as_central(naive):
    aware = as_utc(naive)
    assert bizdate.parse_ts(aware) == aware
    assert bizdate.parse_ts(aware).utcoffset() == dt.timedelta(0)   # an offset is never replaced
    got = bizdate.parse_ts(naive)
    assert got.tzinfo is not None
    assert got.replace(tzinfo=None) == naive
    assert got.utcoffset() in (-5 * H, -6 * H)                 # a Central offset, not the server's


# ── to_iso_central ────────────────────────────────────────────────────────────────────────────
_ISO_CENTRAL = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[56]:00")


@given(NAIVE, st.integers(0, 999999))
def test_to_iso_central_round_trips_an_instant_with_the_offset_that_moment_had(naive, micro):
    naive = naive.replace(microsecond=micro)
    t = as_utc(naive)
    s = bizdate.to_iso_central(t)
    assert _ISO_CENTRAL.fullmatch(s)                           # to the second, Central offset only
    off = central_offset_of_instant(naive)
    assert s.endswith(fmt_offset(off))
    local = naive + off
    assert s[:19] == local.replace(microsecond=0).isoformat()
    # the same instant comes back, so the two 01:30s of a fall-back night stay distinct
    assert bizdate.parse_ts(s).astimezone(UTC) == t.replace(microsecond=0)
    assert bizdate.to_iso_central(s) == s                      # idempotent
    assert bizdate.to_iso_central(bizdate.parse_ts(s).astimezone(UTC)) == s


@given(NAIVE, st.integers(-14 * 60, 14 * 60))
def test_to_iso_central_converts_any_offset_to_central(naive, minutes):
    off = dt.timedelta(minutes=minutes)
    text = naive.replace(microsecond=0).isoformat() + fmt_offset(off)
    utc_naive = naive.replace(microsecond=0) - off
    s = bizdate.to_iso_central(text)
    want_off = central_offset_of_instant(utc_naive)
    assert s == (utc_naive + want_off).isoformat() + fmt_offset(want_off)


@given(NAIVE)
def test_to_iso_central_z_timestamps(naive):
    naive = naive.replace(microsecond=0)
    s = bizdate.to_iso_central(naive.isoformat() + "Z")
    assert s == bizdate.to_iso_central(as_utc(naive))
    assert bizdate.parse_ts(s).astimezone(UTC).replace(tzinfo=None) == naive


@given(NAIVE)
def test_a_naive_timestamp_is_central_wall_time_never_the_servers(naive):
    naive = naive.replace(microsecond=0)
    # skip the one wall-clock hour that does not exist (02:00-02:59 on the spring-forward Sunday)
    assume(not (naive.date() == spring_day(naive.year) and naive.hour == 2))
    d = naive.date()
    if d == fall_day(d.year):
        dst = naive.hour < 2                                   # 01:xx happens twice: the first (CDT) one
    elif d == spring_day(d.year):
        dst = naive.hour >= 3
    else:
        dst = spring_day(d.year) < d < fall_day(d.year)
    want = naive.isoformat() + ("-05:00" if dst else "-06:00")
    assert bizdate.to_iso_central(naive.isoformat()) == want   # a string
    assert bizdate.to_iso_central(naive) == want               # a datetime
    assert bizdate.parse_ts(naive.isoformat()).tzinfo.key == "America/Chicago"


@pytest.mark.parametrize("text,want", [
    ("2026-11-01T01:30:00", "2026-11-01T01:30:00-05:00"),       # ambiguous: the first one
    ("2026-11-01T02:30:00", "2026-11-01T02:30:00-06:00"),
    ("2026-03-08T01:59:00", "2026-03-08T01:59:00-06:00"),
    ("2026-03-08T03:00:00", "2026-03-08T03:00:00-05:00"),
    ("2027-03-14T12:00:00", "2027-03-14T12:00:00-05:00"),
    ("2028-11-05T00:30:00", "2028-11-05T00:30:00-05:00"),
])
def test_naive_timestamps_on_transition_days(text, want):
    assert bizdate.to_iso_central(text) == want


def test_a_naive_wall_time_that_never_happened_still_names_the_right_instant():
    # 02:30 on the spring-forward Sunday does not exist; it is read with the offset before the jump
    # (PEP 495, fold=0), i.e. 08:30 UTC, which is 03:30 CDT.
    got = bizdate.parse_ts("2026-03-08T02:30:00")
    assert got.astimezone(UTC) == dt.datetime(2026, 3, 8, 8, 30, tzinfo=UTC)
    out = bizdate.to_iso_central("2026-03-08T02:30:00")
    assert bizdate.parse_ts(out).astimezone(UTC) == got.astimezone(UTC)


def test_to_iso_central_keeps_nothing():
    assert bizdate.to_iso_central(None) is None
    assert bizdate.to_iso_central("") is None
    assert bizdate.iso_date(None) is None and bizdate.iso_date("") is None
    assert bizdate.biz_date(None) is None and bizdate.biz_date("") is None


@given(NAIVE)
def test_biz_date_agrees_for_instants_dates_and_strings(naive):
    t = as_utc(naive)
    want = central_date_of_instant(naive)
    assert bizdate.biz_date(t) == want
    assert bizdate.biz_date(t.isoformat()) == want
    assert bizdate.biz_date(naive.replace(microsecond=0).isoformat() + "Z") == want
    assert bizdate.biz_date(bizdate.to_iso_central(t)) == want  # reading its own Central string
    assert bizdate.biz_date(want) == want                       # a bare date is already Central
    assert bizdate.biz_date(want.isoformat()) == want


# ── central_midnight and range_utc: the DST rule ──────────────────────────────────────────────
@given(MODERN)
def test_central_midnight_is_midnight_with_the_real_dst_offset(d):
    m = bizdate.central_midnight(d)
    assert (m.hour, m.minute, m.second, m.microsecond) == (0, 0, 0, 0)
    assert m.date() == d
    assert m.utcoffset() == midnight_offset(d)
    assert m.utcoffset() in (-5 * H, -6 * H)
    assert bizdate.central_midnight(d.isoformat()) == m
    assert bizdate.biz_date(m) == d


# The transition days written out by hand (not from nth_sunday), so the oracle is itself checked.
TRANSITIONS = [
    (dt.date(2026, 3, 8), dt.date(2026, 11, 1)),
    (dt.date(2027, 3, 14), dt.date(2027, 11, 7)),
    (dt.date(2028, 3, 12), dt.date(2028, 11, 5)),
]


@pytest.mark.parametrize("spring,fall", TRANSITIONS)
def test_the_oracle_matches_the_known_2026_to_2028_transition_days(spring, fall):
    assert spring_day(spring.year) == spring and fall_day(fall.year) == fall
    assert spring.weekday() == 6 and fall.weekday() == 6


@pytest.mark.parametrize("spring,fall", TRANSITIONS)
def test_transition_days_are_23_and_25_hours_and_the_rest_24(spring, fall):
    one = dt.timedelta(days=1)

    def length(d):
        a, b = bizdate.range_utc(d, d)
        return b - a

    assert length(spring) == 23 * H
    assert length(fall) == 25 * H
    for d in (spring - one, spring + one, fall - one, fall + one):
        assert length(d) == 24 * H
    # offsets: the spring day starts in CST, the day after in CDT; the fall day starts in CDT,
    # the day after in CST
    assert bizdate.central_midnight(spring).utcoffset() == -6 * H
    assert bizdate.central_midnight(spring + one).utcoffset() == -5 * H
    assert bizdate.central_midnight(fall).utcoffset() == -5 * H
    assert bizdate.central_midnight(fall + one).utcoffset() == -6 * H
    # a week across each transition is 7 days +/- 1 hour
    a, b = bizdate.range_utc(spring - 3 * one, spring + 3 * one)
    assert b - a == 7 * 24 * H - H
    a, b = bizdate.range_utc(fall - 3 * one, fall + 3 * one)
    assert b - a == 7 * 24 * H + H


@pytest.mark.parametrize("year", [2026, 2027, 2028])
def test_every_day_of_the_year_has_the_right_length_and_the_year_nets_to_whole_days(year):
    spring, fall = spring_day(year), fall_day(year)
    d, lengths = dt.date(year, 1, 1), {}
    while d.year == year:
        a, b = bizdate.range_utc(d, d)
        lengths[d] = b - a
        d += dt.timedelta(days=1)
    assert lengths.pop(spring) == 23 * H
    assert lengths.pop(fall) == 25 * H
    assert set(lengths.values()) == {24 * H}                   # 363 or 364 ordinary days
    a, b = bizdate.range_utc(dt.date(year, 1, 1), dt.date(year, 12, 31))
    assert b - a == bizdate.days_in_year(year) * 24 * H        # +23h and +25h cancel


def test_dst_rule_holds_for_every_year_2007_to_2100():
    one = dt.timedelta(days=1)
    for year in range(2007, 2101):
        spring, fall = spring_day(year), fall_day(year)
        assert spring.month == 3 and 8 <= spring.day <= 14 and spring.weekday() == 6
        assert fall.month == 11 and 1 <= fall.day <= 7 and fall.weekday() == 6
        for d, want in ((spring, 23), (fall, 25), (spring - one, 24), (spring + one, 24),
                        (fall - one, 24), (fall + one, 24), (dt.date(year, 7, 4), 24)):
            a, b = bizdate.range_utc(d, d)
            assert b - a == want * H, d
            assert a.utcoffset() == dt.timedelta(0)            # range_utc is in UTC


@given(MODERN)
def test_one_days_length_in_utc_is_23_24_or_25_hours_by_the_rule(d):
    a, b = bizdate.range_utc(d, d)
    assert b - a == day_length(d)
    assert a.utcoffset() == dt.timedelta(0) and b.utcoffset() == dt.timedelta(0)


@given(MODERN, st.integers(0, 400))
def test_range_utc_is_half_open_and_covers_exactly_first_to_last(first, span):
    last = first + dt.timedelta(days=span)
    assume(last <= dt.date(2100, 12, 30))
    a, b = bizdate.range_utc(first, last)
    one_us = dt.timedelta(microseconds=1)
    assert a == bizdate.central_midnight(first)
    assert b == bizdate.central_midnight(last + dt.timedelta(days=1))
    # the first microsecond of `first` is in, the one before it is not; likewise the end
    assert bizdate.biz_date(a) == first
    assert bizdate.biz_date(a - one_us) == first - dt.timedelta(days=1)
    assert bizdate.biz_date(b - one_us) == last
    assert bizdate.biz_date(b) == last + dt.timedelta(days=1)
    # the length is the sum of the days'
    total = sum((day_length(first + dt.timedelta(days=i)) for i in range(span + 1)), dt.timedelta())
    assert b - a == total


@given(MODERN, st.integers(0, 60), st.integers(0, 60))
def test_consecutive_ranges_tile_with_no_gap_or_overlap(first, n1, n2):
    mid = first + dt.timedelta(days=n1)
    last = mid + dt.timedelta(days=1 + n2)
    assume(last <= dt.date(2100, 12, 30))
    a1, b1 = bizdate.range_utc(first, mid)
    a2, b2 = bizdate.range_utc(mid + dt.timedelta(days=1), last)
    assert b1 == a2                                            # no gap, no overlap
    assert bizdate.range_utc(first, last) == (a1, b2)          # and the union is the whole range


@given(MODERN)
def test_an_empty_range_is_empty_and_strings_work(d):
    a, b = bizdate.range_utc(d, d - dt.timedelta(days=1))
    assert a == b
    assert bizdate.range_utc(d.isoformat(), d.isoformat()) == bizdate.range_utc(d, d)


# ── the overrides, as properties ──────────────────────────────────────────────────────────────
@given(DATES)
def test_bd_today_pins_today_and_every_default_argument(d):
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BD_NOW", raising=False)
        mp.setenv("BD_TODAY", d.isoformat())
        assert bizdate.today_central() == d
        assert bizdate.now_central().date() == d
        assert bizdate.week_start() == bizdate.week_start(d)
        assert bizdate.week_bounds() == bizdate.week_bounds(d)
        assert bizdate.year_bounds() == bizdate.year_bounds(d)
        assert bizdate.day_of_year() == bizdate.day_of_year(d)


@given(NAIVE, DATES)
def test_bd_now_fixes_the_moment_and_bd_today_only_moves_the_date(naive, other):
    naive = naive.replace(microsecond=0)
    t = as_utc(naive)
    off = central_offset_of_instant(naive)
    local = naive + off
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BD_TODAY", raising=False)
        mp.setenv("BD_NOW", naive.isoformat() + "Z")
        assert bizdate.today_central() == local.date()         # Central's date, not UTC's
        assert bizdate.now_central() == t
        assert bizdate.to_iso_central(bizdate.now_central()) == local.isoformat() + fmt_offset(off)
        assert bizdate.week_start() == bizdate.week_start(local.date())
        mp.setenv("BD_TODAY", other.isoformat())               # BD_TODAY wins the date, keeps the time
        assert bizdate.today_central() == other
        moved = bizdate.now_central()
        assert moved.date() == other
        assert moved.time() == local.time()
        if other == local.date():
            assert moved == t


def test_bd_now_without_an_offset_is_central_wall_time():
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BD_TODAY", raising=False)
        mp.setenv("BD_NOW", "2026-11-04T10:05:00")
        assert bizdate.now_central().isoformat() == "2026-11-04T10:05:00-06:00"
        assert bizdate.today_central() == dt.date(2026, 11, 4)
        mp.setenv("BD_NOW", "2026-07-04T10:05:00")
        assert bizdate.now_central().isoformat() == "2026-07-04T10:05:00-05:00"


# ── surrounding whitespace is ignored (parse_date, parse_ts, biz_date strip their text) ───────
_WS = st.text(alphabet=" \t\r\n", max_size=3)


@given(DATES, _WS, _WS)
def test_dates_ignore_surrounding_whitespace(d, pre, post):
    padded = pre + d.isoformat() + post
    assert bizdate.parse_date(padded) == d
    assert bizdate.biz_date(padded) == d
    assert bizdate.add_days(padded, 0) == d
    assert bizdate.iso_date(padded) == d.isoformat()


@given(NAIVE, st.sampled_from(["Z", "z", "+00:00", "-05:00"]), _WS, _WS)
def test_parse_ts_ignores_surrounding_whitespace(naive, tail, pre, post):
    text = naive.isoformat() + tail
    assert bizdate.parse_ts(pre + text + post) == bizdate.parse_ts(text)
    assert bizdate.biz_date(pre + text + post) == bizdate.biz_date(text)
    assert bizdate.to_iso_central(pre + text + post) == bizdate.to_iso_central(text)


# ── the overrides and the real clock ──────────────────────────────────────────────────────────
def test_bd_today_on_a_fall_back_day_keeps_the_first_of_the_two_01_30s():
    # BD_NOW is Central wall time 01:30 on the day before; BD_TODAY moves the date to the fall-back
    # Sunday, where 01:30 happens twice. The first (CDT, fold=0) one is meant.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("BD_NOW", "2026-10-31T01:30:00")
        mp.setenv("BD_TODAY", "2026-11-01")
        got = bizdate.now_central()
        assert got.isoformat() == "2026-11-01T01:30:00-05:00"
        assert got.astimezone(UTC) == dt.datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_without_overrides_now_is_the_real_instant_in_central():
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BD_NOW", raising=False)
        mp.delenv("BD_TODAY", raising=False)
        before = dt.datetime.now(UTC)
        got = bizdate.now_central()
        today = bizdate.today_central()
        after = dt.datetime.now(UTC)
    assert before - dt.timedelta(seconds=1) <= got <= after + dt.timedelta(seconds=1)
    assert got.tzinfo.key == "America/Chicago"                 # Central, not UTC or the server's zone
    assert got.utcoffset() in (-5 * H, -6 * H)
    assert today in (got.date(), bizdate.biz_date(after))


@pytest.mark.parametrize("year", range(2007, 2101))
def test_a_naive_datetime_with_fold_1_is_the_second_of_the_two_fall_back_hours(year):
    d = fall_day(year)
    first = dt.datetime.combine(d, dt.time(1, 30))
    second = first.replace(fold=1)
    assert bizdate.to_iso_central(first) == d.isoformat() + "T01:30:00-05:00"
    assert bizdate.to_iso_central(second) == d.isoformat() + "T01:30:00-06:00"
    assert bizdate.parse_ts(second).astimezone(UTC) - bizdate.parse_ts(first).astimezone(UTC) == H
