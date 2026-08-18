"""The bell tells you when the CRM moves.

Hanz, 2026-08-19: "why are the notif bell not working?" → "Every step of the CRM, message, chat
notif".

It WAS working, which is what made the report confusing. The bell already carried customer messages,
deposit submissions, bid deadlines, the Basisboard pipeline and the lead inbox — so it looked alive
while saying nothing about our OWN pipeline. Nothing told you a proposal had been opened, approved,
closed lost, or that a deposit had landed. Those are the steps the board is made of, and they were
the ones missing.

The portal has no webhook pointed at us, so this is the same snapshot-diff shape _refresh_pipeline
already uses for Basisboard: "this changed" means "this differs from what we saw last time".

WHY THE STATUS FIELDS AND NOT `stage()`. crm-core's stage() has an order and several fallbacks, and a
Python re-implementation of it would be a second copy that drifts — the mistake this codebase keeps
warning about. The three status fields ARE the steps, so they are diffed directly. Nothing here needs
to know what a "stage" is.
"""
import notifications as n

TS = "2026-08-19T15:00:00+00:00"


def _row(pid="p1", name="Nearman Creek", proposal="sent", deposit="", contacts=""):
    return {"proposal_id": pid, "project_name": name, "proposal_status": proposal,
            "deposit_status": deposit, "contacts_status": contacts}


def _prev(**kw):
    r = _row(**kw)
    return {r["proposal_id"]: {"proposal_status": r["proposal_status"],
                               "deposit_status": r["deposit_status"],
                               "contacts_status": r["contacts_status"],
                               "name": r["project_name"]}}


def _bodies(items):
    return [i["body"] for i in items]


# ── the steps somebody actually wants to hear about ──────────────────────────
def test_a_proposal_the_customer_opened():
    items = n._diff_crm(_prev(proposal="sent"), [_row(proposal="viewed")], TS)
    assert _bodies(items) == ["Opened the proposal"]
    assert items[0]["kind"] == "crm_step"
    assert items[0]["link"] == "/portal.html?open=p1"
    assert items[0]["title"] == "Nearman Creek"


def test_an_approval_is_marked_high():
    items = n._diff_crm(_prev(proposal="viewed"), [_row(proposal="approved")], TS)
    assert _bodies(items) == ["Approved the proposal"]
    assert items[0]["severity"] == "high", (
        "an approval reads the same as a page view, so nothing draws the eye to it")


def test_a_deposit_landing_is_marked_high():
    items = n._diff_crm(_prev(proposal="approved", deposit="submitted"),
                        [_row(proposal="approved", deposit="received")], TS)
    assert _bodies(items) == ["Deposit received"]
    assert items[0]["severity"] == "high"


def test_the_other_steps_are_reported_too():
    for before, after, want in [
        (dict(proposal="approved"), dict(proposal="closed_lost"), "Closed lost"),
        (dict(proposal="approved", deposit=""), dict(proposal="approved", deposit="requested"),
         "Deposit invoice issued"),
        (dict(proposal="approved", contacts=""), dict(proposal="approved", contacts="received"),
         "Sent their project contacts"),
    ]:
        items = n._diff_crm(_prev(**before), [_row(**after)], TS)
        assert _bodies(items) == [want], (before, after, _bodies(items))


def test_a_deposit_the_customer_submitted_is_NOT_a_step():
    """It already reaches the bell as a 💵 portal message AND a toast — see _PORTAL_MSG_TYPES and
    test_notifications. A step for it as well would show one event twice, which is how a bell stops
    being read at all.

    Mutation: add "submitted" to _CRM_STEPS["deposit_status"]. Only this test fails."""
    items = n._diff_crm(_prev(proposal="approved", deposit="requested"),
                        [_row(proposal="approved", deposit="submitted")], TS)
    assert items == [], "the deposit submission is reported twice: %r" % _bodies(items)


def test_nothing_changing_says_nothing():
    assert n._diff_crm(_prev(proposal="viewed"), [_row(proposal="viewed")], TS) == []


