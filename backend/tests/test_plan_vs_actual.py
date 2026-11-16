"""Plan vs Actual, the calendar side (#780): one row per Project, built on the server.

Exercised THROUGH THE HTTP API (GET /api/project-analytics) with a fake calendar source standing in
for Google, because the response is what the page lays out. The fake answers like Google does: only
the events overlapping the window it is asked for, so the year-long read in pieces is really tested.
The claims that cost something when they are wrong:

  * ONE ROW PER PROJECT. Mobilizations group by Job number, else by name; a name group joins the
    one Job number with its name (a job half relabelled); a Punch joins its job (by Job number,
    else by name with "Punch" removed, ignoring case and spacing), and an unmatched Punch is its
    own row labelled Punch.
  * PLANNED HOURS = each Mobilization's Workdays up to YESTERDAY (Central) x its own Crew size x 8.
    A missing Crew size adds nothing and says so; it never reads as nobody on site.
  * THE WINDOW. Running today, Deadline in the last 14 days, Start in the next 14 days, or a Punch
    with a Workday within 14 days of today. A listed job's figures use every Mobilization read.
  * NEVER A 500. Google failing is a 200 with a plain error.

"Today" is injected (Wednesday 2026-11-18); the dev box clock is never read. PUBLIC REPO: every
job, person and calendar id below is made up.
"""
import copy
import datetime as dt

import pytest
from fastapi.testclient import TestClient

import main
import project_calendar as pc
import supabase_client

CAL_ID = "made-up-crew-schedule@group.calendar.google.com"
URL = "/api/project-analytics"
TODAY = dt.date(2026, 11, 18)          # a Wednesday; yesterday is Tuesday 2026-11-17


# ── fakes ─────────────────────────────────────────────────────────────────────
class FakeGoogle:
    """Answers like Google's events.list: the events overlapping [time_min, time_max)."""

    def __init__(self, events=None):
        self.events = list(events or [])
        self.calls = []
        self.fail = False

    def list_events(self, calendar_id, time_min, time_max):
        self.calls.append((calendar_id, time_min, time_max))
        if self.fail:
            raise RuntimeError("upstream unavailable")
        lo, hi = time_min[:10], time_max[:10]
        out = []
        for ev in self.events:
            start = ev["start"]["date"]
            end_excl = ev["end"]["date"]
            if start < hi and end_excl > lo:
                out.append(copy.deepcopy(ev))
        return out


class _DraftsQuery:
    def __init__(self, db):
        self.db = db
        self.wanted = None

    def select(self, cols):
        return self

    def is_(self, k, v):
        return self

    def in_(self, k, vals):
        self.wanted = list(vals)
        return self

    def execute(self):
        self.db.queries += 1
        rows = [{"id": r["id"], "created_at": r["created_at"], "job_number": r["job_number"],
                 "project_name": r["project_name"], "archived": None}
                for r in self.db.rows if r["job_number"] in (self.wanted or [])]
        return type("R", (), {"data": rows})()


class FakeDrafts:
    def __init__(self):
        self.rows = []
        self.queries = 0

    def table(self, name):
        assert name == "drafts", name
        return _DraftsQuery(self)


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def drafts_db(monkeypatch):
    db = FakeDrafts()
    monkeypatch.setattr(supabase_client, "get_client", lambda: db)
    return db


@pytest.fixture
def google(monkeypatch, drafts_db):
    src = FakeGoogle()
    monkeypatch.setenv("PROJECT_CALENDAR_ID", CAL_ID)
    monkeypatch.setenv("PROJECT_CALENDAR_TTL_S", "0")
    monkeypatch.setattr(pc, "_make_source", lambda: src)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY)
    return src


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pc.cache_clear()
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user", "status": "active"})
    main._profile_cache_clear()
    yield
    pc.cache_clear()


@pytest.fixture
def client():
    return TestClient(main.app)


