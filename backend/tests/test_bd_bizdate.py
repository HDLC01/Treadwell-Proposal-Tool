"""bizdate.py: Central dates and timestamps, Monday weeks, DST, and the BD_TODAY / BD_NOW overrides.

The dev PC's clock runs about 13 hours ahead of Central, so these tests never compare with the
machine's own date; they fix the clock through the overrides or work on given values.
"""
from __future__ import annotations

import datetime as dt

import pytest

from bd import bizdate
UTC = dt.UTC


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


# ── to_iso_central: the offset the moment had ─────────────────────────────────────────────────
@pytest.mark.parametrize("moment,want", [
    (utc(2026, 10, 30, 21, 0), "2026-10-30T16:00:00-05:00"),         # CDT (the contract's example)
    (utc(2026, 11, 4, 16, 0), "2026-11-04T10:00:00-06:00"),          # CST (the contract's example)
    # Fall back, Sunday 2026-11-01: 01:30 happens twice.
    (utc(2026, 11, 1, 6, 30), "2026-11-01T01:30:00-05:00"),
    (utc(2026, 11, 1, 7, 30), "2026-11-01T01:30:00-06:00"),
    # Spring forward, Sunday 2026-03-08: 01:59 CST is followed by 03:00 CDT.
    (utc(2026, 3, 8, 7, 59), "2026-03-08T01:59:00-06:00"),
    (utc(2026, 3, 8, 8, 0), "2026-03-08T03:00:00-05:00"),
    (utc(2026, 11, 4, 16, 0, 0, 999999), "2026-11-04T10:00:00-06:00"),   # to the second
])
def test_to_iso_central_uses_that_moments_offset(moment, want):
    assert bizdate.to_iso_central(moment) == want


def test_to_iso_central_reads_strings_and_keeps_none():
    assert bizdate.to_iso_central("2026-11-04T16:00:00Z") == "2026-11-04T10:00:00-06:00"
    assert bizdate.to_iso_central("2026-07-22T11:05:00-05:00") == "2026-07-22T11:05:00-05:00"
    assert bizdate.to_iso_central("2026-11-04T10:00:00") == "2026-11-04T10:00:00-06:00"   # naive = Central
    assert bizdate.to_iso_central(None) is None


def test_round_trip_of_every_mock_style_timestamp():
    for s in ("2026-01-15T10:45:00-06:00", "2026-09-15T15:30:00-05:00", "2026-11-02T09:20:00-06:00"):
        assert bizdate.to_iso_central(bizdate.parse_ts(s).astimezone(UTC)) == s


# ── biz_date: the Central calendar date ───────────────────────────────────────────────────────
@pytest.mark.parametrize("value,want", [
    ("2026-11-05T03:00:00Z", dt.date(2026, 11, 4)),    # 9 pm Central the night before
    ("2026-11-05T06:00:00Z", dt.date(2026, 11, 5)),    # midnight CST
    ("2026-07-01T04:59:00Z", dt.date(2026, 6, 30)),    # 23:59 CDT
    ("2026-07-01T05:00:00Z", dt.date(2026, 7, 1)),
    ("2026-11-04", dt.date(2026, 11, 4)),              # a bare date is already Central
    (dt.date(2026, 11, 4), dt.date(2026, 11, 4)),
    (utc(2027, 1, 1, 5, 59), dt.date(2026, 12, 31)),   # New Year's Eve in Central
    (None, None),
])
def test_biz_date(value, want):
    assert bizdate.biz_date(value) == want


# ── weeks and years ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("day,monday", [
    ("2026-11-02", "2026-11-02"),   # Monday
    ("2026-11-04", "2026-11-02"),   # Wednesday (the mock's today)
    ("2026-11-08", "2026-11-02"),   # Sunday belongs to the week before it
    ("2026-11-09", "2026-11-09"),
    ("2026-11-01", "2026-10-26"),   # the fall-back Sunday
    ("2026-03-08", "2026-03-02"),   # the spring-forward Sunday
    ("2027-01-01", "2026-12-28"),   # a week across New Year
])
def test_week_bounds_are_monday_to_sunday(day, monday):
    mon, sun = bizdate.week_bounds(day)
    assert mon.isoformat() == monday
    assert sun == mon + dt.timedelta(days=6)
    assert mon.weekday() == 0 and sun.weekday() == 6


