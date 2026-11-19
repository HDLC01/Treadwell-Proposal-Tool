"""Contacts: GET/POST /api/bd/contacts, GET /api/bd/contacts/duplicates, GET/PATCH /api/bd/contacts/{id},
POST /api/bd/contacts/{id}/confirm and POST /api/bd/contacts/{id}/archive (merge stays in pending.py).

BD's contacts routes, moved under /api/bd/ with the same checks, answers and words. #807 brought one
contact (get, patch, confirm) for This Week; #808 brings the rest with the contact page and Add
contact: the list, the possible-duplicate person check, create and archive.

docs/bd/api-contract.md "Contacts" is the spec; where it is silent this follows BD's mock (api.js
listContacts, findDuplicates, createContact, getContact, patchContact, confirmContact,
archiveContact), as BD did. "api.js X" names a function of that retired mock, frontend/js/api.js in
the BD repository, only to trace a rule back. What this router shares with the companies router (the
duplicate check, finding or making a company, a contact's field checks, making a contact) is in
bd/contacts_service.py, because no BD router imports another.

Who:
    list, duplicates, GET one   any BD role
    POST (create), archive      salesperson, assistant, admin
    PATCH    salesperson, assistant, admin; a manager only the cadence override and a maintenance
             contact's frequency_per_year ("Managers can change only how often to follow up.");
             only the assistant (or an admin) clears a duplicate flag
    confirm  salesperson, assistant, admin
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, Request

from .. import appsettings, auth, bizdate, db, errors, interactions_service, paging, serialize, web
from ..contacts_service import (BD_FREQUENCY_SENTENCE, CATEGORIES, CONTACT_NOT_FOUND, DATE_FIELDS, FIX, NAME_MAX,
                                TEXT_DEFAULT_MAX, TEXT_FIELDS, as_int, check_date, check_tags, check_text,
                                company_spec_ok, create_contact, find_duplicates, resolve_company, tags, too_long,
                                user_exists)
from ..events import log_event
from ..normalize import normalize_company
from ..phone import digits as phone_digits
from ..phone import to_e164

router = web.make_router()

MISSED_CALL_DAYS = 14          # api.js MISSED_CALL_DAYS: an older unanswered call gets no card

BD_CADENCES = appsettings.BD_CADENCES      # weekly | monthly | quarterly
CADENCES = ("never", "behind", "on_track", "complete")

# The cadence rules' sentences (api-contract.md "PATCH /api/bd/contacts/{id}"), and how an event says
# a cadence in words.
MANAGER_SENTENCE = "Managers can change only how often to follow up."
PICK_CADENCE = "Pick weekly, monthly or quarterly."
PICK_FUTURE_DAY = "Pick a day from today on."
NEED_LAST_DAY = "Pick the last day of the override."
NEED_HOW_OFTEN = "Pick how often first."
CADENCE_PHRASE = {"weekly": "every week", "monthly": "every month", "quarterly": "every quarter"}
# What a manager may send: the cadence fields and frequency_per_year (which a BD contact then
# refuses with BD_FREQUENCY_SENTENCE: only a maintenance contact has a number of its own).
MANAGER_KEYS = ("cadence_override", "cadence_override_until", "frequency_per_year")

# How each sort orders the list (api.js listContacts `key`): an empty key goes last, ties by id.
# "C" collation compares like JavaScript's `<` on strings. Only these fixed strings reach the SQL.
SORTS = {
    "name": 'lower(cs.name) collate "C", cs.id',
    "company": 'lower(btrim(cs.company_name)) collate "C", lower(cs.name) collate "C", cs.id',
    "last_live_at": "cs.last_live_at desc nulls last, cs.id",
    "next_due_date": "cs.next_due_date nulls last, cs.id",
}


def _summary_row(conn, contact_id):
    return conn.execute(serialize.CONTACT_SELECT + " where cs.id = %s", (contact_id,)).fetchone()


# ── the list, the duplicate check and create ──────────────────────────────────────────────────
def _flag(params, key: str, fields: dict, allowed=("true", "false")):
    v = params.get(key)
    if v is None or v == "":
        return None
    if v not in allowed:
        fields[key] = "Use " + " or ".join(allowed) + "."
        return None
    return v


@router.get("/api/bd/contacts")
def list_contacts(request: Request, user: dict = Depends(auth.current_user)):
    q = request.query_params
    fields: dict = {}
    where, params = [], []

    archived = _flag(q, "archived", fields)
    where.append("cs.archived_at is not null" if archived == "true" else "cs.archived_at is null")
    category = q.get("category") or None
    if category is not None:
        if category in CATEGORIES:
            where.append("cs.category = %s")
            params.append(category)
        else:
            fields["category"] = "Use bd or maintenance."
    owner = paging.query_int(q, "owner", fields)
    if owner is not None:
        where.append("cs.owner_id = %s")
        params.append(owner)
    for key in ("industry", "lead_source", "stage"):
        value = q.get(key)
        if value:
            where.append("cs." + key + " = %s")
            params.append(value)
    confirmed = _flag(q, "confirmed", fields)
    if confirmed is not None:
        where.append("cs.confirmed = %s")
        params.append(confirmed == "true")
    cadence = q.get("cadence") or None
    if cadence is not None:
        if cadence in CADENCES:
            where.append("cs.cadence_status = %s")
            params.append(cadence)
        else:
            fields["cadence"] = "Use never, behind, on_track or complete."
    company = paging.query_int(q, "company", fields)
    if company is not None:
        where.append("cs.company_id = %s")
        params.append(company)
    if _flag(q, "duplicates", fields) == "true":
        where.append("cs.duplicate_of is not null")
    raw_needle = q.get("q")
    if raw_needle:
        needle = raw_needle.strip().lower()
        hay = ("lower(coalesce(cs.name, '') || ' ' || coalesce(cs.company_name, '') || ' ' ||"
               " coalesce(cs.email, '') || ' ' || coalesce(cs.title, '') || ' ' || coalesce(cs.city, ''))")
        test = "strpos(" + hay + ", %s) > 0 or strpos(cs.company_normalized_name, %s) > 0"
        params += [needle, normalize_company(needle)]
        nums = phone_digits(needle)
        if len(nums) >= 3:
            test += " or strpos(regexp_replace(coalesce(cs.phone, ''), '[^0-9]', '', 'g'), %s) > 0"
            params.append(nums)
        where.append("(" + test + ")")
    sort = q.get("sort") or "company"
    if sort not in SORTS:
        fields["sort"] = "Use name, company, last_live_at or next_due_date."
    limit, offset = paging.page_params(q, fields)
    if fields:
        if list(fields) == ["sort"]:
            raise errors.bad_request("Unknown sort.", fields)
        raise errors.bad_request(FIX, fields)

    sql_where = " and ".join(where)
    with db.connect() as conn:
        total = conn.execute("select count(*) as n from contacts_summary cs where " + sql_where,
                             params).fetchone()["n"]
        rows = conn.execute(serialize.CONTACT_SELECT + " where " + sql_where + " order by " + SORTS[sort]
                            + " limit %s offset %s", params + [limit, offset]).fetchall()
    return {"ok": True, "total": int(total), "items": [serialize.contact(r) for r in rows]}


# Declared before /api/bd/contacts/{id}, so "duplicates" is never read as an id.
@router.get("/api/bd/contacts/duplicates")
def contact_duplicates(request: Request, user: dict = Depends(auth.current_user)):
    """Add contact's "this person may already exist" check: company and/or email and/or phone,
    and `except` (the contact being edited)."""
    q = request.query_params
    fields: dict = {}
    except_id = paging.query_int(q, "except", fields)
    if fields:
        raise errors.bad_request(FIX, fields)
    with db.connect() as conn:
        items = find_duplicates(conn, q.get("company"), q.get("email"), q.get("phone"), except_id)
    return {"ok": True, "items": items}


@router.post("/api/bd/contacts", status_code=201)
def post_contact(body: Any = Body(None), user: dict = Depends(auth.require_role("salesperson", "assistant"))):
    body = paging.json_object(body)
    with db.connect() as conn:
        contact, dups = create_contact(conn, user, body, source="manual")
    return {"ok": True, "contact": contact, "possible_duplicates": dups}


# ── one contact ───────────────────────────────────────────────────────────────────────────────
def _open_task(conn, contact_id):
    """api.js currentTask: the contact's latest task on this week's lists (any owner), or None.
    The same rule (interactions_service.current_task) that logging a call uses to close the task,
    so the contact page and the logger can never disagree about which task is "this week's"."""
    from psycopg import sql

    row = interactions_service.current_task(conn, contact_id)
    if row is None:
        return None
    return serialize.fetch_tasks(conn, sql.SQL("t.id = %s"), (row["id"],), "id", 1)[0]


def _pending_recommendation(conn, contact_id):
    row = conn.execute(serialize.RECOMMENDATION_SELECT + " where r.contact_id = %s and r.status = 'pending'"
                       " order by r.created_at desc, r.id limit 1", (contact_id,)).fetchone()
    return serialize.recommendation(row) if row else None


def _missed_call(conn, summary_row):
    """api.js getContact: only the latest voicemail / no-answer call counts. It gets the card when
    nobody has talked live since, it is at most 14 Central days old, and nobody has sent a
    follow-up or said "Nothing" for it. The WHERE is interactions_service.is_missed in SQL."""
    i = conn.execute(
        "select id, occurred_at, followup_status from interactions where contact_id = %s"
        " and (kind = 'voicemail' or (kind = 'call' and outcome = 'no_answer'))"
        " order by occurred_at desc, id limit 1", (summary_row["id"],)).fetchone()
    if i is None:
        return None
    live = summary_row.get("last_live_at")
    if live is not None and live > i["occurred_at"]:
        return None
    if bizdate.days_between(i["occurred_at"], bizdate.today_central()) > MISSED_CALL_DAYS:
        return None
    if i["followup_status"]:
        return None
    return {"interaction_id": i["id"], "occurred_at": serialize.ts(i["occurred_at"]), "followup_sent": False}


@router.get("/api/bd/contacts/{id}")
def get_contact(id: str, user: dict = Depends(auth.current_user)):
    cid = paging.path_id(id, CONTACT_NOT_FOUND)
    with db.connect() as conn:
        row = _summary_row(conn, cid)
        if row is None:
            raise errors.not_found(CONTACT_NOT_FOUND)
        return {"ok": True, "contact": serialize.contact(row), "open_task": _open_task(conn, cid),
                "pending_recommendation": _pending_recommendation(conn, cid),
                "missed_call": _missed_call(conn, row)}


EDITABLE = ("name", "title", "email", "phone", "city", "industry", "lead_source", "stage", "category",
            "account_type", "frequency_per_year", "importance", "next_step", "next_step_date",
            "promised_date", "tags", "notes")


def _override_after(body: dict, row) -> tuple:
    """(cadence_override, cadence_override_until) as this PATCH leaves them, still as sent (a word
    or None; a date string or None) or as stored (a date). `{"cadence_override": null}` alone
    clears both; a key left out keeps what is stored."""
    has_word, has_day = "cadence_override" in body, "cadence_override_until" in body
    # "" is not a way to clear: only null clears, so "" fails the checks below like any other bad value.
    word = body["cadence_override"] if has_word else row["cadence_override"]
    day = body["cadence_override_until"] if has_day else row["cadence_override_until"]
    if has_word and word is None and not has_day:
        day = None
    return word, day


def _validate_cadence(body: dict, row, fields: dict) -> None:
    """The override rules: a word from the three, a last day that is today or later, both or
    neither."""
    if "cadence_override" not in body and "cadence_override_until" not in body:
        return
    word, day = _override_after(body, row)
    # One sentence at a time, in this order (api.js patchContact reads it the same way).
    if word is not None and (not isinstance(word, str) or word not in BD_CADENCES):
        fields["cadence_override"] = PICK_CADENCE
    elif day is not None and "cadence_override_until" in body and bizdate.exact_date(day) is None:
        fields["cadence_override_until"] = "Use a date (YYYY-MM-DD)."
    elif word is not None and day is None:
        fields["cadence_override_until"] = NEED_LAST_DAY
    elif word is None and day is not None:
        fields["cadence_override"] = NEED_HOW_OFTEN
    elif day is not None and bizdate.parse_date(day) < bizdate.today_central():
        # Also catches a stale stored day kept by a PATCH that sets only the word.
        fields["cadence_override_until"] = PICK_FUTURE_DAY


def _day_words(d) -> str:
    """"Sat, Jan 31": a date for an event line (no year, no zero padding)."""
    d = bizdate.parse_date(d)
    return d.strftime("%a, %b ") + str(d.day)


def _validate_patch(body: dict, user: dict, row=None) -> dict:
    fields = {}
    if "name" in body and (not isinstance(body["name"], str) or not body["name"].strip()):
        fields["name"] = "A contact needs a name."
    elif "name" in body and len(body["name"].strip()) > NAME_MAX:
        fields["name"] = too_long(NAME_MAX)
    if "category" in body and body["category"] not in CATEGORIES:
        fields["category"] = "Use bd or maintenance."
    # The category this PATCH leaves the contact in decides whether it has a number of its own.
    cat = body["category"] if body.get("category") in CATEGORIES else (row or {}).get("category", "bd")
    if "frequency_per_year" in body:
        f = as_int(body["frequency_per_year"])
        if cat == "bd":
            fields["frequency_per_year"] = BD_FREQUENCY_SENTENCE
        elif f is None or not 1 <= f <= 52:
            fields["frequency_per_year"] = "Use a number from 1 to 52."
    if row is not None:
        _validate_cadence(body, row, fields)
    if "duplicate_of" in body:
        if body["duplicate_of"] is not None:
            fields["duplicate_of"] = "Send null to clear the flag."
        elif user.get("role") == "salesperson":
            raise errors.forbidden("Only the assistant can clear a duplicate flag.")
    for key in TEXT_FIELDS:
        check_text(body, key, fields)
    if "lead_source" in body and "lead_source" not in fields and not (body["lead_source"] or "").strip():
        fields["lead_source"] = "Pick a lead source."
    for key in DATE_FIELDS:
        check_date(body, key, fields)
    check_tags(body, fields)
    if "importance" in body and as_int(body["importance"]) not in (1, 2, 3):
        fields["importance"] = "Use 1, 2 or 3."
    for key in ("owner_id", "co_owner_id"):
        if key in body and body[key] is not None and as_int(body[key]) is None:
            fields[key] = "Pick a user."
    if "company" in body and not company_spec_ok(body["company"]):
        fields["company"] = "Pick or type a company."
    elif isinstance((body.get("company") or {}).get("name"), str) and len(body["company"]["name"].strip()) > NAME_MAX:
        fields["company"] = too_long(NAME_MAX)
    return fields


@router.patch("/api/bd/contacts/{id}")
def patch_contact(id: str, body: Any = Body(None), user: dict = Depends(auth.current_user)):
    cid = paging.path_id(id, CONTACT_NOT_FOUND)
    body = paging.json_object(body)
    with db.connect() as conn:
        row = _summary_row(conn, cid)
        if row is None:
            raise errors.not_found(CONTACT_NOT_FOUND)
        if user.get("role") == "manager":
            if any(k not in MANAGER_KEYS for k in body):
                raise errors.forbidden(MANAGER_SENTENCE)
        elif not auth.has_role(user, "salesperson", "assistant"):
            raise errors.forbidden()
        fields = _validate_patch(body, user, row)
        if fields:
            raise errors.bad_request(FIX, fields)

        # Owners first: a bad one must fail before anything is written.
        owner = None
        if body.get("owner_id") is not None:
            owner = user_exists(conn, as_int(body["owner_id"]))
            if owner is None:
                raise errors.bad_request("That owner does not exist.", {"owner_id": "Pick a user."})
        if body.get("co_owner_id") is not None and user_exists(conn, as_int(body["co_owner_id"])) is None:
            raise errors.bad_request("That co-owner does not exist.", {"co_owner_id": "Pick a user."})

        # The duplicate hint is re-checked for the fields that change, as an add checks them.
        check_company = None
        check_email = None
        if "email" in body and (body["email"] or "").strip().lower() != (row["email"] or "").lower():
            check_email = body["email"]
        check_phone = body["phone"] if "phone" in body and to_e164(body["phone"]) != row["phone_e164"] else None

        sets, params = [], []
        if body.get("company"):
            co = resolve_company(conn, body["company"], body)
            if co["id"] != row["company_id"]:
                check_company = co["name"]
                sets.append("company_id = %s")
                params.append(co["id"])

        new_freq = as_int(body["frequency_per_year"]) if "frequency_per_year" in body else None
        # The number a person typed is the stored column (a BD contact's shown number is derived).
        old_freq = row["stored_frequency_per_year"]
        if new_freq is not None and new_freq != old_freq:
            log_event(conn, "frequency_changed", actor=user, contact_id=cid,
                      detail="%d a year to %d a year" % (old_freq, new_freq),
                      data={"from": old_freq, "to": new_freq})

        if "cadence_override" in body or "cadence_override_until" in body:
            word, day = _override_after(body, row)
            day = bizdate.parse_date(day) if day is not None else None
            old = (row["cadence_override"], row["cadence_override_until"])
            if (word, day) != old:
                global_word = appsettings.load(conn).get("bd_cadence") or ""
                if word is None:
                    detail = "Back to the BD cadence, " + CADENCE_PHRASE.get(global_word, "every quarter")
                else:
                    was = CADENCE_PHRASE.get(row.get("cadence") or global_word, "every quarter")
                    detail = "%s to %s until %s" % (was[0].upper() + was[1:], CADENCE_PHRASE[word], _day_words(day))
                log_event(conn, "frequency_changed", actor=user, contact_id=cid, detail=detail,
                          data={"from": {"cadence_override": old[0], "cadence_override_until": bizdate.iso_date(old[1])},
                                "to": {"cadence_override": word, "cadence_override_until": bizdate.iso_date(day)}})
            sets += ["cadence_override = %s", "cadence_override_until = %s"]
            params += [word, day]

        for key in EDITABLE:
            if key not in body:
                continue
            value = body[key]
            if key in ("frequency_per_year", "importance"):
                value = as_int(value)
            elif key == "name":
                value = value.strip()
            elif key == "notes":
                value = value or ""
            elif key == "tags":
                value = tags(value)
            elif key in DATE_FIELDS:
                value = value or None
            sets.append(key + " = %s")
            params.append(value)

        if "category" in body and body["category"] != row["category"] and "frequency_per_year" not in body:
            # A flip with no number of its own: the stored number becomes the new category's default
            # (a BD contact's 52 or 12 must not become a maintenance contact's target; the BD number
            # is only a record, as at creation).
            settings = appsettings.load(conn)
            if body["category"] == "maintenance":
                flip_freq = (settings.get("default_frequency") or {}).get("maintenance") or 3
            else:
                flip_freq = appsettings.CADENCE_FREQ.get(settings.get("bd_cadence") or "", 4)
            sets.append("frequency_per_year = %s")
            params.append(int(flip_freq))

        if "owner_id" in body:
            new_owner = owner["id"] if owner else None
            if new_owner != row["owner_id"]:
                log_event(conn, "owner_changed", actor=user, contact_id=cid,
                          detail="Now " + (owner["name"] if owner else "nobody"),
                          data={"from": row["owner_id"], "to": new_owner})
                _release_pinned_tasks(conn, cid, new_owner)
            sets.append("owner_id = %s")
            params.append(new_owner)
        if "co_owner_id" in body:
            # Naming a co-owner (or nobody) replaces a workbook co-owner who had no login. A save
            # that leaves co_owner_id out keeps that name (the Phase 1 "Troy/Greg" blocker).
            sets += ["co_owner_id = %s", "co_owner_name = null"]
            params.append(as_int(body["co_owner_id"]) if body["co_owner_id"] is not None else None)

        dups = find_duplicates(conn, check_company, check_email, check_phone, cid) \
            if (check_company or check_email or check_phone) else []
        flag_id, flag_name = row["duplicate_of"], row["duplicate_name"]
        newly_flagged = bool(dups) and flag_id is None
        if newly_flagged:
            flag_id, flag_name = dups[0]["contact_id"], dups[0]["name"]
        if "duplicate_of" in body:
            # "Not a duplicate": whatever the flag is now (even one this edit just found) goes.
            if flag_id is not None:
                log_event(conn, "duplicate_cleared", actor=user, contact_id=cid,
                          detail="Was flagged with " + (flag_name or "another contact"),
                          data={"duplicate_of": flag_id})
                sets += ["duplicate_of = null", "duplicate_reason = null"]
        elif newly_flagged:
            sets += ["duplicate_of = %s", "duplicate_reason = %s"]
            params += [dups[0]["contact_id"], dups[0]["reason"]]

        if sets:
            conn.execute("update contacts set " + ", ".join(sets) + " where id = %s", params + [cid])
        contact = serialize.fetch_contact(conn, cid)
    return {"ok": True, "contact": contact, "possible_duplicates": dups}


def _release_pinned_tasks(conn, contact_id, new_owner_id) -> None:
    """A contact changed hands: the previous owner's open maintenance tasks for it (this week's list
    and later ones) are snoozed to the following Monday, as the weekly rollover does, so the pin sits
    on exactly one list. They are not the old owner's to do any more and cannot be taken off by hand.
    The new owner gets the pin at the next Friday build, or from Give Me 10 More at once (their
    ranking sees a due maintenance contact that is on none of their lists)."""
    conn.execute(
        "update tasks t set status = 'snoozed', snoozed_until = b.week_start + 7, closed_by_archive = false"
        " from task_batches b where b.id = t.batch_id and t.contact_id = %s and t.kind = 'maintenance'"
        " and t.status = 'open' and b.week_start >= %s and b.owner_id is distinct from %s",
        (contact_id, bizdate.week_start(bizdate.today_central()), new_owner_id))


@router.post("/api/bd/contacts/{id}/confirm")
def confirm_contact(id: str, body: Any = Body(None),
                    user: dict = Depends(auth.require_role("salesperson", "assistant"))):
    body = paging.json_object(body)
    if "confirmed" in body and body["confirmed"] is not None and not isinstance(body["confirmed"], bool):
        raise errors.bad_request(FIX, {"confirmed": "Use true or false."})
    cid = paging.path_id(id, CONTACT_NOT_FOUND)
    yes = body.get("confirmed") is not False
    with db.connect() as conn:
        row = conn.execute("select id, confirmed from contacts where id = %s", (cid,)).fetchone()
        if row is None:
            raise errors.not_found(CONTACT_NOT_FOUND)
        if row["confirmed"] != yes:
            conn.execute("update contacts set confirmed = %s where id = %s", (yes, cid))
            log_event(conn, "confirmed" if yes else "unconfirmed", actor=user, contact_id=cid)
    return {"ok": True, "contact": {"id": cid, "confirmed": yes}}


@router.post("/api/bd/contacts/{id}/archive")
def archive_contact(id: str, body: Any = Body(None),
                    user: dict = Depends(auth.require_role("salesperson", "assistant"))):
    """Off every list and batch (the history is kept); {"archived": false} restores it and reopens
    what the archive closed on this week's list or a later one."""
    body = paging.json_object(body)
    fields = {}
    if "archived" in body and body["archived"] is not None and not isinstance(body["archived"], bool):
        fields["archived"] = "Use true or false."
    if body.get("reason") is not None and not isinstance(body["reason"], str):
        fields["reason"] = "Use text."
    elif isinstance(body.get("reason"), str) and len(body["reason"].strip()) > TEXT_DEFAULT_MAX:
        fields["reason"] = too_long(TEXT_DEFAULT_MAX)
    if fields:
        raise errors.bad_request(FIX, fields)
    cid = paging.path_id(id, CONTACT_NOT_FOUND)
    on = body.get("archived") is not False
    reason = (body.get("reason") or "").strip() or None
    with db.connect() as conn:
        if conn.execute("select id from contacts where id = %s", (cid,)).fetchone() is None:
            raise errors.not_found(CONTACT_NOT_FOUND)
        if on:
            row = conn.execute("update contacts set archived_at = bd_now() where id = %s returning archived_at",
                               (cid,)).fetchone()
            # An open task on any weekly list closes; the flag remembers the archive closed it.
            conn.execute("update tasks set status = 'snoozed', closed_by_archive = true"
                         " where contact_id = %s and status = 'open'", (cid,))
        else:
            row = conn.execute("update contacts set archived_at = null where id = %s returning archived_at",
                               (cid,)).fetchone()
            # Undo the archive's own closures on THIS week's lists and on later ones (next week's
            # Friday batch exists from Friday 16:00); an earlier week stays closed.
            conn.execute(
                "update tasks t set status = 'open', snoozed_until = null from task_batches b"
                " where b.id = t.batch_id and t.contact_id = %s and t.closed_by_archive"
                " and t.status = 'snoozed' and b.week_start >= %s", (cid, bizdate.week_start()))
            conn.execute("update tasks set closed_by_archive = false where contact_id = %s and closed_by_archive",
                         (cid,))
        log_event(conn, "archived" if on else "restored", actor=user, contact_id=cid, detail=reason)
    return {"ok": True, "contact": {"id": cid, "archived_at": serialize.ts(row["archived_at"])}}
