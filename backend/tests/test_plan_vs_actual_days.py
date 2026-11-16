"""Plan vs Actual, a job's day-by-day (#789): one entry per Workday of its Mobilizations and Punches.

The job detail's chart draws one column per Workday the calendar booked for the job, Punches
included, in date order. The SERVER builds those entries; the page only lays them out. Each entry
carries the plan (the Crew size booked that day, added up when two Mobilizations overlap, and that
times the hours in a workday) and, for a linked job up to yesterday, what Raken's time cards
recorded that day (the distinct people with hours, and the hours). A booked Workday nobody clocked
in on is marked missed; a day from today on carries the plan only.

Exercised THROUGH THE HTTP API with test_raken_actuals' fake Raken and fake Google calendar, as
test_raken_actuals is. "Today" is Wednesday 2026-11-18 (Central), so Raken is read through Tuesday
2026-11-17. PUBLIC REPO: every job, person, project, number and id below is made up.
"""
from test_plan_vs_actual import mob
from test_raken_actuals import (  # noqa: F401 - fixtures, found by pytest by name
    JOB, _clean, by_key, card, client, fake, get, google, project, refresh)


def days_of(row):
    return {d["date"]: d for d in row["day_by_day"]}


def test_overlapping_mobilizations_add_their_crews_and_weekends_are_skipped(client, google, fake):
    """1st Mob Mon Nov 9 to Fri Nov 13, 3 people; 2nd Mob Thu Nov 12 to Tue Nov 17, 2 people. The
    two overlap on Thu and Fri; the weekend between is never a column."""
    google.events = [mob("a", "26.520, Example Arena (3) (Pat)", "2026-11-09", "2026-11-13"),
                     mob("b", "26.520, Example Arena - 2nd Mob - (2) (Pat)", "2026-11-12",
                         "2026-11-17")]
    row = by_key(get(client))["job:26.520"]
    entries = row["day_by_day"]
    assert [d["date"] for d in entries] == [
        "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13",
        "2026-11-16", "2026-11-17"], "one column per Workday, in date order, no weekend"
    assert [d["planned_crew"] for d in entries] == [3, 3, 3, 5, 5, 2, 2]
    assert [d["planned_hours"] for d in entries] == [24, 24, 24, 40, 40, 16, 16]
    assert not any(d["future"] for d in entries)
    # Not connected to Raken here: the plan only.
    assert all(d["on_site"] is None and d["hours"] is None and d["missed"] is False
               for d in entries)


def test_a_linked_job_carries_each_days_people_on_site_and_hours_and_a_missed_day(
        client, google, fake):
    """Booked Mon Nov 16 and Tue Nov 17 so far: two people clocked in Monday, nobody Tuesday."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-16", "w-2", 7.5),
                  card("r-1", "2026-11-16", "w-2", 0.5)]
    row = by_key(refresh(client))["job:26.501"]
    d = days_of(row)
    assert d["2026-11-16"]["on_site"] == 2, "distinct people, not cards"
    assert d["2026-11-16"]["hours"] == 16
    assert d["2026-11-16"]["missed"] is False
    assert d["2026-11-17"]["on_site"] == 0 and d["2026-11-17"]["hours"] == 0
    assert d["2026-11-17"]["missed"] is True, "a booked Workday with no time-card hours"
    assert d["2026-11-17"]["planned_crew"] == 3 and d["2026-11-17"]["planned_hours"] == 24


def test_days_from_today_on_carry_the_plan_only(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8),
                  card("r-1", "2026-11-18", "w-1", 8)]
    row = by_key(refresh(client))["job:26.501"]
    d = days_of(row)
    assert [k for k, v in sorted(d.items()) if v["future"]] == [
        "2026-11-18", "2026-11-19", "2026-11-20"], "today and after"
    for day in ("2026-11-18", "2026-11-19", "2026-11-20"):
        assert d[day]["on_site"] is None and d[day]["hours"] is None
        assert d[day]["missed"] is False, "a day still to come is never missed"
        assert d[day]["planned_crew"] == 3 and d[day]["planned_hours"] == 24
    assert d["2026-11-17"]["future"] is False and d["2026-11-17"]["hours"] == 8


def test_a_punch_is_a_column_of_its_parent_with_its_own_crew_and_hours(client, google, fake):
    """The job ran Mon Nov 2 to Fri Nov 6; its Punch, Thu Nov 12, carries another Job number and
    joins it by name. The Punch's day is a column of the job, its hours from its own Raken project."""
    google.events = [mob("m", "26.125, Acme Clinic Psych (2) (Pat)", "2026-11-02", "2026-11-06"),
                     mob("p", "26.912, Acme Clinic Psych Punch (1) (Lee)", "2026-11-12",
                         "2026-11-12")]
    fake.projects = [project("r-1", "26.125", "Acme Clinic Psych"),
                     project("r-2", "26.912", "Acme Clinic Psych Punch")]
    fake.cards = [card("r-1", day, w, 8) for day in ("2026-11-02", "2026-11-03", "2026-11-04",
                                                       "2026-11-05", "2026-11-06")
                  for w in ("w-1", "w-2")] + [card("r-2", "2026-11-12", "w-3", 4)]
    (row,) = refresh(client)["projects"]
    entries = row["day_by_day"]
    assert [d["date"] for d in entries] == [
        "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-12"]
    punch = entries[-1]
    assert punch["planned_crew"] == 1 and punch["planned_hours"] == 8
    assert punch["on_site"] == 1 and punch["hours"] == 4 and punch["missed"] is False
    assert entries[0]["on_site"] == 2 and entries[0]["hours"] == 16


