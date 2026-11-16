"""Plan vs Actual, the calendar side (#780): one row per Project, built here, laid out by the page.

Project Analytics opens on Plan vs Actual. Each row sets a job's plan from the Treadwell Projects
calendar beside what Raken recorded for it. This module builds the PLAN side; backend/raken_actuals.py
sets the last "Refresh now" read of Raken beside every row (#782): each row's "raken" and
"statuses", the response's "raken" block (state, one plain message, the "as of" time in Central)
and "raken_only". A GET never calls Raken; refresh() does, one at a time. The words are
GLOSSARY.md's: Project, Mobilization, Punch, Job number, Crew size, Foreman, Workday, Planned
hours, Deadline.

READING. The calendar is read from 365 days before today to 14 days after, through
project_calendar.read_range (its cache, its stale copies, its plain errors), in pieces of
project_calendar.MAX_SPAN_DAYS laid on a FIXED grid of days counted from GRID_ORIGIN. The pieces do
not move when the day does, so the first read of a new day finds the same cache entries as the day
before: if Google fails then, yesterday's copy is served, and the shared cache gains a new entry
only when the year reaches a new piece. The pieces cover a little more than the year, so what they
return is cut back to the year. An event that spans two pieces comes back from both and is kept once.
The calendar stays read-only and only PROJECT_CALENDAR_ID is ever read (ADR 0001): this module never
talks to Google itself.

GROUPING. Every event read is grouped into Projects, then only the Projects in the window are listed:
  * a Mobilization that is not a Punch groups by Job number, else by its name (case and spacing
    ignored);
  * a job half relabelled (#792): a group made by name joins the Job-number group whose name
    matches (case and spacing ignored), and the row is the Job number's, every Mobilization
    counted. When two Job numbers share the name, nothing is guessed: the name group stays its own
    row;
  * a Punch joins the Project with its Job number; with no Job number, or one that matches no job,
    the Project whose name equals the Punch's name with the word "Punch" removed (case and spacing
    ignored). When several Projects share that name, it joins the one whose work ended last before
    the Punch began, else the one that ends last. A Punch whose Job number matched no job may so
    join a Project grouped by name; that row then takes the Punch's Job number. A Punch that matches no
    Project is its own row, labelled Punch;
  * a Project's Start is its first non-Punch Mobilization's first day, and its Deadline the last day
    of its last non-Punch Mobilization. A Punch row's are its Punches' own.

THE WINDOW. A Project is listed when today (Central) is between its Start and Deadline, its Deadline
was in the last 14 days, its Start is in the next 14 days, or one of its Punches has a Workday within
14 days either side of today. A listed Project's figures use EVERY Mobilization read, not only the
ones inside the window.

THE FIGURES ("so far" stops at yesterday, Central, so a mid-day read never sets half a day of time
cards against a full planned day):
  * Workdays booked so far: the distinct Workdays (Monday to Friday) of its Mobilizations, Punches
    included, up to yesterday;
  * Planned hours: the sum over its Mobilizations of that Mobilization's Workdays so far x its Crew
    size x HOURS_PER_WORKDAY. A Mobilization with no Crew size adds nothing, and the row says
    "Crew size missing" (crew_size_missing) rather than counting it as nobody on site;
  * the Crew pair's plan figure: the Crew size of the Mobilization running today, else the most
    recent one to have started, else the first one still to come;
  * Workdays left: Monday to Friday from today through the Deadline while the job runs; a job not
    started is TIMING_STARTS (the page says "Starts <date>"), a finished one TIMING_FINISHED.

NEVER A 500. Not connected answers connected:false; a Google failure with nothing saved answers
ok:true, no projects and the plain error; a stale copy is served with stale:true.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

import project_calendar as pc
import raken_actuals

log = logging.getLogger("treadwell.plan_vs_actual")

ERR_BUILD = "Plan vs Actual could not be worked out just now."

READ_BACK_DAYS = 365
READ_AHEAD_DAYS = 14
# Where the grid of read pieces is counted from. Any fixed day works; it must never move with today.
GRID_ORIGIN = _dt.date(2000, 1, 1)
WINDOW_DAYS = 14
# Every Work type, Gyp included, until Operations says otherwise.
HOURS_PER_WORKDAY = 8

# The contract with the page (js/project-calendar-core.js names the same values as P.TIMING and
# P.RAKEN_NOT_CONNECTED; tests/test_project_calendar_core_js.py holds the two sides together).
# A row's timing: before its Start, between Start and Deadline, after its Deadline.
TIMING_STARTS = "starts"
TIMING_RUNNING = "running"
TIMING_FINISHED = "finished"
TIMINGS = (TIMING_STARTS, TIMING_RUNNING, TIMING_FINISHED)
# The Raken side of every row until Raken is connected: raken_actuals' own state, named once.
RAKEN_NOT_CONNECTED = raken_actuals.STATE_NOT_CONNECTED

_DAY = _dt.timedelta(days=1)
_PUNCH_WORD = re.compile(r"\bpunch\b", re.IGNORECASE)


def _raken() -> Dict[str, str]:
    """A row's Raken side as build() leaves it. _response() always overwrites it through
    raken_actuals.apply (or raken_actuals.unavailable); it is here so a row built on its own still
    has the key."""
    return {"state": RAKEN_NOT_CONNECTED}


def _response(connected: bool, today: _dt.date, projects: List[Dict[str, Any]], *,
              stale: bool = False, fetched_at: Optional[str] = None,
              error: Optional[str] = None, notice: Optional[str] = None,
              numbers: Iterable[str] = ()) -> Dict[str, Any]:
    """The whole response. The Raken side of every row, the response's Raken block (its state, one
    plain message, the "as of" time in Central, and whether a "Refresh now" is running) and the
    Raken-only list come from the last "Refresh now", set beside the rows here; Raken itself is
    never called from a GET. `numbers` are the Job numbers of every job read from the calendar."""
    first, last = read_window(today)
    try:
        side = raken_actuals.apply(projects, today, numbers)
    except Exception as exc:  # noqa: BLE001 - the calendar side must still show
        log.warning("plan vs actual: Raken side not set (%s)", type(exc).__name__)
        side = raken_actuals.unavailable(projects)
    side["raken"]["refreshing"] = _REFRESH_LOCK.locked()
    return {"ok": True, "connected": connected, "stale": stale, "fetched_at": fetched_at,
            "error": error, "notice": notice, "today": today.isoformat(),
            "so_far_through": (today - _DAY).isoformat(),
            "read_from": first.isoformat(), "read_to": last.isoformat(),
            "hours_per_workday": HOURS_PER_WORKDAY, "window_days": WINDOW_DAYS,
            "work_types": [dict(w) for w in pc.WORK_TYPE_LEGEND], "raken": side["raken"],
            "raken_only": side["raken_only"], "projects": projects}


# ─── reading ──────────────────────────────────────────────────────────────────
def read_window(today: _dt.date) -> Tuple[_dt.date, _dt.date]:
    return today - _dt.timedelta(days=READ_BACK_DAYS), today + _dt.timedelta(days=READ_AHEAD_DAYS)


def pieces(first: _dt.date, last: _dt.date) -> List[Tuple[_dt.date, _dt.date]]:
    """The grid pieces that cover [first, last]: consecutive, inclusive, MAX_SPAN_DAYS each, the
    first starting on the grid line at or before `first`. The same days always give the same
    pieces, whatever day the read starts on."""
    span = pc.MAX_SPAN_DAYS
    cur = GRID_ORIGIN + _dt.timedelta(days=((first - GRID_ORIGIN).days // span) * span)
    out = []
    while cur <= last:
        end = cur + _dt.timedelta(days=span - 1)
        out.append((cur, end))
        cur = end + _DAY
    return out


def _event_key(ev: Dict[str, Any]) -> Tuple[str, ...]:
    return ("id", ev["id"]) if ev.get("id") else ("t", ev["title"], ev["start"], ev["last_day"])


def _read_year(cal: str, source: Any, today: _dt.date) -> Dict[str, Any]:
    """Every piece read; one result as read_range gives it. `events` is None when ANY piece failed
    with nothing saved: a year with a hole in it would under-count every figure."""
    first, last = read_window(today)
    lo, hi = first.isoformat(), last.isoformat()
    seen = set()
    events: List[Dict[str, Any]] = []
    stale = False
    stamps: List[str] = []
    error: Optional[str] = None
    notice: Optional[str] = None
    for a, b in pieces(first, last):
        got = pc.read_range(cal, source, a, b)
        error = error or got["error"]
        notice = notice or got["notice"]
        if got["events"] is None:
            return {"events": None, "stale": False, "fetched_at": None, "error": error,
                    "notice": None}
        stale = stale or got["stale"]
        if got["fetched_at"]:
            stamps.append(got["fetched_at"])
        for ev in got["events"]:
            if ev["last_day"] < lo or ev["start"] > hi:
                continue                 # read with its piece, but outside the year
            k = _event_key(ev)
            if k not in seen:
                seen.add(k)
                events.append(dict(ev))
    # The oldest piece decides how fresh the whole list is.
    return {"events": events, "stale": stale, "fetched_at": min(stamps) if stamps else None,
            "error": error, "notice": notice}


# ─── grouping ─────────────────────────────────────────────────────────────────
def _fold(text: Any) -> str:
    """A name compared without regard to case or spacing."""
    return re.sub(r"\s+", "", str(text or "")).lower()


def _punch_parent_name(name: str) -> str:
    """The Punch's name with the word "Punch" removed, folded for comparison."""
    return _fold(pc.tidy(_PUNCH_WORD.sub(" ", name or "")))


