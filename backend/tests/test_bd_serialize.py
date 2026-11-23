"""bd/serialize.py: database rows -> the contract's JSON objects.

EVERY router builds its answers with these functions, so the exact key set, the JSON types and the
null-vs-missing rules of each object can only drift in one place, and these tests pin it there.

Two halves:

1. PURE (no database, no node). Hand-built row dicts go through every serializer. For each shape:
   the exact key set (also compared with the JSON example in docs/bd/api-contract.md), the JSON type of
   every field, `json.dumps` cleanly (no Decimal, date or datetime object leaks out), the defaults
   for nulls, and a KeyError for a REQUIRED column that went missing (so a schema drift fails loudly)
   while the optional ones (read with .get) never raise. Timestamps leave in Central with the offset
   THAT moment had, across both DST changes.
2. DATABASE (the bd_seeded fixture: the fixture seed, backend/bd/ops/fixture_seed.py, read as the
   bd_app-like login; skipped locally without BD_TEST_DATABASE_URL): every *_SELECT produces each
   column its serializer reads, and the fetch_* helpers join and filter correctly.

Everything is fictional: 555-01xx phones, example.com emails. No clock is read; every moment is given.
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import pathlib
import re

import pytest
from psycopg.sql import SQL

from bd import serialize
from bd.bizdate import iso_date
from bd.ops import fixture_seed

UTC = dt.UTC
D = decimal.Decimal
ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = (ROOT / "docs" / "bd" / "api-contract.md").read_text(encoding="utf-8")

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


# ── JSON type predicates (a bool is not an int here: `type(v) is int`) ─────────────────────────
def is_int(v):
    return type(v) is int


def is_str(v):
    return type(v) is str


def is_bool(v):
    return type(v) is bool


def is_num(v):
    return type(v) in (int, float)


def is_dict(v):
    return type(v) is dict


def is_str_list(v):
    return type(v) is list and all(type(x) is str for x in v)


def is_ts(v):
    return type(v) is str and bool(TS_RE.match(v))


def is_date(v):
    return type(v) is str and bool(DATE_RE.match(v))


def opt(pred):
    return lambda v: v is None or pred(v)


def check_shape(out, spec):
    """`out` has EXACTLY the spec's keys, each of the right JSON type, and survives json.dumps."""
    assert set(out) == set(spec), "extra: %s, missing: %s" % (sorted(set(out) - set(spec)),
                                                                sorted(set(spec) - set(out)))
    for key, pred in spec.items():
        assert pred(out[key]), "%s has the wrong JSON type: %r" % (key, out[key])
    assert json.loads(json.dumps(out, allow_nan=False)) == out
    return out


USER_SPEC = {"id": is_int, "name": is_str, "email": is_str, "role": is_str, "active": is_bool,
             "last_seen_at": opt(is_ts)}
USER_COMPACT_SPEC = {"id": is_int, "name": is_str, "role": is_str}
COMPANY_SPEC = {"id": is_int, "name": is_str, "city": opt(is_str), "industry": opt(is_str),
                "created_at": opt(is_ts), "contact_count": is_int}
REF_SPEC = {"id": is_int, "name": is_str}
USER_REF_SPEC = {"id": opt(is_int), "name": opt(is_str)}
CONTACT_SPEC = {
    "id": is_int, "company": is_dict, "name": is_str, "title": opt(is_str), "email": opt(is_str),
    "phone": opt(is_str), "phone_e164": opt(is_str), "city": opt(is_str), "industry": opt(is_str),
    "lead_source": opt(is_str), "stage": opt(is_str), "category": is_str, "account_type": opt(is_str),
    "owner": opt(is_dict), "co_owner": opt(is_dict), "frequency_per_year": is_int, "confirmed": is_bool,
    "importance": is_int, "next_step": opt(is_str), "next_step_date": opt(is_date),
    "promised_date": opt(is_date), "last_quote_date": opt(is_date), "last_live_at": opt(is_ts),
    "last_attempt_at": opt(is_ts), "attempts_since_live": is_int, "touches_this_year": is_int,
    "next_due_date": opt(is_date), "cadence_status": is_str, "duplicate_of": opt(is_dict),
    "source": is_str, "tags": is_str_list, "notes": is_str, "created_at": opt(is_ts),
    "cadence": opt(is_str), "cadence_source": opt(is_str), "cadence_override": opt(is_str),
    "cadence_override_until": opt(is_date), "last_followup_at": opt(is_ts),
    "maintenance_due_date": opt(is_date), "maintenance_due": is_bool,
}
CONTACT_COMPACT_SPEC = {
    "id": is_int, "name": is_str, "title": opt(is_str), "company": is_dict, "phone": opt(is_str),
    "phone_e164": opt(is_str), "email": opt(is_str), "category": is_str, "confirmed": is_bool,
    "lead_source": opt(is_str), "last_live_at": opt(is_ts), "cadence_status": is_str,
}
CONTACT_REF_SPEC = {"id": is_int, "name": is_str, "company": is_dict}
DUPLICATE_MATCH_SPEC = {"contact_id": is_int, "name": is_str, "company": is_str, "city": opt(is_str),
                        "reason": is_str}
INTERACTION_SPEC = {
    "id": is_int, "contact_id": is_int, "contact": is_dict, "kind": is_str, "direction": opt(is_str),
    "counts_as_touch": is_bool, "occurred_at": is_ts, "duration_s": opt(is_int), "outcome": opt(is_str),
    "summary": opt(is_str), "transcript": opt(is_str), "recording_url": opt(is_str), "provider": is_str,
    "external_id": opt(is_str), "user": opt(is_dict),
}
BATCH_SPEC = {"id": is_int, "kind": is_str, "owner": is_dict, "week_start": is_date, "generated_at": is_ts}
TASK_SPEC = {"id": is_int, "batch_id": is_int, "contact": opt(is_dict), "kind": is_str, "reason": is_str,
             "reasons": is_str_list, "score": is_int, "status": is_str, "done_at": opt(is_ts),
             "snoozed_until": opt(is_date)}
WEEK_ROW_PERSON_SPEC = {
    "id": is_int, "name": is_str, "title": opt(is_str), "phone": opt(is_str), "phone_e164": opt(is_str),
    "email": opt(is_str), "confirmed": is_bool, "last_live_at": opt(is_ts), "attempts_since_live": is_int,
    "promised_date": opt(is_date), "next_step": opt(is_str), "next_step_date": opt(is_date),
    "task_id": opt(is_int), "not_right_person": is_bool,
}
WEEK_ROW_SPEC = {
    "id": is_int, "section": is_str, "batch_id": is_int, "task_ids": lambda v: type(v) is list and all(map(is_int, v)),
    "kind": is_str, "status": is_str, "done_at": opt(is_ts), "snoozed_until": opt(is_date), "reason": is_str,
    "reasons": is_str_list, "score": is_int, "company": is_dict, "misses": is_int, "last_live_at": opt(is_ts),
    "people": lambda v: type(v) is list,
}
RECOMMENDATION_SPEC = {
    "id": is_int, "contact_id": is_int, "interaction_id": opt(is_int), "action": is_str,
    "due_date": opt(is_date), "reason": is_str, "source": is_str, "status": is_str, "created_at": is_ts,
    "decided_at": opt(is_ts), "decided_by": opt(is_dict),
}
FOLLOWUP_SPEC = {"id": is_int, "contact_id": is_int, "interaction_id": opt(is_int), "channel": is_str,
                 "to": opt(is_str), "subject": opt(is_str), "body": is_str, "source": is_str, "status": is_str}
CANDIDATE_SPEC = {
    "id": is_int, "project_id": is_str, "project_name": opt(is_str), "company": opt(is_str),
    "contact_name": opt(is_str), "email": opt(is_str), "phone": opt(is_str), "quote_total": opt(is_num),
    "quote_date": opt(is_date), "status": is_str, "possible_duplicate": opt(is_dict),
}
IMPORT_SPEC = {
    "id": is_int, "file_name": is_str, "dry_run": is_bool, "started_at": is_ts, "by": opt(is_dict),
    "rows_read": is_int, "created": is_int, "updated": is_int, "skipped": is_int,
    "possible_duplicates": is_int, "errors": lambda v: type(v) is list,
}
UNMATCHED_SPEC = {"id": is_int, "provider": is_str, "external_id": opt(is_str), "direction": opt(is_str),
                  "from_e164": opt(is_str), "occurred_at": is_ts, "duration_s": opt(is_int),
                  "summary": opt(is_str), "status": is_str}


# ── docs/bd/api-contract.md: the examples are the other half of the agreement ──────────────────────
_JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)


def _block_after(marker):
    start = CONTRACT.index(marker)
    return json.loads(_JSON_BLOCK.search(CONTRACT, start).group(1))


