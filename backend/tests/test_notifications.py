"""Notification-bell logic: deadline bucketing + pipeline diff (pure functions)."""
from datetime import date

import notifications as n


def test_deadline_buckets():
    today = date(2026, 7, 6)
    projects = [
        {"id": "a", "project_name": "Overdue",  "deadline": "2026-07-01", "archived": False},
        {"id": "b", "project_name": "Today",    "deadline": "2026-07-06", "archived": False},
        {"id": "c", "project_name": "Soon",     "deadline": "2026-07-09", "archived": False},
        {"id": "d", "project_name": "Far",      "deadline": "2026-08-30", "archived": False},
        {"id": "e", "project_name": "NoDate",   "deadline": None,          "archived": False},
        {"id": "f", "project_name": "Archived", "deadline": "2026-07-01", "archived": True},
    ]
    items = n._deadline_notifications(projects, today)
    kinds = {i["title"]: i["kind"] for i in items}
    assert kinds["Overdue"] == "deadline_overdue"
    assert kinds["Today"] == "deadline_today"
    assert kinds["Soon"] == "deadline_soon"
    assert kinds["NoDate"] == "deadline_none"
    assert "Far" not in kinds        # >7 days out → not yet noteworthy
    assert "Archived" not in kinds   # inactive/finished → never nags
    # deep-links open the intake editor for that project
    overdue = next(i for i in items if i["title"] == "Overdue")
    assert overdue["link"] == "/?d=a&edit=1"
    assert "Overdue by 5 days" in overdue["body"]


