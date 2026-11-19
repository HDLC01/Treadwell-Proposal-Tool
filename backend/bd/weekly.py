"""The weekly 10: who is suggested, the Friday batch, "Give Me 10 More", the rollover and when the
Friday run is due. Ported from BD's weekly.py (#807) with package-relative imports and psycopg
imported where it is used (the app imports this module at start-up, and imports open nothing);
the rules are unchanged. BD's Phase 1 mock was the reference:

    BDCore.taskKind / rankContacts / pickWeekly / pickNext / toTask   frontend/bd/js/bd-core.js
    api.js runWeekly (the Friday batch + rollover), tenMore, addBatch (BD's mock, retired in #806)

"api.js X" below names a function of BD's retired mock, frontend/js/api.js in the BD repository; it
is kept only to trace a rule back. docs/bd/api-contract.md is the spec.

The routes that build (POST /api/bd/week/ten-more, POST /api/bd/admin/weekly/run) call
ten_more() and build_batch(); the Friday worker (bd/weekly_worker.py) calls run_due().

NOT AI. Nothing here calls the model; the score is the rule table in priority.py.

PURE RULES (no database)
    task_kind(contact) -> "maintenance" | "new" | "followup"
    rank_contacts(contacts, facts_by_id, today) -> [Pick]     best first, excluded ones left out
    pick_weekly(ranked, n_new=5, n_follow=5) -> [Pick]        the Friday split
    pick_next(ranked, n=10) -> [Pick]                         "Give Me 10 More"
    should_run(now, last_run_week, run_day="friday", run_hour=16, enabled=True) -> date | None
    facts_from_ids(ids) -> {id: {"has_open_task": True}}

    Pick = {"contact_id", "contact", "kind", "score", "reason", "reasons"}   (BDCore toTask)

THE ORDER (rankContacts), two tiers that never mix:
    1. DUE MAINTENANCE (kind "maintenance": a maintenance contact whose follow-up is due, the
       contacts_summary maintenance_due), most overdue first: maintenance_due_date ascending, a
       contact never followed up (no date) before any date, then contact id ascending. A
       maintenance contact that is NOT due is excluded (priority.py exclusion 4): it is on a list
       only when due, in the Friday build and in Give Me 10 More alike.
    2. EVERYONE ELSE (business development), score descending, then contact id ascending.
That is a total order (ids are unique), so it is deterministic. pick_weekly puts EVERY due
maintenance contact first, then takes, from the BD contacts only, the best `n_new` "new" and the
best `n_follow` "followup"; when one side is short the OTHER side fills the gap (new first, then
follow-ups, as the mock does), so the BD part reaches n_new + n_follow whenever enough people are
left. The BD picks are re-sorted by score and id. The batch is maintenance + BD (more than 10 due
maintenance contacts simply make it longer), and that is the order its rows are inserted (task ids
ascend: maintenance first, then BD best first). A maintenance task's score is the normal priority
score and its reasons start with why it is due (priority.maintenance_due_reason).

DATABASE (psycopg 3 connection with dict rows; every build runs in ONE transaction of its own, a
savepoint when the caller already has one; run_due builds each owner in its own, see there)
    load_owned(conn, owner, today) -> [contacts_summary row]   the owner's contacts, not archived
    load_facts(conn, owner, week_start, any_status) -> facts_by_id   ONE query per batch
    rank(conn, owner, today, facts_by_id=None) -> [Pick]
    build_batch(conn, owner, today, kind="friday", week_start=None, force=False, settings=None)
    ten_more(conn, owner, today, n=10)
    last_friday_week(conn, owner, up_to=None) -> date | None
    run_due(conn, now=None, commit=False, failed=None) -> [result]   what the worker calls

WHOSE WEEK (the routes' owner rules: This Week's routes and the admin's run share them)
    week_owner(conn, owner_param, me) -> users dict    GET /api/bd/week's owner (404 when unknown)
    list_owner(conn, owner_param, me) -> users dict    the builds' owner: a salesperson, else 404
    monday_or_none(value) -> date | None               a week_start a caller sent

`owner` is a users row/dict with "id", or a bare id. `today` is a Central date (or "YYYY-MM-DD").
contacts_summary derives last_live_at, attempts_since_live ... as of the SQL bd_today(); when
`today` is not the connection's business date, these functions set it for their own transaction
only (set_config(..., true)) and put it back.

THE FACTS (priority.py's second argument), loaded by load_facts in one query:
    Friday batch      has_open_task = the contact has an OPEN task in the TARGET week (any batch:
                      a "Give Me 10 More" batch of that week counts; the rollover and a forced
                      replacement have already snoozed the older ones). api.js runWeekly `skip`.
    Give Me 10 More   has_open_task = the contact has a task in THIS week in ANY state (open, done
                      or snoozed), so "the next 10" never repeats a name, or an OPEN task on a
                      LATER week's list (next week's Friday batch, built on Friday at 16:00, so a
                      press on Friday evening or the weekend never doubles a name). api.js
                      tenMore `skip`.
    No quote fact: last_quote_date is the contact's own column (see priority.py).

THE ROLLOVER (api.js runWeekly), done by build_batch(kind="friday") BEFORE it picks: every OPEN
task of the owner in a batch of an EARLIER week than the target week (Friday or Give Me 10 More),
and with force every open task of EVERY Friday batch of the target week (the live one being
replaced and any replaced earlier, where a task may have been reopened since: the mock has no
replaced flag and treats them all alike), becomes "snoozed" with snoozed_until = the target
week's Monday. Nothing carries over as overdue; the contact is scored
again. It happens when the batch is built (Friday 16:00 for next week), not on Monday.

IDEMPOTENCY. One live Friday batch per owner and week: the unique index of
migrations/003_one_friday_batch.sql, plus a per-owner advisory lock so two builders take turns.
An existing batch (or a racing one) raises BatchExists, and the whole build rolls back.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import logging
from collections.abc import Iterator
from typing import Any

from . import appsettings, bizdate, errors, paging, priority, serialize

RUN_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# The run builds NEXT week's list and its rollover closes this week's open tasks, so it may only
# run once this week's work is over: Friday, Saturday or Sunday (a Monday run would snooze the
# list on the Monday it starts). the admin's settings accept only these.
ALLOWED_RUN_DAYS = ("friday", "saturday", "sunday")
DEFAULT_NEW = 5
DEFAULT_FOLLOW = 5
DEFAULT_RUN_DAY = "friday"
DEFAULT_RUN_HOUR = 16
TEN_MORE_COUNT = 10
log = logging.getLogger("bd.weekly")
_LOCK_KEY = 0x0BDC0003          # pg_advisory_xact_lock(_LOCK_KEY, hashtext(owner id))


class WeeklyError(Exception):
    """A weekly build that cannot happen (the routes answer 409)."""


class BatchExists(WeeklyError):
    def __init__(self, owner_id: Any, week_start: Any, batch_id: Any = None) -> None:
        self.owner_id, self.week_start, self.batch_id = owner_id, week_start, batch_id
        super().__init__("A Friday batch already exists for owner %s, week of %s." % (owner_id, week_start))


class NothingLeft(WeeklyError):
    def __init__(self, owner_id: Any, week_start: Any) -> None:
        self.owner_id, self.week_start = owner_id, week_start
        super().__init__("Everyone on your list is already covered this week.")


# ── pure rules ───────────────────────────────────────────────────────────────────────────────
def task_kind(contact: Any) -> str:
    """BDCore.taskKind: "maintenance" (a due maintenance contact), else "new" (never had a live
    talk) or "followup". Being unconfirmed does not change the kind (it adds +8 and a reason
    instead)."""
    c = contact or {}
    if c.get("category") == "maintenance" and priority._truthy(c.get("maintenance_due")):
        return "maintenance"
    return "followup" if priority._truthy(c.get("last_live_at")) else "new"


def facts_from_ids(ids: Any) -> dict:
    """{contact_id: {"has_open_task": True}} for a list of ids (api.js `skip`)."""
    return {int(i): {"has_open_task": True} for i in (ids or [])}


def _facts_for(facts_by_id: Any, cid: Any) -> dict:
    """The facts of one contact; has_open_task is always sent (the mock sends true or false)."""
    f = dict((facts_by_id or {}).get(cid) or {})
    f["has_open_task"] = bool(f.get("has_open_task"))
    return f


def _rank_key(r: dict) -> tuple:
    """BDCore.rankOrder: due maintenance first (earliest follow-up date first, "" = never followed
    up before any date, then id), then the rest by score descending and id."""
    if r["kind"] == "maintenance":
        due = priority._text(r["contact"].get("maintenance_due_date"))
        return (0, str(due) if priority._truthy(due) else "", r["contact_id"])
    return (1, -r["score"], r["contact_id"])


def rank_contacts(contacts: Any, facts_by_id: Any, today: Any) -> list:
    """BDCore.rankContacts over contacts whose derived fields are already as of `today`: every
    contact that may be suggested, scored, in list order: due maintenance first (most overdue
    first), then everyone else by score, best first (ties: lower id first). A maintenance contact
    that is not due is left out; a due one's reasons start with why it is due."""
    out = []
    for c in contacts or []:
        cid = c["id"]
        s = priority.score(c, _facts_for(facts_by_id, cid), today)
        if s["excluded"]:
            continue
        kind = task_kind(c)
        reasons = s["reasons"]
        if kind == "maintenance":
            reasons = [priority.maintenance_due_reason(c, today)] + reasons
        out.append({"contact_id": cid, "contact": c, "kind": kind, "score": s["score"],
                    "reason": priority.reason_text(reasons), "reasons": reasons})
    out.sort(key=_rank_key)
    return out


