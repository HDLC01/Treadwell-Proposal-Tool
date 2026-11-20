"""The OLD BD database, for the cut-over copy's tests (#812). Not a test file.

    build_old(url)        BD's original four migrations (tests/fixtures/bd_old_migrations, vendored
                          unchanged), applied the way BD's own runner applied them: schema public,
                          the ledger public.schema_migrations, each file in its own transaction
    seed_old(url)         ROWS below, ids kept, then every identity sequence moved past its rows
                          (contacts' further on, to CONTACTS_SEQUENCE_AT, as if rows had been deleted)
    databases(admin)      a module's templates: one old database (built and seeded, sorting text
                          byte-wise as BD's alpine Postgres does) and one tool database (migrated by
                          the runner, the bd_app-like login ready, sorting text the ICU en-US way)
    clone(admin, tpl)     a fresh database copied from a template, dropped afterwards
    templates, dbs        the cut-over tests' fixtures (a module's two templates; a test's two clones,
                          the bd_app-like login's url and two record paths), with the plain readings
                          they share: scalar, columns_of, rows, bd_counts, refused_lines

ROWS is made up and covers every table the old app has, with the awkward values on purpose: nulls
next to empty strings, odd text (quotes, a backslash, a tab, a newline, an emoji, accents, the word
NULL inside an array), json and jsonb (1.10 that a float would turn into 1.1, nested keys out of
order), numerics with their scale, timestamps on both sides of the 2026 DST changes in Central time
(01:30 on 2026-11-01 happens twice) and with microseconds, generated columns, a self-reference to
a HIGHER id (contact 54 is flagged as a duplicate of 58), events and settings.

Every free-text value a person typed carries the marker "ZQ", so a test can prove the command never
prints row data; people's names, emails and phones are listed in PERSONAL. Company names never carry
it: the duplicates list prints account names by design. Everything is invented: example.com emails,
555-01xx phones.

THE DUPLICATES WORKED EXAMPLE (the Possible duplicates rule, by hand, before any code ran):
    42 "Harrow & Finch Glazing Inc."  / 43 "Harrow and Finch Glazing"   -> pair, both clean to
        harrow finch glazing ("&" and "and" go, Inc goes); Persephone (42) and Lucan (43) share the
        domain harrowfinch.example.com, not a phone: hint "email domain"
    40 "Juniper Ridge Const. LLC"     / 41 "Juniper Ridge Construction" -> pair (LLC goes, "Const."
        is Construction); Thessaly (40) and Orrin (41) share +18165550141 written two ways, their
        domains differ: hint "phone"
    44 "Saltmarsh Mechanical" / 45 "Saltmarsh Electrical": the near miss. Ingrid and Caspian share a
        phone and a domain, but the names differ: no pair
    46 "Quarry Lane Storage" / 47 "Quarry Lane Storage, Inc.": the names match, but both hold only
        maintenance people, so neither is on the BD tab: no pair
    48 a lone account
In cleaned-name order: 42/43 first, then 40/41.
"""
from __future__ import annotations

import contextlib
import pathlib
import types

import pytest

import _bd_db

OLD_MIGRATIONS = pathlib.Path(__file__).resolve().parent / "fixtures" / "bd_old_migrations"
CONTACTS_SEQUENCE_AT = 75     # the old contacts sequence had handed out 75 (rows 60-75 were deleted)

EXPECTED_PAIRS = [
    (42, "Harrow & Finch Glazing Inc.", 43, "Harrow and Finch Glazing", "email domain"),
    (40, "Juniper Ridge Const. LLC", 41, "Juniper Ridge Construction", "phone"),
]

ODD = "Line one\nLine two\ttabbed, \"double\" 'single' back\\slash ZQ \U0001F9F1 café  end "


def _ts(s: str) -> str:
    return s + "+00"


class RawJson(str):
    """JSON text inserted as written, so 1.10 stays 1.10 (a Python float would make it 1.1)."""