def _all_blocks():
    return [json.loads(m.group(1)) for m in _JSON_BLOCK.finditer(CONTRACT)]


def _contract_import():
    return next(b["import"] for b in _all_blocks() if isinstance(b, dict) and "import" in b)


def _contract_unmatched():
    return next(b["items"][0] for b in _all_blocks()
                if isinstance(b, dict) and b.get("items") and isinstance(b["items"][0], dict)
                and "from_e164" in b["items"][0])


def _contract_batch():
    return json.loads(re.search(r"TaskBatch: `(\{.*?\})`", CONTRACT).group(1))


CONTRACT_EXAMPLES = {
    "user": (USER_SPEC, lambda: _block_after("### UserRef and User")),
    "company": (COMPANY_SPEC, lambda: _block_after("### Company\n")),
    "contact": (CONTACT_SPEC, lambda: _block_after("### Contact\n")),
    "contact_compact": (CONTACT_COMPACT_SPEC, lambda: _block_after("### ContactCompact")),
    "interaction": (INTERACTION_SPEC, lambda: _block_after("### Interaction\n")),
    "task": (TASK_SPEC, lambda: _block_after("### Task, TaskBatch")),
    "task_batch": (BATCH_SPEC, _contract_batch),
    "week_row": (WEEK_ROW_SPEC, lambda: _block_after("### WeekRow")),
    "week_row_person": (WEEK_ROW_PERSON_SPEC, lambda: _block_after("### WeekRow")["people"][0]),
    "recommendation": (RECOMMENDATION_SPEC, lambda: _block_after("### Recommendation")),
    "followup_draft": (FOLLOWUP_SPEC, lambda: _block_after("### FollowupDraft")),
    "candidate": (CANDIDATE_SPEC, lambda: _block_after("### Candidate\n")),
    "import_record": (IMPORT_SPEC, _contract_import),
    "unmatched_call": (UNMATCHED_SPEC, _contract_unmatched),
}


@pytest.mark.parametrize("name", sorted(CONTRACT_EXAMPLES))
def test_key_set_is_the_contracts_example(name):
    """The serializer's keys (pinned here) are the keys of the contract's JSON example."""
    spec, example = CONTRACT_EXAMPLES[name]
    assert set(spec) == set(example()), name


# ── row factories ───────────────────────────────────────────────────────────────────────────────
def user_row(**kw):
    row = {"id": 1, "name": "Troy", "email": "troy@example.com", "role": "salesperson", "active": True,
           "last_seen_at": utc(2026, 11, 4, 14, 12), "auth_sub": "sub-1", "created_at": utc(2026, 1, 1, 15)}
    row.update(kw)
    return row


def company_row(**kw):
    row = {"id": 10, "name": "Prairiefold Foods", "city": "Topeka, KS", "industry": "Food Processing",
           "created_at": utc(2026, 1, 12, 15, 0), "contact_count": 1, "normalized_name": "prairiefold foods"}
    row.update(kw)
    return row


def contact_row(**kw):
    """A contacts_summary row with every column set (and a few the serializer must NOT send)."""
    row = {
        "id": 10, "company_id": 10, "company_name": "Prairiefold Foods",
        "company_normalized_name": "prairiefold foods", "name": "Victor Almeida",
        "title": "Sanitation Manager", "email": "victor.almeida@prairiefoldfoo.example.com",
        "email_lower": "victor.almeida@prairiefoldfoo.example.com", "phone": "816-555-0110",
        "phone_e164": "+18165550110", "city": "Topeka, KS", "industry": "Food Processing",
        "lead_source": "Current Account", "stage": "Proposal", "category": "bd", "account_type": "Fleet",
        "owner_id": 1, "owner_name": "Troy", "co_owner_id": None, "co_owner_name": "Greg",
        "frequency_per_year": D("4"), "stored_frequency_per_year": D("6"),
        "cadence": "quarterly", "cadence_source": "global", "cadence_override": "monthly",
        "cadence_override_until": dt.date(2026, 10, 31), "confirmed": True, "importance": D("3"),
        "next_step": "Call back with the coving price", "next_step_date": dt.date(2026, 11, 5),
        "promised_date": dt.date(2026, 11, 5), "last_quote_date": dt.date(2026, 10, 9),
        "duplicate_of": 1, "duplicate_reason": "Same email", "duplicate_name": "Dana Whitfield",
        "duplicate_company": "Ridgecrest Fabrication Works", "source": "workbook",
        "tags": ["food-safe", "priority"], "notes": "Likes email", "archived_at": None,
        "created_at": utc(2026, 1, 12, 15, 0), "last_live_at": utc(2026, 10, 22, 16, 20),
        "last_attempt_at": utc(2026, 10, 22, 16, 20), "attempts_since_live": 0, "touches_this_year": 4,
        "last_followup_at": utc(2026, 10, 23, 14, 5), "maintenance_due_date": None, "maintenance_due": False,
        "effective_frequency": 4, "touches_needed": 4, "cadence_interval_days": 91,
        "next_due_date": dt.date(2027, 1, 21), "cadence_status": "complete", "as_of": dt.date(2026, 11, 4),
    }
    row.update(kw)
    return row


CONTACT_REQUIRED = ("id", "company_id", "company_name", "name", "category", "frequency_per_year",
                    "confirmed", "importance", "source", "cadence_status")


def contact_row_min():
    """Only the columns serialize.contact reads with [] (everything else absent, not None)."""
    full = contact_row()
    return {k: full[k] for k in CONTACT_REQUIRED}


def interaction_row(**kw):
    row = {"id": 1073, "contact_id": 17, "contact_name": "Megan Tully", "company_id": 17,
           "company_name": "Halvorsen & Pike Contractors", "kind": "call", "direction": "out",
           "counts_as_touch": True, "occurred_at": utc(2026, 11, 2, 15, 20), "duration_s": 480,
           "outcome": "answered", "summary": "Spring bid list is out in January.",
           "transcript": "Troy: Hi Megan.", "recording_url": "https://example.com/recordings/AC002701.mp3",
           "provider": "quo", "external_id": "AC002701", "user_id": 1, "user_name": "Troy",
           "followup_status": None, "followup_at": None, "created_at": utc(2026, 11, 2, 15, 30)}
    row.update(kw)
    return row


INTERACTION_REQUIRED = ("id", "contact_id", "contact_name", "company_id", "company_name", "kind",
                        "counts_as_touch", "occurred_at", "provider")


def batch_row(**kw):
    row = {"id": 41, "kind": "friday", "owner_id": 1, "owner_name": "Troy",
           "week_start": dt.date(2026, 11, 2), "generated_at": utc(2026, 10, 30, 21, 0)}
    row.update(kw)
    return row


def task_row(**kw):
    row = {"id": 401, "batch_id": 41, "contact_id": 2, "kind": "followup",
           "reason": "Promised a call by Fri, Nov 6.", "reasons": ["Promised a call by Fri, Nov 6"],
           "score": 75, "status": "open", "done_at": None, "snoozed_until": None, "snooze_reason": None,
           "closed_by_archive": False, "created_at": utc(2026, 10, 30, 21, 0)}
    row.update(kw)
    return row


def recommendation_row(**kw):
    row = {"id": 72, "contact_id": 8, "interaction_id": 1074, "action": "Try Ray again",
           "due_date": dt.date(2026, 11, 9), "reason": "Voicemail, no live talk yet.", "source": "fallback",
           "status": "pending", "created_at": utc(2026, 11, 2, 20, 35), "decided_at": None,
           "decided_by": None, "decided_by_name": None}
    row.update(kw)
    return row


def draft_row(**kw):
    row = {"id": 81, "contact_id": 8, "interaction_id": 1074, "channel": "email",
           "to_address": "ray.duchene@meridalefleets.example.com", "subject": "Shop floor at Meridale",
           "body": "Hi Ray,\n\nIs there a good time this week?", "source": "ai", "status": "draft"}
    row.update(kw)
    return row


def candidate_row(**kw):
    row = {"id": 92, "project_id": "8a4b2c1d-5e6f-4a7b-8c9d-0e1f2a3b4c5d", "project_name": "Warehouse 2 Sealer",
           "company": "Switchgrass Construction", "contact_name": "Mia Thornton",
           "email": "mia.thornton@switchgrass.example.com", "phone": "816-555-0182",
           "quote_total": D("42800.00"), "quote_date": dt.date(2026, 10, 16), "status": "new",
           "possible_duplicate_id": 15, "pd_name": "Angela Ruiz", "pd_company": "Switchgrass Construction",
           "origin": "pull", "payload": {}, "created_at": utc(2026, 10, 17, 15)}
    row.update(kw)
    return row


