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
    assert a["id"] == "pmsg:11" and a["kind"] == "portal_message" and a["sort"] == -1
    assert a["title"] == "Dana · Warehouse"                   # customer_name preferred
    assert a["link"] == "/portal.html?open=p1"
    assert b["title"] == "sam@acme.com · a project"           # falls back to email + generic project
    assert b["body"] == "New message"                         # empty body → placeholder
    # sort:-1 keeps messages ahead of every deadline section (sorts 0..4)
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
