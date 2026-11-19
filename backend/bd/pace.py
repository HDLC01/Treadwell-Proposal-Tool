"""The annual pace bar and the "N of 10" headline: a port of BDCore.pace / weeklyProgress
(frontend/bd/js/bd-core.js). The two must give the same answers; tests/test_bd_pace.py runs the same
case table as tests/test_bd_core_js.py, plus random cases through node against bd-core.js itself.

    pace(contacts, interactions, today)       the full port (dicts in, the Pace object out)
    pace_from_totals(target, completed, today) the same numbers from SQL sums (GET /api/week)
    weekly_progress(tasks)                     {"done", "total", "label"}

The rules (api-contract.md, WeekView):
    target_total      sum of every owned contact's frequency (missing, 0 or bad = the category
                      default: 4 bd, 3 maintenance)
    required_to_date  target x day_of_year / days_in_year, one decimal (Central day)
    completed         touches (live call, meeting, hosted) dated this Central year, up to today
    pct               round(100 x completed / target), 0 when there is no target
    delta             round(completed - required_to_date)

Every round() is JavaScript's Math.round, i.e. floor(x + 1/2): halves go UP, towards +infinity,
so -14.5 is -14 (Decimal's ROUND_HALF_UP would give -15, Python's round() gives -14 only by its
half-to-even luck). The arithmetic is exact (fractions), so float noise never moves a result.
"""
from __future__ import annotations

import datetime as _dt
import math
from fractions import Fraction
from typing import Any

from . import bizdate

MAINTENANCE_TOUCHES = 3
DEFAULT_FREQUENCY_BD = 4
DASH = "—"


def js_round(x: Any) -> int:
    """JavaScript's Math.round on an exact number: floor(x + 1/2)."""
    return math.floor(Fraction(x) + Fraction(1, 2))


def _number(v: Any) -> Any:
    """JavaScript's Number(v) for the values a frequency can hold; None for NaN."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and math.isnan(v) else v
    try:
        text = str(v).strip()
        if text == "":
            return 0
        f = float(text)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return int(f) if f.is_integer() else f


def freq_of(contact: Any) -> int | float:
    """Live talks a year this contact needs (BDCore.freqOf)."""
    f = _number((contact or {}).get("frequency_per_year"))
    if f is not None and f > 0:
        return f
    return MAINTENANCE_TOUCHES if (contact or {}).get("category") == "maintenance" else DEFAULT_FREQUENCY_BD


def is_touch(i: Any) -> bool:
    """The one counting rule (BDCore.isTouch); a `counts_as_touch` flag is never trusted."""
    if not i:
        return False
    kind = i.get("kind")
    if kind in ("meeting", "hosted"):
        return True
    return kind == "call" and i.get("outcome") in ("answered", "meeting_set")


def _day(today: Any) -> _dt.date:
    return bizdate.parse_date(today if isinstance(today, _dt.date) else str(today)[:10])


def _biz_date_or_none(v: Any) -> _dt.date | None:
    try:
        return bizdate.biz_date(v)
    except (TypeError, ValueError):
        return None


def pace_label(year: int, pct: int, delta: int) -> str:
    head = "%d BD Pace: %d%% %s " % (year, pct, DASH)
    if delta == 0:
        return head + "right on pace"
    n = abs(delta)
    return head + "%d %s" % (n, "interaction" if n == 1 else "interactions") + (
        " ahead of pace" if delta > 0 else " behind pace")


def _plain(x: Any) -> Any:
    """An int for a whole value, else a float (JSON numbers, as JavaScript would print them)."""
    if isinstance(x, Fraction):
        return int(x) if x.denominator == 1 else float(x)
    return x


def pace_from_totals(target: Any, completed: Any, today: Any) -> dict:
    """The Pace object from Σ frequency and the touches this year (both already counted)."""
    day = _day(today)
    year = day.year
    target_q = Fraction(target or 0)
    completed = int(completed or 0)
    required = Fraction(js_round(10 * target_q * bizdate.day_of_year(day) / bizdate.days_in_year(year)), 10)
    pct = js_round(100 * Fraction(completed) / target_q) if target_q > 0 else 0
    delta = js_round(completed - required)
    return {
        "year": year,
        "as_of": day.isoformat(),
        "required_to_date": float(required),
        "completed": completed,
        "target_total": _plain(target_q),
        "pct": pct,
        "delta": delta,
        "label": pace_label(year, pct, delta),
    }


def pace(contacts: Any, interactions: Any, today: Any) -> dict:
    """BDCore.pace: `contacts` are the owner's contacts, `interactions` any interactions (only
    those of these contacts, that are touches, dated this Central year up to today, count)."""
    day = _day(today)
    ids: set[Any] = set()
    target = Fraction(0)
    for c in contacts or []:
        ids.add(c.get("id"))
        target += Fraction(freq_of(c))
    completed = 0
    for i in interactions or []:
        if not is_touch(i) or i.get("contact_id") not in ids:
            continue
        d = _biz_date_or_none(i.get("occurred_at"))
        if d is not None and d.year == day.year and d <= day:
            completed += 1
    return pace_from_totals(target, completed, day)


def weekly_progress(tasks: Any) -> dict:
    """BDCore.weeklyProgress: done / total of a list of tasks (snoozed ones stay in the total)."""
    items = list(tasks or [])
    done = sum(1 for t in items if t.get("status") == "done")
    return {"done": done, "total": len(items), "label": "%d of %d done" % (done, len(items))}