def import_row(**kw):
    row = {"id": 4, "file_name": "BD workbook.xlsx", "dry_run": True, "started_at": utc(2026, 11, 4, 17, 0),
           "finished_at": utc(2026, 11, 4, 17, 1), "by_id": 4, "by_name": "Hanz", "rows_read": 36,
           "created": 0, "updated": 2, "skipped": 34, "possible_duplicates": 1,
           "errors": [{"sheet": "Business Development Accounts", "row": 41, "message": "No company name."}]}
    row.update(kw)
    return row


def unmatched_row(**kw):
    row = {"id": 61, "provider": "quo", "external_id": "AC990011", "kind": "call", "direction": "in",
           "from_e164": "+19135550199", "occurred_at": utc(2026, 11, 3, 22, 42), "duration_s": 95,
           "summary": "Caller asked about a quote for a shop floor.", "transcript": None,
           "recording_url": None, "status": "open"}
    row.update(kw)
    return row


def without(row, *keys):
    return {k: v for k, v in row.items() if k not in keys}


# ══ TIMESTAMPS AND DATES ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("moment,want", [
    (utc(2026, 7, 22, 16, 5), "2026-07-22T11:05:00-05:00"),           # summer: CDT
    (utc(2026, 1, 12, 15, 0), "2026-01-12T09:00:00-06:00"),           # winter: CST
    (utc(2026, 10, 30, 21, 0), "2026-10-30T16:00:00-05:00"),          # the contract's Friday 16:00
    (utc(2026, 11, 4, 16, 0), "2026-11-04T10:00:00-06:00"),
    (utc(2026, 11, 1, 6, 30), "2026-11-01T01:30:00-05:00"),           # fall back: 01:30 happens twice,
    (utc(2026, 11, 1, 7, 30), "2026-11-01T01:30:00-06:00"),           #   an hour apart, offsets differ
    (utc(2026, 3, 8, 7, 59), "2026-03-08T01:59:00-06:00"),           # spring forward: 02:xx never exists
    (utc(2026, 3, 8, 8, 0), "2026-03-08T03:00:00-05:00"),
    (utc(2027, 1, 1, 5, 59), "2026-12-31T23:59:00-06:00"),           # New Year's Eve in Central
    (utc(2026, 11, 4, 16, 0, 0, 999999), "2026-11-04T10:00:00-06:00"),   # to the second
])
def test_a_utc_moment_leaves_as_central_wall_time_with_its_own_offset(moment, want):
    assert serialize.ts(moment) == want
    # and through a real serializer, so a field that forgot ts() would fail here
    assert serialize.user(user_row(last_seen_at=moment))["last_seen_at"] == want
    assert serialize.unmatched_call(unmatched_row(occurred_at=moment))["occurred_at"] == want


def test_the_fall_back_hour_keeps_two_distinct_moments_distinct():
    first = serialize.interaction(interaction_row(occurred_at=utc(2026, 11, 1, 6, 30)))["occurred_at"]
    second = serialize.interaction(interaction_row(occurred_at=utc(2026, 11, 1, 7, 30)))["occurred_at"]
    assert first != second
    assert dt.datetime.fromisoformat(second) - dt.datetime.fromisoformat(first) == dt.timedelta(hours=1)


def _expected_central_offset(moment):
    """The US rule, written out independently of zoneinfo: CDT (-05:00) from 2:00 CST on the second
    Sunday of March to 2:00 CDT on the first Sunday of November (08:00Z and 07:00Z)."""
    changes = {2026: (utc(2026, 3, 8, 8), utc(2026, 11, 1, 7)), 2027: (utc(2027, 3, 14, 8), utc(2027, 11, 7, 7))}
    start, end = changes[moment.year]
    return "-05:00" if start <= moment < end else "-06:00"


def test_every_half_hour_of_two_years_round_trips_with_the_right_offset():
    """Property over the whole 2026-2027 timeline: the string is the same instant, carries the DST
    offset of that instant, and its date part is the Central date iso_date gives."""
    moment = utc(2026, 1, 1)
    end = utc(2028, 1, 1)
    step = dt.timedelta(minutes=30)
    count = 0
    while moment < end:
        out = serialize.ts(moment)
        assert TS_RE.match(out), out
        assert dt.datetime.fromisoformat(out) == moment, (moment, out)
        assert out.endswith(_expected_central_offset(moment)), (moment, out)
        assert out[:10] == iso_date(moment), (moment, out)
        moment += step
        count += 1
    assert count == 730 * 48             # 2026 and 2027, both 365 days


def test_ts_keeps_none_and_reads_a_naive_datetime_as_central():
    assert serialize.ts(None) is None
    assert serialize.ts(dt.datetime(2026, 11, 4, 10, 0)) == "2026-11-04T10:00:00-06:00"


@pytest.mark.parametrize("value,want", [
    (dt.date(2026, 11, 4), "2026-11-04"),
    (dt.date(2026, 1, 1), "2026-01-01"),
    (utc(2026, 11, 5, 3, 0), "2026-11-04"),     # 9 pm Central the night before: the Central date
    (utc(2026, 11, 5, 6, 0), "2026-11-05"),
    (None, None),
])
def test_dates_are_central_yyyy_mm_dd(value, want):
    assert serialize.task(task_row(snoozed_until=value))["snoozed_until"] == want
    assert serialize.task_batch(batch_row(week_start=value or dt.date(2026, 11, 2)))["week_start"] == (
        want or "2026-11-02")


# ══ _num ═════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("value,want", [
    (None, None), (D("42800.00"), 42800.0), (D("0.10"), 0.1), (D("-3"), -3.0), (D("0"), 0.0),
    (7, 7), (7.5, 7.5), (0, 0),
])
def test_num(value, want):
    out = serialize._num(value)
    assert out == want
    if isinstance(value, D):
        assert type(out) is float                # a Decimal never reaches json.dumps
    else:
        assert out is value


# ══ PEOPLE ═══════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("user_id,name,want", [
    (1, "Troy", {"id": 1, "name": "Troy"}),
    (None, "Greg", {"id": None, "name": "Greg"}),     # a workbook co-owner with no login yet
    (2, None, {"id": 2, "name": None}),
    (2, "", {"id": 2, "name": ""}),
    (None, None, None),                               # nobody
    (None, "", None),
])
def test_user_ref(user_id, name, want):
    assert serialize.user_ref(user_id, name) == want


def test_user_exact_output_and_shape():
    out = check_shape(serialize.user(user_row()), USER_SPEC)
    assert out == {"id": 1, "name": "Troy", "email": "troy@example.com", "role": "salesperson", "active": True,
                   "last_seen_at": "2026-11-04T08:12:00-06:00"}      # nothing of auth_sub / created_at


@pytest.mark.parametrize("active,want", [(True, True), (False, False), (1, True), (0, False), (None, False)])
def test_user_active_is_always_a_bool(active, want):
    assert serialize.user(user_row(active=active))["active"] is want


def test_user_never_signed_in_has_null_last_seen_whether_none_or_absent():
    assert serialize.user(user_row(last_seen_at=None))["last_seen_at"] is None
    assert serialize.user(without(user_row(), "last_seen_at"))["last_seen_at"] is None


@pytest.mark.parametrize("key", ["id", "name", "email", "role", "active"])
def test_user_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.user(without(user_row(), key))


def test_user_compact_is_exactly_id_name_role():
    out = check_shape(serialize.user_compact(user_row(role="manager")), USER_COMPACT_SPEC)
    assert out == {"id": 1, "name": "Troy", "role": "manager"}        # no email: the list is open to staff
    for key in ("id", "name", "role"):
        with pytest.raises(KeyError):
            serialize.user_compact(without(user_row(), key))


# ══ COMPANIES ════════════════════════════════════════════════════════════════════════════════════
def test_company_ref_and_company():
    assert check_shape(serialize.company_ref(10, "Prairiefold Foods"), REF_SPEC) == {
        "id": 10, "name": "Prairiefold Foods"}
    out = check_shape(serialize.company(company_row()), COMPANY_SPEC)
    assert out == {"id": 10, "name": "Prairiefold Foods", "city": "Topeka, KS", "industry": "Food Processing",
                   "created_at": "2026-01-12T09:00:00-06:00", "contact_count": 1}     # no normalized_name


def test_company_optional_columns_and_count_default():
    out = check_shape(serialize.company({"id": 3, "name": "Acme"}), COMPANY_SPEC)
    assert out == {"id": 3, "name": "Acme", "city": None, "industry": None, "created_at": None,
                   "contact_count": 0}


@pytest.mark.parametrize("count,want", [(None, 0), (0, 0), (5, 5), (D("3"), 3)])
def test_company_contact_count_is_an_int(count, want):
    out = serialize.company(company_row(contact_count=count))["contact_count"]
    assert out == want and type(out) is int


@pytest.mark.parametrize("key", ["id", "name"])
def test_company_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.company(without(company_row(), key))