def pick_weekly(ranked: list[dict], n_new: Any = None, n_follow: Any = None) -> list:
    """BDCore.pickWeekly on an already ranked list: every due maintenance contact first (as
    ranked), then n_new "new" + n_follow "followup" BD contacts, the short side filled from the
    other (new first), best first. The split is about the BD contacts only."""
    want_new = DEFAULT_NEW if n_new is None else int(n_new)
    want_follow = DEFAULT_FOLLOW if n_follow is None else int(n_follow)
    pinned = [r for r in ranked if r["kind"] == "maintenance"]
    news = [r for r in ranked if r["kind"] == "new"]
    follows = [r for r in ranked if r["kind"] == "followup"]
    take_new = min(want_new, len(news))
    take_follow = min(want_follow, len(follows))
    room = want_new + want_follow - take_new - take_follow
    if room > 0 and take_new < len(news):
        a = min(room, len(news) - take_new)
        take_new += a
        room -= a
    if room > 0 and take_follow < len(follows):
        take_follow += min(room, len(follows) - take_follow)
    picked = news[:take_new] + follows[:take_follow]
    picked.sort(key=lambda r: (-r["score"], r["contact_id"]))
    return pinned + picked


def pick_next(ranked: list[dict], n: Any = None) -> list:
    """BDCore.pickNext: the next n of the same ranking, whatever their kind (a maintenance contact
    that came due mid-week heads the list as a maintenance task)."""
    return list(ranked[:TEN_MORE_COUNT if n is None else int(n)])