def _day(value: str) -> _dt.date:
    return _dt.date.fromisoformat(value)


def _group(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Projects as {"key", "job_number", "mobs", "punches", "punch_row"}."""
    groups: Dict[str, Dict[str, Any]] = {}
    punches: List[Dict[str, Any]] = []
    for ev in events:
        if ev["is_punch"]:
            punches.append(ev)
            continue
        key = "job:" + ev["job_number"] if ev["job_number"] else "name:" + _fold(ev["name"])
        g = groups.setdefault(key, {"key": key, "job_number": ev["job_number"], "mobs": [],
                                    "punches": [], "punch_row": False})
        g["mobs"].append(ev)

    # A job half relabelled (#792): a name group joins THE Job-number group of the same name. When
    # two Job numbers share the name, it could be either, so it stays its own row.
    by_job_name = _groups_by_name(g for g in groups.values() if g["job_number"])
    for key in [k for k, g in groups.items() if not g["job_number"]]:
        matches = by_job_name.get(_fold(groups[key]["mobs"][0]["name"])) or []
        if len(matches) == 1:
            matches[0]["mobs"].extend(groups.pop(key)["mobs"])

    by_name = _groups_by_name(groups.values())

    for ev in punches:
        parent = None
        if ev["job_number"]:
            parent = groups.get("job:" + ev["job_number"])
        if parent is None:               # no Job number, or one that matches no job (#792)
            parent = _name_parent(by_name.get(_punch_parent_name(ev["name"])) or [], ev)
            if parent is not None and ev["job_number"] and not parent["job_number"]:
                # Only the Punch is relabelled yet: its Job number is the job's, so the row reads
                # under it. The groups dict is done being looked up by key, so renaming is safe.
                parent["job_number"] = ev["job_number"]
                parent["key"] = "job:" + ev["job_number"]
        if parent is None:
            key = ("punch:job:" + ev["job_number"] if ev["job_number"]
                   else "punch:name:" + _fold(ev["name"]))
            parent = groups.setdefault(key, {"key": key, "job_number": ev["job_number"],
                                             "mobs": [], "punches": [], "punch_row": True})
        parent["punches"].append(ev)
    return list(groups.values())


def _groups_by_name(groups: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Each folded Mobilization name, with the Projects that have a Mobilization of that name."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for g in groups:
        for name in {_fold(m["name"]) for m in g["mobs"]}:
            out.setdefault(name, []).append(g)
    return out


def _name_parent(candidates: List[Dict[str, Any]], punch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Of the Projects sharing the Punch's name, the one whose work ended last before the Punch
    began, else the one that ends last."""
    if not candidates:
        return None
    ends = [(max(m["last_day"] for m in g["mobs"]), g) for g in candidates]
    before = [e for e in ends if e[0] <= punch["start"]]
    return max(before or ends, key=lambda e: (e[0], e[1]["key"]))[1]


# ─── figures ──────────────────────────────────────────────────────────────────
def _workday_dates(first: _dt.date, last: _dt.date) -> List[_dt.date]:
    out = []
    d = first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += _DAY
    return out


def _so_far(ev: Dict[str, Any], yesterday: _dt.date) -> int:
    start = _day(ev["start"])
    return pc.workdays(start, min(_day(ev["last_day"]), yesterday)) if start <= yesterday else 0


def _plan_mob(mobs: List[Dict[str, Any]], today: _dt.date) -> Optional[Dict[str, Any]]:
    """The Mobilization running today, else the most recent to have started, else the next."""
    iso = today.isoformat()
    running = [m for m in mobs if m["start"] <= iso <= m["last_day"]]
    if running:
        return max(running, key=lambda m: (m["start"], m["last_day"]))
    started = [m for m in mobs if m["start"] < iso]
    if started:
        return max(started, key=lambda m: (m["start"], m["last_day"]))
    return min(mobs, key=lambda m: (m["start"], m["last_day"])) if mobs else None


def _mob_out(ev: Dict[str, Any], yesterday: _dt.date) -> Dict[str, Any]:
    return {"id": ev["id"], "title": ev["title"], "name": ev["name"],
            "job_number": ev["job_number"], "start": ev["start"],
            "last_day": ev["last_day"], "workdays": ev["workdays"],
            "workdays_so_far": _so_far(ev, yesterday), "crew_size": ev["crew_size"],
            "mobilization": ev["mobilization"], "foreman": ev["foreman"],
            "work_type": ev["work_type"], "color": ev["color"], "html_link": ev["html_link"]}


def _in_window(start: _dt.date, deadline: _dt.date, punches: List[Dict[str, Any]],
               today: _dt.date) -> bool:
    lo, hi = today - _dt.timedelta(days=WINDOW_DAYS), today + _dt.timedelta(days=WINDOW_DAYS)
    if start <= today <= deadline:
        return True
    if lo <= deadline < today or today < start <= hi:
        return True
    for p in punches:
        a, b = max(_day(p["start"]), lo), min(_day(p["last_day"]), hi)
        if a <= b and _workday_dates(a, b):
            return True
    return False


def _project(g: Dict[str, Any], today: _dt.date) -> Optional[Dict[str, Any]]:
    """The row for one Project, or None when it is outside the window."""
    yesterday = today - _DAY
    mobs = sorted(g["mobs"], key=lambda m: (m["start"], m["last_day"], m["id"]))
    punches = sorted(g["punches"], key=lambda m: (m["start"], m["last_day"], m["id"]))
    main_work = mobs or punches          # a Punch row's dates are its Punches' own
    start = _day(min(m["start"] for m in main_work))
    deadline = _day(max(m["last_day"] for m in main_work))
    if not _in_window(start, deadline, punches, today):
        return None

    every = mobs + punches
    booked = set()
    planned = 0
    for m in every:
        if _day(m["start"]) <= yesterday:
            booked.update(_workday_dates(_day(m["start"]), min(_day(m["last_day"]), yesterday)))
        if isinstance(m["crew_size"], int):
            planned += _so_far(m, yesterday) * m["crew_size"] * HOURS_PER_WORKDAY

    plan = _plan_mob(every, today)
    latest = main_work[-1]
    foreman = (plan or {}).get("foreman") or next(
        (m["foreman"] for m in reversed(every) if m["foreman"]), None)
    if today < start:
        timing, left = TIMING_STARTS, None
    elif today > deadline:
        timing, left = TIMING_FINISHED, None
    else:
        timing, left = TIMING_RUNNING, pc.workdays(today, deadline)

    return {
        "key": g["key"],
        "job_number": g["job_number"],
        "name": latest["name"],
        "is_punch": g["punch_row"],
        "label": "Punch" if g["punch_row"] else None,
        "work_type": latest["work_type"],
        "color": latest["color"],
        "foreman": foreman,
        "start": start.isoformat(),
        "deadline": deadline.isoformat(),
        "timing": timing,
        "workdays_left": left,
        "workdays_so_far": len(booked),
        "crew_size": (plan or {}).get("crew_size"),
        "planned_hours": planned,
        "crew_size_missing": any(not isinstance(m["crew_size"], int) for m in every),
        "prevailing_wage": any(m["prevailing_wage"] for m in every),
        "night_work": any(m["night_work"] for m in every),
        "project": None,
        "mobilizations": [_mob_out(m, yesterday) for m in mobs],
        "punches": [_mob_out(m, yesterday) for m in punches],
        "raken": _raken(),
        "statuses": [],
    }


def build(events: Iterable[Dict[str, Any]], today: _dt.date) -> List[Dict[str, Any]]:
    """The listed Projects, Deadline first, then name."""
    out = [p for p in (_project(g, today) for g in _group(events)) if p is not None]
    out.sort(key=lambda p: (p["deadline"], p["name"].lower(), p["key"]))
    return out


# ─── the one function the route calls ─────────────────────────────────────────
def _calendar_side(today: _dt.date) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any]]:
    """(connected, the listed rows, the read's stale/fetched_at/error/notice). Never raises."""
    cal, source = pc.connection()
    if source is None:
        return False, [], {}
    got = _read_year(cal, source, today)
    if got["events"] is None:
        return True, [], {"error": got["error"]}
    # Every Job number on the calendar read, listed or not: none of them is Raken-only.
    numbers = sorted({ev["job_number"] for ev in got["events"] if ev.get("job_number")})
    try:
        projects = build(got["events"], today)
    except Exception as exc:  # noqa: BLE001 — a fault here must never 500 the page
        log.warning("plan vs actual: list not built (%s)", type(exc).__name__)
        return True, [], {"error": ERR_BUILD, "numbers": numbers}
    # One query for the tool Projects the listed Job numbers belong to, as on the Schedule.
    projects = pc.link_projects(projects)
    return True, projects, {"stale": got["stale"], "fetched_at": got["fetched_at"],
                            "error": got["error"], "notice": got["notice"], "numbers": numbers}