# ══ CONTACT ══════════════════════════════════════════════════════════════════════════════════════
FULL_CONTACT = {
    "id": 10, "company": {"id": 10, "name": "Prairiefold Foods"}, "name": "Victor Almeida",
    "title": "Sanitation Manager", "email": "victor.almeida@prairiefoldfoo.example.com",
    "phone": "816-555-0110", "phone_e164": "+18165550110", "city": "Topeka, KS",
    "industry": "Food Processing", "lead_source": "Current Account", "stage": "Proposal",
    "category": "bd", "account_type": "Fleet", "owner": {"id": 1, "name": "Troy"},
    "co_owner": {"id": None, "name": "Greg"}, "frequency_per_year": 4, "confirmed": True, "importance": 3,
    "next_step": "Call back with the coving price", "next_step_date": "2026-11-05",
    "promised_date": "2026-11-05", "last_quote_date": "2026-10-09",
    "duplicate_of": {"contact_id": 1, "name": "Dana Whitfield", "company": "Ridgecrest Fabrication Works",
                     "reason": "Same email"},
    "source": "workbook", "tags": ["food-safe", "priority"], "notes": "Likes email",
    "created_at": "2026-01-12T09:00:00-06:00", "last_live_at": "2026-10-22T11:20:00-05:00",
    "last_attempt_at": "2026-10-22T11:20:00-05:00", "attempts_since_live": 0, "touches_this_year": 4,
    "next_due_date": "2027-01-21", "cadence_status": "complete",
    # a lapsed override is still shown as stored; cadence_source says it no longer applies
    "cadence": "quarterly", "cadence_source": "global", "cadence_override": "monthly",
    "cadence_override_until": "2026-10-31", "last_followup_at": "2026-10-23T09:05:00-05:00",
    "maintenance_due_date": None, "maintenance_due": False,
}


def test_contact_full_row_exact_output():
    out = check_shape(serialize.contact(contact_row()), CONTACT_SPEC)
    assert out == FULL_CONTACT
    # the view's helper columns are never sent
    for leak in ("email_lower", "company_normalized_name", "effective_frequency", "touches_needed",
                 "cadence_interval_days", "as_of", "stored_frequency_per_year", "owner_id", "co_owner_id", "company_id", "company_name",
                 "archived_at", "duplicate_reason", "duplicate_name"):
        assert leak not in out


def test_contact_minimal_row_every_optional_column_absent():
    """Only the [] columns exist: every .get column may be missing without raising."""
    out = check_shape(serialize.contact(contact_row_min()), CONTACT_SPEC)
    assert out == {
        "id": 10, "company": {"id": 10, "name": "Prairiefold Foods"}, "name": "Victor Almeida",
        "title": None, "email": None, "phone": None, "phone_e164": None, "city": None, "industry": None,
        "lead_source": None, "stage": None, "category": "bd", "account_type": None, "owner": None,
        "co_owner": None, "frequency_per_year": 4, "confirmed": True, "importance": 3, "next_step": None,
        "next_step_date": None, "promised_date": None, "last_quote_date": None, "duplicate_of": None,
        "source": "workbook", "tags": [], "notes": "", "created_at": None, "last_live_at": None,
        "last_attempt_at": None, "attempts_since_live": 0, "touches_this_year": 0, "next_due_date": None,
        "cadence_status": "complete", "cadence": None, "cadence_source": None, "cadence_override": None,
        "cadence_override_until": None, "last_followup_at": None, "maintenance_due_date": None,
        "maintenance_due": False,
    }


def test_a_maintenance_contact_carries_its_follow_up_clock_and_no_cadence():
    out = check_shape(serialize.contact(contact_row(
        category="maintenance", frequency_per_year=3, cadence=None, cadence_source=None,
        cadence_override=None, cadence_override_until=None, last_followup_at=utc(2026, 7, 3, 15, 0),
        maintenance_due_date=dt.date(2026, 10, 31), maintenance_due=True)), CONTACT_SPEC)
    assert (out["cadence"], out["cadence_source"], out["cadence_override"], out["cadence_override_until"]) == (
        None, None, None, None)
    assert (out["last_followup_at"], out["maintenance_due_date"], out["maintenance_due"]) == (
        "2026-07-03T10:00:00-05:00", "2026-10-31", True)


def test_contact_all_nulls_row_matches_the_minimal_one():
    """A row from the database has every column, NULL; absent and None must give the same object."""
    nulls = dict.fromkeys(contact_row())
    nulls.update(contact_row_min())
    assert serialize.contact(nulls) == serialize.contact(contact_row_min())


@pytest.mark.parametrize("key", CONTACT_REQUIRED)
def test_contact_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.contact(without(contact_row(), key))


@pytest.mark.parametrize("freq,imp", [(4, 1), (D("4"), D("1")), (D("12.0"), D("2")), (52, 3)])
def test_contact_frequency_and_importance_are_plain_ints(freq, imp):
    out = serialize.contact(contact_row(frequency_per_year=freq, importance=imp))
    assert out["frequency_per_year"] == int(freq) and type(out["frequency_per_year"]) is int
    assert out["importance"] == int(imp) and type(out["importance"]) is int
    json.dumps(out)


@pytest.mark.parametrize("confirmed,want", [(True, True), (False, False), (1, True), (0, False), (None, False)])
def test_contact_confirmed_is_a_bool(confirmed, want):
    assert serialize.contact(contact_row(confirmed=confirmed))["confirmed"] is want
    assert serialize.contact_compact(contact_row(confirmed=confirmed))["confirmed"] is want


@pytest.mark.parametrize("tags,want", [
    (None, []), ([], []), (["a"], ["a"]), (("a", "b"), ["a", "b"]),
])
def test_contact_tags_none_is_an_empty_list(tags, want):
    out = serialize.contact(contact_row(tags=tags))["tags"]
    assert out == want and type(out) is list


def test_contact_tags_are_a_copy_not_the_rows_own_list():
    tags = ["a", "b"]
    out = serialize.contact(contact_row(tags=tags))
    out["tags"].append("c")
    assert tags == ["a", "b"]


def test_contact_tags_absent_column_is_an_empty_list():
    assert serialize.contact(without(contact_row(), "tags"))["tags"] == []


@pytest.mark.parametrize("notes,want", [(None, ""), ("", ""), ("Likes email", "Likes email"), ("  ", "  ")])
def test_contact_notes_none_is_an_empty_string(notes, want):
    assert serialize.contact(contact_row(notes=notes))["notes"] == want


def test_contact_notes_absent_column_is_an_empty_string():
    assert serialize.contact(without(contact_row(), "notes"))["notes"] == ""


def test_contact_archived_at_exists_only_when_set():
    assert "archived_at" not in serialize.contact(contact_row(archived_at=None))
    assert "archived_at" not in serialize.contact(without(contact_row(), "archived_at"))
    out = serialize.contact(contact_row(archived_at=utc(2026, 11, 3, 18, 0)))
    assert out["archived_at"] == "2026-11-03T12:00:00-06:00"
    # the only difference an archive makes is that one key
    assert without(out, "archived_at") == serialize.contact(contact_row())
    json.dumps(out)


@pytest.mark.parametrize("co_id,co_name,want", [
    (None, None, None),                                 # no co-owner at all
    (None, "", None),                                   # an empty name is nobody
    (2, None, {"id": 2, "name": None}),                 # id only
    (None, "Greg", {"id": None, "name": "Greg"}),       # a workbook name with no login yet
    (2, "Greg", {"id": 2, "name": "Greg"}),
])
def test_contact_co_owner(co_id, co_name, want):
    assert serialize.contact(contact_row(co_owner_id=co_id, co_owner_name=co_name))["co_owner"] == want


def test_contact_co_owner_columns_absent_is_none():
    assert serialize.contact(without(contact_row(), "co_owner_id", "co_owner_name"))["co_owner"] is None


@pytest.mark.parametrize("owner_id,owner_name,want", [
    (None, None, None),
    (None, "Troy", None),                               # a name without an id is not an owner
    (1, "Troy", {"id": 1, "name": "Troy"}),
    (1, None, {"id": 1, "name": None}),
])
def test_contact_owner_is_none_when_owner_id_is_none(owner_id, owner_name, want):
    assert serialize.contact(contact_row(owner_id=owner_id, owner_name=owner_name))["owner"] == want


@pytest.mark.parametrize("reason,want", [
    (None, "Same company name"),                        # the column default
    ("", "Same company name"),
    ("Same email", "Same email"),
    ("Same phone", "Same phone"),
])
def test_contact_duplicate_of_default_reason(reason, want):
    out = serialize.contact(contact_row(duplicate_of=7, duplicate_reason=reason))["duplicate_of"]
    assert out == {"contact_id": 7, "name": "Dana Whitfield", "company": "Ridgecrest Fabrication Works",
                   "reason": want}


def test_contact_duplicate_of_none_is_none_even_with_leftover_columns():
    out = serialize.contact(contact_row(duplicate_of=None, duplicate_reason="Same email"))
    assert out["duplicate_of"] is None


