"""BD's Admin: the people, the settings, the manual weekly run, the phone system, the unmatched calls.

    GET   /api/bd/admin/users                           admin
    POST  /api/bd/admin/users                           admin (super_admin to add an admin)
    PATCH /api/bd/admin/users/{id}                      admin (super_admin to change an admin)
    PUT   /api/bd/admin/settings                        admin
    POST  /api/bd/admin/weekly/run                      admin (Run Friday batch now, #807)
    GET   /api/bd/admin/telephony                       admin
    GET   /api/bd/admin/unmatched-calls                 assistant, admin
    POST  /api/bd/admin/unmatched-calls/{id}/attach     assistant, admin
    POST  /api/bd/admin/unmatched-calls/{id}/dismiss    assistant, admin

BD's routers/admin.py, moved under /api/bd/ (#807 the weekly run, #809 the rest) with the same checks,
answers and words. docs/bd/api-contract.md "Admin" is the spec. The import routes are
bd/routers/imports.py.

BD'S PEOPLE TABLE IS NOT THE PROPOSAL TOOL'S (#802). These routes read and write bd.users only: a BD
login and its BD role. They never touch the tool's profiles, roles, sidebar (nav) policy or Special
permissions, and the tool's Admin page never touches bd.users. A proposal-tool admin has no BD role
until a BD admin adds them here like anyone else (Q30). The address must be one the tool's sign-in
lets in (its allowed domain, read through bd/auth.py's sign_in_domain, the one seam to the tool's
gate): BD's own allowed-domain setting was not carried, because the tool's gate does that check.

The rules worth knowing before changing anything here:
  * Only a super admin adds an admin or super admin, changes a user who is one, or makes someone
    one (an admin a plain admin made could never be changed again). Nobody changes their OWN role
    or sign-in (`active`); their own name is fine. Both rules are bd/auth.py's refuse_new_login and
    refuse_login_change (Q29).
  * PUT /api/bd/admin/settings merges `weekly` and `default_frequency` key by key into what is
    stored (`bd_cadence` is one of weekly | monthly | quarterly; `default_frequency.bd` is retired
    and ignored), checks the WHOLE result, and keeps nothing when anything is wrong. Read-only keys
    (the counting rule and the clock) are ignored. GET /api/bd/settings reads the same store through
    appsettings.load, and so does the Friday worker (weekly.run_due), so a saved run day or hour moves
    the next Friday batch at once.
  * The telephony status reads only WHETHER BD_TELEPHONY_PROVIDER, BD_QUO_API_KEY and
    BD_QUO_WEBHOOK_SECRET are set, the latest integration event's time, the provider's count of
    integration events (`events`, added in #809 for its criterion; BD answered only the time) and
    the count of open unmatched calls. It never answers a key or a secret.
  * Attaching an unmatched call creates the interaction with the outcome the assistant gives, or,
    without one, "answered" only from ANSWER_MIN_SECONDS (a 40-second voicemail must never count
    as a live conversation). The interaction goes in through interactions_service.log_interaction
    (one place for the interaction rules) WITHOUT closing this week's task or suggesting a next
    step. counts_as_touch is a generated column (the counting rule is the database's), and the
    contact's derived fields (last live, cadence, ...) come from the contacts_summary view.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from fastapi import Body, Depends, Path, Query, Request

from .. import appsettings, auth, bizdate, config, db, errors, interactions_service, serialize, web, weekly
from ..auth import ROLES, name_of_email, refuse_login_change, refuse_new_login, require_role
from ..events import log_event
from ..paging import as_id, json_object, page_or_400, path_id
from ..phone import display, last10

router = web.make_router()

ADMIN_ONLY = require_role()                    # admins and super admins
ASSISTANT = require_role("assistant")          # the assistant's part of the Admin page, + admins

ANSWER_MIN_SECONDS = 60
ATTACH_OUTCOMES = ("answered", "voicemail", "no_answer")
UNMATCHED_STATUSES = ("open", "attached", "dismissed", "all")
# The weekly run builds NEXT week's list and closes this week's open tasks, so only the end of
# the week may hold it (weekly.ALLOWED_RUN_DAYS; the Admin page's day picker).
RUN_DAYS = weekly.ALLOWED_RUN_DAYS
WEEKLY_KEYS = ("new_count", "followup_count", "run_day", "run_hour", "enabled")
# default_frequency.bd is retired (the BD cadence is settings.bd_cadence): a client may still send it,
# and it is ignored.
FREQUENCY_KEYS = ("maintenance",)

USER_COLUMNS = "id, email, name, role, active, last_seen_at"
NAME_MAX = 120
EMAIL_MAX = 254                                # the longest address mail allows (RFC 5321)
USER_NOT_FOUND = "That user does not exist."
CALL_NOT_FOUND = "That call does not exist."


def _email_ok(email: str, domain: str) -> bool:
    return bool(domain) and re.fullmatch(r"[^@\s]+@" + re.escape(domain), email) is not None


def _fail_fields(fields: dict, messages: dict | None = None, default: str = "Some fields need fixing."):
    """400 with `fields`; one field uses its own headline (messages[field], else its sentence)."""
    if not fields:
        return
    if len(fields) == 1:
        key = next(iter(fields))
        raise errors.bad_request((messages or {}).get(key, default), fields)
    raise errors.bad_request(default, fields)


# ── the people (BD logins) ───────────────────────────────────────────────────────────────────
@router.get("/api/bd/admin/users")
def list_users(request: Request, user: dict = Depends(ADMIN_ONLY)):
    """Every BD login, turned-off ones too (the page turns sign-ins back on from here). Paged by
    limit/offset like every list; `total` counts them all."""
    limit, offset = page_or_400(request.query_params)
    with db.connect() as conn:
        total = conn.execute("select count(*)::integer as n from users").fetchone()["n"]
        rows = conn.execute("select " + USER_COLUMNS + " from users order by id limit %s offset %s",
                            (limit, offset)).fetchall()
    return {"ok": True, "items": [serialize.user(r) for r in rows], "total": total}


@router.post("/api/bd/admin/users")
def create_user(body: Any = Body(None), me: dict = Depends(ADMIN_ONLY)):
    body = json_object(body)
    raw_email = body.get("email")
    email = raw_email.strip().lower() if isinstance(raw_email, str) else ""
    role = body.get("role")
    raw_name = body.get("name")
    domain = auth.sign_in_domain()
    fields = {}
    if len(email) > EMAIL_MAX:
        fields["email"] = "Use at most %d characters." % EMAIL_MAX
    elif not _email_ok(email, domain):
        fields["email"] = "Use a @%s address." % domain
    if role not in ROLES:
        fields["role"] = "Pick a role."
    if raw_name is not None and not isinstance(raw_name, str):
        fields["name"] = "Use text."
    elif isinstance(raw_name, str) and len(raw_name.strip()) > NAME_MAX:
        fields["name"] = "Use at most %d characters." % NAME_MAX
    if fields:
        raise errors.bad_request("Some fields need fixing.", fields)
    name = (raw_name or "").strip() or name_of_email(email)
    with db.connect() as conn:
        if conn.execute("select 1 from users where email = %s", (email,)).fetchone():
            raise errors.conflict("That person already has a login.")
        refusal = refuse_new_login(me, role)
        if refusal:
            raise errors.forbidden(refusal)
        row = conn.execute(
            "insert into users (email, name, role, active) values (%s, %s, %s, true)"
            " on conflict (email) do nothing returning " + USER_COLUMNS,
            (email, name, role)).fetchone()
        if row is None:                       # someone added them a moment ago
            raise errors.conflict("That person already has a login.")
        log_event(conn, "user_added", me, data={"user_id": row["id"], "role": role})
    return {"ok": True, "user": serialize.user(row)}


@router.patch("/api/bd/admin/users/{id}")
def patch_user(user_id: str = Path(alias="id"), body: Any = Body(None), me: dict = Depends(ADMIN_ONLY)):
    body = json_object(body)
    uid = path_id(user_id, USER_NOT_FOUND)
    with db.connect() as conn:
        target = conn.execute("select " + USER_COLUMNS + " from users where id = %s for update",
                              (uid,)).fetchone()
        if target is None:
            raise errors.not_found(USER_NOT_FOUND)
        refusal = refuse_login_change(me, target, body)
        if refusal:
            raise errors.forbidden(refusal)

        fields, messages = {}, {}
        if "role" in body and body["role"] not in ROLES:
            fields["role"], messages["role"] = "Unknown role.", "Pick a role."
        if "active" in body and not isinstance(body["active"], bool):
            fields["active"], messages["active"] = "Use true or false.", "Use true or false."
        if "name" in body:
            nm = body["name"]
            if not isinstance(nm, str) or not nm.strip():
                fields["name"], messages["name"] = "Use a name.", "Use a name."
            elif len(nm.strip()) > NAME_MAX:
                fields["name"] = messages["name"] = "Use at most %d characters." % NAME_MAX
        _fail_fields(fields, messages)

        new = {k: body[k] for k in ("role", "active", "name") if k in body}
        if "name" in new:
            new["name"] = new["name"].strip()
        changed = {k: v for k, v in new.items() if v != target[k]}
        row = target
        if changed:
            row = conn.execute(
                "update users set role = %s, active = %s, name = %s where id = %s returning " + USER_COLUMNS,
                (new.get("role", target["role"]), new.get("active", target["active"]),
                 new.get("name", target["name"]), target["id"])).fetchone()
            log_event(conn, "user_changed", me,
                      data={"user_id": target["id"],
                            "changes": {k: {"from": target[k], "to": v} for k, v in changed.items()}})
    return {"ok": True, "user": serialize.user(row)}


# ── settings ─────────────────────────────────────────────────────────────────────────────────
def _whole(v, lo, hi):
    """v as an int when it is a whole number from lo to hi (5.0 is 5, as in JSON; true is not a
    number), else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int) and lo <= v <= hi:
        return v
    return None


