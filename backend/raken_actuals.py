"""Plan vs Actual, the Raken side (#782): what Raken's time cards recorded for each listed job.

backend/plan_vs_actual.py builds each Project's plan from the Treadwell Projects calendar. This
module reads Raken when someone presses "Refresh now", keeps that read on the data volume, and sets
it beside the plan on every GET. A GET never calls Raken. The words are GLOSSARY.md's: Job number,
Workday, Actual hours, Behind, Not linked.

WHAT IS READ (developer.rakenapp.com/api/docs, "List Projects" and "List Time Cards", read
2026-11-16). Every call goes through raken.get / raken.list_all: one call at a time, a fixed pause,
a bounded 429 back-off, NotProvisioned for 403 API_KEY_NOT_FOUND. One refresh makes at most CALL_CAP
calls, and each run logs how many it made.
  * GET /projects: every page. A project's Project Number is its "number" field; its "uuid" and
    "name" are kept too. Raken's own `query` search is a substring match, so it is not used: the
    tool compares numbers itself.
  * GET /timeCards with fromDate and toDate (yyyy-MM-dd), which Raken caps at 31 days apart, so
    the span is read in back-to-back pieces of PIECE_DAYS days, each piece page by page. No project
    filter: one read serves every job and the Raken-only section. Approved and unapproved cards are
    both counted (the card's "approved" is not read); a card with "deletedAt" set is skipped. A
    card's day is its "date", its worker "worker"."uuid", its project "project"."uuid", and its
    hours "totalHours", else the sum of its "timeEntries"[]."hours". Work logs are never read: they
    repeat the same hours.
  The paging envelope is {"page": {..., "nextOffset": "10"}, "collection": [...]}; the docs' example
  gives nextOffset as a STRING. These field names come from the docs and their example responses;
  they are NOT yet checked against a live response, because Raken has not turned its Public API on
  for Treadwell's account (raken.NOT_PROVISIONED_MESSAGE). The first real refresh should be checked
  against Raken's own screens.

THE SPAN. From the earliest Start among the listed Projects (capped at READ_BACK_DAYS before today),
or RECENT_DAYS before today if that is earlier (the Raken-only section needs the last RECENT_DAYS),
through YESTERDAY in Central.

WHAT IS KEPT (STORE_FILE, through atomic_json.write_json, so a restart keeps it): the Raken
projects (uuid, name, number), and for each project each day's hours and the distinct workers who
had hours that day; the span read; and when it was read, in Central. A failed refresh keeps the
last good read and records why (one of raken.py's fixed messages), so the page can say how old the
numbers are.

THE FIGURES, worked out on every GET against the CURRENT calendar rows (apply()):
  * a row links when exactly one Raken project's number, trimmed, equals its Job number. No Job
    number, no such project, or two of them: Not linked (reason "no_job_number", "no_raken_project"
    or "duplicate", the duplicates named). A Not linked row has no other status;
  * a Punch's hours count toward its parent: a Punch in the row that carries a Job number of its
    own adds the one Raken project carrying that number;
  * days booked = the row's Workdays so far, cut to the days the read covered (so a read from an
    earlier day never counts a day it did not read as missed); days clocked in = those days with any
    hours; average on site = the distinct workers on each of those days, added up, divided by the
    days clocked in; Actual hours = every hour read up to the read's last day;
  * statuses: ["not_linked"], or ["behind"] when days clocked in < days booked, else []. A list,
    so a later ticket can add Over budget beside Behind.
  * Raken-only: Raken projects with hours in the last RECENT_DAYS of the read whose project is not
    linked to any listed row and whose number is no listed row's Job number.

SECRETS AND LOGS. Nothing read from a Raken response is ever logged or worded into a message (CodeQL
py/clear-text-logging-sensitive-data): log lines carry literal text and counts only, and names reach
the page as data, worded there.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import project_calendar as pc
import raken
from atomic_json import write_json

log = logging.getLogger("treadwell.raken_actuals")

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
STORE_FILE = _DATA_DIR / "raken_actuals.json"

PIECE_DAYS = 31            # Raken caps fromDate at 31 days before toDate; a piece spans 31 days
READ_BACK_DAYS = 365
RECENT_DAYS = 14
# The most Raken calls one refresh may make. A year of time cards is 12 pieces of a few pages each;
# a read that needs more than this stops plainly instead of spending the company's daily allowance.
CALL_CAP = 300
TOO_MANY_MESSAGE = "Raken has more time cards than one refresh reads. Ask for the limit to be raised."

# A row's Raken state. The page names the same values (js/project-calendar-core.js, P.RAKEN);
# tests/test_project_calendar_core_js.py holds the two sides together.
STATE_NOT_CONNECTED = raken.STATE_NOT_CONNECTED     # also: not set up on this server
STATE_EXPIRED = raken.STATE_EXPIRED
STATE_NOT_PROVISIONED = raken.STATE_NOT_PROVISIONED
STATE_UNREACHABLE = "unreachable"                     # also: rate limited, daily quota used up
STATE_NOT_REFRESHED = "not_refreshed"                 # connected, never read yet
STATE_LINKED = "linked"
STATE_NOT_LINKED = "not_linked"
ROW_STATES = (STATE_NOT_CONNECTED, STATE_EXPIRED, STATE_NOT_PROVISIONED, STATE_UNREACHABLE,
              STATE_NOT_REFRESHED, STATE_LINKED, STATE_NOT_LINKED)
# The response's own Raken state: the connection's, or this when the numbers are there to show.
STATE_CONNECTED = raken.STATE_CONNECTED

STATUS_BEHIND = "behind"
STATUS_NOT_LINKED = "not_linked"
STATUSES = (STATUS_BEHIND, STATUS_NOT_LINKED)

REASON_NO_JOB_NUMBER = "no_job_number"
REASON_NO_RAKEN_PROJECT = "no_raken_project"
REASON_DUPLICATE = "duplicate"

_DAY = _dt.timedelta(days=1)

# Replaced by tests.
def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


# ─── reading Raken ────────────────────────────────────────────────────────────
def pieces(first: _dt.date, last: _dt.date) -> List[Tuple[_dt.date, _dt.date]]:
    """Back-to-back inclusive pieces of at most PIECE_DAYS days covering [first, last]."""
    out = []
    cur = first
    while cur <= last:
        end = min(cur + _dt.timedelta(days=PIECE_DAYS - 1), last)
        out.append((cur, end))
        cur = end + _DAY
    return out


def _text(v: Any) -> Optional[str]:
    s = str(v).strip() if isinstance(v, (str, int, float)) else ""
    return s or None


def _number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _hours(c: Dict[str, Any]) -> float:
    total = _number(c.get("totalHours"))
    if total is not None:
        return max(total, 0.0)
    entries = c.get("timeEntries")
    s = 0.0
    for e in entries if isinstance(entries, list) else []:
        h = _number(e.get("hours")) if isinstance(e, dict) else None
        if h is not None and h > 0:
            s += h
    return s


def _uuid_of(obj: Any) -> Optional[str]:
    return _text(obj.get("uuid")) if isinstance(obj, dict) else None


def read_projects() -> List[Dict[str, Any]]:
    out = []
    for p in raken.list_all("/projects"):
        uuid = _text(p.get("uuid"))
        if uuid:
            out.append({"uuid": uuid, "name": _text(p.get("name")),
                        "number": _text(p.get("number"))})
    return out


def read_time_cards(first: _dt.date, last: _dt.date) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """{project uuid: {day: {"h": hours, "w": [worker uuids]}}} for [first, last], and the number
    of cards counted."""
    lo, hi = first.isoformat(), last.isoformat()
    seen: Set[str] = set()
    days: Dict[str, Dict[str, Dict[str, Any]]] = {}
    workers: Dict[Tuple[str, str], Set[str]] = {}
    counted = 0
    start_calls = raken._CALLS["n"]
    for a, b in pieces(first, last):
        if raken._CALLS["n"] - start_calls >= CALL_CAP:
            log.warning("raken actuals: refresh stopped at the cap of %d calls", CALL_CAP)
            raise raken.RakenError(TOO_MANY_MESSAGE)
        for c in raken.list_all("/timeCards", {"fromDate": a.isoformat(), "toDate": b.isoformat()}):
            if c.get("deletedAt"):
                continue
            cid = _text(c.get("uuid"))
            if cid:
                if cid in seen:
                    continue             # a card a piece's edge returned twice
                seen.add(cid)
            proj = _uuid_of(c.get("project"))
            day = str(c.get("date") or "")[:10]
            try:
                _dt.date.fromisoformat(day)
            except ValueError:
                continue
            hours = _hours(c)
            if not proj or not (lo <= day <= hi) or hours <= 0:
                continue
            counted += 1
            slot = days.setdefault(proj, {}).setdefault(day, {"h": 0.0, "w": []})
            slot["h"] += hours
            who = _uuid_of(c.get("worker"))
            if who:
                workers.setdefault((proj, day), set()).add(who)
    for (proj, day), ws in workers.items():
        days[proj][day]["w"] = sorted(ws)
    for per_day in days.values():
        for slot in per_day.values():
            slot["h"] = round(slot["h"], 2)
    return days, counted


def span(listed: Iterable[Dict[str, Any]], today: _dt.date) -> Tuple[_dt.date, _dt.date]:
    """The days the refresh reads: from the earliest listed Start (no further back than
    READ_BACK_DAYS), or RECENT_DAYS back if that is earlier, through yesterday."""
    floor = today - _dt.timedelta(days=READ_BACK_DAYS)
    first = today - _dt.timedelta(days=RECENT_DAYS)
    for p in listed:
        try:
            first = min(first, _dt.date.fromisoformat(str(p.get("start"))))
        except ValueError:
            continue
    return max(first, floor), today - _DAY


# ─── the kept result ──────────────────────────────────────────────────────────
_LOCK = threading.Lock()
_MEMO: Dict[str, Any] = {"loaded": False, "store": {}}


def _central_stamp() -> str:
    return now_utc().astimezone(pc.CENTRAL).replace(microsecond=0).isoformat()


def load() -> Dict[str, Any]:
    """{"result": {...} or None, "failure": {...} or None}: memory first, else the file."""
    with _LOCK:
        if _MEMO["loaded"]:
            return dict(_MEMO["store"])
    try:
        data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        log.warning("raken actuals: the kept result is unreadable (%s)", type(exc).__name__)
        data = {}
    store = {"result": data.get("result") if isinstance(data, dict) else None,
             "failure": data.get("failure") if isinstance(data, dict) else None}
    if not isinstance(store["result"], dict):
        store["result"] = None
    if not isinstance(store["failure"], dict):
        store["failure"] = None
    with _LOCK:
        _MEMO["loaded"], _MEMO["store"] = True, store
    return dict(store)


def _save(store: Dict[str, Any]) -> None:
    """Keep it in memory, then on the volume. A volume that cannot be written is logged; the
    result still serves until a restart."""
    with _LOCK:
        _MEMO["loaded"], _MEMO["store"] = True, dict(store)
    try:
        write_json(STORE_FILE, {"version": 1, **store})
    except OSError as exc:
        log.warning("raken actuals: the result could not be saved (%s)", type(exc).__name__)


def read_and_keep(first: _dt.date, last: _dt.date) -> None:
    """Read Raken over [first, last] and keep the result, or keep why it failed. Never raises."""
    before = raken._CALLS["n"]
    store = load()
    try:
        projects = read_projects()
        days, counted = read_time_cards(first, last)
    except raken.SignInExpired:
        # raken.py has marked the stored sign-in expired; the page reads that from the file, so no
        # failure is recorded here (it would outlive a new Connect Raken). The last numbers stay.
        log.warning("raken actuals: refresh stopped, the sign-in has expired")
        return
    except raken.NotProvisioned:
        _fail(store, STATE_NOT_PROVISIONED, raken.NOT_PROVISIONED_MESSAGE)
        log.warning("raken actuals: refresh stopped, Raken's Public API is not on for the account")
        return
    except raken.RakenError as exc:
        # exc.message is one of raken.py's fixed sentences, never text from a response.
        msg = exc.message if exc.message in _FIXED else raken.UNREACHABLE_MESSAGE
        _fail(store, STATE_UNREACHABLE, msg)
        log.warning("raken actuals: refresh failed after %d calls", raken._CALLS["n"] - before)
        return
    except Exception as exc:  # noqa: BLE001 - a refresh must never 500 the page
        _fail(store, STATE_UNREACHABLE, raken.UNREACHABLE_MESSAGE)
        log.warning("raken actuals: refresh failed (%s)", type(exc).__name__)
        return
    result = {"as_of": _central_stamp(), "read_from": first.isoformat(),
              "through": last.isoformat(), "projects": projects, "days": days}
    _save({"result": result, "failure": None})
    log.info("raken actuals: read %d projects and %d time cards in %d pieces, %d calls",
             len(projects), counted, len(pieces(first, last)), raken._CALLS["n"] - before)


_FIXED = (TOO_MANY_MESSAGE, raken.UNREACHABLE_MESSAGE, raken.RATE_LIMITED_MESSAGE, raken.QUOTA_MESSAGE,
          raken.NOT_SAVED_MESSAGE, raken.NOT_CONNECTED_MESSAGE, raken.NOT_SET_UP_MESSAGE)


def _fail(store: Dict[str, Any], state: str, message: str) -> None:
    _save({"result": store.get("result"),
           "failure": {"state": state, "message": message, "at": _central_stamp()}})


def reset_for_tests() -> None:
    """Forget what is held in memory, as a restart does. The file stays."""
    with _LOCK:
        _MEMO["loaded"], _MEMO["store"] = False, {}


# ─── setting the result beside the plan ───────────────────────────────────────
def connection() -> Tuple[str, Optional[str]]:
    """(state, message) of the sign-in, from the server's own file: never a call to Raken."""
    if not raken.is_configured():
        return STATE_NOT_CONNECTED, raken.NOT_SET_UP_MESSAGE
    state = raken.signin_state()
    if state == raken.STATE_NOT_CONNECTED:
        return STATE_NOT_CONNECTED, raken.NOT_CONNECTED_MESSAGE
    if state == raken.STATE_EXPIRED:
        return STATE_EXPIRED, raken.EXPIRED_MESSAGE
    return STATE_CONNECTED, None