def test_contact_duplicate_of_survives_missing_name_and_company():
    out = serialize.contact(without(contact_row(), "duplicate_name", "duplicate_company", "duplicate_reason"))
    assert out["duplicate_of"] == {"contact_id": 1, "name": None, "company": None, "reason": "Same company name"}


def test_contact_counters_default_to_zero_and_are_ints():
    out = serialize.contact(contact_row(attempts_since_live=None, touches_this_year=None))
    assert out["attempts_since_live"] == 0 and out["touches_this_year"] == 0
    out = serialize.contact(contact_row(attempts_since_live=D("2"), touches_this_year=D("3")))
    assert (out["attempts_since_live"], out["touches_this_year"]) == (2, 3)
    assert type(out["attempts_since_live"]) is int and type(out["touches_this_year"]) is int


def test_contact_dates_and_timestamps_keep_their_kind():
    """next_*/promised/quote/due are dates (no time, no offset); created/last_* are timestamps."""
    out = serialize.contact(contact_row())
    for key in ("next_step_date", "promised_date", "last_quote_date", "next_due_date"):
        assert DATE_RE.match(out[key]), key
    for key in ("created_at", "last_live_at", "last_attempt_at"):
        assert TS_RE.match(out[key]), key


def test_contact_summer_and_winter_touch_times_carry_different_offsets():
    out = serialize.contact(contact_row(last_live_at=utc(2026, 7, 22, 16, 5), last_attempt_at=utc(2026, 12, 2, 16, 5)))
    assert out["last_live_at"] == "2026-07-22T11:05:00-05:00"
    assert out["last_attempt_at"] == "2026-12-02T10:05:00-06:00"


# ══ CONTACT COMPACT, CONTACT REF, DUPLICATE MATCH ════════════════════════════════════════════════
def test_contact_compact_exact_output():
    out = check_shape(serialize.contact_compact(contact_row()), CONTACT_COMPACT_SPEC)
    assert out == {
        "id": 10, "name": "Victor Almeida", "title": "Sanitation Manager",
        "company": {"id": 10, "name": "Prairiefold Foods"}, "phone": "816-555-0110",
        "phone_e164": "+18165550110", "email": "victor.almeida@prairiefoldfoo.example.com",
        "category": "bd", "confirmed": True, "lead_source": "Current Account",
        "last_live_at": "2026-10-22T11:20:00-05:00", "cadence_status": "complete",
    }
    for leak in ("notes", "tags", "owner", "stage", "city", "importance"):
        assert leak not in out


COMPACT_REQUIRED = ("id", "name", "company_id", "company_name", "category", "confirmed", "cadence_status")


def test_contact_compact_minimal_row_and_nulls():
    row = {k: contact_row()[k] for k in COMPACT_REQUIRED}
    out = check_shape(serialize.contact_compact(row), CONTACT_COMPACT_SPEC)
    for key in ("title", "phone", "phone_e164", "email", "lead_source", "last_live_at"):
        assert out[key] is None
    assert serialize.contact_compact(dict.fromkeys(contact_row()) | row) == out


@pytest.mark.parametrize("key", COMPACT_REQUIRED)
def test_contact_compact_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.contact_compact(without(contact_row(), key))


def test_contact_ref_exact_output_and_required_columns():
    out = check_shape(serialize.contact_ref(contact_row()), CONTACT_REF_SPEC)
    assert out == {"id": 10, "name": "Victor Almeida", "company": {"id": 10, "name": "Prairiefold Foods"}}
    for key in ("id", "name", "company_id", "company_name"):
        with pytest.raises(KeyError):
            serialize.contact_ref(without(contact_row(), key))


def test_duplicate_match_takes_the_reason_it_is_given():
    out = check_shape(serialize.duplicate_match(contact_row(), "Same phone"), DUPLICATE_MATCH_SPEC)
    assert out == {"contact_id": 10, "name": "Victor Almeida", "company": "Prairiefold Foods",
                   "city": "Topeka, KS", "reason": "Same phone"}
    assert serialize.duplicate_match(contact_row(city=None), "Same email")["city"] is None
    assert serialize.duplicate_match(without(contact_row(), "city"), "Same email")["city"] is None
    for key in ("id", "name", "company_name"):
        with pytest.raises(KeyError):
            serialize.duplicate_match(without(contact_row(), key), "Same email")


# ══ INTERACTIONS ═════════════════════════════════════════════════════════════════════════════════
def test_interaction_exact_output():
    out = check_shape(serialize.interaction(interaction_row()), INTERACTION_SPEC)
    assert out == {
        "id": 1073, "contact_id": 17,
        "contact": {"id": 17, "name": "Megan Tully", "company": {"id": 17, "name": "Halvorsen & Pike Contractors"}},
        "kind": "call", "direction": "out", "counts_as_touch": True,
        "occurred_at": "2026-11-02T09:20:00-06:00", "duration_s": 480, "outcome": "answered",
        "summary": "Spring bid list is out in January.", "transcript": "Troy: Hi Megan.",
        "recording_url": "https://example.com/recordings/AC002701.mp3", "provider": "quo",
        "external_id": "AC002701", "user": {"id": 1, "name": "Troy"},
    }


def test_interaction_minimal_row_and_null_columns_agree():
    minimal = {k: interaction_row()[k] for k in INTERACTION_REQUIRED}
    out = check_shape(serialize.interaction(minimal), INTERACTION_SPEC)
    for key in ("direction", "duration_s", "outcome", "summary", "transcript", "recording_url",
                "external_id", "user"):
        assert out[key] is None
    nulls = dict.fromkeys(interaction_row()) | minimal
    assert serialize.interaction(nulls) == out


@pytest.mark.parametrize("key", INTERACTION_REQUIRED)
def test_interaction_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.interaction(without(interaction_row(), key))


@pytest.mark.parametrize("user_id,user_name,want", [
    (None, None, None),
    (None, "Troy", None),                               # a left-joined name without an id is nobody
    (1, "Troy", {"id": 1, "name": "Troy"}),
    (1, None, {"id": 1, "name": None}),                 # the user row was deleted: id survives
])
def test_interaction_user(user_id, user_name, want):
    assert serialize.interaction(interaction_row(user_id=user_id, user_name=user_name))["user"] == want


def test_interaction_a_phone_call_logged_by_nobody_has_user_none_when_columns_absent():
    assert serialize.interaction(without(interaction_row(), "user_id", "user_name"))["user"] is None


@pytest.mark.parametrize("flag,want", [(True, True), (False, False), (1, True), (0, False)])
def test_interaction_counts_as_touch_is_a_bool(flag, want):
    assert serialize.interaction(interaction_row(counts_as_touch=flag))["counts_as_touch"] is want


def test_interaction_does_not_send_internal_columns():
    out = serialize.interaction(interaction_row(followup_status="pending", followup_at=utc(2026, 11, 3)))
    assert "followup_status" not in out and "followup_at" not in out and "created_at" not in out


# ══ THE WEEKLY 10 ════════════════════════════════════════════════════════════════════════════════
def test_task_batch_exact_output():
    out = check_shape(serialize.task_batch(batch_row()), BATCH_SPEC)
    assert out == {"id": 41, "kind": "friday", "owner": {"id": 1, "name": "Troy"},
                   "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00"}


def test_task_batch_owner_name_is_optional_but_the_owner_always_exists():
    out = serialize.task_batch(without(batch_row(), "owner_name"))
    assert out["owner"] == {"id": 1, "name": None}


@pytest.mark.parametrize("key", ["id", "kind", "owner_id", "week_start", "generated_at"])
def test_task_batch_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.task_batch(without(batch_row(), key))


def test_task_exact_output_passes_the_contact_through_untouched():
    compact = serialize.contact_compact(contact_row())
    out = check_shape(serialize.task(task_row(), compact), TASK_SPEC)
    assert out["contact"] is compact                  # already serialised: never re-built or copied
    assert without(out, "contact") == {
        "id": 401, "batch_id": 41, "kind": "followup", "reason": "Promised a call by Fri, Nov 6.",
        "reasons": ["Promised a call by Fri, Nov 6"], "score": 75, "status": "open", "done_at": None,
        "snoozed_until": None,
    }


def test_task_contact_defaults_to_none():
    assert serialize.task(task_row())["contact"] is None
    assert serialize.task(task_row(), None)["contact"] is None


def test_task_nulls_become_empty_values():
    out = check_shape(serialize.task(task_row(reason=None, reasons=None, score=None)), TASK_SPEC)
    assert out["reason"] == "" and out["reasons"] == [] and out["score"] == 0
    bare = {k: task_row()[k] for k in ("id", "batch_id", "kind", "status")}
    out = check_shape(serialize.task(bare), TASK_SPEC)
    assert (out["reason"], out["reasons"], out["score"]) == ("", [], 0)
    assert out["done_at"] is None and out["snoozed_until"] is None