def merge_settings(current: dict, body: dict):
    """(next settings, top-level keys touched): `body` laid over `current`. Read-only and unknown
    keys are ignored; `weekly` / `default_frequency` objects merge key by key (their unknown
    sub-keys are ignored); any other value replaces."""
    nxt = copy.deepcopy(current)
    touched = []
    for key, value in body.items():
        if key in appsettings.READ_ONLY_KEYS or key not in nxt:
            continue
        if key in appsettings.MERGED_KEYS and isinstance(value, dict) and isinstance(nxt.get(key), dict):
            allowed = WEEKLY_KEYS if key == "weekly" else FREQUENCY_KEYS
            for sub, subval in value.items():
                if sub in allowed:
                    nxt[key][sub] = copy.deepcopy(subval)
        else:
            nxt[key] = copy.deepcopy(value)
        touched.append(key)
    return nxt, touched


# Size limits on a pick list (Hanz, 2026-11-11: "do all"): every role loads these on every page.
PICK_LIST_MAX = 100
PICK_ENTRY_MAX = 120


def validate_settings(s: dict) -> dict:
    """{field: sentence} for everything wrong with a whole Settings object, normalising `s` in place
    when it is right (whole numbers as ints, pick-list values trimmed)."""
    fields = {}
    raw_w = s.get("weekly")
    w = raw_w if isinstance(raw_w, dict) else {}
    new, fol = _whole(w.get("new_count"), 0, 10), _whole(w.get("followup_count"), 0, 10)
    hour = _whole(w.get("run_hour"), 0, 23)
    if new is None or fol is None or new + fol != 10:
        fields["weekly"] = "New people and follow-ups must add up to 10."
    elif w.get("run_day") not in RUN_DAYS or hour is None or not isinstance(w.get("enabled"), bool):
        fields["weekly"] = "Pick Friday, Saturday or Sunday, an hour from 0 to 23, and on or off."
    else:
        w["new_count"], w["followup_count"], w["run_hour"] = new, fol, hour

    if s.get("bd_cadence") not in appsettings.BD_CADENCES:
        fields["bd_cadence"] = "Pick weekly, monthly or quarterly."

    raw_f = s.get("default_frequency")
    f = raw_f if isinstance(raw_f, dict) else {}
    mt = _whole(f.get("maintenance"), 1, 52)
    if mt is None:
        fields["default_frequency"] = "Use a number from 1 to 52."
    else:
        f.pop("bd", None)
        f["maintenance"] = mt

    goal = _whole(s.get("weekly_meeting_goal"), 0, 50)
    if goal is None:
        fields["weekly_meeting_goal"] = "Use a number from 0 to 50."
    else:
        s["weekly_meeting_goal"] = goal
    least = _whole(s.get("non_dsbc_website_min"), 0, 50)
    if least is None or (goal is not None and least > goal):
        fields["non_dsbc_website_min"] = "Use a number from 0 up to the meeting goal."
    else:
        s["non_dsbc_website_min"] = least

    if not isinstance(s.get("ai_enabled"), bool):
        fields["ai_enabled"] = "Use on or off."

    for key in appsettings.PICK_LISTS:
        values = s.get(key)
        cleaned: list[str] | None = None
        if isinstance(values, list) and (len(values) > PICK_LIST_MAX or any(
                isinstance(x, str) and len(x.strip()) > PICK_ENTRY_MAX for x in values)):
            fields[key] = "Keep at most %d values of %d characters or fewer." % (PICK_LIST_MAX, PICK_ENTRY_MAX)
            continue
        if isinstance(values, list) and len(values) > 0 and all(
                isinstance(x, str) and x.strip() for x in values):
            stripped = [x.strip() for x in values]
            if len({x.lower() for x in stripped}) == len(stripped):
                cleaned = stripped
        if cleaned is None:
            fields[key] = "Keep at least one value, each one different."
        else:
            s[key] = cleaned

    if "lead_sources" not in fields:
        missing = [x for x in s.get("system_lead_sources") or [] if x not in s["lead_sources"]]
        if missing:
            fields["lead_sources"] = (" and ".join(missing)
                                      + " can't be removed: the weekly meeting goal counts on them.")
    return fields


