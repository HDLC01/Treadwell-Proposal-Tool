"""Plan vs Actual, the Excel download (#785): the list as it is filtered on screen, as a workbook.

The download exists so the projected hours can be pasted into the weekly budget report, which still
lives in Excel. Exercised THROUGH THE HTTP API (GET /api/project-analytics/export.xlsx) with
test_raken_actuals' fake Google calendar and fake Raken, and every claim is checked by opening the
downloaded workbook with openpyxl and reading it back. The claims that cost something when wrong:

  * THE SAME LIST AS THE SCREEN. The page's status filter (a pressed count) and its search box go
    to the server as `status` and `q`, and the server filters with the page's own rule
    (plan_vs_actual.visible_projects, the twin of js/project-calendar-core.js visibleProjects). A
    test runs both on the same inputs and checks they agree. Punch rows and Not linked rows are in.
  * THE SCREEN'S COLUMNS: Job number, name, Work type, Foreman, Deadline, Workdays left, the four
    pairs (Workdays booked so far / Days clocked in, Crew size / On site, Planned hours / Actual
    hours, Budgeted hours / Projected total hours), Over/under, the statuses as words, and notes.
    A figure nobody knows is a blank cell, never 0.
  * THE SUMMARY FIGURES on their own sheet: the four counts, Last week, the Budget totals.
  * DATES ARE CENTRAL and real Excel dates; the file name carries the day it was made, in Central.
  * NO FORMULA INJECTION. Job names are typed by hand in Google: a text cell starting with = + - @
    is written as text, so a job name can never run as a formula.
  * NEVER A 500. A Google failure with nothing saved, or any fault building the list, still
    downloads a workbook, carrying the plain message in place of the rows.

"Today" is Wednesday 2026-11-18 (Central). PUBLIC REPO: every job, person, project, number and id
below is made up.
"""
import datetime as dt
import io
import json
import shutil
import subprocess
import zipfile
from zoneinfo import ZoneInfo

import openpyxl
import pytest

import main
import plan_vs_actual
import plan_vs_actual_xlsx
import supabase_client
from test_plan_vs_actual import mob
from test_project_calendar_core_js import CORE, FRONTEND
from test_project_calendar_core_js import run as run_core
from test_raken_actuals import (JOB, _clean, card, client, fake, get, google,  # noqa: F401
                                project, refresh)
from test_raken_budget import division

XLSX = "/api/project-analytics/export.xlsx"
SHEET = "Plan vs Actual"
SUMMARY = "Summary"
HEADERS = ["Job number", "Name", "Work type", "Foreman", "Deadline", "Workdays left",
           "Workdays booked so far", "Days clocked in", "Crew size", "On site (average a day)",
           "Planned hours", "Actual hours", "Budgeted hours", "Projected total hours",
           "Over/under", "Statuses", "Notes"]

# A list with every kind of row the screen can show. Sorted as the server sorts it: Deadline, name.
DEPOT = mob("b", "26.502, Example Depot (4) (Sam)", "2026-11-16", "2026-11-20", "2")
ANNEX = mob("c", "26.503, Example Annex (2) (Lee)", "2026-11-09", "2026-11-13")     # finished
SHOP_PUNCH = mob("d", "Example Shop Punch - (1) (Lee)", "2026-11-17", "2026-11-17")  # its own row
GYM = mob("e", "26.505, Example Gym (Pat)", "2026-11-30", "2026-12-04")              # not started


@pytest.fixture
def world(google, fake):
    google.events = [JOB, DEPOT, ANNEX, SHOP_PUNCH, GYM]
    fake.projects = [project("r-1", "26.501", "Example Clinic"),
                     project("r-2", "26.502", "Example Depot"),
                     project("r-5", "26.505", "Example Gym")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8),
                  card("r-1", "2026-11-17", "w-2", 8),
                  card("r-2", "2026-11-16", "w-3", 8)]          # nobody on the Depot on Tuesday
    fake.insights = {"r-1": [division("01", 100, 90)], "r-2": [division("01", 100, 130)]}
    return google, fake


def download(client, **params):
    r = client.get(XLSX, params=params)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return r, openpyxl.load_workbook(io.BytesIO(r.content))


def rows(wb):
    ws = wb[SHEET]
    header = [c.value for c in ws[1]]
    assert header == HEADERS
    return [dict(zip(header, (c.value for c in row))) for row in ws.iter_rows(min_row=2)
            if any(c.value is not None for c in row)]