def test_a_not_linked_job_has_the_plan_only(client, google, fake):
    google.events = [mob("a", "26.502, Example Depot (2)", "2026-11-16", "2026-11-20")]
    fake.projects = [project("r-9", "26.999", "Example Elsewhere")]
    fake.cards = [card("r-9", "2026-11-16", "w-1", 8)]
    row = by_key(refresh(client))["job:26.502"]
    assert row["statuses"] == ["not_linked"]
    assert [d["planned_crew"] for d in row["day_by_day"]] == [2, 2, 2, 2, 2]
    assert all(d["on_site"] is None and d["hours"] is None and d["missed"] is False
               for d in row["day_by_day"]), "nothing to compare a Not linked job with"


def test_a_mobilization_with_no_crew_size_plans_nobody_and_says_so(client, google, fake):
    """No crew number in the title: the day's plan is unknown, never zero people."""
    google.events = [mob("a", "26.503, Example Annex", "2026-11-16", "2026-11-17"),
                     mob("b", "26.503, Example Annex - 2nd Mob - (2)", "2026-11-17", "2026-11-17")]
    d = days_of(by_key(get(client))["job:26.503"])
    assert d["2026-11-16"]["planned_crew"] is None and d["2026-11-16"]["planned_hours"] is None
    assert d["2026-11-16"]["crew_size_missing"] is True
    # Tuesday: one Mobilization without a Crew size beside one with 2. The 2 is shown, and the
    # day still says a Crew size is missing.
    assert d["2026-11-17"]["planned_crew"] == 2 and d["2026-11-17"]["crew_size_missing"] is True


def test_the_get_serves_the_days_from_the_kept_read_without_calling_raken(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-2", 6)]
    refresh(client)
    calls = (fake.project_calls, len(fake.card_calls), len(fake.insight_calls))
    d = days_of(by_key(get(client))["job:26.501"])
    assert (fake.project_calls, len(fake.card_calls), len(fake.insight_calls)) == calls
    assert d["2026-11-16"]["hours"] == 8 and d["2026-11-17"]["hours"] == 6
    assert d["2026-11-17"]["on_site"] == 1

def test_a_mistyped_end_year_never_grows_the_days_past_the_read(client, google, fake):
    """A Google event ending in 2062 instead of 2026 still overlaps the year read, so it is listed,
    but its day-by-day stops where the read stops (today + READ_AHEAD_DAYS): no column, and no
    bytes in every GET, for the decades in between."""
    google.events = [mob("a", "26.530, Example Mistype (2)", "2026-11-16", "2062-11-20"), JOB]
    rows = by_key(get(client))
    entries = rows["job:26.530"]["day_by_day"]
    assert entries[0]["date"] == "2026-11-16"
    assert entries[-1]["date"] == "2026-12-02", "the read's last day, Wed Dec 2"
    assert len(entries) == 13
    assert "job:26.501" in rows


def test_an_event_ending_on_the_last_date_python_has_never_empties_the_list(client, google, fake):
    """A timed event ending on 9999-12-31 used to step one day past date.max: OverflowError, and
    the WHOLE list replaced by the build error. Only that event's own row may suffer, and here not
    even that: its days stop at the read."""
    google.events = [{"id": "z", "summary": "26.531, Example Forever (2)",
                      "start": {"dateTime": "2026-11-16T08:00:00-06:00"},
                      "end": {"dateTime": "9999-12-31T12:00:00-06:00"},
                      "htmlLink": "https://calendar.example/event?eid=z"}, JOB]
    body = get(client)
    assert not body.get("error"), body.get("error")
    rows = by_key(body)
    assert "job:26.501" in rows
    assert rows["job:26.531"]["day_by_day"][-1]["date"] == "2026-12-02"