def test_a_status_nobody_needs_a_bell_for_is_silent():
    """`sent` → `sent` after a re-send, and any value not in the step map. A notification per poll
    for a field that merely re-wrote itself would bury the real ones."""
    items = n._diff_crm(_prev(proposal="viewed"), [_row(proposal="something_new")], TS)
    assert items == []


# ── the first send ───────────────────────────────────────────────────────────
def test_a_proposal_id_never_seen_before_is_one_send_not_three():
    """The portal has no row until somebody publishes, so a first send arrives as a whole new id
    with statuses already set. Running it through the per-field loop would fire "Proposal sent",
    "Deposit invoice issued" and more for what the sender experienced as one button.

    Mutation: delete the `if old is None` branch. This test and the next both fail."""
    items = n._diff_crm({}, [_row(proposal="sent", deposit="requested")], TS)
    assert _bodies(items) == ["Proposal sent to the customer"]
    assert items[0]["icon"] == "📤"


def test_the_first_send_still_names_the_project():
    items = n._diff_crm({}, [_row(name="Westport Retail Center")], TS)
    assert items[0]["title"] == "Westport Retail Center"


def test_a_row_with_no_id_is_skipped_not_crashed_on():
    items = n._diff_crm({}, [{"project_name": "No id"}, _row()], TS)
    assert len(items) == 1 and items[0]["title"] == "Nearman Creek"


# ── two changes at once ──────────────────────────────────────────────────────
def test_two_fields_moving_in_one_window_are_two_items():
    items = n._diff_crm(_prev(proposal="viewed"),
                        [_row(proposal="approved", contacts="received")], TS)
    assert sorted(_bodies(items)) == ["Approved the proposal", "Sent their project contacts"]


def test_two_items_in_one_window_do_not_collide_on_their_id():
    """The frontend dedupes by id (auth.js's `toasted` set), so two items sharing one would make the
    second vanish.

    ON `{now_val}` IN THE ID, honestly: mutation testing says removing it changes nothing, and that
    is correct rather than a hole here. Each field is visited once per diff, so field+pid+timestamp
    is already unique — there is no way for one field to produce two items in one window. The value
    is in the id because it makes the id self-describing in a log and in that dedupe set, not
    because uniqueness depends on it. What this test pins is the property that matters: whatever the
    id is built from, no two items in one window share one."""
    items = n._diff_crm(_prev(proposal="viewed"),
                        [_row(proposal="approved", deposit="received", contacts="received")], TS)
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "two steps share an id: %r" % ids


def test_every_step_carries_what_the_bell_renders():
    """auth.js reads all of these. A missing ts sorts the item to the epoch and it never counts as
    unread; a missing link makes the row unclickable."""
    items = n._diff_crm(_prev(proposal="sent"),
                        [_row(proposal="approved", deposit="received", contacts="received")], TS)
    assert items
    for i in items:
        for key in ("id", "kind", "icon", "severity", "sort", "ts", "link", "title", "body"):
            assert i.get(key) not in (None, ""), "%s is missing %r" % (i.get("body"), key)
        assert i["ts"] == TS


# ── where they sit in the feed ───────────────────────────────────────────────
def test_a_step_sits_below_a_customer_message_and_below_every_deadline():
    """Order is a product decision, not an accident. A customer replying outranks us moving a card,
    and an OVERDUE BID outranks both — that one has a date attached."""
    step = n._diff_crm(_prev(), [_row(proposal="viewed")], TS)[0]
    msg = n._portal_message_notifications({"portal_messages": [
        {"id": 1, "proposal_id": "p1", "body": "hi", "created_at": TS}]})[0]
    assert msg["sort"] < step["sort"], "a CRM step outranks a customer message"
    import datetime as _dt
    deadlines = n._deadline_notifications(
        [{"id": "a", "project_name": "Overdue", "deadline": "2026-08-01", "archived": False},
         {"id": "b", "project_name": "Soon", "deadline": "2026-08-22", "archived": False}],
        _dt.date(2026, 8, 19))
    for d in deadlines:
        assert d["sort"] < step["sort"], (
            "a CRM step outranks the %s deadline, which has a date on it" % d["kind"])