def weekly_settings(settings: Any) -> dict:
    """The `weekly` Settings with the defaults filled in: new_count, followup_count, run_day,
    run_hour, enabled."""
    w = dict((settings or {}).get("weekly") or {})
    return {
        "new_count": DEFAULT_NEW if w.get("new_count") is None else int(w["new_count"]),
        "followup_count": DEFAULT_FOLLOW if w.get("followup_count") is None else int(w["followup_count"]),
        "run_day": str(w.get("run_day") or DEFAULT_RUN_DAY).lower(),
        "run_hour": DEFAULT_RUN_HOUR if w.get("run_hour") is None else int(w["run_hour"]),
        "enabled": True if w.get("enabled") is None else bool(w["enabled"]),
    }


def run_moment(day: Any, run_day: str = DEFAULT_RUN_DAY, run_hour: Any = DEFAULT_RUN_HOUR) -> _dt.datetime:
    """The aware Central moment of the weekly run in the Monday-Sunday week `day` falls in."""
    if run_day not in ALLOWED_RUN_DAYS:
        raise ValueError("run_day must be one of %s" % ", ".join(ALLOWED_RUN_DAYS))
    if not 0 <= int(run_hour) <= 23:
        raise ValueError("run_hour must be 0-23")
    when = bizdate.add_days(bizdate.week_start(day), RUN_DAYS.index(run_day))
    # The run day never holds a DST change at that hour in America/Chicago (they happen on Sunday
    # at 02:00), so the wall-clock time is unambiguous; fold=0 picks the first if it ever were.
    return _dt.datetime.combine(when, _dt.time(int(run_hour), 0)).replace(tzinfo=bizdate.BIZ_TZ, fold=0)


