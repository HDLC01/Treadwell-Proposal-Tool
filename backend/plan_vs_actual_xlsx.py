"""Plan vs Actual as an Excel workbook (#785): the list as it is filtered on screen.

The download exists so the projected hours can be pasted into the weekly budget report while that
report still lives in Excel. It is built here from the SAME response the page lays out
(plan_vs_actual.fetch()), filtered by the page's own rule (plan_vs_actual.visible_projects) with
the page's status filter and search text, so the file and the screen hold the same rows.

THE WORKBOOK. Two sheets:
  * "Plan vs Actual": one row per job listed, Punch rows and Not linked rows included, with the
    screen's columns: Job number, name, Work type, Foreman, Deadline, Workdays left, the four pairs
    (Workdays booked so far against Days clocked in, Crew size against On site, Planned hours
    against Actual hours, Budgeted hours against Projected total hours), Over/under, the statuses
    in words and a Notes column for what the screen says in small print. A figure nobody knows (a
    Raken figure for a job not linked, a Budget pair with no Raken budget, a missing Crew size) is
    a blank cell, never 0.
  * "Summary": when it was made and how fresh Raken's figures are, the filter and search it was
    made with, and the summary strip's figures (the four counts over the whole list, as on screen;
    Last week; the Budget totals).
Dates are real Excel dates on the Central calendar; the Raken "as of" time is Central wall-clock.

THE SCREEN'S WORDS. The statuses, Workdays left, the Notes and the caveat beside Last week's
Planned hours are the page's own words (js/project-calendar-core.js statusChips, leftLabel,
rakenLabel, budgetCells, lastWeekTile), written again here. tests/test_plan_vs_actual_xlsx.py runs
both on the same rows and checks they agree, so rewording one side alone fails there. Two notes are
worded for a spreadsheet on purpose: a Job number two Raken projects carry (the file names no Raken
project) and the booked days a Behind read covered.

TEXT IS NEVER A FORMULA. Job names and Foremen are typed by hand in Google. Every text cell is
written with the string type and Excel's quote prefix, so a name starting with = + - @ shows as
typed and stays text even when the cell is edited. Characters a workbook cannot hold are dropped.

NEVER A 500. With nothing to list because the calendar could not be read (or is not connected),
the first sheet carries the plain message in place of the rows; message_workbook() is the same
file for any fault the route catches.
"""
from __future__ import annotations

import datetime as _dt
import io
from typing import Any, Dict, List, Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font

import plan_vs_actual as pva
import project_calendar as pc
import raken_actuals as ra

SHEET = "Plan vs Actual"
SUMMARY = "Summary"
ERR_BUILD = "The download could not be built just now. Try again in a minute."
NOT_CONNECTED = "The Treadwell Projects calendar is not connected yet."

HEADERS = ["Job number", "Name", "Work type", "Foreman", "Deadline", "Workdays left",
           "Workdays booked so far", "Days clocked in", "Crew size", "On site (average a day)",
           "Planned hours", "Actual hours", "Budgeted hours", "Projected total hours",
           "Over/under", "Statuses", "Notes"]
_WIDTHS = [12, 36, 14, 14, 13, 18, 12, 11, 10, 12, 11, 11, 12, 13, 11, 22, 48]

DATE_FMT = "ddd, mmm d, yyyy"
STAMP_FMT = "mmm d, yyyy h:mm AM/PM"
WHOLE_FMT = "#,##0"
TENTH_FMT = "#,##0.0"
SIGNED_FMT = "+#,##0.0;-#,##0.0;0"
_FMT = {"Deadline": DATE_FMT, "Workdays booked so far": WHOLE_FMT, "Days clocked in": WHOLE_FMT,
        "Crew size": WHOLE_FMT, "On site (average a day)": TENTH_FMT, "Planned hours": WHOLE_FMT,
        "Actual hours": TENTH_FMT, "Budgeted hours": TENTH_FMT, "Projected total hours": TENTH_FMT,
        "Over/under": SIGNED_FMT, "Workdays left": WHOLE_FMT}

