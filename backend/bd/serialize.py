"""Database rows -> the contract's JSON objects (docs/bd/api-contract.md "Core objects"). EVERY router
builds its answers with these, so a field name, a type or a null-vs-missing can only be wrong in
one place.

Rows are dicts (db.connect() uses dict_row). Each function documents the columns it reads; the
*_SELECT constants are SQL that produces exactly those columns, to be extended with a WHERE /
ORDER BY by the caller (values always as parameters):

    rows = conn.execute(INTERACTION_SELECT + " where i.contact_id = %s order by i.occurred_at desc", (cid,))
    items = [interaction(r) for r in rows]

Objects and the functions that make them:
    UserRef            user_ref(id, name)            {"id", "name"}  (id may be None: a workbook co-owner)
    User               user(row)                     users row
    (users list item)  user_compact(row)             {"id", "name", "role"}  GET /api/users
    Company            company(row)                  COMPANY_SELECT row
    {id, name}         company_ref(id, name)
    Contact            contact(row)                  contacts_summary row ("select * from contacts_summary")
    ContactCompact     contact_compact(row)          contacts_summary row
    (contact ref)      contact_ref(row)              {"id", "name", "company": {id, name}}
    (dup match)        duplicate_match(row, reason)  {"contact_id","name","company","city","reason"}
    Account            account(row, category, ...)   one Contacts-page tab row (bd/routers/accounts.py)
    AccountPerson      account_person(row)           contacts_summary row
    (company move)     account_move(...)             what POST /api/bd/contacts/accounts/{id}/move answers
    Interaction        interaction(row)              INTERACTION_SELECT row
    TaskBatch          task_batch(row)               BATCH_SELECT row
    Task               task(row, contact)            tasks row + an already-serialised ContactCompact
    Recommendation     recommendation(row)           RECOMMENDATION_SELECT row
    FollowupDraft      followup_draft(row)           followup_drafts row
    Candidate          candidate(row)                CANDIDATE_SELECT row
    Import             import_record(row)            IMPORT_SELECT row
    (unmatched call)   unmatched_call(row)           unmatched_calls row
    Settings           appsettings.load(conn)        (already the contract's object)

Fetch helpers: fetch_contact(conn, id), fetch_contacts(conn, where, params, order, limit),
fetch_interaction(conn, id), fetch_tasks(conn, where, params, order, limit), fetch_company(conn, id).
A list fetch takes its filter as psycopg's sql.Composable written in code (values in `params`), its
order as a KEY from CONTACT_ORDERS / TASK_ORDERS and at most MAX_LIMIT rows, so nothing a request
sends can become SQL text.

Timestamps go out as ISO 8601 in Central with that moment's offset ("2026-10-30T16:00:00-05:00");
dates as "YYYY-MM-DD"; money (numeric) as a float.

One deliberate quirk, copied from the mock: a Contact carries `archived_at` ONLY when it is
archived (mock-data.js contacts have no such key; the mock adds it on archive).
"""
from __future__ import annotations

import datetime as _dt
import decimal
from collections.abc import Mapping
from typing import Any

from .bizdate import iso_date, to_iso_central

ts = to_iso_central

# A database row (psycopg dict_row) or any mapping with the same keys.
Row = Mapping[str, Any]