def should_run(now: Any, last_run_week: Any, run_day: str = DEFAULT_RUN_DAY, run_hour: Any = DEFAULT_RUN_HOUR,
               enabled: bool = True) -> _dt.date | None:
    """The Monday of the week to build a Friday batch for, or None.

    Due once the run moment of the current Central week has passed (Friday 16:00 by default; a
    naive `now` is Central wall-clock time), for NEXT week, and only while that week has no live
    Friday batch yet: `last_run_week` is the latest week_start of the owner's live Friday
    batches up to that Monday (None: never). So Friday 15:59 is not due, 16:00 is, and a worker
    that was down on Friday catches up on Saturday or Sunday. On Monday a new week begins and its
    run moment is ahead again: a batch missed over a whole weekend is not built by the worker
    (an admin builds it with POST /api/bd/admin/weekly/run and week_start = this Monday)."""
    if not enabled:
        return None
    moment = bizdate.parse_ts(now).astimezone(bizdate.BIZ_TZ)
    due = run_moment(moment.date(), run_day, run_hour)
    if moment < due:
        return None
    target = bizdate.add_days(bizdate.week_start(moment.date()), 7)
    if last_run_week is not None and bizdate.parse_date(last_run_week) >= target:
        return None
    return target


# ── database helpers ─────────────────────────────────────────────────────────────────────────
def _owner_id(owner: Any) -> int:
    return int(owner["id"] if isinstance(owner, dict) else owner)


def _day(today: Any) -> _dt.date:
    if today is None:
        raise ValueError("today is required (a Central date)")
    if isinstance(today, _dt.datetime):
        return bizdate.parse_ts(today).astimezone(bizdate.BIZ_TZ).date()     # its Central date, whatever zone
    return bizdate.parse_date(today if isinstance(today, _dt.date) else str(today)[:10])


@contextlib.contextmanager
def _transaction(conn: Any, today: _dt.date) -> Iterator[None]:
    """One transaction (a savepoint inside the caller's) in which bd_today() is `today`."""
    with conn.transaction():
        row = conn.execute("select bd_today() as d, current_setting('bd.today', true) as raw").fetchone()
        moved = row["d"] != today
        if moved:
            conn.execute("select set_config('bd.today', %s, true)", (today.isoformat(),))
        yield
        if moved:
            conn.execute("select set_config('bd.today', %s, true)", (row["raw"] or "",))


def _lock_owner(conn: Any, owner_id: Any) -> None:
    """Builders of one owner's list take turns until their transaction ends."""
    conn.execute("select pg_advisory_xact_lock(%s, hashtext(%s))", (_LOCK_KEY, str(owner_id)))