# Insert order: parents first. Column names are the old database's. contacts.duplicate_of is set
# after every contact is in (it points at a higher id).
ROWS: dict = {
    "users": [
        {"id": 1, "email": "marlo.quint@example.com", "name": "Marlo Quint", "role": "salesperson",
         "active": True, "auth_sub": "sub-ZQ-0001", "last_seen_at": _ts("2026-11-01 06:30:00.123456"),
         "created_at": _ts("2026-01-05 15:00:00")},
        {"id": 2, "email": "tamsin.okafor@example.com", "name": "Tamsin Okafor", "role": "assistant",
         "active": True, "auth_sub": None, "last_seen_at": None, "created_at": _ts("2026-01-05 15:00:01")},
        {"id": 3, "email": "ziggy.halvorsen@example.com", "name": "Ziggy Halvorsen", "role": "admin",
         "active": False, "auth_sub": "", "last_seen_at": _ts("2026-03-08 07:59:59"),
         "created_at": _ts("2026-01-05 15:00:02")},
    ],
    "companies": [
        {"id": 40, "name": "Juniper Ridge Const. LLC", "normalized_name": "juniper ridge const",
         "city": "Lee's Summit", "industry": "General contractor", "created_at": _ts("2026-02-01 12:00:00")},
        {"id": 41, "name": "Juniper Ridge Construction", "normalized_name": "juniper ridge construction",
         "city": None, "industry": None, "created_at": _ts("2026-02-01 12:00:00")},
        {"id": 42, "name": "Harrow & Finch Glazing Inc.", "normalized_name": "harrow finch glazing",
         "city": "Olathe", "industry": "Glazing", "created_at": _ts("2026-03-08 08:00:00")},
        {"id": 43, "name": "Harrow and Finch Glazing", "normalized_name": "harrow and finch glazing",
         "city": "Olathe", "industry": "", "created_at": _ts("2026-03-08 08:00:00")},
        {"id": 44, "name": "Saltmarsh Mechanical", "normalized_name": "saltmarsh mechanical",
         "city": "Lawrence", "industry": "Mechanical", "created_at": _ts("2026-04-01 12:00:00")},
        {"id": 45, "name": "Saltmarsh Electrical", "normalized_name": "saltmarsh electrical",
         "city": "Lawrence", "industry": "Electrical", "created_at": _ts("2026-04-01 12:00:00")},
        {"id": 46, "name": "Quarry Lane Storage", "normalized_name": "quarry lane storage",
         "city": "Topeka", "industry": "Cold storage", "created_at": _ts("2026-05-01 12:00:00")},
        {"id": 47, "name": "Quarry Lane Storage, Inc.", "normalized_name": "quarry lane storage",
         "city": "Topeka", "industry": "Cold storage", "created_at": _ts("2026-05-01 12:00:00")},
        {"id": 48, "name": "Velvetleaf Dental", "normalized_name": "velvetleaf dental",
         "city": "Manhattan", "industry": "Dental", "created_at": _ts("2026-11-01 07:30:00")},
    ],
    "contacts": [
        {"id": 51, "company_id": 40, "name": "Thessaly Brookhart", "title": "Chief Estimator ZQ",
         "email": "thessaly.brookhart@juniperridge.example.com", "phone": "(816) 555-0141",
         "city": "Lee's Summit", "industry": "General contractor", "lead_source": "Referral",
         "stage": "Bidding", "category": "bd", "account_type": None, "owner_id": 1, "co_owner_id": 2,
         "co_owner_name": None, "frequency_per_year": 12, "confirmed": True, "importance": 3,
         "next_step": "Send the ZQ sample board", "next_step_date": "2026-11-06", "promised_date": "2026-11-05",
         "last_quote_date": "2026-10-15", "source": "workbook",
         "tags": ["key account", "a,b", "NULL", None, "quote\"d ZQ", ""], "notes": ODD,
         "archived_at": None, "created_at": _ts("2026-02-01 12:00:00"),
         "import_values": RawJson('{"title": "Chief Estimator ZQ", "ratio": 1.10, "z": [1, null], "a": "ü"}'),
         "cadence_override": None, "cadence_override_until": None},
        {"id": 52, "company_id": 41, "name": "Orrin Valdemar", "title": None,
         "email": "orrin@valdemar-mail.example.com", "phone": "816.555.0141", "category": "bd", "owner_id": 1,
         "frequency_per_year": 4, "source": "manual", "tags": [], "notes": "",
         "created_at": _ts("2026-02-02 12:00:00")},
        {"id": 53, "company_id": 42, "name": "Persephone Ashgrove", "title": "Owner ZQ",
         "email": "persephone@harrowfinch.example.com", "phone": "913-555-0143", "category": "bd", "owner_id": 2,
         "frequency_per_year": 4, "importance": 2, "cadence_override": "monthly",
         "cadence_override_until": "2026-12-31", "source": "workbook", "notes": "Prefers ZQ texts.",
         "created_at": _ts("2026-03-08 07:59:59")},
        {"id": 54, "company_id": 43, "name": "Lucan Merriweather", "title": "Operations ZQ",
         "email": "lucan@harrowfinch.example.com", "phone": "913 555 0144", "category": "bd", "owner_id": 1,
         "co_owner_name": "Jules ZQ", "frequency_per_year": 4, "duplicate_of": 58,
         "duplicate_reason": "Same email", "source": "import", "created_at": _ts("2026-03-08 08:00:00")},
        {"id": 55, "company_id": 44, "name": "Ingrid Solvang", "email": "ingrid@saltmarsh.example.com",
         "phone": "+1 785 555 0145", "category": "bd", "owner_id": 2, "frequency_per_year": 4,
         "source": "manual", "created_at": _ts("2026-04-01 12:00:00")},
        {"id": 56, "company_id": 45, "name": "Caspian Thorne", "email": "caspian@saltmarsh.example.com",
         "phone": "785-555-0145", "category": "bd", "owner_id": 1, "frequency_per_year": 4,
         "source": "manual", "created_at": _ts("2026-04-01 12:00:01")},
        {"id": 57, "company_id": 46, "name": "Wilhelmina Featherstone", "title": "Plant Manager ZQ",
         "email": "wilhelmina@quarrylane.example.com", "phone": "785-555-0147", "category": "maintenance",
         "account_type": "Cold storage", "owner_id": 1, "frequency_per_year": 3, "source": "workbook",
         "created_at": _ts("2026-05-01 12:00:00")},
        {"id": 58, "company_id": 47, "name": "Bartholomew Eckhart", "title": None,
         "email": "Bart.Eckhart@QuarryLane.Example.com", "phone": "  ", "category": "maintenance",
         "owner_id": 2, "frequency_per_year": 2, "source": "workbook", "created_at": _ts("2026-05-01 12:00:01")},
        {"id": 59, "company_id": 48, "name": "Seraphina Odhiambo", "title": "Office ZQ", "email": "",
         "phone": "1-913-555-0149", "category": "bd", "owner_id": None, "frequency_per_year": 52,
         "source": "proposal_tool", "archived_at": _ts("2026-03-08 08:00:00"),
         "created_at": _ts("2026-11-01 06:59:59.999999")},
    ],
    "interactions": [
        {"id": 101, "contact_id": 51, "kind": "call", "direction": "out", "outcome": "answered",
         "occurred_at": _ts("2026-03-08 07:59:59"), "duration_s": 420, "summary": "Spoke about the ZQ floor.",
         "user_id": 1, "created_at": _ts("2026-03-08 07:59:59")},
        {"id": 102, "contact_id": 51, "kind": "voicemail", "direction": "out", "outcome": "voicemail",
         "occurred_at": _ts("2026-03-08 08:00:00"), "duration_s": 35, "summary": "Left a ZQ message.",
         "user_id": 1, "created_at": _ts("2026-03-08 08:00:00")},
        {"id": 103, "contact_id": 53, "kind": "meeting", "occurred_at": _ts("2026-11-01 06:30:00"),
         "summary": "Walked the ZQ site.", "transcript": ODD, "user_id": 2, "created_at": _ts("2026-11-01 06:30:00")},
        {"id": 104, "contact_id": 53, "kind": "call", "direction": "in", "outcome": "no_answer",
         "occurred_at": _ts("2026-11-01 07:30:00"), "duration_s": 0, "provider": "quo", "external_id": "QZ-0001",
         "user_id": None, "created_at": _ts("2026-11-01 07:30:00")},
        {"id": 105, "contact_id": 57, "kind": "hosted", "occurred_at": _ts("2026-06-10 22:00:00.5"),
         "summary": "Lunch and learn ZQ.", "user_id": 1, "created_at": _ts("2026-06-10 22:00:00.5")},
        {"id": 106, "contact_id": 55, "kind": "email", "direction": "out", "occurred_at": _ts("2026-10-28 13:00:00"),
         "summary": "Sent the ZQ options.", "recording_url": "https://recordings.example.com/zq/106",
         "user_id": 2, "created_at": _ts("2026-10-28 13:00:00")},
        {"id": 107, "contact_id": 52, "kind": "sms", "direction": "out", "occurred_at": _ts("2026-11-02 18:00:00"),
         "summary": "Sorry we missed you ZQ.", "user_id": 1, "followup_status": "sent",
         "followup_at": _ts("2026-11-02 18:05:00"), "created_at": _ts("2026-11-02 18:00:00")},
        {"id": 108, "contact_id": 51, "kind": "note", "occurred_at": _ts("2026-11-03 17:00:00"), "summary": "",
         "user_id": 3, "created_at": _ts("2026-11-03 17:00:00")},
    ],
    "task_batches": [
        {"id": 201, "owner_id": 1, "week_start": "2026-11-02", "kind": "friday",
         "generated_at": _ts("2026-10-30 21:00:00")},
        {"id": 202, "owner_id": 1, "week_start": "2026-10-26", "kind": "friday",
         "generated_at": _ts("2026-10-23 21:00:00"), "replaced_at": _ts("2026-10-24 15:00:00")},
        {"id": 203, "owner_id": 1, "week_start": "2026-10-26", "kind": "friday",
         "generated_at": _ts("2026-10-24 15:00:00")},
        {"id": 204, "owner_id": 2, "week_start": "2026-11-02", "kind": "ten_more",
         "generated_at": _ts("2026-11-03 15:00:00")},
    ],
    "tasks": [
        {"id": 301, "batch_id": 201, "contact_id": 51, "kind": "followup", "reason": "Key account ZQ.",
         "reasons": ["Key account", "Quote out 3 weeks"], "score": 82, "status": "open",
         "created_at": _ts("2026-10-30 21:00:00")},
        {"id": 302, "batch_id": 201, "contact_id": 57, "kind": "maintenance", "reason": "",
         "reasons": [], "score": 0, "status": "open", "created_at": _ts("2026-10-30 21:00:00")},
        {"id": 303, "batch_id": 203, "contact_id": 53, "kind": "new", "reason": "Never talked live ZQ.",
         "reasons": ["Never talked live"], "score": 41, "status": "done",
         "done_at": _ts("2026-10-27 18:00:00"), "created_at": _ts("2026-10-24 15:00:00")},
        {"id": 304, "batch_id": 202, "contact_id": 52, "kind": "new", "reason": "Old batch.",
         "reasons": ["Never talked live"], "score": 38, "status": "snoozed", "snoozed_until": "2026-11-10",
         "snooze_reason": "Away ZQ", "closed_by_archive": True, "created_at": _ts("2026-10-23 21:00:00")},
        {"id": 305, "batch_id": 204, "contact_id": 56, "kind": "followup", "reason": "Ten more.",
         "reasons": ["Due"], "score": 10, "status": "open", "created_at": _ts("2026-11-03 15:00:00")},
    ],
    "ai_recommendations": [
        {"id": 401, "contact_id": 51, "interaction_id": 101, "action": "Send the ZQ schedule",
         "due_date": "2026-11-06", "reason": "Asked on the ZQ call.", "source": "ai", "status": "pending",
         "created_at": _ts("2026-03-08 08:10:00")},
        {"id": 402, "contact_id": 53, "interaction_id": None, "action": "Quote the ZQ repair",
         "due_date": None, "reason": "", "source": "fallback", "status": "confirmed",
         "created_at": _ts("2026-11-01 06:45:00"), "decided_at": _ts("2026-11-01 07:45:00"), "decided_by": 2},
    ],
    "followup_drafts": [
        {"id": 501, "contact_id": 53, "interaction_id": 104, "channel": "email",
         "to_address": "persephone@harrowfinch.example.com", "subject": "Sorry we missed your ZQ call",
         "body": "Hi Persephone, when is a good ZQ time?", "source": "fallback", "status": "draft",
         "created_at": _ts("2026-11-01 07:35:00")},
        {"id": 502, "contact_id": 52, "interaction_id": 107, "channel": "sms", "to_address": "+18165550141",
         "subject": None, "body": "Call back any time ZQ.", "source": "ai", "status": "sent",
         "sent_interaction_id": 107, "created_at": _ts("2026-11-02 17:55:00"), "sent_at": _ts("2026-11-02 18:00:00")},
    ],
    "candidates": [
        {"id": 601, "project_id": "00000000-0000-4000-8000-000000000601", "project_name": "ZQ warehouse floor",
         "company": " Juniper Ridge ", "contact_name": "Thessaly Brookhart",
         "email": "thessaly.brookhart@juniperridge.example.com", "phone": "816-555-0141",
         "quote_total": "48250.00", "quote_date": "2026-10-15", "status": "new", "possible_duplicate_id": 51,
         "origin": "pull", "payload": RawJson('{"source": "ZQ fixture", "amounts": [0.10, 1000, -2.5e-3],'
                                              ' "nested": {"z": 1, "a": "ü", "m": null}}'),
         "created_at": _ts("2026-10-15 15:00:00")},
        {"id": 602, "project_id": "00000000-0000-4000-8000-000000000602", "project_name": None,
         "company": "Velvetleaf Dental", "contact_name": "Seraphina Odhiambo", "email": None, "phone": None,
         "quote_total": None, "quote_date": None, "status": "added", "contact_id": 59, "origin": "push",
         "payload": {}, "added_by": 1, "created_at": _ts("2026-10-29 15:00:00"),
         "decided_at": _ts("2026-10-30 15:00:00")},
        {"id": 603, "project_id": "00000000-0000-4000-8000-000000000603", "project_name": "ZQ dock",
         "company": "Harrow & Finch", "contact_name": "Lucan Merriweather", "email": "lucan@harrowfinch.example.com",
         "phone": "913-555-0144", "quote_total": "0.10", "quote_date": "2026-11-01", "status": "ignored",
         "origin": "pull", "payload": {"k": "ZQ"}, "created_at": _ts("2026-11-01 07:00:00")},
    ],
    "integration_events": [
        {"provider": "quo", "event_id": "evt-ZQ-2", "event_type": None, "received_at": _ts("2026-11-01 07:31:00"),
         "payload": {}, "result": "unmatched", "interaction_id": None},
        {"provider": "quo", "event_id": "evt-ZQ-1", "event_type": "call.completed",
         "received_at": _ts("2026-11-01 07:30:30"),
         "payload": {"id": "evt-ZQ-1", "call": {"from": "+19135550199", "seconds": 0}},
         "result": "interaction_created", "interaction_id": 104},
        {"provider": "Quo", "event_id": "evt-ZQ-1", "event_type": "sms.received",
         "received_at": _ts("2026-11-02 18:00:00"), "payload": {"text": "ZQ"}, "result": "ignored",
         "interaction_id": None},
    ],
    "unmatched_calls": [
        {"id": 801, "provider": "quo", "external_id": "QZ-0002", "kind": "call", "direction": "in",
         "from_e164": "+19135550199", "occurred_at": _ts("2026-11-03 22:42:00"), "duration_s": 95,
         "summary": "Caller asked about a ZQ quote.", "status": "open", "created_at": _ts("2026-11-03 22:43:00")},
        {"id": 802, "provider": "quo", "external_id": None, "kind": "sms", "direction": "in",
         "from_e164": "+18165550141", "occurred_at": _ts("2026-11-02 18:01:00"), "summary": "ZQ reply",
         "status": "attached", "attached_interaction_id": 107, "handled_by": 2,
         "handled_at": _ts("2026-11-02 19:00:00"), "created_at": _ts("2026-11-02 18:01:00")},
    ],
    "settings": [
        {"key": "bd_cadence", "value": "monthly", "updated_at": _ts("2026-03-08 08:30:00"), "updated_by": 3},
        {"key": "default_frequency", "value": {"maintenance": 3}, "updated_at": _ts("2026-01-05 15:00:00"),
         "updated_by": None},
        {"key": "lead_sources", "value": ["Referral", "Web", "Other/Misc"],
         "updated_at": _ts("2026-11-01 06:30:00"), "updated_by": 1},
        {"key": "Weekly", "value": {"day": "friday", "hour": 16, "note": "tab\there \"q\" é ZQ"},
         "updated_at": _ts("2026-11-01 07:30:00"), "updated_by": None},
    ],
    "events": [
        {"id": 901, "kind": "created", "actor_id": 1, "contact_id": 51, "detail": "Added ZQ by hand.",
         "data": {"source": "manual"}, "at": _ts("2026-02-01 12:00:00")},
        {"id": 902, "kind": "imported", "actor_id": None, "contact_id": None, "detail": None, "data": {},
         "at": _ts("2026-11-01 06:30:00")},
        {"id": 903, "kind": "edited", "actor_id": 2, "contact_id": 58, "detail": "Changed the ZQ title.",
         "data": RawJson('{"fields": ["title", "notes"], "before": {"title": null, "n": 1.10}}'),
         "at": _ts("2026-11-01 07:30:00")},
    ],
    "imports": [
        {"id": 701, "file_name": "bd-zq-import.csv", "dry_run": True, "started_at": _ts("2026-10-01 15:00:00"),
         "finished_at": _ts("2026-10-01 15:01:00"), "by_id": 3, "rows_read": 3, "created": 2, "updated": 0,
         "skipped": 1, "possible_duplicates": 1,
         "errors": [{"sheet": "CSV", "row": 4, "message": "No company name ZQ."}]},
        {"id": 702, "file_name": "workbook.xlsx", "dry_run": False, "started_at": _ts("2026-10-02 15:00:00"),
         "finished_at": None, "by_id": None, "errors": []},
    ],
}