def fetch() -> Dict[str, Any]:
    """The Plan vs Actual list, with the last Raken read beside it. Never raises, never calls
    Raken."""
    today = pc.today_central()
    connected, projects, meta = _calendar_side(today)
    return _response(connected, today, projects, **meta)


# ─── "Refresh now" ────────────────────────────────────────────────────────────
# One refresh at a time, and no press ever waits for another: a Raken read can take minutes, and a
# request thread blocked on it is one the whole app's sync routes share. A press while a refresh
# runs answers at once as fetch() does, its Raken block saying refreshing: true, and the page polls
# the GET until it is done. A press within raken_actuals.REFRESH_COOLDOWN_S of a good read answers
# from that read: Raken's daily allowance is shared by the whole company.
_REFRESH_LOCK = threading.Lock()


def refresh() -> Dict[str, Any]:
    """Read Raken over the span the listed Projects need, keep the result, and answer as fetch()
    does. Never raises: a fault on the Raken side is logged, and the answer shows the kept read."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return fetch()
    try:
        today = pc.today_central()
        connected, projects, meta = _calendar_side(today)
        try:
            if (raken_actuals.connection()[0] == raken_actuals.STATE_CONNECTED
                    and not raken_actuals.fresh()):
                # No rows because the calendar could not be read: read at least as far back as
                # last time, so the numbers on screen never shrink during an outage.
                calendar_failed = not connected or (not projects and bool(meta.get("error")))
                first, last = raken_actuals.span(projects, today, keep_last=calendar_failed)
                raken_actuals.read_and_keep(first, last, rows=projects, keep_last=calendar_failed)
        except Exception as exc:  # noqa: BLE001 - "Refresh now" must never 500 the page
            log.warning("plan vs actual: Raken not refreshed (%s)", type(exc).__name__)
    finally:
        _REFRESH_LOCK.release()
    return _response(connected, today, projects, **meta)