def load_owned(conn: Any, owner: Any, today: Any) -> list:
    """Every contact the owner owns and has not archived, as contacts_summary rows as of `today`
    (api.js ownedBy). Call inside _transaction, or through rank()."""
    return conn.execute(
        "select * from contacts_summary where owner_id = %s and archived_at is null order by id",
        (_owner_id(owner),)).fetchall()


def load_facts(conn: Any, owner: Any, week_start: Any, any_status: bool) -> dict:
    """The facts of every contact on the owner's lists for the week starting `week_start`, in one
    query: {contact_id: {"has_open_task": True}}. any_status=False counts OPEN tasks only (the
    Friday batch); True counts every task of that week, plus every OPEN task on a later week's
    list (Give Me 10 More)."""
    rows = conn.execute(
        "select distinct t.contact_id from tasks t join task_batches b on b.id = t.batch_id"
        " where b.owner_id = %(owner)s and ((b.week_start = %(ws)s and (%(any)s or t.status = 'open'))"
        " or (%(any)s and b.week_start > %(ws)s and t.status = 'open'))",
        {"owner": _owner_id(owner), "ws": bizdate.parse_date(week_start), "any": bool(any_status)}).fetchall()
    return facts_from_ids(r["contact_id"] for r in rows)


def rank(conn: Any, owner: Any, today: Any, facts_by_id: Any = None) -> list:
    """rank_contacts over the owner's contacts as of `today`."""
    day = _day(today)
    with _transaction(conn, day):
        rows = load_owned(conn, owner, day)
    return rank_contacts(rows, facts_by_id, day)


def _insert_batch(conn: Any, owner_id: Any, week_start: Any, kind: str, picks: list[dict]) -> Any:
    """api.js addBatch: the batch, then its tasks in pick order. Returns the BATCH_SELECT row."""
    row = conn.execute(
        "insert into task_batches (owner_id, week_start, kind) values (%s, %s, %s) returning id",
        (owner_id, week_start, kind)).fetchone()
    if picks:
        with conn.cursor() as cur:
            cur.executemany(
                "insert into tasks (batch_id, contact_id, kind, reason, reasons, score)"
                " values (%s, %s, %s, %s, %s, %s)",
                [(row["id"], p["contact_id"], p["kind"], p["reason"], list(p["reasons"]), p["score"])
                 for p in picks])
    return conn.execute(serialize.BATCH_SELECT + " where b.id = %s", (row["id"],)).fetchone()


def last_friday_week(conn: Any, owner: Any, up_to: Any = None) -> Any:
    """The latest week_start of the owner's live (not replaced) Friday batches, on or before
    `up_to` when given; None when there is none."""
    row = conn.execute(
        "select max(week_start) as w from task_batches where owner_id = %s and kind = 'friday'"
        " and replaced_at is null and (%s::date is null or week_start <= %s::date)",
        (_owner_id(owner), up_to, up_to)).fetchone()
    return row["w"]