# The screen's words for each status, in the screen's order (P.STATUS_LABELS).
STATUS_LABELS = ((ra.STATUS_NOT_LINKED, "Not linked"), (ra.STATUS_BEHIND, "Behind"),
                 (ra.STATUS_OVER_BUDGET, "Over budget"), (ra.STATUS_ON_PLAN, "On plan"))
_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def file_name(today: _dt.date) -> str:
    """The download's name: the Central day it was made."""
    return "project-analytics-%s.xlsx" % today.isoformat()


def made_on(data: Dict[str, Any], fallback: _dt.date) -> _dt.date:
    """The Central day the response was worked out for (its "today"), else `fallback`."""
    return _day(data.get("today")) or fallback


# ─── values ───────────────────────────────────────────────────────────────────
def _day(value: Any) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _planned_caveat(lw: Dict[str, Any]) -> str:
    """The caveat beside Last week's Planned hours when a Workday that week has no Crew size (the
    page's lastWeekTile). "" otherwise."""
    if lw.get("crew_size_missing") is not True:
        return ""
    if _num(lw.get("planned_hours")) is not None:
        return "Some Workdays have no Crew size, so Planned hours are short."
    return "No Workday last week has a Crew size, so Planned hours are not known."


def _central_stamp(value: Any) -> Optional[_dt.datetime]:
    """An ISO instant as Central wall-clock with no zone (Excel has none). None when unreadable."""
    try:
        at = _dt.datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    if at is None:
        return None
    if at.tzinfo is not None:
        at = at.astimezone(pc.CENTRAL).replace(tzinfo=None)
    return at


def _day_long(day: Optional[_dt.date]) -> str:
    """"Mon, Nov 30, 2026", the page's dayLong."""
    if day is None:
        return ""
    return "%s, %s %d, %d" % (_DOW[day.weekday()], _MON[day.month - 1], day.day, day.year)


def _stamp_long(at: _dt.datetime) -> str:
    """"Nov 9, 2026, 3:05 PM": a time in words, as the Raken "as of" cell shows one (STAMP_FMT)."""
    return "%s %d, %d, %d:%02d %s" % (_MON[at.month - 1], at.day, at.year, at.hour % 12 or 12,
                                       at.minute, "AM" if at.hour < 12 else "PM")


