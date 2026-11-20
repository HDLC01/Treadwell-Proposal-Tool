"""BD accounts: the Contacts page's two tabs, its search, and moving a whole company between the BD and
Maintenance tabs (#810).

    GET  /api/bd/contacts/accounts                       the BD tab (?category=maintenance: the Maintenance tab)
    GET  /api/bd/contacts/search?q=                      account names, people's names, phones, emails
    POST /api/bd/contacts/accounts/{id}/move             {"to": "maintenance" | "bd"}: every person at it
    POST /api/bd/contacts/accounts/moves/{id}/undo       puts back exactly what that one move changed

A "BD account" is a companies row (the table keeps its name, Q19). Its people are its contacts that are
not archived; a person is on the BD tab or the Maintenance tab by their own `category` column, so an
account is on a tab when at least one of its people is (an account holding only maintenance people is
not on the BD tab, Q35). Nothing here changes the shape of the data.

The paths sit under /api/bd/contacts/ on purpose: the tool's audit log records every read of a path
holding "/contacts" (main._AUDIT_SENSITIVE), and these answer people's phones and emails. They never
carry a search term: the term travels as ?q=, and the audit log writes the path alone. This module is
listed before `contacts` in bd/routers/__init__.py, so "accounts" and "search" are never read as a
contact id by GET /api/bd/contacts/{id}.

THE ACCOUNT ROW (Q19, Q33, Q34, Q41):
  * people_count   the tab's people at the account (BD tab: BD people only; Maintenance tab:
                   maintenance people only), archived people left out.
  * owner          whoever owns the most of those people. A tie goes to the tied owner who logged
                   the most recent live talk at the account (Q41); when none of them has, to the
                   tied owner first by name. "+N" is `other_owners`: how many other people own
                   someone there.
  * last_live_at   the latest live touch (BD's one counting rule, interactions.counts_as_touch: a
                   call where someone talked, a meeting, a hosted event) with ANYONE at the account
                   who is not archived, BD or maintenance (Q34), dated on or before today (Central).

MOVING A COMPANY (2026-11-20, Q1-Q11). Salesperson, manager and admins; never the assistant (Q5). It
changes every person of the other category at that company (archived people too, so the company is
one category throughout) and nothing else, and takes effect at once:
  * to maintenance: each person's open BD call on this week's list (or on next week's, once the Friday
    run has made it) comes off, as a "Not this week" does (status snoozed). Nothing is added to the
    10, logged calls still count and the list is never refilled. A person whose maintenance
    follow-up is due by BD's rule (contacts_summary.maintenance_due: 120 days or more since the last
    follow-up, or never followed up) gets the pinned maintenance follow-up on their owner's list at
    once, made by the Friday batch's own rules (bd/weekly.py rank_contacts). It goes on the owner's
    live Friday list of that week when the person has no task there; otherwise (the person's BD call
    that just came off is on it, or there is no Friday list) on a small list of its own for that week
    (a "ten_more" batch holding only pinned follow-ups, which are never part of the 10).
  * to BD: each person's open pinned maintenance follow-up comes off (snoozed), and nothing is added.
  * the stored frequency becomes the new category's default, as a contact edit's category flip does.
  * ONE event, kind "company_moved", actor_id = who: {"company_id", "to", "people", and the ids
    needed to undo it: "contacts" [[id, the frequency before]], "tasks_off", "pins", "batches"}.
    Ids and counts only: no name, phone, email or note.

UNDO (Q3). Only the person who made the move, within UNDO_SECONDS of it, and only while it is the
company's latest move and everything it changed is still as it left it (each person still in the new
category, each call it took off still off, each follow-up it pinned still open). Then it puts back
exactly what was there before, the calls it took off included, and writes one "company_move_undone"
event. A stale undo is 409 and changes nothing.
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, Path, Request

from .. import appsettings, auth, bizdate, db, errors, paging, serialize, web, weekly
from ..contacts_service import COMPANY_NOT_FOUND, FIX
from ..events import log_event
from ..normalize import normalize_company
from ..phone import digits as phone_digits

router = web.make_router()

CATEGORIES = ("bd", "maintenance")
MOVE_ROLES = ("salesperson", "manager")        # and admins (Q5); require_role adds them
UNDO_SECONDS = 120
SEARCH_MAX = 200
SEARCH_LIMIT = 100
MOVED = "company_moved"
UNDONE = "company_move_undone"

MOVE_NOT_FOUND = "That move does not exist."
NOT_YOUR_MOVE = "Only the person who made this move can undo it."
ALREADY_UNDONE = "This move is already undone."
TOO_LATE = "It's too late to undo this move."
CHANGED_SINCE = "Something changed since this move, so it can't be undone."
NOBODY_TO_MOVE = {"maintenance": "Nobody at this company is a BD contact.",
                  "bd": "Nobody at this company is a maintenance contact."}

# How each sort orders the accounts (only these fixed strings reach the SQL); ties by id.
SORTS = {
    "name": 'lower(btrim(co.name)) collate "C", co.id',
    "people": 'acc.people desc, lower(btrim(co.name)) collate "C", co.id',
    "last_live_at": 'live.last_live_at desc nulls last, lower(btrim(co.name)) collate "C", co.id',
}

# A live talk BD counts, dated on or before today, with someone at company `co` who is not archived.
_LIVE_AT_COMPANY = (
    "select max(i.occurred_at) as last_live_at from contacts c2 join interactions i on i.contact_id = c2.id"
    " where c2.company_id = co.id and c2.archived_at is null and i.counts_as_touch"
    " and bd_date(i.occurred_at) <= bd_today()")


# ── the account list ─────────────────────────────────────────────────────────────────────────
def _pick_owner(people: list, talks: dict) -> tuple:
    """(owner UserRef or None, other_owners) of one account's people (contacts_summary rows).
    `talks` is {user_id: latest live talk they logged at the account}."""
    counts: dict = {}
    names: dict = {}
    for p in people:
        if p["owner_id"] is not None:
            counts[p["owner_id"]] = counts.get(p["owner_id"], 0) + 1
            names[p["owner_id"]] = p["owner_name"]
    if not counts:
        return None, 0
    top = max(counts.values())
    tied = [uid for uid, n in counts.items() if n == top]
    talked = [uid for uid in tied if talks.get(uid) is not None]
    if talked:
        owner = max(talked, key=lambda uid: (talks[uid], -uid))
    else:
        owner = min(tied, key=lambda uid: (str(names[uid] or "").lower(), uid))
    return serialize.user_ref(owner, names[owner]), len(counts) - 1


def _accounts(conn, category: str, sort: str, limit: int, offset: int) -> tuple:
    params = {"cat": category, "limit": limit, "offset": offset}
    acc = ("select c.company_id, count(*)::integer as people from contacts c"
           " where c.archived_at is null and c.category = %(cat)s group by c.company_id")
    total = conn.execute("select count(*) as n from (" + acc + ") a", params).fetchone()["n"]
    rows = conn.execute(
        "with acc as (" + acc + ")"
        " select co.id, co.name, co.city, co.industry, acc.people, live.last_live_at"
        " from acc join companies co on co.id = acc.company_id"
        " left join lateral (" + _LIVE_AT_COMPANY + ") live on true"
        " order by " + SORTS[sort] + " limit %(limit)s offset %(offset)s", params).fetchall()
    ids = [r["id"] for r in rows]
    people: dict = {i: [] for i in ids}
    talks: dict = {i: {} for i in ids}
    if ids:
        for p in conn.execute(
                serialize.CONTACT_SELECT + " where cs.company_id = any(%s) and cs.archived_at is null"
                " and cs.category = %s order by lower(cs.name) collate \"C\", cs.id", (ids, category)).fetchall():
            people[p["company_id"]].append(p)
        for t in conn.execute(
                "select c.company_id, i.user_id, max(i.occurred_at) as at from interactions i"
                " join contacts c on c.id = i.contact_id where c.company_id = any(%s) and c.archived_at is null"
                " and i.counts_as_touch and i.user_id is not null and bd_date(i.occurred_at) <= bd_today()"
                " group by c.company_id, i.user_id", (ids,)).fetchall():
            talks[t["company_id"]][t["user_id"]] = t["at"]
    items = []
    for r in rows:
        owner, others = _pick_owner(people[r["id"]], talks[r["id"]])
        items.append(serialize.account(r, category, owner, others, people[r["id"]]))
    return int(total), items


@router.get("/api/bd/contacts/accounts")
def list_accounts(request: Request, user: dict = Depends(auth.current_user)):
    q = request.query_params
    fields: dict = {}
    category = q.get("category") or "bd"
    if category not in CATEGORIES:
        fields["category"] = "Use bd or maintenance."
    sort = q.get("sort") or "name"
    if sort not in SORTS:
        fields["sort"] = "Use name, people or last_live_at."
    limit, offset = paging.page_params(q, fields)
    if fields:
        if list(fields) == ["sort"]:
            raise errors.bad_request("Unknown sort.", fields)
        raise errors.bad_request(FIX, fields)
    with db.connect() as conn:
        total, items = _accounts(conn, category, sort, limit, offset)
    return {"ok": True, "category": category, "total": total, "items": items}


# ── search ───────────────────────────────────────────────────────────────────────────────────
@router.get("/api/bd/contacts/search")
def search(request: Request, user: dict = Depends(auth.current_user)):
    """Account names, people's names, phones (any format, on the last 10 digits) and emails (any
    case). One item per account and tab it is found on, with the people who matched there."""
    raw = request.query_params.get("q")
    needle = (raw or "").strip().lower()
    if not needle:
        raise errors.bad_request(FIX, {"q": "Type something to search for."})
    if len(needle) > SEARCH_MAX:
        raise errors.bad_request(FIX, {"q": "Keep this to %d characters or fewer." % SEARCH_MAX})
    params: dict = {"n": needle}
    account_hit = "strpos(lower(co.name), %(n)s) > 0"
    cleaned = normalize_company(needle)
    if cleaned:                          # a term that cleans to nothing must not match everything
        account_hit = "(" + account_hit + " or strpos(co.normalized_name, %(cleaned)s) > 0)"
        params["cleaned"] = cleaned
    phone_hit = "false"
    nums = phone_digits(needle)
    if len(nums) >= 10:
        phone_hit = "coalesce(right(c.phone_e164, 10) = %(tel)s, false)"
        params["tel"] = nums[-10:]
    person_hit = ("(strpos(lower(c.name), %(n)s) > 0 or coalesce(strpos(c.email_lower, %(n)s) > 0, false)"
                  " or " + phone_hit + ")")
    with db.connect() as conn:
        rows = conn.execute(
            "select co.id as company_id, co.name as company_name, c.category, c.id, c.name,"
            " " + account_hit + " as account_hit, " + person_hit + " as person_hit"
            " from contacts c join companies co on co.id = c.company_id"
            " where c.archived_at is null and (" + account_hit + " or " + person_hit + ")"
            " order by lower(btrim(co.name)) collate \"C\", co.id, c.category, lower(c.name) collate \"C\", c.id",
            params).fetchall()
    items: list = []
    by_key: dict = {}
    for r in rows:
        key = (r["company_id"], r["category"])
        item = by_key.get(key)
        if item is None:
            item = {"tab": r["category"], "account": serialize.company_ref(r["company_id"], r["company_name"]),
                    "account_match": bool(r["account_hit"]), "people": []}
            by_key[key] = item
            items.append(item)
        if r["person_hit"]:
            item["people"].append({"id": r["id"], "name": r["name"]})
    return {"ok": True, "total": len(items), "items": items[:SEARCH_LIMIT]}


# ── moving a company ─────────────────────────────────────────────────────────────────────────
def _lock_company(conn, company_id) -> dict:
    row = conn.execute("select id, name from companies where id = %s for update", (company_id,)).fetchone()
    if row is None:
        raise errors.not_found(COMPANY_NOT_FOUND)
    return row


def _new_frequency(conn, to: str) -> int:
    """The stored frequency a person takes in `to`, as PATCH /api/bd/contacts/{id}'s category flip
    sets it: maintenance's default, or the BD cadence's number."""
    settings = appsettings.load(conn)
    if to == "maintenance":
        return int((settings.get("default_frequency") or {}).get("maintenance") or 3)
    return int(appsettings.CADENCE_FREQ.get(settings.get("bd_cadence") or "", 4))


def _list_week(conn, owner_id, today) -> Any:
    """The week whose list the owner works now: next week's once the Friday run has made its live
    Friday list (the run has already closed this week's), else this week."""
    this_week = bizdate.week_start(today)
    next_week = bizdate.add_days(this_week, 7)
    made = conn.execute("select 1 from task_batches where owner_id = %s and week_start = %s and kind = 'friday'"
                        " and replaced_at is null", (owner_id, next_week)).fetchone()
    return next_week if made else this_week


def _pin_due(conn, contact_ids: list, today) -> tuple:
    """The pinned maintenance follow-up, at once, for each moved person who is due and owned by an
    active salesperson (only a salesperson has a weekly list). Returns (task ids, batch ids made)."""
    rows = conn.execute(
        "select cs.* from contacts_summary cs join users u on u.id = cs.owner_id where cs.id = any(%s)"
        " and cs.archived_at is null and u.role = 'salesperson' and u.active order by cs.id",
        (contact_ids,)).fetchall()
    by_owner: dict = {}
    for r in rows:
        by_owner.setdefault(r["owner_id"], []).append(r)
    pins, batches = [], []
    for owner_id in sorted(by_owner):
        weekly.lock_owner(conn, owner_id)
        ws = _list_week(conn, owner_id, today)
        facts = weekly.load_facts(conn, owner_id, ws, any_status=False)
        picks = [p for p in weekly.rank_contacts(by_owner[owner_id], facts, today) if p["kind"] == "maintenance"]
        if not picks:
            continue
        friday = conn.execute("select id from task_batches where owner_id = %s and week_start = %s"
                              " and kind = 'friday' and replaced_at is null order by id desc limit 1",
                              (owner_id, ws)).fetchone()
        on_friday = set()
        if friday is not None:
            on_friday = {r["contact_id"] for r in conn.execute(
                "select contact_id from tasks where batch_id = %s", (friday["id"],)).fetchall()}
        own_batch = None
        for p in picks:
            if friday is not None and p["contact_id"] not in on_friday:
                batch_id = friday["id"]
            else:
                if own_batch is None:
                    own_batch = conn.execute(
                        "insert into task_batches (owner_id, week_start, kind) values (%s, %s, 'ten_more')"
                        " returning id", (owner_id, ws)).fetchone()["id"]
                    batches.append(own_batch)
                batch_id = own_batch
            pins.append(conn.execute(
                "insert into tasks (batch_id, contact_id, kind, reason, reasons, score)"
                " values (%s, %s, 'maintenance', %s, %s, %s) returning id",
                (batch_id, p["contact_id"], p["reason"], list(p["reasons"]), p["score"])).fetchone()["id"])
    return pins, batches


def _take_off(conn, contact_ids: list, kinds: tuple, today) -> list:
    """Each open task of `kinds` for these people on this week's list or a later one comes off, as
    "Not this week" does (snoozed until the Monday after its week). Returns their ids."""
    rows = conn.execute(
        "update tasks t set status = 'snoozed', snoozed_until = b.week_start + 7"
        " from task_batches b where b.id = t.batch_id and t.contact_id = any(%s) and t.status = 'open'"
        " and t.kind = any(%s) and b.week_start >= %s returning t.id",
        (contact_ids, list(kinds), bizdate.week_start(today))).fetchall()
    return sorted(r["id"] for r in rows)


def _move_body(body) -> str:
    to = paging.json_object(body).get("to")
    if to not in CATEGORIES:
        raise errors.bad_request(FIX, {"to": "Use maintenance or bd."})
    return to


@router.post("/api/bd/contacts/accounts/{id}/move")
def move_account(company_id: str = Path(alias="id"), body: Any = Body(None),
                 me: dict = Depends(auth.require_role(*MOVE_ROLES))):
    cid = paging.path_id(company_id, COMPANY_NOT_FOUND)
    to = _move_body(body)
    other = "bd" if to == "maintenance" else "maintenance"
    today = bizdate.today_central()
    with db.connect() as conn:
        company = _lock_company(conn, cid)
        rows = conn.execute("select id, frequency_per_year, archived_at from contacts where company_id = %s"
                            " and category = %s order by id for update", (cid, other)).fetchall()
        people = sum(1 for r in rows if r["archived_at"] is None)
        if not people:
            raise errors.conflict(NOBODY_TO_MOVE[to])
        ids = [r["id"] for r in rows]
        conn.execute("update contacts set category = %s, frequency_per_year = %s where id = any(%s)",
                     (to, _new_frequency(conn, to), ids))
        if to == "maintenance":
            off = _take_off(conn, ids, ("new", "followup"), today)
            pins, batches = _pin_due(conn, ids, today)
        else:
            off = _take_off(conn, ids, ("maintenance",), today)
            pins, batches = [], []
        event_id = log_event(conn, MOVED, actor=me, data={
            "company_id": cid, "to": to, "people": people,
            "contacts": [[r["id"], r["frequency_per_year"]] for r in rows],
            "tasks_off": off, "pins": pins, "batches": batches})
        at = conn.execute("select at from events where id = %s", (event_id,)).fetchone()["at"]
    return {"ok": True, "move": serialize.account_move(event_id, company, to, people, len(off), len(pins),
                                                        at, UNDO_SECONDS)}


def _ids(value) -> list:
    return [int(v) for v in value] if isinstance(value, list) else []


@router.post("/api/bd/contacts/accounts/moves/{id}/undo")
def undo_move(move_id: str = Path(alias="id"), body: Any = Body(None),
              me: dict = Depends(auth.require_role(*MOVE_ROLES))):
    mid = paging.path_id(move_id, MOVE_NOT_FOUND)
    paging.json_object(body)
    with db.connect() as conn:
        ev = conn.execute("select id, actor_id, data from events where id = %s and kind = %s",
                          (mid, MOVED)).fetchone()
        if ev is None:
            raise errors.not_found(MOVE_NOT_FOUND)
        data = ev["data"] if isinstance(ev["data"], dict) else {}
        company = _lock_company(conn, data.get("company_id"))
        if ev["actor_id"] != me["id"]:
            raise errors.forbidden(NOT_YOUR_MOVE)
        if conn.execute("select 1 from events where kind = %s and (data->>'move_id')::bigint = %s",
                        (UNDONE, mid)).fetchone():
            raise errors.conflict(ALREADY_UNDONE)
        late = conn.execute("select at < bd_now() - %s * interval '1 second' as late from events where id = %s",
                            (UNDO_SECONDS, mid)).fetchone()["late"]
        if late:
            raise errors.conflict(TOO_LATE)
        to = data.get("to")
        pairs = [(int(p[0]), int(p[1])) for p in data.get("contacts") or [] if isinstance(p, list) and len(p) == 2]
        ids = [p[0] for p in pairs]
        off, pins, batches = _ids(data.get("tasks_off")), _ids(data.get("pins")), _ids(data.get("batches"))
        later = conn.execute("select 1 from events where kind = %s and id > %s and (data->>'company_id')::bigint = %s",
                             (MOVED, mid, company["id"])).fetchone()
        state = conn.execute(
            "select (select count(*) from contacts where id = any(%(ids)s) and category = %(to)s) as moved,"
            " (select count(*) from tasks where id = any(%(off)s) and status = 'snoozed') as off,"
            " (select count(*) from tasks where id = any(%(pins)s) and status = 'open') as pins",
            {"ids": ids, "to": to, "off": off, "pins": pins}).fetchone()
        if later or to not in CATEGORIES or (state["moved"], state["off"], state["pins"]) != (
                len(ids), len(off), len(pins)):
            raise errors.conflict(CHANGED_SINCE)
        back = "bd" if to == "maintenance" else "maintenance"
        conn.execute("update contacts c set category = %s, frequency_per_year = p.freq"
                     " from unnest(%s::bigint[], %s::integer[]) as p(id, freq) where c.id = p.id",
                     (back, ids, [p[1] for p in pairs]))
        conn.execute("update tasks set status = 'open', snoozed_until = null where id = any(%s)", (off,))
        conn.execute("delete from tasks where id = any(%s)", (pins,))
        conn.execute("delete from task_batches b where b.id = any(%s)"
                     " and not exists (select 1 from tasks t where t.batch_id = b.id)", (batches,))
        log_event(conn, UNDONE, actor=me, data={"move_id": mid, "company_id": company["id"], "to": to,
                                                "people": data.get("people")})
    return {"ok": True, "undone": {"id": mid, "company": serialize.company_ref(company["id"], company["name"]),
                                   "to": to, "people": data.get("people")}}
