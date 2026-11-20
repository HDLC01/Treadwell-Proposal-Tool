"""The BD fixture seed: a small, MADE-UP data set for the tests and for staging (#805, Q27).

    from bd.ops import fixture_seed
    counts = fixture_seed.seed(conn)      # into an EMPTY bd schema; one transaction
    fixture_seed.reset_data(conn)         # empty every BD table, ids back to 1 (tests only)

It replaces BD's mock data. Everything here is invented: example.com emails (each account has its
own subdomain of example.com, so a shared email domain is something the duplicate check can see)
and 555-01xx phones. Real people never appear in this file: on staging, the seed command
(python -m bd.ops.seed) adds the real BD users from its command line.

What it holds on purpose (tests/test_bd_fixture_seed.py checks each):
  * every BD role, each held by a made-up person, plus one turned-off login;
  * LIKELY_DUPLICATE_PAIRS: two pairs of accounts whose cleaned names are equal
    ("Prairie Ridge Builders LLC" / "Prairie Ridge Builders, Inc.", and
    "Cottonwood & Sons Paving" / "Cottonwood Sons Paving Co.");
  * NEAR_MISS: "Cedar Creek Concrete" / "Cedar Crest Concrete", whose names differ but whose
    contacts share a phone number and an email domain (a hint alone never makes a pair);
  * MULTI_OWNER_ACCOUNT: one account whose people have three different owners;
  * MAINTENANCE_ONLY_ACCOUNT: one account whose people are all maintenance contacts;
  * a flagged duplicate contact, a co-owner with a login and one named without a login, an
    unowned contact, a contact on a cadence override, a phone call logged by nobody;
  * at least one row in every table the serializers read (backend/bd/serialize.py).
FIXTURE_TODAY is the day it reads best on (a Wednesday; its Friday batches are that week's).

Rows are written with their ids, then every identity sequence is moved past the highest id, so
rows added later never collide. It runs as bd_app (insert, plus UPDATE on the sequences).
"""
from __future__ import annotations

from typing import Any

FIXTURE_TODAY = "2026-11-04"

LIKELY_DUPLICATE_PAIRS = ((10, 11), (12, 13))
NEAR_MISS = (14, 15)
MULTI_OWNER_ACCOUNT = 16
MAINTENANCE_ONLY_ACCOUNT = 17

# Every BD table, children before parents, so plain DELETEs never trip a foreign key.
# bd.schema_migrations is never touched.
APP_TABLES = ("events", "tasks", "task_batches", "followup_drafts", "ai_recommendations",
              "integration_events", "unmatched_calls", "candidates", "interactions", "contacts",
              "account_pairs_kept", "companies", "imports", "settings", "users")
IDENTITY_TABLES = ("users", "companies", "contacts", "interactions", "task_batches", "tasks",
                   "ai_recommendations", "followup_drafts", "candidates", "unmatched_calls",
                   "events", "imports")
JSON_COLUMNS = frozenset({"payload", "errors", "data", "value", "import_values"})


def _ts(s: str) -> str:
    """A UTC moment, written plainly (the session time zone is UTC)."""
    return s + "+00:00"


