"""Plan vs Actual, the summary strip (#788): the status counts, last week's Planned hours against
Actual hours, and the Budget totals, built on the server in the same response as the list.

Exercised THROUGH THE HTTP API with test_raken_actuals' fake Google calendar and fake Raken. The
claims that cost something when they are wrong:

  * The four counts follow each row's own flags. A job Behind AND Over budget counts under both, so
    the counts can add up to more than the jobs. A job whose Raken budget was not read carries no
    flag (it could be Over budget), so it is counted under none; a job with no Raken budget is never
    Over budget. With Raken not read, the counts are no figure, never four zeros.
  * Last week is the previous Monday to Friday in Central: Planned hours from each booked Workday
    that week (that day's planned crew x 8, the day-by-day's own figure), Actual hours from that
    week's time cards, both summed over LINKED jobs. A weekend adds nothing to either. With Raken
    not read, the planned figure still shows and Actual hours are no figure, never 0. A day with
    no Crew size is flagged, never quietly short.
  * The Budget totals add up only the jobs whose Budget pair was read with a Raken budget, and say
    how many jobs that is.

"Today" is Wednesday 2026-11-18 (Central), so last week is Mon 2026-11-09 to Fri 2026-11-13. PUBLIC
REPO: every job, project, number and id below is made up.
"""
import datetime as dt

import plan_vs_actual
import project_calendar as pc
import raken
import raken_actuals
from test_plan_vs_actual import TODAY, mob
from test_raken_actuals import (_clean, card, client, fake, get, google,  # noqa: F401
                                project, refresh)
from test_raken_budget import division


def summary(body):
    return body["summary"]