def _workdays(first: _dt.date, last: _dt.date) -> List[str]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _DAY
    return out


def _booked(row: Dict[str, Any], lo: _dt.date, hi: _dt.date) -> Set[str]:
    """The row's booked Workdays inside [lo, hi]."""
    out: Set[str] = set()
    for m in list(row.get("mobilizations") or []) + list(row.get("punches") or []):
        try:
            a = max(_dt.date.fromisoformat(m["start"]), lo)
            b = min(_dt.date.fromisoformat(m["last_day"]), hi)
        except (KeyError, TypeError, ValueError):
            continue
        out.update(_workdays(a, b))
    return out


def _by_number(projects: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for p in projects:
        n = (p.get("number") or "").strip()
        if n:
            out.setdefault(n, []).append(p)
    return out


def _public(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"uuid": p.get("uuid"), "name": p.get("name"), "number": p.get("number")}


def _row(row: Dict[str, Any], result: Dict[str, Any], index: Dict[str, List[Dict[str, Any]]],
         lo: _dt.date, hi: _dt.date) -> Tuple[Dict[str, Any], List[str], Set[str]]:
    """(the row's Raken side, its statuses, the Raken projects it took)."""
    number = (row.get("job_number") or "").strip()
    if not number:
        return {"state": STATE_NOT_LINKED, "reason": REASON_NO_JOB_NUMBER}, [STATUS_NOT_LINKED], set()
    found = index.get(number) or []
    if len(found) != 1:
        side: Dict[str, Any] = {"state": STATE_NOT_LINKED,
                                "reason": REASON_DUPLICATE if found else REASON_NO_RAKEN_PROJECT}
        if found:
            side["duplicates"] = [_public(p) for p in found]
        return side, [STATUS_NOT_LINKED], {p["uuid"] for p in found}
    linked = [found[0]]
    # A Punch's hours count toward its parent: a Punch carrying a Job number of its own brings the
    # one Raken project with that number.
    for punch in row.get("punches") or []:
        n = (punch.get("job_number") or "").strip()
        extra = (index.get(n) or []) if n and n != number else []
        if len(extra) == 1 and extra[0] not in linked:
            linked.append(extra[0])
    uuids = {p["uuid"] for p in linked}
    days = result.get("days") or {}
    hours: Dict[str, float] = {}
    workers: Dict[str, Set[str]] = {}
    lo_s, hi_s = lo.isoformat(), hi.isoformat()
    for u in uuids:
        for day, slot in (days.get(u) or {}).items():
            if not (lo_s <= day <= hi_s) or not isinstance(slot, dict):
                continue
            hours[day] = hours.get(day, 0.0) + float(slot.get("h") or 0)
            workers.setdefault(day, set()).update(slot.get("w") or [])
    booked = _booked(row, lo, hi)
    clocked = sorted(d for d in booked if hours.get(d, 0) > 0)
    avg = (round(sum(len(workers.get(d, ())) for d in clocked) / len(clocked), 1)
           if clocked else None)
    side = {"state": STATE_LINKED, "projects": [_public(p) for p in linked],
            "days_booked": len(booked), "days_clocked": len(clocked), "avg_on_site": avg,
            "actual_hours": round(sum(hours.values()), 2), "through": hi_s}
    return side, ([STATUS_BEHIND] if len(clocked) < len(booked) else []), uuids


def apply(rows: List[Dict[str, Any]], today: _dt.date) -> Dict[str, Any]:
    """Fill every row's "raken" and "statuses" from the kept result. Answers the response's Raken
    block and the Raken-only list: {"raken": {...}, "raken_only": [...]}."""
    state, message = connection()
    store = load() if state == STATE_CONNECTED else {"result": None, "failure": None}
    result, failure = store.get("result"), store.get("failure")
    block: Dict[str, Any] = {"state": state, "message": message, "as_of": None, "through": None,
                             "read_from": None, "stale": False}
    if state == STATE_CONNECTED and result is None:
        if failure:
            block["state"], block["message"] = failure.get("state"), failure.get("message")
            if block["state"] not in ROW_STATES:
                block["state"] = STATE_UNREACHABLE
        else:
            block["state"] = STATE_NOT_REFRESHED
    if state != STATE_CONNECTED or result is None:
        for r in rows:
            r["raken"] = {"state": block["state"]}
            r["statuses"] = []
        return {"raken": block, "raken_only": []}

    yesterday = today - _DAY
    try:
        lo = _dt.date.fromisoformat(result["read_from"])
        hi = min(_dt.date.fromisoformat(result["through"]), yesterday)
    except (KeyError, TypeError, ValueError):
        lo, hi = yesterday, yesterday - _DAY      # an unreadable result reads as nothing
    block.update(as_of=result.get("as_of"), through=hi.isoformat(), read_from=lo.isoformat(),
                 stale=bool(failure) or hi < yesterday)
    if failure:
        block["message"] = failure.get("message")
    projects = [p for p in result.get("projects") or [] if isinstance(p, dict) and p.get("uuid")]
    index = _by_number(projects)
    taken: Set[str] = set()
    numbers: Set[str] = set()
    for r in rows:
        r["raken"], r["statuses"], used = _row(r, result, index, lo, hi)
        taken |= used
        for m in [r] + list(r.get("mobilizations") or []) + list(r.get("punches") or []):
            n = (m.get("job_number") or "").strip()
            if n:
                numbers.add(n)
    return {"raken": block, "raken_only": _raken_only(result, projects, taken, numbers, hi)}


def _raken_only(result: Dict[str, Any], projects: List[Dict[str, Any]], taken: Set[str],
                numbers: Set[str], hi: _dt.date) -> List[Dict[str, Any]]:
    recent_from = (hi - _dt.timedelta(days=RECENT_DAYS - 1)).isoformat()
    hi_s = hi.isoformat()
    known = {p["uuid"]: p for p in projects}
    out = []
    for uuid, per_day in (result.get("days") or {}).items():
        if uuid in taken or not isinstance(per_day, dict):
            continue
        p = known.get(uuid) or {"uuid": uuid, "name": None, "number": None}
        if (p.get("number") or "").strip() in numbers:
            continue
        in_range = {d: s for d, s in per_day.items() if d <= hi_s and isinstance(s, dict)}
        recent = [d for d, s in in_range.items() if d >= recent_from and float(s.get("h") or 0) > 0]
        if not recent:
            continue
        out.append(dict(_public(p),
                        actual_hours=round(sum(float(s.get("h") or 0) for s in in_range.values()), 2),
                        last_day=max(recent)))
    out.sort(key=lambda x: ((x.get("name") or "").lower(), x.get("number") or "", x["uuid"]))
    return out