def summary(wb):
    """The Summary sheet as {label in column A: value in column B}."""
    return {r[0].value: r[1].value for r in wb[SUMMARY].iter_rows(min_row=1)
            if r[0].value is not None}


def caveats(wb):
    """The Summary sheet's caveats beside a figure: {label in column A: text in column C}."""
    return {r[0].value: r[2].value for r in wb[SUMMARY].iter_rows(min_row=1, max_col=3)
            if r[0].value is not None and r[2].value is not None}


def names(wb):
    return [(r["Job number"], r["Name"]) for r in rows(wb)]


# ── the list ──────────────────────────────────────────────────────────────────
def test_the_workbook_holds_every_row_of_the_list_with_the_screens_columns(client, world):
    refresh(client)
    r, wb = download(client)
    assert wb.sheetnames == [SHEET, SUMMARY]
    got = rows(wb)
    assert [(x["Job number"], x["Name"]) for x in got] == [
        ("26.503", "Example Annex"), (None, "Example Shop Punch"), ("26.501", "Example Clinic"),
        ("26.502", "Example Depot"), ("26.505", "Example Gym")], \
        "the server's order, Punch and Not linked rows included"
    annex, punch, clinic, depot, gym = got

    api = {p["key"]: p for p in get(client)["projects"]}
    assert clinic["Work type"] == api["job:26.501"]["work_type"]
    assert clinic["Foreman"] == "Pat"
    assert clinic["Deadline"] == dt.datetime(2026, 11, 20), "a real Excel date"
    assert clinic["Workdays left"] == 3, "Wednesday to Friday"
    assert (clinic["Workdays booked so far"], clinic["Days clocked in"]) == (2, 2)
    assert (clinic["Crew size"], clinic["On site (average a day)"]) == (3, 1.5)
    assert (clinic["Planned hours"], clinic["Actual hours"]) == (48, 24)
    assert (clinic["Budgeted hours"], clinic["Projected total hours"], clinic["Over/under"]) \
        == (100, 90, 10)
    assert clinic["Statuses"] == "On plan"

    assert depot["Statuses"] == "Behind, Over budget"
    assert depot["Over/under"] == -30 and depot["Days clocked in"] == 1

    assert annex["Workdays left"] == "Finished"
    assert annex["Statuses"] == "Not linked"
    assert "No Raken project carries Job number 26.503" in annex["Notes"]

    assert punch["Statuses"] == "Not linked"
    assert "Punch" in punch["Notes"] and "No Job number on the calendar" in punch["Notes"]

    assert gym["Workdays left"] == "Starts Mon, Nov 30, 2026"
    assert "Crew size missing" in gym["Notes"] and "No Raken budget" in gym["Notes"]


def test_a_figure_nobody_knows_is_a_blank_cell_never_zero(client, world):
    refresh(client)
    _r, wb = download(client)
    by = {x["Name"]: x for x in rows(wb)}
    for name in ("Example Annex", "Example Shop Punch"):          # Not linked: no Raken side
        for col in ("Days clocked in", "On site (average a day)", "Actual hours",
                    "Budgeted hours", "Projected total hours", "Over/under"):
            assert by[name][col] is None, (name, col)
    gym = by["Example Gym"]
    assert gym["Crew size"] is None, "no Crew size in the title is not nobody on site"
    assert gym["Budgeted hours"] is None and gym["Over/under"] is None, "no Raken budget"
    assert gym["On site (average a day)"] is None, "nobody was due on site yet"


def test_before_raken_is_read_every_raken_cell_and_every_count_is_blank(client, world):
    _r, wb = download(client)
    for x in rows(wb):
        assert x["Days clocked in"] is None and x["Actual hours"] is None
        assert x["Statuses"] in (None, "")
        assert x["Workdays booked so far"] is not None, "the calendar side still shows"
    s = summary(wb)
    for label in ("On plan", "Behind", "Over budget", "Not linked", "Last week Actual hours"):
        assert s[label] is None, label


# ── the filter and the search ─────────────────────────────────────────────────
def test_the_status_filter_and_the_search_box_pick_the_rows(client, world):
    refresh(client)
    assert names(download(client, status="behind")[1]) == [("26.502", "Example Depot")]
    assert names(download(client, q="pat")[1]) == [("26.501", "Example Clinic"),
                                                   ("26.505", "Example Gym")]
    assert names(download(client, q="example", status="not_linked")[1]) == [
        ("26.503", "Example Annex"), (None, "Example Shop Punch")]
    assert names(download(client, q="nothing like it")[1]) == []
    s = summary(download(client, q="pat", status="on_plan")[1])
    assert (s["Status filter"], s["Search"]) == ("On plan", "pat")
    assert (s["Jobs in the list"], s["Jobs in this file"]) == (5, 2)


