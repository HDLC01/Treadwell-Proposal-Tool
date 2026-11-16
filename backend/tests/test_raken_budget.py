"""Plan vs Actual, the Budget pair (#783): Budgeted hours against Projected total hours, with
Over/under, both from Raken's production insights; Over budget and On plan beside Behind.

Exercised THROUGH THE HTTP API with test_raken_actuals' fake Google calendar and fake Raken. The fake
answers GET /projects/{uuid}/productionInsights in the shape Raken's API docs give ("Get Production
Insights for a Project", read 2026-11-16): the {"page": {..."nextOffset": "10"}, "collection": [...]}
envelope, one item per cost-code division carrying "division", "budgetedHours",
"projectedTotalHours" (and "actualHours", "costCodes", which the tool does not read). The claims that
cost something when they are wrong:

  * Budgeted hours and Projected total hours are the sums of every division's, across every page,
    from ONE read, so the two never drift. Over/under = Budgeted - Projected total.
  * A job with no Raken budget shows neither figure nor Over/under, and is never Over budget.
  * Over budget when Over/under is below zero; Behind as #782 made it; both can show; On plan when
    linked and neither, and only when Raken's budget was read (none counts as read): a Budget pair
    not read could be Over budget. A Not linked job has no other status.
  * Projected total hours below the time-card Actual hours: the row says so.
  * The insights calls count inside the refresh's CALL_CAP. One project's insights failing leaves
    that row's Budget pair empty, says why, and fails nothing else.

"Today" is Wednesday 2026-11-18 (Central). PUBLIC REPO: every job, project, number and id below is
made up.
"""
import json

import pytest

import raken
import raken_actuals
from test_plan_vs_actual import mob
from test_raken_actuals import (JOB, _clean, by_key, card, client, fake, get, google,  # noqa: F401
                                project, refresh)


def division(name, budgeted, projected, actual=0.0):
    return {"division": name, "budgetedHours": budgeted, "actualHours": actual,
            "completeHoursPercent": 0, "remainingHours": None, "completeQuantityPercent": 0,
            "projectedTotalHours": projected, "projectedHoursGainOrLoss": None,
            "costCodes": [{"costCode": {"uuid": "made-up-cc", "code": "100", "division": name,
                                        "description": "Made-up cost code"},
                           "budgetedHours": 999999, "projectedTotalHours": 999999}]}


# Booked Mon Nov 16 and Tue Nov 17 so far; both clocked in, so never Behind unless a test says so.
ON_TIME = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8)]


def linked_job(fake, divisions, cards=None):
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = list(ON_TIME if cards is None else cards)
    fake.insights = {"r-1": divisions}


# ── the Budget pair ───────────────────────────────────────────────────────────
def test_the_budget_pair_sums_every_divisions_hours_across_every_page(client, google, fake):
    google.events = [JOB]
    fake.page_size = 2
    linked_job(fake, [division("01", 100, 90), division("02", 50.5, 60.25),
                      division("03", 20, 10), division("04", 9.5, 9.5), division("05", 0, 3)])
    p = by_key(refresh(client))["job:26.501"]
    r = p["raken"]
    assert r["budget"] == "shown"
    assert r["budgeted_hours"] == 180, "the divisions' own figures, never their cost codes'"
    assert r["projected_total_hours"] == 172.75
    assert r["over_under"] == 7.25
    assert r["projection_below_actual"] is False
    assert p["statuses"] == ["on_plan"]
    pages = [c for c in fake.insight_calls if c[0] == "r-1"]
    assert [q.get("offset") for _u, q in pages] == ["0", "2", "4"], "every page, one at a time"
    assert fake.max_in_flight == 1


def test_raken_s_projected_total_hours_are_added_up_as_raken_gives_them(client, google, fake):
    """GLOSSARY.md: Projected total hours are Raken's own projection, which Treadwell never works
    out itself. A division's figure is added as given, even one below zero."""
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90), division("02", 10, -5)])
    r = by_key(refresh(client))["job:26.501"]["raken"]
    assert r["projected_total_hours"] == 85 and r["over_under"] == 25


