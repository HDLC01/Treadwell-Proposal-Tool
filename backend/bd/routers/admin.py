"""The BD admin's routes. Today: POST /api/bd/admin/weekly/run, "Run Friday batch now" (admin only).

BD's /api/admin/weekly/run, moved under /api/bd/ (#807) with the same checks, answers and words,
because an admin runs the weekly batch by hand from This Week. BD's other admin routes (people,
settings, the phone system, unmatched calls) move with the pages that use them and join this module.
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends

from .. import bizdate, db, errors, serialize, web, weekly
from ..auth import require_role
from .week import list_owner, monday_or_none

router = web.make_router()

ADMIN_ONLY = require_role()                    # admins and super admins


# ── Run Friday batch now ─────────────────────────────────────────────────────────────────────
def _js_truthy(v) -> bool:
    """JavaScript's truthiness, for the body values BD's page tests with `||` and `!`: null, false,
    0, NaN and "" are false; everything else (an empty list or object too) is true."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


@router.post("/api/bd/admin/weekly/run")
def weekly_run(body: Any = Body(None), me: dict = Depends(ADMIN_ONLY)):
    """"Run Friday batch now": the Friday batch of ONE salesperson (`owner`; default as
    GET /api/bd/week: the first active salesperson) for next week, or the Monday given as
    `week_start`, which must be this Monday or next Monday (a later one would roll this week's
    open tasks over to it). The same build as the Friday worker (weekly.build_batch: the
    rollover first, then the split from settings.weekly; never the model). 409 when that week
    already has a Friday batch, unless `force` (then the old one is kept, marked replaced, and
    every open task of the week's Friday batches snoozed). Checks in this order: admin (403) ->
    owner (404, also when nobody active is a salesperson) -> week_start (400) -> 409."""
    b = body if isinstance(body, dict) else {}
    with db.connect() as conn:
        who = list_owner(conn, b.get("owner"), me)
        today = bizdate.today_central()
        this_monday = bizdate.week_start(today)
        next_monday = bizdate.add_days(this_monday, 7)
        raw = b.get("week_start")
        if _js_truthy(raw):
            ws = monday_or_none(raw)
            if ws is None:
                raise errors.bad_request("week_start must be a Monday.", {"week_start": "Pick a Monday."})
            if ws != this_monday and ws != next_monday:
                raise errors.bad_request("week_start must be this Monday or next Monday.",
                                         {"week_start": "Pick this Monday or next Monday."})
        else:
            ws = next_monday
        try:
            res = weekly.build_batch(conn, who, today, week_start=ws, force=_js_truthy(b.get("force")))
        except weekly.BatchExists:
            raise errors.conflict("A Friday batch already exists for %s that week." % who["name"]) from None
        return {"ok": True, "batches": [serialize.task_batch(res["batch"])],
                "tasks_created": res["tasks_created"]}