# Insert order: parents first. Column names are the database's.
FIXTURE: dict[str, list[dict[str, Any]]] = {
    "users": [
        {"id": 1, "email": "avery.quill@example.com", "name": "Avery Quill", "role": "salesperson",
         "active": True, "last_seen_at": _ts("2026-11-03 15:02:00")},
        {"id": 2, "email": "blair.fenn@example.com", "name": "Blair Fenn", "role": "salesperson",
         "active": True, "last_seen_at": None},
        {"id": 3, "email": "casey.moret@example.com", "name": "Casey Moret", "role": "assistant",
         "active": True, "last_seen_at": _ts("2026-11-02 14:30:00")},
        {"id": 4, "email": "devon.hale@example.com", "name": "Devon Hale", "role": "manager",
         "active": True, "last_seen_at": _ts("2026-10-30 21:15:00")},
        {"id": 5, "email": "emery.stoll@example.com", "name": "Emery Stoll", "role": "admin",
         "active": True, "last_seen_at": None},
        {"id": 6, "email": "frankie.oduya@example.com", "name": "Frankie Oduya", "role": "super_admin",
         "active": True, "last_seen_at": None},
        {"id": 7, "email": "gale.ward@example.com", "name": "Gale Ward", "role": "salesperson",
         "active": False, "last_seen_at": _ts("2026-03-12 16:00:00")},
    ],
    "companies": [
        {"id": 10, "name": "Prairie Ridge Builders LLC", "city": "Overland Park", "industry": "General contractor"},
        {"id": 11, "name": "Prairie Ridge Builders, Inc.", "city": "Overland Park", "industry": "General contractor"},
        {"id": 12, "name": "Cottonwood & Sons Paving", "city": "Olathe", "industry": "Paving"},
        {"id": 13, "name": "Cottonwood Sons Paving Co.", "city": "Olathe", "industry": "Paving"},
        {"id": 14, "name": "Cedar Creek Concrete", "city": "Lawrence", "industry": "Concrete"},
        {"id": 15, "name": "Cedar Crest Concrete", "city": "Lawrence", "industry": "Concrete"},
        {"id": 16, "name": "Bluestem Logistics", "city": "Lenexa", "industry": "Warehousing"},
        {"id": 17, "name": "Kaw Valley Cold Storage", "city": "Topeka", "industry": "Food storage"},
        {"id": 18, "name": "Osage Plains Brewing", "city": "Manhattan", "industry": "Food and beverage"},
    ],
    "contacts": [
        {"id": 21, "company_id": 10, "name": "Dana Whitlow", "title": "Project Manager",
         "email": "dana.whitlow@prairieridge.example.com", "phone": "913-555-0101", "city": "Overland Park",
         "industry": "General contractor", "lead_source": "Referral", "stage": "Bidding", "category": "bd",
         "owner_id": 1, "frequency_per_year": 12, "confirmed": True, "importance": 3,
         "next_step": "Send the epoxy sample board", "next_step_date": "2026-11-06",
         "promised_date": "2026-11-05", "last_quote_date": "2026-10-15", "source": "workbook",
         "tags": ["key account", "epoxy"], "notes": "Prefers a call before nine."},
        {"id": 22, "company_id": 11, "name": "Rory Sandell", "title": "Estimator",
         "email": "rory.sandell@prairieridgebuilders.example.com", "phone": "(913) 555-0102",
         "category": "bd", "owner_id": 2, "source": "manual"},
        {"id": 23, "company_id": 12, "name": "Marisa Cole", "title": "Owner",
         "email": "marisa@cottonwoodpaving.example.com", "phone": "816.555.0103", "category": "bd",
         "owner_id": 1, "co_owner_id": 2, "importance": 2, "source": "workbook"},
        {"id": 24, "company_id": 13, "name": "Theo Banks", "title": "Operations",
         "email": "theo@cottonwoodpaving.example.com", "phone": "816 555 0104", "category": "bd",
         "owner_id": 2, "co_owner_name": "Jules", "source": "workbook"},
        {"id": 25, "company_id": 14, "name": "Priya Nandan", "title": "Superintendent",
         "email": "priya@cedarcreek.example.com", "phone": "785-555-0105", "category": "bd",
         "owner_id": 1, "source": "manual"},
        {"id": 26, "company_id": 15, "name": "Owen Pratt", "title": "Estimator",
         "email": "owen@cedarcreek.example.com", "phone": "+1 785 555 0105", "category": "bd",
         "owner_id": 2, "source": "manual"},
        {"id": 27, "company_id": 16, "name": "Lena Ortiz", "title": "Facilities Director",
         "email": "lena.ortiz@bluestem.example.com", "phone": "913-555-0107", "category": "bd",
         "owner_id": 1, "importance": 3, "cadence_override": "monthly", "cadence_override_until": "2026-12-31",
         "source": "workbook"},
        {"id": 28, "company_id": 16, "name": "Sam Achebe", "title": "Warehouse Manager",
         "email": "sam.achebe@bluestem.example.com", "phone": "913-555-0108", "category": "bd",
         "owner_id": 2, "source": "manual"},
        {"id": 29, "company_id": 16, "name": "Ines Varga", "title": "Purchasing",
         "email": "ines.varga@bluestem.example.com", "phone": "913-555-0109", "category": "bd",
         "owner_id": 4, "source": "manual"},
        {"id": 30, "company_id": 17, "name": "Hal Brecken", "title": "Plant Manager",
         "email": "hal@kawvalley.example.com", "phone": "785-555-0110", "category": "maintenance",
         "account_type": "Cold storage", "owner_id": 1, "source": "workbook"},
        {"id": 31, "company_id": 17, "name": "Nora Lindqvist", "title": "Maintenance Lead",
         "email": "nora@kawvalley.example.com", "phone": "785-555-0111", "category": "maintenance",
         "account_type": "Cold storage", "owner_id": 1, "frequency_per_year": 2, "source": "workbook"},
        {"id": 32, "company_id": 18, "name": "Wes Calder", "title": "Brewmaster",
         "email": "wes@osageplains.example.com", "phone": "913-555-0112", "category": "bd",
         "owner_id": None, "source": "import"},
        {"id": 33, "company_id": 11, "name": "D. Whitlow", "title": None,
         "email": "Dana.Whitlow@prairieridge.example.com", "phone": None, "category": "bd",
         "owner_id": 2, "duplicate_of": 21, "duplicate_reason": "Same email", "source": "import"},
    ],
    "interactions": [
        {"id": 101, "contact_id": 21, "kind": "call", "direction": "out", "outcome": "answered",
         "occurred_at": _ts("2026-10-20 15:00:00"), "duration_s": 420,
         "summary": "Talked through the spring floor schedule.", "user_id": 1},
        {"id": 102, "contact_id": 21, "kind": "voicemail", "direction": "out", "outcome": "voicemail",
         "occurred_at": _ts("2026-11-02 16:00:00"), "duration_s": 35, "summary": "Left a message.", "user_id": 1},
        {"id": 103, "contact_id": 23, "kind": "meeting", "direction": None, "outcome": None,
         "occurred_at": _ts("2026-06-15 14:00:00"), "summary": "Walked the lot.", "user_id": 1},
        {"id": 104, "contact_id": 25, "kind": "call", "direction": "in", "outcome": "no_answer",
         "occurred_at": _ts("2026-11-03 17:00:00"), "duration_s": 0, "provider": "quo",
         "external_id": "QX-0001", "user_id": None},
        {"id": 105, "contact_id": 27, "kind": "email", "direction": "out", "outcome": None,
         "occurred_at": _ts("2026-10-28 13:00:00"), "summary": "Sent the coating options.", "user_id": 2},
        {"id": 106, "contact_id": 30, "kind": "hosted", "direction": None, "outcome": None,
         "occurred_at": _ts("2026-06-10 22:00:00"), "summary": "Lunch and learn.", "user_id": 1},
        {"id": 107, "contact_id": 30, "kind": "call", "direction": "out", "outcome": "answered",
         "occurred_at": _ts("2026-08-20 15:00:00"), "duration_s": 300, "summary": "Checked the dock floor.",
         "user_id": 1, "followup_status": "sent", "followup_at": _ts("2026-08-20 16:00:00")},
        {"id": 108, "contact_id": 26, "kind": "sms", "direction": "out", "outcome": None,
         "occurred_at": _ts("2026-11-01 18:00:00"), "summary": "Sorry we missed you.", "user_id": 2},
    ],
    "task_batches": [
        {"id": 201, "owner_id": 1, "week_start": "2026-11-02", "kind": "friday",
         "generated_at": _ts("2026-10-30 21:00:00")},
        {"id": 202, "owner_id": 2, "week_start": "2026-11-02", "kind": "friday",
         "generated_at": _ts("2026-10-30 21:00:00")},
    ],
    "tasks": [
        {"id": 301, "batch_id": 201, "contact_id": 30, "kind": "maintenance", "score": 0,
         "reason": "Maintenance follow-up is due.", "reasons": ["Maintenance follow-up is due"], "status": "open"},
        {"id": 302, "batch_id": 201, "contact_id": 21, "kind": "followup", "score": 82,
         "reason": "Key account; quote out three weeks.", "reasons": ["Key account", "Quote out 3 weeks"],
         "status": "open"},
        {"id": 303, "batch_id": 201, "contact_id": 25, "kind": "new", "score": 41,
         "reason": "Never talked live.", "reasons": ["Never talked live"], "status": "done",
         "done_at": _ts("2026-11-03 18:00:00")},
        {"id": 304, "batch_id": 202, "contact_id": 22, "kind": "new", "score": 38,
         "reason": "Never talked live.", "reasons": ["Never talked live"], "status": "open"},
        {"id": 305, "batch_id": 202, "contact_id": 28, "kind": "followup", "score": 55,
         "reason": "Due this month.", "reasons": ["Due this month"], "status": "snoozed",
         "snoozed_until": "2026-11-10", "snooze_reason": "On vacation"},
    ],
    "ai_recommendations": [
        {"id": 401, "contact_id": 21, "interaction_id": 101, "action": "Send the spring schedule",
         "due_date": "2026-11-06", "reason": "Asked for it on the call.", "source": "ai", "status": "pending",
         "created_at": _ts("2026-10-20 15:10:00")},
        {"id": 402, "contact_id": 23, "interaction_id": 103, "action": "Quote the lot repair",
         "due_date": "2026-06-22", "reason": "Asked during the walk.", "source": "fallback",
         "status": "confirmed", "created_at": _ts("2026-06-15 15:00:00"),
         "decided_at": _ts("2026-06-16 14:00:00"), "decided_by": 4},
    ],
    "followup_drafts": [
        {"id": 501, "contact_id": 25, "interaction_id": 104, "channel": "email",
         "to_address": "priya@cedarcreek.example.com", "subject": "Sorry we missed your call",
         "body": "Hi Priya, sorry we missed you. When is a good time to call back?", "source": "fallback",
         "status": "draft"},
        {"id": 502, "contact_id": 26, "interaction_id": 108, "channel": "sms", "to_address": "+17855550105",
         "subject": None, "body": "Sorry we missed you. Call back any time.", "source": "ai", "status": "sent",
         "sent_at": _ts("2026-11-01 18:00:00")},
    ],
    "candidates": [
        {"id": 601, "project_id": "00000000-0000-4000-8000-000000000601",
         "project_name": "Prairie Ridge warehouse floor", "company": " Prairie Ridge Builders ",
         "contact_name": "Dana Whitlow", "email": "dana.whitlow@prairieridge.example.com",
         "phone": "913-555-0101", "quote_total": "48250.00", "quote_date": "2026-10-15", "status": "new",
         "possible_duplicate_id": 21, "origin": "pull", "payload": {"source": "fixture"}},
        {"id": 602, "project_id": "00000000-0000-4000-8000-000000000602",
         "project_name": "Juniper Hollow Dental remodel", "company": "Juniper Hollow Dental",
         "contact_name": "Ari Mendel", "email": "ari@juniperhollow.example.com", "phone": "913-555-0113",
         "quote_total": "12900.50", "quote_date": "2026-10-29", "status": "new", "origin": "push",
         "payload": {"source": "fixture"}},
    ],
    "imports": [
        {"id": 701, "file_name": "bd-fixture-import.csv", "dry_run": True,
         "started_at": _ts("2026-10-01 15:00:00"), "finished_at": _ts("2026-10-01 15:01:00"), "by_id": 5,
         "rows_read": 3, "created": 2, "updated": 0, "skipped": 1, "possible_duplicates": 1,
         "errors": [{"sheet": "CSV", "row": 4, "message": "No company name."}]},
    ],
    "unmatched_calls": [
        {"id": 801, "provider": "quo", "external_id": "QX-0002", "kind": "call", "direction": "in",
         "from_e164": "+19135550199", "occurred_at": _ts("2026-11-03 22:42:00"), "duration_s": 95,
         "summary": "Caller asked about a quote for a shop floor.", "status": "open"},
    ],
}