def test_insights_are_read_in_raken_s_own_default_mode_unless_the_constant_says_otherwise(
        client, google, fake, monkeypatch):
    """Which mode matches Raken's own Insights screen is to be settled on one real job (#781). Until
    then the tool sends nothing, so Raken uses its documented default."""
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    assert raken_actuals.INSIGHTS_MANUAL_TRACKING is None
    refresh(client)
    assert fake.insight_calls and all("manualTracking" not in q for _u, q in fake.insight_calls)
    assert all("fromDate" not in q and "toDate" not in q for _u, q in fake.insight_calls), \
        "the whole job, as Raken projects it"
    monkeypatch.setattr(raken_actuals, "INSIGHTS_MANUAL_TRACKING", True)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    fake.insight_calls.clear()
    refresh(client)
    assert [q.get("manualTracking") for _u, q in fake.insight_calls] == ["true"]


def test_a_job_projected_over_its_budget_is_over_budget(client, google, fake):
    google.events = [JOB]
    linked_job(fake, [division("01", 1000, 1080), division("02", 200, 250)])
    p = by_key(refresh(client))["job:26.501"]
    assert p["raken"]["budgeted_hours"] == 1200
    assert p["raken"]["projected_total_hours"] == 1330
    assert p["raken"]["over_under"] == -130
    assert p["statuses"] == ["over_budget"]


def test_a_job_projected_exactly_on_its_budget_is_on_plan(client, google, fake):
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 100)])
    p = by_key(refresh(client))["job:26.501"]
    assert p["raken"]["over_under"] == 0
    assert p["statuses"] == ["on_plan"]


def test_a_job_behind_and_over_budget_shows_both(client, google, fake):
    """Booked Monday and Tuesday; nobody clocked in on Tuesday."""
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 130)], cards=[card("r-1", "2026-11-16", "w-1", 8)])
    p = by_key(refresh(client))["job:26.501"]
    assert p["statuses"] == ["behind", "over_budget"]


@pytest.mark.parametrize("divisions", [
    [],
    [division("01", 0, 0)],
    [division("01", None, None), division("02", 0, 12)],
    [division("01", "not a number", 50)],
], ids=["no-divisions", "zero-budget", "null-and-zero-budgets", "unreadable-budget"])
def test_a_job_with_no_raken_budget_shows_no_budget_and_is_never_over_budget(
        client, google, fake, divisions):
    google.events = [JOB]
    linked_job(fake, divisions)
    p = by_key(refresh(client))["job:26.501"]
    r = p["raken"]
    assert r["budget"] == "none"
    assert r["budgeted_hours"] is None and r["projected_total_hours"] is None
    assert r["over_under"] is None and r["projection_below_actual"] is False
    assert p["statuses"] == ["on_plan"]


def test_a_job_with_no_raken_budget_can_still_be_behind(client, google, fake):
    google.events = [JOB]
    linked_job(fake, [], cards=[card("r-1", "2026-11-16", "w-1", 8)])
    assert by_key(refresh(client))["job:26.501"]["statuses"] == ["behind"]


def test_a_projection_below_the_actual_hours_is_noted(client, google, fake):
    """Raken projects only the work in its budget; time cards on other cost codes still count as
    Actual hours (16 here), so the projection can fall below them."""
    google.events = [JOB]
    linked_job(fake, [division("01", 40, 12)])
    r = by_key(refresh(client))["job:26.501"]["raken"]
    assert r["actual_hours"] == 16 and r["projected_total_hours"] == 12
    assert r["projection_below_actual"] is True


FOUR_JOBS = [mob(k, "26.50%d, Example Job %d (2)" % (n, n), "2026-11-16", "2026-11-20")
             for k, n in (("a", 1), ("b", 2), ("c", 3), ("d", 4))]


def four_linked(fake):
    fake.projects = [project("r-%d" % n, "26.50%d" % n, "Example Job %d" % n) for n in range(1, 5)]
    fake.cards = [card("r-%d" % n, d, "w-%d" % n, 8)
                  for n in range(1, 5) for d in ("2026-11-16", "2026-11-17")]
    fake.insights = {"r-%d" % n: [division("01", 100, 90)] for n in range(1, 5)}


# ── which projects are read ───────────────────────────────────────────────────
def test_insights_are_read_once_for_each_linked_raken_project_and_no_other(client, google, fake):
    google.events = [JOB,
                     mob("b", "26.502, Example Depot (2)", "2026-11-16", "2026-11-20"),
                     mob("c", "26.503, Example Annex (2)", "2026-11-16", "2026-11-20")]
    fake.projects = [project("r-1", "26.501", "Example Clinic"),
                     project("r-2", "26.502", "Example Depot"),
                     project("r-3", "26.502", "Example Depot Copy"),
                     project("r-9", "26.799", "Example Unscheduled")]
    fake.cards = ON_TIME + [card("r-9", "2026-11-16", "w-9", 8)]
    fake.insights = {"r-1": [division("01", 10, 9)], "r-9": [division("01", 10, 9)]}
    body = refresh(client)
    assert [u for u, _q in fake.insight_calls] == ["r-1"], \
        "not a duplicate number's projects, not a Raken-only one"
    rows = by_key(body)
    for key in ("job:26.502", "job:26.503"):
        assert rows[key]["statuses"] == ["not_linked"]
        assert "budget" not in rows[key]["raken"]


