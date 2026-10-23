"""A follow-up waiting on somebody here rings the bell.

Remind mode (v1) parks every follow-up as a TASK for the assigned estimator instead of emailing
the customer on its own, so a task nobody notices is a customer nobody chases. Same shape as the
portal-messages source: polled, throttled, cached in the shared state, one team-wide bell.
"""
from datetime import datetime, timedelta, timezone

import notifications as n

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)


def _client(monkeypatch, payload=None, boom=False, seen=None):
    import httpx

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class _Client:
        def __init__(self, *a, **k):
            if seen is not None:
                seen.update(k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            if seen is not None:
                seen["url"] = url
            if boom:
                raise httpx.HTTPError("down")
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setenv("PORTAL_ADMIN_URL", "http://portal")
    monkeypatch.setenv("SERVICE_TOKEN", "tok")


def test_unconfigured_fetches_nothing(monkeypatch):
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    state = {}
    n._refresh_followup_tasks(state)
    assert "followup_tasks" not in state


def test_a_failure_keeps_the_previous_cache(monkeypatch):
    _client(monkeypatch, boom=True)
    state = {"followup_tasks": [{"id": "t1"}]}
    n._refresh_followup_tasks(state)
    assert state["followup_tasks"] == [{"id": "t1"}]


def test_success_caches_the_tasks_from_the_proxys_upstream(monkeypatch):
    seen = {}
    tasks = [{"id": "t1", "proposal_id": "p1", "project_name": "Nearman Creek",
              "label": "Nudge: not opened yet", "due_at": "2026-10-22T12:00:00+00:00"}]
    _client(monkeypatch, {"ok": True, "tasks": tasks}, seen=seen)
    state = {}
    n._refresh_followup_tasks(state)
    assert state["followup_tasks"] == tasks
    assert "followup_tasks_synced_at" in state
    # The endpoint main.py's /api/portal/followup-tasks forwards to, with the service token.
    assert seen["url"] == "http://portal/api/admin/followup-tasks"
    assert seen["headers"] == {"X-Service-Token": "tok"}


def test_the_poll_is_throttled(monkeypatch):
    _client(monkeypatch, {"ok": True, "tasks": [{"id": "new"}]})
    state = {"followup_tasks": [{"id": "old"}], "followup_tasks_synced_at": n._now_iso()}
    n._refresh_followup_tasks(state)
    assert state["followup_tasks"] == [{"id": "old"}]


def test_a_due_task_becomes_one_bell_row_that_opens_the_follow_up_tab(monkeypatch):
    monkeypatch.setattr(n, "_now", lambda: NOW)
    state = {"followup_tasks": [
        {"id": "t1", "proposal_id": "p1", "project_name": "Nearman Creek",
         "label": "Second nudge", "due_at": "2026-10-23T12:00:00Z"},
        # Not due yet: parked for next week.
        {"id": "t2", "proposal_id": "p2", "project_name": "Later Co",
         "due_at": (NOW + timedelta(days=5)).isoformat()},
        {"proposal_id": "p3"},                                  # no id: dropped
    ]}
    items = n._followup_task_notifications(state)
    assert [i["id"] for i in items] == ["fut:t1"]
    row = items[0]
    assert row["link"] == "/portal.html?open=p1&sec=followup"
    assert row["title"] == "Nearman Creek" and "Second nudge" in row["body"]
    assert row["ts"] == "2026-10-23T12:00:00Z"
    assert row["kind"] == "followup_task" and row["sort"] == n._TIER_CRM_STEP


def test_the_bell_carries_the_task_through_get_notifications(monkeypatch):
    monkeypatch.setattr(n, "_load_state", lambda: {"followup_tasks": [
        {"id": "t9", "proposal_id": "p9", "project_name": "Halstead Cannery",
         "label": "Check-in", "due_at": "2026-10-23T09:00:00+00:00"}]})
    monkeypatch.setattr(n, "_save_state", lambda s: None)
    monkeypatch.setattr(n, "_now", lambda: NOW)
    monkeypatch.setattr(n.basisboard_client, "is_configured", lambda: False)
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(n.drafts_mod, "list_drafts", lambda *a, **k: [])
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: [])
    got = n.get_notifications()
    assert [x["id"] for x in got["notifications"]] == ["fut:t9"]
    assert got["unread"] == 1