def _num(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


# ── people ───────────────────────────────────────────────────────────────────────────────────
def user_ref(user_id: Any, name: Any) -> dict | None:
    """UserRef, or None when there is nobody (no id and no name)."""
    if user_id is None and not name:
        return None
    return {"id": user_id, "name": name}


def user(row: Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "active": bool(row["active"]),
        "last_seen_at": ts(row.get("last_seen_at")),
    }


def user_compact(row: Row) -> dict:
    return {"id": row["id"], "name": row["name"], "role": row["role"]}


# ── companies ────────────────────────────────────────────────────────────────────────────────
COMPANY_SELECT = (
    "select co.id, co.name, co.city, co.industry, co.created_at,"
    " (select count(*) from contacts c where c.company_id = co.id and c.archived_at is null)::integer"
    " as contact_count from companies co"
)


def company_ref(company_id: Any, name: Any) -> dict:
    return {"id": company_id, "name": name}


def company(row: Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "city": row.get("city"),
        "industry": row.get("industry"),
        "created_at": ts(row.get("created_at")),
        "contact_count": int(row.get("contact_count") or 0),
    }


# ── contacts ─────────────────────────────────────────────────────────────────────────────────
CONTACT_SELECT = "select * from contacts_summary cs"


def _co_owner(row: Row) -> dict | None:
    if row.get("co_owner_id") is None and not row.get("co_owner_name"):
        return None
    return user_ref(row.get("co_owner_id"), row.get("co_owner_name"))


def _duplicate_of(row: Row) -> dict | None:
    if row.get("duplicate_of") is None:
        return None
    return {
        "contact_id": row["duplicate_of"],
        "name": row.get("duplicate_name"),
        "company": row.get("duplicate_company"),
        "reason": row.get("duplicate_reason") or "Same company name",
    }


def contact(row: Row) -> dict:
    """The full Contact from a contacts_summary row. `frequency_per_year` is the view's derived one
    (BD: from the cadence; maintenance: stored); `cadence_override` / `_until` are the stored
    values, still shown after the override has lapsed (`cadence_source` says whether it applies)."""
    out = {
        "id": row["id"],
        "company": company_ref(row["company_id"], row["company_name"]),
        "name": row["name"],
        "title": row.get("title"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "phone_e164": row.get("phone_e164"),
        "city": row.get("city"),
        "industry": row.get("industry"),
        "lead_source": row.get("lead_source"),
        "stage": row.get("stage"),
        "category": row["category"],
        "owner": user_ref(row.get("owner_id"), row.get("owner_name")) if row.get("owner_id") is not None else None,
        "co_owner": _co_owner(row),
        "frequency_per_year": int(row["frequency_per_year"]),
        "cadence": row.get("cadence"),
        "cadence_source": row.get("cadence_source"),
        "cadence_override": row.get("cadence_override"),
        "cadence_override_until": iso_date(row.get("cadence_override_until")),
        "confirmed": bool(row["confirmed"]),
        "importance": int(row["importance"]),
        "next_step": row.get("next_step"),
        "next_step_date": iso_date(row.get("next_step_date")),
        "promised_date": iso_date(row.get("promised_date")),
        "last_quote_date": iso_date(row.get("last_quote_date")),
        "duplicate_of": _duplicate_of(row),
        "source": row["source"],
        "tags": list(row.get("tags") or []),
        "notes": row.get("notes") if row.get("notes") is not None else "",
        "account_type": row.get("account_type"),
        "created_at": ts(row.get("created_at")),
        "last_live_at": ts(row.get("last_live_at")),
        "last_attempt_at": ts(row.get("last_attempt_at")),
        "last_followup_at": ts(row.get("last_followup_at")),
        "attempts_since_live": int(row.get("attempts_since_live") or 0),
        "touches_this_year": int(row.get("touches_this_year") or 0),
        "next_due_date": iso_date(row.get("next_due_date")),
        "cadence_status": row["cadence_status"],
        "maintenance_due_date": iso_date(row.get("maintenance_due_date")),
        "maintenance_due": bool(row.get("maintenance_due")),
    }
    if row.get("archived_at") is not None:
        out["archived_at"] = ts(row["archived_at"])
    return out


def contact_compact(row: Row) -> dict:
    """ContactCompact (tasks, company pages) from a contacts_summary row."""
    return {
        "id": row["id"],
        "name": row["name"],
        "title": row.get("title"),
        "company": company_ref(row["company_id"], row["company_name"]),
        "phone": row.get("phone"),
        "phone_e164": row.get("phone_e164"),
        "email": row.get("email"),
        "category": row["category"],
        "confirmed": bool(row["confirmed"]),
        "lead_source": row.get("lead_source"),
        "last_live_at": ts(row.get("last_live_at")),
        "cadence_status": row["cadence_status"],
    }


def contact_ref(row: Row) -> dict:
    """{"id", "name", "company": {"id", "name"}} from a contacts_summary row (or any row with
    id, name, company_id, company_name)."""
    return {"id": row["id"], "name": row["name"], "company": company_ref(row["company_id"], row["company_name"])}


def duplicate_match(row: Row, reason: str) -> dict:
    """One `possible_duplicates` / GET /api/contacts/duplicates item, from a contacts_summary row."""
    return {"contact_id": row["id"], "name": row["name"], "company": row["company_name"],
            "city": row.get("city"), "reason": reason}


# ── BD accounts (the Contacts page, #810) ────────────────────────────────────────────────────
def account_person(row: Row) -> dict:
    """One person under an account row, from a contacts_summary row: who they are, how to reach
    them, and what their status pill and cadence pill read (BD.statusPill)."""
    return {
        "id": row["id"],
        "name": row["name"],
        "title": row.get("title"),
        "phone": row.get("phone"),
        "phone_e164": row.get("phone_e164"),
        "email": row.get("email"),
        "category": row["category"],
        "confirmed": bool(row["confirmed"]),
        "importance": int(row["importance"]),
        "owner": user_ref(row.get("owner_id"), row.get("owner_name")) if row.get("owner_id") is not None else None,
        "duplicate_of": _duplicate_of(row),
        "lead_source": row.get("lead_source"),
        "last_live_at": ts(row.get("last_live_at")),
        "last_followup_at": ts(row.get("last_followup_at")),
        "cadence_status": row["cadence_status"],
        "cadence": row.get("cadence"),
        "cadence_source": row.get("cadence_source"),
        "cadence_override_until": iso_date(row.get("cadence_override_until")),
        "maintenance_due": bool(row.get("maintenance_due")),
        "maintenance_due_date": iso_date(row.get("maintenance_due_date")),
    }


def account(row: Row, category: str, owner: dict | None, other_owners: int, people: list) -> dict:
    """An account row of one tab (`category`): the company, its people on that tab, the owner,
    how many other people own someone there ("+N") and the last live talk with anyone there."""
    return {
        "id": row["id"],
        "name": row["name"],
        "city": row.get("city"),
        "industry": row.get("industry"),
        "category": category,
        "people_count": len(people),
        "owner": owner,
        "other_owners": int(other_owners),
        "last_live_at": ts(row.get("last_live_at")),
        "people": [account_person(p) for p in people],
    }


def account_move(move_id: Any, company_row: Row, to: str, people: int, calls_off: int, pinned: int,
                 at: Any, undo_seconds: int) -> dict:
    """What a company move answers: its id (for Undo), the company, where it went, how many people,
    how many calls came off this week's lists, how many follow-ups were pinned, and until when Undo works."""
    return {
        "id": move_id,
        "company": company_ref(company_row["id"], company_row["name"]),
        "to": to,
        "people": int(people),
        "calls_off": int(calls_off),
        "pinned": int(pinned),
        "undo_until": ts(at + _dt.timedelta(seconds=int(undo_seconds))),
    }


def account_pair(a: Row, b: Row, phones: Any, email_domains: Any) -> dict:
    """A likely duplicate pair of BD accounts (#811): both sides, lower id first, each with its people
    who are not archived, and what they share (a hint only, never the reason for the pair)."""
    def side(r: Row) -> dict:
        return {"id": r["id"], "name": r["name"], "city": r["city"], "people_count": int(r["people_count"])}
    return {"a": side(a), "b": side(b),
            "hints": {"phones": sorted(phones), "email_domains": sorted(email_domains)}}


def account_merge(merge_id: Any, account: dict, into: dict, name_before: Any, people: Any,
                  people_count: Any, at: Any, by: Any) -> dict:
    """One merge (#811), as POST .../merge answers it and as Recently merged lists it: its id (for
    Undo), the account merged away and the survivor (CompanyRefs; the survivor by its name now), the
    survivor's name before, how many people moved and how many the survivor holds now (neither counts
    the archived), when, and by whom."""
    return {"id": merge_id, "account": account, "into": into, "name_before": name_before,
            "people": None if people is None else int(people), "people_count": int(people_count),
            "at": ts(at), "by": by}


def merge_undone(merge_id: Any, account: dict, into: dict, people: Any) -> dict:
    return {"id": merge_id, "account": account, "into": into, "people": people}


def kept_pair(a: dict, b: dict, decided_by: Any, decided_at: Any) -> dict:
    """A pair kept as two accounts (#811): both CompanyRefs, lower id first, who decided and when."""
    return {"a": a, "b": b, "decided_by": decided_by, "decided_at": ts(decided_at)}


# ── interactions ─────────────────────────────────────────────────────────────────────────────
INTERACTION_SELECT = (
    "select i.id, i.contact_id, c.name as contact_name, c.company_id, co.name as company_name,"
    " i.kind, i.direction, i.counts_as_touch, i.occurred_at, i.duration_s, i.outcome, i.summary,"
    " i.transcript, i.recording_url, i.provider, i.external_id, i.user_id, u.name as user_name,"
    " i.followup_status, i.followup_at, i.created_at"
    " from interactions i"
    " join contacts c on c.id = i.contact_id"
    " join companies co on co.id = c.company_id"
    " left join users u on u.id = i.user_id"
)


def interaction(row: Row) -> dict:
    return {
        "id": row["id"],
        "contact_id": row["contact_id"],
        "contact": {"id": row["contact_id"], "name": row["contact_name"],
                    "company": company_ref(row["company_id"], row["company_name"])},
        "kind": row["kind"],
        "direction": row.get("direction"),
        "counts_as_touch": bool(row["counts_as_touch"]),
        "occurred_at": ts(row["occurred_at"]),
        "duration_s": row.get("duration_s"),
        "outcome": row.get("outcome"),
        "summary": row.get("summary"),
        "transcript": row.get("transcript"),
        "recording_url": row.get("recording_url"),
        "provider": row["provider"],
        "external_id": row.get("external_id"),
        "user": user_ref(row["user_id"], row.get("user_name")) if row.get("user_id") is not None else None,
    }


# ── the weekly 10 ────────────────────────────────────────────────────────────────────────────
BATCH_SELECT = (
    "select b.id, b.kind, b.owner_id, u.name as owner_name, b.week_start, b.generated_at"
    " from task_batches b join users u on u.id = b.owner_id"
)


def task_batch(row: Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "owner": user_ref(row["owner_id"], row.get("owner_name")),
        "week_start": iso_date(row["week_start"]),
        "generated_at": ts(row["generated_at"]),
    }


def task(row: Row, contact: Any = None) -> dict:
    """Task from a tasks row; `contact` is the ContactCompact (serialised) or None."""
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "contact": contact,
        "kind": row["kind"],
        "reason": row.get("reason") or "",
        "reasons": list(row.get("reasons") or []),
        "score": int(row.get("score") or 0),
        "status": row["status"],
        "done_at": ts(row.get("done_at")),
        "snoozed_until": iso_date(row.get("snoozed_until")),
    }


# ── AI next actions and follow-ups ───────────────────────────────────────────────────────────
RECOMMENDATION_SELECT = (
    "select r.id, r.contact_id, r.interaction_id, r.action, r.due_date, r.reason, r.source, r.status,"
    " r.created_at, r.decided_at, r.decided_by, du.name as decided_by_name"
    " from ai_recommendations r left join users du on du.id = r.decided_by"
)


def recommendation(row: Row) -> dict:
    return {
        "id": row["id"],
        "contact_id": row["contact_id"],
        "interaction_id": row.get("interaction_id"),
        "action": row["action"],
        "due_date": iso_date(row.get("due_date")),
        "reason": row.get("reason") or "",
        "source": row["source"],
        "status": row["status"],
        "created_at": ts(row["created_at"]),
        "decided_at": ts(row.get("decided_at")),
        "decided_by": user_ref(row["decided_by"], row.get("decided_by_name")) if row.get("decided_by") is not None else None,
    }


def followup_draft(row: Row) -> dict:
    return {
        "id": row["id"],
        "contact_id": row["contact_id"],
        "interaction_id": row.get("interaction_id"),
        "channel": row["channel"],
        "to": row.get("to_address"),
        "subject": row.get("subject"),
        "body": row.get("body") or "",
        "source": row["source"],
        "status": row["status"],
    }


# ── review candidates ────────────────────────────────────────────────────────────────────────
CANDIDATE_SELECT = (
    "select k.*, pd.name as pd_name, pdco.name as pd_company"
    " from candidates k"
    " left join contacts pd on pd.id = k.possible_duplicate_id"
    " left join companies pdco on pdco.id = pd.company_id"
)


def candidate(row: Row) -> dict:
    dup = None
    if row.get("possible_duplicate_id") is not None:
        dup = {"contact_id": row["possible_duplicate_id"], "name": row.get("pd_name"),
               "company": row.get("pd_company")}
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_name": row.get("project_name"),
        "company": row.get("company"),
        "contact_name": row.get("contact_name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "quote_total": _num(row.get("quote_total")),
        "quote_date": iso_date(row.get("quote_date")),
        "status": row["status"],
        "possible_duplicate": dup,
    }


# ── admin ────────────────────────────────────────────────────────────────────────────────────
IMPORT_SELECT = (
    "select im.*, u.name as by_name from imports im left join users u on u.id = im.by_id"
)


def import_record(row: Row) -> dict:
    return {
        "id": row["id"],
        "file_name": row["file_name"],
        "dry_run": bool(row["dry_run"]),
        "started_at": ts(row["started_at"]),
        "by": user_ref(row["by_id"], row.get("by_name")) if row.get("by_id") is not None else None,
        "rows_read": int(row.get("rows_read") or 0),
        "created": int(row.get("created") or 0),
        "updated": int(row.get("updated") or 0),
        "skipped": int(row.get("skipped") or 0),
        "possible_duplicates": int(row.get("possible_duplicates") or 0),
        "errors": list(row.get("errors") or []),
    }


def unmatched_call(row: Row) -> dict:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "external_id": row.get("external_id"),
        "direction": row.get("direction"),
        "from_e164": row.get("from_e164"),
        "occurred_at": ts(row["occurred_at"]),
        "duration_s": row.get("duration_s"),
        "summary": row.get("summary"),
        "status": row["status"],
    }


