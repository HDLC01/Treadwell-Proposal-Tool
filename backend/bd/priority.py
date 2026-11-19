"""The priority score: who matters most this week, and why. A faithful port of BDCore.scoreContact
and BDCore.reasonText (frontend/bd/js/bd-core.js), which are the reference; tests/test_bd_priority.py
runs a hand-built table and a few hundred random contacts through BOTH and requires the same
score, reasons and exclusion, word for word.

    score(contact, facts, today) -> {"score", "reasons", "excluded", "exclude_reason"}
    reason_text(reasons) -> str          the chip: the top two reasons as sentences
    ago_text(days), short_date(iso)      the two phrase helpers the reasons use (BDCore.agoText,
                                         BDCore.shortDate)

PURE: no database, no clock. `today` is a Central date ("2026-11-04" or a date).

THE CONTACT. Any mapping with the Contact fields the rules read (a contacts_summary row, a
serialised Contact, or a hand-built dict): last_live_at, last_attempt_at, attempts_since_live,
category, frequency_per_year, importance, confirmed, promised_date, next_step_date,
last_quote_date, archived_at, and for maintenance contacts maintenance_due, maintenance_due_date,
last_followup_at (the follow-up clock of the contacts_summary view). Database values (date, aware datetime) are turned into the strings
the mock holds ("2026-11-02", "2026-11-02T09:20:00-06:00") first, so every comparison below is
the JavaScript one on the same text.

THE FACTS. What is true about the contact that is not a column of it, laid OVER the contact
exactly as scoreContact does (a fact with the same name as a field replaces it):
    has_open_task    bool   the contact is already on the list being built (see
                            weekly.load_facts: the target week's OPEN tasks for a Friday batch,
                            this week's tasks in ANY state for "Give Me 10 More"). The mock
                            always sends it, true or false.
    last_quote_date  "YYYY-MM-DD" (optional)  the proposal tool's latest quote to this contact.
                            Today it is the contacts.last_quote_date column (the Phase 6 bridge
                            writes it), so weekly.py sends no such fact; a later source of quote
                            activity would send it here instead of changing the rules.

THE FACTORS (docs/build-plan.md "Phase 3"; the order below is the order points are added, which
breaks ties between reasons of equal points):
    never had a live talk     +40  "Never contacted" / "Never reached after N tries"
    cadence                   min(40, round(30 x days_since_live / interval)), interval = 120
                              (maintenance) or the UNFLOORED 365 / frequency; only when > 0:
                              "Last live talk <ago>; needs N a year"
    promised / next step      the earlier of the two dates that is AFTER the last live talk (one
                              on or before it was met by that talk): due or past +50, within 7
                              days +25: "Promised a call by Fri, Nov 6" / "Next step due ..."
    quote activity            last_quote_date 0-30 days ago +15 "Recent quote activity (Wed, Oct 21)"
    importance                3: +20 "Key account"; 2: +10 and no words
    tries since live          +5 each, at most 3; words only when there WAS a live talk
                              ("2 tries since the last live talk"; a never-reached contact
                              already says "Never reached after 2 tries")
    not confirmed             confirmed is exactly false: +8 "Needs confirming: still the right person?"
Reasons are the worded parts, most points first (ties: the order above).

EXCLUSION (checked in this order; an excluded contact still gets its score):
    archived_at set                         "archived"
    has_open_task                           "already in this week's list"
    last attempt fewer than 3 days ago      "tried in the last 3 days"
    maintenance and not maintenance_due     "maintenance, not due yet"   (a maintenance contact is on
                                            a list ONLY when its follow-up is due; the field is the
                                            contacts_summary one, laid over by facts like any other)

Arithmetic is IEEE double, as in JavaScript (Python floats are the same doubles), and every
round() is Math.round (halves up, towards +infinity).
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any

from . import bizdate

ATTEMPT_COOLDOWN_DAYS = 3
MAINTENANCE_TOUCH_DAYS = 120
MAINTENANCE_TOUCHES = 3
DEFAULT_FREQUENCY_BD = 4
CADENCE_CAP = 40

MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]       # date.weekday() order

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CENTRAL_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+-0[56]:00$")
_SENTENCE_END = re.compile(r"[.?!]$")


# ── JavaScript's value rules ─────────────────────────────────────────────────────────────────
def _truthy(v: Any) -> bool:
    """JavaScript truthiness for the values a contact field can hold."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0 and not (isinstance(v, float) and math.isnan(v))
    if isinstance(v, str):
        return v != ""
    return True