NODE = shutil.which("node")


def _page_rows(data, q, status):
    """What the page lists for (q, status): js/project-calendar-core.js visibleProjects, with the
    status the page would apply (statusFilter: none while the counts are not known)."""
    script = ("const P = require(%s);\nconst d = %s;\n"
              "const out = P.visibleProjects(d.projects, %s, P.statusFilter(d, %s))"
              ".map(p => [p.job_number, p.name]);\n"
              "console.log(JSON.stringify(out));"
              % (json.dumps(str(CORE)), json.dumps(data), json.dumps(q), json.dumps(status)))
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8",
                          timeout=60, cwd=str(FRONTEND))
    assert proc.returncode == 0, proc.stderr
    return [tuple(x) for x in json.loads(proc.stdout.strip().splitlines()[-1])]


INPUTS = [("", ""), ("", "behind"), ("", "over_budget"), ("", "on_plan"), ("", "not_linked"),
          ("PAT", ""), ("  example   clinic ", ""), ("work type unknown", ""), ("26.50", "behind"),
          ("lee", "not_linked"), ("punch", ""), ("zzz", "on_plan"), ("", "made_up_status"),
          ("pat" + " " * 300 + "zzz", "")]   # past 200 characters: neither side reads the zzz


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_page_and_the_server_list_the_same_rows_for_the_same_filter_and_search(client, world):
    """The server's filter is the page's rule, written once more in Python. Same inputs, same rows,
    before Raken is read (the counts are not known, so no status filters) and after."""
    for stage in ("before", "after"):
        if stage == "after":
            refresh(client)
        data = get(client)
        for q, status in INPUTS:
            _r, wb = download(client, q=q, status=status)
            assert names(wb) == _page_rows(data, q, status), (stage, q, status)


# ── the summary figures ───────────────────────────────────────────────────────
def test_the_summary_sheet_carries_the_strips_figures(client, world):
    refresh(client)
    data = get(client)
    s_api = data["summary"]
    _r, wb = download(client, status="behind")
    s = summary(wb)
    assert (s["On plan"], s["Behind"], s["Over budget"], s["Not linked"]) == (2, 1, 1, 2), \
        "the counts are over the whole list, as on screen, whatever the filter"
    assert s["Jobs in no count"] == s_api["unflagged"] == 0
    assert (s["Budgeted hours"], s["Projected total hours"], s["Over/under"]) == (200, 220, -20)
    assert (s["Jobs with a Raken budget read"], s["Linked jobs"]) == (2, 3)
    lw = s_api["last_week"]
    assert s["Last week from"] == dt.datetime(2026, 11, 9)
    assert s["Last week to"] == dt.datetime(2026, 11, 13)
    assert s["Last week Planned hours"] == lw["planned_hours"]
    assert s["Last week Actual hours"] == lw["actual_hours"]
    assert (s["Status filter"], s["Search"]) == ("Behind", None)
    assert "Last week Planned hours" not in caveats(wb), "every Workday last week had a Crew size"


BARN = mob("g", "26.507, Example Barn (Lee)", "2026-11-10", "2026-11-12")   # no Crew size


@pytest.mark.parametrize("annex_linked, planned, caveat", [
    (False, None, "No Workday last week has a Crew size, so Planned hours are not known."),
    (True, 5 * 2 * 8, "Some Workdays have no Crew size, so Planned hours are short."),
])
def test_the_summary_sheet_says_when_last_weeks_planned_hours_are_short(
        client, world, annex_linked, planned, caveat):
    """The screen's Last week tile puts a caveat beside Planned hours when a Workday that week has
    no Crew size; the file pasted into the budget report carries the same words beside the figure.
    The Barn (no Crew size) is the only linked job last week, or the Annex (two a day) is too."""
    google, fake = world
    google.events = google.events + [BARN]
    fake.projects = fake.projects + [project("r-7", "26.507", "Example Barn")] + (
        [project("r-3", "26.503", "Example Annex")] if annex_linked else [])
    refresh(client)
    lw = get(client)["summary"]["last_week"]
    assert lw["crew_size_missing"] is True and lw["planned_hours"] == planned
    _r, wb = download(client)
    assert summary(wb)["Last week Planned hours"] == planned
    assert caveats(wb)["Last week Planned hours"] == caveat