# Table and column names go into SQL as psycopg identifiers, never by string formatting (db.py's
# rule), even though they come from the constants above.
def _table(table: str) -> Any:
    from psycopg import sql

    return sql.Identifier("bd", table)


def _sequence_of(conn: Any, table: str) -> Any:
    """pg_get_serial_sequence's first argument: the quoted table name, as a string literal."""
    from psycopg import sql

    return sql.Literal(_table(table).as_string(conn))


def reset_data(conn: Any) -> None:
    """Empty every BD table and restart its ids at 1 (bd.schema_migrations is kept), in one round
    trip. Tests only: the seed command never deletes anything."""
    from psycopg import sql

    conn.execute(sql.SQL("; ").join(
        [sql.SQL("delete from {}").format(_table(t)) for t in APP_TABLES]
        + [sql.SQL("select setval(pg_get_serial_sequence({}, 'id'), 1, false)").format(_sequence_of(conn, t))
           for t in IDENTITY_TABLES]))


def _value(column: str, value: Any) -> Any:
    if column in JSON_COLUMNS:
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return value


def seed(conn: Any, people: Any = ()) -> dict:
    """Insert the fixture into an EMPTY bd schema, in one transaction, then the `people`
    [(email, name, role)] as active users after the made-up ones. Returns {table: row count}."""
    with conn.transaction():
        return _seed(conn, list(people))