def test_task_score_zero_stays_zero_and_decimal_score_is_an_int():
    assert serialize.task(task_row(score=0))["score"] == 0
    out = serialize.task(task_row(score=D("75")))["score"]
    assert out == 75 and type(out) is int


def test_task_reasons_are_a_copy():
    reasons = ["a", "b"]
    out = serialize.task(task_row(reasons=reasons))
    out["reasons"].append("c")
    assert reasons == ["a", "b"]


def test_task_done_and_snoozed_use_timestamp_and_date_formats():
    out = check_shape(serialize.task(task_row(status="done", done_at=utc(2026, 11, 4, 16, 0))), TASK_SPEC)
    assert out["done_at"] == "2026-11-04T10:00:00-06:00"
    out = check_shape(serialize.task(task_row(status="snoozed", snoozed_until=dt.date(2026, 11, 9))), TASK_SPEC)
    assert out["snoozed_until"] == "2026-11-09"
    assert "snooze_reason" not in out and "closed_by_archive" not in out and "contact_id" not in out


# ── WeekRow (#828) ────────────────────────────────────────────────────────────────────────────
def test_week_row_person_exact_output():
    row = contact_row(promised_date=dt.date(2027, 1, 15), next_step="Send the floor samples",
                      next_step_date=dt.date(2027, 1, 20), attempts_since_live=2, last_live_at=utc(2026, 6, 1, 15))
    out = check_shape(serialize.week_row_person(row, 401, True), WEEK_ROW_PERSON_SPEC)
    assert (out["id"], out["task_id"], out["not_right_person"], out["attempts_since_live"]) == (10, 401, True, 2)
    assert (out["promised_date"], out["next_step_date"]) == ("2027-01-15", "2027-01-20")
    assert out["last_live_at"] == "2026-06-01T10:00:00-05:00"
    out = check_shape(serialize.week_row_person(contact_row(attempts_since_live=None), None, False),
                      WEEK_ROW_PERSON_SPEC)
    assert (out["task_id"], out["not_right_person"], out["attempts_since_live"]) == (None, False, 0)


def test_week_row_takes_the_first_task_and_the_companys_facts():
    first = serialize.task(task_row(status="done", done_at=utc(2026, 11, 4, 16, 0)))
    second = serialize.task(task_row(id=402, contact_id=3, status="snoozed", snoozed_until=dt.date(2026, 11, 9),
                                     reason="Other.", reasons=["Other"], score=40))
    people = [serialize.week_row_person(contact_row(), 401, False)]
    facts = {"misses": 2, "last_live_at": utc(2026, 6, 1, 15), "last_attempt_at": None}
    out = check_shape(serialize.week_row("ten", [first, second], "done", serialize.company_ref(10, "Prairiefold Foods"),
                                         facts, people), WEEK_ROW_SPEC)
    assert (out["id"], out["task_ids"], out["batch_id"], out["kind"], out["score"]) == (401, [401, 402], 41, "followup", 75)
    assert (out["done_at"], out["snoozed_until"]) == ("2026-11-04T10:00:00-06:00", "2026-11-09")
    assert (out["misses"], out["last_live_at"]) == (2, "2026-06-01T10:00:00-05:00")
    assert out["people"] is people and out["company"] == {"id": 10, "name": "Prairiefold Foods"}
    out = serialize.week_row("due", [serialize.task(task_row())], "open", serialize.company_ref(10, "X"), None, [])
    assert (out["misses"], out["last_live_at"], out["done_at"], out["snoozed_until"]) == (0, None, None, None)


@pytest.mark.parametrize("key", ["id", "batch_id", "kind", "status"])
def test_task_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.task(without(task_row(), key))


# ══ AI NEXT ACTIONS AND FOLLOW-UPS ═══════════════════════════════════════════════════════════════
def test_recommendation_exact_output():
    out = check_shape(serialize.recommendation(recommendation_row()), RECOMMENDATION_SPEC)
    assert out == {"id": 72, "contact_id": 8, "interaction_id": 1074, "action": "Try Ray again",
                   "due_date": "2026-11-09", "reason": "Voicemail, no live talk yet.", "source": "fallback",
                   "status": "pending", "created_at": "2026-11-02T14:35:00-06:00", "decided_at": None,
                   "decided_by": None}


def test_recommendation_decided_by_is_a_user_ref_only_with_an_id():
    row = recommendation_row(status="changed", decided_at=utc(2026, 11, 4, 16, 50), decided_by=1,
                             decided_by_name="Troy")
    out = check_shape(serialize.recommendation(row), RECOMMENDATION_SPEC)
    assert out["decided_by"] == {"id": 1, "name": "Troy"}
    assert out["decided_at"] == "2026-11-04T10:50:00-06:00"
    assert serialize.recommendation(recommendation_row(decided_by=None, decided_by_name="Troy"))[
        "decided_by"] is None
    assert serialize.recommendation(recommendation_row(decided_by=1, decided_by_name=None))[
        "decided_by"] == {"id": 1, "name": None}


def test_recommendation_nulls_and_defaults():
    minimal = {k: recommendation_row()[k] for k in ("id", "contact_id", "action", "source", "status", "created_at")}
    out = check_shape(serialize.recommendation(minimal), RECOMMENDATION_SPEC)
    assert out["interaction_id"] is None and out["due_date"] is None and out["decided_at"] is None
    assert out["decided_by"] is None and out["reason"] == ""
    assert serialize.recommendation(recommendation_row(reason=None))["reason"] == ""
    assert serialize.recommendation(recommendation_row(interaction_id=None, due_date=None))["interaction_id"] is None


@pytest.mark.parametrize("key", ["id", "contact_id", "action", "source", "status", "created_at"])
def test_recommendation_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.recommendation(without(recommendation_row(), key))


def test_followup_draft_exact_output_renames_to_address():
    out = check_shape(serialize.followup_draft(draft_row()), FOLLOWUP_SPEC)
    assert out == {"id": 81, "contact_id": 8, "interaction_id": 1074, "channel": "email",
                   "to": "ray.duchene@meridalefleets.example.com", "subject": "Shop floor at Meridale",
                   "body": "Hi Ray,\n\nIs there a good time this week?", "source": "ai", "status": "draft"}
    assert "to_address" not in out


def test_followup_draft_sms_has_a_null_subject_and_an_e164_to():
    out = check_shape(serialize.followup_draft(
        draft_row(channel="sms", to_address="+18165550182", subject=None)), FOLLOWUP_SPEC)
    assert out["subject"] is None and out["to"] == "+18165550182" and out["channel"] == "sms"


def test_followup_draft_nulls_and_defaults():
    minimal = {k: draft_row()[k] for k in ("id", "contact_id", "channel", "source", "status")}
    out = check_shape(serialize.followup_draft(minimal), FOLLOWUP_SPEC)
    assert out["to"] is None and out["subject"] is None and out["interaction_id"] is None
    assert out["body"] == ""
    assert serialize.followup_draft(draft_row(body=None))["body"] == ""


@pytest.mark.parametrize("key", ["id", "contact_id", "channel", "source", "status"])
def test_followup_draft_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.followup_draft(without(draft_row(), key))


# ══ REVIEW CANDIDATES ════════════════════════════════════════════════════════════════════════════
def test_candidate_exact_output_money_is_a_float():
    out = check_shape(serialize.candidate(candidate_row()), CANDIDATE_SPEC)
    assert out == {
        "id": 92, "project_id": "8a4b2c1d-5e6f-4a7b-8c9d-0e1f2a3b4c5d", "project_name": "Warehouse 2 Sealer",
        "company": "Switchgrass Construction", "contact_name": "Mia Thornton",
        "email": "mia.thornton@switchgrass.example.com", "phone": "816-555-0182", "quote_total": 42800.0,
        "quote_date": "2026-10-16", "status": "new",
        "possible_duplicate": {"contact_id": 15, "name": "Angela Ruiz", "company": "Switchgrass Construction"},
    }
    assert type(out["quote_total"]) is float
    assert "origin" not in out and "payload" not in out and "pd_name" not in out


@pytest.mark.parametrize("total", [D("0.00"), D("0.05"), D("999999999999.99")])
def test_candidate_quote_total_round_trips_through_json(total):
    out = serialize.candidate(candidate_row(quote_total=total))
    assert json.loads(json.dumps(out))["quote_total"] == float(total)


def test_candidate_possible_duplicate_needs_the_id():
    out = serialize.candidate(candidate_row(possible_duplicate_id=None))
    assert out["possible_duplicate"] is None            # a stray pd_name alone is not a match
    out = serialize.candidate(candidate_row(possible_duplicate_id=15, pd_name=None, pd_company=None))
    assert out["possible_duplicate"] == {"contact_id": 15, "name": None, "company": None}
    out = serialize.candidate(without(candidate_row(), "possible_duplicate_id", "pd_name", "pd_company"))
    assert out["possible_duplicate"] is None