IDENTITY_TABLES = ("users", "companies", "contacts", "interactions", "task_batches", "tasks",
                   "ai_recommendations", "followup_drafts", "candidates", "unmatched_calls", "events", "imports")
JSON_COLUMNS = {("contacts", "import_values"), ("candidates", "payload"), ("integration_events", "payload"),
                ("settings", "value"), ("events", "data"), ("imports", "errors")}

# People's details the command must never print (with every "ZQ" value).
PERSONAL = sorted({r[c] for t in ("users", "contacts") for r in ROWS[t] for c in ("name", "email", "phone")
                   if isinstance(r.get(c), str) and r[c].strip()}
                  | {r["contact_name"] for r in ROWS["candidates"]})


# ── building it ─────────────────────────────────────────────────────────────────────────────────
def build_old(url: str) -> None:
    """BD's own runner (backend/migrate.py in the BD repo), as it ran on the old server."""
    with _bd_db.connect(url) as conn:
        conn.execute("create table if not exists schema_migrations ("
                     " name text primary key, applied_at timestamptz not null default now())")
        for path in sorted(OLD_MIGRATIONS.glob("*.sql")):
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))


def _value(table: str, column: str, value):
    if isinstance(value, RawJson):
        return str(value)
    if (table, column) in JSON_COLUMNS:
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return value