# ── dates and the file name ───────────────────────────────────────────────────
def test_dates_are_central_and_the_file_name_carries_the_day_it_was_made(client, world):
    """The fake Raken read finished at 15:05 UTC: 9:05 in the morning in Central. The dev box runs
    about thirteen hours ahead of Central, so its own date is never used."""
    refresh(client)
    r, wb = download(client)
    assert r.headers["content-disposition"] == \
        'attachment; filename="project-analytics-2026-11-18.xlsx"'
    s = summary(wb)
    assert s["Made"] == dt.datetime(2026, 11, 18)
    assert s["Raken as of"] == dt.datetime(2026, 11, 18, 9, 5)
    ws = wb[SHEET]
    deadline = next(c for c in ws[2] if isinstance(c.value, dt.datetime))
    assert deadline.is_date and "y" in deadline.number_format


# ── formula injection ─────────────────────────────────────────────────────────
def test_a_job_name_that_looks_like_a_formula_is_written_as_text(client, google, fake):
    evil = ['=HYPERLINK("http://evil.example","Example")', "@SUM(1+1) Example Hall",
            "+Example Yard", "-Example Shed"]
    google.events = [
        mob("f1", "26.601, %s (2) (Pat)" % evil[0], "2026-11-16", "2026-11-20"),
        mob("f2", "26.602, %s (2) (Pat)" % evil[1], "2026-11-16", "2026-11-20"),
        mob("f3", "26.603, %s (2) (Pat)" % evil[2], "2026-11-16", "2026-11-20"),
        mob("f4", "%s Annex (2) (=1+2)" % evil[3], "2026-11-16", "2026-11-20"),
    ]
    r, wb = download(client)
    api_names = [p["name"] for p in get(client)["projects"]]
    assert any(n.startswith(("=", "@", "+", "-")) for n in api_names)
    ws = wb[SHEET]
    cells = [c for row in ws.iter_rows(min_row=2) for c in row if isinstance(c.value, str)]
    risky = [c for c in cells if c.value[:1] in ("=", "+", "-", "@")]
    assert {c.value for c in risky} >= {n for n in api_names if n[:1] in "=+-@"}
    for c in risky:
        assert c.data_type == "s", c.value
        assert c.quotePrefix, "Excel keeps it as text when the cell is edited"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if name.startswith("xl/worksheets/"):
                assert b"<f>" not in z.read(name) and b"<f " not in z.read(name), name


# ── never a 500 ───────────────────────────────────────────────────────────────
def test_a_google_failure_with_nothing_saved_still_downloads_the_plain_message(client, google, fake):
    google.fail = True
    data = get(client)
    assert data["error"] and data["projects"] == []
    _r, wb = download(client)
    ws = wb[SHEET]
    assert [c.value for c in ws[1]] == HEADERS
    assert ws["A2"].value == data["error"]
    assert summary(wb)["Note"] == data["error"]


def test_any_fault_building_the_list_still_downloads_a_workbook(client, google, fake, monkeypatch):
    def boom():
        raise RuntimeError("made-up fault")
    monkeypatch.setattr(plan_vs_actual, "fetch", boom)
    r, wb = download(client)
    assert wb[SHEET]["A2"].value == "The download could not be built just now. Try again in a minute."
    assert r.headers["content-disposition"].endswith('-2026-11-18.xlsx"')


# ── access ────────────────────────────────────────────────────────────────────
def test_every_signed_in_role_downloads_the_workbook(client, world, monkeypatch):
    """Any signed-in staff member may download it, as every Plan vs Actual route (hide-only)."""
    refresh(client)
    for role in ("user", "estimator", "admin"):
        monkeypatch.setattr(main.profiles, "get_by_email",
                            lambda e, role=role: {"id": "u", "email": e, "role": role,
                                                  "status": "active"})
        main._profile_cache_clear()
        _r, wb = download(client)
        assert len(rows(wb)) == 5, role


def test_signed_out_the_download_is_refused(client, world, monkeypatch, real_verify_token):
    """It exports every job's labor numbers: nobody signed out gets a workbook."""
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    r = client.get(XLSX, headers={"authorization": ""})
    assert r.status_code == 401
    assert not r.content.startswith(b"PK"), "no workbook"


def test_a_status_that_is_not_one_of_the_four_counts_filters_nothing(client, world):
    """Only the four counts filter, on the server as on the page (P.statusFilter): anything else
    is no filter, and the Summary never repeats it."""
    refresh(client)
    for status in ("made_up_status", "BEHIND", "<b>x</b>"):
        _r, wb = download(client, status=status)
        assert len(rows(wb)) == 5, status
        assert summary(wb)["Status filter"] == "All jobs", status