def test_the_step_tier_is_the_activity_tier():
    """Same tier as the Basisboard pipeline and the lead inbox: recent activity, newest first. Not
    its own tier, because tiers 0-2 and 4 are the deadline buckets."""
    step = n._diff_crm(_prev(), [_row(proposal="viewed")], TS)[0]
    pipeline = n._diff_pipeline(
        {"x": {"stage_id": "s1", "stage_name": "Bidding", "awarded": False, "name": "X"}},
        [{"id": "x", "stage_id": "s2", "stage_name": "Won", "awarded": False, "name": "X"}], TS)[0]
    assert step["sort"] == pipeline["sort"]


# ── a bid that was never sent has no portal row at all ───────────────────────
def test_a_bid_closed_before_it_was_sent_still_reaches_the_bell(monkeypatch):
    """Closing an unsent bid lost (shipped 2026-08-19) writes to the DRAFT — there is no portal row
    for _diff_crm to see. It comes off our own events log instead."""
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: [
        {"id": 5, "action": "closed_lost", "created_at": TS,
         "detail": {"project_name": "Maple Street", "reason": "another_contractor"}},
        {"id": 6, "action": "reactivated", "created_at": TS,
         "detail": {"project_name": "Maple Street"}},
        {"id": 7, "action": "created", "created_at": TS, "detail": {"project_name": "Noise"}},
    ])
    items = n._draft_event_notifications()
    assert [i["title"] for i in items] == ["Maple Street", "Maple Street"]
    assert "Closed lost before it was sent" in items[0]["body"]
    assert "another contractor" in items[0]["body"], (
        "the reason is not shown, so the item says less than the card does")
    assert "Reopened" in items[1]["body"]
    assert all(i["kind"] == "crm_step" for i in items)


def test_the_draft_log_is_filtered_not_dumped(monkeypatch):
    """`created`, `generated`, `assigned`, `notify_picked` and the rest are an audit trail, not news.
    Surfacing them all would put a bell item on every autosave-adjacent action."""
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: [
        {"id": i, "action": a, "created_at": TS, "detail": {"project_name": a}}
        for i, a in enumerate(["created", "generated", "assigned", "notify_picked",
                               "trashed", "restored", "archived", "to_dropbox"])])
    assert n._draft_event_notifications() == []


def test_an_unreadable_event_log_does_not_break_the_bell(monkeypatch):
    def boom(limit=100):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(n.drafts_mod, "list_events", boom)
    assert n._draft_event_notifications() == []


# ── the refresher: baselines, throttling, and never making things up ─────────
def _portal_env(monkeypatch, payload, calls=None):
    monkeypatch.setenv("PORTAL_ADMIN_URL", "http://portal.test")
    monkeypatch.setenv("SERVICE_TOKEN", "tok")

    class _Resp:
        def __init__(self, d): self._d = d
        def raise_for_status(self): pass
        def json(self): return self._d

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url):
            if calls is not None:
                calls.append(url)
            if isinstance(payload, Exception):
                raise payload
            return _Resp(payload)

    import httpx
    monkeypatch.setattr(httpx, "Client", _Client)


def test_the_first_run_records_a_baseline_and_announces_nothing(monkeypatch):
    """Otherwise deploying this would announce every proposal in the database as newly sent — sixty
    notifications about things that happened weeks ago, which is worse than the silence it replaces.

    Mutation: drop the `if prev:` guard. Only this test fails."""
    _portal_env(monkeypatch, {"proposals": [_row(), _row("p2", "Other")]})
    state = {}
    n._refresh_crm(state)
    assert state.get("crm_events") in (None, []), (
        "the first poll announced %r" % state.get("crm_events"))
    assert set(state["crm_snapshot"]) == {"p1", "p2"}, "no baseline was recorded"
    assert state.get("crm_synced_at")


def test_the_second_run_reports_what_moved(monkeypatch):
    _portal_env(monkeypatch, {"proposals": [_row(proposal="sent")]})
    state = {}
    n._refresh_crm(state)
    _portal_env(monkeypatch, {"proposals": [_row(proposal="approved")]})
    state.pop("crm_synced_at")                     # let it through the throttle
    n._refresh_crm(state)
    assert _bodies(state["crm_events"]) == ["Approved the proposal"]