def insert_rows(conn, schema: str, rows: dict) -> None:
    """Plain INSERTs of `rows` ({table: [row dict]}) into schema.table, a self-reference second."""
    from psycopg import sql

    later = []
    for table, items in rows.items():
        for row in items:
            row = dict(row)
            if table == "contacts" and row.get("duplicate_of") is not None:
                later.append((row.pop("duplicate_of"), row.pop("duplicate_reason"), row["id"]))
            cols = list(row)
            conn.execute(sql.SQL("insert into {} ({}) values ({})").format(
                sql.Identifier(schema, table), sql.SQL(", ").join(map(sql.Identifier, cols)),
                sql.SQL(", ").join(sql.Placeholder() * len(cols))), [_value(table, c, row[c]) for c in cols])
    for dup, reason, cid in later:
        conn.execute(sql.SQL("update {} set duplicate_of = %s, duplicate_reason = %s where id = %s").format(
            sql.Identifier(schema, "contacts")), (dup, reason, cid))


def seed_old(url: str) -> None:
    from psycopg import sql

    with _bd_db.connect(url) as conn, conn.transaction():
        conn.execute("set local timezone = 'UTC'")
        insert_rows(conn, "public", ROWS)
        for table in IDENTITY_TABLES:
            conn.execute(sql.SQL("select setval(pg_get_serial_sequence({}, 'id'), (select max(id) from {}))").format(
                sql.Literal("public." + table), sql.Identifier("public", table)))
        conn.execute("select setval(pg_get_serial_sequence('public.contacts', 'id'), %s)", (CONTACTS_SEQUENCE_AT,))