def _js_number(v: Any) -> Any:
    """Number(v) for null / booleans / numbers / numeric text; NaN as None."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and math.isnan(v) else v
    text = str(v).strip()
    if text == "":
        return 0
    if text in ("Infinity", "+Infinity", "-Infinity"):
        return float(text.replace("Infinity", "inf"))
    if "_" in text or any(w in text.lower() for w in ("inf", "nan")):
        return None                          # Python reads these; JavaScript says NaN
    try:
        f = float(text)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _or(v: Any, default: Any) -> Any:
    """`Number(x) || default`: NaN and 0 fall back."""
    return v if v is not None and v != 0 else default


def js_round(x: Any) -> int:
    """Math.round on a double: the nearest integer, halves towards +infinity."""
    f = math.floor(x)
    return int(f) + 1 if x - f >= 0.5 else int(f)


def js_str(n: Any) -> str:
    """String(n) for a number: 4 -> "4", 4.0 -> "4", 2.5 -> "2.5"."""
    if isinstance(n, float):
        if n.is_integer() and abs(n) < 1e21:
            return str(int(n))
        return repr(n)
    return str(n)


def _plain(n: Any) -> Any:
    """A whole float as an int (JSON prints 75, as JavaScript would), else as is."""
    if isinstance(n, float) and n.is_integer():
        return int(n)
    return n


def plural(n: Any, one: str, many: str | None = None) -> str:
    return js_str(n) + " " + (one if n == 1 else (many or one + "s"))


# ── dates, as bd-core.js reads them ──────────────────────────────────────────────────────────
def _text(v: Any) -> Any:
    """A field value as the mock's text: date -> "YYYY-MM-DD", datetime -> Central ISO with its
    offset, anything else unchanged."""
    if isinstance(v, _dt.datetime):
        return bizdate.to_iso_central(v)
    if isinstance(v, _dt.date):
        return v.isoformat()
    return v


def biz_date_of(v: Any) -> str:
    """BDCore.bizDateOf: the Central "YYYY-MM-DD" of a date or timestamp; "" for nothing/bad."""
    if not _truthy(v):
        return ""
    s = str(_text(v))
    if _DATE_ONLY.match(s):
        return s
    if _CENTRAL_TS.match(s):
        return s[:10]
    try:
        d = bizdate.biz_date(s)
    except (TypeError, ValueError):
        return ""
    return d.isoformat() if d else ""


def _day_num(iso: Any) -> int | None:
    """BDCore.dayNum: days since 1970-01-01 of the first 10 characters; None for NaN."""
    try:
        return (_dt.date.fromisoformat(str(iso)[:10]) - _dt.date(1970, 1, 1)).days
    except (TypeError, ValueError):
        return None


def days_between(a: Any, b: Any) -> int | None:
    """BDCore.daysBetween: whole Central days from a to b (b - a); None where JavaScript has NaN."""
    da, db = _day_num(biz_date_of(b)), _day_num(biz_date_of(a))
    if da is None or db is None:
        return None
    return da - db


def short_date(iso: Any) -> str:
    """BDCore.shortDate: "2026-11-06" -> "Fri, Nov 6"."""
    d = _dt.date.fromisoformat(str(_text(iso))[:10])
    return "%s, %s %d" % (WEEKDAYS_SHORT[d.weekday()], MONTHS_SHORT[d.month - 1], d.day)


def ago_text(days: Any) -> str:
    """BDCore.agoText: "today", "yesterday", "5 days ago", "2 weeks ago", "3 months ago"."""
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days >= 45:
        return plural(math.floor(days / 30), "month") + " ago"
    if days >= 14:
        return plural(math.floor(days / 7), "week") + " ago"
    return plural(days, "day") + " ago"


# ── frequency (BDCore.freqOf / touchesNeeded) ────────────────────────────────────────────────
def freq_of(c: Any) -> int | float:
    f = _js_number((c or {}).get("frequency_per_year"))
    if f is not None and f > 0:
        return f
    return MAINTENANCE_TOUCHES if (c or {}).get("category") == "maintenance" else DEFAULT_FREQUENCY_BD


def touches_needed(c: Any) -> int | float:
    return MAINTENANCE_TOUCHES if (c or {}).get("category") == "maintenance" else freq_of(c)


# ── the score ────────────────────────────────────────────────────────────────────────────────
def score(contact: Any, facts: Any = None, today: Any = None) -> dict:
    """BDCore.scoreContact. `facts` is laid over `contact` (see the module docstring)."""
    if today is None:
        raise ValueError("score() needs today's Central date")
    today_iso = today.isoformat() if isinstance(today, _dt.date) else str(today)[:10]
    c = {k: _text(v) for k, v in dict(contact or {}).items()}
    for k, v in dict(facts or {}).items():
        c[k] = _text(v)

    parts: list[tuple[int, str | None, int]] = []    # [points, text, order]

    def add(points: int, text: str | None) -> None:
        parts.append((points, text, len(parts)))

    tries_all = _or(_js_number(c.get("attempts_since_live")), 0)
    if not _truthy(c.get("last_live_at")):
        add(40, ("Never reached after " + plural(tries_all, "try", "tries")) if tries_all > 0 else "Never contacted")
    else:
        since = days_between(c.get("last_live_at"), today_iso)
        interval = MAINTENANCE_TOUCH_DAYS if c.get("category") == "maintenance" else 365 / freq_of(c)
        if since is not None:
            cadence = min(CADENCE_CAP, js_round(30 * since / interval))
            need = "needs " + js_str(touches_needed(c)) + " a year"
            if cadence > 0:
                add(cadence, "Last live talk " + ago_text(since) + "; " + need)

    # A date on or before the last live talk was met by that talk: it never adds points again.
    last_live = biz_date_of(c.get("last_live_at"))
    dates = sorted(str(x) for x in (c.get("promised_date"), c.get("next_step_date"))
                   if _truthy(x) and not (last_live and last_live >= biz_date_of(x)))
    if dates:
        d = dates[0]
        promised = d == c.get("promised_date")
        gap = days_between(today_iso, d)
        what = "Promised a call by " if promised else "Next step due "
        if gap is not None and gap <= 0:
            add(50, what + short_date(d))
        elif gap is not None and gap <= 7:
            add(25, what + short_date(d))

    if _truthy(c.get("last_quote_date")):
        q = days_between(c.get("last_quote_date"), today_iso)
        # Worded as a sign of an active account, never as a quote to chase: quote follow-up stays
        # in the proposal tool and the portal.
        if q is not None and 0 <= q <= 30:
            add(15, "Recent quote activity (" + short_date(c.get("last_quote_date")) + ")")

    imp = _or(_js_number(c.get("importance")), 1)
    # Importance 2 adds points but no words: "Important account" on half the cards says nothing.
    if imp >= 3:
        add(20, "Key account")
    elif imp == 2:
        add(10, None)

    tries = min(3, tries_all)
    if tries > 0:
        add(5 * tries, (plural(tries_all, "try", "tries") + " since the last live talk")
            if _truthy(c.get("last_live_at")) else None)

    if c.get("confirmed") is False:
        add(8, "Needs confirming: still the right person?")

    total = 0
    for p in parts:
        total += p[0]
    worded = sorted((p for p in parts if p[1]), key=lambda p: (-p[0], p[2]))
    reasons = [p[1] for p in worded]

    excluded, why = False, None
    if _truthy(c.get("archived_at")):
        excluded, why = True, "archived"
    elif _truthy(c.get("has_open_task")):
        excluded, why = True, "already in this week's list"
    elif _truthy(c.get("last_attempt_at")):
        gap = days_between(c.get("last_attempt_at"), today_iso)
        if gap is not None and gap < ATTEMPT_COOLDOWN_DAYS:
            excluded, why = True, "tried in the last 3 days"
    if not excluded and c.get("category") == "maintenance" and not _truthy(c.get("maintenance_due")):
        excluded, why = True, "maintenance, not due yet"
    return {"score": _plain(total), "reasons": reasons, "excluded": excluded, "exclude_reason": why}


def maintenance_due_reason(contact: Any, today: Any) -> str:
    """BDCore.maintenanceDueReason: why a due maintenance contact is on the list, the first of its
    reasons: "No follow-up logged yet" | "Follow-up due today" | "Follow-up was due Fri, Nov 6"."""
    if today is None:
        raise ValueError("maintenance_due_reason() needs today's Central date")
    today_iso = today.isoformat() if isinstance(today, _dt.date) else str(today)[:10]
    c = contact or {}
    due = biz_date_of(c.get("maintenance_due_date"))
    if not _truthy(c.get("last_followup_at")) or not due:
        return "No follow-up logged yet"
    if due == today_iso:
        return "Follow-up due today"
    return "Follow-up was due " + short_date(due)


def reason_text(reasons: Any) -> str:
    """BDCore.reasonText: the top two reasons, each ending as a sentence, joined by a space."""
    return " ".join(r if _SENTENCE_END.search(r) else r + "." for r in list(reasons or [])[:2])
