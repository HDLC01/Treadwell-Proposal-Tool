"""Likely duplicate BD accounts: the list, Merge, Undo and Keep separate (#811, #802 Q21, Q33, Q36).

    GET  /api/bd/contacts/accounts/duplicates          likely pairs, with hints, and the recent merges
    POST /api/bd/contacts/accounts/{id}/merge          {"into": survivor id, "name_from": either id}
    POST /api/bd/contacts/accounts/merges/{id}/undo    puts back exactly what that one merge changed
    POST /api/bd/contacts/accounts/duplicates/keep     {"accounts": [id, id]}: the pair is never listed again

WHO. The assistant, the BD admin and the super admin (Q21, Q36), `can.merge_companies`; everyone else
is 403 on all four. Nothing merges on its own: no worker, startup hook or read calls a merge
(tests/test_bd_account_merge.py runs the Friday batch and every read and finds nothing merged).

THE RULE: bd/account_pairs_service.py (the cut-over command's duplicates list shares it). The paths
sit under /api/bd/contacts/, so the tool's audit log records each read (the hints carry phone
numbers), by path alone.

MERGE (a soft merge). Both companies are locked first, in id order (contacts_service.lock_companies;
Add contact, a contact's company change and the import read an account FOR SHARE, so they wait for a
merge in flight and then follow it). EVERY person at the merged-away
account moves to the survivor (BD and maintenance, archived too, because the account is hidden after
and anyone left there would vanish with it). Each keeps their own owner (Q33); their history, tasks
and recommendations point at the person, so they follow. The survivor takes the name the merger
picked, from either account (`name_from`); which account survives (`into`) is a separate choice. The
other account is not deleted: merged_into / merged_at / merged_by mark it, and the account list,
search and the type-ahead never show it, nor does Add contact or the import ever put a person on it
(bd/contacts_service.live_company). One event, `company_merged`, no contact, ids and account names
only: {company_id, into, name_from, name_before, name_after, contacts: [ids], people}. One transaction.
The answer and each row of Recently merged are one shape, serialize.account_merge. Recently merged
leaves out a merge already undone and one whose survivor was merged on since (Undo would refuse it).

UNDO has no time limit ("every merge can be undone"), and anyone who may merge may undo it. It moves
back exactly the people that merge moved, restores the survivor's name when the merge changed it, and
clears the mark; people added to the survivor since stay where they are. It is refused, changing
nothing, when it can no longer put back exactly what was there: the merge was undone already (which
is also the case when the account was merged again since), a moved person is no longer at the
survivor (they moved company, or the survivor was merged on with them), the survivor was renamed after
the merge renamed it, or the account's mark is no longer this merge's. One event, `company_merge_undone`.

The words differ on purpose, as in #810: the page and GLOSSARY.md say "BD account"; the table, the
event kinds and the can key say "company", the name the table keeps.
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, Path, Request

from .. import account_pairs_service as pairs
from .. import auth, db, errors, normalize, paging, serialize, web
from .. import contacts_service as cs
from ..contacts_service import ALREADY_MERGED, COMPANY_NOT_FOUND, FIX
from ..events import log_event

router = web.make_router()

MERGE_ROLES = ("assistant",)        # and admins (Q21, Q36); require_role adds them
MERGED = cs.MERGED_EVENT            # "company_merged"; contacts_service reads it too
UNDONE = cs.UNDONE_EVENT            # "company_merge_undone"
MERGES_SHOWN = 10                   # the "Recently merged" list's length

MERGE_NOT_FOUND = "That merge does not exist."
INTO_MERGED = "That account was merged into another, so nothing can merge into it."
ALREADY_UNDONE = "This merge is already undone."
CHANGED_SINCE = "Something changed since this merge, so it can't be undone."
PICK_INTO = "Pick the account to merge into."
PICK_OTHER = "Pick another account."
PICK_NAME = "Pick one of the two names."
PICK_TWO = "Pick two different accounts."


def _body_id(value):
    """A JSON number naming a row, read as Add contact's {"id"} is (contacts_service.company_by_id):
    6 or 6.0; else None (text, bools, fractions)."""
    return paging.as_id(cs.as_int(value))


def _people(conn, company_id) -> int:
    return conn.execute("select count(*) as n from contacts where company_id = %s and archived_at is null",
                        (company_id,)).fetchone()["n"]


# ── the list (the rule itself: bd/account_pairs_service.py) ─────────────────────────────────────
def _recent_merges(conn) -> list:
    """The latest merges Undo may still take: not undone, the account still marked merged into the
    survivor (a cut-over copy puts no mark back on an account that gained people in the old app,
    #812), and the survivor not merged on since."""
    rows = conn.execute(
        "select e.id, e.at, e.data, u.id as by_id, u.name as by_name, lo.name as account_name, su.name as into_name,"
        " (select count(*) from contacts c where c.company_id = su.id and c.archived_at is null)::integer"
        "   as people_count"
        " from events e left join users u on u.id = e.actor_id"
        " join companies lo on lo.id = (e.data->>'company_id')::bigint"
        " join companies su on su.id = (e.data->>'into')::bigint"
        " where e.kind = %s and lo.merged_into = su.id and su.merged_into is null"
        " and not exists (select 1 from events x where x.kind = %s and (x.data->>'merge_id')::bigint = e.id)"
        " order by e.id desc limit %s", (MERGED, UNDONE, MERGES_SHOWN)).fetchall()
    return [serialize.account_merge(
        r["id"], serialize.company_ref(r["data"]["company_id"], r["account_name"]),
        serialize.company_ref(r["data"]["into"], r["into_name"]), r["data"].get("name_before"),
        r["data"].get("people"), r["people_count"], r["at"], serialize.user_ref(r["by_id"], r["by_name"]))
        for r in rows]


@router.get("/api/bd/contacts/accounts/duplicates")
def list_duplicates(request: Request, me: dict = Depends(auth.require_role(*MERGE_ROLES))):
    limit, offset = paging.page_or_400(request.query_params)
    with db.connect() as conn:
        found = pairs.likely_pairs(conn)
        page = found[offset:offset + limit]
        hints = pairs.hints(conn, sorted({p[1]["id"] for p in page} | {p[2]["id"] for p in page}))
        items = [serialize.account_pair(a, b, *pairs.shared(hints, a["id"], b["id"])) for _key, a, b in page]
        merges = _recent_merges(conn)
    return {"ok": True, "total": len(found), "items": items, "merges": merges}


# ── merge ────────────────────────────────────────────────────────────────────────────────────
@router.post("/api/bd/contacts/accounts/{id}/merge")
def merge_account(company_id: str = Path(alias="id"), body: Any = Body(None),
                  me: dict = Depends(auth.require_role(*MERGE_ROLES))):
    loser_id = paging.path_id(company_id, COMPANY_NOT_FOUND)
    body = paging.json_object(body)
    fields: dict = {}
    into_id = _body_id(body.get("into"))
    if into_id is None:
        fields["into"] = PICK_INTO
    elif into_id == loser_id:
        fields["into"] = PICK_OTHER
    name_from = _body_id(body.get("name_from"))
    if name_from is None or name_from not in (loser_id, into_id):
        fields["name_from"] = PICK_NAME
    if fields:
        raise errors.bad_request(FIX, fields)
    with db.connect() as conn:
        rows = cs.lock_companies(conn, [loser_id, into_id])
        loser, into = rows[loser_id], rows[into_id]
        if loser["merged_into"] is not None:
            raise errors.conflict(ALREADY_MERGED)
        if into["merged_into"] is not None:
            raise errors.conflict(INTO_MERGED)
        moved = conn.execute("update contacts set company_id = %s where company_id = %s returning id, archived_at",
                             (into_id, loser_id)).fetchall()
        name_after = rows[name_from]["name"]
        if name_after != into["name"]:
            conn.execute("update companies set name = %s, normalized_name = %s where id = %s",
                         (name_after, normalize.normalize_company(name_after), into_id))
        conn.execute("update companies set merged_into = %s, merged_at = bd_now(), merged_by = %s where id = %s",
                     (into_id, me["id"], loser_id))
        people = sum(1 for r in moved if r["archived_at"] is None)
        event_id = log_event(conn, MERGED, actor=me, data={
            "company_id": loser_id, "into": into_id, "name_from": name_from, "name_before": into["name"],
            "name_after": name_after, "contacts": sorted(r["id"] for r in moved), "people": people})
        at = conn.execute("select at from events where id = %s", (event_id,)).fetchone()["at"]
        people_count = _people(conn, into_id)
    return {"ok": True, "merge": serialize.account_merge(
        event_id, serialize.company_ref(loser_id, loser["name"]), serialize.company_ref(into_id, name_after),
        into["name"], people, people_count, at, serialize.user_ref(me["id"], me.get("name")))}


# ── undo ─────────────────────────────────────────────────────────────────────────────────────
@router.post("/api/bd/contacts/accounts/merges/{id}/undo")
def undo_merge(merge_id: str = Path(alias="id"), body: Any = Body(None),
               me: dict = Depends(auth.require_role(*MERGE_ROLES))):
    mid = paging.path_id(merge_id, MERGE_NOT_FOUND)
    paging.json_object(body)
    with db.connect() as conn:
        ev = conn.execute("select id, at, data from events where id = %s and kind = %s", (mid, MERGED)).fetchone()
        data = ev["data"] if ev is not None and isinstance(ev["data"], dict) else None
        loser_id, into_id = (_body_id(data.get("company_id")), _body_id(data.get("into"))) if data else (None, None)
        if loser_id is None or into_id is None:
            raise errors.not_found(MERGE_NOT_FOUND)
        rows = cs.lock_companies(conn, [loser_id, into_id])
        loser, into = rows[loser_id], rows[into_id]
        if conn.execute("select 1 from events where kind = %s and (data->>'merge_id')::bigint = %s",
                        (UNDONE, mid)).fetchone():
            raise errors.conflict(ALREADY_UNDONE)
        ids = [int(i) for i in data.get("contacts") or [] if _body_id(i) is not None]
        # Lock the people it moved before looking at them, so a company change at the same moment is
        # either seen here or waits until Undo is done.
        at_survivor = conn.execute("select count(*) as n from (select id from contacts where id = any(%s)"
                                   " and company_id = %s order by id for update) x", (ids, into_id)).fetchone()["n"]
        renamed = data.get("name_after") != data.get("name_before")
        if (loser["merged_into"] != into_id or loser["merged_at"] != ev["at"] or at_survivor != len(ids)
                or (renamed and into["name"] != data.get("name_after"))):
            raise errors.conflict(CHANGED_SINCE)
        conn.execute("update contacts set company_id = %s where id = any(%s) and company_id = %s",
                     (loser_id, ids, into_id))
        name = into["name"]
        if renamed:
            name = str(data.get("name_before"))
            conn.execute("update companies set name = %s, normalized_name = %s where id = %s",
                         (name, normalize.normalize_company(name), into_id))
        conn.execute("update companies set merged_into = null, merged_at = null, merged_by = null where id = %s",
                     (loser_id,))
        log_event(conn, UNDONE, actor=me, data={"merge_id": mid, "company_id": loser_id, "into": into_id,
                                                "people": data.get("people")})
    return {"ok": True, "undone": serialize.merge_undone(mid, serialize.company_ref(loser_id, loser["name"]),
                                                         serialize.company_ref(into_id, name), data.get("people"))}


# ── keep separate ────────────────────────────────────────────────────────────────────────────
@router.post("/api/bd/contacts/accounts/duplicates/keep")
def keep_separate(body: Any = Body(None), me: dict = Depends(auth.require_role(*MERGE_ROLES))):
    body = paging.json_object(body)
    given = body.get("accounts")
    ids = [_body_id(v) for v in given] if isinstance(given, list) else []
    if len(ids) != 2 or None in ids or ids[0] == ids[1]:
        raise errors.bad_request(FIX, {"accounts": PICK_TWO})
    a, b = sorted(ids)
    with db.connect() as conn:
        rows = cs.lock_companies(conn, [a, b])
        if rows[a]["merged_into"] is not None or rows[b]["merged_into"] is not None:
            raise errors.conflict(ALREADY_MERGED)
        conn.execute("insert into account_pairs_kept (account_a, account_b, decided_by) values (%s, %s, %s)"
                     " on conflict (account_a, account_b) do nothing", (a, b, me["id"]))
        kept = conn.execute("select k.decided_at, u.id as by_id, u.name as by_name from account_pairs_kept k"
                            " join users u on u.id = k.decided_by where k.account_a = %s and k.account_b = %s",
                            (a, b)).fetchone()
    return {"ok": True, "kept": serialize.kept_pair(
        serialize.company_ref(a, rows[a]["name"]), serialize.company_ref(b, rows[b]["name"]),
        serialize.user_ref(kept["by_id"], kept["by_name"]), kept["decided_at"])}