# ── fetch helpers ────────────────────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 500
MAX_LIMIT = 500
CONTACT_ORDERS = {"id": "cs.id", "id_desc": "cs.id desc", "name": "cs.name, cs.id",
                  "name_desc": "cs.name desc, cs.id desc"}
TASK_ORDERS = {"id": "t.id", "id_desc": "t.id desc", "batch": "b.id, t.id"}


def _list_sql(head: str, where: Any, order: str, orders: dict, limit: Any) -> Any:
    """head + where + an allowed order + a bounded limit, as one sql.Composed."""
    from psycopg import sql

    if not isinstance(where, sql.Composable):
        raise TypeError("where must be psycopg.sql.Composable (SQL written in code), not %s"
                        % type(where).__name__)
    if order not in orders:
        raise ValueError("unknown order %r (one of %s)" % (order, ", ".join(sorted(orders))))
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("limit must be a whole number from 1 to %d" % MAX_LIMIT)
    return sql.SQL(" ").join([sql.SQL(head), sql.SQL("where"), where, sql.SQL("order by " + orders[order]),
                              sql.SQL("limit {}").format(sql.Literal(limit))])


def _true() -> Any:
    from psycopg import sql

    return sql.SQL("true")


def fetch_contact(conn: Any, contact_id: Any) -> dict | None:
    """The full Contact, or None."""
    row = conn.execute(CONTACT_SELECT + " where cs.id = %s", (contact_id,)).fetchone()
    return contact(row) if row else None