def test_an_empty_answer_never_replaces_the_baseline(monkeypatch):
    """An empty list is far likelier to be a portal that answered oddly than every proposal having
    been deleted. Wiping the snapshot would make the NEXT poll announce the entire database as newly
    sent — the flood the baseline rule exists to prevent, arriving one poll later.

    Mutation: delete the `if not rows: return`. Only this test fails."""
    _portal_env(monkeypatch, {"proposals": [_row()]})
    state = {}
    n._refresh_crm(state)
    before = dict(state["crm_snapshot"])
    _portal_env(monkeypatch, {"proposals": []})
    state.pop("crm_synced_at")
    n._refresh_crm(state)
    assert state["crm_snapshot"] == before, "an empty answer wiped the baseline"


def test_a_portal_that_errors_keeps_the_snapshot_and_does_not_raise(monkeypatch):
    _portal_env(monkeypatch, {"proposals": [_row()]})
    state = {}
    n._refresh_crm(state)
    before = dict(state["crm_snapshot"])
    _portal_env(monkeypatch, RuntimeError("portal down"))
    state.pop("crm_synced_at")
    n._refresh_crm(state)                          # must not raise
    assert state["crm_snapshot"] == before


def test_an_unconfigured_portal_does_nothing_at_all(monkeypatch):
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    state = {}
    n._refresh_crm(state)
    assert state == {}


def test_it_is_throttled_so_the_25s_poll_does_not_hammer_the_portal(monkeypatch):
    """auth.js polls the bell far more often than the portal wants to be asked. The other three
    refreshers all carry this guard; without it every open tab is a request per poll."""
    calls = []
    _portal_env(monkeypatch, {"proposals": [_row()]}, calls)
    state = {}
    n._refresh_crm(state)
    n._refresh_crm(state)
    n._refresh_crm(state)
    assert len(calls) == 1, "the portal was asked %d times inside the throttle window" % len(calls)
    assert calls[0] == "http://portal.test/api/admin/pipeline"


def test_the_events_are_pruned_so_the_state_file_cannot_grow_forever(monkeypatch):
    """Same cap as the pipeline events, via the same helper — this state lives in a JSON file on the
    volume and is re-read on every poll."""
    _portal_env(monkeypatch, {"proposals": [_row(proposal="sent")]})
    state = {"crm_events": [{"ts": TS, "id": "old:%d" % i} for i in range(150)],
             "crm_snapshot": {"p1": {"proposal_status": "sent", "deposit_status": "",
                                     "contacts_status": "", "name": "Nearman Creek"}}}
    _portal_env(monkeypatch, {"proposals": [_row(proposal="approved")]})
    n._refresh_crm(state)
    assert len(state["crm_events"]) <= 100


# ── the frontend needs no change, and that is a claim worth pinning ──────────
def test_the_bell_renderer_is_generic_so_a_step_needs_no_frontend_change():
    """auth.js's renderList reads icon/title/body/ts/link off every item and knows nothing about
    `kind`. That is why this feature is backend-only — and it stops being true the moment somebody
    special-cases a kind in there."""
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "auth.js") \
        .read_text(encoding="utf-8")
    body = js[js.index("function renderList()"):js.index("async function poll()")]
    for field in ("n.icon", "n.title", "n.body", "n.ts", "n.link", "n.severity"):
        assert field in body, "renderList no longer reads %s" % field
    assert "kind" not in body, (
        "renderList now branches on `kind`, so a CRM step may not render like everything else")


def test_a_crm_step_does_not_fire_a_toast():
    """Toasts are reserved for a CUSTOMER doing something — a message or a deposit. Every stage
    change sliding in from the bottom-right would be a toast storm on a busy afternoon, and the ask
    was the bell.

    Asserted on the filter itself: it keys on `kind === "portal_message"`, and `crm_step` is not it.
    If that ever widens, this is the test that says so and asks for the decision to be re-made."""
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "auth.js") \
        .read_text(encoding="utf-8")
    body = js[js.index("function maybeToast("):]
    body = body[:body.index("async function markSeen()")]
    assert 'x.kind === "portal_message"' in body, "the toast filter has changed shape"
    assert "crm_step" not in body, "CRM steps now toast — was that deliberate?"