def test_with_no_calendar_connected_it_downloads_the_plain_message(client, google, fake,
                                                                    monkeypatch):
    monkeypatch.delenv("PROJECT_CALENDAR_ID", raising=False)
    assert get(client)["connected"] is False
    _r, wb = download(client)
    assert wb[SHEET]["A2"].value == "The Treadwell Projects calendar is not connected yet."
    assert summary(wb)["Note"] == "The Treadwell Projects calendar is not connected yet."


def test_a_google_failure_after_a_good_read_lists_the_last_copy_and_says_when_it_was_read(
        client, world):
    """The stale copy's rows are listed, and the Note says when it was read, in Central, worded as
    the rest of the file words a time ("Nov 18, 2026, 9:05 AM")."""
    google, _fake = world
    first = get(client)
    google.fail = True
    data = get(client)
    assert data["stale"] is True and data["fetched_at"] == first["fetched_at"]
    _r, wb = download(client)
    assert len(rows(wb)) == 5
    at = dt.datetime.fromisoformat(data["fetched_at"]).astimezone(ZoneInfo("America/Chicago"))
    when = "%s %d, %d, %d:%02d %s" % (at.strftime("%b"), at.day, at.year, at.hour % 12 or 12,
                                       at.minute, "AM" if at.hour < 12 else "PM")
    note = summary(wb)["Note"]
    assert note.startswith("The calendar is the last copy read at %s (Central)." % when), note
    assert data["error"] in note


# ── the screen's words ────────────────────────────────────────────────────────
def _variants(projects):
    """The world's rows, and each kind of row the world lacks, made from them: every Raken state,
    every Budget pair state, and the Raken projection below Actual hours."""
    linked = next(p for p in projects if (p.get("raken") or {}).get("state") == "linked")
    out = [dict(p) for p in projects]
    for state in ("not_connected", "expired", "not_provisioned", "unreachable", "not_refreshed",
                  None):
        out.append(dict(linked, raken={"state": state} if state else {}))
    for change in ({"budget": "not_read"}, {"budget": "none"},
                   {"budget": "shown", "projection_below_actual": True}):
        out.append(dict(linked, raken=dict(linked["raken"], **change)))
    return out


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_workbook_words_a_row_as_the_page_does(client, world):
    """The Statuses, the Workdays left and the Notes are the page's own words (statusChips,
    leftLabel, rakenLabel, budgetCells' note), so rewording one on the page alone fails here. Two
    notes are worded for a spreadsheet on purpose and are not compared: a Job number two Raken
    projects carry (the page names them; the file names no Raken project) and the booked days a
    Behind read covered (the page's "2 of 2" beside the figure)."""
    refresh(client)
    rows_in = _variants(get(client)["projects"])
    got = run_core("out(%s.map((p) => [P.statusChips(p).map((c) => c.label).join(', '),"
                   " P.leftLabel(p), p.raken && p.raken.state === 'linked'"
                   " ? P.budgetCells(p).note : P.rakenLabel(p)]))" % json.dumps(rows_in))
    for p, (statuses, left, note) in zip(rows_in, got):
        row = dict(zip(HEADERS, plan_vs_actual_xlsx.job_row(p)))
        assert (row["Statuses"] or "") == statuses, p["name"]
        n = row["Workdays left"]
        assert left == (n if isinstance(n, str) else
                        "%d workday%s left" % (n, "" if n == 1 else "s")), p["name"]
        notes = (row["Notes"] or "").split("; ")
        assert (note in notes) if note else True, (p["name"], note, notes)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_caveat_beside_last_weeks_planned_hours_is_the_tiles_own(client, world):
    weeks = [{"crew_size_missing": True, "planned_hours": 80},
             {"crew_size_missing": True, "planned_hours": None},
             {"crew_size_missing": False, "planned_hours": 80}]
    for w in weeks:
        w.update({"from": "2026-11-09", "to": "2026-11-13", "jobs": 2, "raken": "read",
                  "actual_hours": 60})
    got = run_core("out(%s.map((w) => P.lastWeekTile({summary: {last_week: w}}).note))"
                   % json.dumps(weeks))
    for w, note in zip(weeks, got):
        caveat = plan_vs_actual_xlsx._planned_caveat(w)
        assert note.endswith(" " + caveat) if caveat else "Crew size" not in note, (w, note)