def test_candidate_minimal_row():
    minimal = {k: candidate_row()[k] for k in ("id", "project_id", "status")}
    out = check_shape(serialize.candidate(minimal), CANDIDATE_SPEC)
    for key in ("project_name", "company", "contact_name", "email", "phone", "quote_total", "quote_date",
                "possible_duplicate"):
        assert out[key] is None


@pytest.mark.parametrize("key", ["id", "project_id", "status"])
def test_candidate_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.candidate(without(candidate_row(), key))


# ══ ADMIN ════════════════════════════════════════════════════════════════════════════════════════
def test_import_record_exact_output():
    out = check_shape(serialize.import_record(import_row()), IMPORT_SPEC)
    assert out == {
        "id": 4, "file_name": "BD workbook.xlsx", "dry_run": True, "started_at": "2026-11-04T11:00:00-06:00",
        "by": {"id": 4, "name": "Hanz"}, "rows_read": 36, "created": 0, "updated": 2, "skipped": 34,
        "possible_duplicates": 1,
        "errors": [{"sheet": "Business Development Accounts", "row": 41, "message": "No company name."}],
    }
    assert "finished_at" not in out and "by_id" not in out


def test_import_record_nulls_become_zero_and_empty():
    minimal = {k: import_row()[k] for k in ("id", "file_name", "dry_run", "started_at")}
    out = check_shape(serialize.import_record(minimal), IMPORT_SPEC)
    assert out["by"] is None and out["errors"] == []
    for key in ("rows_read", "created", "updated", "skipped", "possible_duplicates"):
        assert out[key] == 0
    nulls = import_row(by_id=None, by_name="Hanz", rows_read=None, created=None, updated=None, skipped=None,
                       possible_duplicates=None, errors=None)
    assert serialize.import_record(nulls) == out


@pytest.mark.parametrize("dry,want", [(True, True), (False, False), (1, True), (0, False)])
def test_import_record_dry_run_is_a_bool(dry, want):
    assert serialize.import_record(import_row(dry_run=dry))["dry_run"] is want


def test_import_record_errors_are_a_copy():
    errors = [{"row": 1}]
    out = serialize.import_record(import_row(errors=errors))
    out["errors"].append({"row": 2})
    assert errors == [{"row": 1}]


@pytest.mark.parametrize("key", ["id", "file_name", "dry_run", "started_at"])
def test_import_record_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.import_record(without(import_row(), key))


def test_unmatched_call_exact_output():
    out = check_shape(serialize.unmatched_call(unmatched_row()), UNMATCHED_SPEC)
    assert out == {"id": 61, "provider": "quo", "external_id": "AC990011", "direction": "in",
                   "from_e164": "+19135550199", "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95,
                   "summary": "Caller asked about a quote for a shop floor.", "status": "open"}
    for leak in ("kind", "transcript", "recording_url", "handled_by"):
        assert leak not in out


def test_unmatched_call_minimal_row():
    minimal = {k: unmatched_row()[k] for k in ("id", "provider", "occurred_at", "status")}
    out = check_shape(serialize.unmatched_call(minimal), UNMATCHED_SPEC)
    for key in ("external_id", "direction", "from_e164", "duration_s", "summary"):
        assert out[key] is None


@pytest.mark.parametrize("key", ["id", "provider", "occurred_at", "status"])
def test_unmatched_call_missing_required_column_is_a_key_error(key):
    with pytest.raises(KeyError):
        serialize.unmatched_call(without(unmatched_row(), key))


# ══ EVERY OUTPUT IS JSON ═════════════════════════════════════════════════════════════════════════
def test_every_serializer_output_dumps_with_the_strictest_settings():
    outputs = [
        serialize.user(user_row()), serialize.user_compact(user_row()), serialize.company(company_row()),
        serialize.contact(contact_row(archived_at=utc(2026, 11, 3, 18))),
        serialize.contact_compact(contact_row()), serialize.contact_ref(contact_row()),
        serialize.duplicate_match(contact_row(), "Same email"), serialize.interaction(interaction_row()),
        serialize.task_batch(batch_row()), serialize.task(task_row(), serialize.contact_compact(contact_row())),
        serialize.recommendation(recommendation_row()), serialize.followup_draft(draft_row()),
        serialize.candidate(candidate_row()), serialize.import_record(import_row()),
        serialize.unmatched_call(unmatched_row()),
    ]
    for out in outputs:
        text = json.dumps(out, allow_nan=False)
        assert json.loads(text) == out


# ── mutation-review additions: columns that must not be mixed up ──────────────────────────────────
def test_contact_date_columns_each_come_from_their_own_column():
    """The fixture gives several date columns the same day, which would hide a swap."""
    out = serialize.contact(contact_row(
        next_step_date=dt.date(2026, 11, 5), promised_date=dt.date(2026, 11, 6),
        last_quote_date=dt.date(2026, 11, 7), next_due_date=dt.date(2026, 11, 8)))
    assert (out["next_step_date"], out["promised_date"], out["last_quote_date"], out["next_due_date"]) == (
        "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08")


def test_contact_touch_timestamps_each_come_from_their_own_column():
    out = serialize.contact(contact_row(last_live_at=utc(2026, 10, 20, 16, 0), last_attempt_at=utc(2026, 10, 22, 16, 0),
                                        created_at=utc(2026, 1, 12, 15, 0)))
    assert out["last_live_at"] == "2026-10-20T11:00:00-05:00"
    assert out["last_attempt_at"] == "2026-10-22T11:00:00-05:00"
    assert out["created_at"] == "2026-01-12T09:00:00-06:00"


def test_contact_compact_last_live_is_the_live_touch_not_the_last_attempt():
    row = contact_row(last_live_at=utc(2026, 10, 20, 16, 0), last_attempt_at=utc(2026, 10, 22, 16, 0))
    assert serialize.contact_compact(row)["last_live_at"] == "2026-10-20T11:00:00-05:00"
    assert serialize.contact_compact(contact_row(last_live_at=None, last_attempt_at=utc(2026, 10, 22, 16, 0)))[
        "last_live_at"] is None


# ══ DATABASE: the SELECTs and the fetch helpers (on the fixture seed) ═════════════════════════════