# Five jobs running this week, Mon Nov 16 to Fri Nov 20, two people each; booked so far Mon, Tue.
def five_jobs(google, fake):
    google.events = [mob(k, "26.50%d, Example Job %d (2)" % (n, n), "2026-11-16", "2026-11-20")
                     for k, n in (("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5))]
    # 26.503 has no Raken project: Not linked.
    fake.projects = [project("r-%d" % n, "26.50%d" % n, "Example Job %d" % n) for n in (1, 2, 4, 5)]
    both_days = ("2026-11-16", "2026-11-17")
    fake.cards = ([card("r-1", d, "w-1", 8) for d in both_days]
                  + [card("r-2", "2026-11-16", "w-2", 8)]            # Tuesday missed: Behind
                  + [card("r-4", d, "w-4", 8) for d in both_days]
                  + [card("r-5", d, "w-5", 8) for d in both_days])
    fake.insights = {"r-1": [division("01", 100, 90)],              # under: On plan
                     "r-2": [division("01", 100, 130)],             # over: Over budget, and Behind
                     "r-4": [division("01", 100, 90)]}              # its read fails: not read
    fake.insight_fail = {"r-4"}
    # r-5 has no Raken budget: never Over budget.


# ── the four counts ───────────────────────────────────────────────────────────
def test_the_counts_follow_each_jobs_flags_and_a_job_with_two_counts_under_both(
        client, google, fake):
    five_jobs(google, fake)
    body = refresh(client)
    flags = {p["job_number"]: p["statuses"] for p in body["projects"]}
    assert flags == {"26.501": ["on_plan"], "26.502": ["behind", "over_budget"],
                     "26.503": ["not_linked"], "26.504": [], "26.505": ["on_plan"]}
    s = summary(body)
    assert s["counts"] == {"on_plan": 2, "behind": 1, "over_budget": 1, "not_linked": 1}
    assert s["raken_read"] is True
    assert s["unflagged"] == 1, "26.504, its budget not read, is in no count: the strip says so"
    assert s["jobs"] == 5
    assert summary(get(client)) == s, "the GET carries the same strip"


# ── last week ─────────────────────────────────────────────────────────────────
# Example Gym, linked to Raken project r-6:
#   1st Mob Thu Nov 5 to Tue Nov 10, 3 people: last week Mon Nov 9 and Tue Nov 10 = 2 x 3 x 8 = 48;
#   its Thu/Fri belong to the week before, and the weekend between adds nothing;
#   a Punch Wed Nov 11, 1 person = 8;
#   2nd Mob Thu Nov 12 to Mon Nov 16, 5 people (the Crew size changed): Thu, Fri = 2 x 5 x 8 = 80;
#   Sat Nov 14 and Sun Nov 15 add nothing; Mon Nov 16 is this week.
# Planned last week: 48 + 8 + 80 = 136.
GYM = [mob("g1", "26.601, Example Gym (3) (Pat)", "2026-11-05", "2026-11-10"),
       mob("gp", "26.601, Example Gym Punch (1) (Lee)", "2026-11-11", "2026-11-11"),
       mob("g2", "26.601, Example Gym - 2nd Mob (5) (Pat)", "2026-11-12", "2026-11-16")]
GYM_CARDS = [card("r-6", "2026-11-06", "w-1", 8),        # the week before: not counted
             card("r-6", "2026-11-09", "w-1", 8), card("r-6", "2026-11-09", "w-2", 7.5),
             card("r-6", "2026-11-10", "w-1", 8),
             card("r-6", "2026-11-11", "w-3", 4),        # the Punch
             card("r-6", "2026-11-13", "w-1", 9),
             card("r-6", "2026-11-14", "w-1", 6),        # a Saturday: not Monday to Friday
             card("r-6", "2026-11-16", "w-1", 8)]        # this week: not counted
# Example Depot, linked to r-7, Mon Nov 9 to Wed Nov 11, 2 people: 3 x 2 x 8 = 48 planned last week;
# its cards include Thursday Nov 12, a day the calendar did not book: still last week's hours.
DEPOT = mob("d1", "26.602, Example Depot (2)", "2026-11-09", "2026-11-11")
DEPOT_CARDS = [card("r-7", "2026-11-09", "w-5", 8), card("r-7", "2026-11-12", "w-5", 3)]
# Example Annex is Not linked (no Raken project carries 26.603): its plan is left out.
ANNEX = mob("x1", "26.603, Example Annex (4)", "2026-11-09", "2026-11-13")


def gym_depot_annex(google, fake):
    google.events = GYM + [DEPOT, ANNEX]
    fake.projects = [project("r-6", "26.601", "Example Gym"), project("r-7", "26.602", "Example Depot")]
    fake.cards = GYM_CARDS + DEPOT_CARDS


def test_last_week_sets_planned_against_actual_hours_over_linked_jobs(client, google, fake):
    gym_depot_annex(google, fake)
    w = summary(refresh(client))["last_week"]
    assert (w["from"], w["to"]) == ("2026-11-09", "2026-11-13"), "the previous Monday to Friday"
    assert w["planned_hours"] == 136 + 48, "the Not linked job's 160 planned hours left out"
    # Gym: 8 + 7.5 + 8 + 4 + 9 = 36.5; Depot: 8 + 3 = 11.
    assert w["actual_hours"] == 47.5
    assert w["jobs"] == 2
    assert w["raken"] == "read"


def test_with_raken_not_read_last_week_shows_the_plan_and_no_actual_figure(client, google, fake):
    """Nothing says which jobs are linked until Raken is read, so the plan of every listed job
    shows; Actual hours are no figure, never 0."""
    raken.TOKEN_FILE.unlink()
    gym_depot_annex(google, fake)
    for body in (refresh(client), get(client)):
        s = summary(body)
        assert s["last_week"]["raken"] == "not_read"
        assert s["last_week"]["actual_hours"] is None
        assert s["last_week"]["planned_hours"] == 136 + 48 + 160
        assert s["last_week"]["jobs"] == 3
        assert s["raken_read"] is False
        assert s["counts"] is None, "unknown, never four zeros"
        assert s["unflagged"] is None
    assert fake.card_calls == []


def test_with_raken_not_read_a_job_with_no_job_number_adds_no_plan(client, google, fake):
    """A job with no Job number can never be linked, so even unread its plan is left out: the
    figure is no larger than it can be once Raken is read."""
    raken.TOKEN_FILE.unlink()
    gym_depot_annex(google, fake)
    google.events = google.events + [mob("s1", "Example Shed (2)", "2026-11-09", "2026-11-13")]
    w = summary(refresh(client))["last_week"]
    assert w["planned_hours"] == 136 + 48 + 160 and w["jobs"] == 3


# Example Kiln, linked to r-8, Mon Nov 9 to Fri Nov 13, its title gives no Crew size.
KILN = mob("k1", "26.604, Example Kiln (Kim)", "2026-11-09", "2026-11-13")


def test_a_workday_last_week_with_no_crew_size_is_flagged_never_quietly_short(
        client, google, fake):
    """Its days add nothing to Planned hours, so the figure is short: the strip says so."""
    gym_depot_annex(google, fake)
    google.events = google.events + [KILN]
    fake.projects = fake.projects + [project("r-8", "26.604", "Example Kiln")]
    w = summary(refresh(client))["last_week"]
    assert w["planned_hours"] == 136 + 48 and w["crew_size_missing"] is True


def test_with_no_crew_size_known_all_last_week_planned_hours_are_no_figure(
        client, google, fake):
    """Every Workday booked last week has no Crew size: Planned hours are unknown, never 0."""
    google.events = [KILN]
    fake.projects = [project("r-8", "26.604", "Example Kiln")]
    w = summary(refresh(client))["last_week"]
    assert w["planned_hours"] is None and w["crew_size_missing"] is True


def test_with_every_crew_size_known_last_week_is_not_flagged(client, google, fake):
    gym_depot_annex(google, fake)
    assert summary(refresh(client))["last_week"]["crew_size_missing"] is False


def test_raken_not_turned_on_yet_is_not_read_too(client, google, fake):
    fake.refuse = {"message": "made-up refusal", "code": "API_KEY_NOT_FOUND"}
    gym_depot_annex(google, fake)
    w = summary(refresh(client))["last_week"]
    assert w["raken"] == "not_read" and w["actual_hours"] is None
    assert w["planned_hours"] == 136 + 48 + 160


def test_a_kept_read_that_stops_short_of_last_week_gives_no_actual_figure(
        client, google, fake, monkeypatch):
    """Read on Thursday Nov 12 (through Wednesday Nov 11), shown on Wednesday Nov 18: the read
    never saw last Thursday and Friday, so last week's Actual hours would be short. No figure."""
    gym_depot_annex(google, fake)
    monkeypatch.setattr(pc, "today_central", lambda: dt.date(2026, 11, 12))
    refresh(client)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY)
    pc.cache_clear()
    w = summary(get(client))["last_week"]
    assert w["raken"] == "not_covered" and w["actual_hours"] is None
    assert w["planned_hours"] == 136 + 48 and w["jobs"] == 2


# ── the Budget totals ─────────────────────────────────────────────────────────
def test_the_budget_totals_add_up_only_the_jobs_with_a_raken_budget_read(client, google, fake):
    """26.501 (100 budgeted, 90 projected) and 26.502 (100, 130) have both. 26.504's budget was
    not read, 26.505 has no Raken budget and 26.503 is Not linked: none of them is added."""
    five_jobs(google, fake)
    b = summary(refresh(client))["budget"]
    assert b["budgeted_hours"] == 200 and b["projected_total_hours"] == 220
    assert b["over_under"] == -20
    assert b["jobs"] == 2, "how many jobs the totals cover"
    assert b["linked_jobs"] == 4


def test_with_no_raken_budget_read_the_totals_are_no_figure(client, google, fake):
    raken.TOKEN_FILE.unlink()
    five_jobs(google, fake)
    b = summary(refresh(client))["budget"]
    assert b == {"budgeted_hours": None, "projected_total_hours": None, "over_under": None,
                 "jobs": 0, "linked_jobs": 0}


# ── never a 500 ───────────────────────────────────────────────────────────────
def test_when_the_raken_side_cannot_be_set_the_strip_keeps_its_shape(
        client, google, fake, monkeypatch):
    gym_depot_annex(google, fake)
    good = summary(refresh(client))

    def broken(*_a, **_k):
        raise RuntimeError("made-up fault")
    monkeypatch.setattr(raken_actuals, "_row", broken)
    s = summary(get(client))
    assert set(s) == set(good) and set(s["last_week"]) == set(good["last_week"])
    assert s["counts"] is None and s["raken_read"] is False, "not read: unknown, not zeros"
    assert s["last_week"]["raken"] == "not_read" and s["last_week"]["actual_hours"] is None
    assert s["budget"]["jobs"] == 0


def test_when_the_strip_cannot_be_worked_out_the_list_still_shows(
        client, google, fake, monkeypatch):
    gym_depot_annex(google, fake)
    good = summary(refresh(client))

    def broken(*_a, **_k):
        raise RuntimeError("made-up fault")
    monkeypatch.setattr(plan_vs_actual, "_last_week", broken)
    body = get(client)
    assert len(body["projects"]) == 3
    assert body["summary"] is None, "no strip rather than a wrong one"
    assert good is not None


def test_with_the_calendar_not_connected_the_strip_counts_nothing(client, monkeypatch):
    monkeypatch.setattr(pc, "_make_source", lambda: None)
    monkeypatch.delenv("PROJECT_CALENDAR_ID", raising=False)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY)
    body = get(client)
    assert body["connected"] is False
    s = summary(body)
    assert s["jobs"] == 0 and s["counts"] is None and s["raken_read"] is False
    assert s["last_week"]["planned_hours"] == 0 and s["budget"]["jobs"] == 0