def mob(eid, summary, first, last, color=None):
    """An all-day event from `first` through `last` (both inclusive, YYYY-MM-DD)."""
    end_excl = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
    ev = {"id": eid, "summary": summary, "start": {"date": first}, "end": {"date": end_excl},
          "htmlLink": "https://calendar.example/event?eid=" + eid}
    if color is not None:
        ev["colorId"] = color
    return ev


def get(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def rows(client):
    return get(client)["projects"]


def row(client, key):
    found = [p for p in rows(client) if p["key"] == key]
    assert len(found) == 1, [p["key"] for p in rows(client)]
    return found[0]


# ── the response ──────────────────────────────────────────────────────────────
def test_the_response_carries_the_calendar_side_and_raken_not_connected(client, google):
    google.events = [mob("a", "26.125, Acme Clinic Psych (6) (Pat)", "2026-11-16", "2026-11-20", "11")]
    body = get(client)
    assert body["ok"] is True and body["connected"] is True and body["error"] is None
    assert body["today"] == "2026-11-18" and body["so_far_through"] == "2026-11-17"
    assert body["raken"] == {"state": "not_connected"}
    assert [w["name"] for w in body["work_types"]] == ["Epoxy", "Polish", "Gyp"]
    (p,) = body["projects"]
    assert p["key"] == "job:26.125"
    assert p["job_number"] == "26.125" and p["name"] == "Acme Clinic Psych"
    assert p["work_type"] == "Epoxy" and p["color"] == "#d50000" and p["foreman"] == "Pat"
    assert p["start"] == "2026-11-16" and p["deadline"] == "2026-11-20"
    assert p["raken"] == {"state": "not_connected"}
    (m,) = p["mobilizations"]
    assert m["start"] == "2026-11-16" and m["last_day"] == "2026-11-20" and m["crew_size"] == 6
    assert m["html_link"] == "https://calendar.example/event?eid=a"
    assert p["punches"] == []


def test_the_response_names_the_hours_in_a_workday_and_the_window_the_page_words(client, google):
    """The page says "x 8" and "14 days"; the numbers are the server's, so it reads them from here."""
    body = get(client)
    assert body["hours_per_workday"] == 8 and body["window_days"] == 14


# ── reading a year in pieces ──────────────────────────────────────────────────
def test_a_year_back_and_two_weeks_ahead_is_read_in_pieces_of_at_most_120_days(
        client, google, monkeypatch):
    """365 days before today to 14 days after, every day once, never more than the reader's cap per
    request, and only ever the configured calendar. The pieces sit on a fixed grid, so the next
    day asks for the same pieces (and finds the same cache entries) unless the year has reached a
    new one."""
    def read_days():
        google.calls.clear()
        body = get(client)
        days = []
        for cal, time_min, time_max in google.calls:
            assert cal == CAL_ID
            a, b = dt.date.fromisoformat(time_min[:10]), dt.date.fromisoformat(time_max[:10])
            assert 0 < (b - a).days <= pc.MAX_SPAN_DAYS
            days.extend(a + dt.timedelta(days=i) for i in range((b - a).days))
        return body, days, list(google.calls)

    body, days, calls = read_days()
    assert body["read_from"] == "2025-11-18" and body["read_to"] == "2026-12-02"
    assert days == sorted(set(days)), "a day was read twice"
    assert days[0] <= dt.date(2025, 11, 18) and days[-1] >= dt.date(2026, 12, 2)
    assert days == [days[0] + dt.timedelta(days=i) for i in range(len(days))], "a day was skipped"
    assert len(calls) <= 5

    monkeypatch.setattr(pc, "today_central", lambda: TODAY + dt.timedelta(days=1))
    _body, _days, next_calls = read_days()
    assert next_calls == calls


def test_a_job_longer_than_120_days_is_one_mobilization_counted_once(client, google):
    """Mon 2026-05-04 to Fri 2026-11-27 crosses three pieces of the read. Google returns it from
    each; the row must still hold it once, with its Workdays counted once."""
    google.events = [mob("long", "26.300, Example Warehouse (2) (Ann)", "2026-05-04", "2026-11-27", "9")]
    assert len(google.calls) == 0
    p = row(client, "job:26.300")
    assert len(google.calls) > 1
    assert len(p["mobilizations"]) == 1
    # Mon May 4 to Tue Nov 17 inclusive: 28 whole weeks (140) plus Mon and Tue.
    assert p["workdays_so_far"] == 142 == p["mobilizations"][0]["workdays_so_far"]
    assert p["planned_hours"] == 142 * 2 * 8
    assert p["work_type"] == "Polish" and p["deadline"] == "2026-11-27"


# ── one row per Project; Planned hours ────────────────────────────────────────
ACME_1 = mob("a1", "26.125, Acme Clinic Psych (6) (Pat)", "2026-11-02", "2026-11-06", "11")
ACME_2 = mob("a2", "26.125, Acme Clinic Psych - 2nd Mob (4) (Kim)", "2026-11-16", "2026-11-20", "11")


def test_mobilizations_with_one_job_number_are_one_row_and_each_brings_its_own_crew_size(
        client, google):
    """1st Mob: Mon Nov 2 to Fri Nov 6, 6 people, all five days done = 240 h. 2nd Mob: Mon Nov 16 to
    Fri Nov 20, 4 people, Mon and Tue done (today is Wed) = 64 h."""
    google.events = [ACME_2, ACME_1]
    (p,) = rows(client)
    assert [m["id"] for m in p["mobilizations"]] == ["a1", "a2"]
    assert [m["workdays_so_far"] for m in p["mobilizations"]] == [5, 2]
    assert p["workdays_so_far"] == 7
    assert p["planned_hours"] == 5 * 6 * 8 + 2 * 4 * 8 == 304
    assert p["crew_size"] == 4, "the Crew size of the Mobilization running today"
    assert p["foreman"] == "Kim"
    assert p["start"] == "2026-11-02" and p["deadline"] == "2026-11-20"
    assert p["crew_size_missing"] is False


def test_without_a_mobilization_today_the_crew_is_the_most_recent_ones(client, google):
    google.events = [ACME_1, mob("a2", "26.125, Acme Clinic Psych - 2nd Mob (4)",
                                 "2026-11-10", "2026-11-13", "11"),
                     mob("a3", "26.125, Acme Clinic Psych - 3rd Mob (3)", "2026-11-23",
                         "2026-11-24", "11")]
    p = row(client, "job:26.125")
    assert p["crew_size"] == 4, "Nov 10-13 is the most recent to have started"
    assert p["deadline"] == "2026-11-24"


def test_a_job_not_started_takes_the_crew_of_its_first_mobilization(client, google):
    google.events = [mob("n", "26.140, Example Annex (5) (Lee)", "2026-11-23", "2026-11-25")]
    p = row(client, "job:26.140")
    assert p["crew_size"] == 5 and p["planned_hours"] == 0 and p["workdays_so_far"] == 0


def test_a_mobilization_with_no_crew_size_adds_nothing_and_the_row_says_so(client, google):
    google.events = [ACME_1, mob("a2", "26.125, Acme Clinic Psych - 2nd Mob (Kim)",
                                 "2026-11-16", "2026-11-20", "11")]
    p = row(client, "job:26.125")
    assert p["planned_hours"] == 5 * 6 * 8, "two days with no Crew size add nothing"
    assert p["workdays_so_far"] == 7, "the days are still booked"
    assert p["crew_size_missing"] is True
    assert p["crew_size"] is None, "never zero people"


def test_with_no_job_number_mobilizations_group_by_name_ignoring_case_and_spacing(client, google):
    google.events = [mob("d1", "Example Diner (4)", "2026-11-09", "2026-11-10"),
                     mob("d2", "example  diner - 2nd Mob (2)", "2026-11-17", "2026-11-19"),
                     mob("x", "Example Depot (3)", "2026-11-17", "2026-11-19")]
    keys = sorted(p["key"] for p in rows(client))
    assert keys == ["name:exampledepot", "name:examplediner"]
    p = row(client, "name:examplediner")
    assert p["job_number"] is None
    assert p["planned_hours"] == 2 * 4 * 8 + 1 * 2 * 8


# ── Punches ───────────────────────────────────────────────────────────────────
def test_a_punch_joins_the_job_with_its_job_number_and_never_moves_the_deadline(client, google):
    google.events = [ACME_1, mob("p", "26.125, Acme Clinic Psych Punch (2) (Lee)",
                                 "2026-11-12", "2026-11-12", "11")]
    (p,) = rows(client)
    assert p["key"] == "job:26.125" and p["is_punch"] is False
    assert [m["id"] for m in p["punches"]] == ["p"]
    assert p["punches"][0]["crew_size"] == 2
    assert p["punches"][0]["html_link"] == "https://calendar.example/event?eid=p"
    assert p["deadline"] == "2026-11-06", "the end of the last Mobilization that is not a Punch"
    assert p["workdays_so_far"] == 6 and p["planned_hours"] == 5 * 6 * 8 + 1 * 2 * 8
    assert p["crew_size"] == 2, "the Punch is the most recent Mobilization"


def test_a_punch_with_no_job_number_joins_the_job_with_its_name_minus_punch(client, google):
    """Case and spacing are ignored; the job may carry a Job number the Punch does not."""
    google.events = [ACME_1, mob("p", "acme clinic  PSYCH Punch - (1) (Lee)",
                                 "2026-11-12", "2026-11-12")]
    (p,) = rows(client)
    assert p["key"] == "job:26.125"
    assert [m["id"] for m in p["punches"]] == ["p"]


def test_a_punch_that_matches_no_job_is_its_own_row_labelled_punch(client, google):
    google.events = [ACME_1, mob("p", "Example Shop Punch - (1) (Lee)", "2026-11-19", "2026-11-19")]
    by_key = {p["key"]: p for p in rows(client)}
    p = by_key["punch:name:exampleshoppunch"]
    assert p["is_punch"] is True and p["label"] == "Punch"
    assert p["mobilizations"] == [] and [m["id"] for m in p["punches"]] == ["p"]
    assert p["start"] == p["deadline"] == "2026-11-19"
    assert p["foreman"] == "Lee" and p["crew_size"] == 1
    assert by_key["job:26.125"]["punches"] == []


def test_a_punch_whose_job_number_has_no_job_is_its_own_row(client, google):
    google.events = [mob("p", "26.999, Example Lofts Punch (2)", "2026-11-17", "2026-11-17")]
    (p,) = rows(client)
    assert p["key"] == "punch:job:26.999" and p["label"] == "Punch" and p["job_number"] == "26.999"
    assert p["planned_hours"] == 16


# ── a job half relabelled (#792) ──────────────────────────────────────────────
def test_a_first_mob_without_a_job_number_joins_the_second_mob_that_has_one(client, google):
    """While Darrin relabels the calendar the 1st Mob still reads by name and the 2nd Mob carries
    the Job number: one row, under the Job number. 1st Mob: Mon Nov 9 to Wed Nov 18 (running today),
    6 people, Nov 9-17 done = 7 Workdays = 336 h. 2nd Mob: Mon Nov 23 to Wed Nov 25, 4 people."""
    google.events = [mob("u1", "example  CLINIC (6) (Pat)", "2026-11-09", "2026-11-18", "11"),
                     mob("n2", "26.210, Example Clinic - 2nd Mob (4) (Kim)", "2026-11-23",
                         "2026-11-25", "11")]
    (p,) = rows(client)
    assert p["key"] == "job:26.210" and p["job_number"] == "26.210"
    assert [m["id"] for m in p["mobilizations"]] == ["u1", "n2"]
    assert p["start"] == "2026-11-09" and p["deadline"] == "2026-11-25"
    assert p["workdays_so_far"] == 7 and p["planned_hours"] == 7 * 6 * 8
    assert p["crew_size"] == 6 and p["foreman"] == "Pat", "the unnumbered Mob is running today"


def test_a_later_mob_without_a_job_number_sets_the_deadline_of_the_numbered_job(client, google):
    google.events = [mob("n1", "26.211, Example Lofts (3) (Kim)", "2026-11-02", "2026-11-06"),
                     mob("u2", "Example Lofts - 2nd Mob (2) (Lee)", "2026-11-16", "2026-11-24")]
    (p,) = rows(client)
    assert p["key"] == "job:26.211"
    assert p["deadline"] == "2026-11-24" and p["timing"] == "running" and p["workdays_left"] == 5
    assert p["workdays_so_far"] == 7 and p["planned_hours"] == 5 * 3 * 8 + 2 * 2 * 8
    assert p["crew_size"] == 2


def test_a_punch_whose_job_number_matches_nothing_joins_the_job_with_its_name(client, google):
    """The Punch was relabelled with a Job number the job's own Mobilizations do not carry (yet, or
    by a slip): its name still finds the job before it becomes a row of its own."""
    google.events = [ACME_1, mob("p", "26.912, Acme Clinic Psych Punch (2) (Lee)",
                                 "2026-11-12", "2026-11-12", "11")]
    (p,) = rows(client)
    assert p["key"] == "job:26.125" and p["is_punch"] is False and p["label"] is None
    assert [m["id"] for m in p["punches"]] == ["p"]
    assert p["deadline"] == "2026-11-06"
    assert p["planned_hours"] == 5 * 6 * 8 + 1 * 2 * 8


def test_with_two_job_numbers_sharing_the_name_the_unnumbered_mob_stays_its_own_row(
        client, google):
    """Two jobs at the same place carry different Job numbers. A Mobilization with that name and no
    Job number could belong to either, so it is not merged into one: nothing is guessed."""
    google.events = [mob("j1", "26.301, Example Tower (3)", "2026-11-09", "2026-11-13"),
                     mob("j2", "26.302, Example Tower (2)", "2026-11-16", "2026-11-20"),
                     mob("u", "example tower (5)", "2026-11-17", "2026-11-19")]
    by_key = {p["key"]: p for p in rows(client)}
    assert sorted(by_key) == ["job:26.301", "job:26.302", "name:exampletower"]
    assert [m["id"] for m in by_key["job:26.301"]["mobilizations"]] == ["j1"]
    assert [m["id"] for m in by_key["job:26.302"]["mobilizations"]] == ["j2"]
    u = by_key["name:exampletower"]
    assert u["job_number"] is None and [m["id"] for m in u["mobilizations"]] == ["u"]
    assert u["planned_hours"] == 1 * 5 * 8


# ── the window ────────────────────────────────────────────────────────────────
def test_the_window_is_running_now_finished_in_the_last_14_days_or_starting_in_the_next_14(
        client, google):
    google.events = [
        mob("run", "26.001, Running Job (2)", "2026-11-18", "2026-11-18"),
        mob("d14", "26.002, Finished Fourteen Days Ago (2)", "2026-11-02", "2026-11-04"),
        mob("d15", "26.003, Finished Fifteen Days Ago (2)", "2026-11-02", "2026-11-03"),
        mob("s14", "26.004, Starts In Fourteen Days (2)", "2026-12-02", "2026-12-04"),
        mob("s15", "26.005, Starts In Fifteen Days (2)", "2026-12-03", "2026-12-04"),
        mob("old", "26.006, Long Finished (2)", "2026-03-02", "2026-03-06"),
    ]
    assert sorted(p["job_number"] for p in rows(client)) == ["26.001", "26.002", "26.004"]


def test_an_old_job_with_a_punch_near_today_is_listed_with_every_mobilization_counted(
        client, google):
    """The main work ended in March; a Punch on Thu Nov 26 (8 days ahead) brings it back, and its
    Planned hours still count the March week."""
    google.events = [mob("m", "26.050, Example Plaza (3) (Sam)", "2026-03-02", "2026-03-06", "10"),
                     mob("p", "26.050, Example Plaza Punch (1) (Sam)", "2026-11-26", "2026-11-26")]
    p = row(client, "job:26.050")
    assert p["deadline"] == "2026-03-06" and p["timing"] == "finished"
    assert p["planned_hours"] == 5 * 3 * 8
    assert p["work_type"] == "Gyp"


def test_a_punch_counts_for_the_window_only_on_a_workday_within_14_days(client, google):
    """Sat Nov 28 and Sun Nov 29 are inside the 14 days but are not Workdays; Wed Dec 2 is the last
    day in; Thu Dec 3 is one too far."""
    google.events = [
        mob("m1", "26.061, Weekend Job (3)", "2026-03-02", "2026-03-06"),
        mob("p1", "26.061, Weekend Job Punch (1)", "2026-11-28", "2026-11-29"),
        mob("m2", "26.062, Edge Job (3)", "2026-03-02", "2026-03-06"),
        mob("p2", "26.062, Edge Job Punch (1)", "2026-12-02", "2026-12-02"),
        mob("m3", "26.063, Late Job (3)", "2026-03-02", "2026-03-06"),
        mob("p3", "26.063, Late Job Punch (1)", "2026-12-03", "2026-12-03"),
        mob("m4", "26.064, Early Job (3)", "2026-03-02", "2026-03-06"),
        mob("p4", "26.064, Early Job Punch (1)", "2026-11-04", "2026-11-04"),
    ]
    assert sorted(p["job_number"] for p in rows(client)) == ["26.062", "26.064"]


# ── Workdays left; weekends; "so far" stops at yesterday ──────────────────────
def test_workdays_left_count_monday_to_friday_from_today(client, google):
    """Wed Nov 18 to Tue Nov 24: Wed, Thu, Fri, Mon, Tue."""
    google.events = [mob("a", "26.070, Example Hall (2)", "2026-11-16", "2026-11-24")]
    p = row(client, "job:26.070")
    assert p["timing"] == "running" and p["workdays_left"] == 5


def test_a_job_not_started_says_starts_and_a_finished_one_says_finished(client, google):
    google.events = [mob("s", "26.071, Not Started Yet (2)", "2026-11-23", "2026-11-24"),
                     mob("f", "26.072, Already Done (2)", "2026-11-09", "2026-11-17")]
    s, f = row(client, "job:26.071"), row(client, "job:26.072")
    assert s["timing"] == "starts" and s["workdays_left"] is None and s["start"] == "2026-11-23"
    assert f["timing"] == "finished" and f["workdays_left"] is None


def test_weekends_are_never_booked_or_planned(client, google):
    """Thu Nov 12 to Tue Nov 17 crosses a weekend: Thu, Fri, Mon, Tue."""
    google.events = [mob("w", "26.073, Weekend Crossing (5)", "2026-11-12", "2026-11-17")]
    p = row(client, "job:26.073")
    assert p["workdays_so_far"] == 4 and p["planned_hours"] == 4 * 5 * 8


def test_so_far_stops_at_yesterday(client, google):
    """A Mobilization that starts today has booked nothing so far."""
    google.events = [mob("t", "26.074, Starts Today (6)", "2026-11-18", "2026-11-20")]
    p = row(client, "job:26.074")
    assert p["workdays_so_far"] == 0 and p["planned_hours"] == 0
    assert p["timing"] == "running" and p["workdays_left"] == 3 and p["crew_size"] == 6


def test_overlapping_mobilizations_book_a_day_once_but_plan_both_crews(client, google):
    google.events = [mob("a", "26.075, Two Crews (3)", "2026-11-16", "2026-11-17"),
                     mob("b", "26.075, Two Crews - 2nd Mob (2)", "2026-11-17", "2026-11-19")]
    p = row(client, "job:26.075")
    assert p["workdays_so_far"] == 2
    assert p["planned_hours"] == 2 * 3 * 8 + 1 * 2 * 8


# ── not connected, failures, the tool Project ─────────────────────────────────
def test_with_nothing_configured_it_says_not_connected(client, monkeypatch, drafts_db):
    monkeypatch.delenv("PROJECT_CALENDAR_ID", raising=False)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY)
    body = get(client)
    assert body["connected"] is False and body["projects"] == [] and body["error"] is None
    assert body["raken"] == {"state": "not_connected"}