def test_a_late_night_timestamp_lands_in_its_central_week():
    # Sunday 2026-11-08 23:30 Central is Monday 05:30 UTC: still the week of Nov 2.
    assert bizdate.week_start(utc(2026, 11, 9, 5, 30)) == dt.date(2026, 11, 2)


def test_year_bounds_day_of_year_and_leap_years():
    assert bizdate.year_bounds("2026-11-04") == (dt.date(2026, 1, 1), dt.date(2026, 12, 31))
    assert bizdate.day_of_year("2026-01-01") == 1
    assert bizdate.day_of_year("2026-11-04") == 308
    assert bizdate.day_of_year("2028-12-31") == 366
    assert bizdate.days_in_year(2026) == 365 and bizdate.days_in_year(2028) == 366
    assert bizdate.days_in_year(2100) == 365 and bizdate.days_in_year(2000) == 366


def test_add_months_clamps_like_bdcore():
    assert bizdate.add_months("2026-01-31", 1) == dt.date(2026, 2, 28)
    assert bizdate.add_months("2028-01-31", 1) == dt.date(2028, 2, 29)
    assert bizdate.add_months("2026-11-04", 2) == dt.date(2027, 1, 4)
    assert bizdate.add_months("2026-03-31", -1) == dt.date(2026, 2, 28)


def test_days_between_counts_central_days():
    assert bizdate.days_between("2026-10-22T11:20:00-05:00", "2026-11-04") == 13
    assert bizdate.days_between("2026-11-04", "2026-11-04T23:59:00-06:00") == 0
    assert bizdate.add_days("2026-11-04", 91) == dt.date(2027, 2, 3)


def test_range_utc_covers_whole_central_days():
    start, end = bizdate.range_utc("2026-11-02", "2026-11-08")
    assert start.astimezone(UTC) == utc(2026, 11, 2, 6, 0)
    assert end.astimezone(UTC) == utc(2026, 11, 9, 6, 0)
    start, end = bizdate.range_utc("2026-11-01", "2026-11-01")     # a 25-hour day
    assert (end - start) == dt.timedelta(hours=25)


def test_parse_date_is_strict():
    assert bizdate.parse_date("2026-11-04") == dt.date(2026, 11, 4)
    for bad in ("2026-11-4", "11/04/2026", "2026-11-04T10:00:00-06:00", "", None, "2026-02-30"):
        with pytest.raises(ValueError):
            bizdate.parse_date(bad)


def test_parse_ts_refuses_a_bare_date():
    with pytest.raises(ValueError):
        bizdate.parse_ts("2026-11-04")


# ── the overrides ─────────────────────────────────────────────────────────────────────────────
def test_bd_today_moves_today_and_keeps_a_real_time_of_day(monkeypatch):
    monkeypatch.delenv("BD_NOW", raising=False)
    monkeypatch.setenv("BD_TODAY", "2026-11-04")
    assert bizdate.today_central() == dt.date(2026, 11, 4)
    now = bizdate.now_central()
    assert now.date() == dt.date(2026, 11, 4)
    assert now.utcoffset() == dt.timedelta(hours=-6)                  # CST on that date
    monkeypatch.setenv("BD_TODAY", "2026-07-04")
    assert bizdate.now_central().utcoffset() == dt.timedelta(hours=-5)  # CDT on that one
    assert bizdate.week_bounds()[0] == dt.date(2026, 6, 29)
    assert bizdate.year_bounds() == (dt.date(2026, 1, 1), dt.date(2026, 12, 31))


def test_bd_now_fixes_the_moment(monkeypatch):
    monkeypatch.delenv("BD_TODAY", raising=False)
    monkeypatch.setenv("BD_NOW", "2026-11-05T03:30:00Z")
    assert bizdate.now_central().isoformat() == "2026-11-04T21:30:00-06:00"
    assert bizdate.today_central() == dt.date(2026, 11, 4)       # the Central date, not UTC's
    monkeypatch.setenv("BD_TODAY", "2026-12-01")                 # BD_TODAY wins for the date
    assert bizdate.today_central() == dt.date(2026, 12, 1)
    assert bizdate.to_iso_central(bizdate.now_central()) == "2026-12-01T21:30:00-06:00"


def test_without_overrides_today_is_centrals_not_the_machines(monkeypatch):
    monkeypatch.delenv("BD_TODAY", raising=False)
    monkeypatch.delenv("BD_NOW", raising=False)
    real = dt.datetime.now(UTC).astimezone(bizdate.BIZ_TZ).date()
    assert bizdate.today_central() == real
    assert bizdate.now_central().tzinfo is not None