# ── databases for a test module ─────────────────────────────────────────────────────────────────
@contextlib.contextmanager
def databases(admin: str):
    """{"old": template name, "tool": template name}: the old database built and seeded, the tool's
    migrated by the runner. Both dropped afterwards."""
    _bd_db.ensure_app_login(admin)
    with _bd_db.new_database(admin) as old, _icu_database(admin) as tool:
        build_old(old)
        seed_old(old)
        with _bd_db.cluster_lock(admin, exclusive=False):
            _bd_db.migrate(tool)
        yield {"old": _bd_db.dbname(old), "tool": _bd_db.dbname(tool)}


def _icu_database(admin: str):
    """An empty database whose default collation is ICU's en-US, where "quo" sorts before "Quo" and
    "Weekly" after "lead_sources" (prod's Supabase sorts like that). The old database sorts
    byte-wise, as BD's alpine Postgres does, so every test copies between two different orders."""
    return _bd_db.new_database(admin, template="template0",
                               options="locale_provider icu icu_locale 'en-US' locale 'C'")


def clone(admin: str, template: str):
    """A fresh database copied from `template` (which must have no open connection), dropped after.
    Yields its admin url."""
    return _bd_db.new_database(admin, template=template)


def table_rows(url: str, schema: str, table: str, columns: list, order: str) -> list:
    """Every row of schema.table as text, read plainly (an independent reading, not the command's)."""
    from psycopg import sql

    with _bd_db.connect(url) as conn:
        conn.execute("set timezone = 'UTC'")
        return [tuple(r) for r in conn.execute(sql.SQL("select {} from {} order by " + order).format(
            sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in columns),
            sql.Identifier(schema, table))).fetchall()]