def test_a_google_failure_with_nothing_saved_is_a_plain_error_not_a_500(client, google):
    google.fail = True
    body = get(client)
    assert body["ok"] is True and body["connected"] is True and body["projects"] == []
    assert body["error"] == "Google Calendar could not be reached."


def test_a_google_failure_after_a_good_read_serves_the_last_copy_as_stale(client, google):
    google.events = [ACME_2]
    first = get(client)
    google.fail = True
    body = get(client)
    assert body["stale"] is True and body["error"] == "Google Calendar could not be reached."
    assert [p["key"] for p in body["projects"]] == ["job:26.125"]
    assert body["fetched_at"] == first["fetched_at"]


def test_a_google_failure_the_day_after_a_good_read_still_serves_yesterdays_copy(
        client, google, monkeypatch):
    """The year read moves by a day at Central midnight. Yesterday's copy must still answer the
    first read of the new day when Google fails, not an empty list."""
    google.events = [ACME_2]
    first = get(client)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY + dt.timedelta(days=1))
    google.fail = True
    body = get(client)
    assert body["today"] == "2026-11-19"
    assert body["stale"] is True and body["error"] == "Google Calendar could not be reached."
    assert [p["key"] for p in body["projects"]] == ["job:26.125"]
    assert body["fetched_at"] == first["fetched_at"]