def _seed(conn: Any, people: list) -> dict:
    from psycopg import sql

    from ..normalize import normalize_company

    rows_by_table = {t: [dict(r) for r in rows] for t, rows in FIXTURE.items()}
    for co in rows_by_table["companies"]:
        co["normalized_name"] = normalize_company(co["name"])
    duplicates = []
    for c in rows_by_table["contacts"]:          # the flag points at a contact: set it afterwards
        if c.get("duplicate_of") is not None:
            duplicates.append((c.pop("duplicate_of"), c.pop("duplicate_reason"), c["id"]))
    with conn.cursor() as cur:
        for table, rows in rows_by_table.items():
            for row in rows:
                cols = list(row)
                cur.execute(sql.SQL("insert into {} ({}) values ({})").format(
                    _table(table), sql.SQL(", ").join(map(sql.Identifier, cols)),
                    sql.SQL(", ").join(sql.Placeholder() * len(cols))),
                    [_value(c, row[c]) for c in cols])
        for dup, reason, cid in duplicates:
            cur.execute("update bd.contacts set duplicate_of = %s, duplicate_reason = %s where id = %s",
                        (dup, reason, cid))
        for table in IDENTITY_TABLES:
            bump_sequence(cur, table)
        for email, name, role in people:
            cur.execute("insert into bd.users (email, name, role, active) values (%s, %s, %s, true)",
                        (email, name, role))
        cur.execute(sql.SQL("select ") + sql.SQL(", ").join(
            sql.SQL("(select count(*) from {}) as {}").format(_table(t), sql.Identifier(t)) for t in FIXTURE))
        counts = cur.fetchone()
    values = [counts[t] for t in FIXTURE] if isinstance(counts, dict) else list(counts)
    return dict(zip(FIXTURE, values))


def bump_sequence(conn: Any, table: str) -> None:
    """Make `table`'s id identity continue after its highest id."""
    from psycopg import sql

    if table not in IDENTITY_TABLES:
        raise ValueError("not an identity table: %r" % table)
    conn.execute(sql.SQL(
        "select setval(pg_get_serial_sequence({seq}, 'id'),"
        " greatest((select coalesce(max(id), 0) from {t}), 1),"
        " (select count(*) > 0 from {t}))").format(seq=_sequence_of(conn, table), t=_table(table)))