# ── the cut-over tests' fixtures (import them by name: from _bd_old_source import dbs, templates) ──
@pytest.fixture(scope="module")
def templates(bd_admin):
    with databases(bd_admin) as names:
        yield names


@pytest.fixture
def dbs(bd_admin, templates, tmp_path):
    """The test's own old database and tool database (clones of the module's templates), the
    bd_app-like login's url on the tool database, and two record paths (a cut-over, a re-cut-over)."""
    with clone(bd_admin, templates["old"]) as old, clone(bd_admin, templates["tool"]) as tool:
        yield types.SimpleNamespace(old=old, tool=tool, app=_bd_db.app_login_url(tool),
                                    record=tmp_path / "cutover-record.json",
                                    record2=tmp_path / "recutover-record.json")


# ── plain readings (not the command's code) ─────────────────────────────────────────────────────
def scalar(url: str, query: str, params=None):
    with _bd_db.connect(url) as conn:
        return conn.execute(query, params).fetchone()[0]


def columns_of(url: str, schema: str, table: str) -> list:
    """The table's columns in the database's own order, from the catalog (not the command's map)."""
    with _bd_db.connect(url) as conn:
        return [r[0] for r in conn.execute(
            "select a.attname from pg_attribute a join pg_class c on c.oid = a.attrelid"
            " join pg_namespace n on n.oid = c.relnamespace where n.nspname = %s and c.relname = %s"
            " and a.attnum > 0 and not a.attisdropped order by a.attnum", (schema, table)).fetchall()]


ORDER = {"settings": 'key collate "C"', "schema_migrations": "name",
         "integration_events": 'provider collate "C", event_id collate "C"'}


def rows(url: str, schema: str, table: str, cols: list) -> list:
    return table_rows(url, schema, table, cols, ORDER.get(table, "id"))


def bd_counts(url: str) -> dict:
    """{table: rows} for every table in schema bd but the ledger."""
    with _bd_db.connect(url) as conn:
        tables = [r[0] for r in conn.execute(
            "select relname from pg_class where relnamespace = 'bd'::regnamespace and relkind = 'r'"
            " and relname <> 'schema_migrations' order by 1").fetchall()]
        return {t: conn.execute("select count(*) from bd.%s" % t).fetchone()[0] for t in tables}


def refused_lines(err: str) -> list:
    return [x for x in err.splitlines() if x.startswith("refusing")]
