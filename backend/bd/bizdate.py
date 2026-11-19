"""Business dates: every "today", "this week" and "this year" a person sees is America/Chicago.

The dev PC's clock runs about 13 hours ahead of Central, and the server stores UTC, so NOTHING in
the backend may take a date from `datetime.now()` or `date.today()` directly. Use these:

    today_central() -> date          today in Central (honours BD_TODAY / BD_NOW)
    now_central() -> datetime        now, aware, in Central (honours BD_NOW, then BD_TODAY)
    week_bounds(d) -> (mon, sun)     the Monday-Sunday week `d` falls in
    week_start(d) -> date            its Monday
    year_bounds(d) -> (jan1, dec31)
    day_of_year(d), days_in_year(y)
    biz_date(v) -> date | None       the Central calendar date of a date / datetime / ISO string
    to_iso_central(ts) -> str|None   "2026-11-04T10:05:00-06:00": the offset THAT moment had
    iso_date(d) -> str|None          "2026-11-04"
    parse_date(s) -> date            strict "YYYY-MM-DD" (ValueError otherwise)
    exact_date(s) -> date | None     exactly "YYYY-MM-DD", nothing around it (no spaces, no newline)
    parse_ts(s) -> datetime          ISO 8601 with an offset (or "Z"); a naive one is read as Central
    add_days(d, n), days_between(a, b), add_months(d, k)

They mirror the frontend's BIZ_TZ helpers (BD's page helpers, shared.js) and BDCore's date maths
(frontend/bd/js/bd-core.js): weeks start on Monday, a bare date is a Central date, a timestamp is
converted into Central before its date is taken.

THE OVERRIDES (tests and demos only; both unset in production):
  BD_TODAY=2026-11-04            the business date. now_central() keeps the real Central time of
                                 day on that date (like the mock's bizNowISO(onDate)).
  BD_NOW=2026-11-04T10:05:00-06:00   a fixed moment; today_central() follows it unless BD_TODAY
                                 is set too (BD_TODAY wins for the date).
db.connect() copies both into the session (`bd.today`, `bd.now`) so SQL's bd_today() / bd_now()
agree with Python.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import re
from typing import Any
from zoneinfo import ZoneInfo

from . import config

BIZ_TZ_NAME = "America/Chicago"
BIZ_TZ = ZoneInfo(BIZ_TZ_NAME)
UTC = _dt.UTC

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── parsing ──────────────────────────────────────────────────────────────────────────────────
def parse_date(s: Any) -> _dt.date:
    """A strict ISO date "YYYY-MM-DD" (a date object passes through). ValueError otherwise."""
    if isinstance(s, _dt.datetime):
        raise ValueError("expected a date, got a timestamp")
    if isinstance(s, _dt.date):
        return s
    text = str(s or "").strip()
    if not _DATE_ONLY.match(text):
        raise ValueError("not a YYYY-MM-DD date: %r" % (s,))
    return _dt.date.fromisoformat(text)


_EXACT_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def exact_date(s: Any) -> _dt.date | None:
    """A date a caller SENT as text, read exactly: "YYYY-MM-DD" with nothing around it (parse_date
    strips its text; a week_start or an override's last day must not be padded) and a real date. None
    otherwise, a date object included."""
    if not isinstance(s, str) or not _EXACT_DATE.fullmatch(s):
        return None
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None


def parse_ts(s: Any) -> _dt.datetime:
    """An ISO 8601 timestamp as an aware datetime. "Z" is UTC; a timestamp WITHOUT an offset is
    read as Central wall-clock time (never as the server's zone). A datetime passes through
    (a naive one is likewise taken as Central). ValueError on anything else."""
    if isinstance(s, _dt.datetime):
        dt = s
    else:
        text = str(s or "").strip()
        if not text or _DATE_ONLY.match(text):
            raise ValueError("not a timestamp: %r" % (s,))
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BIZ_TZ)
    return dt


# ── now and today ────────────────────────────────────────────────────────────────────────────
def _real_now() -> _dt.datetime:
    return _dt.datetime.now(UTC).astimezone(BIZ_TZ)


def now_central() -> _dt.datetime:
    """Now, as an aware datetime in America/Chicago. BD_NOW fixes the moment; BD_TODAY alone moves
    the date and keeps the real Central time of day (so two calls still advance)."""
    fixed = config.bd_now_override()
    now = parse_ts(fixed).astimezone(BIZ_TZ) if fixed else _real_now()
    day = config.bd_today_override()
    if day:
        d = parse_date(day)
        if d != now.date():
            wall = _dt.datetime.combine(d, now.time().replace(tzinfo=None))
            now = wall.replace(tzinfo=BIZ_TZ, fold=0)
    return now


def today_central() -> _dt.date:
    """Today's date in Central (BD_TODAY, else BD_NOW's Central date, else the real clock)."""
    day = config.bd_today_override()
    if day:
        return parse_date(day)
    return now_central().date()


# ── conversions ──────────────────────────────────────────────────────────────────────────────
def biz_date(v: Any) -> _dt.date | None:
    """The Central calendar date of a date, an aware/naive datetime or an ISO string; None for
    nothing. A bare date is returned as is (it already is a Central date)."""
    if v is None or v == "":
        return None
    if isinstance(v, _dt.datetime):
        return parse_ts(v).astimezone(BIZ_TZ).date()
    if isinstance(v, _dt.date):
        return v
    text = str(v).strip()
    if _DATE_ONLY.match(text):
        return parse_date(text)
    return parse_ts(text).astimezone(BIZ_TZ).date()


def _require_biz_date(v: Any) -> _dt.date:
    """biz_date() for callers that need a date: nothing is a TypeError (as `None - date` was)."""
    day = biz_date(v)
    if day is None:
        raise TypeError("a date is required, got %r" % (v,))
    return day


def to_iso_central(ts: Any) -> str | None:
    """An ISO 8601 string in Central with the offset that moment had, to the second:
    "2026-10-30T16:00:00-05:00" (CDT), "2026-11-04T10:00:00-06:00" (CST). None stays None.
    A naive datetime is taken as Central; a string is parsed first."""
    if ts is None or ts == "":
        return None
    dt = parse_ts(ts) if not isinstance(ts, _dt.datetime) else (ts if ts.tzinfo else ts.replace(tzinfo=BIZ_TZ))
    return dt.astimezone(BIZ_TZ).replace(microsecond=0).isoformat(timespec="seconds")


def iso_date(d: Any) -> str | None:
    """"YYYY-MM-DD" for a date (a datetime gives its Central date); None stays None."""
    if d is None or d == "":
        return None
    return _require_biz_date(d).isoformat()


def central_midnight(d: Any) -> _dt.datetime:
    """00:00 Central on date `d`, aware (the start of that business day)."""
    return _dt.datetime.combine(parse_date(d), _dt.time(0, 0)).replace(tzinfo=BIZ_TZ)


# ── date maths ───────────────────────────────────────────────────────────────────────────────
def add_days(d: Any, n: int) -> _dt.date:
    return parse_date(d) + _dt.timedelta(days=int(n))


def days_between(a: Any, b: Any) -> int:
    """Whole Central days from a to b (b - a). Dates or timestamps."""
    return (_require_biz_date(b) - _require_biz_date(a)).days


def add_months(d: Any, k: int) -> _dt.date:
    """The same day k months on, clamped to the month's last day (Jan 31 + 1 -> Feb 28)."""
    d = parse_date(d)
    m = d.month - 1 + int(k)
    y = d.year + m // 12
    m = m % 12 + 1
    return _dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def week_start(d: Any = None) -> _dt.date:
    """The Monday of the (Monday-Sunday) week `d` falls in; default this week."""
    day = today_central() if d is None else _require_biz_date(d)
    return day - _dt.timedelta(days=day.weekday())


def week_bounds(d: Any = None) -> tuple[_dt.date, _dt.date]:
    """(monday, sunday) of the week `d` falls in; default this week."""
    mon = week_start(d)
    return mon, mon + _dt.timedelta(days=6)


def is_monday(d: Any) -> bool:
    return parse_date(d).weekday() == 0


def year_bounds(d: Any = None) -> tuple[_dt.date, _dt.date]:
    """(Jan 1, Dec 31) of the year `d` falls in; default this year."""
    day = today_central() if d is None else _require_biz_date(d)
    return _dt.date(day.year, 1, 1), _dt.date(day.year, 12, 31)


def days_in_year(y: int) -> int:
    return 366 if calendar.isleap(int(y)) else 365


def day_of_year(d: Any = None) -> int:
    """1 for Jan 1."""
    day = today_central() if d is None else _require_biz_date(d)
    return day.timetuple().tm_yday


def range_utc(first: Any, last: Any) -> tuple[_dt.datetime, _dt.datetime]:
    """[start, end) as aware UTC datetimes covering the Central days first..last inclusive, for
    `occurred_at >= start and occurred_at < end` queries that use an index. (UTC, so the
    difference is the real length: a fall-back day is 25 hours.)"""
    return central_midnight(first).astimezone(UTC), central_midnight(add_days(last, 1)).astimezone(UTC)