def test_a_punchs_own_raken_project_adds_its_budget_to_the_job(client, google, fake):
    google.events = [mob("m", "26.125, Acme Clinic Psych (2) (Pat)", "2026-11-02", "2026-11-06"),
                     mob("p", "26.912, Acme Clinic Psych Punch (1) (Lee)", "2026-11-12",
                         "2026-11-12")]
    fake.projects = [project("r-1", "26.125", "Acme Clinic Psych"),
                     project("r-2", "26.912", "Acme Clinic Psych Punch")]
    fake.cards = [card("r-1", d, "w-1", 8) for d in ("2026-11-02", "2026-11-03", "2026-11-04",
                                                       "2026-11-05", "2026-11-06")] \
        + [card("r-2", "2026-11-12", "w-3", 4)]
    fake.insights = {"r-1": [division("01", 100, 80)], "r-2": [division("01", 10, 12)]}
    (p,) = refresh(client)["projects"]
    assert sorted(u for u, _q in fake.insight_calls) == ["r-1", "r-2"]
    assert p["raken"]["budgeted_hours"] == 110 and p["raken"]["projected_total_hours"] == 92
    assert p["raken"]["over_under"] == 18


# ── when an insights read fails ───────────────────────────────────────────────
def test_one_projects_insights_failing_leaves_only_its_budget_pair_empty(
        client, google, fake, caplog):
    caplog.set_level("DEBUG")
    google.events = [JOB, mob("b", "26.502, Example Depot (2)", "2026-11-16", "2026-11-20")]
    fake.projects = [project("r-1", "26.501", "Example Clinic"),
                     project("r-2", "26.502", "Example Depot")]
    fake.cards = ON_TIME + [card("r-2", "2026-11-16", "w-2", 8), card("r-2", "2026-11-17", "w-2", 8)]
    fake.insights = {"r-1": [division("01", 100, 130)], "r-2": [division("01", 50, 40)]}
    fake.insight_fail = {"r-1"}
    body = refresh(client)
    assert body["raken"]["state"] == "connected" and body["raken"]["stale"] is False
    assert body["raken"]["message"] is None
    rows = by_key(body)
    bad, good = rows["job:26.501"], rows["job:26.502"]
    assert bad["raken"]["budget"] == "not_read"
    assert bad["raken"]["budgeted_hours"] is None and bad["raken"]["over_under"] is None
    assert bad["raken"]["actual_hours"] == 16, "the time cards still show"
    assert bad["statuses"] == [],         "a budget that could not be read is never Over budget, and never On plan either"
    assert good["raken"]["budget"] == "shown" and good["raken"]["over_under"] == 10
    # The tool's own log lines. (httpx's own INFO line names every URL it requests; that is
    # httpx's logger, not a line this tool writes.)
    ours = " | ".join(r.getMessage() for r in caplog.records if r.name.startswith("treadwell"))
    assert "production insights" in ours, "the failure is logged, as a count"
    for leak in ("made-up insights failure", "r-1", "r-2", "Example Clinic", "26.501"):
        assert leak not in ours, leak


def test_a_project_id_that_is_not_a_plain_id_is_never_put_in_a_path(client, google, fake):
    """The id goes into the address; one carrying "/", "?" or ".." could point the read elsewhere
    on Raken's API, so it is not read at all."""
    google.events = [JOB]
    fake.projects = [project("r-1/../timeCards?x=", "26.501", "Example Clinic")]
    fake.cards = [card("r-1/../timeCards?x=", "2026-11-16", "w-1", 8)]
    p = by_key(refresh(client))["job:26.501"]
    assert raken.calls_made() == fake.project_calls + len(fake.card_calls), "no other call made"
    assert fake.insight_calls == []
    assert p["raken"]["state"] == "linked" and p["raken"]["budget"] == "not_read"