@router.put("/api/bd/admin/settings")
def put_settings(body: Any = Body(None), me: dict = Depends(ADMIN_ONLY)):
    body = json_object(body)
    with db.connect() as conn:
        # One settings change at a time: two admins saving at once must not each merge into
        # what the other is about to overwrite.
        conn.execute("select pg_advisory_xact_lock(hashtext('bd.admin.settings'))")
        current = appsettings.load(conn)
        nxt, touched = merge_settings(current, body)
        fields = validate_settings(nxt)
        if fields:
            keys = list(fields)
            raise errors.bad_request(fields[keys[0]] if len(keys) == 1 else "Some settings need fixing.",
                                     fields)
        if touched:
            appsettings.store(conn, {k: nxt[k] for k in touched}, me["id"])
            log_event(conn, "settings_changed", me, data={"keys": touched})
        settings = appsettings.load(conn)
    return {"ok": True, "settings": settings}


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
        who = weekly.list_owner(conn, b.get("owner"), me)
        today = bizdate.today_central()
        this_monday = bizdate.week_start(today)
        next_monday = bizdate.add_days(this_monday, 7)
        raw = b.get("week_start")
        if _js_truthy(raw):
            ws = weekly.monday_or_none(raw)
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


# ── the phone system ─────────────────────────────────────────────────────────────────────────
def _telephony_status(provider: str):
    """(connected, message) for the configured provider. Until the Quo adapter is built,
    "connected" only says whether its key and webhook secret are SET; neither value is read further."""
    if provider in ("", "null", "none"):
        return False, "No phone system connected yet."
    if provider == "quo":
        if config.BD_QUO_API_KEY and config.BD_QUO_WEBHOOK_SECRET:
            return True, "Quo is connected."
        return False, "Quo is picked, but its API key or webhook secret is not set."
    return False, "This phone system is not supported yet."