# ── the builds ───────────────────────────────────────────────────────────────────────────────
def build_batch(conn: Any, owner: Any, today: Any, kind: str = "friday", week_start: Any = None,
                force: bool = False, settings: Any = None) -> dict:
    """Build a batch (api.js runWeekly for "friday", tenMore for "ten_more").

    friday: for the week starting `week_start` (default: the Monday after `today`'s week), scored
    as of `today`. Raises BatchExists when that week already has a live Friday batch, unless
    `force` (then that batch is marked replaced, and the open tasks of every Friday batch of
    that week, replaced earlier or not, are snoozed). The rollover runs first, then every due
    maintenance contact of the owner gets a task, then the BD split from settings.weekly
    (new_count / followup_count) is made over the BD contacts. A batch with no tasks is still created
    when nobody is left (tasks_created 0), as the mock does.

    Returns {"batch": BATCH_SELECT row (serialize.task_batch makes the TaskBatch), "picks": [Pick],
    "tasks_created": int, "snoozed": int (tasks the rollover closed), "replaced": [batch ids]}."""
    if kind == "ten_more":
        return ten_more(conn, owner, today)
    if kind != "friday":
        raise ValueError("kind must be friday or ten_more")
    owner_id = _owner_id(owner)
    day = _day(today)
    ws = bizdate.add_days(bizdate.week_start(day), 7) if week_start is None else bizdate.parse_date(week_start)
    if ws.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    with _transaction(conn, day):
        _lock_owner(conn, owner_id)
        if settings is None:
            settings = appsettings.load(conn)
        w = weekly_settings(settings)
        fridays = conn.execute(
            "select id, replaced_at from task_batches where owner_id = %s and week_start = %s"
            " and kind = 'friday' order by id for update", (owner_id, ws)).fetchall()
        old = [r["id"] for r in fridays if r["replaced_at"] is None]
        if old and not force:
            raise BatchExists(owner_id, ws, old[-1])
        # The rollover: unfinished tasks of earlier weeks, and of every Friday batch of this week
        # (the one being replaced, and one replaced before whose task was reopened), close.
        snoozed = conn.execute(
            "update tasks t set status = 'snoozed', snoozed_until = %(ws)s"
            " from task_batches b where b.id = t.batch_id and b.owner_id = %(owner)s"
            " and t.status = 'open' and (b.week_start < %(ws)s or b.id = any(%(all)s))",
            {"ws": ws, "owner": owner_id, "all": [r["id"] for r in fridays]}).rowcount
        if old:
            conn.execute("update task_batches set replaced_at = bd_now() where id = any(%s)", (old,))
        facts = load_facts(conn, owner_id, ws, any_status=False)
        picks = pick_weekly(rank_contacts(load_owned(conn, owner_id, day), facts, day),
                            w["new_count"], w["followup_count"])
        from psycopg.errors import UniqueViolation

        try:
            with conn.transaction():
                batch = _insert_batch(conn, owner_id, ws, "friday", picks)
        except UniqueViolation as exc:
            raise BatchExists(owner_id, ws) from exc
    return {"batch": batch, "picks": picks, "tasks_created": len(picks), "snoozed": snoozed,
            "replaced": old}


def ten_more(conn: Any, owner: Any, today: Any, n: Any = TEN_MORE_COUNT) -> dict:
    """"Give Me 10 More" (api.js tenMore): a ten_more batch for `today`'s week of the next `n` of the
    ranking (due maintenance first, then by score), leaving out anyone on this week's lists in any state, anyone still open on a later
    week's list (next week's Friday batch exists from Friday 16:00) and anyone tried in the last
    3 days. Raises NothingLeft when nobody is left. No rollover. Returns the build_batch shape."""
    owner_id = _owner_id(owner)
    day = _day(today)
    ws = bizdate.week_start(day)
    with _transaction(conn, day):
        _lock_owner(conn, owner_id)
        facts = load_facts(conn, owner_id, ws, any_status=True)
        picks = pick_next(rank_contacts(load_owned(conn, owner_id, day), facts, day), n)
        if not picks:
            raise NothingLeft(owner_id, ws)
        batch = _insert_batch(conn, owner_id, ws, "ten_more", picks)
    return {"batch": batch, "picks": picks, "tasks_created": len(picks), "snoozed": 0, "replaced": []}