def fetch_contacts(conn: Any, where: Any = None, params: Any = (), order: str = "id",
                   limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Full Contacts. `where` is a psycopg sql.Composable on contacts_summary as `cs` (None: every
    row), with its values in `params`; `order` is a CONTACT_ORDERS key."""
    query = _list_sql(CONTACT_SELECT, _true() if where is None else where, order, CONTACT_ORDERS, limit)
    return [contact(r) for r in conn.execute(query, params).fetchall()]


def fetch_company(conn: Any, company_id: Any) -> dict | None:
    row = conn.execute(COMPANY_SELECT + " where co.id = %s", (company_id,)).fetchone()
    return company(row) if row else None


def fetch_interaction(conn: Any, interaction_id: Any) -> dict | None:
    row = conn.execute(INTERACTION_SELECT + " where i.id = %s", (interaction_id,)).fetchone()
    return interaction(row) if row else None


def fetch_tasks(conn: Any, where: Any = None, params: Any = (), order: str = "id",
                limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Tasks with their ContactCompact. `where` is a psycopg sql.Composable on the tasks table as `t`
    and task_batches as `b` (None: every row), with its values in `params`; `order` is a
    TASK_ORDERS key."""
    query = _list_sql("select t.* from tasks t join task_batches b on b.id = t.batch_id",
                      _true() if where is None else where, order, TASK_ORDERS, limit)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return []
    ids = sorted({r["contact_id"] for r in rows})
    contacts = {r["id"]: contact_compact(r) for r in
                conn.execute(CONTACT_SELECT + " where cs.id = any(%s)", (ids,)).fetchall()}
    return [task(r, contacts.get(r["contact_id"])) for r in rows]