@router.get("/api/bd/admin/telephony")
def telephony(user: dict = Depends(ADMIN_ONLY)):
    provider = (config.BD_TELEPHONY_PROVIDER or "null").lower()
    connected, message = _telephony_status(provider)
    with db.connect() as conn:
        seen = conn.execute("select max(received_at) as at, count(*)::integer as n from integration_events"
                            " where provider = %s", (provider,)).fetchone()
        open_count = conn.execute("select count(*)::integer as n from unmatched_calls where status = 'open'"
                                  ).fetchone()["n"]
    return {"ok": True, "telephony": {
        "provider": provider,
        "connected": connected,
        "last_event_at": serialize.ts(seen["at"]),
        "events": seen["n"],
        "unmatched_open": open_count,
        "message": message,
    }}


# ── unmatched calls ──────────────────────────────────────────────────────────────────────────
@router.get("/api/bd/admin/unmatched-calls")
def list_unmatched(request: Request, status: str = Query("open"), user: dict = Depends(ASSISTANT)):
    limit, offset = page_or_400(request.query_params)
    if status not in UNMATCHED_STATUSES:
        raise errors.bad_request("Pick open, attached, dismissed or all.",
                                 {"status": "Use open, attached, dismissed or all."})
    where, params = ("true", []) if status == "all" else ("status = %s", [status])
    with db.connect() as conn:
        total = conn.execute("select count(*)::integer as n from unmatched_calls where " + where,
                             params).fetchone()["n"]
        rows = conn.execute("select * from unmatched_calls where " + where
                            + " order by id limit %s offset %s", params + [limit, offset]).fetchall()
    return {"ok": True, "items": [serialize.unmatched_call(r) for r in rows], "total": total}


