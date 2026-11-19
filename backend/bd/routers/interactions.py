"""Interactions: GET/POST /api/bd/contacts/{id}/interactions (the timeline and logging),
PATCH/DELETE /api/bd/interactions/{id} (docs/bd/api-contract.md "Interactions").

BD's interactions routes, moved under /api/bd/ (#807) with the same checks, answers and words. This
Week's call dialog logs calls through them. The rules live in bd/interactions_service.py (shared
with the week router and, later, the importer and the telephony webhook); this module checks who
may do what, validates the body with BD's words and shapes the answers through bd/serialize.py.

Who:
    GET    any signed-in role
    POST   salesperson, admin; an assistant may log notes only ("Assistants can add notes only.")
    PATCH  the user who logged it, or an admin ("Only the person who logged this can change it.");
           an assistant cannot turn her note into another kind
    DELETE admin
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends

from .. import auth, bizdate, db, errors, events, paging, serialize, web
from .. import interactions_service as svc

router = web.make_router()

# The earliest moment an interaction may be logged at (Central): the importer's dates start in
# 1990 too. An earlier one (year 1, say) is a typo, and would overflow the Central conversion.
EARLIEST_OCCURRED = 1990
_INT_MAX = 2 ** 31 - 1
ASSISTANT_NOTES_ONLY = "Assistants can add notes only."
NOT_YOURS = "Only the person who logged this can change it."
NO_CONTACT = "That contact does not exist."
NO_INTERACTION = "That interaction does not exist."


# ── input helpers ────────────────────────────────────────────────────────────────────────────
def _occurred_at(value):
    """A timestamp that has happened (its Central date is not after today) and is not before
    1990, as an aware datetime. Review finding DATA-3: the Central conversion is inside the same
    try, so a moment near year 1 (which overflows it) is the plain 400, never a 500."""
    if not isinstance(value, str) or not value.strip():
        raise errors.bad_request("Some fields need fixing.", {"occurred_at": "Use a date and time (ISO 8601)."})
    try:
        at = bizdate.parse_ts(value)
        day = at.astimezone(bizdate.BIZ_TZ).date()      # at is an aware datetime: biz_date(at)'s own branch
    except (ValueError, TypeError, OverflowError):
        raise errors.bad_request("Some fields need fixing.",
                                 {"occurred_at": "Use a date and time (ISO 8601)."}) from None
    if day.year < EARLIEST_OCCURRED:
        raise errors.bad_request("Some fields need fixing.",
                                 {"occurred_at": "Use a date from %d on." % EARLIEST_OCCURRED})
    if day > bizdate.today_central():
        raise errors.bad_request("That time is in the future.", {"occurred_at": "Pick a time that has happened."})
    return at


def _duration(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        n = None
    elif isinstance(value, int):
        n = value
    elif isinstance(value, float) and value.is_integer():
        n = int(value)
    elif isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        n = int(value.strip())
    else:
        n = None
    if n is None or n < 0 or n > _INT_MAX:
        raise errors.bad_request("Some fields need fixing.", {"duration_s": "Use a whole number of seconds."})
    return n


def _text(value, field: str, limit: int, empty):
    if value is None or value == "":
        return empty
    if not isinstance(value, str):
        raise errors.bad_request("Some fields need fixing.", {field: "Use text."})
    if len(value) > limit:
        raise errors.bad_request("Some fields need fixing.", {field: "Too long."})
    return value


def _direction(value):
    if value is None or value == "":
        return None
    if value not in svc.DIRECTIONS:
        raise errors.bad_request("Some fields need fixing.", {"direction": "Use in or out."})
    return value


def _kind_outcome(kind, outcome):
    try:
        return svc.normalize_kind(kind, outcome)
    except svc.InteractionInputError as e:
        raise errors.bad_request(e.message, e.fields) from None


# ── routes ───────────────────────────────────────────────────────────────────────────────────
@router.get("/api/bd/contacts/{id}/interactions")
def list_interactions(id: str, user: dict = Depends(auth.current_user)):
    cid = paging.path_id(id, NO_CONTACT)
    with db.connect() as conn:
        c = conn.execute("select id, source, created_at from contacts where id = %s", (cid,)).fetchone()
        if c is None:
            raise errors.not_found(NO_CONTACT)
        items = svc.timeline(conn, c)
    return {"ok": True, "items": items}


@router.post("/api/bd/contacts/{id}/interactions")
def log_interaction(id: str, body: Any = Body(None), user: dict = Depends(auth.current_user)):
    body = paging.json_object(body)
    if user.get("role") == "assistant":
        if body.get("kind") != "note":
            raise errors.forbidden(ASSISTANT_NOTES_ONLY)
    elif not auth.has_role(user, "salesperson"):
        raise errors.forbidden()
    cid = paging.path_id(id, NO_CONTACT)
    with db.connect() as conn:
        c = conn.execute("select id from contacts where id = %s for update", (cid,)).fetchone()
        if c is None:
            raise errors.not_found(NO_CONTACT)
        kind, outcome = _kind_outcome(body.get("kind"), body.get("outcome"))
        raw_at = body.get("occurred_at")
        at = None if raw_at is None or raw_at == "" else _occurred_at(raw_at)
        duration = _duration(body.get("duration_s"))
        summary = _text(body.get("summary"), "summary", svc.SUMMARY_MAX, "")
        transcript = _text(body.get("transcript"), "transcript", svc.TRANSCRIPT_MAX, None)
        direction = _direction(body.get("direction"))
        out = svc.log_interaction(conn, cid, user, kind=kind, outcome=outcome, occurred_at=at,
                                  direction=direction, duration_s=duration, summary=summary,
                                  transcript=transcript)
        crow = svc.recompute_contact(conn, cid)
    t = out["task"]
    return {
        "ok": True,
        "interaction": serialize.interaction(out["interaction"]),
        "contact": serialize.contact(crow),
        "task": {"id": t["id"], "status": t["status"], "done_at": serialize.ts(t["done_at"])} if t else None,
        "recommendation": serialize.recommendation(out["recommendation"]) if out["recommendation"] else None,
        "missed_call": out["missed_call"],
    }


@router.patch("/api/bd/interactions/{id}")
def patch_interaction(id: str, body: Any = Body(None), user: dict = Depends(auth.current_user)):
    iid = paging.path_id(id, NO_INTERACTION)
    body = paging.json_object(body)
    with db.connect() as conn:
        row = conn.execute("select * from interactions where id = %s for update", (iid,)).fetchone()
        if row is None:
            raise errors.not_found(NO_INTERACTION)
        if not auth.is_admin(user) and row["user_id"] != user["id"]:
            raise errors.forbidden(NOT_YOURS)
        changes = {}
        if "kind" in body or "outcome" in body:
            new_kind = body.get("kind") or ("call" if row["kind"] == "voicemail" and body.get("outcome") else row["kind"])
            new_outcome = body["outcome"] if "outcome" in body else row["outcome"]
            kind, outcome = _kind_outcome(new_kind, new_outcome)
            if user.get("role") == "assistant" and kind != "note":
                raise errors.forbidden(ASSISTANT_NOTES_ONLY)
            changes["kind"], changes["outcome"] = kind, outcome
        if "occurred_at" in body:
            changes["occurred_at"] = _occurred_at(body["occurred_at"])
        if "duration_s" in body:
            changes["duration_s"] = _duration(body["duration_s"])
        if "summary" in body:
            changes["summary"] = _text(body["summary"], "summary", svc.SUMMARY_MAX, "")
        if "transcript" in body:
            changes["transcript"] = _text(body["transcript"], "transcript", svc.TRANSCRIPT_MAX, None)
        irow = svc.update_interaction(conn, row, changes)
    return {"ok": True, "interaction": serialize.interaction(irow)}


@router.delete("/api/bd/interactions/{id}")
def delete_interaction(id: str, user: dict = Depends(auth.require_role())):
    iid = paging.path_id(id, NO_INTERACTION)
    with db.connect() as conn:
        row = conn.execute("select id, contact_id, kind, occurred_at from interactions where id = %s for update",
                           (iid,)).fetchone()
        if row is None:
            raise errors.not_found(NO_INTERACTION)
        svc.delete_interaction(conn, iid)
        # An audit row with no contact_id, so it never shows on the contact's timeline.
        events.log_event(conn, "interaction_deleted", actor=user, contact_id=None,
                         data={"interaction_id": iid, "contact_id": row["contact_id"], "kind": row["kind"],
                               "occurred_at": serialize.ts(row["occurred_at"])})
    return {"ok": True, "deleted": iid}