def test_a_mobilization_before_the_year_read_is_never_counted(client, google):
    """Only the year before today is read, whatever piece of it Google is asked for, so a job's
    figures never depend on how the read happens to be cut up."""
    google.events = [mob("old", "26.040, Example Depot (5) (Kim)", "2025-10-06", "2025-10-10"),
                     mob("p", "26.040, Example Depot Punch (1) (Kim)", "2026-11-17", "2026-11-17")]
    (p,) = rows(client)
    assert p["mobilizations"] == [] and len(p["punches"]) == 1
    assert p["planned_hours"] == 1 * 1 * 8


def test_a_listed_job_links_to_the_tool_project_with_its_job_number(client, google, drafts_db):
    drafts_db.rows = [{"id": "d-home", "created_at": "2026-02-01", "job_number": "26.125",
                       "project_name": "Acme Clinic Psych"}]
    google.events = [ACME_2, mob("x", "Example Diner (4)", "2026-11-17", "2026-11-19")]
    by_key = {p["key"]: p for p in rows(client)}
    assert by_key["job:26.125"]["project"] == {"id": "d-home", "name": "Acme Clinic Psych"}
    assert by_key["name:examplediner"]["project"] is None
    assert drafts_db.queries == 1, "one query for the whole list"


def test_the_list_runs_by_deadline_and_carries_the_flags(client, google):
    google.events = [mob("b", "26.081, Bravo Hall - (PW) (2)", "2026-11-16", "2026-11-25"),
                     mob("a", "26.080, Alpha Hall (2) Night Work", "2026-11-16", "2026-11-19")]
    got = rows(client)
    assert [p["job_number"] for p in got] == ["26.080", "26.081"]
    assert got[0]["night_work"] is True and got[0]["prevailing_wage"] is False
    assert got[1]["prevailing_wage"] is True


def test_the_page_route_is_hide_only_like_every_tab(client, google, tmp_path, monkeypatch):
    """A role denied Project Analytics loses the tab and the page; the route still answers."""
    import nav_access
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
    nav_access.save({"user": ["/project-calendar.html"]}, "admin@made-up.example")
    assert client.get(URL).status_code == 200


def test_a_fault_building_the_list_is_a_plain_error_not_a_500(client, google, monkeypatch):
    import plan_vs_actual

    def boom(events, today):
        raise ValueError("unexpected event shape")

    monkeypatch.setattr(plan_vs_actual, "build", boom)
    google.events = [ACME_2]
    body = get(client)
    assert body["ok"] is True and body["projects"] == []
    assert body["error"] == "Plan vs Actual could not be worked out just now."