class Spy(dict):
    """A row that remembers every column a serializer asks for, with [] or .get."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.read = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)


SELECT_CASES = {
    "user": ("select * from users order by id", serialize.user),
    "user_compact": ("select * from users order by id", serialize.user_compact),
    "company": (serialize.COMPANY_SELECT + " order by co.id", serialize.company),
    "contact": (serialize.CONTACT_SELECT + " order by cs.id", serialize.contact),
    "contact_compact": (serialize.CONTACT_SELECT + " order by cs.id", serialize.contact_compact),
    "contact_ref": (serialize.CONTACT_SELECT + " order by cs.id", serialize.contact_ref),
    "interaction": (serialize.INTERACTION_SELECT + " order by i.id", serialize.interaction),
    "task_batch": (serialize.BATCH_SELECT + " order by b.id", serialize.task_batch),
    "task": ("select * from tasks order by id", serialize.task),
    "recommendation": (serialize.RECOMMENDATION_SELECT + " order by r.id", serialize.recommendation),
    "followup_draft": ("select * from followup_drafts order by id", serialize.followup_draft),
    "candidate": (serialize.CANDIDATE_SELECT + " order by k.id", serialize.candidate),
    "import_record": (serialize.IMPORT_SELECT + " order by im.id", serialize.import_record),
    "unmatched_call": ("select * from unmatched_calls order by id", serialize.unmatched_call),
}


@pytest.mark.parametrize("name", sorted(SELECT_CASES))
def test_every_select_produces_every_column_its_serializer_reads(bd_seeded, bd_db, name):
    """The *_SELECT constants and the serializers are written apart: a column renamed in one and not
    the other would, for a .get column, silently turn into null. Read ALL the seeded rows so the
    conditional branches (owner, co-owner, duplicate, decided_by ...) are exercised too."""
    sql, func = SELECT_CASES[name]
    rows = bd_db.execute(sql).fetchall()
    assert rows, "the seed has no %s rows to check" % name
    read = set()
    for row in rows:
        spy = Spy(row)
        out = func(spy)
        json.dumps(out)                                # what the database gives is JSON-able, too
        read |= spy.read
    missing = read - set(rows[0])
    assert not missing, "%s reads columns its SELECT does not give: %s" % (name, sorted(missing))


def test_candidate_select_gives_the_possible_duplicate_columns(bd_seeded, bd_db):
    rows = bd_db.execute(serialize.CANDIDATE_SELECT + " where k.possible_duplicate_id is not null").fetchall()
    assert rows, "the seed has a candidate with a possible duplicate"
    for row in rows:
        out = serialize.candidate(row)
        assert out["possible_duplicate"]["contact_id"] == row["possible_duplicate_id"]
        assert out["possible_duplicate"]["name"] is not None
        assert out["possible_duplicate"]["company"] is not None


def test_fetch_contact_and_fetch_contacts_agree_and_missing_is_none(bd_seeded, bd_db):
    one = serialize.fetch_contact(bd_db, 33)
    check_shape(one, CONTACT_SPEC)
    assert one["id"] == 33 and one["duplicate_of"]["contact_id"] == 21      # the seed's flagged duplicate
    assert one["duplicate_of"]["reason"] == "Same email"
    assert serialize.fetch_contacts(bd_db, SQL("cs.id = %s"), (33,)) == [one]
    assert serialize.fetch_contact(bd_db, 999999) is None
    assert serialize.fetch_contacts(bd_db, SQL("cs.id = %s"), (999999,)) == []
    # a co-owner named in the workbook with no login yet comes out as {"id": None, "name": ...};
    # one with a login carries the login's id and name
    co_owners = [c["co_owner"] for c in serialize.fetch_contacts(bd_db, SQL("cs.co_owner_name is not null"))]
    assert {"id": None, "name": "Jules"} in co_owners
    assert {"id": 2, "name": "Blair Fenn"} in co_owners


def test_fetch_contacts_where_params_and_order(bd_seeded, bd_db):
    everyone = serialize.fetch_contacts(bd_db)                               # defaults: true, by id
    assert len(everyone) == len(fixture_seed.FIXTURE["contacts"])
    assert [c["id"] for c in everyone] == sorted(c["id"] for c in everyone)
    maintenance = serialize.fetch_contacts(bd_db, SQL("cs.category = %s"), ("maintenance",), "name_desc")
    assert len(maintenance) == 2 and all(c["category"] == "maintenance" for c in maintenance)
    assert [c["name"] for c in maintenance] == sorted((c["name"] for c in maintenance), reverse=True)
    some = serialize.fetch_contacts(bd_db, SQL("cs.id = any(%s)"), ([25, 23, 29],), "id_desc")
    assert [c["id"] for c in some] == [29, 25, 23]
    for c in everyone:
        assert "archived_at" not in c                                         # nobody is archived yet
    bd_db.execute("update contacts set archived_at = %s where id = 23", (utc(2026, 11, 3, 18, 0),))
    archived = serialize.fetch_contact(bd_db, 23)
    assert archived["archived_at"] == "2026-11-03T12:00:00-06:00"
    assert "archived_at" not in serialize.fetch_contact(bd_db, 25)
    assert set(archived) - {"archived_at"} == set(CONTACT_SPEC)


def test_fetch_contacts_and_fetch_tasks_take_no_sql_text_from_a_caller(bd_seeded, bd_db):
    """A sort key or a filter from a query string can never reach the SQL: the order is a key from
    a fixed list, and the filter must be psycopg's sql.Composable (written in code), not a str."""
    for fetch in (serialize.fetch_contacts, serialize.fetch_tasks):
        with pytest.raises(TypeError):
            fetch(bd_db, "true")
        with pytest.raises(ValueError):
            fetch(bd_db, order="id; drop table contacts")
        with pytest.raises(ValueError):
            fetch(bd_db, order="cs.id desc")                  # SQL text is not a key either
    assert set(serialize.CONTACT_ORDERS) >= {"id", "id_desc", "name", "name_desc"}
    assert set(serialize.TASK_ORDERS) >= {"id", "id_desc", "batch"}


def test_fetch_contacts_and_fetch_tasks_are_bounded(bd_seeded, bd_db):
    assert 100 <= serialize.DEFAULT_LIMIT <= serialize.MAX_LIMIT <= 1000
    assert [c["id"] for c in serialize.fetch_contacts(bd_db, limit=3)] == [
        c["id"] for c in serialize.fetch_contacts(bd_db)][:3]
    assert len(serialize.fetch_tasks(bd_db, limit=2)) == 2
    for bad in (0, -1, serialize.MAX_LIMIT + 1, "5"):
        with pytest.raises(ValueError):
            serialize.fetch_contacts(bd_db, limit=bad)
        with pytest.raises(ValueError):
            serialize.fetch_tasks(bd_db, limit=bad)


def test_fetch_tasks_attaches_each_tasks_own_compact_contact(bd_seeded, bd_db):
    tasks = serialize.fetch_tasks(bd_db)
    assert [t["id"] for t in tasks] == [301, 302, 303, 304, 305]               # default order: t.id
    expected_contacts = {301: 30, 302: 21, 303: 25, 304: 22, 305: 28}
    for t in tasks:
        check_shape(without(t, "contact"), {k: v for k, v in TASK_SPEC.items() if k != "contact"})
        assert set(t["contact"]) == set(CONTACT_COMPACT_SPEC)
        assert t["contact"]["id"] == expected_contacts[t["id"]]
        assert t["contact"] == serialize.contact_compact(
            bd_db.execute(serialize.CONTACT_SELECT + " where cs.id = %s", (expected_contacts[t["id"]],)).fetchone())
    assert [t["id"] for t in serialize.fetch_tasks(bd_db, SQL("t.id = any(%s)"), ([302, 304],), "id_desc")] == [304, 302]


def test_fetch_tasks_joins_the_batch_and_survives_an_archived_contact(bd_seeded, bd_db):
    assert len(serialize.fetch_tasks(bd_db, SQL("b.kind = %s"), ("friday",))) == 5
    assert len(serialize.fetch_tasks(bd_db, SQL("b.owner_id = %s"), (2,))) == 2
    assert serialize.fetch_tasks(bd_db, SQL("b.kind = %s"), ("ten_more",)) == []
    assert serialize.fetch_tasks(bd_db, SQL("t.id = %s"), (999999,)) == []
    bd_db.execute("update contacts set archived_at = %s where id = 21", (utc(2026, 11, 3, 18, 0),))
    task = serialize.fetch_tasks(bd_db, SQL("t.id = %s"), (302,))[0]
    assert task["contact"] is not None and task["contact"]["id"] == 21      # still shown, never a null card
    bd_db.execute("update tasks set status = 'done', done_at = %s where id = 304", (utc(2026, 11, 4, 16, 0),))
    done = serialize.fetch_tasks(bd_db, SQL("t.status = %s"), ("done",))
    assert [(t["id"], t["done_at"]) for t in done if t["id"] == 304] == [(304, "2026-11-04T10:00:00-06:00")]


def test_fetch_interaction_and_fetch_company(bd_seeded, bd_db):
    first = bd_db.execute("select id from interactions order by id limit 1").fetchone()["id"]
    out = serialize.fetch_interaction(bd_db, first)
    check_shape(out, INTERACTION_SPEC)
    assert out["id"] == first and out["contact"]["id"] == out["contact_id"]
    assert serialize.fetch_interaction(bd_db, 999999) is None
    company = serialize.fetch_company(bd_db, fixture_seed.MULTI_OWNER_ACCOUNT)
    check_shape(company, COMPANY_SPEC)
    assert company["id"] == fixture_seed.MULTI_OWNER_ACCOUNT and company["contact_count"] == 3
    assert serialize.fetch_company(bd_db, 999999) is None


OPTIONAL_FK_CASES = {
    # name: (table, column nulled, SELECT, alias of the base table in the SELECT, serializer, key that goes None)
    "interaction": ("interactions", "user_id", serialize.INTERACTION_SELECT, "i", serialize.interaction, "user"),
    "recommendation": ("ai_recommendations", "decided_by", serialize.RECOMMENDATION_SELECT, "r",
                       serialize.recommendation, "decided_by"),
    "candidate": ("candidates", "possible_duplicate_id", serialize.CANDIDATE_SELECT, "k", serialize.candidate,
                  "possible_duplicate"),
    "import_record": ("imports", "by_id", serialize.IMPORT_SELECT, "im", serialize.import_record, "by"),
}


@pytest.mark.parametrize("name", sorted(OPTIONAL_FK_CASES))
def test_select_keeps_rows_whose_optional_user_or_contact_is_null(bd_seeded, bd_db, name):
    """A phone call nobody logged, a pending recommendation, a candidate with no duplicate, an
    import with no signed-in user: each must still come out (a LEFT join), with the field None."""
    table, column, select, alias, func, key = OPTIONAL_FK_CASES[name]
    total = bd_db.execute("select count(*) as n from " + table).fetchone()["n"]
    assert total > 0
    bd_db.execute("update " + table + " set " + column + " = null")
    rows = bd_db.execute(select + " order by " + alias + ".id").fetchall()
    assert len(rows) == total, "%s dropped rows whose %s is null" % (name, column)
    for row in rows:
        assert func(row)[key] is None
