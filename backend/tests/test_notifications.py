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