def test_a_read_kept_before_the_budget_pair_existed_shows_it_as_not_read(client, google, fake):
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    refresh(client)
    store = raken_actuals.load()
    result = dict(store["result"])
    result.pop("insights")
    raken_actuals._save({"result": result, "failure": None})
    p = by_key(get(client))["job:26.501"]
    assert p["raken"]["budget"] == "not_read" and p["raken"]["budgeted_hours"] is None
    assert p["statuses"] == [], "whether it is Over budget is not known, so it is not On plan"


def test_a_job_behind_whose_budget_was_not_read_is_behind_only(client, google, fake):
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 130)], cards=[card("r-1", "2026-11-16", "w-1", 8)])
    fake.insight_fail = {"r-1"}
    assert by_key(refresh(client))["job:26.501"]["statuses"] == ["behind"]


def test_the_insights_calls_count_inside_the_call_cap(client, google, fake, monkeypatch):
    """One /projects page and one /timeCards page leave no room under a cap of 2: the insights
    call is never made. Every time card was read, so they are kept, and the message about too
    many time cards would be wrong; the Budget pair the cap left unread says so on its row."""
    monkeypatch.setattr(raken_actuals, "CALL_CAP", 2)
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    body = refresh(client)
    assert fake.project_calls == 1 and len(fake.card_calls) == 1
    assert fake.insight_calls == []
    assert body["raken"]["state"] == "connected" and body["raken"]["message"] is None
    r = by_key(body)["job:26.501"]["raken"]
    assert r["actual_hours"] == 16 and r["budget"] == "not_read"


def test_the_call_cap_reached_among_the_insights_asks_for_no_more_and_keeps_the_last_pairs(
        client, google, fake, monkeypatch):
    google.events = FOUR_JOBS
    four_linked(fake)
    refresh(client)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    monkeypatch.setattr(raken_actuals, "CALL_CAP", 3)
    fake.insight_calls.clear()
    fake.insights = {"r-%d" % n: [division("01", 100, 120)] for n in range(1, 5)}
    body = refresh(client)
    assert [u for u, _q in fake.insight_calls] == ["r-1"]
    assert body["raken"]["stale"] is False
    rows = by_key(body)
    assert [rows["job:26.50%d" % n]["raken"]["over_under"] for n in range(1, 5)] ==         [-20, 10, 10, 10]


def test_a_cap_with_room_for_the_insights_reads_them(client, google, fake, monkeypatch):
    monkeypatch.setattr(raken_actuals, "CALL_CAP", 3)
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    r = by_key(refresh(client))["job:26.501"]["raken"]
    assert r["budget"] == "shown" and len(fake.insight_calls) == 1


def test_a_rate_limit_on_the_insights_stops_the_refresh_and_keeps_the_last_numbers(
        client, google, fake, monkeypatch):
    """A 429 that persists stops the whole refresh, as on any other Raken call: it never carries
    on through the other projects."""
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    refresh(client)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    real = fake._handle

    def limited(request):
        if request.url.path.endswith("/productionInsights"):
            import httpx
            return httpx.Response(429, json={"message": "Too many requests"})
        return real(request)
    monkeypatch.setattr(fake, "_handle", limited)
    body = refresh(client)
    assert body["raken"]["stale"] is True
    assert body["raken"]["message"] == "Raken is limiting requests right now. Try again later."
    assert by_key(body)["job:26.501"]["raken"]["over_under"] == 10, "the last good read"


def test_a_refresh_while_the_calendar_cannot_be_read_still_reads_the_last_budgets(
        client, google, fake, monkeypatch):
    import project_calendar as pc
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    refresh(client)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    fake.insights = {"r-1": [division("01", 100, 120)]}
    fake.insight_calls.clear()
    pc.cache_clear()
    google.fail = True
    refresh(client)
    assert [u for u, _q in fake.insight_calls] == ["r-1"]
    google.fail = False
    pc.cache_clear()
    p = by_key(get(client))["job:26.501"]
    assert p["raken"]["over_under"] == -20 and p["statuses"] == ["over_budget"]


