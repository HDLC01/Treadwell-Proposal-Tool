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
    """The real get_notifications() with every external read stubbed: no Basisboard, no portal, no
    drafts DB, no state file. Same stubbing shape as the refresher tests above."""
    monkeypatch.setattr(n, "_load_state", lambda: dict(state or {}))
    monkeypatch.setattr(n, "_save_state", lambda s: None)
    monkeypatch.setattr(n.basisboard_client, "is_configured", lambda: False)
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(n.drafts_mod, "list_drafts", lambda *a, **k: list(projects))
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: list(events))
    monkeypatch.setattr(n, "_biz_today", lambda: today)
    return n.get_notifications()["notifications"]


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


def test_our_pipeline_outranks_basisboard_by_tier_not_by_clock(monkeypatch):
    """The test above would pass on timestamps alone. With the ages REVERSED the order must not move:
    our own pipeline moving matters more than a third party's, and one Basisboard sweep can emit
    dozens of rows — which is what buried the approval in the first place.

    Mutation: give crm_step the Basisboard tier. This fails."""
    items = _feed(monkeypatch, state={"crm_events": _crm_step(ELEVEN_HOURS_AGO),
                                      "pipeline_events": _pipeline_move(A_MINUTE_AGO)})
    assert [x["kind"] for x in items] == ["crm_step", "pipeline_stage"], (
        "a fresher Basisboard row jumped our own pipeline: %r"
        % [(x["kind"], x["ts"]) for x in items])


def test_a_customer_message_still_outranks_our_own_pipeline(monkeypatch):
    """Unchanged by the retiering, and deliberately tested with the message OLDER than the step so the
    tier is what does the work: a customer replying outranks us moving a card."""
    items = _feed(monkeypatch, state={
        "crm_events": _crm_step(A_MINUTE_AGO),
        "portal_messages": [{"id": 7, "proposal_id": "p1", "project_name": "Nearman Creek",
                             "customer_name": "Dana", "body": "Any update?",
                             "created_at": ELEVEN_HOURS_AGO}]})
    assert [x["kind"] for x in items] == ["portal_message", "crm_step"]


def test_every_event_lands_above_every_deadline_and_the_buckets_keep_their_order(monkeypatch):
    """One item of every section at once — the shape of a real bell.

    Mutation: delete the second `items.sort`. This fails: the feed then orders by ts alone, which
    puts the freshest activity above the customer message and re-orders the deadline buckets by due
    DATE (overdue last) instead of by urgency."""
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
    assert kinds[:2] == ["portal_message", "crm_step"], kinds
    assert set(kinds[2:4]) == {"pipeline_stage", "lead_new"}, kinds
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