def _num(value: Any) -> Optional[float]:
    """A finite number, else None (a blank cell, never 0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def status_label(status: str) -> str:
    return dict(STATUS_LABELS).get(status, "")


def _statuses(p: Dict[str, Any]) -> str:
    st = p.get("statuses") if isinstance(p.get("statuses"), list) else []
    return ", ".join(label for sid, label in STATUS_LABELS if sid in st)


def _left(p: Dict[str, Any]) -> Any:
    """Workdays left while the job runs; "Starts <date>" before it, "Finished" after (the page's
    leftLabel), so the count is never negative."""
    if p.get("timing") == pva.TIMING_STARTS:
        return ("Starts " + _day_long(_day(p.get("start")))).strip()
    if p.get("timing") == pva.TIMING_FINISHED:
        return "Finished"
    return _num(p.get("workdays_left"))


def _raken_note(p: Dict[str, Any], r: Dict[str, Any]) -> str:
    """Why a row's Raken cells are blank (the page's rakenLabel), in literal words: nothing read
    from Raken is copied into it."""
    st = r.get("state")
    if not st or st == ra.STATE_NOT_CONNECTED:
        return "Connect Raken to compare"
    if st == ra.STATE_NOT_LINKED:
        num = str(p.get("job_number") or "")
        if r.get("reason") == ra.REASON_NO_JOB_NUMBER or not num:
            return "No Job number on the calendar"
        dups = r.get("duplicates") if isinstance(r.get("duplicates"), list) else []
        if r.get("reason") == ra.REASON_DUPLICATE and len(dups) >= 2:
            return "%d Raken projects carry Job number %s" % (len(dups), num)
        return "No Raken project carries Job number " + num
    return {ra.STATE_EXPIRED: "Raken sign-in expired",
            ra.STATE_NOT_PROVISIONED: "Raken not turned on yet",
            ra.STATE_UNREACHABLE: "Raken not reached",
            ra.STATE_NOT_REFRESHED: "Press Refresh now"}.get(st, "")


def job_row(p: Dict[str, Any]) -> List[Any]:
    """One job's cells, in HEADERS' order."""
    r = p.get("raken") if isinstance(p.get("raken"), dict) else {}
    linked = r.get("state") == ra.STATE_LINKED
    shown = linked and r.get("budget") == ra.BUDGET_SHOWN
    notes = []
    if p.get("label"):
        notes.append(str(p["label"]))
    if p.get("crew_size_missing"):
        notes.append("Crew size missing")
    if not linked:
        notes.append(_raken_note(p, r))
    else:
        booked, so_far = r.get("days_booked"), p.get("workdays_so_far")
        if isinstance(booked, int) and booked != so_far:
            through = _day_long(_day(r.get("through")))
            notes.append("Days clocked in are out of %d booked days%s" % (
                booked, " through " + through if through else ""))
        if r.get("budget") == ra.BUDGET_NONE:
            notes.append("No Raken budget")
        elif r.get("budget") != ra.BUDGET_SHOWN:
            notes.append("Raken's budget not read")
        elif r.get("projection_below_actual") is True:
            notes.append("Raken's projection covers only the work in its budget")
    return [
        p.get("job_number") or None,
        p.get("name") or "Untitled",
        pva.work_type_of(p),
        p.get("foreman") or None,
        _day(p.get("deadline")),
        _left(p),
        _num(p.get("workdays_so_far")),
        _num(r.get("days_clocked")) if linked else None,
        _num(p.get("crew_size")),
        _num(r.get("avg_on_site")) if linked else None,
        _num(p.get("planned_hours")),
        _num(r.get("actual_hours")) if linked else None,
        _num(r.get("budgeted_hours")) if shown else None,
        _num(r.get("projected_total_hours")) if shown else None,
        _num(r.get("over_under")) if shown else None,
        _statuses(p) or None,
        "; ".join(n for n in notes if n) or None,
    ]


# ─── writing ──────────────────────────────────────────────────────────────────
def _put(ws: Any, row: int, col: int, value: Any, fmt: Optional[str] = None) -> Any:
    """Write one cell. Text is always the string type with Excel's quote prefix, so nothing typed
    in a calendar title can become a formula."""
    cell = ws.cell(row=row, column=col)
    if isinstance(value, str):
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
        cell.data_type = "s"
        cell.quotePrefix = True
    else:
        cell.value = value
        if fmt and value is not None:
            cell.number_format = fmt
    return cell


def _list_sheet(ws: Any, rows: List[Dict[str, Any]], message: str = "") -> None:
    ws.title = SHEET
    for i, h in enumerate(HEADERS, start=1):
        _put(ws, 1, i, h).font = Font(bold=True)
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = _WIDTHS[i - 1]
    ws.freeze_panes = "C2"
    if message:
        _put(ws, 2, 1, message).alignment = Alignment(wrap_text=False)
        return
    for n, p in enumerate(rows, start=2):
        for i, value in enumerate(job_row(p), start=1):
            _put(ws, n, i, value, _FMT.get(HEADERS[i - 1]))
    if rows:
        ws.auto_filter.ref = "A1:%s%d" % (ws.cell(row=1, column=len(HEADERS)).column_letter,
                                          len(rows) + 1)


def _summary_sheet(ws: Any, lines: List[tuple]) -> None:
    """`lines` as (label, value, number format, caveat) rows; a label alone is a section heading.
    A caveat goes in column C, beside the figure it qualifies."""
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 60
    for n, line in enumerate(lines, start=1):
        label, value, fmt, caveat = (tuple(line) + (None, None, None, None))[:4]
        if label is None:
            continue
        cell = _put(ws, n, 1, label)
        if len(line) == 1:
            cell.font = Font(bold=True)
            continue
        _put(ws, n, 2, value, fmt)
        if caveat:
            _put(ws, n, 3, caveat)


def _save(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def message_workbook(message: str, today: _dt.date) -> bytes:
    """A workbook with no rows, saying `message`: what the download is when nothing can be listed."""
    wb = Workbook()
    _list_sheet(wb.active, [], message)
    _summary_sheet(wb.create_sheet(SUMMARY), [
        ("Project Analytics: Plan vs Actual",), ("Made", today, DATE_FMT), ("Note", message)])
    return _save(wb)


def build(data: Dict[str, Any], q: str, status: str, today: _dt.date) -> bytes:
    """The workbook for the response `data` (plan_vs_actual.fetch()), filtered as the page filters
    it with the search text `q` and the pressed count `status`."""
    projects = [p for p in data.get("projects") or [] if isinstance(p, dict)]
    message = ""
    if data.get("connected") is False:
        message = NOT_CONNECTED
    elif not projects and data.get("error"):
        message = str(data["error"])
    if message:
        return message_workbook(message, today)

    shown = pva.visible_projects(data, q, status)
    st = pva.status_filter(data, status)
    s = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    counts = s.get("counts") if pva.counts_known(data) else None
    raken = data.get("raken") if isinstance(data.get("raken"), dict) else {}
    lw = s.get("last_week") if isinstance(s.get("last_week"), dict) else {}
    bt = s.get("budget") if isinstance(s.get("budget"), dict) else {}

    notes = []
    if data.get("stale"):
        at = _central_stamp(data.get("fetched_at"))
        notes.append("The calendar is the last copy read%s." % (
            " at " + _stamp_long(at) + " (Central)" if at else ""))
    for extra in (data.get("error"), data.get("notice"), raken.get("message")):
        if isinstance(extra, str) and extra:
            notes.append(extra)

    def count(sid: str) -> Optional[int]:
        return _num(counts.get(sid)) if isinstance(counts, dict) else None

    lines: List[tuple] = [
        ("Project Analytics: Plan vs Actual",),
        ("Made", today, DATE_FMT),
        ("Raken as of", _central_stamp(raken.get("as_of")), STAMP_FMT),
        ("Counts so far run through", _day(data.get("so_far_through")), DATE_FMT),
        ("Status filter", status_label(st) or "All jobs"),
        ("Search", str(q).strip() or None),
        ("Jobs in the list", len(projects), WHOLE_FMT),
        ("Jobs in this file", len(shown), WHOLE_FMT),
        (None,),
        ("Counts (every job in the list; a job Behind and Over budget is in both)",),
        ("On plan", count(ra.STATUS_ON_PLAN), WHOLE_FMT),
        ("Behind", count(ra.STATUS_BEHIND), WHOLE_FMT),
        ("Over budget", count(ra.STATUS_OVER_BUDGET), WHOLE_FMT),
        ("Not linked", count(ra.STATUS_NOT_LINKED), WHOLE_FMT),
        ("Jobs in no count", _num(s.get("unflagged")) if counts is not None else None, WHOLE_FMT),
        (None,),
        ("Last week (linked jobs)",),
        ("Last week from", _day(lw.get("from")), DATE_FMT),
        ("Last week to", _day(lw.get("to")), DATE_FMT),
        ("Last week Planned hours", _num(lw.get("planned_hours")), WHOLE_FMT,
         _planned_caveat(lw)),
        ("Last week Actual hours",
         _num(lw.get("actual_hours")) if lw.get("raken") == pva.LAST_WEEK_READ else None,
         TENTH_FMT),
        (None,),
        ("Budget (linked jobs with a Raken budget read)",),
        ("Budgeted hours", _num(bt.get("budgeted_hours")), TENTH_FMT),
        ("Projected total hours", _num(bt.get("projected_total_hours")), TENTH_FMT),
        ("Over/under", _num(bt.get("over_under")), SIGNED_FMT),
        ("Jobs with a Raken budget read", _num(bt.get("jobs")) if s.get("raken_read") else None,
         WHOLE_FMT),
        ("Linked jobs", _num(bt.get("linked_jobs")) if s.get("raken_read") else None, WHOLE_FMT),
    ]
    if notes:
        lines += [(None,), ("Note", " ".join(notes))]

    wb = Workbook()
    _list_sheet(wb.active, shown)
    _summary_sheet(wb.create_sheet(SUMMARY), lines)
    return _save(wb)
