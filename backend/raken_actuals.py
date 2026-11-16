"""Plan vs Actual, the Raken side (#782, #783): what Raken's time cards recorded for each listed job,
and the Budget pair from Raken's production insights.

backend/plan_vs_actual.py builds each Project's plan from the Treadwell Projects calendar. This
module reads Raken when someone presses "Refresh now", keeps that read on the data volume, and sets
it beside the plan on every GET. A GET never calls Raken. The words are GLOSSARY.md's: Job number,
Workday, Actual hours, Days clocked in, On site, Behind, Not linked, In Raken, not on the calendar,
Budgeted hours, Projected total hours, Over/under, Over budget, On plan.

WHAT IS READ (developer.rakenapp.com/api/docs, "List Projects", "List Time Cards" and "Get
Production Insights for a Project", read 2026-11-16, with Raken's Postman collection). Every call
goes through raken.get / raken.list_all: one call at a time, a fixed pause,
a bounded 429 back-off, NotProvisioned for 403 API_KEY_NOT_FOUND. One refresh asks for no page once
CALL_CAP calls have been made since it began, /projects included (raken.list_all's stop_at_calls;
the last page's own 429 retries can pass it by two or three). A listing that would need more, or
more than raken's page cap, fails the whole refresh with TOO_MANY_MESSAGE and keeps the last good
read: part of a read would undercount Actual hours and show jobs Behind that are not. Each run logs
how many calls it made. A refresh within REFRESH_COOLDOWN_S of the last good one does not read
Raken again (plan_vs_actual.refresh), since the daily allowance is the whole company's.
  * GET /projects with statuses ACTIVE and INACTIVE (a job finished last week may already be set
    Inactive), every page. A project's Project Number is its "number" field; its "uuid" and
    "name" are kept too. Raken's own `query` search is a substring match, so it is not used: the
    tool compares numbers itself.
  * GET /timeCards with fromDate and toDate (yyyy-MM-dd), which Raken caps at 31 days apart, so
    the span is read in back-to-back pieces of PIECE_DAYS days, each piece page by page. No project
    filter: one read serves every job and the Raken-only section. Approved and unapproved cards are
    both counted (the card's "approved" is not read); a card with "deletedAt" set is skipped. A
    card's day is its "date", its worker "worker"."uuid", its project "project"."uuid", and its
    hours "totalHours", else the sum of its "timeEntries"[]."hours". Work logs are never read: they
    repeat the same hours.
  * GET /projects/{uuid}/productionInsights (#783, "Get Production Insights for a Project"), once
    for every Raken project linked to a listed row, every page. No fromDate/toDate (Raken then
    takes the whole job, project start to today), and manualTracking only when
    INSIGHTS_MANUAL_TRACKING says so. Each item is a cost-code division; its "budgetedHours" and
    "projectedTotalHours" are added up over every page of the one read, so the two figures never
    drift. Its "costCodes" are never added too: they make up the division's figures. Raken's
    /budgets is not used. One project's insights failing (an error answer, an unreadable body)
    leaves that project "not read" and the refresh goes on; the sign-in, the account, the call
    cap, a 429 that persisted or the daily quota stop the whole refresh as on any other call.
  The paging envelope is {"page": {..., "nextOffset": "10"}, "collection": [...]}; the docs' example
  gives nextOffset as a STRING. These field names come from the docs and their example responses;
  they are NOT yet checked against a live response, because Raken has not turned its Public API on
  for Treadwell's account (raken.NOT_PROVISIONED_MESSAGE). The first real refresh should be checked
  against Raken's own screens.

THE SPAN. From the earliest Start among the listed Projects (capped at READ_BACK_DAYS before today),
or RECENT_DAYS before today if that is earlier (the Raken-only section needs the last RECENT_DAYS),
through YESTERDAY in Central. When the calendar could not be read, there are no listed Projects to
say how far back, so the span reaches back at least as far as the kept read did: a refresh during a
Google outage never shrinks the numbers already on screen.

WHAT IS KEPT (STORE_FILE, through atomic_json.write_json, so a restart keeps it): the Raken
projects (uuid, name, number), and for each project each day's hours and the distinct workers who
had hours that day; the span read; each linked project's Budgeted hours and Projected total hours
(both None when Raken has no budget for it, {"failed": true} when they could not be read); and when
it was read, in Central. A failed refresh keeps the last good read and records why (one of
raken.py's fixed messages), so the page can say how old the numbers are.

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
  * the Budget pair: Budgeted hours and Projected total hours added up over the row's Raken
    projects that have a budget, and Over/under = Budgeted - Projected total. "none" when none has
    a budget (no figures, never Over budget); "not_read" when any of them was not read.
    projection_below_actual when the projection is below the Actual hours: Raken projects only the
    work in its budget, while every time card counts as Actual hours;
  * statuses are flags: ["not_linked"] alone; else "behind" when days clocked in < days booked and
    "over_budget" when Over/under < 0, both when both; ["on_plan"] when neither.
  * Raken-only: Raken projects with hours in the last RECENT_DAYS of the read whose project is not
    linked to any listed row and whose number is the Job number of no job on the calendar (the
    year read, not only the listed rows).
  * When the figures cannot be worked out, unavailable() answers the same block, saying so.

SECRETS AND LOGS. Nothing read from a Raken response is ever logged or worded into a message (CodeQL
py/clear-text-logging-sensitive-data): log lines carry literal text and counts only, and names reach
the page as data, worded there.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import math
import os
import re
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
# The most Raken calls one refresh may make, /projects, /timeCards and productionInsights together.
# A year of time cards is 12 pieces of a few pages each, which 300 covered (#782). The Budget pair
# (#783) adds one productionInsights call per linked Raken project (a page holds 100 divisions, so
# one page each): the 14-day window lists tens of jobs, not a hundred, so 100 more is room enough.
# A read that needs more than this stops plainly instead of spending the company's daily allowance.
CALL_CAP = 400
# Raken's production insights take manualTracking (true/false; Raken's own default is false, the
# automatic tracking from materials installed). None sends nothing, so Raken uses its default. Which
# mode matches Raken's own Insights screen is to be settled on one real job once Raken's Public API
# is on (#781); set True or False here then. (The docs give true/false; Raken's Postman collection
# shows manualTracking=no. The first real job settles which spelling Raken takes, too.)
INSIGHTS_MANUAL_TRACKING: Optional[bool] = None
# How long after a good read "Refresh now" answers from it instead of reading Raken again.
REFRESH_COOLDOWN_S = 10 * 60
TOO_MANY_MESSAGE = "Raken has more time cards than one refresh reads. Ask for the limit to be raised."
# When the kept read cannot be set beside the calendar rows. A fixed sentence about Raken's side.
NOT_SHOWN_MESSAGE = "Raken's numbers could not be shown just now."
# The only sentences a failure may carry to the page: raken.py's fixed messages and this module's.
# A RakenError whose text is not one of these is shown as raken.UNREACHABLE_MESSAGE, so no text
# from a response can ever reach a message (CodeQL py/clear-text-logging-sensitive-data).
_FIXED = (TOO_MANY_MESSAGE, raken.UNREACHABLE_MESSAGE, raken.RATE_LIMITED_MESSAGE, raken.QUOTA_MESSAGE,
          raken.NOT_SAVED_MESSAGE, raken.NOT_CONNECTED_MESSAGE, raken.NOT_SET_UP_MESSAGE)

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
STATUS_OVER_BUDGET = "over_budget"
STATUS_ON_PLAN = "on_plan"
STATUS_NOT_LINKED = "not_linked"
STATUSES = (STATUS_BEHIND, STATUS_OVER_BUDGET, STATUS_ON_PLAN, STATUS_NOT_LINKED)

# A linked row's Budget pair (#783): shown; none (Raken has no budget for the job); not read (its
# insights could not be read, or the kept read is older than the Budget pair or the link).
BUDGET_SHOWN = "shown"
BUDGET_NONE = "none"
BUDGET_NOT_READ = "not_read"
BUDGET_STATES = (BUDGET_SHOWN, BUDGET_NONE, BUDGET_NOT_READ)

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
    """A finite number, or None. NaN and Infinity (JSON's literals, the strings, an overflowing
    "1e999") are no figure: JSON cannot carry them, and the kept file would keep them."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        n = float(v.strip() if isinstance(v, str) else v)
    except (ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


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


def read_projects(stop_at_calls: int) -> List[Dict[str, Any]]:
    out = []
    for p in raken.list_all("/projects", {"statuses": ["ACTIVE", "INACTIVE"]},
                            stop_at_calls=stop_at_calls, whole=True):
        uuid = _text(p.get("uuid"))
        if uuid:
            out.append({"uuid": uuid, "name": _text(p.get("name")),
                        "number": _text(p.get("number"))})
    return out


def read_time_cards(first: _dt.date, last: _dt.date,
                    stop_at_calls: int) -> Dict[str, Dict[str, Any]]:
    """{project uuid: {day: {"h": hours, "w": [worker uuids]}}} for [first, last]."""
    lo, hi = first.isoformat(), last.isoformat()
    seen: Set[str] = set()
    days: Dict[str, Dict[str, Dict[str, Any]]] = {}
    workers: Dict[Tuple[str, str], Set[str]] = {}
    for a, b in pieces(first, last):
        for c in raken.list_all("/timeCards", {"fromDate": a.isoformat(), "toDate": b.isoformat()},
                                stop_at_calls=stop_at_calls, whole=True):
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
    return days


def read_insights(uuid: str, stop_at_calls: int) -> Dict[str, Optional[float]]:
    """One project's Budgeted hours and Projected total hours: the sums of its divisions'
    budgetedHours and projectedTotalHours across every page of ONE read, so the two never drift.
    Both None when Raken has no budget for it: no division with budgeted hours above zero, or none
    carrying a projected total (Raken projects only against a budget). The divisions' own figures
    are read, never their costCodes' (which add up to them)."""
    params: Dict[str, Any] = {}
    if INSIGHTS_MANUAL_TRACKING is not None:
        params["manualTracking"] = "true" if INSIGHTS_MANUAL_TRACKING else "false"
    budgeted = projected = 0.0
    projected_seen = False
    for d in raken.list_all("/projects/%s/productionInsights" % uuid, params,
                            stop_at_calls=stop_at_calls, whole=True):
        b, p = _number(d.get("budgetedHours")), _number(d.get("projectedTotalHours"))
        if b is not None and b > 0:
            budgeted += b
        if p is not None:
            projected += max(p, 0.0)
            projected_seen = True
    if budgeted <= 0 or not projected_seen:
        return {"budgeted_hours": None, "projected_total_hours": None}
    return {"budgeted_hours": round(budgeted, 2), "projected_total_hours": round(projected, 2)}


# A Raken id as it may go into an address: letters, digits and hyphens (a UUID), nothing else.
_ID_SHAPE = re.compile(r"[A-Za-z0-9-]{1,64}")


def _stops_the_refresh(exc: raken.RakenError) -> bool:
    """A failure that must stop the whole refresh rather than only the one project's insights: the
    sign-in, the account, the call cap, a rate limit that persisted or the daily quota."""
    return isinstance(exc, (raken.SignInExpired, raken.NotProvisioned, raken.ListingTooLong)) \
        or exc.status == 429


def read_all_insights(uuids: Iterable[str], stop_at_calls: int) -> Dict[str, Dict[str, Any]]:
    """{project uuid: read_insights(...)}, or {"failed": True} for a project whose insights could
    not be read (its row's Budget pair then reads "not read"). One at a time, in a fixed order."""
    out: Dict[str, Dict[str, Any]] = {}
    failed = 0
    for uuid in sorted(set(uuids)):
        if not _ID_SHAPE.fullmatch(uuid):
            # The id goes into the address: one with "/", "?" or ".." could point elsewhere.
            out[uuid] = {"failed": True}
            failed += 1
            continue
        try:
            out[uuid] = read_insights(uuid, stop_at_calls)
        except raken.RakenError as exc:
            if _stops_the_refresh(exc):
                raise
            out[uuid] = {"failed": True}
            failed += 1
    if failed:
        # A count only: which project, and what Raken answered, never reach the log.
        log.warning("raken actuals: production insights not read for %d project(s)", failed)
    return out


def span(listed: Iterable[Dict[str, Any]], today: _dt.date,
         keep_last: bool = False) -> Tuple[_dt.date, _dt.date]:
    """The days the refresh reads: from the earliest listed Start (no further back than
    READ_BACK_DAYS), or RECENT_DAYS back if that is earlier, through yesterday. With `keep_last`
    (the calendar could not be read, so `listed` says nothing), from no later than the kept read's
    first day either."""
    floor = today - _dt.timedelta(days=READ_BACK_DAYS)
    first = today - _dt.timedelta(days=RECENT_DAYS)
    starts = [p.get("start") for p in listed]
    if keep_last:
        starts.append((load().get("result") or {}).get("read_from"))
    for s in starts:
        try:
            first = min(first, _dt.date.fromisoformat(str(s)))
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
        # A save that landed while the file was being read is newer than what was read: keep it.
        if not _MEMO["loaded"]:
            _MEMO["loaded"], _MEMO["store"] = True, store
        return dict(_MEMO["store"])


def _save(store: Dict[str, Any]) -> None:
    """Keep it in memory, then on the volume. A volume that cannot be written is logged; the
    result still serves until a restart."""
    with _LOCK:
        _MEMO["loaded"], _MEMO["store"] = True, dict(store)
    try:
        write_json(STORE_FILE, {"version": 1, **store})
    except OSError as exc:
        log.warning("raken actuals: the result could not be saved (%s)", type(exc).__name__)


def _insight_uuids(rows: Iterable[Dict[str, Any]], projects: List[Dict[str, Any]],
                   keep_last: bool, store: Dict[str, Any]) -> Set[str]:
    """The Raken projects whose production insights a refresh reads: every project linked to a
    listed row (a Punch's own included), as apply() links them. With `keep_last` (the calendar could
    not be read, so there are no rows), the projects the kept read had insights for, still known."""
    index = _by_number(projects)
    out: Set[str] = set()
    for r in rows:
        out.update(p["uuid"] for p in _linked(r, index) or [])
    if keep_last:
        known = {p["uuid"] for p in projects}
        kept = (store.get("result") or {}).get("insights")
        out.update(u for u in (kept if isinstance(kept, dict) else {}) if u in known)
    return out


def read_and_keep(first: _dt.date, last: _dt.date, rows: Iterable[Dict[str, Any]] = (),
                  keep_last: bool = False) -> None:
    """Read Raken over [first, last], and the production insights of every Raken project linked to
    one of `rows`, and keep the result, or keep why it failed. Never raises."""
    before = raken.calls_made()
    stop_at = before + CALL_CAP
    store = load()
    try:
        projects = read_projects(stop_at)
        days = read_time_cards(first, last, stop_at)
        insights = read_all_insights(_insight_uuids(rows, projects, keep_last, store), stop_at)
    except raken.SignInExpired:
        # raken.py has marked the stored sign-in expired; the page reads that from the file, so no
        # failure is recorded here (it would outlive a new Connect Raken). The last numbers stay.
        log.warning("raken actuals: refresh stopped, the sign-in has expired")
        return
    except raken.NotProvisioned:
        _fail(store, STATE_NOT_PROVISIONED, raken.NOT_PROVISIONED_MESSAGE)
        log.warning("raken actuals: refresh stopped, Raken's Public API is not on for the account")
        return
    except raken.ListingTooLong:
        _fail(store, STATE_UNREACHABLE, TOO_MANY_MESSAGE)
        log.warning("raken actuals: refresh stopped at the cap of %d calls or the page cap, "
                    "after %d calls", CALL_CAP, raken.calls_made() - before)
        return
    except raken.RakenError as exc:
        # exc.message is one of raken.py's fixed sentences, never text from a response.
        msg = exc.message if exc.message in _FIXED else raken.UNREACHABLE_MESSAGE
        _fail(store, STATE_UNREACHABLE, msg)
        log.warning("raken actuals: refresh failed after %d calls", raken.calls_made() - before)
        return
    except Exception as exc:  # noqa: BLE001 - a refresh must never 500 the page
        _fail(store, STATE_UNREACHABLE, raken.UNREACHABLE_MESSAGE)
        log.warning("raken actuals: refresh failed (%s)", type(exc).__name__)
        return
    result = {"as_of": _central_stamp(), "read_from": first.isoformat(),
              "through": last.isoformat(), "projects": projects, "days": days,
              "insights": insights}
    _save({"result": result, "failure": None})
    # Counts of pieces, projects and calls only: nothing derived from the response is logged.
    log.info("raken actuals: refresh read %d pieces and %d projects' insights in %d calls",
             len(pieces(first, last)), len(insights), raken.calls_made() - before)


def fresh() -> bool:
    """True when the kept read is a good one taken less than REFRESH_COOLDOWN_S ago, so a refresh
    now would spend Raken's shared allowance to read the same numbers again."""
    store = load()
    result = store.get("result")
    if store.get("failure") or not isinstance(result, dict):
        return False
    try:
        at = _dt.datetime.fromisoformat(str(result.get("as_of")))
    except ValueError:
        return False
    if at.tzinfo is None:
        return False
    return 0 <= (now_utc() - at).total_seconds() < REFRESH_COOLDOWN_S


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
    linked = _linked(row, index)
    if linked is None:
        found = index.get(number) or []
        side: Dict[str, Any] = {"state": STATE_NOT_LINKED,
                                "reason": REASON_DUPLICATE if found else REASON_NO_RAKEN_PROJECT}
        if found:
            side["duplicates"] = [_public(p) for p in found]
        return side, [STATUS_NOT_LINKED], {p["uuid"] for p in found}
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
    actual = round(sum(hours.values()), 2)
    side = {"state": STATE_LINKED, "projects": [_public(p) for p in linked],
            "days_booked": len(booked), "days_clocked": len(clocked), "avg_on_site": avg,
            "actual_hours": actual, "through": hi_s}
    side.update(_budget(uuids, result, actual))
    statuses = []
    if len(clocked) < len(booked):
        statuses.append(STATUS_BEHIND)
    if side["over_under"] is not None and side["over_under"] < 0:
        statuses.append(STATUS_OVER_BUDGET)
    return side, statuses or [STATUS_ON_PLAN], uuids


def _linked(row: Dict[str, Any], index: Dict[str, List[Dict[str, Any]]]
            ) -> Optional[List[Dict[str, Any]]]:
    """The Raken projects a row links to, its own first, or None when it is Not linked: no Job
    number, no Raken project carrying it, or two. A Punch's hours count toward its parent, so a
    Punch carrying a Job number of its own brings the one Raken project with that number."""
    number = (row.get("job_number") or "").strip()
    found = (index.get(number) or []) if number else []
    if len(found) != 1:
        return None
    linked = [found[0]]
    for punch in row.get("punches") or []:
        n = (punch.get("job_number") or "").strip()
        extra = (index.get(n) or []) if n and n != number else []
        if len(extra) == 1 and extra[0] not in linked:
            linked.append(extra[0])
    return linked


def _budget(uuids: Set[str], result: Dict[str, Any], actual: float) -> Dict[str, Any]:
    """A linked row's Budget pair from the kept insights of its Raken projects: Budgeted hours,
    Projected total hours and Over/under (Budgeted - Projected total), each added up over the
    projects that have a Raken budget. Not read when any of them was not read (the figures would
    be part of the job's); none when none has a budget. `projection_below_actual` when the
    projection is below the time-card Actual hours: Raken projects only the work in its budget."""
    kept = result.get("insights")
    kept = kept if isinstance(kept, dict) else {}
    out: Dict[str, Any] = {"budget": BUDGET_NONE, "budgeted_hours": None,
                           "projected_total_hours": None, "over_under": None,
                           "projection_below_actual": False}
    budgeted = projected = 0.0
    shown = False
    for u in uuids:
        got = kept.get(u)
        if not isinstance(got, dict) or got.get("failed"):
            out["budget"] = BUDGET_NOT_READ
            return out
        b, p = _number(got.get("budgeted_hours")), _number(got.get("projected_total_hours"))
        if b is not None and p is not None:
            budgeted, projected, shown = budgeted + b, projected + p, True
    if shown:
        out.update(budget=BUDGET_SHOWN, budgeted_hours=round(budgeted, 2),
                   projected_total_hours=round(projected, 2),
                   over_under=round(budgeted - projected, 2),
                   projection_below_actual=round(projected, 2) < actual)
    return out


def _block(state: str, message: Optional[str]) -> Dict[str, Any]:
    """The response's Raken block, before any read is set in it. The one place its shape is made.
    `refreshing` is set by plan_vs_actual while a "Refresh now" is running."""
    return {"state": state, "message": message, "as_of": None, "through": None,
            "read_from": None, "stale": False, "refreshing": False}


def _without_numbers(rows: List[Dict[str, Any]], block: Dict[str, Any]) -> Dict[str, Any]:
    for r in rows:
        r["raken"] = {"state": block["state"]}
        r["statuses"] = []
    return {"raken": block, "raken_only": []}


def unavailable(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What apply() answers when the figures could not be worked out: every row and the block say
    so, in the same shape, with NOT_SHOWN_MESSAGE."""
    return _without_numbers(rows, _block(STATE_UNREACHABLE, NOT_SHOWN_MESSAGE))


def apply(rows: List[Dict[str, Any]], today: _dt.date,
          calendar_numbers: Iterable[str] = ()) -> Dict[str, Any]:
    """Fill every row's "raken" and "statuses" from the kept result. Answers the response's Raken
    block and the Raken-only list: {"raken": {...}, "raken_only": [...]}. `calendar_numbers` are
    the Job numbers of every job on the calendar read, listed or not: none of them is Raken-only."""
    state, message = connection()
    store = load() if state == STATE_CONNECTED else {"result": None, "failure": None}
    result, failure = store.get("result"), store.get("failure")
    block = _block(state, message)
    if state == STATE_CONNECTED and result is None:
        if failure:
            block["state"], block["message"] = failure.get("state"), failure.get("message")
            if block["state"] not in ROW_STATES:
                block["state"] = STATE_UNREACHABLE
        else:
            block["state"] = STATE_NOT_REFRESHED
    if state != STATE_CONNECTED or result is None:
        return _without_numbers(rows, block)

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
    numbers: Set[str] = {str(n).strip() for n in calendar_numbers if n and str(n).strip()}
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