def test_pipeline_diff_detects_award_stage_and_new():
    prev = {
        "p1": {"stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "P1"},
        "p2": {"stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "P2"},
    }
    cur = [
        {"id": "p1", "stage_id": "s1", "stage_name": "Bidding", "awarded": True,  "name": "P1"},
        {"id": "p2", "stage_id": "s2", "stage_name": "Won",     "awarded": False, "name": "P2"},
        {"id": "p3", "stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "P3"},
    ]
    changes = {c["kind"] for c in n._diff_pipeline(prev, cur, "2026-07-06T00:00:00+00:00")}
    assert changes == {"pipeline_awarded", "pipeline_stage", "pipeline_new"}


def test_pipeline_diff_empty_when_unchanged():
    prev = {"p1": {"stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "P1"}}
    cur = [{"id": "p1", "stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "P1"}]
    assert n._diff_pipeline(prev, cur, "2026-07-06T00:00:00+00:00") == []


# ── portal customer messages ─────────────────────────────────────────────────
def test_portal_message_items_map_and_float_to_top():
    state = {"portal_messages": [
        {"id": 11, "proposal_id": "p1", "project_name": "Warehouse", "customer_name": "Dana",
         "author_email": "dana@acme.com", "body": "When can you start?", "created_at": "2026-07-24T15:00:00+00:00"},
        {"id": 12, "proposal_id": "p2", "project_name": None, "customer_name": None,
         "author_email": "sam@acme.com", "body": "", "created_at": "2026-07-24T16:00:00+00:00"},
        {"id": None, "proposal_id": "p3", "body": "skip me", "created_at": None},   # no id → skipped
    ]}
    items = n._portal_message_notifications(state)
    assert len(items) == 2                                    # the id-less row is dropped
    a, b = items
    assert a["id"] == "pmsg:11" and a["kind"] == "portal_message"
    assert a["title"] == "Dana · Warehouse"                   # customer_name preferred
    assert a["link"] == "/portal.html?open=p1"
    assert b["title"] == "sam@acme.com · a project"           # falls back to email + generic project
    assert b["body"] == "New message"                         # empty body → placeholder
    # the message tier keeps them ahead of every deadline section
    deadlines = n._deadline_notifications(
        [{"id": "x", "project_name": "Overdue", "deadline": "2026-07-01", "archived": False}],
        date(2026, 7, 6))
    assert a["sort"] < min(d["sort"] for d in deadlines)


def test_refresh_portal_messages_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    state = {}
    n._refresh_portal_messages(state)
    assert "portal_messages" not in state                     # nothing fetched, nothing raised


def test_refresh_portal_messages_survives_http_error(monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_URL", "http://portal")
    monkeypatch.setenv("SERVICE_TOKEN", "tok")
    import httpx

    class _BoomClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): raise httpx.HTTPError("down")

    monkeypatch.setattr(httpx, "Client", _BoomClient)
    state = {"portal_messages": [{"id": 1}]}                   # a prior cache
    n._refresh_portal_messages(state)
    assert state["portal_messages"] == [{"id": 1}]            # kept the old cache, no raise


def test_refresh_portal_messages_caches_on_success(monkeypatch):
    monkeypatch.setenv("PORTAL_ADMIN_URL", "http://portal")
    monkeypatch.setenv("SERVICE_TOKEN", "tok")
    import httpx

    payload = {"ok": True, "messages": [{"id": 9, "proposal_id": "p9", "body": "hi",
                                         "created_at": "2026-07-24T12:00:00+00:00"}]}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return payload

    class _OkClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(httpx, "Client", _OkClient)
    state = {}
    n._refresh_portal_messages(state)
    assert state["portal_messages"] == payload["messages"]
    assert "portal_msgs_synced_at" in state                   # cursor stamped for TTL throttle


# ── feed order: things that HAPPENED outrank things merely DUE ────────────────
# Hanz, 2026-08-19: "why is this on the bottom, new notifs should be at the top". He was scrolling
# past a wall of 11-hour-old Basisboard rows to reach a proposal sent at 13:17 and opened at 13:29.
# The cause was the SECTION order: on production the deadline buckets hold 14 overdue + 3 due today
# + 6 due soon, so 23 dated rows sat above anything that had just happened.
#
# These assert through the real get_notifications() rather than on the _TIER_* constants, because the
# ORDER is the claim and the numbers are only the mechanism — a test that reads the constants passes
# happily with the second `items.sort` deleted.
TODAY = date(2026, 8, 19)
A_MINUTE_AGO = "2026-08-19T13:29:00+00:00"
ELEVEN_HOURS_AGO = "2026-08-19T02:30:00+00:00"


def _feed(monkeypatch, state=None, projects=(), events=(), today=TODAY):
    """The notifications the browser would render."""
    return _feed_all(monkeypatch, state, projects, events, today)["notifications"]


def _feed_all(monkeypatch, state=None, projects=(), events=(), today=TODAY):
    """The real get_notifications() with every external read stubbed: no Basisboard, no portal, no
    drafts DB, no state file. Same stubbing shape as the refresher tests above. Returns the WHOLE
    payload, because `unread` is a claim about the same trim the cap tests below exercise."""
    monkeypatch.setattr(n, "_load_state", lambda: dict(state or {}))
    monkeypatch.setattr(n, "_save_state", lambda s: None)
    monkeypatch.setattr(n.basisboard_client, "is_configured", lambda: False)
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(n.drafts_mod, "list_drafts", lambda *a, **k: list(projects))
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: list(events))
    monkeypatch.setattr(n, "_biz_today", lambda: today)
    return n.get_notifications()


def _crm_step(ts, pid="p1", name="Nearman Creek"):
    """One real "the customer approved it", built by the emitter rather than hand-written so the tier
    under test is the one production ships."""
    prev = {pid: {"proposal_status": "sent", "deposit_status": "", "contacts_status": "",
                  "name": name}}
    rows = [{"proposal_id": pid, "project_name": name, "proposal_status": "approved",
             "deposit_status": "", "contacts_status": ""}]
    return n._diff_crm(prev, rows, ts)


def _pipeline_move(ts, pid="bb1"):
    prev = {pid: {"stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "Third party"}}
    cur = [{"id": pid, "stage_id": "s2", "stage_name": "Won", "awarded": False,
            "name": "Third party"}]
    return n._diff_pipeline(prev, cur, ts)


def test_a_step_from_a_minute_ago_beats_a_deadline_that_went_overdue_last_week(monkeypatch):
    """The reported bug, end to end.

    Mutation: put the deadline tiers back above the event tiers. This fails."""
    step = _crm_step(A_MINUTE_AGO)[0]
    items = _feed(monkeypatch, state={"crm_events": [step]},
                  projects=[{"id": "a", "project_name": "Stale bid", "deadline": "2026-08-09",
                             "archived": False}])
    assert [x["kind"] for x in items] == ["crm_step", "deadline_overdue"], (
        "order was %r" % [(x["kind"], x["ts"]) for x in items])
    # And this is why newest-first alone never fixed it: a deadline's ts is its DUE DATE, not when
    # anything happened, so it never reads as recent and never moves.
    assert items[1]["ts"].startswith("2026-08-09")


def test_a_step_beats_an_eleven_hour_old_basisboard_row(monkeypatch):
    """The wall he was scrolling past was Basisboard's."""
    items = _feed(monkeypatch, state={"crm_events": _crm_step(A_MINUTE_AGO),
                                      "pipeline_events": _pipeline_move(ELEVEN_HOURS_AGO)})
    assert [x["kind"] for x in items] == ["crm_step", "pipeline_stage"]


def test_among_things_that_happened_the_clock_decides(monkeypatch):
    """THIS ASSERTION WAS REVERSED ON 2026-08-21, deliberately.

    It used to require that our own pipeline outrank a Basisboard row even when the Basisboard row
    was newer, on the reasoning that a third party's sweep can emit dozens of rows. That reasoning
    ranked KINDS of event against each other, and the side effect was that it ranked them against
    TIME as well: with a stable sort the tier won outright, so an old row of a favoured kind sat
    above everything newer, permanently.

    Hanz, 2026-08-21, looking at a bell whose top row was eight days old: "notification is still
    showing the older ones and not in chronological order". Among things that HAPPENED, the clock is
    now the only thing that orders them. Events still sit above deadlines, which is the part of the
    old design that was right and is asserted below.

    Mutation: restore the tier sort within events. This fails."""
    items = _feed(monkeypatch, state={"crm_events": _crm_step(ELEVEN_HOURS_AGO),
                                      "pipeline_events": _pipeline_move(A_MINUTE_AGO)})
    assert [x["kind"] for x in items] == ["pipeline_stage", "crm_step"], (
        "an eleven-hour-old row outranked something from a minute ago: %r"
        % [(x["kind"], x["ts"]) for x in items])


def test_an_old_customer_message_does_not_outrank_todays_work(monkeypatch):
    """ALSO REVERSED ON 2026-08-21, and this is the one that actually bit Hanz.

    A customer message used to carry the top tier outright, so nine-day-old "Hello" messages sat
    above everything that happened today and filled the event slots, pushing genuinely new rows off
    the end. A customer replying DOES matter more than us moving a card - but not a week later, and
    the old rule could not tell the difference because it never looked at the clock.

    The message is deliberately OLDER than the step here, which is exactly the case that used to be
    ordered backwards."""
    items = _feed(monkeypatch, state={
        "crm_events": _crm_step(A_MINUTE_AGO),
        "portal_messages": [{"id": 7, "proposal_id": "p1", "project_name": "Nearman Creek",
                             "customer_name": "Dana", "body": "Any update?",
                             "created_at": ELEVEN_HOURS_AGO}]})
    assert [x["kind"] for x in items] == ["crm_step", "portal_message"], (
        "an eleven-hour-old customer message outranked a step from a minute ago")


def test_every_event_lands_above_every_deadline_and_the_buckets_keep_their_order(monkeypatch):
    """One item of every section at once — the shape of a real bell.

    THE TWO RULES THIS PINS, after the 2026-08-21 change:
      * every event sits above every deadline - a deadline reads the same tomorrow, an event is news
        exactly once. This half of the old tier design was right and is unchanged.
      * the DEADLINE buckets keep their urgency order (overdue, today, soon, no date), because
        nothing about a deadline is time-sensitive in the newest-first sense - ordering them by due
        date would put the overdue ones LAST.
    What it deliberately no longer pins is the order of events among themselves: that is the clock
    now, asserted in the two tests above.

    Mutation: delete the second `items.sort`. This fails, because the deadline buckets then order by
    due date instead of urgency and the events lose their block above them."""
    items = _feed(
        monkeypatch,
        state={"crm_events": _crm_step(ELEVEN_HOURS_AGO),
               "pipeline_events": _pipeline_move(A_MINUTE_AGO),
               "lead_events": [{"id": "lead:new:1", "kind": "lead_new", "icon": "📥",
                                "severity": "info", "sort": 2, "ts": A_MINUTE_AGO,
                                "title": "A lead", "body": "New lead", "link": "/leads.html"}],
               "portal_messages": [{"id": 7, "proposal_id": "p1", "body": "hi",
                                    "created_at": ELEVEN_HOURS_AGO}]},
        projects=[
            {"id": "o", "project_name": "Overdue", "deadline": "2026-08-01", "archived": False},
            {"id": "t", "project_name": "Today", "deadline": "2026-08-19", "archived": False},
            {"id": "s", "project_name": "Soon", "deadline": "2026-08-22", "archived": False},
            {"id": "n", "project_name": "NoDate", "deadline": None, "archived": False,
             "updated_at": A_MINUTE_AGO},
        ])
    kinds = [x["kind"] for x in items]
    deadlines = [i for i, k in enumerate(kinds) if k.startswith("deadline_")]
    events = [i for i, k in enumerate(kinds) if not k.startswith("deadline_")]
    assert len(deadlines) == 4 and len(events) == 4, kinds
    assert max(events) < min(deadlines), "a deadline outranks an event: %r" % kinds
    # The two freshest events lead, whatever KIND they are (both a minute old here), and the two
    # eleven-hour-old ones follow. Kinds are compared as sets within each age group because two rows
    # sharing a timestamp have no defined order between them and pinning one would be a coin toss.
    assert set(kinds[:2]) == {"pipeline_stage", "lead_new"}, kinds
    assert set(kinds[2:4]) == {"portal_message", "crm_step"}, kinds
    assert kinds[4:] == ["deadline_overdue", "deadline_today", "deadline_soon",
                         "deadline_none"], kinds


def test_a_source_that_forgets_its_tier_lands_last_not_first(monkeypatch):
    """The default in the second `items.sort`. Every source sets `sort` today; the day a new one
    forgets, the untiered item must not hijack the top of the feed the whole team reads first. Its ts
    here is in 2099, so nothing but the default tier can hold it down.

    Mutation: make the default 0 (or -1). This fails."""
    monkeypatch.setattr(n, "_dropbox_notifications", lambda: [
        {"id": "oops", "kind": "mystery", "icon": "•", "severity": "info", "title": "No tier",
         "body": "", "link": "/", "ts": "2099-01-01T00:00:00+00:00"}])
    items = _feed(monkeypatch, state={"crm_events": _crm_step(A_MINUTE_AGO)},
                  projects=[{"id": "n", "project_name": "NoDate", "deadline": None,
                             "archived": False, "updated_at": A_MINUTE_AGO}])
    assert [x["kind"] for x in items][-1] == "mystery", (
        "an untiered item sorted into %r" % [x["kind"] for x in items])


def test_every_emitter_agrees_on_its_category_tier(monkeypatch):
    """The bug the named tiers exist to prevent: a category emits its tier from SEVERAL places —
    three in the Basisboard diff, three for crm_step — and one missed site drops half a category into
    another section. The feed tests above only ever see one item per kind, so this walks all fourteen
    emit sites instead and checks that each kind speaks with one voice.

    Mutation: retier any single emit site. This fails."""
    captured = {}
    monkeypatch.setattr(n, "_load_state", lambda: {})
    monkeypatch.setattr(n, "_save_state", lambda s: captured.update(s))
    n.add_lead_estimate("d1", "A lead")
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: [
        {"id": 1, "action": "to_dropbox", "created_at": A_MINUTE_AGO,
         "detail": {"project_name": "Filed", "folder_url": "https://dropbox.test/x"}},
        {"id": 2, "action": "closed_lost", "created_at": A_MINUTE_AGO,
         "detail": {"project_name": "Unsent", "reason": "another_contractor"}}])
    emitted = (
        n._diff_pipeline(                                     # pipeline_awarded / _stage / _new
            {"p1": {"stage_id": "s1", "stage_name": "Bid", "awarded": False, "name": "P1"},
             "p2": {"stage_id": "s1", "stage_name": "Bid", "awarded": False, "name": "P2"}},
            [{"id": "p1", "stage_id": "s1", "stage_name": "Bid", "awarded": True, "name": "P1"},
             {"id": "p2", "stage_id": "s2", "stage_name": "Won", "awarded": False, "name": "P2"},
             {"id": "p3", "stage_id": "s1", "stage_name": "Bid", "awarded": False, "name": "P3"}],
            A_MINUTE_AGO)
        + n._lead_events([{"id": 1, "project": {"name": "L"}}], A_MINUTE_AGO)   # lead_new
        + captured["lead_events"]                                              # lead_estimate
        + n._diff_crm({}, [{"proposal_id": "p9", "project_name": "First send",
                            "proposal_status": "sent"}], A_MINUTE_AGO)         # crm_step (sent)
        + _crm_step(A_MINUTE_AGO)                                              # crm_step (per-field)
        + n._dropbox_notifications()                                           # to_dropbox
        + n._draft_event_notifications()                                       # crm_step (unsent)
        + n._portal_message_notifications({"portal_messages": [
            {"id": 1, "body": "hi", "created_at": A_MINUTE_AGO}]})             # portal_message
        + n._deadline_notifications([                                          # all four buckets
            {"id": "o", "project_name": "Overdue", "deadline": "2026-08-01", "archived": False},
            {"id": "t", "project_name": "Today", "deadline": "2026-08-19", "archived": False},
            {"id": "s", "project_name": "Soon", "deadline": "2026-08-22", "archived": False},
            {"id": "n", "project_name": "NoDate", "deadline": None, "archived": False},
        ], TODAY)
    )
    assert len(emitted) == 14, "an emit site is no longer covered here: %d items" % len(emitted)
    tiers = {}
    for item in emitted:
        tiers.setdefault(item["kind"], set()).add(item["sort"])
    split = {k: v for k, v in tiers.items() if len(v) > 1}
    assert not split, "these kinds emit more than one tier: %r" % split
    tier = {k: v.pop() for k, v in tiers.items()}
    assert tier["portal_message"] < tier["crm_step"] < tier["pipeline_new"], tier
    assert (tier["pipeline_new"] == tier["pipeline_awarded"] == tier["pipeline_stage"]
            == tier["lead_new"] == tier["lead_estimate"] == tier["to_dropbox"]), tier
    deadline = {k: v for k, v in tier.items() if k.startswith("deadline_")}
    event = {k: v for k, v in tier.items() if not k.startswith("deadline_")}
    assert max(event.values()) < min(deadline.values()), (
        "an event shares or loses to a deadline tier: %r" % tier)
    assert (deadline["deadline_overdue"] < deadline["deadline_today"]
            < deadline["deadline_soon"] < deadline["deadline_none"]), deadline


def test_a_stored_event_is_retiered_on_read_not_trusted_from_the_file(monkeypatch):
    """notif_state.json is a 30-day archive written by whatever code was deployed when each event
    happened, so its items carry the tier that was current THEN. Trusting the stored number would
    park a month of Basisboard/lead/CRM events at the old shared activity value — which is now the
    OVERDUE tier — back in the middle of the deadline block.

    Mutation: extend from `state.get("crm_events")` directly instead of through _retier. This
    fails."""
    stale = dict(_crm_step(A_MINUTE_AGO)[0], sort=3)     # 3 was the shared activity tier until now
    items = _feed(monkeypatch, state={"crm_events": [stale],
                                      "pipeline_events": _pipeline_move(ELEVEN_HOURS_AGO)})
    assert [x["kind"] for x in items] == ["crm_step", "pipeline_stage"], (
        "the tier written in the file won: %r" % [(x["kind"], x["sort"]) for x in items])
    assert stale["sort"] == 3, "_retier wrote the recomputed tier back into the state file"


# ── the cap: putting events on top must not delete the deadlines ──────────────
# Checked against production minutes after the retiering above shipped: the bell returned 60 rows and
# NOT ONE had a kind starting with `deadline_`, while the box held 14 overdue + 3 due today + 6 due
# soon bids. `items[:_MAX_ITEMS]` trims AFTER the sort, so whichever group sorts first takes every
# slot. Hanz asked for new things at the top; nobody asked for overdue bids to disappear, and an
# overdue bid is money.
#
# Asserted through the real get_notifications() for the same reason as the order tests: what the
# browser receives is the claim, and a test that reads _GROUP_RESERVE passes happily with
# _cap_by_group never called at all.
def _ts(i: int) -> str:
    """Distinct ordered timestamps on the day under test — a higher `i` is newer — so "newest first
    inside a tier" has something to be right or wrong about."""
    return "2026-08-19T%02d:%02d:00+00:00" % (10 + i // 60, i % 60)


def _event_state(messages=0, steps=0, pipeline=0):
    """A wall of event items across all three event tiers, built by the production emitters so each
    row carries the tier it really ships with rather than one a test asserted into existence."""
    i = 0
    msgs, crm, pl = [], [], []
    for k in range(messages):
        msgs.append({"id": 1000 + k, "proposal_id": "pm%d" % k, "project_name": "Msg %d" % k,
                     "customer_name": "Dana", "body": "Question %d" % k, "created_at": _ts(i)})
        i += 1
    for k in range(steps):
        crm += _crm_step(_ts(i), pid="cs%d" % k, name="Step %d" % k)
        i += 1
    for k in range(pipeline):
        pl += _pipeline_move(_ts(i), pid="bb%d" % k)
        i += 1
    return {"portal_messages": msgs, "crm_events": crm, "pipeline_events": pl}


def _deadline_projects(overdue=0, today=0, soon=0, none=0):
    """Active drafts in each deadline bucket. The no-deadline rows carry a week-old `updated_at` —
    that field is their `ts`, and a project nobody has touched in a week is the realistic case."""
    out = []
    for k in range(overdue):
        out.append({"id": "od%d" % k, "project_name": "Overdue %d" % k,
                    "deadline": "2026-08-%02d" % (1 + k % 14), "archived": False})
    for k in range(today):
        out.append({"id": "td%d" % k, "project_name": "Today %d" % k,
                    "deadline": "2026-08-19", "archived": False})
    for k in range(soon):
        out.append({"id": "sn%d" % k, "project_name": "Soon %d" % k,
                    "deadline": "2026-08-%02d" % (20 + k % 6), "archived": False})
    for k in range(none):
        out.append({"id": "nd%d" % k, "project_name": "NoDate %d" % k, "deadline": None,
                    "archived": False, "updated_at": "2026-08-12T08:00:00+00:00"})
    return out


# The deadline load measured on production on 2026-08-19 — the 23 urgent rows the global slice threw
# away, plus two projects nobody has given a date yet.
PROD_DEADLINES = dict(overdue=14, today=3, soon=6, none=2)


def test_a_wall_of_events_no_longer_wipes_every_deadline_off_the_bell(monkeypatch):
    """The reported bug: 100 events against production's own deadline load.

    Mutation: drop the per-group cap back to one global `items[:_MAX_ITEMS]`, or give the deadline
    group 0 slots. Both fail here."""
    items = _feed(monkeypatch, state=_event_state(messages=5, steps=15, pipeline=80),
                  projects=_deadline_projects(**PROD_DEADLINES))
    kinds = [x["kind"] for x in items]
    deadlines = [k for k in kinds if k.startswith("deadline_")]
    events = [k for k in kinds if not k.startswith("deadline_")]
    assert deadlines, "100 events emptied the deadline half of the bell again: %r" % kinds
    assert events, "the deadlines took the whole panel: %r" % kinds
    assert len(items) == n._MAX_ITEMS, "the panel renders every row it is sent: %d" % len(items)
    assert len(events) == n._EVENT_SLOTS, kinds
    assert len(deadlines) == n._DEADLINE_SLOTS, kinds
    # Every dated row somebody can still act on survives — that is what the 24 slots are sized for.
    assert kinds.count("deadline_overdue") == 14, kinds
    assert kinds.count("deadline_today") == 3, kinds
    assert kinds.count("deadline_soon") == 6, kinds


def test_a_wall_of_deadlines_does_not_squeeze_the_events_out_either(monkeypatch):
    """The reverse bug, which the fix must not introduce: production already has 23 deadline rows and
    a slow week would add more.

    Mutation: give the event group 0 slots. This fails."""
    items = _feed(monkeypatch, state=_event_state(messages=1, steps=1, pipeline=1),
                  projects=_deadline_projects(overdue=40, today=10, soon=20, none=30))
    kinds = [x["kind"] for x in items]
    # The point is that a wall of deadlines cannot bury the things that HAPPENED. Their order among
    # themselves is the clock now (2026-08-21), so this compares the set: pinning one order would be
    # asserting the timestamps in the fixture rather than the reserve that keeps them on screen.
    assert set(kinds[:3]) == {"portal_message", "crm_step", "pipeline_stage"}, (
        "100 deadlines buried the three things that happened: %r" % kinds[:6])
    assert len(items) == n._MAX_ITEMS
    # And the deadlines took the 33 slots the three events left unclaimed, rather than sitting at
    # their 24-row reserve while the panel showed 27 rows.
    assert len([k for k in kinds if k.startswith("deadline_")]) == n._MAX_ITEMS - 3, kinds


def test_a_quiet_side_lends_its_unused_slots_to_the_busy_one(monkeypatch):
    """Two deadlines and a loud day: the panel fills with 58 events instead of stopping at 38 because
    22 deadline slots went unclaimed.

    Mutation: hand out only the reserves and never the spare. This fails."""
    items = _feed(monkeypatch, state=_event_state(pipeline=100),
                  projects=_deadline_projects(overdue=2))
    kinds = [x["kind"] for x in items]
    assert len(items) == n._MAX_ITEMS
    assert kinds.count("deadline_overdue") == 2, kinds
    assert kinds.count("pipeline_stage") == n._MAX_ITEMS - 2, (
        "the quiet half's slots were left empty: %d events" % kinds.count("pipeline_stage"))


def test_the_cap_chooses_rows_and_never_reorders_them(monkeypatch):
    """Ordering is unchanged by the trim: tier first, newest-first inside a tier.

    Mutation: sort the kept rows instead of re-emitting them in feed order. This fails — a deadline's
    `ts` is its DUE DATE, so any re-sort by `ts` interleaves the buckets and puts due-today above
    overdue."""
    items = _feed(monkeypatch, state=_event_state(messages=5, steps=15, pipeline=80),
                  projects=_deadline_projects(**PROD_DEADLINES))
    kinds = [x["kind"] for x in items]
    # The invariant the cap must not break is the DISPLAY order, and since 2026-08-21 that order is
    # "every event, newest first, then the deadlines by urgency" - not ascending tiers. Checking
    # `tiers == sorted(tiers)` would now fail for a correct feed, because a tier-2 activity row from
    # a minute ago legitimately sits above a tier-0 message from last week.
    is_deadline = [k.startswith("deadline_") for k in kinds]
    assert is_deadline == sorted(is_deadline), (
        "the trim interleaved events and deadlines: %r" % kinds)
    ev_ts = [x.get("ts") or "" for x, d in zip(items, is_deadline) if not d]
    assert ev_ts == sorted(ev_ts, reverse=True), (
        "the trim reordered the events out of newest-first: %r" % ev_ts[:6])
    dl_tiers = [x["sort"] for x, d in zip(items, is_deadline) if d]
    assert dl_tiers == sorted(dl_tiers), (
        "the trim reordered the deadline buckets out of urgency order: %r" % dl_tiers[:6])
    # And the very top row is simply the newest thing that happened, whatever kind it is.
    assert items[0]["ts"] == max(ev_ts), (
        "the newest event no longer leads: %r" % [(items[0].get("id"), items[0].get("ts"))])
    for a, b in zip(items, items[1:]):
        if a["sort"] == b["sort"]:
            assert (a["ts"] or "") >= (b["ts"] or ""), (
                "newest-first broke inside the %s tier" % a["kind"])
    deadlines = [i for i, k in enumerate(kinds) if k.startswith("deadline_")]
    events = [i for i, k in enumerate(kinds) if not k.startswith("deadline_")]
    assert max(events) < min(deadlines), "a deadline outranks an event after the trim: %r" % kinds


def test_the_badge_counts_only_rows_the_panel_will_actually_show(monkeypatch):
    """`unread` is counted AFTER the trim — the badge is a promise about what you will find when you
    open the panel, and the panel has no pager (auth.js renderList renders exactly these rows, and
    opening the bell marks everything seen). A 100 that resolves to 36 findable rows sends people
    hunting for news that was already cleared on their behalf.

    Mutation: count `unread` before the trim. This fails."""
    last_seen = "2026-08-19T09:00:00+00:00"
    state = _event_state(messages=5, steps=15, pipeline=80)
    state["last_seen_at"] = last_seen
    res = _feed_all(monkeypatch, state, _deadline_projects(**PROD_DEADLINES))
    shown = res["notifications"]
    assert res["unread"] == sum(1 for x in shown if (x.get("ts") or "") > last_seen), (
        "the badge disagrees with the rows it was counted from")
    assert res["unread"] <= len(shown)
    # 100 events arrived after the marker and 36 of them are on screen; no deadline row is newer than
    # it (a due date is not a thing that happened).
    assert res["unread"] == n._EVENT_SLOTS, res["unread"]


def test_an_item_that_forgot_its_tier_reserves_no_slot_of_its_own(monkeypatch):
    """A source shipping without a `sort` is a bug, and a bug must not evict an overdue bid to make
    room for itself — so the untiered group reserves nothing and only ever gets spare slots. On a
    quiet feed it still shows, last: see test_a_source_that_forgets_its_tier_lands_last_not_first.

    Mutation: give the untiered group a reserve of its own (`_GROUP_RESERVE.get(g, 1)`). This fails
    twice — the mystery row appears AND the total goes to 61.

    Honestly, on what this does NOT catch: filing untiered items into one of the real groups survives
    here, because the untiered row sorts last and a full group's slice takes its head either way. The
    property worth pinning is the one above — a bug cannot cost a real notification its slot."""
    monkeypatch.setattr(n, "_dropbox_notifications", lambda: [
        {"id": "oops", "kind": "mystery", "icon": "•", "severity": "info", "title": "No tier",
         "body": "", "link": "/", "ts": "2099-01-01T00:00:00+00:00"}])
    items = _feed(monkeypatch, state=_event_state(messages=5, steps=15, pipeline=80),
                  projects=_deadline_projects(**PROD_DEADLINES))
    kinds = [x["kind"] for x in items]
    assert "mystery" not in kinds, "an untiered item took a slot a real notification needed"
    assert len(items) == n._MAX_ITEMS
    assert kinds.count("deadline_overdue") == 14, kinds