def run_due(conn: Any, now: Any = None, commit: bool = False, failed: list | None = None) -> list:
    """The background worker's one call: for every active salesperson whose Friday batch is due
    (should_run, with settings.weekly), build it, scored as of `now`'s Central date. A batch that
    appeared meanwhile (an admin's run) is skipped. Returns [{"owner_id", "week_start",
    "batch_id", "tasks_created"}] for the batches built.

    ONE OWNER NEVER COSTS THE OTHERS THEIR LIST. Each build is its own savepoint (build_batch), so
    an owner whose build raises is rolled back alone, logged by id, appended to `failed` (a list,
    when given) and skipped; the others are still built, and the failed one is tried again on the
    next tick. With commit=True (the worker's pooled connection) each successful build is
    committed at once, so a later failure, even of the connection itself, cannot undo it."""
    moment = bizdate.now_central() if now is None else bizdate.parse_ts(now).astimezone(bizdate.BIZ_TZ)
    day = moment.date()
    settings = appsettings.load(conn)
    w = weekly_settings(settings)
    if not w["enabled"]:
        return []
    target = bizdate.add_days(bizdate.week_start(day), 7)
    built = []
    owners = conn.execute("select id from users where role = 'salesperson' and active order by id").fetchall()
    for o in owners:
        week = should_run(moment, last_friday_week(conn, o["id"], up_to=target), w["run_day"], w["run_hour"])
        if week is None:
            continue
        try:
            res = build_batch(conn, o["id"], day, week_start=week, settings=settings)
        except BatchExists:
            continue
        except Exception:  # one owner's failure must not cost the others their list
            log.exception("weekly batch for owner %s, week of %s failed; trying again next tick",
                          o["id"], week)
            if failed is not None:
                failed.append(o["id"])
            continue
        if commit:
            conn.commit()
        built.append({"owner_id": o["id"], "week_start": week, "batch_id": res["batch"]["id"],
                      "tasks_created": res["tasks_created"]})
    return built


# ── whose week ───────────────────────────────────────────────────────────────────────────────
_ABSENT = object()


def _owner_param(value):
    """The `owner` asked for (query text or a JSON body value), as api.js ownerParam reads it:
    _ABSENT when none (None, blank text), the id for a whole number (a JSON 1.0 is JavaScript's 1)
    or digit text with spaces around it, else None (no such user: true, [1], 1.5, "1e0")."""
    if value is None:
        return _ABSENT
    if isinstance(value, float):
        return paging.as_id(int(value)) if value.is_integer() else None
    if isinstance(value, str):
        return _ABSENT if value.strip() == "" else paging.as_id(value.strip())
    return paging.as_id(value) if isinstance(value, int) else None


def week_owner(conn, owner_param, me) -> dict:
    """The owner whose week is shown (api.js weekOwner): the `owner` asked for, else me when I am
    a salesperson, else the first active salesperson (else me: nobody has a list yet)."""
    uid = _owner_param(owner_param)
    if uid is not _ABSENT:
        row = conn.execute("select id, name, role, active from users where id = %s", (uid,)).fetchone()             if uid is not None else None
        if row is None:
            raise errors.not_found("That user does not exist.")
        if row["role"] != "salesperson":
            raise errors.not_found("%s has no weekly list. Only salespeople do." % row["name"])
        return dict(row)
    if me.get("role") == "salesperson":
        return {"id": me["id"], "name": me["name"], "role": me["role"], "active": me.get("active", True)}
    row = conn.execute("select id, name, role, active from users where role = 'salesperson' and active"
                       " order by id limit 1").fetchone()
    if row is not None:
        return dict(row)
    return {"id": me["id"], "name": me["name"], "role": me["role"], "active": me.get("active", True)}


def list_owner(conn, owner_param, me) -> dict:
    """week_owner for the builds (ten-more, the admin's run; api.js listOwner): the owner it
    falls back to when nobody active is a salesperson is me, and only a salesperson has a weekly
    list, so that is the same 404 as naming one. GET /api/bd/week keeps the fallback (an empty week)."""
    who = week_owner(conn, owner_param, me)
    if who.get("role") != "salesperson":
        raise errors.not_found("%s has no weekly list. Only salespeople do." % who["name"])
    return who


MAX_WEEK_YEAR = 9998          # a week's Sunday must still be a date (9999-12-27 + 6 overflows)


def monday_or_none(value):
    """A week_start the caller sent, as api.js isMondayISO: exactly "YYYY-MM-DD" (nothing around
    it), a real date in years 1-9998, a Monday; else None."""
    d = bizdate.exact_date(value)
    return d if d is not None and d.year <= MAX_WEEK_YEAR and d.weekday() == 0 else None