# ── figures that are not finite numbers ───────────────────────────────────────
@pytest.mark.parametrize("divisions", [
    [division("01", 100, "NaN")],
    [division("01", 100, float("nan"))],
    [division("01", "Infinity", 90)],
    [division("01", 1e999, 90)],
    [division("01", 100, "1e999")],
], ids=["nan-text", "nan-number", "infinity-text", "infinity-number", "overflow-text"])
def test_a_figure_that_is_not_a_finite_number_is_no_figure_and_never_500s(
        client, google, fake, divisions):
    """JSON has no NaN or Infinity: the app renders with allow_nan=False, and the kept file would
    carry the value through every restart until a later refresh replaced it. Such a figure is no
    figure at all."""
    google.events = [JOB]
    linked_job(fake, divisions, cards=[card("r-1", "2026-11-16", "w-1", "NaN"),
                                       card("r-1", "2026-11-17", "w-1", 1e999)])
    body = refresh(client)
    json.dumps(body, allow_nan=False)
    r = by_key(body)["job:26.501"]["raken"]
    assert r["budget"] == "none" and r["over_under"] is None
    assert r["actual_hours"] == 0
    json.dumps(raken_actuals.load(), allow_nan=False)
    raken_actuals.reset_for_tests()
    json.dumps(get(client), allow_nan=False)


# ── a failed insights read never wipes a good figure ──────────────────────────
def test_a_project_whose_insights_fail_keeps_the_last_good_budget_pair(
        client, google, fake, monkeypatch):
    """The numbers on screen never shrink because Raken failed: the time cards are read afresh,
    and the Budget pair stays the last one read."""
    google.events = [JOB]
    linked_job(fake, [division("01", 100, 90)])
    refresh(client)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    fake.cards = ON_TIME + [card("r-1", "2026-11-17", "w-2", 4)]
    fake.insight_fail = {"r-1"}
    body = refresh(client)
    p = by_key(body)["job:26.501"]
    assert body["raken"]["stale"] is False
    assert p["raken"]["actual_hours"] == 20, "the new time cards"
    assert p["raken"]["budget"] == "shown" and p["raken"]["over_under"] == 10
    assert p["statuses"] == ["on_plan"]



def test_insights_failing_twice_in_a_row_stop_the_insights_reads_and_keep_the_time_cards(
        client, google, fake, monkeypatch):
    """An insights endpoint that is down (or a network that drops) fails every project, and a
    Raken that hangs costs a timeout per call: after two failures in a row no more are asked for.
    Every project keeps the last read's Budget pair; the time cards just read are kept."""
    google.events = FOUR_JOBS
    four_linked(fake)
    refresh(client)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    fake.insight_calls.clear()
    fake.insight_fail = {"r-1", "r-2", "r-3", "r-4"}
    fake.cards.append(card("r-4", "2026-11-17", "w-9", 4))
    body = refresh(client)
    assert [u for u, _q in fake.insight_calls] == ["r-1", "r-2"]
    assert body["raken"]["stale"] is False
    rows = by_key(body)
    assert rows["job:26.504"]["raken"]["actual_hours"] == 20, "the new time cards"
    for n in range(1, 5):
        r = rows["job:26.50%d" % n]["raken"]
        assert r["budget"] == "shown" and r["over_under"] == 10, n


def test_one_failure_between_good_reads_does_not_stop_the_others(client, google, fake):
    google.events = FOUR_JOBS
    four_linked(fake)
    fake.insight_fail = {"r-1", "r-3"}
    rows = by_key(refresh(client))
    assert [u for u, _q in fake.insight_calls] == ["r-1", "r-2", "r-3", "r-4"]
    assert [rows["job:26.50%d" % n]["raken"]["budget"] for n in range(1, 5)] == \
        ["not_read", "shown", "not_read", "shown"]


@pytest.mark.parametrize("message,status", [
    (raken.NOT_CONNECTED_MESSAGE, 409), (raken.NOT_SAVED_MESSAGE, 503),
], ids=["disconnected", "sign-in-not-saved"])
def test_the_sign_in_failing_between_insights_calls_stops_the_refresh_and_keeps_the_last_read(
        client, google, fake, monkeypatch, message, status):
    """Every later call would fail the same way: the refresh stops, says why and keeps the last
    good read, as on any other call."""
    google.events = FOUR_JOBS
    four_linked(fake)
    refresh(client)
    monkeypatch.setattr(raken_actuals, "REFRESH_COOLDOWN_S", 0)
    fake.insight_calls.clear()
    real_token = raken.access_token

    def token():
        if fake.insight_calls:
            raise raken.RakenError(message, status)
        return real_token()
    monkeypatch.setattr(raken, "access_token", token)
    body = refresh(client)
    assert [u for u, _q in fake.insight_calls] == ["r-1"]
    assert body["raken"]["stale"] is True and body["raken"]["message"] == message
    assert by_key(body)["job:26.504"]["raken"]["over_under"] == 10
