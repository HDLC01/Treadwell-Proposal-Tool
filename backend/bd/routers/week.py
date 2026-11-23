"""This Week: GET /api/bd/week, POST /api/bd/week/ten-more, POST /api/bd/tasks/{id}/done|snooze|
reopen|not-right-person. (The admin's "Run Friday batch now", POST /api/bd/admin/weekly/run, is in
admin.py; whose week a request means, week_owner / list_owner / monday_or_none, is bd/weekly.py's.)

BD's /api/week and /api/tasks routes, moved under /api/bd/ (#807) with the same checks, answers and
words. docs/bd/api-contract.md "This Week" is the spec. BD's retired mock was the reference where the
contract is silent ("api.js X" names a function of frontend/js/api.js in the BD repository), and the
checks run in its order:

    GET /api/bd/week       owner (404) -> role (403) -> week_start (400)
    ten-more               salesperson or admin (403) -> owner (404; also when the owner it falls
                           back to is not a salesperson) -> a non-admin on someone else's list
                           (403) -> nobody left (409)
    done/snooze            task (404) -> salesperson or admin (403) -> own list (403)
                           -> body (400) -> a maintenance row (409) -> state (409)
    reopen                 task (404) -> salesperson or admin (403) -> own list (403)
                           -> body (400) -> state (409)
    not-right-person       salesperson, assistant or admin (403) -> task (404) -> body (400);
                           any list (the contract names no task owner here; review finding C5)

ONE ROW PER COMPANY (#828). The week's tasks are shown as company rows (WeekView `rows`): the tasks of
one owner's week at one company (the contact's company now) in one place, which is the "Due now"
group for `maintenance` tasks (any batch) and the batch for the others. A row built after #828 holds
one task (a due maintenance company: one per due person); a week built before it can hold two people
at one company, and is shown as one row all the same. The task buttons act on the WHOLE row of the
task named in the path: done, "Not this week" and Reopen change every task of the row, and the row's
status is company_facts.row_status of its tasks. "Not the right person" marks one person (body
`contact_id`, default the task's) and keeps the row open while someone else on it can be called.

`done_count` / `total` are the LIVE Friday batch's BUSINESS-DEVELOPMENT ROWS only (the "did I do
my 10?" headline: the latest Friday batch of the week, without its `maintenance` tasks; one a
forced re-run replaced is still listed but no longer counted); a "Give Me 10 More" batch never
moves them. `due_count` is the number of OPEN "Due now" rows, one per company ("Due now: N"). A
maintenance row with a person still due cannot be snoozed or marked done by hand (409): it leaves
the list when a call, meeting, email or text is logged and nobody on it is due any more; a stale one
can be taken off like any row. Every date is Central (bd_today(), bd_now()).

GET /api/bd/week never builds anything: a week with no batch is the empty state ("No list yet").
Batches are made only by the Friday worker (bd/weekly_worker.py), the admin's run and "Give Me 10
More" (bd/weekly.py does all three; it never calls the model). The week is a function of the server's
data alone: the page shows what this route answers and keeps no list of its own.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import Body, Depends, Path, Query

from .. import appsettings, bizdate, company_facts, db, errors, paging, serialize, web, weekly
from .. import pace as pacemod
from ..auth import current_user, has_role, is_admin, require_role
from ..events import log_event

router = web.make_router()

MAX_REASON = 500
MAX_NOTE = 2000


# ── helpers ──────────────────────────────────────────────────────────────────────────────────
def _parse_week_start(value) -> _dt.date:
    if value is None or value == "":
        return bizdate.week_start()
    d = weekly.monday_or_none(value)
    if d is None:
        raise errors.bad_request("week_start must be a Monday.", {"week_start": "Pick a Monday."})
    return d


MAINTENANCE_STAYS = "A maintenance follow-up stays on the list until you log a call, meeting, email or text."


def _refuse_if_pinned(conn, row) -> None:
    """409 for a maintenance row with a person STILL due: it cannot be taken off by hand. A row whose
    maintenance people are no longer due (a stale one: reopened after its follow-up, or the contact
    became a BD contact) is not pinned and can be skipped or marked done like any other, so nothing is
    ever stuck on the list."""
    ids = [t["contact_id"] for t in row if t["kind"] == "maintenance"]
    if ids and conn.execute("select 1 from contacts_summary where id = any(%s) and maintenance_due limit 1",
                            (ids,)).fetchone():
        raise errors.conflict(MAINTENANCE_STAYS)


def friday_counts(conn, owner_id, week_start) -> dict:
    """{"done_count", "total"} of the owner's live Friday batch that week, in COMPANY ROWS (#828), its
    business-development tasks only (kind <> 'maintenance': the pinned maintenance follow-ups are not
    part of the 10) (BDCore.weeklyProgress over the rows; api.js fridayTasks: the latest one, which is
    the one a forced re-run has not replaced)."""
    rows = conn.execute(
        "select t.kind, t.batch_id, t.status, c.company_id from tasks t join task_batches b on b.id = t.batch_id"
        " join contacts c on c.id = t.contact_id"
        " where b.owner_id = %s and b.week_start = %s and b.kind = 'friday' and b.replaced_at is null"
        " and t.kind <> 'maintenance' order by t.id",
        (owner_id, week_start)).fetchall()
    groups: dict = {}
    for r in rows:
        groups.setdefault(_row_key(r["kind"], r["batch_id"], r["company_id"]), []).append(r["status"])
    p = pacemod.weekly_progress([{"status": company_facts.row_status(s)} for s in groups.values()])
    return {"done_count": p["done"], "total": p["total"]}


# ── company rows (#828) ──────────────────────────────────────────────────────────────────────
def _row_key(kind, batch_id, company_id) -> tuple:
    """THE ROW: which row a task is on. The "Due now" group for a maintenance task, else its batch;
    then its company (its person's company now). week_rows and friday_counts group by it, _row_tasks
    finds the same tasks in SQL. (Logging a call closes more than one row on purpose: every open BD
    row at the company this week, interactions_service.close_current_task.)"""
    return ("due", company_id) if kind == "maintenance" else (batch_id, company_id)


def _section(task, live, batch_kinds) -> str:
    """due ("Due now") | ten (the live Friday 10) | more (Give Me 10 More) | replaced (an old Friday)."""
    if task["kind"] == "maintenance":
        return "due"
    if task["batch_id"] == live:
        return "ten"
    return "more" if batch_kinds.get(task["batch_id"]) == "ten_more" else "replaced"


def load_row_people(conn, owner_id, company_ids, contact_ids) -> list:
    """contacts_summary rows of everyone a row may show: the owner's people at these companies who
    are not archived, and the people the rows' tasks are for (whoever owns them now), by name."""
    return conn.execute(
        serialize.CONTACT_SELECT + " where (cs.company_id = any(%s) and cs.owner_id = %s and cs.archived_at is null)"
        " or cs.id = any(%s) order by lower(cs.name) collate \"C\", cs.id",
        (sorted(company_ids), owner_id, sorted(contact_ids))).fetchall()


def row_people(people, owner_id, company_id, maintenance, task_contact_ids) -> list:
    """The people a row shows (`people` from load_row_people): the row's task people first, in task
    order (the first is the person to call first), then the owner's other people at the company on
    the row's tab (maintenance for a "Due now" row, else BD), by name. (week_rows then moves anyone
    marked not the right person on the row to the end.)"""
    by_id = {p["id"]: p for p in people}
    first = [by_id[c] for c in dict.fromkeys(task_contact_ids) if c in by_id]
    tab = "maintenance" if maintenance else "bd"
    seen = {p["id"] for p in first}
    return first + [p for p in people if p["company_id"] == company_id and p["owner_id"] == owner_id
                    and p["category"] == tab and p["archived_at"] is None and p["id"] not in seen]


def week_rows(conn, owner_id, tasks, batches) -> list:
    """The WeekRows of a week (`tasks`: its Task objects in list order, `batches`: its TaskBatches),
    in the order of each row's first task."""
    fridays = [b["id"] for b in batches if b["kind"] == "friday"]
    live = fridays[-1] if fridays else None
    kinds = {b["id"]: b["kind"] for b in batches}
    groups: dict = {}
    for t in tasks:
        groups.setdefault(_row_key(t["kind"], t["batch_id"], t["contact"]["company"]["id"]), []).append(t)
    if not groups:
        return []
    company_ids = {key[1] for key in groups}
    facts = company_facts.load(conn, company_ids)
    people = load_row_people(conn, owner_id, company_ids, {t["contact"]["id"] for t in tasks})
    flagged = company_facts.flagged(conn, [t["id"] for t in tasks])
    out = []
    for (place, company_id), row in groups.items():
        task_of: dict = {}
        for t in row:
            task_of.setdefault(t["contact"]["id"], t["id"])
        persons = [serialize.week_row_person(p, task_of.get(p["id"]), any((p["id"], t["id"]) in flagged for t in row))
                   for p in row_people(people, owner_id, company_id, place == "due", [t["contact"]["id"] for t in row])]
        # Someone marked not the right person on this row goes last (a stable sort): the row's first
        # person, whom its Call and Next up's Call dial, is someone who may still be the right one.
        persons.sort(key=lambda x: x["not_right_person"])
        out.append(serialize.week_row(_section(row[0], live, kinds), row,
                                      company_facts.row_status((t["status"] for t in row), due=place == "due"),
                                      row[0]["contact"]["company"], facts.get(company_id), persons))
    return out


def owner_pace(conn, owner_id) -> dict:
    """The Pace object over every contact the owner owns (bd and maintenance, not archived),
    as of bd_today(). contacts_summary's effective_frequency is BDCore.freqOf and its
    touches_this_year is the touches dated this Central year up to today."""
    row = conn.execute(
        "select coalesce(sum(cs.effective_frequency), 0)::bigint as target,"
        " coalesce(sum(cs.touches_this_year), 0)::bigint as completed, bd_today() as today"
        " from contacts_summary cs where cs.owner_id = %s and cs.archived_at is null",
        (owner_id,)).fetchone()
    return pacemod.pace_from_totals(row["target"], row["completed"], row["today"])


def week_view(conn, owner: dict, week_start: _dt.date) -> dict:
    """The WeekView (docs/bd/api-contract.md) of `owner` for the week starting `week_start`."""
    from psycopg import sql

    week_end = bizdate.add_days(week_start, 6)
    today = bizdate.today_central()
    batches = [serialize.task_batch(r) for r in conn.execute(
        serialize.BATCH_SELECT + " where b.owner_id = %s and b.week_start = %s order by b.id",
        (owner["id"], week_start)).fetchall()]
    tasks = serialize.fetch_tasks(conn, sql.SQL("b.owner_id = %s and b.week_start = %s"),
                                  (owner["id"], week_start), "batch", serialize.MAX_LIMIT)
    # One row per company (#828). The headline counts the live Friday batch's BD rows only: the
    # latest batch (a forced re-run's replaced one is still listed, not counted), without the pinned
    # maintenance follow-ups. "Due now": the open maintenance rows, one per company, any batch.
    rows = week_rows(conn, owner["id"], tasks, batches)
    progress = pacemod.weekly_progress([r for r in rows if r["section"] == "ten"])
    due_count = sum(1 for r in rows if r["section"] == "due" and r["status"] == "open")

    settings = appsettings.load(conn)
    system = list(settings.get("system_lead_sources") or ["DSBC Sales", "Website Lead"])
    # Interactions on the owner's contacts dated in this week and not after today (Central).
    last = min(week_end, today)
    start, end = bizdate.range_utc(week_start, last) if last >= week_start else (None, None)
    counts = {"touches": 0, "meetings": 0, "non_system": 0}
    if start is not None:
        counts = conn.execute(
            "select count(*) filter (where i.counts_as_touch) as touches,"
            " count(*) filter (where i.kind in ('meeting', 'hosted')"
            "   or (i.kind = 'call' and i.outcome = 'meeting_set')) as meetings,"
            " count(*) filter (where (i.kind in ('meeting', 'hosted')"
            "   or (i.kind = 'call' and i.outcome = 'meeting_set'))"
            "   and coalesce(c.lead_source, '') <> all(%s::text[])) as non_system"
            " from interactions i join contacts c on c.id = i.contact_id"
            " where c.owner_id = %s and c.archived_at is null"
            " and i.occurred_at >= %s and i.occurred_at < %s",
            (system, owner["id"], start, end)).fetchone()

    return {
        "week_start": bizdate.iso_date(week_start),
        "week_end": bizdate.iso_date(week_end),
        "owner": serialize.user_ref(owner["id"], owner["name"]),
        "batch": batches[-1] if batches else None,
        "batches": batches,
        "tasks": tasks,
        "rows": rows,
        "done_count": progress["done"],
        "total": progress["total"],
        "due_count": due_count,
        "pace": owner_pace(conn, owner["id"]),
        "weekly_meetings": {
            "count": int(counts["meetings"]),
            "goal": settings.get("weekly_meeting_goal"),
            "non_dsbc_website": int(counts["non_system"]),
            "min": settings.get("non_dsbc_website_min"),
        },
        "touches_this_week": int(counts["touches"]),
    }


def _load_task(conn, task_id):
    """The task row with its batch's owner_id, week_start and kind, or 404. Not locked: _row_tasks
    locks every task of its row in id order, so two buttons on one row never wait on each other."""
    tid = paging.as_id(task_id)
    row = None
    if tid is not None:
        row = conn.execute(
            "select t.*, b.owner_id, b.week_start, b.kind as batch_kind"
            " from tasks t join task_batches b on b.id = t.batch_id where t.id = %s", (tid,)).fetchone()
    if row is None:
        raise errors.not_found("That task does not exist.")
    return row


def _check_own_list(me, task) -> None:
    if not is_admin(me) and task["owner_id"] != me["id"]:
        raise errors.forbidden("That task is on someone else's list.")


def _salesperson_task(conn, me, task_id):
    """api.js taskById + taskOwnerCheck: 404, then salesperson/admin, then own list."""
    task = _load_task(conn, task_id)
    if not has_role(me, "salesperson"):
        raise errors.forbidden("Your role can't do that.")
    _check_own_list(me, task)
    return task


def _row_tasks(conn, task) -> list:
    """Every task of `task`'s company row (_row_key), locked, in id order: the same owner's week, the
    same company (its people's company now), and the "Due now" group for a maintenance task, else the
    same batch. Always holds `task` itself."""
    return conn.execute(
        "select t.* from tasks t join task_batches b on b.id = t.batch_id join contacts c on c.id = t.contact_id"
        " where b.owner_id = %(owner)s and b.week_start = %(ws)s"
        " and c.company_id = (select company_id from contacts where id = %(cid)s)"
        " and (case when %(due)s then t.kind = 'maintenance' else t.kind <> 'maintenance' and t.batch_id = %(batch)s end)"
        " order by t.id for update of t",
        {"owner": task["owner_id"], "ws": task["week_start"], "cid": task["contact_id"],
         "due": task["kind"] == "maintenance", "batch": task["batch_id"]}).fetchall()


def _row_status(row) -> str:
    return company_facts.row_status((t["status"] for t in row), due=row[0]["kind"] == "maintenance")


def _ids(row) -> list:
    return [t["id"] for t in row]


def _body_text(body, key: str, limit: int, what: str):
    """An optional text field of an optional JSON object body: stripped, "" -> None."""
    value = paging.json_object(body).get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise errors.bad_request("Some fields need fixing.", {key: "Type the %s as text." % what})
    value = value.strip()
    if len(value) > limit:
        raise errors.bad_request("Some fields need fixing.",
                                 {key: "Keep the %s under %d characters." % (what, limit)})
    return value or None


# ── GET /api/bd/week ────────────────────────────────────────────────────────────────────────
@router.get("/api/bd/week")
def get_week(owner: str | None = Query(None), week_start: str | None = Query(None),
             me: dict = Depends(current_user)):
    with db.connect() as conn:
        who = weekly.week_owner(conn, owner, me)
        if not has_role(me, "salesperson", "manager"):
            raise errors.forbidden("The weekly list is the salesperson's.")
        if me.get("role") == "salesperson" and who["id"] != me["id"]:
            raise errors.forbidden("You can see only your own week.")
        ws = _parse_week_start(week_start)
        return {"ok": True, "week": week_view(conn, who, ws)}


# ── POST /api/bd/week/ten-more ───────────────────────────────────────────────────────────────
@router.post("/api/bd/week/ten-more")
def ten_more(body: Any = Body(None), me: dict = Depends(require_role("salesperson"))):
    """"Give Me 10 More" (api.js tenMore): a ten_more batch of this week with the next 10 by score,
    leaving out anyone on this week's lists in any state; answers with the whole week."""
    # api.js reads body.owner, and a body that is not an object has none.
    asked = body.get("owner") if isinstance(body, dict) else None
    if asked is None and me.get("role") == "salesperson":
        asked = me["id"]
    with db.connect() as conn:
        who = weekly.list_owner(conn, asked, me)
        if not is_admin(me) and who["id"] != me["id"]:
            raise errors.forbidden("You can ask for more only on your own list.")
        today = bizdate.today_central()          # read once: the build and the answer share a week
        try:
            weekly.ten_more(conn, who, today)
        except weekly.NothingLeft:
            raise errors.conflict("Everyone on your list is already covered this week.") from None
        return {"ok": True, "week": week_view(conn, who, bizdate.week_start(today))}


# ── the task buttons ─────────────────────────────────────────────────────────────────────────
@router.post("/api/bd/tasks/{id}/done")
def task_done(task_id: str = Path(alias="id"), body: Any = Body(None), me: dict = Depends(current_user)):
    with db.connect() as conn:
        task = _salesperson_task(conn, me, task_id)
        paging.json_object(body)
        tasks = _row_tasks(conn, task)
        _refuse_if_pinned(conn, tasks)
        if _row_status(tasks) == "done":
            raise errors.conflict("That task is already done.")
        conn.execute(
            "update tasks set status = 'done', done_at = bd_now(), snoozed_until = null,"
            " closed_by_archive = false where id = any(%s) and status <> 'done'", (_ids(tasks),))
        row = conn.execute("select id, batch_id, status, done_at from tasks where id = %s", (task["id"],)).fetchone()
        n = friday_counts(conn, task["owner_id"], task["week_start"])
        return {"ok": True,
                "task": {"id": row["id"], "batch_id": row["batch_id"], "status": row["status"],
                         "done_at": serialize.ts(row["done_at"])},
                "done_count": n["done_count"], "total": n["total"]}


@router.post("/api/bd/tasks/{id}/snooze")
def task_snooze(task_id: str = Path(alias="id"), body: Any = Body(None), me: dict = Depends(current_user)):
    with db.connect() as conn:
        task = _salesperson_task(conn, me, task_id)
        reason = _body_text(body, "reason", MAX_REASON, "reason")
        tasks = _row_tasks(conn, task)
        _refuse_if_pinned(conn, tasks)
        if _row_status(tasks) != "open":
            raise errors.conflict("Only an open task can be skipped.")
        # Back on the next week's Monday: the company is simply scored again on Friday.
        until = bizdate.add_days(task["week_start"], 7)
        conn.execute(
            "update tasks set status = 'snoozed', snoozed_until = %s, snooze_reason = %s,"
            " closed_by_archive = false where id = any(%s) and status = 'open'", (until, reason, _ids(tasks)))
        row = conn.execute("select id, status, snoozed_until from tasks where id = %s", (task["id"],)).fetchone()
        n = friday_counts(conn, task["owner_id"], task["week_start"])
        return {"ok": True,
                "task": {"id": row["id"], "status": row["status"],
                         "snoozed_until": bizdate.iso_date(row["snoozed_until"])},
                "done_count": n["done_count"], "total": n["total"]}


@router.post("/api/bd/tasks/{id}/reopen")
def task_reopen(task_id: str = Path(alias="id"), body: Any = Body(None), me: dict = Depends(current_user)):
    with db.connect() as conn:
        task = _salesperson_task(conn, me, task_id)
        paging.json_object(body)
        tasks = _row_tasks(conn, task)
        if _row_status(tasks) == "open":
            raise errors.conflict("That task is already open.")
        conn.execute(
            "update tasks set status = 'open', done_at = null, snoozed_until = null,"
            " snooze_reason = null, closed_by_archive = false where id = any(%s)", (_ids(tasks),))
        row = conn.execute("select id, status from tasks where id = %s", (task["id"],)).fetchone()
        return {"ok": True, "task": {"id": row["id"], "status": row["status"], "done_at": None,
                                     "snoozed_until": None}}


def _row_person(body, on_row: list, task) -> int:
    """The person a "not the right person" names: body `contact_id`, someone on the task's row (400
    otherwise), or the task's own person when it is left out."""
    value = paging.json_object(body).get("contact_id")
    if value is None:
        return task["contact_id"]
    cid = paging.as_id(value)
    if cid is None or cid not in on_row:
        raise errors.bad_request("Some fields need fixing.", {"contact_id": "Pick someone on this row."})
    return cid


@router.post("/api/bd/tasks/{id}/not-right-person")
def task_not_right_person(task_id: str = Path(alias="id"), body: Any = Body(None),
                          me: dict = Depends(require_role("salesperson", "assistant"))):
    with db.connect() as conn:
        # Any salesperson or the assistant, on anyone's list: the contract names no task owner
        # here (unlike /done, /snooze, /reopen) and api.js taskNotRightPerson checks only the role
        # (review finding C5). Flagging a wrong person is a data fix, not a list action.
        task = _load_task(conn, task_id)
        note = _body_text(body, "note", MAX_NOTE, "note")
        tasks = _row_tasks(conn, task)
        company_id = conn.execute("select company_id from contacts where id = %s",
                                  (task["contact_id"],)).fetchone()["company_id"]
        task_people = [t["contact_id"] for t in tasks]
        on_row = [p["id"] for p in row_people(
            load_row_people(conn, task["owner_id"], [company_id], task_people), task["owner_id"], company_id,
            task["kind"] == "maintenance", task_people)]
        who = _row_person(body, on_row, task)
        contact = conn.execute(
            "update contacts set confirmed = false,"
            " notes = case when %(note)s::text is null then notes"
            "              when coalesce(notes, '') = '' then %(note)s::text"
            "              else notes || E'\\n' || %(note)s::text end"
            " where id = %(id)s returning id, confirmed, notes",
            {"note": note, "id": who}).fetchone()
        log_event(conn, "unconfirmed", actor=me, contact_id=who, detail=note,
                  data={"task_id": task["id"], "via": "not_right_person"})
        # The row stays open while someone else on it can be called; with nobody left it closes.
        left = conn.execute("select p.id from contacts p where p.id = any(%(people)s) and " + company_facts.CALLABLE_SQL,
                            {"people": on_row, "tasks": [str(i) for i in _ids(tasks)]}).fetchall()
        if not left:
            conn.execute(
                "update tasks set status = 'done', done_at = bd_now(), snoozed_until = null,"
                " closed_by_archive = false where id = any(%s) and status <> 'done'", (_ids(tasks),))
        row = conn.execute("select id, status, done_at from tasks where id = %s", (task["id"],)).fetchone()
        return {"ok": True,
                "task": {"id": row["id"], "status": row["status"], "done_at": serialize.ts(row["done_at"])},
                "contact": {"id": contact["id"], "confirmed": bool(contact["confirmed"]),
                            "notes": contact["notes"]}}