def _open_call(conn, call_id) -> dict:
    """The unmatched call, locked for this transaction: 404 unknown (a path id that is not a
    number too), 409 already handled."""
    cid = path_id(call_id, CALL_NOT_FOUND)
    row = conn.execute("select * from unmatched_calls where id = %s for update", (cid,)).fetchone()
    if row is None:
        raise errors.not_found(CALL_NOT_FOUND)
    if row["status"] != "open":
        raise errors.conflict("That call was already handled.")
    return row


@router.post("/api/bd/admin/unmatched-calls/{id}/attach")
def attach_unmatched(call_id: str = Path(alias="id"), body: Any = Body(None), me: dict = Depends(ASSISTANT)):
    import psycopg

    body = json_object(body)
    with db.connect() as conn:
        call = _open_call(conn, call_id)

        fields, messages = {}, {}
        contact_id = body.get("contact_id")
        if isinstance(contact_id, bool) or not isinstance(contact_id, int):
            fields["contact_id"], messages["contact_id"] = "Pick a contact.", "Pick a contact."
        said = body.get("outcome")
        if said is not None and said not in ATTACH_OUTCOMES:
            fields["outcome"], messages["outcome"] = "Use answered, voicemail or no_answer.", "Pick how the call went."
        save_number = body.get("save_number", False)
        if save_number is None:
            save_number = False
        if not isinstance(save_number, bool):
            fields["save_number"], messages["save_number"] = "Use true or false.", "Use true or false."
        _fail_fields(fields, messages)

        contact = None
        if as_id(contact_id) is not None:
            contact = conn.execute("select id from contacts where id = %s for update", (contact_id,)).fetchone()
        if contact is None:
            raise errors.not_found("That contact does not exist.")

        if call["kind"] == "sms":
            kind, outcome, duration = "sms", None, None       # a text has no outcome
        else:
            outcome = said or ("answered" if (call["duration_s"] or 0) >= ANSWER_MIN_SECONDS else "no_answer")
            kind, duration = "call", call["duration_s"]       # call + voicemail is stored as a voicemail
        if call["external_id"] is not None and conn.execute(
                "select 1 from interactions where provider = %s and external_id = %s",
                (call["provider"], call["external_id"])).fetchone():
            raise errors.conflict("That call is already on a contact's timeline.")
        try:
            with conn.transaction():          # a savepoint: the webhook may store it meanwhile
                # The attach neither closes this week's task nor suggests a next step; a touch still
                # meets a kept promise (apply_touch). A maintenance task is the one exception: it
                # closes with the due state it was pinned for.
                logged = interactions_service.log_interaction(
                    conn, contact_id, None, kind=kind, outcome=outcome, occurred_at=call["occurred_at"],
                    direction=call["direction"], duration_s=duration, summary=call["summary"] or "",
                    transcript=call["transcript"], recording_url=call["recording_url"],
                    provider=call["provider"], external_id=call["external_id"],
                    close_task=False, recommend=False)
        except psycopg.errors.UniqueViolation:
            raise errors.conflict("That call is already on a contact's timeline.") from None
        interaction_id = logged["interaction"]["id"]

        if save_number:
            ten = last10(call["from_e164"])
            if ten:
                conn.execute("update contacts set phone = %s where id = %s", (display(ten), contact_id))

        conn.execute(
            "update unmatched_calls set status = 'attached', attached_interaction_id = %s,"
            " handled_by = %s, handled_at = bd_now() where id = %s",
            (interaction_id, me["id"], call["id"]))
        interaction = serialize.fetch_interaction(conn, interaction_id)
    return {"ok": True, "unmatched_call": {"id": call["id"], "status": "attached"},
            "interaction": interaction}


@router.post("/api/bd/admin/unmatched-calls/{id}/dismiss")
def dismiss_unmatched(call_id: str = Path(alias="id"), me: dict = Depends(ASSISTANT)):
    with db.connect() as conn:
        call = _open_call(conn, call_id)
        conn.execute("update unmatched_calls set status = 'dismissed', handled_by = %s, handled_at = bd_now()"
                     " where id = %s", (me["id"], call["id"]))
    return {"ok": True, "unmatched_call": {"id": call["id"], "status": "dismissed"}}
